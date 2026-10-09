from __future__ import annotations

import asyncio
import concurrent.futures
import re
import threading
from pathlib import Path

from pydantic import HttpUrl
from PyQt6.QtCore import QEvent, Qt, QThread, QTimer
from PyQt6.QtCore import pyqtSignal as Signal
from PyQt6.QtGui import QColor, QGuiApplication, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config.manager import manager
from ..config.resources import resources
from ..models.emby import clean_overview_text, normalize_premiere_date, normalize_production_year
from ..utils import executor
from .emby_actor_manager import (
    ActorInfo,
    build_local_avatar_index,
    clean_actor_data_batch_async,
    fetch_actor_detail,
    fetch_actor_info_from_source,
    fetch_all_actors,
    from_gfriends,
    from_graphis,
    from_local_avatar,
    from_minnano_image,
    get_gfriends_index,
    get_media_folders,
    search_actor_info,
    sync_batch_async,
)

# 演员管理器（主窗 + 设置 / 数据源测试 / 演员详情 / 选择媒体库 等子窗口）整体字号放大一号。
# 走 QSS 而非 setFont：Qt 里样式表的 font-size 会覆盖控件字体，且样式表沿 QObject 父子链
# 级联——有父窗口的子对话框一并生效；设置/数据源测试是无父独立顶层窗口，各自再设一条
# 同值规则，保证三处字号一致——setFont 对顶层窗口不继承，只对子控件生效。
_FONT_SIZE_STEP = 1


def _ui_font_pt(step: int | None = None) -> str:
    """返回「应用默认字号 + step」的磅值文本，供 QSS `font-size` 使用。

    step 缺省取模块级 `_FONT_SIZE_STEP`（运行时读取，便于测试改档）。
    基准取 `QApplication.font()`，随系统/主界面字号浮动；应用若用像素字号
    （pointSize <= 0）按 96dpi 折算成磅值，两者都取不到时以 9pt 为基准。
    窗口标题栏文字（Emby/Jellyfin演员管理器 / Emby/Jellyfin 演员设置）由系统窗口框绘制，
    不受 QSS 影响，故不在本项放大范围内。
    """
    if step is None:
        step = _FONT_SIZE_STEP
    font = QApplication.font()
    pt = font.pointSizeF()
    if pt <= 0:
        px = font.pixelSize()
        pt = px * 72.0 / 96.0 if px > 0 else 9.0
    return f"{pt + step:g}pt"


def scan_actor_data_noise(actors: list[ActorInfo]) -> list[tuple[ActorInfo, str, bool]]:
    """议题 #149: 扫描需要清洗的演员——简介含历史噪声(清洗后有变化)或生日非法(0000-00-00 等)。

    返回 (actor, 清洗后简介, 是否重置生日) 三元组; 生日为 Emby 未设置零值 0001-01-01
    或可被 normalize_premiere_date 正常解析时不算噪声。
    """
    dirty: list[tuple[ActorInfo, str, bool]] = []
    for a in actors:
        new_overview = clean_overview_text(a.existing_overview)
        raw_birth = (a.existing_premiere_date or "").strip()
        fix_birth = (
            bool(raw_birth) and not raw_birth.startswith("0001-01-01") and normalize_premiere_date(raw_birth) is None
        )
        if new_overview != (a.existing_overview or "") or fix_birth:
            dirty.append((a, new_overview, fix_birth))
    return dirty


