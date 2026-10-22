"""启动配置检查：必需项失败、可选项降级。"""
import pytest

from agent.subagents.network_search_agent import build_network_search_agent
from api.config import check_startup_config, has_database, has_tavily


def test_missing_llm_model_fails_fast(monkeypatch):
    monkeypatch.delenv("LLM_QWEN_MAX", raising=False)
    with pytest.raises(RuntimeError) as error:
        check_startup_config()
    assert "LLM_QWEN_MAX" in str(error.value)


def test_missing_llm_api_key_fails_fast(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as error:
        check_startup_config()
    assert "OPENAI_API_KEY" in str(error.value)


def test_missing_tavily_degrades_instead_of_crashing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    warnings = check_startup_config()          # 不应抛异常
    assert any("TAVILY_API_KEY" in item for item in warnings)
    assert has_tavily() is False
    assert build_network_search_agent() is None


def test_fully_configured_registers_search_agent(monkeypatch):
    monkeypatch.setenv("LLM_QWEN_MAX", "deepseek-chat")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily")

    warnings = check_startup_config()
    assert not any("TAVILY_API_KEY" in item for item in warnings)
    assert has_tavily() is True
    assert build_network_search_agent() is not None


def test_missing_mysql_degrades(monkeypatch):
    monkeypatch.delenv("MYSQL_USER", raising=False)
    warnings = check_startup_config()
    assert any("MySQL" in item for item in warnings)
    assert has_database() is False


def test_database_configured(monkeypatch):
    monkeypatch.setenv("MYSQL_USER", "u")
    monkeypatch.setenv("MYSQL_PASSWORD", "p")
    monkeypatch.setenv("MYSQL_DATABASE", "d")
    warnings = check_startup_config()
    assert not any("MySQL" in item for item in warnings)
    assert has_database() is True
