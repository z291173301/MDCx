import html
import math
import os
import platform
import re
import shutil
import threading
import time
import traceback
import webbrowser
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from PyQt6.QtCore import QEvent, QItemSelectionModel, QPoint, QPointF, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFontMetrics,
    QFontMetricsF,
    QGuiApplication,
    QHoverEvent,
    QIcon,
    QImage,
    QKeySequence,
    QPixmap,
    QShortcut,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QWIDGETSIZE_MAX,
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QSystemTrayIcon,
    QTableWidgetItem,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mdcx.base.file import (
    check_and_clean_files,
    get_success_list,
    movie_lists,
    newtdisk_creat_symlink,
    save_remain_list,
    save_remain_list_now,
    save_success_list,
)
from mdcx.base.image import add_del_extrafanart_copy
from mdcx.base.video import add_del_extras, add_del_theme_videos
from mdcx.base.web import RemoteVersion, check_theporndb_api_token, check_version, is_remote_version_newer
from mdcx.base.web_sync import get_text_sync
from mdcx.config.enums import NfoInclude, Switch, Website
from mdcx.config.extend import deal_url, get_movie_path_setting, parse_media_paths
from mdcx.config.manager import manager
from mdcx.config.resources import resources
from mdcx.consts import GITHUB_ISSUES_URL, GITHUB_RELEASES_URL, IS_WINDOWS, LOCAL_VERSION, VERSION_NAME
from mdcx.core.naming import NameRenderOptions, NamingTarget, render_name
from mdcx.core.network_check import (
    DEFAULT_SEPARATOR_WIDTH,
    NetworkCheckStatus,
    merge_site_check_cache,
    run_network_check,
    scrape_probe_ladder_text,
)
from mdcx.core.nfo import write_nfo
from mdcx.core.scrape_cache import ScrapeStateCache
from mdcx.core.scraper import again_search, get_remain_list, start_new_scrape
from mdcx.crawlers.fc2ppvdb import (
    FC2CMADB_BASE_URL,
    cookie_has_login_key,
    cookie_str_to_dict,
    fetch_article_info_with_warmup,
)
from mdcx.image import PreviewImageLoader
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.models.model_types import CrawlersResult, FileInfo, OtherInfo, ShowData
from mdcx.signals import signal_qt
from mdcx.tools.actress_db import ActressDB
from mdcx.tools.missing import check_missing_number
from mdcx.tools.subtitle import add_sub_for_all_video
from mdcx.utils import (
    add_html,
    add_html_plain_text,
    executor,
    get_current_time,
    get_used_time,
    kill_a_thread,
    split_path,
)
from mdcx.utils.file import (
    create_hardlink_sync,
    create_symlink_sync,
    delete_file_sync,
    open_file_thread,
    resolve_link_source_sync,
    resolve_success_record_source_sync,
)
from mdcx.utils.path import safe_rmtree
from mdcx.views.CustomClass import CustomScrollArea
from mdcx.views.donate_window import DonateDialog
from mdcx.views.MDCx import Ui_MDCx
from mdcx.views.similar_window import SimilarDialog

from ..cut_window import CutWindow
from .handlers import net_separator_width, show_netstatus
from .health_check import run_startup_health_checks
from .init import (
    DEFAULT_WINDOW_SIZE,
    Init_QSystemTrayIcon,
    Init_Singal,
    Init_Ui,
    _adaptive_window_sizes,
    apply_ui_scale_option_limits,
    init_QTreeWidget,
)
from .load_config import load_config
from .save_config import save_config
from .site_priority_dialog import apply_site_priority_theme
from .style import apply_application_palette, build_menu_style, set_dark_style, set_style

if TYPE_CHECKING:
    from PyQt6.QtGui import QMouseEvent


LINK_DIR_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
WINDOWS_RESERVED_DIR_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
DEFAULT_LINK_DIR_NAME = "unnamed"

# 检测网络面板「=」分隔线的字符数上下限与兜底值。QSS 里 #textBrowser_net_main 是
# Consolas 13px 等宽（实测单字宽 7px），按可视宽取整除即可铺满右边缘。
_NET_SEP_FALLBACK = 88  # 量不到可视宽时的历史值
_NET_SEP_MIN = 40  # 极窄窗口下的下限，保证不塌成一条短杠
_NET_SEP_MAX = 400  # 超宽屏兜顶，避免误量出成百上千个
_NET_SEP_VIEWPORT_SLACK = 64  # 可视宽与控件宽的合法差（边框 + QSS padding + 滚动条）
_NET_SEP_TEXT_PADDING = 4  # QSS `padding: 2px, 2px` 的左右合计
_NET_SEP_SCROLLBAR_FALLBACK = 16  # 量不到滚动条宽时的兜底（QSS 里竖向滚动条固定 16px）


class MyMAinWindow(QMainWindow):
    # 检测网络面板首屏只发一次；分隔线字符数随之只量一次并缓存（两态相同）。
    _net_startup_emitted = False
    _net_separator_chars_cache: int = 0
    # 检测报告内分隔线的字符数：必须在**主线程**点按钮时量好存这里——检测跑在
    # 工作线程里，不能去碰文本框（Qt 控件非线程安全）。worker 只读这个整数。
    _net_report_sep_chars: int = 0

    # region 信号量
    main_logs_show = pyqtSignal(str)  # 显示刮削日志信号
    main_logs_clear = pyqtSignal(str)  # 清空刮削日志信号
    req_logs_clear = pyqtSignal(str)  # 清空请求日志信号
    main_req_logs_show = pyqtSignal(str)  # 显示刮削后台日志信号
    net_logs_show = pyqtSignal(str)  # 显示网络检测日志信号
    set_javdb_cookie = pyqtSignal(str)  # 加载javdb cookie文本内容到设置页面
    set_javdb_status = pyqtSignal(str)  # javdb 检查状态更新
    set_fc2ppvdb_status = pyqtSignal(str)  # fc2ppvdb 检查状态更新
    set_javbus_cookie = pyqtSignal(str)  # 加载javbus cookie文本内容到设置页面
    set_javbus_status = pyqtSignal(str)  # javbus 检查状态更新
    exec_save_config = pyqtSignal()  # 主线程执行保存配置
    set_label_file_path = pyqtSignal(str)  # 主界面更新路径信息显示
    set_pic_pixmap = pyqtSignal(list, list)  # 主界面显示封面、缩略图
    set_pic_text = pyqtSignal(str)  # 主界面显示封面信息
    change_to_mainpage = pyqtSignal(str)  # 切换到主界面
    request_preview_images = pyqtSignal(str, str)  # 主线程刷新封面/缩略图预览（poster_path, thumb_path）
    label_result = pyqtSignal(str)
    pushButton_start_cap = pyqtSignal(str)
    pushButton_start_cap2 = pyqtSignal(str)
    pushButton_start_single_file = pyqtSignal(str)
    pushButton_add_sub_for_all_video = pyqtSignal(str)
    pushButton_show_pic_actor = pyqtSignal(str)
    pushButton_add_actor_info = pyqtSignal(str)
    pushButton_add_actor_pic = pyqtSignal(str)
    pushButton_add_actor_pic_kodi = pyqtSignal(str)
    pushButton_del_actor_folder = pyqtSignal(str)
    pushButton_check_and_clean_files = pyqtSignal(str)
    pushButton_move_mp4 = pyqtSignal(str)
    pushButton_find_missing_number = pyqtSignal(str)
    pushButton_cover_backfill_start = pyqtSignal(str)
    pushButton_actor_db_translate = pyqtSignal(str)
    pushButton_actor_db_link = pyqtSignal(str)
    pushButton_actor_db_sync_aliases = pyqtSignal(str)
    pushButton_actor_db_fill_minnano = pyqtSignal(str)
    pushButton_actor_db_fill_zh_javdb = pyqtSignal(str)
    pushButton_actor_db_clean_male = pyqtSignal(str)
    pushButton_actor_db_verify_tmdbid = pyqtSignal(str)
    pushButton_actor_db_check = pyqtSignal(str)
    pushButton_actor_db_update_nfo_tmdbid = pyqtSignal(str)
    actor_db_finished = pyqtSignal(str)  # task_id；空串表示恢复所有按钮
    label_show_version = pyqtSignal(str)
    version_check_done = pyqtSignal(bool)  # 版本检查完成（参数为是否有新版本），主线程执行 UI 操作
    net_check_done = pyqtSignal()  # 网络检测完成，主线程恢复按钮状态
    net_check_progress = pyqtSignal(int, int)  # 网络检测单项完成 (done, total)，主线程刷新按钮进度文本
    nfo_lib_data_loaded = pyqtSignal(str)  # NFO 库管理：后台读取 NFO 完成，主线程填充表单
    nfo_lib_images_changed = pyqtSignal(str)  # NFO 库管理：信息管理页裁剪封面完成，主线程只刷新两张预览图（不切页）
    nfo_lib_save_done = pyqtSignal(str)  # NFO 库管理：后台保存完成，主线程恢复按钮
    nfo_lib_batch_done = pyqtSignal(str)  # NFO 库管理：批量操作完成，主线程更新状态
    nfo_lib_batch_progress = pyqtSignal(str)  # NFO 库管理：批量操作进度，主线程更新标签

    # endregion

    def __init__(self, parent=None):
        super().__init__(parent)

        # region 初始化需要的变量
        self.localversion = LOCAL_VERSION  # 当前版本号(数值, 用于版本比较)
        self.version_display = f"{VERSION_NAME} ({LOCAL_VERSION})"  # 展示用: v2.0.0 (220260712)
        self.new_version = "\n🔍 点击检查最新版本"  # 有版本更新时在左下角显示的新版本信息
        self._notified_new_version: RemoteVersion | None = (
            None  # 已提示过的远端版本：12h 定时复查仅在发现更新的版本时再提示，避免同一版本重复刷屏
        )
        self.show_data: ShowData | None = None  # 当前树状图选中文件的数据
        self.img_path = None  # 当前树状图选中文件的图片地址
        self.m_drag = False  # 允许鼠标拖动的标识
        self.m_DragPosition: QPoint | None = None  # 鼠标拖动位置
        self.logs_counts = 0  # 日志次数（每1w次清屏）
        self.req_logs_counts = 0  # 日志次数（每1w次清屏）
        self.main_log_queue: deque[str] = deque()
        self.main_log_batch_size = 80
        self.main_log_max_count = 10000
        self.network_check_cancel_event: threading.Event | None = None
        self.network_check_future = None
        self.file_main_open_path = Path()  # 主界面打开的文件路径
        self.json_array: dict[str, ShowData] = {}  # 主界面右侧结果树状数据
        self.preview_request_id = 0  # 主界面图片预览请求序号，用于丢弃过期加载结果
        # 议题 #144: 原图 pixmap 缓存, 显示层按封面/缩略图框当前尺寸重缩放
        # (最大化时框同步放大图片随之放大; resize/切番共用同一缩放出口)
        self._poster_src_pixmap: QPixmap | None = None
        self._thumb_src_pixmap: QPixmap | None = None
        self._did_apply_initial_size = False
        self._user_initiated_close = False  # 标记是否为用户主动关闭窗口
        self._naming_design: dict | None = None  # 命名页模板预览区：首次登记的设计几何基准
        self._naming_resyncing = False  # 命名页模板预览区：重算中标志（防 label resize 递归触发）
        self._naming_last_width = -1  # 命名页说明文字上次同步所用的宽度
        # 渲染扫描重入门闩：lbl.render() 会派发 Resize 重入 eventFilter 而 eventFilter
        # 又同步调 _naming_label_painted_height，不设闩会无限递归爆栈（见其 docstring）。
        self._naming_scanning = False
        self._naming_fix_tries = 0  # 同一宽度下的重算次数上限，防止布局压不下时反复排队
        self._fanyi_design: dict | None = None  # 翻译页两组：首次登记的设计几何基准
        self._fanyi_resyncing = False  # 翻译页两组：重算中标志（防标签 resize 递归触发）
        self._defn_resyncing = False  # 命名页画质组：重算中标志（防标签 resize 递归触发）
        self._defn_last_width = -1  # 命名页画质组说明文字上次同步所用宽度（宽度变了才重排）
        self._actor_scroll = None  # 设置-演员页的 CustomScrollArea（对齐判据要读它的视口宽）
        self._nfo_scroll = None  # 设置-NFO页的 CustomScrollArea（右列对齐的钩子宿主）
        self._adv_scroll = None  # 设置-高级页的 CustomScrollArea（四行对齐的钩子宿主）
        self._guaxiaomulu_scroll = None  # 设置-刮削目录页的 CustomScrollArea（文件清理提示对齐的钩子宿主）
        self._zimu_scroll = None  # 设置-字幕页的 CustomScrollArea（底部空白收缩的钩子宿主）
        self._xiazai_scroll = None  # 设置-下载页的 CustomScrollArea（两行复选框对齐的钩子宿主）
        self._zimu_dl_spacer = None  # 字幕页下载行插在 label_102 与「点击下载字幕包」之间的固定间隔
        # 演员信息组三列对齐注入的间隔项 [(布局, QSpacerItem)]，每遍同步先清后建（幂等）
        self._actor_info_spacers = []
        # 钉位时为防 Minimum 策略被间隔挤瘦而 setFixedWidth 的控件 [(控件, 原宽)]，还原时解锁
        self._actor_info_width_locks = []
        # 钉位时归零的行左内边距 [(布局, 原 QMargins)]，还原时复位
        self._actor_info_margin_restores = []
        # 窄态右移对齐注入的间隔项 [(布局, QSpacerItem)]，每遍同步先清后建（幂等）
        self._actor_narrow_spacers = []
        # 窄态右移对齐改过的持久设置 [("size", 控件, (原min, 原max)) / ("stretch", 布局, 原stretch元组)]，
        # 还原时原样写回。刻意与 _actor_info_width_locks 分开：本方法跑在
        # _sync_actor_info_columns 之后，若复用那边的列表并 setFixedWidth(0)「解锁」，
        # 会顺手拆掉那一拍刚钉好的 253/252 宽态铺排。
        self._actor_narrow_restores = []
        # 最大化态 A2 列对齐改过的持久设置 [("size", 控件, (原min, 原max)) /
        # ("geometry", 控件, 原 QRect) / ("stretch", 布局, 原stretch元组)]，
        # 窄态第一步原样写回；同样与前两套登记分开，且必须逆序写回。
        self._actor_wide_restores = []
        # 命名页画质行注入的间隔 [(布局, QSpacerItem)] + 容器加宽登记
        # [("width", 容器, 原宽)]，每遍同步先清后建（幂等）。注意容器是绝对定位，
        # 恢复 min/max 收不回宽度，必须按原宽写回。
        self._naming_defn_spacers = []
        self._naming_defn_restores = []
        # 命名页窄态左移登记 [(控件, 原x)]：最小化时三个复选框左移到 path 列，
        # 最大化时原样写回（宽态锚点即设计位置）。每遍先清后建，幂等往返自愈。
        self._naming_narrow_restores = []
        # 水印页网格列登记 [("colmin", 网格, (列, 原最小宽)) / ("colstretch", 网格, 列)]，
        # stretch 无 getter，还原时一律写回 0（默认值，本仓库无他处改动该列 stretch）
        self._watermark_col_restores = []
        # 水印页 col1 四行尾部补的 Expanding 间隔 [(行布局名, QSpacerItem)]，还原时摘掉
        self._watermark_tail_spacers = []
        # 水印页宽态右移对齐注入的固定间隔 [(行布局名, QSpacerItem)]，还原时摘掉
        self._watermark_shift_spacers = []
        # NFO页目标列对齐：两项行（horizontalLayout_135）宽态尾部补的 Expanding
        # 间隔（两项全钉死后无处吸收富余，QHBoxLayout 会把富余摊进三个间隙；
        # 三项行末项 Minimum 自然吸收，无需补），还原时摘掉
        self._nfo_target_col_tails = []
        # NFO页目标列对齐是否处于宽态生效中。生效时 C1 列最小宽归本方法所有，
        # 右列控制器必须跳过（它每遍先清零 C1min，生效中跑它会把本钉宽洗掉；
        # 且判据 critic.x>custom.x 在生效中恒为假，它本就是 no-op）。
        # 失效（窄态/复位/放不下）时由本方法先清标志再调它接管，保证 C1 有主。
        self._nfo_target_col_active = False
        # NFO页目标列对齐重入守卫：宽态循环里泵事件会触发嵌套全量同步，嵌套的
        # 本方法直接返回（外层循环的泵+重测会覆盖嵌套跳过的一切情况），防止递归。
        self._nfo_target_col_running = False
        # NFO页目标列对齐 trailing 节拍计数：慢路径动过手（应用过钉宽）即排一拍
        # 全量同步（慢路径收敛的只是当前拍内的几何；滚动区/内容宽度的后续生长、
        # 如 lw10w 1509→1589，会在退出后才落定，必须有一拍跑在它后面）。
        # 快路径/窄态/defer 即清零；上限 8 拍防抖荡；下一拍收敛即停排。
        self._nfo_target_col_trailing = 0
        self._zimu_dl_gap = -1  # 该间隔当前生效的宽度（-1 = 未安装/已拆除）
        self._nfo_colon_cal: tuple | None = None  # NFO冒号对齐：(字体样式key, 组标题冒号x, 行标签右pad)，像素标定缓存
        self._adv_dock_spacer = None  # 高级页隐藏图标行插在 label_42 与「隐藏菜单栏图标」之间的固定间隔
        self._adv_dock_gap = -1  # 该间隔当前生效的宽度（-1 = 从未设置）

        self.window_radius = 0  # 窗口四角弧度，为0时表示显示窗口标题栏
        self.window_border = 0  # 窗口描边，为0时表示显示窗口标题栏
        # 议题 #69: 恢复系统标题栏最大化按钮(议题 #67 曾按报告人要求禁用)。
        # #62/#66/#68 的最大化布局错乱根因(缩放三连)已在当时修复:
        # resizeEvent → _sync_page_layouts 会统一同步所有休眠页与内部组件,
        # 最大化路径由 tests/test_window_state_matrix.py 的最大化用例回归锁定。
        # 历史陷阱记录: setWindowFlags 触发 changeEvent, 若在 window_radius 等属性
        # 初始化前调用会在事件处理器内抛 AttributeError(PyQt6 qFatal abort 的形态之一)。
        # 当前无 setWindowFlags 调用, 此陷阱仅作为后续改动的注意事项保留。
        self.dark_mode = False  # 暗黑模式标识
        self.check_mac = True  # 检测配置目录
        self._actor_db_running: set[str] = set()  # 正在运行的 actor_db 异步任务的 btn_attr 集合
        self._nfo_lib_current_path: Path | None = None  # NFO 库管理：当前选中的 NFO 路径
        self._nfo_lib_pending_data: CrawlersResult | None = None  # NFO 库管理：后台读取的临时数据
        self._nfo_lib_pending_info: OtherInfo | None = None  # NFO 库管理：后台读取的临时 OtherInfo
        self._nfo_lib_save_result: bool = False  # NFO 库管理：后台保存结果
        self._nfo_lib_batch_result: tuple[int, int, int] = (0, 0, 0)  # NFO 库管理：批量结果 (成功, 失败, 总数)
        self._nfo_lib_original_data: CrawlersResult | None = None  # NFO 库管理：加载时的原始数据（diff 基准）
        # self.window_marjin = 0 窗口外边距，为0时不往里缩
        self.show_flag = True  # 是否加载刷新样式

        self.timer = QTimer()  # 初始化一个定时器，用于显示日志
        self.timer.timeout.connect(self.show_detail_log)
        self.timer.timeout.connect(self._flush_main_log_queue)
        self.timer.start(100)  # 设置间隔100毫秒
        self.timer_scrape = QTimer()  # 初始化一个定时器，用于间隔刮削
        self.timer_scrape.timeout.connect(self.auto_scrape)
        self.timer_update = QTimer()  # 初始化一个定时器，用于检查更新
        self.timer_update.timeout.connect(self.show_version)
        self.timer_update.start(43200000)  # 设置检查间隔12小时
        self.timer_remain_task = QTimer()  # 初始化一个定时器，用于显示保存剩余任务
        self.timer_remain_task.timeout.connect(save_remain_list)
        self.timer_remain_task.start(1500)  # 设置间隔1.5秒
        self.atuo_scrape_count = 0  # 循环刮削次数
        # endregion

        # region 其它属性声明
        self.threads_list: list[threading.Thread] = []  # 启动的线程列表
        self.start_click_time = 0
        self.start_click_pos: QPoint
        self.window_marjin = None
        self.now_show_name = None
        self._nfo_editor_snapshot: tuple[str, ...] | None = None
        self.show_name = None
        self.t_net = None
        self.options: QFileDialog.Option
        self.tray_icon: QSystemTrayIcon
        self.item_succ: QTreeWidgetItem
        self.item_fail: QTreeWidgetItem
        # endregion

        # region 初始化 UI
        resources.get_fonts()
        resources.start_data_loading()
        self.Ui = Ui_MDCx()  # 实例化 Ui
        self.Ui.setupUi(self)  # 初始化 Ui
        # 设置-演员页三行的对齐必须在滚动区拉伸的同一个 resizeEvent 里做完，
        # 否则通用拉伸先把它们钉到右缘（中间态），外层下一拍再拉到基准线，
        # 用户会看到「先在右边、再跳到左边」。详见 _sync_actor_page_align 与
        # CustomScrollArea._post_wide_sync_hook。
        # 按内容控件名认页面，不写死滚动区对象名（演员页是 scrollArea_12，
        # scrollArea_9 是字幕页，写死会装错地方、静默失效）。
        for _sa in self.Ui.tabWidget.findChildren(CustomScrollArea):
            _content = _sa.widget()
            if _content is not None and _content.objectName() == "scrollAreaWidgetContents_yanyuan":
                _sa._post_wide_sync_hook = self._sync_actor_page_wide_hooks
                self._actor_scroll = _sa
            elif _content is not None and _content.objectName() == "scrollAreaWidgetContents_nfo":
                # NFO 页同病：右列（影评/导演/TMDB/标签）的列最小宽是在「拉伸前」的
                # 几何上量的，那一拍条件不成立就留空，等下一拍才补上 → 用户看到
                # 「先在左边、再向右跳」。挂在拉伸之后的钩子上即可同拍完成。
                _sa._post_wide_sync_hook = self._sync_nfo_page_align
                self._nfo_scroll = _sa
            elif _content is not None and _content.objectName() == "scrollAreaWidgetContents_gaoji":
                # 高级页同病：网格里两项均分的行（界面外观行的「暗黑模式」、隐藏入口
                # 行的「隐藏NFO库管理」）会被通用拉伸推到右缘，本控制器下一拍才拉回
                # 基准线 → 用户看到「先在右侧、再向左漂移」（最大化与还原两个方向
                # 各出现一次）。挂在拉伸之后的钩子上即可同拍完成。
                _sa._post_wide_sync_hook = self._sync_advanced_page_wide_hook
                self._adv_scroll = _sa
            elif _content is not None and _content.objectName() == "scrollAreaWidgetContents_guaxiaomulu":
                # 刮削目录页同病：文件清理提示 label_271 被通用逻辑判为 _STRETCH
                # （宽 381 ≥ 内宽一半），最大化时宽按「设计宽 + extra」铺开、
                # 文本 AlignCenter 居中，整体右偏到按钮右侧；挂钩子同拍拉回按钮下方。
                _sa._post_wide_sync_hook = self._sync_guaxiaomulu_page_align
                self._guaxiaomulu_scroll = _sa
            elif _content is not None and _content.objectName() == "scrollAreaWidgetContents_zimu":
                # 字幕页：内容短（两组底缘 735 + 余量 72），最大化时视口更高，
                # widgetResizable 把内容拉到视口高，组框下方留下大片白色填充；
                # 挂钩子同拍把填充收进末尾组框（见 _sync_zimu_fill_blank）。
                _sa._post_wide_sync_hook = self._sync_zimu_page_align
                self._zimu_scroll = _sa
            elif _content is not None and _content.objectName() == "scrollAreaWidgetContents_xiazai":
                # 下载页：两行复选框（groupBox_24「下载」/ groupBox_33「保留旧文件」）
                # 都是「一项均分」但项数不同（7 vs 8），单元格边界必然错开 →
                # 通用拉伸落定后同拍把下载行钉到保留旧文件行的同一条竖线，
                # 否则会看到「先在右边、再向左跳」（同 _sync_advanced_page_wide_hook）。
                _sa._post_wide_sync_hook = self._sync_xiazai_row_align
                self._xiazai_scroll = _sa
        # QStackedWidget 只会把当前可见页 resize 到自身尺寸，休眠页永远停留在设计尺寸；
        # 切页后必须重新同步一次内部几何，否则"先改窗口尺寸再切页"时页面内容全部按陈旧尺寸布局
        self.Ui.stackedWidget.currentChanged.connect(self._sync_page_layouts)
        self.Ui.stackedWidget.currentChanged.connect(self._on_page_change_nfo_panel)
        # 命名页在设置页 tab 内：切到该 tab 时滚动区视口宽变化（滚动条占位）会重排
        # 内部网格，需在事件循环下一拍按最新宽度重算模板预览区（见 _sync_naming_template_section）。
        self.Ui.tabWidget.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._sync_naming_template_section)
        )
        # 翻译页同款：简介组/演员组的容器高度按实测内容算出，切 tab 引起的视口
        # 变化（滚动条占位）会改掉网格列宽 → 文字折行数变 → 需要重算。
        self.Ui.tabWidget.currentChanged.connect(lambda _index: QTimer.singleShot(0, self._sync_fanyi_group_spacing))
        # 命名页画质组同款：QHD 说明文字的折行数随网格拉伸后的终态宽度变化，
        # 切 tab 下一拍按最新宽度重算收紧（见 _sync_definition_group_spacing）。
        self.Ui.tabWidget.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._sync_definition_group_spacing)
        )
        # 设置页 tab 内各页同理：切 tab 下一拍只排队，真活留到再下一拍的全量同步。
        # 实测：切 NFO 页当拍布局 deferred 级联（scrollbar 出现约 14px、宽幅重拉）
        # 要到一批 processEvents 后才落定，直接同步会读到级联前的旧 custom.x
        # （1076 stale，由此 C1min=449 钉错 critic），而全量 pass 自带 page 级
        # 刷新、落定后单遍收敛（1075 对齐 / 显式重跑 459 收敛实测）。
        # 80% 分数缩放下各页签竖向滚动条厚度逐页不等宽（未点开的页签从未被
        # 布局，见 _sync_settings_scrollbar_widths）。排在全量同步之后落定，
        # 量到的才是级联终态厚度
        self.Ui.tabWidget.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._sync_settings_scrollbar_widths)
        )
        self.Ui.tabWidget.currentChanged.connect(lambda _index: QTimer.singleShot(0, self._queue_nfo_post_cascade_sync))
        # 首开 NFO 字段说明跳动修复：beats 跑在 paint 之后，首开第一拍常读到
        # 中间态视口（滚动条闪烁）误触发 pin 左移。直连同步 settle（paint 前落定，
        # 循环至稳），beats 留作兜底；休眠时方法内早退零成本。
        self.Ui.tabWidget.currentChanged.connect(self._settle_settings_after_switch)
        # stacked 切页同理：NFO 休眠时 resize/changeEvent 进来的 _sync_page_layouts
        # 会被各 sync 内 isVisibleTo 早退跳过，而切回设置页时 NFO 的 tab 索引没变、
        # tabWidget.currentChanged 根本不触发——NFO 将永远停留在旧几何（用户截图：
        # 窄态下 opl 从未被同步过、以天然位落在 pr 左边；宽态因之前切过 tab 已对齐）。
        # 故 stacked 切页下一拍同样只排队：休眠页由内层守卫 no-op，NFO 可见时在级
        # 联落定后的第二拍补齐（与 tab 钩子同一机制，幂等无累积）。
        self.Ui.stackedWidget.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._sync_settings_scrollbar_widths)
        )
        self.Ui.stackedWidget.currentChanged.connect(
            lambda _index: QTimer.singleShot(0, self._queue_nfo_post_cascade_sync)
        )
        # 切回设置页（NFO tab 索引不变、无 tab 钩子）同样首帧落定，方法内判
        # 设置页/NFO 可见性，休眠早退；_on_page_change_nfo_panel 取消切页时
        # 已回到主页，守卫直接返回。
        self.Ui.stackedWidget.currentChanged.connect(self._settle_settings_after_switch)
        # 说明文字宽度变化（滚动条占位、休眠页拉伸等）时自动补一次重算。
        self.Ui.label_66.installEventFilter(self)
        # 命名页画质组 QHD 说明（label_331）：只按宽度触发，见 _sync_definition_group_spacing
        # —— 高度由纯宽度函数算出，钉上后立刻自洽，无需「高度对不上」的重入门闩
        # （painted 回扫法在非纯白背景下恒返回自身高度，那种比较只会造成 +2 漂移）。
        self.Ui.label_331.installEventFilter(self)
        # 信息管理页右侧两个预览框：左键单击弹出大图窗口，见 eventFilter 分支
        self.Ui.label_nfo_lib_poster_preview.installEventFilter(self)
        self.Ui.label_nfo_lib_thumb_preview.installEventFilter(self)
        self._bind_system_theme_refresh()
        self.cutwindow = CutWindow(self)
        self.preview_image_loader = PreviewImageLoader(self)
        self.preview_image_loader.loaded.connect(self._apply_preview_images)
        self.Init_Singal()  # 信号连接
        self.Init_Ui()  # 设置Ui初始状态
        self._init_donate_widgets()  # 侧栏「使用说明」下方加收款码 + [赞助作者] 链接
        self.load_config()  # 加载配置
        self._setup_name_template_preview()
        get_success_list()  # 获取历史成功刮削列表
        # endregion

        # region 启动显示信息和后台检查更新
        self.show_scrape_info()  # 主界面左下角显示一些配置信息
        # 检测网络面板的首屏文字（代理状态块 + CF Bypass 提示 + 启动自检）不在这里发，
        # 改由 showEvent 推迟一拍走 _emit_net_startup_panel：分隔线「=」的字符数要按
        # 还原态的真实可视宽算，而此刻窗口还没 resize 到默认尺寸、文本区仍是 .ui 设计宽。
        self.show_version()  # 日志页面显示版本信息
        self.creat_right_menu()  # 加载右键菜单
        self.pushButton_main_clicked()  # 切换到主界面
        self.auto_start()  # 自动开始刮削
        # endregion

    def _setup_name_template_preview(self) -> None:
        self.Ui.plainTextEdit_name_template_preview.setPlainText(
            self.Ui.lineEdit_media_name.text()
            or "{{ number }}{% if studio %} [{{ studio }}]{% endif %} {{ originaltitle }}"
        )
        self.Ui.plainTextEdit_name_template_preview.textChanged.connect(self._update_name_template_preview)
        self._update_name_template_preview()

    def _build_name_preview_sample(self) -> tuple[FileInfo, CrawlersResult]:
        file_info = FileInfo.empty()
        file_info.number = "ABC-123"
        file_info.file_path = Path("D:/Media/Input/ABC-123.mp4")
        file_info.folder_path = file_info.file_path.parent
        file_info.file_name = "ABC-123"
        file_info.definition = "4K"
        file_info.c_word = "-中字"
        file_info.wuma = "-无码"

        result = CrawlersResult.empty()
        result.number = "ABC-123"
        result.title = "中文标题"
        result.originaltitle = "Original Title"
        result.actors = ["演员A", "演员B"]
        result.all_actors = ["演员A", "演员B", "男演员C"]
        result.directors = ["导演A"]
        result.series = "系列A"
        result.studio = "Studio A"
        result.publisher = "发行商A"
        result.release = "2024-01-02"
        result.runtime = "120"
        result.mosaic = "有码"
        result.letters = "ABC"
        result.wanted = "123"
        result.score = "4.5"
        result.outline = "示例简介"
        return file_info, result

    def _update_name_template_preview(self) -> None:
        template = self.Ui.plainTextEdit_name_template_preview.toPlainText()
        if not template.strip():
            self.Ui.label_name_template_preview_result.setText("状态：等待输入模板")
            # 结果文字行数随模板变化，重新贴合一次，否则上次钉的高度会裁字或留白
            self._sync_naming_template_section()
            return
        try:
            file_info, result = self._build_name_preview_sample()
            rendered = render_name(
                template,
                file_info,
                result,
                NameRenderOptions(
                    target=NamingTarget.FILE,
                    show_definition_suffix=False,
                    show_cnword_suffix=False,
                    show_moword_suffix=False,
                    max_length=120,
                ),
            )
        except Exception as exc:
            self.Ui.label_name_template_preview_result.setStyleSheet("color: rgb(190, 0, 0);")
            self.Ui.label_name_template_preview_result.setText("状态：语法错误\n" + html.escape(str(exc), quote=False))
            self._sync_naming_template_section()
            return

        self.Ui.label_name_template_preview_result.setStyleSheet("color: rgb(8, 128, 128);")
        self.Ui.label_name_template_preview_result.setText(
            "状态：语法正确\n"
            f"结果：{html.escape(rendered.text, quote=False)}\n"
            "示例：number=ABC-123, studio=Studio A, originaltitle=Original Title definition=4K"
        )
        self._sync_naming_template_section()

    # region Init
    def Init_Ui(self): ...

    def Init_Singal(self): ...

    def Init_QSystemTrayIcon(self): ...

    def init_QTreeWidget(self): ...

    def load_config(self): ...

    def creat_right_menu(self):
        self.menu_start = QAction(QIcon(resources.start_icon), "  开始刮削\tS", self)
        self.menu_stop = QAction(QIcon(resources.stop_icon), "  停止刮削\tS", self)
        self.menu_number = QAction(QIcon(resources.input_number_icon), "  重新刮削\tN", self)
        self.menu_website = QAction(QIcon(resources.input_website_icon), "  输入网址重新刮削\tU", self)
        self.menu_del_file = QAction(QIcon(resources.del_file_icon), "  删除文件\tD", self)
        self.menu_del_folder = QAction(QIcon(resources.del_folder_icon), "  删除文件和文件夹\tA", self)
        self.menu_make_symlink = QAction(QIcon(resources.open_folder_icon), "  在指定位置创建软链接", self)
        self.menu_make_symlink_in_dir = QAction(
            QIcon(resources.open_folder_icon), "  在指定位置创建软链接（按文件名建目录）", self
        )
        self.menu_make_hardlink = QAction(QIcon(resources.open_folder_icon), "  在指定位置创建硬链接", self)
        self.menu_make_hardlink_in_dir = QAction(
            QIcon(resources.open_folder_icon), "  在指定位置创建硬链接（按文件名建目录）", self
        )
        self.menu_folder = QAction(QIcon(resources.open_folder_icon), "  打开文件夹\tF", self)
        self.menu_nfo = QAction(QIcon(resources.open_nfo_icon), "  编辑 NFO\tE", self)
        self.menu_play = QAction(QIcon(resources.play_icon), "  播放\tP", self)
        self.menu_hide = QAction(QIcon(resources.hide_boss_icon), "  隐藏\tQ", self)
        self.menu_similar = QAction(QIcon(resources.open_folder_icon), "  查看相似片推荐", self)

        self.menu_start.triggered.connect(self.pushButton_start_scrape_clicked)
        self.menu_stop.triggered.connect(self.pushButton_start_scrape_clicked)
        self.menu_number.triggered.connect(self.search_by_number_clicked)
        self.menu_website.triggered.connect(self.search_by_url_clicked)
        self.menu_del_file.triggered.connect(self.main_del_file_click)
        self.menu_del_folder.triggered.connect(self.main_del_folder_click)
        self.menu_make_symlink.triggered.connect(self.main_make_symlink_click)
        self.menu_make_symlink_in_dir.triggered.connect(self.main_make_symlink_in_dir_click)
        self.menu_make_hardlink.triggered.connect(self.main_make_hardlink_click)
        self.menu_make_hardlink_in_dir.triggered.connect(self.main_make_hardlink_in_dir_click)
        self.menu_folder.triggered.connect(self.main_open_folder_click)
        self.menu_nfo.triggered.connect(self.main_open_nfo_click)
        self.menu_play.triggered.connect(self.main_play_click)
        self.menu_hide.triggered.connect(self.hide)
        self.menu_similar.triggered.connect(self.main_show_similar_click)

        QShortcut(QKeySequence(self.tr("N")), self, self.search_by_number_clicked)
        QShortcut(QKeySequence(self.tr("U")), self, self.search_by_url_clicked)
        QShortcut(QKeySequence(self.tr("D")), self, self.main_del_file_click)
        QShortcut(QKeySequence(self.tr("A")), self, self.main_del_folder_click)
        QShortcut(QKeySequence(self.tr("F")), self, self.main_open_folder_click)
        QShortcut(QKeySequence(self.tr("E")), self, self.main_open_nfo_click)
        QShortcut(QKeySequence(self.tr("P")), self, self.main_play_click)
        QShortcut(QKeySequence(self.tr("S")), self, self.pushButton_start_scrape_clicked)
        QShortcut(QKeySequence(self.tr("Q")), self, self.hide)
        # QShortcut(QKeySequence(self.tr("Esc")), self, self.hide)
        QShortcut(QKeySequence(self.tr("Esc")), self, self.hide_tips_widget_on_escape)
        QShortcut(QKeySequence(self.tr("Ctrl+M")), self, self.pushButton_min_clicked2)
        QShortcut(QKeySequence(self.tr("Ctrl+W")), self, self.ready_to_exit)

        self.Ui.page_main.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.Ui.page_main.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos=None):
        if not pos:
            pos = self.Ui.pushButton_right_menu.pos() + QPoint(40, 10)
            # pos = QCursor().pos()
        menu = QMenu()
        menu.setStyleSheet(build_menu_style(self.dark_mode))
        selected_entries = self._get_selected_entries()
        selected_entry = selected_entries[0] if len(selected_entries) == 1 else None
        if len(selected_entries) > 1:
            menu.addAction(QAction(f"已选择 {len(selected_entries)} 项", self))
            menu.addSeparator()
            menu.addAction(self.menu_del_file)
            menu.addAction(self.menu_del_folder)
            menu.addAction(self.menu_make_symlink)
            menu.addAction(self.menu_make_symlink_in_dir)
            menu.addAction(self.menu_make_hardlink)
            menu.addAction(self.menu_make_hardlink_in_dir)
            menu.exec(self.Ui.page_main.mapToGlobal(pos))
            return

        if selected_entry is not None:
            _, _, _, file_path = selected_entry
            file_name = split_path(file_path)[1]
            menu.addAction(QAction(file_name, self))
            menu.addSeparator()
        elif self.file_main_open_path:
            file_name = split_path(self.file_main_open_path)[1]
            menu.addAction(QAction(file_name, self))
            menu.addSeparator()
        else:
            menu.addAction(QAction("请刮削后使用！", self))
            menu.addSeparator()
            if self.Ui.pushButton_start_cap.text() != "开始":
                menu.addAction(self.menu_stop)
            else:
                menu.addAction(self.menu_start)
        menu.addAction(self.menu_number)
        menu.addAction(self.menu_website)
        menu.addSeparator()
        menu.addAction(self.menu_del_file)
        menu.addAction(self.menu_del_folder)
        menu.addAction(self.menu_make_symlink)
        menu.addAction(self.menu_make_symlink_in_dir)
        menu.addAction(self.menu_make_hardlink)
        menu.addAction(self.menu_make_hardlink_in_dir)
        menu.addSeparator()
        menu.addAction(self.menu_folder)
        menu.addAction(self.menu_nfo)
        menu.addAction(self.menu_play)
        menu.addAction(self.menu_hide)
        menu.addAction(self.menu_similar)
        menu.exec(self.Ui.page_main.mapToGlobal(pos))
        # menu.move(pos)
        # menu.show()

    def _tree_result_context_menu(self, pos: QPoint):
        item = self.Ui.treeWidget_number.itemAt(pos)
        if item is not None and item.text(0) not in {"成功", "失败"}:
            self._set_result_item_as_current_selection(item)
        global_pos = self.Ui.treeWidget_number.viewport().mapToGlobal(pos)
        self._menu(self.Ui.page_main.mapFromGlobal(global_pos))

    # endregion

    # region 窗口操作
    def tray_icon_click(self, e):
        if e == QSystemTrayIcon.ActivationReason.Trigger and IS_WINDOWS:
            if self.isVisible():
                self.hide()
            else:
                self.activateWindow()
                self.raise_()
                self.show()

    def tray_icon_show(self):
        if self.windowState() & Qt.WindowState.WindowMinimized:  # 最小化时恢复
            self.showNormal()
        self.recover_windowflags()  # 恢复焦点
        self.activateWindow()
        self.raise_()
        self.show()

    def change_mainpage(self, t):
        self.pushButton_main_clicked()

    def eventFilter(self, a0, a1):
        # print(event.type())

        if a1.type() == QEvent.Type.MouseButtonRelease:  # 松开鼠标，检查是否在前台
            self.recover_windowflags()
        # 议题 #132：不再在 ApplicationActivate 时自动 show() 隐藏的主窗。
        # 主窗隐藏（托盘图标隐藏 / 关闭到托盘 / 最小化到托盘）都是用户主动行为，
        # 此时操作 Emby 演员管理器等工具会触发 ApplicationActivate，旧逻辑会把隐藏的
        # 主窗拉出前台。恢复显示只由托盘菜单/托盘图标点击（tray_icon_show /
        # tray_icon_click）负责；最小化态由 Qt 自行保持。
        # 议题 #102 曾保留「非最小化隐藏态」的 show()，议题 #132 实测反馈表明托盘
        # 隐藏后操作管理器仍会弹出主窗，故此处改为完全不自动弹出。
        if a0.objectName() == "label_poster" or a0.objectName() == "label_thumb":
            if a1.type() == QEvent.Type.MouseButtonPress:
                a1 = cast("QMouseEvent", a1)
                if a1.button() == Qt.MouseButton.LeftButton:
                    self.start_click_time = time.time()
                    self.start_click_pos = a1.globalPosition().toPoint()
            elif a1.type() == QEvent.Type.MouseButtonRelease:
                a1 = cast("QMouseEvent", a1)
                if a1.button() == Qt.MouseButton.LeftButton:
                    if not bool(a1.globalPosition().toPoint() - self.start_click_pos) or (
                        time.time() - self.start_click_time < 0.05
                    ):
                        self._pic_main_clicked()
        # 信息管理页右侧预览框：左键单击弹出大图窗口（← → 切同组图片，Esc 关闭）。
        # QLabel 默认不处理鼠标事件，但事件过滤器先于控件自身收到事件，所以照样能接。
        _nfo_preview_kind = None
        if a0 is getattr(self.Ui, "label_nfo_lib_poster_preview", None):
            _nfo_preview_kind = "poster"
        elif a0 is getattr(self.Ui, "label_nfo_lib_thumb_preview", None):
            _nfo_preview_kind = "thumb"
        if _nfo_preview_kind and a1.type() == QEvent.Type.MouseButtonRelease:
            a1 = cast("QMouseEvent", a1)
            if a1.button() == Qt.MouseButton.LeftButton:
                self.nfo_lib_preview_clicked(_nfo_preview_kind)
        if a0 is self.Ui.textBrowser_log_main.viewport() or a0 is self.Ui.textBrowser_log_main_2.viewport():
            if not self.Ui.textBrowser_log_main_3.isHidden() and a1.type() == QEvent.Type.MouseButtonPress:
                self.Ui.textBrowser_log_main_3.hide()
                self.Ui.pushButton_scraper_failed_list.hide()
                self.Ui.pushButton_save_failed_list.hide()
        # 命名页模板预览区：说明文字宽度一变（滚动条占位、窗口拉伸、切页）就重算，
        # 否则上次钉死的高度会残留成「视频文件名」上方的空白。
        # 高度与当前宽度算出的需要值不一致时同样要重算——钉高是在某个瞬间算的，
        # 那一刻标签还比较窄的话，窗口变宽后文字不再折行就会剩下一片死空白，
        # 而宽度没再变过就再也不会触发 Resize 分支。故高度也要校验（重算次数封顶，
        # 避免布局真压不下时无限排队）。
        if a0 is getattr(self.Ui, "label_66", None) and a1.type() == QEvent.Type.Resize:
            # _naming_scanning 是 _naming_label_painted_height 的重入门闩：本分支会同步
            # 调它，而它内部的 lbl.render() 又会派发 Resize 打回这里。不加这道判断时两者
            # 互为递归直到栈溢出（0xC00000FD，无 Python 崩溃日志）。详见该方法 docstring。
            if not self._naming_resyncing and not self._naming_scanning:
                need = self._naming_label_painted_height(a0)
                if a0.width() != self._naming_last_width:
                    self._naming_fix_tries = 0
                if a0.width() != self._naming_last_width or a0.height() != need:
                    if self._naming_fix_tries < 3:
                        self._naming_fix_tries += 1
                        self._naming_last_width = a0.width()
                        QTimer.singleShot(0, self._sync_naming_template_section)
        # 命名页画质组 QHD 说明（label_331）：宽度一变（滚动条占位、窗口拉伸、切页）
        # 就重算，否则上次钉死的高度残留成 HD 行与分辨率行之间的空白。折行数只由
        # 宽度决定，_label_text_height_for_width 是纯函数：钉上后同宽度必得同高，
        # 故只按宽度触发即可立即收敛，无需「高度对不上」的重试（label_66 的 painted
        # 回扫法才需要那一套，见 _naming_label_painted_height 的 docstring）。
        if a0 is getattr(self.Ui, "label_331", None) and a1.type() == QEvent.Type.Resize:
            # 只按宽度触发（label_66 还要校验高度是因为它用 painted 回扫法，级联中途
            # 量到陈旧折行；这里是纯宽度函数，钉上后同宽度必得同高，见方法 docstring）。
            # 宽度变了才排一次队：_defn_last_width 记住上次同步所用宽度，同宽度重复
            # Resize 直接跳过，天然封顶，不需要 label_66 那套重试计数。
            w = a0.width()
            if not self._defn_resyncing and w > 0 and w != self._defn_last_width:
                self._defn_last_width = w
                QTimer.singleShot(0, self._sync_definition_group_spacing)
        # 刮削缓存失败列表：表格/视口宽一变就按 4:2:6:3 重分布列宽，保持无横向滚动条。
        # setColumnWidth 不改变表格自身尺寸，只触发 header 几何变化，不会递归触发此处 Resize，
        # 故直接同步布局（若用 singleShot 延迟一拍，填入多行致视口收缩后断言时仍是旧列宽）。
        # 视口 Resize 也要监听：填入多行后垂直滚动条出现会挤窄视口，此时表格尺寸不变。
        _scrape_tw = getattr(self.Ui, "tableWidget_scrape_cache_failed", None)
        if _scrape_tw is not None and a1.type() == QEvent.Type.Resize:
            if a0 is _scrape_tw or a0 is _scrape_tw.viewport():
                if not getattr(self, "_scrape_cache_layouting", False):
                    self._layout_scrape_cache_columns()
        return super().eventFilter(a0, a1)

    def showEvent(self, a0):
        if not self._did_apply_initial_size:
            self._did_apply_initial_size = True
            self._apply_adaptive_default_size()  # 首次显示时按屏幕自适应默认窗口大小并居中
        # 检测网络面板首屏推迟一拍发：_apply_adaptive_default_size() 里的 resize 只把
        # resizeEvent 排进队列，文本区几何要等该事件被派发才落定（resizeEvent →
        # _sync_page_layouts 里同步 setGeometry）。此刻量到的还是 .ui 设计宽，会让分隔线
        # 多算字符而在默认态折行，故挂 singleShot 等首帧之后再量（见 _net_separator_chars）。
        # 用 _net_startup_emitted 兜住托盘隐藏/再显示时 showEvent 重复触发。
        if not self._net_startup_emitted:
            self._net_startup_emitted = True
            QTimer.singleShot(0, self._emit_net_startup_panel)
        # 拖到别的显示器 / 改分辨率后重算：放不下当前屏幕的高分屏缩放档位要重新隐藏
        apply_ui_scale_option_limits(self.Ui.comboBox_ui_scale, self.screen())
        super().showEvent(a0)

    def _net_separator_chars(self) -> int:
        """检测网络面板「=」分隔线的字符数：量一次并缓存，两态保持相同。

        这段文字是启动时一次性打印的固定字符串，最大化/还原都不会重新渲染，
        故字符数只由首次（还原态）量一次并复用——否则两态字符数会不一致。

        该文本框在 QSS 里是 Consolas 13px 等宽（实测单字宽 7px），按「可视宽 ÷
        单字宽」取整除即可把分隔线铺到右边缘，且不会超出可视宽而折行。

        竖向滚动条必须提前预留：首屏只有几行字，面板装得下、滚动条尚未出现，
        此刻量到的可视宽是「没有滚动条」时的宽度；等用户点【开始检测】把几十行
        站点结果灌进来，滚动条弹出、可视宽会窄掉一个滚动条宽（实测 16px），
        此前发出的分隔线就会超出可视宽、被折成两行。故不论滚动条此刻显不显示，
        一律先扣掉一个滚动条宽度，保证两态都不会折行。
        """
        cached = self._net_separator_chars_cache
        if cached:
            return cached
        browser = self.Ui.textBrowser_net_main
        width = 0
        try:
            viewport = browser.viewport()
            # viewport 宽与控件宽的差只可能是「边框 + QSS padding + 滚动条」，
            # 超出这个范围说明还没随几何落定，改用控件宽兜底。
            if 0 < browser.width() - viewport.width() <= _NET_SEP_VIEWPORT_SLACK:
                # viewport 已排除滚动条占位（显示时），直接用；未显示时预留出来。
                width = viewport.width()
                if not browser.verticalScrollBar().isVisible():
                    width -= self._net_scrollbar_reserve(browser.verticalScrollBar())
            elif browser.width() > 0:
                # 兜底宽（控件宽 - padding）含滚动条占位，需自行扣减。
                width = browser.width() - _NET_SEP_TEXT_PADDING
                bar = browser.verticalScrollBar()
                width -= bar.width() if bar.isVisible() else self._net_scrollbar_reserve(bar)
        except Exception:
            width = 0
        advance = QFontMetricsF(browser.font()).horizontalAdvance("=") if width > 0 else 0
        count = int(width // advance) if advance > 0 else 0
        if count <= 0:
            count = _NET_SEP_FALLBACK
        count = max(_NET_SEP_MIN, min(count, _NET_SEP_MAX))
        self._net_separator_chars_cache = count
        return count

    @staticmethod
    def _net_scrollbar_reserve(bar) -> int:
        """竖向滚动条出现时要占掉的宽度（此刻通常还没显示）。

        QSS 里 `QScrollBar:vertical { width: 16px; }` 是固定宽，`sizeHint()` 能直接
        量到（实测 16）；量不到时退回常量兜底，保证预留一定不为 0。
        """
        try:
            hint = bar.sizeHint().width()
        except Exception:
            hint = 0
        return max(hint, _NET_SEP_SCROLLBAR_FALLBACK)

    def _emit_net_startup_panel(self) -> None:
        """首帧之后发检测网络面板的启动文字（原先在 __init__ 里直接发）。"""
        try:
            sep = self._net_separator_chars()
            self.show_net_info("\n🏠 代理设置在:【软件设置】-【网络】-【网络设置】")
            show_netstatus(sep)  # 检查网络界面显示当前网络代理信息
            self.show_net_info(
                "💡 CF Bypass：【软件设置】-【网络】-【外部CF服务】填写TRAWL/FlareSolverr服务地址，如http://127.0.0.1:8191\n"
                "▶️ 点击右上角【开始检测】按钮开始测试网络连通性"
            )
            signal_qt.add_log("🍯 你可以点击左下角的图标来 显示 / 隐藏 请求信息面板！")
            run_startup_health_checks()  # 启动自检：配置目录可写/代理可达/TMDB key
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    def _apply_adaptive_default_size(self) -> None:
        """默认尺寸按所在屏可用区自适应（min(1030, 可用宽×0.9) × min(700, 可用高×0.85)），并居中。

        尺寸公式保持历史行为（用户在 80% 缩放下 1030×700 的默认初始宽高不能变），
        改动只补上「居中」；界面缩放过大导致界面超出屏幕，由设置页高分屏缩放下拉
        隐藏超限档位来防（见 init.UI_SCALE_OPTIONS）。
        """
        screen = self.screen()
        avail = screen.availableGeometry() if screen is not None else None
        if avail is not None:
            def_w, def_h = _adaptive_window_sizes(avail.width(), avail.height())[2:]
        else:
            def_w, def_h = DEFAULT_WINDOW_SIZE
        self.resize(def_w, def_h)
        self._center_on_screen(avail)

    def _center_on_screen(self, avail: QRect | None = None, *, allow_defer: bool = True) -> None:
        """把窗口整体（含标题栏与边框）精确居中到所在屏可用区的正中央。

        两个易错点（Qt 6 实测）：
        1. 人眼看到的是 frameGeometry（含边框），而 geometry() 只是客户区——用客户区居中
           会整体偏移半个标题栏/边框，故一律以 frameGeometry 为准；
        2. QWidget.move() 收的是「边框左上角」（move(100,200) → frame 在 100,200、客户区
           在 102,202），与 pos() 语义一致，故这里不需要再补偿边框厚度。
        """
        if avail is None:
            screen = self.screen() or QApplication.primaryScreen()
            if screen is None:
                return
            avail = screen.availableGeometry()
        if allow_defer and self.windowHandle() is None:
            # 原生窗口尚未创建，frameGeometry 退化为客户区（边框厚度不可知）：
            # 推到下一事件循环（原生窗口已创建）再居中一次，否则会偏出半个标题栏。
            QTimer.singleShot(0, lambda: self._center_on_screen(allow_defer=False))
            return
        frame = self.frameGeometry()
        x = avail.x() + (avail.width() - frame.width()) // 2
        y = avail.y() + (avail.height() - frame.height()) // 2
        # 窗口比可用区还大时（极端小屏）至少让左上角留在屏内，标题栏不会跑到屏外抓不到
        self.move(max(x, avail.x()), max(y, avail.y()))

    # 用于计算窗口各子页面初始设计尺寸，被 resizeEvent 用于按比例缩放
    _BASE_W = 1040
    _BASE_H = 760

    # 窗口缩放时，需要用子页面内容的实际高度来自定义 MDCx 中央区域的高度
    _CONTENT_TOP_OFFSET = 6
    _CONTENT_BOTTOM_MARGIN = 2

    # 软件界面「清空结果列表」刷子按钮与结果树左缘的固定间距（设计态 760 - 600）。
    # 结果树左缘 tree_x = main_w - tree_w - 18、树宽 tree_w = int(202 × main_w/820)
    # 随窗口拉伸，故把刷子钉在「树左缘 + 本常量」上、而不是钉在页面右缘：
    # 树内首行「成功」两字的左缘恒为「树左缘 + 固定缩进」，于是刷子与「成功」的
    # 间距在最大化/还原两态完全一致（最大化不再随树拉伸而越拉越远）。
    _MAIN_TREE_CLEAR_DX = 160

    # 软件界面「编辑 NFO/打开文件夹/播放/右键菜单」四按钮组的设计态右缘
    # （.ui：最右 pushButton_right_menu x=547 + 宽 40 = 587）。最大化/还原两态都把
    # 组右缘钉到缩略图框右边界；本常量是极窄窗（缩略图右缘退到 587 左侧）时的下限，
    # 保证按钮组只右移不左移，绝不压住「标题：」值行（设计态右界 417）。
    _MAIN_ACTION_ROW_RIGHT = 587

    # 高级页「界面外观」行的 layoutWidget5 设计宽度（MDCx.ui 里
    # QRect(0,-10,550,51)）。最大化时该容器要临时加宽以对齐，见
    # _sync_advanced_page_align 的设计态对照值（.ui 里 layoutWidget5 = 550x51）；
    # 该控制器每一态都会按实测列宽重算，此常量仅作「放弃对齐」时的回退值。
    _ADV_FRAME_LW_W = 550

    # 高级页「隐藏窗口」行的 layoutWidget_17 设计宽度（MDCx.ui 里
    # QRect(0,0,551,32)）。最大化时该容器要加宽以把「点最小化按钮」「无」推到
    # 各自锚点，见 _sync_advanced_page_tail_align；该方法每态都按实测锚点重算，
    # 此常量仅作「放弃对齐 / 最小化态复位」时的设计态对照值。
    _ADV_HIDE_LW_W = 551

    # 议题 #117：信息管理页「简介/标签」多行框的设计高度（.ui 中 min=max=60）。
    # 视口放不下整表时按缺口压缩这两个框，压缩下限 40（再矮就没法看内容，
    # 宁可保留滚动条）。
    _NFO_LIB_FIELD_FULL_H = 60
    _NFO_LIB_FIELD_MIN_H = 40

    # 最大化时「简介/标签」多行框吸收视口富余高度的上限。再高就会把两行
    # 内容拉成一大片空白（1440p 上尤其明显），超出部分留在表单下方。
    _NFO_LIB_FIELD_MAX_H = 300

    # 信息管理页多条件筛选输入框：设计上限（MDCx.py 里
    # maximumSize(180, QWIDGETSIZE_MAX)）与最小化时必须还原到的值。
    # 信息管理顶栏：目录显示框与筛选框在布局里各占一份拉伸（.ui 里
    # horstretch 均为 1），剩余空间永远平分、两框恒等宽，无需运行时换算。
    # 曾用 `_sync_nfo_lib_top_bar()` 按 0.5 比例换算（最大化加宽/还原复位 180），
    # 用户要求两框等宽后删除——布局均分在所有窗口状态下天然成立，无自反馈抖动。

    # 命名页「视频命名规则」组（groupBox_8）：模板预览框的高度。默认模板只有一行，
    # 128px 会在框内留出大片空白，这里按用户要求取其一半。
    _NAMING_PREVIEW_H = 64
    # groupBox_8 内容上下留白（设计值：组高 1051 - 网格高 1001）。
    _NAMING_BOX_PAD = 50
    # groupBox_8 之后同页的 QGroupBox，组高收缩后需整体上移保持设计间距。
    _NAMING_FOLLOW_GROUPS = (
        "groupBox_40",
        "groupBox_77",
        "groupBox_46",
        "groupBox_38",
        "groupBox_37",
        "groupBox_62",
        "groupBox_65",
        "groupBox_67",
    )

    def _sync_nfo_lib_action_buttons(self) -> None:
        """复位「批量保存」「保存当前nfo文件」的宽度上限，并把「裁剪封面」对齐批量保存的高度。

        两个保存按钮在布局里都是跨列的，宽度由布局撑满；这里解除可能残留的
        maximumWidth 限制，让它们重新铺满所在边框（groupBox / 表单跨列区域）。
        「裁剪封面」改用批量保存同款样式后，把高度对齐，保证上下留白一致。
        """
        ui = self.Ui
        batch = ui.pushButton_nfo_lib_batch_save
        for button in (batch, ui.pushButton_nfo_lib_save):
            button.setMinimumWidth(0)
            if button.maximumWidth() != QWIDGETSIZE_MAX:
                button.setMaximumWidth(QWIDGETSIZE_MAX)
            owner = button.parentWidget()
            if owner is not None and owner.layout() is not None:
                owner.layout().invalidate()
                owner.layout().activate()
        # 「裁剪封面」与「批量保存」同高：批量保存的固定高度来自 minimumHeight 36
        height = max(batch.minimumHeight(), batch.sizeHint().height())
        crop = ui.pushButton_nfo_lib_crop
        if crop.minimumHeight() != height:
            crop.setMinimumHeight(height)

    def _nfo_lib_form_rows(self) -> list[tuple[QWidget | None, QWidget | None]]:
        """列出信息管理表单 QFormLayout 每一行的 (标签控件, 字段控件)。

        第 15 行「保存当前nfo文件」是跨列按钮，只有字段没有标签。
        """
        layout = self.Ui.formLayout_nfo_lib
        rows: list[tuple[QWidget | None, QWidget | None]] = []
        for row in range(layout.rowCount()):
            label_item = layout.itemAt(row, QFormLayout.ItemRole.LabelRole)
            field_item = layout.itemAt(row, QFormLayout.ItemRole.FieldRole)
            rows.append(
                (
                    label_item.widget() if label_item is not None else None,
                    field_item.widget() if field_item is not None else None,
                )
            )
        return rows

    def _pin_nfo_lib_form_rows(self, pinned: bool) -> None:
        """钉住/还原信息管理表单各行的最大高度（最大化时消除行间空白）。

        现象：窗口最大化后内容 widget 被拉高到视口高，QFormLayout 把多出来的
        高度平均分给所有「还能长高」的行——单行输入框的 sizeHint 只有 22px，
        分到的却是 54px，于是每一行下面凭空多出约一行宽的空白（用户截图：
        发行日/年份之间）。

        做法：除「简介/标签」两个多行框外，把每行控件的最大高度钉到各自自然
        高（sizeHint 与 minimumHeight 取大者，保存按钮 36px 不受影响），富余
        高度就只会流向那两个多行框，行距回到设计的 4px。
        pinned=False 时按钉住前记下的值原样还原，最小化态布局不受影响。
        """
        flex_fields = (
            self.Ui.plainTextEdit_nfo_lib_outline,
            self.Ui.plainTextEdit_nfo_lib_tag,
        )
        saved: dict = self.__dict__.setdefault("_nfo_lib_row_max_heights", {})
        if not pinned and not saved:
            return
        for label, field in self._nfo_lib_form_rows():
            if field in flex_fields:
                continue
            for widget in (label, field):
                if widget is None:
                    continue
                if not pinned:
                    widget.setMaximumHeight(saved.pop(widget, QWIDGETSIZE_MAX))
                    continue
                if widget not in saved:
                    saved[widget] = widget.maximumHeight()
                natural = max(widget.sizeHint().height(), widget.minimumHeight())
                widget.setMaximumHeight(natural)

    def _sync_nfo_lib_form_fields(self) -> None:
        """小窗时压缩信息管理页「简介/标签」高度，让保存按钮免滚动可见（议题 #117）。

        现象：窗口缩到默认尺寸以下时，15 行表单 + 底部余量总高超出滚动视口，
        出现垂直滚动条，「保存当前nfo文件」被推到视口外，用户以为按钮丢了。
        做法：按视口可用高动态定这两个多行框的高——全高放得下就保持设计高
        （最小化时布局完全不变），放不下就按缺口在两个框之间等分压缩，
        最低压到 _NFO_LIB_FIELD_MIN_H。

        最大化时额外消除行间空白（见 _pin_nfo_lib_form_rows）：各行钉到自然高，
        视口的富余高度全部交给「简介/标签」两个多行框（各自封顶
        _NFO_LIB_FIELD_MAX_H），超出封顶的部分留在表单下方而不是摊到行间。
        """
        ui = self.Ui
        scroll = ui.scrollArea_nfo_lib_form
        content = ui.scrollAreaWidgetContents_nfo_lib
        layout = content.layout()
        viewport_h = scroll.viewport().height()
        if layout is None or viewport_h <= 0:
            return
        boxes = (ui.plainTextEdit_nfo_lib_outline, ui.plainTextEdit_nfo_lib_tag)
        full = self._NFO_LIB_FIELD_FULL_H
        floor = self._NFO_LIB_FIELD_MIN_H

        def apply_box_height(height: int) -> int:
            """把两个多行框钉到 height，返回整表紧凑排布所需高（含底部余量）。"""
            for box in boxes:
                box.setMinimumHeight(height)
                box.setMaximumHeight(height)
            layout.invalidate()
            layout.activate()
            content.updateGeometry()
            return layout.sizeHint().height() + scroll.content_bottom_margin()

        maxed = self.isMaximized()
        self._pin_nfo_lib_form_rows(maxed)
        if not maxed:
            content.setMaximumHeight(QWIDGETSIZE_MAX)

        base = apply_box_height(full)
        deficit = base - viewport_h
        if deficit > 0:
            # 缺口在两个框之间均摊（向上取整保证压够），并守住可读下限
            shrink = min(-(-deficit // len(boxes)), full - floor)
            if shrink > 0:
                apply_box_height(full - shrink)
        elif maxed:
            slack = viewport_h - base
            grow = min(slack // len(boxes), self._NFO_LIB_FIELD_MAX_H - full)
            if grow > 0:
                apply_box_height(full + grow)
            if slack > 2 * grow:
                # 两框已到封顶高度：把内容 widget 也钉到紧凑高，富余高度留在
                # 表单下方（否则 QFormLayout 会把它摊回行间，行距又不紧凑了）
                content.setMaximumHeight(layout.sizeHint().height() + scroll.content_bottom_margin())
                layout.invalidate()
                layout.activate()
                content.updateGeometry()
        scroll.sync_content_min_height()

    # 软件工具页演员库分组内部常态几何（紧凑排布）。
    # _sync 按此摆常态，最大化只加宽（y/h 取字典）。
    _ACTOR_DB_TOOL_DESIGN = {
        "label_actor_db_note": (40, 30, 621, 20),
        "pushButton_actor_db_open": (40, 90, 200, 28),
        "pushButton_actor_db_stop": (260, 90, 200, 28),
        "pushButton_actor_db_clean_male": (40, 118, 200, 30),
        "pushButton_actor_db_fill_minnano": (260, 118, 200, 30),
        "pushButton_actor_db_verify_tmdbid": (40, 148, 200, 30),
        "pushButton_actor_db_check": (260, 148, 200, 30),
        "pushButton_actor_db_update_nfo_tmdbid": (40, 184, 200, 30),
        "pushButton_actor_db_fill_zh_javdb": (260, 184, 200, 30),
        "lineEdit_actor_db_nfo_dir": (40, 222, 451, 30),
        "pushButton_actor_db_pick_nfo_dir": (571, 217, 110, 40),
        "label_actor_db_update_nfo_desc": (40, 260, 621, 28),
        "pushButton_actor_db_sync_aliases": (571, 292, 110, 40),
        "comboBox_actor_db_alias_source": (40, 296, 451, 32),
        "checkBox_actor_db_alias_all": (40, 336, 142, 28),
        "label_actor_db_sync_offset": (186, 336, 56, 28),
        "spinBox_actor_db_sync_offset": (246, 336, 64, 28),
        "label_actor_db_sync_limit": (314, 336, 56, 28),
        "spinBox_actor_db_sync_limit": (374, 336, 72, 28),
        "label_actor_db_sync_slice_hint": (450, 336, 211, 28),
        "label_actor_db_sync_aliases_desc": (40, 356, 621, 42),
    }

    # groupBox_actor_db_maintenance 的 .ui 设计几何（30, 40, 701, 412）。
    # 通用逻辑每遍把组框高复位到此值，本方法窄态分支绝对设值、双向幂等。
    _ACTOR_DB_TOOL_BOX_DESIGN = (30, 40, 701, 412)
    # 最小化/还原态：单文件刮削组（groupBox_7）整体下移量（顶部说明删除后不再需要增高，
    # 保留为 0 以保持组间距与设计一致）。
    # 设计几何：演员库组底边 40+412=452，单文件组顶边 472（常态间隙 20）；
    # 单文件组底边 472+241=713，裁剪组（groupBox_13）顶边
    # 733，间隙 20。绝对设值（设计顶边 472 + 位移），双向幂等；
    # 最大化分支不动（通用逻辑每遍把组顶边复位到设计值，宽态自然回到 472）。
    _TOOL_SINGLE_FILE_DESIGN_Y = 472
    _TOOL_SINGLE_FILE_SHIFT = 0
    # 演员库维护组底部的别名分片行控件（按设计横排顺序，从左到右）。
    # 最小化/还原态整行顺排时按此顺序取设计宽度依次摆放，且首项「全量更新并入」
    # 的左缘由 _actor_db_sync_row_left 对齐到封面补图组的「覆盖已有图片」。
    _ACTOR_DB_SYNC_ROW_NAMES = (
        "checkBox_actor_db_alias_all",
        "label_actor_db_sync_offset",
        "spinBox_actor_db_sync_offset",
        "label_actor_db_sync_limit",
        "spinBox_actor_db_sync_limit",
        "label_actor_db_sync_slice_hint",
    )

    # 「补全别名」说明标签（label_actor_db_sync_aliases_desc）最小化态的加宽封顶。
    # 实测依据（12px 字号，整串 996px）：设计宽 621px 下首行只能排到「…缺别名的行，」
    # （612px），第二行从「勾选「全量更新」」起；768px 下首行恰好排到「…则并入全部」
    # （768px），第二行为「行，用「起始行数/单次限制」可分片续跑」——即用户要的折行。
    # 再宽只会在右缘留白、不改变折行，故按可用宽自适应后封顶此值（见
    # _actor_db_aliases_desc_width）；组框被通用逻辑压到设计宽以下时退回设计宽 621px，
    # 窄窗行为与改动前逐像素一致。
    _ACTOR_DB_ALIASES_DESC_MAX_W = 768

    @classmethod
    def _actor_db_aliases_desc_width(cls, box_w: int) -> int:
        """最小化态「补全别名」说明标签宽度：随组框可用宽自适应、封顶 768px。

        标签 x=40、右边距按设计对称留 40px，故可用宽 = 组框宽 - 80；下限取
        _ACTOR_DB_TOOL_DESIGN 的设计宽（组框窄于设计宽时不再缩小，避免窄窗回归）。
        """
        design_w = cls._ACTOR_DB_TOOL_DESIGN["label_actor_db_sync_aliases_desc"][2]
        return max(min(box_w - 80, cls._ACTOR_DB_ALIASES_DESC_MAX_W), design_w)

    # 「起始行数0+单次限制5000=默认更新数据表行数」提示标签（label_actor_db_sync_slice_hint）
    # 最小化态单行整串所需的额外余量。背景：文案由「默认更新值」改为「默认更新数据表
    # 行数」后，12px 字号下该串 horizontalAdvance 由 240px 涨到 288px，超过设计宽
    # 211px；标签 wordWrap=True，排不下就折成两行、第二行被 28px 行高裁掉尾字。
    # 实测（离屏）：QTextDocument 量高在宽 ≤295px 时为 36px（两行）、≥296px 时
    # 22px（单行），即单行临界宽约 288+8=296；余量取 8px。QLabel.heightForWidth
    # 在此不可信（宽 211 也报 26px），判据以 QTextDocument 为准，同
    # tests/test_actor_db_hint_height.py 的坑注。
    _ACTOR_DB_SLICE_HINT_PAD = 8

    @classmethod
    def _actor_db_slice_hint_width(cls, hint) -> int:
        """最小化态分片行提示标签宽度：按字体度量取单行整串宽，不足设计宽时仍取设计宽。

        hint 的 wordWrap=True 是设计需要（窄窗时不让文字顶出组框左缘外），但常态下
        设计宽 211px 排不下加长后的整串文案，折行会裁字；故按「整串宽 + 余量」加宽，
        不足设计宽时（换回短文案或大字号以外的度量差异）保持 211px 不动。
        行内左缘仍由 _ACTOR_DB_SYNC_ROW_NAMES 顺排决定，只有末位标签的宽度向右拓展。
        """
        hint.ensurePolished()  # 字号来自样式表，未 polish 时 fontMetrics 不反映 12px
        design_w = cls._ACTOR_DB_TOOL_DESIGN["label_actor_db_sync_slice_hint"][2]
        need = hint.fontMetrics().horizontalAdvance(hint.text()) + cls._ACTOR_DB_SLICE_HINT_PAD
        return max(design_w, need)

    def _actor_db_sync_row_left(self, ui, box) -> int:
        """最小化态别名分片行的左缘（组内局部 x）：与封面补图组「覆盖已有图片」严格同列。

        背景：两枚复选框分属兄弟 groupBox，绝对 x 相等即视觉上下对齐。_sync_page_layouts
        里本方法早于 _sync_cover_backfill_option_row 执行，读到的是上一遍写回的几何——
        但「覆盖已有图片」的 x 恒为设计值（_sync_cover_backfill_option_row 只按 extra
        平移另两枚，首框永远钉在 40），故本测量跨遍稳定、可直接依赖。

        跨框 mapTo 是未定义行为（两框无祖先关系，同 _sync_guaxiaomulu_clean_tip_align 里
        「跨分支 mapTo」的坑注），故经共同祖先（滚动内容区）中转：各自 mapTo(host)
        后作差，得到的就是 box 的局部 x。

        回退：ui 结构不符预期（缺框、缺控件、父子关系变化）时回退设计值 40，
        即 .ui 里的设计几何，保证与最大化态不产生额外偏差。
        """
        fallback = self._ACTOR_DB_TOOL_DESIGN["checkBox_actor_db_alias_all"][0]
        cover_box = getattr(ui, "groupBox_cover_backfill", None)
        overwrite = getattr(ui, "checkBox_cover_backfill_overwrite", None)
        if cover_box is None or overwrite is None or overwrite.parentWidget() is not cover_box:
            return fallback
        host = box.parentWidget()
        if host is None or cover_box.parentWidget() is not host:
            return fallback
        return overwrite.mapTo(host, QPoint(0, 0)).x() - box.mapTo(host, QPoint(0, 0)).x()

    # 软件工具页封面补图组三选项行的常态几何（与 MDCx.ui 一致；y 中心同为 135）。
    # _sync_cover_backfill_option_row 按此落常态，最大化只把两处间隙等量拉开。
    _COVER_BACKFILL_OPTION_DESIGN = {
        "checkBox_cover_backfill_overwrite": (40, 125, 161, 20),
        "checkBox_cover_backfill_watermark": (220, 125, 161, 20),
        "checkBox_create_link": (410, 120, 191, 30),
    }
    # groupBox_cover_backfill 的 .ui 设计宽度（30, 962, 701, 200）：增量基准。
    _COVER_BACKFILL_DESIGN_W = 701

    # 「清除所有.actors 文件夹」与 checkBox_actor_photo_ne_new（请求 Graphis 最新
    # 图片）左缘对齐——用户截图上它仍停在最右，未纳入后续对齐需求。
    _ACTOR_PAGE_GRAPHIS_TARGETS = ("pushButton_del_actor_folder",)
    # 最大化态：「清除所有.actors文件夹」右缘对到「选择目录」按钮右缘。目标即上面
    # _ACTOR_PAGE_GRAPHIS_TARGETS 那枚（groupBox_68 内 _DOCK_RIGHT 绝对定位项）；锚点
    # 取「本地头像库」行的 pushButton_select_actor_photo_folder——另一个
    # pushButton_select_gfriends_local 与它在 layoutWidget_8 的 gridLayout 里同列，
    # 窄态 689 / 宽态 1579 两态右缘恒等，任选其一皆可。
    _ACTOR_PAGE_DEL_BTN = "pushButton_del_actor_folder"
    _ACTOR_PAGE_SEL_BTN = "pushButton_select_actor_photo_folder"
    # 最大化态：「网络头像库：」显示输入框(lineEdit_net_actor_photo)与「Gfriends 本地
    # 仓库：」「本地头像库：」两行的显示输入框上下对齐。后两者与一枚 Fixed 110px 的
    # 「选择目录」按钮同处一个水平行，网格只能按「输入框 + spacing + 按钮」排完，
    # 右缘自然停在按钮列；而「网络头像库」行的输入框是 layoutWidget_8 网格里的直
    # 接项、右边没有按钮，宽态下会独占整列富余宽度，比另两枚宽出整整一枚按钮的宽
    # （1920 实测 1393 vs 1277，右缘 1579 vs 1463），上下参差。故宽态把它钉成与
    # 「Gfriends 本地仓库」输入框同宽：左缘本就同列（A1），钉宽后右缘也相等。
    # 参照输入框取 Gfriends 那枚而不是「本地头像库」那枚：两者宽态实测恒等，
    # 而 Gfriends 那枚与需求① 反推按钮列用的是同一行，几何已在本拍落定。
    _ACTOR_PAGE_NET_PATH_EDIT = "lineEdit_net_actor_photo"
    _ACTOR_PAGE_PATH_REF_EDIT = "lineEdit_gfriends_local_path"
    # 最小化态：同一枚「网络头像库」输入框改由 _sync_actor_page_narrow_align 末尾第 ⑤ 步
    # 钉宽（用户要求窄态右缘缩进对齐），与宽态第 ⑥ 步互为镜像、同一对控件同一手法。
    # 该网格（layoutWidget_8）要一并登记进 _clear_actor_narrow_align 的重排行名里，
    # 否则解锁后网格不重排，控件仍停在窄态钉宽。
    _ACTOR_PAGE_NET_PATH_GRID = "layoutWidget_8"
    # 与 checkBox_actor_photo_ne_face（使用 Graphis 头像，即 A2 列）左缘对齐的两个
    # 右缘锚定项：「补全完成后自动补全演员头像」「刮削结束后自动补全演员头像」。
    _ACTOR_PAGE_A2_TARGETS = (
        "checkBox_actor_photo_auto",
        "checkBox_actor_info_photo",
    )
    # A2 列锚点：使用 Graphis 头像
    _ACTOR_PAGE_A2_ANCHOR = "checkBox_actor_photo_ne_face"
    # 需求②：checkBox_actor_photo_kodi 与 radioButton_actor_photo_miss
    # （仅缺少头像的演员）左缘对齐——后者本就被移到 A2，故 kodi 随之到位。
    _ACTOR_PAGE_MISS_TARGETS = ("checkBox_actor_photo_kodi",)
    # 窄态：上方两枚「开始补全」收窄到与最下方那枚同宽（参照 pushButton_add_actor_pic_kodi）。
    # 三者分属三个 groupBox 的绝对定位项，宽度互不影响，故可独立处理。
    _ACTOR_NARROW_ADD_BTN_TARGETS = ("pushButton_add_actor_info", "pushButton_add_actor_pic")
    # 窄态：「仅缺少信息的演员」「仅缺少头像的演员」也左移到 A2 列。它们都是各自行的
    # **尾项**，行内间隔只能增不能减，故左移只能靠同行前导项（两个「所有演员」）收窄让位。
    # 「本地头像库」所在的来源行 hl95 结构不同（目标是 Fixed 宽单选、行尾是嵌套子布局），
    # 由下面 _ACTOR_NARROW_SOURCE_PULL 单独处理，不并入本表。
    # (行布局, 目标控件, 前导项控件, 容器)
    _ACTOR_NARROW_LEFT_PULL_ROWS = (
        (
            "horizontalLayout_101",
            "radioButton_actor_info_miss",
            "radioButton_actor_info_all",
            "layoutWidget_15",
        ),
        (
            "horizontalLayout_96",
            "radioButton_actor_photo_miss",
            "radioButton_actor_photo_all",
            "layoutWidget_12",
        ),
        (
            "horizontalLayout_103",
            "radioButton_server_jellyfin",
            "radioButton_server_emby",
            "gridLayoutWidget_25",
        ),
    )
    # 窄态：来源行 hl95 的「本地头像库」连同紧跟其后的「点击下载头像包」左移到 A2 列。
    # (行布局, 目标控件, 前导项控件, 行尾嵌套子布局)
    # 该行套不了上面那套「前导项收窄 + 行尾插 Expanding 间隔」：目标单选是 Fixed 宽
    # （min==max==59）吸不走余量、必须插间隔；而行尾 hl97 是嵌套子布局（内含
    # 「点击下载头像包」一枚 QLabel、文字实测 84px），插了间隔会与它争余量、把链接
    # 文字夹没（实测被压到 49px）。改用「stretch 挪给行尾 + 前导项钉窄」：前导项钉死
    # 后不再参与余量分配，行尾吃满剩余宽度（只会变宽、不会夹字），目标左缘正好落在
    # 前导项右侧。曾试过直接钉住行尾那枚 QLabel 的现宽，副作用是 hl95 的最小宽随之
    # 变化、把 layoutWidget_8 的三等分挤偏（A2 由 356 漂到 362），故不取。
    _ACTOR_NARROW_SOURCE_PULL = (
        "horizontalLayout_95",
        "radioButton_actor_photo_local",
        "radioButton_actor_photo_net",
        "horizontalLayout_97",
    )
    # 前导项收窄下限：QRadioButton 的 sizeHint 实测仅 52px（「所有演员」），文字 +
    # 单选指示器 ~130px 足够，与 _ACTOR_NARROW_MIN_DONOR_W / _ACTOR_PAGE_A2_MIN_LEAD_W
    # 同口径。取 130 而非 150 是为了让更窄的窗口（如 940）也能把目标对到 A2 列。
    _ACTOR_NARROW_MIN_LEAD_W = 130
    # QSizePolicy::GrowFlag 的位值。PyQt6 的 QSizePolicy.Policy 只导出 Fixed /
    # Minimum / Maximum / Preferred / MinimumExpanding / Expanding / Ignored 七档，
    # 没有单独导出 GrowFlag，只能按位取（GrowFlag=1、ShrinkFlag=2）。
    _SIZE_POLICY_GROW_FLAG = 1
    # ── 最大化态：三个布局行把目标控件对到 A2 列 ──
    # (行布局, 容器, 目标控件, 目标前的末项, 是否需要加宽容器)
    # 「仅缺少头像的演员」所在 layoutWidget_12 是固定宽 511 的绝对定位件，塞不进
    # 203px 的右移量，必须先把容器加宽（见 _ACTOR_INFO_SCOPE_HOLDER_DESIGN 注释
    # 里 layoutWidget_15 的同款做法）；另两行的容器是随窗口变的一整列。
    _ACTOR_PAGE_A2_ROWS = (
        (
            "horizontalLayout_96",
            "layoutWidget_12",
            "radioButton_actor_photo_miss",
            "radioButton_actor_photo_all",
            True,
        ),
        (
            "horizontalLayout_103",
            "gridLayoutWidget_25",
            "radioButton_server_jellyfin",
            "radioButton_server_emby",
            False,
        ),
        (
            "horizontalLayout_95",
            "layoutWidget_8",
            "radioButton_actor_photo_local",
            "radioButton_actor_photo_net",
            False,
        ),
    )
    # 「点击下载头像包」（label_download_actor_zip，在 hl95 尾部子布局 hl97 内）与
    # 「本地头像库」同行紧跟其后，用户要求二者一同对齐到 A2——它不是独立目标，
    # 只需跟着尾部 stretch 走，故不在上表单列，此处仅供断言/文档引用。
    _ACTOR_PAGE_A2_FOLLOWERS = (("radioButton_actor_photo_local", "label_download_actor_zip"),)
    # layoutWidget_12 的设计几何（相对 frame_2，MDCx.ui 140,1,511,41）：宽态加宽、
    # 窄态按此复位。它不进任何 registry，故窄态通用同步不会自愈，必须显式还原。
    _ACTOR_PAGE_HOLDER12_DESIGN = (140, 1, 511, 41)
    # 前导项收窄让位的下限：文字 + 单选指示器实测 ~130px，低于此值宁可不移
    _ACTOR_PAGE_A2_MIN_LEAD_W = 150
    # checkBox_actor_photo_kodi 在 groupBox_68 内被 _classify_inner 判为 None
    # （既非 _STRETCH 也非右缘 ≥90%），压根没进 registry，于是通用宽幅同步
    # 既不会推它、也不会在还原时把它推回来。最大化被本方法挪走后只能靠自己复位，
    # 故单独记下它的设计几何（相对 groupBox_68，与 MDCx.ui 一致）。
    _ACTOR_PAGE_MISS_DESIGN = (300, 130, 141, 40)

    # ── 演员信息组（groupBox_64）列对齐：行标签冒号 + 各行左缘对到 Graphis 列 ──
    # 锚点是 groupBox_41（头像组）horizontalLayout_93 里三个 Graphis 复选框的左缘：
    # 宽态实测 186 / 652 / 1119；窄态实测 186 / 346 / 505（此时 A1 恰与演员信息组
    # col1 起点、「中文简体」同列，故窄态用 A1 当基准 = 用户要的「与中文简体对齐」）。
    # 这里只存控件名，实际 x 一律运行时 mapTo 实测，不写死。
    _ACTOR_INFO_A1_ANCHOR = "checkBox_actor_photo_ne_backdrop"  # 使用Graphis背景
    _ACTOR_INFO_A2_ANCHOR = "checkBox_actor_photo_ne_face"  # 使用Graphis头像
    _ACTOR_INFO_A3_ANCHOR = "checkBox_actor_photo_ne_new"  # 请求Graphis最新图片
    # 演员信息组 gridLayout_14 的 col0（行标签列）设计宽
    _ACTOR_INFO_LABEL_COL_W = 130
    # 「补全范围：」行（绝对定位链路 frame_4/layoutWidget_15/horizontalLayout_101）
    _ACTOR_INFO_SCOPE_ROW = ("radioButton_actor_info_all", "radioButton_actor_info_miss")
    # layoutWidget_15 相对 frame_4 的设计几何（MDCx.ui 140,10,511,32）
    _ACTOR_INFO_SCOPE_HOLDER_DESIGN = (140, 10, 511, 32)
    # 把它左移到 136 = gridLayout_14 的 col1 起点（= content 186 = A1 列），
    # 于是「所有演员」自然落在 A1 左缘，无需再插间隔。
    _ACTOR_INFO_SCOPE_WIDE_X = 136
    # 「补全范围：」两个单选的设计宽（窄态实测 253/252，511 = 253+6+252 恰好铺满
    # layoutWidget_15 的设计宽）。宽态拉宽容器前必须先按这两值 setFixedWidth，否则
    # Minimum 策略的单选会跟着容器长到 366，钉位间隔就没空间了。
    _ACTOR_INFO_SCOPE_W = (253, 252)
    # 宽态把容器拉宽后，「仅缺少信息的演员」右缘 + 内边距留白
    _ACTOR_INFO_SCOPE_PAD = 20
    # 宽态：「演员信息数据库：」路径输入框的右缘目标列 = 「选择目录」按钮左缘。
    # 取 Gfriends 本地仓库那枚（pushButton_select_gfriends_local，Fixed 110px 不动）——
    # 它与「本地头像库」行的 pushButton_select_actor_photo_folder 同处
    # layoutWidget_8 网格的同一列，两态右缘恒等，故「选择文件」按它对齐即与下方两枚
    # 「选择目录」严格上下对齐，而下方两枚自身位置一个像素都不动。
    _ACTOR_INFO_SEL_FOLDER_BTN = "pushButton_select_gfriends_local"
    # 上面那行路径输入框锁宽的下限：MDCx.ui 里 lineEdit_actor_db_path 的 minimumSize
    # 宽 300。宽度不足（窗口很窄）时宁可不锁，保持通用布局给出的宽度。
    _ACTOR_INFO_PATH_MIN_W = 300

    # 宽态各行左缘目标（需求① + 上一轮的②③④）：「使用数据库补全演员信息」与
    # 「不存在中文时，翻译日语为中文」连同同排后续控件一并对齐 A1；语言行维持
    # 简/繁/日 = A1/A2/A3。「演员信息数据库：」路径行不在此表——它由需求② 单独
    # 按「左缘 A1、右缘 A2」铺排（见 _sync_actor_info_columns）。
    _ACTOR_INFO_WIDE_TARGETS = {
        "horizontalLayout_92": (
            ("radioButton_actor_info_zh_cn", "A1"),
            ("radioButton_actor_info_zh_tw", "A2"),
            ("radioButton_actor_info_ja", "A3"),
        ),
        "horizontalLayout_100": (("checkBox_actor_info_translate", "A1"),),
        "horizontalLayout_159": (("checkBox_actor_db", "A1"),),
    }
    # 受控行的前导缩进（必须先归零，行起点才等于 col1 起点——间隔只能右推、不能左拉）：
    # .ui 里 hl100 是 hl98 的**子布局**、hl159 是 hl158 的子布局，缩进来自「父布局的
    # spacing + 前导控件」，不是子布局自己的 margin：
    #   hl98 = [label_280(Fixed 10), hl100]  → spacing 6 + label 10 = 16px
    #   hl158 = [hl159(leftMargin 20)]       → 20px
    # 故对**父布局**归零 spacing、对 hl159 归零 leftMargin，并把 label_280 压到 0 宽。
    # (父布局名, spacing, 左内边距, 行首占位控件名或 None)
    _ACTOR_INFO_ROW_LEAD_INDENT = (
        ("horizontalLayout_98", 0, "label_280"),
        ("horizontalLayout_159", 0, None),
    )
    # 自身 leftMargin 非零、需归零的行布局（hl159 的 20px）
    _ACTOR_INFO_ROW_ZERO_MARGIN = ("horizontalLayout_159",)
    # 窄态：语言行把「中文繁体」右移到 A2、「日语」右移到 A3（中文简体不动）；
    # 「不存在中文时，翻译日语为中文」与「使用数据库补全演员信息」连同同排后续控件
    # 左移到 A1。窄态 A1→A2 仅 160px，但语言行尾部本就有 Expanding 间隔可吸收位移，
    # 故繁/日两列放得下（1000 宽实测 need 102/101）。
    _ACTOR_INFO_NARROW_TARGETS = {
        "horizontalLayout_92": (
            ("radioButton_actor_info_zh_tw", "A2"),
            ("radioButton_actor_info_ja", "A3"),
        ),
        "horizontalLayout_100": (("checkBox_actor_info_translate", "A1"),),
        "horizontalLayout_159": (("checkBox_actor_db", "A1"),),
    }

    # ── 演员页窄态（最小化/还原）右移对齐 ──
    # 锚点（自身保持不动）：checkBox_actor_info_photo「补全完成后自动补全演员头像」。
    # 它是 groupBox_64 的绝对定位右缘锚定项，窄态 abs = 480 + extra，于是各行的
    # need 全都随 extra 变化；实际 x 一律运行时 mapTo 实测，不写死。
    _ACTOR_NARROW_ANCHOR = "checkBox_actor_info_photo"
    # 走「目标收窄 + 同行间距撑开」让位的行（需求①②④）：
    # (行布局, 目标控件, 容器, 需钉宽的项[(控件, 钉宽)])
    # 前两行的容器宽恒为设计值 511（layoutWidget_15 每遍被 _sync_actor_info_columns
    # 重设，layoutWidget_12 压根不进任何 registry），故钉宽值是常数 253/252；
    # 服务类型行的容器宽随窗口变（col1 = 503/473/1393），两个单选是「均分」关系，
    # 钉宽值必须取当前实宽，locks 里写 None 即表示「钉到当前宽」。
    _ACTOR_NARROW_SCOPE_ROWS = (
        (
            "horizontalLayout_101",
            "radioButton_actor_info_miss",
            "layoutWidget_15",
            (("radioButton_actor_info_all", 253), ("radioButton_actor_info_miss", 252)),
        ),
        (
            "horizontalLayout_96",
            "radioButton_actor_photo_miss",
            "layoutWidget_12",
            (("radioButton_actor_photo_all", 253), ("radioButton_actor_photo_miss", 252)),
        ),
        (
            "horizontalLayout_103",
            "radioButton_server_jellyfin",
            "gridLayoutWidget_25",
            (("radioButton_server_emby", None), ("radioButton_server_jellyfin", None)),
        ),
    )
    # 「演员信息数据库：」行（gridLayoutWidget_14/horizontalLayout_155）：
    # 「选择文件」右移到与「选择目录」同列，路径框右缘同时撑到按钮左缘。
    # (行布局, 路径框, 按钮, 对齐基准按钮)
    _ACTOR_NARROW_PATH_ROW = (
        "horizontalLayout_155",
        "lineEdit_actor_db_path",
        "pushButton_select_actor_info_db",
        "pushButton_select_gfriends_local",
    )
    # 路径框收窄下限：低于此值宁可不右移（实测需求值 409 + extra，最低 ~297）
    _ACTOR_NARROW_PATH_MIN_W = 200
    # 「来源」行（layoutWidget_8 的 horizontalLayout_95）：目标是「本地头像库」，其右侧
    # 「点击下载头像包」（hl97 子布局）与它同属一行、随之一起右移。
    # (行布局, 目标控件, 前导项控件名, 行尾子布局名)
    _ACTOR_NARROW_SOURCE_ROW = (
        "horizontalLayout_95",
        "radioButton_actor_photo_local",
        "radioButton_actor_photo_net",
        "horizontalLayout_97",
    )
    # 目标控件收窄让位的下限：文字 + 单选指示器实测 ~130px，低于此值宁可不右移，
    # 也不让控件把自己的文字挤没（当前 need 上限 ~35px，实测不会触发，留作防线）。
    _ACTOR_NARROW_MIN_DONOR_W = 150

    def _sync_actor_db_tool_layout(self) -> None:
        """软件工具页演员库分组：紧凑排布 + 最大化拉宽。

        背景：scrollArea_10 内 groupBox_actor_db_maintenance 最大化时被通用逻辑拉宽，
        而内部绝对定位子项默认只有拉伸/右缘锚定两种跟随（说明被钉到最右侧、
        输入框/下拉拉伸盖住按钮）。本方法在 _sync_page_layouts 末尾执行
        （通用拉伸之后覆盖），接管组内全部 22 个控件：
        - 常态（最小化/还原）：按 _ACTOR_DB_TOOL_DESIGN 紧凑排布；
        - 最大化：宽幅控件拉宽，右列按钮（LibreDMM/停止/minnano/检查）保持在右列。

        例外两处：常态下「补全别名」说明「来源TMDB需配置TMDB API KEY；…」
        （整串实测 996px）按组框可用宽加宽（封顶 768px，
        见 _ACTOR_DB_ALIASES_DESC_MAX_W 的折行实测）、高度取两行；常态下末位提示标签
        「起始行数0+单次限制5000=默认更新数据表行数」按字体度量取单行整串宽
        （设计宽排不下会折行裁字，见 _actor_db_slice_hint_width）。
        （顶部同文案说明已删除，组内其余控件整体上移一行，组框同步收窄。）
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_actor_db_maintenance", None)
        if box is None or not box.isVisibleTo(self):
            # 休眠页跳过（切页 showEvent 后 _sync_page_layouts 会补齐）
            return
        widgets = {name: getattr(ui, name, None) for name in self._ACTOR_DB_TOOL_DESIGN}
        if any(w is None for w in widgets.values()):
            return
        # 链接缺项说明、打开库说明、JavDB中文名空说明已删除（两态隐藏）
        ui.label_actor_db_link_desc.hide()
        ui.label_actor_db_open_desc.hide()
        ui.label_actor_db_fill_zh_javdb_desc.hide()
        maxed = self.isMaximized()
        box_w = box.width()
        # 先按常态紧凑几何落位
        for name, (x, y, w, h) in self._ACTOR_DB_TOOL_DESIGN.items():
            widgets[name].setGeometry(x, y, w, h)
        note = widgets["label_actor_db_note"]
        if not maxed:
            # 基准取 _ACTOR_DB_TOOL_BOX_DESIGN 而非当前高：绝对设值、双向幂等。
            _bx, _by, _bw, _ = box.geometry().getRect()
            box.setGeometry(_bx, _by, _bw, self._ACTOR_DB_TOOL_BOX_DESIGN[3])
            # 常态复位顶部两枚按钮位置（translate/link 不在 _ACTOR_DB_TOOL_DESIGN 内，
            # 最大化分支改过它们的宽度，窄态必须显式恢复 200 宽）
            ui.pushButton_actor_db_translate.setGeometry(40, 58, 200, 32)
            ui.pushButton_actor_db_link.setGeometry(260, 58, 200, 32)
            # 「补全别名」说明按组框可用宽加宽（封顶见 _ACTOR_DB_ALIASES_DESC_MAX_W）：
            # 设计宽 621px 下首行只排到「…缺别名的行，」，加宽后首行排到「…则并入全部」，
            # 折行与用户要求一致。组框窄于设计宽时退回 621px，其余控件相对间距不变。
            _, desc_y0, _, desc_h0 = self._ACTOR_DB_TOOL_DESIGN["label_actor_db_sync_aliases_desc"]
            widgets["label_actor_db_sync_aliases_desc"].setGeometry(
                40, desc_y0, self._actor_db_aliases_desc_width(box_w), desc_h0
            )
            # 窄窗下通用逻辑会收缩单文件组输入框并左移其按钮，nfo/别名两行按钮
            # 跟随同量 extra 收缩（输入框/下拉宽度由 _sync_tool_page_input_fill
            # 按实时按钮位置统一拓宽，此处只摆按钮）
            extra_nb = box_w - 701
            if extra_nb != 0:
                _, pick_y0, _, pick_h0 = self._ACTOR_DB_TOOL_DESIGN["pushButton_actor_db_pick_nfo_dir"]
                # 保底 19px 间隙且输入框不窄于 150：按钮 x 不小于 40+150+19
                pick_x_nb = max(571 + extra_nb, 40 + 150 + 19)
                widgets["pushButton_actor_db_pick_nfo_dir"].setGeometry(pick_x_nb, pick_y0, 110, pick_h0)
                # 补全别名按钮与清空信息按钮同列：清空信息通用逻辑按 571+extra 左移，本按钮同公式跟随
                _, alias_y0, alias_w0, alias_h0 = self._ACTOR_DB_TOOL_DESIGN["pushButton_actor_db_sync_aliases"]
                widgets["pushButton_actor_db_sync_aliases"].setGeometry(
                    571 + extra_nb, alias_y0, alias_w0, alias_h0
                )
            # 别名分片行：统一 y 高度，整行零间隙顺排，左缘与封面补图组的
            # 「覆盖已有图片」严格上下对齐（用户要求）。此前把右缘钉到封面补图
            # 番号输入框右缘 552 反推左缘，六控件设计宽合计 601 > 552-40，
            # 左缘被推到 -49（组框左缘之外），首枚复选框被裁成「更新并入」；
            # 改由 _actor_db_sync_row_left 直接取对齐左缘（设计值 40），
            # 整行随之前移，右缘随之落到 641（末位提示标签按字体度量加宽后为 726，
            # 见下方 _actor_db_slice_hint_width），窄窗下本就略越组框右缘——
            # 组框不裁剪子控件，与组宽无关。
            _, sync_y, _, _ = self._ACTOR_DB_TOOL_DESIGN["checkBox_actor_db_alias_all"]
            current_x = self._actor_db_sync_row_left(ui, box)
            for name in self._ACTOR_DB_SYNC_ROW_NAMES:
                w = self._ACTOR_DB_TOOL_DESIGN[name][2]
                # 末位提示标签按字体度量取单行整串宽（加长文案后 211px 设计宽排不下，
                # wordWrap 会折成两行、第二行被 28px 行高裁掉）：宽度不够就向右拓展，
                # 左缘仍紧接末位 spin，行内其余五项逐像素不动。组框不裁剪子控件，
                # 窄窗下整行本就越出组框右缘（实测 760px 窗宽时右缘 641 > 组宽 409），
                # 故此处不再按组框可用宽封顶，避免又折回两行。见 _actor_db_slice_hint_width。
                if name == "label_actor_db_sync_slice_hint":
                    w = self._actor_db_slice_hint_width(widgets[name])
                widgets[name].setGeometry(current_x, sync_y, w, 28)
                current_x += w
            # 最小化/还原态：单文件刮削组顶边按设计值绝对设值、双向幂等。
            # （顶部说明删除后不再需要下移一行，_TOOL_SINGLE_FILE_SHIFT 保留为 0。）
            # 最大化分支不执行，宽态仍停在设计顶边 472。
            single = getattr(ui, "groupBox_7", None)
            if single is not None:
                _sx, _, _sw, _sh = single.geometry().getRect()
                single.setGeometry(_sx, self._TOOL_SINGLE_FILE_DESIGN_Y + self._TOOL_SINGLE_FILE_SHIFT, _sw, _sh)
            return
        # ---- 最大化：拉宽 ----
        extra = max(box_w - 701, 0)  # 组框相对设计宽度的增量
        note.setGeometry(40, 30, 621 + extra, 20)
        # ---- 顶部 5×2 维护按钮：两列同步向左右拓宽（extra 均分，列间距 20 不变，高度不变）----
        half = extra // 2
        left_w = 200 + half
        right_x = 260 + half
        right_w = 200 + extra - half
        ui.pushButton_actor_db_translate.setGeometry(40, 58, left_w, 32)
        ui.pushButton_actor_db_link.setGeometry(right_x, 58, right_w, 32)
        widgets["pushButton_actor_db_open"].setGeometry(40, 90, left_w, 28)
        widgets["pushButton_actor_db_stop"].setGeometry(right_x, 90, right_w, 28)
        widgets["pushButton_actor_db_clean_male"].setGeometry(40, 118, left_w, 30)
        widgets["pushButton_actor_db_fill_minnano"].setGeometry(right_x, 118, right_w, 30)
        widgets["pushButton_actor_db_verify_tmdbid"].setGeometry(40, 148, left_w, 30)
        widgets["pushButton_actor_db_check"].setGeometry(right_x, 148, right_w, 30)
        widgets["pushButton_actor_db_update_nfo_tmdbid"].setGeometry(40, 184, left_w, 30)
        widgets["pushButton_actor_db_fill_zh_javdb"].setGeometry(right_x, 184, right_w, 30)
        widgets["label_actor_db_update_nfo_desc"].setGeometry(40, 260, 621 + extra, 28)
        widgets["label_actor_db_sync_aliases_desc"].setGeometry(40, 356, 621 + extra, 42)
        # nfo 目录行：选择目录按钮落位 (571+extra, 110x40)；输入框宽度由
        # _sync_tool_page_input_fill 统一拓宽到按钮左侧，此处不再定宽
        _, pick_y, _, pick_h = self._ACTOR_DB_TOOL_DESIGN["pushButton_actor_db_pick_nfo_dir"]
        pick_w = 110
        pick_x = 571 + extra
        widgets["pushButton_actor_db_pick_nfo_dir"].setGeometry(pick_x, pick_y, pick_w, pick_h)
        # 别名行：补全别名按钮与「选择目录/选择文件」同列同尺寸 (571+extra, 110x40)；
        # TMDB 下拉宽度同样由 _sync_tool_page_input_fill 接管
        _ax, combo_y, _, _ah = self._ACTOR_DB_TOOL_DESIGN["comboBox_actor_db_alias_source"]
        widgets["pushButton_actor_db_sync_aliases"].setGeometry(pick_x, combo_y - 4, 110, 40)
        # 起始行/限量提示：紧贴 5000 调整框右侧，不随右缘锚定飞到最右边
        # 最大化时别名同步行其余控件保持设计几何不动（原有行为）
        spin = ui.spinBox_actor_db_sync_limit
        hint = widgets["label_actor_db_sync_slice_hint"]
        hint.setGeometry(spin.x() + spin.width() + 10, spin.y(), 261, spin.height())

    def _sync_cover_backfill_option_row(self) -> None:
        """软件工具页封面补图组三选项行：最大化时同步拉开间距。

        背景：scrollArea_10 内 groupBox_cover_backfill 最大化时被通用逻辑拉宽，
        而组内三枚复选框（覆盖已有图片 / 添加水印 / 刮削过程中自动创建软链接）
        在通用登记表里都判为 None——宽度 161/191 不足「拉伸」阈值 340，右缘 601
        也不到「右缘锚定」阈值 631，于是被整体丢下：组框变宽而三框仍挤在
        40/220/410，右侧空出一大片。本方法在 _sync_page_layouts 中紧随通用拉伸
        与 _sync_actor_db_tool_layout 之后执行（务必晚于 sync_wide_children_width，
        否则读到的组宽还是旧的），接管这三枚复选框的水平位置。

        公式（x 只动、y/w/h 恒定）：
        - extra = max(组宽 - 701, 0)：组框相对设计宽度的增量；
        - half = extra // 2：两处间隙各摊一半，首框贴左缘、末框贴右缘；
        - 覆盖已有图片 40 固定，添加水印 220+half，软链接 410+extra。
        于是 gap1 = 19+half、gap2 = 29+half（差恒为 10，与常态一致），
        末框右缘 601+extra 与组内缘 701+extra 的距离恒为 100px。

        判据用几何量而非 isMaximized()：最大化时窗口管理器先发尺寸、状态位稍后
        才生效，用 isMaximized() 会先停在常态、再跳到宽态（见
        _actor_page_stretch_extra 的坑）。extra==0 时三框恰好写回常态几何，
        故本方法天然幂等，缩小还原也能逐像素复原。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_cover_backfill", None)
        if box is None or not box.isVisibleTo(self):
            # 休眠页跳过（切页 showEvent 后 _sync_page_layouts 会补齐）
            return
        opts = {name: getattr(ui, name, None) for name in self._COVER_BACKFILL_OPTION_DESIGN}
        if any(w is None for w in opts.values()):
            return
        extra = max(box.width() - self._COVER_BACKFILL_DESIGN_W, 0)
        half = extra // 2
        x1, y1, w1, h1 = self._COVER_BACKFILL_OPTION_DESIGN["checkBox_cover_backfill_overwrite"]
        x2, y2, w2, h2 = self._COVER_BACKFILL_OPTION_DESIGN["checkBox_cover_backfill_watermark"]
        x3, y3, w3, h3 = self._COVER_BACKFILL_OPTION_DESIGN["checkBox_create_link"]
        opts["checkBox_cover_backfill_overwrite"].setGeometry(x1, y1, w1, h1)
        opts["checkBox_cover_backfill_watermark"].setGeometry(x2 + half, y2, w2, h2)
        opts["checkBox_create_link"].setGeometry(x3 + extra, y3, w3, h3)

    def _sync_tool_page_input_fill(self) -> None:
        """软件工具页显示输入框（含 TMDB 下拉）向右拓宽到右侧按钮左侧。

        背景：通用逻辑只把输入拉到设计宽+extra、按钮按右缘锚定，行内 80px
        间隙恒定（按钮改窄后空出）。本方法在 _sync_page_layouts 中紧随通用拉伸、
        _sync_actor_db_tool_layout、_sync_cover_backfill_option_row 之后执行，
        取按钮终态位置把输入右缘钉到按钮左缘-19（19px 为原设计间隙）。

        判据用实时按钮几何而非 isMaximized()：大小态通用，窄窗下按钮左移时
        输入同步收缩；仅改宽，x/y/h 不动（封面补图番号输入除外：其 x 随
        标签列缩进，见下）。布局容器内的输入（网盘/本地目录、
        本地资源库/演员名查缺）通过拓宽容器让输入列吸收增量。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        GAP = 19  # 输入右缘与右侧按钮左缘间距
        # 绝对定位输入：右缘 = 同行右侧按钮左缘 - GAP
        for in_name, btn_name in (
            ("lineEdit_single_file_path", "pushButton_select_file"),
            ("lineEdit_appoint_url", "pushButton_select_file_clear_info"),
            ("lineEdit_actor_db_nfo_dir", "pushButton_actor_db_pick_nfo_dir"),
            ("comboBox_actor_db_alias_source", "pushButton_actor_db_sync_aliases"),
        ):
            edit = getattr(ui, in_name, None)
            btn = getattr(ui, btn_name, None)
            if edit is None or btn is None:
                continue
            edit.setGeometry(edit.x(), edit.y(), max(btn.x() - GAP - edit.x(), 150), edit.height())
        # 封面补图番号行：标签与软链接助手组本地目录标签（label_338，Fixed 100
        # 列）同列，输入框与网盘目录输入同列缩进；右缘仍钉到开始补图按钮左侧。
        # 网盘/本地目录标签与输入行位置保持不变，只读其几何作列基准。
        cover_edit = getattr(ui, "lineEdit_cover_backfill_numbers", None)
        cover_btn = getattr(ui, "pushButton_cover_backfill_start", None)
        cover_box = getattr(ui, "groupBox_cover_backfill", None)
        if cover_edit is not None and cover_btn is not None and cover_box is not None:
            net_box = getattr(ui, "gridLayoutWidget_36", None)
            src_box = getattr(ui, "groupBox_21", None)
            ref_label = getattr(ui, "label_338", None)
            ref_input = getattr(ui, "lineEdit_netdisk_path", None)
            if net_box is not None and src_box is not None and ref_label is not None and ref_input is not None:
                dx = net_box.x() + (src_box.x() - cover_box.x())
                cover_label = getattr(ui, "label_cover_backfill_number", None)
                if cover_label is not None:
                    cover_label.setGeometry(dx + ref_label.x(), cover_edit.y(), ref_label.width(), cover_edit.height())
                new_x = dx + ref_input.x()
            else:
                new_x = cover_edit.x()
            cover_edit.setGeometry(new_x, cover_edit.y(), max(cover_btn.x() - GAP - new_x, 150), cover_edit.height())
        # 布局容器内的输入：拓宽容器（标签列 Fixed，输入列吸收增量）
        for box_name, btn_name in (
            ("gridLayoutWidget_36", "pushButton_select_netdisk_path"),
            ("gridLayoutWidget_18", "pushButton_select_local_library"),
        ):
            box = getattr(ui, box_name, None)
            btn = getattr(ui, btn_name, None)
            if box is None or btn is None:
                continue
            box.setGeometry(box.x(), box.y(), max(btn.x() - GAP - box.x(), 230), box.height())
            lay = box.layout()
            if lay is not None:
                lay.invalidate()
                lay.activate()
        # 刮削排除目录行（移动视频组）无右侧按钮：右缘与其它输入行看齐，
        # 钉到右侧按钮列左缘 - GAP（按钮列各按钮 x 一致，任取其一作基准）
        esc = getattr(ui, "lineEdit_escape_dir_move", None)
        ref_btn = getattr(ui, "pushButton_select_file", None)
        move = getattr(ui, "pushButton_move_mp4", None)
        if esc is not None:
            if ref_btn is not None:
                esc.setGeometry(esc.x(), esc.y(), max(ref_btn.x() - GAP - esc.x(), 150), esc.height())
            elif move is not None:
                esc.setGeometry(esc.x(), esc.y(), max(move.x() + move.width() - esc.x(), 150), esc.height())
        # 宽操作按钮（刮削/选择图片/一键创建软链接/开始移动/检查缺失番号）：
        # 右缘与本组显示输入框右缘看齐（= 右侧按钮列左缘 - GAP）；本组无右侧
        # 按钮时借用页级按钮列基准；仅改宽，x/y/h 不动
        page_ref = getattr(ui, "pushButton_select_file", None)
        for act_name, ref_name in (
            ("pushButton_start_single_file", "pushButton_select_file"),
            ("pushButton_select_thumb", None),
            ("pushButton_find_missing_number", "pushButton_select_local_library"),
            ("pushButton_move_mp4", None),
            ("pushButton_creat_symlink", "pushButton_select_netdisk_path"),
        ):
            act = getattr(ui, act_name, None)
            ref = getattr(ui, ref_name, None) if ref_name else page_ref
            if act is None or ref is None:
                continue
            act.setGeometry(act.x(), act.y(), max(ref.x() - GAP - act.x(), 150), act.height())

    @staticmethod
    def _scroll_stretch_extra(scroll) -> int:
        """某个设置页滚动区当前的横向拉伸量（> 0 表示该页确实被拉宽了）。

        公式与 CustomScrollArea.sync_wide_children_width() 内部用的完全一致：
        视口宽 - 设计宽 - 右边距，这样「被拉宽」这件事只有一个判据来源。
        """
        if scroll is None:
            return 0
        content = scroll.widget()
        viewport = scroll.viewport()
        design_w = getattr(content, "_wide_children_design_width", 0) if content is not None else 0
        if not design_w or viewport is None:
            return 0
        return viewport.width() - design_w - scroll.content_right_trim()

    def _actor_page_stretch_extra(self) -> int:
        """演员页当前的横向拉伸量（见 _scroll_stretch_extra）。

        > 0 表示页面确实被拉宽了，这才是「该把三行对到基准线上」的判据。
        这里刻意不用 isMaximized()：最大化时窗口管理器先发尺寸、状态标志稍后才
        生效，那一拍里 isMaximized() 还是 False，于是右缘锚定被绘制出来，等标志
        到位再重排一次才对齐——用户看到的就是「先在右边、再跳到左边」。改用几何
        量后，拉伸与对齐永远发生在同一拍，与标志到达顺序无关。
        """
        return self._scroll_stretch_extra(getattr(self, "_actor_scroll", None))

    def _sync_actor_page_align(self, actor_scroll=None) -> None:
        """软件设置-演员页：两个基准线上的四个控件左缘对齐（仅页面被拉宽时生效）。

        用户截图（最大化态，1920 屏 content 1650 宽，组框 1569 宽）：
          ① 「补全完成后自动补全演员头像」「刮削结束后自动补全演员头像」「清除所有
             .actors 文件夹」三者的左缘停在 content_x=1348/1348/1388，而「请求
             Graphis 最新图片」在 1136，要求三者与它严格上下对齐（各自左移
             212/212/252px）；「请求 Graphis 最新图片」自身保持不变。
          ② 「刮削结束后自动创建」要求与「仅缺少头像的演员」严格上下对齐（右移
             119px）；「仅缺少头像的演员」自身保持不变。
        还原态页面、控件、布局必须保持不变（与纯设计几何逐像素一致）。

        根因：groupBox_41/64/68 的这四个控件是绝对定位直接子项，CustomScrollArea
        的通用宽幅同步按 _classify_inner 分类——右缘 ≥ 组框宽 90% 的判为
        _DOCK_RIGHT，最大化时执行 sub.move(design_x + extra) 把它们钉到右缘；
        而锚点 checkBox_actor_photo_ne_new 在 layoutWidget_8 内，是 _STRETCH
        （两项等分拉伸），于是被推到 1136，与右缘钉定的三者分属两条线。

        做法（只改「页面被拉宽」的态，还原态一个像素都不碰，纯函数、双向幂等）：
        本方法既挂在滚动区拉伸之后的钩子上（CustomClass._post_wide_sync_hook），
        也在 _sync_page_layouts 末尾再跑一遍：
          - 拉伸量 <= 0（还原态）**直接 return，一个 setGeometry 都不发**：还原态
            几何完全由 CustomScrollArea.sync_wide_children_width() 产出，本方法
            若去「落回设计几何」就会把 _DOCK_RIGHT 的 design_x + extra 覆盖成
            design_x，还原态凭空右移 -extra（实测 win=1030 时 extra=-26，三个控件
            齐刷刷右移 26px），违反「最小化时界面、控件、布局等等保持不变」。同理
            也不能把这几个名字挪进 _MANUAL_* 从 registry 里摘掉——那会让通用同步
            彻底不碰它们，还原态同样回到设计 x。故一律不摘不改。
          - 拉伸量 > 0：先显式重跑一次宽幅同步（拿到终态 extra，休眠页由切 tab 的
            showEvent 补齐），再用 mapTo 把锚点量到与目标同一个 content 祖先
            坐标系，得到「锚点绝对 x」与「目标当前绝对 x」，目标新 x = 当前 x +
            差值后 setGeometry；守卫 x>=0 且右缘不越父级，越界（窄屏）则该控件保持
            通用逻辑给出的位置。
          - 还原时通用逻辑每遍都会 move(design_x + extra) 自愈，不依赖本方法复位。
        休眠页跳过。

        历史坑：本方法早期用 isMaximized() 当判据，在窗口管理器「先发尺寸、后发状态」
        的真实顺序下判据读成 False，右缘锚定被绘制出来，等标志到位才二次对齐，于是
        出现「先在右边、再跳到左边」的跳动。判据换成 _actor_page_stretch_extra() 的
        几何拉伸量后，拉伸与对齐必然同一拍完成；还原时同样一拍完成缩回。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_41", None)
        if box is None or not box.isVisibleTo(self):
            return
            # 还原态（页面未被拉宽）：除 checkBox_actor_photo_kodi 外一个像素都不碰，
            # 几何完全交给通用宽幅同步（见 docstring）。kodi 未进 registry，通用逻辑
            # 不会自愈，必须显式复位，否则拉宽挪走后会一直停在锚点线上。
            # 判据是拉伸量而非 isMaximized()，理由见 _actor_page_stretch_extra。
            # ③「刮削结束后自动创建」（kodi）未进 registry，通用同步不会自愈，必须跟着
            # 刚被移到 A2 的「仅缺少头像的演员」一起到位——故必须排在下面 hl96 循环
            # **之后**：量到的是 miss 移动后的新 x。
            return
        if actor_scroll is not None and actor_scroll.isVisibleTo(self):
            actor_scroll.sync_wide_children_width()  # 取终态 extra，勿量过期几何
        graphis = getattr(ui, "checkBox_actor_photo_ne_new", None)
        miss = getattr(ui, "radioButton_actor_photo_miss", None)
        widgets = {
            name: getattr(ui, name, None) for name in self._ACTOR_PAGE_GRAPHIS_TARGETS + self._ACTOR_PAGE_MISS_TARGETS
        }
        if graphis is None or miss is None or any(w is None for w in widgets.values()):
            return
        content = box.parentWidget()
        if content is None:
            return

        def shift_to(name, anchor):
            """把 name 的左缘对到 anchor 的左缘（同一 content 坐标系）。"""
            w = widgets[name]
            if w.parentWidget() is None or anchor.parentWidget() is None:
                return
            dx = anchor.mapTo(content, anchor.rect().topLeft()).x() - w.mapTo(content, w.rect().topLeft()).x()
            g = w.geometry()
            nx = g.x() + dx
            if nx < 0 or nx + g.width() > w.parentWidget().width():
                return  # 越出父级（窄屏最大化）：保持通用逻辑给出的位置
            if dx:
                w.setGeometry(nx, g.y(), g.width(), g.height())

        for name in self._ACTOR_PAGE_GRAPHIS_TARGETS:
            shift_to(name, graphis)
        for name in self._ACTOR_PAGE_MISS_TARGETS:
            shift_to(name, miss)

    def _clear_actor_wide_align(self) -> None:
        """清掉最大化态 A2 列对齐留下的钉宽/容器几何/stretch（先清后建，故幂等）。

        与 _clear_actor_narrow_align 同款：钉宽「记录原 min/max、原样写回」，
        不用 setFixedWidth(0) 真解锁——本方法与窄态那一对都会跑在
        _sync_actor_info_columns 之后，真解锁会拆掉那一拍刚钉好的宽态铺排。
        逆序写回的原因同上：同一控件一趟里可能被钉两次。
        """
        for kind, obj, saved in reversed(self._actor_wide_restores):
            if obj is None:
                continue
            if kind == "size":
                obj.setMinimumWidth(saved[0])
                obj.setMaximumWidth(saved[1])
                obj.updateGeometry()
            elif kind == "geometry":
                obj.setGeometry(saved)
            elif kind == "stretch":
                for i, value in enumerate(saved):
                    obj.setStretch(i, value)
        self._actor_wide_restores = []
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        for row_name, _, _, _, _ in self._ACTOR_PAGE_A2_ROWS:
            row = getattr(ui, row_name, None)
            if row is None or row.parentWidget() is None:
                continue
            row.invalidate()
            row.activate()

    def _sync_actor_page_wide_a2_align(self, actor_scroll=None) -> None:
        """最大化态：把若干控件左缘对到 A2 列（使用 Graphis 头像），锚点自身不动。

        用户需求（最大化时；最小化/还原态页面、布局、控件保持不变）：
          ① 「Jellyfin」「补全完成后自动补全演员头像」「本地头像库」「点击下载头像包」
             「刮削结束后自动补全演员头像」向左移动到与「使用 Graphis 头像」严格上下
             对齐的位置，「使用 Graphis 头像」自身保持不变；
          ② 「仅缺少头像的演员」「刮削结束后自动创建」向右移动到同一列。
          ③ 「清除所有.actors文件夹」右侧向右移动到与「选择目录」按钮上下对齐
             （右缘对齐，只平移不改宽度）。
          ④ 「网络头像库：」显示输入框收窄成与「Gfriends 本地仓库：」「本地头像库：」
             两行显示输入框同宽（上下对齐；左缘本就同列，收窄后右缘也相等）。

        A2 锚点是 checkBox_actor_photo_ne_face（使用 Graphis 头像，layoutWidget_8 内
        的 _STRETCH 三等分项），实际 x 一律运行时 mapTo 实测，绝不写死——
        1920 宽实测 652、1600 宽实测 546。

        三类控件三种手法（与窄态那套互不重叠，各自登记、各自还原）：
          - 右缘锚定的绝对定位项（「补全完成后自动补全演员头像」等）由
            _sync_actor_page_align 的 shift_to 处理，本方法不碰。
          - 只需「前导项收窄让位」的行：hl103（Jellyfin）与 hl95（本地头像库）。
            两行都是「均分可用宽」，把目标前的末项钉窄，目标的左缘就落在
            (行左缘 + 前导宽 + spacing) 上；行内总需求随之小于可用宽，**尾部项
            吸收全部余量**（hl103 的 Jellyfin / hl95 的 hl97），故这里必须把
            stretch 从头一项挪给尾一项——否则 Qt 会把余量摊回头一项，钉窄失效。
          - 容器是固定宽绝对定位件的行：hl96（仅缺少头像的演员）所在的
            layoutWidget_12 恒为 511，塞不下 203px 的右移量，先把容器加宽到
            「2×(目标相对位置) + spacing」让两等分项各占一半，再钉住。
          - 网格里的直系输入框（lineEdit_net_actor_photo）：钉宽（lock_width），
            见方法末尾 ⑥ 的注释。

        判据用 _actor_page_stretch_extra() 的几何拉伸量而非 isMaximized()，理由见
        _actor_page_stretch_extra docstring。窄态第一步清干净即 return，
        最小化态一个像素都不碰（layoutWidget_12 按设计几何复位，它不进任何
        registry、通用同步不会自愈）。休眠页跳过。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_41", None)
        if box is None or not box.isVisibleTo(self):
            return
        self._clear_actor_wide_align()
        if self._actor_page_stretch_extra() <= 0:
            # 窄态：只还原被加宽的容器（它不进任何 registry，通用同步不会自愈）。
            # kodi 的窄态位置由 _sync_actor_page_align 的窄态分支负责（它把 kodi
            # 按设计几何复位），本方法窄态一个像素都不碰它——否则会覆盖 ① 的结果。
            holder = getattr(ui, "layoutWidget_12", None)
            if holder is not None and holder.parentWidget() is not None:
                holder.setGeometry(*self._ACTOR_PAGE_HOLDER12_DESIGN)
            return
        # 刻意**不**重跑 sync_wide_children_width()：它会把 ① 刚对好的右缘锚定项
        # 重新 move(design_x + extra) 钉回右缘，把 ① 的成果整个抹掉。① 排在本方法
        # 之前、同一拍里刚跑完宽幅同步，量到的几何已是终态。
        content = box.parentWidget()
        if content is None:
            return
        anchor = getattr(ui, self._ACTOR_PAGE_A2_ANCHOR, None)
        if anchor is None:
            return
        anchor_x = anchor.mapTo(content, anchor.rect().topLeft()).x()

        def left_x(w):
            return w.mapTo(content, w.rect().topLeft()).x()

        def lock_width(w, width):
            if w is None:
                return
            if w.minimumWidth() == width and w.maximumWidth() == width:
                return
            self._actor_wide_restores.append(("size", w, (w.minimumWidth(), w.maximumWidth())))
            w.setFixedWidth(width)
            w.updateGeometry()

        def lock_stretch(row, tail_idx):
            self._actor_wide_restores.append(("stretch", row, [row.stretch(i) for i in range(row.count())]))
            for i in range(row.count()):
                row.setStretch(i, 1 if i == tail_idx else 0)
            row.invalidate()
            row.activate()

        # ① 两个「自动补全演员头像」是右缘锚定的绝对定位项（groupBox_41 / groupBox_64
        # 的直接子项），通用宽幅同步每遍都按 design_x + extra 把它们钉回右缘，故这里
        # 与 _sync_actor_page_align 的 shift_to 同款：量出差值后 setGeometry 左移。
        # 放在本方法而不是 _sync_actor_page_align 里，是因为 _sync_actor_info_columns
        # 末尾的 grid.invalidate()+activate() 会把它们重新弹回右缘——本方法排在它
        # 之后，才不会被覆盖（还原态则完全交给通用同步，本方法一个像素都不碰）。
        for name in self._ACTOR_PAGE_A2_TARGETS:
            w = getattr(ui, name, None)
            if w is None or w.parentWidget() is None:
                continue
            dx = anchor_x - left_x(w)
            g = w.geometry()
            nx = g.x() + dx
            if nx < 0 or nx + g.width() > w.parentWidget().width():
                continue  # 越出父级：保持通用逻辑给出的位置
            if dx:
                w.setGeometry(nx, g.y(), g.width(), g.height())

        # ③「刮削结束后自动创建」（kodi）未进 registry，通用同步不会自愈，必须跟着
        # 刚被移到 A2 的「仅缺少头像的演员」一起到位——故必须排在下面 hl96 循环
        # **之后**：量到的是 miss 移动后的新 x。
        # 刚被移到 A2 的「仅缺少头像的演员」一起到位——故必须排在 ② 的 hl96 循环
        # **之后**：量到的是 miss 移动后的新 x。
        for row_name, holder_name, target_name, lead_name, widen in self._ACTOR_PAGE_A2_ROWS:
            row = getattr(ui, row_name, None)
            holder = getattr(ui, holder_name, None)
            target = getattr(ui, target_name, None)
            lead = getattr(ui, lead_name, None)
            if row is None or holder is None or target is None or lead is None:
                continue
            if row.parentWidget() is not holder or target.parentWidget() is not holder:
                continue
            tidx = row.indexOf(target)
            lidx = row.indexOf(lead)
            if tidx < 0 or lidx < 0 or lidx >= tidx:
                continue
            if widen:
                # 容器是固定宽绝对定位件：先按「两等分项各占一半」加宽，再钉住两半。
                dx, dy, _, dh = self._ACTOR_PAGE_HOLDER12_DESIGN
                target_rel = anchor_x - holder.mapTo(content, holder.rect().topLeft()).x()
                width = 2 * target_rel + row.spacing()
                if width <= self._ACTOR_PAGE_HOLDER12_DESIGN[2]:
                    continue  # 容器已够宽（或目标反而更左）：交给下一轮/通用逻辑
                self._actor_wide_restores.append(("geometry", holder, holder.geometry()))
                holder.setGeometry(dx, dy, width, dh)
                grid = getattr(ui, "gridLayout_14", None)
                if grid is not None:
                    grid.invalidate()
                    grid.activate()
            row.invalidate()
            row.activate()
            # 前导项钉到「让目标的左缘正好落在锚点上」的宽度
            between = sum(
                row.itemAt(i).widget().width() for i in range(lidx + 1, tidx) if row.itemAt(i).widget() is not None
            )
            need_w = anchor_x - left_x(lead) - row.spacing() * (tidx - lidx) - between
            if need_w < self._ACTOR_PAGE_A2_MIN_LEAD_W:
                continue  # 会把前导项自己的文字挤没：宁可不移
            # 余量必须全部交给目标之后的尾部项，否则 Qt 会摊回头一项、钉窄失效
            lock_stretch(row, tidx)
            lock_width(lead, need_w)
            row.invalidate()
            row.activate()
        kodi = getattr(ui, "checkBox_actor_photo_kodi", None)
        miss = getattr(ui, "radioButton_actor_photo_miss", None)
        if kodi is not None and miss is not None and kodi.parentWidget() is not None:
            dx = anchor_x - left_x(miss)
            kg = kodi.geometry()
            kx = kg.x() + dx
            # 只右移不左拉（需求②说的是「向右移动」）：miss 因让位下限不够而没动时
            # dx 为负，此时 kodi 必须原地不动，否则会被反向拖走。
            if dx > 0 and 0 <= kx and kx + kg.width() <= kodi.parentWidget().width() and kx != kg.x():
                kodi.setGeometry(kx, kg.y(), kg.width(), kg.height())
        # ④ 最大化态：最下方「开始补全」按钮(pushButton_add_actor_pic_kodi)宽度与
        # 上方「开始补全」按钮(pushButton_add_actor_pic)一致，上方按钮自身不动；
        # 最小化时本方法首步清干净即 return，按钮宽保持设计值 130。
        # 注意：上面的 kodi 是复选框 checkBox_actor_photo_kodi，此处是同名后缀的按钮。
        ref_btn = getattr(ui, "pushButton_add_actor_pic", None)
        kodi_btn = getattr(ui, "pushButton_add_actor_pic_kodi", None)
        if kodi_btn is not None and ref_btn is not None and kodi_btn.parentWidget() is not None:
            target_w = ref_btn.width()
            if target_w > 0 and kodi_btn.width() != target_w:
                if 0 <= kodi_btn.x() and kodi_btn.x() + target_w <= kodi_btn.parentWidget().width():
                    # 绝对定位件只锁 min/max 还原时不会自动缩回（无布局驱动），故连同
                    # 几何一起登记，窄态 _clear_actor_wide_align 逆序写回即复原 130。
                    self._actor_wide_restores.append(("geometry", kodi_btn, kodi_btn.geometry()))
                    lock_width(kodi_btn, target_w)
                    kg2 = kodi_btn.geometry()
                    kodi_btn.setGeometry(kg2.x(), kg2.y(), target_w, kg2.height())
        # ⑤ 最大化态：「清除所有.actors文件夹」右缘对到「选择目录」按钮右缘。实测两者
        # 右缘差在宽态恒为 20px（1920 1559 vs 1579 / 1600 1239 vs 1259 / 1366 1005 vs
        # 1025 / 1100 739 vs 759），窄态为 -7px，故只在本方法（宽态）里补这段右移，
        # 最小化态一个像素都不碰。
        # 只平移不改宽度：需求说的是「右侧向右移动」，而两者设计宽本就不同
        # （171 vs 110），拉宽会把「清除所有.actors文件夹」的按钮撑成另一种长相。
        # 目标是 groupBox_68 内 _DOCK_RIGHT 绝对定位项，通用宽幅同步每遍都按
        # design_x + extra 钉回，故与 ① 同款 setGeometry 即天然幂等、窄态往返自愈，
        # 不必登记 _actor_wide_restores（与 _ACTOR_PAGE_A2_TARGETS 同理）。
        del_btn = getattr(ui, self._ACTOR_PAGE_DEL_BTN, None)
        sel_btn = getattr(ui, self._ACTOR_PAGE_SEL_BTN, None)
        if (
            del_btn is not None
            and sel_btn is not None
            and del_btn.parentWidget() is not None
            and sel_btn.parentWidget() is not None
        ):
            dx = left_x(sel_btn) + sel_btn.width() - left_x(del_btn) - del_btn.width()
            g = del_btn.geometry()
            nx = g.x() + dx
            if dx and 0 <= nx and nx + g.width() <= del_btn.parentWidget().width():
                del_btn.setGeometry(nx, g.y(), g.width(), g.height())
        # ⑥ 最大化态：「网络头像库：」显示输入框钉成与「Gfriends 本地仓库：」「本地
        # 头像库：」两行显示输入框同宽（上下对齐）。它在 layoutWidget_8 网格里是直接项、
        # 右侧无按钮，宽态独占整列富余宽；另两枚右缘被 Fixed 110px 的「选择目录」按钮
        # 顶住，故差出一枚按钮宽。钉宽是唯一手段（它不进任何 registry，通用宽幅同步
        # 只按设计宽拉伸它的父容器，不会碰它自身的宽，故钉住的宽不会被抹掉）；
        # 格子比控件宽时 Qt 把控件排在格子左缘，左缘本就与另两枚同列（A1），
        # 钉宽后右缘也相等。窄态第一步清干净即 return，一个像素都不碰——
        # 窄态里同一枚输入框由 _sync_actor_page_narrow_align 末尾第 ⑤ 步负责
        # （最小化时右缘要向左缩进对齐，成因与手法完全相同）。
        net = getattr(ui, self._ACTOR_PAGE_NET_PATH_EDIT, None)
        ref = getattr(ui, self._ACTOR_PAGE_PATH_REF_EDIT, None)
        net_grid = getattr(ui, "layoutWidget_8", None)
        if (
            net is not None
            and ref is not None
            and net_grid is not None
            and net_grid.layout() is not None
            and net.parentWidget() is net_grid
            and ref.parentWidget() is not None
        ):
            grid8 = net_grid.layout()
            grid8.invalidate()
            grid8.activate()  # 先落定，才能量到参照输入框的终态宽
            want_w = ref.width()
            if 0 < want_w < net.width() and want_w >= net.minimumWidth():
                lock_width(net, want_w)
                grid8.invalidate()
                grid8.activate()
                # 读回纠偏：布局重排后若有 1px 级取整误差，用实测差补回去
                drift = net.width() - want_w
                if drift:
                    lock_width(net, want_w - drift)
                    grid8.invalidate()
                    grid8.activate()

    def _clear_actor_info_spacers(self) -> None:
        """清掉 _sync_actor_info_columns 注入的间隔项与宽度锁（每遍同步先清后建，故幂等）。

        宽度锁必须一并解除：钉位时给控件 setFixedWidth 防 Minimum 策略被间隔挤瘦，
        还原态若不解锁，控件就永久钉在宽态的宽/窄上（演员数据库路径输入框尤其明显）。
        """
        for w, width in self._actor_info_width_locks:
            if w is not None:
                w.setFixedWidth(width)
                w.updateGeometry()
        self._actor_info_width_locks = []
        for obj, saved, _kind in self._actor_info_margin_restores:
            if obj is None:
                continue
            if isinstance(saved, int):
                obj.setSpacing(saved)
            else:
                obj.setContentsMargins(saved)
        self._actor_info_margin_restores = []
        for row, spacer in self._actor_info_spacers:
            if row is not None and spacer is not None:
                row.removeItem(spacer)
        self._actor_info_spacers = []

    def _sync_actor_page_wide_hooks(self, actor_scroll=None) -> None:
        """演员页宽幅拉伸后的四拍对齐（顺序敏感，勿调换）。

        ① _sync_actor_page_align：把「清除所有.actors 文件夹」对到 checkBox_actor_photo_ne_new
           （请求 Graphis 最新图片），把两个「自动补全演员头像」对到 A2 列。
        ② _sync_actor_info_columns：演员信息组三列对齐，它的 A3 锚点正是同一个
           checkBox_actor_photo_ne_new，必须在 ① 之后量才不会读到过期 x。
        ③ _sync_actor_page_wide_a2_align：最大化态把「Jellyfin」「本地头像库」「仅缺少
           头像的演员」等对到 A2 列（使用 Graphis 头像），并把「清除所有.actors 文件夹」
           右缘对到「选择目录」按钮右缘（需求③，也是宽态专属）。排在 ② 之后是**必须的**：
           ② 末尾 grid.invalidate()+activate() 会把 _DOCK_RIGHT 的绝对定位项重新
           钉回右缘（design_x + extra），把 ① 刚对好的两个「自动补全演员头像」弹回
           去（实测被弹回 1348）。
        ④ _sync_actor_page_narrow_align：窄态把「仅缺少信息的演员」「仅缺少头像
           的演员」「本地头像库」右移到「补全完成后自动补全演员头像」那一列上——
           必须在 ② 之后，因为它要量的正是 ② 顺带定下的那两个单选的当前 x。
        """
        self._sync_actor_page_align(actor_scroll)
        self._sync_actor_info_columns(actor_scroll)
        self._sync_actor_page_wide_a2_align(actor_scroll)
        self._sync_actor_page_narrow_align(actor_scroll)

    def _sync_actor_info_columns(self, actor_scroll=None) -> None:
        """演员信息组：行标签冒号对齐 + 各行左缘对齐到 Graphis 列 + 路径框宽度铺排。

        锚点是 groupBox_41（头像组）三个 Graphis 复选框的左缘，运行时 mapTo 实测：
          A1 = 使用Graphis背景、A2 = 使用Graphis头像、A3 = 请求Graphis最新图片。
        窄态(1000) 实测 A1 = 186，与演员信息组 col1 起点同 x；宽态(1920) = 186/652/1119。
        「中文简体」自身恒在 col1 起点（= A1），故窄态用 A1 当基准与用户要求的
        「与中文简体严格上下对齐」完全等价。

        行标签冒号对齐（窄宽双态）：「补全语言：」「演员信息数据库：」与「补全范围：」
        的右缘严格一致。两标签是 Fixed 130 右对齐，只要 gridLayout_14 的 col0 从 x=0
        起算就自然成立——.ui 已给 col1 各行加尾部 Expanding spacer 把 col0 钉到最左。
        本方法把 col0 钉死 130px 下限：否则 QGridLayout 会把富余宽度摊给 col0
        （实测宽态 col0 长到 762、col1 起点被推到 818），col1 内的行起点右移。

        宽态（需求①、②）：
          ① 「使用数据库补全演员信息」「不存在中文时，翻译日语为中文」及其同排后续
             控件（点击下载链接 / 不勾选则无中文时使用日语）左缘对齐 A1；
             「中文简体」同在 A1，「中文繁体」A2、「日语」A3 不变。
          ② 「演员信息数据库：」路径输入框左缘扩到 A1、右缘缩到「选择目录」按钮左缘，
             「选择文件」按钮随之右移到该列，与下方两枚「选择目录」严格上下对齐
             （下方两枚自身位置不变）。窄态此行不动（窄态由需求⑨ 的钉宽负责）。
        窄态：「不存在中文时，翻译日语为中文」「使用数据库补全演员信息」
          及其同排后续控件左缘对齐 A1（即「中文简体」所在列）；「所有演员」同左移到
          A1；语言行「中文繁体」右移到 A2、「日语」右移到 A3（中文简体不动，
          A2/A3 锚点自身不动；行尾 Expanding 间隔吸收位移）。

        共同手法（col1 内的行受 QGridLayout 管理，对子控件 setGeometry 会在下次
        layout 激活时被覆盖，一律用 QSpacerItem 注入定位）：
          - 间隔宽度取「目标绝对 x − 控件当前实测绝对 x」，天然含自身宽度与 spacing，
            不会随同行控件增多而累积误差；
          - 钉位时无条件 setFixedWidth 锁住当宽：这些控件是 Minimum 策略，插入固定宽
            间隔后会被挤瘦（实测「所有演员」253→52），锁宽后同行控件各按设计宽排布；
          - 每次插完 invalidate+activate 让 Qt 重排，下一目标才量得到新位置；
          - 「补全范围：」行是绝对定位链路（frame_4 → layoutWidget_15 → hl101），与
            gridLayout_14 无关：容器左移到 x=136（= col1 起点）后「所有演员」自然落在
            A1；宽态再把容器拉宽到容得下 A2 并把「仅缺少信息的演员」钉到 A2。行内只剩
            两个 Fixed 宽单选+固定间隔时 QHBoxLayout 会把富余宽度摊到**行首**（凭空
            56px 空档），故尾部补一个 Expanding 间隔。
          - setColumnMinimumWidth/setColumnStretch 是**持久**设置，窄态也必须钉住
            col0=130，否则「先最大化再还原」窄态会被宽态的列宽污染。

        判据用 _actor_page_stretch_extra() 的几何拉伸量而非 isMaximized()，理由见
        _sync_actor_page_align docstring。休眠页跳过。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_64", None)
        grid = getattr(ui, "gridLayout_14", None)
        if box is None or grid is None or not box.isVisibleTo(self):
            return
        scope_holder = getattr(ui, "layoutWidget_15", None)
        content = box.parentWidget()
        if content is None:
            return

        wide = self._actor_page_stretch_extra() > 0
        # 先无条件清干净上一遍留下的间隔/宽度锁/缩进，再按当前态重建。窄态同样要走完
        # 重建流程（需求⑦ 窄态也要钉位），故不能在清理后提前 return。
        self._clear_actor_info_spacers()
        if wide and actor_scroll is not None and actor_scroll.isVisibleTo(self):
            actor_scroll.sync_wide_children_width()  # 取终态 extra，勿量过期几何

        # col0 钉 130 → col1 起点 = gridLayoutWidget_14.x + 130 + spacing = content 186。
        # 窄态本就如此（无富余宽度可摊），此调用幂等；宽态是必需。
        grid.setColumnMinimumWidth(0, self._ACTOR_INFO_LABEL_COL_W)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.invalidate()
        grid.activate()

        anchors = {}
        for key, name in (
            ("A1", self._ACTOR_INFO_A1_ANCHOR),
            ("A2", self._ACTOR_INFO_A2_ANCHOR),
            ("A3", self._ACTOR_INFO_A3_ANCHOR),
        ):
            anchor = getattr(ui, name, None)
            if anchor is None:
                return
            anchors[key] = anchor.mapTo(content, anchor.rect().topLeft()).x()

        def pin(row, name, target_x, width=None):
            """把 row 内 name 的左缘推到 target_x；锁宽后按实测差值插前导间隔。

            width 给定时同时把控件钉到该宽（「演员信息数据库：」输入框铺 A1→A2 用）。
            """
            w = getattr(ui, name, None)
            if w is None or w.parentWidget() is None:
                return
            idx = row.indexOf(w)
            if idx < 0:
                return
            row.invalidate()
            row.activate()  # 先落定，才能量到本控件的当前真实 x
            if not any(locked is w for locked, _ in self._actor_info_width_locks):
                self._actor_info_width_locks.append((w, w.width()))
                w.setFixedWidth(width if width is not None else w.width())
                row.invalidate()
                row.activate()
            need = target_x - w.mapTo(content, w.rect().topLeft()).x()
            if need <= 0:
                return  # 已在目标列或更右，无需再插间隔
            spacer = QSpacerItem(need, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            row.insertItem(idx, spacer)
            self._actor_info_spacers.append((row, spacer))
            row.invalidate()
            row.activate()  # 让下一目标量到插入后的新位置

        # 受控行的前导缩进必须先清零，行起点才等于 col1 起点（A1）——间隔只能右推、
        # 不能左拉。缩进来自「父布局 spacing + 行首占位控件」，见常量注释。
        # 只动 spacing 与 leftMargin，不整组重设 contentsMargins：后者会连带清掉
        # right/bottom，在 QHBoxLayout 里改动过多边距曾导致渲染期崩溃。
        for parent_name, spacing, lead_widget in self._ACTOR_INFO_ROW_LEAD_INDENT:
            parent = getattr(ui, parent_name, None)
            if parent is None or parent.parentWidget() is None:
                continue
            if parent.spacing() != spacing:
                self._actor_info_margin_restores.append((parent, parent.spacing(), None))
                parent.setSpacing(spacing)
            if lead_widget:
                head = getattr(ui, lead_widget, None)
                if head is not None and head.width() > 0:
                    if not any(locked is head for locked, _ in self._actor_info_width_locks):
                        self._actor_info_width_locks.append((head, head.width()))
                        head.setFixedWidth(0)
            parent.invalidate()
            parent.activate()
        for child_name in self._ACTOR_INFO_ROW_ZERO_MARGIN:
            child = getattr(ui, child_name, None)
            if child is None:
                continue
            margins = child.contentsMargins()
            if margins.left() != 0:
                self._actor_info_margin_restores.append((child, margins, None))
                child.setContentsMargins(0, margins.top(), margins.right(), margins.bottom())
        grid.invalidate()
        grid.activate()

        # 各行左缘对齐：宽态与窄态用不同的目标列集合。
        targets = self._ACTOR_INFO_WIDE_TARGETS if wide else self._ACTOR_INFO_NARROW_TARGETS
        for layout_name, rows in targets.items():
            row = getattr(ui, layout_name, None)
            if row is None or row.parentWidget() is None:
                continue
            for name, key in rows:
                pin(row, name, anchors[key])

        # 宽态需求②：「演员信息数据库：」路径输入框左缘 A1、右缘缩到「选择目录」按钮列，
        # 「选择文件」随之右移，与下方两枚「选择目录」严格上下对齐（下方两枚自身不动）。
        # 宽度不写死：由「选择目录」按钮的实测左缘反推（含行内 spacing，故按钮恰好
        # 落在该列上），窗口任意宽度都成立；宽态三处 A1 恒等，无需插前导间隔。
        if wide:
            path_row = getattr(ui, "horizontalLayout_155", None)
            sel = getattr(ui, self._ACTOR_INFO_SEL_FOLDER_BTN, None)
            if (
                path_row is not None
                and path_row.parentWidget() is not None
                and sel is not None
                and sel.parentWidget() is not None
            ):
                sel_x = sel.mapTo(content, sel.rect().topLeft()).x()
                want_w = sel_x - path_row.spacing() - anchors["A1"]
                if want_w >= self._ACTOR_INFO_PATH_MIN_W:
                    pin(path_row, "lineEdit_actor_db_path", anchors["A1"], width=want_w)

        # 「补全范围：」行：绝对定位链路。容器左移到 col1 起点后「所有演员」落在 A1，
        # 宽态再拉宽容器并把「仅缺少信息的演员」钉到 A2。
        row = getattr(ui, "horizontalLayout_101", None)
        if row is None or scope_holder is None or row.parentWidget() is not scope_holder:
            return
        sx, sy, design_w, sh = self._ACTOR_INFO_SCOPE_HOLDER_DESIGN
        holder_w = design_w
        if wide:
            origin_x = scope_holder.mapTo(content, scope_holder.rect().topLeft()).x()
            holder_w = max(
                anchors["A2"] - origin_x + self._ACTOR_INFO_SCOPE_W[1] + self._ACTOR_INFO_SCOPE_PAD,
                design_w,
            )
        # 先把两个单选钉回设计宽（253/252），再决定容器宽：顺序不能反——容器一旦拉宽，
        # Minimum 策略的单选会跟着长到 366，钉位间隔就没空间了。
        for name, width in zip(self._ACTOR_INFO_SCOPE_ROW, self._ACTOR_INFO_SCOPE_W, strict=True):
            w = getattr(ui, name, None)
            if w is not None and not any(locked is w for locked, _ in self._actor_info_width_locks):
                self._actor_info_width_locks.append((w, w.width()))
                w.setFixedWidth(width)
                w.updateGeometry()
        scope_holder.setGeometry(self._ACTOR_INFO_SCOPE_WIDE_X, sy, holder_w, sh)
        grid.invalidate()
        grid.activate()
        row.invalidate()
        row.activate()
        if wide:
            # 尾部 Expanding 间隔：否则富余宽度摊到行首，两列整体偏 56px。
            tail = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            row.addItem(tail)
            self._actor_info_spacers.append((row, tail))
            row.invalidate()
            row.activate()
        pin(row, self._ACTOR_INFO_SCOPE_ROW[0], anchors["A1"])
        if wide:
            pin(row, self._ACTOR_INFO_SCOPE_ROW[1], anchors["A2"])

    def _clear_actor_narrow_align(self) -> None:
        """清掉窄态右移对齐留下的间隔/钉宽/stretch（每遍同步先清后建，故幂等、往返自愈）。

        钉宽一律「记录原 min/max、原样写回」，不用 setFixedWidth(0) 真解锁：本方法跑在
        _sync_actor_info_columns 之后，而后者刚把 hl101 的两个单选钉在 253/252
        （_ACTOR_INFO_SCOPE_W），这里真解锁会顺手拆掉那一拍的锁、宽态铺排随即失准。
        对 hl96 记录到的本就是 (0, QWIDGETSIZE_MAX)，写回即真解锁，同一套代码两边都对。

        还原必须**逆序**（后记的先写回，最后写回的就是最早记下的那个原值）：同一控件
        在一趟里往往被钉两次（先钉设计宽、再钉让位后的收窄宽），正序还原会让中间值
        覆盖原值、把控件永久钉死在窄态的收窄宽上（实测 hl96 的「仅缺少头像的演员」
        窄态钉到 237 后再也回不去，宽态随之被带歪）。
        """
        for row, spacer in self._actor_narrow_spacers:
            if row is not None and spacer is not None:
                row.removeItem(spacer)
        self._actor_narrow_spacers = []
        for kind, obj, saved in reversed(self._actor_narrow_restores):
            if obj is None:
                continue
            if kind == "size":
                obj.setMinimumWidth(saved[0])
                obj.setMaximumWidth(saved[1])
                obj.updateGeometry()
            elif kind == "spacing":
                obj.setSpacing(saved)
            elif kind == "stretch":
                for i, value in enumerate(saved):
                    obj.setStretch(i, value)
            elif kind == "geometry":
                # 绝对定位件（如窄态收窄后的两个「开始补全」按钮）：只还原 min/max
                # 不会把宽度缩回去——没有布局驱动 resize，故连几何一并写回。
                obj.setGeometry(saved)
        self._actor_narrow_restores = []
        ui = getattr(self, "Ui", None)
        names = [row[0] for row in self._ACTOR_NARROW_SCOPE_ROWS] + [
            self._ACTOR_NARROW_SOURCE_ROW[0],
            self._ACTOR_NARROW_PATH_ROW[0],
        ]
        for name in names:
            row = getattr(ui, name, None)
            if row is None or row.parentWidget() is None:
                continue
            row.invalidate()
            row.activate()
        # ⑤ 钉宽的那枚「网络头像库」输入框在 layoutWidget_8 的网格里，解锁后必须让它
        # 重排一次，否则 net 仍停在窄态的钉宽上。注意 layoutWidget_8 本身是 QWidget
        # （QLayoutWidget），invalidate/activate 在它**布局**上而不是它身上。
        net_holder = getattr(ui, self._ACTOR_PAGE_NET_PATH_GRID, None)
        grid8 = None if net_holder is None else net_holder.layout()
        if grid8 is not None:
            grid8.invalidate()
            grid8.activate()

    def _sync_actor_page_narrow_align(self, actor_scroll=None) -> None:
        """演员页窄态（最小化/还原）：一组控件左移到 A2 列、另一组右移到各自锚点列。

        用户需求（四轮共七条）：
          「补全完成后自动补全演员头像」「刮削结束后自动补全演员头像」「刮削结束后自动
          创建」向左移动到与「使用Graphis头像」上下严格对齐；
          「仅缺少信息的演员」「仅缺少头像的演员」「Jellyfin」向左移动到与「使用
          Graphis头像」上下严格对齐；
          「本地头像库」与「点击下载头像包」向左移动到与「使用Graphis头像」上下严格
          对齐；
          「选择文件」右移到与「选择目录」上下对齐，「演员信息数据库」显示框右侧
          拓展到右移后的「选择文件」按钮左侧；
          「网络头像库」显示输入框最右侧向左缩进到与「Gfridends本地仓库」「本地头像库」
          两行显示输入框右缘上下严格对齐。
        锚点（checkBox_actor_photo_ne_face、「选择目录」按钮、「Gfridends本地仓库」
        「本地头像库」两行显示输入框）自身保持不动；最大化时的页面、布局、控件、
        提示词逐像素不变。

        A2 锚点是 checkBox_actor_photo_ne_face（使用 Graphis 头像），实际 x 运行时
        mapTo 实测。旧锚点 checkBox_actor_info_photo 已在上面「②」里被左移到 A2 列，
        故此处 a2_x == anchor_x，需求②的右移分支 need 恒为 0、自然整段跳过——保留是
        为了窗口再窄一点（A2 继续左移）时仍能正确工作。

        左移组：目标都是所在行的**尾项**，行内间隔只能增不能减，故唯一途径是让同行
        前导项收窄让位。四行三种让位手法：
          ① hl101/hl96/hl103（两个「所有演员」行 + 服务类型行）：收窄前导项后，行尾
             余量归谁要按尾项能不能涨分流——尾项能涨（minWidth<maxWidth 且带 GrowFlag，
             实测 maxWidth=16777215/minWidth=0）时余量本来就全归它、不要插手；尾项被
             _sync_actor_info_columns 钉死（minWidth==maxWidth==252）时吸不走余量，
             必须插一个 Expanding 行尾间隔把余量全吸走，否则前导项 253→164 又被摊回
             222、目标只走到 434 而非 356。曾对三行一律插间隔，实测会让可涨的两行尾项
             被压回 sizeHint（80px、文字截断），故按可涨性分流。
          ② hl95（layoutWidget_8 的来源行，「本地头像库」+「点击下载头像包」）：结构
             与①不同——目标是 Fixed 宽单选（min==max==59）吸不走余量、必须插间隔，
             而行尾 hl97 是嵌套子布局（内含「点击下载头像包」一枚 QLabel），插间隔会
             与它争余量、把链接文字夹没。改用「stretch 挪给行尾 + 前导项钉窄」：前导
             项钉死后不再参与分配，行尾吃满剩余宽度（只会变宽），目标左缘正好落在前导
             项右侧。曾试过直接钉住行尾那枚 QLabel 的现宽，副作用是 hl95 最小宽变化、
             把 layoutWidget_8 的三等分挤偏（A2 由 356 漂到 362），故不取。

        右移组：实际 x 一律运行时 mapTo 实测（不写死）。need <= 0（目标已在锚点右侧）
        一律不动：需求只说「向右移动」，间隔只能右推、不能左拉。共同点是「间隔只会被
        Qt 挤瘦、不会撑大」：QSpacerItem 的 minimumSize 是 (0,0)，行内需求超出可用宽
        时它第一个被压缩，实测 hl101 插 13px 间隔、目标只走了 6px。故每行都必须先给
        目标右侧腾出等量宽度，再插固定间隔：
          ③ hl101（frame_4/layoutWidget_15，「仅缺少信息的演员」）：容器宽恒为设计值
             511（每遍被 _sync_actor_info_columns 重设），加宽它会溢出组框右缘，故
             不动容器——把目标自身收窄 spacing+need（文字左对齐，视觉零变化），
             再在它前面插 need 宽的固定间隔。
          ④ hl96（frame_2/layoutWidget_12，「仅缺少头像的演员」）：容器同样恒 511，
             用 ③ 的手法。
          ⑤ hl95：容器是 gridLayout 的一整列、宽随窗口变，没有可收窄的固定容器，故把
             stretch 挪给行尾 hl97 再插固定间隔（与左移组②互斥，两者不会同时生效）。
             「点击下载头像包」右缘停在原处、只有左缘右移，其文字实测为左对齐（.ui 里
             写的是 RTL 方向的 Qt::AlignLeading|Qt::AlignLeft，实测 AlignLeft 生效）。
          ⑥ hl103（groupBox_43/gridLayoutWidget_25 的服务类型行，「Jellyfin」）：行宽
             随窗口变（col1 = 503/473/1393），两个单选是「均分可用宽」关系而非固定
             设计宽，故钉宽值取当前实宽（locks 里写 None）。可用宽必须取**行自身**
             的矩形宽而不是容器宽——容器 gridLayoutWidget_25 还有一整列给别的行
             （容器 639 / 行 503），取容器宽会把「Emby」推出 136px。
          ⑦ hl155（gridLayoutWidget_14 的路径行，「选择文件」）：这一行尾部本就有一个
             Expanding 间隔，故「路径框 + 按钮 + 间隔」恒等于行宽——把路径框钉到
             「选择目录」按钮左缘减去行间距，按钮即落到那一列。两者设计宽同为 110px，
             「与选择目录左缘对齐」和「右缘对齐」在这里是同一件事。路径框收窄到
             _ACTOR_NARROW_PATH_MIN_W 以下时宁可不右移。

        收窄组（本方法第 ⑤ 步，宽态第 ⑥ 步的镜像）：「网络头像库：」显示输入框钉成与
        「Gfridends本地仓库：」同宽。它是 layoutWidget_8 网格里的直系项、右侧没有按钮，
        故独占整列富余宽度，比另两枚宽出一整枚按钮的宽（1030 实测 503 vs 387）——
        用户看到的「最右侧超出」正是这个成因。三枚左缘本就同列，故钉宽即同时对齐左右缘。
        只收窄不撑宽（want >= net.minimumWidth() 才动手）；登记 _actor_narrow_restores，
        宽态第一步清干净即真解锁。

        每行处理完都实测回读一次并按差值修正（容器让位法与 stretch 让位法都只在 Qt
        「有富余就分给可拉伸项」的模型下才精确，回读修正使其不依赖该模型的细节）。
        状态登记在 _actor_narrow_spacers / _actor_narrow_restores，每遍同步先清后建，
        幂等且窄↔宽往返自愈；宽态第一步清干净即 return，最大化态一个像素都不碰。
        判据用 _actor_page_stretch_extra() 的几何拉伸量而非 isMaximized()，理由见
        _actor_page_align docstring。休眠页跳过。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_64", None)
        content = None if box is None else box.parentWidget()
        if box is None or content is None or not box.isVisibleTo(self):
            return
        self._clear_actor_narrow_align()
        if self._actor_page_stretch_extra() > 0:
            return  # 宽态：几何全部由通用宽幅同步 + _sync_actor_info_columns 产出

        def left_x(w):
            return w.mapTo(content, w.rect().topLeft()).x()

        def set_fixed_width(w, width):
            """只改钉宽、不再登记原值——供回读修正用（登记由先前的 lock_width 负责）。"""
            w.setFixedWidth(width)
            w.updateGeometry()

        def lock_width(w, width):
            """把 w 钉到 width（width 为 None 表示钉到当前宽），并记下原 min/max 供还原。

            已是该宽则不重复登记：同一趟里对同一控件的二次调整走 set_fixed_width。
            """
            if w is None:
                return
            if width is None:
                width = w.width()
            if w.minimumWidth() == width and w.maximumWidth() == width:
                return
            self._actor_narrow_restores.append(("size", w, (w.minimumWidth(), w.maximumWidth())))
            set_fixed_width(w, width)

        def set_spacing(row, value):
            """只改行间距、不再登记原值——供回读修正用（登记由 lock_spacing 负责）。"""
            row.setSpacing(value)

        def lock_spacing(row, value):
            """把行间距改成 value，并记下原值供还原。"""
            if row.spacing() == value:
                return
            self._actor_narrow_restores.append(("spacing", row, row.spacing()))
            set_spacing(row, value)

        # 窄态新增①：上方两个「开始补全」收窄到与最下方「开始补全」同宽。
        # 设计态上方两枚是 261、最下方（pushButton_add_actor_pic_kodi）是 130；宽度实测
        # 取参照按钮当前实宽，不写死数值——宽态那枚被加宽过，窄态本方法跑到这里时
        # _sync_actor_page_wide_a2_align 已先行 _clear_actor_wide_align 把它复原成 130。
        # 两者都是各自 groupBox 的绝对定位件、无布局驱动，故除钉 min/max 外还须连几何
        # 一起登记（还原态只解锁 min/max 不会把宽度缩回去）。宽态本方法首步即 return，
        # 最大化时这三个按钮的尺寸一个像素都不碰。
        ref_btn = getattr(ui, "pushButton_add_actor_pic_kodi", None)
        target_btn_w = ref_btn.width() if ref_btn is not None else 0
        if target_btn_w > 0:
            for name in self._ACTOR_NARROW_ADD_BTN_TARGETS:
                w = getattr(ui, name, None)
                if w is None or w.parentWidget() is None or w.width() == target_btn_w:
                    continue
                g = w.geometry()
                if g.x() < 0 or g.x() + target_btn_w > w.parentWidget().width():
                    continue  # 收窄后越出父级：保持原状
                # 几何先记、钉宽后记：还原逆序写回时 size 先解锁、geometry 最后落定。
                self._actor_narrow_restores.append(("geometry", w, g))
                lock_width(w, target_btn_w)
                w.setGeometry(g.x(), g.y(), target_btn_w, g.height())

        # 窄态新增②：上一步收窄完成后，把「补全完成后自动补全演员头像」
        # 「刮削结束后自动补全演员头像」连同「刮削结束后自动创建」一起向左移动到与
        # 「使用Graphis头像」(A2 锚点) 严格上下对齐，锚点自身保持不动。
        # 三者都是绝对定位项、通用宽幅同步每遍都按 design_x + extra 重置它们，本方法的
        # 左移因此天然幂等（第二遍 dx=0）且宽↔窄往返自愈，不需要登记还原。
        # **必须排在下面 anchor_x 取样之前**：_ACTOR_NARROW_ANCHOR 正是
        # checkBox_actor_info_photo（「补全完成后自动补全演员头像」），它在本步被左移到
        # A2 列；后续各行按 anchor_x 右移时必须读到移动后的新 x，否则那批控件会停在
        # 旧锚点列、与锚点错开 102px（实测「仅缺少信息的演员」「Jellyfin」等随即失准）。
        a2 = getattr(ui, self._ACTOR_PAGE_A2_ANCHOR, None)
        a2_x = None if a2 is None else left_x(a2)
        if a2 is not None:
            for name in self._ACTOR_PAGE_A2_TARGETS + self._ACTOR_PAGE_MISS_TARGETS:
                w = getattr(ui, name, None)
                if w is None or w.parentWidget() is None:
                    continue
                try:
                    g = w.geometry()
                    dx = left_x(a2) - left_x(w)
                    nx = g.x() + dx
                except Exception:
                    continue
                # 只左移不右拉（需求只说「向左移动」）；越出父级则保持通用逻辑给出的位置
                if dx >= 0 or nx < 0 or nx + g.width() > w.parentWidget().width() or nx == g.x():
                    continue
                w.setGeometry(nx, g.y(), g.width(), g.height())

        anchor = getattr(ui, self._ACTOR_NARROW_ANCHOR, None)
        if anchor is None:
            return
        anchor_x = anchor.mapTo(content, anchor.rect().topLeft()).x()

        # 窄态新增③：「仅缺少信息的演员」「仅缺少头像的演员」也左移到 A2 列，与「使用Graphis
        # 头像」严格上下对齐（与上面②里的两个复选框同列，窄态就此与宽态一致）。
        # 手法：这枚单选是所在行的**尾项**，行内间隔只能增不能减，故左移的唯一途径是让同行
        # 前导项（两个「所有演员」）收窄让位——行内总需求随之变小，多出的富余全落在行尾空档
        # （这两行都没有 stretch 项），目标不会被顶回原处。
        # 只收窄绝不加宽（加宽前导项会把目标往右推）；收窄到下限仍够不到 A2 时整行放弃，
        # 宁可不动也不夹掉控件自己的文字。
        for row_name, target_name, lead_name, holder_name in self._ACTOR_NARROW_LEFT_PULL_ROWS:
            row = getattr(ui, row_name, None)
            target = getattr(ui, target_name, None)
            lead = getattr(ui, lead_name, None)
            holder = getattr(ui, holder_name, None)
            if row is None or target is None or lead is None or holder is None or a2_x is None:
                continue
            if row.parentWidget() is not holder or lead.parentWidget() is not holder:
                continue
            row.invalidate()
            row.activate()  # 先落定，才能量到这一行当前的真实 x
            # 前导项该有的宽 = 现宽 + 目标还差的位移。写成位移差而不是
            # 「a2_x − 容器左缘 − spacing」：前者不依赖 margins/spacing/首项是否带
            # 固定宽（服务类型行那两个单选是「均分可用宽」关系，实测 503/503），后者
            # 在这类行上会算偏。
            want = lead.width() + (a2_x - left_x(target))
            if not self._ACTOR_NARROW_MIN_LEAD_W <= want < lead.width():
                continue  # 够不到 A2 / 已在 A2 列或更左（不得反向加宽）
            # 行尾余量归谁，要按尾项能不能涨分两种情况（目标控件本身就是行尾项）：
            #  - 尾项能涨（minWidth<maxWidth 且带 GrowFlag，如「仅缺少头像的演员」
            #    「Jellyfin」实测 maxWidth=16777215/minWidth=0）：余量本来就全归它，
            #    收窄前导项后它自动涨满整行、目标左缘正好落在 lead 右侧，不要插手。
            #  - 尾项被钉死（minWidth==maxWidth，如「仅缺少信息的演员」被
            #    _sync_actor_info_columns 钉在 252px）：它吸不走余量，收窄前导项腾出的
            #    空档会留在行内把目标顶回原处，必须插一个 Expanding 行尾间隔把余量全
            #    吸走（前导项 253→164 又被摊回 222、目标只走到 434 而非 356）。
            # 曾对三行一律插间隔，实测会让可涨的两行尾项被压回 sizeHint（80px、文字
            # 截断，要等下一拍同步才涨回来），故按可涨性分流。间隔登记进
            # _actor_narrow_spacers，_clear_actor_narrow_align 每遍先清后建、不叠加。
            if not (
                target.minimumWidth() < target.maximumWidth()
                and bool(target.sizePolicy().horizontalPolicy().value & self._SIZE_POLICY_GROW_FLAG)
            ):
                tail_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                row.addItem(tail_spacer)
                self._actor_narrow_spacers.append((row, tail_spacer))
            lock_width(lead, want)
            row.invalidate()
            row.activate()
            d = a2_x - left_x(target)
            if d:
                # 回读修正：前导项是 Fixed 宽、目标紧随其后，差多少补多少即可
                set_fixed_width(lead, max(self._ACTOR_NARROW_MIN_LEAD_W, want - d))
                row.invalidate()
                row.activate()

        # 窄态新增③之补：来源行 hl95 —— 「本地头像库」连同紧跟其后的「点击下载头像包」
        # 也左移到 A2 列（宽态由 _sync_actor_page_wide_a2_align 的 _ACTOR_PAGE_A2_ROWS
        # 里 hl95 那一行负责；窄态此前只有右移逻辑，目标一直停在 A2 列右侧数十像素处）。
        # 手法见 _ACTOR_NARROW_SOURCE_PULL 注释：stretch 挪给行尾 hl97 + 前导项钉窄，
        # 不插 Expanding 间隔（会与嵌套子布局争余量、夹掉「点击下载头像包」文字）。
        src_row_name, src_target_name, src_head_name, src_tail_name = self._ACTOR_NARROW_SOURCE_PULL
        src_row = getattr(ui, src_row_name, None)
        src_target = getattr(ui, src_target_name, None)
        src_head = getattr(ui, src_head_name, None)
        src_tail = getattr(ui, src_tail_name, None)
        if None not in (src_row, src_target, src_head, src_tail) and a2_x is not None:
            src_row.invalidate()
            src_row.activate()
            head_idx = src_row.indexOf(src_head)
            tail_idx = src_row.indexOf(src_tail)
            d = a2_x - left_x(src_target)
            want = src_head.width() + d
            # 只左移不右拉；收窄到下限仍够不到 A2 时整行放弃，宁可不动也不夹掉控件文字
            if head_idx >= 0 and tail_idx >= 0 and d < 0 and self._ACTOR_NARROW_MIN_LEAD_W <= want < src_head.width():
                self._actor_narrow_restores.append(
                    ("stretch", src_row, [src_row.stretch(i) for i in range(src_row.count())])
                )
                for i in range(src_row.count()):
                    src_row.setStretch(i, 1 if i == tail_idx else 0)
                lock_width(src_head, want)
                src_row.invalidate()
                src_row.activate()
                d = a2_x - left_x(src_target)
                if d:
                    # 回读修正：前导项钉死、目标紧随其后，差多少补多少即可
                    set_fixed_width(src_head, max(self._ACTOR_NARROW_MIN_LEAD_W, want + d))
                    src_row.invalidate()
                    src_row.activate()

        # ①② 两个「补全范围：」行：容器不动，靠「目标收窄 + 同行间距撑开」右移。
        # 上面③已把两行的目标对到 A2 列，这里 need 恒为 0、自然整段跳过——右移分支保留
        # 是为了窗口再窄一点（A2 列继续左移）时仍能正确工作。
        for row_name, target_name, holder_name, locks in self._ACTOR_NARROW_SCOPE_ROWS:
            row = getattr(ui, row_name, None)
            target = getattr(ui, target_name, None)
            holder = getattr(ui, holder_name, None)
            if row is None or target is None or holder is None:
                continue
            if row.parentWidget() is not holder or target.parentWidget() is not holder:
                continue
            row.invalidate()
            row.activate()  # 先落定，才能量到本控件的当前真实 x
            need = anchor_x - left_x(target)
            if need <= 0:
                continue  # 已在锚点列或更右：需求只要求右移，不左拉
            for name, width in locks:
                lock_width(getattr(ui, name, None), width)
            idx = row.indexOf(target)
            count = row.count()
            if idx < 0 or count < 2:
                continue
            margins = row.contentsMargins()
            # 可用宽取「行自身被分到的矩形」而不是容器宽：前两行的行就是容器的唯一
            # 布局（行宽 == 容器宽 - margins），服务类型行的容器 gridLayoutWidget_25
            # 还有一整列给别的行（容器 639 / 行 503），取容器宽会把行首推出 136px。
            row_w = row.geometry().width()
            avail = (
                (row_w - margins.left() - margins.right())
                if row_w > 0
                else holder.width() - margins.left() - margins.right()
            )
            # 除目标外其余项的实宽（都已被上面钉成固定宽，不会在行内伸缩）
            others = sum(
                getattr(ui, name).width() for name, _ in locks if getattr(ui, name, None) not in (None, target)
            )
            base = row.spacing()
            # 目标让位量由「容器可用宽」反推，保证行内总需求恰好等于容器宽：
            # 有富余时 QHBoxLayout 会把富余摊到行首（实测凭空多出 6px 空档，行首控件
            # 整体右移），总需求一旦不等，行首的「所有演员」就会跟着漂。
            donor = avail - others - (base + need) * (count - 1)
            if donor < self._ACTOR_NARROW_MIN_DONOR_W:
                continue  # 让位会挤掉目标自己的文字：宁可不右移
            lock_width(target, donor)
            lock_spacing(row, base + need)
            row.invalidate()
            row.activate()
            d = anchor_x - left_x(target)
            # 回读修正：间距与让位量同步增减，行内总需求恒定，绝不会被挤瘦/摊到行首；
            # 修正后会让目标窄到夹住自己的文字则放弃（保持这一趟的近似值，下一遍再修）
            if d and donor - d >= self._ACTOR_NARROW_MIN_DONOR_W:
                set_fixed_width(target, donor - d)
                set_spacing(row, base + need + d)
                row.invalidate()
                row.activate()

        # ③ 来源行：stretch 让位法（详见 docstring）。
        # 收成闭包而非就地 early-return：③ 与 ④ 是两件独立的事，③ 不适用（need<=0，
        # 目标已在锚点列或更右）时必须继续跑 ④。此前这里是 `return`，一旦 ③ 不适用
        # 就把 ④ 整段跳过，「选择文件」再也对不到「选择目录」那一列。
        def _shift_source_row():
            row_name, target_name, head_name, tail_name = self._ACTOR_NARROW_SOURCE_ROW
            row = getattr(ui, row_name, None)
            target = getattr(ui, target_name, None)
            head = getattr(ui, head_name, None)
            tail = getattr(ui, tail_name, None)
            if row is None or target is None or head is None or tail is None:
                return
            row.invalidate()
            row.activate()
            if anchor_x - left_x(target) <= 0:
                return  # 已在锚点列或更右：需求只要求右移，不左拉
            head_idx = row.indexOf(head)
            tail_idx = row.indexOf(tail)
            if head_idx < 0 or tail_idx < 0:
                return

            self._actor_narrow_restores.append(("stretch", row, [row.stretch(i) for i in range(row.count())]))
            for i in range(row.count()):
                row.setStretch(i, 1 if i == tail_idx else 0)
            row.invalidate()
            row.activate()
            # 前导项已收窄让回了一部分，按实测差值补足（富余全在行尾 hl97，间隔不会被挤瘦）
            idx = row.indexOf(target)
            if idx < 0:
                return
            spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            row.insertItem(idx, spacer)
            self._actor_narrow_spacers.append((row, spacer))
            row.invalidate()
            row.activate()
            lead = anchor_x - left_x(target)
            for _ in range(3):
                d = anchor_x - left_x(target)
                if not d:
                    break
                lead = max(0, lead + d)
                spacer.changeSize(lead, 0)
                row.invalidate()
                row.activate()

        _shift_source_row()

        # ④ 「演员信息数据库：」行：路径框右缘撑到「选择文件」左缘，按钮即落到
        # 「选择目录」那一列。该行尾部本就有一个 Expanding 间隔，故行内总需求恒等于
        # 行宽时按钮右缘正好等于 col1 右缘——与「选择目录」按钮同宽（110px 设计），
        # 「左右缘对齐」在这里是同一件事。
        # 同样收成闭包：④ 有多处提前 return，就地 return 会把 ⑤ 整段跳过。
        def _shift_actor_db_path_row():
            row_name, path_name, btn_name, ref_name = self._ACTOR_NARROW_PATH_ROW
            row = getattr(ui, row_name, None)
            path = getattr(ui, path_name, None)
            btn = getattr(ui, btn_name, None)
            ref = getattr(ui, ref_name, None)
            if row is None or path is None or btn is None or ref is None:
                return
            row.invalidate()
            row.activate()
            if row.indexOf(btn) < 0 or row.indexOf(path) < 0 or ref.parentWidget() is None:
                return
            want = left_x(ref) - row.spacing() - left_x(path)
            if want < self._ACTOR_NARROW_PATH_MIN_W:
                return  # 会把路径框压到夹不住文字：宁可不右移
            lock_width(path, want)
            row.invalidate()
            row.activate()
            d = left_x(ref) - left_x(btn)
            if d:
                # 回读修正：路径框是 Fixed 宽、按钮紧随其后，差多少补多少即可
                set_fixed_width(path, want - d)
                row.invalidate()
                row.activate()

        _shift_actor_db_path_row()

        # ⑤ 最小化态：「网络头像库：」显示输入框右缘向左缩进到与「Gfriends 本地
        # 仓库：」「本地头像库：」两行显示输入框右缘上下严格对齐；那两枚（连同
        # 「选择目录」按钮）自身保持不动，最大化态一个像素都不碰。
        # 与宽态第 ⑥ 步（_sync_actor_page_wide_a2_align 末尾）同一手法、同一对控件：
        # 「网络头像库」行的输入框是 layoutWidget_8 网格里的直接项，右侧没有按钮，
        # 于是独占整列富余宽度，比另两枚宽出整整一枚按钮的宽（1030 实测 503 vs
        # 387，右缘 689 vs 573；1000 实测 473 vs 357）——这正是「最右侧超出」的成因。
        # 三枚左缘本就同列（A1 恒 186），故钉宽成参照枚的宽即同时满足左右缘对齐。
        # 只在窄态跑：lock_width 登记进 _actor_narrow_restores，宽态第一步
        # _clear_actor_narrow_align 即把 min/max 原样写回（真解锁，见该方法 docstring），
        # 而宽态自身的钉宽由 _sync_actor_page_wide_a2_align 第 ⑥ 步独立负责。
        net = getattr(ui, self._ACTOR_PAGE_NET_PATH_EDIT, None)
        ref_edit = getattr(ui, self._ACTOR_PAGE_PATH_REF_EDIT, None)
        net_holder = getattr(ui, "layoutWidget_8", None)
        if (
            net is not None
            and ref_edit is not None
            and net_holder is not None
            and net_holder.layout() is not None
            and net.parentWidget() is net_holder
            and ref_edit.parentWidget() is not None
        ):
            grid8 = net_holder.layout()
            grid8.invalidate()
            grid8.activate()  # 先落定，才能量到参照输入框的终态宽
            want = ref_edit.width()
            # 参照宽必须还容得下最小宽（MDCx.ui 给的是 300）才收；已经在该宽或更宽
            # （窗口更窄时另两枚的「选择目录」行反而更挤）一律不碰，避免反向撑大。
            if 0 < want < net.width() and want >= net.minimumWidth():
                lock_width(net, want)
                grid8.invalidate()
                grid8.activate()
                # 回读纠偏：布局重排后若有 1px 级取整误差，用实测差补回去
                drift = net.width() - want
                if drift:
                    lock_width(net, want - drift)
                    grid8.invalidate()
                    grid8.activate()

    # 刮削目录页文件清理提示的设计宽（MDCx.ui label_271 设计几何 140,490,381,16）。
    _GUAXIAOMULU_TIP_DESIGN_W = 381

    def _sync_guaxiaomulu_page_align(self, _scroll=None) -> None:
        """设置-刮削目录：把本页两处对齐入口整条重跑（钩子用，零参可调）。

        挂在刮削目录滚动区拉伸之后的钩子上
        （CustomScrollArea._post_wide_sync_hook），使「拉伸」与「对齐」在同一个
        事件里做完，中间态（提示被拉宽后居中右偏、「刮削时自动清理」先停在右缘）
        不会被绘制。休眠页直接返回，由切 tab 的 showEvent 补齐。

        顺序敏感：两处都要排在通用拉伸之后，且「刮削时自动清理」换列排在提示对齐
        之后——前者的对齐位置依赖网格终态列宽，而提示对齐内部会重跑一次
        sync_wide_children_width()（宽态），把它钉回右缘。
        """
        scroll = _scroll if _scroll is not None else getattr(self, "_guaxiaomulu_scroll", None)
        self._sync_guaxiaomulu_clean_tip_align(scroll)
        self._sync_guaxiaomulu_checkbox_align(scroll)

    def _sync_guaxiaomulu_clean_tip_align(self, scroll=None) -> None:
        """设置-刮削目录：最大化时文件清理提示左移到按钮下方居中，最小化不动。

        用户需求：最大化时「⚠️ 使用前请确认规则是否已启用！！！不启用不生效！！！」
        （label_271）向左移动到「点击检查待刮削目录并清理文件」按钮
        （pushButton_check_and_clean_files）下方；最小化时布局、页面、控件保持不变，
        只能左右移动、不能上下移动。

        根因：label_271 宽 381 ≥ 组框内宽一半，被 CustomScrollArea 通用宽幅同步判为
        _STRETCH，最大化时宽按「设计宽 + extra」铺开；文本 AlignCenter 居中，
        整体右偏到按钮右侧，而按钮本身是 _KEEP 原位不动。

        做法（只改「页面被拉宽」的态，还原态一个像素都不碰，双向幂等）：
          - 拉伸量 <= 0 直接 return：几何完全交给通用同步，本方法不复位、不摘
            registry（理由同 _sync_actor_page_align：复位会覆盖通用同步的缩回量，
            还原态凭空移位）。
          - 拉伸量 > 0：先显式重跑一次宽幅同步拿到终态按钮位置，再把提示按设计宽
            摆到按钮下方水平居中（x = 按钮.x + (按钮宽 - 设计宽)//2，y/h 不动）；
            越界（窄屏）则保持通用逻辑给出的位置。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_61", None)
        tip = getattr(ui, "label_271", None)
        btn = getattr(ui, "pushButton_check_and_clean_files", None)
        if box is None or tip is None or btn is None or not box.isVisibleTo(self):
            return
        if self._scroll_stretch_extra(scroll) <= 0:
            return
        if scroll is not None and scroll.isVisibleTo(self):
            scroll.sync_wide_children_width()  # 取终态按钮位置，勿量过期几何
        g = tip.geometry()
        nx = btn.x() + (btn.width() - self._GUAXIAOMULU_TIP_DESIGN_W) // 2
        if nx < 0 or nx + self._GUAXIAOMULU_TIP_DESIGN_W > tip.parentWidget().width():
            return
        if g.x() != nx or g.width() != self._GUAXIAOMULU_TIP_DESIGN_W:
            tip.setGeometry(nx, g.y(), self._GUAXIAOMULU_TIP_DESIGN_W, g.height())

    # ── 刮削目录页两处横向对齐（需求①软链接行让位 / ②③自动清理换列）──
    # 「文件扫描设置」软链接行：行布局 / 前导项 / 目标。
    # 目标是 horizontalLayout_19 里 gridLayout_19 第 (3,1) 格的子布局，
    # 两项都是 Minimum 策略、总需求恰好等于 col1 宽（窄 504 / 宽 1394）。
    _GUAXIAOMULU_SCAN_ROW = (
        "horizontalLayout_115",
        "checkBox_check_symlink",
        "checkBox_check_symlink_definition",
    )
    # 两态锚点（自身保持不动）：「记录刮削成功的文件列表」，horizontalLayout_133 第二项。
    _GUAXIAOMULU_SCAN_ANCHOR = "checkBox_record_success_file"
    # 「文件清理设置」组里六个「启用」（gridLayout_52 各行末列 Fixed 110）左缘一致，
    # 任取其一即代表该列竖线；组框内绝对定位的「刮削时自动清理」要对齐它。
    _GUAXIAOMULU_ENABLE_ANCHOR = "checkBox_clean_file_ext"
    # 「刮削时自动清理」是 groupBox_61 内的绝对定位项、不受任何布局管理，
    # 通用宽幅同步按 _DOCK_RIGHT 只 move(设计x + extra)、宽高不动
    # （设计几何 520,430,141,41），故宽态左移 / 窄态右移都由本方法在同一事件里
    # move 回去（宽度 141 保持不变——需求只说左右移动）。
    _GUAXIAOMULU_AUTO_CLEAN = "checkBox_auto_clean"
    # 前导项收窄让位的下限：低于此值会夹住「检查并清理失效的软链接」自己的文字
    # （实测其 sizeHint 宽 101），宁可不右移。窗口窄于约 960 时会触发该守卫。
    _GUAXIAOMULU_MIN_LEAD_W = 150

    # ── 命名页画质命名规则行（最大化时「使用路径中包含的画质信息」右移到「视频文件名」列）──
    # 行布局 horizontalLayout_112 在 layoutWidget_26 内，三项 Minimum/Minimum/Fixed、
    # 总需求恰好等于容器宽（窄 471：197 + 196 + 66 + 2×6），与刮削目录 horizontalLayout_115
    # 同构：既不能 setGeometry（会被下次 layout 激活覆盖），也不能只插间隔（总需求一旦
    # 小于容器宽，Qt 把富余摊给其余 Minimum 项、目标弹回原位）。
    # 做法是「容器加宽 + 固定间隔」：容器加宽 need、目标前插 need - spacing 宽的间隔，
    # 行内总需求恒等于容器宽（多出的一项引入一个新间距，spacer = need - spacing），
    # 三项自身宽度纹丝不动，「不获取分辨率」随行同步右移。锚点（自身不动）是
    # checkBox_filename_4k「视频文件名」（绝对定位，窄宽两态 abs 恒 450）。
    _NAMING_DEFN_ROW = (
        "horizontalLayout_112",
        "radioButton_videosize_video",
        "radioButton_videosize_path",
    )
    # 行内第三个单选（Fixed 策略）：它的宽度不参与 need 计算，但必须一并钉死——
    # 不同环境字体不同，它的 hint 也不同（实测 66 vs 99），行内总需求必须按三项实测
    # 宽逐项加总，靠"估算"一定会对不上、挤压会吃掉间隔或目标自身的宽度。
    _NAMING_DEFN_TAIL = "radioButton_videosize_none"
    _NAMING_DEFN_ANCHOR = "checkBox_filename_4k"
    _NAMING_DEFN_HOLDER = "layoutWidget_26"
    _NAMING_DEFN_FRAME = "frame_6"
    # ── 命名页窄态（最小化）三复选框左移到 path 列 ──
    # 目标：checkBox_filename_mosaic（马赛克组视频文件名）/ checkBox_cd_part_space
    # （分集分隔符空格）/ checkBox_filename_4k（画质组视频文件名），设计局部 x 均为
    # 420（abs 450）；锚点 radioButton_videosize_path（使用路径中包含的画质信息，
    # 自身不动，窄宽两态 abs 恒 403）。三目标均为组框内绝对定位项，直接 move(x)，
    # 只改 x 不碰 y/宽高；经公共祖先 content 换算，严格上下对齐。最大化时本分支
    # 不动手（先清干净即 return），宽态布局控件提示纹丝不动。
    _NAMING_NARROW_ANCHOR = "radioButton_videosize_path"
    _NAMING_NARROW_TARGETS = (
        "checkBox_filename_mosaic",
        "checkBox_cd_part_space",
        "checkBox_filename_4k",
    )
    # ── 命名页小数点复选框（窄宽两态都向「不获取分辨率」对齐）──
    # 目标 checkBox_cd_part_point（分集组绝对定位项，设计局部 x=560）；
    # 锚点 radioButton_videosize_none（画质行末项，自身不动——宽态它随行同步右移
    # 是 _sync_naming_definition_align 做的，本方法只读它的落定位置，故与
    # _NAMING_DEFN_TAIL 是同一控件）。
    # 两态实测（content-abs；1000×700 窄态 / 1920×1170 宽态，离屏）：
    #   窄态 point 590 vs none 605（差 -15）；宽态 point 590 vs none 653（差 -63，
    #   none 随 path 右移了 47）。用户需求：两态都把小数点移到与不获取分辨率
    #   严格上下对齐，不获取分辨率保持不动（取代此前的「小数点与空格保持 140
    #   设计间距、等距右随」——窄态下该约定本来也从未成立：空格被左移 47 而小数点
    #   纹丝不动，point-space 实测 187 ≠ 140，正是旧回归测试 [1000] 挂掉的原因）。
    # 越界判据用 sizeHint 宽（实测 59）而非控件全宽 110：窄态父组框被宽幅同步收窄
    # （1000 宽窗口下 groupBox_38 仅 649，目标局部 x=575，575+110=685 会误判越界），
    # 而实际内容（勾选框 + “.小数点”文字）仅 59 宽，575+59=634 完全可见。
    _NAMING_POINT_TARGET = "checkBox_cd_part_point"
    _NAMING_POINT_ANCHOR = "radioButton_videosize_none"

    # ── 水印页水印设置组（最大化时四行左标签冒号左移到「首个水印位置：」冒号）──
    # gridLayout_24 的 col0 在宽态被 QGridLayout 摊了 +272 富余（label_128 从 x0 被推到
    # x272，右缘 180→452），而锚点所在 gridLayout_30 的 col0 恒 130（右缘恒 180）。
    # 做法是把 col0 钉死 130 + stretch 全给 col1（演员页 gridLayout_14 的 col0 同款根因），
    # 四行标签自动归位，右侧复选框/滑杆/提示词随 col1 同步左移。锚点（自身不动）是
    # label_126「首个水印位置：」。
    _WATERMARK_GRID = "gridLayout_24"
    _WATERMARK_ANCHOR = "label_126"
    _WATERMARK_COL = 0
    _WATERMARK_COL_W = 130
    # col1 四个内容行的布局名（与 _WATERMARK_GRID 同文件 .ui 内连续定义）：各在尾部补
    # 一个水平 Expanding 间隔。col1 行内多为 Maximum 策略（capped 在 sizeHint）或
    # Fixed 宽（滑杆 400~500、LCD 70），无处吸收富余时多出的宽度会溢回 col0，
    # 光钉 col0/stretch 拉不动；尾部间隔让 col1 可以无界吸收，富余才全进 col1、
    # col0 恒 130。行内原有项宽度纹丝不动（间隔吸收全部富余）。
    _WATERMARK_CONTENT_ROWS = (
        "horizontalLayout_7",
        "horizontalLayout_15",
        "horizontalLayout_14",
        "horizontalLayout_5",
    )
    # ── 水印页宽态右移对齐（新增需求）──
    # thumb、固定一个位置 → 与右上严格上下对齐；fanart、固定不同位置 → 与右下
    # 严格上下对齐；右上、右下（不固定位置组的 radioButton_top_right /
    # radioButton_bottom_right）自身保持不动。最小化时不动。
    # 再新增：破解 → 右上，无码 → 右下，4K/8K → 左下（锚点为不固定位置组的
    # radioButton_top_right / radioButton_bottom_right / radioButton_bottom_left，
    # 均保持不动）；有码保持不动。注意同行顺序是 有码-破解-流出-无码-4K/8K，
    # 破解右移必然连带其后的流出同步右移（用户已确认：三项对齐、流出跟随）。
    # 又新增：有码 → 左上右上中间，流出 → 右上右下中间（左上/右上/右下保持不动；
    # 流出按字面要去左上右下中间，但会被钉在右上的破解挡住，用户改定为右上右下中间）。
    # 锚点可写单个控件名（取其左缘），或写两个控件名的元组（取两者左缘的中点）。
    _WATERMARK_SHIFT_ANCHOR_TOP = "radioButton_top_right"
    _WATERMARK_SHIFT_ANCHOR_BOTTOM = "radioButton_bottom_right"
    # 每行按从左到右顺序收敛：先推前一个目标（会连带后一个），再推后一个
    _WATERMARK_SHIFT_ROWS = (
        ("horizontalLayout_7", "checkBox_thumb_mark", "radioButton_top_right"),
        ("horizontalLayout_7", "checkBox_fanart_mark", "radioButton_bottom_right"),
        ("horizontalLayout_5", "radioButton_fixed_corner", "radioButton_top_right"),
        ("horizontalLayout_5", "radioButton_fixed_position", "radioButton_bottom_right"),
        ("horizontalLayout_14", "checkBox_censored", ("radioButton_top_left", "radioButton_top_right")),
        ("horizontalLayout_14", "checkBox_umr", "radioButton_top_right"),
        ("horizontalLayout_14", "checkBox_leak", ("radioButton_top_right", "radioButton_bottom_right")),
        ("horizontalLayout_14", "checkBox_uncensored", "radioButton_bottom_right"),
        ("horizontalLayout_14", "checkBox_hd", "radioButton_bottom_left"),
    )

    def _sync_guaxiaomulu_checkbox_align(self, scroll=None) -> None:
        """刮削目录页：软链接行让位 +「刮削时自动清理」按态换列（三条需求）。

        用户需求（三条锚点自身均保持不动）：
          ① 最大化/最小化时把「获取软链接指向的原文件的分辨率」左移到与「记录刮削成功
             的文件列表」严格上下对齐——两态都做，实测两态都是 -58px。
          ② 最大化时把「刮削时自动清理」左移到与「记录刮削成功的文件列表」严格上下对齐。
          ③ 最小化时把「刮削时自动清理」右移到与「启用」严格上下对齐。

        实测几何（abs = 相对滚动内容左缘；1030×753 窄态 / 1920×1170 宽态）：
          窄态 record 383 / definition 441 / check_symlink 186 / auto_clean 528 / 启用 579
          宽态 record 828 / definition 886 / check_symlink 186 / auto_clean 1418 / 启用 1469
        需求①两态右移量同为 58px：锚点列随窗口右移，而软链接行的前导项恒钉在
        col1 起点 186，两者之差与态无关。锚点 x 一律运行时 mapTo 实测、不写死。

        两条手法（根因不同，勿混用）：
          ① horizontalLayout_115 是 gridLayout_19 的子布局，两项都是 Minimum 策略
             且总需求恰好等于 col1 宽，故既不能用 setGeometry（会被下次 layout 激活
             覆盖）也不能只插间隔（行内总需求一旦小于容器宽，Qt 会把富余摊给其余
             Minimum 项、目标又弹回原位）。做法是「前导项收窄让位」：把「检查并清理
             失效的软链接」钉到 need_w = 锚点x - 前导项x - 行间距 - 中间项宽之和，
             目标作为行内唯一的可拉伸项正好吃光剩余宽度，左缘即落在锚点上。
             钉宽每遍先**真解锁**（setMinimumWidth(0) + setMaximumWidth(QWIDGETSIZE_MAX)）
             再量——这正是 _actor_info_width_locks 用 setFixedWidth(saved) 永不真解锁
             的坑：拿上一遍的钉宽去算，误差会逐遍累积。
             need_w < 150 时保持解锁、不右移（宁可不满足也不夹住前导项自己的文字）。
          ② 「刮削时自动清理」是 groupBox_61 内的绝对定位项，直接 move 即可；但通用
             宽幅同步每遍会按 _DOCK_RIGHT 把它钉回「设计x + extra」（窄 498 / 宽
             1388），所以本方法必须排在 sync_wide_children_width() 之后——滚动区的
             _post_wide_sync_hook 与 _sync_page_layouts 尾部两处调用都满足这一点，
             与 _sync_guaxiaomulu_clean_tip_align 同款排布。只改 x，y 与宽不动。

        判态用几何拉伸量 _scroll_stretch_extra()（> 0 为宽态）而非 isMaximized()：
        窗口管理器最大化时先发尺寸、后发状态标志，那一拍 isMaximized() 还是 False，
        用户会看到「先在右边、再跳到左边」（同 _sync_actor_page_align 的理由）。
        幂等：每遍先解锁再按当前几何重算，双向幂等、窄↔宽往返自愈。休眠页零成本。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box32 = getattr(ui, "groupBox_32", None)
        box61 = getattr(ui, "groupBox_61", None)
        anchor = getattr(ui, self._GUAXIAOMULU_SCAN_ANCHOR, None)
        if box32 is None or box61 is None or anchor is None or not box32.isVisibleTo(self):
            return
        content = box32.parentWidget()
        if content is None or box61.parentWidget() is not content:
            return
        if scroll is None:
            scroll = getattr(self, "_guaxiaomulu_scroll", None)

        def left_x(w):
            return w.mapTo(content, w.rect().topLeft()).x()

        # ① 软链接行：前导项收窄让位，目标左缘落到锚点列（两态都做）。
        row_name, lead_name, target_name = self._GUAXIAOMULU_SCAN_ROW
        row = getattr(ui, row_name, None)
        lead = getattr(ui, lead_name, None)
        target = getattr(ui, target_name, None)
        if row is not None and lead is not None and target is not None:
            if lead.parentWidget() is target.parentWidget():
                lead.setMinimumWidth(0)
                lead.setMaximumWidth(QWIDGETSIZE_MAX)
                lead.updateGeometry()
                row.invalidate()
                row.activate()  # 先落定，才能量到本行的当前真实 x 与宽
                lidx = row.indexOf(lead)
                tidx = row.indexOf(target)
                if lidx >= 0 and tidx > lidx:
                    anchor_x = left_x(anchor)
                    between = 0
                    for i in range(lidx + 1, tidx):
                        mid = row.itemAt(i).widget()
                        if mid is not None:
                            between += mid.width()
                    need_w = anchor_x - left_x(lead) - row.spacing() * (tidx - lidx) - between
                    if need_w >= self._GUAXIAOMULU_MIN_LEAD_W:
                        lead.setFixedWidth(need_w)
                        row.invalidate()
                        row.activate()
                        # 回读修正：上面已按构造式推出「目标x == 锚点x」，这里不依赖
                        # Qt 分配细节再校一遍，残差就再让多少（仍以不夹住文字为界）。
                        d = anchor_x - left_x(target)
                        if d:
                            fixed = max(need_w - d, self._GUAXIAOMULU_MIN_LEAD_W)
                            lead.setFixedWidth(fixed)
                            row.invalidate()
                            row.activate()

        # ②③ 「刮削时自动清理」：宽态对到「记录刮削成功的文件列表」列，窄态对到「启用」列。
        clean = getattr(ui, self._GUAXIAOMULU_AUTO_CLEAN, None)
        enable = getattr(ui, self._GUAXIAOMULU_ENABLE_ANCHOR, None)
        if clean is not None and enable is not None and clean.parentWidget() is box61:
            src = anchor if self._scroll_stretch_extra(scroll) > 0 else enable
            # 跨分支 mapTo（record 在 groupBox_32、目标在 groupBox_61）是未定义行为，
            # 必须经公共祖先 content 中转再换算回 groupBox_61 的局部坐标。
            box_x = box61.mapTo(content, QPoint(0, 0)).x()
            nx = src.mapTo(content, QPoint(0, 0)).x() - box_x
            # 不越过滚动内容右缘（否则内容最小宽被抬高、冒出一条水平滚动条）
            limit = content.width() - box_x
            if nx != clean.x() and 0 <= nx and nx + clean.width() <= limit:
                clean.move(nx, clean.y())

    def _sync_reuse_meta_gap_align(self) -> None:
        """刮削模式页：复用行「覆盖……元数据文件」与 STRM 行「覆盖……文本」同 x。

        两行同处 gridLayout_2 第 1 列（左缘天然一致），差值只来自“首框宽度差 +
        行内间距差”，由行内 gap spacer（第 1 项）补齐。sizeHint 在 show 前后会变
        （初始化公式一次算不准，窄态实测差 6px），故按实测差值闭环收敛：量两框经
        content 中转的 x 差，残差就加多少，相等即 no-op。gap 钉 Fixed、行尾 spacer
        保持 Expanding，宽态富余只进尾部；gap 变宽不改变行总宽（尾部吸收），不触发
        新的 resize，不会自激。休眠页跳过（切页同拍收敛，无漂移可见）。
        """
        ui = self.Ui
        content = getattr(ui, "scrollAreaWidgetContents_guaxiaomoshi", None)
        row = getattr(ui, "horizontalLayout_reuse_meta", None)
        if content is None or row is None or not content.isVisibleTo(self):
            return
        strm_box = getattr(ui, "checkBox_separate_overwrite_strm", None)
        meta_box = getattr(ui, "checkBox_separate_overwrite_meta", None)
        if strm_box is None or meta_box is None:
            return
        gap_item = row.itemAt(1)
        gap = gap_item.spacerItem() if gap_item is not None else None
        tail_item = row.itemAt(3)
        tail = tail_item.spacerItem() if tail_item is not None else None
        if gap is None or tail is None:
            return
        if gap.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Fixed:
            gap.changeSize(max(gap.sizeHint().width(), 0), 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        if tail.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Expanding:
            tail.changeSize(
                max(tail.sizeHint().width(), 0), 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
            )
        for _ in range(3):
            xs = strm_box.mapTo(content, QPoint(0, 0)).x()
            xm = meta_box.mapTo(content, QPoint(0, 0)).x()
            if xs == xm:
                break
            gap.changeSize(
                max(gap.sizeHint().width() + (xs - xm), 0), 20, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum
            )
            row.invalidate()
            row.activate()

    def _sync_javdb_tip_pos(self) -> None:
        """刮削模式页：Javdb 延时提示（label_26）上移一行并钉死。

        label_26 已移出 gridLayout_15、独立为 groupBox_53 子件（.ui 设计几何
        (146,160,513,28)：相对旧 grid 内位置上移一行 = fontMetrics 高 14）；
        grid 内 0-2 行不受影响（容器高已同步收缩 181→129）。
        运行时钉死两点：x 经 content 映射与 label_separate_mode 文本左缘精确
        相等（用户要求严格对齐）；y = 容器.y + row2底 + spacing + share − h，
        其中 share = (H − 各行高 − 2*spacing) / 3 全运行时实测（富余摊槽位的
        真实值），h = 提示自身 fontMetrics 高。|dx|、|dy| ≤ 1 即 no-op，
        休眠页/缺件早退，切页同拍收敛。
        """
        ui = self.Ui
        content = getattr(ui, "scrollAreaWidgetContents_guaxiaomoshi", None)
        tip = getattr(ui, "label_26", None)
        sep = getattr(ui, "label_separate_mode", None)
        grid_widget = getattr(ui, "gridLayoutWidget_15", None)
        grid = getattr(ui, "gridLayout_15", None)
        if (
            content is None
            or tip is None
            or sep is None
            or grid_widget is None
            or grid is None
            or not content.isVisibleTo(self)
        ):
            return
        # x：与分离模式描述文本左缘精确相等（经 content 中转，同 _sync_reuse_meta_gap_align）。
        anchor_x = sep.mapTo(content, QPoint(0, 0)).x()
        if abs(anchor_x - tip.mapTo(content, QPoint(0, 0)).x()) > 1:
            tip.move(tip.x() + (anchor_x - tip.mapTo(content, QPoint(0, 0)).x()), tip.y())
        # y：row2 底 + spacing + 所属槽位富余 − 一行字高（全运行时实测）。
        spacing = grid.verticalSpacing()
        if spacing < 0:
            spacing = grid.spacing()
        rows_h = 0
        row2_bottom = None
        for _r in range(3):
            _item = grid.itemAtPosition(_r, 1)
            if _item is None:
                return
            _g = _item.geometry()  # 第 1 列是 HBox 不是 widget，必须用 cell 几何（widget() 取不到）
            rows_h += _g.height()
            if _r == 2:
                row2_bottom = _g.y() + _g.height()
        if row2_bottom is None:
            return
        share = (grid_widget.height() - rows_h - 2 * spacing) / 3
        expect_y = grid_widget.y() + row2_bottom + spacing + share - tip.fontMetrics().height()
        if abs(expect_y - tip.y()) > 1:
            tip.move(tip.x(), round(expect_y))

    def _clear_naming_defn_align(self) -> None:
        """清掉命名页画质行加宽/间隔（每遍同步先清后建，故幂等、往返自愈）。

        holder（layoutWidget_26）是 frame_6 内绝对定位的容器：只恢复 min/max
        不会收回宽度（widget 保持当前宽），必须按记录值把宽度写回去，否则加宽量
        逐遍累积（实测 holder 471→554、窄态也要不回来）。
         seeing narrow restores here too: wide anchor is filename_4k design pos,
        narrow moves it left — must restore before wide measures, and baseline
        (method-disabled) must be true design.
        """
        self._clear_naming_narrow_align()
        for row, spacer in self._naming_defn_spacers:
            if row is not None and spacer is not None:
                row.removeItem(spacer)
        self._naming_defn_spacers = []
        for kind, obj, saved in reversed(self._naming_defn_restores):
            if obj is None:
                continue
            if kind == "width":
                # 先真解锁：holder 加宽用的是 setFixedWidth（min == max == 加宽值），
                # 不先恢复 min/max 的话 setGeometry 会被钳在加宽值、窄态也要不回来
                # （实测 holder 471→559 越垒越高）。
                obj.setMinimumWidth(0)
                obj.setMaximumWidth(QWIDGETSIZE_MAX)
                obj.setGeometry(obj.x(), obj.y(), saved, obj.height())
                obj.updateGeometry()
            elif kind == "unlock":
                # 行内 Minimum 项的钉宽：行布局每遍从零重排，真解锁即可。
                obj.setMinimumWidth(0)
                obj.setMaximumWidth(QWIDGETSIZE_MAX)
                obj.updateGeometry()
        self._naming_defn_restores = []
        ui = getattr(self, "Ui", None)
        row = getattr(ui, self._NAMING_DEFN_ROW[0], None) if ui is not None else None
        if row is not None and row.parentWidget() is not None:
            row.invalidate()
            row.activate()

    def _clear_naming_narrow_align(self) -> None:
        """清掉命名页窄态三复选框左移（每遍先清后建，幂等往返自愈）。"""
        for obj, saved_x in reversed(self._naming_narrow_restores):
            if obj is None:
                continue
            try:
                if obj.x() != saved_x:
                    obj.move(saved_x, obj.y())
            except RuntimeError:
                continue
        self._naming_narrow_restores = []

    def _sync_naming_definition_align(self, scroll=None) -> None:
        """命名页画质命名规则：最大化时 path 右移到视频文件名列 + 小数点对齐 none 列。

        用户需求：最大化时把「使用路径中包含的画质信息」向右移动到与下方「视频文件名」
        严格上下对齐的位置，「不获取分辨率」同步向右移动，「视频文件名」位置保持不变；
        同时把「.小数点」向右移动到与「不获取分辨率」严格上下对齐（读落定后的 none
        位置，故排在间隔收敛之后）；最小化时画质行保持不变（窄态只做三复选框左移 +
        小数点对齐，见 _sync_naming_narrow_align）。

        实测几何（abs = 相对滚动内容左缘；1030×753 窄态 / 1920×1170 宽态）：
          video 200 / path 403 / none 605 / filename_4k 450（两态完全一致，通用宽幅同步
          不碰 layoutWidget_26，frame_6 只被拉宽到 1510、内部 471 宽的行原地不动）。
        故 need 恒为 47（= 450 - 403），仍运行时 mapTo 实测、不写死。

        手法「容器加宽 + 固定间隔」（见类常量注释）：holder 加宽 need，目标前插
        need - spacing 宽的 Fixed 间隔。行内总需求恒等于容器宽，间隔不会被挤瘦，
        三项自身宽度纹丝不动。插完实测回读、按差值 changeSize 三轮收敛。
        必须排在 _sync_definition_group_spacing 之后：后者每遍按 frame_layout 的
        sizeHint 高度重钉 frame 高（只取高度，本间隔高为 0 不影响），且它用
        setGeometry(..., frame_lw.width(), ...) 保留容器宽度——排前面会把本方法刚加的
        宽度当成终态保留，逻辑仍自洽；但它 activate() 的是旧几何，排后面量到的 need
        才是终态。窄态第一步清干净即 return，最小化逐像素不变。休眠页跳过。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_65", None)
        if box is None or not box.isVisibleTo(self):
            return
        self._clear_naming_defn_align()
        self._clear_naming_narrow_align()
        if scroll is None:
            scroll = getattr(ui, "scrollArea_7", None)
        if self._scroll_stretch_extra(scroll) <= 0:
            self._sync_naming_narrow_align(scroll)
            return  # 窄态：只做三复选框左移，宽态分支不动
        content = box.parentWidget()
        anchor = getattr(ui, self._NAMING_DEFN_ANCHOR, None)
        holder = getattr(ui, self._NAMING_DEFN_HOLDER, None)
        frame = getattr(ui, self._NAMING_DEFN_FRAME, None)
        row_name, _lead_name, target_name = self._NAMING_DEFN_ROW
        row = getattr(ui, row_name, None)
        target = getattr(ui, target_name, None)
        lead = getattr(ui, self._NAMING_DEFN_ROW[1], None)
        tailfix = getattr(ui, self._NAMING_DEFN_TAIL, None)
        if content is None or anchor is None or holder is None or frame is None:
            return
        if row is None or target is None or lead is None or tailfix is None:
            return
        if target.parentWidget() is not holder or row.parentWidget() is not holder:
            return

        def left_x(w):
            return w.mapTo(content, w.rect().topLeft()).x()

        row.invalidate()
        row.activate()
        anchor_x = left_x(anchor)
        need = anchor_x - left_x(target)
        if need <= 0:
            return
        spacing = row.spacing()
        spacer_w = need - spacing
        if spacer_w <= 0:
            return
        # 三个单选全钉死在当前宽（见类常量注释），再逐项加总定容器宽：
        # 行内总需求恒等于容器宽，间隔既不会被挤瘦、富余也不会摊给行首。
        # 恢复时真解锁（行布局每遍从零重排，不存在"拆掉上游锁"问题）。
        for w in (lead, target, tailfix):
            self._naming_defn_restores.append(("unlock", w, None))
            w.setFixedWidth(w.width())
        new_w = lead.width() + spacer_w + target.width() + tailfix.width() + spacing * row.count()
        # 不越过所在 frame 右缘（否则内容最小宽被抬高、冒出水平滚动条）
        if holder.x() + new_w > frame.width():
            return
        self._naming_defn_restores.append(("width", holder, holder.width()))
        holder.setFixedWidth(new_w)
        holder.updateGeometry()
        idx = row.indexOf(target)
        if idx < 0:
            return
        spacer = QSpacerItem(spacer_w, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        row.insertItem(idx, spacer)
        self._naming_defn_spacers.append((row, spacer))
        row.invalidate()
        row.activate()
        # 回读修正：spacer 与 holder 联动增减（行内总需求恒等于容器宽，间隔既不会被
        # 挤瘦、富余也不会摊给行首的 Minimum 项），故一步即收敛；holder 加宽受 frame
        # 右缘钳制，超界则放弃修正（保持近似值，下一遍再修）。
        for _ in range(3):
            d = anchor_x - left_x(target)
            if not d:
                break
            if holder.x() + holder.width() + d > frame.width():
                break
            spacer.changeSize(max(0, spacer.sizeHint().width() + d), 0)
            holder.setFixedWidth(holder.width() + d)
            row.invalidate()
            row.activate()
        # 小数点：宽态向「不获取分辨率」对齐。必须排在间隔收敛之后——none 的位置
        # 由上面的收敛循环刚定下，此时量到的是终态；helper 内自己再换算一次，
        # 不依赖本方法的 anchor_x。
        self._move_naming_point_to_none(content)

    def _move_naming_point_to_none(self, content) -> None:
        """命名页：小数点复选框左缘对齐「不获取分辨率」左缘（窄宽两态都做）。

        用户需求：最小化时把「.小数点」向左移动、最大化时向右移动到与「不获取
        分辨率」严格上下对齐的位置，「不获取分辨率」位置保持不变（方向由运行时
        几何决定：量到在哪边就往哪边移，不写死左右）。
        目标是分集组内绝对定位项，直接 move(x)，只改 x 不碰 y/宽高；跨组 mapTo
        经公共祖先 content 中转；越界则放弃。复位记录复用 _naming_narrow_restores
        （调用方每遍先清后建，故幂等、往返自愈）。小数点在
        CustomScrollArea._MANUAL_WIDGET_NAMES 里，通用宽幅同步不会登记/搬动它。
        """
        ui = getattr(self, "Ui", None)
        if ui is None or content is None:
            return
        target = getattr(ui, self._NAMING_POINT_TARGET, None)
        anchor = getattr(ui, self._NAMING_POINT_ANCHOR, None)
        if target is None or anchor is None:
            return
        parent = target.parentWidget()
        if parent is None or parent.parentWidget() is not content:
            # 目标须是内容直属组框的子项，否则换算无意义
            return
        try:
            anchor_x = anchor.mapTo(content, anchor.rect().topLeft()).x()
            target_x = target.mapTo(content, target.rect().topLeft()).x()
        except Exception:
            return
        d = anchor_x - target_x
        if not d:
            return
        nx = target.x() + d
        if nx < 0:
            return
        need = max(target.sizeHint().width(), target.minimumSizeHint().width())
        if nx + need > parent.width():
            return
        if target.x() != nx:
            self._naming_narrow_restores.append((target, target.x()))
            target.move(nx, target.y())

    def _sync_naming_narrow_align(self, scroll=None) -> None:
        """命名页窄态：三复选框左移到 path 列 + 小数点对齐 none 列，锚点均不动。

        用户需求：最小化时把视频文件名（上下两个：checkBox_filename_mosaic /
        checkBox_filename_4k）与空格（checkBox_cd_part_space）向左移动到与
        「使用路径中包含的画质信息」（radioButton_videosize_path）上下严格对齐，
        把「.小数点」（checkBox_cd_part_point）移动到与「不获取分辨率」
        （radioButton_videosize_none）上下严格对齐，两个锚点位置均保持不变；
        最大化时页面布局控件提示等均保持不变（本分支窄态才动手，宽态调用方已
        提前 return——宽态的小数点由 _sync_naming_definition_align 负责）。

        三目标均为组框内绝对定位项（设计局部 x 均为 420），直接 move(x)，只改 x
        不碰 y/宽高；跨组 mapTo 必须经公共祖先 content 中转。越界则放弃该项。
        休眠页跳过（切页 showEvent 会补齐）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_65", None)
        if box is None or not box.isVisibleTo(self):
            return
        content = box.parentWidget()
        anchor = getattr(ui, self._NAMING_NARROW_ANCHOR, None)
        if content is None or anchor is None:
            return
        try:
            anchor_x = anchor.mapTo(content, anchor.rect().topLeft()).x()
        except Exception:
            return
        for name in self._NAMING_NARROW_TARGETS:
            target = getattr(ui, name, None)
            if target is None:
                continue
            parent = target.parentWidget()
            if parent is None or parent.parentWidget() is not content:
                # 目标须是内容直属组框的子项，否则换算无意义
                if parent is None:
                    continue
            try:
                target_x = target.mapTo(content, target.rect().topLeft()).x()
            except Exception:
                continue
            d = anchor_x - target_x
            if not d:
                continue
            nx = target.x() + d
            if nx < 0 or nx + target.width() > parent.width():
                continue
            if target.x() != nx:
                self._naming_narrow_restores.append((target, target.x()))
                target.move(nx, target.y())
        # 小数点：窄态同样向「不获取分辨率」对齐（锚点不动）
        self._move_naming_point_to_none(content)

    def _clear_watermark_colon_align(self) -> None:
        """清掉水印页网格列钉死 + 四行尾部间隔 + 宽态右移间隔（每遍先清后建，幂等）。"""
        ui = getattr(self, "Ui", None)
        for row_name, spacer in self._watermark_shift_spacers:
            row = getattr(ui, row_name, None) if ui is not None else None
            if row is not None and spacer is not None:
                row.removeItem(spacer)
        self._watermark_shift_spacers = []
        for row_name, spacer in self._watermark_tail_spacers:
            row = getattr(ui, row_name, None) if ui is not None else None
            if row is not None and spacer is not None:
                row.removeItem(spacer)
        self._watermark_tail_spacers = []
        for kind, obj, saved in reversed(self._watermark_col_restores):
            if obj is None:
                continue
            if kind == "colmin":
                obj.setColumnMinimumWidth(saved[0], saved[1])
            elif kind == "colstretch":
                obj.setColumnStretch(saved, 0)
        self._watermark_col_restores = []
        ui = getattr(self, "Ui", None)
        grid = getattr(ui, self._WATERMARK_GRID, None) if ui is not None else None
        if grid is not None:
            grid.invalidate()
            grid.activate()

    def _sync_watermark_colon_align(self, scroll=None) -> None:
        """水印页水印设置：最大化时四行左标签冒号左移到「首个水印位置：」冒号 + 右移对齐。

        用户需求：最大化时把「添加水印的图片」「水印大小」「水印类型」「水印位置」向左
        移动到与「首个水印位置：」严格上下对齐的位置（注意是对齐冒号），「首个水印位置：」
        的位置保持不变，右侧的复选框、提示词、组件等同步向左移动；最小化时界面、控件、
        组件等等均保持不变。

        新增需求（宽态，锚点均保持不动）：thumb、固定一个位置向右移动到与右上严格
        上下对齐；fanart、固定不同位置向右移动到与右下严格上下对齐。右上/右下指
        不固定位置组的 radioButton_top_right / radioButton_bottom_right。
        再新增（宽态）：破解 → 右上，无码 → 右下，4K/8K → 左下（左下指同组的
        radioButton_bottom_left）。有码保持不动；流出被破解连带同步右移（同行
        顺序有码-破解-流出-…，已与用户确认）。
        又新增（宽态）：有码 → 左上与右上中间，流出 → 右上与右下中间（左上指
        同组的 radioButton_top_left）。此时有码/流出各自拥有独立间隔，破解/
        无码/4K8K 的对齐保持不变。

        实测几何（右缘 abs = 相对滚动内容左缘；1030×753 窄态 / 1920×1170 宽态）：
          窄态四标签右缘全 180 == 锚点 180（天然对齐，col0 恒 130）；
          宽态四标签右缘全 452 vs 锚点 180（col0 被 QGridLayout 摊了 +272 富余）。
        做法见类常量注释：col0 钉死 130 + stretch 全给 col1。窄态第一步清干净即
        return，最小化逐像素不变。休眠页跳过。判态用几何拉伸量而非 isMaximized()。

        右移手法：col1 两行（horizontalLayout_7/5）目标前插 Fixed 间隔。行尾已有
        Expanding 间隔吸收富余，故固定间隔只会把目标向右推、行内其余项宽度不动；
        每行按顺序收敛（先推前一个目标、再推后一个），插完回读三轮收敛。只允许
        右移（need <= 0 则该项保持 0 宽间隔），越界则放弃。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_31", None)
        if box is None or not box.isVisibleTo(self):
            return
        self._clear_watermark_colon_align()
        if scroll is None:
            scroll = getattr(ui, "scrollArea_4", None)
        if self._scroll_stretch_extra(scroll) <= 0:
            return  # 窄态：一个像素不碰
        grid = getattr(ui, self._WATERMARK_GRID, None)
        if grid is None:
            return
        col = self._WATERMARK_COL
        self._watermark_col_restores.append(("colmin", grid, (col, grid.columnMinimumWidth(col))))
        self._watermark_col_restores.append(("colstretch", grid, col))
        self._watermark_col_restores.append(("colstretch", grid, col + 1))
        grid.setColumnMinimumWidth(col, self._WATERMARK_COL_W)
        grid.setColumnStretch(col, 0)
        grid.setColumnStretch(col + 1, 1)
        # col1 四行尾部补 Expanding 间隔（类常量注释）：无处吸收富余时多出的宽度会
        # 溢回 col0，尾部间隔让 col1 无界吸收，行内原有项宽度纹丝不动。
        for row_name in self._WATERMARK_CONTENT_ROWS:
            row = getattr(ui, row_name, None)
            if row is None:
                continue
            tail = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            row.addItem(tail)
            self._watermark_tail_spacers.append((row_name, tail))
        grid.invalidate()
        grid.activate()
        # ── 宽态右移对齐：thumb/固定一个位置 → 右上，fanart/固定不同位置 → 右下 ──
        content = box.parentWidget()
        if content is None:
            return
        for row_name, target_name, anchor_name in self._WATERMARK_SHIFT_ROWS:
            row = getattr(ui, row_name, None)
            target = getattr(ui, target_name, None)
            if isinstance(anchor_name, tuple):
                anchors = [getattr(ui, n, None) for n in anchor_name]
                anchor = anchors[0]
                if row is None or target is None or any(a is None for a in anchors):
                    continue
            else:
                anchor = getattr(ui, anchor_name, None)
                anchors = None
                if row is None or target is None or anchor is None:
                    continue
            if target.parentWidget() is None:
                continue
            idx = row.indexOf(target)
            if idx < 0:
                continue
            spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            row.insertItem(idx, spacer)
            self._watermark_shift_spacers.append((row_name, spacer))
            row.invalidate()
            row.activate()
            for _ in range(3):
                try:
                    if anchors is not None:
                        xs = [a.mapTo(content, a.rect().topLeft()).x() for a in anchors]
                        anchor_x = (xs[0] + xs[1]) // 2
                    else:
                        anchor_x = anchor.mapTo(content, anchor.rect().topLeft()).x()
                    target_x = target.mapTo(content, target.rect().topLeft()).x()
                except Exception:
                    break
                d = anchor_x - target_x
                if not d:
                    break
                new_w = spacer.sizeHint().width() + d
                if new_w < 0:
                    break  # 只允许右移：锚点在左则保持 0 宽间隔
                try:
                    target_parent = target.parentWidget()
                    limit = content.width() - target_parent.mapTo(content, target_parent.rect().topLeft()).x()
                except Exception:
                    break
                if target.width() + new_w > limit and d > 0:
                    break
                spacer.changeSize(new_w, 0)
                row.invalidate()
                row.activate()

    # 字幕页「添加外挂字幕」组设计几何（MDCx.ui groupBox_45: x30 y310 w701 h425）。
    _ZIMU_BOX_DESIGN_Y = 310
    _ZIMU_BOX_DESIGN_H = 425
    # 字幕页纵向铺排的目标底垫：绿色说明底边与组框底边之间只留 12px，
    # 其余多余底垫删除（绿色说明上提、组框底边同步上收）。
    _ZIMU_TEAL_BOTTOM_PAD = 12

    def _zimu_wide_rows(self, filler: int, teal_h: int):
        """字幕页宽态纵向铺排：各行 y 与组框高（公式化，双向幂等）。

        _sync_zimu_fill_blank（定组框高）与 _sync_zimu_row_align（定各行 y）
        共用同一公式，任一先跑结果一致，不存在“对齐完又被覆盖”。
        铺排：上方网格 4 行各增 unit（unit = filler//8），长按钮下移 5*unit，
        复选框行下移 5*unit + unit//3，绿色说明先按 5*unit + 2*(unit//3)
        铺排、再整体上移 X（删掉下方多余底垫；X 取到底垫只剩 12px 所需量，
        并钳位不越过复选框行），组框高按绿色说明底部贴合
        （box_h = teal_y + teal_h + 12，恒 <= 设计高 + filler）。
        filler <= 0 时 unit/X 自动归零，返回值即设计几何。
        """
        unit = max(0, filler) // 8
        gap = unit // 3
        btn_y = self._ZIMU_BUTTON_DESIGN_Y + 5 * unit
        checks_y = self._ZIMU_CHECKS_DESIGN_Y + 5 * unit + gap
        spread_teal_y = self._ZIMU_TEAL_DESIGN_Y + 5 * unit + 2 * gap
        pad_full = self._ZIMU_BOX_DESIGN_H + filler - (spread_teal_y + teal_h)
        room = max(0, spread_teal_y - (checks_y + 38))
        up = min(max(0, pad_full - self._ZIMU_TEAL_BOTTOM_PAD), room)
        teal_y = spread_teal_y - up
        box_h = min(self._ZIMU_BOX_DESIGN_H + filler, teal_y + teal_h + self._ZIMU_TEAL_BOTTOM_PAD)
        return unit, btn_y, checks_y, teal_y, box_h

    # 组内复选框行 / 绿色说明 label_125 / 长按钮的设计 y（宽态铺排的归位基准）。
    _ZIMU_CHECKS_DESIGN_Y = 272
    _ZIMU_TEAL_DESIGN_Y = 309
    _ZIMU_BUTTON_DESIGN_Y = 220
    # 上方网格容器 gridLayoutWidget_27 的设计高（宽态按行铺排量同步增高）。
    _ZIMU_GRID_DESIGN_H = 186
    # 「点击下载字幕包」（label_download_sub_zip）的文字对齐：恒 AlignLeft|AlignVCenter。
    #
    # 根因（用户截图，最小化态）：该 QLabel 的设计态是 AlignCenter，而它所在的
    # horizontalLayout_10 是「两项均分布局」——窄态下提示文字「下载字幕包解压…」
    # 与链接同行均分，链接格子被拉到 84~250px 宽，格子左缘本就与「视频文件名」
    # （checkBox_filename）左缘同位（同宽时实测 content 坐标都是 433），但居中把
    # 可见文字整体右移了 (格子宽-文字宽)/2（用户环境格子约 200px、文字 105px，
    # 右移约 47px；本仓默认字体下 0~28px 随窗口浮动），于是「点击下载字幕包」
    # 看上去比「视频文件名」右移一大截。改左对齐后，可见文字左缘 == 链接格子
    # 左缘，两行同位时即与「视频文件名」严格上下对齐。
    # 宽态本来就用这个值（见 _sync_zimu_row_align），两态统一后不再有“宽态对、
    # 窄态偏右”的割裂；文字位置以外的任何几何（格子、提示文字、宽态铺排）不动。
    _ZIMU_LINK_ALIGN = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

    def _sync_zimu_page_align(self, _scroll=None) -> None:
        """设置-字幕：把底部空白收缩 + 行对齐入口整条重跑（钩子用，零参可调）。

        挂在字幕滚动区拉伸之后的钩子上
        （CustomScrollArea._post_wide_sync_hook），使「拉伸」与「收缩/对齐」在
        同一个事件里做完，中间态（白色填充/右缘控件先被绘制一帧）不会出现。
        休眠页直接返回，由切 tab 的 showEvent 补齐。

        顺序：先 _sync_zimu_fill_blank（它内部会重跑宽幅同步拿到终态，通用
        同步会把右缘锚定的复选框搬回右侧），再 _sync_zimu_row_align（按终态
        几何左移）。顺序颠倒会对齐完又被通用同步覆盖。
        """
        scroll = _scroll if _scroll is not None else getattr(self, "_zimu_scroll", None)
        self._sync_zimu_fill_blank(scroll)
        self._sync_zimu_row_align(scroll)

    def _sync_zimu_fill_blank(self, scroll=None) -> None:
        """设置-字幕：高视口下把组框下方的白色填充收进末尾组框，矮视口不动。

        用户需求：最大化时「添加外挂字幕」组最底部下方有大片白色空白，删除或缩进；
        最小化时界面、布局、控件保持不变；组内控件不移动（只动组框底边）。

        根因：字幕页内容短（groupBox_45 底缘 735，内容最小高 = 735 + 底部余量 72），
        widgetResizable=true 的滚动区在视口更高时把内容拉伸到视口高，多出的部分
        即组框下方的白色填充（1920x1170 下约 380px）；矮窗口视口 < 内容最小高，
        出现垂直滚动条、无填充。

        做法（只改「出现白色填充」的态，其余一个像素都不碰，双向幂等）：
          - 先显式重跑一次宽幅同步拿到终态视口/组框（registry 高度从未改动，
            每次复位回设计值 425，无累积漂移），再算填充
            filler = 视口高 - (组框.y + 设计高) - 底部余量；
          - filler <= 0（矮视口/最小化）直接 return：几何完全交给通用同步；
          - filler > 0：组框高度按 _zimu_wide_rows 公式收缩（x/y/宽不动，
            组间距保持设计值 19 不放大；绿色说明上提、底垫只留 12px，
            删掉的多余底垫转为组框下方的页面底色，纵向不再有单块大空白）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_45", None)
        if box is None or not box.isVisibleTo(self):
            return
        if scroll is None:
            scroll = getattr(self, "_zimu_scroll", None)
        if scroll is None:
            return
        if scroll.isVisibleTo(self):
            scroll.sync_wide_children_width()  # 取终态视口与组框，勿量过期几何
        viewport = scroll.viewport()
        if viewport is None:
            return
        margin = scroll.content_bottom_margin()
        filler = viewport.height() - (self._ZIMU_BOX_DESIGN_Y + self._ZIMU_BOX_DESIGN_H) - margin
        if filler <= 0:
            return
        teal = getattr(ui, "label_125", None)
        want_h = self._zimu_wide_rows(filler, teal.height() if teal is not None else 131)[4]
        g = box.geometry()
        if g.y() != self._ZIMU_BOX_DESIGN_Y or g.height() != want_h:
            box.setGeometry(g.x(), self._ZIMU_BOX_DESIGN_Y, g.width(), want_h)
            scroll.sync_content_min_height()

    def _sync_zimu_row_align(self, scroll=None) -> None:
        """设置-字幕：两处控件对齐「视频文件名」——复选框只宽态、下载链接两态都做。

        用户需求（最大化态）：「新添加字幕的视频在结束后重新刮削」
        （checkBox_sub_rescrape）左移到与「视频文件名」（checkBox_filename，
        位置保持不变）左缘上下对齐；「点击下载字幕包」
        （label_download_sub_zip）左移到「视频文件名」下方（左缘同样对齐）。

        用户需求（最小化态）：「点击下载字幕包」也左移到与「视频文件名」严格
        上下对齐，「视频文件名」位置保持不变；最大化时页面、布局、控件、提示
        文字等均保持不变（故宽态分支一字未改）。
        最小化态只需把链接文字从设计态的 AlignCenter 换成 _ZIMU_LINK_ALIGN：
        该行是两项均分布局，窄态下链接格子左缘本就与「视频文件名」左缘同位，
        偏右的全部来自居中（详见 _ZIMU_LINK_ALIGN 处的实测数据）。
        残留残差（不修，几何上无法两全）：「视频文件名」行也是两项均分，其第二项
        起点 = 行首 + 半行宽；下载行第二项起点 = 提示词自然宽 + 间距。窗口够宽
        时两者相等 → 严格对齐（本仓默认字体 Sans Serif 9pt/offscreen 96dpi 实测
        窗口 ≥ 1000px 残差 0，含用户截图的 1014x730）；更窄时提示词宽于半行宽
        （2*228+6 > 行宽），链接格子只能停在提示词右侧，残差 19~49px
        （800/900/950 宽实测 49/44/19）。要消除它只能压窄提示词（用户明确要求
        不动提示词）或让链接压住提示词，故保留残差，由
        tests/test_window_state_matrix.py::test_zimu_download_link_aligns_to_filename_when_narrow
        逐值锁定。

        根因：复选框是 groupBox_45 的直接子项，宽 236 ≥ 内宽一半不成立、右缘
        425+236=661 ≥ 组宽 701*0.9，被通用宽幅同步判为 _DOCK_RIGHT，最大化时
        整体右移到右缘；下载行是横向均分布局，链接位置随列宽漂移。
        上游「视频文件名」行同样是两项均分布局，两列 col0 同为 130，当前恰好
        同位——本方法按活测量的「视频文件名」左缘钉死，不依赖这种巧合。

        做法（只改「页面被拉宽」的态，还原态逐像素复原，双向幂等）：
          - extra <= 0 直接拆除下载行间隔、解除 label_102 钉宽、把链接文字改回
            左对齐、复位复选框行 y 后 return（复选框 x/组框几何由通用同步按设计复位）；
          - extra > 0：以「视频文件名」经公共祖先 content 映射的 x 为基准
            （注：QWidget.mapTo 要求目标是调用者的祖先，跨分支直接映射会
            拿到未定义值，离屏实测恒偏 +302，故一律经 content 中转）；
            复选框 move() 到基准 x（y 按纵向铺排值一并落定，越界则放弃）；
            下载行把 label_102 钉回 sizeHint 宽 + 插入固定间隔把链接推到
            基准 x（只允许左移，右推/放不下则放弃，链接右缘恒等于行右缘）。
            链接 QLabel 设计态是 AlignCenter：格子拉宽后即使左缘对齐，可见
            文字仍居中偏右，故宽态把文字对齐改左（窄态同样保持左对齐，见上）。
          - 纵向均匀铺排（宽态有填充时）：填充量按八等分铺进行内行距——上方
            网格 4 行各增 unit（unit = filler//8），长按钮下移 5*unit，
            复选框行下移 5*unit + unit//3（紧贴长按钮下方，间隙只 +unit//3），
            绿色说明先按 5*unit + 2*(unit//3) 铺排、再整体上提删掉下方多余
            底垫（底边与组框底边只留 12px，钳位不越过复选框行），组框高同步
            收缩；
            组框 y 钉回设计值，组间距保持 19 不放大。任一单块空白
            都不再是“大片”，下半部分相对位置保持紧凑。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        box = getattr(ui, "groupBox_45", None)
        filename = getattr(ui, "checkBox_filename", None)
        rescrape = getattr(ui, "checkBox_sub_rescrape", None)
        add_chs = getattr(ui, "checkBox_sub_add_chs", None)
        teal = getattr(ui, "label_125", None)
        button = getattr(ui, "pushButton_add_sub_for_all_video", None)
        lead = getattr(ui, "label_102", None)
        link = getattr(ui, "label_download_sub_zip", None)
        lay = getattr(ui, "horizontalLayout_10", None)
        grid = getattr(ui, "gridLayout_27", None)
        grid27 = getattr(ui, "gridLayoutWidget_27", None)
        if (
            box is None
            or filename is None
            or rescrape is None
            or add_chs is None
            or teal is None
            or button is None
            or lead is None
            or link is None
            or lay is None
            or grid is None
            or grid27 is None
            or not box.isVisibleTo(self)
        ):
            return
        if scroll is None:
            scroll = getattr(self, "_zimu_scroll", None)
        if scroll is None:
            return
        content = scroll.widget()
        if content is None:
            return
        if self._scroll_stretch_extra(scroll) <= 0:
            # 还原态：清零网格行最小高、拆除下载行间隔、解除前导钉宽、复位复选框
            # 行 y，其余交给通用同步复位。链接文字这里仍钉 _ZIMU_LINK_ALIGN
            # （不再恢复居中）：窄态下格子左缘已与「视频文件名」同位，改左对齐
            # 即让可见文字与它严格上下对齐，且不碰任何控件几何。
            if link.alignment() != self._ZIMU_LINK_ALIGN:
                link.setAlignment(self._ZIMU_LINK_ALIGN)
            if add_chs.y() != self._ZIMU_CHECKS_DESIGN_Y:
                add_chs.move(add_chs.x(), self._ZIMU_CHECKS_DESIGN_Y)
            if any(grid.rowMinimumHeight(r) != 0 for r in range(4)):
                for r in range(4):
                    grid.setRowMinimumHeight(r, 0)
                grid.invalidate()
                grid.activate()
            spacer = self._zimu_dl_spacer
            if spacer is not None and lay.indexOf(spacer) >= 0:
                lay.removeItem(spacer)
                self._zimu_dl_gap = -1
                self._pin_row_lead_width(lead, None)
                lay.invalidate()
                lay.activate()
            elif self._pin_row_lead_width(lead, None):
                lay.invalidate()
                lay.activate()
            return
        # 纵向均匀铺排：先清零行最小高再量设计行高，避免在已铺排几何上累加；
        # 上方网格 4 行各增 unit，长按钮/复选框行/绿色说明整体跟进（下半部分
        # 相对位置保持紧凑，复选框行与绿色说明只比设计间隙多 unit//3）。
        viewport = scroll.viewport()
        filler = 0
        if viewport is not None:
            filler = (
                viewport.height() - (self._ZIMU_BOX_DESIGN_Y + self._ZIMU_BOX_DESIGN_H) - scroll.content_bottom_margin()
            )
        unit, btn_y, checks_y, teal_y, _box_h = self._zimu_wide_rows(filler, teal.height())
        if any(grid.rowMinimumHeight(r) != 0 for r in range(4)):
            for r in range(4):
                grid.setRowMinimumHeight(r, 0)
            grid.invalidate()
            grid.activate()
        if unit > 0:
            for r in range(4):
                grid.setRowMinimumHeight(r, grid.cellRect(r, 1).height() + unit)
            gg = grid27.geometry()
            if gg.height() != self._ZIMU_GRID_DESIGN_H + 4 * unit:
                grid27.setGeometry(gg.x(), gg.y(), gg.width(), self._ZIMU_GRID_DESIGN_H + 4 * unit)
            grid.invalidate()
            grid.activate()
        if button.y() != btn_y:
            button.move(button.x(), btn_y)
        if add_chs.y() != checks_y:
            add_chs.move(add_chs.x(), checks_y)
        if teal.y() != teal_y:
            # label_125 与长按钮是通用同步的 _STRETCH 项：每次重跑都会按设计
            # 几何复位，此处落在终态之后 move，只改 y 不碰宽高。
            teal.move(teal.x(), teal_y)
        # 基准：「视频文件名」左缘（经 content 中转到各坐标系，见 docstring）。
        fn_cx = filename.mapTo(content, QPoint(0, 0)).x()
        # ---- 「新添加字幕…重新刮削」复选框：x 到基准，y 按铺排 ----
        tx_box = fn_cx - box.x()
        if tx_box >= 0 and tx_box + rescrape.width() <= box.width() - 8:
            if rescrape.x() != tx_box or rescrape.y() != checks_y:
                rescrape.move(tx_box, checks_y)
        # ---- 「点击下载字幕包」：钉前导 + 固定间隔，只允许左移 ----
        tx_g27 = fn_cx - box.x() - grid27.x()
        lead_w = lead.sizeHint().width()
        want_gap = tx_g27 - lead.x() - lead_w - lay.spacing()
        ok = want_gap >= 0 and tx_g27 <= link.x() and tx_g27 + link.sizeHint().width() <= grid27.width()
        new_gap = want_gap if ok else 0
        changed = self._pin_row_lead_width(lead, lead_w if ok else None)
        want_align = self._ZIMU_LINK_ALIGN if ok else Qt.AlignmentFlag.AlignCenter
        if link.alignment() != want_align:
            link.setAlignment(want_align)
        spacer = self._zimu_dl_spacer
        if self._zimu_dl_gap != new_gap or spacer is None or lay.indexOf(spacer) != 1:
            if spacer is None or lay.indexOf(spacer) != 1:
                if spacer is not None and lay.indexOf(spacer) >= 0:
                    lay.removeItem(spacer)
                # PyQt6 的 insertSpacing 返回值恒为 None，改插完再 itemAt 取回
                lay.insertSpacing(1, new_gap)
                spacer = lay.itemAt(1)
                self._zimu_dl_spacer = spacer
            if spacer is not None:
                spacer.changeSize(new_gap, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
                self._zimu_dl_gap = new_gap
                changed = True
        if not changed:
            return
        lay.invalidate()
        lay.activate()
        ui.gridLayout_27.invalidate()
        ui.gridLayout_27.activate()

    # ============ page_setting / 下载页: 「下载」行钉到「保留旧文件」行同一竖线 ============
    # 逐项对应关系（左=下载行 groupBox_24/horizontalLayoutWidget_14/horizontalLayout_16，
    # 右=保留旧文件行 groupBox_33/horizontalLayoutWidget_18/horizontalLayout_23）。
    # 「压缩」对应「剧照副本」是用户截图红框指定的位置；末项「主题视频」只存在于
    # 保留旧文件行，无对应项。封面图虽是两行共同的首项（x 天然同位），仍列入：
    # 见 _sync_xiazai_row_align 里关于「宽度也要跟」的那段说明。
    _XIAZAI_ROW_ALIGN_PAIRS = (
        ("checkBox_download_poster", "checkBox_old_poster"),
        ("checkBox_download_thumb", "checkBox_old_thumb"),
        ("checkBox_download_fanart", "checkBox_old_fanart"),
        ("checkBox_download_extrafanart", "checkBox_old_extrafanart"),
        ("checkBox_download_trailer", "checkBox_old_trailer"),
        ("checkBox_download_nfo", "checkBox_old_nfo"),
        ("checkBox_compress_downloaded_images", "checkBox_old_extrafanart_copy"),
    )

    def _sync_xiazai_row_align(self, xiazai_scroll=None) -> None:
        """设置-下载：把「下载」行的 7 个复选框逐项钉到「保留旧文件」行的同一竖线。

        用户需求（截图，最小化态）：「下载」行的复选框要向下与「保留旧文件」行
        严格上下对齐；「保留旧文件」行的位置保持不变。最大化态同样要求对齐。
        纵向（y/高）本就一致（实测两行容器在 content 里同 x=90、同高 31、两行
        复选框同高 17），故只重钉 x 与宽。

        根因：两行的容器与内部布局在 .ui 里长得几乎一样（都是
        horizontalLayoutWidget_* + QHBoxLayout），但项数不同——下载行 7 项、
        保留旧文件行 8 项，且第 7 项文案不同（「压缩」对「剧照副本」，其后还有
        「主题视频」）。QBoxLayout 在无 stretch、无 expanding 项时把余量**均分**
        给各项，于是第 k 项左缘 = 行首 + Σ(前 k 项自然宽 + spacing) + k·余量/项数，
        项数少的那一行每一项都落在 8 项那行的右侧。实测逐项偏差（content 坐标，
        离屏、默认 9pt 字体）：窗口 900 宽 +7~+52px、1032 宽 +12~+69px、
        1200 宽 +14~+83px、1500 宽 +20~+115px、1920 宽 +27~+160px——正是截图里
        「越往右偏得越多」的形状。

        为什么宽度也要跟：只 move x 的话，左邻仍停在自己的布局位置上，而它被拉宽
        后的控件里画的是**左对齐**文字——实测窗口 1200 宽时「压缩」被移到 671，
        而它左邻「nfo」的控件在 644、文字画到 687，两者字形直接压在一起（实测
        1200/1500/1920 各压 16~28px）。把宽度也重钉成保留旧文件行的同项宽度后，
        每个控件右缘正好止于下一项左缘（那正是保留旧文件行自身的排布），
        极窄窗口下文字被裁的宽度也与参照行一致，实测各宽度字形重叠恒为 0。

        挂在下载滚动区拉伸之后的钩子上（CustomScrollArea._post_wide_sync_hook）：
        通用拉伸会把两个行容器按「设计宽 + extra」拉宽并 invalidate+activate 重排，
        钩子跑在其后才是终态几何，同拍完成、不会被绘制出中间态。休眠页直接返回
        （量到的是设计态陈旧几何），由切 tab 的 showEvent 补齐。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        scroll = xiazai_scroll if xiazai_scroll is not None else getattr(self, "_xiazai_scroll", None)
        if scroll is None or not scroll.isVisibleTo(self):
            return
        content = scroll.widget()
        if content is None:
            return
        for dl_name, old_name in self._XIAZAI_ROW_ALIGN_PAIRS:
            dl = getattr(ui, dl_name, None)
            old = getattr(ui, old_name, None)
            if dl is None or old is None:
                continue
            # 两个复选框分属两个不同 groupBox，x 必须经公共祖先 content 归一后才能比：
            # QWidget.mapTo 要求目标是调用者的祖先，跨分支直接比 widget.x() 拿到的是
            # 「相对各自行容器」的局部坐标，会把真偏差算成 0（同 verify_actor_mapto）。
            have = dl.mapTo(content, QPoint(0, 0)).x()
            want = old.mapTo(content, QPoint(0, 0)).x()
            old_w = old.width()
            if have == want and dl.width() == old_w:
                continue  # 已对齐（含幂等重跑）：不发任何几何事件
            # 只重钉 x 与宽：y 与高度交给各自布局，跨行控件的纵向关系不动。
            dl.setGeometry(dl.x() + (want - have), dl.y(), old_w, dl.height())

    def resizeEvent(self, a0):
        # 全局 UI 为绝对定位布局（上游遗留），centralwidget 无布局管理器，
        # 窗口缩放时手动同步导航栏/内容区/顶部进度条几何，否则最大化后内容区固定 820x692
        super().resizeEvent(a0)
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        width, height = self.width(), self.height()
        ui.widget_setting.setGeometry(0, 0, 210, height)
        # 左侧背景条是 widget_setting 的子项、设计高仅 700：最大化后父项拉高而它
        # 滞留原高，底部露出父项底色、与上部各页配色断层，故随父项同高同步。
        try:
            ui.left_backgroud_widget.setGeometry(0, 0, 210, height)
        except Exception:
            pass
        self._sync_dock_layout()  # 左侧导航坞 + 贴底状态区（议题 #86/#102/#181）
        ui.stackedWidget.setGeometry(210, 6, max(width - 210 - 2, 400), max(height - 8, 300))
        ui.progressBar_scrape.setGeometry(209, -1, max(width - 211, 100), 7)
        self._sync_page_layouts()  # 同步动态页面的内部尺寸

    # ============ 左侧导航坞（widget_setting）自适应（议题 #86/#102/#181）============
    # .ui 里侧栏是绝对定位：widget_buttons(0,50,210,390) 内 layoutWidget6(0,0,211,380)
    # 由 QVBoxLayout(spacing 8) 竖排 8 个 40px 导航按钮（8*40+7*8=376），下方
    # label_show_version(0,489,210,201) 是底对齐状态区（正常模式/配置文件名/版本号/
    # 点击检查最新版本），label_local_number(0,680,21,21) 是左下角数字浮标。
    # 设计态整列需 50+390+49+201+40(底距)=730 高；界面缩放很大时（用户 175% 反馈：
    # 可用逻辑分辨率仅 1097x594，窗口高 ~500）贴底公式 min(..., height-201) 会把状态区
    # 顶进导航区 → 状态文字压在「检测网络/使用说明」按钮上（叠字，见 _sync_dock_layout）。
    _DOCK_NAV_BTNS = (
        "pushButton_main",
        "pushButton_log",
        "pushButton_tool",
        "pushButton_emby_manager_nav",
        "pushButton_nfo_library",
        "pushButton_setting",
        "pushButton_net",
        "pushButton_about",
    )
    _DOCK_NAV_BTN_H = 40  # 导航按钮设计高（.ui setMaximumHeight(…, 40)）
    _DOCK_NAV_BTN_H_MIN = 36  # 压缩下限：border-width 9px×2 + 14px 字号仍能显示文字
    _DOCK_NAV_SPACING = 8  # verticalLayout 设计间距
    _DOCK_NAV_SPACING_MIN = 2  # 压缩下限（再小按钮会粘连）
    # widget_buttons 容器高。8 个导航按钮的内容高 8*40 + 7*8 = 376，容器只留这么多：
    # 原设计值 390 多出的 14px 是纯余量（layoutWidget6 的 QVBoxLayout 把富余空间堆在
    # 末尾，**不影响按钮落位**，见 _layout_dock_nav），收掉后二维码白得 14px 预算。
    # 这 14px 正是「状态文字固定预留 5 行 + 二维码恒 180px」能在**默认窗高 700**
    # 同时成立的关键：700 高下 5 行预留(75) + 间距(16) + 链接(22) + 内距(4) + 二维码(180)
    # = 297，加导航底 20+376=396 共 693 ≤ 700，还余 7px；若容器仍高 390（导航底 410）
    # 则需 707 > 700，缺口会把导航整个上移 7px（用户反馈的「整体向上移动」）。
    # 注：曾为「让下方收款码满宽」把按钮/间距收紧到 38/4、容器收到 340，用户反馈后已
    # 撤回——满宽不是必需的，收款码按固定边长摆放即可（见 _layout_donate）。
    _DOCK_NAV_H = 376
    # 导航区顶边的两个取值，与 _windows_auto_adjust 里的 widget_buttons.move(0, 50/20)
    # 必须一致——那条 move 只在启动/标题栏设置变更时跑一次，_sync_dock_layout 随后会
    # 读 .y() 把它当基线。写成常量而不是读 .y()：_layout_dock_nav 结尾会
    # setGeometry(0, top, …) 把读回来的值又写回去，若基线来自自身就会被逐次抬高。
    _DOCK_NAV_TOP_HIDE = 50  # 隐藏窗口标题栏（window_title == "hide"）
    _DOCK_NAV_TOP_SHOW = 20  # 显示窗口标题栏
    # 导航区可上移到离窗顶多近。用户原话「软件界面容器上方还有10px以上的空间」——
    # 即要求二维码显示不满时把导航整体上移利用这段空间，但**不能顶到 0**（留 10px，
    # 否则第一个按钮贴着窗口边框、圆角与阴影会被切）。
    _DOCK_NAV_TOP_MIN = 10
    _DOCK_STATUS_H = 201  # label_show_version 设计高
    _DOCK_STATUS_H_MIN = 72  # 状态区压缩下限（13px 字号约 4 行，超出裁上方空行）
    _DOCK_STATUS_GAP = 12  # 导航底与状态区顶的最小间距
    # 状态区底（= 状态矩形底 = 窗底）距窗底的预留。原为 40（议题 #102：贴底太靠下），
    # 但 label_show_version 是 AlignBottom 的——文字只占矩形底部约 3~4 行，矩形底与
    # 文字底之间那 40px 全是死区，用户截图里「读取模式·字段优先 / actor.json / MDCx
    # 版本号 / 点击检查最新版本」四行整体悬在窗底上方、下面空一截。改为 0。
    # 顺带把二维码的高度预算也放宽 40px（见 _layout_donate 的 one_size 公式），
    # 这是「二维码保持 180px」能稳定成立的关键——原先默认窗高下预算只有 177。
    # 第十五轮起它只决定「窗底这条基准线在哪」：赞助块顶锚导航底后，富余高度全部落
    # 在块与这条线之间（用户要的就是这个），0 = 基准线就是窗底、富余最多。
    # 注：置 0 后 _DOCK_STATUS_Y_MIN 在公式里被 min(..., height-_DOCK_STATUS_H) 覆盖
    # （min(max(x, 489), x) ≡ x），该下限对「空间够」分支不再生效，仅矮窗分支仍用。
    _DOCK_STATUS_BOTTOM_PAD = 0  # 状态区底与窗底之间的预留（0 = 基准线就是窗底）
    _DOCK_STATUS_Y_MIN = 489  # 状态区不低于设计 y
    _DOCK_LOCAL_Y_MIN = 680  # label_local_number 不低于设计 y
    _DOCK_LOCAL_H = 21  # label_local_number 设计高
    # 状态文字块高（_dock_status_text_h）的上次测量值，-1 = 从未测量。作「行数是否变了」
    # 的闸门：show_scrape_info 在刮削过程中按**文件**刷新同一行进度文案（可达上千次），
    # 不设闸门就会每个文件重排一次左侧导航 + 收款码（见 _resync_dock_status_layout）。
    _dock_status_text_h_last = -1

    # region 侧栏「使用说明」下方的微信收款码 + [赞助作者] 链接
    _DONATE_LINK_FONT_PX = 16  # 文档用：字号实际由 style.py 的 QSS 决定，此处仅备查
    # 16px 的 fontMetrics().height() = 19，行高 22 留 3px 余量；_DONATE_LINK_H 须 ≥ 它
    _DONATE_LINK_H = 22
    # 以下三个间距按「默认窗口 1030x700 下二维码尽量大」倒推得出（用户第 10 轮要求）。
    # 第十五轮把块改成顶锚后，预算公式改写为（真实运行：nav_top 20、_DOCK_NAV_H 376
    # → nav_bottom 396、5 行预留**真实** 85）：
    #   one_size = 窗底 − (nav_bottom + _DONATE_TOP_GAP) − LINK_GAP − LINK_H − TEXT_GAP − 预留
    # 原值 TEXT_GAP 17 / LINK_GAP 6 / PAD 6 时 one_size 只有 155，二维码被卡在 155。
    # 第十三轮收到 10 / 2 / 2（预留按 lineSpacing 估成 75，gap = 10+LIFT 6 = 16，
    # 合计与本轮的 6+85 = 91 **完全相等**），第十五轮只是把「估错的 10px」从预留挪进
    # 间距，总消耗 117 不变，故 one_size = height − 513 与各档门槛逐值保持不变。
    _DONATE_LINK_GAP = 2  # 二维码与 [赞助作者] 的间距
    # [赞助作者] 底边 → 状态文字首行的间距。**第十五轮由 10 改成 6**。
    # 旧值 10 是在「状态文字块高按 lineSpacing×(行数−1)+height 估」的前提下定的，
    # 而真实运行里状态文字每行都带 emoji（🎉/💠/🛠/🐰/🔍），Qt 回退字体的**真实行距是
    # 17px 而不是 lineSpacing 的 15px**，5 行实测 85px 而非估出来的 75px——低估的 10px
    # 全被这段 10px 的间距吃掉，于是用户截图里「[赞助作者]」与文字只剩 6px、且第 5 行
    # 「🔍 点击检查最新版」被窗底裁掉半个字高（见 _dock_status_text_reserve_h 的探针）。
    # 现在间距按「实测够用」取 6：既保证不叠字，又让 **≥693 时二维码仍恒为 180**（预算
    # 守恒，见 _DONATE_QR_SIZE 处 one_size = height − 513）。
    # 原 _DONATE_LIFT（6，「赞助块整体上移量」）随本轮改动**整体删除**：赞助块改为**顶锚**
    # 在导航底（见 _layout_donate），已经顶到能顶的最高处，再谈「上移多少」没有意义，
    # 那 6px 如今就是下面这个间距。
    _DONATE_TEXT_GAP = 6  # [赞助作者] 底边到状态文字首行的间距
    # 最大化时支付宝码与微信码之间的间距：取「一行汉字的高度」，即侧栏 [赞助作者]
    # 的行高（_DONATE_LINK_H / _DONATE_LINK_FONT_PX=16 实测 fontMetrics().height()=19、
    # 行高约 22），使两码之间的视觉分隔与正文行距统一（用户第 14 轮要求）。
    # 独立于 _DONATE_PAD：后者是色块与导航/状态文字的内边距，收窄它是为了把高度
    # 全留给二维码；两码之间的间距是给用户看的分隔，要「疏」不要「紧」。
    _DONATE_ALIPAY_GAP = 22
    # 与导航区/状态区的内边距。第十五轮起其只在**底锚（最大化）**路径的净高
    # 公式（avail = qr_bottom − PAD − nav_bottom）与「[赞助作者]→状态文字」
    # 间距下限护栏里用；顶锚档的「导航底 → 块顶」间距由 _DONATE_TOP_GAP 控制
    # （保持最大化布局逐像素不变）。
    _DONATE_PAD = 0  # 底锚档净高护栏/间距下限专用，顶锚不再用它
    # 非最大化（顶锚）时「使用说明按钮底 → 二维码顶」的间距。
    # 与导航按钮间距等高：软件设置→检测网络之间即 _DOCK_NAV_SPACING = 8，
    # 故此处同样取 8；二维码与 [赞助作者] 间距仍是 2px（_DONATE_LINK_GAP 不变）；
    # 最大化（底锚）布局不动，故独立成常量、不改 _DONATE_PAD。
    _DONATE_TOP_GAP = 8
    # **底锚（最大化）时**状态文字带底边离窗底预留的高度——沿用旧版议题 #102 的
    # `_DOCK_STATUS_BOTTOM_PAD = 40`。
    # 第十六轮实测（100% 字号、最大化 1040 高、读取完成后 5 行文字）：
    #   MDCx-20261007（底锚）：支付宝 509 / 微信 711 / [赞助作者] 893 / 文字 925..1000
    #   本轮实现（底锚）    ：支付宝 503 / 微信 705 / [赞助作者] 887 / 文字 915..1000
    # 差 6px（旧版文字块高按 lineSpacing 估成 75 而真实 85，这 10px 差值恰好补掉大半）。
    # 为什么不给 0（贴着窗底）：用户要的是「**和旧版一样的高度**」，旧版窗底就留 40px，
    # 给 0 反而比旧版再低 40px、观感与截图 001 不符。
    # 为什么不给全局恢复 `_DOCK_STATUS_BOTTOM_PAD = 40`：那个值参与分支①的 status_y
    # 公式，会把 `one_size` 砍掉 40 → 默认窗高 700 立刻放不满 180，违反
    # 「等于或高于699时收款码高度恒为180px」。故只在底锚路径里用。
    _DONATE_BOTTOM_SLACK = 20
    # 二维码边长**设计值 180**：侧栏宽 210，两侧各留 15px 空白（210 - 2*15 = 180）。
    # 用户诉求（第十三轮，原话「固定！固定！固定！」）：「微信与支付宝二维码要在任何情况下
    # 都不会放大或缩小或向上移动或向下移动」「把两个二维码图片高度都改回180px，固定」，
    # 并补充「窗高低于 699（100% 字号）时还是将收款码缩小，等于或高于699时收款码高度
    # 恒为180px」。故本常量是**上限**，取值规则为：
    #   · 可用高度 ≥ 180 → **恒为 180**（不放大、不缩小、不随窗口高度变化）；
    #   · 可用高度 < 180  → 按可用高度等比缩小（用户明确要求「还是将收款码缩小」）；
    #   · 缩小到 _DONATE_QR_MIN 以下 → 整块隐藏（40px 的码已无法辨识，叠字/糊码更糟）。
    # 高度预算（真实运行：nav_top 20、_DOCK_NAV_H 376 → nav_bottom 396、5 行预留 **85**）：
    #   one_size = 窗底 − 块顶(nav_bottom + _DONATE_TOP_GAP 8) − LINK_GAP 2 − LINK_H 22 − gap 6 − 预留 85
    #           = height − 396 − 123 = height − 519
    # （块顶 = nav_bottom + _DONATE_TOP_GAP(8)；_DONATE_TOP_GAP 与导航按钮间距
    #   _DOCK_NAV_SPACING 等高，即软件设置→检测网络的间距。）
    # 与第十三轮算出的 `height − 513` 差 6px（使用说明→二维码由 2px 放到 8px，
    # 多占的 6px 即此差值）。所以：
    #   · 默认窗高 700 起余 1px、≥699 二维码恒 180，且**读取前后完全相同**；
    #   · 低于 699 先由 _sync_dock_layout 把导航上移（最多 _DOCK_NAV_TOP_MIN=10，即用户
    #     授权的「上方还有 10px 以上的空间」）补 10px，即 689 及以上仍能补到 180；
    #     689 以下按剩余高度缩小、549 以下整块隐藏。
    # 变的只有**富余高度落在哪里**，而这一点**按窗口状态分两种锚法**（第十六轮）：
    #   · 非最大化 → **顶锚**在导航底，富余全落块**下方**。于是「二维码 → [赞助作者] →
    #     五行状态字」整体上移到能到的最高处（用户第十五轮：「允许向上移动多少px就向上
    #     移动多少px，移动到最大允许的高度px值」）。本式 one_size = height − 519 即此档。
    #   · 最大化 → **底锚**在窗底，富余全堆在块**上方**（旧版 MDCx-20261007 的锚法）。
    #     用户第十六轮：「最大化时…向上移动太多太多了，最大化时向下移动一些，改成和
    #     MDCx-20261007 中最大化时一样的高度，最小化时…均保持不变」。此档预算见
    #     _DONATE_BOTTOM_SLACK。
    # 两种锚法都只用**固定量**定位，故第十三轮「读取/刮削不动」的不变量在两档都成立。
    _DONATE_QR_SIZE = 180
    # 二维码**缩小的下限**：低于此边长直接隐藏整块收款码（军规③：宁可不显示也不叠字）。
    # 与「边长设计值」无关——满 180 时绝不使用本常量。
    _DONATE_QR_MIN = 40
    # 状态文字块的**预留行数**（定位专用，与当前文字行数无关）。
    # 用户诉求：「读取或刮削模式下读取或刮削前二维码位置、软件界面、软件日志、软件工具、
    # 演员管理、信息管理、软件设置、检测网络、使用说明位置都保持固定」。旧实现按实测
    # 行数定位，读取完成时 show_scrape_info 在文字**顶部**追加一行「🎉 刮削完成 N/N」，
    # 文字块长高一行 → 码块上移一行 + 可用高度少一行 → 二维码缩小、导航被上移
    # （实测 100% 字号 700 高：导航 20→13、二维码 416→405）。改用固定预留行数后，
    # 读取前后算出的几何逐值相同。
    # 5 行 = 真实运行读取完成后的最大常见行数（进度行 + 模式 + 文件 + 版本 + 检查更新）。
    # **预留高度不等于 lineSpacing×(5−1)+height**：这五行每行都带 emoji，Qt 回退字体的
    # 真实行距是 17px 而 lineSpacing 只报 15px，5 行真实 85px、公式只有 75px。少算的
    # 10px 全被间距吃掉 → 用户截图里「[赞助作者]」与文字只剩 6px、第 5 行「🔍 点击检查
    # 最新版」被窗底裁掉半个字高。故预留高度由 `_dock_status_text_reserve_h()` 用
    # 「5 个 emoji 的真实排版」探针量出来（见该方法）。
    # 超出预留（单文件模式 + 软链接 + 进度行 = 7 行，真实 119px）时 _layout_donate
    # 改按实测行数判叠字、必要时隐藏收款码（宁可不显示也不叠字，军规③）。
    _DONATE_STATUS_RESERVE_LINES = 5
    # 探针用矩形的宽度：只要求「一行放得下一个 emoji、不发生软换行」，取 4096 远超需要。
    # 刻意不用侧栏真实宽度 210——那样 boundingRect 会按 210 折行，行数算错（实测
    # `"\n"×5` 在 100000 宽下得 90，而真实渲染只有 85，正是折行把行高算多了）。
    _DONATE_TEXT_PROBE_W = 4096
    # 最大化时在微信码**上方**再加一张支付宝码（宽度与微信码严格一致）。
    # 判据仍是「**两张都放得下完整 _DONATE_QR_SIZE 才显示**」（宁可少一张，也绝不因多
    # 一张码而缩小微信码）；窗高偏矮时微信码自己会缩小，但那只影响微信码，**不因此
    # 把支付宝码也塞进来**。_DONATE_ALIPAY_MIN 仅作控件占位初值。
    _DONATE_ALIPAY_MIN = 90  # 支付宝码占位初值（满尺寸时边长恒为 _DONATE_QR_SIZE）
    _DONATE_LINK_COLOR = "#0078D7"  # 与「赞助作者」页 [赞助作者] 链接同色
    _DONATE_LINK_COLOR_DARK = "#4DA6FF"  # 暗黑模式提亮，保证可读

    def _init_donate_widgets(self) -> None:
        """在侧栏挂「微信收款码 + [赞助作者]」两个控件（运行时注入，不改 .ui）。

        .ui/MDCx.py 由 pyuic6 生成且有同步测试，故侧栏新增控件走运行时注入：
        挂到 widget_setting 下并 raise_ 到 left_backgroud_widget 之上。
        位置/显隐由 _layout_donate 随窗口高度自适应（见 _sync_dock_layout）。
        """
        ui = self.Ui
        parent = ui.widget_setting
        qr = QLabel(parent=parent)
        qr.setObjectName("label_donate_qr")
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 先按设计边长 _DONATE_QR_SIZE 占位（用户要求「等于或高于693时高度恒为180px」），
        # 首帧由 _layout_donate 按实际可用高度摆位后再显示；窗口偏矮时它会缩小
        qr.setFixedSize(self._DONATE_QR_SIZE, self._DONATE_QR_SIZE)
        qr.setToolTip(" 微信扫码赞助 ")
        qr.hide()  # 位置/尺寸由 _layout_donate 摆好后再显示，避免首帧错位
        link = QLabel(parent=parent)
        link.setObjectName("label_donate_link")
        link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        link.setFixedHeight(self._DONATE_LINK_H)
        link.setOpenExternalLinks(False)
        link.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        link.setToolTip(" 点击查看赞助方式 ")
        link.linkActivated.connect(lambda _url: self.show_donate_dialog())
        link.hide()
        # 支付宝码：只在最大化且两张都放得下 _DONATE_QR_SIZE 时显示（见 _layout_donate），
        # 宽度与微信码严格一致
        alipay = QLabel(parent=parent)
        alipay.setObjectName("label_donate_alipay")
        alipay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        alipay.setFixedSize(self._DONATE_ALIPAY_MIN, self._DONATE_ALIPAY_MIN)
        alipay.setToolTip(" 支付宝扫码赞助 ")
        alipay.hide()
        ui.label_donate_qr = qr
        ui.label_donate_link = link
        ui.label_donate_alipay = alipay
        self._donate_qr_cache = QPixmap()
        self._donate_qr_cache_size = 0
        self._donate_alipay_cache = QPixmap()
        self._donate_alipay_cache_size = 0
        qr.raise_()
        alipay.raise_()
        link.raise_()
        self._style_donate_link()

    def _style_donate_link(self) -> None:
        """[赞助作者] 富文本链接：颜色亮色 #0078D7 / 暗黑提亮。

        字号不在这里写——style.py 的 `QLabel#label_donate_link{font-size:14px}` 与
        导航按钮同一套 QSS 机制（QLabel.setFont 会被样式表覆盖而失效，只有 QSS
        或富文本内联 font-size 起作用），避免两处字号各自漂移。
        """
        link = getattr(self.Ui, "label_donate_link", None)
        if link is None:
            return
        color = self._DONATE_LINK_COLOR_DARK if self.dark_mode else self._DONATE_LINK_COLOR
        link.setText(f'<a href="#donate" style="color:{color}; text-decoration:none;">[赞助作者]</a>')

    def show_donate_dialog(self) -> None:
        """弹出赞助窗口（收款码 + 新人榜/土豪榜）。"""
        try:
            dialog = DonateDialog(self)
            dialog.exec()
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    def _hide_donate(self) -> None:
        """空间完全不够时隐藏收款码（极矮窗口，导航独占整列）。"""
        for name in ("label_donate_qr", "label_donate_link", "label_donate_alipay"):
            widget = getattr(self.Ui, name, None)
            if widget is not None:
                widget.setVisible(False)

    def _dock_status_text_h(self) -> int:
        """状态区（正常模式·字段优先 / 配置文件 / 版本号 / 点击检查）文字块的**估算**高度。

        label_show_version 的对齐方式随赞助块模式切换（底对齐 ↔ 顶对齐，见 `_layout_donate`），
        故这里**不用于定位**，只作两件事：
          ① 「行数变了没有」的闸门键（`_resync_dock_status_layout`）——`show_scrape_info` 在
             刮削过程中按**文件**刷新同一行进度文案（一次批量可达上千次），不设闸门就会
             每个文件重排一次左侧导航 + 收款码；
          ② 极矮窗口下判断状态区还能不能留 `_DOCK_STATUS_H_MIN`（见 `_sync_dock_layout`）。
        公式是**估算**：真实运行每行都带 emoji、真实行距 17px 而 lineSpacing 只报 15px，
        故它会**低估**（100% 字号 5 行估 75、真实 85）。凡是需要「准」的地方一律用
        `_dock_status_text_probe_h`（真实排版探针）或 `_dock_status_text_reserve_h`。

        历史（本函数曾是定位的唯一来源，也就是用户反馈的「读取后整体上移」根因）：
        第十三轮前 `_layout_donate` 用这里的实测值锚定二维码下沿，于是读取完成时
        `show_scrape_info` 在顶部追加的「🎉 刮削完成 N/N」把整块上移一行、还把二维码
        缩小、把导航上移（实测 700 高：导航 20→13、二维码 416→405）。定位已全面改用
        固定预留（见 `_dock_status_text_reserve_h`）。
        """
        label = self.Ui.label_show_version
        fm = label.fontMetrics()
        text = label.text()
        breaks = text.count("\n") + text.count("<br>")
        # show_scrape_info 的文本以换行开头（f"\n{scrape_info}..."），那一行是空的、
        # 只在块顶部留白而无墨迹。label 是底对齐的，这行空白不移动末行，故要扣掉，
        # 否则间距会整整多出一个行高（实测 15px）。
        stripped = text.lstrip("\n\r")
        breaks -= text[: len(text) - len(stripped)].count("\n")
        return fm.lineSpacing() * breaks + fm.height()

    def _dock_status_text_probe_h(self, text: str) -> int:
        """按 `text` 的**真实排版**量出文字块高度（离屏探针，非估算）。

        为什么不能拿 `lineSpacing × (行数−1) + height` 顶替：真实运行的状态文字每一行
        都以 emoji 开头（🎉/💠/🛠/🐰/🔍），Qt 对这些码位回退到 emoji 字体，而**回退字体的
        行距比 `fontMetrics().lineSpacing()` 报的值大 2px**。实测 100% 字号 Consolas：
        `lineSpacing()=15 / height()=15`，但 `QLabel.sizeHint().height()` 逐行实测
        1行17 / 2行34 / 3行51 / 4行68 / **5行85** / 6行102 / 7行119 —— 即真实行距 17。
        公式估出的 5 行 75 整整少 10px，这就是用户截图里末行被窗底裁掉的直接原因。

        `boundingRect(宽矩形, TextExpandTabs, text)` 会走真实的字体回退与行距，实测对
        5 个 emoji 得 85，与 `sizeHint()` 的真实渲染**逐值相符**；对纯 ASCII/CJK 则给出
        15/行（正确，那些字形没有回退）。宽度必须够大（`_DONATE_TEXT_PROBE_W`），否则
        boundingRect 会按给定宽度折行、把行高算多（实测 `"\n"×5` 得 90 ≠ 85）。

        `<br>` 会被 Qt 当软换行渲染（`show_scrape_info` 的文案里有），但对纯文本探针而言
        只是普通字符，故先换成 `\n` 再量。行首那个空行（`show_scrape_info` 的文本以 `\n`
        开头）同样先剥掉——它只在块顶留白、无墨迹，且底/顶对齐都不受它影响。
        """
        probe = text.replace("<br>", "\n").lstrip("\n\r")
        if not probe:
            return 0
        fm = self.Ui.label_show_version.fontMetrics()
        return fm.boundingRect(
            QRect(0, 0, self._DONATE_TEXT_PROBE_W, 0),
            Qt.TextFlag.TextExpandTabs,
            probe,
        ).height()

    def _dock_status_text_reserve_h(self) -> int:
        """状态文字块的**预留**高度：固定行数 × 真实行距，与当前文字行数无关。

        收款码块整条链的下沿恒定挂在「块顶 + 预留高 + 间距」处（见 `_layout_donate`），
        于是读取/刮削时状态文字多一行或少一行，**二维码、`[赞助作者]`、导航按钮、状态矩形
        一个像素都不会动**（用户原话：「我需要的是读取或刮削前…位置都保持固定！注意是固定！
        固定！固定！」）。行数取 `_DONATE_STATUS_RESERVE_LINES`（5，覆盖真实运行读取完成
        后的「进度行 + 模式 + 文件 + 版本 + 检查更新」）。文字实际比预留还高时（单文件模式
        + 软链接 + 进度行可达 7 行），`_layout_donate` 用 `_dock_status_text_probe_h` 量出的
        真实高度判叠字、必要时隐藏收款码（军规③）——**这一步只影响显隐、不移动任何控件**。

        高度由 `_dock_status_text_probe_h` 对 `RESERVE_LINES` 个 emoji 量出（100% 字号实测
        85px），**不用 lineSpacing 公式**（那只得 75px，见该方法 docstring）。字号/主题
        变化时两者同步变化，不会出现「预留比实际还小」的错配。
        """
        lines = 6 if self._donate_bottom_anchor() else self._DONATE_STATUS_RESERVE_LINES
        return self._dock_status_text_probe_h("\n".join(["\U0001f389"] * lines))

    def _dock_status_text_real_h(self) -> int:
        """状态文字**当前文本**的真实渲染高度（`_dock_status_text_probe_h` 的实例用法）。

        只用于一处判断：`_layout_donate` 里「预留带装不装得下当前文字」——装不下就隐藏
        整块收款码，把高度全让给状态文字（宁可不显示也不裁字，军规③）。**不参与定位**，
        故文字增删行不会移动任何控件。
        """
        return self._dock_status_text_probe_h(self.Ui.label_show_version.text())

    def _resync_dock_status_layout(self) -> None:
        """状态文字**行数变了**之后重排贴底区，避免新增的行被收款码块盖住。

        回归背景（用户截图，读取模式）：首次读取完成后 `show_scrape_info` 往
        `label_show_version` **顶部**追加一行「🎉 刮削完成 7/7」。旧实现里收款码块是按
        **旧行数**摆好的（`_layout_donate` 用实测文字高锚定二维码下沿），于是两者叠字，
        **最大化再最小化一下就恢复正常**。如今定位已改用固定预留（行数变化不再移动任何
        控件），这里保留重排是为了让「文字超出预留行数」时能重新判一次叠字并隐藏收款码。

        用文字块高做闸门：行数没变就不动。`show_scrape_info` 在刮削过程中按文件调用
        （`scraper.py: 已刮削 {count}/{count_all}`），不设闸门会每个文件重排一次
        左侧导航 + 收款码。
        """
        if getattr(self, "Ui", None) is None:
            return
        text_h = self._dock_status_text_h()
        if text_h == self._dock_status_text_h_last:
            return
        self._dock_status_text_h_last = text_h
        self._sync_dock_layout()

    def set_dock_status_text(self, text: str) -> None:
        """`label_show_version` 的唯一入口：写文本 + 行数变了就重排贴底区。

        原先 `init.py` 把 `label_show_version` 信号直接连到 `QLabel.setText`，文本变了
        没人重排，新行就被收款码块盖住（见 `_resync_dock_status_layout`）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        ui.label_show_version.setText(text)
        self._resync_dock_status_layout()

    def _donate_bottom_anchor(self) -> bool:
        """赞助块是否用**底锚**（整块挂窗底）——仅最大化/全屏时为真（第十六轮）。

        用户原话（附 001/002 两张最大化截图，001 是 MDCx-20261007 编译出来的效果）：
        「最大化时向下移动一些，改成和 MDCx-20261007 中最大化时一样的高度，最小化时软件
        界面布局、组件、控件、提示词等等均保持不变」。

        第十五轮把整块改成**顶锚**导航底，在**任何**窗态都生效；最大化时富余高度有几百
        像素，块被顶到导航区正下方，状态文字一路跟着上移（实测 1040 高：文字 955→608，
        **上移 347px**），与旧版截图差 109~130px，用户反馈「向上移动太多太多了」。

        实测两版几何（100% 字号、最大化 1040 高、读取完成后 5 行文字；探针
        `C:\\Users\\ZhouHan\\AppData\\Local\\Temp\\opencode\\probe_ref.py` 直接跑旧源码得到）：
            MDCx-20261007（底锚）：支付宝 509 / 微信 711 / [赞助作者] 893 / 文字 925..1000
            第十五轮顶锚版        ：支付宝 398 / 微信 600 / [赞助作者] 782 / 文字 810..895
        故最大化改回底锚（`_DONATE_BOTTOM_SLACK` 把差值收到 6px），非最大化保持顶锚不变。

        全屏与最大化同义（支付宝码门控同理），故一并判。
        """
        return self.isMaximized() or self.isFullScreen()

    def _layout_donate(self, nav_bottom: int, status_y: int, status_h: int) -> tuple[int, int, int]:
        """在导航区与状态区之间安放收款码，返回校正后的 (status_y, status_h, qr_deficit)。

        ## 定位：**按窗口状态二选一**锚法（第十六轮）

        两种锚法摆的都是同一条链 `[支付宝码(仅最大化)] → 微信码 → [赞助作者] → 状态文字
        预留带`，唯一区别是「富余高度落在块的哪一侧」——这正是第十五/十六两轮来回调整的
        那个变量。

        **① 非最大化 → 顶锚**（第十五轮，用户原话「最小化时在不压缩二维码180px的高度、
        不遮盖[赞助作者]、刮削完成 7/7的字体的前提下将…整体向上移动，允许向上移动多少px
        就向上移动多少px，移动到最大允许的高度px值」）：
            group_top = nav_bottom + _DONATE_TOP_GAP
            qr_top    = group_top（支付宝码显示时微信码顺延到支付宝码下方）
            link_top  = qr_top + qr_size + _DONATE_LINK_GAP
            text_top  = link_top + _DONATE_LINK_H + gap
            块底      = text_top + reserve_h
            one_size  = 窗底 − group_top − (LINK_GAP + LINK_H + gap + reserve_h) = height − 519
        富余高度全部落在块**下方**；`qr_top` 只由 `nav_bottom` 决定，故 700/741/800/900/1080
        各档高度下二维码**同一个像素都不差**（这比第十三轮「读取/刮削不动」的承诺更强）。

        **② 最大化 → 底锚**（第十六轮，用户原话「最大化时二维码图片、赞助作者、刮削完成
        7/7…向上移动太多太多了，最大化时向下移动一些，改成和 MDCx-20261007 中最大化时
        一样的高度」）：
            text_top  = status_bottom − _DONATE_BOTTOM_SLACK − reserve_h
            link_top  = text_top − gap − _DONATE_LINK_H
            qr_bottom = link_top − _DONATE_LINK_GAP
            qr_top    = qr_bottom − qr_size       （支付宝码再往**上**顺延）
            one_size  = qr_bottom − _DONATE_PAD − nav_bottom = height − 553
        富余高度全部落在块**上方**（导航区与支付宝码之间留白），与 MDCx-20261007 的锚法
        一致（实测差 6px，见 `_DONATE_BOTTOM_SLACK`）。

        两种锚法都**只用固定量**定位（`status_bottom`、`nav_bottom`、`reserve_h`、`gap`…），
        与状态文字当前几行无关，故第十三轮「读取/刮削不动」的不变量在两档都成立。
        本轮起例外：块顶为「nav_bottom + _DONATE_TOP_GAP(8)」，即使用说明→二维码
        取与软件设置→检测网络等高的导航按钮间距（_DOCK_NAV_SPACING）；最大化一侧不动。

        ## 不变量：定位与文字行数无关

        预留高用 `_dock_status_text_reserve_h()`（固定 5 行的**真实**高度，100% 字号实测
        85px），**不用** `_dock_status_text_h()`（估算，见其 docstring）。第十三轮前正是用
        那个估算值锚定，于是读取完成时 `show_scrape_info` 在顶部追加的「🎉 刮削完成 N/N」
        让整块上移一行、二维码缩小、缺口又把导航上移（实测 700 高：导航 20→13、
        二维码 416→405，用户截图逐条对上）。

        ## 边长规则（两档同）

        可用高度 ≥ `_DONATE_QR_SIZE` 时 `qr_size ≡ _DONATE_QR_SIZE`；不足时按可用高度等比
        **缩小**（用户第十三轮：「窗高低于 699（100% 字号）时还是将收款码缩小，等于或
        高于699时收款码高度恒为180px」）；缩到 `_DONATE_QR_MIN` 以下才整块隐藏。缩小量
        同样只由固定量算出，故「读取前后边长一致」这条不变量对缩小档也成立。

        ## 最大化时上方多一张支付宝码

        **只在两张码都能保持完整 _DONATE_QR_SIZE 时才显示**（判据**不用** qr_size）。
        放不下就**只显示微信码**，绝不因为多一张码而缩小微信码（旧实现在「放得下但需要缩」
        这一档把微信码缩到 two_size，实测最大化 h=800 时只有 114×114）。两码之间留
        `_DONATE_ALIPAY_GAP`，支付宝码在微信码**上方**、同宽同列；非最大化一律不显示。
        两档锚法下微信码都在支付宝码**下方**（顶锚时顺延、底锚时上提），最大化往返会让
        微信码移动一段距离，这是用户钦定的锚法差异，不是漂移（边长始终 180 不变）。

        ## 返回二维码缺口

        第三个值是「还差多少像素才能满 180」（顶锚档还要算上「状态区下限」护栏的让出量
        `status_short`，真实运行为 0；底锚档状态矩形高恒为 `reserve_h`，缩小二维码不牵连
        它，故不含该项）。调用方 `_sync_dock_layout` 用它把导航区整体上移来补（见那里的
        两遍布局），故本函数保持纯计算、不自行挪导航——挪多少是布局策略问题。缺口只由
        固定量算出，故「上移多少」对同一窗口高度是常量：读取前与读取后完全一致。
        """
        ui = self.Ui
        status = ui.label_show_version
        qr = getattr(ui, "label_donate_qr", None)
        link = getattr(ui, "label_donate_link", None)
        alipay = getattr(ui, "label_donate_alipay", None)
        if qr is None or link is None or alipay is None:
            # 收款码控件还没建好（_init_donate_widgets 未跑）：无从谈缺口，返回 0 表示
            # 「不欠尺寸」，调用方据此不会去上移导航。**必须返回三元组**——签名是三元，
            # 少一个会让 _sync_dock_layout 的解包直接 ValueError。
            return status_y, status_h, 0
        side_w = ui.widget_setting.width()
        status_bottom = status_y + status_h  # 窗底（分支①②里都等于 self.height()）
        reserve_h = self._dock_status_text_reserve_h()  # 固定 5 行的真实高度
        # 「[赞助作者] → 状态文字」间距：不得小于「状态区压缩下限」反推出来的值，否则
        # 预留带顶到状态区顶之上会把左下角文字裁掉（军规③）。
        gap = max(
            self._DONATE_TEXT_GAP,
            self._DOCK_STATUS_H_MIN + self._DONATE_PAD - reserve_h,
        )
        # 「状态区下限」护栏的让出量：只在**顶锚**档参与——那一档的状态矩形高是
        # `one_size + reserve_h − qr_size`（缩小多少就把状态区压矮多少），极端小字号下
        # 预留带撑不到 `_DOCK_STATUS_H_MIN` 时必须再让出这段，否则状态区会比文字还矮、
        # 末行被窗底裁，正是议题 #181 的原始回归。真实运行（100% 字号）`reserve_h` = 85
        # > 72，这道护栏恒不生效（`status_h ≡ reserve_h`）。
        status_short = max(0, self._DOCK_STATUS_H_MIN - reserve_h)
        # 锚法：最大化 → 底锚（第十六轮，与 MDCx-20261007 一致）；其余 → 顶锚（第十五轮）。
        bottom_anchor = self._donate_bottom_anchor()
        # 注意：下面两条分支都用 `donate_y` 这个**局部**量推导位置，直到确认要显示才写回
        # `status_y`。否则隐藏分支会返回「新的 y + 调用方给的旧 h」这种拼接值，把状态矩形
        # 整体上移 `_DONATE_BOTTOM_SLACK + reserve_h`（实测 520 高时底边从 520 缩到 507，
        # 数字浮标也跟着上移）。
        if bottom_anchor:
            # ── 底锚：自窗底往上摆 ────────────────────────────────────────────────
            # 文字带底边离窗底留 `_DONATE_BOTTOM_SLACK`（旧版 _DOCK_STATUS_BOTTOM_PAD 的
            # 值，见该常量注释），于是文字带顶只由 status_bottom 与固定量决定。
            donate_y = status_bottom - self._DONATE_BOTTOM_SLACK - reserve_h
            link_bottom = donate_y - gap
            link_top = link_bottom - self._DONATE_LINK_H
            qr_bottom = link_top - self._DONATE_LINK_GAP
            # 微信码顶不得低于 nav_bottom + PAD ⇒ 码下沿固定、可用量即这条净高。
            # 底锚档状态矩形恒为 reserve_h，缩二维码不牵连它，故 `status_short` 不参与。
            avail = qr_bottom - self._DONATE_PAD - nav_bottom
            qr_size = min(self._DONATE_QR_SIZE, avail)
            qr_deficit = max(0, self._DONATE_QR_SIZE - avail)  # 交给调用方上移导航补
        else:
            # ── 顶锚：自导航底往下摆 ────────────────────────────────────────────────
            # 块顶：顶锚导航底，再留 _DONATE_TOP_GAP 的顶间距（能有多高就多高，见 docstring）。
            group_top = nav_bottom + self._DONATE_TOP_GAP
            # 二维码之外的全部固定占用（码下 → 窗底）：链接间距 + 链接高 + 间距 + 预留带。
            fixed_below = self._DONATE_LINK_GAP + self._DONATE_LINK_H + gap + reserve_h
            # 微信码可用高度 = 窗底 − 块顶 − 固定占用；只由固定量算出，与文字行数无关。
            one_size = status_bottom - group_top - fixed_below
            avail = one_size - status_short
            qr_size = min(self._DONATE_QR_SIZE, avail)
            # 缺口含 `status_short`：上移 1px 只让边长长 1px，故要让边长补满 180 就得多
            # 上移这么多；漏掉它会让上移上来的像素被护栏吃掉、边长卡在平台期（实测 176）。
            qr_deficit = max(0, self._DONATE_QR_SIZE - avail)
        # 边长规则（两档同）：可用高度够就**恒为 _DONATE_QR_SIZE**（绝不放大、也绝不因
        # 窗口拉高而变大），不够才按可用高度等比缩小。
        # 缩小到 _DONATE_QR_MIN 以下已无法辨识（甚至可能为负），整块隐藏（军规③：
        # 宁可不显示也不糊码/不叠字）。这里返回缺口而不是直接收工：调用方还有第二遍
        # 布局（上移导航后重排），那一遍若补齐了空间就按 180 显示；补不齐则本分支再次隐藏。
        # 此时返回**调用方原样传入**的 (status_y, status_h)：块藏起来后状态矩形回到设计
        # 贴底带、恢复底对齐（见 `_hide_donate` 处的对齐切换），不该留半截新几何。
        if qr_size < self._DONATE_QR_MIN:
            self._hide_donate()
            status.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
            return status_y, status_h, qr_deficit
        # 支付宝码在微信码**上方**、同宽同列，且**只在最大化时**出现（用户钦定）。
        # 要两张都是完整 _DONATE_QR_SIZE，块内净高得够放 2×QR_SIZE + ALIPAY_GAP（判据成立
        # 时 avail ≥ 382，故 qr_size 必然已经是 180，两码不会一边满一边缩）。
        # 宁可少一张码，也不让「微信码已缩小」把支付宝码也带出来（旧实现在「放得下但需要
        # 缩」这一档把两张一起缩到 two_size，实测最大化 h=800 时只有 114×114）。
        show_alipay = bottom_anchor and (avail - self._DONATE_ALIPAY_GAP) >= 2 * self._DONATE_QR_SIZE
        if bottom_anchor:
            # 微信码下沿固定在 qr_bottom，支付宝码在其**上方** ALIPAY_GAP 处
            qr_top = qr_bottom - qr_size
            alipay_top = qr_top - qr_size - self._DONATE_ALIPAY_GAP if show_alipay else None
            donate_h = reserve_h
        else:
            alipay_top = None
            qr_top = group_top
            link_top = qr_top + qr_size + self._DONATE_LINK_GAP
            link_bottom = link_top + self._DONATE_LINK_H
            # 顶锚档的状态矩形顶 = 链接底 + gap（与底锚档 `link_bottom = donate_y - gap`
            # 对称；调用方注释亦记为 `status_y = link_bottom + gap`）。漏掉这 6px，
            # 状态矩形就会向上吞掉预留给 gap 的空间：预算里为 gap 留了高度，
            # 实际却以 0 间距贴住链接，`_DONATE_TEXT_GAP` 在顶锚路径形同虚设。
            donate_y = link_bottom + gap
            donate_h = max(0, status_bottom - donate_y)
        status_y, status_h = donate_y, donate_h
        # 状态文字**顶对齐**在自己的预留带里。这一步是「不移动」的关键：底对齐时每多一行
        # 文字整个块就上移一行（用户第十三轮的回归）；顶对齐后新增的行往**下**长进预留带的
        # 富余里，首行原地不动。底锚档矩形就是预留带那一段（高恒为 reserve_h）。
        # 文字实际比预留还高（单文件模式 + 软链接 + 进度行可达 7 行）会撑出预留带、被窗底
        # 裁掉——此时宁可不显示收款码也不裁字（军规③）。
        # 注意它**只影响显隐、不影响位置**：行数变化绝不移动任何控件。
        # 顶锚档的护栏保证了 `status_h >= min(reserve_h, _DOCK_STATUS_H_MIN)`，故这条判据
        # 实际只看「几行字 vs 预留几行」，与窗口高度无关。
        if self._dock_status_text_real_h() > status_h + 20:
            self._hide_donate()
            status.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
            return status_y, status_h, qr_deficit
        status.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        qr_x = (side_w - qr_size) // 2
        qr.setFixedSize(qr_size, qr_size)
        qr.move(qr_x, qr_top)
        if alipay_top is not None:
            # 支付宝码与微信码同宽同列，排在微信码上方 _DONATE_ALIPAY_GAP（一行汉字高）处
            alipay.setFixedSize(qr_size, qr_size)
            alipay.move(qr_x, alipay_top)
            if self._donate_alipay_cache_size != qr_size:
                source = QPixmap(resources.donate_alipay_icon)
                if source.isNull():
                    self._donate_alipay_cache = QPixmap()
                    self._donate_alipay_cache_size = qr_size
                    alipay.setText("二维码\n加载失败")
                else:
                    self._donate_alipay_cache = source.scaled(
                        qr_size,
                        qr_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    self._donate_alipay_cache_size = qr_size
                    alipay.setText("")
            if not self._donate_alipay_cache.isNull():
                alipay.setPixmap(self._donate_alipay_cache)
            alipay.setVisible(True)
        else:
            alipay.setVisible(False)
        link.setGeometry(0, link_top, side_w, self._DONATE_LINK_H)
        # 源图 900×900，缩放结果按边长缓存，避免拖动窗口时反复解码
        if self._donate_qr_cache_size != qr_size:
            source = QPixmap(resources.donate_wechat_icon)
            if source.isNull():
                self._donate_qr_cache_size = qr_size
                self._donate_qr_cache = QPixmap()
                qr.setText("二维码\n加载失败")
                qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                self._donate_qr_cache = source.scaled(
                    qr_size,
                    qr_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._donate_qr_cache_size = qr_size
                qr.setText("")
                qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if not self._donate_qr_cache.isNull():
            qr.setPixmap(self._donate_qr_cache)
        qr.setVisible(True)
        link.setVisible(True)
        return status_y, status_h, qr_deficit

    # endregion 侧栏收款码

    def _dock_nav_buttons(self) -> list[QPushButton]:
        """当前可见的导航按钮（配置可隐藏「演员管理/信息管理」两项）。"""
        ui = self.Ui
        return [b for b in (getattr(ui, name) for name in self._DOCK_NAV_BTNS) if not b.isHidden()]

    def _dock_nav_top_base(self) -> int:
        """导航区顶边的**设计基线**（50 隐藏标题栏 / 20 显示标题栏）。

        与 `_windows_auto_adjust` 里的 `widget_buttons.move(0, 50|20)` 取同一判据
        （`manager.config.window_title == "hide"`），但**不读 `ui.widget_buttons.y()`**：
        `_layout_dock_nav` 结尾会用 `setGeometry(0, top, …)` 把 top 写回去，若基线
        读自身则「上移导航」的结果会变成下次的基线，被逐次抬到窗顶。这里返回常量，
        「上移多少」完全由 `_sync_dock_layout` 的缺口计算决定，两边不互相污染。
        """
        try:
            hidden = manager.config.window_title == "hide"
        except Exception:  # 配置未就绪（启动早期）：按显示标题栏的保守值
            hidden = False
        return self._DOCK_NAV_TOP_HIDE if hidden else self._DOCK_NAV_TOP_SHOW

    def _layout_dock_nav(self, top: int, btn_h: int, spacing: int, container_h: int) -> None:
        """按给定按钮高/间距重排导航按钮（每个按钮 min=max=btn_h，布局无自由度，
        故内容高恒为 count*btn_h + (count-1)*spacing，调用方直接用公式值即可）。

        按钮位置由 layoutWidget6 内的 QVBoxLayout 驱动（军规②：改完尺寸/间距必须
        显式 invalidate+activate）。实测（最小脚本 + 离屏探针）：layoutWidget6 自身
        高度不影响按钮落位——富余空间只堆在末尾（间距不被拉伸），且 SetMinimumSize
        约束会用**缓存的** sizeHint 回写父几何，故此处不再 resize 它，只读不用写。
        """
        ui = self.Ui
        for btn in self._dock_nav_buttons():
            btn.setMinimumHeight(btn_h)
            btn.setMaximumHeight(btn_h)
        ui.verticalLayout.setSpacing(spacing)
        ui.verticalLayout.invalidate()
        ui.verticalLayout.activate()
        ui.widget_buttons.setGeometry(0, top, ui.widget_buttons.width(), container_h)

    def _sync_dock_layout(self) -> None:
        """左侧导航坞 + 贴底状态区随窗口高度同步，窗口过矮时压缩而非重叠。

        议题 #86：状态区原本固定设计 y 坐标，窗口拉高后滞留在上半区——改为贴 widget_setting
        底边下移并预留 40px（#102）；min(..., height-h) 上限保证矮窗口下 label 完整可见。
        议题 #181（用户 175% 界面缩放反馈截图）：上述公式只兜"底边不出窗"，没兜"顶边不撞
        导航"——窗口高 < 730 时状态区顶边（height-201）会进入导航区（50..440），
        「正常模式/actor.json/版本号」与「检测网络/使用说明」按钮叠字。
        这里按"设计基准 + 剩余高度"重算（军规③：固定公式、双向幂等，窗口拉高即复原）：
          ① 空间够（height ≥ 导航底 + 间距 + 状态设计高）：完全保持设计几何；
          ② 不够：导航保持设计高，状态区吃掉剩余高度（最小 72）；
          ③ 仍不够：先压导航间距、再压按钮高（各自有下限），状态区仍不足 72 才隐藏；
             极矮窗口（< 约 460）导航按设计尺寸排布、最下方按钮被窗底裁——此时
             叠字比裁切更糟，不再继续压缩。

        两条分支都会调 `_layout_donate`，由它把收款码块（微信码/[赞助作者]/状态文字预留带）
        按窗口状态选锚法并顺带决定 `label_show_version` 的对齐方式与矩形（见该函数）：
        最大化 → **底锚**窗底（第十六轮，与 MDCx-20261007 一致），其余 → **顶锚**导航底
        （第十五轮）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        # 无论走哪条分支都刷新闸门基线：本函数是唯一的「权威重排」入口，走完之后
        # 布局所依据的文字块高就是当前值，下一次文字变化才能被正确识别为「变了」。
        # 放在最前面是因为下面有多处 return，而重排本身很贵、这次测量很便宜。
        self._dock_status_text_h_last = self._dock_status_text_h()
        height = self.height()
        # 导航顶边基线取常量（50/20）而非 ui.widget_buttons.y()：_layout_dock_nav 结尾会
        # setGeometry(0, top, …) 把 top 写回控件，读自身会让「上移导航」的结果变成下次的
        # 基线、被逐次抬到窗顶。判据与 _windows_auto_adjust 的 move(0, 50|20) 保持一致。
        nav_top = self._dock_nav_top_base()
        nav = self._dock_nav_buttons()
        status = ui.label_show_version
        local = ui.label_local_number
        # ① 空间够：设计几何（议题 #86/#102 原公式，逐值不变）
        status_y = min(
            max(height - self._DOCK_STATUS_H - self._DOCK_STATUS_BOTTOM_PAD, self._DOCK_STATUS_Y_MIN),
            height - self._DOCK_STATUS_H,
        )
        if status_y >= nav_top + self._DOCK_NAV_H + self._DOCK_STATUS_GAP:
            # 状态矩形的**原始**几何：两遍布局都从这两个值起算，不复用上一遍的返回值。
            # _layout_donate 会把状态矩形顶**压到 [赞助作者] 下方**（status_y =
            # link_bottom + gap），把它的输出再喂回去等于在已压低的地基上继续压。
            # （本轮起 status_bottom ≡ status_y0 + _DOCK_STATUS_H ≡ 窗底，两遍的
            #   status_bottom 恒等，故这步是等价变换；但显式保留原始值才能让
            #   「两遍从同一起点」成为不变量，而不是靠巧合成立。）
            status_y0, status_h0 = status_y, self._DOCK_STATUS_H
            # 收款码插在导航区与状态区之间；不够就压状态区（顶对齐，文字在预留带里不动）
            status_y, status_h, qr_deficit = self._layout_donate(nav_top + self._DOCK_NAV_H, status_y0, status_h0)
            # 收款码没满 _DONATE_QR_SIZE（唯一成因：窗口偏矮，**与状态文字几行无关**）时，
            # 把导航整体上移来把缺口补上——用户原话「如果下方实在没空间展示…就将…整体向上
            # 移动，上方还有一些空间，二维码图片高度还是要保持180px，软件界面容器上方还有
            # 10px以上的空间」。上移量按缺口**恰好**取 min(缺口, 基线 − _DOCK_NAV_TOP_MIN)：
            #   · 恰好取缺口 ⇒ one_size 正好补到 180，不多占位（导航不会无谓上浮）；
            #   · 上限 _DOCK_NAV_TOP_MIN ⇒ 导航顶不越过 10px，第一个按钮不贴窗框圆角；
            #   · 仍不够就按剩余高度**缩小**二维码（用户：「低于 693 时还是将收款码
            #     缩小」），缩到 _DONATE_QR_MIN 以下则由 _layout_donate 整块隐藏。
            # 第十三轮修正：缺口只由固定量算出，故同一窗口高度下「上移多少」是常量，
            # 读取/刮削前后导航与收款码的落位一字不差（不再随进度行数漂移）。
            # 第十五轮补充：赞助块顶锚导航底，故这段上移同时也把整块（二维码+[赞助作者]+
            # 状态文字）一起抬高，缺口补满即三者的落位全部落在最高允许处。
            # 第十六轮：最大化改底锚后，这段上移只影响**支付宝码能否也放满 180** 与
            # 微信码上沿离导航区的余量，块的主体（微信码下沿/链接/状态文字）仍由
            # 「status_bottom − 固定量」决定，故最大化往返不会因上移量变化而抖动。
            if qr_deficit > 0:
                raise_by = min(qr_deficit, nav_top - self._DOCK_NAV_TOP_MIN)
                if raise_by > 0:
                    nav_top -= raise_by
                    self._layout_dock_nav(nav_top, self._DOCK_NAV_BTN_H, self._DOCK_NAV_SPACING, self._DOCK_NAV_H)
                    status_y, status_h, qr_deficit = self._layout_donate(
                        nav_top + self._DOCK_NAV_H, status_y0, status_h0
                    )
            self._layout_dock_nav(nav_top, self._DOCK_NAV_BTN_H, self._DOCK_NAV_SPACING, self._DOCK_NAV_H)
            status.setGeometry(0, status_y, status.width(), status_h)
            status.setVisible(True)
            local.setVisible(True)
            local.move(
                0,
                min(
                    max(height - self._DOCK_LOCAL_H - self._DOCK_STATUS_BOTTOM_PAD, self._DOCK_LOCAL_Y_MIN),
                    height - self._DOCK_LOCAL_H,
                ),
            )
            return
        # ② 窗口过矮：导航按设计高/间距排布，状态区吃剩余高度
        avail = height - nav_top
        btn_h, spacing = self._DOCK_NAV_BTN_H, self._DOCK_NAV_SPACING
        count = len(nav)
        content_h = count * btn_h + max(count - 1, 0) * spacing
        status_h = min(self._DOCK_STATUS_H, max(0, avail - content_h - self._DOCK_STATUS_GAP))
        if status_h < self._DOCK_STATUS_H_MIN and count:
            # ③ 状态区放不下 72：先压间距、再压按钮高，腾出状态区所需高度
            need = max(avail - self._DOCK_STATUS_H_MIN - self._DOCK_STATUS_GAP, 0)
            if count > 1 and count * btn_h + (count - 1) * spacing > need:
                spacing = max(self._DOCK_NAV_SPACING_MIN, min(spacing, (need - count * btn_h) // (count - 1)))
            if count * btn_h + (count - 1) * spacing > need:
                btn_h = max(self._DOCK_NAV_BTN_H_MIN, min(btn_h, (need - (count - 1) * spacing) // count))
            content_h = count * btn_h + (count - 1) * spacing
            status_h = min(self._DOCK_STATUS_H, max(0, avail - content_h - self._DOCK_STATUS_GAP))
        hide_status = status_h < self._DOCK_STATUS_H_MIN
        # 容器高度取 min(内容高, 可用高)：不够时最下方按钮被窗底裁（④，见 docstring）
        self._layout_dock_nav(nav_top, btn_h, spacing, max(min(content_h, avail), 0))
        if hide_status:
            # ④ 极矮窗口：状态区让位，导航独占整列（叠字比裁切更糟）
            status.setVisible(False)
            local.setVisible(False)
            self._hide_donate()
            # 对齐方式跟着显隐走：块藏起来时状态矩形回到 201 高的贴底带，恢复底对齐，
            # 文字重新贴住窗底（块显示时是顶对齐，见 _layout_donate）
            status.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
            return
        status.setVisible(True)
        local.setVisible(True)
        status_y = nav_top + content_h + self._DOCK_STATUS_GAP
        # 这条分支是「窗口确实过矮」（状态区已进压缩阶梯），导航已按下限排布、无上移余量，
        # 故忽略返回的 qr_deficit：此时二维码按剩余高度**缩小**是正确取舍（用户第十三轮
        # 「低于 693 时还是将收款码缩小」），不该再抢导航空间；缩到 _DONATE_QR_MIN
        # 以下则 _layout_donate 已选择**隐藏**整块收款码（军规③：不叠字、不糊码）。
        status_y, status_h, _qr_deficit = self._layout_donate(nav_top + content_h, status_y, status_h)
        status.setGeometry(0, status_y, status.width(), status_h)
        # 数字浮标贴状态区左下角，且不得超出窗底
        local.move(0, min(status_y + status_h - self._DOCK_LOCAL_H, height - self._DOCK_LOCAL_H))

    # 议题 #154：「编辑 NFO」覆盖层内容区字段最小高度（设计值）
    _NFO_EDITOR_TEXT_MIN_H = 150
    _NFO_EDITOR_TAG_MIN_H = 100
    _NFO_COMMA_HINT = "多个以逗号隔开"
    _NFO_OVERLAY_X = 8
    _NFO_OVERLAY_Y = 8
    _NFO_OVERLAY_MARGIN = 12
    _NFO_OVERLAY_BTN_W = 91
    _NFO_OVERLAY_BTN_H = 40
    _NFO_OVERLAY_BTN_GAP = 108
    _NFO_OVERLAY_BAR_H = 50
    _NFO_OVERLAY_TREE_GAP = 8

    def _ensure_nfo_editor_layout(self) -> None:
        """议题 #154/#166：覆盖层内容区改为行式布局，字段随宽度拉伸。

        .ui 里内容区固定 860×1300、19 个字段按绝对坐标摆放。改为 QVBoxLayout
        + 每行 QHBoxLayout；逗号提示改挂到演员/标签字段，不再占独立行。
        仅首次构建。
        """
        ui = self.Ui
        ui.label_370.hide()
        ui.label_379.hide()
        ui.lineEdit_nfo_actor.setPlaceholderText(self._NFO_COMMA_HINT)
        ui.lineEdit_nfo_actor.setToolTip(self._NFO_COMMA_HINT)
        ui.textEdit_nfo_tag.setPlaceholderText(self._NFO_COMMA_HINT)
        ui.textEdit_nfo_tag.setToolTip(self._NFO_COMMA_HINT)
        content = ui.scrollAreaWidgetContents_nfo_editor
        if content.layout() is not None:
            return
        ui.scrollArea_nfo.set_content_bottom_margin(0)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(9, 6, 9, 12)
        outer.setSpacing(6)

        def _label(text_label):
            text_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            text_label.setFixedWidth(82)
            return text_label

        def add_full_row(text_label, field) -> None:
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(_label(text_label))
            row.addWidget(field, 1)
            outer.addLayout(row)

        def add_pair_row(l1, f1, l2, f2) -> None:
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(_label(l1))
            row.addWidget(f1, 1)
            row.addWidget(_label(l2))
            row.addWidget(f2, 1)
            outer.addLayout(row)

        def add_triple_row(l1, f1, l2, f2, l3, f3) -> None:
            row = QHBoxLayout()
            row.setSpacing(10)
            for text_label, field in ((l1, f1), (l2, f2), (l3, f3)):
                row.addWidget(_label(text_label))
                row.addWidget(field, 1)
            outer.addLayout(row)

        add_full_row(ui.label_381, ui.label_nfo)
        add_triple_row(
            ui.label_360,
            ui.lineEdit_nfo_number,
            ui.label_369,
            ui.comboBox_nfo,
            ui.label_380,
            ui.lineEdit_nfo_year,
        )
        add_full_row(ui.label_359, ui.lineEdit_nfo_actor)
        add_full_row(ui.label_361, ui.lineEdit_nfo_title)
        add_full_row(ui.label_372, ui.lineEdit_nfo_originaltitle)
        add_full_row(ui.label_19, ui.textEdit_nfo_outline)
        add_full_row(ui.label_371, ui.textEdit_nfo_originalplot)
        add_full_row(ui.label_362, ui.textEdit_nfo_tag)
        add_pair_row(ui.label_363, ui.lineEdit_nfo_release, ui.label_364, ui.lineEdit_nfo_runtime)
        add_pair_row(ui.label_373, ui.lineEdit_nfo_score, ui.label_374, ui.lineEdit_nfo_wanted)
        add_pair_row(ui.label_366, ui.lineEdit_nfo_director, ui.label_365, ui.lineEdit_nfo_series)
        add_pair_row(ui.label_368, ui.lineEdit_nfo_studio, ui.label_367, ui.lineEdit_nfo_publisher)
        add_full_row(ui.label_375, ui.lineEdit_nfo_poster)
        add_full_row(ui.label_376, ui.lineEdit_nfo_cover)
        add_full_row(ui.label_377, ui.lineEdit_nfo_trailer)
        add_full_row(ui.label_378, ui.lineEdit_nfo_website)
        for box, height in (
            (ui.textEdit_nfo_outline, self._NFO_EDITOR_TEXT_MIN_H),
            (ui.textEdit_nfo_originalplot, self._NFO_EDITOR_TEXT_MIN_H),
            (ui.textEdit_nfo_tag, self._NFO_EDITOR_TAG_MIN_H),
        ):
            box.setMinimumHeight(height)

    def _nfo_overlay_right_edge(self) -> int:
        """覆盖层右缘 = min(缩略图右缘, 结果树左缘 - 间距)，不盖住番号树。"""
        ui = self.Ui
        stacked_x = ui.stackedWidget.x()
        thumb = ui.label_thumb
        tree = ui.treeWidget_number
        thumb_right = stacked_x + thumb.x() + thumb.width()
        tree_left = stacked_x + tree.x()
        return min(thumb_right, tree_left - self._NFO_OVERLAY_TREE_GAP)

    def _sync_nfo_overlay_geometry(self) -> None:
        """议题 #166：覆盖层作为主页伴侣面板，右缘收到缩略图/结果树之间。"""
        ui = self.Ui
        nfo = ui.widget_nfo
        if nfo is None or nfo.isHidden():
            return
        self._ensure_nfo_editor_layout()
        nfo_x, nfo_y, margin = self._NFO_OVERLAY_X, self._NFO_OVERLAY_Y, self._NFO_OVERLAY_MARGIN
        nfo_right = self._nfo_overlay_right_edge()
        nfo_w = max(nfo_right - nfo_x, 280)
        tree_limit = ui.stackedWidget.x() + ui.treeWidget_number.x() - self._NFO_OVERLAY_TREE_GAP
        if nfo_x + nfo_w > tree_limit:
            nfo_w = max(tree_limit - nfo_x, 280)
        max_h = max(self.height() - nfo_y - margin, 300)
        content = ui.scrollAreaWidgetContents_nfo_editor
        lay = content.layout()
        if lay is not None:
            lay.activate()
            content_h = max(lay.sizeHint().height(), 200)
        else:
            content_h = 200
        nfo_h = min(29 + content_h + self._NFO_OVERLAY_BAR_H, max_h)
        nfo.setGeometry(nfo_x, nfo_y, nfo_w, nfo_h)
        btn_w, btn_h, gap, bar_h = (
            self._NFO_OVERLAY_BTN_W,
            self._NFO_OVERLAY_BTN_H,
            self._NFO_OVERLAY_BTN_GAP,
            self._NFO_OVERLAY_BAR_H,
        )
        pair_w = btn_w + gap + btn_w
        save_x = max((nfo_w - pair_w) // 2, 0)
        close_x = save_x + btn_w + gap
        btn_y = max(nfo_h - margin - btn_h, 0)
        ui.pushButton_nfo_close.setGeometry(close_x, btn_y, btn_w, btn_h)
        ui.pushButton_nfo_save.setGeometry(save_x, btn_y, btn_w, btn_h)
        ui.pushButton_nfo_save.raise_()
        ui.pushButton_nfo_close.raise_()
        ui.label_save_tips.setGeometry(margin, max(nfo_h - margin - 24, 0), max(save_x - margin, 60), 20)
        ui.label_4.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        ui.label_4.setGeometry(0, 5, nfo_w, ui.label_4.height())
        scroll = ui.scrollArea_nfo
        if scroll is not None:
            scroll.setGeometry(9, 29, max(nfo_w - 9 - margin, 200), max(nfo_h - 29 - bar_h, 200))

    def _sync_page_layouts(self) -> None:
        """让所有页面的内部组件跟随主窗口尺寸缩放。

        窗口右侧 stackedWidget resizeEvent 同步，但子页面（page_setting里的tabWidget、
        page_tool的自定义区域、page_net的textBrowser），仅需位置在绝对坐标系下按比例还原。
        方法：基于主窗口追加 (210,6) → 用处当前发扬的尺寸作为基准，对元素调用一次 setGeometry。
        每个组件保留最初设计偏移 (X, Y)，仅需对宽 高 按比例缩放。
        """
        ui = self.Ui
        # stackedWidget 可用宽高（扣除侧栏和上下间距）
        avail_w = max(self.width() - 210 - 2, 400)
        avail_h = max(self.height() - self._CONTENT_TOP_OFFSET - self._CONTENT_BOTTOM_MARGIN, 300)

        # 关键前置：QStackedWidget 只 resize 当前可见页，休眠页永远停留在设计尺寸。
        # 必须先把所有页面统一 resize 到 stackedWidget 尺寸，后续基于 page.width()/height()
        # 的计算才有正确基准（否则"先缩放窗口再切页"时全部按设计尺寸 820x692 布局）。
        # Windows 原生边框最大化时，对带 QLayout 页面的 resize 可能因窗口重建事件
        # 时序错过布局更新（议题 #78：信息管理页右侧残留 ~194px 空白、底部控件坠落
        # 视野）——resize 后对每页布局显式 invalidate + activate 强制重排。
        stacked = ui.stackedWidget
        for index in range(stacked.count()):
            page = stacked.widget(index)
            page.resize(avail_w, avail_h)
            layout = page.layout()
            if layout is not None:
                layout.invalidate()
                layout.activate()

        # ============ page_main（软件界面）：横向 + 纵向跟随 ============
        # 设计基准宽 820：宽幅控件拉伸贴右缘、右缘锚定控件保持宽度平移、其余保持原位。
        main_page = ui.page_main
        main_w = main_page.width()
        # 幂等：基于设计基准 820 的 cover_scale（全函数共用，须在统计栏/封面段前计算）
        cover_scale = main_w / 820
        # 宽幅拉伸（设计右缘≈页面右缘）：文件路径标签、分隔线
        ui.label_file_path.resize(max(main_w - 34, 300), ui.label_file_path.height())
        ui.line_14.resize(max(main_w - 49, 300), ui.line_14.height())
        # 右缘锚定（结果树宽随 cover_scale 拉伸贴向缩略图右缘、右缘贴齐页面右 18px；
        # 议题 #173：固定 202 宽在最大化时离缩略图过远，改随窗口拉伸、两态间距一致）
        tree_w = max(int(202 * cover_scale), 202)
        ui.pushButton_start_cap.move(max(main_w - 120 - 20, 20), 13)
        # 统计标签最大化时左对齐到结果树左缘、贴到「成功」列正上方（此前右对齐会停在
        # 树右上角、与「成功」错位）；纵向两态同高、始终贴住顶部分隔线下方，与还原/
        # 最小化一致，避免最大化时整组下沉、与顶部线之间留出空隙
        _maxed = self.isMaximized()
        _tree_x = max(main_w - tree_w - 18, 300)
        ui.label_result.move(_tree_x if _maxed else max(main_w - 211 - 9, 300), 70)
        ui.treeWidget_number.move(_tree_x, 110)
        ui.treeWidget_number.resize(tree_w, max(ui.treeWidget_number.height(), 100))
        # 刷子按钮（清空结果列表）：最大化时钉在结果树左缘右侧固定 _MAIN_TREE_CLEAR_DX，
        # 使它与树内「成功」两字的间距同还原态一致；还原/最小化态沿用贴右缘原位
        # （设计态 main_w=820 时两者同为 760，双向幂等）。
        _brush_x = _tree_x + self._MAIN_TREE_CLEAR_DX if _maxed else max(main_w - 20 - 40, 300)
        ui.pushButton_tree_clear.move(min(_brush_x, max(main_w - ui.pushButton_tree_clear.width(), 0)), 110)
        # 选择目录按钮跟随开始按钮左移，保持 14px 视觉间距（设计 666 与 680 之间）
        ui.pushButton_select_media_folder.move(max(ui.pushButton_start_cap.x() - 101 - 14, 20), 13)

        # 议题 #124/#135：封面/缩略图按窗口宽度横向等比放大（160×220 → ×scale），
        # 下方信息区（简介/标签/日期/导演/制作 + 右列时长/系列/发行 + 分隔线 + 勾选框）
        # 按封面框的增高量整体**下移**，保持与「番号/标题/封面」同一左列（x 不变），
        # 从而不会被放大的黑框盖住。#135 修正：此前误将信息区整组**右移**到缩略图
        # 右侧，导致最小化时字段被推到窗口右半、与番号/标题/封面不对齐。
        ui.label_poster.setGeometry(int(80 * cover_scale), 160, int(156 * cover_scale), int(220 * cover_scale))
        ui.label_thumb.setGeometry(int(252 * cover_scale), 160, int(328 * cover_scale), int(220 * cover_scale))
        # 议题 #144: 框放大后原图按新框尺寸重渲染(窗口缩放与图片显示同步)
        self._rescale_preview_pixmaps()
        cover_bottom = int(160 + 220 * cover_scale)
        # 信息区下移量 = 封面框增高量；再夹到页面可用高度内，避免宽而矮的窗口把末行裁掉
        info_delta = min(cover_bottom - 380, max(main_page.height() - 700, 0))
        # 议题 #154（撤销 #152 的行高增长）：简介/标签恒定 40px、最多两行，超出的文本
        # 按当前宽度做两行省略（宽度越大每行容纳越多，最大化自然比最小化显示更多）；
        # 下方各行只随封面增高 info_delta 下移，不再被行高增量推出页底。
        info_grow = info_delta  # 简介/标签以下各行的总下移量
        ui.label_poster_size.setGeometry(
            int(80 * cover_scale), cover_bottom, int(411 * cover_scale), int(40 * cover_scale)
        )
        ui.label_thumb_size.setGeometry(
            int(222 * cover_scale), cover_bottom, int(201 * cover_scale), int(40 * cover_scale)
        )
        thumb_right = int(580 * cover_scale)
        # 编辑 NFO/打开文件夹/播放/右键菜单四个按钮：右缘恒与缩略图框右边界严格上下
        # 对齐（组内相对位置与间距不变，组宽 160 = 4×40），最大化/还原两态同一条规则，
        # 缩略图框自身位置不动。对齐基准取缩略图实际右缘（x+w）而非 int(580*scale)，
        # 避免两处 int() 分开取整出现 1px 偏差。
        # 极窄窗（缩略图右缘退到设计右缘 587 左侧）时夹回设计位：只右移不左移。
        _align_right = max(ui.label_thumb.x() + ui.label_thumb.width(), self._MAIN_ACTION_ROW_RIGHT)
        _rx = _align_right - ui.pushButton_right_menu.width()
        _px = _rx - ui.pushButton_play.width()
        _fx = _px - ui.pushButton_open_folder.width()
        _nx = _fx - ui.pushButton_open_nfo.width()
        ui.pushButton_right_menu.move(_rx, 110)
        ui.pushButton_play.move(_px, 110)
        ui.pushButton_open_folder.move(_fx, 110)
        ui.pushButton_open_nfo.move(_nx, 110)
        # 显示封面勾选框右缘同样对齐到缩略图右边界：最大化走对齐，还原/最小化沿用设计坐标 490
        if _maxed:
            ui.checkBox_cover.move(_align_right - ui.checkBox_cover.width(), cover_bottom)
        else:
            ui.checkBox_cover.move(490, cover_bottom)
        # 信息区各控件：左列标签锚定设计 x=30（与「番号/标题/封面」对齐），y 统一下移
        # info_delta；下划线/值列按 cover_scale 等比例加长（议题 #141）：
        #   · 简介/标签（设计 x=70、宽 500）与右列时长/系列/发行（设计 x=350）的下划线
        #     右缘延伸到「缩略图框右缘」thumb_right = 580×scale；
        #   · 左列窄字段（日期/导演/制作，设计宽 220）宽度按 ×scale 加长；
        #   · 右列整体按 ×scale 右移，避免与加长后的左列窄字段重叠。
        # 左列标签（x 固定，保持与番号/标题/封面竖向对齐）
        # 简介/标签两行标签与其值行同顶（#154 行高恒定），其余行用 info_grow
        ui.label_18.move(30, 430 + info_delta)
        ui.label_33.move(30, 480 + info_delta)
        for name, y in (
            ("label_13", 530),
            ("label_23", 580),
            ("label_30", 630),
        ):
            getattr(ui, name).move(30, y + info_grow)
        # 简介/标签：左缘 x=70，右缘延伸到缩略图右缘；行高恒定 40px、最多两行（#154），
        # 下划线贴行底(设计偏移 30)，简介之下的各行只随 info_delta 下移
        wide_w = max(thumb_right - 70, 60)
        ui.label_outline.setGeometry(70, 430 + info_delta, wide_w, 40)
        ui.line_6.setGeometry(70, 460 + info_delta, wide_w, ui.line_6.height())
        ui.label_tag.setGeometry(70, 480 + info_delta, wide_w, 40)
        ui.line_7.setGeometry(70, 510 + info_delta, wide_w, ui.line_7.height())
        # 宽度变化后按新宽度重算简介/标签的两行省略文本（#154：最大化显示更多内容）
        self._refresh_main_outline_tag()
        # 左列窄字段（日期/导演/制作）：宽度按 ×scale 等比例加长
        narrow_w = max(int(220 * cover_scale), 60)
        for name, y in (
            ("label_release", 530),
            ("label_director", 580),
            ("label_studio", 630),
            ("line_8", 560),
            ("line_12", 610),
            ("line_13", 660),
        ):
            getattr(ui, name).setGeometry(70, y + info_grow, narrow_w, getattr(ui, name).height())
        # 右列（标签 x=310、值 x=350，按 ×scale 右移）：下划线右缘延伸到缩略图右缘
        right_label_x = int(310 * cover_scale)
        right_value_x = int(350 * cover_scale)
        right_line_w = max(thumb_right - right_value_x, 60)
        for name, y in (
            ("label_31", 580),
            ("label_22", 530),
            ("label_24", 630),
        ):
            getattr(ui, name).move(right_label_x, y + info_grow)
        for name, y in (
            ("label_series", 580),
            ("label_runtime", 530),
            ("label_publish", 630),
            ("line_9", 560),
            ("line_10", 610),
            ("line_11", 660),
        ):
            getattr(ui, name).setGeometry(right_value_x, y + info_grow, right_line_w, getattr(ui, name).height())
        # 上区行（y70 番号/演员、y110 标题）右界受同右行按钮限制（label_source 460 /
        # pushButton_open_nfo 427）：右界 = min(对应限制, 结果树左缘-30)
        top_right = max(min(450, ui.treeWidget_number.x() - 30), 420)
        title_right = max(min(417, ui.treeWidget_number.x() - 30), 390)
        ui.label_number.resize(max(top_right - 80, 161), ui.label_number.height())
        ui.label_actor.resize(max(top_right - 300, 161), ui.label_actor.height())
        ui.label_title.resize(max(title_right - 80, 341), ui.label_title.height())

        # ============ page_setting: tabWidget + 内部12个 scrollArea ============
        # tabWidget 设计参考几何(20,10,800,682) → scrollArea(0,0,796,658)
        # 保持 tabWidget 固定 X/Y=20,10，宽高跟随主窗口
        tab_w = max(avail_w - 40, 200)
        tab_h = max(avail_h - 20, 150)
        scroll_w = max(tab_w - 4, 396)
        scroll_h = max(tab_h - 24, 326)  # tab栏约占24px + 4px 边框
        ui.tabWidget.setGeometry(20, 10, tab_w, tab_h)

        # Qt 绝对定位布局中：先让所有 tab 的 tab_page 自身 resize 到正确尺寸，
        # 这样 scrollArea 才会感知到变化；然后对每个 scrollArea 显式设置几何。
        # 否则 scrollArea 保留设计器固定尺寸（如 796x658），不跟随变化。
        # 高级页（tab5）/ 演员页（tab_5）滚动区要留给 _sync_advanced_page_align /
        # _sync_actor_page_align 做宽幅同步 + 量基准，休眠页由切 tab 的 showEvent 补齐。
        adv_scroll = None
        actor_scroll = None
        guaxiaomulu_scroll = None
        zimu_scroll = None
        xiazai_scroll = None
        for index in range(ui.tabWidget.count()):
            tab_page = ui.tabWidget.widget(index)
            # 关键：tab_page 必须先获得新尺寸，scrollArea 才能跟随同步
            tab_page.resize(tab_w, tab_h)
            scroll_area = tab_page.findChild(CustomScrollArea)
            if scroll_area is not None and scroll_area.parentWidget() == tab_page:
                scroll_area.setGeometry(0, 0, scroll_w, scroll_h)
                if tab_page.objectName() == "tab5":
                    adv_scroll = scroll_area
                elif tab_page.objectName() == "tab_5":
                    actor_scroll = scroll_area
                content = scroll_area.widget()
                if content is not None and content.objectName() == "scrollAreaWidgetContents_guaxiaomulu":
                    guaxiaomulu_scroll = scroll_area
                elif content is not None and content.objectName() == "scrollAreaWidgetContents_zimu":
                    zimu_scroll = scroll_area
                elif content is not None and content.objectName() == "scrollAreaWidgetContents_xiazai":
                    xiazai_scroll = scroll_area

        # ---- page_setting 底部配置操作浮框（当前配置/另存为/恢复默认/保存）----
        # 设计基准 y620-692 贴页底（page_setting 高 692）。窗口放大后浮框停在设计
        # 高度、视觉悬空——整组按 (设计页高 692 - 设计 y) 的下缘边距锚定新底部，
        # 保存按钮（设计右缘 731/页宽 820）同步右缘锚定，背景 label 拉伸贴宽。
        setting_page = ui.page_setting
        sp_h = setting_page.height()
        sp_w = setting_page.width()
        bottom = max(sp_h - (692 - 630), 100)  # 控件组设计基线 y=630
        ui.label_config.setGeometry(0, max(sp_h - (692 - 620), 90), max(sp_w - 21, 400), 72)
        ui.comboBox_change_config.move(100, max(bottom + 5, 105))
        ui.pushButton_save_config.move(max(sp_w - 241 - 89, 500), bottom)
        # 另存为/恢复默认向右移动，使三段间距相等：
        # 当前配置右→另存为左 = 另存为右→恢复默认左 = 恢复默认右→保存左
        _cb_r = ui.comboBox_change_config.x() + ui.comboBox_change_config.width()
        _save_l = ui.pushButton_save_config.x()
        _gap = max((_save_l - _cb_r - ui.pushButton_save_new_config.width() - ui.pushButton_init_config.width()) / 3, 0)
        ui.pushButton_save_new_config.move(int(_cb_r + _gap), bottom)
        ui.pushButton_init_config.move(int(_cb_r + _gap * 2 + ui.pushButton_save_new_config.width()), bottom)
        # 「当前配置:」标签（设计 y=629，与基线 630 差 1）随浮框组贴底，
        # 否则最大化后停在设计位置、悬在滚动内容中部（用户截图中的浮框问题）
        ui.label_241.move(20, max(bottom - 1, 100))

        # ============ page_tool: scrollArea_10 ============
        tool_area = ui.page_tool
        scroll_10 = tool_area.findChild(CustomScrollArea)
        if scroll_10 is not None and scroll_10.parentWidget() == tool_area:
            scroll_10.setGeometry(20, 0, max(tool_area.width() - 20 - 20, 400), max(tool_area.height() - 75, 300))
            scroll_10.sync_wide_children_width()
            self._sync_actor_db_tool_layout()
            # 封面补图组三选项行随组框拉宽同步拉开间距（须在 sync_wide_children_width
            # 之后，才能读到拉宽后的组宽）
            self._sync_cover_backfill_option_row()
            # 显示输入框（含 TMDB 下拉）向右拓宽到右侧按钮左侧（须在上面两者
            # 之后，取按钮终态位置；大小态通用，无需 isMaximized 分支）
            self._sync_tool_page_input_fill()
            # ---- page_tool 底部配置操作栏（当前配置/另存为/恢复默认/保存）----
            # 与 page_setting 底部栏同组件同功能：滚动区高度收掉 75px 给页脚留位，
            # 页脚按 (设计页高 692 - 设计 y) 的下缘边距锚定新底部，保存按钮右缘锚定。
            tp_h = tool_area.height()
            tp_w = tool_area.width()
            t_bottom = max(tp_h - (692 - 630), 100)
            ui.label_config_tool.setGeometry(0, max(tp_h - (692 - 620), 90), max(tp_w - 21, 400), 72)
            ui.comboBox_change_config_tool.move(100, max(t_bottom + 5, 105))
            ui.pushButton_save_config_tool.move(max(tp_w - 241 - 89, 500), t_bottom)
            # 与 page_setting 一致：三段间距相等
            _cb_r_t = ui.comboBox_change_config_tool.x() + ui.comboBox_change_config_tool.width()
            _save_l_t = ui.pushButton_save_config_tool.x()
            _gap_t = max(
                (
                    _save_l_t
                    - _cb_r_t
                    - ui.pushButton_save_new_config_tool.width()
                    - ui.pushButton_init_config_tool.width()
                )
                / 3,
                0,
            )
            ui.pushButton_save_new_config_tool.move(int(_cb_r_t + _gap_t), t_bottom)
            ui.pushButton_init_config_tool.move(
                int(_cb_r_t + _gap_t * 2 + ui.pushButton_save_new_config_tool.width()), t_bottom
            )
            ui.label_241_tool.move(20, max(t_bottom - 1, 100))

        # ============ page_net: textBrowser_net_main + 右侧按钮 ============
        # 议题 #67: 文本区从按钮条带下方 (y=60) 开始, 按钮不再悬浮遮挡日志首行
        net_area = ui.page_net
        net_browser = ui.textBrowser_net_main
        if net_browser.parentWidget() == net_area:
            net_browser.setGeometry(30, 60, max(net_area.width() - 30 - 2, 400), max(net_area.height() - 60, 300))
        # 设计基准页面宽 822：check_net 右缘 800(右距20)、net_copy 右缘 670(右距152)、net_retry 右缘 548(右距274)
        ui.pushButton_check_net.move(max(net_area.width() - 142, 20), 13)
        ui.pushButton_net_copy.move(max(net_area.width() - 262, 20), 13)
        ui.pushButton_net_retry.move(max(net_area.width() - 384, 20), 13)

        # ============ page_about: textBrowser_about ============
        about_browser = ui.textBrowser_about
        if about_browser.parentWidget() == ui.page_about:
            about_browser.setGeometry(
                30, 0, max(ui.page_about.width() - 30 - 2, 300), max(ui.page_about.height() - 0, 300)
            )

        # ============ page_log: textBrowser_log_main (上) / textBrowser_log_main_2 (下) / log_main_3(失败列表) ============
        log_page = ui.page_log
        log_w = max(log_page.width() - 28 - 2, 300)
        log_h_total = log_page.height()
        # 下栏（失败日志）隐藏时上栏铺满整页；显示时上下按原比例 (421:271 ≈ 61%:39%) 分高
        lower_browser = ui.textBrowser_log_main_2
        if lower_browser.isHidden():
            upper_h = max(log_h_total, 100)
        else:
            upper_h = max(int(log_h_total * 0.61), 100)
        lower_h = max(log_h_total - upper_h - 1, 100)
        upper_w = max(log_w, 300)
        ui.textBrowser_log_main.setGeometry(28, 0, upper_w, upper_h)
        if not lower_browser.isHidden():
            lower_browser.setGeometry(28, upper_h + 1, upper_w, lower_h)
        # 覆盖性日志视图 (失败列表) 铺满整个日志页
        ui.textBrowser_log_main_3.setGeometry(0, 0, max(log_page.width() - 2, 300), max(log_page.height() - 2, 300))
        # 设计基准页面宽 822/高 692：按钮右缘锚定右侧、底部按钮锚定下缘
        ui.pushButton_start_cap2.move(max(log_page.width() - 142, 20), 13)
        ui.pushButton_clear_logs.move(max(log_page.width() - 42, 20), 61)
        ui.pushButton_view_failed_list.move(max(log_page.width() - 257, 20), 13)
        ui.pushButton_show_hide_logs.move(0, max(log_page.height() - 42, 13))
        ui.pushButton_save_failed_list.move(0, max(log_page.height() - 42, 13))

        # ============ widget_nfo（「编辑 NFO」覆盖层）随主窗口缩放（议题 #152/#154/#166）============
        # 可见时作为主页伴侣面板：左贴导航右缘、右收到缩略图/结果树之间，不盖住番号树。
        self._sync_nfo_overlay_geometry()

        # ============ page_nfo_library: 简介/标签高度自适应（议题 #117）============
        self._sync_nfo_lib_form_fields()

        # 目录显示框与筛选框在布局里均分宽度（.ui horstretch 均为 1），无需运行时同步。
        self._sync_nfo_lib_action_buttons()

        # ============ page_setting / 命名页: 模板预览固定高度 + 说明文字贴合 ============
        self._sync_naming_template_section()

        # ============ page_setting / 命名页: 画质组按内容收紧 HD 行到分辨率行的间距 ============
        # 必须排在通用拉伸之后：网格列宽（从而说明文字折行数、需要的总高度）
        # 取决于拉伸后的终态宽度，-template/翻译两组同理。
        self._sync_definition_group_spacing()
        # 命名页画质行右移对齐：必须排在 _sync_definition_group_spacing 之后——后者每遍
        # activate() frame_layout 并按其 sizeHint 高度重钉 frame 高，排前面量到的 need
        # 才是终态（本间隔高为 0，不影响它的 frame_h 计算）。
        self._sync_naming_definition_align(getattr(ui, "scrollArea_7", None))

        # ============ page_setting / 翻译页: 简介组与演员组按内容收紧间距 ============
        # 必须排在通用拉伸之后：两个网格的列宽（从而提示文字折行数、说明文字需
        # 要的总高度）取决于拉伸后的终态宽度。
        self._sync_fanyi_group_spacing()

        # ============ page_setting / 水印页: 四行左标签冒号左移到「首个水印位置：」冒号 ============
        # 排在通用拉伸之后：gridLayoutWidget_24 的宽由通用宽幅同步铺开，内部列分配由本方法钉死。
        # 窄态内部直接 return，最小化布局逐像素不变。
        self._sync_watermark_colon_align(getattr(ui, "scrollArea_4", None))

        # ============ page_setting / 刮削网站页: 「指定网站」下拉框右缘对齐「锁定类型」 ============
        # 必须排在通用拉伸之后：本方法要量「锁定类型」下拉框在 content 里的实时右缘，
        # 而两个组框的宽度刚被宽幅同步按新视口改写（排前面量到的是上一视口的旧值）。
        self._sync_site_pref_combo_width()

        # ============ page_setting / 刮削网站页: 「刮削不到？看这里！」按钮垂直居中到下拉框 ============
        # 必须排在 _sync_site_pref_combo_width 之后：本方法按下拉框的实时几何重钉
        # 按钮 y，而上一步刚改写下拉框的宽度上限（进而影响所在行高与行位置）。
        self._sync_scrape_note_vertical()

        # ============ page_setting / 刮削网站页: 宽态国产番号说明单行时收回空行 ============
        # 排在通用拉伸之后：本方法量的是该说明的终态宽度与其折行数，只有宽幅同步
        # 按新视口改写完组框/网格列宽后量到的 need 才是终态（否则宽度还是上一视口
        # 的旧值，单行判定会迟一拍）。也不影响 _sync_scrape_note_vertical——它锚的是
        # 另一个组框（groupBox_11）里的「指定网站」下拉框，与本组网格无交集。
        self._sync_site_type_tip_single_line()

        # ============ page_setting / NFO页: 宽幅组落定（先落定再量） ============
        # verify_gb 复验血案：tab 切换时 showEvent 的 wide-sync 跑在级联中途
        # （视口 805），落定到 819 后再无事件触发它，groupBox_81 带着 stale
        # extra 定格（715+9=724），与水印组恒差 14px，且后面六个控制器全在
        # stale 几何上量测。在 NFO 控制器量测之前显式重跑一次 NFO 滚动区的
        # 宽幅同步（同 resizeEvent 顺序：先拉伸后补最小高），保证控制器量的
        # 全是终态几何。休眠页跳过（切页 showEvent + beats 会补齐）。
        if ui.groupBox_81.isVisibleTo(self):
            ui.scrollArea_13.sync_wide_children_width()
            ui.scrollArea_13.sync_content_min_height()

        # ============ page_setting / NFO页: 左标签冒号左移与组标题冒号对齐 ============
        self._sync_nfo_colon_align()

        # ============ page_setting / NFO页: 宽视口下右列左对齐到 thirds ============
        self._sync_nfo_right_column_align()

        # ============ page_setting / NFO页: 宽视口下原标题/简介/原简介左对齐到发行日期列 ============
        self._sync_nfo_title_plot_align()

        # ============ page_setting / NFO页: 窄态下分级信息/时长左对齐到发行日期列 ============
        self._sync_nfo_row_align()

        # ============ page_setting / NFO页: 窄态下末项自定义/想看人数右对齐到上映日期列 ============
        self._sync_nfo_tail_align()

        # ============ page_setting / NFO页: 宽态下合集两项左对齐到片商/发行商列 ============
        self._sync_nfo_set_align()

        # ============ page_setting / NFO页: 窄态下字段说明按钮左移进组框 ============
        self._sync_nfo_field_tips()

        # ============ page_setting / 高级页: 四行第1列对齐到「刮削结束后自动退出软件」 ============
        # 必须排在最后：本控制器要量高级页的实时列宽，而宽幅同步会改写
        # groupBox_12 的列宽，放前面量到的是过期值（同 verify_gb 血案）。
        self._sync_advanced_page_align(adv_scroll)
        # 高级页窄态：「每次间隔」时长框右缘缩到与「间歇刮削」文件数框右缘对齐
        # （还原态单列一条需求，最大化态一个像素都不碰）。必须排在上面这个方法
        # **之后**：它末尾那批 gridLayout_20.activate() 会把两行重新排一遍，提前
        # 量到的是过期几何；且它自带早退分支，不能从里面挂钩子。
        self._sync_advanced_page_rest_interval_align(self._scroll_stretch_extra(self._adv_scroll) > 0)

        # ============ page_setting / 演员页: 两行控件对齐到各自基准线 ============
        # 同样排在通用拉伸之后：本方法先落设计几何再按最大化分支覆盖。
        self._sync_actor_page_align(actor_scroll)
        # 演员信息组三列对齐（行标签冒号 + 三个分隔符行对到 Graphis 三列）。
        # 必须在 _sync_actor_page_align 之后：本方法要量 checkBox_actor_photo_ne_new
        # 的左缘当 A3 锚点，而锚点位置由前者刚定下。
        self._sync_actor_info_columns(actor_scroll)
        # 最大化态 A2 列对齐。排在 ② 之后是**必须的**：② 末尾会 grid.invalidate()
        # + activate() 整个 gridLayout_14，把 _DOCK_RIGHT 的绝对定位项重新钉回
        # 「design_x + extra」的右缘（实测「补全完成后自动补全演员头像」被弹回
        # 1348）；排在 ① 之后是为了 A2 锚点 x 已是终态。
        self._sync_actor_page_wide_a2_align(actor_scroll)
        # 窄态右移对齐（最小化时把三个「仅缺少…/本地头像库」对到锚点列）：必须在
        # _sync_actor_info_columns 之后——它要量后者刚钉好的两个单选的当前 x。
        self._sync_actor_page_narrow_align(actor_scroll)

        # ============ page_setting / 刮削目录页: 文件清理提示左移到按钮下方 ============
        # 排在通用拉伸之后：提示是 _STRETCH，最大化时先被拉宽右偏，本方法同拍拉回；
        # 还原态（extra <= 0）内部直接 return，最小化布局逐像素不变。
        guaxiaomulu_scroll = (
            guaxiaomulu_scroll if guaxiaomulu_scroll is not None else getattr(self, "_guaxiaomulu_scroll", None)
        )
        self._sync_guaxiaomulu_clean_tip_align(guaxiaomulu_scroll)
        # 本页两处横向对齐（软链接行让位 +「刮削时自动清理」按态换列）：必须排在
        # 上面那次宽态重跑之后，否则「刮削时自动清理」会被 _DOCK_RIGHT 钉回右缘。
        self._sync_guaxiaomulu_checkbox_align(guaxiaomulu_scroll)

        # ============ page_setting / 刮削模式页: 复用行第二复选框对齐 STRM 行 ====
        # 覆盖元数据框须与覆盖 STRM 框同 x（上下严格对齐）且永不再动：按实测差值闭环
        # 收敛（sizeHint 在 show 前后会变，初始化公式一次算不准），相等即 no-op；
        # 休眠页内部直接 return，切页同拍收敛。
        self._sync_reuse_meta_gap_align()

        # ============ page_setting / 刮削模式页: Javdb 延时提示上移一行并钉死 =
        # label_26 已移出 grid 独立为 groupBox_53 子件：x 与分离模式描述文本
        # 精确对齐、y 上移一行；grid 内 0-2 行保持不动。休眠页内部 return。
        self._sync_javdb_tip_pos()

        # ============ page_setting / 字幕页: 底部填充收缩 + 两处左对齐 ============
        # 排在通用拉伸之后：必须走统一入口 _sync_zimu_page_align（先收缩后对齐）。
        # 若尾部只调 _sync_zimu_fill_blank，它内部的重跑宽幅同步会把钩子刚对好的
        # 复选框搬回右缘（钩子才是破坏者同款）；矮视口各分支内部直接 return，
        # 最小化布局逐像素不变。
        self._sync_zimu_page_align(zimu_scroll if zimu_scroll is not None else getattr(self, "_zimu_scroll", None))

        # ============ page_setting / 下载页: 「下载」行钉到「保留旧文件」行同位 ============
        # 排在通用拉伸之后：本方法要量「保留旧文件」行各复选框在 content 里的实时
        # x/宽，而两个行容器刚被宽幅同步按新视口改写并重排（排前面量到的是上一视口
        # 的旧值）。休眠页内部 return，由切 tab 的 showEvent + 钩子补齐。
        self._sync_xiazai_row_align(
            xiazai_scroll if xiazai_scroll is not None else getattr(self, "_xiazai_scroll", None)
        )

    def _sync_advanced_page_wide_hook(self) -> None:
        """滚动区宽幅拉伸之后立刻把高级页四行对回基准线（零参，钩子用）。

        见 _sync_advanced_page_align 的说明：通用拉伸先把网格里两项均分的行
        （界面外观行的「暗黑模式」、隐藏入口行的「隐藏NFO库管理」）等分推到右缘，
        本控制器要到下一拍才把它们拉回「刮削结束后自动退出软件」那条竖线。
        那一帧一旦被绘制，用户就会看到「先在右侧、再向左漂移」——最大化方向是
        「隐藏NFO库管理」，还原方向是「暗黑模式」（还原时 layoutWidget5 还留着
        最大化态的加宽宽度，同样先把两项等分往外推）。挂在拉伸之后的钩子上，
        两者就在同一拍内完成，中间态不会被绘制。

        与 _sync_nfo_page_align / _sync_actor_page_align 同源，休眠页同样零成本。
        """
        # 宽幅同步刚在 CustomScrollArea._run_post_wide_sync_hook 里做完，列宽已是
        # 终态，这里不必（也不宜）再递归跑一遍 sync_wide_children_width()。
        self._sync_advanced_page_align(self._adv_scroll, wide_synced=True)

    def _sync_advanced_page_align(self, adv_scroll=None, wide_synced=False) -> None:
        """设置-高级：六行控件对齐到「显示字段来源信息」同一条竖线（最大化态）。

        v2.1.9 之前这页的竖线是「刮削结束后自动退出软件」，本次需求把竖线换成
        用户指定的 `checkBox_show_from_log`（显示字段来源信息），并把竖线本身
        （「刮削结束后自动退出软件」）也纳入要左移的目标——它原来既是基准又是
        目标，基准不能自己动，故拆成「阶段一先搬基准、阶段二再按基准对齐其余
        四行」两步。七项目标（截图红框 1~5，其中第 3 框是两枚「关」）：
        checkBox_auto_exit / checkBox_show_dialog_stop_scrape /
        checkBox_hide_menu_icon / checkBox_dark_mode / checkBox_hide_nfo_nav /
        radioButton_log_off / radioButton_update_off。前五项在本方法内处理，
        后两项（两枚「关」）由 _sync_advanced_page_tail_align 跟随
        checkBox_hide_nfo_nav 自动到位——它量的是 nfo 的实时 x，nfo 换竖线它
        就跟着换，无需改动。

        竖线取法分两态（这是「最小化时页面、布局、控件、提示词等等均保持不变」
        的唯一保证）：最大化取 `checkBox_show_from_log`；还原态仍取
        `checkBox_auto_exit` 的自然位——它在 1030×753 下是 x=412，而新锚点只有
        x=292，若还原态也用新锚点，这五项会从 412 被左移到 292，正好违反需求。
        逐项试过「还原态一律解除钉宽」同样不行：解除后第 8 行「隐藏菜单栏图标」
        会掉到 353、第 9 行「暗黑模式」会掉到 393，与改动前的 412 都不等。

        用户截图（先最大化态、后还原态两轮）：「停止刮削时」「隐藏菜单栏图标
        （Mac）」「暗黑模式」「隐藏 NFO 库管理」四个复选框的左缘都挤在第1列起
        点，要求对齐到第2行「刮削结束后自动退出软件」的正下方严格上下对齐；该
        基准复选框自身位置必须保持不变。最大化态要全对齐、还原态只要求前三个
        （「隐藏NFO库管理」在还原态放不下，用户没要求、也不该裁字）。

        根因（离屏实测 + 用户截图双证，gridLayoutWidget_20 两列 QGridLayout，
        col1 起于 x=97）：QHBoxLayout 把剩余空间在**所有可拉伸项之间等分**
        （弹窗确认行 811/811、界面外观行 272/272、隐藏入口行 539/538/539、
        隐藏图标行 191/104/1321），所以第1列里每一个复选框的绝对 x 都随列宽漂移。
        最大化时 CustomScrollArea.sync_wide_children_width() 把列从 568 拉到
        1628，两项均分的那几行末位被推到 x=914，而 Fixed 前缀行（隐藏图标行）
        仍停在 x=404——同一条竖线上出现三个不同的左缘，等分只认剩余空间总量，
        既不能靠 margin 也不能靠撑宽前导项（等分会推着目标项一起走）。

        做法（量基准 + 钉死前导项，纯函数、双向幂等）：
        阶段一搬基准：checkBox_auto_exit 与 checkBox_auto_start 同在
        horizontalLayout_102 里两均分，故钉死前导项 checkBox_auto_start 为
        `pin_2 = 竖线 - row_x - spacing`，末位即精确落竖线。阶段二量到的
        `anchor = col_x(checkBox_auto_exit)` 在最大化态恒等于
        col_x(checkBox_show_from_log)（实测 1100×800 = 201、1920×1170 = 474），
        在还原态就是自然位，两态共用下面同一份代码。每遍现量现用，不写死像素。
        令 pin = anchor - row_x - spacing，钉死该行前导控件为 pin 宽后剩余空间
        全部归末位项，目标项的绝对 x 恒等于 anchor：
          弹窗确认行  钉「退出软件时」            -> 「停止刮削时」        落 anchor
          隐藏图标行  在 label_42 之后插固定间隔  -> 「隐藏菜单栏图标（Mac）」落 anchor，
                      前两项保持贴 col1 左缘（改用整行左 margin 会把「隐藏Dock图标
                      （Mac）」「保存后重启生效」一起推走，破坏本页左缘节奏）
          界面外观行  把 layoutWidget5 加宽到 2*(anchor-row_x)-spacing（两项均分）
                      -> 「暗黑模式」落 anchor；该容器是 frame 的普通子 QWidget
                      （frame 无 layout），故用 setGeometry 而非 layout 属性
                      竖线前移后该容器会**收窄**（1100×800 由 658 收到 396），
                      下界 lw.sizeHint()=152 与上界 frame.width() 都仍成立
          隐藏入口行  钉「隐藏 Emby 演员管理」    -> 「隐藏 NFO 库管理」落 anchor，
                      并把它自己钉回 sizeHint 宽（QCheckBox 可拉伸，不钉会被余量
                      撑到 658px，左对齐绘制时字形只占 152，与说明标签之间空出
                      394px，见用户截图红框）-> 说明标签紧贴其右 6px（仅最大化）
        前导控件全是左对齐绘制，钉宽/插间隔只改右侧留白，不移动自身字形。
        走 setFixedWidth / QSpacerItem / setGeometry 而非 move()：layout
        重新 activate 会覆盖 move()。任一行余量放不下（窗口太窄、说明标签挤不
        下）就整行解除，保持设计态原样。
        「隐藏入口：」冒号对齐已在 MDCx.ui/.py 静态补齐 RightToLeft + AlignRight，
        与同列标签共用网格列右缘，不需运行时介入。休眠页跳过。
        """
        ui = self.Ui
        host = ui.gridLayoutWidget_20
        if not host.isVisibleTo(self):
            return
        # 同 verify_gb 血案：先显式重跑宽幅同步，保证量到的是终态列宽。
        # 从拉伸之后的钩子进来时列宽已经是终态，wide_synced=True 跳过这次递归。
        if not wide_synced and adv_scroll is not None and adv_scroll.isVisibleTo(self):
            adv_scroll.sync_wide_children_width()
        anchor_box = ui.checkBox_auto_exit
        lead_box = ui.checkBox_show_dialog_exit
        auto_start = ui.checkBox_auto_start
        src_from = ui.checkBox_show_from_log
        src_data = ui.checkBox_show_data_log
        if not (
            anchor_box.isVisibleTo(self)
            and lead_box.isVisibleTo(self)
            and auto_start.isVisibleTo(self)
            and src_from.isVisibleTo(self)
        ):
            return
        # 「该对齐隐藏入口行」的判据同样改成几何量而非 isMaximized()：窗口管理器
        # 最大化时先发尺寸、后发状态标志，那一拍 isMaximized() 还是 False，于是
        # 钉宽被跳过、右缘等分被绘制，等标志到位再重排一次才对齐——用户看到
        # 「隐藏NFO库管理先在右侧、再向左漂移」。还原态拉伸量为负，与原先
        # 「非最大化不钉」的行为一致。
        wide = self._scroll_stretch_extra(self._adv_scroll) > 0
        # 新锚点「显示字段来源信息」在 groupBox_3（调试模式）里、不是 host 的
        # 后代，mapTo(host, ...) 无效（Qt 只在祖先链上定义），须经公共祖先
        # scrollAreaWidgetContents_gaoji 中转再减去 host 的 content 坐标。
        content = ui.scrollAreaWidgetContents_gaoji
        host_x = host.mapTo(content, QPoint(0, 0)).x()

        def col_x(widget) -> int:
            """控件左缘换算到 gridLayoutWidget_20 的局部坐标（跨分支经 content 中转）。"""
            return widget.mapTo(content, QPoint(0, 0)).x() - host_x

        row_x = col_x(lead_box)
        col_w = host.width() - row_x

        # ---- 先摆平调试模式行（本批需求①），它一动下面量到的 data_log 锚点就变 ----
        # 详见 _sync_advanced_page_debug_row：那里的钉宽会改变「显示字段内容信息」
        # 的坐标，而本方法紧接着就要用它当还原态锚点，顺序反了会量到旧值。
        self._sync_advanced_page_debug_row(wide)

        # ---- 阶段一：先把需求①自己的目标「刮削结束后自动退出软件」搬到新竖线上 ----
        # 它与「自动启动后自动开始刮削」同在 horizontalLayout_102 里两均分、x 随
        # 列宽漂移，本方法原先从不触碰该行；要让它左移只能先钉死前导项（钉宽 =
        # 目标列坐标 - row_x - spacing，末位即精确落目标）。竖线取法分两态：
        #   最大化：取需求指定的新锚点 checkBox_show_from_log；
        #   还原态：取「刮削结束后自动退出软件」的自然位（＝本方法进入前的旧基准）。
        # 还原态必须如此——新锚点在 1030×753 下只有 x=292，而旧基准自然位 412，
        # 若沿用新锚点，这五项会从 412 被左移到 292，直接违反「最小化时逐像素不变」。
        # 钉完立刻 activate（改约束不重排）再统一按 col_x(anchor_box) 量竖线：
        # 宽态此时它恰等于新锚点，于是后面四段两种窗宽状态共用同一份代码、天然
        # 幂等、互不依赖，也避免了「还原时先量到上一次宽态钉宽」的一帧错位。
        # 最大化：照旧，钉前导项把「刮削结束后自动退出软件」搬到「显示字段来源信息」
        # 那条竖线（目标即新锚点）。还原态的目标是「隐藏菜单栏图标（Mac）」，而
        # 它的坐标要等下面第 8 行那批 activate 才定下来，故窄态那一半挪到方法末尾
        # （见下方「窄态阶段一」），此处只处理宽态。
        lay_2 = ui.horizontalLayout_102  # 自动启动后自动开始刮削 / 刮削结束后自动退出软件
        if wide:
            target = col_x(src_from)
            pin_2 = target - row_x - lay_2.spacing()
            ok_2 = (
                pin_2 >= auto_start.sizeHint().width()
                and col_w - pin_2 - lay_2.spacing() >= anchor_box.sizeHint().width()
            )
            changed = self._pin_row_lead_width(auto_start, pin_2 if ok_2 else None)
        else:
            # 窄态：先解除上一遍可能残留的宽态钉宽，否则下面量到的是带钉宽的坐标
            changed = self._pin_row_lead_width(auto_start, None)
        if changed:
            lay_2.invalidate()
            lay_2.activate()
            ui.gridLayout_20.invalidate()
            ui.gridLayout_20.activate()
            row_x = col_x(lead_box)
            col_w = host.width() - row_x
        # ok_2 为真时它恰在 target 上，为假时是自然位——两种情形都直接量它即可
        anchor = col_x(anchor_box)
        # 下面三行（弹窗确认行 / 隐藏图标行 / 界面外观行）的竖线分两态取：
        #   最大化：沿用上一批需求，仍是「显示字段来源信息」那条竖线（= 阶段一钉完
        #     后 auto_exit 的坐标，故上面量到的 anchor 在宽态恒等于新锚点）；
        #   还原态：换成「显示字段内容信息」（本批需求②）。实测 1030×753 是 495、
        #     1000×700 是 475，都在那条旧基准（auto_exit 自然位 412~430）的右侧，
        #     所以本批在还原态是**右移**；上一批需求说的「向左」是相对最大化态而言，
        #     两批方向相反但落点一致（都精确对齐到锚点左缘），互不冲突。
        if not wide:
            anchor = col_x(src_data)
        if anchor <= row_x or col_w <= 0:
            return
        lay_a = ui.horizontalLayout_55  # 退出软件时 / 停止刮削时
        lay_b = ui.horizontalLayout_dock  # 隐藏Dock图标 / 保存后重启生效 / 隐藏菜单栏图标
        lay_d = ui.horizontalLayout_nav_hide  # 隐藏Emby演员管理 / 隐藏NFO库管理 / 说明
        # 阶段一已就位（改了就当场 activate），此处重新起算：下面四段共用行末
        # 那批 invalidate+activate
        changed = False

        # ---- 弹窗确认行：钉「退出软件时」，「停止刮削时」即落 anchor（两态生效） ----
        stop_scrape = ui.checkBox_show_dialog_stop_scrape
        pin_a = anchor - row_x - lay_a.spacing()
        ok_a = (
            pin_a >= lead_box.sizeHint().width() and col_w - pin_a - lay_a.spacing() >= stop_scrape.sizeHint().width()
        )
        changed |= self._pin_row_lead_width(lead_box, pin_a if ok_a else None)

        # ---- 隐藏图标行：前两项是 Fixed 文本项，插固定间隔把末项单独推到 anchor ----
        # 用「插在 label_42 之后」的固定间隔，而不是给整行加左 margin：后者会
        # 把「隐藏Dock图标（Mac）」「保存后重启生效」一起推到右边，破坏本页
        # 「每行第一个控件都贴着 col1 左缘」的节奏（实测 col1 左缘 = row_x = 97）。
        # gap_b < 0 说明列太窄、Fixed 前缀已经越过 anchor，QCheckBox/QLabel 的
        # sizeHint 就是不裁字下限，压缩必裁字，所以整行放弃（保持设计态原样）。
        dock_icon = ui.checkBox_hide_dock_icon
        label_42 = ui.label_42
        menu_icon = ui.checkBox_hide_menu_icon
        prefix = dock_icon.sizeHint().width() + label_42.sizeHint().width() + 2 * lay_b.spacing()
        gap_b = anchor - row_x - prefix
        ok_b = gap_b >= 0 and col_w - gap_b - prefix >= menu_icon.sizeHint().width()
        new_gap_b = gap_b if ok_b else 0
        if self._adv_dock_gap != new_gap_b:
            # PyQt6 的 insertSpacing 返回值恒为 None，改插完再 itemAt 取回
            spacer = self._adv_dock_spacer
            if spacer is None or lay_b.indexOf(spacer) != 2:
                lay_b.insertSpacing(2, new_gap_b)
                spacer = lay_b.itemAt(2)
                self._adv_dock_spacer = spacer
            if spacer is not None:
                spacer.changeSize(new_gap_b, 0, QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
                self._adv_dock_gap = new_gap_b
                changed = True

        # ---- 界面外观行：「暗黑模式」落 anchor，两条路子按「容器装不装得下」二选一 ----
        # 路子甲（最大化）：layoutWidget5 加宽到 2*(anchor-row_x)-spacing，行内两项
        #   均分，末位即落 anchor。want_w 恒等于 col_w（anchor = row_x + col_w/2 + 3，
        #   两项均分同式），即最多填满 frame，绝不溢出。
        # 路子乙（还原态，需求②）：anchor 换成了更靠右的「显示字段内容信息」，
        #   2*(anchor-row_x) 实测 644~684，而 frame 只有 523~553，甲路必然越界。
        #   改钉死前导项「隐藏窗口标题栏」为 anchor - lw左缘 - spacing，容器保持
        #   设计宽 _ADV_FRAME_LW_W，末位「暗黑模式」照样精确落 anchor，且容器右缘
        #   与还原态现状完全一致（不新增任何越界/裁字）。
        lw = ui.layoutWidget5
        lay_c = ui.horizontalLayout_62
        lead_c = ui.checkBox_hide_window_title
        dark_c = ui.checkBox_dark_mode
        want_w = 2 * (anchor - row_x) - lay_c.spacing()
        ok_even = want_w <= ui.frame.width() and want_w >= lw.sizeHint().width()
        pin_c = anchor - col_x(lw) - lay_c.spacing()
        ok_pin = (
            pin_c >= lead_c.sizeHint().width() and lw.width() - pin_c - lay_c.spacing() >= dark_c.sizeHint().width()
        )
        new_w = want_w if ok_even else self._ADV_FRAME_LW_W
        pin_w = None if ok_even or not ok_pin else pin_c
        changed |= self._pin_row_lead_width(lead_c, pin_w)
        if lw.width() != new_w:
            lw.setGeometry(lw.x(), lw.y(), new_w, lw.height())
            changed = True

        # ---- 隐藏入口行：钉「隐藏 Emby 演员管理」，「隐藏NFO库管理」落 anchor ----
        # 仅最大化：还原态列宽只有 568，pin_d 之后余量 255 放不下「隐藏NFO库管理
        # + 说明标签」的 412，钉了必然裁字，用户也只要求最大化时对齐。
        # 钉住后还须把 nfo 本身也钉回 sizeHint 宽：QCheckBox 默认 sizePolicy 可拉伸，
        # 最大化时它会独吞余量把说明标签顶到 1323（实测），而复选框是左对齐绘制、
        # 文字只占 152，于是文字与说明标签之间出现 394px 空洞（用户截图红框）。
        # 钉死后余量全归末位的说明标签，它紧贴 nfo 文字右侧 6px。
        actor = ui.checkBox_hide_actor_nav
        nfo = ui.checkBox_hide_nfo_nav
        hint = ui.label_nav_hide_hint
        pin_d = anchor - row_x - lay_d.spacing()
        room = col_w - pin_d - 2 * lay_d.spacing()
        ok_d = wide and pin_d >= actor.sizeHint().width() and room >= (nfo.sizeHint().width() + hint.sizeHint().width())
        changed |= self._pin_row_lead_width(actor, pin_d if ok_d else None)
        changed |= self._pin_row_lead_width(nfo, nfo.sizeHint().width() if ok_d else None)

        if changed:
            for lay in (lay_a, lay_b, lay_d, lay_c):
                lay.invalidate()
                lay.activate()
            ui.gridLayout_20.invalidate()
            ui.gridLayout_20.activate()

        # ---- 保留任务行：「无限次刮削」落到「停止刮削时」同一竖线（两态生效） ----
        # 「停止刮削时」自身位置保持不变，只钉前导项「记住未完成的刮削任务」。
        # 必须排在上面那批 activate 之后：stop 的终态 x 由 lay_a 那批钉宽决定，
        # 提前量到的是等分旧值。row5 与 row6 同处 gridLayout_20 的 col1，
        # 行左缘天然相等，但仍按实测分开起算，避免布局边距假设。
        lay_r = ui.horizontalLayout_89
        remain_task = ui.checkBox_remain_task
        infinite_scrape = ui.checkBox_infinite_scrape
        row5_x = col_x(remain_task)
        want_r = col_x(stop_scrape)
        col_w_r = host.width() - row5_x
        pin_r = want_r - row5_x - lay_r.spacing()
        ok_r = (
            want_r > row5_x
            and pin_r >= remain_task.sizeHint().width()
            and col_w_r - pin_r - lay_r.spacing() >= infinite_scrape.sizeHint().width()
        )
        if self._pin_row_lead_width(remain_task, pin_r if ok_r else None):
            lay_r.invalidate()
            lay_r.activate()
            ui.gridLayout_20.invalidate()
            ui.gridLayout_20.activate()

        # ---- 窄态阶段一（本批需求）：「刮削结束后自动退出软件」右移到「隐藏菜单栏图标」----
        # 必须排在上面那批 activate 之后：窄态下「隐藏菜单栏图标」的左缘是由第 8 行
        # 的 gap_b 决定的，而 gap_b 又由本方法的 anchor 算出——只有这批 activate 跑完
        # 它才是终态坐标（实测 1030×753 为 435），提前量到的是上一遍的旧值。
        # 反过来本方法也不受这一段影响：第 2 行是 (2,1) 那格，与第 8 行不同格，
        # 钉 auto_start 只改它自己的格内几何，不会把第 8 行的坐标再推走。
        # 宽态不需要这一段：那时「隐藏菜单栏图标」与「刮削结束后自动退出软件」
        # 本来就同在「显示字段来源信息」那条竖线上（实测 1100×800 起四档全等），
        # 阶段一已在上方把它对到位。
        if not wide:
            menu_x = col_x(menu_icon)
            pin_m = menu_x - row_x - lay_2.spacing()
            room_m = col_w - pin_m - lay_2.spacing()
            ok_m = pin_m >= auto_start.sizeHint().width() and room_m >= anchor_box.sizeHint().width() and menu_x > row_x
            if self._pin_row_lead_width(auto_start, pin_m if ok_m else None):
                lay_2.invalidate()
                lay_2.activate()
                ui.gridLayout_20.invalidate()
                ui.gridLayout_20.activate()

        # ---- 下半页三处右移对齐：必须排在 gridLayout_20.activate() 之后 ----
        # 需求①的锚点「隐藏NFO库管理」正是上面这批 activate 才定下的最终 x，
        # 提前量到的是它被等分推到右缘的旧值（用户截图红框里那两个「关」就是这么
        # 被钉歪的）。changed 为假时网格几何本就是终态，照量不误。
        self._sync_advanced_page_tail_align()

    def _sync_advanced_page_rest_interval_align(self, wide: bool) -> None:
        """还原态：「每次间隔」时长框右缘缩到与「间歇刮削」文件数框右缘严格对齐。

        本批需求②。同一 grid（`gridLayout_20`）col1 上的两行：
        row3 = `horizontalLayout_109`（间歇刮削：☑连续刮削 + 文件数框 + 「个文件后，
        自动休息」+ 休息时长框 + 「（时:分:秒）」），row4 = `horizontalLayout_104`
        （☑每次间隔 + 间隔时长框 + 长说明标签）。**长的是 hl109**（真实字体下需要
        76+141+117+141+80 + 4×6 = 579，而 hl104 只要 76+141+314 + 2×6 = 543），
        窄态下 hl109 先放不下，Qt 只能压缩行内**唯一还压得动的项**——两枚
        `QLineEdit`（它们 sizePolicy 是 Fixed 可以被压，标签的 minimumSizeHint ==
        sizeHint 故一格不让），于是 `lineEdit_rest_count` 被压窄；hl104 那行却仍有
        余量、`lineEdit_timed_interval` 保持满宽 141px，右缘于是越过上面那枚的
        右缘——正是用户红线标出的那截参差。**锚点行与其余控件一律不动**，只缩
        每次间隔这一枚，钉成「右缘 == 文件数框右缘」：
            want = (anchor 右缘) - (target 左缘)
        缩的是 hl104 的第二项，故只有它右侧的 `label_84` 会左移、行内总宽变小；
        hl104 本来就有余量、不会去挤行外任何东西。

        量目标自然位之前**必须先解除上一遍自己的钉宽并重排**（与
        `_sync_advanced_page_debug_row` 的「自我强化」同坑：带着旧钉宽去量，量到的
        是自己钉出来的落点）。`want` 只有在「确实更窄且仍夹得住内容」时才钉，放不下
        就保持自然态、绝不硬压。最大化态**只做解除**：那一态两枚框本来就都是满宽
        141px，钉不钉一样，故最大化界面逐像素不变。
        """
        ui = self.Ui
        content = ui.scrollAreaWidgetContents_gaoji
        if not content.isVisibleTo(self):
            return
        anchor_row = ui.horizontalLayout_109
        target_row = ui.horizontalLayout_104
        anchor = ui.lineEdit_rest_count
        target = ui.lineEdit_timed_interval
        if not (
            anchor_row is not None
            and target_row is not None
            and anchor_row.parentWidget() is not None
            and target_row.parentWidget() is not None
            and anchor is not None
            and target is not None
            and anchor.isVisibleTo(self)
            and target.isVisibleTo(self)
        ):
            return

        def cx(widget) -> int:
            """控件左缘映射到滚动内容的绝对 x（跨分支必须经 content 中转）。"""
            return widget.mapTo(content, QPoint(0, 0)).x()

        def anchor_right() -> int:
            return cx(anchor) + anchor.width()

        # ---- 最大化态只解除：那一态本来就等宽，钉了也是徒增一次重排 ----
        if wide:
            if self._pin_row_lead_width(target, None):
                target_row.invalidate()
                target_row.activate()
            return

        # ---- 还原态：先解除并重排，量到的是自然位而不是自己上遍钉出来的落点 ----
        if self._pin_row_lead_width(target, None):
            target_row.invalidate()
            target_row.activate()
        anchor_row.invalidate()
        anchor_row.activate()
        want = anchor_right() - cx(target)
        if not (0 < want < target.width() and want >= target.minimumSizeHint().width()):
            return
        if self._pin_row_lead_width(target, want):
            target_row.invalidate()
            target_row.activate()
        # 读回纠偏：重排后可能残留 1px 取整误差，补回去。
        drift = anchor_right() - cx(target) - target.width()
        if drift:
            self._pin_row_lead_width(target, target.width() - drift)
            target_row.invalidate()
            target_row.activate()

    def _sync_advanced_page_debug_row(self, wide: bool) -> None:
        """还原态：调试模式行「显示字段来源信息」右移到与「隐藏NFO库管理」上下对齐。

        本批需求①。这一处在 groupBox_3（调试模式）自己的 horizontalLayout_29 里，
        与 _sync_advanced_page_align 处理的那几行不在同一个 grid，且**必须排在它
        之前**：那边量「显示字段内容信息」当锚点，钉宽一动这一项的坐标就变。

        行内三项（显示刮削过程信息 / 显示字段来源信息 / 显示字段内容信息）
        **等分余量**（实测 1030×753 各 196/197/196、1920×1170 各 493），所以钉住
        任何一项都会把后面几项一起挪动。需求要「显示字段来源信息」右移 21px 落到
        nfo 上，而「显示字段内容信息」**位置保持不变**：只钉前导项「显示刮削过程
        信息」的话，末位会被重新等分推着右移 ~10px（495 → 505），违反需求。故
        **前两项一起钉**：
          钉 web  = nfo_x - 行左缘 - spacing ->「显示字段来源信息」左缘 = nfo_x
          钉 from = data_x - nfo_x - spacing ->「显示字段来源信息」右缘紧贴末位的
                                                原左缘，末位因此原地不动
        末位不设任何钉宽、只吃余量，它的左缘恒等于「行左缘 + 钉web + 间隔 + 钉from
        + 间隔」= data_x，与容器宽无关（容器宽的增减全被末位吸收），故改变窗宽也
        不会让末位漂移；两条钉宽也只由两个锚点决定，反复同步幂等。

        **量 data_x 之前必须先把两段钉宽解除并重排**，否则量到的是上一遍自己钉出
        来的落点、不是自然位：pin_from = data_x - nfo_x - spacing 与 data_x =
        nfo_x + pin_from + spacing 互为反函数，带着旧钉宽迭代会自我强化成一个错值
        （实测会把「显示字段内容信息」从 495 一路拉到 408、钉宽缩到 89px）。
        故这里无条件「解除 → activate → 量 → 钉 → activate」，代价是本行两次重排
        （行内只有 3 项，可忽略），且全程在绘制之前完成、看不到中间态。
        最大化态本方法**只做解除**：那时「显示字段来源信息」与「隐藏NFO库管理」
        本来就同在一条竖线上（实测 1100×800 起四档全部相等），钉不钉都一样。
        """
        ui = self.Ui
        content = ui.scrollAreaWidgetContents_gaoji
        if not content.isVisibleTo(self):
            return
        lay_web = ui.horizontalLayout_29
        lw3 = ui.layoutWidget_3
        web_log = ui.checkBox_show_web_log
        src_from = ui.checkBox_show_from_log
        src_data = ui.checkBox_show_data_log
        nfo = ui.checkBox_hide_nfo_nav
        if not (lay_web is not None and lw3.isVisibleTo(self) and web_log.isVisibleTo(self)):
            return
        if not (src_from.isVisibleTo(self) and src_data.isVisibleTo(self) and nfo.isVisibleTo(self)):
            return

        def cx(widget) -> int:
            """控件左缘映射到滚动内容的绝对 x（跨分支必须经 content 中转）。"""
            return widget.mapTo(content, QPoint(0, 0)).x()

        # ---- 第一步：回到自然态，量末位的自然左缘（见上文「自我强化」那段）----
        self._pin_row_lead_width(web_log, None)
        self._pin_row_lead_width(src_from, None)
        lay_web.invalidate()
        lay_web.activate()
        data_x = cx(src_data)

        # ---- 第二步：按两个锚点算出两条钉宽，放得下才钉，放不下保持自然态 ----
        sp = lay_web.spacing()
        pin_web = cx(nfo) - cx(lw3) - sp
        pin_from = data_x - cx(nfo) - sp
        room = lw3.width() - pin_web - pin_from - 2 * sp
        ok = (
            not wide
            and pin_web >= web_log.sizeHint().width()
            and pin_from >= src_from.sizeHint().width()
            and room >= src_data.sizeHint().width()
        )
        if not ok:
            return
        if self._pin_row_lead_width(web_log, pin_web) | self._pin_row_lead_width(src_from, pin_from):
            lay_web.invalidate()
            lay_web.activate()

    def _sync_advanced_page_tail_align(self) -> None:
        """高级页下半三处对齐（三条需求分属最大化 / 最小化两态），锚点一律不动。

        需求分两批、方向相反，实现上按「落点取哪个锚点」区分：
          最大化态（第一批）：
          ① 「保存日志」「检查更新」两行的「关」右移到与「隐藏NFO库管理」严格
             上下对齐；
          ② 「隐藏窗口」行的「点最小化按钮」右移到与「显示字段来源信息」严格
             上下对齐；
          ③ 同一行最右侧的「无」右移到与「显示字段内容信息」严格上下对齐。
          最小化态（第二批，「最大化时页面、布局、控件、提示词等均保持不变」）：
          ① 同上的两行「关」**向左**移到与「隐藏NFO库管理」严格上下对齐；
          ② 「点最小化按钮」**向左**移到与「隐藏NFO库管理」严格上下对齐
             （注意最小化态的锚点是 nfo 而非 from_log，两态不同）；
          ③ 「无」**向左**移到与「显示字段内容信息」严格上下对齐（与最大化态
             同一锚点，故这一条两态共用同一份代码）。
        锚点自身（「隐藏NFO库管理」「显示字段来源信息」「显示字段内容信息」
        「显示刮削过程信息」）全程不动。

        三处根因不同，手法也不同，勿互相套用：
          ① 两行的容器（horizontalLayoutWidget_11 / _7）是 groupBox_17 / _4 的
             **直接子项**，被通用宽幅同步判成 _STRETCH、每遍按「设计宽+extra」
             拉宽并 invalidate+activate 内部行布局；行内两个单选均分余量（实测
             宽态 742/741），于是「关」的左缘随窗宽漂移。锚点自身也在同一次
             拉伸里被摆好，故只需**钉死前导项「开」**：行内只剩末位「关」可拉伸，
             它的左缘恒等于「容器左缘 + 钉宽 + spacing」，取钉宽 = 锚点x -
             「开」x - spacing 即严格对齐（与 _pin_row_lead_width 同一套）。
          ②③ 「隐藏窗口」行的容器 layoutWidget_17 **完全不参与拉伸**——它是
             frame_3 的子控件、frame_3 又是 gridLayoutWidget_20 的子控件，而
             通用同步只登记「顶层组框的直接子项」，故它四个尺寸下恒为 551x32、
             行内三个单选按 551 均分（实测 180/179/180，宽窄两态一模一样）。
             两个锚点却在另一个组框（groupBox_3）里、随该组一起被拉伸，行内位置
             与锚点位置之间没有任何联动。只能**钉死前两项 + 把容器加宽**：
             设 m/n 为「点最小化按钮」「无」的落点（相对容器左缘），钉
             「点关闭按钮」= m-spacing、钉「点最小化按钮」= n-m-spacing，则
             两者左缘分别恰为 m、n；容器宽须 ≥ n + 「无」sizeHint，否则末位被
             压到裁字（这一条与界面外观行加宽 layoutWidget5 是同款手法）。

        锚点与落点全部运行时 mapTo 实测，不写死像素。宽态实测（竖线换到
        checkBox_show_from_log 之后）：1920 为 nfo=589 / from=589 / data=1088、
        关=589、mini=589、none=1088；1100 最小的一档为 nfo=316 / from=316 /
        data=541、关=316、mini=316、none=541。窄态 1030 实测 nfo=313 /
        from=292 / data=495，关=393（→nfo，钉宽 217）、mini=301（→nfo，
        钉 close=192 / mini=176、容器 411）、none=486（→data，容器收窄）。
        窄态之所以也要做：nfo 在窄态是这半页最靠右的那条竖线（313 > from=292），
        且两枚「关」的窄态自然位 393 恰在它右侧 80px——不钉住就会一直歪着。
        mapTo 一律经公共祖先
        scrollAreaWidgetContents_gaoji 中转：三处目标分属 groupBox_17/_4
        （groupBox_12 的兄弟）与 frame_3（groupBox_12 的孙子），跨分支 mapTo 是
        未定义行为（同 _sync_guaxiaomulu_checkbox_align 的教训）。
        """
        ui = self.Ui
        content = ui.scrollAreaWidgetContents_gaoji
        if not content.isVisibleTo(self):
            return
        # 判态用几何拉伸量而非 isMaximized()：窗口管理器最大化时先发尺寸、后发
        # 状态标志，那一拍 isMaximized() 还是 False，用户会看到「先在原位、再
        # 跳到对齐位」，与本页既有的隐藏NFO库管理/暗黑模式同款理由。
        wide = self._scroll_stretch_extra(self._adv_scroll) > 0
        nfo = ui.checkBox_hide_nfo_nav
        src_from = ui.checkBox_show_from_log
        src_data = ui.checkBox_show_data_log
        if not (nfo.isVisibleTo(self) and src_from.isVisibleTo(self) and src_data.isVisibleTo(self)):
            return

        def cx(widget) -> int:
            """控件左缘映射到滚动内容的绝对 x（跨分支必须经 content 中转）。"""
            return widget.mapTo(content, QPoint(0, 0)).x()

        changed = False
        lays: list = []

        nfo_x = cx(nfo)
        data_x = cx(src_data)

        # ---- 需求②：两个「关」-> 宽态跟「隐藏NFO库管理」，窄态跟「显示字段内容信息」 ----
        # 两态锚点不同，故按态取。宽态 need 与既有实现逐位相同；窄态把落点从上一批
        # 需求的 nfo（1030×753 = 313）换成本批指定的「显示字段内容信息」（实测
        # 1030×753 = 495、1000×700 = 475，是这半页最靠右的那条竖线）。
        off_x = nfo_x if wide else data_x
        for cont, lay, lead, tail in (
            (ui.horizontalLayoutWidget_11, ui.horizontalLayout_13, ui.radioButton_log_on, ui.radioButton_log_off),
            (ui.horizontalLayoutWidget_7, ui.horizontalLayout_9, ui.radioButton_update_on, ui.radioButton_update_off),
        ):
            if not cont.isVisibleTo(self):
                continue
            need = off_x - cx(lead) - lay.spacing()
            room = cont.width() - need - lay.spacing()
            ok = need >= lead.sizeHint().width() and room >= tail.sizeHint().width()
            if self._pin_row_lead_width(lead, need if ok else None):
                changed = True
                lays.append(lay)

        # ---- ②③ 「点最小化按钮」/「无」；落点按态取，判据仍要防「放不下」 ----
        lw = ui.layoutWidget_17
        lay_h = ui.horizontalLayout_106
        frame3 = ui.frame_3
        close_r = ui.radioButton_hide_close
        mini_r = ui.radioButton_hide_mini
        none_r = ui.radioButton_hide_none
        if lw.isVisibleTo(self) and frame3.isVisibleTo(self):
            base = cx(lw)
            sp = lay_h.spacing()
            # 「点最小化按钮」：宽态对齐「显示字段来源信息」，窄态对齐「隐藏NFO库
            # 管理」。两者在窄态分处 292 / 313，取错会让它在还原后停在 292 而非
            # 313（这正是需求②与需求①在窄态要求落到同一条竖线上的用意）。
            m = (cx(src_from) if wide else nfo_x) - base
            # 「无」：两态同一锚点「显示字段内容信息」。
            n = cx(src_data) - base
            w_close = m - sp
            w_mini = n - m - sp
            # 容器宽度只需「恰好放下「无」」，两个下界语义不同、勿混：
            #   下界取 lw.sizeHint()（168 = 三个单选 hint 之和 + 两个间隔），
            #     低于它末位必被压、裁字；
            #   上界取 frame3.width()，超出即越出 frame_3（frame 无布局，
            #     越界子控件会被父控件绘制区裁掉）。
            # 刻意**不**拿设计宽 551 当下界：n 随 extra 增长，extra 刚转正时
            # want_w 只有 400 出头（1100 宽实测 457 < 551），拿 551 卡门会让
            # 「刚过最大化线的那一大段窗宽」全部对不上（实测 1100x800 漏排）。
            # 宽态下把容器收窄到 457 不裁字：三项已各自钉到 ≥ sizeHint 的宽度。
            # 窄态容器同样会收窄（551 → 411），这一条是需求③要的「向左移动」。
            want_w = n + none_r.sizeHint().width()
            ok_h = (
                m > sp
                and n > m
                and w_close >= close_r.sizeHint().width()
                and w_mini >= mini_r.sizeHint().width()
                and lw.sizeHint().width() <= want_w <= frame3.width()
            )
            if ok_h:
                if self._pin_row_lead_width(close_r, w_close) | self._pin_row_lead_width(mini_r, w_mini):
                    changed = True
                if lw.width() != want_w:
                    lw.setGeometry(lw.x(), lw.y(), want_w, lw.height())
                    changed = True
                if lay_h not in lays:
                    lays.append(lay_h)
            else:
                # 真放不下（钉宽会裁字或越出 frame_3）：逐项解除并按设计宽复位。
                # 窄态实测 w_close/w_mini 均 ≥ sizeHint、want_w=411 落在
                # [168, 588] 内，故窄态不走这条分支。
                if self._pin_row_lead_width(close_r, None) | self._pin_row_lead_width(mini_r, None):
                    changed = True
                if lw.width() != self._ADV_HIDE_LW_W:
                    lw.setGeometry(lw.x(), lw.y(), self._ADV_HIDE_LW_W, lw.height())
                    changed = True
                if lay_h not in lays:
                    lays.append(lay_h)

        if not changed:
            return
        # 钉宽只改约束、不会立刻重排：必须显式 activate，否则要等下一轮事件，
        # 而那之前 resizeEvent 已经画完（用户看到「先在原位、再跳过去」）。
        for lay in lays:
            lay.invalidate()
            lay.activate()

    @staticmethod
    def _pin_row_lead_width(box, width) -> bool:
        """把行内前导控件钉成固定宽（width=None 表示解除），返回是否发生改动。

        见 _sync_advanced_page_align：只有钉死前导项，末位项的绝对位置才与
        列宽解耦。走 setFixedWidth（= setMinimumWidth + setMaximumWidth）而非
        move()，因为 layout 重新 activate 会覆盖 move()；解除时恢复
        (0, QWIDGETSIZE_MAX) 而不是 0，否则控件会被压成零宽。
        """
        if width is None:
            new_min, new_max = 0, 16777215  # 16777215 = QWIDGETSIZE_MAX
        else:
            new_min = new_max = max(0, int(width))
        if box.minimumWidth() == new_min and box.maximumWidth() == new_max:
            return False
        box.setMinimumWidth(new_min)
        box.setMaximumWidth(new_max)
        return True

    def _queue_nfo_post_cascade_sync(self) -> None:
        """tab 切换后第一拍：只排队，把全量同步留到级联落定后的第二拍。"""
        QTimer.singleShot(0, self._sync_page_layouts)

    def _settle_settings_after_switch(self) -> None:
        """切 tab/切页后同步落定设置页（首开 NFO 字段说明跳动修复）。

        现象：初次打开设置-NFO 的瞬间，「字段说明」按钮从右边跳到左边
        （再次打开不再出现）。根因链：
        1) tab 切换只走双拍 beats（280 行注释：直接读会拿到级联前 stale
           几何钉错 thirds，故第一拍只排队、第二拍才全量同步）；
        2) paint 发生在 beats 之前，首开第一拍常看到中间态视口
           （滚动条闪烁 805 级），trailing 按它把组框定格偏窄，
           field pin 误判溢出把按钮左移 → 肉眼看到跳动；第二拍落定后
           复位 640，之后各次打开几何早已落定、beats 全是 no-op，
           故不再跳。
        做法：currentChanged 上直连本方法（paint 之前执行），至多 3 轮
        {全量同步+泵事件}至稳（快照按钮 x/组宽/视口；trailing
        的 setGeometry 同步生效、泵让滚动条级联落定），切 tab 返回时几何
        已是终态（注：曾试 setUpdatesEnabled 关 paint 抑中间帧，反而扰动
        渲染扫描类量测致落点偏移 rd.x 203→213、country_year/tail 挂，
        已删除）。只接离散切换信号，不进 resize 路径；beats 原位保留
        作级联兜底；设置页/NFO 休眠时直接返回（零成本）。
        """
        ui = self.Ui
        if not ui.page_setting.isVisibleTo(self):
            return
        btn = ui.pushButton_field_tips_nfo
        if not btn.isVisibleTo(self):
            return
        gb = ui.groupBox_81
        sc = ui.scrollArea_13
        for _ in range(3):
            before = (btn.x(), gb.width(), sc.viewport().width())
            self._sync_page_layouts()
            QApplication.processEvents()
            after = (btn.x(), gb.width(), sc.viewport().width())
            if after == before:
                break

    def _sync_settings_scrollbar_widths(self) -> None:
        """设置页各页签竖向滚动条厚度兜底（保证逐页等宽、有 sane 下限）

        这就是用户「演员/网络/高级（以及字幕/水印）几页滚动条看着更细」那个现象
        的修法。取证的坑在于：**必须先让设置页真正显示出来**再去量——stackedWidget
        里 page_setting 的下标是 4（不是 2），早前几版脚本按 2 进页，页面始终
        isVisibleTo False，本方法每次都在守卫处早退，于是量到的「12 页一致、都是
        16px」全是假象（那批数据只有真正被布局过的一条是真的）。
        正确取证：QT_SCALE_FACTOR=0.8（对应用户 1920x1080 + 125% 系统缩放）、
        窗口 1030x650、进入设置页后逐页切，**对每条可见滚动条 grab() 逐像素量**——
        修前 11 页里 10 页渲染宽度就是 12px（恰好落在字幕/水印/演员/网络/高级），
        修后 11 页全是 16px，与 QSS 声明一致。
        做法：切页落定后取各页厚度，只采信落在合理区间（8~48px）的读数，取
        其中最宽者为准，把其余一律 setFixedWidth 对齐；已一致时完全 no-op
        （幂等）；除滚动条自身厚度外不改任何几何，组框与行列宽由末尾的全量
        同步按新视口重排。
        读数来源（离屏整窗实测，勿再改回 width()）：厚度取 **sizeHint()** 而非
        width()。QSS 里 `QScrollBar:vertical{width:16px}` 是权威厚度，它落在
        sizeHint 上；width() 只是控件当前几何，未 polish / 未被布局过的页签停在
        平台默认 PM_ScrollBarExtent（实测 12，比 QSS 少 4）。这正是「首开某页
        是宽的、切走再回来变窄、且每次落在随机页签」的成因：先用 width() 取到
        某个未抛光页的 12，再被 setFixedWidth 永久钉死（min=max=12 覆盖 QSS），
        12 页一齐降级且再也回不到 16。sizeHint 不受布局时序影响，12 页恒为 16。
        取最宽者（max）而非最窄：一次坏读数只能把自己拉回众数，不能拖着全组
        降级——这与本方法文档、docs/Development.md 及
        tests/test_window_state_matrix.py 的断言一致（min 会让该回归测试失败）。
        另：未布局页除厚度外还可能报出荒唐的**长度**（Qt 默认 100px），本方法只
        管厚度，不涉长度。
        注：本项目 Python 3.14 free-threading 下信号槽内抛异常会直接带崩
        进程（已见 add_log 槽事故），故整体 try/except 兜底。
        """
        try:
            ui = self.Ui
            if not ui.page_setting.isVisibleTo(self):
                return
            bars = []
            for index in range(ui.tabWidget.count()):
                page = ui.tabWidget.widget(index)
                if page is None:
                    continue
                area = page.findChild(CustomScrollArea)
                if area is None:
                    continue
                bar = area.verticalScrollBar()
                for widget in (area, area.viewport(), bar):
                    widget.ensurePolished()
                bars.append(bar)
            if len(bars) < 2:
                return
            # 只采信合理区间读数：未布局页可能报出荒唐值（Qt 默认 100px 那种），
            # 必须滤掉，否则会把所有页签错钉成 100px（离屏实测教训）
            declared = [bar.sizeHint().width() for bar in bars]
            sane = [width for width in declared if 8 <= width <= 48]
            if not sane:
                # sizeHint 全不可信时退回几何读数，仍取最宽者兜底
                sane = [bar.width() for bar in bars if 8 <= bar.width() <= 48]
                if not sane:
                    return
            target = max(sane)
            corrected = False
            for bar in bars:
                # 按「约束」而不是按「几何」判定是否需要钉：若某条 width() 恰好已经
                # 等于 target（例如首开时唯一被布局过的那一条），几何判据会把它判为
                # 已是宽态而放过——那条就永远只靠 QSS 撑着，后续任何一次 polish/
                # 布局都能把它打回平台默认厚度，正是「随机落在某个页签」的残余。
                # 逐条钉成 min=max=target 才是幂等且封死的终态。
                if bar.minimumWidth() != target or bar.maximumWidth() != target:
                    bar.setFixedWidth(target)
                    corrected = True
            if corrected:
                # 视口随之变化，立刻按新视口重排（否则组框按旧视口定格）
                self._sync_page_layouts()
        except Exception:
            return

    # 设置-刮削网站：「网站偏好」组里「指定网站」下拉框右缘对齐「锁定类型」下拉框
    _SITE_PREF_COMBO = "comboBox_website_all"  # 指定网站（row 3 col 1，gridLayout_28）
    _SITE_PREF_COMBO_REF = "comboBox_fixed_scraping_type"  # 锁定类型（row 17 col 1，gridLayout_36）
    _SITE_PREF_SCROLL = "scrollArea_8"  # 刮削网站页签的滚动区
    # 「刮削不到？看这里！」按钮：groupBox_11 的绝对定位子控件（不在任何 layout 里），
    # y 由 _sync_scrape_note_vertical 按下拉框实时中心重钉，故不随行高/字号漂移。
    _SITE_PREF_NOTE_BUTTON = "pushButton_scrape_note"
    # 设计态宽度上限（.ui 声明的 maximumSize 宽 = 16000），首次进入时记下，
    # 「读数无意义」分支据此原样交回布局。None = 尚未记下。
    _site_pref_combo_design_max: int | None = None

    # 两个下拉框同在 scrollAreaWidgetContents_guaxiaowangzhan 内、都落在各自网格的
    # 第 1 列，故该 content 是二者的公共祖先（跨分支 mapTo 必须经公共祖先中转）。
    # 「网站偏好」只有 2 列、「类型刮削网站」有 4 列（多出「编辑网站」「网站优先」
    # 两个按钮列），列宽因此天然差 111px（离屏实测窄态 513-402、宽态 1403-1292，
    # 两态差值恒等），表现为「指定网站」下拉框右缘越过「锁定类型」111px。
    def _sync_site_pref_combo_width(self) -> None:
        """设置-刮削网站：「指定网站」下拉框右缘收缩到「锁定类型」下拉框右缘。

        用户需求：「软件设置-刮削网站-指定网站下拉框右侧收缩到锁定类型右侧的位置」。
        做法：量出参考下拉框（锁定类型）在公共祖先 content 里的右缘，换算成
        「指定网站」下拉框的可用宽度上限并 setMaximumWidth 钉住——不用 move()/
        setGeometry()，因为两者都在 QGridLayout 里，layout 重新 activate 会直接
        覆盖绝对坐标（与 _pin_row_lead_width 同一结论），而宽度上限是布局本身
        遵守的约束。每次全量同步都按当前视口重算，故窄态/宽态各自收敛到差值 0，
        且窗口在两态间来回变化时宽度会跟着重新张开（只减不增会锁死在窄态）。
        幂等：目标宽度不变时不再触碰控件；本方法在整条 resize 路径上高频调用，
        故对休眠页签做可见性早退（成本近似为零，且避免从未布局的假读数）。
        """
        ui = self.Ui
        combo = getattr(ui, self._SITE_PREF_COMBO, None)
        ref = getattr(ui, self._SITE_PREF_COMBO_REF, None)
        if combo is None or ref is None:
            return
        scroll = getattr(ui, self._SITE_PREF_SCROLL, None)
        if scroll is None or not scroll.isVisibleTo(self):
            # 从未打开过的页签：两个下拉框还停在未经布局的默认几何（实测 100px 宽），
            # 此时量到的右缘是假读数，据此钉上限会把宽度钉死在错值上。整段早退、
            # 不碰任何约束，等首次切进本页签（currentChanged → _settle_settings_after_switch
            # 与 _queue_nfo_post_cascade_sync 都会再跑一遍全量同步）时几何已落定再对齐。
            return
        content = scroll.widget()
        # 落定前置：本控制器量的是两个下拉框的实时右缘，而它们所在的组框宽度由
        # CustomScrollArea 的宽幅同步按当前视口改写。首次打开本页签时宽幅同步还
        # 没跑（组框停在未布局的默认宽度，实测两框仅 100~219px 宽），此刻量到的
        # 是中间态假读数——若据此钉上限，宽度会被永久钉死在 147px，再也张不开
        # （钉住后布局不再扩张，钉值与实际需求形成自锁）。故先显式重跑一遍宽幅
        # 同步（同 _sync_nfo_page_align 对 scrollArea_13 的处理），再量终态。
        scroll.sync_wide_children_width()
        # 设计上限取 .ui 的 16000（comboBox_website_all 声明的 maximumSize 宽），
        # 首次进入时记下，供「读数无意义」分支原样交回布局——不能拿 QWIDGETSIZE_MAX
        # 顶替，那会永久改掉设计约束。
        if self._site_pref_combo_design_max is None:
            self._site_pref_combo_design_max = combo.maximumWidth()
        design_max = self._site_pref_combo_design_max
        # 尚未布局（宽高为 0）或滚动区没内容时读数无意义，放开上限交回布局
        if content is None or combo.width() <= 0 or ref.width() <= 0 or content.width() <= 0:
            if combo.maximumWidth() != design_max:
                combo.setMaximumWidth(design_max)
            return
        combo_x = combo.mapTo(content, QPoint(0, 0)).x()
        ref_right = ref.mapTo(content, ref.rect().bottomRight()).x() + 1
        target = ref_right - combo_x
        floor = combo.minimumSizeHint().width()
        if target < floor:
            # 视口窄到「锁定类型」所在四列网格（多出「编辑网站」「网站优先」两列）
            # 先被挤瘪，参考框右缘已退到本框最小可用宽度之内，此时对齐目标不可达
            # （实测 720x680 窗口下目标仅 93px < 最小 147px）。钉一个低于自身最小
            # 尺寸的上限只会与布局互相拉扯，故交回设计上限、放弃本轮对齐。
            if combo.maximumWidth() != design_max:
                combo.setMaximumWidth(design_max)
            return
        if combo.maximumWidth() != target:
            combo.setMaximumWidth(target)

    def _sync_scrape_note_vertical(self) -> None:
        """设置-刮削网站：「刮削不到？看这里！」按钮垂直居中到「指定网站」下拉框。

        用户需求：「向上移动后要居于下拉框水平中间的位置」。该按钮是 groupBox_11
        的绝对定位子控件（不在任何 layout 里），.ui 里声明的 y 是**死值**——网格行高
        会随字体变化（下拉框上方的 widget_field_priority_options 行、以及各说明
        文字的折行数都参与撑高），行序一换这个死值就与下拉框错行。只改 .ui 能对齐
        当前默认字号，一旦用户改 UI 缩放（comboBox_ui_scale 支持 80%~300%，
        init.py 的 _UI_SCALE_VALUES）或系统字号，行高就变、按钮跟着漂。

        故这里在每次全量同步里按「下拉框实时中心」重钉按钮 y：move() 只改 y、不碰
        宽度与 x（x 由 CustomScrollArea 的 _DOCK_RIGHT 右缘锚定负责，见
        CustomClass.py 的 _classify_inner——那里判 _DOCK_RIGHT 依赖按钮的 right()
        落位，本方法不动 x 故不与之冲突）。只用 setGeometry 的 y 分量，保持 x/宽高
        原样。
        休眠页签整段早退：从未布局时下拉框停在未布局的假几何（实测 y=28、高 30），
        据此钉 y 会把按钮钉到错行且再无事件纠正（休眠读取数是同 _sync_site_pref_
        combo_width 里的假读数陷阱）。切进本页签时 currentChanged 的 settle/beats
        会补跑全量同步，那时几何已落定。
        幂等：目标 y 不变时不触碰控件（本方法在整条 resize 路径上高频调用）。
        """
        ui = self.Ui
        combo = getattr(ui, self._SITE_PREF_COMBO, None)
        button = getattr(ui, self._SITE_PREF_NOTE_BUTTON, None)
        if combo is None or button is None:
            return
        scroll = getattr(ui, self._SITE_PREF_SCROLL, None)
        if scroll is None or not scroll.isVisibleTo(self):
            return
        # 取按钮的父控件（groupBox_11）作公共祖先：按钮直接挂在它下面，而下拉框
        # 嵌在再下一层的 layoutWidget1 网格里，两者的 y 分属不同坐标系，必须经
        # 公共祖先中转才能直接比（直接用下拉框的 parentWidget 会差出
        # layoutWidget1 在组框内的偏移 28px）。两者高度不同（30 vs 26），
        # 用中心点对齐。
        anchor = button.parentWidget()
        if anchor is None or combo.height() <= 0 or combo.width() <= 0:
            return
        combo_y = combo.mapTo(anchor, QPoint(0, 0)).y()
        target = combo_y + (combo.height() - button.height()) // 2
        if button.y() != target:
            button.move(button.x(), target)

    # 设置-刮削网站：「类型刮削网站」组里国产番号说明（label_232）与「动漫里番」
    _SITE_TYPE_GRID = "gridLayout_36"  # 类型刮削网站网格（layoutWidget_6 上的四列网格）
    _SITE_TYPE_GUOCHAN_TIP = "label_232"  # 国产番号说明（row 11 col 1~3，wordWrap）
    # 单行判定容差：heightForWidth 的返回值与 fontMetrics().height() 有零头差
    _SITE_TYPE_SINGLE_LINE_SLACK = 3
    # .ui 给 label_232 声明的 maximumSize 高（34px = 两行）的运行时缓存，首次进入
    # 记下，窄态据此原样交回设计约束。None = 尚未记下。
    _site_type_tip_design_max_h: int | None = None

    def _sync_site_type_tip_single_line(self) -> None:
        """设置-刮削网站：宽态国产番号说明单行时收回空行，「动漫里番」上移一行。

        用户需求：「软件设置-刮削网站-类型刮削网站页最大化时将动漫里番向上移动一行，
        因为提示词已经在一行显示了，目前最大化时动漫里番离国产番号的间距太大了」，
        且「最小化时的界面、布局、组件、控件、提示词等等均保持不变」。

        根因：label_232（国产番号说明）开了 wordWrap，.ui 里钉了 maximumSize 高 34
        （=两行），而 QGridLayout 定行高走 sizeHint 受 maximumSize 夹取、**不走
        heightForWidth**（离屏实测：把上限放开后各宽度下都取 sizeHint 的 43~78px，
        从不按实际折行数收缩）。窗口最大化后该说明所在的三列可用宽度足够，提示词
        只剩一行（实测 heightForWidth = 15px），行高却仍被钉死在 34px，行下方留出
        约 19px 死白，「动漫里番」整块被顶下去一行——正是用户截图里的大间距。
        只改 .ui 无解（静态值无法随窗口宽度变化），只能在运行时收敛。

        做法：量出该说明在当前终态宽度下的真实需要高度 need = heightForWidth(width)，
        仅当它确实只占一行（need ≤ 单行高 + 容差）且该页已被拉宽（见
        _scroll_stretch_extra）时，把 maximumSize 高收成 need，让网格压缩掉这一行；
        同一笔高度再以 gridLayout_36 的 bottomMargin 原样还回去，使网格自然高度与
        容器高度之差（余量 36px）保持不变——否则 QGridLayout 会把少掉的高度摊到 18
        个 verticalSpacing 上（每档 +1px），「动漫里番」只上移 6px 而非一行（实测）。

        最小化不变：窄态该说明仍需两行及以上（实测 1014 及以下 need ≥ 30px），
        freed = 0，本方法对控件与布局零改动，与改动前逐像素一致；且宽窄来回切换时
        两侧都能各自收敛回终态（离屏实测 1014→1400→1920→1014 全程验证）。
        幂等：两个目标值与现值一致时完全不触碰控件，故在整条 resize 路径上高频
        调用无副作用。need 与单行高都取自当前字体实测，与 UI 缩放无关。
        """
        ui = self.Ui
        grid = getattr(ui, self._SITE_TYPE_GRID, None)
        tip = getattr(ui, self._SITE_TYPE_GUOCHAN_TIP, None)
        if grid is None or tip is None:
            return
        scroll = getattr(ui, self._SITE_PREF_SCROLL, None)
        if scroll is None or not scroll.isVisibleTo(self):
            # 休眠页签整段早退：从未布局时 tip 停在未经布局的默认宽度，量到的 need
            # 是假读数，据此收上限会把高度永久钉死在错值上（与
            # _sync_site_pref_combo_width 同一个假读数陷阱）。切进本页签时
            # currentChanged 的 settle/beats 会补跑全量同步，那时几何已落定。
            return
        # 设计上限取 .ui 声明的 maximumSize 高（34px，两行），首次进入时记下，
        # 窄态据此原样交回布局——不能拿 QWIDGETSIZE_MAX 顶替，那会永久改掉设计约束。
        if self._site_type_tip_design_max_h is None:
            self._site_type_tip_design_max_h = tip.maximumHeight()
        design_max_h = self._site_type_tip_design_max_h
        # 尚未布局（宽度为 0）或控件不开 wordWrap 时 heightForWidth 无意义，
        # 放行交回布局（不做任何改动）。
        if not tip.hasHeightForWidth() or tip.width() <= 0:
            if tip.maximumHeight() != design_max_h:
                tip.setMaximumHeight(design_max_h)
            return
        need = tip.heightForWidth(tip.width())
        line_h = tip.fontMetrics().height()
        freed = 0
        if self._scroll_stretch_extra(scroll) > 0 and 0 < need <= line_h + self._SITE_TYPE_SINGLE_LINE_SLACK:
            # 只在真正单行时收紧：两行及以上说明本来就占满 34px，收了反而截断提示词
            freed = max(0, design_max_h - need)
        if tip.maximumHeight() != design_max_h - freed:
            tip.setMaximumHeight(design_max_h - freed)
        # 收回的高度以底边距还回，保持网格自然高度不变 → 少掉的行高不会被摊进间隔
        margins = grid.contentsMargins()
        if margins.bottom() != freed:
            grid.setContentsMargins(margins.left(), margins.top(), margins.right(), freed)
            grid.invalidate()
            grid.activate()

    # 设置-NFO「写入NFO的字段」组：col0 左标签（130px Fixed 右对齐），冒号在右缘
    _NFO_COLON_LABELS = (
        "label_163",  # 标题：
        "label_384",  # 简介：
        "label_385",  # 发行日期：
        "label_392",  # 国家/分级：
        "label_391",  # 年份/时长/想看：
        "label_390",  # 评分：
        "label_386",  # 演员/导演：
        "label_208",  # 系列/标签：
        "label_334",  # 风格/合集：
        "label_388",  # 片商/发行商：
        "label_150",  # 封面/背景/预告片：
    )

    def _sync_nfo_colon_align(self) -> None:
        """设置-NFO：左标签冒号左移与组标题冒号严格上下对齐，窄态宽态一致。

        用户截图：标题：/简介：/发行日期：/国家/分级：/年份/时长/想看：/
        评分：/演员/导演：/系列/标签：/风格/合集：/片商/发行商：/封面/背景/
        预告片：等 11 个左标签缩进在右，要求整体左移、冒号与组标题
        「写入NFO的字段：」的冒号严格对齐，右侧控件跟随、间距不变，
        最小化与最大化都要对齐。
        根因：col0 标签 130px Fixed 右对齐，冒号恒在 col0 右缘
        （layoutWidget_10.x + 130，实测窄态 gb 坐标 x=150）；组标题冒号
        在组左缘 + 标题字形宽（实测 x≈103）。两者差约 42px，而内容区左
        空气只有 layoutWidget_10.x ≈ 20px（gridLayout_40 margin 全 0，
        已离屏实测），固定 margin 杠杆不够；且标题字形宽随字体变，
        魔法数字必随字体漂移（见右列对齐 b14 教训）。
        做法（像素标定 + 纯函数位移，双向幂等）：_calibrate_nfo_colons
        对组盒做一次渲染扫描，标定组标题冒号 x 与行标签右 pad（字形右缘
        与矩形右缘差，同字同号两边抵消的余量），按字体样式 key 缓存，
        稳态零渲染开销；每遍用「当前位 + 位移」把 layoutWidget_10 连 x
        带宽整体左移（右缘保持，col1 右侧不动，col0/col1 间距全保留），
        防裁字守卫只允许裁 col0 左缘空白（右对齐标签文本左缘禁区，活测
        最长文本），最长标签宽于组标题冒号位置时（如当前）钳住取免裁字
        最大位移、接受残差（预算证明严格对齐结构性无解）。只碰容器几何，不碰 y 与行。
        在 _sync_page_layouts 最先调用（右列/thirds、标题/发行日期两同步
        都是相对位置比较，整体平移对其透明）。休眠页跳过，切 tab 下一拍
        单发补齐（同 b14/b17 钩子）。
        """
        ui = self.Ui
        gb = ui.groupBox_81
        if not gb.isVisibleTo(self):
            return
        lw = ui.layoutWidget_10
        lbs = [getattr(ui, n) for n in self._NFO_COLON_LABELS]
        ref = lbs[0]  # 标题：，col0 右对齐代表行
        key = (gb.font().toString(), ref.font().toString(), type(gb.style()).__name__)
        cal = self._nfo_colon_cal
        if cal is None or cal[0] != key:
            fresh = self._calibrate_nfo_colons(gb, lw, lbs)
            if fresh is None:
                return
            self._nfo_colon_cal = (key,) + fresh
            cal = self._nfo_colon_cal
        _, title_colon, row_pad = cal
        dm = title_colon - (lw.x() + ref.x() + ref.width() - row_pad)
        new_x = lw.x() + dm
        # 防裁字：文本左缘（gb 坐标）不许进负区
        fm = ref.fontMetrics()
        widths = [fm.horizontalAdvance(getattr(ui, n).text()) for n in self._NFO_COLON_LABELS]
        fitting = [w for w in widths if w <= ref.width()]
        min_x = (
            (max(fitting) - ref.width()) if fitting else -1000000
        )  # 守卫生于 advance 空间：+row_pad 版曾稳定触发 fail-fast 崩溃，故保持本式；残余 advance 缺口为 bearings，ink 由回归测试验证放得下
        if new_x < min_x:
            new_x = min_x
        right = lw.x() + lw.width()
        new_w = right - new_x
        if new_x == lw.x() and new_w == lw.width():
            return
        lw.setGeometry(new_x, lw.y(), new_w, lw.height())
        grid = lw.layout()
        if grid is not None:
            grid.invalidate()
            grid.activate()

    @staticmethod
    def _calibrate_nfo_colons(gb, lw, labels):
        """渲染扫描标定 (组标题冒号x, 行标签右pad)，失败返回 None（调用方跳过）。

        标题行（组顶 y 2..17）从左向右找第一个 ≥15px 的墨点间隙：
        有注释同行时间隙后是注释，无注释时标题冒号即带内最右墨点，
        两种版式都成立。行标签文本恒以中文冒号结尾，从矩形右缘向左
        首个墨点即冒号右缘；11 个取中位数抗个别渲染抖动。阈值相对背景
        取 60，暗黑主题同样成立。纵坐标按 dpr 换算，返回逻辑像素。
        """
        try:
            pix = gb.grab()
            img = pix.toImage().convertToFormat(QImage.Format.Format_RGB32)
        except Exception:
            return None
        wpx, hpx = img.width(), img.height()
        if wpx <= 0 or hpx <= 0:
            return None
        dpr = pix.devicePixelRatio() or 1.0

        def lum(x, y):
            c = img.pixel(int(x), int(y))
            return (((c >> 16) & 0xFF) * 3 + ((c >> 8) & 0xFF) * 6 + (c & 0xFF)) / 9.0

        bg = lum(wpx / 2, hpx - 4 * dpr)

        def ink(x, y):
            return abs(lum(x, y) - bg) > 60

        # 组标题冒号：y 2..17 带，x 0..400 的墨点 runs
        y0, y1 = int(2 * dpr), min(int(17 * dpr), hpx)
        x_max = min(int(400 * dpr), wpx)
        runs = []
        cur = None
        for x in range(0, x_max):
            hit = any(ink(x, y) for y in range(y0, y1))
            if hit:
                if cur is None:
                    cur = [x, x]
                else:
                    cur[1] = x
            elif cur is not None:
                runs.append(tuple(cur))
                cur = None
        if cur is not None:
            runs.append(tuple(cur))
        if not runs:
            return None
        title_colon = runs[-1][1]
        for i, (_a, b) in enumerate(runs):
            if b > 60 * dpr and i + 1 < len(runs) and runs[i + 1][0] - b >= 15 * dpr:
                title_colon = b
                break
        title_colon = title_colon / dpr
        if not 0 < title_colon < 400:
            return None
        # 11 行标签冒号：各带内从矩形右缘向左首个墨点，取中位数
        found = []
        for lb in labels:
            try:
                top = lb.mapTo(gb, lb.rect().topLeft())
                right = top.x() + lb.rect().width()
                yy0 = max(0, int(top.y() * dpr))
                yy1 = min(hpx, int((top.y() + lb.rect().height()) * dpr))
                xx = int(right * dpr)
                stop = (right - 40) * dpr
                while xx > stop:
                    if any(ink(xx, y) for y in range(yy0, yy1)):
                        found.append(xx / dpr)
                        break
                    xx -= 1
            except Exception:
                continue
        if len(found) < 6:
            return None
        found.sort()
        median = found[len(found) // 2]
        ref = labels[0]
        row_pad = (lw.x() + ref.x() + ref.width()) - median
        if not 0 <= row_pad <= 40:
            return None
        return (title_colon, row_pad)

    def _sync_nfo_page_align(self) -> None:
        """设置-NFO：把七个列对齐控制器整条重跑一遍（纯几何刷新入口）。

        用途只有一个：挂在 NFO 滚动区拉伸之后的钩子上
        （CustomScrollArea._post_wide_sync_hook），使「拉伸」与「对齐」在同一个
        事件里做完。起因是最大化时的可见跳动（与演员页同病、方向相反）：

          离屏实测（探针 probe_2tasks.py，scrollArea_13 拉伸事件序列）
            wide   colMinW1=0    criticX=444  customX=492   ← 拉伸前，条件不成立
            rca    (0,444,492) → (0,444,492)               ← 量到旧几何，留空
            wide   colMinW1=0    criticX=918  customX=498   ← 拉伸后已发散
            hook   （原本是 no-op：本页没挂钩子）            ← 错过的补救机会
            rca    (0,950,498) → (675,498,498)             ← 下一拍才补上 → 肉眼可见的右跳

        _sync_nfo_right_column_align 的判据是 `critic.x() > custom.x()`，而
        CustomScrollArea 是在主窗口 resizeEvent **之后**才把自己和内部子项拉到
        终态的，所以主窗口那一拍量到的必然是拉伸前的几何。挂上钩子后判据在拉伸
        后的几何上求值，一拍即到位，中间态没有机会被绘制。
        七个控制器都是纯函数、双向幂等（各自 docstring 已声明），重复调用安全；
        休眠页直接返回（切 tab 的 showEvent 与 beats 会补齐）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None or not ui.groupBox_81.isVisibleTo(self):
            return
        self._sync_nfo_colon_align()
        self._sync_nfo_right_column_align()
        self._sync_nfo_title_plot_align()
        self._sync_nfo_row_align()
        self._sync_nfo_tail_align()
        self._sync_nfo_set_align()
        self._sync_nfo_field_tips()
        self._sync_nfo_target_column_align()

    def _sync_nfo_right_column_align(self) -> None:
        """设置-NFO：宽视口下右列（影评/导演/TMDB/标签）左对齐到自定义分级/想看人数。

        用户截图：最大化后影评人评分（criticrating）/导演（director）/演员写入
        TMDB ID/标签（tag）被推到自定义分级（customrating）/想看人数（votes）
        右侧两百多 px，要求四者左移与 thirds 严格上下对齐、其余不动、窄态不变。
        根因：gridLayout_66 的 columnstretch=(1,0) 让 C0 吃掉全部横向 surplus，
        C1.x 以斜率 1 随列宽右移；而 country/mpaa/customrating、year/runtime/wanted
        两行 HBox 无弹簧、三项均分 surplus，thirds.x 以斜率 2/3 右移。两者只在
        默认宽度附近相交（约 787px），窗口加宽后 C1 持续超越 thirds；纯拉伸配比
        定不住常数项（hints 差约 48px），故用列最小宽做自适应钳制。
        做法（纯函数、双向幂等）：先清 C1 列最小宽→重排→量自然位置；仅当
        critic.x > custom.x（发散态）时设 C1 列最小宽 = 列宽 - custom.x + score.x，
        把 C1 左缘精确钉到 thirds（导演/TMDB/标签同属 C1，一并归位）；窄态自然
        critic.x <= custom.x，保持清零、布局原样不动。各控件同属 layoutWidget_10，
        .x() 同一坐标系直接可比；只碰列宽，不碰 y 与其它行。
        """
        ui = self.Ui
        grid = ui.gridLayout_66
        score = ui.checkBox_nfo_score
        critic = ui.checkBox_nfo_criticrating
        custom = ui.checkBox_nfo_customrating
        if self._nfo_target_col_active:
            # 目标列对齐生效中：C1 列最小宽归它所有，直接返回。它生效时
            # critic 与 custom 同在锚 B 列、判据恒为假，本来也是 no-op；
            # 不返回的话本方法开头的清零会把它的钉宽洗掉（_sync_page_layouts
            # 第 4014 行每遍都调本方法，且跑在钩子链之后、专抢最后一写）。
            return
        grid.setColumnMinimumWidth(1, 0)
        # 防御性刷新：直接调用时若外层有 pending 布局请求，先落定再测量
        # （内层激活只排布 cell 内部，不管 cell 本身在哪）。钩子时序问题另由
        # _queue_nfo_post_cascade_sync 解决，此处只保测量新鲜。
        outer = ui.gridLayout_40
        if outer is not None:
            outer.activate()
        grid.invalidate()
        grid.activate()
        if critic.x() > custom.x():
            col_w = grid.geometry().width()
            grid.setColumnMinimumWidth(1, max(col_w - custom.x() + score.x(), 0))
            grid.invalidate()
            grid.activate()

    def _sync_nfo_title_plot_align(self) -> None:
        """设置-NFO：原标题/简介/原简介左对齐到发行日期列，窄态宽态一致。

        用户截图：最大化后原标题（originaltitle）应与发行日期（relasedate）
        上下对齐、简介（plot）与 relasedate 对齐、原简介（originalplot）
        与上映日期（premiered）对齐，relasedate/premiered 不动；后用户要求
        最小化（窄视口）同样对齐：ot/plot 对齐 rd.x，opl 对齐 pr.x，
        relasedate/premiered 位置不变、最大化行为不变、任何控件都不上下移动。
        根因：发行三项（release/relasedate/premiered）为 Minimum 策略，
        视口加宽时各自吞掉 extra/3；而原标题/简介行的 150 前缀把后继项 x
        冻结在窄态位置。纯拉伸定不住三者的相对位置，故用前缀最小宽做自适
        应钳制。
        做法（纯函数、双向幂等、单遍精确）：先把 sorttitle/outline/plot 三
        前缀恢复最小宽 150→重排→量自然位置；再设三前缀最小宽为「当前宽+
        位移」（位移 g0=max(rd.x-ot.x,0)，g1=max(rd.x-plot.x,0)，
        g2=max(pr.x-opl.x-g1,0)，opl 永不超过 pr），把后继项精确钉到
        发行日期列。公式只用实测相对位移，与视口宽窄无关，
        窄态宽态同一套：窄态 d≈+29 小步右移，宽态 d 大步右移；已对齐时位
        移为 0 天然无操作。用当前宽而非 150 做基址：前缀 hint 随字体
        变化（如测试字体下 sorttitle hint 为 192），基址 150 会系统性欠
        299-257=42px；当前宽基址与样式无关且天然幂等。复选框加宽只延长点
        击区，视觉无变化。relasedate/premiered 不动：三行是 gridLayout_40
        里三个独立 HBox（135/136/137），加宽 135/136 的前缀只推本行后继项，
        137 行的 rd/pr 几何不受影响。各控件同属 layoutWidget_10，.x() 同一
        坐标系直接可比；只碰前缀列宽，不碰 y 与其它行（高不变→行高不变→
        无上下移动）。休眠页（不可见）跳过，由切 tab 下一拍单发
        与切回设置页排队触发补齐。
        """
        ui = self.Ui
        st = ui.checkBox_nfo_sorttitle
        ot = ui.checkBox_nfo_originaltitle
        outline = ui.checkBox_nfo_outline
        plot = ui.checkBox_nfo_plot
        opl = ui.checkBox_nfo_originalplot
        rd = ui.checkBox_nfo_relasedate
        pr = ui.checkBox_nfo_premiered
        if not ot.isVisibleTo(self):
            return
        rows = (ui.horizontalLayout_135, ui.horizontalLayout_136, ui.horizontalLayout_137)
        for cb in (st, outline, plot):
            cb.setMinimumWidth(150)
        for row in rows:
            row.invalidate()
            row.activate()
        # 防御性刷新：同 thirds，行位置由外层分配，先落定再读 ot/rd.x。
        outer = ui.gridLayout_40
        if outer is not None:
            outer.activate()
        # 窄态宽态同一套公式：位移全是实测相对值，与视口宽窄无关；
        # 窄态自然 d≈+29 小步右移，宽态 d 大步右移，已对齐时 d=0 无操作。
        # 只取正部 + opl 上限钳制：过窄窗口布局被压缩时 d 可能为负（如 900
        # 宽下 rd 被挤到 ot 左边），此时“向右移+参照不动”几何无解——负位移
        # 钳零（前缀不动），且 opl 永不超过 pr（不过调）；宽态 d 全为正，
        # 与旧式 d2=pr.x-opl.x-d1 逐值相等，行为不变。
        d0 = rd.x() - ot.x()
        d1 = rd.x() - plot.x()
        g0 = max(d0, 0)
        g1 = max(d1, 0)
        g2 = max(pr.x() - opl.x() - g1, 0)
        st.setMinimumWidth(max(st.width() + g0, 150))
        outline.setMinimumWidth(max(outline.width() + g1, 150))
        plot.setMinimumWidth(max(plot.width() + g2, 150))
        for row in rows:
            row.invalidate()
            row.activate()

    def _sync_nfo_row_align(self) -> None:
        """设置-NFO：窄态下分级信息（mpaa）/时长（runtime）左对齐到发行日期列。

        用户截图（最小化）：mpaa 框偏左、runtime 框偏右（生产字体约 30/60px），
        最大化天然对齐。只许水平移动，宽态不动。
        根因：三行（h137 发行/h141 国家/h40 年份）皆左堆积无弹簧的 Minimum 行，
        同一起点 X0。有余量时三行均分天然对齐；容器窄到装不下 hint 总宽时，
        Minimum 项被挤到 hint 以下、各行按各自文本乱挤（country 短→mpaa 落下；
        year 比 release 抗挤→runtime 被顶出）。离屏实测（测试字体 850 宽）：
        rd=257、mpaa=252（左 5）、runtime=268（右 11），与用户症状同向。
        挤压分配随宽度混沌翻转（850 宽 settled 态 mpaa 反超 +2、750 宽
        runtime 自然偏左 -13），单边修法顾此失彼，故四方向条件钉死。
        pin 目标必须锚定参照行 h137 实测值：rd.width() 是 relasedate 自身
        宽度，挤压区里比 release 宽出一截，拿它当目标会系统性钉错位
        （mpaa 稳定 +2、第二遍也不自愈）；正确目标 = rd.x - 前项.x -
        h137 实测间距，min=max 一次钉死，有界迭代 3 遍兜 ±1px 取整漂移
        （60px 地板保可读）。无条件全钉死不可行：宽态 mid-cascade 误测
        pin<share 会把 country 钉小、custom 左顶 10px（thirds 单跑即挂）；
        条件式只在错位方向触发，复位保证误触发下一拍自愈。有余量时条件
        皆不触发，宽态零改动。复选框只改列宽，高不变→行高不变→无上下移动。
        休眠页跳过，由切页钩子补齐。
        """
        ui = self.Ui
        country = ui.checkBox_nfo_country
        mpaa = ui.checkBox_nfo_mpaa
        year = ui.checkBox_nfo_year
        runtime = ui.checkBox_nfo_runtime
        release = ui.checkBox_nfo_release
        rd = ui.checkBox_nfo_relasedate
        for cb in (rd, mpaa, runtime):
            if not cb.isVisibleTo(self):
                return
        rows = (ui.horizontalLayout_137, ui.horizontalLayout_141, ui.horizontalLayout_40)
        # 重置上一轮约束，还原自然位（设计最小宽 0，最大宽默认）。
        country.setMinimumWidth(0)
        country.setMaximumWidth(16777215)
        year.setMinimumWidth(0)
        year.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        outer = ui.gridLayout_40
        if outer is not None:
            outer.activate()
        # 条件对称钉死（有界迭代到不动点）：只修实测到错位的方向。
        # pin 目标必须锚定参照行 h137 的实测值——rd.width() 是 relasedate
        # 自身宽度，挤压区里它比 release 宽出一截（850 宽下 133 vs 115，
        # 长文本抗挤），拿它当 country/year 的目标会系统性钉错位
        # （mpaa 稳定 +2、第二遍也不自愈：cap 不 binding）。
        # 正确目标 = rd.x - 前项.x - h137 实测间距（release 同行、X0 同系，
        # min=max 一次钉死）；单遍后重排可能再漂 ±1px（挤压整数取整），
        # 故有界重测 3 遍。参照行 h137 本轮内不受 pins 影响（只动 h141/h40
        # 的前项），目标稳定，迭代收敛。无条件全钉死仍禁止（宽态
        # mid-cascade 误测把 custom 左顶的教训见上）；复位保证误触发自愈。
        for _ in range(3):
            gap_ref = rd.x() - release.x() - release.width()
            t_country = rd.x() - country.x() - gap_ref
            t_year = rd.x() - year.x() - gap_ref
            if mpaa.x() == rd.x() and runtime.x() == rd.x():
                break
            if mpaa.x() != rd.x():
                country.setMinimumWidth(max(t_country, 60))
                country.setMaximumWidth(max(t_country, 60))
            if runtime.x() != rd.x():
                year.setMinimumWidth(max(t_year, 60))
                year.setMaximumWidth(max(t_year, 60))
            for row in rows:
                row.invalidate()
                row.activate()
            if outer is not None:
                outer.activate()

    def _sync_nfo_tail_align(self) -> None:
        """设置-NFO：窄态下末项 customrating/votes 右对齐到 premiered，宽态不动。

        用户需求：“nfo 页面最小化时将自定义（customrating）、想看人数
        （votes）向右移动到与发行日期（premiered）严格上下对齐的位置，
        发行日期（premiered）保持不变，最大化的页面保持不变，只能左右
        移动不能上下移动”。
        根因：_sync_nfo_row_align 只钉了三行的前两项（country/year →
        mpaa/runtime 对齐 rd）；窄态 800~900 挤压带里，第二项自身宽度
        也会漂（850 宽下 mpaa.w=119 vs relasedate.w=133，长文本抗挤），
        导致末项 custom/votes 落在 pr 左边（800 宽 custom 偏左 15、
        850 宽偏左 14；votes 在 850 偏左 2）。700/750 及 900+ 均天然
        对齐，1900 宽态全 0。
        做法（条件对称式，有界迭代到不动点，仿 row_align）：每遍先把
        mpaa/runtime 的约束复位（最小宽 0、最大宽默认），重排落定后实测；
        只修错位的方向——custom.x != pr.x 则把 mpaa 钉到 rd 实测宽度
        （min=max 一次钉死，60 地板），votes.x != pr.x 则把 runtime 钉到
        rd 实测宽度；对齐即停，最多 3 遍（挤压整数取整漂移）。
        目标为什么是 rd.width()（与 b34 教训不矛盾）：前项已被 row_align
        钉到与 release 等宽（同一起点 X0、同间距），故 custom.x == pr.x
        当且仅当 mpaa.w == rd.w（同序位等宽）；实测 850：钉 133 后
        custom.x = 136+115+6+133+6 = 396 = pr.x 精确成立。
        前项 country/year 与参照 rd/pr 本方法只读不动；只改列宽，不碰 y；
        宽态修正量恒 0（自然对齐→条件跳过→约束零残留）。休眠页跳过，
        复用 tab/切页双拍钩子，无新钩子。
        """
        ui = self.Ui
        mpaa = ui.checkBox_nfo_mpaa
        custom = ui.checkBox_nfo_customrating
        runtime = ui.checkBox_nfo_runtime
        votes = ui.checkBox_nfo_wanted
        rd = ui.checkBox_nfo_relasedate
        pr = ui.checkBox_nfo_premiered
        for cb in (pr, custom, votes):
            if not cb.isVisibleTo(self):
                return
        rows = (ui.horizontalLayout_137, ui.horizontalLayout_141, ui.horizontalLayout_40)
        # 重置上一轮约束，还原自然位（设计最小宽 0，最大宽默认）。
        mpaa.setMinimumWidth(0)
        mpaa.setMaximumWidth(16777215)
        runtime.setMinimumWidth(0)
        runtime.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        outer = ui.gridLayout_40
        if outer is not None:
            outer.activate()
        # 条件对称钉死（有界迭代到不动点）：只修实测到错位的方向。
        # row_align 在本方法之前已跑完，前项 country/year 被钉死，
        # 故本轮内 mpaa/runtime 的 pin 只动末项位置，前两项不受影响；
        # 参照行 h137 不受 pins 影响，目标稳定，迭代收敛。
        for _ in range(3):
            t_second = rd.width()
            if custom.x() == pr.x() and votes.x() == pr.x():
                break
            if custom.x() != pr.x():
                mpaa.setMinimumWidth(max(t_second, 60))
                mpaa.setMaximumWidth(max(t_second, 60))
            if votes.x() != pr.x():
                runtime.setMinimumWidth(max(t_second, 60))
                runtime.setMaximumWidth(max(t_second, 60))
            for row in rows:
                row.invalidate()
                row.activate()
            if outer is not None:
                outer.activate()

    def _sync_nfo_set_align(self) -> None:
        """设置-NFO：宽态下合集两项左对齐到片商/发行商列，窄态保持不动。

        用户需求：最大化时合集（使用演员字段）与片商（maker）严格上下对齐、
        合集（使用系列字段）与发行商（publisher）严格上下对齐；最小化时布局
        不动；只能左右移动。
        根因：风格行 h114 是 3 等分、片商行 h138 是 4 等分（皆左堆积无弹簧、
        同一起点、无自定义间距），有余量时均分：d_aset=W_cell/12、
        d_set=W_cell/6，随宽度线性漂移（离屏实测 1000→+41/+82、
        1900→+116/+232，逐值吻合）。
        做法（条件左移单向、宽态门控）：宽态门 extra=viewport-796>200
        （scrollArea_13 即 NFO 设置滚动区，设计宽 796；不用 isMaximized，
        因离屏不可测；1400 中宽 extra≈334 同样开门，属宽向无害）。
        关门（窄态）时复位 genre/actor_set 约束并直接返回，窄态逐像素不动。
        开门后 3 遍有界迭代（两钉串行：先钉 genre、重排后用新鲜位置再算
        actor_set 钉）：只在实测到偏右时封顶前项
        （cap=参照.x-前项.x-行内实测间距，60 地板），studio/maker/
        publisher/label 与 y 全不动；参照行 h138 不受 pins 影响，目标稳定。
        休眠页（不可见）跳过，由切 tab/切页下一拍单发触发补齐。
        """
        ui = self.Ui
        genre = ui.checkBox_nfo_genre
        actor_set = ui.checkBox_nfo_actor_set
        nfo_set = ui.checkBox_nfo_set
        maker = ui.checkBox_nfo_maker
        publisher = ui.checkBox_nfo_publisher
        if not actor_set.isVisibleTo(self):
            return
        # 宽态门：关门时复位并返回，窄态布局逐像素不动。
        viewport_w = ui.scrollArea_13.viewport().width()
        rows = (ui.horizontalLayout_114, ui.horizontalLayout_138)
        outer = ui.gridLayout_40
        genre.setMinimumWidth(0)
        genre.setMaximumWidth(16777215)
        actor_set.setMinimumWidth(0)
        actor_set.setMaximumWidth(16777215)
        for row in rows:
            row.invalidate()
            row.activate()
        if outer is not None:
            outer.activate()
        if viewport_w - 796 <= 200:
            return
        gap = ui.horizontalLayout_114.spacing()
        # 条件左移（有界迭代到不动点）：两钉必须串行——genre 钉会连带左移
        # 整块 [actor_set, set]，actor_set 钉必须用 genre 钉生效并重排后的
        # 新鲜位置计算，否则同一快照下重复扣除 genre 修正量（1900 宽实测
        # overshoot 116px：set 落到 publisher 左边）。
        for _ in range(3):
            if actor_set.x() == maker.x() and nfo_set.x() == publisher.x():
                break
            if actor_set.x() > maker.x():
                cap = maker.x() - genre.x() - gap
                if cap < genre.width() and cap >= 60:
                    genre.setMaximumWidth(cap)
                    for row in rows:
                        row.invalidate()
                        row.activate()
                    if outer is not None:
                        outer.activate()
            if nfo_set.x() > publisher.x():
                cap2 = publisher.x() - actor_set.x() - gap
                if cap2 < actor_set.width() and cap2 >= 60:
                    actor_set.setMaximumWidth(cap2)
                    for row in rows:
                        row.invalidate()
                        row.activate()
                    if outer is not None:
                        outer.activate()

    def _sync_nfo_target_column_align(self) -> None:
        """设置-NFO：宽态下目标两列左移到演员/剧集列与分级/片商列，窄态保持不动。

        用户需求（最大化）：原标题/剧情/发行日期/分级/时长（A 组，五个 HBox 行
        horizontalLayout_135/136/137/141/40 的第 2 项）向左移动到与演员/剧集
        （`checkBox_tag_actor`/`checkBox_tag_series`，标签行第 2 列）严格上下
        对齐；简介/首映/自定义评分/投票（同五行的第 3 项）与影评评分/导演/
        演员TMDB ID/标签（gridLayout_66 的 C1 四格）向左移动到与分级/片商
        （`checkBox_tag_definition`/`checkBox_tag_studio`，标签行第 3 列）严格
        上下对齐。四个锚点自身一律不动；最小化时页面、布局、控件、提示词等
        全部保持原样；只许左右移动。
        根因：五 HBox 行左堆积无弹簧、三项按 Minimum 均分 surplus（首项天然
        定在 X0=136 不动），第 2/3 项以斜率 ~1/3、~2/3 右移；gridLayout_66
        的 columnstretch=(1,0) 让 C0 吃掉全部 surplus，C1.x 以斜率 1 右移；
        而标签两行是 4 等分均分。三者斜率各异，只在默认宽度附近相交，窗口
        加宽后持续发散（离屏 1920×1170 实测 A 列 599 vs 锚 476、B 列/C1 列
        1092 vs 锚 846）。各行同属 layoutWidget_10，.x() 同一坐标系直接可比。
        做法（宽态门控，快慢双径、双向幂等）：窄态（拉伸量 <= 0）清掉本钉宽/尾间隔/
        C1 列最小宽后重跑右列/标题/行/尾四个控制器还原窄态行为，直接返回。宽态先走
        快路径：激活全链后按当前几何算约束，与现状逐值一致即零成本返回（不清不泵，
        resize 拖拽高频调用无负担）。否则走慢路径：绝不清直接闭环——C1 列最小宽一清零
        grid66 即收缩、col1 收窄、锚点左移，量到的是随即被自己的应用作废的几何（曾导致
        481 落定 488 的 stale，且多加同步也只会重复倒带）；锚点从未被钉，带着当前约束
        直接量到热值。随后至多 6 轮：激活→测量→比对，一致则泵事件冲掉本次应用的后果
        后再验证一次（仍一致才真收敛），否则应用后泵事件供下一轮重测。慢路径动过手
        必排一拍 NFO 链 trailing（singleShot(0)，上限 8 拍）：慢路径收敛的只是当前拍内
        几何，滚动区/内容宽度后续生长（如 lw10w 1509→1589）落定在退出之后，必须有一拍
        跑在它后面；下一拍快路径收敛即停排。单拍测量不可靠：切页级联里锚点随滚动区
        拉伸分阶段落定，且本方法的 C1 列最小宽会加宽 grid66、经 grid40 col1 反推锚点
        （自反馈），闭环是必需的。另有归属权问题：_sync_page_layouts 每遍都调右列
        控制器且跑在钩子链之后，它开头的清零会洗掉本钉宽——以 _nfo_target_col_active
        标志声明归属，生效中右列控制器直接返回（判据恒为假、本是 no-op），泵事件触发的
        嵌套全量同步因此无害；窄态/复位/放不下时先清标志再调它接管，保证 C1 有主。
        重入守卫 _nfo_target_col_running 拦住循环泵事件触发的嵌套本方法（外层循环覆盖
        一切）。宽态按行实测计算：首项钉宽 =
        锚A.x - 首项.x - 行间距（第 2 项即落到锚 A 列），第 2 项钉宽 =
        锚B.x - 锚A.x - 行间距（第 3 项即落到锚 B 列）；C1 沿用右列控制器的
        列最小宽公式（col 宽 - 锚B.x + 左列首项.x，此时第 3 项已在锚 B 列，
        与旧公式逐值相等），C1 四格一并归位。全有或全无：任一钉宽低于
        max(文本 hint, 60) 防裁字地板即整单放弃（首项 hint 最大 122、
        第 2 项最大 150，1920 宽下钉宽恒 364，
        C0 目标 734 远大于左列 hint，正常只走通过分支）。两项行
        （horizontalLayout_135）两项全钉死后行内无 Minimum 项吸收富余，
        离屏实测 QHBoxLayout 会把富余均摊进前/中/后三个间隙（双 364 在
        1473 行里落到 246/862 而非左对齐，纯 Qt 最小复现确认与业务代码无关），
        故只给两项行尾部补 Expanding 间隔吸收（水印页尾部间隔同款手法；
        三项行末项 Minimum 自然吸收、无需补），间隔每遍先摘后补。复选框只改列宽，
        高不变→行高不变→无上下移动。休眠页（不可见）跳过。
        与既有控制器的相容：本方法挂在 `_sync_nfo_page_align` 链尾。标题控制器
        在本方法之后仍成立（ot==rd、plot==rd、opl==pr 依然逐位相等，
        三前缀最小宽恰为本钉宽、>150 不变）；右列控制器判据 critic.x>custom.x
        在本方法之后恒为假（两者同在锚 B 列），C1 列最小宽改由本方法写入，
        其“宽态应钳制/窄态应清零”测试依然成立；行/尾控制器只在窄态触发，
        宽态下本方法覆写它们的复位值（min=max 全覆盖），故它们宽态“零残留”
        的旧断言改由本方法的钉宽断言接管（见测试）。
        """
        ui = self.Ui
        rows = (
            ui.horizontalLayout_135,
            ui.horizontalLayout_136,
            ui.horizontalLayout_137,
            ui.horizontalLayout_141,
            ui.horizontalLayout_40,
        )
        firsts = (
            ui.checkBox_nfo_sorttitle,
            ui.checkBox_nfo_outline,
            ui.checkBox_nfo_release,
            ui.checkBox_nfo_country,
            ui.checkBox_nfo_year,
        )
        seconds = (
            ui.checkBox_nfo_originaltitle,
            ui.checkBox_nfo_plot,
            ui.checkBox_nfo_relasedate,
            ui.checkBox_nfo_mpaa,
            ui.checkBox_nfo_runtime,
        )
        anchor_a = ui.checkBox_tag_actor
        anchor_b = ui.checkBox_tag_definition
        if not anchor_a.isVisibleTo(self):
            return
        if self._nfo_target_col_running:
            return  # 嵌套调用（宽态循环里泵事件触发的）：外层循环覆盖一切
        grid = ui.gridLayout_66
        score = ui.checkBox_nfo_score
        c0_cells = (
            score,
            ui.checkBox_nfo_actor,
            ui.checkBox_nfo_all_actor,
            ui.checkBox_nfo_series,
        )
        outer = ui.gridLayout_40

        def _activate_all():
            for row in rows:
                row.invalidate()
                row.activate()
            grid.invalidate()
            grid.activate()
            if outer is not None:
                outer.activate()

        def _compute():
            # 量锚点并算出钉宽/C1min。返回 (ok, first_pins, second_pins, c1_min)，
            # ok 为 False 即放不下（防裁字地板），调用方走 defer。
            anchor_a_x = anchor_a.x()
            anchor_b_x = anchor_b.x()
            first_pins = [anchor_a_x - cb.x() - row.spacing() for cb, row in zip(firsts, rows, strict=True)]
            second_pins = [anchor_b_x - anchor_a_x - row.spacing() for row in rows]
            col_w = grid.geometry().width()
            c1_min = max(col_w - anchor_b_x + score.x(), 0)
            c0_target = anchor_b_x - score.x() - grid.spacing()
            floor = max([cb.sizeHint().width() for cb in firsts + seconds + c0_cells] + [60])
            ok = min(first_pins + second_pins) >= floor and c0_target >= floor
            return ok, first_pins, second_pins, c1_min

        def _matches(first_pins, second_pins, c1_min):
            return (
                all(
                    cb.minimumWidth() == pin and cb.maximumWidth() == pin
                    for cb, pin in zip(firsts + seconds, first_pins + second_pins, strict=True)
                )
                and grid.columnMinimumWidth(1) == c1_min
            )

        def _clear():
            # 注意 sorttitle/outline/plot 三个前缀在 .ui 设计里自带最小宽 150
            # （Fixed-150 前缀，标题控制器每遍也是按 150 复位），清零会破坏设计值，
            # 故按 150 复位；其余七项设计最小宽即 0（行/尾控制器同式），
            # 最大宽设计均为默认。
            for cb in (firsts[0], firsts[1], seconds[1]):
                cb.setMinimumWidth(150)
            for cb in (firsts[2], firsts[3], firsts[4], seconds[0], seconds[2], seconds[3], seconds[4]):
                cb.setMinimumWidth(0)
            for cb in firsts + seconds:
                cb.setMaximumWidth(16777215)
            for row, spacer in self._nfo_target_col_tails:
                row.removeItem(spacer)
            self._nfo_target_col_tails = []
            grid.setColumnMinimumWidth(1, 0)
            self._nfo_target_col_active = False

        # 宽态门：拉伸量 <= 0 即窄态，复位后把管理同组控件的四个控制器重跑一遍，
        # 还原与本方法无关的窄态行为（本方法在窄态逐像素无残留；标志已清，
        # 右列控制器接管 C1 即恢复自然行为）。
        if self._scroll_stretch_extra(ui.scrollArea_13) <= 0:
            _clear()
            self._nfo_target_col_trailing = 0
            self._sync_nfo_right_column_align()
            self._sync_nfo_title_plot_align()
            self._sync_nfo_row_align()
            self._sync_nfo_tail_align()
            return
        # 快路径：稳态零成本。锚点从未被钉、可直接读；归属标志还在且按当前几何
        # 算出的约束与现状逐值一致→直接返回（不清不泵，resize 拖拽高频调用无负担）。
        _activate_all()
        ok, first_pins, second_pins, c1_min = _compute()
        if ok and self._nfo_target_col_active and _matches(first_pins, second_pins, c1_min):
            self._nfo_target_col_trailing = 0
            return
        # 慢路径：不清直接闭环。绝不能先清再量：C1 列最小宽一清零 grid66 即收缩、
        # col1 收窄、锚点左移，量到的是随即被自己的应用作废的几何（此前 stale 的根因：
        # 以约束相等退出，却验证了倒回去的世界；多加几拍同步也无用，只会重复倒带）。
        # 锚点从未被钉，带着当前约束直接量到的是热值；钉宽只约束首项/第 2 项自身宽度，
        # 不改变行首 x，公式不受污染。随后至多 6 轮：激活→测量→比对，一致则泵事件
        # 冲掉本次应用的后果后再验证一次（仍一致才真收敛），否则应用后泵事件供下一轮
        # 重测。嵌套调用由重入守卫拦，外层循环覆盖一切，有界终止。
        self._nfo_target_col_running = True
        try:
            self._nfo_target_col_active = True
            applied_any = False
            for _ in range(6):
                _activate_all()
                ok, first_pins, second_pins, c1_min = _compute()
                if not ok:
                    # 放不下就整单放弃、不裁字（小宽态 defer）：清掉本钉宽后把 C1 交还
                    # 给右列控制器（此时判据若成立它会自己钳制），行为即自然布局。
                    _clear()
                    self._nfo_target_col_trailing = 0
                    self._sync_nfo_right_column_align()
                    return
                if _matches(first_pins, second_pins, c1_min):
                    # 与当前约束逐值一致：泵事件冲掉之前应用的后果，再验证一次，
                    # 仍一致才算真收敛（否则继续循环应用）。
                    QApplication.processEvents()
                    _activate_all()
                    ok2, first_pins2, second_pins2, c1_min2 = _compute()
                    if ok2 and _matches(first_pins2, second_pins2, c1_min2):
                        break
                    first_pins, second_pins, c1_min = first_pins2, second_pins2, c1_min2
                    if not ok2:
                        _clear()
                        self._nfo_target_col_trailing = 0
                        self._sync_nfo_right_column_align()
                        return
                applied_any = True
                for cb, pin in zip(firsts, first_pins, strict=True):
                    cb.setMinimumWidth(pin)
                    cb.setMaximumWidth(pin)
                for cb, pin in zip(seconds, second_pins, strict=True):
                    cb.setMinimumWidth(pin)
                    cb.setMaximumWidth(pin)
                # 两项行两项全钉死后无处吸收富余（离屏实测 QHBoxLayout 会把富余均摊进
                # 三个间隙），三项行末项 Minimum 自然吸收。只给两项行尾部补 Expanding
                # 间隔（水印页尾部间隔同款手法），窄态/复位时摘掉；已补过不再重复补。
                for row in rows:
                    if row.count() == 2 and not any(r is row for r, _ in self._nfo_target_col_tails):
                        tail = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                        row.addItem(tail)
                        self._nfo_target_col_tails.append((row, tail))
                _activate_all()
                grid.setColumnMinimumWidth(1, c1_min)
                grid.invalidate()
                grid.activate()
                QApplication.processEvents()
                _activate_all()
            # 慢路径动过手：排一拍 NFO 链跑在后续生长（lw10/内容宽）后面。
            # 注意必须直接排链（_sync_nfo_page_align，有休眠守卫），不能排全量同步——
            # 链只挂在宽幅拉伸钩子上，无拉伸时全量同步根本到不了本方法。
            # 下一拍收敛（快路径）即停排；仍失稳则再排；上限 8 拍防抖荡。
            if applied_any:
                if self._nfo_target_col_trailing < 8:
                    self._nfo_target_col_trailing += 1
                    QTimer.singleShot(0, self._sync_nfo_page_align)
                else:
                    self._nfo_target_col_trailing = 0
        finally:
            self._nfo_target_col_running = False

    def _sync_nfo_field_tips(self) -> None:
        """设置-NFO：窄态下字段说明按钮左移进组框，宽态保持不动。

        用户截图：最小化时「字段说明」按钮（pushButton_field_tips_nfo，
        Fixed 80x26，设计几何 x=640..720）伸出「写入NFO的字段」组框
        （groupBox_81，设计 x=30 宽 701，右缘 731，设计余量仅 11px）。
        根因：宽幅同步按 width=设计宽+extra 双向拉伸组框（extra<=0 时
        缩回）；extra<0（视口窄于设计 796）时组右缘左移，按钮还钉在 640
        就伸出去（1089 窗 extra≈-14，伸出约 3px；越窄越糟）。
        做法（绝对 pin，只左移）：复位 x=640→重排→若按钮右缘超过
        （组右缘-11），则 btn.move(组右缘-11-80, y)；宽态 640 逐像素不动，
        y 不动。按钮与组框同属 scrollAreaWidgetContents_nfo，同父坐标系
        直接可比。休眠页跳过，由切 tab/切页下一拍补齐；多拍收敛幂等。
        """
        ui = self.Ui
        btn = ui.pushButton_field_tips_nfo
        gb = ui.groupBox_81
        if not btn.isVisibleTo(self):
            return
        btn.move(640, btn.y())
        limit = gb.x() + gb.width() - 11
        if btn.x() + btn.width() > limit:
            btn.move(limit - btn.width(), btn.y())

    def _naming_label_painted_height(self, lbl) -> int:
        """标签实际绘制出来的高度（px）。

        QLabel 的 sizeHint()/heightForWidth() 对「整段 <br> 硬换行 + 长段落自动折行」
        这类文字都偏大：前者按未折行的行数估算，后者按整段行距估算，都比真正画出
        来的像素高几十像素（实测 label_66 绘制 282 / hFW 287 / sh 387；预览结果文字
        绘制 65 / hFW 82 / sh 99，且 minimumSize 还钉着 82）。按这些值钉高，「视频文
        件名」「示例字段」下方就会留出空白。
        所以改成把标签渲染到一张白底 pixmap 上，从底部逐行回扫第一个有墨迹的行——
        那就是文字真正的下沿。

        门闩（必须）：本方法内部的 `lbl.render(pixmap)` 会向 label_66 派发
        QEvent.Resize，而 __init__ 在 label_66 上装了本窗口做 eventFilter，
        eventFilter 的 label_66 Resize 分支又会同步调用本方法 —— 两者互为递归，
        没有任何标志拦得住，无限递归直接栈溢出（Windows 0xC00000FD）把进程打死，
        而且**不是 Python 异常，crash 目录里连日志都不会留**（只有 sys.excepthook
        写的 _py.log）。faulthandler 实测栈（探针 crashstress.py / so_repro.py）：
            main_window.py:2509 in _naming_label_painted_height
            main_window.py:642  in eventFilter
            main_window.py:2509 in _naming_label_painted_height
            main_window.py:642  in eventFilter            ← 无限重复直到爆栈
        表现给用户就是「点软件设置-翻译/NFO 有几率直接退出」。故重入时直接返回标签
        自身高度（中性值，不会误触发外层的重排判断），由外层那次调用负责收尾。
        """
        if self._naming_scanning:
            return lbl.height()
        self._naming_scanning = True
        try:
            return self._measure_painted_height(lbl)
        finally:
            self._naming_scanning = False

    @staticmethod
    def _measure_painted_height(lbl) -> int:
        """_naming_label_painted_height 的实际测量体（供门闩版调用，不要直接调）。"""
        width = max(lbl.width(), 1)
        probe_h = min(max(lbl.sizeHint().height(), 200) + 200, 2000)
        pixmap = QPixmap(width, probe_h)
        pixmap.fill(QColor(255, 255, 255))
        lbl.render(pixmap)
        # 回扫用原始字节，而不是逐像素 pixelColor()：标签最多 2000 行 × 600 列，
        # 逐像素一次最大化要调 42 万次 pixelColor（cProfile tottime 0.18s，是
        # _sync_page_layouts 里最大的一笔）。这段时间事件循环被 resizeEvent 堵住、
        # 窗口一次都没绘制，用户就看到「最大化时四周先是一大圈黑屏」。改成按行取
        # bytes 切片整体比较（纯 C 层切片+比较），同图同结果、耗时可忽略。
        # 取样规则与旧实现保持一致：x 从 0 到 width 步进 2，不改变已验证的落点。
        try:
            img = pixmap.toImage().convertToFormat(QImage.Format.Format_Grayscale8)
            bpr = img.bytesPerLine()
            buf = img.constBits().asstring(img.sizeInBytes())
            white_row = b"\xff" * ((width + 1) // 2)
            for y in range(probe_h - 1, -1, -1):
                base = y * bpr
                if buf[base : base + width : 2] != white_row:
                    return y + 1
            return 1
        except Exception:
            # 取不到原始缓冲（非常规像素格式等）时退回逐像素旧路径
            pass
        img = pixmap.toImage()
        white = QColor(255, 255, 255)
        for y in range(probe_h - 1, -1, -1):
            for x in range(0, width, 2):
                if img.pixelColor(x, y) != white:
                    return y + 1
        return 1

    @staticmethod
    def _label_text_height_for_width(lbl) -> int:
        """按标签**当前宽度**算出文字真正需要的高度（px）——纯宽度函数，无高度自反馈。

        为什么不用 _naming_label_painted_height：那个方法把标签 render 到白底
        pixmap 上、从底部回扫第一个「非纯白」的行。但「白」是写死的 0xff，而
        标签的实际背景由调色板/样式表决定，不是纯白就没有一行等于 0xff，方法
        退化成恒等函数「返回标签自身高度」（offscreen 无 QSS 时背景是 0xef，
        label_66 / label_331 / label_358 实测 painted 全部 == 标签高度）。恒等
        函数配 `setFixedHeight(painted + 2)` 就是正反馈：每轮长 2px 永不收敛
        （label_331 由 41 一路漂到 47+）。真机上恰好白底才量得准，属环境碰运气。

        改用 QTextDocument（QLabel 富文本走的就是同款排版引擎）按当前宽度重新
        排版取文档高：结果只由 字体 + 文本 + 宽度 决定，不掺入标签当前高度，
        故同宽度必得同值（幂等、不累积漂移），也不受背景色影响。
        高度取文档高（含上下 document margin）而非墨迹范围，保证绝不裁字；
        实测 label_331 单行墨迹 13px / 文档高 22px，+2 余量后 24px。
        """
        doc = QTextDocument()
        doc.setDefaultFont(lbl.font())
        text = lbl.text() or ""
        if "<" in text:
            doc.setHtml(text)
        else:
            doc.setPlainText(text)
        doc.setTextWidth(max(lbl.contentsRect().width(), 1))
        return math.ceil(doc.size().height()) + 2

    @staticmethod
    def _label_ink_height_for_width(lbl) -> int:
        """按标签**当前宽度**算出文字墨迹真正占多高（px）——纯宽度函数，无高度自反馈。

        比 _label_text_height_for_width 更紧：后者取 QTextDocument 文档高，量的是
        含上下 document margin 的**行盒**范围；本方法量**墨迹**范围，故省下的正是
        用户截图里圈出的那两段空白（label_331 单行行盒 24px / 墨迹 18px）。

        墨迹上沿用 Qt 字体度量直接算：QTextLine 没有 tightBoundingRect，
        但「行盒顶到墨迹顶」的偏移有闭式解
            ink_top = QFontMetrics(font).ascent() + QFontMetrics(font).tightBoundingRect(text).y()
        （实测 label_331 → 12 + (-9) = 3，与其 AlignTop 下逐高度像素扫描得到的
        ink top 恒为 3 完全吻合；label_357 / label_358 同样命中）。

        行数靠 QTextDocument 文档高反推：`docH = 2×documentMargin + 行数×lineSpacing`
        （实测 margin=4：w=620→38→2 行，w=400→53→3 行，w=200→98→6 行，全部对上）。
        不能用 `QTextBlock.layout().lineCount()`：离屏下 layout 未激活恒返回 0；
        也不能用 `QTextLayout.beginLayout()`：同样在未挂 paint device 时返回 0 行。

        逐行**精确**墨迹高 Qt 给不出（QTextLine 只有行盒级 API），故按
        `ink_top + (行数-1) × lineSpacing + 单行墨迹高` 近似，其中单行墨迹高
        取 tightBoundingRect 高度按行数摊平。实测（真实 QSS 字体 asc=12 ls=15）：
          label_331 单行 → 3 + 0 + 12 = 15（像素扫描实测墨迹恰为 y 3..18）；
          label_331 两行 → 3 + 15 + 12 = 30（实测墨迹 y 3..27，不裁）；
          label_357      → 4 + 0 +  8 = 12（墨迹仅 8px，垂直居中留 4px 余量）；
          label_358      → 3 + 0 +  9 = 12（墨迹 9px）。
        绝对不能用 `ink_top + 行数 × lineSpacing`：那样 label_357 会得 19px，
        而它真实墨迹只有 8px，白白多留 7px 正是用户圈出的空隙。
        """
        text = lbl.text() or ""
        if not text.strip():
            return 0
        fm = QFontMetrics(lbl.font())
        # 富文本标签的 <p> 等包裹会污染断行宽度，先剥成纯文本（QLabel 显示的
        # 也是剥掉后的字形）；纯文本标签原样返回。
        doc = QTextDocument()
        doc.setDefaultFont(lbl.font())
        if "<" in text:
            doc.setHtml(text)
        else:
            doc.setPlainText(text)
        doc.setTextWidth(max(lbl.contentsRect().width(), 1))
        spacing = fm.lineSpacing()
        usable = max(doc.size().height() - 2 * doc.documentMargin(), spacing)
        lines = max(1, round(usable / spacing))
        tight = fm.tightBoundingRect(text)
        ink_top = fm.ascent() + tight.y()
        # tight.height() 对多行文本是整段包围盒，按行数摊平才回到「单行墨迹高」
        ink_line = max(tight.height() / lines, 1)
        return max(1, math.ceil(ink_top + (lines - 1) * spacing + ink_line))

    def _sync_naming_template_section(self) -> None:
        """命名页「视频命名规则」组（groupBox_8）按内容收缩，消除大片空白。

        两个现象（用户截图）：
        1. 「视频文件名」上方大片空白——说明文字 label_66 是 AlignTop 的可换行富
           文本标签，整块网格按内容收缩后，说明文字必须给出真实需要的高度，
           否则要么裁字、要么在下方留白（见 _naming_label_painted_height）。
        2. 「模板预览」占满网格剩余空间被撑得过高。
        3. 「示例字段」下方大片空白——预览结果文字
           label_name_template_preview_result 同理，它的 sizeHint/minimumSize 都
           远大于实际绘制高度，不贴合就会把整组底部顶出一片空白。

        做法：预览钉到设计三分之一高度；说明文字按实际绘制高度贴合；整个网格的
        组高按内容收缩，其后的 QGroupBox 按同一增量上移保持设计间距
        （下移/上移都用「设计基准 + 增量」，幂等无累积漂移，见 MEMORY 军规③）。
        """
        ui = self.Ui
        box = ui.groupBox_8
        widget = ui.gridLayoutWidget_8
        lbl = ui.label_66
        preview = ui.plainTextEdit_name_template_preview
        result = ui.label_name_template_preview_result
        grid = ui.gridLayout_8
        if lbl.width() <= 0 or box.width() <= 0:
            return
        if self._naming_resyncing:
            return
        # 休眠页零成本：命名页不可见时整段跳过（切到该 tab 的 currentChanged 与
        # 滚动区 showEvent 会补齐，接线见 __init__），省掉两次 pixmap 渲染扫描 +
        # 网格重排 + 后续 6 个 groupBox 的 move。这一项是把最大化时 resizeEvent 的
        # 阻塞从 ~600ms 压到 ~40ms 的关键（用户报「放大时四周先是一大圈黑屏」：
        # 窗口在这一段时间里一次都没绘制，新露出的区域当然是黑的）。
        # 不要在这里加「输入指纹相同就整体返回」的短路：sync_wide_children_width()
        # 会把 groupBox_8 与后续 groupBox 按登记的设计几何复位，指纹没变但几何已被
        # 复位时早退，会留下 groupBox_8 已收缩、后续组仍在设计位的错位。
        if not box.isVisibleTo(self):
            return

        # 首次调用登记设计几何（此后 sync_wide_children_width 只改宽不改高，
        # groupBox_8 的高由本方法接管）。
        if self._naming_design is None:
            self._naming_design = {
                "box_h": box.height(),
                "groups": {name: getattr(ui, name).y() for name in self._NAMING_FOLLOW_GROUPS},
            }

        # 本方法会改 label_66 高度并触发其 Resize；用标志位抑制 eventFilter 的递归重算。
        self._naming_resyncing = True
        try:
            # 1) 两段说明文字都按实际绘制高度贴合。测量前必须先解除上一轮的固定
            #    高度，否则标签仍被裁着，量到的只是残缺高度（会越量越小、最后裁字）。
            for text_widget in (lbl, result):
                text_widget.setMinimumHeight(0)
                text_widget.setMaximumHeight(16777215)
            grid.invalidate()
            grid.activate()
            lbl.setFixedHeight(self._naming_label_painted_height(lbl))
            # 2) 模板预览固定高度，不再吸收网格剩余空间。
            preview.setFixedHeight(self._NAMING_PREVIEW_H)
            # 3) 预览结果文字（状态/结果/示例字段）同样按真实绘制高度贴合。
            result.setFixedHeight(self._naming_label_painted_height(result))
            grid.invalidate()
            grid.activate()

            # 3) 组高按内容收缩，后续组同步上移。
            content_h = grid.sizeHint().height()
            new_box_h = content_h + self._NAMING_BOX_PAD
            widget.setGeometry(widget.x(), widget.y(), widget.width(), content_h)
            box.setGeometry(box.x(), box.y(), box.width(), new_box_h)

            # 宽幅容器登记表里存的是设计几何，同步宽度时会按登记高度复位 groupBox_8 /
            # gridLayoutWidget_8，这里把登记高度一并更新。
            registry = getattr(ui.scrollAreaWidgetContents_mingming, "_wide_children_design", None)
            for entry in registry or ():
                if entry.widget is box:
                    ex, ey, ew, _eh = entry.geometry
                    entry.geometry = (ex, ey, ew, new_box_h)
                    for item in entry.inner:
                        if item.widget is widget:
                            ix, iy, iw, _ih = item.geometry
                            item.geometry = (ix, iy, iw, content_h)

            delta = self._naming_design["box_h"] - new_box_h
            for name in self._NAMING_FOLLOW_GROUPS:
                group = getattr(ui, name)
                group.move(group.x(), self._naming_design["groups"][name] - delta)

            scroll = getattr(ui, "scrollArea_7", None)
            if scroll is not None:
                scroll.sync_content_min_height()
            self._naming_last_width = lbl.width()
        finally:
            self._naming_resyncing = False

    # ============ 设置-翻译页（简介 / 演员两组）的间距收紧常量 ============
    # groupBox_83（简介）：网格容器与 frame_5「双语显示」之间保留的间距、
    # 组底留白。设计值里容器底部有 7px、组底 9px，两处都太松，合并成常量。
    _FANYI_INTRO_GRID_GAP = 10
    _FANYI_BOX_BOT_PAD = 9
    # groupBox_84（演员）：行首留白。Qt 会把容器多出来的高度在「顶 / 行间 /
    # 底」之间均分（实测 layoutWidget_20 418 vs 网格 sizeHint 352，多出的 66px
    # 被均分成 顶16 / 行间各+16 / 底18），长说明文字的行顶因此落在 120。
    # 改为由本控制器显式给定：留白 30 时首行「演员语言」行顶落在组内 52，标题
    # 下方空着将近两行（用户截图「内容整体向上移动两行，移动完成后删掉下方多出
    # 来的空白空间」）。留白归 0 后首行行顶回到 layoutWidget_20 的设计 y=22，
    # 标题下方不再有整行空白；组高是「容器底 + _FANYI_BOX_BOT_PAD」算出来的，
    # 行首少 30 组高就同步收 30，其后各组随 delta_actor 整体上移，空出来的
    # 30px 不会被留成组底/组间空档。
    _FANYI_ACTOR_TOP_PAD = 0
    # groupBox_trans（翻译引擎）：组底留白。设计值里 layoutWidget_2 底到组底 10px。
    _FANYI_TRANS_BOT_PAD = 10
    # groupBox_trans 之后、简介组（groupBox_83）之前的组：翻译引擎组一收紧，
    # 它们必须跟着上移，否则组间距会被整段拉开。
    _FANYI_TRANS_FOLLOW_GROUPS = (
        "groupBox_llm",
        "groupBox_82",
    )
    # groupBox_83/84 之后所有需要跟着上移的组（都是绝对定位在内容控件上的）。
    _FANYI_FOLLOW_GROUPS = (
        "groupBox_84",
        "groupBox_85",
        "groupBox_86",
        "groupBox_87",
        "groupBox_88",
        "groupBox_89",
    )

    def _sync_fanyi_group_spacing(self) -> None:
        """设置-翻译页：简介组与演员组按内容收紧间距（用户截图两处反馈）。

        ① 简介组（groupBox_83）「翻译方式」与「双语显示」之间空得离谱。
           离屏实测（探针 fanyi_probe2.py，还原态）：翻译方式行底在组内 y=108，
           双语显示墨迹顶约 180，中间约 72px，而真正占位的只有一行 17px 的
           提示文字。拆开来：label_176 拿了 34px 却只画 24px（富文本 <p> 的段
           落边距吃掉了 17px）；gridLayout_48 的 sizeHint 106 被容器 131 拉出
           25px 余量、Qt 在顶/行间/底均分（实测行距 12 而非设计的 6）；容器底
           还剩 7px、组底 9px。
        ② 演员组（groupBox_84）长说明文字 label_249 整体比设计值低一行。
           gridLayout_50 的 sizeHint 352 被容器 418 拉出 66px，同样被均分成
           顶16/行间各+16/底18，文字行顶落在 120；文字本身 14 行 × 20px = 280
           正好等于标签高度，最后一行贴着组框内框。用户要求「整体上移一行，
           同时从底部去掉一行高度」。后续追加要求「内容整体向上移动两行，
           移动完成后删掉下方多出来的空白空间」——那 30px 行首留白（首行行顶
           52）正是标题下方的整行空白，去掉后首行行顶回到容器设计位 22，组高
           同步收 30，组底留白仍是 _FANYI_BOX_BOT_PAD。
        ③ 翻译引擎组（groupBox_trans）「DeepLX URL」与提示文字
           label_baidu_hint 之间空着一整行，其下的「百度 APP / 百度密钥」两行
           被整体下推（用户截图：提示词向上移动一行，百度 APP、百度密钥同步
           向上移动一行）。真机实测（windows 平台，YaHei UI 9pt）：容器
           layoutWidget_2 高 280，而各行真实需要只有 218（勾选行/输入行各 30、
           两行说明文字各 16、行间 6×6）；gridLayout_32 末尾没有 Expanding
           间隔，多出来的 62px 就全灌进独占一行的 label_baidu_hint（垂直策略
           Preferred + wordWrap 的 heightForWidth 有效，且是该行唯一控件），
           文字被垂直居中 → 上下各空、下面两行被推下去。与 ①② 同根因。

        做法（与 _sync_naming_template_section 同款：设计基准 + 增量，幂等
        不累积漂移）：
          0) 先收紧翻译引擎组：两行说明文字按墨迹高度贴合（纯宽度函数，见
             _label_ink_height_for_width）→ 容器高度钉成网格 sizeHint → 组高
             = 容器底 + _FANYI_TRANS_BOT_PAD；其后所有组（含简介组自身）按这个
             收缩量上移。放在最前面做，后面的增量都在它之上累加。
          1) 量「真实绘制高度」前必须先解除上一轮的固定高度，否则量到的是被裁
             的残缺高度（会越量越小、最后裁字）。富文本标签取 painted 与
             heightForWidth 的较大者——heightForWidth 对富文本才准。
          2) 把网格容器高度钉成 sizeHint（不给 Qt 任何均分空间），行首留白改
             由常量显式给定，几何完全可预测。
          3) 组高 = 容器底 + 固定底留白；其后的 QGroupBox 按「设计 y − 累计收
             缩量」上移，并同步更新 scrollArea_11 宽幅登记表里的高度，最后
             sync_content_min_height() 收紧内容控件（否则页尾留一大片空白）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None or self._fanyi_resyncing:
            return
        intro, actor = ui.groupBox_83, ui.groupBox_84
        hint, story = ui.label_176, ui.label_249
        trans = ui.groupBox_trans
        trans_note, trans_hint = ui.label_164, ui.label_baidu_hint
        g_intro, g_actor, g_trans = ui.gridLayout_48, ui.gridLayout_50, ui.gridLayout_32
        lw13, lw20, frame = ui.layoutWidget_13, ui.layoutWidget_20, ui.frame_5
        lw2 = ui.layoutWidget_2
        # 休眠页零成本：没激活的页签不会给出真实视口，量出来的都是设计尺寸。
        if not (trans.isVisibleTo(self) and intro.isVisibleTo(self) and actor.isVisibleTo(self)):
            return
        if trans_note.width() <= 0 or trans_hint.width() <= 0 or hint.width() <= 0 or story.width() <= 0:
            return

        if self._fanyi_design is None:
            shifted = (*self._FANYI_TRANS_FOLLOW_GROUPS, "groupBox_83", *self._FANYI_FOLLOW_GROUPS)
            self._fanyi_design = {
                "groups": {n: getattr(ui, n).y() for n in shifted},
                "trans_h": trans.height(),
                "intro_h": intro.height(),
                "actor_h": actor.height(),
            }

        self._fanyi_resyncing = True
        try:
            # 0) 翻译引擎组：两行说明文字按墨迹高度贴合 → 容器按网格 sizeHint 收紧。
            #    label_baidu_hint 是独占一行的 wordWrap 标签（垂直策略 Preferred、
            #    heightForWidth 有效），容器一富余它就把多出来的整段高度吃掉，
            #    文字垂直居中、下面「百度 APP / 百度密钥」两行被整体下推（用户截图
            #    里 DeepLX URL 与提示文字之间那整行空白）。先解除上一轮的固定高度
            #    再量，避免量到被裁的残缺高度（越量越小、最后裁字）。
            for lbl in (trans_note, trans_hint):
                lbl.setMinimumHeight(0)
                lbl.setMaximumHeight(16777215)
            g_trans.invalidate()
            g_trans.activate()
            # 纯宽度函数（只吃 字体+文本+宽度）：墨迹高而非行盒高，多大宽度都刚好
            # 贴住文字；行盒高会把用户圈出的空白原样留回来。
            trans_note.setFixedHeight(self._label_ink_height_for_width(trans_note))
            trans_hint.setFixedHeight(self._label_ink_height_for_width(trans_hint))
            g_trans.invalidate()
            g_trans.activate()

            # 1) 翻译引擎组：容器按网格 sizeHint 收紧（末尾 Expanding 间隔吸收
            #    残余富余，不会再有某一列被灌高），组高 = 容器底 + 固定底留白。
            trans_lw_h = g_trans.sizeHint().height()
            lw2.setGeometry(lw2.x(), lw2.y(), lw2.width(), trans_lw_h)
            trans_h = lw2.y() + trans_lw_h + self._FANYI_TRANS_BOT_PAD
            trans.setGeometry(trans.x(), trans.y(), trans.width(), trans_h)
            delta_trans = self._fanyi_design["trans_h"] - trans_h
            # 翻译引擎组之后、简介组之前的组按同一收缩量上移（组间距不变）。
            for name in self._FANYI_TRANS_FOLLOW_GROUPS:
                group = getattr(ui, name)
                group.move(group.x(), self._fanyi_design["groups"][name] - delta_trans)

            # 2) 简介/演员组：解除固定高度 → 量真实需要高度 → 重新钉上。
            for lbl in (hint, story):
                lbl.setMinimumHeight(0)
                lbl.setMaximumHeight(16777215)
            g_intro.invalidate()
            g_actor.invalidate()
            g_intro.activate()
            g_actor.activate()
            # 单行提示：painted + 2（+2 是抗字体 hinting 抖动的余量；若某宽度下
            # 折成两行，量到的 painted 会自动变大，不依赖任何写死行数）。
            hint_h = self._naming_label_painted_height(hint) + 2
            # 长说明文字是富文本（<p style='line-height:20px'>），QFontMetrics 对
            # 它无效，只能靠渲染扫描 + heightForWidth，取两者较大值防止裁字。
            story_h = max(
                self._naming_label_painted_height(story) + 2,
                story.heightForWidth(story.width()),
            )
            hint.setFixedHeight(hint_h)
            story.setFixedHeight(story_h)
            g_actor.setContentsMargins(0, self._FANYI_ACTOR_TOP_PAD, 0, 0)
            g_intro.invalidate()
            g_actor.invalidate()
            g_intro.activate()
            g_actor.activate()

            # 3) 简介组：容器按网格 sizeHint 收紧，frame_5 跟着上移。
            #    y 按「设计基准 − 翻译引擎组收缩量」给，不吃当前值，幂等。
            intro_lw_h = g_intro.sizeHint().height()
            lw13.setGeometry(lw13.x(), lw13.y(), lw13.width(), intro_lw_h)
            frame.move(frame.x(), lw13.y() + intro_lw_h + self._FANYI_INTRO_GRID_GAP)
            intro_h = frame.y() + frame.height() + self._FANYI_BOX_BOT_PAD
            intro_y = self._fanyi_design["groups"]["groupBox_83"] - delta_trans
            intro.setGeometry(intro.x(), intro_y, intro.width(), intro_h)
            delta_intro = self._fanyi_design["intro_h"] - intro_h

            # 4) 演员组：容器按网格 sizeHint 收紧（行首留白已折进 topMargin，
            #    留白 0 时首行行顶 = 容器设计 y，标题下方不再空一整行）。
            actor_lw_h = g_actor.sizeHint().height()
            lw20.setGeometry(lw20.x(), lw20.y(), lw20.width(), actor_lw_h)
            actor_h = lw20.y() + actor_lw_h + self._FANYI_BOX_BOT_PAD
            actor_y = self._fanyi_design["groups"]["groupBox_84"] - delta_trans - delta_intro
            actor.setGeometry(actor.x(), actor_y, actor.width(), actor_h)
            delta_actor = self._fanyi_design["actor_h"] - actor_h

            # 5) 后续组按累计收缩量上移（设计基准 + 增量，反复调用不漂移）。
            for name in self._FANYI_FOLLOW_GROUPS[1:]:
                group = getattr(ui, name)
                group.move(
                    group.x(),
                    self._fanyi_design["groups"][name] - delta_trans - delta_intro - delta_actor,
                )

            # 宽幅登记表里存的是设计几何，同步宽度时会按登记值复位这些控件，
            # 这里只把 y/h 写回登记（与命名页画质组同一处理）。
            #
            # 设计宽度必须原样取回登记值（entry.geometry[2]），绝不能写
            # intro.width()/actor.width()：那读到的是「上一轮宽幅同步已拉伸后的
            # 当前宽」，把它当设计宽存回去，下一轮宽幅同步就会再加一次 extra，
            # 宽度无界增长（离屏实测：每次窗口缩放两组框宽 +1216px，几轮后
            # 简介/演员框飞出窗口右缘，右侧大片空白）。设计宽度是登记表的唯一
            # 真值来源，只在 setupUi 的 setWidget 时刻采集过一次。
            registry = getattr(ui.scrollAreaWidgetContents_fanyi, "_wide_children_design", None)
            # 本方法接管过的组：连 y 一起写回登记。y 也要写——组一收紧，后续组
            # 的设计位就整体上移了（翻译引擎 −44、简介/演员各自再减），登记里若
            # 仍留设计 y，宽幅同步会把它们按旧位复位，本方法与宽幅同步的先后
            # 顺序就成了隐性依赖。
            managed = {trans, intro, actor}
            for name in (*self._FANYI_TRANS_FOLLOW_GROUPS, *self._FANYI_FOLLOW_GROUPS):
                managed.add(getattr(ui, name))
            for entry in registry or ():
                if entry.widget in managed:
                    ex, _ey, ew, _eh = entry.geometry
                    entry.geometry = (ex, entry.widget.y(), ew, entry.widget.height())
                # 组内绝对定位的容器：登记 y/h，避免宽幅同步按设计值把收紧后的
                # 高度又撑回去（那会让本方法与宽幅同步的先后顺序成为隐性依赖）。
                for item in entry.inner:
                    if item.widget is lw2:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, lw2.y(), iw, trans_lw_h)
                    elif item.widget is lw13:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, lw13.y(), iw, intro_lw_h)
                    elif item.widget is lw20:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, lw20.y(), iw, actor_lw_h)
                    elif item.widget is frame:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, frame.y(), iw, frame.height())

            scroll = getattr(ui, "scrollArea_11", None)
            self._sync_fanyi_trans_align(scroll)
            if scroll is not None:
                scroll.sync_content_min_height()
        finally:
            self._fanyi_resyncing = False

    def _sync_fanyi_trans_align(self, scroll=None) -> None:
        """设置-翻译页：窄态四个目标左移到锚点列；宽态（最大化）四个目标对到锚点列。

        用户需求（窄态/最小化，保持此前行为不变）：「显示翻译来源」与「日语+中文」
        左移到与「中文繁体」（radioButton_outline_zh_tw，保持不动）严格上下对齐；
        「使用演员映射表翻译演员」左移到与「中文繁体」对齐（锚点为
        radioButton_actor_zh_tw，保持不动）；「关闭」
        （radioButton_trans_show_one）左移到与「日语」
        （radioButton_outline_jp，保持不动）严格上下对齐。

        用户需求（宽态/最大化，翻译页其余布局、控件、提示词等保持不变）：
        「显示翻译来源」「使用演员映射表翻译演员」向左移动到与「中文繁体」
        上下严格对齐（中文繁体不动）；「日语+中文」向右移动到与「中文繁体」
        严格上下对齐，「关闭」向右移动到与「日语」严格上下对齐（中文繁体、
        日语不动）。即四个目标的 content-x 与各自锚点完全相等，方向不限。

        做法：
          - 窄态（拉伸量 <= 0）：沿用此前逻辑——只允许左移，右推/已对齐则放弃；
            若宽态加宽/钉宽过双语显示行容器与三个单选，先交还设计值（见下）。
          - 宽态：四个目标按锚点 content-x 精确对齐（双向）。两个复选框的父容器
            （layoutWidget_13/20）会被通用宽幅同步拉宽，目标落在容器内，无需
            处理；但「双语显示」行的 frame_5（设计 661）与 layoutWidget_24
            （设计 521）是绝对定位、通用同步不拉宽——直接 move() 会把单选框钉
            到父容器之外导致裁剪（子控件超出父矩形不绘制）。故先把 frame_5 加宽
            到组宽（组宽 − 左右各 20px 设计边距），layoutWidget_24 加宽到
            frame 宽 − 140（设计：frame 内 x=140、右缘贴齐），再 activate。
            加宽后 HBox 会把多余宽度均分到三个单选身上（离屏实测横向三单选会被
            拉到 460 宽），「中文+日语」会被拉宽变形、其余两项位置也算不准，
            故把三个单选的宽度钉为自然宽（sizeHint，与字号/缩放自适应），HBox
            把它们顶左排列，「中文+日语」保持自然大小不动；再 move() 目标到锚点。
          - 经 content 中转量锚点与目标的绝对 x 差值（QWidget.mapTo 要求目标是
            调用者的祖先，跨分支直接映射会拿到未定义值，故一律经 content 中转），
            目标 move() 到锚点 x（只改 x 不碰 y/宽高；越出父级则放弃；布局容器
            后续 activate 会按设计复位，还原不依赖本方法，每遍重钉故双向幂等）。
        休眠页跳过。
        """
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        if scroll is None:
            scroll = getattr(ui, "scrollArea_11", None)
        box = getattr(ui, "groupBox_83", None)
        if box is None or not box.isVisibleTo(self):
            return
        content = scroll.widget() if scroll is not None else box.parentWidget()
        if content is None:
            return
        pairs = (
            ("radioButton_outline_zh_tw", "checkBox_show_translate_from"),
            ("radioButton_outline_zh_tw", "radioButton_trans_show_jp_zh"),
            ("radioButton_outline_jp", "radioButton_trans_show_one"),
            ("radioButton_actor_zh_tw", "checkBox_actor_translate"),
        )
        wide = self._scroll_stretch_extra(scroll) > 0
        if wide:
            self._widen_fanyi_bilingual_row()
        else:
            self._restore_fanyi_bilingual_row()
        for anchor_name, target_name in pairs:
            anchor = getattr(ui, anchor_name, None)
            target = getattr(ui, target_name, None)
            if anchor is None or target is None:
                continue
            if target.parentWidget() is None or anchor.parentWidget() is None:
                continue
            dx = anchor.mapTo(content, anchor.rect().topLeft()).x() - target.mapTo(content, target.rect().topLeft()).x()
            if not wide and dx >= 0:
                continue  # 窄态只允许左移，右推/已对齐则放弃；宽态按锚点精确对齐
            g = target.geometry()
            nx = g.x() + dx
            if nx < 0 or nx + g.width() > target.parentWidget().width():
                continue  # 越出父级则保持通用逻辑给出的位置
            if dx:
                target.move(nx, g.y())
        if wide:
            # 「中文+日语」保持设计位置（父容器内 x=0、自然宽）：加宽后 HBox 会把
            # 多余空间均分成前后间隙把它顶到中间（离屏实测 x=288），此处每遍钉回。
            first = getattr(ui, "radioButton_trans_show_zh_jp", None)
            if first is not None and first.x() != 0:
                first.move(0, first.y())

    # 「双语显示」行在 .ui 里的设计几何（frame_5：组内 x=20 w=661；
    # layoutWidget_24：frame 内 x=140 w=521，右缘贴齐 frame 右缘）。
    _FANYI_BILINGUAL_FRAME_W = 661
    _FANYI_BILINGUAL_LW_W = 521
    _FANYI_BILINGUAL_LW_X = 140
    _FANYI_BILINGUAL_RADIOS = (
        "radioButton_trans_show_zh_jp",  # 中文+日语（保持自然大小不动，只钉宽防 HBox 拉伸）
        "radioButton_trans_show_jp_zh",  # 日语+中文
        "radioButton_trans_show_one",  # 关闭
    )

    def _widen_fanyi_bilingual_row(self) -> None:
        """宽态：加宽「双语显示」行容器并把三个单选钉为自然宽（见 trans_align）。"""
        ui = self.Ui
        frame, lw = ui.frame_5, ui.layoutWidget_24
        want_frame_w = ui.groupBox_83.width() - 2 * 20
        if frame.width() != want_frame_w:
            frame.resize(want_frame_w, frame.height())
        want_lw_w = frame.width() - self._FANYI_BILINGUAL_LW_X
        if lw.width() != want_lw_w:
            lw.resize(want_lw_w, lw.height())
        if lw.layout() is not None:
            lw.layout().invalidate()
            lw.layout().activate()
        for name in self._FANYI_BILINGUAL_RADIOS:
            radio = getattr(ui, name, None)
            if radio is None:
                continue
            natural = radio.sizeHint().width()
            if radio.minimumWidth() != natural or radio.maximumWidth() != natural:
                radio.setFixedWidth(natural)

    def _restore_fanyi_bilingual_row(self) -> None:
        """窄态：把宽态加宽/钉宽过的容器与单选交还设计值（幂等，数值相符即 no-op）。"""
        ui = self.Ui
        frame, lw = ui.frame_5, ui.layoutWidget_24
        if frame.width() != self._FANYI_BILINGUAL_FRAME_W:
            frame.resize(self._FANYI_BILINGUAL_FRAME_W, frame.height())
        if lw.width() != self._FANYI_BILINGUAL_LW_W:
            lw.resize(self._FANYI_BILINGUAL_LW_W, lw.height())
        if lw.layout() is not None:
            lw.layout().invalidate()
            lw.layout().activate()
        for name in self._FANYI_BILINGUAL_RADIOS:
            radio = getattr(ui, name, None)
            if radio is None:
                continue
            # .ui 里三个单选均无 maximumSize 约束、minimumWidth 均为 0
            # （trans_show_jp_zh 另有 minimumHeight 30，那是高度方向，此处不动）。
            if radio.minimumWidth() != 0 or radio.maximumWidth() != 16777215:
                radio.setMinimumWidth(0)
                radio.setMaximumWidth(16777215)

    # ============ 设置-命名页（画质组 groupBox_65）的间距收紧常量 ============
    # 网格容器与 QHD 说明、说明与分辨率行、分辨率行与末端添加4K行、末端添加4K行与
    # definition 说明之间的保留间距，以及组底留白。设计值里网格容器 77px
    # （两行内容只要约 46px，多出的 30px 被 Qt 均分到顶/行间/底）、QHD 说明
    # 固定 41px（窄态两行刚好，最大化时文字只占一行、剩下一半空白），HD 行到
    # 分辨率行之间看着太松。运行时按内容收紧后组高同步收缩。
    #
    # 用户截图标注（最大化态）：QHD 说明「向上移动一行」、分辨率行及以下
    # 「向上移动两行」、多出来的三行空间删掉。折成像素就是这三处预留间距
    # （10 / 7 / 9）+ frame_6 的居中余量（设计 46 − 内容 32 = 14）
    # = 40px ≈ 三行单行文字高，故全部归零：网格底与说明贴合、分辨率行与
    # 末端添加4K行贴合、末端添加4K行与尾说明贴合。组底留白 25px 是用户明确要求
    # 不动的（definition 说明下方空白不增加）。
    #
    # 随后用户改口：「分辨率获取方式：」及它下方的内容**向下移动一行**。故
    # 说明与分辨率行之间恢复一整行行高（_DEFN_NOTE_GAP = -1 → 按 label_331
    # 字体实测 lineSpacing 取值）。再后来要求尾说明（label_358）单独再下移
    # 一行，于是末端添加4K行与尾说明之间也恢复一整行行高（_DEFN_TAIL_GAP = -1
    # → 按 label_358 字体实测 lineSpacing 取值）。最后要求「末端添加4K字符」行
    # 单独再下移一行，于是分辨率行与末端添加4K行之间同样恢复一整行行高
    # （_DEFN_FRAME_GAP = -1 → 按 frame_6 内 radio 字体实测 lineSpacing 取值）。
    # 三处都按字体实测而非写死，用户机器字号比离屏大，写死会少一半；组内自上
    # 而下串联，故每一处下移会把其下方所有行一起带下去。
    _DEFN_GRID_GAP = 0  # 网格容器底 → label_331 顶（说明紧贴 HD 行）
    # label_331 底 → frame_6 顶：用户要求「分辨率获取方式：」及其下方内容整体
    # 向下移动一行，故这里留一整行文字高（此前为 0，四处全贴合）。取 label_331
    # 字体的实测行高而非写死数值——用户机器字号比离屏大，写死会少一半。
    _DEFN_NOTE_GAP = -1  # -1 = 用 label_331 的一行行高（见下方 note_gap 解析）
    # frame_6 底 → 末端添加4K行顶：用户要求「末端添加4K字符」行再向下移动一行，取
    # frame_6 内 radio 的实测行高（与前两处同理按字体实测，不写死）。
    _DEFN_FRAME_GAP = -1  # -1 = 用 radioButton_videosize_video 的一行行高
    # 末端添加4K行底 → label_358 顶：用户要求尾说明（指命名时在番号后添加4K…）
    # 「向下移动一行的宽度」= 也空出一整行文字高。与 _DEFN_NOTE_GAP 同理按
    # label_358 字体实测 lineSpacing 取值，不写死。
    _DEFN_TAIL_GAP = -1  # -1 = 用 label_358 的一行行高（见下方 tail_gap 解析）
    _DEFN_BOX_BOT_PAD = 25  # label_358 底 → 组底（与设计一致，下方空白不增加）
    _DEFN_GROUP_GAP = 19  # 组底 → groupBox_67 顶（命名页统一 19px 间距）
    # 末端添加4K行内复选框相对行标签的下沉量（设计：标签 y218，复选框 y221）。
    _DEFN_ROW_CHECK_DY = 3

    def _sync_definition_group_spacing(self) -> None:
        """设置-命名页：画质组按内容收紧 HD 行到分辨率获取方式的间距。

        现象（用户截图）：「HD、FHD、QHD、UHD」行与「分辨率获取方式」行之间太松，
        最大化与最小化都要收。静态改 .ui 只能顾一态：label_331 固定高度在窄态
        两行刚好，最大化时文字只占一行就剩下一半空白。
        做法（与 _sync_fanyi_group_spacing 同款：解除固定高度 → 量真实需要高度 →
        重新钉上 → 其余行按固定间距串起来 → 组高同步收缩 → 后续组上移；全程按
        当前几何与实测值推导，幂等不累积漂移）：
          1) 网格容器钉到 sizeHint（不给 Qt 均分空间，两行单选贴紧）；
          2) label_331 按**墨迹**高度贴合（最大化单行、最小化双行，各自刚好；
             级联中途标签内部还是陈旧折行，eventFilter 的 label_331 分支会多跑
             几遍直到收敛，label_66 同款）；
          3) 组高 = definition 说明底 + 固定底留白（下方空白与设计一致不增加）；
          4) groupBox_67（其他说明，组内唯一后续组）按新组底 + 19px 间距上移；
          5) 同步更新宽幅登记表里的高度/位置（只换 y/h，设计宽度原样保留，
             否则下一次宽幅同步会把 extra 加重），最后 sync_content_min_height
             收紧内容（否则页尾留白）。
        """
        ui = getattr(self, "Ui", None)
        if ui is None or self._defn_resyncing:
            return
        box = ui.groupBox_65
        # 休眠页零成本：命名 tab 不可见时视口宽度不是终态，量到的折行数不对，
        # 切页 showEvent + beats 会补齐（翻译组同款）。
        if not box.isVisibleTo(self):
            return
        grid = ui.gridLayout_43
        lw = ui.gridLayoutWidget_35
        note = ui.label_331
        frame = ui.frame_6
        row_label = ui.label_357
        check_f = ui.checkBox_foldername_4k
        check_n = ui.checkBox_filename_4k
        tail = ui.label_358
        follower = ui.groupBox_67
        if note.width() <= 0:
            return

        self._defn_resyncing = True
        try:
            # 1) 解除固定高度 → 量真实需要高度 → 重新钉上。
            #    量之前必须先解除上一轮的固定高度，否则标签仍被裁着，量到的只是
            #    残缺高度（会越量越小、最后裁字，-template/翻译两组同款教训）。
            note.setMinimumHeight(0)
            note.setMaximumHeight(16777215)
            grid.invalidate()
            grid.activate()
            grid_h = grid.sizeHint().height()
            # 说明文字按当前宽度重排量出真实需要高度（_label_ink_height_for_width：
            # 纯宽度函数、不掺标签自身高度，故不会每轮 +2 漂移；painted 回扫法在
            # 非纯白背景下退化成恒等函数，不能用，见其 docstring）。量墨迹而非
            # 行盒，用户圈出的两段空白正是「行盒底 - 墨迹底」的差。最大化单行、
            # 最小化双行，各自刚好。
            note_h = self._label_ink_height_for_width(note)
            # 「末端添加4K字符：」行标签同样是垂直居中，30px 行里墨迹只有 8px、
            # 上下各空 10px（用户圈的位置2/位置3）。钉到墨迹高 + 4px，
            # 行高随后由单选/复选框的 minimumHeight（16px）决定。
            row_h = self._label_ink_height_for_width(row_label) + 4
            row_label.setFixedHeight(row_h)
            lw.setGeometry(lw.x(), lw.y(), lw.width(), grid_h)
            note.setFixedHeight(note_h)
            grid.invalidate()
            grid.activate()

            # 2) 其余行按固定间距串起来（x/宽不动，只动 y；宽度归宽幅同步管）。
            #    frame_6 是无布局的 QFrame（三个单选装在 layoutWidget_26 里），
            #    设计 46px 里只有 32px 是内容、14px 是 Qt 垂直居中白给的余量。
            #    按内部布局 sizeHint 钉死高度、内容贴顶、行标签垂直居中——量的是
            #    布局而不是写死 32，窄态单选折行时不会裁字。
            frame_lw = ui.layoutWidget_26
            frame_layout = ui.horizontalLayout_112
            frame_layout.invalidate()
            frame_layout.activate()
            frame_h = max(frame_layout.sizeHint().height(), frame_lw.sizeHint().height())
            frame_lw.setGeometry(frame_lw.x(), 0, frame_lw.width(), frame_h)
            frame_tag = ui.label_332
            frame_tag.move(frame_tag.x(), max((frame_h - frame_tag.height()) // 2, 0))
            note.move(note.x(), lw.y() + grid_h + self._DEFN_GRID_GAP)
            # 「向下移动一行」= 在说明与分辨率行之间插一整行文字高。label_358
            # （指命名时在番号后添加4K…）在 frame_6 下方，跟着 frame 一起下移，
            # 用户第二条要求自动满足。
            note_gap = self._DEFN_NOTE_GAP
            if note_gap < 0:
                note_gap = QFontMetrics(note.font()).lineSpacing()
            frame.setGeometry(frame.x(), note.y() + note_h + note_gap, frame.width(), frame_h)
            row_y = frame.y() + frame.height()
            # 「末端添加4K字符」行同样下移一行，行高取 frame_6 内 radio 的实测行高。
            frame_gap = self._DEFN_FRAME_GAP
            if frame_gap < 0:
                frame_gap = QFontMetrics(ui.radioButton_videosize_video.font()).lineSpacing()
            row_y += frame_gap
            row_label.move(row_label.x(), row_y)
            check_f.move(check_f.x(), row_y + self._DEFN_ROW_CHECK_DY)
            check_n.move(check_n.x(), row_y + self._DEFN_ROW_CHECK_DY)
            tail_gap = self._DEFN_TAIL_GAP
            if tail_gap < 0:
                tail_gap = QFontMetrics(tail.font()).lineSpacing()
            tail_y = row_y + max(row_h, check_f.height(), check_n.height()) + tail_gap
            tail.move(tail.x(), tail_y)
            box_h = tail_y + tail.height() + self._DEFN_BOX_BOT_PAD
            box.setGeometry(box.x(), box.y(), box.width(), box_h)
            follower.move(follower.x(), box.y() + box_h + self._DEFN_GROUP_GAP)

            # 3) 宽幅登记表里存的是设计几何，同步宽度时会按登记值复位这些控件，
            #    这里把登记的 y/h 一并更新（设计宽度原样保留，只换 y/h）。
            registry = getattr(ui.scrollAreaWidgetContents_mingming, "_wide_children_design", None)
            for entry in registry or ():
                if entry.widget is box:
                    ex, ey, ew, _eh = entry.geometry
                    entry.geometry = (ex, ey, ew, box_h)
                    continue
                for item in entry.inner:
                    if item.widget is lw:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, lw.y(), iw, grid_h)
                    elif item.widget is note:
                        ix, _iy, iw, _ih = item.geometry
                        item.geometry = (ix, note.y(), iw, note_h)
                    elif item.widget is frame:
                        ix, _iy, iw, _ih = item.geometry
                        # 高度换成实测的 frame_h：宽幅同步会按登记高度复位 frame_6，
                        # 留设计 46 的话每次缩放都会把收紧效果又撑回去 14px。
                        item.geometry = (ix, frame.y(), iw, frame_h)
                    elif item.widget is tail:
                        ix, _iy, iw, ih = item.geometry
                        item.geometry = (ix, tail.y(), iw, ih)

            scroll = getattr(ui, "scrollArea_7", None)
            if scroll is not None:
                scroll.sync_content_min_height()
        finally:
            self._defn_resyncing = False

    # 当隐藏边框时，最小化后，点击任务栏时，需要监听事件，在恢复窗口时隐藏边框
    def changeEvent(self, a0):
        # self.show_traceback_log(QEvent.WindowStateChange)
        # WindowState （WindowNoState=0 正常窗口; WindowMinimized= 1 最小化;
        # WindowMaximized= 2 最大化; WindowFullScreen= 3 全屏;WindowActive= 8 可编辑。）
        # windows平台无问题，仅mac平台python版有问题
        # 议题：最大化/还原时 resizeEvent 中 isMaximized() 时序不可靠（状态位尚未更新），
        # 在窗口状态变更事件后延迟一帧重算布局，确保统计标签 y 坐标正确跟随最大化状态
        if a0.type() == QEvent.Type.WindowStateChange:
            # 延迟一帧后状态位才可靠，此时**必须重算侧栏**：_layout_donate 用
            # isMaximized() 决定是否在微信码上方加支付宝码，而 resizeEvent 那一拍
            # 窗口管理器「先发尺寸、后发状态」，isMaximized() 还是 False，只靠
            # resizeEvent 会导致最大化后支付宝码始终不出现（用户反馈「最大化没变化」）
            QTimer.singleShot(0, self._sync_page_layouts)
            QTimer.singleShot(0, self._sync_dock_layout)
        if (
            not IS_WINDOWS
            and self.window_radius
            and a0.type() == QEvent.Type.WindowStateChange
            and self.windowState() == Qt.WindowState.WindowNoState
        ):
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)  # 隐藏边框
            self.show()

        # activeAppName = AppKit.NSWorkspace.sharedWorkspace().activeApplication()['NSApplicationName'] # 活动窗口的标题

    def closeEvent(self, a0):
        if Switch.HIDE_CLOSE in manager.config.switch_on:
            self.hide()
            # 主窗口收起时把预览窗口连带关闭，不留孤儿窗口在屏幕/任务栏上
            preview = getattr(self, "nfo_lib_preview_window", None)
            if preview is not None:
                preview.close()
        else:
            self.ready_to_exit()
        if a0:
            a0.ignore()

    # 显示与隐藏窗口标题栏
    def _windows_auto_adjust(self):
        if manager.config.window_title == "hide":  # 隐藏标题栏
            if self.window_radius == 0:
                self.show_flag = True
            self.window_radius = 5
            if IS_WINDOWS:
                self.window_border = 1
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            else:
                self.window_border = 0
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)  # 隐藏标题栏
            self.Ui.pushButton_close.setVisible(True)
            self.Ui.pushButton_min.setVisible(True)
            self.Ui.widget_buttons.move(0, 50)

        else:  # 显示标题栏
            if self.window_radius == 5:
                self.show_flag = True
            self.window_radius = 0
            self.window_border = 0
            self.window_marjin = 0
            if IS_WINDOWS:
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)  # 显示标题栏
            self.Ui.pushButton_close.setVisible(False)
            self.Ui.pushButton_min.setVisible(False)
            self.Ui.widget_buttons.move(0, 20)

        if bool(self.dark_mode != self.Ui.checkBox_dark_mode.isChecked()):
            self.show_flag = True
            self.dark_mode = self.Ui.checkBox_dark_mode.isChecked()

        if self.show_flag:
            self.show_flag = False
            self.set_style()  # 样式美化
            apply_site_priority_theme(self)
            self._style_donate_link()  # 暗黑/亮色切换时同步 [赞助作者] 链接颜色

            # self.setWindowState(Qt.WindowNoState)                               # 恢复正常窗口
            self.show()
            self._change_page()

    def _change_page(self):
        page = int(self.Ui.stackedWidget.currentIndex())
        if page == 0:
            self.pushButton_main_clicked()
        elif page == 1:
            self.pushButton_show_log_clicked()
        elif page == 2:
            self.pushButton_show_net_clicked()
        elif page == 3:
            self.pushButton_tool_clicked()
        elif page == 4:
            self.pushButton_setting_clicked()
        elif page == 5:
            self.pushButton_about_clicked()

    def set_style(self): ...

    def set_dark_style(self): ...

    def _bind_system_theme_refresh(self) -> None:
        try:
            style_hints = QGuiApplication.styleHints()
            if style_hints is not None:
                style_hints.colorSchemeChanged.connect(lambda *_args: apply_application_palette(self.dark_mode))
        except Exception:
            pass

    # region 拖动窗口
    # 按下鼠标
    def mousePressEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.m_drag = True
            self.m_DragPosition = a0.globalPosition().toPoint() - self.pos()
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))  # 按下左键改变鼠标指针样式为手掌

    # 松开鼠标
    def mouseReleaseEvent(self, a0):
        if a0 and a0.button() == Qt.MouseButton.LeftButton:
            self.m_drag = False
            self.m_DragPosition = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))  # 释放左键改变鼠标指针样式为箭头

    # 拖动鼠标
    def mouseMoveEvent(self, a0):
        if a0 and self.m_drag and self.m_DragPosition is not None and a0.buttons() & Qt.MouseButton.LeftButton:
            self.move(a0.globalPosition().toPoint() - self.m_DragPosition)
            a0.accept()
        else:
            self.m_drag = False
            self.m_DragPosition = None
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    # endregion

    # region 关闭
    # 关闭按钮点击事件响应函数
    def pushButton_close_clicked(self):
        self._user_initiated_close = True
        if Switch.HIDE_CLOSE in manager.config.switch_on:
            self.hide()
        else:
            self.ready_to_exit()

    def ready_to_exit(self):
        if Switch.SHOW_DIALOG_EXIT in manager.config.switch_on:
            if not self.isVisible():
                self.show()
            if self.windowState() & Qt.WindowState.WindowMinimized:
                self.showNormal()

            # print(self.window().isActiveWindow()) # 是否为活动窗口
            self.raise_()
            box = QMessageBox(QMessageBox.Icon.Warning, "退出", "确定要退出吗？")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.button(QMessageBox.StandardButton.Yes).setText("退出 MDCx")
            box.button(QMessageBox.StandardButton.No).setText("取消")
            box.setDefaultButton(QMessageBox.StandardButton.No)
            reply = box.exec()
            if reply != QMessageBox.StandardButton.Yes:
                self.raise_()
                self.show()
                return
        self.exit_app()

    # 关闭窗口
    def exit_app(self):
        show_poster = manager.config.show_poster
        switch_on = manager.config.switch_on
        need_save_config = False

        if self.Ui.checkBox_cover.isChecked() != show_poster:
            manager.config.show_poster = self.Ui.checkBox_cover.isChecked()
            need_save_config = True
        if self.Ui.textBrowser_log_main_2.isHidden() == (Switch.SHOW_LOGS in switch_on):
            if self.Ui.textBrowser_log_main_2.isHidden():
                manager.config.switch_on.remove(Switch.SHOW_LOGS)
            else:
                manager.config.switch_on.append(Switch.SHOW_LOGS)
            need_save_config = True
        if need_save_config:
            try:
                manager.save()
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())
        if hasattr(self, "preview_image_loader"):
            self.preview_image_loader.shutdown()
        if hasattr(self, "tray_icon"):
            self.tray_icon.hide()
        signal_qt.show_traceback_log("\n\n\n\n************ 程序正常退出！************\n")
        QApplication.quit()

    # endregion

    # 最小化窗口
    def pushButton_min_clicked(self):
        if Switch.HIDE_MINI in manager.config.switch_on:
            self.hide()
            return
        # mac 平台 python 版本 最小化有问题，此处就是为了兼容它，需要先设置为显示窗口标题栏才能最小化
        if not IS_WINDOWS:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)  # 不隐藏边框

        # self.setWindowState(Qt.WindowState.WindowMinimized)
        # self.show_traceback_log(self.isMinimized())
        self.showMinimized()

    def pushButton_min_clicked2(self):
        if not IS_WINDOWS:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)  # 不隐藏边框
            # self.show()  # 加上后可以显示缩小动画
        self.showMinimized()

    # 重置左侧按钮样式
    def set_left_button_style(self):
        try:
            if self.dark_mode:
                self.Ui.left_backgroud_widget.setStyleSheet(
                    f"background: #1F272F;border-right: 1px solid #20303F;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
                )
                self.Ui.pushButton_main.setStyleSheet(
                    "QPushButton:hover#pushButton_main{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_log.setStyleSheet(
                    "QPushButton:hover#pushButton_log{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_net.setStyleSheet(
                    "QPushButton:hover#pushButton_net{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_tool.setStyleSheet(
                    "QPushButton:hover#pushButton_tool{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_emby_manager_nav.setStyleSheet(
                    "QPushButton:hover#pushButton_emby_manager_nav{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_nfo_library.setStyleSheet(
                    "QPushButton:hover#pushButton_nfo_library{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_setting.setStyleSheet(
                    "QPushButton:hover#pushButton_setting{color: white;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_about.setStyleSheet(
                    "QPushButton:hover#pushButton_about{color: white;background-color: rgba(160,160,165,40);}"
                )
            else:
                self.Ui.pushButton_main.setStyleSheet(
                    "QPushButton:hover#pushButton_main{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_log.setStyleSheet(
                    "QPushButton:hover#pushButton_log{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_net.setStyleSheet(
                    "QPushButton:hover#pushButton_net{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_tool.setStyleSheet(
                    "QPushButton:hover#pushButton_tool{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_emby_manager_nav.setStyleSheet(
                    "QPushButton:hover#pushButton_emby_manager_nav{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_nfo_library.setStyleSheet(
                    "QPushButton:hover#pushButton_nfo_library{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_setting.setStyleSheet(
                    "QPushButton:hover#pushButton_setting{color: black;background-color: rgba(160,160,165,40);}"
                )
                self.Ui.pushButton_about.setStyleSheet(
                    "QPushButton:hover#pushButton_about{color: black;background-color: rgba(160,160,165,40);}"
                )
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # endregion

    # region 显示版本号
    def show_version(self):
        try:
            t = threading.Thread(target=self._show_version_thread)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _show_version_thread(self):
        version_info = f"基于 MDC-GUI 修改 当前版本: {self.version_display}"
        download_link = ""
        has_new_version = False
        latest_version = check_version()
        if latest_version:
            # 版本号(vX.Y.Z)与日期(YYYYMMDD tag)同时对比：任一更新即视为有新版本，
            # 版本号相等时由日期决出。详见 is_remote_version_newer。
            if is_remote_version_newer(latest_version, self.localversion, VERSION_NAME):
                has_new_version = True
                # 定时复查与启动自检共用本函数：仅在首次发现该新版本时提示
                # （红字日志、下载链接与左下角标签刷新），同一版本重复检查
                # 不再刷屏；出现更新的版本时会自动再次提示。
                if latest_version != self._notified_new_version:
                    self._notified_new_version = latest_version
                    # 左下角提示格式「有新版本了！（日期tag）」：保留 🍉 图标与感叹号，只显示日期 tag 全角括号红字。
                    self.new_version = f'\n🍉 有新版本了！<font color="red">（{latest_version.tag}）</font>'
                    signal_qt.show_scrape_info()
                    version_info = f'基于 MDC-GUI 修改 · 当前版本: {self.version_display} （ <font color="red" >最新版本是: {latest_version.display}，请及时更新！🚀 </font>）'
                    download_link = f' ⬇️ <a href="{GITHUB_RELEASES_URL}">下载新版本</a>'
            else:
                version_info = f'基于 MDC-GUI 修改 · 当前版本: {self.version_display} （ <font color="green">你使用的是最新版本！🎉 </font>）'

        feedback = f' 💌 问题反馈: <a href="{GITHUB_ISSUES_URL}">GitHub Issues</a>'

        # 显示版本信息和反馈入口
        signal_qt.show_log_text(version_info)
        if feedback or download_link:
            self.main_logs_show.emit(f"{feedback}{download_link}")
        signal_qt.show_log_text("============================================================================================================")
        # 议题 #73: 用户误以为启动自检在某项失败后"停止检测"。声明自检范围与
        # 全量检测入口, 避免混淆（全量检测在「检测网络」页, 单站失败互相独立）。
        signal_qt.show_log_text(
            " 启动自检：数据库/ThePornDB/JavDb/JavBus/FC2PPVDB连通性，如需检测全部站点，请到左侧「检测网络」页点击开始检测"
        )
        # QWidget 与 cookie 检查必须在主线程执行：通过信号调度回主线程
        self.version_check_done.emit(has_new_version)
        if manager.config.use_database:
            ActressDB.init_db()
        try:
            t = threading.Thread(target=check_theporndb_api_token)
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _on_version_check_done(self, has_new_version: bool):
        """主线程：版本检查完成后的 UI 更新与 cookie 检测。"""
        if has_new_version:
            self.Ui.label_show_version.setCursor(Qt.CursorShape.OpenHandCursor)  # 设置鼠标形状为十字形
        self.pushButton_check_javdb_cookie_clicked()  # 检测javdb cookie
        self.pushButton_check_javbus_cookie_clicked()  # 检测javbus cookie
        # 议题 #130：启动时也检测 FC2PPVDB cookie 有效性（未填写时该函数直接返回，不发请求）
        self.pushButton_check_fc2ppvdb_cookie_clicked()  # 检测fc2ppvdb cookie

    # endregion

    # region 各种点击跳转浏览器
    def label_version_clicked(self, ev):
        try:
            webbrowser.open(GITHUB_RELEASES_URL)
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # endregion

    # region 左侧切换页面
    # 点左侧的主界面按钮
    def pushButton_main_clicked(self):
        # 侧栏配色与「软件设置」页保持一致（#EEF3FF / 右边框 #D8E2FF）
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #EEF3FF;border-right: 1px solid #D8E2FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(0)
        self.set_left_button_style()
        self.Ui.pushButton_main.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # 点左侧的日志按钮
    def pushButton_show_log_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(1)
        self.set_left_button_style()
        self.Ui.pushButton_log.setStyleSheet(
            "font-weight: bold; background-color: rgba(160,160,165,60);"
        )  # self.Ui.textBrowser_log_main.verticalScrollBar().setValue(  #     self.Ui.textBrowser_log_main.verticalScrollBar().maximum())  # self.Ui.textBrowser_log_main_2.verticalScrollBar().setValue(  #     self.Ui.textBrowser_log_main_2.verticalScrollBar().maximum())

    # 点左侧的工具按钮
    def pushButton_tool_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(3)
        self.set_left_button_style()
        self.Ui.pushButton_tool.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # 点左侧的设置按钮
    def pushButton_setting_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #EEF3FF;border-right: 1px solid #D8E2FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(4)
        self.set_left_button_style()
        try:
            if self.dark_mode:
                self.Ui.pushButton_setting.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")
            else:
                self.Ui.pushButton_setting.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,100);")
            self._check_mac_config_folder()
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # 点击左侧【检测网络】按钮，切换到检测网络页面
    def pushButton_show_net_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(2)
        self.set_left_button_style()
        self.Ui.pushButton_net.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # 点左侧的关于按钮
    def pushButton_about_clicked(self):
        self.Ui.left_backgroud_widget.setStyleSheet(
            f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;border-bottom-left-radius: {self.window_radius}px;"
        )
        self.Ui.stackedWidget.setCurrentIndex(5)
        self.set_left_button_style()
        self.Ui.pushButton_about.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")

    # endregion

    # region NFO 库管理

    def pushButton_nfo_library_clicked(self):
        from .nfo_library import pushButton_nfo_library_clicked

        pushButton_nfo_library_clicked(self)

    def pushButton_nfo_lib_select_dir_clicked(self):
        from .nfo_library import pushButton_nfo_lib_select_dir_clicked

        pushButton_nfo_lib_select_dir_clicked(self)

    def pushButton_nfo_lib_select_all_clicked(self):
        from .nfo_library import pushButton_nfo_lib_select_all_clicked

        pushButton_nfo_lib_select_all_clicked(self)

    def pushButton_nfo_lib_select_none_clicked(self):
        from .nfo_library import pushButton_nfo_lib_select_none_clicked

        pushButton_nfo_lib_select_none_clicked(self)

    def pushButton_nfo_lib_refresh_clicked(self):
        from .nfo_library import pushButton_nfo_lib_refresh_clicked

        pushButton_nfo_lib_refresh_clicked(self)

    def lineEdit_nfo_lib_dir_return_pressed(self):
        from .nfo_library import lineEdit_nfo_lib_dir_return_pressed

        lineEdit_nfo_lib_dir_return_pressed(self)

    def listWidget_nfo_lib_item_clicked(self):
        from .nfo_library import listWidget_nfo_lib_item_clicked

        listWidget_nfo_lib_item_clicked(self)

    def pushButton_nfo_lib_save_clicked(self):
        from .nfo_library import pushButton_nfo_lib_save_clicked

        pushButton_nfo_lib_save_clicked(self)

    def on_nfo_lib_data_loaded(self, nfo_path_str: str):
        from .nfo_library import on_nfo_lib_data_loaded

        on_nfo_lib_data_loaded(self, nfo_path_str)

    def on_nfo_lib_images_changed(self, nfo_path_str: str):
        from .nfo_library import on_nfo_lib_images_changed

        on_nfo_lib_images_changed(self, nfo_path_str)

    def on_nfo_lib_save_done(self, nfo_path_str: str):
        from .nfo_library import on_nfo_lib_save_done

        on_nfo_lib_save_done(self, nfo_path_str)

    def lineEdit_nfo_lib_filter_changed(self):
        from .nfo_library import lineEdit_nfo_lib_filter_changed

        lineEdit_nfo_lib_filter_changed(self)

    def pushButton_nfo_lib_crop_clicked(self):
        from .nfo_library import pushButton_nfo_lib_crop_clicked

        pushButton_nfo_lib_crop_clicked(self)

    def nfo_lib_preview_clicked(self, kind: str):
        """单击信息管理页右侧预览图（kind = poster / thumb）：弹出大图窗口。"""
        from .nfo_library import nfo_lib_preview_clicked

        nfo_lib_preview_clicked(self, kind)

    def _on_nfo_lib_preview_nfo_index_changed(self, index: int):
        from .nfo_library import _on_nfo_lib_preview_nfo_index_changed

        _on_nfo_lib_preview_nfo_index_changed(self, index)

    def pushButton_nfo_lib_batch_actor_clicked(self):
        from .nfo_library import pushButton_nfo_lib_batch_actor_clicked

        pushButton_nfo_lib_batch_actor_clicked(self)

    def pushButton_nfo_lib_batch_add_tag_clicked(self):
        from .nfo_library import pushButton_nfo_lib_batch_add_tag_clicked

        pushButton_nfo_lib_batch_add_tag_clicked(self)

    def pushButton_nfo_lib_batch_del_tag_clicked(self):
        from .nfo_library import pushButton_nfo_lib_batch_del_tag_clicked

        pushButton_nfo_lib_batch_del_tag_clicked(self)

    def pushButton_nfo_lib_batch_series_clicked(self):
        from .nfo_library import pushButton_nfo_lib_batch_series_clicked

        pushButton_nfo_lib_batch_series_clicked(self)

    def pushButton_nfo_lib_batch_save_clicked(self):
        from .nfo_library import pushButton_nfo_lib_batch_save_clicked

        pushButton_nfo_lib_batch_save_clicked(self)

    def on_nfo_lib_batch_done(self, arg: str):
        from .nfo_library import on_nfo_lib_batch_done

        on_nfo_lib_batch_done(self, arg)

    def on_nfo_lib_batch_progress(self, text: str):
        from .nfo_library import on_nfo_lib_batch_progress

        on_nfo_lib_batch_progress(self, text)

    def listWidget_nfo_lib_context_menu(self, pos):
        from .nfo_library import listWidget_nfo_lib_context_menu

        listWidget_nfo_lib_context_menu(self, pos)

    # endregion

    # region 主界面
    # 开始刮削按钮
    def pushButton_start_scrape_clicked(self):
        text = self.Ui.pushButton_start_cap.text()
        if text == "开始":
            if not get_remain_list():
                start_new_scrape(FileMode.Default)
        elif text == "■ 停止":
            self.pushButton_stop_scrape_clicked()
        # text == "■ 停止中"：防抖——用户疯狂点击时静默忽略，避免重复触发 stop 流程

    # 停止确认弹窗
    def pushButton_stop_scrape_clicked(self):
        if Switch.SHOW_DIALOG_STOP_SCRAPE in manager.config.switch_on:
            box = QMessageBox(QMessageBox.Icon.Warning, "停止刮削", "确定要停止刮削吗？")
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.button(QMessageBox.StandardButton.Yes).setText("停止刮削")
            box.button(QMessageBox.StandardButton.No).setText("取消")
            box.setDefaultButton(QMessageBox.StandardButton.No)
            reply = box.exec()
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self.Ui.pushButton_start_cap.text() == "■ 停止":
            Flags.stop_requested = True
            signal_qt.stop = True
            executor.run(save_success_list())
            # 停止时立即持久化最新剩余任务，不能只依赖 1.5s 定时器
            # （停止后定时器保存到的可能是竞态旧快照，续刮会丢任务，议题 #98）
            save_remain_list_now()
            Flags.rest_time_convert_ = Flags.rest_time_convert
            Flags.rest_time_convert = 0
            self.Ui.pushButton_start_cap.setText(" ■ 停止中 ")
            self.Ui.pushButton_start_cap2.setText(" ■ 停止中 ")
            signal_qt.show_scrape_info("⛔️ 刮削停止中...")
            executor.cancel_async()  # 取消异步任务
            if not self.threads_list:
                self.stop_used_time = 0.0
                self.show_stop_info_thread()
                return
            t = threading.Thread(target=self._kill_threads)  # 关闭线程池
            t.start()

    # 显示停止信息
    def _show_stop_info(self):
        signal_qt.reset_buttons_status.emit()
        try:
            Flags.rest_time_convert = Flags.rest_time_convert_
            if Flags.stop_other:
                signal_qt.show_scrape_info("⛔️ 已手动停止！")
                signal_qt.show_log_text(
                    "⛔️ 已手动停止！\n================================================================================"
                )
                self.set_label_file_path.emit("⛔️ 已手动停止！")
                return
            signal_qt.exec_set_processbar.emit(0)
            end_time = time.time()
            used_time = str(round((end_time - Flags.start_time), 2))
            if Flags.scrape_done:
                average_time = str(round((end_time - Flags.start_time) / Flags.scrape_done, 2))
            else:
                average_time = used_time
            signal_qt.show_scrape_info("⛔️ 刮削已手动停止！")
            self.set_label_file_path.emit(
                f"⛔️ 刮削已手动停止！\n   已刮削 {Flags.scrape_done} 个视频, 还剩余 {Flags.total_count - Flags.scrape_done} 个! 刮削用时 {used_time} 秒"
            )
            signal_qt.show_log_text(
                f"\n ⛔️ 刮削已手动停止！\n 😊 已刮削 {Flags.scrape_done} 个视频, 还剩余 {Flags.total_count - Flags.scrape_done} 个! 刮削用时 {used_time} 秒, 停止用时 {self.stop_used_time} 秒"
            )
            signal_qt.show_log_text("================================================================================")
            signal_qt.show_log_text(
                " ⏰ Start time".ljust(13) + ": " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(Flags.start_time))
            )
            signal_qt.show_log_text(
                " 🏁 End time".ljust(13) + ": " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))
            )
            signal_qt.show_log_text(f"{' ⏱ Used time'.ljust(13)}: {used_time}S")
            signal_qt.show_log_text(f"{' 🍕 Per time'.ljust(13)}: {average_time}S")
            signal_qt.show_log_text("================================================================================")
            Flags.again_dic.clear()
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())
        finally:
            signal_qt.stop = False

    def show_stop_info_thread(
        self,
    ):
        t = threading.Thread(target=self._show_stop_info)
        t.start()

    # 关闭线程池和扫描线程
    def _kill_threads(self):
        Flags.total_kills = len(self.threads_list)
        Flags.now_kill = 0
        start_time = time.time()
        self.set_label_file_path.emit(f"⛔️ 正在停止刮削...\n   正在停止已在运行的任务线程（1/{Flags.total_kills}）...")
        signal_qt.show_log_text(
            f"\n ⛔️ {get_current_time()} 已停止添加新的刮削任务，正在停止已在运行的任务线程（{Flags.total_kills}）..."
        )
        signal_qt.show_traceback_log(f"⛔️ 正在停止正在运行的任务线程 ({Flags.total_kills}) ...")
        i = 0
        for each in self.threads_list:
            i += 1
            signal_qt.show_traceback_log(f"正在停止线程: {i}/{Flags.total_kills} {each.name} ...")
        signal_qt.show_traceback_log(
            "线程正在停止中，请稍后...\n 🍯 停止时间与线程数量及线程正在执行的任务有关，比如正在执行网络请求、文件下载等IO操作时，需要等待其释放资源。。。\n"
        )
        signal_qt.stop = True
        for each in self.threads_list:  # 线程池的线程
            kill_a_thread(each, timeout=0.0)

        # 对全部线程使用一个总等待窗口，避免线程数量放大停止耗时。
        wait_deadline = time.monotonic() + 12.0
        while any(each.is_alive() for each in self.threads_list) and time.monotonic() < wait_deadline:
            time.sleep(0.05)

        self.stop_used_time = get_used_time(start_time)
        stopped_count = sum(not each.is_alive() for each in self.threads_list)
        signal_qt.show_log_text(f" 🕷 已停止线程：{stopped_count}/{Flags.total_kills}")
        if stopped_count == Flags.total_kills:
            signal_qt.show_traceback_log(f"所有线程已停止！！！({self.stop_used_time}s)\n ⛔️ 刮削已手动停止！\n")
            signal_qt.show_log_text(f" ⛔️ {get_current_time()} 所有线程已停止！({self.stop_used_time}s)")
        else:
            remaining = ", ".join(each.name for each in self.threads_list if each.is_alive())
            signal_qt.show_traceback_log(f"线程停止超时({self.stop_used_time}s)：{remaining}")
            signal_qt.show_log_text(f" ⚠️ {get_current_time()} 线程停止超时：{remaining}")
        thread_remain_list = []
        [thread_remain_list.append(t.name) for t in threading.enumerate()]  # 剩余线程名字列表
        thread_remain = ", ".join(thread_remain_list)
        signal_qt.show_traceback_log(f"剩余线程 ({len(thread_remain_list)}): {thread_remain}")
        self.show_stop_info_thread()

    # 进度条
    def set_processbar(self, value):
        self.Ui.progressBar_scrape.setProperty("value", value)

    # region 刮削结果显示
    def _addTreeChild(self, result, filename):
        node = QTreeWidgetItem()
        node.setText(0, filename)
        if result == "succ":
            self.item_succ.addChild(node)
        else:
            self.item_fail.addChild(node)
        # self.Ui.treeWidget_number.verticalScrollBar().setValue(self.Ui.treeWidget_number.verticalScrollBar().maximum())
        # self.Ui.treeWidget_number.setCurrentItem(node)
        # self.Ui.treeWidget_number.scrollToItem(node)

    def _get_single_selected_entry(self) -> tuple[QTreeWidgetItem, str, ShowData, Path] | None:
        selected_entries = self._get_selected_entries()
        if len(selected_entries) != 1:
            return None
        return selected_entries[0]

    def _has_single_selected_result_item(self) -> bool:
        return self._get_single_selected_entry() is not None

    def _set_result_item_as_current_selection(self, item: QTreeWidgetItem) -> None:
        if item.text(0) in {"成功", "失败"}:
            return

        tree = self.Ui.treeWidget_number
        selected_items = tree.selectedItems()
        if item not in selected_items:
            tree.clearSelection()
            item.setSelected(True)
        model_index = tree.indexFromItem(item)
        if model_index.isValid():
            tree.selectionModel().setCurrentIndex(model_index, QItemSelectionModel.SelectionFlag.NoUpdate)

    def show_list_name(self, status: Literal["succ", "fail"], show_data: ShowData, real_number=""):
        # 添加树状节点
        self._addTreeChild(status, show_data.show_name)

        if not show_data.data.title:
            show_data.data.title = show_data.show_name
            show_data.data.number = real_number
        self.json_array[show_data.show_name] = show_data
        if not self._has_single_selected_result_item():
            self.show_name = show_data.show_name
            self.set_main_info(show_data)

    @staticmethod
    def _elide_label_two_lines(label, text: str, max_lines: int = 2) -> str:
        """议题 #154：把文本按标签当前宽度裁到最多两行，超出部分以省略号截断。

        简介/标签恒定 40px 高，最多显示两行；不同窗口宽度下每行容纳的字数不同，
        因此必须按实际宽度重算，最大化才能比最小化显示更多内容。
        """
        text = text or ""
        if not text:
            return text
        width = label.width()
        if width <= 0:
            return text
        metrics = label.fontMetrics()
        max_h = metrics.lineSpacing() * max_lines
        flags = int(Qt.TextFlag.TextWordWrap)
        # 用无界高度测量真实换行高度，再与两行上限比较（受限高度会把返回值截断）
        probe = QRect(0, 0, width, 1_000_000)
        if metrics.boundingRect(probe, flags, text).height() <= max_h:
            return text
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            candidate = text[:mid].rstrip() + "…"
            if metrics.boundingRect(probe, flags, candidate).height() <= max_h:
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip() + "…"

    def _set_main_two_line(self, label, text: str) -> None:
        label.setText(self._elide_label_two_lines(label, text))

    def _refresh_main_outline_tag(self) -> None:
        """议题 #154：窗口宽度变化后，按新宽度重算简介/标签的两行省略文本。"""
        ui = getattr(self, "Ui", None)
        if ui is None:
            return
        self._set_main_two_line(ui.label_outline, getattr(self, "_main_outline_text", ""))
        self._set_main_two_line(ui.label_tag, getattr(self, "_main_tag_text", ""))

    def set_main_info(self, show_data: "ShowData | None"):
        if show_data is not None:
            self.show_data = show_data
            file_info = show_data.file_info
            data = show_data.data
            other = show_data.other
            self.show_name = show_data.show_name
        else:
            file_info = FileInfo.empty()
            data = CrawlersResult.empty()
            other = OtherInfo.empty()
            self.show_name = None
        try:
            number = data.number
            self.Ui.label_number.setToolTip(number)
            if len(number) > 11:
                number = number[:10] + "……"
            self.Ui.label_number.setText(number)
            actor = str(data.actor)
            if data.all_actor and NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
                actor = str(data.all_actor)
            self.Ui.label_actor.setToolTip(actor)
            if number and not actor:
                actor = manager.config.actor_no_name
            if len(actor) > 10:
                actor = actor[:9] + "……"
            self.Ui.label_actor.setText(actor)
            self.file_main_open_path = file_info.file_path  # 文件路径

            title = data.title.split("\n")[0].strip(" :")
            self.Ui.label_title.setToolTip(title)
            if len(title) > 27:
                title = title[:25] + "……"
            self.Ui.label_title.setText(title)
            outline = str(data.outline)
            self._main_outline_text = outline
            self.Ui.label_outline.setToolTip(outline)
            self._set_main_two_line(self.Ui.label_outline, outline)
            tag = ", ".join(str(item) for item in data.tag) if isinstance(data.tag, list) else str(data.tag)
            self._main_tag_text = tag
            self.Ui.label_tag.setToolTip(tag)
            self._set_main_two_line(self.Ui.label_tag, tag)
            self.Ui.label_release.setText(str(data.release))
            self.Ui.label_release.setToolTip(str(data.release))
            if data.runtime:
                self.Ui.label_runtime.setText(str(data.runtime) + " 分钟")
                self.Ui.label_runtime.setToolTip(str(data.runtime) + " 分钟")
            else:
                self.Ui.label_runtime.setText("")
            self.Ui.label_director.setText(str(data.director))
            self.Ui.label_director.setToolTip(str(data.director))
            series = str(data.series)
            self.Ui.label_series.setToolTip(series)
            if len(series) > 32:
                series = series[:31] + "……"
            self.Ui.label_series.setText(series)
            self.Ui.label_studio.setText(data.studio)
            self.Ui.label_studio.setToolTip(data.studio)
            self.Ui.label_publish.setText(data.publisher)
            self.Ui.label_publish.setToolTip(data.publisher)
            self.Ui.label_poster.setToolTip("点击裁剪图片")
            self.Ui.label_thumb.setToolTip("点击裁剪图片")
            # 生成img_path，用来裁剪使用
            img_path = other.fanart_path if other.fanart_path and other.fanart_path.is_file() else other.thumb_path
            self.img_path = img_path
            if self.Ui.checkBox_cover.isChecked():  # 主界面显示封面和缩略图
                poster_path = other.poster_path
                thumb_path = other.thumb_path
                fanart_path = other.fanart_path
                if not (thumb_path and thumb_path.is_file()) and fanart_path and fanart_path.is_file():
                    thumb_path = fanart_path
                poster_from = data.poster_from
                cover_from = data.thumb_from
                self._request_preview_images(poster_path, thumb_path, poster_from, cover_from)
        except Exception:
            if not signal_qt.stop:
                signal_qt.show_traceback_log(traceback.format_exc())

    def _request_preview_images(
        self,
        poster_path: Path | None,
        thumb_path: Path | None,
        poster_from="",
        cover_from="",
        force_reload: bool = False,
    ) -> None:
        self.preview_request_id += 1
        if not poster_path or not poster_path.is_file():
            self.resize_label_and_setpixmap([False, "", "暂无封面图", 156, 220], None)
        if not thumb_path or not thumb_path.is_file():
            self.resize_label_and_setpixmap(None, [False, "", "暂无缩略图", 328, 220])
        self.preview_image_loader.load(
            self.preview_request_id,
            poster_path,
            thumb_path,
            poster_from,
            cover_from,
            force_reload=force_reload,
        )

    def _apply_preview_images(self, request_id: int, poster_pix: list, thumb_pix: list) -> None:
        if request_id != self.preview_request_id:
            return
        poster_text = poster_pix[2] if poster_pix[2] != "暂无封面图" else ""
        thumb_text = thumb_pix[2] if thumb_pix[2] != "暂无缩略图" else ""
        self.Ui.label_poster_size.setText((poster_text + " " + thumb_text).strip())
        self.resize_label_and_setpixmap(poster_pix, thumb_pix)

    def _on_request_preview_images(self, poster_path: str, thumb_path: str) -> None:
        """主线程：裁剪完成后刷新主界面预览（由 request_preview_images 信号触发）。"""
        self._request_preview_images(
            Path(poster_path) if poster_path else None,
            Path(thumb_path) if thumb_path else None,
            poster_from="cut",
            cover_from="local",
            force_reload=True,
        )

    def _rescale_preview_pixmaps(self) -> None:
        """议题 #144: 按 label 当前几何重渲染原图, 保证窗口缩放与图片显示同步。

        缩放规则 KeepAspectRatio(等比、不裁剪、居中留白由 QLabel 对齐负责),
        design 尺寸与原行为一致; 缓存为空(占位文本态)时跳过。
        """
        for src, label in (
            (self._poster_src_pixmap, self.Ui.label_poster),
            (self._thumb_src_pixmap, self.Ui.label_thumb),
        ):
            if src is None or src.isNull():
                continue
            size = label.size()
            if size.width() <= 0 or size.height() <= 0:
                continue
            label.setPixmap(
                src.scaled(
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def resize_label_and_setpixmap(self, poster_pix, thumb_pix):
        if poster_pix is not None:
            if poster_pix[0]:
                self._poster_src_pixmap = (
                    poster_pix[1] if isinstance(poster_pix[1], QPixmap) else QPixmap.fromImage(poster_pix[1])
                )
            else:
                self._poster_src_pixmap = None
                self.Ui.label_poster.clear()
                self.Ui.label_poster.setText(poster_pix[2])

        if thumb_pix is not None:
            if thumb_pix[0]:
                self._thumb_src_pixmap = (
                    thumb_pix[1] if isinstance(thumb_pix[1], QPixmap) else QPixmap.fromImage(thumb_pix[1])
                )
            else:
                self._thumb_src_pixmap = None
                self.Ui.label_thumb.clear()
                self.Ui.label_thumb.setText(thumb_pix[2])

        # 议题 #144: 几何归 _sync_page_layouts 管辖(此前 resize(156,220/328,220)
        # 会把已放大的框砸回设计尺寸), 这里只负责按当前框尺寸出图
        self._rescale_preview_pixmaps()

    # endregion

    def _get_selected_result_items(self) -> list[QTreeWidgetItem]:
        """
        获取当前树状图中有效的结果项（不包含成功/失败根节点）。
        """
        selected_items = []
        for item in self.Ui.treeWidget_number.selectedItems():
            if not item or item.text(0) in {"成功", "失败"}:
                continue
            if item.text(0) not in self.json_array:
                continue
            selected_items.append(item)
        return selected_items

    def _get_selected_entries(self) -> list[tuple[QTreeWidgetItem, str, ShowData, Path]]:
        result = []
        for item in self._get_selected_result_items():
            show_name = item.text(0)
            show_data = self.json_array.get(show_name)
            if show_data is None or not show_data.file_info.file_path:
                continue
            result.append((item, show_name, show_data, show_data.file_info.file_path))
        return result

    def _build_delete_preview(self, paths: list[Path], limit: int = 8) -> str:
        preview = "\n".join(str(path) for path in paths[:limit])
        if len(paths) > limit:
            preview += f"\n... 其余 {len(paths) - limit} 项省略"
        return preview

    def _shorten_text(self, text: str, limit: int) -> str:
        text = str(text).strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    def _normalize_delete_error_reason(self, error_text: str) -> str:
        if not error_text:
            return "未知错误"

        lines = [line.strip() for line in str(error_text).splitlines() if line.strip()]
        full_text = "\n".join(lines).lower()

        if "symbolic link privilege not held" in full_text or "winerror 1314" in full_text:
            return "当前没有创建软链接权限，请尝试以管理员身份运行或开启开发者模式"

        if (
            "winerror 17" in full_text
            or "different disk drive" in full_text
            or "cross-device link" in full_text
            or "not same device" in full_text
        ):
            return "硬链接要求源文件与目标路径位于同一磁盘，请改用软链接"

        if "目标已存在:" in str(error_text):
            for line in lines:
                if "目标已存在:" in line:
                    return line.strip()

        for line in lines:
            if line.startswith("错误:"):
                return line.removeprefix("错误:").strip()

        for line in reversed(lines):
            if "PermissionError:" in line:
                return line.split("PermissionError:", 1)[1].strip()
            if "FileNotFoundError:" in line:
                return line.split("FileNotFoundError:", 1)[1].strip()
            if "OSError:" in line:
                return line.split("OSError:", 1)[1].strip()

        return lines[-1]

    def _build_action_result_text(self, success_count: int, failure_count: int, skipped_count: int = 0) -> str:
        parts = [f"成功 {success_count} 个"]
        if skipped_count:
            parts.append(f"跳过 {skipped_count} 个")
        parts.append(f"失败 {failure_count} 个")
        return "，".join(parts)

    def _show_action_failure_feedback(
        self,
        action_name: str,
        success_count: int,
        failure_details: list[tuple[Path, str]],
        skipped_count: int = 0,
    ) -> None:
        if not failure_details:
            return

        preview_limit = 3
        preview_lines = [
            f"- {self._shorten_text(str(path), 90)}\n  原因：{self._shorten_text(reason, 70)}"
            for path, reason in failure_details[:preview_limit]
        ]
        if len(failure_details) > preview_limit:
            preview_lines.append(f"... 其余 {len(failure_details) - preview_limit} 条请展开“显示详情”或查看日志")

        detail_limit = 20
        detail_lines = [
            f"{index}. {path}\n   原因：{reason}"
            for index, (path, reason) in enumerate(failure_details[:detail_limit], start=1)
        ]
        if len(failure_details) > detail_limit:
            detail_lines.append(f"... 其余 {len(failure_details) - detail_limit} 条请查看日志")
        detail_text = "\n\n".join(detail_lines)

        box = QMessageBox(QMessageBox.Icon.Warning, f"{action_name}结果", f"{action_name}完成")
        box.setInformativeText(
            f"{self._build_action_result_text(success_count, len(failure_details), skipped_count)}\n\n"
            f"{str(chr(10)).join(preview_lines)}"
        )
        box.setDetailedText(detail_text)
        view_log_button = box.addButton("查看日志", QMessageBox.ButtonRole.ActionRole)
        box.addButton("确定", QMessageBox.ButtonRole.AcceptRole)
        self._bind_localized_message_box_detail_buttons(box)
        box.exec()

        if box.clickedButton() == view_log_button:
            self.pushButton_show_log_clicked()
            self.show_hide_logs(True)

    def _localize_message_box_detail_buttons(self, box: QMessageBox) -> None:
        for button in box.findChildren(QPushButton):
            text = button.text().strip()
            if text == "Show Details...":
                button.setText("显示详情")
            elif text == "Hide Details...":
                button.setText("隐藏详情")

    def _bind_localized_message_box_detail_buttons(self, box: QMessageBox) -> None:
        def relocalize() -> None:
            self._localize_message_box_detail_buttons(box)

        relocalize()
        QTimer.singleShot(0, relocalize)
        for button in box.findChildren(QPushButton):
            button.clicked.connect(lambda _checked=False: QTimer.singleShot(0, relocalize))

    def _select_link_output_dir(self, link_name: str) -> Path | None:
        default_dir = str(get_movie_path_setting().softlink_path)
        selected_dir = QFileDialog.getExistingDirectory(
            None,
            f"选择{link_name}目标目录",
            default_dir,
            options=self.options | QFileDialog.Option.ShowDirsOnly,
        )
        return Path(selected_dir) if selected_dir else None

    def _confirm_record_link_paths(self, link_name: str) -> bool | None:
        box = QMessageBox(
            QMessageBox.Icon.Question,
            f"创建{link_name}",
            f"是否将本次成功创建的{link_name}路径写入程序的刮削成功列表？",
        )
        box.setInformativeText("已存在的同源链接会自动去重；取消则中止本次创建。")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
        )
        yes_button = box.button(QMessageBox.StandardButton.Yes)
        assert yes_button is not None
        yes_button.setText("写入并继续")
        no_button = box.button(QMessageBox.StandardButton.No)
        assert no_button is not None
        no_button.setText("仅创建")
        cancel_button = box.button(QMessageBox.StandardButton.Cancel)
        assert cancel_button is not None
        cancel_button.setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Cancel:
            return None
        return reply == QMessageBox.StandardButton.Yes

    def _build_link_target_path(
        self,
        source_path: Path,
        output_dir: Path,
        display_path: Path | None = None,
        group_in_named_dir: bool = False,
    ) -> tuple[Path, list[str]]:
        file_name = display_path.name if display_path is not None else source_path.name
        if not group_in_named_dir:
            return output_dir / file_name, []

        raw_dir_name = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
        raw_dir_name = raw_dir_name or file_name
        dir_name, dir_notes = self._sanitize_link_dir_name(raw_dir_name)
        target_dir, collision_note = self._get_available_link_target_dir(output_dir, dir_name, file_name)
        if collision_note:
            dir_notes.append(f"链接目录名已自动避让冲突: {dir_name} -> {target_dir.name}")
        return target_dir / file_name, dir_notes

    def _get_link_dir_name_max(self) -> int:
        folder_name_max = int(manager.config.folder_name_max)
        if folder_name_max <= 0 or folder_name_max > 255:
            return 60
        return folder_name_max

    def _fit_link_dir_name_length(self, dir_name: str, suffix: str = "") -> str:
        max_length = self._get_link_dir_name_max()
        if len(dir_name) + len(suffix) <= max_length:
            return dir_name + suffix

        base_length = max(max_length - len(suffix), 1)
        trimmed = dir_name[:base_length].rstrip(". ").rstrip()
        if not trimmed:
            trimmed = DEFAULT_LINK_DIR_NAME[:base_length].rstrip(". ").rstrip() or DEFAULT_LINK_DIR_NAME[:1]
        return trimmed + suffix

    def _is_windows_reserved_dir_name(self, dir_name: str) -> bool:
        return dir_name.rstrip(". ").upper() in WINDOWS_RESERVED_DIR_NAMES

    def _sanitize_link_dir_name(self, raw_name: str) -> tuple[str, list[str]]:
        sanitized = LINK_DIR_INVALID_CHARS_RE.sub("_", raw_name)
        sanitized = re.sub(r"\s+", " ", sanitized)
        sanitized = re.sub(r"_+", "_", sanitized)
        sanitized = sanitized.strip().strip(". ").rstrip(". ").strip()
        notes: list[str] = []

        if not sanitized or not sanitized.strip("._- "):
            sanitized = DEFAULT_LINK_DIR_NAME
            notes.append(f"链接目录名清洗后为空，已回退为默认目录名: {raw_name} -> {sanitized}")
        elif sanitized != raw_name:
            notes.append(f"链接目录名已清洗: {raw_name} -> {sanitized}")

        if self._is_windows_reserved_dir_name(sanitized):
            original_name = sanitized
            sanitized = f"{sanitized}_"
            notes.append(f"链接目录名命中 Windows 保留名，已自动调整: {original_name} -> {sanitized}")

        fitted_name = self._fit_link_dir_name_length(sanitized)
        if fitted_name != sanitized:
            notes.append(f"链接目录名过长，已按最大长度截断: {sanitized} -> {fitted_name}")
        return fitted_name, notes

    def _can_reuse_link_target_dir(self, target_dir: Path, file_name: str) -> bool:
        if not target_dir.exists():
            return True
        if not target_dir.is_dir():
            return False

        target_file = target_dir / file_name
        if target_file.exists() or target_file.is_symlink():
            return True

        try:
            return not any(target_dir.iterdir())
        except Exception:
            return False

    def _get_available_link_target_dir(self, output_dir: Path, dir_name: str, file_name: str) -> tuple[Path, str]:
        candidate_dir = output_dir / dir_name
        if self._can_reuse_link_target_dir(candidate_dir, file_name):
            return candidate_dir, ""

        suffix_index = 2
        while True:
            candidate_name = self._fit_link_dir_name_length(dir_name, f"_{suffix_index}")
            candidate_dir = output_dir / candidate_name
            if self._can_reuse_link_target_dir(candidate_dir, file_name):
                return candidate_dir, candidate_name
            suffix_index += 1

    def _prepare_link_target_dir(self, target_path: Path, group_in_named_dir: bool) -> tuple[bool, str, bool]:
        if not group_in_named_dir:
            return True, "", False

        target_dir = target_path.parent
        if target_dir == target_path:
            return False, "目标目录无效", False
        if target_dir.exists():
            if target_dir.is_dir():
                return True, "", False
            return False, f"目标目录已存在同名文件: {target_dir}", False

        try:
            target_dir.mkdir(parents=True, exist_ok=False)
            return True, "", True
        except Exception as error:
            return False, self._normalize_delete_error_reason(str(error)), False

    def _cleanup_empty_link_target_dir(self, target_path: Path, created_dir: bool) -> None:
        if not created_dir:
            return

        target_dir = target_path.parent
        try:
            if target_dir.exists() and target_dir.is_dir() and not any(target_dir.iterdir()):
                target_dir.rmdir()
                signal_qt.show_log_text(f" ↩ 创建失败，已回滚空目录: {target_dir}")
        except Exception as error:
            signal_qt.show_log_text(
                f" ⚠ 回滚空目录失败: {target_dir}\n    原因: {self._normalize_delete_error_reason(str(error))}"
            )

    def _create_links_for_selected_files(
        self, link_type: Literal["soft", "hard"], group_in_named_dir: bool = False
    ) -> None:
        selected_entries = self._get_selected_entries()
        if selected_entries:
            link_targets = [(show_name, file_path) for _, show_name, _, file_path in selected_entries]
        else:
            if not self._check_main_file_path():
                return
            link_targets = [(self.show_name or "", self.file_main_open_path)]

        if not link_targets:
            return

        link_name = "软链接" if link_type == "soft" else "硬链接"
        if group_in_named_dir:
            link_name = f"{link_name}（按文件名建目录）"
        should_record_success = self._confirm_record_link_paths(link_name)
        if should_record_success is None:
            return
        output_dir = self._select_link_output_dir(link_name)
        if output_dir is None:
            return

        signal_qt.show_log_text(f" 🔗 开始创建{link_name}")
        signal_qt.show_log_text(f" 📁 目标目录: {output_dir}")
        signal_qt.show_log_text(f" 📝 成功列表写入: {'是' if should_record_success else '否'}")

        success_count = 0
        skipped_count = 0
        success_paths_to_record: set[Path] = set()
        failure_details: list[tuple[Path, str]] = []
        for _show_name, file_path in link_targets:
            success, source_path, error_info = resolve_link_source_sync(file_path)
            if not success:
                failure_details.append((file_path, self._normalize_delete_error_reason(error_info)))
                signal_qt.show_log_text(
                    f" ❌ {link_name}失败: {file_path}\n    原因: {self._normalize_delete_error_reason(error_info)}"
                )
                continue

            target_path, target_notes = self._build_link_target_path(
                source_path, output_dir, file_path, group_in_named_dir
            )
            for note in target_notes:
                signal_qt.show_log_text(f" ℹ {note}")
            ok, dir_error, created_dir = self._prepare_link_target_dir(target_path, group_in_named_dir)
            if not ok:
                failure_details.append((target_path, dir_error))
                signal_qt.show_log_text(
                    f" ❌ {link_name}失败: {target_path}\n    源文件: {source_path}\n    原因: {dir_error}"
                )
                continue

            if link_type == "soft":
                result, info = create_symlink_sync(source_path, target_path)
            else:
                result, info = create_hardlink_sync(source_path, target_path)

            record_success, success_record_path, record_info = resolve_success_record_source_sync(file_path)
            if not record_success:
                success_record_path = file_path
                record_info = (
                    f"解析成功列表源路径失败，已回退记录当前路径: {self._normalize_delete_error_reason(record_info)}"
                )

            if result:
                if "已存在同源" in info:
                    skipped_count += 1
                    if should_record_success:
                        success_paths_to_record.add(success_record_path)
                    if record_info:
                        signal_qt.show_log_text(f" ℹ 成功列表记录路径: {success_record_path}\n    说明: {record_info}")
                    signal_qt.show_log_text(f" ⏭ 已跳过{link_name}: {target_path}\n    原因: {info}")
                else:
                    success_count += 1
                    if should_record_success:
                        success_paths_to_record.add(success_record_path)
                    if record_info:
                        signal_qt.show_log_text(f" ℹ 成功列表记录路径: {success_record_path}\n    说明: {record_info}")
                    signal_qt.show_log_text(f" ✅ 已创建{link_name}: {target_path}\n    源文件: {source_path}")
            else:
                self._cleanup_empty_link_target_dir(target_path, created_dir)
                failure_details.append((target_path, self._normalize_delete_error_reason(info)))
                signal_qt.show_log_text(
                    f" ❌ {link_name}失败: {target_path}\n    源文件: {source_path}\n    原因: {self._normalize_delete_error_reason(info)}"
                )

        if should_record_success and success_paths_to_record:
            Flags.success_list.update(success_paths_to_record)
            executor.run(save_success_list())
            signal_qt.show_log_text(f" 💾 已写入成功列表 {len(success_paths_to_record)} 项")

        fail_count = len(failure_details)
        signal_qt.show_log_text(
            f" 🎉 创建{link_name}完成：成功 {success_count} 个，跳过 {skipped_count} 个，失败 {fail_count} 个"
        )
        if fail_count:
            signal_qt.show_scrape_info(
                f"💡 创建{link_name}完成，成功 {success_count} 个，跳过 {skipped_count} 个，失败 {fail_count} 个！{get_current_time()}"
            )
            self._show_action_failure_feedback(f"创建{link_name}", success_count, failure_details, skipped_count)
        elif skipped_count and not success_count:
            signal_qt.show_scrape_info(
                f"💡 所选文件的{link_name}已存在，已跳过 {skipped_count} 个！{get_current_time()}"
            )
        elif skipped_count:
            signal_qt.show_scrape_info(
                f"💡 创建{link_name}完成，成功 {success_count} 个，跳过 {skipped_count} 个！{get_current_time()}"
            )
        elif success_count == 1:
            signal_qt.show_scrape_info(f"💡 已创建{link_name}！{get_current_time()}")
        else:
            signal_qt.show_scrape_info(f"💡 已创建 {success_count} 个{link_name}！{get_current_time()}")

    def _find_result_item_by_name(self, show_name: str) -> QTreeWidgetItem | None:
        for root_item in (self.item_succ, self.item_fail):
            for i in range(root_item.childCount()):
                child = root_item.child(i)
                if child is not None and child.text(0) == show_name:
                    return child
        return None

    def _nfo_editor_field_values(self) -> tuple[str, ...]:
        ui = self.Ui
        return (
            ui.lineEdit_nfo_number.text(),
            ui.lineEdit_nfo_actor.text(),
            ui.lineEdit_nfo_year.text(),
            ui.lineEdit_nfo_title.text(),
            ui.lineEdit_nfo_originaltitle.text(),
            ui.textEdit_nfo_outline.toPlainText(),
            ui.textEdit_nfo_originalplot.toPlainText(),
            ui.textEdit_nfo_tag.toPlainText(),
            ui.lineEdit_nfo_release.text(),
            ui.lineEdit_nfo_runtime.text(),
            ui.lineEdit_nfo_score.text(),
            ui.lineEdit_nfo_wanted.text(),
            ui.lineEdit_nfo_director.text(),
            ui.lineEdit_nfo_series.text(),
            ui.lineEdit_nfo_studio.text(),
            ui.lineEdit_nfo_publisher.text(),
            ui.lineEdit_nfo_poster.text(),
            ui.lineEdit_nfo_cover.text(),
            ui.lineEdit_nfo_trailer.text(),
            ui.lineEdit_nfo_website.text(),
            ui.comboBox_nfo.currentText(),
        )

    def _nfo_editor_is_dirty(self) -> bool:
        if self.Ui.widget_nfo.isHidden() or self._nfo_editor_snapshot is None:
            return False
        return self._nfo_editor_field_values() != self._nfo_editor_snapshot

    def _confirm_nfo_editor_leave(self) -> bool:
        """离开当前编辑对象前确认未保存改动。False 表示取消本次离开。"""
        if not self._nfo_editor_is_dirty():
            return True
        box = QMessageBox(QMessageBox.Icon.Question, "编辑 NFO", "当前 NFO 有未保存的修改，是否先保存？")
        box.setStandardButtons(
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
        )
        save_btn = box.button(QMessageBox.StandardButton.Save)
        assert save_btn is not None
        save_btn.setText("保存")
        discard_btn = box.button(QMessageBox.StandardButton.Discard)
        assert discard_btn is not None
        discard_btn.setText("丢弃")
        cancel_btn = box.button(QMessageBox.StandardButton.Cancel)
        assert cancel_btn is not None
        cancel_btn.setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.Save:
            self.save_nfo_info()
        return True

    def _close_nfo_editor(self) -> None:
        if not self._confirm_nfo_editor_leave():
            return
        self.Ui.widget_nfo.hide()
        self._nfo_editor_snapshot = None

    def _on_page_change_nfo_panel(self, index: int) -> None:
        """议题 #177: 切页时暂隐编辑 NFO 面板(非关闭, 表单与结果树选中态保留),
        切回主界面自动恢复; 有未保存改动时取消切页以留在主界面继续编辑。"""
        nfo = self.Ui.widget_nfo
        if index != 0:
            if not nfo.isHidden():
                if self._nfo_editor_is_dirty() and not self._confirm_nfo_editor_leave():
                    stacked = self.Ui.stackedWidget
                    stacked.blockSignals(True)
                    stacked.setCurrentIndex(0)
                    stacked.blockSignals(False)
                    return
                nfo.hide()
                self._nfo_page_hiding = True
        elif getattr(self, "_nfo_page_hiding", False):
            nfo.show()
            self._sync_nfo_overlay_geometry()
            self._nfo_page_hiding = False

    def _clear_main_info_panel(self, *, force: bool = False) -> None:
        if not force and not self.Ui.widget_nfo.isHidden() and not self._confirm_nfo_editor_leave():
            return
        self.set_main_info(None)
        self.file_main_open_path = Path()
        self.show_name = None
        self.show_data = None
        if not self.Ui.widget_nfo.isHidden():
            self.Ui.widget_nfo.hide()
        self._nfo_editor_snapshot = None

    def _remove_deleted_result_items(self, show_names: list[str]) -> None:
        if not show_names:
            return

        current_show_name = self.show_name
        for show_name in show_names:
            self.json_array.pop(show_name, None)

        for show_name in show_names:
            item = self._find_result_item_by_name(show_name)
            if item is None:
                continue
            parent = item.parent()
            if parent is not None:
                parent.removeChild(item)

        self.Ui.treeWidget_number.clearSelection()
        if current_show_name in show_names:
            self._clear_main_info_panel(force=True)

    # 主界面-点击树状条目
    def treeWidget_number_clicked(self, *_args):
        selected_items = self._get_selected_result_items()
        if len(selected_items) != 1:
            if len(selected_items) > 1:
                self._clear_main_info_panel()
            return

        item = selected_items[0]
        try:
            index_json = str(item.text(0))
            if index_json == self.show_name:
                return
            overlay_open = not self.Ui.widget_nfo.isHidden()
            if overlay_open and not self._confirm_nfo_editor_leave():
                prev = self._find_result_item_by_name(self.show_name) if self.show_name else None
                tree = self.Ui.treeWidget_number
                tree.blockSignals(True)
                try:
                    tree.clearSelection()
                    if prev is not None:
                        prev.setSelected(True)
                finally:
                    tree.blockSignals(False)
                return
            self.set_main_info(self.json_array[index_json])
            self._show_nfo_info()
            if overlay_open:
                self._sync_nfo_overlay_geometry()
        except Exception:
            signal_qt.show_traceback_log(item.text(0) + ": No info!")

    def _check_main_file_path(self):
        selected_entries = self._get_selected_entries()
        if len(selected_entries) > 1:
            QMessageBox.about(self, "选择过多", "请只选择一个项目后再使用！！")
            signal_qt.show_scrape_info(f"💡 请只选择一个项目后再使用！{get_current_time()}")
            return False
        if len(selected_entries) == 1:
            _, show_name, show_data, file_path = selected_entries[0]
            self.show_name = show_name
            self.set_main_info(show_data)
            self.file_main_open_path = file_path

        if self.file_main_open_path == Path() or not self.file_main_open_path.is_file():
            QMessageBox.about(self, "没有目标文件", "请刮削后再使用！！")
            signal_qt.show_scrape_info(f"💡 请刮削后使用！{get_current_time()}")
            return False
        return True

    def main_play_click(self):
        """
        主界面点播放
        """
        # 发送hover事件，清除hover状态（因为弹窗后，失去焦点，状态不会变化）
        self.Ui.pushButton_play.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_play, event)
        if self._check_main_file_path():
            # mac需要改为无焦点状态，不然弹窗失去焦点后，再切换回来会有找不到焦点的问题（windows无此问题）
            # if not self.is_windows:
            #     self.setWindowFlags(self.windowFlags() | Qt.WindowDoesNotAcceptFocus)
            #     self.show()
            # 启动线程打开文件
            t = threading.Thread(target=open_file_thread, args=(self.file_main_open_path, False))
            t.start()

    def main_open_folder_click(self):
        """
        主界面点打开文件夹
        """
        self.Ui.pushButton_open_folder.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_open_folder, event)
        if self._check_main_file_path():
            # mac需要改为无焦点状态，不然弹窗失去焦点后，再切换回来会有找不到焦点的问题（windows无此问题）
            # if not self.is_windows:
            #     self.setWindowFlags(self.windowFlags() | Qt.WindowDoesNotAcceptFocus)
            #     self.show()
            # 启动线程打开文件
            t = threading.Thread(target=open_file_thread, args=(self.file_main_open_path, True))
            t.start()

    def main_open_nfo_click(self):
        """
        主界面点打开nfo
        """
        self.Ui.pushButton_open_nfo.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_open_nfo, event)
        if self._check_main_file_path():
            self.Ui.widget_nfo.show()
            # 议题 #154：首次打开路径不经过 resizeEvent，需显式同步覆盖层几何，
            # 否则沿用 .ui 设计尺寸、字段布局与钉底按钮错位。
            self._sync_nfo_overlay_geometry()
            self._show_nfo_info()

    def main_show_similar_click(self):
        """
        主界面点查看相似片推荐
        """
        entries = self._get_selected_entries()
        if not entries:
            if not self.show_data or not self.show_data.data.number:
                signal_qt.show_log_text(" 🔴 请先在结果树中选择一部影片，再查看相似推荐！")
                return
            target = self.show_data.data
        else:
            target = entries[0][2].data

        # 相似语料 = 历史成功结果（跨会话，来自 SQLite 缓存）+ 当次刮削结果
        corpus = SimilarDialog.collect_corpus(Flags.json_data_dic)
        cache = ScrapeStateCache(resources.u("scrape_state.db"))
        if cache.open():
            try:
                cached_corpus = SimilarDialog.collect_corpus_from_cache(cache)
                seen_numbers = {getattr(c, "number", "") for c in corpus}
                for c in cached_corpus:
                    if c.number not in seen_numbers:
                        corpus.append(c)
            finally:
                cache.close()
        if len(corpus) < 2:
            signal_qt.show_log_text(" 🔴 相似推荐需要至少 2 部已刮削影片，请先刮削更多！")
            return

        dialog = SimilarDialog(corpus, target, parent=self)
        dialog.item_selected.connect(self._jump_to_similar_number)
        dialog.exec()

    def _jump_to_similar_number(self, number: str):
        """双击相似推荐项后，在结果树中定位到对应影片。"""
        for show_name, show_data in self.json_array.items():
            if getattr(show_data, "data", None) and show_data.data.number == number:
                item = self._find_result_item_by_name(show_name)
                if item is not None:
                    self.Ui.treeWidget_number.clearSelection()
                    item.setSelected(True)
                    self.Ui.treeWidget_number.scrollToItem(item)
                    self.treeWidget_number_clicked()
                return
        # 历史缓存中的结果不在当次结果树中，无法跳转，仅提示
        signal_qt.show_log_text(f" 💡 番号 {number} 是历史刮削结果，不在本次结果树中，无法跳转")

    def main_open_right_menu(self):
        """
        主界面点打开右键菜单
        """
        # 发送hover事件，清除hover状态（因为弹窗后，失去焦点，状态不会变化）
        self.Ui.pushButton_right_menu.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
        event = QHoverEvent(QEvent.Type.HoverLeave, QPointF(40, 40), QPointF(0, 0))
        QApplication.sendEvent(self.Ui.pushButton_right_menu, event)
        self._menu()

    def search_by_number_clicked(self):
        """
        主界面点输入番号
        """
        if self._check_main_file_path():
            file_path = self.file_main_open_path
            main_file_name = split_path(file_path)[1]
            default_text = os.path.splitext(main_file_name)[0].upper()
            text, ok = QInputDialog.getText(
                self, "输入番号重新刮削", f"文件名: {main_file_name}\n请输入番号:", text=default_text
            )
            if ok and text:
                Flags.again_dic[file_path] = (text, "", "")
                signal_qt.show_scrape_info(f"💡 已添加刮削！{get_current_time()}")
                if self.Ui.pushButton_start_cap.text() == "开始":
                    again_search()

    def search_by_url_clicked(self):
        """
        主界面点输入网址
        """
        if self._check_main_file_path():
            file_path = self.file_main_open_path
            main_file_name = split_path(file_path)[1]
            from mdcx.manual import ManualConfig

            supported_sites = ", ".join(sorted({site.value for site in ManualConfig.WEB_DIC.values()}))
            text, ok = QInputDialog.getText(
                self,
                "输入网址重新刮削",
                f"文件名: {main_file_name}\n支持网站: {supported_sites}"
                "\n请输入番号对应的网址（不是网站首页地址！！！是番号页面地址！！！）:",
            )
            if ok and text:
                website, url = deal_url(text)
                if website:
                    Flags.again_dic[file_path] = ("", url, website)
                    signal_qt.show_scrape_info(f"💡 已添加刮削！{get_current_time()}")
                    if self.Ui.pushButton_start_cap.text() == "开始":
                        again_search()
                else:
                    signal_qt.show_scrape_info(f"💡 不支持的网站！{get_current_time()}")

    def main_del_file_click(self):
        """
        主界面点删除文件
        """
        selected_entries = self._get_selected_entries()
        if selected_entries:
            delete_targets = [(show_name, file_path) for _, show_name, _, file_path in selected_entries]
        else:
            if not self._check_main_file_path():
                return
            delete_targets = [(self.show_name or "", self.file_main_open_path)]

        if not delete_targets:
            return

        file_paths = [file_path for _, file_path in delete_targets]
        if len(file_paths) == 1:
            box_text = f"将要删除文件: \n{file_paths[0]}\n\n 你确定要删除吗？"
        else:
            box_text = (
                f"将要删除 {len(file_paths)} 个文件：\n{self._build_delete_preview(file_paths)}\n\n你确定要继续吗？"
            )

        box = QMessageBox(QMessageBox.Icon.Warning, "删除文件", box_text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("删除文件")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply != QMessageBox.StandardButton.Yes:
            return

        signal_qt.show_log_text(" 🗑 开始删除文件")
        signal_qt.show_log_text(f" 📦 本次待删除文件数: {len(file_paths)}")

        success_show_names = []
        failure_details: list[tuple[Path, str]] = []
        for show_name, file_path in delete_targets:
            result, error_info = delete_file_sync(file_path)
            if result:
                if show_name:
                    success_show_names.append(show_name)
                signal_qt.show_log_text(f" ✅ 已删除文件: {file_path}")
            else:
                reason = self._normalize_delete_error_reason(error_info)
                failure_details.append((file_path, reason))
                signal_qt.show_log_text(f" ❌ 删除文件失败: {file_path}\n    原因: {reason}")

        self._remove_deleted_result_items(success_show_names)
        fail_count = len(failure_details)
        success_count = len(file_paths) - fail_count
        signal_qt.show_log_text(f" 🎉 删除文件完成：成功 {success_count} 个，失败 {fail_count} 个")
        if fail_count:
            signal_qt.show_scrape_info(
                f"💡 文件删除完成，成功 {success_count} 个，失败 {fail_count} 个！{get_current_time()}"
            )
            self._show_action_failure_feedback("删除文件", success_count, failure_details)
        elif success_count == 1:
            signal_qt.show_scrape_info(f"💡 已删除文件！{get_current_time()}")
        else:
            signal_qt.show_scrape_info(f"💡 已删除 {success_count} 个文件！{get_current_time()}")

    def main_del_folder_click(self):
        """
        主界面点删除文件夹
        """
        selected_entries = self._get_selected_entries()
        if selected_entries:
            delete_targets = [(show_name, file_path) for _, show_name, _, file_path in selected_entries]
        else:
            if not self._check_main_file_path():
                return
            delete_targets = [(self.show_name or "", self.file_main_open_path)]

        if not delete_targets:
            return

        file_paths = [file_path for _, file_path in delete_targets]
        folder_to_show_names: dict[Path, list[str]] = {}
        for show_name, file_path in delete_targets:
            folder_path = Path(split_path(file_path)[0])
            folder_to_show_names.setdefault(folder_path, [])
            if show_name:
                folder_to_show_names[folder_path].append(show_name)

        folder_paths = sorted(folder_to_show_names, key=lambda p: len(p.parts), reverse=True)
        if len(folder_paths) == 1:
            box_text = f"将要删除文件夹: \n{folder_paths[0]}\n\n 你确定要删除吗？"
        else:
            box_text = (
                f"将要删除 {len(folder_paths)} 个文件夹（来源于 {len(file_paths)} 个选中项）：\n"
                f"{self._build_delete_preview(folder_paths)}\n\n你确定要继续吗？"
            )

        box = QMessageBox(QMessageBox.Icon.Warning, "删除文件", box_text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("删除文件和文件夹")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply != QMessageBox.StandardButton.Yes:
            return

        signal_qt.show_log_text(" 🗑 开始删除文件夹")
        signal_qt.show_log_text(f" 📦 本次待删除文件夹数: {len(folder_paths)}")

        success_folder_count = 0
        success_show_names: list[str] = []
        failure_details: list[tuple[Path, str]] = []
        for folder_path in folder_paths:
            try:
                # 守护: 拒绝系统关键路径(用户主目录/文件根), 防止路径计算错误误删用户文件
                safe_rmtree(folder_path)
                success_folder_count += 1
                success_show_names.extend(folder_to_show_names.get(folder_path, []))
                signal_qt.show_log_text(f" ✅ 已删除文件夹: {folder_path}")
            except FileNotFoundError:
                success_folder_count += 1
                success_show_names.extend(folder_to_show_names.get(folder_path, []))
                signal_qt.show_log_text(f" ✅ 文件夹不存在，按已删除处理: {folder_path}")
            except Exception as error:
                reason = self._normalize_delete_error_reason(str(error))
                failure_details.append((folder_path, reason))
                signal_qt.show_log_text(f" ❌ 删除文件夹失败: {folder_path}\n    原因: {reason}")

        if success_show_names:
            self._remove_deleted_result_items(success_show_names)

        fail_count = len(failure_details)
        signal_qt.show_log_text(f" 🎉 删除文件夹完成：成功 {success_folder_count} 个，失败 {fail_count} 个")
        if fail_count:
            self.show_scrape_info(
                f"💡 文件夹删除完成，成功 {success_folder_count} 个，失败 {fail_count} 个！{get_current_time()}"
            )
            self._show_action_failure_feedback("删除文件夹", success_folder_count, failure_details)
        elif success_folder_count == 1:
            self.show_scrape_info(f"💡 已删除文件夹！{get_current_time()}")
        else:
            self.show_scrape_info(f"💡 已删除 {success_folder_count} 个文件夹！{get_current_time()}")

    def main_make_symlink_click(self):
        """
        主界面在指定位置创建软链接
        """
        self._create_links_for_selected_files("soft")

    def main_make_symlink_in_dir_click(self):
        """
        主界面在指定位置创建软链接，并按文件名创建目录
        """
        self._create_links_for_selected_files("soft", group_in_named_dir=True)

    def main_make_hardlink_click(self):
        """
        主界面在指定位置创建硬链接
        """
        self._create_links_for_selected_files("hard")

    def main_make_hardlink_in_dir_click(self):
        """
        主界面在指定位置创建硬链接，并按文件名创建目录
        """
        self._create_links_for_selected_files("hard", group_in_named_dir=True)

    def _pic_main_clicked(self):
        """
        主界面点图片
        """
        file_info = None if self.show_data is None else self.show_data.file_info
        self.cutwindow.showimage(self.img_path, file_info)
        self.cutwindow.show()

    # 主界面-开关封面显示
    def checkBox_cover_clicked(self):
        if not self.Ui.checkBox_cover.isChecked():
            self.Ui.label_poster.setText("封面图")
            self.Ui.label_thumb.setText("缩略图")
            # 议题 #144: 占位文本态同时清原图缓存, 否则 resize 重放会把图盖回占位;
            # 几何归 _sync_page_layouts 管辖, 此处不再 resize 设计尺寸
            self._poster_src_pixmap = None
            self._thumb_src_pixmap = None
            self.Ui.label_poster_size.setText("")
            self.Ui.label_thumb_size.setText("")
        else:
            self.set_main_info(self.show_data)

    def update_amazon_strict_pic_verify_state(self, *_args):
        """Amazon 高清搜索关闭时联动禁用其子选项（严格校验开关已随读零校验架构移除）。"""
        amazon_enabled = self.Ui.checkBox_amazon_big_pic.isChecked()
        self.Ui.checkBox_amazon_skip_poster_size_precheck.setEnabled(amazon_enabled)
        self.Ui.label_amazon_skip_poster_size_precheck.setEnabled(amazon_enabled)
        if not amazon_enabled:
            self.Ui.checkBox_amazon_skip_poster_size_precheck.setChecked(False)

    def update_field_priority_try_all_images_state(self, *_args):
        self.Ui.checkBox_field_priority_try_all_images.setEnabled(self.Ui.radioButton_scrape_info.isChecked())

    # region 主界面编辑nfo
    def _show_nfo_info(self):
        try:
            if not self.show_name:
                return
            show_data = self.json_array[self.show_name]
            json_data = show_data.data
            file_info = show_data.file_info
            self.now_show_name = show_data.show_name
            actor = json_data.actor
            if json_data.all_actor and NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
                actor = json_data.all_actor
            self.Ui.label_nfo.setText(str(file_info.file_path))
            self.Ui.lineEdit_nfo_number.setText(json_data.number)
            self.Ui.lineEdit_nfo_actor.setText(actor)
            self.Ui.lineEdit_nfo_year.setText(json_data.year)
            self.Ui.lineEdit_nfo_title.setText(json_data.title)
            self.Ui.lineEdit_nfo_originaltitle.setText(json_data.originaltitle)
            self.Ui.textEdit_nfo_outline.setPlainText(json_data.outline)
            self.Ui.textEdit_nfo_originalplot.setPlainText(json_data.originalplot)
            self.Ui.textEdit_nfo_tag.setPlainText(json_data.tag)
            self.Ui.lineEdit_nfo_release.setText(json_data.release)
            self.Ui.lineEdit_nfo_runtime.setText(json_data.runtime)
            self.Ui.lineEdit_nfo_score.setText(json_data.score)
            self.Ui.lineEdit_nfo_wanted.setText(json_data.wanted)
            self.Ui.lineEdit_nfo_director.setText(json_data.director)
            self.Ui.lineEdit_nfo_series.setText(json_data.series)
            self.Ui.lineEdit_nfo_studio.setText(json_data.studio)
            self.Ui.lineEdit_nfo_publisher.setText(json_data.publisher)
            self.Ui.lineEdit_nfo_poster.setText(json_data.poster)
            self.Ui.lineEdit_nfo_cover.setText(json_data.thumb)
            self.Ui.lineEdit_nfo_trailer.setText(json_data.trailer)
            all_items = [self.Ui.comboBox_nfo.itemText(i) for i in range(self.Ui.comboBox_nfo.count())]
            self.Ui.comboBox_nfo.setCurrentIndex(all_items.index(json_data.country))
            self._nfo_editor_snapshot = self._nfo_editor_field_values()
        except Exception:
            if not signal_qt.stop:
                signal_qt.show_traceback_log(traceback.format_exc())

    def save_nfo_info(self):
        try:
            if self.now_show_name is None:
                return
            show_data = self.json_array[self.now_show_name]
            json_data = show_data.data
            file_info = show_data.file_info
            nfo_path = file_info.file_path.with_suffix(".nfo")
            nfo_folder = nfo_path.parent
            json_data.number = self.Ui.lineEdit_nfo_number.text()
            if NfoInclude.ACTOR_ALL in manager.config.nfo_include_new:
                json_data.all_actor = self.Ui.lineEdit_nfo_actor.text()
            json_data.actor = self.Ui.lineEdit_nfo_actor.text()
            json_data.year = self.Ui.lineEdit_nfo_year.text()
            json_data.title = self.Ui.lineEdit_nfo_title.text()
            json_data.originaltitle = self.Ui.lineEdit_nfo_originaltitle.text()
            json_data.outline = self.Ui.textEdit_nfo_outline.toPlainText()
            json_data.originalplot = self.Ui.textEdit_nfo_originalplot.toPlainText()
            json_data.tag = self.Ui.textEdit_nfo_tag.toPlainText()
            json_data.release = self.Ui.lineEdit_nfo_release.text()
            json_data.runtime = self.Ui.lineEdit_nfo_runtime.text()
            json_data.score = self.Ui.lineEdit_nfo_score.text()
            json_data.wanted = self.Ui.lineEdit_nfo_wanted.text()
            json_data.director = self.Ui.lineEdit_nfo_director.text()
            json_data.series = self.Ui.lineEdit_nfo_series.text()
            json_data.studio = self.Ui.lineEdit_nfo_studio.text()
            json_data.publisher = self.Ui.lineEdit_nfo_publisher.text()
            json_data.poster = self.Ui.lineEdit_nfo_poster.text()
            json_data.thumb = self.Ui.lineEdit_nfo_cover.text()
            json_data.trailer = self.Ui.lineEdit_nfo_trailer.text()
            if executor.run(write_nfo(file_info, json_data, nfo_path, nfo_folder, update=True)):
                self.Ui.label_save_tips.setText(f"已保存! {get_current_time()}")
                self.set_main_info(show_data)
                self._nfo_editor_snapshot = self._nfo_editor_field_values()
            else:
                self.Ui.label_save_tips.setText(f"保存失败! {get_current_time()}")
        except Exception:
            if not signal_qt.stop:
                signal_qt.show_traceback_log(traceback.format_exc())

    # endregion

    # 主界面左下角显示信息
    def show_scrape_info(self, before_info=""):
        try:
            before_info = before_info.strip()
            if Flags.file_mode == FileMode.Single:
                website_label = self.Ui.comboBox_website_all.currentData() or self.Ui.comboBox_website_all.currentText()
                scrape_info = f"💡 单文件刮削\n💠 {Flags.main_mode_text} · {website_label}"
            else:
                scrape_info = f"💠 {Flags.main_mode_text} · {Flags.scrape_like_text}"
                if manager.config.scrape_like == "single":
                    scrape_info = f"💡 {manager.config.website_single} 刮削\n" + scrape_info
            if manager.config.soft_link == 1:
                scrape_info = "🍯 软链接 · 开\n" + scrape_info
            elif manager.config.soft_link == 2:
                scrape_info = "🍯 硬链接 · 开\n" + scrape_info
            after_info = f"\n{scrape_info}\n🛠 {manager.file}\n🐰 MDCx {self.localversion}"
            text = before_info + after_info + self.new_version
            if "<font" in text or "<span" in text:
                # QLabel AutoText 在换行符先于标签出现时判为纯文本、会原样输出标签：
                # 含红字提示时统一用 <br> 换行，保证标红正常渲染与换行显示。
                text = text.replace("\n", "<br>")
            self.label_show_version.emit(text)
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    # region 获取/保存成功刮削列表
    def pushButton_success_list_save_clicked(self):
        box = QMessageBox(QMessageBox.Icon.Warning, "保存成功列表", "确定要将当前列表保存为已刮削成功文件列表吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("保存")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            success_text = self.Ui.textBrowser_show_success_list.toPlainText().replace("暂无成功刮削的文件", "").strip()
            Flags.success_list = {
                p for path in success_text.splitlines() if (line := path.strip()) and (p := Path(line)).suffix
            }
            executor.run(save_success_list())
            get_success_list()
            self.Ui.widget_show_success.hide()

    def pushButton_success_list_clear_clicked(self):
        box = QMessageBox(QMessageBox.Icon.Warning, "清空成功列表", "确定要清空当前已刮削成功文件列表吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("清空")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            Flags.success_list.clear()
            executor.run(save_success_list())
            self.Ui.widget_show_success.hide()

    def pushButton_view_success_file_clicked(self):
        self.Ui.widget_show_success.show()
        info = "暂无成功刮削的文件"
        if len(Flags.success_list):
            info = "\n".join(sorted(str(p) for p in Flags.success_list))
        self.Ui.textBrowser_show_success_list.setText(info)

    # endregion
    # endregion

    # region 日志页
    # 日志页清空显示（仅清界面，不动日志文件）
    def pushButton_clear_logs_clicked(self):
        self.main_log_queue.clear()
        self.logs_counts = 0
        self.req_logs_counts = 0
        self.Ui.textBrowser_log_main.clear()
        self.Ui.textBrowser_log_main_2.clear()

    # 日志页点展开折叠日志
    def pushButton_show_hide_logs_clicked(self):
        if self.Ui.textBrowser_log_main_2.isHidden():
            self.show_hide_logs(True)
        else:
            self.show_hide_logs(False)

    # 日志页点展开折叠日志
    def show_hide_logs(self, show):
        if show:
            self.Ui.pushButton_show_hide_logs.setIcon(QIcon(resources.hide_logs_icon))
            self.Ui.textBrowser_log_main_2.show()
            # 硬编码 resize 会覆盖窗口缩放同步结果（议题 #68），统一交给 _sync_page_layouts
            self._sync_page_layouts()
            self.Ui.textBrowser_log_main.verticalScrollBar().setValue(
                self.Ui.textBrowser_log_main.verticalScrollBar().maximum()
            )
            self.Ui.textBrowser_log_main_2.verticalScrollBar().setValue(
                self.Ui.textBrowser_log_main_2.verticalScrollBar().maximum()
            )

            # self.Ui.textBrowser_log_main_2.moveCursor(self.Ui.textBrowser_log_main_2.textCursor().End)

        else:
            self.Ui.pushButton_show_hide_logs.setIcon(QIcon(resources.show_logs_icon))
            self.Ui.textBrowser_log_main_2.hide()
            self._sync_page_layouts()
            self.Ui.textBrowser_log_main.verticalScrollBar().setValue(
                self.Ui.textBrowser_log_main.verticalScrollBar().maximum()
            )

    # 日志页点展开折叠失败列表
    def pushButton_show_hide_failed_list_clicked(self):
        if self.Ui.textBrowser_log_main_3.isHidden():
            self.show_hide_failed_list(True)
        else:
            self.show_hide_failed_list(False)

    # 日志页点展开折叠失败列表
    def show_hide_failed_list(self, show):
        if show:
            self.Ui.textBrowser_log_main_3.show()
            self.Ui.pushButton_scraper_failed_list.show()
            self.Ui.pushButton_save_failed_list.show()
            self.Ui.textBrowser_log_main_3.verticalScrollBar().setValue(
                self.Ui.textBrowser_log_main_3.verticalScrollBar().maximum()
            )

        else:
            self.Ui.pushButton_save_failed_list.hide()
            self.Ui.textBrowser_log_main_3.hide()
            self.Ui.pushButton_scraper_failed_list.hide()

    # 日志页点一键刮削失败列表
    def pushButton_scraper_failed_list_clicked(self):
        if len(Flags.failed_list) and self.Ui.pushButton_start_cap.text() == "开始":
            start_new_scrape(FileMode.Default, movie_list=[s[0] for s in Flags.failed_list])
            self.show_hide_failed_list(False)

    # 日志页点另存失败列表
    def pushButton_save_failed_list_clicked(self):
        if len(Flags.failed_list):
            log_name = "failed_" + time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime()) + ".txt"
            log_name = get_movie_path_setting().movie_path / log_name
            filename, filetype = QFileDialog.getSaveFileName(
                None, "保存失败文件列表", log_name.as_posix(), "Text Files (*.txt)", options=self.options
            )
            if filename:
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(self.Ui.textBrowser_log_main_3.toPlainText().strip())

    def _write_main_logs_to_file(self, logs: list[str]):
        if not logs:
            return
        text = "\n".join(logs) + "\n"
        try:
            Flags.log_txt.write(text.encode("utf-8"))
        except Exception:
            log_folder = manager.data_folder / "Log"
            if not os.path.exists(log_folder):
                os.makedirs(log_folder, exist_ok=True)
            log_name = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime()) + ".txt"
            log_name = log_folder / log_name
            try:
                old = Flags.log_txt
                if old is not None:
                    try:
                        old.close()
                    except Exception:
                        pass
                Flags.log_txt = open(log_name, "wb", buffering=0)
                Flags.log_txt.write(text.encode("utf-8"))
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())

    def _flush_main_log_queue(self):
        if not self.main_log_queue:
            return
        logs: list[str] = []
        while self.main_log_queue and len(logs) < self.main_log_batch_size:
            logs.append(self.main_log_queue.popleft())
        if manager.config.save_log:
            self._write_main_logs_to_file(logs)
        try:
            self.logs_counts += len(logs)
            if self.logs_counts >= self.main_log_max_count:
                self.logs_counts = len(logs)
                self.main_logs_clear.emit("")
                self.main_logs_show.emit(add_html(" 🗑️ 日志过多，已清屏！"))
            self.main_logs_show.emit(add_html("\n".join(logs)))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self.Ui.textBrowser_log_main.append(traceback.format_exc())

    # 显示详细日志
    def show_detail_log(self):
        text = signal_qt.get_log()
        if text and manager.config.show_web_log:
            self.main_req_logs_show.emit(add_html_plain_text(text))
            if self.req_logs_counts < 10000:
                self.req_logs_counts += 1
            else:
                self.req_logs_counts = 0
                self.req_logs_clear.emit("")
                self.main_req_logs_show.emit(add_html_plain_text(" 🗑️ 日志过多，已清屏！"))

    # 日志页面显示内容
    def show_log_text(self, text):
        if not text:
            return
        self.main_log_queue.append(str(text))

    # endregion

    # region 工具页
    # 工具页面点查看本地番号
    def label_local_number_clicked(self, ev):
        if self.Ui.pushButton_find_missing_number.isEnabled():
            self.pushButton_show_log_clicked()  # 点击按钮后跳转到日志页面
            if self.Ui.lineEdit_actors_name.text() != manager.config.actors_name:  # 保存配置
                self.pushButton_save_config_clicked()
            executor.submit(check_missing_number(False))

    # 工具页面本地资源库点选择目录
    def pushButton_select_local_library_clicked(self):
        from .tool_handlers import pushButton_select_local_library_clicked

        pushButton_select_local_library_clicked(self)

    # 工具页面网盘目录点选择目录
    def pushButton_select_netdisk_path_clicked(self):
        from .tool_handlers import pushButton_select_netdisk_path_clicked

        pushButton_select_netdisk_path_clicked(self)

    # 工具页面本地目录点选择目录
    def pushButton_select_localdisk_path_clicked(self):
        from .tool_handlers import pushButton_select_localdisk_path_clicked

        pushButton_select_localdisk_path_clicked(self)

    # 工具/设置页面点选择目录
    def pushButton_select_media_folder_clicked(self):
        from .tool_handlers import pushButton_select_media_folder_clicked

        pushButton_select_media_folder_clicked(self)

    # 工具-软链接助手
    def pushButton_creat_symlink_clicked(self):
        """
        工具点一键创建软链接
        """
        self.pushButton_show_log_clicked()  # 点击按钮后跳转到日志页面

        if (Switch.COPY_NETDISK_NFO in manager.config.switch_on) != self.Ui.checkBox_copy_netdisk_nfo.isChecked():
            self.pushButton_save_config_clicked()

        try:
            executor.submit(newtdisk_creat_symlink(self.Ui.checkBox_copy_netdisk_nfo.isChecked()))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    # 工具-检查番号
    def pushButton_find_missing_number_clicked(self):
        """
        工具点检查缺失番号
        """
        self.pushButton_show_log_clicked()  # 点击按钮后跳转到日志页面

        # 如果本地资源库或演员与配置内容不同，则自动保存
        if (
            self.Ui.lineEdit_actors_name.text() != manager.config.actors_name
            or self.Ui.lineEdit_local_library_path.text() != manager.config.local_library
        ):
            self.pushButton_save_config_clicked()
        executor.submit(check_missing_number(True))

    # 工具-单文件刮削
    def pushButton_select_file_clicked(self):
        media_path = self.Ui.lineEdit_movie_path.text()  # 获取待刮削目录作为打开目录
        if not media_path:
            media_path = manager.data_folder
        else:
            media_path = parse_media_paths(media_path)[0]
        file_path, filetype = QFileDialog.getOpenFileName(
            None,
            "选取视频文件",
            media_path.as_posix(),
            "Movie Files(*.mp4 "
            "*.avi *.rmvb *.wmv "
            "*.mov *.mkv *.flv *.ts "
            "*.webm *.MP4 *.AVI "
            "*.RMVB *.WMV *.MOV "
            "*.MKV *.FLV *.TS "
            "*.WEBM);;All Files(*)",
            options=self.options,
        )
        if file_path:
            self.Ui.lineEdit_single_file_path.setText(file_path)

    def pushButton_start_single_file_clicked(self):  # 点刮削
        Flags.single_file_path = Path(self.Ui.lineEdit_single_file_path.text().strip())
        if not Flags.single_file_path:
            signal_qt.show_scrape_info("💡 请选择文件！")
            return

        if not os.path.isfile(Flags.single_file_path):
            signal_qt.show_scrape_info("💡 文件不存在！")  # 主界面左下角显示信息
            return

        if not self.Ui.lineEdit_appoint_url.text():
            signal_qt.show_scrape_info("💡 请填写番号网址！")  # 主界面左下角显示信息
            return

        self.pushButton_show_log_clicked()  # 点击刮削按钮后跳转到日志页面
        Flags.appoint_url = self.Ui.lineEdit_appoint_url.text().strip()
        # 单文件刮削从用户输入的网址中识别网址名，复用现成的逻辑=>主页面输入网址刮削
        website, url = deal_url(Flags.appoint_url)
        if website:
            Flags.website_name = website
        else:
            signal_qt.show_scrape_info(f"💡 不支持的网站！{get_current_time()}")
            return
        start_new_scrape(FileMode.Single)

    def pushButton_select_file_clear_info_clicked(self):  # 点清空信息
        self.Ui.lineEdit_single_file_path.setText("")
        self.Ui.lineEdit_appoint_url.setText("")

        # self.Ui.lineEdit_movie_number.setText('')

    # 工具-裁剪封面图
    def pushButton_select_thumb_clicked(self):
        path = self.Ui.lineEdit_movie_path.text()
        if not path:
            path = manager.data_folder.as_posix()
        else:
            path = parse_media_paths(path)[0].as_posix()
        file_path, fileType = QFileDialog.getOpenFileName(
            None, "选取缩略图", path, "Picture Files(*.jpg *.png);;All Files(*)", options=self.options
        )
        if file_path:
            self.cutwindow.showimage(Path(file_path))
            self.cutwindow.show()

    # 工具-视频移动
    def pushButton_move_mp4_clicked(self):
        box = QMessageBox(QMessageBox.Icon.Warning, "移动视频和字幕", "确定要移动视频和字幕吗？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.button(QMessageBox.StandardButton.Yes).setText("移动")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = box.exec()
        if reply == QMessageBox.StandardButton.Yes:
            self.pushButton_show_log_clicked()  # 点击开始移动按钮后跳转到日志页面
            try:
                t = threading.Thread(target=self._move_file_thread)
                self.threads_list.append(t)
                t.start()  # 启动线程,即让线程开始执行
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())
                signal_qt.show_log_text(traceback.format_exc())

    def _move_file_thread(self):
        signal_qt.change_buttons_status.emit()
        try:
            self._move_files_core()
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())
        finally:
            signal_qt.reset_buttons_status.emit()

    def _move_files_core(self):
        movie_items = []
        for movie_path in get_movie_path_setting().movie_paths:
            if not Path(movie_path).exists():
                signal_qt.show_log_text(f" 🔴 Movie folder does not exist: {movie_path}")
                continue
            c = get_movie_path_setting(movie_path_override=movie_path)
            ignore_dirs = c.ignore_dirs
            ignore_dirs.append(movie_path / "Movie_moved")
            movie_list = executor.run(
                movie_lists(ignore_dirs, manager.config.media_type + manager.config.sub_type, movie_path)
            )
            movie_items.extend((movie_path, file_path) for file_path in movie_list)
        if not movie_items:
            signal_qt.show_log_text("No movie found!")
            signal_qt.show_log_text("================================================================================")
            return
        signal_qt.show_log_text("Start move movies...")
        skip_list = []
        for movie_path, file_path in movie_items:
            des_path = movie_path / "Movie_moved"
            if not des_path.exists():
                signal_qt.show_log_text(f"Created folder: {des_path}")
            os.makedirs(des_path, exist_ok=True)
            file_name = file_path.name
            file_ext = file_path.suffix.lower()
            try:
                shutil.move(file_path, des_path)
                if file_ext in manager.config.media_type:
                    signal_qt.show_log_text("   Move movie: " + file_name + " to Movie_moved Success!")
                else:
                    signal_qt.show_log_text("   Move sub: " + file_name + " to Movie_moved Success!")
            except Exception as e:
                skip_list.append([file_name, file_path, str(e)])
        if skip_list:
            signal_qt.show_log_text(f"\n{len(skip_list)} file(s) did not move!")

    # 工具-封面补图
    def pushButton_cover_backfill_start_clicked(self):
        from .tool_handlers import pushButton_cover_backfill_start_clicked

        pushButton_cover_backfill_start_clicked(self)

    def pushButton_actor_db_translate_clicked(self):
        from .tool_handlers import pushButton_actor_db_translate_clicked

        pushButton_actor_db_translate_clicked(self)

    def pushButton_actor_db_link_clicked(self):
        from .tool_handlers import pushButton_actor_db_link_clicked

        pushButton_actor_db_link_clicked(self)

    def pushButton_actor_db_sync_aliases_clicked(self):
        from .tool_handlers import pushButton_actor_db_sync_aliases_clicked

        pushButton_actor_db_sync_aliases_clicked(self)

    def pushButton_actor_db_fill_minnano_clicked(self):
        self._run_actor_db_tool("fill_minnano")

    def pushButton_actor_db_fill_zh_javdb_clicked(self):
        offset = self.Ui.spinBox_actor_db_sync_offset.value()
        limit = self.Ui.spinBox_actor_db_sync_limit.value()
        slice_hint = f"，起始行={offset}，限量={limit if limit > 0 else '不限'}"
        signal_qt.show_log_text(
            "开始扫描 actor_database.xlsx：从 JavDB 补全中文名/繁体名（仅处理「中文名==日文原名」的行）"
            + slice_hint
            + ")..."
        )
        self._run_actor_db_tool("fill_zh_javdb", offset=offset, limit=limit)

    def pushButton_actor_db_open_clicked(self):
        from .tool_handlers import pushButton_actor_db_open_clicked

        pushButton_actor_db_open_clicked(self)

    def pushButton_actor_db_clean_male_clicked(self):
        from .tool_handlers import pushButton_actor_db_clean_male_clicked

        pushButton_actor_db_clean_male_clicked(self)

    def pushButton_actor_db_verify_tmdbid_clicked(self):
        from .tool_handlers import pushButton_actor_db_verify_tmdbid_clicked

        pushButton_actor_db_verify_tmdbid_clicked(self)

    def pushButton_actor_db_check_clicked(self):
        from .tool_handlers import pushButton_actor_db_check_clicked

        pushButton_actor_db_check_clicked(self)

    def pushButton_actor_db_pick_nfo_dir_clicked(self):
        from .tool_handlers import pushButton_actor_db_pick_nfo_dir_clicked

        pushButton_actor_db_pick_nfo_dir_clicked(self)

    def pushButton_actor_db_update_nfo_tmdbid_clicked(self):
        from .tool_handlers import pushButton_actor_db_update_nfo_tmdbid_clicked

        pushButton_actor_db_update_nfo_tmdbid_clicked(self)

    # btn_attr → 任务完成后按钮应恢复的 idle 文案
    _ACTOR_DB_IDLE_TEXT_MAP: dict[str, str] = {
        "actor_db_translate": "补全演员中文姓名",
        "actor_db_link": "补全LibreDMM链接",
        "actor_db_sync_aliases": "补全别名",
        "actor_db_fill_minnano": "Minnano-AV补全",
        "actor_db_fill_zh_javdb": "JavDB演员中文名",
        "actor_db_clean_male": "删除所有男性演员",
        "actor_db_verify_tmdbid": "校验TMDB ID字段",
        "actor_db_check": "检查用户演员数据",
        "actor_db_update_nfo_tmdbid": "更新TMDB ID字段",
    }
    # 由 change_buttons_status/reset_buttons_status 管理的 actor_db 按钮子集；
    # 这些按钮在主刮削时被禁用、刮削结束后若未在跑 actor_db 任务则被恢复。
    _ACTOR_DB_SCRAPE_MANAGED: frozenset[str] = frozenset(
        {
            "actor_db_translate",
            "actor_db_link",
            "actor_db_sync_aliases",
            "actor_db_fill_minnano",
            "actor_db_fill_zh_javdb",
        }
    )

    def _run_actor_db_async(
        self,
        btn_attr: str,
        busy_text: str,
        log_prefix: str,
        coro_factory,
    ) -> None:
        """演员库工具入口的通用模板：按钮防重入 + executor.submit + 完成信号。

        Args:
            btn_attr: Ui.pushButton_xxx 与 self.pushButton_xxx 共用属性名（无 'pushButton_' 前缀）。
            busy_text: 按钮按下时的临时文案。
            log_prefix: 异常日志前缀（如 "演员库维护"、"剔除男演员"、"校验 tmdbid"）。
            coro_factory: 无参 callable，返回协程。协程内异常会被捕获并 show_log。
        """
        from mdcx.utils.qt_thread import run_in_background

        run_in_background(
            button=getattr(self.Ui, f"pushButton_{btn_attr}"),
            coro_factory=coro_factory,
            busy_signal=getattr(self, f"pushButton_{btn_attr}"),
            busy_text=busy_text,
            finished_signal=self.actor_db_finished,
            finished_arg=btn_attr,
            log_prefix=log_prefix,
        )
        self._actor_db_running.add(btn_attr)

    def _run_actor_db_tool(self, mode: str, **kwargs) -> None:
        """运行演员库维护工具（翻译/链接/别名/minnano 补全），统一走通用模板。"""
        from mdcx.tools.actor_db_tool import run_actor_db_xlsx

        button_map = {
            "translate": "actor_db_translate",
            "link": "actor_db_link",
            "sync_aliases": "actor_db_sync_aliases",
            "fill_minnano": "actor_db_fill_minnano",
            "fill_zh_javdb": "actor_db_fill_zh_javdb",
        }
        busy_text = {
            "translate": "运行中...",
            "link": "运行中...",
            "sync_aliases": "运行中...",
            "fill_minnano": "运行中...",
            "fill_zh_javdb": "运行中...",
        }[mode]
        self._run_actor_db_async(
            button_map[mode],
            busy_text,
            "演员库维护",
            lambda: run_actor_db_xlsx(mode=mode, **kwargs),
        )

    def _run_actor_db_clean_male(self) -> None:
        """运行「剔除男演员」存量清洗（按 tmdbid 校验 TMDB gender，删除男优）。"""
        from mdcx.tools.actor_db_tool import clean_male_actors

        self._run_actor_db_async("actor_db_clean_male", "清洗中...", "剔除男演员", clean_male_actors)

    def _run_actor_db_verify_tmdbid(self) -> None:
        """运行「校验TMDB ID有效性」存量清洗（404 失效 id 清除回无 id 状态）。"""
        from mdcx.tools.actor_db_tool import verify_tmdb_ids

        self._run_actor_db_async("actor_db_verify_tmdbid", "校验中...", "校验 tmdbid", verify_tmdb_ids)

    def _run_actor_db_check(self) -> None:
        """运行「检查用户库」：对运行库执行格式/结构/数据异常检查，弹窗报告+自动修复安全项。"""
        from mdcx.tools.actor_db_tool import _check_actor_db_issues

        db_path = Path(resources.u("actor_database.xlsx"))
        if not db_path.exists():
            signal_qt.show_log_text("🔴 actor_database.xlsx 不存在，请先刮削或执行一次演员库维护生成数据库")
            return

        btn = self.Ui.pushButton_actor_db_check
        if not btn.isEnabled():
            return

        btn.setEnabled(False)
        self.pushButton_actor_db_check.emit("检查中...")
        self._actor_db_running.add("actor_db_check")

        try:
            issues = _check_actor_db_issues(db_path)
        except Exception as e:
            signal_qt.show_log_text(f"🔴 检查用户库异常: {e}")
            import traceback as tb

            signal_qt.show_log_text(tb.format_exc())
            self._on_actor_db_finished("actor_db_check")
            return

        try:
            self._show_actor_db_check_dialog(issues, db_path)
        finally:
            # 弹窗关闭后恢复按钮
            self._on_actor_db_finished("actor_db_check")

    def _show_actor_db_check_dialog(self, issues: dict, db_path: Path) -> None:
        """弹窗展示检查结果：无问题→绿色提示；有问题→红色列表+「自动修复」按钮。"""
        from PyQt6.QtWidgets import QMessageBox

        errors = issues["errors"]
        warnings = issues["warnings"]
        total = len(errors) + len(warnings)

        if total == 0:
            QMessageBox.information(self, "检查用户库", "✅ 未发现任何问题。\n\n库结构、格式、数据完整性均正常。")
            signal_qt.show_log_text("✅ 检查用户库完成：未发现问题")
            return

        # 分类统计
        from collections import Counter

        cat_names = {
            "jp_empty": "jp 为空",
            "jp_dup": "jp 重复",
            "kw_format": "keyword 格式",
            "kw_dup": "keyword 重复",
            "birth_format": "出生日期格式",
            "birth_range": "出生日期年份异常",
            "career_no_year": "生涯无年份",
            "tmdb_no_id": "tmdbid 空缺",
            "tmdb_mismatch": "tmdb id 与 url 不匹配",
            "tmdb_dup": "tmdbid 重复",
            "orphan_link": "孤儿链接",
            "name_empty": "中/文名空缺",
            "bio_jp": "简介日文残留",
            "bio_unstruct": "简介非结构化",
        }
        error_cats = Counter(cat for _, _, cat in errors)
        warning_cats = Counter(cat for _, _, cat in warnings)

        lines = [f"检查发现 {len(errors)} 个错误 + {len(warnings)} 个警告：\n"]
        lines.append("<b style='color: #c62828;'>错误（需立即处理）：</b>")
        for cat, count in sorted(error_cats.items(), key=lambda x: -x[1]):
            lines.append(f"  • {cat_names.get(cat, cat)}: {count} 项")
        for row, msg, _cat in errors[:20]:
            lines.append(f"&nbsp;&nbsp;- 行{row}: {msg}")
        if len(errors) > 20:
            lines.append(f"&nbsp;&nbsp;... 还有 {len(errors) - 20} 条未显示")
        lines.append("")
        if warnings:
            lines.append("<b style='color: #ef6c00;'>警告（建议处理）：</b>")
            for cat, count in sorted(warning_cats.items(), key=lambda x: -x[1]):
                lines.append(f"  • {cat_names.get(cat, cat)}: {count} 项")
            for row, msg, _cat in warnings[:10]:
                lines.append(f"&nbsp;&nbsp;- 行{row}: {msg}")
            if len(warnings) > 10:
                lines.append(f"&nbsp;&nbsp;... 还有 {len(warnings) - 10} 条未显示")

        msg_html = "<br>".join(lines)

        # 区分可自动修/需人工
        auto_fixable = {"jp_empty", "jp_dup", "kw_format", "kw_dup", "birth_range", "career_no_year", "tmdb_mismatch"}
        needs_manual = {"tmdb_no_id", "tmdb_dup", "tmdb_dup_url"}
        auto_count = sum(c for cat, c in error_cats.items() if cat in auto_fixable)
        manual_count = sum(c for cat, c in error_cats.items() if cat in needs_manual)

        if manual_count > 0:
            lines.append("")
            lines.append(
                f"<b style='color: #ef6c00;'>{manual_count} 项 tmdb 相关需人工处理</b>（打开数据库后手动修复）"
            )
            for row, msg, cat in errors:
                if cat in needs_manual:
                    lines.append(f"&nbsp;&nbsp;- 行{row}: {msg}")

            lines.append("")
            lines.append("<b>手动修复步骤：</b>")
            lines.append("1. 点击「打开数据库」按钮，在 Excel/WPS/LibreOffice 中打开 actor_database.xlsx")
            lines.append("2. 根据告警信息定位到错误行")
            lines.append("3. 处理 tdb 相关错误：")
            lines.append("   • tmdbid 空缺：删除该行的 tmdb url 链接")
            lines.append("   • tmdbid 重复：核对 TMDB 网站后修正为正确的 id 或删除重复行")
            lines.append("   • id 与 url 不匹配：以 tmdbid 为准，重新生成 url 或改 tmdbid")
            lines.append("4. 保存并重新打开本工具检查")

            msg_html = "<br>".join(lines)

        if auto_count > 0:
            box = QMessageBox(self)
            box.setWindowTitle("检查用户库 — 发现问题")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(msg_html)
            fix_btn = box.addButton(f"自动修复 {auto_count} 项", QMessageBox.ButtonRole.AcceptRole)
            open_btn = box.addButton("打开数据库查看", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is fix_btn:
                self._do_actor_db_auto_fix(db_path)
            elif clicked is open_btn:
                from mdcx.utils.file import open_file_thread

                try:
                    open_file_thread(db_path, False)
                except Exception as e:
                    signal_qt.show_log_text(f"⚠️ 无法打开数据库: {e}")
        else:
            box = QMessageBox(self)
            box.setWindowTitle("检查用户库 — 发现问题（无自动修复项）")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setTextFormat(Qt.TextFormat.RichText)
            box.setText(msg_html)
            open_btn = box.addButton("打开数据库查看", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Ok)
            box.exec()
            if box.clickedButton() is open_btn:
                from mdcx.utils.file import open_file_thread

                try:
                    open_file_thread(db_path, False)
                except Exception as e:
                    signal_qt.show_log_text(f"⚠️ 无法打开数据库: {e}")

    def _do_actor_db_auto_fix(self, db_path: Path) -> None:
        """执行自动修复并反馈结果。"""
        from PyQt6.QtWidgets import QMessageBox

        from mdcx.tools.actor_db_tool import auto_fix_actor_db

        try:
            result = auto_fix_actor_db(db_path)
            fixed = result["fixed"]
            needs_manual = result["needs_manual"]

            lines = [f"自动修复完成：{sum(fixed.values())} 项已修复"]
            save_error = result.get("save_error")
            if save_error:
                lines.insert(0, f"<font color='red'>⚠️ 修复结果保存失败：{save_error}</font>")
                lines.insert(1, "<font color='red'>请关闭 Excel 或其他占用该文件的程序后重试！</font>")
            if fixed:
                for cat, count in fixed.items():
                    cat_names = {
                        "jp_empty": "jp 空行删除",
                        "jp_dup": "jp 重复合并",
                        "kw_format": "keyword 格式规范化",
                        "birth_range": "出生日期越界清空",
                        "career_no_year": "生涯无年份删除",
                        "tmdb_mismatch": "tmdb url 重置",
                    }
                    lines.append(f"  • {cat_names.get(cat, cat)}: {count}")
            if needs_manual:
                lines.append("")
                lines.append(f"{len(needs_manual)} 项需人工处理：")
                for row, msg, _cat in needs_manual[:10]:
                    lines.append(f"  - 行{row}: {msg}")
                if len(needs_manual) > 10:
                    lines.append(f"  ... 还有 {len(needs_manual) - 10} 项")
        except Exception as e:
            lines = [f"自动修复失败: {e}"]

        box = QMessageBox(self)
        box.setWindowTitle("自动修复完成")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("<br>".join(lines))
        open_btn = box.addButton("打开数据库验证", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            from mdcx.utils.file import open_file_thread

            try:
                open_file_thread(db_path, False)
            except Exception as e:
                signal_qt.show_log_text(f"⚠️ 无法打开数据库: {e}")

    def _run_actor_db_update_nfo(self) -> None:
        """运行「更新 nfo tmdbid」（用本地库新 id 覆盖 nfo 旧 id，无 id 的补上）。"""
        from pathlib import Path

        from mdcx.tools.actor_db_tool import update_nfo_tmdb_ids

        dir_text = self.Ui.lineEdit_actor_db_nfo_dir.text().strip()
        if not dir_text:
            signal_qt.show_log_text("🔴 请先选择 nfo 目录")
            return
        dir_path = Path(dir_text)
        if not dir_path.is_dir():
            signal_qt.show_log_text(f"🔴 nfo 目录不存在: {dir_text}")
            return

        self._run_actor_db_async(
            "actor_db_update_nfo_tmdbid",
            "更新中...",
            "更新 nfo",
            lambda: update_nfo_tmdb_ids(dir_path),
        )

    def pushButton_actor_db_stop_clicked(self) -> None:
        """停止当前演员库维护任务（独立于主界面刮削停止）。

        置位 signal_qt.stop 与 Flags.stop_requested，各维护工具的
        _is_stop_requested() 会在滑动窗口每轮响应并保存已处理部分。
        """
        Flags.stop_requested = True
        signal_qt.stop = True
        signal_qt.show_log_text("⛔️ 已请求停止演员库维护任务，正在保存已处理部分...")

    def _on_actor_db_finished(self, task_id: str = "") -> None:
        """主线程恢复演员库维护按钮状态（由 actor_db_finished 信号触发）。

        task_id: 完成的按钮 attr（如 "actor_db_clean_male"）。空串表示恢复全部按钮
        （兼容旧调用，例如 _run_actor_db_check / _run_actor_db_update_nfo 的同步路径）。
        """
        self._actor_db_running.discard(task_id)

        if task_id and task_id in self._ACTOR_DB_IDLE_TEXT_MAP:
            btn_attr = task_id
            btn = getattr(self.Ui, f"pushButton_{btn_attr}")
            # 仍在跑的任务只重置文案，不重置 enabled（避免与其他 actor_db 任务交叉）
            btn.setEnabled(btn_attr not in self._actor_db_running)
            getattr(self, f"pushButton_{btn_attr}").emit(self._ACTOR_DB_IDLE_TEXT_MAP[btn_attr])
            return

        # 空 task_id 或未知 attr：仅恢复未在跑任务的按钮；在跑的保持 disabled
        for btn_attr, idle_text in self._ACTOR_DB_IDLE_TEXT_MAP.items():
            btn = getattr(self.Ui, f"pushButton_{btn_attr}", None)
            sig = getattr(self, f"pushButton_{btn_attr}", None)
            if btn is not None and btn_attr not in self._actor_db_running:
                btn.setEnabled(True)
            if sig is not None:
                sig.emit(idle_text)

        # 演员库任务全部结束后复位停止标志。
        # pushButton_actor_db_stop_clicked 只置位不复位，若在非刮削状态点击停止，
        # signal_qt.stop / Flags.stop_requested 将永久为 True，导致日志静默、下一任务秒停。
        # 演员库任务与主刮削互斥（change_buttons_status 会禁用 actor_db 按钮），此处复位安全。
        if not self._actor_db_running:
            Flags.stop_requested = False
            signal_qt.stop = False

    # region 设置页
    # region 选择目录
    # 设置-目录-软链接目录-点选择目录
    def pushButton_select_softlink_folder_clicked(self):
        from .tool_handlers import pushButton_select_softlink_folder_clicked

        pushButton_select_softlink_folder_clicked(self)

    # 设置-目录-成功输出目录-点选择目录
    def pushButton_select_sucess_folder_clicked(self):
        from .tool_handlers import pushButton_select_sucess_folder_clicked

        pushButton_select_sucess_folder_clicked(self)

    # 设置-目录-失败输出目录-点选择目录
    def pushButton_select_failed_folder_clicked(self):
        from .tool_handlers import pushButton_select_failed_folder_clicked

        pushButton_select_failed_folder_clicked(self)

    # 设置-目录-数据存放目录-点选择目录
    def pushButton_select_data_dir_clicked(self):
        from .tool_handlers import pushButton_select_data_dir_clicked

        pushButton_select_data_dir_clicked(self)

    # 设置-字幕-字幕文件目录-点选择目录
    def pushButton_select_subtitle_folder_clicked(self):
        from .tool_handlers import pushButton_select_subtitle_folder_clicked

        pushButton_select_subtitle_folder_clicked(self)

    # 设置-头像-头像文件目录-点选择目录
    def pushButton_select_actor_photo_folder_clicked(self):
        from .tool_handlers import pushButton_select_actor_photo_folder_clicked

        pushButton_select_actor_photo_folder_clicked(self)

    # 设置-演员-Gfriends本地仓库-点选择目录
    def pushButton_select_gfriends_local_clicked(self):
        from .tool_handlers import pushButton_select_gfriends_local_clicked

        pushButton_select_gfriends_local_clicked(self)

    # 设置-演员-Gfriends本地仓库-点更新
    def pushButton_sync_gfriends_clicked(self):
        from .tool_handlers import pushButton_sync_gfriends_clicked

        pushButton_sync_gfriends_clicked(self)

    # 设置-其他-配置文件目录-点选择目录
    def pushButton_select_config_folder_clicked(self):
        p = self._get_select_folder_path(self.Ui.lineEdit_config_folder)
        if not p:
            return
        p = Path(p)
        if p.is_dir() and p != manager.data_folder:
            manager.list_configs()
            config_path = p / "config.json"
            manager.path = config_path
            if config_path.is_file():
                temp_dark = self.dark_mode
                temp_window_radius = self.window_radius
                self.load_config()
                if temp_dark != self.dark_mode and temp_window_radius == self.window_radius:
                    self.show_flag = True
                    self._windows_auto_adjust()
            else:
                self.Ui.lineEdit_config_folder.setText(str(p))
                self.pushButton_save_config_clicked()
            signal_qt.show_scrape_info(f"💡 目录已切换！{get_current_time()}")

    # endregion

    # 设置-演员-补全信息-演员信息数据库-选择文件按钮
    def pushButton_select_actor_info_db_clicked(self):
        from .tool_handlers import pushButton_select_actor_info_db_clicked

        pushButton_select_actor_info_db_clicked(self)

    # region 设置-问号
    def pushButton_tips_normal_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_normal_mode.toolTip())

    def pushButton_tips_separate_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_separate_mode.toolTip())

    def pushButton_tips_sort_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_sort_mode.toolTip())

    def pushButton_tips_update_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_update_mode.toolTip())

    def pushButton_tips_read_mode_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_read_mode.toolTip())

    def pushButton_tips_soft_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_soft.toolTip())

    def pushButton_tips_hard_clicked(self):
        self._show_tips(self.Ui.pushButton_tips_hard.toolTip())

    # 设置-显示说明信息
    def _show_tips(self, msg):
        self.Ui.textBrowser_show_tips.setText(msg)
        self.Ui.widget_show_tips.show()

    # ESC 关闭说明弹窗（仅弹窗可见时生效，不影响其他 ESC 行为）
    def hide_tips_widget_on_escape(self):
        if self.Ui.widget_show_tips.isVisible():
            self.Ui.widget_show_tips.hide()

    # 设置-刮削网站和字段中的详细说明弹窗
    def pushButton_scrape_note_clicked(self):
        from mdcx.crawlers import get_registered_crawler_site_values

        sites_html = "".join(f"  <li>{site}</li>\n" for site in get_registered_crawler_site_values())
        self._show_tips(f"""<html>
<head/>
<body>
  <p><span style=" font-weight:700;">所有可用网站:</span></p>
{sites_html}  <p><span style=" font-weight:700;">指定类型影片可指定刮削网站:<span></p>
   <p>· 有码：dmm、dmm_api、thejavdb_api、libredmm、r18dev、avbase、xcity、prestige、mgstage、getchu、javlibrary、freejavbt、lulubar、avmoo，以及 javbus、javdb 系、missav 系、official（含 Dahlia/Faleno 厂牌与无码官网路由）、airav_cc、avsex、javday、javfree、iqqtv、7mmtv 等综合站；javdb_api/javdb_app/missav_api/r18dev/thejavdb_api 是免 CF 直连通道</p>
   <p>· 无码：aventertainments、avsox，以及 javbus、javdb 系、missav 系、avsex、official、javday、iqqtv、7mmtv 等综合站</p>
  <p>· 欧美：theporndb、avheat</p>
  <p>· 国产：madouqu、madou_club、avsex、iqqtv、javday</p>
  <p>· 动漫/里番：getchu、javdb、javdb_api（锁定「动漫」用此三站；DLID 开头或路径含 getchu/里番/动漫自动用 getchu 单站）</p>
  <p>· Mywife：mywife </p>
  <p>· 素人：mgstage、prestige、javbus、javdb 系、dmm、dmm_api、avbase、missav、missav_api、mywife、iqqtv、7mmtv </p>
  <p>· FC2：fc2、fc2ppvdb、javdb 系、javfree、7mmtv </p>
</body>
</html>""")

    def pushButton_field_tips_nfo_clicked(self):
        msg = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n\
<movie>\n\
    <plot><![CDATA[剧情简介]]></plot>\n\
    <outline><![CDATA[剧情简介]]></outline>\n\
    <originalplot><![CDATA[原始剧情简介]]></originalplot>\n\
    <tagline>发行日期 XXXX-XX-XX</tagline> \n\
    <premiered>发行日期</premiered>\n\
    <releasedate>发行日期</releasedate>\n\
    <release>发行日期</release>\n\
    <num>番号</num>\n\
    <title>标题</title>\n\
    <originaltitle>原始标题</originaltitle>\n\
    <sorttitle>类标题 </sorttitle>\n\
    <mpaa>家长分级</mpaa>\n\
    <customrating>自定义分级</customrating>\n\
    <actor>\n\
        <name>名字</name>\n\
        <type>类型：演员</type>\n\
    </actor>\n\
    <director>导演</director>\n\
    <rating>评分</rating>\n\
    <criticrating>影评人评分</criticrating>\n\
    <votes>想看人数</votes>\n\
    <year>年份</year>\n\
    <runtime>时长</runtime>\n\
    <series>系列</series>\n\
    <set>\n\
        <name>合集</name>\n\
    </set>\n\
    <studio>片商/制作商</studio> \n\
    <maker>片商/制作商</maker>\n\
    <publisher>厂牌/发行商</publisher>\n\
    <label>厂牌/发行商</label>\n\
    <tag>标签</tag>\n\
    <genre>风格</genre>\n\
    <cover>背景图地址</cover>\n\
    <poster>封面图地址</poster>\n\
    <trailer>预告片地址</trailer>\n\
    <website>刮削网址</website>\n\
</movie>\n\
        """
        self._show_tips(msg)

    # endregion

    # 设置-刮削目录 点击检查待刮削目录并清理文件
    def pushButton_check_and_clean_files_clicked(self):
        if not manager.computed.can_clean:
            self.pushButton_save_config_clicked()
        self.pushButton_show_log_clicked()
        try:
            executor.submit(check_and_clean_files())
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    # 设置-字幕 为所有视频中的无字幕视频添加字幕
    def pushButton_add_sub_for_all_video_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_sub_for_all_video())
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    # region 设置-下载
    # 为所有视频中的创建/删除剧照附加内容
    def pushButton_add_all_extras_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_extras("add"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    def pushButton_del_all_extras_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_extras("del"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # 为所有视频中的创建/删除剧照副本
    def pushButton_add_all_extrafanart_copy_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        self.pushButton_save_config_clicked()
        try:
            executor.submit(add_del_extrafanart_copy("add"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    def pushButton_del_all_extrafanart_copy_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        self.pushButton_save_config_clicked()
        try:
            executor.submit(add_del_extrafanart_copy("del"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # 为所有视频中的创建/删除主题视频
    def pushButton_add_all_theme_videos_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_theme_videos("add"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    def pushButton_del_all_theme_videos_clicked(self):
        self.pushButton_show_log_clicked()  # 点按钮后跳转到日志页面
        try:
            executor.submit(add_del_theme_videos("del"))
        except Exception:
            signal_qt.show_log_text(traceback.format_exc())

    # endregion

    # region 设置-演员
    # 设置-演员 补全演员信息
    def pushButton_add_actor_info_clicked(self):
        from .tool_handlers import pushButton_add_actor_info_clicked

        pushButton_add_actor_info_clicked(self)

    # 设置-演员 补全演员头像按钮
    def pushButton_add_actor_pic_clicked(self):
        from .tool_handlers import pushButton_add_actor_pic_clicked

        pushButton_add_actor_pic_clicked(self)

    # 设置-演员 补全演员头像按钮 kodi
    def pushButton_add_actor_pic_kodi_clicked(self):
        from .tool_handlers import pushButton_add_actor_pic_kodi_clicked

        pushButton_add_actor_pic_kodi_clicked(self)

    # 设置-演员 清除演员头像按钮 kodi
    def pushButton_del_actor_folder_clicked(self):
        from .tool_handlers import pushButton_del_actor_folder_clicked

        pushButton_del_actor_folder_clicked(self)

    # 工具-Emby 演员管理器
    def pushButton_emby_actor_manager_clicked(self):
        from .tool_handlers import pushButton_emby_actor_manager_clicked

        pushButton_emby_actor_manager_clicked(self)

    # 设置-演员 查看演员列表按钮
    def pushButton_show_pic_actor_clicked(self):
        from .tool_handlers import pushButton_show_pic_actor_clicked

        pushButton_show_pic_actor_clicked(self)

    # endregion

    # 设置-线程数量
    def lcdNumber_thread_change(self):
        thread_number = self.Ui.horizontalSlider_thread.value()
        self.Ui.lcdNumber_thread.display(thread_number)

    # 设置-javdb延时
    def lcdNumber_javdb_time_change(self):
        javdb_time = self.Ui.horizontalSlider_javdb_time.value()
        self.Ui.lcdNumber_javdb_time.display(javdb_time)

    # 设置-其他网站延时
    def lcdNumber_thread_time_change(self):
        thread_time = self.Ui.horizontalSlider_thread_time.value()
        self.Ui.lcdNumber_thread_time.display(thread_time)

    # 设置-超时时间
    def lcdNumber_timeout_change(self):
        timeout = self.Ui.horizontalSlider_timeout.value()
        self.Ui.lcdNumber_timeout.display(timeout)

    # 设置-重试次数
    def lcdNumber_retry_change(self):
        retry = self.Ui.horizontalSlider_retry.value()
        self.Ui.lcdNumber_retry.display(retry)

    # 设置-水印大小
    def lcdNumber_mark_size_change(self):
        mark_size = self.Ui.horizontalSlider_mark_size.value()
        self.Ui.lcdNumber_mark_size.display(mark_size)

    # 设置-网络-网址设置-下拉框切换
    def switch_custom_website_change(self, site):
        # 显示文本可能带区域标签后缀（如 "javdb（勿用日本节点）"），剥掉后再转枚举
        site = site.split("（")[0].strip()
        if site not in Website:
            return
        site = Website(site)
        self.Ui.lineEdit_site_custom_url.setText(manager.config.get_site_url(site))

    # 切换配置

    # 设置 - 网络 - 使用代理 - 添加网站
    def _add_no_proxy_site(self, site_value: str):
        """当用户从下拉框选择网站时，添加到输入框"""
        # 显示文本可能带区域标签后缀（如 "javdb（勿用日本节点）"），取值时剥掉
        site_value = site_value.split("（")[0].strip()
        if not site_value or site_value == "选择网站...":
            return
        # 重置下拉框到默认值
        self.Ui.comboBox_no_proxy_sites.setCurrentIndex(0)
        # 获取当前输入
        current = self.Ui.lineEdit_no_proxy_sites.text().strip()
        # 分割现有值
        existing_sites = [s.strip() for s in current.split(",") if s.strip()]
        # 添加新网站（如果不存在）
        if site_value not in existing_sites:
            existing_sites.append(site_value)
            # 更新输入框
            self.Ui.lineEdit_no_proxy_sites.setText(",".join(existing_sites))

    def config_file_change(self, new_config_file: str):
        if new_config_file != manager.file:
            new_config_path = manager.data_folder / new_config_file
            signal_qt.show_log_text(
                f"\n================================================================================\n切换配置：{new_config_path}"
            )
            manager.path = new_config_path
            temp_dark = self.dark_mode
            temp_window_radius = self.window_radius
            self.load_config()
            if temp_dark != self.dark_mode and temp_window_radius == self.window_radius:
                self.show_flag = True
                self._windows_auto_adjust()
            signal_qt.show_scrape_info(f"💡 配置已切换！{get_current_time()}")

    # 重置配置
    def pushButton_init_config_clicked(self):
        self.Ui.pushButton_init_config.setEnabled(False)
        self.Ui.pushButton_init_config_tool.setEnabled(False)
        manager.reset()
        temp_dark = self.dark_mode
        temp_window_radius = self.window_radius
        self.load_config()
        if temp_dark and temp_window_radius:
            self.show_flag = True
            self._windows_auto_adjust()
        self.Ui.pushButton_init_config.setEnabled(True)
        self.Ui.pushButton_init_config_tool.setEnabled(True)
        signal_qt.show_scrape_info(f"💡 配置已重置！{get_current_time()}")

    # 设置-命名-分集-字母
    def checkBox_cd_part_a_clicked(self):
        if self.Ui.checkBox_cd_part_a.isChecked():
            self.Ui.checkBox_cd_part_c.setEnabled(True)
        else:
            self.Ui.checkBox_cd_part_c.setEnabled(False)

    # 分离模式-复用/覆盖元数据互斥：只允许同时选中一个（toggled(False) 不动作，故无信号回环）
    def checkBox_separate_reuse_meta_changed(self, checked):
        if checked:
            self.Ui.checkBox_separate_overwrite_meta.setChecked(False)

    def checkBox_separate_overwrite_meta_changed(self, checked):
        if checked:
            self.Ui.checkBox_separate_reuse_meta.setChecked(False)

    # 分离模式-STRM：生成是覆盖的前提，未勾选生成时覆盖项置灰（保留其勾选值，重新勾选生成后自动恢复）
    def checkBox_separate_generate_strm_changed(self, checked):
        self.Ui.checkBox_separate_overwrite_strm.setEnabled(bool(checked))

    # 设置-刮削目录-同意清理(我已知晓/我已同意)
    def checkBox_i_agree_clean_clicked(self):
        if self.Ui.checkBox_i_understand_clean.isChecked() and self.Ui.checkBox_i_agree_clean.isChecked():
            self.Ui.pushButton_check_and_clean_files.setEnabled(True)
            self.Ui.checkBox_auto_clean.setEnabled(True)
        else:
            self.Ui.pushButton_check_and_clean_files.setEnabled(False)
            self.Ui.checkBox_auto_clean.setEnabled(False)

    # 读取设置页的设置, 保存config.ini，然后重新加载
    def _check_mac_config_folder(self):
        if self.check_mac and not IS_WINDOWS and ".app/Contents/Resources" in manager.data_folder.as_posix():
            self.check_mac = False
            box = QMessageBox(
                QMessageBox.Icon.Warning,
                "选择配置文件目录",
                f"检测到当前配置文件目录为：\n {manager.data_folder}\n\n由于 MacOS 平台在每次更新 APP 版本时会覆盖该目录的配置，因此请选择其他的配置目录！\n这样下次更新 APP 时，选择相同的配置目录即可读取你之前的配置！！！",
            )
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.button(QMessageBox.StandardButton.Yes).setText("选择目录")
            box.button(QMessageBox.StandardButton.No).setText("取消")
            box.setDefaultButton(QMessageBox.StandardButton.Yes)
            reply = box.exec()
            if reply == QMessageBox.StandardButton.Yes:
                self.pushButton_select_config_folder_clicked()

    # 设置-保存
    def pushButton_save_config_clicked(self):
        try:
            self.save_config()
            self.load_config()  # 确保界面显示和实际配置一致
            # 重建网络派生对象：AsyncWebClient 的重试/超时/代理在构造时固化，
            # 仅改 manager.config 不会生效（如检测网络仍用旧重试次数）。
            # _replace_config 原子切换新客户端，旧客户端由持有方租约保护、
            # 空闲后关闭（检测进行中点保存不断连）。
            manager._replace_config(manager.config)
        except Exception:
            error = traceback.format_exc()
            signal_qt.show_traceback_log(error)
            self.tray_icon_show()
            QMessageBox.critical(self, "保存配置失败", f"配置保存失败，软件已保持运行。\n\n{error}")
            return
        signal_qt.show_scrape_info(f"💡 配置已保存！{get_current_time()}")

    # 设置-另存为
    def pushButton_save_new_config_clicked(self):
        new_config_name, ok = QInputDialog.getText(self, "另存为新配置", "请输入新配置的文件名")
        if ok and new_config_name:
            new_config_name = new_config_name.replace("/", "").replace("\\", "")
            new_config_name = re.sub(r'[\\:*?"<>|\r\n]+', "", new_config_name)
            if os.path.splitext(new_config_name)[1] != ".json":
                new_config_name += ".json"
            if new_config_name != manager.file:
                manager.path = manager.data_folder / new_config_name
                self.pushButton_save_config_clicked()

    def save_config(self): ...

    # endregion

    # region 检测网络
    def _measure_net_report_sep_chars(self) -> int:
        """主线程点按钮时量一次报告分隔线宽度，存给检测 worker 线程用。

        报告里的「-」「=」要和面板最上/最下两条横幅同长，故复用同一份可视宽测量
        （`_net_separator_chars` 已缓存，启动首屏量过一次），再过同一个收敛函数
        `net_separator_width`——两边的减 8 与下限 8 才不会各算各的。
        """
        self._net_report_sep_chars = net_separator_width(self._net_separator_chars())
        return self._net_report_sep_chars

    def _net_report_separator_width(self) -> int:
        """worker 线程读用的报告分隔线宽度（纯整数运算，不碰任何 Qt 控件）。

        没量过（例如直接调 `network_check()` 绕过按钮）时退回模块兜底值。
        """
        return self._net_report_sep_chars or DEFAULT_SEPARATOR_WIDTH

    def network_check(self):
        try:
            signal_qt.show_net_info("\n⛑ 开始检测网络...")
            cancel_event = threading.Event()
            self.network_check_cancel_event = cancel_event
            self.network_check_results = None
            self._net_check_lines = []

            def progress(line):
                self._net_check_lines.append(line)
                signal_qt.show_net_info(line)

            def on_item_done(done: int, total: int):
                self.net_check_progress.emit(done, total)

            self.network_check_future = executor.submit(
                run_network_check(
                    progress=progress,
                    on_item_done=on_item_done,
                    cancel_event=cancel_event,
                    separator_width=self._net_report_separator_width(),
                )
            )
            self.network_check_results = self.network_check_future.result()
            merge_site_check_cache(self.network_check_results)  # 持久化供站点选择列表回显
        except Exception as e:
            # 议题 #73 实证：空消息异常（裸 TimeoutError 等）只显示「出现异常：」毫无线索。
            # 带异常类型名，并把 traceback 直接展示在检测页——用户复制结果就是完整诊断。
            signal_qt.show_net_info(f"\n⛔️ 网络检测出现异常：{type(e).__name__}: {e}")
            signal_qt.show_net_info("=" * self._net_report_separator_width() + "\n")
            signal_qt.show_net_info(traceback.format_exc().rstrip())
            signal_qt.show_traceback_log(str(e))
            signal_qt.show_traceback_log(traceback.format_exc())
        finally:
            self.network_check_cancel_event = None
            self.network_check_future = None
            # 按钮状态必须在主线程恢复，经信号调度
            self.net_check_done.emit()

    def _run_net_retry(self):
        """后台线程：重试上次检测的失败/警告项。"""
        results = self.network_check_results
        if not results:
            signal_qt.show_net_info("⛔️ 请先运行一次完整检测，再使用「重试失败项」")
            return
        failed_specs = [
            result.spec
            for result in results
            if result.status in (NetworkCheckStatus.FAILED, NetworkCheckStatus.WARNING)
        ]
        if not failed_specs:
            signal_qt.show_net_info("✅ 上次检测没有失败/警告项，无需重试")
            return
        try:
            signal_qt.show_net_info(f"\n⛑ 重试 {len(failed_specs)} 个失败/警告项...")
            cancel_event = threading.Event()
            self.network_check_cancel_event = cancel_event
            self._net_check_lines = []
            # 议题 #118：探测超时递进已移进单轮内部（30s/45s 最多两次），
            # 「重试失败项」回归纯重测——价值在于用户改完代理/CF 配置后再给一次机会
            signal_qt.show_net_info(f"⏱ 单站刮削探测自动递进重试，超时阶梯 {scrape_probe_ladder_text()}")

            def progress(line):
                self._net_check_lines.append(line)
                signal_qt.show_net_info(line)

            def on_item_done(done: int, total: int):
                self.net_check_progress.emit(done, total)

            self.network_check_future = executor.submit(
                run_network_check(
                    progress=progress,
                    on_item_done=on_item_done,
                    cancel_event=cancel_event,
                    specs=failed_specs,
                    emit_header=False,
                    separator_width=self._net_report_separator_width(),
                )
            )
            self.network_check_results = self.network_check_future.result()
            merge_site_check_cache(self.network_check_results)  # 部分重测同样合并进缓存
        except Exception as e:
            signal_qt.show_net_info(f"\n⛔️ 重试失败项出现异常：{type(e).__name__}: {e}")
            signal_qt.show_net_info(traceback.format_exc().rstrip())
            signal_qt.show_traceback_log(traceback.format_exc())
        finally:
            self.network_check_cancel_event = None
            self.network_check_future = None
            self.net_check_done.emit()

    def pushButton_net_retry_clicked(self):
        if self.network_check_future is not None:
            signal_qt.show_net_info("⏳ 上一次检测仍在进行，请稍后再试")
            return
        self._measure_net_report_sep_chars()
        t = threading.Thread(target=self._run_net_retry, daemon=True)
        t.start()

    def pushButton_net_copy_clicked(self):
        lines = getattr(self, "_net_check_lines", None) or []
        if not lines:
            signal_qt.show_net_info("⛔️ 暂无可复制内容，请先运行检测")
            return
        header = self._build_net_diagnostic_header()
        text = "\n".join(header + lines)
        QApplication.clipboard().setText(text)
        signal_qt.show_net_info("✅ 检测报告已复制到剪贴板（含版本/系统概要，代理地址已脱敏，可直接粘贴到 issue 求助）")

    @staticmethod
    def _build_net_diagnostic_header() -> list[str]:
        """生成复制到剪贴板的诊断报告头部：版本/系统/脱敏后的网络配置概要。"""
        from mdcx.utils import mask_proxy_url

        config = manager.config
        use_proxy = bool(config.use_proxy and config.proxy)
        proxy_info = mask_proxy_url(config.proxy) if use_proxy else "未启用"
        return [
            "=" * 88,
            "MDCx 网络诊断报告（提 issue 时可直接粘贴本段全部内容）",
            f"  版本: {VERSION_NAME} ({LOCAL_VERSION})",
            f"  系统: {platform.system()} {platform.release()} ({platform.machine()})",
            f"  时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"  代理: {proxy_info}    CloudFlare Bypass: {'已配置' if config.cf_bypass_url.strip() else '未配置'}"
            f"    外部CF服务: {'已配置' if config.cf_bypass_trawl_url.strip() else '未配置'}",
            "=" * 88,
        ]

    def _on_net_check_progress(self, done: int, total: int):
        """主线程：检测进行中，按钮文本显示进度百分比。"""
        if total > 0 and self.network_check_future is not None:
            self.Ui.pushButton_check_net.setText(f"停止检测 {done}/{total}")

    def _on_net_check_done(self):
        """主线程：网络检测完成，恢复按钮状态并刷新站点下拉框的检测状态徽标。"""
        from .init import refresh_network_check_badges

        refresh_network_check_badges(self)
        self.Ui.pushButton_check_net.setEnabled(True)
        self.Ui.pushButton_check_net.setText("开始检测")
        self.Ui.pushButton_check_net.setStyleSheet(
            "QPushButton#pushButton_check_net{background-color:#4C6EFF}QPushButton:hover#pushButton_check_net{background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_check_net{#4C6EE0}"
        )

    # 网络检查
    def pushButton_check_net_clicked(self):
        if self.Ui.pushButton_check_net.text() == "开始检测":
            if self.network_check_future is not None:
                # 上一个检测线程尚未结束，避免并发启动多个实例
                return
            self.Ui.pushButton_check_net.setText("停止检测")
            self.Ui.pushButton_check_net.setStyleSheet(
                "QPushButton#pushButton_check_net{color: white;background-color:#3758D8;}QPushButton:hover#pushButton_check_net{color: white;background-color:#4C6EFF;}QPushButton:pressed#pushButton_check_net{color: white;background-color:#2F49B8;}"
            )
            try:
                self._measure_net_report_sep_chars()
                self.t_net = threading.Thread(target=self.network_check)
                self.t_net.start()  # 启动线程,即让线程开始执行
            except Exception:
                signal_qt.show_traceback_log(traceback.format_exc())
                signal_qt.show_net_info(traceback.format_exc())
        elif self.Ui.pushButton_check_net.text().startswith("停止检测"):
            if self.network_check_cancel_event:
                self.network_check_cancel_event.set()
            signal_qt.show_net_info("\n⛔️ 正在停止网络检测...")
            self.Ui.pushButton_check_net.setStyleSheet(
                "QPushButton#pushButton_check_net{color: white;background-color:#4C6EFF;}QPushButton:hover#pushButton_check_net{color: white;background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_check_net{color: white;background-color:#4C6EE0}"
            )
            self.Ui.pushButton_check_net.setText("开始检测")
        else:
            try:
                if self.network_check_cancel_event:
                    self.network_check_cancel_event.set()
            except Exception as e:
                signal_qt.show_traceback_log(str(e))
                signal_qt.show_traceback_log(traceback.format_exc())

    # 检测网络界面日志显示；按行首状态图标着色，便于小白快速定位失败项
    def show_net_info(self, text):
        try:
            color = ""
            stripped = str(text or "").lstrip()
            if stripped.startswith(("❌", "⛔️", "⛔")):
                color = "#e53935"
            elif stripped.startswith("⚠"):
                color = "#f9a825"
            elif stripped.startswith("✅"):
                color = "#43a047"
            self.net_logs_show.emit(add_html_plain_text(text, color=color))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self.Ui.textBrowser_net_main.append(traceback.format_exc())

    # 检查javdb cookie
    def pushButton_check_javdb_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_javdb.toPlainText()
        if not input_cookie:
            self.set_javdb_status.emit("❌ 未填写 Cookie")
            self.show_log_text(" ❌ JavDb 未填写 Cookie，可在「软件设置」-「网络」添加！")
            return
        self.set_javdb_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_javdb_cookie, args=(input_cookie,))
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _check_javdb_cookie(self, input_cookie: str):
        tips = "❌ 未填写 Cookie，影响 FC2 刮削！"
        if not input_cookie:
            self.set_javdb_status.emit(tips)
            return tips
        # self.Ui.pushButton_check_javdb_cookie.setEnabled(False)
        tips = "✅ 连接正常！"
        header = {"cookie": input_cookie}
        javdb_url = manager.config.get_site_url(Website.JAVDB, "https://javdb.com") + "/v/D16Q5?locale=zh"
        try:
            response, error = get_text_sync(javdb_url, headers=header)
            if response is None:
                if "Cookie" in error:
                    # 议题 #130：网络/站点不可达不等于 cookie 失效，一律只告警、保留 cookie
                    tips = "❌ Cookie 检查失败（网络/站点不可达），已保留原 Cookie"
                else:
                    tips = f"❌ 连接失败！请检查网络或代理设置！ {response}"
            else:
                if "The owner of this website has banned your access based on your browser's behaving" in response:
                    ip_adress_list = re.findall(r"(\d+\.\d+\.\d+\.\d+)", response)
                    ip_adress = ip_adress_list[0] + " " if ip_adress_list else ""
                    tips = f"❌ 你的 IP {ip_adress}被 JavDb 封了！"
                elif "Due to copyright restrictions" in response or "Access denied" in response:
                    tips = "❌ 当前 IP 被禁止访问！请使用非日本节点！"
                elif "ray-id" in response:
                    tips = "❌ 访问被 CloudFlare 拦截！"
                elif "/logout" in response:  # 已登录，有登出按钮
                    # vip_info 自带标点/括号：未开通沿用括号补注，已开通则独立成句感叹
                    vip_info = "（未开通VIP）"
                    tips = f"✅ 连接正常！{vip_info}"
                    if input_cookie:
                        if "icon-diamond" in response or "/v/D16Q5" in response:  # 有钻石图标或者跳到详情页表示已开通
                            vip_info = "已开通VIP！"
                        if manager.config.javdb != input_cookie:  # 保存cookie
                            tips = f"✅ 连接正常！{vip_info}Cookie 已保存！"
                            self.exec_save_config.emit()
                        else:
                            tips = f"✅ 连接正常！{vip_info}"
                else:
                    # 议题 #130：/logout 缺失只说明"未检测到登录态"，可能是维护页/拦截页，
                    # 不构成 cookie 失效的确凿证据——只告警、保留 cookie，由用户手动替换。
                    tips = "❌ 未检测到登录态，Cookie 可能无效（已保留，可手动替换）"
        except Exception as e:
            tips = f"❌ 连接失败！请检查网络或代理设置！ {e}"
            signal_qt.show_traceback_log(tips)
        if input_cookie:
            self.set_javdb_status.emit(tips)
            # self.Ui.pushButton_check_javdb_cookie.setEnabled(True)
        self.show_log_text(tips.replace("❌", " ❌ JavDb").replace("✅", " ✅ JavDb"))
        return tips

    # 检查 fc2ppvdb cookie
    # region 刮削缓存管理
    # 失败列表加权列宽：文件名/番号/最后错误/时间按 4:2:6:3 分摊视口剩余宽，
    # 失败次数按内容固定。Qt6 QHeaderView 无 setStretchFactor，Stretch 只能均分，
    # 故用 Interactive + 手动按权分配，保证番号约旧 2 倍、时间约旧 3 倍且无横向滚动条。
    _SCRAPE_CACHE_COL_WEIGHTS = {0: 4, 1: 2, 3: 6, 4: 3}

    def _apply_scrape_cache_header_modes(self) -> None:
        """议题 #179: 失败列表列宽策略。

        旧实现列宽固定 5×130=650（Interactive），表格宽随窗口伸缩而列不动——
        窄窗（用户截图 1032 视口 641）出水平滚动条，宽窗/最大化右侧大片空白。
        改为文件名/番号/最后错误/时间按 4:2:6:3 加权分摊视口宽、
        失败次数按内容收缩，列总宽恒等于视口宽，不出横向滚动条。
        番号约旧 2 倍（多出部分由文件名让出），时间约旧 3 倍（多出部分由最后错误让出）。
        """
        tw = self.Ui.tableWidget_scrape_cache_failed
        tw.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = tw.horizontalHeader()
        header.setMinimumSectionSize(10)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self._scrape_cache_layouting = False
        try:
            tw.installEventFilter(self)
            tw.viewport().installEventFilter(self)
        except Exception:
            pass
        QTimer.singleShot(0, self._layout_scrape_cache_columns)

    def _layout_scrape_cache_columns(self) -> None:
        """按权重重分布失败列表列宽，列总宽恒等于视口宽。"""
        tw = getattr(getattr(self, "Ui", None), "tableWidget_scrape_cache_failed", None)
        if tw is None:
            return
        if getattr(self, "_scrape_cache_layouting", False):
            return
        vp = tw.viewport().width()
        if vp <= 0:
            return
        self._scrape_cache_layouting = True
        try:
            tw.resizeColumnToContents(2)
            fixed = tw.columnWidth(2)
            # 预留 2px 网格线/边框：总宽接近视口时滚动 maximum 仍可能为 1，故按 vp-2 预算分配。
            budget = max(vp - 2, 0)
            remaining = budget - fixed
            if remaining < 0:
                remaining = 0
            weights = self._SCRAPE_CACHE_COL_WEIGHTS
            total = sum(weights.values())
            w0 = remaining * weights[0] // total
            w1 = remaining * weights[1] // total
            w3 = remaining * weights[3] // total
            w4 = remaining - w0 - w1 - w3
            tw.setColumnWidth(0, max(w0, 10))
            tw.setColumnWidth(1, max(w1, 10))
            tw.setColumnWidth(3, max(w3, 10))
            tw.setColumnWidth(4, max(w4, 10))
            # 表格网格线/边框会占 1~2px：实测总宽恰等于视口时滚动 maximum 仍为 1，
            # 此处按实际列宽回扣溢出，保证 maximum == 0（预算 vp-2，仍满足铺满断言 vp-2）。
            overflow = sum(tw.columnWidth(c) for c in range(5)) - max(vp - 2, 0)
            if overflow > 0:
                tw.setColumnWidth(3, max(10, tw.columnWidth(3) - overflow))
        finally:
            self._scrape_cache_layouting = False

    def _open_scrape_cache(self) -> ScrapeStateCache | None:
        cache = ScrapeStateCache(resources.u("scrape_state.db"))
        if not cache.open():
            signal_qt.show_log_text(" 🔴 刮削缓存数据库不可用")
            return None
        return cache

    def pushButton_scrape_cache_refresh_clicked(self) -> None:
        cache = self._open_scrape_cache()
        if cache is None:
            return
        try:
            stats = cache.stats()
            failed = cache.list_failed_detail()
        finally:
            cache.close()
        self._update_scrape_cache_ui(stats, failed)
        signal_qt.show_log_text(
            f" 刮削缓存已刷新：完成 {stats['done']} / 失败 {stats['failed']} / 总计 {stats['total']}"
        )

    def _update_scrape_cache_ui(self, stats: dict, failed: list) -> None:
        self.Ui.label_scrape_cache_done.setText(f"已完成：{stats['done']}")
        self.Ui.label_scrape_cache_failed.setText(f"失败：{stats['failed']}")
        self.Ui.label_scrape_cache_exhausted.setText(f"超限失败：{stats['failed_exhausted']}")
        self.Ui.label_scrape_cache_total.setText(f"总计：{stats['total']}")
        self.Ui.label_scrape_cache_dbpath.setText(f"数据库：{stats['db_path']}")
        self.Ui.label_scrape_cache_dbsize.setText(f"大小：{stats['db_size_kb']} KB")
        tw = self.Ui.tableWidget_scrape_cache_failed
        tw.setRowCount(len(failed))
        for i, f in enumerate(failed):
            name_item = QTableWidgetItem(Path(f.file_path).name)
            name_item.setData(Qt.ItemDataRole.UserRole + 1, f.file_path)
            tw.setItem(i, 0, name_item)
            tw.setItem(i, 1, QTableWidgetItem(f.number))
            tw.setItem(i, 2, QTableWidgetItem(str(f.fail_count)))
            err = f.error or ""
            tw.setItem(i, 3, QTableWidgetItem(err[:100] + ("…" if len(err) > 100 else "")))
            tw.setItem(
                i,
                4,
                QTableWidgetItem(
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.scraped_at)) if f.scraped_at else ""
                ),
            )
        # 议题 #179: 原 resizeColumnsToContents()+setColumnWidth(3,260) 与列宽伸缩策略冲突
        # （长文本会把列总宽撑出视口，实测 sum=1462 必出横向滚动条），列宽按 4:2:6:3 加权分配。
        self._layout_scrape_cache_columns()

    def pushButton_scrape_cache_export_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出失败列表", "scrape_failed.csv", "CSV (*.csv)")
        if not path:
            return
        cache = self._open_scrape_cache()
        if cache is None:
            return
        try:
            failed = cache.list_failed_detail(limit=100000)
        finally:
            cache.close()
        import csv

        with open(path, "w", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp)
            w.writerow(["文件路径", "番号", "失败次数", "最后错误", "时间"])
            for f in failed:
                w.writerow(
                    [
                        f.file_path,
                        f.number,
                        f.fail_count,
                        f.error,
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.scraped_at)) if f.scraped_at else "",
                    ]
                )
        signal_qt.show_log_text(f" 已导出 {len(failed)} 条失败记录到 {path}")

    def pushButton_scrape_cache_reset_clicked(self) -> None:
        tw = self.Ui.tableWidget_scrape_cache_failed
        rows = sorted({idx.row() for idx in tw.selectedIndexes()})
        if not rows:
            signal_qt.show_log_text(" 请先在表格中选中要重置的记录")
            return
        paths = []
        for r in rows:
            item = tw.item(r, 0)
            if item is not None:
                p = item.data(Qt.ItemDataRole.UserRole + 1)
                if p:
                    paths.append(p)
        if not paths:
            return
        cache = self._open_scrape_cache()
        if cache is None:
            return
        try:
            for p in paths:
                cache.delete_state(Path(p))
        finally:
            cache.close()
        signal_qt.show_log_text(f" 已重置 {len(paths)} 条记录（下次刮削将重新处理）")
        self.pushButton_scrape_cache_refresh_clicked()

    def pushButton_scrape_cache_clear_clicked(self) -> None:
        reply = QMessageBox.question(
            self,
            "确认清空缓存",
            "将清空全部刮削缓存状态，下次刮削将重新处理所有文件。\n已生成的 NFO 不会被删除。确认清空？",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        cache = self._open_scrape_cache()
        if cache is None:
            return
        try:
            cache.clear()
        finally:
            cache.close()
        signal_qt.show_log_text(" 刮削缓存已全部清空")
        self.pushButton_scrape_cache_refresh_clicked()

    # endregion
    def pushButton_check_fc2ppvdb_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_fc2ppvdb.toPlainText().strip()
        if not input_cookie:
            self.set_fc2ppvdb_status.emit("❌ 未填写 Cookie")
            self.show_log_text(" ❌ FC2PPVDB 未填写 Cookie，可在「软件设置」-「网络」添加！")
            return
        self.set_fc2ppvdb_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_fc2ppvdb_cookie, args=(input_cookie,))
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            signal_qt.show_log_text(traceback.format_exc())

    def _check_fc2ppvdb_cookie(self, input_cookie: str):
        tips = "❌ 未填写 Cookie"
        if not input_cookie:
            self.set_fc2ppvdb_status.emit(tips)
            return tips

        if not cookie_has_login_key(input_cookie):
            tips = "❌ Cookie 无效！请粘贴 fc2cmadb.com 登录后的完整 cookie（含 XSRF-TOKEN 与 session 项）"
        else:
            cookies = cookie_str_to_dict(input_cookie)
            with manager.acquire_computed() as computed:
                response, error = executor.run(
                    fetch_article_info_with_warmup(
                        computed.async_client,
                        base_url=FC2CMADB_BASE_URL,
                        number="4988506",
                        cookies=cookies,
                        use_proxy=manager.config.use_proxy,
                    )
                )
            if response is None:
                tips = f"❌ Cookie 检查失败：{error}"
            elif not response.get("article"):
                tips = "❌ Cookie 检查失败：返回数据异常"
            elif not response.get("actresses") and not response.get("article", {}).get("actresses"):
                tips = "⚠️ Cookie 连通但未获取到演员数据，请确认已登录 fc2cmadb.com"
                if manager.config.fc2ppvdb != input_cookie:
                    self.exec_save_config.emit()
            elif manager.config.fc2ppvdb != input_cookie:
                self.exec_save_config.emit()
                tips = "✅ 连接正常，Cookie 已保存！"
            else:
                tips = "✅ 连接正常！"

        self.set_fc2ppvdb_status.emit(tips)
        self.show_log_text(tips.replace("❌", " ❌ FC2PPVDB").replace("✅", " ✅ FC2PPVDB"))
        return tips

    # javbus cookie
    def pushButton_check_javbus_cookie_clicked(self):
        input_cookie = self.Ui.plainTextEdit_cookie_javbus.toPlainText()
        self.set_javbus_status.emit("⏳ 正在检测中...")
        try:
            t = threading.Thread(target=self._check_javbus_cookie, args=(input_cookie,))
            t.start()  # 启动线程,即让线程开始执行
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self.show_log_text(traceback.format_exc())

    def _check_javbus_cookie(self, input_cookie: str):
        # self.Ui.pushButton_check_javbus_cookie.setEnabled(False)
        tips = "✅ 连接正常！"
        headers = {"Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,ja;q=0.6", "cookie": input_cookie}
        javbus_url = manager.config.get_site_url(Website.JAVBUS, "https://javbus.com") + "/FSDSS-660"

        try:
            response, error = get_text_sync(javbus_url, headers=headers)

            if response is None:
                tips = f"❌ 连接失败！请检查网络或代理设置！ {error}"
            elif "lostpasswd" in response:
                if input_cookie:
                    tips = "❌ Cookie 无效！"
                else:
                    tips = "❌ 当前节点需要 Cookie 才能刮削！请填写 Cookie 或更换节点！"
            elif manager.config.javbus != input_cookie:
                self.exec_save_config.emit()
                tips = "✅ 连接正常！Cookie 已保存！  "

        except Exception as e:
            tips = f"❌ 连接失败！请检查网络或代理设置！ {e}"

        self.show_log_text(tips.replace("❌", " ❌ JavBus").replace("✅", " ✅ JavBus"))
        self.set_javbus_status.emit(tips)
        # self.Ui.pushButton_check_javbus_cookie.setEnabled(True)
        return tips

    # endregion

    # region 其它
    # 点选择目录弹窗
    def _get_select_folder_path(self, default_source: QLineEdit | str | Path | None = None):
        media_path = self._get_select_folder_default_path(default_source).as_posix()
        media_folder_path = QFileDialog.getExistingDirectory(
            None, "选择目录", media_path, options=self.options | QFileDialog.Option.ShowDirsOnly
        )
        return media_folder_path

    def _get_select_folder_default_path(self, default_source: QLineEdit | str | Path | None = None) -> Path:
        if isinstance(default_source, QLineEdit):
            default_text = default_source.text()
        elif default_source is None:
            default_text = ""
        else:
            default_text = str(default_source)

        for path in self._iter_select_folder_candidates(default_text):
            if path.is_dir():
                return path

        for path in self._iter_select_folder_candidates(self.Ui.lineEdit_movie_path.text()):
            if path.is_dir():
                return path

        if manager.data_folder.is_dir():
            return manager.data_folder
        return Path.home()

    def _iter_select_folder_candidates(self, path_text: str):
        movie_roots = [path for path in parse_media_paths(self.Ui.lineEdit_movie_path.text()) if path.is_dir()]
        for item in re.split(r"[;；,，]", path_text):
            item = item.strip().strip("\"'")
            if not item:
                continue
            path = Path(item)
            if path.is_absolute():
                yield path
                continue
            for movie_root in movie_roots:
                yield movie_root / path
            yield path

    # 改回接受焦点状态
    def recover_windowflags(self):
        return

    def change_buttons_status(self):
        Flags.stop_other = True
        self.Ui.pushButton_start_cap.setText("■ 停止")
        self.Ui.pushButton_start_cap2.setText("■ 停止")
        self.Ui.pushButton_select_media_folder.setVisible(False)
        self.Ui.pushButton_start_single_file.setEnabled(False)
        self.Ui.pushButton_start_single_file.setText("正在刮削中...")
        self.Ui.pushButton_add_sub_for_all_video.setEnabled(False)
        self.Ui.pushButton_add_sub_for_all_video.setText("正在刮削中...")
        self.Ui.pushButton_show_pic_actor.setEnabled(False)
        self.Ui.pushButton_show_pic_actor.setText("刮削中...")
        self.Ui.pushButton_add_actor_info.setEnabled(False)
        self.Ui.pushButton_add_actor_info.setText("正在刮削中...")
        self.Ui.pushButton_add_actor_pic.setEnabled(False)
        self.Ui.pushButton_add_actor_pic.setText("正在刮削中...")
        self.Ui.pushButton_add_actor_pic_kodi.setEnabled(False)
        self.Ui.pushButton_add_actor_pic_kodi.setText("正在刮削中...")
        self.Ui.pushButton_del_actor_folder.setEnabled(False)
        self.Ui.pushButton_del_actor_folder.setText("正在刮削中...")
        # self.Ui.pushButton_check_and_clean_files.setEnabled(False)
        self.Ui.pushButton_check_and_clean_files.setText("正在刮削中...")
        self.Ui.pushButton_move_mp4.setEnabled(False)
        self.Ui.pushButton_move_mp4.setText("正在刮削中...")
        self.Ui.pushButton_find_missing_number.setEnabled(False)
        self.Ui.pushButton_find_missing_number.setText("正在刮削中...")
        self.Ui.pushButton_start_cap.setStyleSheet(
            "QPushButton#pushButton_start_cap{color: white;background-color:#DC2626;}QPushButton:hover#pushButton_start_cap{color: white;background-color:#EF4444;}QPushButton:pressed#pushButton_start_cap{color: white;background-color:#B91C1C;}"
        )
        self.Ui.pushButton_start_cap2.setStyleSheet(
            "QPushButton#pushButton_start_cap2{color: white;background-color:#DC2626;}QPushButton:hover#pushButton_start_cap2{color: white;background-color:#EF4444;}QPushButton:pressed#pushButton_start_cap2{color: white;background-color:#B91C1C;}"
        )
        self.Ui.pushButton_cover_backfill_start.setEnabled(False)
        self.Ui.pushButton_actor_db_translate.setEnabled(False)
        self.Ui.pushButton_actor_db_link.setEnabled(False)
        self.Ui.pushButton_actor_db_sync_aliases.setEnabled(False)
        self.Ui.pushButton_actor_db_fill_minnano.setEnabled(False)
        self.Ui.pushButton_actor_db_fill_zh_javdb.setEnabled(False)

    def reset_buttons_status(self):
        self.Ui.pushButton_start_cap.setEnabled(True)
        self.Ui.pushButton_start_cap2.setEnabled(True)
        self.pushButton_start_cap.emit("开始")
        self.pushButton_start_cap2.emit("开始")
        self.Ui.pushButton_select_media_folder.setVisible(True)
        self.Ui.pushButton_start_single_file.setEnabled(True)
        self.pushButton_start_single_file.emit("开始刮削")
        self.Ui.pushButton_add_sub_for_all_video.setEnabled(True)
        self.pushButton_add_sub_for_all_video.emit("点击检查所有视频的字幕情况并为无字幕视频添加字幕")

        self.Ui.pushButton_show_pic_actor.setEnabled(True)
        self.pushButton_show_pic_actor.emit("查看")
        self.Ui.pushButton_add_actor_info.setEnabled(True)
        self.pushButton_add_actor_info.emit("开始补全")
        self.Ui.pushButton_add_actor_pic.setEnabled(True)
        self.pushButton_add_actor_pic.emit("开始补全")
        self.Ui.pushButton_add_actor_pic_kodi.setEnabled(True)
        self.pushButton_add_actor_pic_kodi.emit("开始补全")
        self.Ui.pushButton_del_actor_folder.setEnabled(True)
        self.pushButton_del_actor_folder.emit("清除所有.actors文件夹")
        self.Ui.pushButton_check_and_clean_files.setEnabled(True)
        self.pushButton_check_and_clean_files.emit("点击检查待刮削目录并清理文件")
        self.Ui.pushButton_move_mp4.setEnabled(True)
        self.pushButton_move_mp4.emit("开始移动")
        self.Ui.pushButton_find_missing_number.setEnabled(True)
        self.pushButton_find_missing_number.emit("检查缺失番号")
        self.Ui.pushButton_cover_backfill_start.setEnabled(True)
        # actor_db 由主刮削管理（change_buttons_status 禁用）的按钮子集：
        # 仅当对应 btn_attr 不在 _actor_db_running 时才恢复 Enabled；在跑则保持 disabled。
        for btn_attr in self._ACTOR_DB_SCRAPE_MANAGED:
            btn = getattr(self.Ui, f"pushButton_{btn_attr}", None)
            sig = getattr(self, f"pushButton_{btn_attr}", None)
            if btn is not None and btn_attr not in self._actor_db_running:
                btn.setEnabled(True)
            if sig is not None:
                sig.emit(self._ACTOR_DB_IDLE_TEXT_MAP[btn_attr])

        self.Ui.pushButton_start_cap.setStyleSheet(
            "QPushButton#pushButton_start_cap{color: white;background-color:#4C6EFF;}QPushButton:hover#pushButton_start_cap{color: white;background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_start_cap{color: white;background-color:#4C6EE0}"
        )
        self.Ui.pushButton_start_cap2.setStyleSheet(
            "QPushButton#pushButton_start_cap2{color: white;background-color:#4C6EFF;}QPushButton:hover#pushButton_start_cap2{color: white;background-color: rgba(76,110,255,240)}QPushButton:pressed#pushButton_start_cap2{color: white;background-color:#4C6EE0}"
        )
        Flags.file_mode = FileMode.Default
        self.threads_list = []
        if len(Flags.failed_list):
            self.Ui.pushButton_scraper_failed_list.setText(f"一键重新刮削当前 {len(Flags.failed_list)} 个失败文件")
        else:
            self.Ui.pushButton_scraper_failed_list.setText("当有失败任务时，点击可以一键刮削当前失败列表")

    # endregion

    # region 自动刮削
    def auto_scrape(self):
        if Switch.TIMED_SCRAPE in manager.config.switch_on and self.Ui.pushButton_start_cap.text() == "开始":
            QTimer.singleShot(100, self._auto_scrape_do_work)

    def _auto_scrape_do_work(self):
        timed_interval = manager.config.timed_interval
        self.atuo_scrape_count += 1
        signal_qt.show_log_text(
            f"\n\n 🍔 已启用「循环刮削」！间隔时间：{timed_interval}！即将开始第 {self.atuo_scrape_count} 次循环刮削！"
        )
        if Flags.scrape_start_time:
            signal_qt.show_log_text(
                " ⏰ 上次刮削时间: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(Flags.scrape_start_time))
            )
        start_new_scrape(FileMode.Default)

    def auto_start(self):
        if Switch.AUTO_START in manager.config.switch_on:
            signal_qt.show_log_text("\n\n 🍔 已启用「软件启动后自动刮削」！即将开始自动刮削！")
            self.pushButton_start_scrape_clicked()

    # endregion


# region 外部方法定义
MyMAinWindow.load_config = load_config  # type: ignore[method-assign]
MyMAinWindow.save_config = save_config  # type: ignore[method-assign]
MyMAinWindow.Init_QSystemTrayIcon = Init_QSystemTrayIcon  # type: ignore[method-assign]
MyMAinWindow.Init_Ui = Init_Ui  # type: ignore[method-assign]
MyMAinWindow.Init_Singal = Init_Singal  # type: ignore[method-assign]
MyMAinWindow.init_QTreeWidget = init_QTreeWidget  # type: ignore[method-assign]
MyMAinWindow.set_style = set_style  # type: ignore[method-assign]
MyMAinWindow.set_dark_style = set_dark_style  # type: ignore[method-assign]
# endregion