class LibrarySelectDialog(QDialog):
    # 议题 #146: 默认最小尺寸只够 ~7 行, 媒体库多时需滚动半屏。
    # 现按库数自适应初始大小(最多同时展示 20 行, 宽高 16:9, 不超过屏幕可用区 85%)。
    # 议题 #156: 行高由 item 显式 sizeHint 钉死为复选框高度, 并预留横向滚动条空间——
    # 此前行高靠估算、与实际渲染行高无确定关系, Windows 上 20 行预算只容得下 19 行。
    MAX_VISIBLE_ROWS = 20

    @staticmethod
    def initial_size(
        row_h: int, visible_rows: int, chrome_h: int, avail_w: int, avail_h: int, slack: int = 12
    ) -> tuple[int, int]:
        """计算对话框初始宽高: 高 = chrome + 可见行 + slack, 宽按 16:9, 双向钳制到屏幕可用区 85%。

        纯函数便于测试: chrome_h 为除列表可视区外的窗口内容高度(layout sizeHint 差值);
        slack 覆盖列表边框与可能出现的横向滚动条高度(议题 #156)。
        """
        target_h = chrome_h + visible_rows * row_h + slack
        # 整体向上缩进一行汉族的高度（约 20px）
        target_h = max(320, target_h - 20)
        target_w = int(round(target_h * 16 / 9))
        target_w = max(420, min(target_w, int(avail_w * 0.85)))
        target_h = max(320, min(target_h, int(avail_h * 0.85)))
        return target_w, target_h

    def __init__(self, libraries: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择媒体库")
        self.setMinimumWidth(420)
        self.setMinimumHeight(320)
        # 议题 #156: 合集(boxsets)是 Emby 自动创建的空壳库(无演员/标签), 默认不展示;
        # 极端情况下全部库都是合集时回退展示原始列表, 避免空对话框
        filtered = [lib for lib in libraries if (lib.get("CollectionType") or "") != "boxsets"]
        self._hidden_boxsets = len(libraries) - len(filtered)
        self._libraries = filtered or list(libraries)
        self._checkboxes: list[QCheckBox] = []
        self._init_ui()
        self._apply_initial_size()

    def _apply_initial_size(self):
        parent = self.parentWidget()
        screen_obj = parent.screen() if parent is not None else QGuiApplication.primaryScreen()
        available = screen_obj.availableGeometry()
        count = self.list_widget.count()
        # 议题 #156: 行高取 item 显式 sizeHint(在 _init_ui 中 setSizeHint 钉死), 不再估算
        row_h = self.list_widget.sizeHintForRow(0) if count else 26
        visible = max(1, min(count, self.MAX_VISIBLE_ROWS))
        chrome_h = max(0, self.layout().sizeHint().height() - self.list_widget.sizeHint().height())
        # 预留横向滚动条高度: 长库名触发横向滚动条时会吃掉约一行可视高度
        slack = 12 + self.list_widget.horizontalScrollBar().sizeHint().height()
        self.resize(*self.initial_size(row_h, visible, chrome_h, available.width(), available.height(), slack))

    def _init_ui(self):
        layout = QVBoxLayout(self)
        count = len(self._libraries)
        # 议题 #156: 隐藏合集库时在计数里明说, 避免"库数对不上"的疑惑
        hidden_note = f"，已隐藏 {self._hidden_boxsets} 个合集库" if self._hidden_boxsets else ""
        label = QLabel(f"选择要获取演员的媒体库（共 {count} 个{hidden_note}，默认全选）：")
        layout.addWidget(label)
        self.list_widget = QListWidget()
        for lib in self._libraries:
            name = lib.get("Name", "未知")
            ctype = lib.get("CollectionType", "")
            display = f"{name}  [{ctype}]" if ctype else name
            cb = QCheckBox(display)
            cb.setChecked(True)
            self._checkboxes.append(cb)
            item = QListWidgetItem()
            # 议题 #156: 行高钉死为复选框高度, 使 _apply_initial_size 的行数预算与实际渲染一致
            item.setSizeHint(cb.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, cb)
        layout.addWidget(self.list_widget)
        btn_layout = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("取消全选")
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        btn_layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        btn_layout.addWidget(buttons)
        layout.addLayout(btn_layout)

    def _set_all(self, checked: bool):
        for cb in self._checkboxes:
            cb.setChecked(checked)

    def get_selected_ids(self) -> list[str]:
        selected = []
        for i, cb in enumerate(self._checkboxes):
            if cb.isChecked() and i < len(self._libraries):
                selected.append(self._libraries[i].get("Id", ""))
        return selected


class _WorkerCancelled(Exception):
    """后台协程被关窗/停止取消，不向用户弹错误。"""


# 议题 #175: wait 超时后把仍在跑的 QThread 从窗口父级卸下，并保住 Python 引用，
# 避免 WA_DeleteOnClose 拆掉 C++ 线程对象导致整个进程 abort。
_ORPHAN_WORKER_THREADS: set[QThread] = set()


def _detach_running_thread(thread: QThread) -> None:
    thread.setParent(None)
    _ORPHAN_WORKER_THREADS.add(thread)

    def _drop(_checked: bool = False, *, _t=thread) -> None:
        _ORPHAN_WORKER_THREADS.discard(_t)
        _t.deleteLater()

    thread.finished.connect(_drop)


class _CancellableWorkerThread(QThread):
    """议题 #175: 关窗时必须能打断 executor 阻塞，否则 QThread 随父窗口销毁会 abort 主进程。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._future = None
        self._lock = threading.Lock()

    def cancel(self):
        self.abort()

    def abort(self):
        with self._lock:
            future = self._future
        if future is not None and not future.done():
            future.cancel()

    def _run_coro(self, coro):
        future = executor.submit(coro)
        with self._lock:
            self._future = future
        try:
            return future.result()
        except (concurrent.futures.CancelledError, asyncio.CancelledError) as e:
            raise _WorkerCancelled from e
        finally:
            with self._lock:
                self._future = None


class FetchActorsThread(_CancellableWorkerThread):
    progress = Signal(int, int, str)
    fetch_done = Signal(list, int)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.library_ids = None

    def run(self):
        try:
            actors, raw_count = self._run_coro(
                fetch_all_actors(
                    filter_actor_only=manager.config.actor_filter_only,
                    deduplicate=manager.config.actor_deduplicate,
                    parent_ids=self.library_ids,
                    progress_callback=lambda c, t, m: self.progress.emit(c, t, m),
                )
            )
            self.fetch_done.emit(actors, raw_count)
        except _WorkerCancelled:
            return
        except Exception as e:
            self.error.emit(str(e))


class PreparePreviewThread(_CancellableWorkerThread):
    progress = Signal(int, int, str)
    preview_done = Signal(list)
    error = Signal(str)

    _INFO_PLACEHOLDER = "无维基百科信息"

    @classmethod
    def _is_missing_image(cls, a: ActorInfo) -> bool:
        """是否缺头像: 服务器无 Primary 头像标签。"""
        return not a.has_image

    @classmethod
    def _is_missing_info(cls, a: ActorInfo) -> bool:
        """是否缺简介: 无简介, 或简介仅剩「无维基百科信息」占位文案。

        #147: 该判口径必须与「统计栏缺简介」保持一致——占位简介按缺处理,
        否则取数模式选中的数与统计栏分项对不上。
        """
        return not a.has_overview or cls._INFO_PLACEHOLDER in a.existing_overview

    @classmethod
    def select_targets(cls, actors: list[ActorInfo], mode: str) -> list[ActorInfo]:
        """议题 #127: 按获取模式筛出需要处理的演员子集, 避免无效人次的遍历与服务器的复核。

        - missing_image: 仅缺头像的演员
        - missing_info : 仅缺简介的演员（含简介只剩占位文案的情况）
        - missing_all  : 缺头像或缺简介的并集
        - missing_both : 缺头像且缺简介的交集（议题 #155，对应统计栏「全缺」）
        - force_*      : 用户显式选择「重新获取」, 不做筛选
        """
        if mode.startswith("force"):
            return list(actors)

        if mode == "missing_both":
            return [a for a in actors if cls._is_missing_image(a) and cls._is_missing_info(a)]

        want_image = mode in ("missing_all", "missing_image")
        want_info = mode in ("missing_all", "missing_info")

        return [
            a for a in actors if (want_image and cls._is_missing_image(a)) or (want_info and cls._is_missing_info(a))
        ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actors = []
        self.targets: list[ActorInfo] | None = None
        self.mode = "missing_all"
        self.gfriends_index = None
        self.cache_dir = resources.u("emby_actor_cache")
        self.image_sources = ["gfriends", "graphis", "minnano", "local"]
        self.local_avatar_dir = ""
        self._local_avatar_index: dict[str, str] | None = None
        self._cancel = False

    def cancel(self):
        # 「停止获取」只设标志，等当前演员收尾后预览结果仍回填；关窗走 abort() 打断阻塞。
        self._cancel = True

    def run(self):
        try:
            from .minnano_crawler import load_cache as minnano_load_cache

            minnano_load_cache()
            targets = self.targets if self.targets is not None else self.select_targets(self.actors, self.mode)
            total = len(targets)
            if total == 0:
                self.preview_done.emit(self.actors)
                return
            need_image = self.mode in ("missing_all", "missing_image", "missing_both", "force_all", "force_image")
            need_info = self.mode in (
                "missing_all",
                "missing_info",
                "missing_both",
                "force_all",
                "force_info",
                "force_overview",
            )
            force = "force" in self.mode
            cancelled = self._run_coro(self._process_all(targets, need_image, need_info, force, total))
            if not cancelled:
                self.progress.emit(total, total, "预览数据准备完成")
            self.preview_done.emit(self.actors)
        except _WorkerCancelled:
            return
        except Exception:
            import traceback

            self.error.emit(f"获取数据失败: {traceback.format_exc()}")

    async def _process_all(
        self, targets: list[ActorInfo], need_image: bool, need_info: bool, force: bool, total: int
    ) -> bool:
        """在单个 event loop 内并发处理所有演员，避免多线程多 loop 并发共享 async_client。"""
        if need_image and "local" in self.image_sources and self.local_avatar_dir:
            self.progress.emit(0, total, "扫描本地头像目录...")
            self._local_avatar_index = await asyncio.to_thread(build_local_avatar_index, self.local_avatar_dir)

        sem = asyncio.Semaphore(10)

        async def guarded(actor: ActorInfo) -> ActorInfo:
            async with sem:
                try:
                    if need_image:
                        await self._try_fetch_image(actor, force)
                    if need_info:
                        await self._try_fetch_info(actor, force)
                except Exception:
                    import traceback

                    from ..signals import signal

                    signal.show_log_text(f"🔶 演员处理异常: {actor.name}: {traceback.format_exc()}")
                return actor

        completed = 0
        cancelled = False
        tasks = [guarded(actor) for actor in targets]
        for coro in asyncio.as_completed(tasks):
            if self._cancel:
                cancelled = True
                break
            completed += 1
            actor = await coro
            self.progress.emit(completed, total, f"处理中: {actor.name} ({completed}/{total})")
        return cancelled

    async def _try_fetch_image(self, actor: ActorInfo, force: bool):
        if not force and actor.has_image:
            return
        graphis_attempted = False
        graphis_backdrop: str | None = None
        # 头像：按配置源顺序第一个命中即采用（保留用户设置优先级）
        for src in self.image_sources:
            if src == "graphis":
                graphis_attempted = True
                graphis_result = await from_graphis(actor, self.cache_dir)
                if isinstance(graphis_result, tuple) and graphis_result[0]:
                    actor.new_image_path = graphis_result[0]
                    actor.need_update_image = True
                    graphis_backdrop = graphis_result[1]
                    break
                continue
            result = await self._fetch_avatar_from(actor, src)
            if result:
                actor.new_image_path = result
                actor.need_update_image = True
                break
        # 背景图：头像命中不代表有背景（gfriends/local/minnano 均无背景），
        # 若仍缺背景，用 graphis 补——避免头像先命中导致背景永远无法补齐。
        # graphis 若已在头像循环尝试过，直接复用其结果，不重复请求。
        if not actor.has_backdrop and not actor.need_update_backdrop and "graphis" in self.image_sources:
            if graphis_backdrop:
                actor.new_backdrop_path = graphis_backdrop
                actor.need_update_backdrop = True
            elif not graphis_attempted:
                graphis_result = await from_graphis(actor, self.cache_dir)
                if isinstance(graphis_result, tuple) and graphis_result[1]:
                    actor.new_backdrop_path = graphis_result[1]
                    actor.need_update_backdrop = True

    async def _fetch_avatar_from(self, actor: ActorInfo, src: str) -> str | None:
        """从单个图源尝试获取头像路径；未命中返回 None。graphis 由 _try_fetch_image 特判处理。"""
        if src == "gfriends" and self.gfriends_index:
            return await from_gfriends(actor, self.gfriends_index, self.cache_dir)
        if src == "minnano":
            return await from_minnano_image(actor, self.cache_dir)
        if src == "local":
            return from_local_avatar(actor, self.local_avatar_dir, self._local_avatar_index)
        return None

    async def _try_fetch_info(self, actor: ActorInfo, force: bool):
        # 议题 #127: 简介缺失判定已由 select_targets 前置（列表阶段已带回 existing_overview，
        # 不再逐演员发 fetch_actor_detail 复核）；占位简介视为缺失需重新补全。
        if not force and actor.has_overview and self._INFO_PLACEHOLDER not in actor.existing_overview:
            return
        result = await search_actor_info(actor)
        if result:
            actor.need_update_info = True
        if getattr(self, "mode", "") == "force_overview":
            # 议题 #164: 「重新获取所有演员简介」只回写简介——清空其余 new_* 字段,
            # 同步出口(update_person_info)按真值逐字段写入, 出生日期/出生地/标签/
            # ProviderIds 均保持服务器原值; 简介没取到则不标记待同步。
            actor.new_taglines = []
            actor.new_production_year = None
            actor.new_premiere_date = ""
            actor.new_production_locations = []
            actor.new_provider_ids = {}
            actor.need_update_info = bool(actor.new_overview)


class SyncThread(_CancellableWorkerThread):
    progress = Signal(int, int, str)
    actor_done = Signal(str, str, bool, str)  # (actor_id, name, success, msg)
    sync_done = Signal(int, int)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actors = []

    def run(self):
        try:
            success, fail = self._run_coro(
                sync_batch_async(
                    self.actors,
                    progress_callback=lambda c, t, m: self.progress.emit(c, t, m),
                    actor_callback=lambda actor, ok, msg: self.actor_done.emit(actor.actor_id, actor.name, ok, msg),
                )
            )
            self.sync_done.emit(success, fail)
        except _WorkerCancelled:
            return
        except Exception as e:
            self.error.emit(str(e))


class CleanDataThread(_CancellableWorkerThread):
    """议题 #149: 存量数据清洗(简介噪声/非法生日), 不经取数流程。"""

    progress = Signal(int, int, str)
    # 议题 #162: actor_done 携带失败原因——此前 msg 在回调处被丢弃, 清洗失败只剩计数
    actor_done = Signal(str, bool, str)  # (actor_id, success, 结果消息)
    clean_done = Signal(int, int)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[tuple[ActorInfo, str, bool]] = []

    def run(self):
        try:
            success, fail = self._run_coro(
                clean_actor_data_batch_async(
                    self.items,
                    progress_callback=lambda c, t, m: self.progress.emit(c, t, m),
                    actor_callback=lambda actor, ok, msg: self.actor_done.emit(actor.actor_id, ok, msg),
                )
            )
            self.clean_done.emit(success, fail)
        except _WorkerCancelled:
            return
        except Exception as e:
            self.error.emit(str(e))


def _future_result_or(future, default):
    """取 Future 结果；协程异常时返回 default，避免异常传播到后台 loop 线程。"""
    try:
        return future.result()
    except Exception:
        return default


class EmbyActorManagerDialog(QDialog):
    _connect_result = Signal(object)
    _media_folders_result = Signal(object)
    _gfriends_result = Signal(object)

    def __init__(self, parent=None):
        # 不传 parent：始终保持独立顶层窗口。议题 #61——以主窗口为 parent 时，
        # 主窗口 hide 会级联隐藏 dialog，最大化 dialog 又会把主窗口带出。
        super().__init__(None)
        self.setWindowTitle("Emby/Jellyfin演员管理器")
        self.setMinimumSize(1100, 700)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 关闭时由 Qt 销毁 C++ 对象，主窗口侧的 destroyed 信号随之清空引用。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 初始落在最小尺寸上体验局促，默认取屏幕可用区 80%（离屏/无屏环境回退最小尺寸）
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.resize(max(1100, int(geo.width() * 0.8)), max(700, int(geo.height() * 0.8)))
        else:
            self.resize(1100, 700)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(self._load_stylesheet())
        self.cache_dir = resources.u("emby_actor_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._actors: list[ActorInfo] = []
        self._raw_count: int = 0
        # 议题 #143: 计数方式为持久化配置, 重开管理器/重启后恢复
        self._show_unique: bool = manager.config.actor_count_mode == 1
        self._gfriends_index = None
        self._preview_thread = None
        self._sync_thread = None
        self._clean_thread = None
        self._clean_items: dict[str, tuple[str, bool]] = {}
        self._clean_failed: list[tuple[str, str]] = []  # 议题 #162: (actor_id, 失败消息)
        self._fetch_thread = None
        self._refresh_thread = None
        # 独立子窗口单例引用（设置/数据源测试）：destroyed 信号负责清空
        self._settings_dialog = None
        self._test_dialog = None
        # 议题 #25: 任务会话代数——取消/重启任务后旧线程的排队回调整体作废
        self._session_gen = 0
        self._failed_names: set[str] = set()
        self._log_file: Path | None = None
        self._init_ui()
        self._connect_signals()
        self._open_log_file()

    def _begin_session(self, thread) -> None:
        """任务线程发起时颁发代数；与对话框当前值一致才允许写回 UI/状态。"""
        self._session_gen += 1
        thread._session_gen = self._session_gen

    def _is_stale_session(self) -> bool:
        """回调入口守卫：sender 携带的会话代数已过期则返回 True（调用方直接丢弃）。"""
        gen = getattr(self.sender(), "_session_gen", None)
        return gen is not None and gen != self._session_gen

    def _load_stylesheet(self) -> str:
        # 首条 QWidget 规则统一下发放大后的字号：写在最前且只含 font-size，
        # 下方各控件规则（QGroupBox 加粗 / 按钮配色等）仍照常合并生效。
        # 控件自身样式表里若再写死 font-size 会盖掉本规则（故提示文字只留颜色）。
        return f"""
        QWidget {{ font-size: {_ui_font_pt()}; }}
        QGroupBox {{ font-weight: bold; border: 1px solid #cccccc; border-radius: 4px; margin-top: 8px; padding-top: 14px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
        QTableWidget {{ gridline-color: #e0e0e0; selection-background-color: #bbdefb; }}
        QTableWidget::item:selected {{ background-color: #42a5f5; color: #ffffff; }}
        QPushButton#btnSync {{ background-color: #2e7d32; color: #ffffff; font-weight: bold; }}
        QPushButton#btnSync:hover {{ background-color: #388e3c; }}
        QPushButton#btnDanger {{ background-color: #c62828; color: #ffffff; }}
        QPushButton#btnDanger:hover {{ background-color: #d32f2f; }}
        QPushButton#btnPrimary {{ background-color: #1565c0; color: #ffffff; }}
        QPushButton#btnPrimary:hover {{ background-color: #1976d2; }}
        """

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(12, 12, 12, 12)
        self._build_connection_section(main_layout)
        splitter = QSplitter(Qt.Orientation.Vertical)
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        self._build_actor_list(list_layout)
        splitter.addWidget(list_widget)
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        self._build_log_section(log_layout)
        splitter.addWidget(log_widget)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter, 1)

        # 底部状态栏：当前状态 + Emby 连接状态
        self.status_bar = QStatusBar()
        self.status_bar.showMessage("未连接")
        main_layout.addWidget(self.status_bar)

    def _set_status(self, message: str):
        connected = hasattr(self, "_connected") and self._connected
        prefix = "已连接" if connected else "未连接"
        self.status_bar.showMessage(f"{prefix} | {message}")

    def _build_connection_section(self, parent_layout: QVBoxLayout):
        group = QGroupBox("Emby/Jellyfin 连接设置")
        grid = QGridLayout(group)
        grid.addWidget(QLabel("服务器地址:"), 0, 0)
        self.txt_url = QLineEdit(str(manager.config.emby_url or ""))
        self.txt_url.setPlaceholderText("http://192.168.1.100:8096")
        grid.addWidget(self.txt_url, 0, 1)
        grid.addWidget(QLabel("API 密钥:"), 0, 2)
        self.txt_api_key = QLineEdit(manager.config.api_key or "")
        self.txt_api_key.setPlaceholderText("Emby：管理后台 → 高级 → API 密钥；Jellyfin：控制台 → API 密钥")
        self.txt_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(self.txt_api_key, 0, 3)
        btn_layout = QHBoxLayout()
        self.btn_connect = QPushButton("连接 Emby/Jellyfin")
        self.btn_connect.setObjectName("btnPrimary")
        btn_layout.addWidget(self.btn_connect)
        self.btn_fetch = QPushButton("获取演员列表")
        self.btn_fetch.setObjectName("btnPrimary")
        self.btn_fetch.setEnabled(False)
        btn_layout.addWidget(self.btn_fetch)
        self.cmb_fetch_mode = QComboBox()
        # 议题 #164: 按「单缺字段 → 双缺 → 并集 → 重新获取组」范围递增排序;
        # 去掉（并集）（交集）标注——名称已自明, 集合术语保留在 tooltip。
        self.cmb_fetch_mode.addItems(
            [
                "仅缺失简介",
                "仅缺失头像",
                "头像和简介都缺",
                "缺失头像或缺失简介",
                "重新获取所有演员详情",
                "重新获取所有演员简介",
                "重新获取所有演员头像",
                "重新获取所有演员头像和简介",
            ]
        )
        # 议题 #147: 明确「或=并集(缺任一即取)/且=交集(两者都缺)」, 并说明占位简介按缺失处理,
        # 与统计栏分项统一口径。议题 #155: 补「交集」独立入口, 与统计栏「全缺」分项对应。
        self.cmb_fetch_mode.setItemData(
            0, "仅缺简介的演员（简介仅剩「无维基百科信息」占位也按缺处理）", Qt.ItemDataRole.ToolTipRole
        )
        self.cmb_fetch_mode.setItemData(1, "仅缺头像的演员（含缺简介者，只要缺头像）", Qt.ItemDataRole.ToolTipRole)
        self.cmb_fetch_mode.setItemData(
            2,
            "缺头像 且 缺简介 = 交集（两者都缺才选取，对应统计栏「全缺」；占位简介按缺处理）",
            Qt.ItemDataRole.ToolTipRole,
        )
        self.cmb_fetch_mode.setItemData(
            3, "缺头像 或 缺简介 = 并集（缺任其一即选取；全缺也在内）", Qt.ItemDataRole.ToolTipRole
        )
        # 议题 #149: 全量刷新简介/出生日期/出生地/标签等信息; 影片数来自服务器、
        # 头像交由第三方工具, 均不在本模式范围内。
        self.cmb_fetch_mode.setItemData(
            4,
            "不筛缺失，为全部演员 重新获取 简介/出生日期/出生地/标签（不动头像与影片数）",
            Qt.ItemDataRole.ToolTipRole,
        )
        # 议题 #164: 仅简介的重新获取——同步出口按真值逐字段写入, 只回写简介,
        # 不覆盖手动修正过的出生日期/出生地/标签。
        self.cmb_fetch_mode.setItemData(
            5,
            "不筛缺失，为全部演员 重新获取 简介（只回写简介，出生日期/出生地/标签/头像/影片数均不动）",
            Qt.ItemDataRole.ToolTipRole,
        )
        self.cmb_fetch_mode.setItemData(6, "不筛缺失，为全部演员 重新获取 头像", Qt.ItemDataRole.ToolTipRole)
        self.cmb_fetch_mode.setItemData(7, "不筛缺失，为全部演员 重新获取 头像+简介", Qt.ItemDataRole.ToolTipRole)
        # 议题 #164: 重排后默认项显式锚定并集(index 3)——保持"打开即最通用模式"的既有行为
        self.cmb_fetch_mode.setCurrentIndex(3)
        self.cmb_fetch_mode.setFixedWidth(220)
        btn_layout.addWidget(self.cmb_fetch_mode)
        self.btn_preview = QPushButton("根据设定获取数据")
        self.btn_preview.setObjectName("btnPrimary")
        self.btn_preview.setEnabled(False)
        btn_layout.addWidget(self.btn_preview)
        # 议题 #149: 数据清洗按钮, 按需求置于「根据设定获取数据」与「开始全部更新同步」之间
        self.btn_clean = QPushButton("数据清洗")
        self.btn_clean.setObjectName("btnPrimary")
        self.btn_clean.setEnabled(False)
        self.btn_clean.setToolTip(
            "原地清洗服务器存量演员数据（不经取数流程）:\n"
            "① 0000-00-00 等非法生日 → 重置为未设置\n"
            "② 「无维基百科信息」占位简介 → 清空\n"
            "<br>/换行/==== 段落标题属合法结构, 客户端按其渲染分行, 不压平（议题 #171）\n"
            "清洗后可选「更新所有演员数据」做全量信息刷新；头像与影片数不受影响"
        )
        btn_layout.addWidget(self.btn_clean)
        self.btn_sync = QPushButton("开始全部更新同步")
        self.btn_sync.setObjectName("btnSync")
        self.btn_sync.setEnabled(False)
        btn_layout.addWidget(self.btn_sync)
        btn_layout.addStretch()
        self.btn_test_source = QPushButton("数据源测试")
        btn_layout.addWidget(self.btn_test_source)
        self.btn_clear_cache = QPushButton("清空缓存文件夹")
        btn_layout.addWidget(self.btn_clear_cache)
        self.btn_settings = QPushButton("设置")
        btn_layout.addWidget(self.btn_settings)
        grid.addLayout(btn_layout, 1, 0, 1, 4)
        help_label = QLabel(
            "使用说明：① 填写地址和密钥 → ② 连接/获取演员列表 → ③ 选择模式获取数据 → "
            "④ 绿色行=待更新 → ⑤ 开始同步到服务器。双击行可查看当前头像/简介/出生日期/影片数等详情。"
        )
        # 不写 font-size：跟随 _load_stylesheet 里放大后的统一字号，写死 12px 会反盖回去。
        # 允许折行：这行说明是单行长文本，不折行时它的 sizeHint 会成为整个对话框的最小宽度
        # （字号放大后 1128 → 1222px，1280 宽的小屏会被撑出屏外）；折行后最小宽度回到按钮行决定。
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #888888; padding: 2px 0;")
        grid.addWidget(help_label, 2, 0, 1, 4)
        parent_layout.addWidget(group)

    def _build_actor_list(self, parent_layout: QVBoxLayout):
        stats_layout = QHBoxLayout()
        self.lbl_total = QLabel("总数: -")
        # 议题 #157: 重复演员数 = 原始条目数 − 唯一名字数, 直接展示免用户两种计数方式手算
        self.lbl_duplicate = QLabel("重复: -")
        self.lbl_duplicate.setToolTip(
            "重复演员数 = 同名演员产生的多余条目数（原始条目数 − 唯一名字数）。\n"
            "可在「设置」中勾选「重复演员去重（按名称合并）」合并同名条目。"
        )
        self.lbl_has_both = QLabel("完整: -")
        self.lbl_missing_image = QLabel("缺头像: -")
        self.lbl_missing_info = QLabel("缺简介: -")
        self.lbl_missing_all = QLabel("全缺: -")
        self.lbl_backdrop = QLabel("有背景图: -")
        for lbl in (
            self.lbl_total,
            self.lbl_duplicate,
            self.lbl_has_both,
            self.lbl_missing_image,
            self.lbl_missing_info,
            self.lbl_missing_all,
            self.lbl_backdrop,
        ):
            lbl.setStyleSheet("padding: 2px 8px;")
            stats_layout.addWidget(lbl)
        stats_layout.addStretch()
        stats_layout.addWidget(QLabel("计数方式:"))
        self.cmb_count_mode = QComboBox()
        self.cmb_count_mode.addItems(["原始条目数", "唯一名字数"])
        # 议题 #143: 先恢复已保存的选择再 connect, 避免构造时误触发保存
        self.cmb_count_mode.setCurrentIndex(1 if self._show_unique else 0)
        self.cmb_count_mode.currentIndexChanged.connect(self._on_count_mode_changed)
        stats_layout.addWidget(self.cmb_count_mode)
        parent_layout.addLayout(stats_layout)
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("筛选:"))
        self.cmb_filter = QComboBox()
        self.cmb_filter.addItems(["全部", "待同步", "缺头像", "缺背景", "缺简介", "缺头像和简介", "完整"])
        self.cmb_filter.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.cmb_filter)
        filter_layout.addWidget(QLabel("  搜索:"))
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("输入演员名搜索...")
        self.txt_search.setMaximumWidth(200)
        self.txt_search.textChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.txt_search)
        hint = QLabel("双击行可编辑")
        # 同上：不钉死字号，跟随统一放大的字号
        hint.setStyleSheet("color: #888888;")
        filter_layout.addWidget(hint)
        filter_layout.addStretch()
        parent_layout.addLayout(filter_layout)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        parent_layout.addWidget(self.progress_bar)
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["状态", "姓名", "头像", "简介", "详情", "出生日期", "出生地", "标签", "影片数"]
        )
        horizontal_header = self.table.horizontalHeader()
        assert horizontal_header is not None
        horizontal_header.setStretchLastSection(False)
        horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        # 议题 #136：详情/标签改为按 3:1 分配剩余宽度（标签过宽、详情过窄），
        # 具体宽度由 _apply_column_widths 在 resize 时按视口计算，总宽保持铺满。
        horizontal_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        horizontal_header.setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        vertical_header = self.table.verticalHeader()
        assert vertical_header is not None
        vertical_header.setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.setColumnWidth(0, 50)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 55)
        self.table.setColumnWidth(3, 55)
        self.table.setColumnWidth(5, 110)
        self.table.setColumnWidth(6, 140)
        self.table.setColumnWidth(8, 60)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
        parent_layout.addWidget(self.table)
        # 议题 #160: 纵向滚动条显隐只改 viewport 几何、不触发窗口 resizeEvent;
        # 监听 viewport 尺寸变化, 在其后按真实视口宽重算列宽, 消除随之出现的横向滚动条
        table_viewport = self.table.viewport()
        assert table_viewport is not None
        table_viewport.installEventFilter(self)

    # 固定宽度列（0 状态/1 姓名/2 头像/3 简介/5 出生日期/6 出生地/8 影片数）；
    # 剩余宽度在 4 详情 与 7 标签 之间按 _DETAIL_WIDTH_RATIO 分配（议题 #136）。
    _FIXED_COLUMN_WIDTHS = {0: 50, 1: 160, 2: 55, 3: 55, 5: 110, 6: 140, 8: 60}
    _DETAIL_WIDTH_RATIO = 0.75  # 详情占剩余宽度的 3/4，标签 1/4（标签约为原一半）

    def _apply_column_widths(self) -> None:
        """按视口宽度重新分配「详情/标签」列宽，保证各列总宽铺满且比例稳定。"""
        table = getattr(self, "table", None)
        if table is None:
            return
        viewport_w = table.viewport().width()
        if viewport_w <= 0:
            return
        fixed_sum = sum(self._FIXED_COLUMN_WIDTHS.values())
        remain = max(viewport_w - fixed_sum, 120)
        detail_w = int(remain * self._DETAIL_WIDTH_RATIO)
        tags_w = remain - detail_w
        # 防御性重入保护: setColumnWidth 实测不改 viewport 宽(不会自激), 嵌套调用为同值空操作
        if getattr(self, "_applying_widths", False):
            return
        self._applying_widths = True
        try:
            table.setColumnWidth(4, detail_w)
            table.setColumnWidth(7, tags_w)
        finally:
            self._applying_widths = False

    def eventFilter(self, a0, a1):
        """议题 #160: viewport 尺寸变化(含纵向滚动条显隐/DPI 变化)后重算列宽。"""
        table = getattr(self, "table", None)
        if table is not None and a0 is table.viewport() and a1 is not None and a1.type() == QEvent.Type.Resize:
            self._apply_column_widths()
        return super().eventFilter(a0, a1)

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        self._apply_column_widths()

    def showEvent(self, a0):
        super().showEvent(a0)
        self._apply_column_widths()

    def _build_log_section(self, parent_layout: QVBoxLayout):
        group = QGroupBox("运行日志")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(500)
        layout.addWidget(self.log_text)
        parent_layout.addWidget(group)

    def _connect_signals(self):
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_fetch.clicked.connect(self._on_fetch)
        self.btn_preview.clicked.connect(self._on_prepare_preview)
        self.btn_clean.clicked.connect(self._on_clean_data)
        self.btn_sync.clicked.connect(self._on_sync)
        self.btn_settings.clicked.connect(self._on_open_settings)
        self.btn_test_source.clicked.connect(self._on_open_test_source)
        self.btn_clear_cache.clicked.connect(self._on_clear_cache)
        self._connect_result.connect(self._on_connect_result)
        self._media_folders_result.connect(self._on_media_folders_result)
        self._gfriends_result.connect(self._on_gfriends_result)

    def _on_open_settings(self):
        self._show_child_window("_settings_dialog", EmbyActorSettingsDialog)

    def _on_open_test_source(self):
        self._show_child_window("_test_dialog", ActorSourceTestDialog)

    def _show_child_window(self, attr: str, factory):
        """设置/数据源测试与管理器互相独立：非模态顶层窗口，可与管理器并存操作；

        单例复用——已存在则提前台（含从最小化还原），已销毁则新建；
        destroyed 信号清引用，避免悬空指针。
        """
        try:
            existing = getattr(self, attr, None)
            if existing is not None:
                if existing.isMinimized():
                    existing.showNormal()
                else:
                    existing.show()
                existing.raise_()
                existing.activateWindow()
                return
        except RuntimeError:
            # C++ 对象已被销毁（WA_DeleteOnClose 释放），换新的
            setattr(self, attr, None)
        dialog = factory()
        dialog.destroyed.connect(lambda *_a, _attr=attr: setattr(self, _attr, None))
        setattr(self, attr, dialog)
        dialog.show()

    def _on_clear_cache(self):
        from ..config.resources import resources

        cache_dirs = [self.cache_dir, resources.u("actor")]
        reply = QMessageBox.question(
            self,
            "确认清空缓存",
            "将删除已下载的演员头像缓存，下次获取时会重新下载\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        removed = 0
        import shutil

        for cache_dir in cache_dirs:
            if not cache_dir.is_dir():
                continue
            for f in cache_dir.iterdir():
                try:
                    if f.is_dir():
                        shutil.rmtree(f, ignore_errors=True)
                    else:
                        f.unlink()
                    removed += 1
                except Exception:
                    continue
        self.log(f"🧹 已清空 {len(cache_dirs)} 个缓存目录，删除 {removed} 个文件/目录")

    def _open_log_file(self):
        """打开演员管理器日志文件（追加模式）。

        议题 #88：与主程序日志同目录（data_folder/Log，而非 userdata/logs），
        并按打开时刻加时间戳命名（如 2026-09-07-05-13-17 actor_manager.log），
        避免历次会话全塞进同一个 actor_manager.log。
        """
        import time

        try:
            log_dir = manager.data_folder / "Log"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y-%m-%d-%H-%M-%S")
            self._log_file = log_dir / f"{ts} actor_manager.log"
        except Exception:
            self._log_file = None

    def _close_log_file(self):
        """关闭日志文件（由 Qt 在窗口关闭时自动调用）"""
        self._log_file = None

    def log(self, msg: str):
        import datetime

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        formatted = f"[{ts}] {msg}"
        self.log_text.appendPlainText(formatted)
        if self._log_file is not None:
            try:
                with open(self._log_file, "a", encoding="utf-8") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass

    def _set_buttons_enabled(self, enabled: bool):
        self.btn_connect.setEnabled(enabled)
        self.btn_fetch.setEnabled(enabled and hasattr(self, "_connected") and self._connected)
        actors = getattr(self, "_actors", None) or []
        self.btn_preview.setEnabled(enabled and len(actors) > 0)
        self.btn_clean.setEnabled(enabled and len(actors) > 0)
        pending = any(a.need_update_info or a.need_update_image or a.need_update_backdrop for a in actors)
        self.btn_sync.setEnabled(enabled and pending)

    def _on_connect(self):
        url = self.txt_url.text().strip()
        key = self.txt_api_key.text().strip()
        if not url or not key:
            QMessageBox.warning(self, "提示", "请输入服务器地址和 API 密钥")
            return
        from .emby_shared import _build_jellyfin_headers, _emby_api_prefix, _emby_get_json

        self._emby_url = url
        self._emby_key = key

        async def test():
            # 议题 #133: 连接探测改用轻量直连 httpx(无指纹/无池/无限流)。
            # Emby/Jellyfin 都用 Authorization 头携带 token, 统一走 header 校验,
            # 不再为 Emby 单独拼 ?api_key=。传入用户刚输入的 token, 校验后才持久化。
            resp, err = await _emby_get_json(
                f"{_emby_api_prefix()}/System/Info",
                headers=_build_jellyfin_headers(token=key),
            )
            if resp:
                name = resp.get("ServerName", "Emby")
                version = resp.get("Version", "")
                return True, f"连接成功！{name} v{version}"
            return False, f"连接失败: {err}"

        self.btn_connect.setEnabled(False)
        self.btn_connect.setText("连接中...")
        self._set_status("连接中...")
        try:
            future = executor.submit(test())
        except Exception as e:
            future = None
            self.btn_connect.setEnabled(True)
            self.btn_connect.setText("连接 Emby/Jellyfin")
            self._set_status("连接失败")
            self.log(f"❌ 连接失败: {e}")
            return
        future.add_done_callback(lambda fut: self._connect_result.emit(_future_result_or(fut, (False, "连接失败"))))

    def _on_connect_result(self, result: tuple[bool, str]):
        ok, msg = result
        self.btn_connect.setEnabled(True)
        self.btn_connect.setText("已连接" if ok else "连接 Emby/Jellyfin")
        if ok:
            self._connected = True
            self.btn_fetch.setEnabled(True)
            self._set_status("连接成功")
            self.log(f"✅ {msg}")
            self._persist_connection()
        else:
            self._set_status("连接失败")
            self.log(f"❌ {msg}")
            QMessageBox.critical(self, "连接失败", msg)

    def _persist_connection(self):
        """把 UI 填写的地址/密钥写回全局配置，保证后续请求与界面一致。"""
        try:
            cfg = manager.config.model_copy(deep=True)
            cfg.api_key = self._emby_key
            cfg.emby_url = HttpUrl(self._emby_url)
            manager._replace_config(cfg)
            # 写盘移后台线程，避免主线程同步 IO 卡顿
            threading.Thread(target=manager.save, daemon=True).start()
            self.log("💾 已保存连接设置到配置")
        except Exception as e:
            self.log(f"🔶 连接设置保存失败，继续使用当前配置: {e}")

    def _on_fetch(self):
        if not hasattr(self, "_connected") or not self._connected:
            QMessageBox.warning(self, "提示", "请先连接 Emby/Jellyfin 服务器")
            return
        self.btn_fetch.setEnabled(False)
        self._set_status("获取媒体库列表...")
        try:
            future = executor.submit(get_media_folders())
        except Exception as e:
            self.btn_fetch.setEnabled(True)
            self._set_status("获取媒体库列表失败")
            self.log(f"❌ 获取媒体库列表失败: {e}")
            return
        future.add_done_callback(lambda fut: self._media_folders_result.emit(_future_result_or(fut, [])))

    def _on_media_folders_result(self, libraries: list[dict]):
        self.btn_fetch.setEnabled(True)
        if not libraries:
            self._set_status("获取媒体库列表失败")
            self.log("❌ 无法获取媒体库列表")
            return
        dlg = LibrarySelectDialog(libraries, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.log("⏹ 用户取消")
            return
        selected_ids = dlg.get_selected_ids()
        if not selected_ids:
            QMessageBox.warning(self, "提示", "请至少选择一个媒体库")
            return
        library_ids = None if len(selected_ids) == len(libraries) else selected_ids
        self._current_library_ids = library_ids  # 供同步后自动刷新复用，避免丢媒体库过滤
        self._set_buttons_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._set_status("获取演员列表...")
        self.log("📜 开始获取演员列表...")
        self._fetch_thread = FetchActorsThread(self)
        self._fetch_thread.library_ids = library_ids
        self._begin_session(self._fetch_thread)
        self._fetch_thread.progress.connect(self._on_fetch_progress)
        self._fetch_thread.fetch_done.connect(self._on_fetch_finished)
        self._fetch_thread.error.connect(self._on_thread_error)
        self._fetch_thread.start()

    def _on_fetch_progress(self, current: int, total: int, msg: str):
        if self._is_stale_session():
            return
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
        self.setWindowTitle(f"Emby/Jellyfin演员管理器 - {msg}")

    def _on_fetch_finished(self, actors: list[ActorInfo], raw_count: int):
        if self._is_stale_session():
            return
        self._actors = actors
        self._raw_count = raw_count
        self._set_status("获取完成")
        self.log(f"获取完成，共 {len(actors)} 个演员")
        self._populate_table(actors)
        self._update_statistics(actors)
        self.btn_preview.setEnabled(len(actors) > 0)
        self.progress_bar.setVisible(False)
        self._set_buttons_enabled(True)
        try:
            future = executor.submit(get_gfriends_index())
        except Exception as e:
            self.log(f"🔶 Gfriends 索引加载失败: {e}")
            return
        future.add_done_callback(lambda fut: self._gfriends_result.emit(_future_result_or(fut, None)))

    def _on_gfriends_result(self, index):
        self._gfriends_index = index
        if index:
            self.log(f"✅ Gfriends 头像库加载完成，共 {len(index)} 个头像")

    def _on_prepare_preview(self):
        if self._preview_thread and self._preview_thread.isRunning():
            self._preview_thread.cancel()
            # 议题 #25: 代数+1 作废旧线程全部排队回调；UI 立即恢复可操作，
            # 不再等旧线程收尾信号（旧版依赖它恢复按钮，cancel→快速重开存在覆盖窗口）
            self._session_gen += 1
            self.log("⏹️ 用户取消")
            self.btn_preview.setText("根据设定获取数据")
            self.progress_bar.setVisible(False)
            self._set_status("已取消")
            self._set_buttons_enabled(True)
            return
        mode_map = {
            "仅缺失简介": "missing_info",
            "仅缺失头像": "missing_image",
            "头像和简介都缺": "missing_both",
            "缺失头像或缺失简介": "missing_all",
            "重新获取所有演员详情": "force_info",
            "重新获取所有演员简介": "force_overview",
            "重新获取所有演员头像": "force_image",
            "重新获取所有演员头像和简介": "force_all",
        }
        mode = mode_map.get(self.cmb_fetch_mode.currentText(), "missing_all")
        # 议题 #127: 「缺失」类模式只处理子集, 不再逐人遍历全库
        targets = PreparePreviewThread.select_targets(self._actors, mode)
        if self._actors and not targets:
            self.log("✅ 按当前模式没有需要获取数据的演员")
            return
        self._set_buttons_enabled(False)
        self.btn_preview.setEnabled(True)
        self.btn_preview.setText("停止获取")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._set_status("获取数据中...")
        self.log(f"📥 正在获取数据（模式: {self.cmb_fetch_mode.currentText()}，共 {len(targets)} 人）")
        self._preview_thread = PreparePreviewThread(self)
        self._preview_thread.actors = self._actors
        self._preview_thread.targets = targets
        self._preview_thread.mode = mode
        self._preview_thread.gfriends_index = self._gfriends_index
        self._preview_thread.cache_dir = self.cache_dir
        self._preview_thread.image_sources = list(manager.config.actor_image_sources)

        self._preview_thread.local_avatar_dir = (
            manager.config.actor_photo_folder if hasattr(manager.config, "actor_photo_folder") else ""
        )
        self._begin_session(self._preview_thread)
        self._preview_thread.progress.connect(self._on_fetch_progress)
        self._preview_thread.preview_done.connect(self._on_preview_finished)
        self._preview_thread.error.connect(self._on_thread_error)
        self._preview_thread.start()

    def _on_preview_finished(self, actors: list[ActorInfo]):
        if self._is_stale_session():
            return
        self._actors = actors
        self._populate_table(actors)
        self._update_statistics(actors)
        to_sync = [a for a in actors if a.need_update_info or a.need_update_image or a.need_update_backdrop]
        self.btn_sync.setEnabled(len(to_sync) > 0)
        self.btn_sync.setText(f"开始全部更新同步({len(to_sync)} 项)")
        self._set_status("数据准备完成")
        self.log(f"✅ 预览准备完成，{len(to_sync)} 项待同步")
        self.btn_preview.setText("根据设定获取数据")
        self.progress_bar.setVisible(False)
        self._set_buttons_enabled(True)

    def _on_clean_data(self):
        """议题 #149: 扫描存量噪声 → 弹确认(含前 5 条 before/after) → 批量清洗。"""
        if not self._actors:
            return
        dirty = scan_actor_data_noise(self._actors)
        if not dirty:
            QMessageBox.information(self, "数据清洗", "✅ 未发现需要清洗的数据")
            return
        samples = []
        for a, new_ov, fix_birth in dirty[:5]:
            parts = []
            if new_ov != (a.existing_overview or ""):
                before = (a.existing_overview or "")[:40] or "(空)"
                after = new_ov[:40] or "(空)"
                parts.append(f"简介: {before} → {after}")
            if fix_birth:
                parts.append(f"生日: {(a.existing_premiere_date or '')[:10]} → (置空)")
            samples.append(f"· {a.name}: " + "; ".join(parts))
        reply = QMessageBox.question(
            self,
            "确认数据清洗",
            f"发现 {len(dirty)} 个演员的数据需要清洗（示例前 5 条）:\n\n"
            + "\n".join(samples)
            + "\n\n清洗将直接改写服务器数据且不可撤销（不动头像与影片数），建议先备份。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_buttons_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._set_status("数据清洗中...")
        self.log(f"🧹 开始数据清洗，共 {len(dirty)} 个演员...")
        self._clean_items = {a.actor_id: (new_ov, fix_birth) for a, new_ov, fix_birth in dirty}
        self._clean_failed = []
        self._clean_thread = CleanDataThread(self)
        self._clean_thread.items = dirty
        self._begin_session(self._clean_thread)
        self._clean_thread.progress.connect(self._on_sync_progress)
        self._clean_thread.actor_done.connect(self._on_clean_actor_done)
        self._clean_thread.clean_done.connect(self._on_clean_finished)
        self._clean_thread.error.connect(self._on_thread_error)
        self._clean_thread.start()

    def _on_clean_actor_done(self, actor_id: str, success: bool, msg: str):
        if self._is_stale_session():
            return
        # 清洗成功后立即就地更新内存状态; 失败保留原值, 下次清洗可重试
        # 议题 #162: 失败逐条落日志(名字+服务器原因), 完成时汇总, 消除"只见计数不见原因"盲区
        if not success:
            self._clean_failed.append((actor_id, msg))
            self.log(f"🔴 清洗失败: {msg}")
            return
        actor = next((a for a in self._actors if a.actor_id == actor_id), None)
        item = self._clean_items.get(actor_id)
        if actor is None or item is None:
            return
        new_ov, fix_birth = item
        actor.existing_overview = new_ov
        actor.has_overview = bool(new_ov)
        if fix_birth:
            actor.existing_premiere_date = ""

    def _on_clean_finished(self, success: int, fail: int):
        if self._is_stale_session():
            return
        self.progress_bar.setVisible(False)
        self._set_buttons_enabled(True)
        self._set_status("数据清洗完成")
        self._clean_items = {}
        self.log(f"🧹 数据清洗完成！成功: {success}, 失败: {fail}")
        # 议题 #162: 清洗是直接改写服务器的, 无"待同步"残留——完成提示讲清这一点,
        # 并列出失败者名单与重试指引, 避免用户误以为还要点「开始全部更新同步」。
        names = []
        for actor_id, _ in self._clean_failed:
            actor = next((a for a in self._actors if a.actor_id == actor_id), None)
            names.append(actor.name if actor else actor_id)
        self._clean_failed = []
        detail = ""
        if names:
            preview = "、".join(names[:20]) + ("…" if len(names) > 20 else "")
            detail = f"\n\n❌ 失败 {len(names)} 个: {preview}\n失败原因见上方运行日志；再点一次「数据清洗」即可仅重试失败项。"
        if fail == 0:
            detail += "\n\n清洗已直接写入服务器，无需再点「开始全部更新同步」。"
        QMessageBox.information(self, "数据清洗完成", f"✅ 成功: {success}\n❌ 失败: {fail}{detail}")
        self._populate_table(self._actors)
        self._update_statistics(self._actors)

    def _on_sync(self):
        to_sync = [a for a in self._actors if a.need_update_info or a.need_update_image or a.need_update_backdrop]
        if not to_sync:
            QMessageBox.information(self, "提示", "没有需要同步的项")
            return
        reply = QMessageBox.question(
            self,
            "确认同步",
            f"将同步 {len(to_sync)} 个演员的信息/头像/背景图到 Emby/Jellyfin，\n此操作不可撤销，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._set_buttons_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.btn_sync.setText("同步中...")
        self._set_status("同步中...")
        self.log(f"📛 开始同步 {len(to_sync)} 个演员...")
        self._failed_names.clear()
        self._sync_thread = SyncThread(self)
        self._sync_thread.actors = to_sync
        self._begin_session(self._sync_thread)
        self._sync_thread.progress.connect(self._on_sync_progress)
        self._sync_thread.actor_done.connect(self._on_sync_actor_done)
        self._sync_thread.sync_done.connect(self._on_sync_finished)
        self._sync_thread.error.connect(self._on_thread_error)
        self._sync_thread.start()

    def _on_sync_progress(self, current: int, total: int, msg: str):
        if self._is_stale_session():
            return
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.setWindowTitle(f"Emby/Jellyfin演员管理器 - {msg}")

    def _on_sync_actor_done(self, actor_id: str, name: str, success: bool, msg: str):
        if self._is_stale_session():
            return
        # 用 actor_id 匹配，避免同名演员（未去重时）按名字错位更新状态
        actor = next((a for a in self._actors if a.actor_id == actor_id), None)
        if success:
            if actor is not None:
                self._apply_sync_success(actor)
            self.log(f"✅ {name} 同步成功")
        else:
            # 失败的演员保留 need_update 标记，可在下次同步重试
            self._failed_names.add(name)
            self.log(f"❌ {name} 同步失败: {msg}")

    def _apply_sync_success(self, a: ActorInfo):
        if a.need_update_image:
            a.has_image = bool(a.new_image_path)
            a.need_update_image = False
        if a.need_update_info:
            a.has_overview = bool(a.new_overview and a.new_overview.strip())
            a.existing_overview = a.new_overview or a.existing_overview
            a.existing_taglines = list(a.new_taglines)
            a.existing_production_year = a.new_production_year
            a.existing_premiere_date = a.new_premiere_date
            a.existing_production_locations = list(a.new_production_locations)
            a.need_update_info = False
        if a.need_update_backdrop:
            a.has_backdrop = bool(a.new_backdrop_path)
            a.need_update_backdrop = False

    def _on_sync_finished(self, success: int, fail: int):
        if self._is_stale_session():
            return
        self.progress_bar.setVisible(False)
        self._set_buttons_enabled(True)
        self.btn_sync.setText("开始全部更新同步")
        self._set_status("同步完成")
        self.log(f"同步完成！成功: {success}, 失败: {fail}")
        QMessageBox.information(self, "同步完成", f"✅ 成功: {success}\n❌ 失败: {fail}")
        self._populate_table(self._actors)
        self._update_statistics(self._actors)
        # 同步完成后 3 秒自动重新获取演员列表，确保与 Emby 完全一致
        self.log("⏳ 3 秒后自动刷新演员列表...")
        QTimer.singleShot(3000, self._on_auto_refresh)

    def _on_auto_refresh(self):
        if not hasattr(self, "_connected") or not self._connected:
            return
        self._set_buttons_enabled(False)
        self.log("🔄 正在自动刷新演员列表...")
        self._refresh_thread = FetchActorsThread(self)
        self._refresh_thread.library_ids = getattr(self, "_current_library_ids", None)
        self._refresh_thread.progress.connect(self._on_fetch_progress)
        self._refresh_thread.fetch_done.connect(self._on_auto_refresh_finished)
        self._refresh_thread.error.connect(self._on_thread_error)
        self._refresh_thread.start()

    def _on_auto_refresh_finished(self, actors: list[ActorInfo], raw_count: int):
        if self._failed_names:
            failed_old = {a.name: a for a in self._actors if a.name in self._failed_names}
            if failed_old:
                merged = []
                for new in actors:
                    old = failed_old.get(new.name)
                    if old is None:
                        merged.append(new)
                        continue
                    # 失败演员保留待同步状态与本地新数据，仅用刷新结果更新服务器侧状态
                    old.has_image = new.has_image
                    old.has_overview = new.has_overview
                    old.has_backdrop = new.has_backdrop
                    old.existing_overview = new.existing_overview
                    old.movie_count = new.movie_count
                    old.movie_titles = new.movie_titles
                    merged.append(old)
                actors = merged
                self.log(f"🔁 已保留 {len(failed_old)} 个同步失败演员的待同步状态，可直接重试")
        self._actors = actors
        self._raw_count = raw_count
        self._populate_table(actors)
        self._update_statistics(actors)
        self.btn_preview.setEnabled(len(actors) > 0)
        self._set_status("自动刷新完成")
        self.log(f"✅ 自动刷新完成，共 {len(actors)} 个演员")
        self._set_buttons_enabled(True)

    def _on_thread_error(self, msg: str):
        if self._is_stale_session():
            return
        self.progress_bar.setVisible(False)
        # 线程已结束，恢复按钮文本与状态，避免"停止/同步中..."残留
        self.btn_preview.setText("根据设定获取数据")
        self.btn_sync.setText("开始全部更新同步")
        self._set_buttons_enabled(True)
        self.log(f"🔶 错误: {msg}")
        QMessageBox.critical(self, "错误", msg)

    def closeEvent(self, event):
        # 议题 #175: 获取数据中关窗会 "QThread: Destroyed while thread is still running"
        # 把整个进程 abort（Windows 上看起来像主程序一起退出，日志为空）。
        # 关闭前取消全部工作线程并等待；超时则卸父级，避免随 WA_DeleteOnClose 一起销毁。
        self._shutdown_worker_threads()
        super().closeEvent(event)

    def _shutdown_worker_threads(self, timeout_ms: int = 5000) -> None:
        attrs = ("_fetch_thread", "_preview_thread", "_sync_thread", "_clean_thread", "_refresh_thread")
        threads = []
        for attr in attrs:
            thread = getattr(self, attr, None)
            if thread is None:
                continue
            for sig_name in (
                "progress",
                "error",
                "fetch_done",
                "preview_done",
                "sync_done",
                "clean_done",
                "actor_done",
            ):
                sig = getattr(thread, sig_name, None)
                if sig is None:
                    continue
                try:
                    sig.disconnect()
                except (TypeError, RuntimeError):
                    pass
            if hasattr(thread, "abort"):
                thread.abort()
            elif hasattr(thread, "cancel"):
                thread.cancel()
            threads.append(thread)
        remaining = timeout_ms
        for thread in threads:
            if not thread.isRunning():
                continue
            waited = thread.wait(max(remaining, 0))
            if waited or not thread.isRunning():
                continue
            _detach_running_thread(thread)
            remaining = 0

    def _on_filter_changed(self):
        self._populate_table(self._actors)

    def _on_table_double_clicked(self, row: int, col: int):
        # 表格启用排序后视觉行序 != _get_filtered_actors() 索引，用演员名反查，避免打开错误演员
        item = self.table.item(row, 1)
        if item is None:
            return
        name = item.text()
        actor = next((a for a in self._actors if a.name == name), None)
        if actor is None:
            return
        dialog = ActorDetailDialog(actor, self, on_synced=self._on_detail_synced)
        dialog.exec()

    def _on_detail_synced(self, actor: ActorInfo):
        # 同步单个演员后刷新主窗口表格与统计
        self.log(f"✅ {actor.name} 同步完成，刷新列表")
        self._populate_table(self._actors)
        self._update_statistics(self._actors)
        self._update_sync_button()

    def _get_filtered_actors(self) -> list[ActorInfo]:
        filter_mode = self.cmb_filter.currentText()
        search_text = self.txt_search.text().strip().lower()
        filtered = []
        for a in self._actors:
            if filter_mode == "缺头像" and a.has_image:
                continue
            elif filter_mode == "缺背景" and a.has_backdrop:
                continue
            elif filter_mode == "缺简介" and a.has_overview:
                continue
            elif filter_mode == "缺头像和简介" and a.has_image and a.has_overview:
                continue
            elif filter_mode == "完整" and not (a.has_image and a.has_overview):
                continue
            elif filter_mode == "待同步" and not (a.need_update_info or a.need_update_image or a.need_update_backdrop):
                continue
            if search_text and search_text not in a.name.lower():
                continue
            filtered.append(a)
        return filtered

    def _populate_table(self, actors: list[ActorInfo]):
        self.table.setSortingEnabled(False)
        filtered = self._get_filtered_actors() if actors else []
        self.table.setRowCount(len(filtered))
        for row, actor in enumerate(filtered):
            icon_item = QTableWidgetItem(actor.status_icon)
            icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, icon_item)
            name_item = QTableWidgetItem(actor.name)
            name_item.setToolTip(f"ID: {actor.actor_id}")
            self.table.setItem(row, 1, name_item)
            img_item = QTableWidgetItem("✅" if actor.has_image else "❌")
            img_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if actor.need_update_image:
                img_item.setText("🔄")
            img_item.setToolTip(
                f"头像: {'有' if actor.has_image else '无'} | 背景图: {'有' if actor.has_backdrop else '无'}"
            )
            self.table.setItem(row, 2, img_item)
            info_item = QTableWidgetItem("✅" if actor.has_overview else "❌")
            info_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if actor.need_update_info:
                info_item.setText("🔄")
            self.table.setItem(row, 3, info_item)
            overview_text = (
                actor.existing_overview[:80] + "..."
                if len(actor.existing_overview) > 80
                else (actor.existing_overview or "（无）")
            )
            self.table.setItem(row, 4, QTableWidgetItem(overview_text))
            # 议题 #134：详情与标签之间展示出生日期、出生地，均为 Emby 服务器现有值
            raw_birthday = (actor.existing_premiere_date or "")[:10]
            # Emby 未设置生日时返回 0001-01-01，按空值展示，避免列表出现占位日期
            birthday_text = "" if raw_birthday.startswith("0001-01-01") else raw_birthday
            birthday_item = QTableWidgetItem(birthday_text)
            # 议题 #153：出生日期为定宽列, 居中显示与 状态/头像/影片数 列观感一致
            birthday_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 5, birthday_item)
            location_text = (
                ", ".join(actor.existing_production_locations) if actor.existing_production_locations else ""
            )
            self.table.setItem(row, 6, QTableWidgetItem(location_text))
            tags = ", ".join(actor.existing_taglines[:2]) if actor.existing_taglines else ""
            self.table.setItem(row, 7, QTableWidgetItem(tags))
            mc_item = QTableWidgetItem(str(actor.movie_count) if actor.movie_count > 0 else "0")
            mc_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if actor.movie_titles:
                mc_item.setToolTip("\n".join(actor.movie_titles[:20]))
            self.table.setItem(row, 8, mc_item)
            if actor.need_update_info or actor.need_update_image:
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    if item:
                        item.setBackground(QColor("#c8e6c9"))
        self.table.setSortingEnabled(True)
        self._update_sync_button()

    def _on_count_mode_changed(self, index: int):
        self._show_unique = index == 1
        self._update_statistics(self._actors)
        # 议题 #143: 切换即保存, 重启 MDCx / 重开管理器后保持不变
        try:
            cfg = manager.config.model_copy(deep=True)
            cfg.actor_count_mode = 1 if index == 1 else 0
            manager._replace_config(cfg)
            manager.save()
        except Exception as e:
            self.log(f"🔶 计数方式保存失败: {e}")

    def _update_statistics(self, actors: list[ActorInfo]):
        unique_all = {a.name for a in actors}
        if self._show_unique:
            total = len(unique_all)
        else:
            total = self._raw_count if self._raw_count > 0 else len(actors)
        # 议题 #157: 重复数 = 过滤后条目数 − 唯一名字数, 与计数方式切换无关, 恒为同名多余条目
        self.lbl_duplicate.setText(f"重复: {max(self._raw_count - len(unique_all), 0)}")
        # 议题 #147: 分项与「获取数据」模式用同一套缺失判定 (占位简介按缺处理),
        # 保证统计栏的 缺头像/缺简介/全缺 之和与取数模式选中的候选数一致; 完整=两者皆不缺。
        has_both = sum(
            1
            for a in actors
            if not PreparePreviewThread._is_missing_image(a) and not PreparePreviewThread._is_missing_info(a)
        )
        has_image_only = sum(
            1
            for a in actors
            if PreparePreviewThread._is_missing_info(a) and not PreparePreviewThread._is_missing_image(a)
        )
        has_info_only = sum(
            1
            for a in actors
            if PreparePreviewThread._is_missing_image(a) and not PreparePreviewThread._is_missing_info(a)
        )
        has_none = sum(
            1 for a in actors if PreparePreviewThread._is_missing_image(a) and PreparePreviewThread._is_missing_info(a)
        )
        backdrop_count = sum(1 for a in actors if a.has_backdrop)
        self.lbl_total.setText(f"总数: {total}")
        self.lbl_has_both.setText(f"完整: {has_both}")
        self.lbl_missing_image.setText(f"缺头像: {has_info_only}")
        self.lbl_missing_info.setText(f"缺简介: {has_image_only}")
        self.lbl_missing_all.setText(f"全缺: {has_none}")
        self.lbl_backdrop.setText(f"有背景图: {backdrop_count}")

    def _update_sync_button(self):
        to_sync = [a for a in self._actors if a.need_update_info or a.need_update_image or a.need_update_backdrop]
        sync_count = len(to_sync)
        self.btn_sync.setEnabled(sync_count > 0)
        self.btn_sync.setText(f"开始全部更新同步({sync_count} 项)" if sync_count > 0 else "开始全部更新同步")


IMAGE_SOURCE_NAMES = {
    "gfriends": "Gfriends网络头像",
    "graphis": "Graphis头像/背景",
    "minnano": "Minnano-av.com",
    "local": "本地头像保存目录",
}
INFO_SOURCE_NAMES = {
    "local": "本地演员名数据库",
    "wiki": "维基百科中文网站",
    "minnano": "Minnano-av.com",
    "database": "本地已保存数据库",
}


class _SourceQuickSettingsPanel(QGroupBox):
    """快速设置面板：头像/信息数据源拖拽排序 + 本地头像目录，改动即自动保存。

    数据源测试窗口与演员详情窗口共用，避免两处重复实现。
    """

    def __init__(self, parent=None, show_folder_row: bool = True, fixed_width: int | None = 300):
        super().__init__("快速设置", parent)
        if fixed_width is not None:
            self.setFixedWidth(fixed_width)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("头像数据源（拖拽排序）:"))
        self.image_list = QListWidget()
        self.image_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._fill_list(self.image_list, manager.config.actor_image_sources, IMAGE_SOURCE_NAMES)
        layout.addWidget(self.image_list)
        layout.addWidget(QLabel("信息数据源（拖拽排序）:"))
        self.info_list = QListWidget()
        self.info_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._fill_list(self.info_list, manager.config.actor_info_sources, INFO_SOURCE_NAMES)
        layout.addWidget(self.info_list)
        layout.addStretch()
        self._lists_expanded = False
        if show_folder_row:
            layout.addWidget(QLabel("本地头像目录:"))
            folder_row = QHBoxLayout()
            folder_row.setContentsMargins(-460, 0, 0, 0)
            folder_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.folder_edit = QLineEdit(manager.config.actor_photo_folder)
            self.folder_edit.setMinimumWidth(260)
            browse_btn = QPushButton("浏览")
            browse_btn.clicked.connect(self._browse_folder)
            folder_row.addWidget(self.folder_edit)
            folder_row.addWidget(browse_btn)
            layout.addLayout(folder_row)

        img_model = self.image_list.model()
        if img_model:
            img_model.rowsMoved.connect(self._save)
        info_model = self.info_list.model()
        if info_model:
            info_model.rowsMoved.connect(self._save)
        if getattr(self, "folder_edit", None) is not None:
            self.folder_edit.textChanged.connect(self._save)

    def set_lists_expanded(self, expanded: bool) -> None:
        """最大化时头像/信息两列表 1:1 分配面板纵向富余高度；还原时恢复默认效果。

        通过布局 stretch 实现：富余空间只按 stretch>0 分配，两列表 stretch=1、
        底部弹簧保持 0，最大化时弹簧分不到高度；还原时改回 0 即恢复原状。
        同值不重复触发布局，避免 resize 递归。
        """
        try:
            if self._lists_expanded == expanded:
                return
            self._lists_expanded = expanded
            _layout = self.layout()
            if _layout is not None:
                _layout.setStretchFactor(self.image_list, 1 if expanded else 0)
                _layout.setStretchFactor(self.info_list, 1 if expanded else 0)
        except Exception:
            pass

    @staticmethod
    def _fill_list(list_widget: QListWidget, sources: list[str], names: dict[str, str]):
        list_widget.clear()
        for src in sources:
            item = QListWidgetItem(names.get(src, src) or src)
            item.setData(Qt.ItemDataRole.UserRole, src)
            list_widget.addItem(item)

    def _browse_folder(self):
        folder_edit = getattr(self, "folder_edit", None)
        if folder_edit is None:
            return
        path = QFileDialog.getExistingDirectory(self, "选择本地头像目录", folder_edit.text())
        if path:
            folder_edit.setText(path)

    def _save(self, *args):
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_image_sources = [
            self.image_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.image_list.count())
        ]
        cfg.actor_info_sources = [
            self.info_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.info_list.count())
        ]
        folder_edit = getattr(self, "folder_edit", None)
        cfg.actor_photo_folder = (
            folder_edit.text().strip() if folder_edit is not None else manager.config.actor_photo_folder
        )
        manager._replace_config(cfg)
        manager.save()


