from pathlib import Path

# 模型可能误传的虚拟路径前缀（跨环境常见的根目录名）
_VIRTUAL_PREFIXES = {"workspace", "mnt", "data", "home", "user", "root", "app", "tmp"}


def resolve_path(session_dir: str, path: str = "", filename: str = "") -> Path:
    """把模型给的任意路径收敛到 session_dir 内，返回安全的绝对路径。

    模型会传各种奇怪路径，这里统一清洗：
    - 虚拟前缀（/workspace、/mnt/data ...）→ 丢弃
    - 绝对路径开头的 /（变成相对）
    - 路径穿越 .. → 丢弃
    - 空段、. → 丢弃
    最后兜底：结果必须仍在 session_dir 内，否则降级为只保留文件名。
    """
    raw_parts = []
    for seg in (path, filename):
        if seg:
            raw_parts.extend(str(seg).replace("\\", "/").split("/"))

    cleaned = []
    for part in raw_parts:
        part = part.strip()
        if part in ("", ".", ".."):
            continue
        if part.lower() in _VIRTUAL_PREFIXES:
            continue
        cleaned.append(part)

    session = Path(session_dir).resolve()
    target = session.joinpath(*cleaned).resolve()

    # 安全兜底：结果必须在 session_dir 内，否则降级为只保留文件名
    if target != session and session not in target.parents:
        target = session / target.name

    return target
