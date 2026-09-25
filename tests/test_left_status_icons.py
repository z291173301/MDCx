"""左下角状态区图标与仓库地址回归测试（纯静态，无需 Qt 运行时）。

背景：主界面左下角状态区（`label_show_version`）每行行首带一个 emoji 图标，
位置与 `mdcx-diy-main` 对齐；版本检查/下载/反馈地址统一由 `mdcx/consts.py`
的 `GITHUB_REPO` 派生，使用说明页（`MDCx.ui` / `MDCx.py`「十二、获取帮助」）
硬编码同一仓库地址。历史上出现过 `before_info` 的 emoji 被正则剥掉、
跳转地址指向旧仓库的回归，本文件把图标规范与仓库地址固化为自动化测试。

完整规范见 `docs/DEVELOPMENT.md`「左下角状态区图标规范」一节。
"""

from pathlib import Path

from mdcx.consts import (
    GITHUB_ISSUES_URL,
    GITHUB_RELEASES_API_LIST,
    GITHUB_RELEASES_URL,
    GITHUB_REPO,
)
from mdcx.models.flags import Flags

REPO = Path(__file__).resolve().parent.parent
MAIN_WINDOW_PATH = REPO / "mdcx" / "controllers" / "main_window" / "main_window.py"
CONSTS_PATH = REPO / "mdcx" / "consts.py"
UI_PATH = REPO / "mdcx" / "views" / "MDCx.ui"
PY_PATH = REPO / "mdcx" / "views" / "MDCx.py"

# 自有仓库（版本检查跳转、下载链接、Issue 反馈、使用说明页统一指向它）。
OWN_REPO = "z291173301/MDCx"
OLD_REPO = "cdlongbow/mdcx-diy"

# show_scrape_info / new_version 中必须逐字存在的图标行（删任一即报红）。
# 与 docs/DEVELOPMENT.md「左下角状态区图标规范」保持同步，改规范先改文档再改此处。
_REQUIRED_ICON_LITERALS = (
    "💡 单文件刮削",
    "💠 {Flags.main_mode_text}",
    "💡 {manager.config.website_single} 刮削",
    "🍯 软链接 · 开",
    "🍯 硬链接 · 开",
    "🛠 {manager.file}",
    "🐰 MDCx {self.localversion}",
    "🔍 点击检查最新版本",
    "🍉 有新版本了",
)


def _main_window_text() -> str:
    return MAIN_WINDOW_PATH.read_text(encoding="utf-8")


def test_status_icons_present_in_show_scrape_info():
    """左下角状态区 9 处行首图标缺一不可（被删/被改即报红）。"""
    text = _main_window_text()
    missing = [lit for lit in _REQUIRED_ICON_LITERALS if lit not in text]
    assert not missing, f"左下角状态区图标被修改或删除，缺失：{missing}"


def test_before_info_emoji_not_stripped():
    """before_info 的 emoji 不得再被过滤（曾用正则剥掉导致首行图标丢失）。"""
    text = _main_window_text()
    assert "SCRAPE_INFO_EMOJI_RE" not in text, (
        "emoji 过滤常量回来了：before_info 的 💡/🔎/🎉/⛔/✅ 会被剥掉，与 diy-main 显示不一致"
    )
    assert "before_info = before_info.strip()" in text, "before_info 应只做 strip，不得过滤 emoji"


def test_github_repo_points_to_own_fork():
    """版本检查跳转/下载/API/反馈地址统一指向自有仓库。"""
    assert GITHUB_REPO == OWN_REPO, f"GITHUB_REPO 应为 {OWN_REPO}，实际 {GITHUB_REPO}"
    assert GITHUB_RELEASES_URL == f"https://github.com/{OWN_REPO}/releases"
    assert GITHUB_RELEASES_API_LIST == f"https://api.github.com/repos/{OWN_REPO}/releases?per_page=10"
    assert GITHUB_ISSUES_URL == f"https://github.com/{OWN_REPO}/issues/new/choose"
    consts_text = CONSTS_PATH.read_text(encoding="utf-8")
    assert OLD_REPO not in consts_text, f"consts.py 仍引用旧仓库 {OLD_REPO}"


def test_help_page_urls_point_to_own_fork():
    """使用说明页「获取帮助」的项目主页/Release 下载指向自有仓库（.ui/.py 一致）。"""
    ui_text = UI_PATH.read_text(encoding="utf-8")
    py_text = PY_PATH.read_text(encoding="utf-8")
    for label, text in (("MDCx.ui", ui_text), ("MDCx.py", py_text)):
        assert f"https://github.com/{OWN_REPO}" in text, f"{label} 使用说明页缺少项目主页新地址"
        assert f"https://github.com/{OWN_REPO}/releases" in text, f"{label} 使用说明页缺少 Release 新地址"
        assert OLD_REPO not in text, f"{label} 使用说明页仍引用旧仓库 {OLD_REPO}"


def test_flags_reset_preserves_mode_texts():
    """Flags.reset() 不得清空模式文案（否则刮削后模式行只剩 💠 光杆图标）。

    背景：_run 经 reset_flags_preserving_single_file_inputs() 调 reset()，
    reset 曾把 main_mode_text / scrape_like_text 置空且无人恢复，
    刮削完成后左下角模式行在所有模式下显示为「💠 ·」（读取模式最先被发现）。
    二者是配置派生展示态，reset 必须保留。
    """
    old_main, old_like = Flags.main_mode_text, Flags.scrape_like_text
    try:
        Flags.main_mode_text = "读取模式"
        Flags.scrape_like_text = "字段优先"
        Flags.reset()
        assert Flags.main_mode_text == "读取模式", "reset() 清空了 main_mode_text，模式行将只剩图标"
        assert Flags.scrape_like_text == "字段优先", "reset() 清空了 scrape_like_text，模式行将只剩图标"
    finally:
        Flags.main_mode_text, Flags.scrape_like_text = old_main, old_like
