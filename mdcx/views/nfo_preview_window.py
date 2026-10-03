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

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
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


# 任务栏 AppUserModelID 读写用的 COM 结构与常量（仅定义类型，不做系统调用）。
# 同一块 GUID 定义被 Set/Get 共用，提在模块级避免重复定义。
if sys.platform == "win32":
    import ctypes as _ctypes_win
    from ctypes import wintypes as _wintypes_win

    class _AppIdGUID(_ctypes_win.Structure):
        _fields_ = [
            ("Data1", _wintypes_win.DWORD),
            ("Data2", _wintypes_win.WORD),
            ("Data3", _wintypes_win.WORD),
            ("Data4", _wintypes_win.BYTE * 8),
        ]

    class _AppIdPropertyKey(_ctypes_win.Structure):
        _fields_ = [("fmtid", _AppIdGUID), ("pid", _wintypes_win.DWORD)]

    _APP_ID_STORE_IID = _AppIdGUID(
        0x886D8EEB,
        0x8CF2,
        0x4446,
        (_wintypes_win.BYTE * 8)(0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99),
    )  # IID_IPropertyStore
    _APP_ID_PKEY = _AppIdPropertyKey(
        _AppIdGUID(
            0x9F4C2855,
            0x9F79,
            0x4B39,
            (_wintypes_win.BYTE * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3),
        ),
        5,  # PKEY_AppUserModel_ID
    )
