"""数据库查询工具：让模型能探索表结构并执行只读 SQL。

三个工具配合使用：
    list_sql_tables()        → 有哪些表
    get_table_data(table)    → 预览列名和数据格式
    execute_sql_query(sql)   → 执行自定义只读查询

安全策略（三层）：
    1. 数据库账号本身只有 SELECT 权限（最硬的防线）
    2. SQL 白名单：只允许 SELECT/SHOW/DESCRIBE/EXPLAIN/WITH 开头
    3. 结果上限：最多 200 行、20000 字符，防止撑爆上下文
"""
import csv
import io
import os
import re

import mysql.connector
from mysql.connector import Error, OperationalError, ProgrammingError
from langchain_core.tools import tool

from api.monitor import monitor

MAX_ROWS = 200
MAX_PREVIEW_ROWS = 100
MAX_RESULT_CHARS = 20000
QUERY_TIMEOUT_MS = 5000

_ALLOWED_KEYWORDS = {"select", "show", "describe", "desc", "explain", "with"}


def _db_config() -> dict | None:
    """从环境变量读取连接配置；核心项缺失时返回 None（由调用方降级）。"""
    user = os.getenv("MYSQL_USER")
    password = os.getenv("MYSQL_PASSWORD")
    database = os.getenv("MYSQL_DATABASE")
    if not all((user, password, database)):
        return None
    return {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": user,
        "password": password,
        "database": database,
        "charset": "utf8mb4",
        "connection_timeout": 5,
        "read_timeout": 10,
        "autocommit": True,
    }


def _connect(config: dict):
    return mysql.connector.connect(**config)


def _format_error(error: Exception) -> str:
    """把数据库异常翻译成模型能决策的提示。"""
    if isinstance(error, OperationalError):
        return (
            f"数据库当前不可用：{error}。"
            "请不要反复重试，基于已有信息回答，并告知用户数据库暂时不可用。"
        )
    if isinstance(error, ProgrammingError):
        return f"SQL 执行失败：{error}。请检查表名/列名后修正 SQL。"
    return f"数据库操作失败：{type(error).__name__}: {error}"


def _quote_identifier(name: str) -> str:
    """给表名加反引号，并转义内部反引号。"""
    return "`" + str(name).replace("`", "``") + "`"


def check_read_only_sql(sql: str) -> tuple[bool, str]:
    """检查 SQL 是否只读、单条。返回 (是否允许, 拒绝原因)。"""
    text = (sql or "").strip()
    if not text:
        return False, "SQL 不能为空"

    body = text.rstrip(";").strip()
    if ";" in body:
        return False, "只允许执行单条语句（检测到分号后的额外内容）"

    first = body.split(None, 1)[0].lower()
    if first not in _ALLOWED_KEYWORDS:
        allowed = ", ".join(sorted(_ALLOWED_KEYWORDS))
        return False, f"只允许只读查询（{allowed}），收到 {first.upper()}"

    lowered = f" {body.lower()} "
    if first == "with" and re.search(
        r"\b(delete|update|insert|replace|merge)\b", body, re.IGNORECASE
    ):
        return False, "WITH 后面只允许跟 SELECT"

    if any(token in lowered for token in (" into outfile", " into dumpfile", " load_file(")):
        return False, "查询包含不允许的写文件操作"
    if any(token in lowered for token in (" for update", " lock in share mode")):
        return False, "查询包含锁行操作"

    return True, ""


def rows_to_csv(cursor, rows) -> str:
    """把结果集转成 CSV 文本；逗号/换行/中文由 csv 模块自动处理。"""
    columns = [description[0] for description in (cursor.description or [])]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if columns:
        writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    return buffer.getvalue()


def truncate_result(text: str, row_count: int, row_limited: bool) -> str:
    notes = []
    if row_limited:
        notes.append(f"仅返回前 {MAX_ROWS} 行")
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS]
        notes.append(f"结果超过 {MAX_RESULT_CHARS} 字符，已截断")
    if notes:
        text += "\n[注意：" + "；".join(notes) + "]"
    return text


def _fetch_capped(cursor):
    """最多取 MAX_ROWS+1 行，用来判断是否还有更多。"""
    rows = cursor.fetchmany(MAX_ROWS + 1)
    limited = len(rows) > MAX_ROWS
    return rows[:MAX_ROWS], limited


@monitor.traced_tool("数据库表名查询")
@tool
def list_sql_tables() -> str:
    """列出当前数据库里所有可用的表。

    在写 SQL 之前，先调用这个工具确认表名，避免猜错表名。
    """
    config = _db_config()
    if config is None:
        return "数据库未配置（缺少 MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE）。"

    try:
        connection = _connect(config)
    except Error as error:
        return _format_error(error)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
        if not tables:
            return f"数据库 {config['database']} 中没有表。"
        return "可用的表：" + ", ".join(tables)
    except Error as error:
        return _format_error(error)
    finally:
        connection.close()


@monitor.traced_tool("数据库表数据查询")
@tool
def get_table_data(table_name: str) -> str:
    """预览指定表的结构和数据（最多 100 行，CSV 格式）。

    调用前必须先调用 list_sql_tables 确认表名。
    """
    config = _db_config()
    if config is None:
        return "数据库未配置（缺少 MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE）。"

    wanted = (table_name or "").strip()
    if not wanted:
        return "表名不能为空，请先调用 list_sql_tables 查看可用的表。"

    try:
        connection = _connect(config)
    except Error as error:
        return _format_error(error)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]

            # 用显示名匹配真实表名：既挡住注入，也兼容大小写差异
            canonical = next(
                (name for name in tables if name.lower() == wanted.lower()), None
            )
            if canonical is None:
                return (
                    f"表 {wanted} 不存在。可用的表：{', '.join(tables)}。"
                    "请先调用 list_sql_tables 确认。"
                )

            cursor.execute(
                f"SELECT * FROM {_quote_identifier(canonical)} LIMIT {MAX_PREVIEW_ROWS}"
            )
            rows = cursor.fetchall()
            if not rows:
                return f"表 {canonical} 为空。"
            text = rows_to_csv(cursor, rows)
            return truncate_result(text, len(rows), False)
    except Error as error:
        return _format_error(error)
    finally:
        connection.close()


@monitor.traced_tool("数据库SQL查询")
@tool
def execute_sql_query(query: str) -> str:
    """执行一条只读 SQL（SELECT/SHOW/DESCRIBE/EXPLAIN），返回 CSV。

    使用前建议先用 list_sql_tables 和 get_table_data 了解表结构。
    只允许单条只读语句；最多返回 200 行。
    """
    allowed, reason = check_read_only_sql(query)
    if not allowed:
        return f"查询被拒绝：{reason}"

    config = _db_config()
    if config is None:
        return "数据库未配置（缺少 MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE）。"

    try:
        connection = _connect(config)
    except Error as error:
        return _format_error(error)

    try:
        with connection.cursor() as cursor:
            # 给查询加服务端超时（MySQL 5.7.8+）。失败也不影响主流程。
            try:
                cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {QUERY_TIMEOUT_MS}")
            except Error:
                pass

            cursor.execute(query)
            if not cursor.with_rows:
                return "查询已执行，但没有返回结果集。"

            rows, limited = _fetch_capped(cursor)
            if not rows:
                return "查询成功，但没有匹配的数据。"
            text = rows_to_csv(cursor, rows)
            return truncate_result(text, len(rows), limited)
    except Error as error:
        return _format_error(error)
    finally:
        connection.close()
