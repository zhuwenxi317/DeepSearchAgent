import os

from agent.prompts import sub_agents_content

_database_config = sub_agents_content["database"]


def build_database_agent():
    """按配置决定是否注册数据库查询助手。

    缺少 MySQL 连接信息时返回 None，由主智能体跳过注册；
    同时避免 import db_tools（它本身不会连接，但没必要加载）。
    """
    required = ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")
    if not all(os.getenv(key) for key in required):
        return None

    from tools.db_tools import execute_sql_query, get_table_data, list_sql_tables

    return {
        "name": _database_config["name"],
        "description": _database_config["description"],
        "system_prompt": _database_config["system_prompt"],
        "tools": [list_sql_tables, get_table_data, execute_sql_query],
    }
