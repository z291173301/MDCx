"""版本号同步点一致性校验（发版流程回归）。

版本号有五个同步点：
1. `mdcx/consts.py` 的 `LOCAL_VERSION`（纯数字 YYYYMMDD，GitHub tag 也用它）
2. `mdcx/consts.py` 的 `VERSION_NAME`（展示名 vX.Y.Z）
3. `pyproject.toml` 的 `version`（去掉 v 前缀）
4. `docs/Changelog.md` 首个版本段标题 `## vX.Y.Z (YYYY-MM-DD)` 的版本与日期
5. `uv.lock` 根包 `mdcx` 的 `version`（CI 全平台 `uv sync --locked` 强校验，脱节即构建失败）

`scripts/bump.py --check` 与本测试覆盖同一不变量；此处用 pytest 让它进入常规回归。
"""

import re
import tomllib
from pathlib import Path

from mdcx.consts import LOCAL_VERSION, VERSION_NAME

_ROOT = Path(__file__).parent.parent


def test_version_name_matches_pyproject():
    package_version = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    display_version = VERSION_NAME.removeprefix("v")

    assert re.fullmatch(r"\d+\.\d+\.\d+", display_version)
    assert package_version == display_version


def test_changelog_head_matches_local_version_and_name():
    changelog = (_ROOT / "docs" / "Changelog.md").read_text(encoding="utf-8")
    head = re.search(r"(?m)^##\s+(v\d+\.\d+\.\d+)\s+\((\d{4})-(\d{2})-(\d{2})\)", changelog)

    assert head is not None, "changelog 首个版本段格式应为 '## vX.Y.Z (YYYY-MM-DD)'"
    assert head.group(1) == VERSION_NAME, f"changelog 首个版本段 {head.group(1)} 与 VERSION_NAME {VERSION_NAME} 不一致"
    date_digits = head.group(2) + head.group(3) + head.group(4)
    assert date_digits == str(LOCAL_VERSION), (
        f"changelog 版本段日期 {date_digits} 与 LOCAL_VERSION {LOCAL_VERSION} 不一致"
    )


def test_uv_lock_root_version_matches_display_name():
    """uv.lock 根包版本必须与展示版本一致。

    背景：曾出现只升 `pyproject.toml`、漏同步 `uv.lock` 的情况，CI 四个平台
    （windows/macos-aarch64/macos-intel/linux）的 `uv sync --locked` 在
    `Install locked dependencies` 步全部 exit 1。改版本号/日期后本测试即时告警。
    """
    uv_lock = _ROOT / "uv.lock"
    assert uv_lock.exists(), "uv.lock 缺失"
    content = uv_lock.read_text(encoding="utf-8")
    match = re.search(r'(?m)^\[\[package\]\]\nname = "mdcx"\nversion = "([^"]+)"', content)
    assert match is not None, (
        'uv.lock 中找不到根包 mdcx 的 version（期望 [[package]] / name = "mdcx" / version = "X.Y.Z" 三行连排）'
    )
    display_version = VERSION_NAME.removeprefix("v")
    assert match.group(1) == display_version, (
        f"uv.lock 根包 version={match.group(1)} 与 VERSION_NAME={VERSION_NAME} 不一致；"
        "请执行 `uv lock` 或 `uv run bump --name <版本>` 同步，否则 CI 构建必败"
    )
