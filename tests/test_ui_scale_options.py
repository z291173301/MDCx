"""高分屏缩放档位回归测试：档位表 / 索引映射 / 超屏档位隐藏（议题 #186）。

用户 200% 反馈截图：界面缩放调大后，窗口被压到屏幕可用区以内但内容装不下，
左下角状态区与设置页内容互相挤压。缩放档位是「重启后生效」的一次性选择，
选错了用户只能看到坏界面再回头改，因此**放不下当前屏幕的档位直接从下拉里隐藏**，
从源头上避免误操作（`init.ui_scale_hidden_flags` / `init.apply_ui_scale_option_limits`）。

同时锁定 `init.UI_SCALE_OPTIONS` 与 `MDCx.ui` 中 comboBox_ui_scale 的下拉项
逐条对应——档位表是 load/save/隐藏三处共用的唯一真源，对不上就会静默写错配置。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QComboBox, QListView

from mdcx.controllers.main_window.init import (
    UI_SCALE_MIN_AVAILABLE_SIZE,
    UI_SCALE_OPTIONS,
    apply_ui_scale_option_limits,
    ui_scale_hidden_flags,
    ui_scale_index,
    ui_scale_value,
)

REPO = Path(__file__).resolve().parent.parent
UI_PATH = REPO / "mdcx" / "views" / "MDCx.ui"

# 跟随系统（0.0）之外的档位展示文本：与 MDCx.ui 的下拉项逐字一致
EXPECTED_LABELS = ("跟随系统", "80%", "90%", "100%", "125%", "150%", "175%", "200%", "300%")

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


class _FakeScreen:
    """只提供 apply_ui_scale_option_limits 用到的两个接口，便于喂任意分辨率。"""

    def __init__(self, width: int, height: int, dpr: float = 1.0) -> None:
        self._rect = QRect(0, 0, width, height)
        self._dpr = dpr

    def availableGeometry(self) -> QRect:  # noqa: N802 - 跟随 Qt 命名
        return self._rect

    def devicePixelRatio(self) -> float:  # noqa: N802 - 跟随 Qt 命名
        return self._dpr


def _hidden_values(flags: list[bool]) -> list[float]:
    return [value for value, hidden in zip(UI_SCALE_OPTIONS, flags, strict=True) if hidden]


def _visible_values(flags: list[bool]) -> list[float]:
    return [value for value, hidden in zip(UI_SCALE_OPTIONS, flags, strict=True) if not hidden]


def test_scale_options_table_matches_ui_items():
    """UI_SCALE_OPTIONS 逐条对应 MDCx.ui 里 comboBox_ui_scale 的下拉项（含新增 300%）。"""
    root = ET.parse(UI_PATH).getroot()
    combo = next(widget for widget in root.iter("widget") if widget.get("name") == "comboBox_ui_scale")
    labels = tuple(
        item.find("property/string").text  # type: ignore[union-attr]  # .ui 里必有 text
        for item in combo.findall("item")
    )
    assert labels == EXPECTED_LABELS, f"MDCx.ui 下拉项与预期不符: {labels}"
    assert len(UI_SCALE_OPTIONS) == len(EXPECTED_LABELS)
    # 除「跟随系统」外，展示百分比必须与档位值一致（防手改文案与档位脱节）
    for label, value in zip(EXPECTED_LABELS[1:], UI_SCALE_OPTIONS[1:], strict=True):
        assert label == f"{round(value * 100)}%", f"{label} 与档位 {value} 不符"


def test_ui_scale_index_and_value_round_trip():
    """索引 ↔ 缩放值互为逆运算；越界/非法值一律回落到「跟随系统」。"""
    for index, value in enumerate(UI_SCALE_OPTIONS):
        assert ui_scale_value(index) == value
        assert ui_scale_index(value) == index
    # 越界与非法输入
    assert ui_scale_value(-1) == 0.0
    assert ui_scale_value(len(UI_SCALE_OPTIONS)) == 0.0
    assert ui_scale_index(-0.5) == 0
    # 非档位值向下取档（历史行为：0.85→80%、1.9→175%）
    assert ui_scale_index(0.85) == 1
    assert ui_scale_index(1.9) == 6
    assert ui_scale_index(2.5) == 7


def test_hidden_flags_on_1080p_never_offers_oversized_scales():
    """1920×1080（可用 1920×1040，dpr 1）：175% 起放不下，必须隐藏；150% 仍可用。"""
    flags = ui_scale_hidden_flags(1920, 1040, 1.0)
    assert _hidden_values(flags) == [1.75, 2.0, 3.0]
    assert 1.5 in _visible_values(flags), "150% 在 1080p 上仍应可用"


def test_hidden_flags_scale_independent_of_current_dpr():
    """判定只看物理像素：150% 系统缩放的 2560×1440 与 100% 下的 1920×1040 同档结论。"""
    # 2560×1440 @ 系统 150%：Qt 报逻辑 1706×933、dpr 1.5 → 物理 2560×1400
    flags = ui_scale_hidden_flags(1706, 933, 1.5)
    assert 2.0 in _visible_values(flags), "2560×1440 @150% 下 200% 应可用"
    assert 3.0 in _hidden_values(flags), "2560×1440 高度不够，300% 必须隐藏"
    # 4K 2160p @100%（可用 3840×2100）：300% 也放得下（大屏用户需要这一档）
    flags_4k = ui_scale_hidden_flags(3840, 2100, 1.0)
    assert _hidden_values(flags_4k) == []


def test_hidden_flags_never_hide_follow_system():
    """「跟随系统」永远保留：它是默认值，也是超屏用户的退路。"""
    for avail_w, avail_h, dpr in ((1920, 1040, 1.0), (800, 800, 1.0), (640, 360, 2.0)):
        flags = ui_scale_hidden_flags(avail_w, avail_h, dpr)
        assert flags[0] is False, f"{avail_w}x{avail_h} 下不应隐藏「跟随系统」"


def test_hidden_flags_on_small_screen_keep_only_smallest_scales():
    """可用区小于最小窗口尺寸时，只留放得下的最小几档（与 850×650 判定式一致）。"""
    min_w, min_h = UI_SCALE_MIN_AVAILABLE_SIZE
    flags = ui_scale_hidden_flags(800, 800, 1.0)
    assert _visible_values(flags) == [0.0, 0.8, 0.9]
    # 判定式本身：90% 两边都放得下，100% 卡在宽度上（850 > 800）
    assert 0.9 * min_w <= 800 and 0.9 * min_h <= 800
    assert 1.0 * min_w > 800


def test_apply_ui_scale_option_limits_hides_rows():
    """QComboBox 无隐藏单项接口，靠 QListView.setRowHidden 隐藏对应行。"""
    _ensure_app()
    combo = QComboBox()
    view = QListView()
    combo.setView(view)
    for label in EXPECTED_LABELS:
        combo.addItem(label)

    apply_ui_scale_option_limits(combo, _FakeScreen(1920, 1040, 1.0))
    hidden = [view.isRowHidden(i) for i in range(combo.count())]
    assert hidden == ui_scale_hidden_flags(1920, 1040, 1.0)
    assert combo.itemText(7) == "200%" and hidden[7] is True

    # 换到大屏后重新计算：此前隐藏的档位要恢复
    apply_ui_scale_option_limits(combo, _FakeScreen(3840, 2100, 1.0))
    assert not any(view.isRowHidden(i) for i in range(combo.count()))


def test_apply_ui_scale_option_limits_keeps_current_value_when_hidden():
    """当前生效的档位即使被隐藏也不改选中项：不能静默改掉用户的界面缩放。"""
    _ensure_app()
    combo = QComboBox()
    view = QListView()
    combo.setView(view)
    for label in EXPECTED_LABELS:
        combo.addItem(label)
    combo.setCurrentIndex(8)  # 300%
    apply_ui_scale_option_limits(combo, _FakeScreen(1920, 1040, 1.0))
    assert combo.currentIndex() == 8
    assert combo.currentText() == "300%"
    assert ui_scale_value(combo.currentIndex()) == 3.0


def test_apply_ui_scale_option_limits_on_real_screen(app_offscreen=None):
    """真实 QScreen 路径（offscreen 平台）不得抛异常，且与纯函数结论一致。"""
    app = _ensure_app()
    screen = app.primaryScreen()
    assert screen is not None
    combo = QComboBox()
    view = QListView()
    combo.setView(view)
    for label in EXPECTED_LABELS:
        combo.addItem(label)
    apply_ui_scale_option_limits(combo, screen)
    avail = screen.availableGeometry()
    expected = ui_scale_hidden_flags(avail.width(), avail.height(), screen.devicePixelRatio())
    assert [view.isRowHidden(i) for i in range(combo.count())] == expected
    # 无屏时静默跳过（不抛异常）
    apply_ui_scale_option_limits(combo, None)


def test_config_accepts_300_percent_only():
    """配置字段上限 3.0：300% 可存，400% 仍应被 pydantic 拒绝。"""
    from pydantic import ValidationError

    from mdcx.config.models import Config

    assert Config().ui_scale_factor == 0.0
    assert Config(ui_scale_factor=3.0).ui_scale_factor == 3.0
    with pytest.raises(ValidationError):
        Config(ui_scale_factor=4.0)
