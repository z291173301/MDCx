"""命名页画质组（groupBox_65）间距收紧回归测试。

背景：HD、FHD、QHD、UHD 行与分辨率获取方式行之间太松，最大化与最小化都要收。
静态 .ui 高度只能顾一态（label_331 窄态两行刚好，最大化时文字只占一行、白白
剩下一半空白），故运行时按内容收紧（见 MyMAinWindow._sync_definition_group_spacing，
翻译组 _sync_fanyi_group_spacing 同款做法）。

本测试用 offscreen 整窗：切到软件设置-命名页，窄/宽两档窗口下分别同步并断言：
1. 网格容器高度钉到 sizeHint（两行单选贴紧，无均分空白）；
2. QHD 说明高度覆盖文字且不超过设计 41px（宽态必须缩到单行）；
3. 四处行间距里「说明↔分辨率行」「分辨率行↔添加4K行」「添加4K行↔尾说明」各
   空出**恰好一行文字高**（用户先后要求这三处向下移动一行），仅「说明↔HD行」
   恒为 0px；
4. 组底留白恒为 25px（definition 说明下方空白不增加）；
5. 后续组（其他说明）间距恒为 19px；
6. 组高小于设计 301px（确实收紧了）；
7. 连续调用两次几何不变（幂等、无累积漂移）；
8. **控件内部**留白也被吃掉（第二轮需求）：用户截图里的空隙不在控件之间、
   而在控件自身——radio/checkbox 的 minimumHeight=30 把「分辨率获取方式行」和
   「末端添加4K字符行」各撑到 30px（字号墨迹只 16px），gridLayout_43 的
   verticalSpacing=6 又在两行单选之间留 6px，「末端添加4K字符：」标签垂直居中
   再空 10px。故 .ui 里把这三处 minimumSize 高度改成 16、verticalSpacing 改 0，
   运行时刻 label_357/label_331 的**墨迹**高度（不是行盒），组内像素扫描实测
   控件自身留白从 14/17/17/8px 全部收敛到 ≤3px；控件之间则按上面第 3 条的
   要求刻意留出整行行高。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QApplication

_app: QApplication | None = None


def _ensure_app() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app


@pytest.fixture(scope="module")
def app():
    return _ensure_app()


@pytest.fixture()
def win(app, monkeypatch, tmp_path):
    from mdcx.consts import MAIN_PATH
    from mdcx.controllers.main_window import main_window as mw_mod
    from mdcx.controllers.main_window import style as style_mod

    monkeypatch.setattr(mw_mod, "run_startup_health_checks", lambda: None)
    monkeypatch.setattr(mw_mod, "show_netstatus", lambda: None)
    monkeypatch.setattr(mw_mod, "check_version", lambda: None)
    monkeypatch.setattr(mw_mod, "save_remain_list", lambda: None)
    monkeypatch.setattr(mw_mod.MyMAinWindow, "set_style", lambda self: None)
    monkeypatch.setattr(mw_mod, "apply_site_priority_theme", lambda _window: None)
    monkeypatch.setattr(
        style_mod.resources,
        "qtr",
        lambda relative_path: str(MAIN_PATH / "resources" / relative_path),
    )
    monkeypatch.chdir(tmp_path)

    window = mw_mod.MyMAinWindow()
    for timer_name in ("timer", "timer_scrape", "timer_update", "timer_remain_task"):
        getattr(window, timer_name).stop()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def _goto_naming(win, app):
    ui = win.Ui
    for i in range(ui.stackedWidget.count()):
        if ui.stackedWidget.widget(i).objectName() == "page_setting":
            ui.stackedWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("page_setting not found")
    for i in range(ui.tabWidget.count()):
        if ui.tabWidget.widget(i).objectName() == "tab_3":
            ui.tabWidget.setCurrentIndex(i)
            break
    else:
        raise AssertionError("tab_3 not found")
    app.processEvents()


def _geom_snapshot(win):
    ui = win.Ui
    names = (
        "groupBox_65",
        "gridLayoutWidget_35",
        "label_331",
        "frame_6",
        "label_357",
        "checkBox_foldername_4k",
        "checkBox_filename_4k",
        "label_358",
        "groupBox_67",
    )
    return {n: getattr(ui, n).geometry().getRect() for n in names}


def _settle_naming(win, app, rounds=8):
    """把事件级联跑稳：同步→处理事件→快照，多轮直到几何连续两轮不变后返回。

    多轮是必要的：_sync_definition_group_spacing 钉高/挪位会触发视口滚动条出现
    或消失 → 命名内容宽变化 → 说明文字折行数可能再变 → 需要下一轮重算。
    """
    last = None
    for _ in range(rounds):
        win._sync_definition_group_spacing()
        app.processEvents()
        cur = _geom_snapshot(win)
        if cur == last:
            return cur
        last = cur
    return last


def _assert_tight(win):
    from mdcx.controllers.main_window.main_window import MyMAinWindow as MW

    ui = win.Ui
    box = ui.groupBox_65
    lw = ui.gridLayoutWidget_35
    note = ui.label_331
    frame = ui.frame_6
    row_label = ui.label_357
    check_f = ui.checkBox_foldername_4k
    check_n = ui.checkBox_filename_4k
    tail = ui.label_358
    follower = ui.groupBox_67

    # 1) 网格容器钉到 sizeHint
    assert lw.height() == ui.gridLayout_43.sizeHint().height(), lw.height()

    # 2) QHD 说明按当前宽度重新排版量出的**墨迹**高度贴合，且不超过设计 41px
    need = win._label_ink_height_for_width(note)
    assert note.height() == need, (note.height(), need)
    assert note.height() <= 41, note.height()

    # 3) 行间距按常量串起来。_DEFN_NOTE_GAP = -1 表示「插一整行文字高」，
    #    实际值取 label_331 字体的 lineSpacing（用户机器字号比离屏大，不写死）。
    assert note.y() == lw.y() + lw.height() + MW._DEFN_GRID_GAP
    note_gap = QFontMetrics(note.font()).lineSpacing()
    assert frame.y() == note.y() + note.height() + note_gap
    # 「末端添加4K字符」行也下移一行，行高取 frame_6 内 radio 的实测 lineSpacing
    frame_gap = QFontMetrics(ui.radioButton_videosize_video.font()).lineSpacing()
    row_y = frame.y() + frame.height() + frame_gap
    assert row_label.y() == row_y
    assert check_f.y() == row_y + MW._DEFN_ROW_CHECK_DY
    assert check_n.y() == row_y + MW._DEFN_ROW_CHECK_DY
    # 行高取三个控件的最大者：标签钉到墨迹高+4，单选/复选框 minimumHeight=16；
    # 之后空出恰好一行（用户「尾说明向下移动一行」）
    tail_gap = QFontMetrics(tail.font()).lineSpacing()
    assert tail.y() == row_y + max(row_label.height(), check_f.height(), check_n.height()) + tail_gap

    # 4) 组底留白 25px（下方空白不增加），组高远小于设计 301px
    assert tail.y() + tail.height() + MW._DEFN_BOX_BOT_PAD == box.height()
    assert box.height() < 301, box.height()

    # 5) 后续组间距 19px
    assert follower.y() == box.y() + box.height() + MW._DEFN_GROUP_GAP

    # 6) 控件**内部**不留白：网格行间距 0、三个单选/复选框 minimumHeight=16、
    #    「末端添加4K字符：」标签钉到墨迹高+4、frame_6 高度=内部布局 sizeHint。
    assert ui.gridLayout_43.verticalSpacing() == 0
    assert ui.radioButton_videosize_video.minimumHeight() == 16
    assert check_f.minimumHeight() == 16
    assert check_n.minimumHeight() == 16
    assert row_label.height() == win._label_ink_height_for_width(row_label) + 4
    assert row_label.height() <= 16, row_label.height()
    assert frame.height() == max(ui.horizontalLayout_112.sizeHint().height(), ui.layoutWidget_26.sizeHint().height())
    assert frame.height() <= 32, frame.height()


def test_definition_group_gap_constants(win, app):
    """各行间距常量必须钉死（用户要求：只留「向下移动一行」那一处间距）。

    _assert_tight 里那些间距是按类常量断言的，常量若被改回别的值它照样通过；
    这里直接把期望值钉死，避免间距被静默改掉。
    """
    from mdcx.controllers.main_window.main_window import MyMAinWindow as MW

    assert MW._DEFN_GRID_GAP == 0
    # -1 = 「插一整行文字高」，实际值在同步时按 label_331 字体 lineSpacing 解析
    assert MW._DEFN_NOTE_GAP == -1
    # 「末端添加4K字符」行同样「向下移动一行」
    assert MW._DEFN_FRAME_GAP == -1
    # 尾说明同样「向下移动一行」
    assert MW._DEFN_TAIL_GAP == -1
    # 组底留白与组间距是用户明确要求保留的，不在归零范围内
    assert MW._DEFN_BOX_BOT_PAD == 25
    assert MW._DEFN_GROUP_GAP == 19

    win.show()
    _goto_naming(win, app)
    win.resize(1600, 750)
    app.processEvents()
    _settle_naming(win, app)

    ui = win.Ui
    lw, note = ui.gridLayoutWidget_35, ui.label_331
    frame, row_label, tail = ui.frame_6, ui.label_357, ui.label_358
    # 说明紧贴 HD 行；说明与分辨率行、分辨率行与末端添加4K行之间各空出恰好
    # 一整行（用户连续三次「向下移动一行」）
    assert note.y() == lw.y() + lw.height()
    assert frame.y() - (note.y() + note.height()) == QFontMetrics(note.font()).lineSpacing()
    assert (
        row_label.y() - (frame.y() + frame.height())
        == QFontMetrics(ui.radioButton_videosize_video.font()).lineSpacing()
    )
    # 尾说明也与「末端添加4K字符」行空出恰好一行
    assert (
        tail.y()
        - (
            row_label.y()
            + max(row_label.height(), ui.checkBox_foldername_4k.height(), ui.checkBox_filename_4k.height())
        )
        == QFontMetrics(tail.font()).lineSpacing()
    )
    # frame_6 内部也贴紧：分辨率获取方式的标签在 frame 内垂直居中，无上下余量
    assert ui.layoutWidget_26.y() == 0
    assert ui.frame_6.height() == max(
        ui.horizontalLayout_112.sizeHint().height(), ui.layoutWidget_26.sizeHint().height()
    )


@pytest.mark.parametrize("width", [1030, 1600])
def test_definition_group_tight_in_both_states(win, app, width):
    """窄/宽两档窗口下画质组都收紧，且几何约束恒成立。

    高度由纯宽度函数（_label_ink_height_for_width：只吃 字体+文本+宽度，不掺标签
    自身高度）算出，不受级联中途标签内部陈旧折行布局影响，故每次同步结果只取决于
    当前宽度、必幂等（这里也断言了）。
    """
    win.show()
    _goto_naming(win, app)
    win.resize(width, 750)
    app.processEvents()
    _settle_naming(win, app)
    _assert_tight(win)
    # 幂等：落定后再跑一次几何纹丝不动
    before = _geom_snapshot(win)
    win._sync_definition_group_spacing()
    app.processEvents()
    assert _geom_snapshot(win) == before


def test_definition_group_wide_needs_no_more_height_than_narrow(win, app):
    """宽态 QHD 说明至多与窄态等高（单行 vs 双行），且两态都不超过设计。"""
    win.show()
    _goto_naming(win, app)
    heights = {}
    for width in (1030, 1600):
        win.resize(width, 750)
        app.processEvents()
        _settle_naming(win, app)
        heights[width] = win.Ui.label_331.height()
    assert heights[1600] <= heights[1030], heights
    assert heights[1030] <= 41, heights
