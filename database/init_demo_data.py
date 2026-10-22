"""初始化演示数据库（本地 MySQL，不依赖 Docker）。

做什么：
    1. 按 .env 的 MYSQL_DATABASE 创建库（utf8mb4）
    2. 执行 database/init_demo_data.sql（会重建 4 张演示表）
    3. 打印每张表的行数和一条样例数据

运行（PowerShell）：
    $env:PYTHONIOENCODING="utf-8"
    ./.venv/Scripts/python.exe database/init_demo_data.py

注意：SQL 开头有 DROP TABLE IF EXISTS，重复执行会覆盖这 4 张演示表。
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

import mysql.connector
from mysql.connector import Error

SQL_FILE = Path(__file__).with_name("init_demo_data.sql")
TABLES = ("warehouses", "products", "inventory", "sales_records")


def iter_statements(sql_text: str):
    """按分号拆分语句，并丢掉以 -- 开头的注释行。

    这份种子 SQL 没有存储过程、没有字符串内分号，所以简单拆分是安全的。
    """
    lines = [
        line for line in sql_text.splitlines()
        if not line.strip().startswith("--")
    ]
    for statement in "\n".join(lines).split(";"):
        statement = statement.strip()
        if statement:
            yield statement


def main():
    database = os.getenv("MYSQL_DATABASE", "deep_search_demo")
    config = {
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", "3306")),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "charset": "utf8mb4",
        "connection_timeout": 5,
        "autocommit": True,
    }

    print(f"目标库：{database}（{config['host']}:{config['port']}，用户 {config['user']}）")
    print("注意：会重建 warehouses / products / inventory / sales_records 四张演示表。\n")

    try:
        connection = mysql.connector.connect(**config)
    except Error as error:
        print(f"❌ 连接失败：{error}")
        return 1

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            cursor.execute(f"USE `{database}`")
            print(f"✅ 数据库 `{database}` 已就绪")

            sql_text = SQL_FILE.read_text(encoding="utf-8")
            executed = 0
            for statement in iter_statements(sql_text):
                try:
                    cursor.execute(statement)
                except Error as error:
                    print(f"\n❌ 第 {executed + 1} 条语句失败：{error}")
                    print(f"   语句开头：{statement[:160].replace(chr(10), ' ')}…")
                    return 1
                if cursor.with_rows:
                    cursor.fetchall()   # 种子文件末尾有几条演示 SELECT，必须读掉
                executed += 1

            print(f"✅ 已执行 {executed} 条语句")

            print("\n数据量：")
            for table in TABLES:
                cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
                print(f"  {table:<14} {cursor.fetchone()[0]:>4} 行")

            cursor.execute(
                "SELECT product_id, product_name, brand, unit_price "
                "FROM products ORDER BY product_id"
            )
            print("\n产品样例：")
            for product_id, name, brand, price in cursor.fetchall():
                print(f"  {product_id}. {brand} {name} — ¥{price}")
    finally:
        connection.close()

    print("\n✅ 初始化完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
