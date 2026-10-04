"""赞助对话框：展示微信/支付宝/支付宝红包三张收款码与赞助榜单。

侧栏「使用说明」按钮下方的 ``[赞助作者]`` 链接点击后弹出本窗口。

版式严格复刻参考截图 ``resources/Img/@赞助.png``：该图是 657×677 的 PNG（**125%
DPI 整窗截图**，含约 40px 原生标题栏）。本对话框的客户区取 657×637，于是**整窗正好
657×677，与参考图 1:1**；客户区里 1 逻辑像素在屏幕上占 1.25 设备像素，所以下文所有
坐标/尺寸都直接照抄参考图的客户区像素（``client_y = ref_y - 40``）：

    y=13   黑色说明（微软雅黑，参考图像素）
    y=43   灰色小字（微软雅黑）
    y=66   三张 198×198 纯白收款码（无边框、无标题文字），卡间距 16，左缘 16
           （与榜单框左缘同值，右侧余 15）
    y=283  两个 309×315 榜单框（1px 边框，框内无横竖线），框间距 8，
              标题「新人榜Top10 / 土豪榜Top10」压在框的上边线上，
              框内 10 行 3 列（用户名 / 日期时间 / 金额），行距 28.78
    y=613  底部一行说明（微软雅黑）

参考图正文是**微软雅黑**：字形无衬线、字面率高（早先误判成宋体）。参考图是 125% DPI 截图，
其字号是**设备**像素而本窗字号是**逻辑**像素，故按「渲染真实控件（同样 125% DPI）→ 与参考图
逐行量墨迹宽高」标定基线：说明行 15px 字距 +2%、灰色小字 11px、榜单标题 14px、数据行 13px、
底部一行 13px，全部**非粗体**（参考图正文无粗体）。其后按用户要求把整宽文字逐次缩小：说明行 19px、灰色小字 14px、底部一行 16px（均非粗体，
字距沿用参考图标定值）；榜单标题也按用户要求改成与底部一行**同字体同字号**（16px 常规），
只有数据行维持参考图基线 13px。字号、余量与判据见 ``_FONT_SPECS`` 上方注释。

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

# 收款码（三张码排布，尺寸/间距/左缘照抄参考图；三张等宽同高，任意一张缺图不影响排版）
_CARD_COUNT = 3
_CARD_W, _CARD_H = 198, 198
_CARD_Y = 66
_CARD_GAP = 16
# 左缘取 16 而非「按总宽居中」((657 - 3*198 - 2*16) / 2 = 15.5)：参考图里收款码左缘与
# 榜单框左缘（_RANK_LEFT_X = 16）严格对齐，居中取整会让整排码比下面的榜单框左移 1px
_CARD_X = 16

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
# 参考图正文是微软雅黑（见模块 docstring）。基线字号按「渲染真实控件 → 与参考图逐行量墨迹
# bbox」标定（参考图 dpi 元数据 119.99 ≈ 125%，其字号是**设备**像素，本窗是**逻辑**像素）：
#   榜单标题   16px 常规 字距 0 → 与底部一行**完全同字体同字号**（按用户要求，非参考图基线：
#                                    参考图标定的 14px 偏小）；见下方「榜单标题」一条
#   数据行     13px 常规 字距 0 → 12×81，参考 日期列墨迹 14×85
# 三行整宽文字（说明行 / 灰色小字 / 底部一行）按用户要求逐次缩小；判据是
# QFontMetrics.horizontalAdvance(整行) ≤ _DIALOG_W(657 逻辑像素)，超过就会折行并被固定高度
# （_INTRO_H=36 / _HINT_H=28 / _FOOTER_H=34）裁掉。三行同用 _FONT（微软雅黑），字距保持
# 参考图标定值，均单行居中：
#   说明行     19px 常规 字距 +2% → advance 588（左右各余约 34）；极限是 21px（650），22px 起 681 会折行
#   灰色小字   14px 常规 字距  0  → advance 546（左右各余约 55）；按用户要求「改小两号」——
#                                    中文字号 三号 16 → 小三 15 → 四号 14，故取 14px（该行 39 字，
#                                    17px 起 663 > 657 会折行，16px 是单行上限而非目标值）
#   底部一行   16px 常规 字距  0  → advance 569（左右各余约 44）；极限是 18px（640），19px 起 675 会折行
# 榜单标题按用户要求取**与底部一行同一规格**（微软雅黑 16px 常规 字距 0，非粗体），故两行
# 的 ``QFont`` 四要素（family/pixelSize/weight/letterSpacing）逐项相等；标题含「Top10」的
# 字母 p 有降部，墨迹高 17.6 比纯汉字的底部一行 16.8 略高，属字形差异而非字号差异：
#   榜单标题   16px → advance 95、底色块宽 99、左缘 框左+12、右缘 框左+111（框宽 309，充裕）
# 说明行按参考图取**非粗体**。标题底色块宽 = horizontalAdvance + _RANK_TITLE_PAD_R，
# 16px 下右缘落在框左 +111（参考图 14px 时为 +99、参考图实测 ~+118），上边线截断效果不变：
# 框左..框左+12 与 框左+111..框右 两段可见，字与线不重叠。
# 雅黑的常见度量与「Microsoft YaHei UI」完全一致，两者可互换。实测墨迹（``grab()`` 821×796
# 设备像素，125% DPI，逐像素判 min(R,G,B)<=140）：灰色小字 683×19 → 逻辑 546.4×15.2、
# 每字宽 14.01、左右留白各 55.2 且行内无空断（确为单行），行高 19 ≤ _HINT_H(28)。
_FONT = "Microsoft YaHei"
_FONT_SPECS = {
    "intro": (19, False, 2),
    "hint": (14, False, 0),
    "rank_title": (16, False, 0),
    "row": (13, False, 0),
    "footer": (16, False, 0),
}
_FS_ROW = _FONT_SPECS["row"][0]  # 表格 QSS 里要用

# ------------------------------------------------------------------ 配色
# 参考图取色（按 min(R,G,B) <= 100 取核心笔画像素，避开 ClearType 色边）
_REF_BG = "#F0F0F0"  # 客户区底色（Windows 默认窗口灰）
_REF_FG = "#000000"  # 说明行/榜单标题最暗像素 (0,1,1)
_REF_HINT = "#4A4A4A"  # 小字核心笔画 min 通道均值 83 / p5=71
_REF_BORDER = "#DCDCDC"  # 榜单框边框 #DCDCDC~#E4E4E4
_REF_CARD = "#FFFFFF"  # 收款码纯白方块

_INTRO_TEXT = "软件是免费的，欢迎捐助： 1.微信支付 2.支付宝付款 3.支付宝红包"
_HINT_TEXT = "您的支持是我最大的动力，捐助是自愿的，表示对本软件的支持，并没有提供额外的功能"
_FOOTER_TEXT = "官方交流群：把酒问青天[1108931283]-密码[MDCx]，进群后必须遵守法律法规"

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
        # 顶部说明（居中，非粗体——参考图正文无粗体）
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

        # 三张收款码：纯白方块，无边框、无标题文字（照抄参考图）
        # 顺序即 _INTRO_TEXT 里的 1.微信支付 2.支付宝付款 3.拿支付宝红包
        for i, image in enumerate(self._donate_icons()):
            self._build_card(_CARD_X + i * (_CARD_W + _CARD_GAP), _CARD_Y, image)

        # 两个榜单框
        self._build_rank(_RANK_LEFT_X, _RANK_TITLES[0])
        self._build_rank(_RANK_LEFT_X + _RANK_W + _RANK_GAP, _RANK_TITLES[1])

        fs_px, fs_bold, fs_sp = _FONT_SPECS["footer"][:3]
        # 底部一行（居中）
        self._label(
            _FOOTER_TEXT, 0, _FOOTER_Y, _DIALOG_W, _FOOTER_H, fs_px, self._c["fg"],
            fs_bold, True, fs_sp,
        )

    @staticmethod
    def _donate_icons() -> tuple[str, ...]:
        """三张收款码的资源路径，顺序与 ``_INTRO_TEXT`` 的 1/2/3 一致。

        刻意用 ``getattr(..., "")`` 而不是直接取属性：旧版资源对象与测试替身
        （``tests/conftest.py`` 的 ``_DummyResources``）可能还没有第三个属性，缺图时
        ``_build_card`` 会显示「二维码加载失败」占位而不是抛异常——卡片槽位数恒为
        ``_CARD_COUNT``，后面几张码不会因为前面某张缺图而整体错位。
        """
        names = ("donate_wechat_icon", "donate_alipay_icon", "donate_redpacket_icon")
        return tuple(getattr(resources, name, "") or "" for name in names)

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