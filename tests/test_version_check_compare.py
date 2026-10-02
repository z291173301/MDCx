"""更新检测的比较规则：**版本号(vX.Y.Z) 与日期(YYYYMMDD) 同时对比**。

规则（`mdcx/base/web.py` 的 `is_remote_version_newer`）——**版本号优先，版本号相等
才比日期**：
- 两侧版本号都能解析且**不同** → 由版本号决出，远端更高即有新版本（此时日期不参与）；
- 两侧版本号都能解析且**相等** → 比日期，远端日期更新即有新版本；
- 任一侧版本号解析不出来（标题非 `vX.Y.Z` 形态）→ 退回**只比日期**。

为什么必须同时比两个维度：原实现只比 `LOCAL_VERSION`（纯数字日期），于是
**同一天发两版**（当天先发 v2.1.8 再发 v2.1.9，两个 tag 都是同一天）永远认不出第二版；
反过来只比版本号，又会在「同版本号、跨日期补发修复版」时漏判。两条并列才覆盖得住。

为什么不让日期在版本号更低时也触发（即不做字面 OR）：那会让程序提示用户**降级**
（远端 v2.1.8 / 今天 vs 本地 v2.1.9 / 昨天），而仓库里 `LOCAL_VERSION` 常先于线上
发布 bump（源码已 20261002 而线上还是 20261001），开发版会对着已发布的历史版本反复
提示「请及时更新」。版本号优先同时避开了这个坑。
"""

import pytest

from mdcx.base.web import RemoteVersion, is_remote_version_newer, parse_release_version


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v2.1.8 (20261001)", (2, 1, 8)),
        ("2.1.8", (2, 1, 8)),
        ("Release v2.1.8 (20261001) 正式版", (2, 1, 8)),
        ("v10.0.12 (20261001)", (10, 0, 12)),
        ("v2.1.8-rc1 (20261001)", (2, 1, 8)),
        ("20261001", None),
        ("", None),
        ("nightly build", None),
    ],
)
def test_parse_release_version(text, expected):
    assert parse_release_version(text) == expected


def _newer(remote_tag: int, remote_name: str, local_tag: int = 20261002, local_name: str = "v2.1.9") -> bool:
    return is_remote_version_newer(RemoteVersion(tag=remote_tag, name=remote_name), local_tag, local_name)


# --- 版本号不同：由版本号决出（日期不参与）-------------------------------------


def test_higher_version_is_new_even_with_older_date():
    """版本号更高即有新版本，哪怕远端日期更旧（版本号优先于日期）。"""
    assert _newer(20261001, "v2.9.0 (20261001)") is True


def test_lower_version_is_not_new_even_with_newer_date():
    """版本号更低则不是新版本，哪怕远端日期更新——否则会提示用户降级。"""
    assert _newer(20261003, "v2.1.8 (20261003)") is False


def test_higher_version_with_newer_date_is_new():
    assert _newer(20261003, "v2.2.0 (20261003)") is True


def test_lower_version_with_older_date_is_not_new():
    assert _newer(20261001, "v2.1.8 (20261001)") is False


# --- 版本号解析不出来：退回只比日期 -------------------------------------------


def test_newer_date_with_unparsable_version_name_is_new():
    """远端标题认不出版本号时，只能靠日期，日期更新即算新。"""
    assert _newer(20261003, "nightly") is True
    assert _newer(20261003, "") is True


def test_older_date_with_unparsable_version_name_is_not_new():
    assert _newer(20261001, "nightly") is False


# --- 版本号相同：改由日期决出 -------------------------------------------------


def test_same_date_higher_version_is_new():
    """当天发两版：tag 都是 20261002，版本号 v2.2.0 > v2.1.9 → 必须提示。"""
    assert _newer(20261002, "v2.2.0 (20261002)") is True


def test_same_date_lower_version_is_not_new():
    assert _newer(20261002, "v2.1.8 (20261002)") is False


def test_same_date_same_version_is_not_new():
    assert _newer(20261002, "v2.1.9 (20261002)") is False


def test_same_date_but_remote_version_unparsable_is_not_new():
    """日期相同且远端版本号认不出 → 没有证据说明有新版本，不提示（宁可不提示也不误报）。"""
    assert _newer(20261002, "nightly") is False


def test_same_date_local_version_unparsable_is_not_new():
    """本地版本名认不出时同样退回「只信日期」。"""
    assert _newer(20261002, "v2.2.0 (20261002)", local_name="") is False


# --- 版本号相同：日期决胜（跨版本号复用日期补发的唯一识别路径）----------------


def test_same_version_newer_date_is_new():
    """版本号相同但远端日期更新 → 有新版本（如 v2.1.8 沿用旧 tag 补发修复版）。"""
    assert _newer(20261005, "v2.1.9 (20261005)") is True


def test_same_version_older_date_is_not_new():
    assert _newer(20261001, "v2.1.9 (20261001)") is False


# --- 真实仓库场景：源码已 bump 到未发布版本 ----------------------------------


def test_dev_build_ahead_of_release_is_not_prompted():
    """本仓库现状：源码 v2.1.9 (20261002)，线上最新 v2.1.8 (20261001) → 不提示。"""
    assert _newer(20261001, "v2.1.8 (20261001)", local_tag=20261002, local_name="v2.1.9") is False


def test_older_build_is_prompted_with_latest_release():
    """v2.1.7 (20260930) 的用户应看到 v2.1.8 (20261001) 的更新提示。"""
    assert _newer(20261001, "v2.1.8 (20261001)", local_tag=20260930, local_name="v2.1.7") is True


def test_release_display_falls_back_to_tag_without_name():
    assert RemoteVersion(tag=20261001, name="").display == "20261001"
    assert RemoteVersion(tag=20261001, name="v2.1.8 (20261001)").display == "v2.1.8 (20261001)"
