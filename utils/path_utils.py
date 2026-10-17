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


def resolve_in_session(
    session_dir: str, value: str, suffix: str | None = None
) -> Path | None:
    """把模型给的单个路径字符串收敛到会话目录内，可选强制扩展名。

    先按 / 切成"子目录 + 文件名"，再交给 resolve_path 做穿越清洗；
    路径为空时返回 None（由调用方决定怎么报错）。
    """
    value = (value or "").strip().replace("\\", "/")
    if not value:
        return None

    segments = [seg for seg in value.split("/") if seg]
    name = segments[-1]
    subdir = "/".join(segments[:-1])

    target = resolve_path(session_dir, subdir, name)
    if suffix and target.suffix.lower() != suffix:
        target = target.with_suffix(suffix)
    return target
