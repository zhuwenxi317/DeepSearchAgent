"""MySQL 连接检查（不建库、不改数据）。

运行（PowerShell）：
    $env:PYTHONIOENCODING="utf-8"
    ./.venv/Scripts/python.exe test/db_connection_test.py

输出说明：
    连接成功 → 会列出服务器版本、当前账号、已有数据库
    失败     → 按错误类型给出排查提示
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

import mysql.connector
from mysql.connector import Error


def main():
    config = {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "charset": "utf8mb4",
        "connection_timeout": 5,
    }
    database = os.getenv("MYSQL_DATABASE")

    print("配置（密码不显示）：")
    for key in ("host", "port", "user"):
        print(f"  {key} = {config[key]}")
    print(f"  database = {database}")
    print()

    try:
        connection = mysql.connector.connect(**config)
    except Error as error:
        message = str(error)
        print(f"❌ 连接失败：{message}\n")
        if "Access denied" in message:
            print("提示：用户名或密码不正确。请检查 .env 里的 MYSQL_USER / MYSQL_PASSWORD。")
        elif "Can't connect" in message or "Connection refused" in message:
            print("提示：MySQL 服务没启动，或 MYSQL_HOST / MYSQL_PORT 不对。")
        elif "Unknown database" in message:
            print("提示：MYSQL_DATABASE 指定的库还不存在——这是正常的，下一步会创建。")
        return 1

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION(), CURRENT_USER()")
            version, account = cursor.fetchone()
            print(f"✅ 连接成功：MySQL {version}")
            print(f"   当前账号：{account}")

            try:
                cursor.execute("SHOW DATABASES")
                databases = [row[0] for row in cursor.fetchall()]
                print(f"   已有数据库：{', '.join(databases)}")
            except Error as error:
                print(f"   （无权限列出所有数据库：{error}）")

            cursor.execute(
                "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s",
                (database,),
            )
            exists = cursor.fetchone() is not None
            if exists:
                print(f"\n   目标库 `{database}` 已存在")
                cursor.execute(f"SHOW TABLES FROM `{database}`")
                tables = [row[0] for row in cursor.fetchall()]
                print(f"   其中的表：{', '.join(tables) if tables else '（空库）'}")
            else:
                print(f"\n   目标库 `{database}` 不存在（下一步会创建）")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
