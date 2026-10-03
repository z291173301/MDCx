"""NFO 库管理页面的工具处理函数。

借鉴 NFO.Editor 的目录浏览 + 批量编辑理念，在 mdcx 内做成独立导航页。
复用 core/nfo.py 的 get_nfo_data / write_nfo 读写能力，不重复造轮子。
"""

from __future__ import annotations

import copy
import re
import traceback
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from mdcx.core.nfo import get_nfo_data, write_nfo
from mdcx.models.model_types import CrawlersResult, FileInfo
from mdcx.signals import signal_qt
from mdcx.utils import executor, get_current_time
from mdcx.utils.file import delete_file_sync, open_file_thread
from mdcx.views.nfo_preview_window import NfoPreviewWindow

if TYPE_CHECKING:
    from .main_window import MyMAinWindow

# NFO 列表项中存储的 data role
NFO_PATH_ROLE = Qt.ItemDataRole.UserRole + 1

# diff 对比的字段：(属性名, 显示名, 是否列表类型)
_DIFF_FIELDS: list[tuple[str, str, bool]] = [
    ("number", "番号", False),
    ("title", "标题", False),
    ("actor", "演员", False),
    ("release", "发行日", False),
    ("year", "年份", False),
    ("runtime", "时长", False),
    ("directors", "导演", True),
    ("studio", "片商", False),
    ("publisher", "发行商", False),
    ("series", "系列", False),
    ("score", "评分", False),
    ("outline", "简介", False),
    ("tags", "标签", True),
    ("thumb", "封面URL", False),
    ("poster", "海报URL", False),
]


def _make_file_info(nfo_path: Path) -> FileInfo:
    """根据 NFO 路径构造最小可用 FileInfo（write_nfo 需要 file_path 和 cd_part）。"""
    video_path = nfo_path.with_suffix("")
    # 尝试找到同目录下同名的视频文件
    for ext in (".mp4", ".mkv", ".avi", ".wmv", ".mov", ".m4v", ".ts", ".rmvb", ".iso"):
        candidate = nfo_path.with_suffix(ext)
        if candidate.is_file():
            video_path = candidate
            break
    else:
        video_path = nfo_path.with_suffix(".mp4")

    return FileInfo(
        number="",
        mosaic="",
        appoint_number="",
        appoint_url="",
        c_word="",
        cd_part="",
        destroyed="",
        file_ex=video_path.suffix,
        file_name=video_path.stem,
        file_path=video_path,
        file_show_name=video_path.stem,
        file_show_path=video_path,
        folder_path=nfo_path.parent,
        has_sub=False,
        leak="",
        letters="",
        short_number="",
        sub_list=[],
        website_name="",
        wuma="",
        youma="",
        definition="",
        codec="",
    )


def pushButton_nfo_library_clicked(self: MyMAinWindow) -> None:
    """左侧导航：切换到 NFO 库管理页面。"""
    self.Ui.left_backgroud_widget.setStyleSheet(
        f"background: #F5F7FF;border-right: 1px solid #E1E7FF;border-top-left-radius: {self.window_radius}px;"
        f"border-bottom-left-radius: {self.window_radius}px;"
    )
    self.Ui.stackedWidget.setCurrentIndex(6)
    self.set_left_button_style()
    self.Ui.pushButton_nfo_library.setStyleSheet("font-weight: bold; background-color: rgba(160,160,165,60);")
    if self.Ui.listWidget_nfo_lib.count() == 0:
        _add_empty_hint(self, "请先选择上方目录加载nfo文件")
    # 议题 #117：休眠页期间窗口缩放不会触发表单高度自适应，切页时补一次
    self._sync_nfo_lib_form_fields()


def pushButton_nfo_lib_select_dir_clicked(self: MyMAinWindow) -> None:
    """选择目录并扫描 NFO 文件。

    确定目录后自动展示目录内第一个番号的信息（表单 + 预览图 + 海报 URL 等），
    免得右侧整片空白还要手动点一次列表。"""
    folder = self._get_select_folder_path(None)
    if not folder:
        return
    self.Ui.lineEdit_nfo_lib_dir.setText(folder)
    _scan_nfo_directory(self, Path(folder), select_first=True)


def pushButton_nfo_lib_select_all_clicked(self: MyMAinWindow) -> None:
    """全选 NFO 列表（议题 #61：列表右侧缺全选快捷键）。

    只选可见项（筛选后剩下行），避免误把筛选时隐藏的条目批量提交。"""
    self.Ui.listWidget_nfo_lib.selectAll()


def pushButton_nfo_lib_select_none_clicked(self: MyMAinWindow) -> None:
    """清空 NFO 列表选择。"""
    self.Ui.listWidget_nfo_lib.clearSelection()


def pushButton_nfo_lib_refresh_clicked(self: MyMAinWindow) -> None:
    """刷新当前目录的 NFO 列表，并重新展示第一个番号的信息。"""
    dir_text = self.Ui.lineEdit_nfo_lib_dir.text().strip()
    if not dir_text:
        signal_qt.show_log_text("请先选择目录")
        return
    _scan_nfo_directory(self, Path(dir_text), select_first=True)