class EmbyActorSettingsDialog(QDialog):
    """Emby 演员数据源设置：数据源优先级排序 + 本地目录 + Gfriends + 数据库开关。"""

    def __init__(self, parent=None):
        # 独立顶层窗口：parent 参数仅为兼容旧调用而保留，不再传入——管理器
        # 最小化/关闭不再级联影响设置窗口；调用方用 show() 单例复用（见 _on_open_settings）。
        super().__init__(None)
        self.setWindowTitle("Emby/Jellyfin 演员设置")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 关闭时由 Qt 销毁 C++ 对象，管理器侧的 destroyed 信号随之清空引用。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 无父独立窗口收不到管理器的 QSS 级联，字号规则自带一条，与管理器同值。
        self.setStyleSheet(f"QWidget {{ font-size: {_ui_font_pt()}; }}")
        self.setMinimumSize(480, 720)
        self.resize(480, 720)
        # 打开时默认在屏幕可用区居中；小屏时钳制，避免标题栏移出可视区。
        _w, _h = 480, 720
        try:
            screen = QGuiApplication.primaryScreen()
            avail = screen.availableGeometry() if screen is not None else None
            if avail is not None and avail.isValid():
                _w = min(_w, avail.width())
                _h = min(_h, avail.height())
                self.resize(_w, _h)
                self.move(
                    avail.x() + max(0, (avail.width() - _w) // 2),
                    avail.y() + max(0, (avail.height() - _h) // 2),
                )
        except Exception:
            pass
        layout = QVBoxLayout(self)

        filter_group = QGroupBox("Emby/Jellyfin 演员获取过滤")
        filter_layout = QVBoxLayout(filter_group)
        self.filter_only_check = QCheckBox("获取演员类型（不包含导演/编剧/制片人）")
        self.filter_only_check.setChecked(manager.config.actor_filter_only)
        filter_layout.addWidget(self.filter_only_check)
        self.deduplicate_check = QCheckBox("重复演员去重（按照服务器演员姓名合并）")
        self.deduplicate_check.setChecked(manager.config.actor_deduplicate)
        filter_layout.addWidget(self.deduplicate_check)
        layout.addWidget(filter_group)

        layout.addWidget(QLabel("头像数据源优先级（拖拽排序，上=优先）:"))
        self.image_list = QListWidget()
        self.image_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for src in manager.config.actor_image_sources:
            item = QListWidgetItem(IMAGE_SOURCE_NAMES.get(src, src) or src)
            item.setData(Qt.ItemDataRole.UserRole, src)
            self.image_list.addItem(item)
        layout.addWidget(self.image_list)

        layout.addWidget(QLabel("信息数据源优先级（拖拽排序，上=优先）:"))
        self.info_list = QListWidget()
        self.info_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        for src in manager.config.actor_info_sources:
            item = QListWidgetItem(INFO_SOURCE_NAMES.get(src, src) or src)
            item.setData(Qt.ItemDataRole.UserRole, src)
            self.info_list.addItem(item)
        layout.addWidget(self.info_list)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("本地头像目录:"))
        self.photo_folder_edit = QLineEdit(manager.config.actor_photo_folder)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_photo_folder)
        dir_row.addWidget(self.photo_folder_edit)
        dir_row.addWidget(browse_btn)
        layout.addLayout(dir_row)

        gf_row = QHBoxLayout()
        gf_row.addWidget(QLabel("Gfriends地址:"))
        self.gfriends_edit = QLineEdit(str(manager.config.gfriends_github))
        gf_row.addWidget(self.gfriends_edit)
        layout.addLayout(gf_row)

        btn_row = QHBoxLayout()
        self.use_db_check = QCheckBox("使用本地信息数据库")
        self.use_db_check.setChecked(manager.config.use_database)
        btn_row.addWidget(self.use_db_check)
        btn_row.addStretch()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _browse_photo_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择本地头像目录", self.photo_folder_edit.text())
        if path:
            self.photo_folder_edit.setText(path)

    def _save(self):
        image_sources = [self.image_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.image_list.count())]
        info_sources = [self.info_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.info_list.count())]
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_image_sources = image_sources
        cfg.actor_info_sources = info_sources
        cfg.actor_filter_only = self.filter_only_check.isChecked()
        cfg.actor_deduplicate = self.deduplicate_check.isChecked()
        cfg.actor_photo_folder = self.photo_folder_edit.text().strip()
        cfg.use_database = self.use_db_check.isChecked()
        try:
            cfg.gfriends_github = self.gfriends_edit.text().strip()
        except Exception as e:
            QMessageBox.warning(self, "提示", f"Gfriends 地址无效: {e}")
            return
        manager._replace_config(cfg)
        manager.save()
        # 非模态独立窗口：accept 只隐藏不销毁，下次打开会残留旧实例；直接关闭，
        # 靠 WA_DeleteOnClose 销毁，管理器侧 destroyed 信号随之清空引用。
        self.close()


