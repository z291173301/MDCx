"""信息管理页右侧预览图的大图窗口。

主页面右侧只有「海报预览」(200x280) 和「缩略图预览」(200x120) 两个小框，
看不清细节。左键单击小框后用本窗口弹出大图：

- 窗口状态跟随主窗口：主窗口最大化则一起最大化，主窗口还原则正好盖在主窗口上
  （位置与尺寸都取主窗口当前值），保留系统标题栏的最小化/最大化/关闭按钮；
- ← / → 在同一个番号（同一条 NFO）内切换封面与缩略图；
- ↑ / ↓ 切换到上一个 / 下一个番号的封面与缩略图（尽量保持同类型）；
- Esc 关闭。

窗口本身不含业务逻辑：番号清单由 mdcx/controllers/main_window/nfo_library.py 组装，
番号切换时通过 nfo_index_changed 信号把新下标回传，由那边同步 NFO 列表选中项。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from mdcx.controllers.main_window.main_window import MyMAinWindow

# 无图片时图片区域的提示文字
_NO_IMAGE_TEXT = "无图片"

# 键位图标（用图标而不是「左右键」这类文字）
_KEY_HINTS: tuple[tuple[str, str, str], ...] = (
    ("←", "→", "相同番号图片"),
    ("↑", "↓", "不同番号图片"),
    ("Esc", "", "关闭"),
)


def _image_kind(path: Path | None) -> str:
    """按文件名判断图片类型（封面 / 缩略图），用于切番号后保持同类型。"""
    name = path.name.lower() if path is not None else ""
    if "poster" in name or "cover" in name:
        return "poster"
    if "thumb" in name:
        return "thumb"
    return ""


def _first_index_of_kind(images: list[Path], kind: str) -> int:
    """找出 images 里第一张指定类型的图片下标，没有则返回 0。"""
    if kind:
        for index, image in enumerate(images):
            if _image_kind(image) == kind:
                return index
    return 0


class NfoPreviewWindow(QDialog):
    """大图预览窗口：← → 换同一番号的封面/缩略图，↑ ↓ 换番号，Esc 关闭。"""

    # 当前番号下标变化（value = 切换后的番号下标），用于同步外部选中项
    nfo_index_changed = pyqtSignal(int)

    def __init__(self, parent: MyMAinWindow | QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("图片预览")
        # 摘掉工具窗/无边框标记，补上最小化与最大化按钮（关闭按钮由 QDialog 自带）
        flags = self.windowFlags() & ~(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setWindowFlags(
            flags
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setSizeGripEnabled(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setModal(False)

        # 番号清单：与图片组一一对应的 NFO 路径，供外部把下标映射回列表选中项
        self.nfo_paths: list[Path] = []
        # 每个番号对应的图片（按 core/nfo.py 的顺序：先封面，后缩略图）
        self.images: list[list[Path]] = []
        # 标题前缀（如「封面预览」），show_entries 时不会覆盖，切图时仍生效
        self.title_prefix = "图片预览"
        self._nfo_index = 0
        self._image_index = 0
        self._source: QPixmap | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.image_label = QLabel(self)
        self.image_label.setObjectName("label_nfo_lib_preview_image")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Ignored：让标签跟着窗口拉伸，图由 _render() 按标签实际尺寸等比缩放
        self.image_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image_label.setMinimumSize(240, 160)
        self.image_label.setText(_NO_IMAGE_TEXT)
        layout.addWidget(self.image_label, 1)
        layout.addWidget(self._build_hint_bar(), 0)
        self._update_info()

    # ============= 对外接口 =============

    def show_entries(
        self,
        entries: list[tuple[Path, list[Path]]],
        nfo_index: int = 0,
        image_index: int = 0,
    ) -> None:
        """载入番号清单并定位到 (nfo_index, image_index)。"""
        self.nfo_paths = [Path(nfo_path) for nfo_path, _ in entries]
        self.images = [[Path(image) for image in images] for _, images in entries]
        self._nfo_index = nfo_index if 0 <= nfo_index < len(self.nfo_paths) else 0
        images = self._current_images()
        self._image_index = max(0, min(image_index, len(images) - 1)) if images else 0
        self._load_current()
        self._update_info()
        self._update_title()

    def show_matching(self, parent: QWidget) -> None:
        """按主窗口当前的样子弹出：窗口状态跟随主窗口，位置与尺寸与主窗口重合。

        普通状态下 setGeometry(parent.geometry()) 让弹窗正好完全盖住主窗口；
        最大化状态直接 showMaximized()，两者都会铺满同一块屏幕。
        """
        self.setWindowState(self._plain_state())
        if parent.isMinimized():
            self.showMinimized()
            return
        if parent.isMaximized():
            self.showMaximized()
        else:
            # 先显示再摆位置：显示前就撑满屏幕会被系统判成最大化
            self.showNormal()
            self.setGeometry(parent.geometry())
        self.raise_()
        self.activateWindow()

    def current_nfo_index(self) -> int:
        """当前番号在番号清单中的下标（清单为空时为 -1）。"""
        return self._nfo_index if self.nfo_paths else -1

    def nfo_count(self) -> int:
        """番号清单长度。"""
        return len(self.nfo_paths)

    def image_count(self) -> int:
        """当前番号下的图片数量。"""
        return len(self._current_images())

    def current_image_index(self) -> int:
        """当前图片在同一番号内的下标（没有图片时为 -1）。"""
        return self._image_index if self.images else -1

    def current_path(self) -> Path | None:
        """当前显示的图片路径（无图片时为 None）。"""
        images = self._current_images()
        return images[self._image_index] if images else None

    def step_image(self, delta: int) -> None:
        """← / →：在同一番号内切换封面 / 缩略图（首尾循环）。"""
        images = self._current_images()
        if len(images) <= 1 or delta == 0:
            return
        self._image_index = (self._image_index + delta) % len(images)
        self._refresh_current()

    def step_nfo(self, delta: int) -> None:
        """↑ / ↓：切换到上一个 / 下一个番号，尽量显示同类型的图片。"""
        if len(self.nfo_paths) <= 1 or delta == 0:
            return
        kind = _image_kind(self.current_path())
        self._nfo_index = (self._nfo_index + delta) % len(self.nfo_paths)
        self._image_index = _first_index_of_kind(self._current_images(), kind)
        self._refresh_current()
        self.nfo_index_changed.emit(self._nfo_index)

    # ============= 内部实现 =============

    def _plain_state(self) -> Qt.WindowState:
        """摘掉最大化 / 最小化 / 全屏，只保留普通状态。"""
        return (
            self.windowState()
            & ~(Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized | Qt.WindowState.WindowFullScreen)
        ) | Qt.WindowState.WindowActive

    def _current_images(self) -> list[Path]:
        """当前番号的图片列表。"""
        if not self.images:
            return []
        return self.images[self._nfo_index] if 0 <= self._nfo_index < len(self.images) else []

    def _refresh_current(self) -> None:
        self._load_current()
        self._update_info()
        self._update_title()

    def _build_hint_bar(self) -> QWidget:
        """图片下方的提示行：左边图片信息，右边键位图标（图标而非文字说明按键）。"""
        bar = QWidget(self)
        bar.setObjectName("widget_nfo_lib_preview_hint")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        self.info_label = QLabel(bar)
        self.info_label.setObjectName("label_nfo_lib_preview_info")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info_label.setMinimumWidth(1)  # 允许整行压缩，别把弹窗最小宽度顶大
        row.addWidget(self.info_label, 1)

        for first, second, text in _KEY_HINTS:
            if first:
                row.addWidget(self._make_key_cap(first))
            if second:
                row.addWidget(self._make_key_cap(second))
            row.addWidget(self._make_hint_text(text))
            row.addSpacing(12)
        return bar

    @staticmethod
    def _make_key_cap(text: str) -> QLabel:
        """键位图标：带边框的小方块，用系统主题绘制，深浅色都跟随。"""
        cap = QLabel(text)
        cap.setObjectName("label_nfo_lib_preview_key")
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap.setFrameShape(QFrame.Shape.Box)
        cap.setFrameShadow(QFrame.Shadow.Sunken)
        cap.setFixedHeight(20)
        cap.setMinimumWidth(24)
        return cap

    @staticmethod
    def _make_hint_text(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("label_nfo_lib_preview_hint_text")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setMinimumWidth(1)  # 同上（0 会被当成没设，仍按文字宽度算最小值）
        return label

    def _load_current(self) -> None:
        path = self.current_path()
        pixmap = QPixmap(str(path)) if path is not None else QPixmap()
        if pixmap.isNull():
            self._source = None
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(_NO_IMAGE_TEXT)
            return
        self._source = pixmap
        self.image_label.setText("")
        self._render()

    def _render(self) -> None:
        """把原图等比缩放到图片区域实际尺寸后显示。"""
        if self._source is None or self._source.isNull():
            return
        target = self.image_label.size()
        if target.width() <= 0 or target.height() <= 0:
            return
        self.image_label.setPixmap(
            self._source.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _update_info(self) -> None:
        """底部信息：图片序号 / 文件名 / 尺寸 / 番号位置。"""
        path = self.current_path()
        if path is None:
            self.info_label.setText("无图片")
            return
        size_text = ""
        if self._source is not None and not self._source.isNull():
            size_text = f"（{self._source.width()}x{self._source.height()}）"
        self.info_label.setText(
            f"图片 {self._image_index + 1}/{len(self._current_images())}　{path.name}{size_text}"
            f"　番号 {self._nfo_index + 1}/{len(self.nfo_paths)}"
        )

    def _update_title(self) -> None:
        path = self.current_path()
        self.setWindowTitle(f"{self.title_prefix} - {path.name}" if path else self.title_prefix)

    # ============= 事件 =============

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Left:
            self.step_image(-1)
        elif key == Qt.Key.Key_Right:
            self.step_image(1)
        elif key == Qt.Key.Key_Up:
            self.step_nfo(-1)
        elif key == Qt.Key.Key_Down:
            self.step_nfo(1)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 图片区是 Ignored 策略，show 后才有实际尺寸，需要按新尺寸重绘一次
        self._render()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
