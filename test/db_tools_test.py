"""数据库工具端到端验证（连接真实 MySQL，只读账号）。

运行（PowerShell）：
    $env:PYTHONIOENCODING="utf-8"
    ./.venv/Scripts/python.exe test/db_tools_test.py

验证点：
    ① 能列出表
    ② 能预览表数据（CSV）
    ③ 能执行只读 JOIN/聚合查询
    ④ 写操作在工具层就被拒绝
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from tools.db_tools import execute_sql_query, get_table_data, list_sql_tables


def main():
    print("① 列出表：")
    tables = list_sql_tables.invoke({})
    print(f"   {tables}")
    for name in ("products", "inventory", "sales_records", "warehouses"):
        assert name in tables, f"缺少表 {name}"

    print("\n② 预览 products：")
    preview = get_table_data.invoke({"table_name": "products"})
    print("\n".join(f"   {line}" for line in preview.splitlines()[:6]))
    assert "product_id" in preview and "华为" in preview

    print("\n③ 执行聚合查询：")
    result = execute_sql_query.invoke({
        "query": (
            "SELECT p.product_name, SUM(i.stock_quantity) AS total_stock "
            "FROM inventory i JOIN products p ON p.product_id = i.product_id "
            "GROUP BY p.product_id, p.product_name ORDER BY total_stock DESC"
        )
    })
    print("\n".join(f"   {line}" for line in result.splitlines()))
    assert "total_stock" in result

    print("\n④ 写操作应被拒绝：")
    denied = execute_sql_query.invoke({"query": "DELETE FROM products"})
    print(f"   {denied}")
    assert "查询被拒绝" in denied

    print("\n✅ 数据库工具通过：表名、预览、聚合查询、只读保护")


if __name__ == "__main__":
    main()