class ActorSourceTestThread(_CancellableWorkerThread):
    """数据源测试线程：在后台执行网络请求，通过信号回传结果。"""

    progress = Signal(str)  # 实时状态（如“正在从XX获取头像/信息”），主线程更新状态栏
    result = Signal(list, object, object)  # logs, avatar_path, info_dict
    error = Signal(str)

    def __init__(self, parent, name: str, need_image: bool, need_info: bool):
        super().__init__(parent)
        self._name = name
        self._need_image = need_image
        self._need_info = need_info

    def run(self):
        try:
            # 走共享后台执行器（app 持久事件循环），与 FetchActorsThread/SyncThread 一致。
            # 议题 #87：此前自建一次性事件循环再关闭，数据源测试复用共享 curl_cffi
            # 客户端时其 cffi 定时器被注册到该一次性 loop 上；loop 关闭后定时器仍触发，
            # 回调里抛 "Event loop is closed"，Windows 上弹 Python-CFFI error。
            # 改走 executor.submit + result（提交到永不随线程关闭的后台循环），根除该弹窗。
            # progress 经 Signal 发回主线程（跨线程 queued 投递），执行器池线程直接 emit 安全。
            def _report(msg: str) -> None:
                try:
                    self.progress.emit(msg)
                except RuntimeError:
                    pass

            logs, avatar_path, info = self._run_coro(
                _actor_source_test_execute(
                    self._name, self._need_image, self._need_info, progress_callback=_report
                )
            )
            self.result.emit(logs, avatar_path, info)
        except _WorkerCancelled:
            return
        except Exception as e:
            self.error.emit(str(e))


