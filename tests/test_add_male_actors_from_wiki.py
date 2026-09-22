"""校验 scripts/add_male_actors_from_wiki.py 的男优名提取与清洗逻辑。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.add_male_actors_from_wiki import _NOISE, extract_names  # noqa: E402


def _make_mhtml(path: Path, links: list[str]):
    """构造最小 mhtml：含指定 <a> 链接文本。"""
    body = "".join(f'<a href="x">{t}</a>' for t in links)
    content = (
        "MIME-Version: 1.0\r\n"
        "Content-Type: multipart/related; boundary=XBOUNDARY\r\n"
        "\r\n"
        "--XBOUNDARY\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "\r\n"
        f"<html><body>{body}</body></html>\r\n"
        "--XBOUNDARY--\r\n"
    )
    path.write_bytes(content.encode("utf-8"))
    return path


def test_extract_names_cleans_paren_alias(tmp_path):
    """括号别名标注取主名（しみけん（清水健）→ しみけん）。"""
    m = _make_mhtml(tmp_path / "p.mhtml", ["しみけん（清水健）", "大沢真司（中沢真）", "一徹"])
    names = extract_names(m)
    assert "しみけん" in names
    assert "大沢真司" in names
    assert "一徹" in names
    assert not any("（" in n for n in names)


def test_extract_names_filters_noise_and_nav(tmp_path):
    """噪声标签与导航词被排除。"""
    m = _make_mhtml(
        tmp_path / "p.mhtml",
        ["貞松大輔", "艦長", "TECH", "AV男優", "検索", "マンボウ堀内", "立即登录"],
    )
    names = extract_names(m)
    assert "貞松大輔" in names
    assert "マンボウ堀内" in names
    for noise in _NOISE:
        assert noise not in names
    assert "AV男優" not in names
    assert "検索" not in names
    assert "立即登录" not in names
