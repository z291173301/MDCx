"""赞助对话框：展示微信/支付宝收款码与赞助榜单。

侧栏「使用说明」按钮下方的 ``[赞助作者]`` 链接点击后弹出本窗口。

版式严格复刻参考截图 ``resources/Img/@赞助.png``：该图是 657×677 的 PNG（**125%
DPI 整窗截图**，含约 40px 原生标题栏）。本对话框的客户区取 657×637，于是**整窗正好
657×677，与参考图 1:1**；客户区里 1 逻辑像素在屏幕上占 1.25 设备像素，所以下文所有
坐标/尺寸都直接照抄参考图的客户区像素（``client_y = ref_y - 40``）：

    y=13   加粗黑色说明（宋体 14px）
    y=43   灰色小字（宋体 11px）
    y=67   两张 192×197 纯白收款码（无边框、无标题文字），卡间距 23
    y=283  两个 309×315 榜单框（1px 边框，框内无横竖线），框间距 8，
              标题「新人榜Top10 / 土豪榜Top10」压在框的上边线上，
              框内 10 行 3 列（用户名 / 日期时间 / 金额），行距 28.78
    y=613  底部一行说明（宋体 14px）

参考图正文是**宋体**：同样把字宽调到与参考一致时，雅黑的字墨迹高会到 25 设备像素
（参考只有 17），差 47%，肉眼明显偏"高瘦"；宋体只到 17~19，与参考几乎一致。

所有子控件都用绝对坐标摆放——窗口尺寸固定，绝对定位是复刻截图最忠实的方式。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
)

from ..config.resources import resources
from ..controllers.main_window.style import get_theme_tokens

# ------------------------------------------------------------------ 设计尺寸
# 客户区尺寸 = 参考图 657×677 整窗扣掉约 40px 原生标题栏（125% DPI）
_DIALOG_W = 657
_DIALOG_H = 637

# 说明 / 小字（高度含少量行高余量，垂直居中）
_INTRO_Y, _INTRO_H = 4, 36
_HINT_Y, _HINT_H = 35, 28

# 收款码（两张码居中排布，尺寸/间距照抄参考图）
_CARD_W, _CARD_H = 192, 197
_CARD_Y = 67
_CARD_GAP = 23

# 榜单框（1px 边框，框内无横竖线）
_RANK_W, _RANK_H = 309, 315
_RANK_Y = 283
_RANK_LEFT_X = 16
_RANK_GAP = 7  # 参考图右框左边线在 x=332：16 + 309 + 7
_RANK_TITLE_DY = -11  # 标题压在框上边线上（相对框顶），参考图墨迹中心 286 / 边线 283
_RANK_TITLE_H = 28
# 标题自身是一块不透明底色，用来把框的上边线在文字两侧「截断」（参考图即此效果）。
# 三个量都照抄参考图实测（左框 x=16 起）：
#   底色块左缘 x=28   → 上边线自框左 +12 起被遮（实测 +9，差 3px 属可接受）
#   文字墨迹 28..132  → 文字左缘即底色块左缘，故无需额外左内边距
#   上边线自 x=137 恢复 → 底色块右缘约在框左 +118
_RANK_TITLE_DX = 12
_RANK_TITLE_PAD_R = 4
# 表格相对框左上角的偏移：用户名列起点距框左 13，日期列中心距框左 145，
# 金额列右对齐终点距框左 293
_TBL_DX, _TBL_DY = 13, 18
_TBL_W, _TBL_H = 284, 290
_COL_W = (86, 94, 104)  # 用户名 / 日期时间 / 金额（照抄参考图列落位，日期列不省略）
_ROW_H = 29  # 10 行 290：283+18+290 = 591 ≤ 框底 598

# 底部一行
_FOOTER_Y, _FOOTER_H = 605, 34

# ------------------------------------------------------------------ 字体
# 参考图正文是宋体（见模块 docstring）。本窗口客户区 657×637 **逻辑**像素照抄了参考图
# 657×637 **设备**像素的全部坐标，故字号要比参考图的等效字号大 1.25 倍（参考图是 125%
# DPI 截图，1 设备像素 = 0.8 逻辑像素）。下面 (px, bold, 字距%) 三元组由「墨迹宽 + 墨迹
# 高」双指标网格搜索得到（量 grab() 的设备像素再换回逻辑像素，与参考图原始像素比较）：
#   加粗说明   18px **粗体**（用户要求黑色加粗）
#   灰色小字   12px 常规 +15% 字距 → 534×11，参考 534×12（宽完全一致）
#   榜单标题   18px **粗体**（用户要求黑色加粗）
#   数据行     17px 常规       → 墨迹高约 14，参考 14；与榜单标题 17.6 的比例 0.82
#                            与参考图 14/17 一致（榜单为空数据，无可见影响）
#   底部一行   18px 常规        → 560×17，参考 578×17（本窗文案不同，宽差无意义）
# 字距：网格搜索在非粗体下最优解为 +2%/+8%，改粗体后笔画变宽、字距回调到 0。
_FONT = "SimSun"
_FONT_SPECS = {
    "intro": (18, True, 0),
    "hint": (12, False, 15),
    "rank_title": (18, True, 0),
    "row": (17, False, 0),
    "footer": (18, False, 0),
}
_FS_ROW = _FONT_SPECS["row"][0]  # 表格 QSS 里要用

# ------------------------------------------------------------------ 配色
# 参考图取色（按 min(R,G,B) <= 100 取核心笔画像素，避开 ClearType 色边）
_REF_BG = "#F0F0F0"  # 客户区底色（Windows 默认窗口灰）
_REF_FG = "#000000"  # 加粗说明/榜单标题最暗像素 (0,1,1)
_REF_HINT = "#4A4A4A"  # 小字核心笔画 min 通道均值 83 / p5=71
_REF_BORDER = "#DCDCDC"  # 榜单框边框 #DCDCDC~#E4E4E4
_REF_CARD = "#FFFFFF"  # 收款码纯白方块

_INTRO_TEXT = "软件是免费的，欢迎捐助： 1.微信支付 2.支付宝付款 3.拿支付宝红包"
_HINT_TEXT = "您的支持是我最大的动力，捐助是自愿的，表示对本软件的支持，并没有提供额外的功能"
_FOOTER_TEXT = "欢迎加入 MDCx 官方交流群一起交流使用经验，反馈问题与建议"

_RANK_TITLES = ("新人榜Top10", "土豪榜Top10")
_RANK_ROWS = 10
_RANK_COLS = 3


class DonateDialog(QDialog):
    """赞助窗口：收款码 + 新人榜/土豪榜（版式严格复刻参考截图）。"""

    def __init__(self, parent=None, dark: bool = False) -> None:
        super().__init__(parent)
        self._dark = bool(getattr(parent, "dark_mode", dark))
        self._c = self._palette()
        self.setWindowTitle("赞助")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedSize(_DIALOG_W, _DIALOG_H)
        # 先铺底色再建控件：QLabel 一旦挂上样式表，样式引擎会覆盖 setFont 传入的字体，
        # 故本对话框全程不用样式表改字体（配色走 QPalette，字体走 setFont）。
        self._style_dialog()
        self._build_ui()

    # ------------------------------------------------------------------ 配色

    def _palette(self) -> dict[str, str]:
        """亮色严格用参考图取色；暗黑模式跟随应用主题 token。"""
        if self._dark:
            t = get_theme_tokens(True)
            return {
                "bg": t["window"],
                "fg": t["text"],
                "hint": t["text_muted"],
                "border": t["border"],
                "card": t["surface"],
            }
        return {
            "bg": _REF_BG,
            "fg": _REF_FG,
            "hint": _REF_HINT,
            "border": _REF_BORDER,
            "card": _REF_CARD,
        }

    # ------------------------------------------------------------------ 构建

    def _label(
        self,
        text: str,
        x: int,
        y: int,
        w: int,
        h: int,
        px: int,
        color: str,
        bold: bool = False,
        center: bool = False,
        spacing: int = 0,
    ) -> QLabel:
        label = QLabel(text, parent=self)
        label.setGeometry(x, y, w, h)
        label.setFont(self._font(px, bold, spacing))
        # 文字颜色走 QPalette 而不是样式表：样式表会连带把字体打回默认值
        palette = label.palette()
        palette.setColor(QPalette.ColorRole.WindowText, QColor(color))
        label.setPalette(palette)
        label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
            if center
            else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        return label

    @staticmethod
    def _font(px: int, bold: bool, spacing: int = 0) -> QFont:
        font = QFont(_FONT)
        font.setPixelSize(px)
        font.setBold(bold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100 + spacing)
        return font

    def _build_ui(self) -> None:
        fs_px, fs_bold, fs_sp = _FONT_SPECS["intro"][:3]
        # 加粗说明（居中）
        self._label(
            _INTRO_TEXT, 0, _INTRO_Y, _DIALOG_W, _INTRO_H, fs_px, self._c["fg"],
            fs_bold, True, fs_sp,
        )
        fs_px, fs_bold, fs_sp = _FONT_SPECS["hint"][:3]
        # 灰色小字（居中，单行不折行——宽度够放下参考图那一行）
        self._label(
            _HINT_TEXT, 0, _HINT_Y, _DIALOG_W, _HINT_H, fs_px, self._c["hint"],
            fs_bold, True, fs_sp,
        )

        # 两张收款码：纯白方块，无边框、无标题文字（照抄参考图）
        total = _CARD_W * 2 + _CARD_GAP
        card_x = (_DIALOG_W - total) // 2
        for i, image in enumerate((resources.donate_wechat_icon, resources.donate_alipay_icon)):
            self._build_card(card_x + i * (_CARD_W + _CARD_GAP), _CARD_Y, image)

        # 两个榜单框
        self._build_rank(_RANK_LEFT_X, _RANK_TITLES[0])
        self._build_rank(_RANK_LEFT_X + _RANK_W + _RANK_GAP, _RANK_TITLES[1])

        fs_px, fs_bold, fs_sp = _FONT_SPECS["footer"][:3]
        # 底部一行（居中）
        self._label(
            _FOOTER_TEXT, 0, _FOOTER_Y, _DIALOG_W, _FOOTER_H, fs_px, self._c["fg"],
            fs_bold, True, fs_sp,
        )

    def _build_card(self, x: int, y: int, image_path: str) -> None:
        """一张收款码：纯白方块直接放在灰底上（参考图无圆角/描边，也无标题文字）。"""
        frame = QFrame(parent=self)
        frame.setObjectName("donate_card")
        frame.setGeometry(x, y, _CARD_W, _CARD_H)
        frame.setStyleSheet(
            f"QFrame#donate_card {{ background: {self._c['card']}; border: none; }}"
        )
        qr = QLabel(parent=frame)
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr.setGeometry(0, 0, _CARD_W, _CARD_H)
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            px, bold, sp = _FONT_SPECS["hint"]
            qr.setText("二维码加载失败")
            # 字体必须写进样式表：样式表一旦生效就会覆盖 setFont
            qr.setStyleSheet(
                f"color: {self._c['hint']}; background: transparent;"
                f" font-family: '{_FONT}'; font-size: {px}px; font-weight: {'bold' if bold else 'normal'};"
            )
        else:
            qr.setPixmap(
                pixmap.scaled(
                    _CARD_W,
                    _CARD_H,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _rank_title(self, box_x: int, title: str) -> QLabel:
        """榜单标题：压在框的上边线上，自身用对话框底色**不透明**填充。

        宽度只包住文字（右缘约在框左 +118），故框的上边线在文字两侧被截断、不会穿过
        笔画；不拉满整条边线，否则整条上边线都会被盖掉。底色块左缘从文字左缘起，
        不压住框的左竖线（参考图左竖线在标题带内是完整的）。
        配色走 QPalette 而非样式表——样式表一旦挂上就会把 setFont 传入的字体打回默认值。
        """
        px, bold, sp = _FONT_SPECS["rank_title"]
        font = self._font(px, bold, sp)
        width = QFontMetrics(font).horizontalAdvance(title) + _RANK_TITLE_PAD_R
        head = QLabel(title, parent=self)
        head.setFixedSize(width, _RANK_TITLE_H)
        # 左缘内缩 _RANK_TITLE_DX：参考图的左竖线在标题带内是完整的，底色块不能压它
        head.move(box_x + _RANK_TITLE_DX, _RANK_Y + _RANK_TITLE_DY)
        head.setFont(font)
        palette = head.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(self._c["bg"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(self._c["fg"]))
        head.setPalette(palette)
        head.setAutoFillBackground(True)  # 不透明底色，把上边线挡在文字之外
        head.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        head.raise_()
        return head

    def _build_rank(self, box_x: int, title: str) -> None:
        """一个榜单区块：1px 边框矩形 + 标题压上边线 + 框内无横竖线的 10×3 表格。"""
        box = QFrame(parent=self)
        box.setObjectName("donate_rank")
        box.setGeometry(box_x, _RANK_Y, _RANK_W, _RANK_H)
        box.setStyleSheet(
            f"QFrame#donate_rank {{ background: transparent; border: 1px solid {self._c['border']}; }}"
        )

        # 标题压在框的上边线上，自身不透明填充把边线在文字两侧截断
        self._rank_title(box_x, title)

        table = QTableWidget(_RANK_ROWS, _RANK_COLS, parent=self)
        table.setGeometry(box_x + _TBL_DX, _RANK_Y + _TBL_DY, _TBL_W, _TBL_H)
        # 参考图榜单无表头、无横竖分隔线、无边框
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setFrameShape(QFrame.Shape.NoFrame)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalHeaderLabels(["用户名", "日期时间", "金额"])
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for col, width in enumerate(_COL_W):
            table.setColumnWidth(col, width)
        for row in range(_RANK_ROWS):
            table.setRowHeight(row, _ROW_H)
        # 用户名左对齐 / 日期时间居中 / 金额右对齐（照抄参考图列落位）
        aligns = (
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        for row in range(_RANK_ROWS):
            for col in range(_RANK_COLS):
                item = QTableWidgetItem("")
                item.setTextAlignment(aligns[col])
                table.setItem(row, col, item)
        table.setFont(self._font(_FONT_SPECS["row"][0], _FONT_SPECS["row"][1]))
        # 字体写进样式表（样式表会覆盖 setFont），字号与参考图数据行同视觉量级
        table.setStyleSheet(
            f"QTableWidget {{ background: transparent; color: {self._c['fg']};"
            f" font-family: '{_FONT}'; font-size: {_FS_ROW}px;"
            f" border: none; gridline-color: transparent; }}"
            f"QTableWidget::item {{ border: none; padding: 0px; }}"
        )
        table.viewport().setStyleSheet("background: transparent;")

    # ------------------------------------------------------------------ 样式

    def _style_dialog(self) -> None:
        """铺客户区底色。

        刻意不用样式表：Qt 里只要控件挂了样式表，样式引擎就会把 setFont 设的字体
        打回默认字号（本项目的侧栏 [赞助作者] 链接也踩过同一个坑），而本窗口的
        字号必须严格照抄参考图，故配色一律走 QPalette。
        """
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(self._c["bg"]))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(self._c["fg"]))
        self.setPalette(palette)
        self.setAutoFillBackground(True)