async def _actor_source_test_execute(
    name: str,
    need_image: bool,
    need_info: bool,
    progress_callback=None,
) -> tuple[list[str], str | None, object]:
    """纯数据版本：不操作 UI，返回 (logs, avatar_path, info)。

    progress_callback(msg): 逐源开始前回调，由调用方经 Signal 转发到主线程做实时状态显示。
    """

    def _report(msg: str) -> None:
        if progress_callback is not None:
            try:
                progress_callback(msg)
            except Exception:
                pass

    # 与右侧快速设置面板文案保持一致的状态提示（顶部红字实时状态用，不写入底部结果框）。
    _IMAGE_PROGRESS = {
        "local": "正在从本地头像保存目录获取头像",
        "minnano": "正在从Minnano-av.com获取头像",
        "gfriends": "正在从Gfriends仓库获取网络头像",
        "graphis": "正在从Graphis网站获取头像/背景",
    }
    _INFO_PROGRESS = {
        "minnano": "正在从Minnano-av.com获取信息",
        "local": "正在从本地演员名数据库获取信息",
        "wiki": "正在从维基百科中文网站获取信息",
        "database": "正在从本地已保存数据库获取信息",
    }
    # 底部结果框展示名（用户指定文案）。
    _IMAGE_RESULT_NAMES = {
        "local": "本地头像目录缓存",
        "minnano": "Minnano-av.com",
        "gfriends": "Gfriends网络头像",
        "graphis": "Graphis网站头像",
    }
    _INFO_RESULT_NAMES = {
        "minnano": "Minnano-av信息",
        "local": "本地演员名数据库",
        "wiki": "维基百科中文网站",
        "database": "本地已保存数据库",
    }

    logs: list[str] = []
    avatar_path: str | None = None
    info: object = None
    actor = ActorInfo(name=name, actor_id="", server_id="")

    if need_image:
        gfriends_index = None
        try:
            gfriends_index = await get_gfriends_index()
        except Exception:
            pass
        for src in manager.config.actor_image_sources:
            _report(_IMAGE_PROGRESS.get(src, f"正在从{src}获取头像"))
            result: object = None
            try:
                if src == "gfriends" and gfriends_index:
                    result = await from_gfriends(actor, gfriends_index, resources.u("emby_actor_cache"))
                elif src == "graphis":
                    result = await from_graphis(actor, resources.u("emby_actor_cache"))
                elif src == "minnano":
                    result = await from_minnano_image(actor, resources.u("emby_actor_cache"))
                elif src == "local":
                    result = from_local_avatar(actor, manager.config.actor_photo_folder)
                else:
                    logs.append(f"{_IMAGE_RESULT_NAMES.get(src, src)}: 未知数据源")
                    continue
            except Exception as e:
                logs.append(f"{_IMAGE_RESULT_NAMES.get(src, src)}: ❌ 异常 {e}")
                continue
            if result:
                logs.append(f"{_IMAGE_RESULT_NAMES.get(src, src)}: ✅ 已命中")
                if isinstance(result, (str, Path)) and Path(result).exists():
                    avatar_path = str(result)
                elif isinstance(result, tuple) and result and Path(result[0]).exists():
                    avatar_path = str(result[0])
            else:
                logs.append(f"{_IMAGE_RESULT_NAMES.get(src, src)}: ❌ 未命中")

    if need_info:
        for src in manager.config.actor_info_sources:
            _report(_INFO_PROGRESS.get(src, f"正在从{src}获取信息"))
            try:
                ok, desc, data = await fetch_actor_info_from_source(actor, src)
            except Exception as e:
                logs.append(f"{_INFO_RESULT_NAMES.get(src, src)}: ❌ 异常 {e}")
                continue
            _display = _INFO_RESULT_NAMES.get(src, src)
            if ok:
                _detail = ""
                if "（" in desc and "）" in desc:
                    try:
                        _detail = desc.split("（", 1)[1].rsplit("）", 1)[0].replace(" ", "")
                    except Exception:
                        _detail = ""
                logs.append(f"{_display}: ✅ 已命中{_detail and f'，{_detail}'}")
            else:
                logs.append(f"{_display}: ❌ 未命中")
            if ok and data:
                if info is None:
                    info = data
                else:
                    # 多源合并：后命中的源只补全空字段，不覆盖已有内容；
                    # 简介保留更长者，避免 wiki 长简介被本地空/短简介覆盖导致预览空白。
                    try:
                        if getattr(info, "birthday", "") in ("", "0000-00-00") and getattr(
                            data, "birthday", ""
                        ) not in ("", "0000-00-00"):
                            info.birthday = data.birthday
                        if getattr(info, "year", "") in ("", "0000") and getattr(
                            data, "year", ""
                        ) not in ("", "0000"):
                            info.year = data.year
                        _old_ov = getattr(info, "overview", "") or ""
                        _new_ov = getattr(data, "overview", "") or ""
                        if _new_ov and (not _old_ov or len(_new_ov) > len(_old_ov)):
                            info.overview = _new_ov
                        for _f in ("locations", "taglines", "tags", "genres"):
                            _old = list(getattr(info, _f, None) or [])
                            _new = list(getattr(data, _f, None) or [])
                            if _new and not _old:
                                setattr(info, _f, _new)
                            elif _new:
                                _merged = _old + [x for x in _new if x not in _old]
                                setattr(info, _f, _merged)
                        _old_pid = getattr(info, "provider_ids", None) or {}
                        _new_pid = getattr(data, "provider_ids", None) or {}
                        if _new_pid:
                            try:
                                _old_pid.update(_new_pid)
                            except Exception:
                                pass
                    except Exception:
                        pass
    return logs, avatar_path, info


