"""创建只读账号并切换 .env（一次性运维脚本）。

做四件事：
    1. 用当前 .env 里的管理员账号（root）创建 'deepsearch'@'localhost'
    2. 只授予 deep_search_demo 的 SELECT 权限
    3. 用新账号验证：能查、不能删
    4. 把 .env 的 MYSQL_USER / MYSQL_PASSWORD 改成新账号

运行（PowerShell，需要管理员 root 凭据已在 .env 中）：
    $env:PYTHONIOENCODING="utf-8"
    ./.venv/Scripts/python.exe database/create_readonly_user.py
"""
import os
import re
import secrets
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

import mysql.connector
from mysql.connector import Error

ENV_PATH = PROJECT_ROOT / ".env"
APP_USER = "deepsearch"
APP_HOST = "localhost"


def update_env(path: Path, updates: dict[str, str]) -> None:
    """就地替换 .env 中的键，保留其它行和注释。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")
    seen = set()
    output = []
    for line in lines:
        match = pattern.match(line)
        if match and match.group(1) in updates:
            key = match.group(1)
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")


def main():
    database = os.getenv("MYSQL_DATABASE", "deep_search_demo")
    admin = {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "charset": "utf8mb4",
        "connection_timeout": 5,
        "autocommit": True,
    }

    # token_urlsafe 只产生字母、数字、- 和 _，可以安全嵌入 DDL
    password = secrets.token_urlsafe(24)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", password)

    print(f"使用管理员账号 {admin['user']} 创建只读账号 '{APP_USER}'@'{APP_HOST}'…")
    try:
        connection = mysql.connector.connect(**admin)
    except Error as error:
        print(f"❌ 连接失败：{error}")
        return 1

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE USER IF NOT EXISTS '{APP_USER}'@'{APP_HOST}' "
                f"IDENTIFIED BY '{password}'"
            )
            cursor.execute(
                f"ALTER USER '{APP_USER}'@'{APP_HOST}' IDENTIFIED BY '{password}'"
            )
            try:
                cursor.execute(
                    f"REVOKE ALL PRIVILEGES, GRANT OPTION FROM "
                    f"'{APP_USER}'@'{APP_HOST}'"
                )
            except Error:
                pass   # 新账号本来就没有权限，忽略
            cursor.execute(
                f"GRANT SELECT ON `{database}`.* TO '{APP_USER}'@'{APP_HOST}'"
            )
        print("✅ 账号已创建/更新，仅授予 SELECT")
    finally:
        connection.close()

    # 用新账号验证：能查、不能删
    readonly = {
        "host": admin["host"],
        "port": admin["port"],
        "user": APP_USER,
        "password": password,
        "charset": "utf8mb4",
        "connection_timeout": 5,
        "autocommit": True,
    }
    try:
        check = mysql.connector.connect(**readonly)
    except Error as error:
        print(f"❌ 新账号连接失败：{error}")
        return 1

    try:
        with check.cursor() as cursor:
            cursor.execute(f"USE `{database}`")
            cursor.execute("SELECT COUNT(*) FROM products")
            print(f"✅ 新账号可查询：products 表 {cursor.fetchone()[0]} 行")
            try:
                cursor.execute("DELETE FROM warehouses WHERE 1 = 0")
            except Error as error:
                print(f"✅ 新账号被拒绝执行 DELETE：{error.msg}")
            else:
                print("⚠️ 警告：只读账号竟然可以执行 DELETE，请检查授权！")
                return 1
    finally:
        check.close()

    update_env(ENV_PATH, {
        "MYSQL_USER": APP_USER,
        "MYSQL_PASSWORD": password,
    })
    print("✅ 已更新 .env：MYSQL_USER / MYSQL_PASSWORD 已切换为只读账号")
    print("   密码已写入 .env，可用编辑器查看；重启服务后生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
