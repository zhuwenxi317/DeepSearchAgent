from dotenv import load_dotenv,find_dotenv
import os
from langchain.chat_models import init_chat_model

# 加载配置文件
# find_dotenv() 确保找到 .env文件 递归查询当前项目文件夹
load_dotenv(find_dotenv())

_model_name = os.getenv("LLM_QWEN_MAX")
_api_key = os.getenv("OPENAI_API_KEY")

# 与其让 init_chat_model 抛一个难懂的 ValidationError，
# 不如在这里把"缺哪个配置"直接说清楚。
if not _model_name:
    raise RuntimeError(
        "缺少 LLM_QWEN_MAX：请在 .env 中配置模型名称（例如 deepseek-chat）"
    )
if not _api_key:
    raise RuntimeError(
        "缺少 OPENAI_API_KEY：请在 .env 中配置 LLM 的 API Key"
    )

model = init_chat_model(
    model=_model_name,
    model_provider="openai"
)

