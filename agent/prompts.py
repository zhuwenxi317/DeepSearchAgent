"""加载 prompt/prompts.yml，把提示词从配置文件读进代码。

代码只负责"取哪个 key"，不负责"内容是什么"——内容全在 YAML 里。
"""
from pathlib import Path

import yaml

project_root_path = Path(__file__).parents[1]
yaml_file_path = project_root_path / "prompt" / "prompts.yml"

# safe_load 而非 load：YAML 支持构造 Python 对象，load 可被用于执行任意代码
with open(yaml_file_path, "r", encoding="utf-8") as f:
    prompt_yaml_content = yaml.safe_load(f)

main_agent_content: dict = prompt_yaml_content["main_agent"]
sub_agents_content: dict = prompt_yaml_content["sub_agents"]