def _scan_nfo_directory(self: MyMAinWindow, folder: Path, select_first: bool = True) -> None:
    """扫描目录下所有 .nfo 文件并填充列表。

    `select_first` 为真时（选择目录、刷新）自动选中并加载第一项，
    让右侧表单与预览图默认显示目录内第一个番号的信息。"""
    self.Ui.listWidget_nfo_lib.clear()
    if not folder.is_dir():
        signal_qt.show_log_text(f"目录不存在: {folder}")
        return

    nfo_files = sorted(folder.rglob("*.nfo"), key=lambda p: p.name.lower())
    count = 0
    for nfo_path in nfo_files:
        item = QListWidgetItem(nfo_path.stem)
        item.setData(NFO_PATH_ROLE, str(nfo_path))
        item.setToolTip(str(nfo_path))
        self.Ui.listWidget_nfo_lib.addItem(item)
        count += 1
    # 剪掉已不在目录中的搜索缓存，避免无界增长（存量命中靠 mtime 校验）
    cache = getattr(self, "_nfo_lib_search_cache", None)
    if cache:
        alive = {str(p) for p in nfo_files}
        for key in [k for k in cache if k not in alive]:
            del cache[key]

    self.Ui.label_nfo_lib_count.setText(f"共 {count} 个")
    if count == 0:
        _add_empty_hint(self, "该目录下未找到 NFO 文件")
        return
    signal_qt.show_log_text(f"NFO 库管理: 扫描到 {count} 个 NFO 文件")
    if select_first:
        _select_first_nfo(self)


def _select_first_nfo(self: MyMAinWindow) -> None:
    """选中列表第一项并加载其 NFO。

    正常会由 `itemSelectionChanged` 信号触发 `listWidget_nfo_lib_item_clicked`；
    万一信号没触发（如列表未获得选择权）则兜底手动调用一次，避免重复加载。"""
    list_widget = self.Ui.listWidget_nfo_lib
    if list_widget.count() == 0:
        return
    item = list_widget.item(0)
    if not (item.flags() & Qt.ItemFlag.ItemIsSelectable):
        return

    list_widget.setCurrentItem(item)
    list_widget.scrollToItem(item)
    if not item.isSelected():
        item.setSelected(True)
    if not list_widget.selectedItems():
        listWidget_nfo_lib_item_clicked(self)


def _add_empty_hint(self: MyMAinWindow, text: str) -> None:
    """列表为空时添加一行不可选的占位提示。"""
    item = QListWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable & ~Qt.ItemFlag.ItemIsEnabled)
    item.setData(NFO_PATH_ROLE, "")
    self.Ui.listWidget_nfo_lib.addItem(item)


def listWidget_nfo_lib_item_clicked(self: MyMAinWindow) -> None:
    """列表项选中：读取 NFO 并填充表单。"""
    items = self.Ui.listWidget_nfo_lib.selectedItems()
    if not items:
        return
    nfo_path = Path(items[0].data(NFO_PATH_ROLE))
    if not nfo_path.is_file():
        signal_qt.show_log_text(f"NFO 文件不存在: {nfo_path}")
        return

    self._nfo_lib_current_path = nfo_path

    async def _load():
        try:
            data, info = await get_nfo_data(nfo_path.with_suffix(""), nfo_path.stem)
            if data is None:
                signal_qt.show_log_text(f"读取失败: {nfo_path.name}")
                return
            # 在主线程更新 UI（get_nfo_data 在后台线程，需要通过信号回传）
            self._nfo_lib_pending_data = data
            self._nfo_lib_pending_info = info
            self.nfo_lib_data_loaded.emit(str(nfo_path))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())

    executor.submit(_load())