else:
    _ctypes_win = None  # type: ignore[assignment]
    _wintypes_win = None  # type: ignore[assignment]
    _APP_ID_STORE_IID = None
    _APP_ID_PKEY = None


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
        # 独立顶层窗口（不挂 owner）：任务栏常驻自己的按钮与实时缩略图，
        # 点缩略图切换窗口全由系统原生支持。
        super().__init__(None)
        # 几何与状态跟随的主窗口：只读引用，不做 QObject 父子（传给 show_matching 用）。
        self._main = parent
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
        # 关掉本窗口不得退出整个应用：主窗口收进托盘后本窗口是最后一扇可见窗口，
        # 默认 WA_QuitOnClose 会触发 app 退出，看起来像连带关了主窗口。
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        try:
            # 任务栏按钮与 Alt+Tab 用跟主窗口相同的 MDCx 图标
            from mdcx.config.resources import resources

            self.setWindowIcon(QIcon(resources.icon_ico))
        except Exception:
            pass
        # 独立的任务栏 AppUserModelID：同进程窗口默认会被系统合并成一个按钮，
        # 预览必须跟主窗口分成左右两个图标，各自点各自隐藏显示。
        self._set_taskbar_app_id("MDCx.NfoPreview")

        # 番号清单：与图片组一一对应的 NFO 路径，供外部把下标映射回列表选中项
        self.nfo_paths: list[Path] = []
        # 每个番号对应的图片（按 core/nfo.py 的顺序：先封面，后缩略图）
        self.images: list[list[Path]] = []
        # 标题前缀（如「封面预览」），show_entries 时不会覆盖，切图时仍生效
        self.title_prefix = "图片预览"
        # 主窗口最小化时预览是否最大化：任务栏整组还原后 OS 可能把预览落回普通态，
        # 靠它重新最大化（见 eventFilter）。False = 无需恢复。
        self._max_before_parent_minimized = False
        # 最小化过的标记：从最小化还原出来时重新严丝合缝盖住主窗口（见 changeEvent）。
        self._was_minimized = False
        # 最小化那一刻是否最大化：还原时恢复最大化（最小化不丢最大化，原生语义）。
        self._was_maximized = False
        # 主窗口还在最小化、盖住动作做不了时先挂起，主窗口回来再执行。
        self._cover_pending = False
        # show_matching 主动摆位置期间忽略 changeEvent 的盖住钩子（防重入）。
        self._placing = False
        if parent is not None:
            parent.installEventFilter(self)
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
        最大化状态先把普通几何钉到主窗口还原尺寸（主窗口启动时的大小）再
        showMaximized()，两者都会铺满同一块屏幕，还原下来正好是启动大小，
        不会缩成布局最小尺寸；最小化同理先钉好普通几何再 showMinimized()。

        Windows 上不能在可见的最大化窗口上直接 setGeometry（还原矩形会被
        写坏，表现为标题栏中间的还原按钮点了没反应），所以几何只在普通态
        下写，且普通态→最大化之间 pump 一次事件，让原生窗口先落稳在普通
        态再最大化；已是最大化时若还原矩形过小或与主窗口还原尺寸不一致才修
        （不一致多因复用窗口：上次最大化态关闭不重置 windowState，下次隐藏
        态直接 setGeometry 写不进还原矩形；或主窗口还原尺寸已变而预览留旧值），
        一致时不动，避免每次点图都闪一下。

        本次是主动摆位置，不触发还原后的盖住钩子（见 changeEvent）。
        """
        from PyQt6.QtWidgets import QApplication

        self._was_minimized = False
        self._was_maximized = False
        self._cover_pending = False
        self._max_before_parent_minimized = False
        self._placing = True
        try:
            self._place_matching(parent, QApplication)
        finally:
            self._placing = False

    def _place_matching(self, parent: QWidget, QApplication) -> None:
        """show_matching 的实际摆位逻辑（调用方负责 _placing 标记）。"""
        if parent.isMinimized():
            desired = self._normal_geometry_for(parent)
            if not self.isVisible():
                # 隐藏态可能还残留着上次最大化/最小化的 state（Esc/× 关闭不重置
                # windowState）：带着 Maximized 做 setGeometry 写不进还原矩形，
                # 下次点还原按钮就会缩到旧尺寸/极小尺寸。先落回普通态再写。
                if self.isMaximized() or self.isMinimized():
                    self.setWindowState(Qt.WindowState.WindowNoState)
                self.setGeometry(desired)
            elif (not self.isMinimized()) and (
                self._restore_rect_too_small() or self._restore_rect_mismatch(desired)
            ):
                self.showNormal()
                QApplication.processEvents()
                self.setGeometry(desired)
                QApplication.processEvents()
            self.showMinimized()
            return
        if parent.isMaximized():
            desired = self._normal_geometry_for(parent)
            if not self.isVisible():
                # 同上：隐藏的最大化态下直接 setGeometry 写不进还原矩形，
                # 表现为「还原按钮不能正常缩小到主页面大小」（时好时坏：
                # 上次关闭时是最大化态就坏，是普通态就好）。
                if self.isMaximized() or self.isMinimized():
                    self.setWindowState(Qt.WindowState.WindowNoState)
                self.setGeometry(desired)
                self.showMaximized()
            elif not self.isMaximized():
                self.showNormal()
                QApplication.processEvents()
                self.setGeometry(desired)
                QApplication.processEvents()
                self.showMaximized()
            elif self._restore_rect_too_small() or self._restore_rect_mismatch(desired):
                # 已最大化但还原矩形是历史残留（过小，或主窗口还原尺寸已变
                # 而预览还留着旧值）：还原→钉好→再最大化修一次。不一致才修，
                # 避免每次点图都闪一下。
                self.showNormal()
                QApplication.processEvents()
                self.setGeometry(desired)
                QApplication.processEvents()
                self.showMaximized()
        else:
            # 先显示再摆位置：显示前就撑满屏幕会被系统判成最大化
            self.showNormal()
            self.setGeometry(parent.geometry())
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _window_property_store(hwnd: int):
        """取窗口的 IPropertyStore（(store, vtable8)，失败返回 (None, None)）。

        COM 接口指针指向对象，对象首字段才是指向虚表的指针：
        先解一层拿到虚表地址，再按索引取函数，少一层就是访问违例。
        调用方负责 release(store)。仅 Windows，失败一律吞掉。
        """
        if sys.platform != "win32" or not hwnd:
            return None, None
        try:
            import ctypes
            from ctypes import wintypes

            shell32 = ctypes.windll.shell32
            # 注意：windll 函数默认按 int 传参/返回值，64 位下指针会被截断，
            # 必须显式声明签名，否则就是访问违例（已有血案）。
            shell32.SHGetPropertyStoreForWindow.argtypes = [
                wintypes.HWND,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            shell32.SHGetPropertyStoreForWindow.restype = ctypes.HRESULT
            store = ctypes.c_void_p()
            hr = shell32.SHGetPropertyStoreForWindow(
                wintypes.HWND(hwnd), ctypes.byref(_APP_ID_STORE_IID), ctypes.byref(store)
            )
            if hr != 0 or not store:
                return None, None
            vtable_addr = ctypes.c_void_p.from_address(store.value).value
            if not vtable_addr:
                NfoPreviewWindow._release_store(store)
                return None, None
            return store, (ctypes.c_void_p * 8).from_address(vtable_addr)
        except Exception:
            return None, None

    @staticmethod
    def _release_store(store) -> None:
        """释放 IPropertyStore（失败吞掉）。"""
        try:
            import ctypes

            vtable_addr = ctypes.c_void_p.from_address(store.value).value
            vtable = (ctypes.c_void_p * 8).from_address(vtable_addr)
            release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
            release(store)
        except Exception:
            pass

    def _set_taskbar_app_id(self, app_id: str) -> None:
        """给本窗口设置独立的任务栏 AppUserModelID（仅 Windows）。

        同进程窗口默认共用一个 AppUserModelID，任务栏会合并成一个按钮
        （悬停缩略图叠在一起不好点）；预览用独立 ID 后跟主窗口分成左右
        两个图标，各自点各自最小化/还原。失败一律吞掉，不影响功能。
        必须在窗口首次显示前调用，且之后不再改标记/父子关系（HWND 稳定）。
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = int(self.winId())
            if not hwnd:
                return
            store, vtable = NfoPreviewWindow._window_property_store(hwnd)
            if store is None or vtable is None:
                return
            try:
                func_type = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
                set_value = func_type(vtable[6])  # IPropertyStore::SetValue
                # PROPVARIANT(VT_LPWSTR=31)：24 字节清零，0 处写 vt，8 处写字符串指针；
                # SetValue 会自己拷贝字符串，这里泄漏几十字节一次，无需清理。
                prop = (ctypes.c_byte * 24)()
                ctypes.cast(prop, ctypes.POINTER(wintypes.USHORT)).contents.value = 31
                text = ctypes.create_unicode_buffer(app_id)
                ctypes.cast(
                    ctypes.addressof(prop) + 8, ctypes.POINTER(ctypes.c_void_p)
                ).contents.value = ctypes.addressof(text)
                if set_value(store, ctypes.byref(_APP_ID_PKEY), ctypes.byref(prop)) == 0:
                    commit = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)(vtable[7])
                    commit(store)
            finally:
                NfoPreviewWindow._release_store(store)
        except Exception:
            pass

    @staticmethod
    def _read_app_id_for_widget(widget: QWidget) -> str | None:
        """读任意窗口的任务栏 AppUserModelID（回归测试用，主窗口应与预览不同）"""
        if sys.platform != "win32":
            return None
        value = None
        ptr = 0
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = int(widget.winId())
            if not hwnd:
                return None
            store, vtable = NfoPreviewWindow._window_property_store(hwnd)
            if store is None or vtable is None:
                return None
            try:
                func_type = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
                get_value = func_type(vtable[5])  # IPropertyStore::GetValue
                prop = (ctypes.c_byte * 24)()
                if get_value(store, ctypes.byref(_APP_ID_PKEY), ctypes.byref(prop)) != 0:
                    return None
                if ctypes.cast(prop, ctypes.POINTER(wintypes.USHORT)).contents.value != 31:
                    return None
                ptr = ctypes.cast(ctypes.addressof(prop) + 8, ctypes.POINTER(ctypes.c_void_p)).contents.value
                value = ctypes.wstring_at(ptr) if ptr else None
            finally:
                NfoPreviewWindow._release_store(store)
        except Exception:
            return None
        if ptr:
            try:
                import ctypes

                ole32 = ctypes.windll.ole32
                ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
                ole32.CoTaskMemFree.restype = None
                ole32.CoTaskMemFree(ctypes.c_void_p(ptr))
            except Exception:
                pass
        return value

    def _read_taskbar_app_id(self) -> str | None:
        """读回本窗口的任务栏 AppUserModelID（仅 Windows，失败/无值返回 None）。

        给回归测试与 showEvent 补齐用：读不到期望值就说明属性丢了。
        """
        return NfoPreviewWindow._read_app_id_for_widget(self)

    def _ensure_taskbar_app_id(self) -> None:
        """显示时补齐 AppID：读回不对就重设（防 HWND 重建/属性丢失导致合回一组）"""
        try:
            if self._read_taskbar_app_id() != "MDCx.NfoPreview":
                self._set_taskbar_app_id("MDCx.NfoPreview")
        except Exception:
            pass

    def _restore_rect_too_small(self) -> bool:
        """还原矩形是否过小（历史版本 showMaximized 前没钉几何的残留）。"""
        try:
            normal = self.normalGeometry()
        except Exception:
            return True
        return not (normal.isValid() and normal.width() >= 360 and normal.height() >= 240)

    def _restore_rect_mismatch(self, desired) -> bool:
        """还原矩形是否与期望不一致（主窗口还原尺寸已变而预览还留着旧值）。

        frame 边框取整可能差 1px，用 2px 容差比对，避免每次点图都触发
        还原→钉好→再最大化的闪一下；差得再大就必须修，否则还原按钮会
        缩到旧位置/旧大小，看起来像「不能正常缩小到主页面大小」。
        """
        try:
            cur = self.normalGeometry()
        except Exception:
            return True
        try:
            if cur is None or desired is None or not cur.isValid() or not desired.isValid():
                return True
            return (
                abs(cur.x() - desired.x()) > 2
                or abs(cur.y() - desired.y()) > 2
                or abs(cur.width() - desired.width()) > 2
                or abs(cur.height() - desired.height()) > 2
            )
        except Exception:
            return True

    @staticmethod
    def _normal_geometry_for(parent: QWidget):
        """弹窗还原时应回到的普通几何：主窗口还原尺寸，即启动时的大小。"""
        from PyQt6.QtCore import QRect
        from PyQt6.QtWidgets import QApplication

        normal = None
        try:
            normal = parent.normalGeometry()
        except Exception:
            normal = None
        if normal is not None and normal.isValid() and normal.width() >= 360 and normal.height() >= 240:
            return normal
        screen = parent.screen() if hasattr(parent, "screen") else None
        if screen is None:
            screen = QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else None
        width, height = 1030, 700
        if avail is not None and avail.isValid():
            width = min(width, avail.width())
            height = min(height, avail.height())
            x = avail.x() + max(0, (avail.width() - width) // 2)
            y = avail.y() + max(0, (avail.height() - height) // 2)
            return QRect(x, y, width, height)
        geo = parent.geometry()
        x = geo.x() + max(0, (geo.width() - width) // 2)
        y = geo.y() + max(0, (geo.height() - height) // 2)
        return QRect(x, y, width, height)

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
        """图片下方的提示行：信息与键位图标作为一组整行居中（最大化/普通态一致）。"""
        bar = QWidget(self)
        bar.setObjectName("widget_nfo_lib_preview_hint")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addStretch(1)

        self.info_label = QLabel(bar)
        self.info_label.setObjectName("label_nfo_lib_preview_info")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info_label.setMinimumWidth(1)  # 允许整行压缩，别把弹窗最小宽度顶大
        row.addWidget(self.info_label, 0)

        for first, second, text in _KEY_HINTS:
            if first:
                row.addWidget(self._make_key_cap(first))
            if second:
                row.addWidget(self._make_key_cap(second))
            row.addWidget(self._make_hint_text(text))
            row.addSpacing(12)
        row.addStretch(1)
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

    def _current_nfo_stem(self) -> str:
        """当前番号（NFO 文件名去后缀），用于通用 poster.jpg/thumb.jpg 的显示名补前缀。"""
        if 0 <= self._nfo_index < len(self.nfo_paths):
            return self.nfo_paths[self._nfo_index].stem
        return ""

    def _display_name(self, path: Path | None) -> str:
        """用于标题栏与底部信息的显示文件名。

        NFO 同目录图片有两种命名：专属名（如 ABP-608-poster.jpg）与通用名
        （poster.jpg / thumb.jpg）。通用名看不出是哪个番号，显示时补上
        番号前缀（ABP-608-poster.jpg）；专属名保持原样，避免重复拼接。
        """
        if path is None:
            return ""
        name = path.name
        if name.lower() in ("poster.jpg", "thumb.jpg"):
            stem = self._current_nfo_stem()
            if stem and not name.lower().startswith(stem.lower()):
                return f"{stem}-{name}"
        return name

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
            f"图片 {self._image_index + 1}/{len(self._current_images())}　{self._display_name(path)}{size_text}"
            f"　番号 {self._nfo_index + 1}/{len(self.nfo_paths)}"
        )

    def _update_title(self) -> None:
        path = self.current_path()
        self.setWindowTitle(f"{self.title_prefix} - {self._display_name(path)}" if path else self.title_prefix)

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
        # 每次显示都保证任务栏 AppID 在位（防 HWND 重建/属性丢失合回一组）
        self._ensure_taskbar_app_id()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowStateChange:
            return
        # 从最小化还原出来：最大化恢复最大化，普通态重新严丝合缝盖住主窗口
        # （任务栏整组还原不再叠偏）。show_matching 主动摆位置时跳过
        # （它自己负责几何，_placing 防重入）。
        if self.isMinimized():
            self._was_minimized = True
            # 最小化那一刻是否最大化：从 oldState 取（当前态已翻成最小化），
            # 还原时恢复最大化用（最小化不丢最大化，原生语义）。
            try:
                old_state = event.oldState()
                self._was_maximized = bool(old_state & Qt.WindowState.WindowMaximized)
            except Exception:
                self._was_maximized = False
            return
        if not self._was_minimized or self._placing or not self.isVisible():
            return
        main = self._main
        if main is not None and main.isMinimized():
            self._cover_pending = True  # 主窗口还没回来，回来再盖（标记留着）
        else:
            self._was_minimized = False
            self._enforce_cover(main)

    def _enforce_cover(self, main: QWidget | None) -> None:
        """还原后严丝合缝盖住主窗口：最大化态铺满同一块屏幕，普通态重合几何。

        最小化前是最大化的恢复最大化（最小化不丢最大化）；普通主窗口上的
        最大化预览已算盖住，不动；不抢焦点，前台归属由任务栏还原决定。
        主窗口还在最小化时挂起，不硬盖。
        """
        if main is None or main.isMinimized():
            self._cover_pending = True
            return
        self._placing = True
        try:
            if main.isMaximized() or self._was_maximized:
                desired = self._normal_geometry_for(main)
                if self.isMaximized():
                    if self._restore_rect_too_small() or self._restore_rect_mismatch(desired):
                        from PyQt6.QtWidgets import QApplication

                        self.showNormal()
                        QApplication.processEvents()
                        self.setGeometry(desired)
                        QApplication.processEvents()
                        self.showMaximized()
                else:
                    from PyQt6.QtWidgets import QApplication

                    self.showNormal()
                    QApplication.processEvents()
                    self.setGeometry(desired)
                    QApplication.processEvents()
                    self.showMaximized()
            elif not self.isMaximized():
                self.showNormal()
                self.setGeometry(main.geometry())
        finally:
            self._placing = False
            self._was_minimized = False
            self._was_maximized = False

    def eventFilter(self, a0, a1) -> bool:
        # 主窗口任务栏最小化/还原整组窗口时跟随：最小化那一刻记下预览是否最大化，
        # 主窗口还原后若预览被 OS 落回普通态则重新最大化；挂起的盖住动作在这里执行。
        # 用户手动点的还原按钮不受影响（只在盖住钩子与快照逻辑里动手脚）。
        if a0 is self._main and a1.type() == QEvent.Type.WindowStateChange:
            try:
                if a0.isMinimized():
                    self._max_before_parent_minimized = self.isMaximized()
                elif self._max_before_parent_minimized:
                    if self.isMaximized():
                        # OS 保住了最大化：无事可做，两个标记都清掉
                        self._max_before_parent_minimized = False
                        self._cover_pending = False
                    else:
                        # 标记留给 _restore_after_parent_restore 消费（它负责清掉）；
                        # 这里只排 timer，让 OS 先完成整组窗口的恢复。
                        QTimer.singleShot(0, self._restore_after_parent_restore)
                        QTimer.singleShot(250, self._restore_after_parent_restore)
                elif self._cover_pending and self.isVisible() and not self.isMinimized() and not self._placing:
                    self._cover_pending = False
                    self._enforce_cover(a0)
            except Exception:
                pass
        return super().eventFilter(a0, a1)

    def _restore_after_parent_restore(self) -> None:
        """主窗口还原后补救：预览本应最大化却被落回普通态时重新最大化。"""
        if not self._max_before_parent_minimized:
            return
        if self.isMinimized() or not self.isVisible():
            # 预览还没被 OS 恢复（或用户收了起来）：留给下一拍 timer 再试
            return
        if not self.isMaximized():
            self.showMaximized()
        self._max_before_parent_minimized = False
        self._cover_pending = False  # 最大化即盖住，不必再盖一次

    def closeEvent(self, event) -> None:
        # 用户主动关闭（Esc/×）：清掉还原钩子的标记
        self._was_minimized = False
        self._was_maximized = False
        self._cover_pending = False
        self._max_before_parent_minimized = False
        super().closeEvent(event)