class ActorSourceTestDialog(QDialog):
    """数据源测试窗口：按配置的数据源优先级逐源尝试获取头像/简介，展示各源结果。

    “更新数据”把本次获取到的头像/简介写回 Emby/Jellyfin 服务器对应演员；
    空字段保留服务器原数据（update_person_info 只写非空新值）。
    """

    _update_done = Signal(bool, str)

    def __init__(self, parent=None):
        # 独立顶层窗口：parent 参数仅为兼容旧调用而保留，不再传入——管理器
        # 最小化/关闭不再级联影响测试窗口；调用方用 show() 单例复用（见 _on_open_test_source）。
        super().__init__(None)
        self.setWindowTitle("数据源测试")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # 关闭时由 Qt 销毁 C++ 对象（closeEvent 已先取消后台线程），
        # 管理器侧的 destroyed 信号随之清空引用。
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        # 无父独立窗口收不到管理器的 QSS 级联，字号规则自带一条，与管理器同值；
        # 蓝色主按钮样式也自带（与管理器 QPushButton#btnPrimary 同值）。
        self.setStyleSheet(
            f"QWidget {{ font-size: {_ui_font_pt()}; }}"
            "QPushButton#btnPrimary { background-color: #1565c0; color: #ffffff; }"
            "QPushButton#btnPrimary:hover { background-color: #1976d2; }"
        )
        self.setMinimumSize(1080, 720)
        self.resize(1080, 720)
        # 打开时默认在屏幕可用区居中；小屏时钳制，避免标题栏移出可视区。
        # 与主窗口一致：使用 frameGeometry 精确计算外框居中，原生窗口未创建时延后一次。
        _w, _h = 1080, 720
        def _center_dialog(avail_rect):
            frame = self.frameGeometry()
            x = avail_rect.x() + max(0, (avail_rect.width() - frame.width()) // 2)
            y = avail_rect.y() + max(0, (avail_rect.height() - frame.height()) // 2)
            self.move(max(x, avail_rect.x()), max(y, avail_rect.y()))
        try:
            screen = QGuiApplication.primaryScreen()
            avail = screen.availableGeometry() if screen is not None else None
            if avail is not None and avail.isValid():
                _w = min(_w, avail.width())
                _h = min(_h, avail.height())
                self.resize(_w, _h)
                if self.windowHandle() is not None:
                    _center_dialog(avail)
                else:
                    QTimer.singleShot(0, lambda av=avail: _center_dialog(av))
        except Exception:
            pass
        root = QVBoxLayout(self)

        # 上部内容容器：顶部输入行 + 主体三列 + 底部标题行，整体作为分割条上窗格，
        # 与结果框之间可上下拖拽分配高度。
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        # 顶部：演员姓名输入框直达按钮左边界；实时状态红字叠在输入框内部右侧。
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("演员姓名："))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("输入演员名（如：三上悠亚）")
        self.name_edit.returnPressed.connect(lambda: self._run(True, True))
        name_row.addWidget(self.name_edit, stretch=1)
        # 实时状态：QLabel 以输入框为父控件浮于框内右侧，点击穿透不影响编辑；
        # 右侧预留文本边距，演员名与状态不重叠。轮换显示“正在从XX获取头像/信息”避免无反馈。
        self.status_label = QLabel(self.name_edit)
        self.status_label.setStyleSheet("color: #c00000; background: transparent;")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.status_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.status_label.setText("")
        self.status_label.hide()
        self.name_edit.installEventFilter(self)
        self.btn_both = QPushButton("获取头像和简介")
        self.btn_both.setObjectName("btnPrimary")
        name_row.addWidget(self.btn_both)
        # 更新数据：把本次获取到的头像/简介写入服务器对应演员（空字段保留原数据）。
        self.btn_update = QPushButton("更新数据")
        self.btn_update.setObjectName("btnPrimary")
        name_row.addWidget(self.btn_update)
        top_layout.addLayout(name_row)
        QTimer.singleShot(0, self._layout_status_overlay)

        # 主体：左(头像) + 中(信息字段表) + 右(快速设置面板)，宽度 1:2:1，随窗口同步缩放
        main_row = QHBoxLayout()

        # 左列：头像预览 + 获取头像（预览框按列宽等比放大，见 _fit_avatar_frame）
        left_col = QVBoxLayout()
        self.avatar_label = QLabel("头像预览")
        # 最小值只做显示下限，不跟随显示尺寸：若用 setFixedSize
        # 把最小锁成当前显示尺寸，QSplitter 会以该最小值钳住上窗格，导致结果框
        # 只能向下拉、向上拉不动。此处最小恒定（宽 190 与原来一致、高降到 196），
        # 显示尺寸只走最大上限（见 _fit_avatar_frame）。
        self.avatar_label.setMinimumSize(190, 196)
        self.avatar_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar_label.setStyleSheet("border: 1px solid #ccc; color: #888;")
        left_col.addStretch()
        # stretch=1 让富余垂直空间优先给预览框（上限仍受 _fit_avatar_frame 的
        # maximumSize 钳制）；水平不设对齐，预览框撑满整列、与“获取头像”按钮同宽。
        # 最小值恒定 190x196 不抬高 QSplitter 上窗格的最小高度，结果框可上下双向拖拽。
        left_col.addWidget(self.avatar_label, 1)
        left_col.addStretch()
        self.btn_image = QPushButton("获取头像")
        self.btn_image.setObjectName("btnPrimary")
        left_col.addWidget(self.btn_image)
        self._left_col = left_col
        main_row.addLayout(left_col, stretch=1)

        # 中列：详细信息预览（字段/值）+ 获取信息
        info_col = QVBoxLayout()
        info_col.addWidget(QLabel("详细信息预览:"))
        self.info_table = QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["字段", "值"])
        h_header = self.info_table.horizontalHeader()
        if h_header:
            h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v_header = self.info_table.verticalHeader()
        if v_header:
            v_header.setVisible(False)
        self.info_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.info_table.setWordWrap(True)
        self.info_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.info_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        # 值列用只读编辑框承载，此处再把表格自身的选中高亮去掉，避免出现蓝色背景。
        self.info_table.setStyleSheet(
            "QTableWidget::item:selected { background: palette(base); color: palette(text); }"
            "QTableWidget::item:focus { border: none; }"
        )
        self.info_table.installEventFilter(self)
        info_col.addWidget(self.info_table)
        self.btn_info = QPushButton("获取信息")
        self.btn_info.setObjectName("btnPrimary")
        info_col.addWidget(self.btn_info)
        # 记录对话框与两按钮默认高度：最大化时按钮高度随对话框高度同步拉升，还原时恢复
        # （见 _sync_panel_stretch）。最小化/普通窗口不做任何改动。
        self._dialog_base_h = max(1, self.height() or 720)
        self._btn_image_base_h = self.btn_image.sizeHint().height()
        self._btn_info_base_h = self.btn_info.sizeHint().height()
        main_row.addLayout(info_col, stretch=2)

        # 右列：快速设置面板（改即自动保存；本地头像目录移到底部与结果同行，此处隐藏；
        # 释放固定 300 宽，按 1:2:1 的 1 份随窗口缩放）
        panel = _SourceQuickSettingsPanel(self, show_folder_row=False, fixed_width=None)
        panel.setMinimumWidth(200)
        self._panel = panel
        # 面板自身尺寸变化后同步底部盒：面板 Resize 事件里读到的已是布局后的最终宽度，
        # 专治最大化→还原等多帧 resize 中对话框 resizeEvent 读到旧值、盒宽卡死的问题。
        panel.installEventFilter(self)
        main_row.addWidget(panel, stretch=1)

        top_layout.addLayout(main_row)
        self._main_row = main_row

        # 底部标题行：左“各数据源结果”，右“本地头像目录”+输入框+浏览。
        # 输入框盒宽度随上面板同步、右对齐到对话框右边缘，冒号对准“获取信息”按钮右边界。
        bottom_header = QHBoxLayout()
        bottom_header.addWidget(QLabel("各数据源结果:"))
        bottom_header.addStretch(1)
        bottom_header.addWidget(QLabel("本地头像目录:"))
        folder_box = QWidget()
        folder_box.setFixedWidth(300)
        folder_layout = QHBoxLayout(folder_box)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        self.folder_edit = QLineEdit(manager.config.actor_photo_folder)
        self.folder_edit.setCursorPosition(0)
        folder_browse_btn = QPushButton("浏览")
        folder_browse_btn.setObjectName("btnPrimary")
        self._folder_browse_btn = folder_browse_btn
        folder_browse_btn.clicked.connect(self._browse_folder)
        folder_layout.addWidget(self.folder_edit)
        folder_layout.addWidget(folder_browse_btn)
        bottom_header.addWidget(folder_box)
        self._folder_box = folder_box
        top_layout.addLayout(bottom_header)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        # 各数据源结果框可上下拖拽调高度：上部内容与结果框之间加垂直分割条；
        # 默认高度保持 150（首帧布局后 _init_result_splitter 设置），重开窗口恢复默认。
        self._result_splitter = QSplitter(Qt.Orientation.Vertical)
        self._result_splitter.addWidget(top_widget)
        self._result_splitter.addWidget(self.result_text)
        self._result_splitter.setChildrenCollapsible(False)
        self._result_splitter.setStretchFactor(0, 1)
        self._result_splitter.setStretchFactor(1, 0)
        # 用户亲手拖过分割条后不再自动纠正高度。
        self._result_user_moved = False
        self._result_splitter.splitterMoved.connect(self._on_result_splitter_moved)
        root.addWidget(self._result_splitter, stretch=1)

        self.btn_both.clicked.connect(lambda: self._run(True, True))
        self.btn_image.clicked.connect(lambda: self._run(True, False))
        self.btn_info.clicked.connect(lambda: self._run(False, True))
        self.btn_update.clicked.connect(self._on_update)
        self._update_done.connect(self._on_update_done)
        self.folder_edit.textChanged.connect(self._save_folder)
        self._avatar_pixmap = None
        self._thread = None
        # 更新数据用的已获取快照：_run 开始时清空，_on_result 成功时写入；
        # 只有拿到头像或详细信息后，更新按钮才会执行写入。
        self._fetched_name = ""
        self._fetched_avatar = None
        self._fetched_info = None
        self._updating = False
        # 最大化时随高度同步拉升的顶行控件默认高度（见 _sync_panel_stretch）：
        # 获取头像和简介/更新数据/浏览三按钮 + 演员名输入框 + 本地头像目录输入框。
        self._btn_both_base_h = self.btn_both.sizeHint().height()
        self._btn_update_base_h = self.btn_update.sizeHint().height()
        self._browse_btn_base_h = self._folder_browse_btn.sizeHint().height()
        self._name_edit_base_h = self.name_edit.sizeHint().height()
        self._folder_edit_base_h = self.folder_edit.sizeHint().height()
        # 布局请求在事件分发中同步执行完布局，延迟一拍读到的即最终几何，
        # 兜底多帧 resize（最大化→还原）中各同步读取拿到的旧值。
        self.installEventFilter(self)

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(self, "选择本地头像目录", self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)
            self.folder_edit.setCursorPosition(0)

    def _save_folder(self):
        cfg = manager.config.model_copy(deep=True)
        cfg.actor_photo_folder = self.folder_edit.text().strip()
        manager._replace_config(cfg)
        manager.save()

    def closeEvent(self, event):
        thread = getattr(self, "_thread", None)
        if thread is not None:
            try:
                thread.result.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                thread.progress.disconnect()
            except (TypeError, RuntimeError):
                pass
            try:
                thread.error.disconnect()
            except (TypeError, RuntimeError):
                pass
            thread.cancel()
            if thread.isRunning() and not thread.wait(5000):
                _detach_running_thread(thread)
        super().closeEvent(event)

    def _set_status(self, msg: str) -> None:
        """框内右侧红字状态：为空时隐藏并恢复输入框边距，否则显示并预留不重叠边距。"""
        try:
            label = self.status_label
            edit = self.name_edit
        except (AttributeError, RuntimeError):
            return
        try:
            label.setText(msg or "")
            if not msg:
                label.hide()
                edit.setTextMargins(0, 0, 0, 0)
                return
            label.show()
            self._layout_status_overlay()
        except (AttributeError, RuntimeError):
            pass

    def _layout_status_overlay(self) -> None:
        """把状态 QLabel 贴到输入框内部右侧，并给输入框留出右侧文本边距防重叠。
        右侧留 6px 空隙，避免遮住输入框圆角边框。"""
        try:
            label = self.status_label
            edit = self.name_edit
        except (AttributeError, RuntimeError):
            return
        try:
            if not label.text():
                return
            margin = 6
            hint = label.sizeHint()
            max_w = max(0, int(edit.width() * 0.8))
            w = min(max(0, hint.width() + margin * 2), max_w) if max_w > 0 else hint.width()
            w = max(w, 10)
            h = max(edit.height(), 10)
            label.setGeometry(edit.width() - w - 6, 0, w, h)
            label.raise_()
            edit.setTextMargins(0, 0, w + 8, 0)
        except (AttributeError, RuntimeError, ValueError):
            pass

    def _set_running(self, running: bool) -> None:
        for btn in (self.btn_both, self.btn_image, self.btn_info, self.btn_update):
            try:
                btn.setEnabled(not running)
            except RuntimeError:
                pass
        if running:
            self.btn_both.setText("获取中")
        else:
            self.btn_both.setText("获取头像和简介")

    def _run(self, need_image: bool, need_info: bool):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入演员姓名")
            return
        old = getattr(self, "_thread", None)
        if old is not None and old.isRunning():
            QMessageBox.information(self, "提示", "正在获取中，请稍候")
            return
        if getattr(self, "_updating", False):
            QMessageBox.information(self, "提示", "正在更新数据，请稍候")
            return
        kinds = []
        if need_image:
            kinds.append("头像")
        if need_info:
            kinds.append("简介")
        start_msg = f"正在为“{name}”获取{'和'.join(kinds)}"
        self._set_status(start_msg)
        self.result_text.clear()
        # 新一轮获取开始即清空旧快照：只有本轮拿到数据后，更新按钮才会执行写入。
        self._fetched_name = name
        self._fetched_avatar = None
        self._fetched_info = None
        self._set_running(True)
        self._thread = ActorSourceTestThread(self, name, need_image, need_info)
        self._thread.progress.connect(self._on_progress)
        self._thread.result.connect(self._on_result)
        self._thread.error.connect(self._on_error)
        self._thread.finished.connect(lambda: self._set_running(False))
        self._thread.start()

    def _on_progress(self, msg: str):
        self._set_status(msg)

    def _on_result(self, logs: list[str], avatar_path: str | None, info: object):
        # 中间进度只显示在顶部输入框右侧红字状态，不写入底部结果框；此处只追加最终各源结论。
        for log in logs:
            self.result_text.append(log)
        self._set_status("")
        self._set_running(False)
        if avatar_path and Path(avatar_path).exists():
            self._show_avatar(avatar_path)
            self._fetched_avatar = avatar_path
        if info:
            self._populate_info_table(info)
            try:
                from ..models.emby import EMbyActressInfo

                if isinstance(info, EMbyActressInfo):
                    self._fetched_info = info
            except Exception:
                pass

    def _on_error(self, msg: str):
        self._set_status(f"❌ 错误: {msg}")
        self.result_text.append(f"❌ 错误: {msg}")
        self._set_running(False)

    @staticmethod
    def _is_blank(value: object) -> bool:
        """空/None/占位零值（生日 0000-00-00、年份 0000）一律视为“无数据”，更新时保留服务器原值。"""
        if value is None:
            return True
        if isinstance(value, str):
            s = value.strip()
            return not s or s in ("0000-00-00", "0000")
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) == 0
        return False

    def _has_fetched_data(self) -> bool:
        """本次是否拿到可更新的数据：头像文件存在，或简介任一字段有具体值。"""
        try:
            if self._fetched_avatar and Path(self._fetched_avatar).exists():
                return True
        except Exception:
            pass
        info = getattr(self, "_fetched_info", None)
        if info is None:
            return False
        try:
            if not self._is_blank(getattr(info, "overview", "")):
                return True
            if not self._is_blank(getattr(info, "birthday", "")):
                return True
            if not self._is_blank(getattr(info, "year", "")):
                return True
            if getattr(info, "locations", None):
                return True
            if getattr(info, "taglines", None):
                return True
        except Exception:
            pass
        return False

    def _on_update(self):
        """更新数据：把本次获取到的头像/简介写入 Emby/Jellyfin 服务器对应演员。

        未连接服务器时提示去演员管理器主页面连接；未获取到数据时不执行；
        空字段保留服务器原数据（见 _do_update_async，只写非空新值）。
        """
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "请输入演员姓名")
            return
        old = getattr(self, "_thread", None)
        if old is not None and old.isRunning():
            QMessageBox.information(self, "提示", "正在获取中，请稍候")
            return
        if getattr(self, "_updating", False):
            QMessageBox.information(self, "提示", "正在更新数据，请稍候")
            return
        if name != (getattr(self, "_fetched_name", "") or "") or not self._has_fetched_data():
            QMessageBox.information(self, "提示", "请先获取头像或简介数据，再更新")
            return
        if not manager.config.emby_url or not manager.config.api_key:
            QMessageBox.warning(self, "提示", "请先在演员管理器主页面连接 Emby/Jellyfin 服务器")
            return
        # 快照：后台更新期间用户改动界面不影响本次写入内容。
        info = self._fetched_info
        try:
            _avatar = self._fetched_avatar if self._fetched_avatar and Path(self._fetched_avatar).exists() else None
        except Exception:
            _avatar = None
        _overview = str(getattr(info, "overview", "") or "") if info is not None else ""
        _birthday = str(getattr(info, "birthday", "") or "") if info is not None else ""
        _year = str(getattr(info, "year", "") or "") if info is not None else ""
        _locations = list(getattr(info, "locations", None) or []) if info is not None else []
        _taglines = list(getattr(info, "taglines", None) or []) if info is not None else []
        self._updating = True
        try:
            self.btn_update.setEnabled(False)
            self.btn_update.setText("更新中")
        except RuntimeError:
            pass
        self._set_status(f"正在更新“{name}”到服务器...")
        try:
            future = executor.submit(
                self._do_update_async(name, _avatar, _overview, _birthday, _year, _locations, _taglines)
            )
        except Exception as e:
            self._updating = False
            try:
                self.btn_update.setEnabled(True)
                self.btn_update.setText("更新数据")
            except RuntimeError:
                pass
            self._set_status("")
            QMessageBox.critical(self, "更新失败", f"❌ 更新任务提交失败: {e}")
            return

        def _emit(fut):
            try:
                self._update_done.emit(*_future_result_or(fut, (False, "❌ 更新失败")))
            except RuntimeError:
                pass

        future.add_done_callback(_emit)

    async def _do_update_async(
        self,
        name: str,
        avatar_path: str | None,
        overview: str,
        birthday: str,
        year: str,
        locations: list,
        taglines: list,
    ) -> tuple[bool, str]:
        from .emby_actor_manager import _ACTOR_DETAIL_CACHE, _sync_actor_async, fetch_actor_detail
        from .emby_shared import _build_jellyfin_headers, _emby_api_prefix, _emby_get_json

        try:
            # 存活探测：配置里有地址/密钥不代表此刻连通，连不上就提示去主页面连接。
            resp, _err = await _emby_get_json(
                f"{_emby_api_prefix()}/System/Info",
                headers=_build_jellyfin_headers(),
            )
            if not resp:
                return False, "⚠️ 未连接到 Emby/Jellyfin 服务器，请先在演员管理器主页面连接后再更新"
            detail = await fetch_actor_detail(name)
            if not detail or not detail.get("Id"):
                return False, f"❌ 服务器中未找到演员“{name}”，请确认该演员已在媒体库中"
            actor = ActorInfo(
                name=detail.get("Name") or name,
                actor_id=detail.get("Id", ""),
                server_id=detail.get("ServerId", ""),
            )
            # 服务器现有值全部带上：空字段回填既不覆盖，也避免 Emby 空引用 400。
            actor.existing_overview = detail.get("Overview") or ""
            actor.existing_taglines = detail.get("Taglines") or []
            actor.existing_production_year = detail.get("ProductionYear")
            actor.existing_premiere_date = detail.get("PremiereDate") or ""
            actor.existing_production_locations = detail.get("ProductionLocations") or []
            actor.existing_provider_ids = detail.get("ProviderIds") or {}
            actor.existing_genres = detail.get("Genres") or []
            actor.existing_tags = detail.get("Tags") or []
            # 只有有具体值/图像的字段才记为新值写入；空一律保留服务器原数据。
            need_info = False
            if (overview or "").strip():
                actor.new_overview = overview
                need_info = True
            _tags = [str(t).strip() for t in (taglines or []) if str(t).strip()]
            if _tags:
                actor.new_taglines = _tags
                need_info = True
            _locs = [str(v).strip() for v in (locations or []) if str(v).strip()]
            if _locs:
                actor.new_production_locations = _locs
                need_info = True
            if normalize_premiere_date(birthday):
                actor.new_premiere_date = birthday
                need_info = True
            if normalize_production_year(year) is not None:
                actor.new_production_year = normalize_production_year(year)
                need_info = True
            need_image = False
            if avatar_path:
                try:
                    if Path(avatar_path).exists():
                        actor.new_image_path = avatar_path
                        need_image = True
                except Exception:
                    pass
            if not need_info and not need_image:
                return False, "本次获取到的数据均为空，已保留服务器原数据，未执行更新"
            actor.need_update_info = need_info
            actor.need_update_image = need_image
            sync_type = "both" if (need_info and need_image) else ("image" if need_image else "info")
            ok, msg = await _sync_actor_async(actor, sync_type)
            if ok:
                try:
                    _ACTOR_DETAIL_CACHE.pop(name, None)
                except Exception:
                    pass
            return ok, msg
        except Exception as e:
            return False, f"❌ 更新异常: {e}"

    def _on_update_done(self, ok: bool, msg: str):
        self._updating = False
        try:
            self.btn_update.setEnabled(True)
            self.btn_update.setText("更新数据")
        except RuntimeError:
            return
        self._set_status("" if ok else "❌ 更新失败")
        try:
            self.result_text.append(msg)
        except RuntimeError:
            pass
        try:
            if ok:
                QMessageBox.information(self, "更新完成", msg)
            else:
                QMessageBox.warning(self, "提示", msg)
        except RuntimeError:
            pass

    @staticmethod
    def _format_overview(text: object) -> str:
        """简介格式化为一行一条：<br>/<p> 等转换行，去残留标签，空白行最多保留一个。"""
        import html as _html

        if not isinstance(text, str) or not text:
            return ""
        t = re.sub(r"(?i)<br\s*/?>", "\n", text)
        t = re.sub(r"(?i)</p\s*>", "\n", t)
        t = re.sub(r"(?i)<p[^>]*>", "", t)
        t = re.sub(r"<[^>]+>", "", t)
        # 合并被换行拆散的段落标题：“===== 个人资料\n=====”→“===== 个人资料 =====”。
        # 仅当某行以 ===== 开头但行内无收尾 =====、且下一行为纯 ===== 时合并；
        # 正常的单行标题无换行穿插，不受影响（与 wiki.py:_join_split_section_titles 同规则）。
        t = re.sub(r"(?m)^(={5,})[ \t]*([^=\n\s][^=\n]*?)[ \t]*\n[ \t]*(={5,})[ \t]*$", r"\1 \2 \3", t)
        try:
            t = _html.unescape(t)
        except Exception:
            pass
        t = t.replace("\r\n", "\n").replace("\r", "\n")
        lines = [ln.strip() for ln in t.split("\n")]
        # 去首尾空行，中间连续空行压成一个
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        out: list[str] = []
        _blank = False
        for ln in lines:
            if not ln:
                if not _blank:
                    out.append("")
                _blank = True
            else:
                out.append(ln)
                _blank = False
        return "\n".join(out)

    def _populate_info_table(self, info: object):
        from ..models.emby import EMbyActressInfo

        if not isinstance(info, EMbyActressInfo):
            return
        _overview = self._format_overview(info.overview or "")
        rows = [
            ("生日", info.birthday),
            ("年份", str(info.year) if info.year else ""),
            ("出生地", ", ".join(info.locations or [])),
            ("标签", ", ".join(info.taglines or [])),
            ("简介", _overview),
        ]
        # 切换前清除旧 cell widget，避免复用残留。
        try:
            for _r in range(5):
                try:
                    self.info_table.removeCellWidget(_r, 1)
                except Exception:
                    pass
        except Exception:
            pass
        self.info_table.setRowCount(len(rows))
        for r, (field, value) in enumerate(rows):
            self.info_table.setItem(r, 0, QTableWidgetItem(field))
            if r == 4:
                continue
            # 单行值用只读 QLineEdit 承载：不受表格选中高亮影响（无蓝底），框内可拖选复制。
            try:
                _edit = QLineEdit(str(value))
                _edit.setReadOnly(True)
                _edit.setFrame(False)
                _edit.setStyleSheet("QLineEdit { border: none; background: palette(base); }")
                self.info_table.setCellWidget(r, 1, _edit)
            except Exception:
                self.info_table.setItem(r, 1, QTableWidgetItem(str(value)))
        # 简介用只读 QTextEdit 承载：支持鼠标拖选复制，行内换行显示。
        try:
            _bio = QTextEdit()
            _bio.setReadOnly(True)
            _bio.setPlainText(_overview)
            _bio.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            _bio.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            _bio.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            _bio.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            _bio.setStyleSheet("QTextEdit { border: none; background: palette(base); }")
            _bio.setFrameStyle(0)
            self.info_table.setCellWidget(4, 1, _bio)
        except Exception:
            _item = QTableWidgetItem(_overview)
            _item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.info_table.setItem(4, 1, _item)
        self._fit_overview_row()
        # 填充后清除表格选中/当前格，避免值列出现蓝色选中背景。
        try:
            self.info_table.clearSelection()
        except Exception:
            pass
        # 列宽确定后文档换行高度才准确，下一帧再按最终宽度重算一次（重算后同样清选中）。
        try:
            QTimer.singleShot(0, self._fit_overview_row)
        except Exception:
            pass

    def _fit_overview_row(self) -> None:
        """简介行高：默认 8 倍行高，内容更高按文档高度撑高，到文字下方为止。

        不再填满表格视口：行高只与内容有关，表格剩余区域保持默认底色。
        末尾顺手清除选中，避免出现蓝色选中背景。"""
        try:
            _vh = self.info_table.verticalHeader()
            _base = (_vh.defaultSectionSize() if _vh is not None else 0) or 30
            for _r in range(4):
                try:
                    if self.info_table.rowHeight(_r) != _base:
                        self.info_table.setRowHeight(_r, _base)
                except Exception:
                    pass
            _default = _base * 8
            _content = 0
            try:
                _w = self.info_table.cellWidget(4, 1)
                if _w is not None:
                    _doc_h = _w.document().size().height()
                    _content = int(_doc_h + _w.contentsMargins().top() + _w.contentsMargins().bottom() + 12)
                else:
                    _it = self.info_table.item(4, 1)
                    if _it is not None:
                        _n = max(1, (_it.text() or "").count("\n") + 1)
                        _fm_h = self.info_table.fontMetrics().lineSpacing() or 16
                        _content = _n * _fm_h + 12
            except Exception:
                pass
            _want = max(_default, _content)
            if _want > 0 and self.info_table.rowHeight(4) != int(_want):
                self.info_table.setRowHeight(4, int(_want))
            try:
                self.info_table.clearSelection()
            except Exception:
                pass
        except Exception:
            pass

    def _show_avatar(self, path: str):
        from PyQt6.QtGui import QPixmap

        pix = QPixmap(path)
        if not pix.isNull():
            self._avatar_pixmap = pix
            self._rescale_avatar()

    def _rescale_avatar(self):
        pix = getattr(self, "_avatar_pixmap", None)
        if pix is None or pix.isNull():
            return
        target = self.avatar_label.size()
        if target.width() < 2 or target.height() < 2:
            return
        self.avatar_label.setPixmap(
            pix.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _fit_avatar_frame(self):
        """头像预览框左右扩展到左列整个可显示宽度，宽高比保持 190:310；高度不够时按高度回缩。
        宽度同时钳制在 1:2:1 公平份额内：读当前列宽做目标，在多帧 resize
        （最大化→还原）后单调收敛。只设最大上限、不碰最小值：最小恒为构造时的
        120x196，QSplitter 上窗格最小高度不再被头像显示尺寸撑住，结果框才能上下双向拖拽。"""
        try:
            row = getattr(self, "_main_row", None)
            col = getattr(self, "_left_col", None)
            if row is None or col is None:
                return
            items = [row.itemAt(i) for i in range(3)]
            if any(it is None for it in items):
                return
            g0, g1, g2 = (it.geometry() for it in items)
            # 用三列实际几何反推公平份额，不依赖边距/间距常量。
            # 目标宽度直接取公平份额（由总宽实时算出，放大/还原双向收敛）：不能再与
            # 当前列宽取 min——放大那帧列宽还是旧的窄值，min 会把目标钉死在旧宽度，
            # 列宽长不大、下一帧量到的还是窄值，左列卡死、头像框比快速设置窄。
            gaps = (g1.x() - g0.right() - 1) + (g2.x() - g1.right() - 1)
            fair = (g2.right() - g0.x() + 1 - gaps) / 4.0
            avail_w = int(fair)
            avail_h = g0.height() - self.btn_image.height() - col.spacing() * 3 - col.contentsMargins().top() - col.contentsMargins().bottom()
            if avail_w < 10 or avail_h < 10:
                return
            ratio = 310 / 190
            w, h = avail_w, int(round(avail_w * ratio))
            if h > avail_h:
                h, w = avail_h, int(round(avail_h / ratio))
            w, h = max(w, 10), max(h, 10)
            cur_max = self.avatar_label.maximumSize()
            if cur_max.width() != w or cur_max.height() != h:
                self.avatar_label.setMaximumSize(w, h)
        except Exception:
            pass

    def _sync_folder_box(self):
        """底部输入框盒宽度随上面板同步、右对齐，冒号对准“获取信息”按钮右边界。"""
        try:
            panel = getattr(self, "_panel", None)
            box = getattr(self, "_folder_box", None)
            if panel is None or box is None or panel.width() <= 0:
                return
            if box.width() != panel.width():
                box.setFixedWidth(panel.width())
        except Exception:
            pass

    def eventFilter(self, a0, a1):
        try:
            if a1 is not None:
                t = a1.type()
                if t == QEvent.Type.Resize and a0 is getattr(self, "_panel", None):
                    self._sync_folder_box()
                elif t == QEvent.Type.Resize and a0 is getattr(self, "name_edit", None):
                    self._layout_status_overlay()
                elif t == QEvent.Type.Resize and a0 is getattr(self, "info_table", None):
                    self._fit_overview_row()
                elif t == QEvent.Type.LayoutRequest and a0 is self:
                    QTimer.singleShot(0, self._after_layout)
                elif t == QEvent.Type.KeyPress and a0 is getattr(self, "info_table", None):
                    try:
                        if a1.matches(QKeySequence.StandardKey.Copy):
                            self._copy_info_selection()
                            return True
                    except Exception:
                        pass
        except Exception:
            pass
        return super().eventFilter(a0, a1)

    def _copy_info_selection(self) -> None:
        """复制信息表选中单元格文本（无选中时复制简介全文），供 Ctrl+C 用。"""
        try:
            _idx = self.info_table.selectedIndexes()
            _texts: list[str] = []
            if _idx:
                for _i in sorted(_idx, key=lambda x: (x.row(), x.column())):
                    if _i.column() == 1:
                        if _i.row() == 4:
                            _w = self.info_table.cellWidget(4, 1)
                            if _w is not None:
                                try:
                                    _cur = _w.textCursor()
                                    _texts.append(
                                        _cur.selectedText()
                                        if _cur.hasSelection()
                                        else _w.toPlainText()
                                    )
                                    continue
                                except Exception:
                                    pass
                        _w04 = None
                        try:
                            _w04 = self.info_table.cellWidget(_i.row(), _i.column())
                        except Exception:
                            _w04 = None
                        if _w04 is not None and isinstance(_w04, QLineEdit):
                            try:
                                _texts.append(
                                    _w04.selectedText() if _w04.hasSelectedText() else _w04.text()
                                )
                            except Exception:
                                _texts.append(_w04.text() or "")
                        else:
                            _it = self.info_table.item(_i.row(), _i.column())
                            if _it is not None:
                                _texts.append(_it.text() or "")
                _data = "\n".join(_texts).strip()
            else:
                _w = self.info_table.cellWidget(4, 1)
                _data = (_w.toPlainText() if _w is not None else "").strip()
            if _data:
                QApplication.clipboard().setText(_data)
        except Exception:
            pass

    def _sync_panel_stretch(self) -> None:
        """最大化时的专属效果，还原时全部恢复默认；按钮高度只在数值变化时设置。

        - 右侧头像/信息两列表 1:1 分配富余高度；
        - 按钮与输入框高度按对话框当前高度/默认高度的比例同步拉升：
          获取头像/获取信息/获取头像和简介/更新数据/浏览 + 演员名输入框 + 本地头像目录输入框。
        普通/最小化窗口时不做任何改动，与原来完全一致。
        """
        try:
            try:
                _max = self.isMaximized()
            except Exception:
                _max = False
            _panel = getattr(self, "_panel", None)
            if _panel is not None and hasattr(_panel, "set_lists_expanded"):
                try:
                    _panel.set_lists_expanded(bool(_max))
                except Exception:
                    pass
            try:
                _base_h = getattr(self, "_dialog_base_h", 0) or 0
                _cur_h = self.height() or 0
                _ratio = (_cur_h / _base_h) if (_max and _base_h > 0 and _cur_h > 0) else 1.0
            except Exception:
                _ratio = 1.0
            for _btn_name, _base_name in (
                ("btn_image", "_btn_image_base_h"),
                ("btn_info", "_btn_info_base_h"),
                ("btn_both", "_btn_both_base_h"),
                ("btn_update", "_btn_update_base_h"),
                ("_folder_browse_btn", "_browse_btn_base_h"),
                ("name_edit", "_name_edit_base_h"),
                ("folder_edit", "_folder_edit_base_h"),
            ):
                try:
                    _btn = getattr(self, _btn_name, None)
                    if _btn is None:
                        continue
                    _base = getattr(self, _base_name, 0) or 0
                    if _base <= 0:
                        try:
                            _base = _btn.sizeHint().height()
                        except Exception:
                            continue
                    _target = max(1, int(round(_base * _ratio)))
                    if _btn.minimumHeight() != _target:
                        _btn.setMinimumHeight(_target)
                except Exception:
                    pass
        except Exception:
            pass

    def changeEvent(self, event):
        super().changeEvent(event)
        try:
            if event is not None and event.type() == QEvent.Type.WindowStateChange:
                self._sync_panel_stretch()
        except Exception:
            pass

    def _after_layout(self):
        """布局执行完后按最终几何重算：盒宽跟随面板、头像框适配左列、头像重绘、框内状态对齐。
        各子函数幂等且有同值保护，不会引起新的布局请求，自收敛。"""
        try:
            self._init_result_splitter()
        except Exception:
            pass
        try:
            self._sync_panel_stretch()
        except Exception:
            pass
        try:
            self._layout_status_overlay()
        except Exception:
            pass
        try:
            self._fit_overview_row()
        except Exception:
            pass
        try:
            self._sync_folder_box()
        except Exception:
            pass
        try:
            self._fit_avatar_frame()
        except Exception:
            pass
        try:
            self._rescale_avatar()
        except Exception:
            pass

    def _on_result_splitter_moved(self, _pos: int, _index: int) -> None:
        self._result_user_moved = True

    def _init_result_splitter(self) -> None:
        """结果框默认 150 高：用户未拖过且当前不是 150 时纠正，已是 150 则不碰。

        布局稳定前会触发多次，值相等时 setSizes 不再进布局，自然收敛不循环；
        对话框关闭即销毁、重开是新实例，天然恢复默认高度，不做持久化。
        """
        if getattr(self, "_result_user_moved", False):
            return
        sp = getattr(self, "_result_splitter", None)
        if sp is None:
            return
        try:
            sizes = sp.sizes()
            if len(sizes) != 2 or sizes[1] == 150:
                return
            total = sp.height()
            if total <= 0:
                return
            want = 150
            sp.setSizes([max(0, total - want), want])
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        # 显示后布局几何才最终落定，下一帧把结果框定到默认 150 高。
        try:
            QTimer.singleShot(0, self._init_result_splitter)
        except Exception:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        try:
            self._sync_panel_stretch()
        except Exception:
            pass
        try:
            self._layout_status_overlay()
        except Exception:
            pass
        try:
            self._fit_overview_row()
        except Exception:
            pass
        try:
            self._sync_folder_box()
        except Exception:
            pass
        try:
            self._fit_avatar_frame()
        except Exception:
            pass
        try:
            self._rescale_avatar()
        except Exception:
            pass


class ActorDetailDialog(QDialog):
    """演员详情编辑对话框：左栏现有数据，右栏新数据（可编辑），右侧快速设置面板。"""

    _detail_done = Signal(str, object)

    def __init__(self, actor: ActorInfo, parent=None, on_synced=None):
        super().__init__(parent)
        self.actor = actor
        self.on_synced = on_synced
        self.setWindowTitle(f"演员详情 - {actor.name}")
        self.setMinimumSize(900, 580)
        root = QHBoxLayout(self)

        # 左栏：现有数据（Emby 当前）
        left = QGroupBox("现有数据")
        left_layout = QVBoxLayout(left)
        self.existing_avatar_label = QLabel("头像预览")
        self.existing_avatar_label.setFixedSize(130, 180)
        self.existing_avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.existing_avatar_label.setStyleSheet("border: 1px solid #ccc; color: #888;")
        left_layout.addWidget(self.existing_avatar_label)
        self.existing_info = QTextEdit()
        self.existing_info.setReadOnly(True)
        # 议题 #180: Emby 简介以 <br> 分行(服务器端渲染需要, 数据本身正确),
        # MDCx 详情展示把 <br> 还原为换行——仅此处替换, 不回写数据。
        self.existing_info.setPlainText(
            "简介: "
            + re.sub(r"<br\s*/?>", "\n", actor.existing_overview or "无", flags=re.IGNORECASE)
            + "\n生日: "
            + (actor.existing_premiere_date[:10] if actor.existing_premiere_date else "无")
            + "\n出生地: "
            + (", ".join(actor.existing_production_locations) if actor.existing_production_locations else "无")
            + "\n标签: "
            + (", ".join(actor.existing_taglines) if actor.existing_taglines else "无")
        )
        left_layout.addWidget(self.existing_info)
        root.addWidget(left)

        # 右栏：新数据（可编辑）
        right = QGroupBox("新数据（同步前可编辑）")
        right_layout = QVBoxLayout(right)
        self.new_avatar_label = QLabel("新头像预览")
        self.new_avatar_label.setFixedSize(130, 180)
        self.new_avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.new_avatar_label.setStyleSheet("border: 1px solid #ccc; color: #888;")
        right_layout.addWidget(self.new_avatar_label)
        right_layout.addWidget(QLabel("简介（可编辑）:"))
        self.overview_edit = QTextEdit()
        self.overview_edit.setPlainText(actor.new_overview)
        right_layout.addWidget(self.overview_edit)
        right_layout.addWidget(QLabel("信息（右键增删行，可编辑）:"))
        self.info_table = QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["字段", "值"])
        h_header = self.info_table.horizontalHeader()
        if h_header:
            h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        v_header = self.info_table.verticalHeader()
        if v_header:
            v_header.setVisible(False)
        self.info_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.info_table.customContextMenuRequested.connect(self._info_table_menu)
        self._populate_info_table()
        right_layout.addWidget(self.info_table)

        btn_row = QHBoxLayout()
        self.btn_fetch_image = QPushButton("获取头像")
        self.btn_fetch_info = QPushButton("获取信息")
        self.btn_sync_both = QPushButton("同步头像+简介")
        self.btn_sync_image = QPushButton("只同步头像")
        self.btn_sync_info = QPushButton("只同步简介")
        for b in (
            self.btn_fetch_image,
            self.btn_fetch_info,
            self.btn_sync_both,
            self.btn_sync_image,
            self.btn_sync_info,
        ):
            b.setObjectName("btnPrimary")
            btn_row.addWidget(b)
        right_layout.addLayout(btn_row)
        root.addWidget(right, stretch=1)

        # 右侧快速设置面板（改即保存）
        panel = _SourceQuickSettingsPanel(self)
        root.addWidget(panel)

        self.btn_fetch_image.clicked.connect(lambda: self._run_fetch_image())
        self.btn_fetch_info.clicked.connect(lambda: self._run_fetch_info())
        self.btn_sync_both.clicked.connect(lambda: self._run_sync("both"))
        self.btn_sync_image.clicked.connect(lambda: self._run_sync("image"))
        self.btn_sync_info.clicked.connect(lambda: self._run_sync("info"))

        self._detail_done.connect(self._on_detail_done)
        self._load_existing_avatar()
        if actor.new_image_path:
            self._show_new_avatar(actor.new_image_path)

    def _populate_info_table(self):
        actor = self.actor
        provider_ids = ", ".join(f"{k}:{v}" for k, v in actor.new_provider_ids.items())
        rows = [
            ("标签", ", ".join(actor.new_taglines)),
            ("年份", str(actor.new_production_year) if actor.new_production_year else ""),
            ("生日", actor.new_premiere_date),
            ("出生地", ", ".join(actor.new_production_locations)),
            ("外部ID", provider_ids),
        ]
        self.info_table.setRowCount(len(rows))
        for r, (field, value) in enumerate(rows):
            self.info_table.setItem(r, 0, QTableWidgetItem(field))
            self.info_table.setItem(r, 1, QTableWidgetItem(value))

    def _info_table_menu(self, pos):
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        add_action = menu.addAction("增加行")
        del_action = menu.addAction("删除行")
        chosen = menu.exec(self.info_table.viewport().mapToGlobal(pos))
        if chosen == add_action:
            row = self.info_table.rowCount()
            self.info_table.insertRow(row)
            self.info_table.setItem(row, 0, QTableWidgetItem(""))
            self.info_table.setItem(row, 1, QTableWidgetItem(""))
        elif chosen == del_action:
            self.info_table.removeRow(self.info_table.currentRow())

    def _load_existing_avatar(self):
        if not self.actor.has_image:
            self.existing_avatar_label.setText("无头像")
            return
        self.existing_avatar_label.setText("加载中...")
        try:
            future = executor.submit(self._download_existing_avatar())
        except Exception as e:
            self.existing_avatar_label.setText("头像加载失败")
            self.log(f"🔶 加载现有头像失败: {e}")
            return
        future.add_done_callback(lambda fut: self._detail_done.emit("existing_avatar", _future_result_or(fut, None)))

    async def _download_existing_avatar(self) -> str | None:
        from .emby_shared import _build_jellyfin_headers, _generate_server_url

        _, _, pic_url, _, _, _ = _generate_server_url(
            {"Name": self.actor.name, "Id": self.actor.actor_id, "ServerId": self.actor.server_id}
        )
        headers = _build_jellyfin_headers()
        async with manager.acquire_computed() as computed:
            body, err = await computed.async_client.get_content(pic_url, headers=headers, use_proxy=False)
        if not body:
            return None
        tmp = resources.u("emby_actor_cache") / f"emby_existing_{self.actor.actor_id}.jpg"
        tmp.write_bytes(body)
        return str(tmp)

    def _run_fetch_image(self):
        try:
            future = executor.submit(self._fetch_image())
        except Exception as e:
            self.log(f"🔶 获取头像失败: {e}")
            return
        future.add_done_callback(
            lambda fut: self._detail_done.emit("fetch_image", _future_result_or(fut, (False, None)))
        )

    async def _fetch_image(self) -> tuple[bool, str | None]:
        from .emby_actor_manager import from_gfriends, from_graphis, from_local_avatar, from_minnano_image

        gfriends_index = None
        try:
            gfriends_index = await get_gfriends_index()
        except Exception:
            pass
        for src in manager.config.actor_image_sources:
            result: object = None
            try:
                if src == "gfriends" and gfriends_index:
                    result = await from_gfriends(self.actor, gfriends_index, resources.u("emby_actor_cache"))
                elif src == "graphis":
                    result = await from_graphis(self.actor, resources.u("emby_actor_cache"))
                elif src == "minnano":
                    result = await from_minnano_image(self.actor, resources.u("emby_actor_cache"))
                elif src == "local":
                    result = from_local_avatar(self.actor, manager.config.actor_photo_folder)
            except Exception:
                continue
            if result:
                path = result[0] if isinstance(result, tuple) and result else result
                if isinstance(path, (str, Path)) and Path(path).exists():
                    self.actor.new_image_path = str(path)
                    self.actor.need_update_image = True
                    return True, str(path)
        return False, None

    def _run_fetch_info(self):
        try:
            future = executor.submit(search_actor_info(self.actor))
        except Exception as e:
            self.log(f"🔶 获取简介失败: {e}")
            return
        future.add_done_callback(lambda fut: self._detail_done.emit("fetch_info", _future_result_or(fut, False)))

    def _on_detail_done(self, action: str, result: object):
        if action == "existing_avatar":
            if result:
                self._show_pixmap(self.existing_avatar_label, str(result))
            else:
                self.existing_avatar_label.setText("无头像")
        elif action == "fetch_image":
            ok, path = result if isinstance(result, tuple) and len(result) == 2 else (False, None)
            if ok and path:
                self._show_new_avatar(path)
            else:
                self.new_avatar_label.setText("未获取到新头像")
        elif action == "fetch_info":
            if result:
                self.overview_edit.setPlainText(self.actor.new_overview)
                self._populate_info_table()
        elif action == "sync":
            ok, msg = result if isinstance(result, tuple) and len(result) == 2 else (False, str(result))
            self.btn_sync_both.setEnabled(True)
            self.btn_sync_image.setEnabled(True)
            self.btn_sync_info.setEnabled(True)
            QMessageBox.information(self, "同步结果", msg)
            if ok and self.on_synced:
                self.on_synced(self.actor)

    def _run_sync(self, sync_type: str):
        from .emby_actor_manager import sync_actor

        self._apply_edits()
        self.btn_sync_both.setEnabled(False)
        self.btn_sync_image.setEnabled(False)
        self.btn_sync_info.setEnabled(False)

        def _worker():
            try:
                result = sync_actor(self.actor, sync_type)
            except Exception:
                import traceback

                result = (False, f"同步异常: {traceback.format_exc()}")
            self._detail_done.emit("sync", result)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_edits(self):
        actor = self.actor
        actor.new_overview = self.overview_edit.toPlainText().strip()
        actor.new_taglines = []
        actor.new_production_locations = []
        actor.new_production_year = None
        actor.new_premiere_date = ""
        for r in range(self.info_table.rowCount()):
            field_item = self.info_table.item(r, 0)
            value_item = self.info_table.item(r, 1)
            if not field_item or not value_item:
                continue
            field = field_item.text().strip()
            value = value_item.text().strip()
            if field == "标签":
                actor.new_taglines = [x.strip() for x in value.split(",") if x.strip()]
            elif field == "年份":
                actor.new_production_year = int(value) if value.isdigit() else None
            elif field == "生日":
                actor.new_premiere_date = value
            elif field == "出生地":
                actor.new_production_locations = [x.strip() for x in value.split(",") if x.strip()]
            elif field == "外部ID":
                provider_ids: dict[str, str] = {}
                for part in value.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    if ":" in part:
                        k, v = part.split(":", 1)
                        provider_ids[k.strip()] = v.strip()
                actor.new_provider_ids = provider_ids
        if (
            actor.new_overview
            or actor.new_taglines
            or actor.new_production_year
            or actor.new_premiere_date
            or actor.new_provider_ids
        ):
            actor.need_update_info = True

    def _show_new_avatar(self, path: str):
        self._show_pixmap(self.new_avatar_label, path)

    @staticmethod
    def _show_pixmap(label: QLabel, path: str):
        from PyQt6.QtGui import QPixmap

        pix = QPixmap(path)
        if not pix.isNull():
            label.setPixmap(pix.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio))
