"""M8 Step 5：脱敏 —— sanitize_for_trace() 递归清洗。

在数据【存进 trace 之前】调用（方案 A：原始数据根本不进 trace）。
清洗规则：
    1. 敏感 key 打码：值替换成 ***REDACTED***
    2. 超长字符串截断：防止塞爆内存/日志
    3. 超深结构剪枝：顺便防循环引用导致的无限递归
"""
from typing import Any

# 敏感字段的判定词（小写匹配，宁可多打码不漏打）
SENSITIVE_KEY_PATTERNS = (
    "api_key",
    "apikey",
    "token",
    "password",
    "passwd",
    "secret",
    "authorization",
    "credential",
)

MAX_STR_LEN = 500      # 字符串超过这个长度就截断
MAX_DEPTH = 5          # 递归深度超过就剪枝（顺带防循环引用无限递归）

REDACTED = "***REDACTED***"


def sanitize_for_trace(obj: Any, depth: int = 0) -> Any:
    """递归清洗任意结构（dict / list / 基本类型），返回安全副本。

    注意是【返回新对象】，不修改入参——调用方手里的原始对象保持不变。
    """
    # 超深剪枝：depth 限制本身就能终止循环引用导致的无限递归
    if depth > MAX_DEPTH:
        return "[结构过深，已剪枝]"

    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            key_lower = str(key).lower().replace("-", "_")
            if any(pattern in key_lower for pattern in SENSITIVE_KEY_PATTERNS):
                result[key] = REDACTED          # 敏感字段：整段打码，不递归
            else:
                result[key] = sanitize_for_trace(value, depth + 1)
        return result

    if isinstance(obj, (list, tuple)):
        return [sanitize_for_trace(item, depth + 1) for item in obj]

    if isinstance(obj, str):
        if len(obj) > MAX_STR_LEN:
            return obj[:MAX_STR_LEN] + "…[截断]"
        return obj

    # int / float / bool / None 等基本类型：原样返回
    return obj
