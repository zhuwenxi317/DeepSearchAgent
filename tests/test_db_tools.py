"""数据库工具的确定性逻辑：SQL 白名单、CSV 格式、结果上限、错误翻译。

不连接真实 MySQL：用假连接替掉 `_connect`，所有测试都不依赖环境。
"""
import csv
import io

import pytest
from mysql.connector import OperationalError

import tools.db_tools as db_tools


class FakeCursor:
    def __init__(self, tables=None, rows=None):
        self.tables = tables or []
        self.rows = rows or []
        self.description = None
        self.with_rows = False
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.executed.append(sql)
        text = sql.strip().upper()
        if text.startswith("SHOW TABLES"):
            self.description = [("Tables_in_demo",)]
            self.with_rows = True
        elif text.startswith("SET SESSION"):
            self.description = None
            self.with_rows = False
        else:
            self.description = [("product_id",), ("product_name",)]
            self.with_rows = True

    def fetchall(self):
        if self.executed and self.executed[-1].strip().upper().startswith("SHOW TABLES"):
            return [(name,) for name in self.tables]
        return self.rows

    def fetchmany(self, size):
        return self.rows[:size]


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


@pytest.fixture
def fake_db(monkeypatch):
    def install(tables=None, rows=None):
        cursor = FakeCursor(tables=tables, rows=rows)
        connection = FakeConnection(cursor)
        monkeypatch.setattr(db_tools, "_db_config", lambda: {"database": "demo"})
        monkeypatch.setattr(db_tools, "_connect", lambda config: connection)
        return cursor, connection

    return install


def test_read_only_accepts_common_queries():
    for sql in [
        "SELECT * FROM products",
        "select count(*) from inventory;",
        "SHOW TABLES",
        "DESCRIBE products",
        "EXPLAIN SELECT * FROM products",
        "WITH t AS (SELECT 1) SELECT * FROM t",
    ]:
        allowed, reason = db_tools.check_read_only_sql(sql)
        assert allowed, f"{sql} 应被允许，却被拒绝：{reason}"


def test_read_only_rejects_writes():
    for sql in [
        "DROP TABLE products",
        "DELETE FROM products",
        "UPDATE products SET price = 0",
        "INSERT INTO products VALUES (1)",
        "ALTER TABLE products ADD COLUMN x INT",
        "TRUNCATE TABLE products",
    ]:
        allowed, _ = db_tools.check_read_only_sql(sql)
        assert not allowed, f"{sql} 应被拒绝"


def test_read_only_rejects_multiple_statements():
    allowed, reason = db_tools.check_read_only_sql(
        "SELECT * FROM products; DROP TABLE products"
    )
    assert not allowed
    assert "单条" in reason


def test_read_only_rejects_with_delete():
    allowed, _ = db_tools.check_read_only_sql(
        "WITH t AS (SELECT 1) DELETE FROM products"
    )
    assert not allowed


def test_rows_to_csv_handles_commas_newlines_and_none():
    cursor = FakeCursor()
    cursor.description = [("name",), ("note",)]
    text = db_tools.rows_to_csv(
        cursor,
        [("A,B", "line1\nline2"), (None, "普通")],
    )
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["name", "note"]
    assert rows[1] == ["A,B", "line1\nline2"]
    assert rows[2] == ["", "普通"]


def test_list_sql_tables(fake_db):
    fake_db(tables=["inventory", "products", "sales_records", "warehouses"])
    result = db_tools.list_sql_tables.invoke({})
    assert "products" in result and "sales_records" in result


def test_get_table_data_rejects_unknown_table(fake_db):
    cursor, _ = fake_db(tables=["products"])
    result = db_tools.get_table_data.invoke({"table_name": "products; DROP TABLE x"})
    assert "不存在" in result
    assert all("SELECT * FROM" not in sql for sql in cursor.executed)


def test_get_table_data_returns_csv(fake_db):
    fake_db(tables=["products"], rows=[(1, "华为电脑"), (2, "显示器")])
    result = db_tools.get_table_data.invoke({"table_name": "PRODUCTS"})
    rows = list(csv.reader(io.StringIO(result)))
    assert rows[0] == ["product_id", "product_name"]
    assert rows[1] == ["1", "华为电脑"]
    assert rows[2] == ["2", "显示器"]


def test_execute_sql_rejects_write(fake_db):
    fake_db()
    result = db_tools.execute_sql_query.invoke({"query": "DELETE FROM products"})
    assert "查询被拒绝" in result


def test_execute_sql_returns_csv_and_limits_rows(fake_db):
    fake_db(rows=[(index, f"产品{index}") for index in range(250)])
    result = db_tools.execute_sql_query.invoke({"query": "SELECT * FROM products"})
    rows = list(csv.reader(io.StringIO(result.split("\n[注意")[0])))
    assert len(rows) == db_tools.MAX_ROWS + 1     # 表头 + 200 行
    assert "仅返回前 200 行" in result


def test_connection_error_is_readable(monkeypatch):
    monkeypatch.setattr(db_tools, "_db_config", lambda: {"database": "demo"})

    def fail(config):
        raise OperationalError("Can't connect to MySQL server")

    monkeypatch.setattr(db_tools, "_connect", fail)
    result = db_tools.list_sql_tables.invoke({})
    assert "数据库当前不可用" in result
