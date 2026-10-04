"""赞助对话框：展示微信/支付宝收款码与赞助榜单（版式复刻自参考截图）。

侧栏「使用说明」按钮下方的 ``[赞助作者]`` 链接点击后弹出本窗口。

版式（657×677，与参考截图一致）：
    标题栏 → 加粗说明 → 灰色小字 → 两张收款码卡片 → 新人榜/土豪榜 → 底部说明
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config.resources import resources
from ..controllers.main_window.style import get_theme_tokens

# 设计尺寸（参考截图 657×677）
_DIALOG_W = 657
_DIALOG_H = 677
_CARD_W = 196
_CARD_H = 205
_QR_SIZE = 168
_RANK_ROWS = 10
_RANK_COLS = 3

_INTRO_TEXT = "软件是免费的，欢迎捐助： 1.微信支付 2.支付宝付款 3.拿支付宝红包"
_HINT_TEXT = "您的支持是我最大的动力，捐助是自愿的，表示对本软件的支持，并没有提供额外的功能"
_FOOTER_TEXT = "欢迎加入 MDCx 官方交流群一起交流使用经验，反馈问题与建议"


class DonateDialog(QDialog):
    """赞助窗口：收款码 + 赞助榜单。"""

    def __init__(self, parent=None, dark: bool = False) -> None:
        super().__init__(parent)
        self._dark = bool(getattr(parent, "dark_mode", dark))
        self.setWindowTitle("赞助")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.resize(_DIALOG_W, _DIALOG_H)
        self.setMinimumSize(_DIALOG_W, _DIALOG_H)
        self.setMaximumSize(_DIALOG_W, _DIALOG_H)
        self._build_ui()
        self._style_dialog()

    # ------------------------------------------------------------------ 构建

    def _build_ui(self) -> None:
        colors = get_theme_tokens(self._dark)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 8)
        outer.setSpacing(6)

        # 说明（加粗）
        intro = QLabel(_INTRO_TEXT)
        intro.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intro.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {colors['text']};")
        outer.addWidget(intro)

        # 小字说明（灰色）
        hint = QLabel(_HINT_TEXT)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 12px; color: {colors['text_muted']};")
        outer.addWidget(hint)

        # 收款码卡片（微信 + 支付宝）
        cards = QHBoxLayout()
        cards.setContentsMargins(0, 4, 0, 0)
        cards.setSpacing(24)
        cards.addStretch(1)
        cards.addWidget(self._build_card("微信支付", resources.donate_wechat_icon))
        cards.addWidget(self._build_card("支付宝付款", resources.donate_alipay_icon))
        cards.addStretch(1)
        outer.addLayout(cards, 1)

        # 榜单：新人榜 Top10 / 土豪榜 Top10
        ranks = QHBoxLayout()
        ranks.setContentsMargins(0, 0, 0, 0)
        ranks.setSpacing(14)
        ranks.addWidget(self._build_rank("新人榜Top10"), 1)
        ranks.addWidget(self._build_rank("土豪榜Top10"), 1)
        outer.addLayout(ranks, 1)

        # 底部说明
        footer = QLabel(_FOOTER_TEXT)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setWordWrap(True)
        footer.setStyleSheet(f"font-size: 12px; color: {colors['text_muted']};")
        outer.addWidget(footer)

    def _build_card(self, title: str, image_path: str) -> QWidget:
        """一张「标题 + 二维码」的收款卡片。"""
        colors = get_theme_tokens(self._dark)
        card = QFrame()
        card.setFixedSize(_CARD_W, _CARD_H)
        card.setStyleSheet(
            f"QFrame#donate_card {{"
            f"background: {colors['window']};"
            f"border: 1px solid {colors['border']};"
            f"border-radius: 4px;"
            f"}}"
        )
        card.setObjectName("donate_card")

        box = QVBoxLayout(card)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(4)

        name = QLabel(title)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {colors['text']};")
        box.addWidget(name)

        qr = QLabel()
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr.setFixedSize(_QR_SIZE, _QR_SIZE)
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            qr.setText("二维码加载失败")
            qr.setStyleSheet(f"font-size: 12px; color: {colors['text_muted']};")
        else:
            qr.setPixmap(
                pixmap.scaled(
                    _QR_SIZE,
                    _QR_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        box.addWidget(qr, 1)
        return card

    def _build_rank(self, title: str) -> QWidget:
        """一个榜单区块：标题 + 10 行 3 列（用户名/日期时间/金额）。"""
        colors = get_theme_tokens(self._dark)
        holder = QWidget()
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)

        head = QLabel(title)
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {colors['text']};")
        box.addWidget(head)

        table = QTableWidget(_RANK_ROWS, _RANK_COLS)
        # 参考截图中榜单无表头行：表头整体隐藏，10 行全是数据行
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # 用户名左对齐 / 日期时间居中 / 金额右对齐（与参考截图列内落位一致）
        aligns = (
            Qt.AlignmentFlag.AlignLeft,
            Qt.AlignmentFlag.AlignCenter,
            Qt.AlignmentFlag.AlignRight,
        )
        for row in range(_RANK_ROWS):
            for col in range(_RANK_COLS):
                item = QTableWidgetItem("")
                item.setTextAlignment(aligns[col])
                table.setItem(row, col, item)
        table.setStyleSheet(
            f"QTableWidget {{"
            f"background: {colors['window']};"
            f"color: {colors['text']};"
            f"gridline-color: {colors['border']};"
            f"border: 1px solid {colors['border']};"
            f"font-size: 12px;"
            f"}}"
            f"QTableWidget::item {{ padding: 2px 4px; }}"
        )
        box.addWidget(table, 1)
        return holder

    # ------------------------------------------------------------------ 样式

    def _style_dialog(self) -> None:
        colors = get_theme_tokens(self._dark)
        self.setStyleSheet(
            f"QDialog {{ background: {colors['window']}; color: {colors['text']}; }}"
            f"QToolTip {{ background: {colors['surface']}; color: {colors['text']};"
            f"border: 1px solid {colors['border']}; }}"
        )
