"""版本号四处同步点一致性校验（发版流程回归）。

版本号有四个同步点：
1. `mdcx/consts.py` 的 `LOCAL_VERSION`（纯数字 YYYYMMDD，GitHub tag 也用它）
2. `mdcx/consts.py` 的 `VERSION_NAME`（展示名 vX.Y.Z）
3. `pyproject.toml` 的 `version`（去掉 v 前缀）
4. `docs/changelog.md` 首个版本段标题 `## vX.Y.Z (YYYY-MM-DD)` 的版本与日期

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
    changelog = (_ROOT / "docs" / "changelog.md").read_text(encoding="utf-8")
    head = re.search(r"(?m)^##\s+(v\d+\.\d+\.\d+)\s+\((\d{4})-(\d{2})-(\d{2})\)", changelog)

    assert head is not None, "changelog 首个版本段格式应为 '## vX.Y.Z (YYYY-MM-DD)'"
    assert head.group(1) == VERSION_NAME, f"changelog 首个版本段 {head.group(1)} 与 VERSION_NAME {VERSION_NAME} 不一致"
    date_digits = head.group(2) + head.group(3) + head.group(4)
    assert date_digits == str(LOCAL_VERSION), (
        f"changelog 版本段日期 {date_digits} 与 LOCAL_VERSION {LOCAL_VERSION} 不一致"
    )