def on_nfo_lib_data_loaded(self: MyMAinWindow, nfo_path_str: str) -> None:
    """后台读取 NFO 完成后，在主线程填充表单（线程安全）。"""
    data: CrawlersResult | None = getattr(self, "_nfo_lib_pending_data", None)
    info = getattr(self, "_nfo_lib_pending_info", None)
    if data is None:
        return

    self.Ui.lineEdit_nfo_lib_number.setText(data.number or "")
    self.Ui.lineEdit_nfo_lib_title.setText(data.title or "")
    self.Ui.lineEdit_nfo_lib_actor.setText(data.actor or "")
    self.Ui.lineEdit_nfo_lib_release.setText(data.release or "")
    self.Ui.lineEdit_nfo_lib_year.setText(data.year or "")
    self.Ui.lineEdit_nfo_lib_runtime.setText(data.runtime or "")
    self.Ui.lineEdit_nfo_lib_director.setText(",".join(data.directors) if data.directors else "")
    self.Ui.lineEdit_nfo_lib_studio.setText(data.studio or "")
    self.Ui.lineEdit_nfo_lib_publisher.setText(data.publisher or "")
    self.Ui.lineEdit_nfo_lib_series.setText(data.series or "")
    self.Ui.lineEdit_nfo_lib_score.setText(data.score or "")
    self.Ui.plainTextEdit_nfo_lib_outline.setPlainText(data.outline or "")
    self.Ui.plainTextEdit_nfo_lib_tag.setPlainText(data.tag or "")
    self.Ui.lineEdit_nfo_lib_cover_url.setText(data.thumb or "")
    self.Ui.lineEdit_nfo_lib_poster_url.setText(data.poster or "")

    # 加载本地封面预览
    poster_path = info.poster_path if info else None
    thumb_path = info.thumb_path if info else None
    if poster_path and poster_path.is_file():
        pix = QPixmap(str(poster_path))
        if not pix.isNull():
            self.Ui.label_nfo_lib_poster_preview.setPixmap(
                pix.scaled(200, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
    else:
        self.Ui.label_nfo_lib_poster_preview.setText("无海报")
    if thumb_path and thumb_path.is_file():
        pix = QPixmap(str(thumb_path))
        if not pix.isNull():
            self.Ui.label_nfo_lib_thumb_preview.setPixmap(
                pix.scaled(200, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
    else:
        self.Ui.label_nfo_lib_thumb_preview.setText("无缩略图")

    # 保留原始数据副本作为保存前 diff 的基准
    self._nfo_lib_original_data = copy.deepcopy(data)

    # 清理临时状态
    self._nfo_lib_pending_data = None
    self._nfo_lib_pending_info = None


def _collect_form_data(self: MyMAinWindow) -> CrawlersResult:
    """从表单控件收集数据构造 CrawlersResult。
    补充表单没有但每次保存会丢失的字段（originalplot, external_ids 等），从原数据中继承。"""
    data = CrawlersResult.empty()
    data.number = self.Ui.lineEdit_nfo_lib_number.text().strip()
    data.title = self.Ui.lineEdit_nfo_lib_title.text().strip()
    data.actor = self.Ui.lineEdit_nfo_lib_actor.text().strip()
    data.all_actor = data.actor
    data.release = self.Ui.lineEdit_nfo_lib_release.text().strip()
    data.year = self.Ui.lineEdit_nfo_lib_year.text().strip()
    data.runtime = self.Ui.lineEdit_nfo_lib_runtime.text().strip()
    director_text = self.Ui.lineEdit_nfo_lib_director.text().strip()
    data.directors = [d.strip() for d in director_text.split(",") if d.strip()] if director_text else []
    data.studio = self.Ui.lineEdit_nfo_lib_studio.text().strip()
    data.publisher = self.Ui.lineEdit_nfo_lib_publisher.text().strip()
    data.series = self.Ui.lineEdit_nfo_lib_series.text().strip()
    data.score = self.Ui.lineEdit_nfo_lib_score.text().strip()
    data.outline = self.Ui.plainTextEdit_nfo_lib_outline.toPlainText().strip()
    tag_text = self.Ui.plainTextEdit_nfo_lib_tag.toPlainText().strip()
    data.tag = tag_text
    data.tags = [t.strip() for t in tag_text.replace("，", ",").split(",") if t.strip()] if tag_text else []
    data.thumb = self.Ui.lineEdit_nfo_lib_cover_url.text().strip()
    data.poster = self.Ui.lineEdit_nfo_lib_poster_url.text().strip()

    # 表单没有但 write_nfo 会读取的字段：从原数据继承，避免保存后丢失
    original: CrawlersResult | None = getattr(self, "_nfo_lib_original_data", None)
    if original is not None:
        data.originalplot = original.originalplot
        data.external_ids = original.external_ids.copy() if original.external_ids else {}
        data.wanted = original.wanted
        data.letters = original.letters
        data.mosaic = original.mosaic
        data.outline_from = original.outline_from
        data.original_actors = original.original_actors
        data.actor_tmdb_ids = original.actor_tmdb_ids.copy() if original.actor_tmdb_ids else {}

    return data


def _build_field_diff(original: CrawlersResult, new_data: CrawlersResult) -> str:
    """对比原始数据和新数据，返回字段级 diff 文本（无差异返回空串）。"""
    lines: list[str] = []
    for attr, label, is_list in _DIFF_FIELDS:
        old_val = getattr(original, attr, "")
        new_val = getattr(new_data, attr, "")
        if is_list:
            old_val = ", ".join(old_val) if old_val else ""
            new_val = ", ".join(new_val) if new_val else ""
        old_str = str(old_val or "")
        new_str = str(new_val or "")
        if old_str != new_str:
            lines.append(f"【{label}】\n  旧: {old_str[:200]}\n  新: {new_str[:200]}")
    return "\n\n".join(lines)


def _show_diff_dialog(self: MyMAinWindow, diff_text: str) -> bool:
    """弹窗显示字段级改动，返回用户是否确认保存。"""
    dialog = QDialog(self)
    dialog.setWindowTitle("确认保存 — 检测到以下改动")
    dialog.setMinimumSize(520, 400)
    layout = QVBoxLayout(dialog)
    text_edit = QPlainTextEdit(diff_text)
    text_edit.setReadOnly(True)
    layout.addWidget(text_edit)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
    cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
    if save_btn:
        save_btn.setText("保存")
    if cancel_btn:
        cancel_btn.setText("取消")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    return dialog.exec() == QDialog.DialogCode.Accepted


def pushButton_nfo_lib_save_clicked(self: MyMAinWindow) -> None:
    """保存当前编辑的 NFO（保存前弹窗显示字段级 diff）。"""
    nfo_path: Path | None = getattr(self, "_nfo_lib_current_path", None)
    if not nfo_path or not nfo_path.is_file():
        QMessageBox.warning(self, "提示", "请先从列表选择一个 NFO 文件")
        return

    # 从表单收集数据
    data = _collect_form_data(self)

    # 字段级 diff 预览：与加载时的原始数据对比
    original: CrawlersResult | None = getattr(self, "_nfo_lib_original_data", None)
    if original is not None:
        diff_text = _build_field_diff(original, data)
        if not diff_text:
            QMessageBox.information(self, "提示", "没有检测到任何改动")
            return
        if not _show_diff_dialog(self, diff_text):
            return

    button = self.Ui.pushButton_nfo_lib_save
    button.setEnabled(False)
    button.setText("保存中...")

    file_info = _make_file_info(nfo_path)
    nfo_folder = nfo_path.parent

    async def _save():
        try:
            success = await write_nfo(
                file_info, data, nfo_path, nfo_folder, update=True, skip_merge=True, preserve_tag_order=True
            )
            self._nfo_lib_save_result = success
            self.nfo_lib_save_done.emit(str(nfo_path))
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self._nfo_lib_save_result = False
            self.nfo_lib_save_done.emit(str(nfo_path))

    executor.submit(_save())


def on_nfo_lib_save_done(self: MyMAinWindow, nfo_path_str: str) -> None:
    """保存完成后恢复按钮状态（线程安全）。"""
    button = self.Ui.pushButton_nfo_lib_save
    success = getattr(self, "_nfo_lib_save_result", False)
    if success:
        button.setText("已保存!")
        signal_qt.show_log_text(f"NFO 已保存: {nfo_path_str}")
    else:
        button.setText("保存失败!")
        signal_qt.show_log_text(f"NFO 保存失败: {nfo_path_str}")

    # 1.5 秒后恢复按钮
    from PyQt6.QtCore import QTimer

    def _restore():
        button.setEnabled(True)
        button.setText("保存当前nfo文件")

    QTimer.singleShot(1500, _restore)


# 演员/标签独立匹配的字段：只含演员名与标签值，不与番号/标题/
# 发行日等其他字段混同（用户明确要求）
_NFO_ACTOR_TAG_XPATHS = (
    "//actor/name/text()",
    "//tag/text()",
)
# 纯数字词精确比对的数字字段：年份/时长/评分
_NFO_NUMBER_XPATHS = (
    "//year/text()",
    "//runtime/text()",
    "//rating/text()",
)
# 日期形词精确比对的发行日字段
_NFO_RELEASE_XPATHS = (
    "//release/text()",
    "//releasedate/text()",
    "//premiered/text()",
)


# 先于拆词抠出的日期片段：Y-M-D（含 / 与年月日）或 6/8 位纯数字。
# 注意分隔符不含空白——含空白的写法退化成三词 AND（宽松但可用），
# 且避免把 "238 5.0" 这类误抠成日期导致回归。
_DATE_PIECE_RE = re.compile(r"\d{2,4}[-./·・/／年月]\d{1,2}[-./·・/／月]\d{1,2}日?|(?<!\d)(\d{6}|\d{8})(?!\d)")


def _split_keyword(keyword: str) -> list[str]:
    """拆词：日期片段整体保留，其余按逗号/顿号/分号/空白/斜杠拆。

    拆出的空段一律丢弃：首尾多余逗号、连续逗号、全角/半角混用
    都不影响匹配（粘贴 `,A,B，` 与 `A,B` 等价；全是逗号则
    视为空搜索显示全部）。
    """
    pieces: list[str] = []

    def _cut(m: re.Match) -> str:
        pieces.append(m.group(0))
        return f"\x00{len(pieces) - 1}\x00"

    rest = _DATE_PIECE_RE.sub(_cut, keyword)
    tokens: list[str] = []
    for t in re.split(r"[,，、;；\s/|/]+", rest):
        if not t:
            continue
        m = re.fullmatch(r"\x00(\d+)\x00", t)
        tokens.append(pieces[int(m.group(1))] if m else t)
    return tokens


# 全角→半角归一（冒号/逗号/句点/斜杠/分号/空格）：`系列: ポルノスター`
# 与标签里的 `系列：ポルノスター` 按同一写法比对。`、`/`；`归一后
# 仍是拆词分隔符，行为不变。
_FULLWIDTH_MAP = str.maketrans({"：": ":", "，": ",", "．": ".", "／": "/", "；": ";", "、": ",", "　": " "})


def _normalize_token_text(text: str) -> str:
    return text.translate(_FULLWIDTH_MAP)


# 纯数字词：整数或一位以上小数（如 `1 / 238 / 2017 / 5.0`）
_NUMERIC_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?$")


# 完整日期词：Y-M-D（分隔符 - . / · ・ ／ 年月日）或 6/8 位纯数字
_DATE_FULL_RE = re.compile(
    r"^(\d{2}|\d{4})[-./·・/／年月](\d{1,2})[-./·・/／月](\d{1,2})日?$|^(\d{6}|\d{8})$"
)


def _date_candidates(year: int, month: int, day: int) -> list[str]:
    """合法性校验通过则返回 [YYYY-MM-DD, YY-MM-DD]，否则空列表。"""
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return []
    return [f"{year:04d}-{month:02d}-{day:02d}", f"{year % 100:02d}-{month:02d}-{day:02d}"]


def _token_variants(token: str) -> list[str]:
    """单个搜索词的匹配候选：原串 + 日期归一化展开。

    NFO 内发行日按 core 逻辑存为规范 `YYYY-MM-DD`，用户手写
    `YY-MM-DD / YYYY.MM.DD / YYYY·MM·DD / YYYY年MM月DD日 /
    YYYYMMDD / YYMMDD` 等都展开成规范形再比对（不区分大小写
    由调用方统一 lower 处理）。
    两位年份同时展开 19xx/20xx（如 `13-06-08` → `2013-06-08`），
    误命中的那支在真实数据里不存在，无实际影响。
    """
    variants = [token]
    m = _DATE_FULL_RE.match(token)
    if m:
        if m.group(4) is not None:
            compact = m.group(4)
            if len(compact) == 8:
                variants.extend(
                    _date_candidates(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
                )
            else:
                yy, month, day = int(compact[:2]), int(compact[2:4]), int(compact[4:6])
                variants.extend(_date_candidates(2000 + yy, month, day))
                variants.extend(_date_candidates(1900 + yy, month, day))
        else:
            year_s, month, day = m.group(1), int(m.group(2)), int(m.group(3))
            if len(year_s) == 4:
                variants.extend(_date_candidates(int(year_s), month, day))
            else:
                yy = int(year_s)
                variants.extend(_date_candidates(2000 + yy, month, day))
                variants.extend(_date_candidates(1900 + yy, month, day))
    # 去重保序
    return list(dict.fromkeys(variants))


def _haystack_matches(haystack: str, token: str) -> bool:
    """文件名快路径：原子串匹配（`261` 照样定位 `ARM-261`）。

    任一候选命中即算该词命中（日期多写法 OR，词间仍是 AND）。
    """
    return any(v in haystack for v in _token_variants(token))


def _nfo_matches(index: tuple[str, frozenset, frozenset], token: str) -> bool:
    """NFO 慢路径：演员/标签独立匹配，不与番号/标题/发行日等混同。

    - 日期形词：归一化后与发行日精确比对（`13-06-08`→`2013-06-08`）；
    - 纯数字词：只与数字字段精确相等（年份/时长/评分）——`1`/`2`
      不等于任何数字字段，故含它们的粘贴整条落空；
    - 其他词：只在演员名/标签值内子串匹配——`ポルノスター,ABP,
      园田美樱,2` 中前三词命中标签/演员，`2` 落空则整条不显示。
    """
    text, numbers, releases = index
    if _DATE_FULL_RE.match(token):
        return any(v in releases for v in _token_variants(token))
    if _NUMERIC_TOKEN_RE.match(token):
        return token in numbers
    return any(v in text for v in _token_variants(token))


def _parse_nfo_search_text(nfo_path: Path) -> tuple[str, frozenset, frozenset]:
    """解析 NFO 拼成小写可搜索索引 `(演员标签文本, 数字字段集, 发行日集)`。

    演员/标签独立匹配：文本只含演员名与标签值，不含番号/标题/
    导演/片商/简介等其他字段；数字字段（年份/时长/评分，
    `criticrating` 按 core 逻辑换算回 10 分制一并收录）单独成集，
    供纯数字词精确比对；发行日（release/releasedate/premiered）
    单独成集，供日期词精确比对。失败回退到文件名。
    全角标点归一到半角后再 lower。
    """
    fallback = _normalize_token_text(nfo_path.stem).lower()
    parts: list[str] = []
    numbers: set[str] = set()
    releases: set[str] = set()
    try:
        raw = nfo_path.read_bytes()
    except OSError:
        return (fallback, frozenset(), frozenset())
    try:
        from lxml import etree

        root = etree.fromstring(raw, etree.XMLParser(encoding="utf-8", recover=True))
        for xp in _NFO_ACTOR_TAG_XPATHS:
            parts.extend(str(v) for v in root.xpath(xp))
        for xp in _NFO_NUMBER_XPATHS:
            numbers.update(str(v) for v in root.xpath(xp))
        for xp in _NFO_RELEASE_XPATHS:
            releases.update(str(v) for v in root.xpath(xp))
        for v in root.xpath("//criticrating/text()"):
            numbers.add(str(v))
            try:
                numbers.add(str(int(str(v)) / 10))
            except ValueError:
                pass
    except Exception:
        pass
    text = _normalize_token_text("\n".join(parts)).lower()
    return (text, frozenset(numbers), frozenset(releases))


def _nfo_lib_search_text(self: MyMAinWindow, nfo_path: Path) -> tuple[str, frozenset, frozenset]:
    """取 NFO 可搜索索引（按 mtime 缓存，文件改动后自动重解析）。"""
    cache = getattr(self, "_nfo_lib_search_cache", None)
    if cache is None:
        cache = self._nfo_lib_search_cache = {}
    key = str(nfo_path)
    try:
        mtime = nfo_path.stat().st_mtime
    except OSError:
        mtime = -1.0
    hit = cache.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    text = _parse_nfo_search_text(nfo_path)
    cache[key] = (mtime, text)
    return text


def lineEdit_nfo_lib_filter_changed(self: MyMAinWindow) -> None:
    """筛选框文本变化时过滤列表（大小写不敏感）。

    演员/标签独立匹配，不与番号/标题/发行日等混同：
    文字词只在演员名/标签值内子串匹配；日期形词与发行日精确比对；
    纯数字词只与年份/时长/评分精确相等；番号走文件名快路径。
    列表项文本只有番号（stem），其余字段在 NFO 文件内：
    先走文件名快路径（命中则免磁盘 IO），否则读缓存的可搜索索引。
    关键词按逗号/顿号/分号/空白/斜杠拆词，多词之间是 AND 关系、
    与顺序无关（如 `矢沢りょう,川上优` 与 `川上优,矢沢りょう` 等价，
    `美乳,巨乳` 要求同一 NFO 内两个标签全包含）。
    日期写法归一：`13-06-08 / 2013.06.08 / 2013·06·08 /
    2013年06月08日 / 20130608` 等都展开成 NFO 内的规范形
    `YYYY-MM-DD` 再与发行日精确比对。
    纯数字词只与数字字段精确相等（年份/时长/评分）——`1`/`2`
    不等于任何数字字段，故 `ポルノスター,ABP,园田美樱,2` 这类粘贴
    整条落空，去掉 `2` 即命中；`238 / 5.0 / 2009` 等照样精确命中。
    全角冒号/逗号等归一到半角后再比对。
    """
    keyword = _normalize_token_text(self.Ui.lineEdit_nfo_lib_filter.text().strip().lower())
    tokens = _split_keyword(keyword)
    for i in range(self.Ui.listWidget_nfo_lib.count()):
        item = self.Ui.listWidget_nfo_lib.item(i)
        if not tokens or all(_haystack_matches(item.text().lower(), t) for t in tokens):
            item.setHidden(False)
            continue
        nfo_path_str = item.data(NFO_PATH_ROLE)
        if not nfo_path_str:
            item.setHidden(True)
            continue
        search = _nfo_lib_search_text(self, Path(nfo_path_str))
        item.setHidden(not all(_nfo_matches(search, t) for t in tokens))


def pushButton_nfo_lib_crop_clicked(self: MyMAinWindow) -> None:
    """裁剪封面：打开裁剪窗口。"""
    nfo_path: Path | None = getattr(self, "_nfo_lib_current_path", None)
    if not nfo_path:
        QMessageBox.warning(self, "提示", "请先选择一个 NFO 文件")
        return

    # 尝试找到同目录的封面图
    poster_path = nfo_path.with_name(nfo_path.stem + "-poster.jpg")
    if not poster_path.is_file():
        poster_path = nfo_path.parent / "poster.jpg"
    if not poster_path.is_file():
        # 尝试 thumb
        thumb_path = nfo_path.with_name(nfo_path.stem + "-thumb.jpg")
        if thumb_path.is_file():
            poster_path = thumb_path
        else:
            poster_path = nfo_path.parent / "thumb.jpg"

    if not poster_path.is_file():
        QMessageBox.warning(self, "提示", "未找到可裁剪的封面图文件")
        return

    # showimage 内部按 Path 使用（img_path.as_posix()/parent/stem），传 str 会抛
    # AttributeError，而 PyQt 只把异常打到 stderr，界面上就表现为「点了没反应」
    self.cutwindow.showimage(poster_path, None)
    self.cutwindow.show()
    self.cutwindow.raise_()
    self.cutwindow.activateWindow()


def _get_selected_nfo_paths(self: MyMAinWindow) -> list[Path]:
    """获取列表中所有选中的 NFO 路径。"""
    return [Path(item.data(NFO_PATH_ROLE)) for item in self.Ui.listWidget_nfo_lib.selectedItems()]


# ============= 右侧预览图大图窗口 =============

# 图片类型 -> core/nfo.py 里的图片命名（同名优先，其次目录内的通用名）
_NFO_LIB_IMAGE_SUFFIX = {"poster": "-poster.jpg", "thumb": "-thumb.jpg"}
_NFO_LIB_IMAGE_FALLBACK = {"poster": "poster.jpg", "thumb": "thumb.jpg"}
_NFO_LIB_IMAGE_LABEL = {"poster": "封面", "thumb": "缩略图"}


def _resolve_nfo_image(nfo_path: Path, kind: str) -> Path | None:
    """按 core/nfo.py 的命名规则定位 nfo 同目录下的封面 / 缩略图。"""
    named = nfo_path.with_name(nfo_path.stem + _NFO_LIB_IMAGE_SUFFIX.get(kind, "-poster.jpg"))
    fallback = nfo_path.parent / _NFO_LIB_IMAGE_FALLBACK.get(kind, "poster.jpg")
    for candidate in (named, fallback):
        if candidate.is_file():
            return candidate
    return None


def _nfo_lib_image_entries(self: MyMAinWindow) -> list[tuple[Path, list[Path]]]:
    """按 NFO 列表顺序组装 [(nfo 路径, 该番号的 [封面, 缩略图])]，只保留有图的番号。

    上下键要「按番号切换」，所以顺序取 NFO 列表（跳过被筛选隐藏的行）；
    列表为空时退回扫描目录。封面在前、缩略图在后，与 core/nfo.py 的判定一致。
    """
    widget = self.Ui.listWidget_nfo_lib
    candidates: list[Path] = []
    for row in range(widget.count()):
        item = widget.item(row)
        if item.isHidden():
            continue
        nfo_path = item.data(NFO_PATH_ROLE)
        if nfo_path:
            candidates.append(Path(nfo_path))
    if not candidates:
        dir_text = self.Ui.lineEdit_nfo_lib_dir.text().strip()
        root = Path(dir_text) if dir_text else None
        if root is not None and root.is_dir():
            candidates = sorted(root.rglob("*.nfo"), key=lambda path: str(path).lower())

    entries: list[tuple[Path, list[Path]]] = []
    for nfo_path in candidates:
        images = [image for kind in ("poster", "thumb") if (image := _resolve_nfo_image(nfo_path, kind))]
        if images:
            entries.append((nfo_path, images))
    return entries


def _get_nfo_lib_preview_window(self: MyMAinWindow) -> NfoPreviewWindow:
    """惰性创建大图预览窗口（挂在主窗口下，随主窗口一起隐藏）。"""
    window = getattr(self, "nfo_lib_preview_window", None)
    if window is None:
        window = NfoPreviewWindow(self)
        window.nfo_index_changed.connect(self._on_nfo_lib_preview_nfo_index_changed)
        self.nfo_lib_preview_window = window
    return window


def nfo_lib_preview_clicked(self: MyMAinWindow, kind: str) -> None:
    """单击右侧预览图：按主窗口当前状态弹出大图。

    ← / → 切换同一番号的封面与缩略图，↑ / ↓ 切换不同番号，Esc 关闭。
    """
    entries = _nfo_lib_image_entries(self)
    current: Path | None = getattr(self, "_nfo_lib_current_path", None)
    if current is None or not entries:
        signal_qt.show_log_text("没有可预览的图片")
        return
    index = next((i for i, (nfo_path, _) in enumerate(entries) if nfo_path == current), 0)
    # 优先打开被单击的那类图（点海报框看封面、点缩略图框看缩略图），没有就退回第一张
    images = entries[index][1]
    image_index = next((i for i, image in enumerate(images) if kind in image.name.lower()), 0)
    window = _get_nfo_lib_preview_window(self)
    window.title_prefix = f"{_NFO_LIB_IMAGE_LABEL.get(kind, '图片')}预览"
    window.show_entries(entries, index, image_index)
    window.show_matching(self)


def _on_nfo_lib_preview_nfo_index_changed(self: MyMAinWindow, index: int) -> None:
    """大图窗口用上下键换番号后，把 NFO 列表选中项跟着切过去。"""
    window = getattr(self, "nfo_lib_preview_window", None)
    paths: list[Path] = list(getattr(window, "nfo_paths", [])) if window else []
    if not (0 <= index < len(paths)):
        return
    target = str(paths[index])
    widget = self.Ui.listWidget_nfo_lib
    for row in range(widget.count()):
        item = widget.item(row)
        if item.data(NFO_PATH_ROLE) != target:
            continue
        if item.isHidden():  # 被筛选掉的行不动，避免筛选结果被按键打乱
            return
        widget.setCurrentRow(row)
        return


def _parse_tags(text: str) -> list[str]:
    """解析逗号分隔的标签文本（中英文逗号都支持）。"""
    return [t.strip() for t in text.replace("，", ",").split(",") if t.strip()]


async def _batch_modify(
    self: MyMAinWindow,
    nfo_paths: list[Path],
    modify_fn,
) -> tuple[int, int]:
    """批量读取-修改-写回 NFO 文件。

    Args:
        nfo_paths: NFO 文件路径列表
        modify_fn: 接受 CrawlersResult，原地修改后返回的回调

    Returns:
        (成功数, 失败数)
    """
    success = 0
    failed = 0
    total = len(nfo_paths)
    for i, nfo_path in enumerate(nfo_paths, 1):
        try:
            # 线程安全：进度走信号，由主线程槽更新标签
            self.nfo_lib_batch_progress.emit(f"处理中 {i}/{total}: {nfo_path.stem}")
            data, _info = await get_nfo_data(nfo_path.with_suffix(""), nfo_path.stem)
            if data is None:
                failed += 1
                signal_qt.show_log_text(f"  🔴 读取失败: {nfo_path.name}")
                continue
            modify_fn(data)
            file_info = _make_file_info(nfo_path)
            await write_nfo(
                file_info, data, nfo_path, nfo_path.parent, update=True, skip_merge=True, preserve_tag_order=True
            )
            success += 1
        except Exception:
            failed += 1
            signal_qt.show_log_text(f"  🔴 {nfo_path.name}: {traceback.format_exc()[-200:]}")
    return success, failed


def pushButton_nfo_lib_batch_actor_clicked(self: MyMAinWindow) -> None:
    """批量替换演员名。"""
    paths = _get_selected_nfo_paths(self)
    if not paths:
        QMessageBox.warning(self, "提示", "请先在列表中选择 NFO 文件")
        return
    new_actor = self.Ui.lineEdit_nfo_lib_batch_actor.text().strip()
    if not new_actor:
        QMessageBox.warning(self, "提示", "请输入新演员名")
        return

    def set_actor(data: CrawlersResult):
        data.actor = new_actor
        data.all_actor = new_actor

    _run_batch(self, paths, set_actor)


def pushButton_nfo_lib_batch_add_tag_clicked(self: MyMAinWindow) -> None:
    """批量加标签。"""
    paths = _get_selected_nfo_paths(self)
    if not paths:
        QMessageBox.warning(self, "提示", "请先在列表中选择 NFO 文件")
        return
    new_tags = _parse_tags(self.Ui.lineEdit_nfo_lib_batch_add_tag.text())
    if not new_tags:
        QMessageBox.warning(self, "提示", "请输入要添加的标签")
        return

    def add_tags(data: CrawlersResult):
        existing = set(data.tags) if data.tags else set()
        existing.update(new_tags)
        data.tags = list(existing)
        data.tag = ",".join(existing)

    _run_batch(self, paths, add_tags)


def pushButton_nfo_lib_batch_del_tag_clicked(self: MyMAinWindow) -> None:
    """批量删标签。"""
    paths = _get_selected_nfo_paths(self)
    if not paths:
        QMessageBox.warning(self, "提示", "请先在列表中选择 NFO 文件")
        return
    del_tags = set(_parse_tags(self.Ui.lineEdit_nfo_lib_batch_del_tag.text()))
    if not del_tags:
        QMessageBox.warning(self, "提示", "请输入要删除的标签")
        return

    def remove_tags(data: CrawlersResult):
        remaining = [t for t in (data.tags or []) if t not in del_tags]
        data.tags = remaining
        data.tag = ",".join(remaining)

    _run_batch(self, paths, remove_tags)


def pushButton_nfo_lib_batch_series_clicked(self: MyMAinWindow) -> None:
    """批量统一系列名。"""
    paths = _get_selected_nfo_paths(self)
    if not paths:
        QMessageBox.warning(self, "提示", "请先在列表中选择 NFO 文件")
        return
    new_series = self.Ui.lineEdit_nfo_lib_batch_series.text().strip()
    if not new_series:
        QMessageBox.warning(self, "提示", "请输入系列名")
        return

    def set_series(data: CrawlersResult):
        data.series = new_series

    _run_batch(self, paths, set_series)


def pushButton_nfo_lib_batch_save_clicked(self: MyMAinWindow) -> None:
    """批量保存：将当前列表中所有被修改过的 NFO 重新写盘。

    由于批量修改（替换演员/加删标签/统一系列）已经即时写盘，
    本按钮作为"刷新所有选中项"的入口，重新读取并写回当前选中 NFO。
    """
    paths = _get_selected_nfo_paths(self)
    if not paths:
        QMessageBox.warning(self, "提示", "请先在列表中选择 NFO 文件")
        return
    _run_batch(self, paths, lambda data: None)


def _run_batch(self: MyMAinWindow, paths: list[Path], modify_fn) -> None:
    """启动后台批量任务。"""
    total = len(paths)
    self.Ui.label_nfo_lib_batch_status.setText(f"开始批量处理 {total} 个文件...")
    signal_qt.show_log_text(f"NFO 库管理: 批量处理 {total} 个文件")

    async def _run():
        try:
            success, failed = await _batch_modify(self, paths, modify_fn)
            self._nfo_lib_batch_result = (success, failed, total)
            self.nfo_lib_batch_done.emit("")
        except Exception:
            signal_qt.show_traceback_log(traceback.format_exc())
            self._nfo_lib_batch_result = (0, total, total)
            self.nfo_lib_batch_done.emit("")

    executor.submit(_run())


def on_nfo_lib_batch_progress(self: MyMAinWindow, text: str) -> None:
    """批量进度信号槽（主线程）：更新状态标签。"""
    self.Ui.label_nfo_lib_batch_status.setText(text)


def on_nfo_lib_batch_done(self: MyMAinWindow, _arg: str) -> None:
    """批量任务完成后在主线程更新状态（线程安全）。"""
    result = getattr(self, "_nfo_lib_batch_result", (0, 0, 0))
    success, failed, total = result
    self.Ui.label_nfo_lib_batch_status.setText(f"完成: 成功 {success} / 失败 {failed} / 共 {total}")
    signal_qt.show_log_text(f"NFO 库管理: 批量完成 — 成功 {success}，失败 {failed}，共 {total}")


# ============= 右键菜单 =============


def listWidget_nfo_lib_context_menu(self: MyMAinWindow, pos) -> None:
    """NFO 列表右键菜单：重新刮削番号 / 打开所在目录 / 删除nfo文件。"""
    items = self.Ui.listWidget_nfo_lib.selectedItems()
    if not items:
        return
    nfo_paths = [Path(item.data(NFO_PATH_ROLE)) for item in items]

    menu = QMenu(self)
    if len(nfo_paths) == 1:
        title_action = QAction(f"{nfo_paths[0].stem}", self)
        title_action.setEnabled(False)
        menu.addAction(title_action)
        menu.addSeparator()
    else:
        count_action = QAction(f"已选择 {len(nfo_paths)} 项", self)
        count_action.setEnabled(False)
        menu.addAction(count_action)
        menu.addSeparator()

    act_rescrape = QAction("重新刮削番号", self)
    act_open_folder = QAction("打开所在目录", self)
    act_delete = QAction("删除nfo文件" + (f"（{len(nfo_paths)} 个）" if len(nfo_paths) > 1 else ""), self)
    menu.addAction(act_rescrape)
    menu.addAction(act_open_folder)
    menu.addSeparator()
    menu.addAction(act_delete)

    chosen = menu.exec(self.Ui.listWidget_nfo_lib.viewport().mapToGlobal(pos))
    if chosen == act_rescrape:
        _nfo_lib_rescrape(self, nfo_paths)
    elif chosen == act_open_folder:
        open_file_thread(nfo_paths[0], True)
    elif chosen == act_delete:
        _nfo_lib_delete_nfo(self, nfo_paths)


def _nfo_lib_rescrape(self: MyMAinWindow, nfo_paths: list[Path]) -> None:
    """重新刮削：把选中 NFO 对应的视频加入重新刮削队列。"""
    from mdcx.core.scraper import again_search
    from mdcx.models.flags import Flags

    added = 0
    for nfo_path in nfo_paths:
        # 找到对应的视频文件
        file_info = _make_file_info(nfo_path)
        video_path = file_info.file_path
        if not video_path.is_file():
            signal_qt.show_log_text(f" 🟡 未找到对应视频文件，跳过: {nfo_path.name}")
            continue
        # 番号默认用 NFO 文件名，可弹窗修改（单个时）
        number = nfo_path.stem.upper()
        if len(nfo_paths) == 1:
            text, ok = _ask_number(self, video_path.name, number)
            if not ok or not text:
                return
            number = text
        Flags.again_dic[video_path] = (number, "", "")
        added += 1

    if added:
        signal_qt.show_log_text(f" 💡 已添加 {added} 个重新刮削任务")
        signal_qt.show_scrape_info(f"💡 已添加刮削！{get_current_time()}")
        if self.Ui.pushButton_start_cap.text() == "开始":
            again_search()


def _ask_number(self: MyMAinWindow, video_name: str, default_number: str):
    from PyQt6.QtWidgets import QInputDialog

    return QInputDialog.getText(self, "输入番号重新刮削", f"文件名: {video_name}\n请输入番号:", text=default_number)


def _nfo_lib_delete_nfo(self: MyMAinWindow, nfo_paths: list[Path]) -> None:
    """删除选中的 NFO 文件（带确认）。"""
    if len(nfo_paths) == 1:
        box_text = f"将要删除文件: \n{nfo_paths[0]}\n\n 你确定要删除吗？"
    else:
        preview = "\n".join(str(p) for p in nfo_paths[:10])
        more = f"\n... 等共 {len(nfo_paths)} 个" if len(nfo_paths) > 10 else ""
        box_text = f"将要删除 {len(nfo_paths)} 个 NFO 文件：\n{preview}{more}\n\n你确定要继续吗？"

    box = QMessageBox(QMessageBox.Icon.Warning, "删除 NFO", box_text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    yes_btn = box.button(QMessageBox.StandardButton.Yes)
    no_btn = box.button(QMessageBox.StandardButton.No)
    if yes_btn:
        yes_btn.setText("删除")
    if no_btn:
        no_btn.setText("取消")
    box.setDefaultButton(QMessageBox.StandardButton.No)
    if box.exec() != QMessageBox.StandardButton.Yes:
        return

    # 删除后从列表移除的项
    removed_names = set()
    success_count = 0
    for nfo_path in nfo_paths:
        result, error_info = delete_file_sync(nfo_path)
        if result:
            success_count += 1
            removed_names.add(nfo_path.stem)
            signal_qt.show_log_text(f" ✅ 已删除: {nfo_path}")
        else:
            reason = error_info or "未知原因"
            signal_qt.show_log_text(f" ❌ 删除失败: {nfo_path}\n    原因: {reason}")

    # 从列表移除已删除的项
    for row in range(self.Ui.listWidget_nfo_lib.count() - 1, -1, -1):
        item = self.Ui.listWidget_nfo_lib.item(row)
        if item.text() in removed_names and Path(item.data(NFO_PATH_ROLE)).stem in removed_names:
            self.Ui.listWidget_nfo_lib.takeItem(row)

    # 更新计数
    remaining = self.Ui.listWidget_nfo_lib.count()
    self.Ui.label_nfo_lib_count.setText(f"共 {remaining} 个")
    signal_qt.show_log_text(f"NFO 库管理: 删除完成 — 成功 {success_count}，失败 {len(nfo_paths) - success_count}")
