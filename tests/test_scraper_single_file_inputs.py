from pathlib import Path

import pytest

from mdcx.models.flags import Flags


@pytest.fixture(autouse=True)
def _clean_flags():
    Flags.reset()
    yield
    Flags.reset()


def test_single_file_inputs_survive_reset():
    """议题 #94：单文件输入必须在 reset 后保留，否则「填网址刮削」永远拿不到 appoint_url。"""
    from mdcx.core.scraper import reset_flags_preserving_single_file_inputs

    Flags.single_file_path = Path("D:/Media/欧美/FapHouse.25.06.28.mp4")
    Flags.appoint_url = "https://theporndb.net/scenes/comatozze-fucking"
    Flags.website_name = "theporndb"
    # 预置一些运行态，证明 reset 确实清理了它们
    Flags.succ_count = 5
    Flags.fail_count = 2

    reset_flags_preserving_single_file_inputs()

    assert Flags.single_file_path == Path("D:/Media/欧美/FapHouse.25.06.28.mp4")
    assert Flags.appoint_url == "https://theporndb.net/scenes/comatozze-fucking"
    assert Flags.website_name == "theporndb"
    # 其余运行态确实被清空
    assert Flags.succ_count == 0
    assert Flags.fail_count == 0


def test_default_mode_inputs_stay_empty_after_reset():
    """普通模式没有单文件输入，reset 后它们应保持空值，行为与裸 reset 一致。"""
    from mdcx.core.scraper import reset_flags_preserving_single_file_inputs

    Flags.single_file_path = Path()
    Flags.appoint_url = ""
    Flags.website_name = ""

    reset_flags_preserving_single_file_inputs()

    assert Flags.single_file_path == Path()
    assert Flags.appoint_url == ""
    assert Flags.website_name == ""


def test_bare_flags_reset_clears_single_file_inputs():
    """对照：裸 Flags.reset() 会清空单文件输入（即 #94 修复前的旧行为），
    以确认修复确实在改变行为而非恒等。"""
    Flags.single_file_path = Path("D:/Media/x.mp4")
    Flags.appoint_url = "https://theporndb.net/scenes/x"
    Flags.website_name = "theporndb"

    Flags.reset()

    assert Flags.single_file_path == Path()
    assert Flags.appoint_url == ""
    assert Flags.website_name == ""
