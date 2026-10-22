"""脱敏器的确定性规则：打码、截断、深度剪枝、循环引用、不修改入参。"""
from api.trace_serializer import (
    MAX_DEPTH,
    MAX_STR_LEN,
    REDACTED,
    sanitize_for_trace,
)


def test_sensitive_keys_are_redacted():
    result = sanitize_for_trace({
        "api_key": "sk-123",
        "API-KEY": "also-secret",
        "access_token": "tok",
        "password": "p",
        "authorization": "Bearer x",
        "query": "正常内容",
    })
    assert result["api_key"] == REDACTED
    assert result["API-KEY"] == REDACTED
    assert result["access_token"] == REDACTED
    assert result["password"] == REDACTED
    assert result["authorization"] == REDACTED
    assert result["query"] == "正常内容"


def test_nested_sensitive_keys_are_redacted():
    result = sanitize_for_trace({"outer": {"credentials": "abc", "ok": 1}})
    assert result["outer"]["credentials"] == REDACTED
    assert result["outer"]["ok"] == 1


def test_long_string_is_truncated():
    result = sanitize_for_trace("x" * (MAX_STR_LEN + 100))
    assert result.endswith("…[截断]")
    assert len(result) < MAX_STR_LEN + 100


def test_short_string_untouched():
    assert sanitize_for_trace("hello") == "hello"


def test_deep_structure_is_pruned():
    value = "leaf"
    for _ in range(MAX_DEPTH + 2):
        value = {"next": value}
    result = sanitize_for_trace(value)
    assert "[结构过深，已剪枝]" in str(result)


def test_cycle_does_not_recurse_forever():
    cycle = {}
    cycle["self"] = cycle
    result = sanitize_for_trace(cycle)   # 不抛 RecursionError 即通过
    assert "[结构过深，已剪枝]" in str(result)


def test_input_is_not_mutated():
    original = {"api_key": "sk-123", "nested": {"token": "t"}}
    result = sanitize_for_trace(original)
    assert original == {"api_key": "sk-123", "nested": {"token": "t"}}
    assert result["api_key"] == REDACTED


def test_lists_and_tuples_become_lists():
    result = sanitize_for_trace(("a", {"token": "t"}, 3))
    assert result == ["a", {"token": REDACTED}, 3]
