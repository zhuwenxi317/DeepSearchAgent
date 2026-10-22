"""路径收敛：所有模型输入都必须落在会话目录内。"""
from pathlib import Path

from utils.path_utils import resolve_in_session, resolve_path


def assert_inside(target: Path, session: Path):
    assert target == session or session in target.parents


def test_normal_relative_path(tmp_path):
    result = resolve_path(str(tmp_path), "报告", "a.md")
    assert result == (tmp_path / "报告" / "a.md").resolve()


def test_parent_traversal_is_stripped(tmp_path):
    result = resolve_path(str(tmp_path), "../../etc", "passwd")
    assert result == (tmp_path / "etc" / "passwd").resolve()
    assert_inside(result, tmp_path.resolve())


def test_absolute_path_is_confined(tmp_path):
    result = resolve_path(str(tmp_path), "/etc", "passwd")
    assert_inside(result, tmp_path.resolve())


def test_virtual_prefix_is_stripped(tmp_path):
    result = resolve_path(str(tmp_path), "/workspace/mnt/data", "a.md")
    assert result == (tmp_path / "a.md").resolve()


def test_empty_segments_ignored(tmp_path):
    result = resolve_path(str(tmp_path), "//a/./b//", "c.md")
    assert result == (tmp_path / "a" / "b" / "c.md").resolve()


def test_result_never_escapes(tmp_path):
    # 各种恶意输入都试一遍：结果必须始终在会话目录内
    session = tmp_path.resolve()
    for path, filename in [
        ("..", "x"),
        ("../..", "x"),
        ("C:/Windows", "x"),
        ("/../../windows", "system.ini"),
        ("a/../../../b", "c"),
    ]:
        assert_inside(resolve_path(str(tmp_path), path, filename), session)


def test_resolve_in_session_returns_none_for_empty(tmp_path):
    assert resolve_in_session(str(tmp_path), "") is None
    assert resolve_in_session(str(tmp_path), "   ") is None


def test_resolve_in_session_enforces_suffix(tmp_path):
    result = resolve_in_session(str(tmp_path), "报告.txt", ".md")
    assert result.name == "报告.md"


def test_resolve_in_session_keeps_matching_suffix(tmp_path):
    result = resolve_in_session(str(tmp_path), "sub/报告.md", ".md")
    assert result == (tmp_path / "sub" / "报告.md").resolve()


def test_resolve_in_session_strips_traversal(tmp_path):
    result = resolve_in_session(str(tmp_path), "../secret.txt")
    assert result == (tmp_path / "secret.txt").resolve()
    assert_inside(result, tmp_path.resolve())
