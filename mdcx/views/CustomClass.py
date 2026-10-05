from dataclasses import dataclass, field

import math

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QComboBox, QLabel, QScrollArea, QSlider, QSpinBox, QWidget

# 子控件跟随分类
_STRETCH = "stretch"  # 宽幅拉伸：宽 ≥ groupBox 内宽 55%（输入框等）
_DOCK_RIGHT = "dock_right"  # 右缘锚定：设计右缘 ≥ groupBox 内宽 90%（浏览按钮等）
_KEEP = "keep"  # 保持原位：其余（标签、小组件）


@dataclass
class _InnerItem:
    """groupBox 内部子项：控件 + 设计几何 + 跟随分类."""

    widget: QWidget
    geometry: tuple[int, int, int, int]
    kind: str = _KEEP


@dataclass
class _WideChildEntry:
    """宽幅顶层容器登记项：容器本体 + 设计几何 + 内部子项清单."""

    widget: QWidget
    geometry: tuple[int, int, int, int]
    inner: list[_InnerItem] = field(default_factory=list)


class CustomQComboBox(QComboBox):
    def wheelEvent(self, e):
        if e.type() == QEvent.Type.Wheel:
            e.ignore()


class CustomQSpinBox(QSpinBox):
    def wheelEvent(self, e):
        if e.type() == QEvent.Type.Wheel:
            e.ignore()


class CustomQSlider(QSlider):
    def wheelEvent(self, e):
        if e.type() == QEvent.Type.Wheel:
            e.ignore()


def wrapped_label_height(label: QLabel, width: int, min_h: int, max_h: int) -> int:
    """QLabel 多行文本所需高度（QLabel.heightForWidth 实测不可靠，勿用）。

    背景：演员库工具页裁字事故——离线实测同字体同宽度下，
    QLabel.heightForWidth(221) 返回 26（单行高度，错误），而 QTextDocument
    量出 merged=50、minnano=36（正确）。heightForWidth 拿到的是陈旧
    sizeHint，与换行后真实高度无关。
    做法：用 QTextDocument（与 QLabel 同一文本排版引擎）按 label 当前
    字体/文本量出换行总高，向上取整再留 6px 引擎差异余量，夹到 [min_h, max_h]。
    调用方负责让 max_h 对应的底边不侵入下一行控件。
    """
    doc = QTextDocument()
    doc.setDefaultFont(label.font())
    doc.setPlainText(label.text() or "")
    doc.setTextWidth(max(width, 1))
    need = math.ceil(doc.size().height()) + 6
    return max(min_h, min(need, max_h))


class CustomScrollArea(QScrollArea):
    """widgetResizable=true 时按子控件包围盒维护内容最小高度的滚动区。

    背景：设计器生成的滚动区内容 widget 无布局，子控件绝对定位；
    widgetResizable=false 时内容保持固定几何尺寸、垂直滚动正常，但内容
    宽度不跟随视口（高 DPI 下右侧被裁剪）；widgetResizable=true 后宽度自
    适应，但 Qt 对无布局 widget 的最小尺寸提示不来自 childrenRect，内容
    被拉伸到视口高度，垂直滚动条失效。这里在滚动区尺寸变化 / 页面显示时
    按 childrenRect 显式补最小高度，同时保留宽度自适应。

    另：内容里的宽幅容器（groupBox 等，设计右缘≈内容设计右缘）在视口变宽时
    跟随拉伸——休眠页 content 拉宽后绝对定位子控件不会自行展开，表单会缩在
    设计宽度 860 内、右侧大片留白（用户反馈"最大化后内容横向不放大"）。
    """

    # Leave enough room for the last row, frame, font metrics, and DPI scaling.
    # ≥ 浮框带侵入视口底部的 63px（page_setting 底部配置浮框盖住滚动区下缘），
    # 保证滚动到底时最后一行完全位于浮框带上方（用户截图：末行文字从浮框后透出）。
    _CONTENT_BOTTOM_MARGIN = 72

    # 顶层容器判定为"宽幅"的右缘阈值比例：设计右缘 ≥ 内容设计宽的 85%。
    _WIDE_CHILD_RIGHT_RATIO = 0.85

    def set_content_bottom_margin(self, margin: int) -> None:
        """按实例覆盖内容底部余量（议题 #117）。

        默认 72px 是为 page_setting 底部配置浮框带（侵入视口 63px）留的避让空间；
        信息管理表单页没有任何浮框遮挡，同样的余量白白吃掉一行多高度，把
        「保存当前nfo文件」按钮挤出视口、凭空多出垂直滚动条。
        """
        self._content_bottom_margin = margin

    def content_bottom_margin(self) -> int:
        return getattr(self, "_content_bottom_margin", self._CONTENT_BOTTOM_MARGIN)

    def set_content_right_trim(self, trim: int) -> None:
        """按实例设置内容右侧内收量（默认 0）。

        软件工具页卡片右缘比软件设置页同类卡片宽出 4px（800~2200 窗宽下
        离线实测恒定，与 DPI 无关），左缘不动：extra 统一减去该值，
        容器与内部跟随项整体左收，内部控件相对位置不变。
        """
        self._content_right_trim = max(trim, 0)

    def content_right_trim(self) -> int:
        return getattr(self, "_content_right_trim", 0)

    def sync_content_min_height(self) -> None:
        content = self.widget()
        if content is None:
            return
        # 议题 #82：layout 驱动的内容（如 NFO 表单 QFormLayout）不能按 childrenRect
        # 算最小高——Expanding 行（简介/标签多行框）在超高容器里会分得额外空间，
        # childrenRect 随之膨胀，最小高一旦抬高就自锁（还原后永远降不回紧凑态，
        # 保存按钮被推出视口）。layout.sizeHint() 是紧凑排布尺寸，与容器拉伸无关。
        content_layout = content.layout()
        if content_layout is not None:
            content_layout.invalidate()
            size_hint = content_layout.sizeHint()
            if size_hint.height() <= 0:
                return
            # 议题 #117：宽度下限取布局硬最小值，不用 sizeHint 首选宽。视口窄于首选宽
            # 时（垂直滚动条一占位就少 14px），sizeHint 宽会把内容顶死在首选宽不缩，
            # 内容右缘被视口裁掉——输入框右侧圆角消失在滚动条底下（用户截图）。
            # sizeHint 宽只是"首选"，字段本身横向 Expanding，可安全压到布局最小宽。
            hard_min_width = content_layout.minimumSize().width()
            min_width = hard_min_width if hard_min_width > 0 else size_hint.width()
            # layout 驱动内容同样补底部余量：sizeHint 是紧凑排布高度，
            # 不加余量时滚动到底最后一行贴视口底、被浮框带盖住 63px
            min_height = size_hint.height() + self.content_bottom_margin()
        else:
            children_rect = content.childrenRect()
            if children_rect.height() <= 0:
                return
            # 无布局内容：min_width 不能以「可能被拉宽过的」childrenRect 为准——
            # 最大化后子控件被拉宽，childrenRect.right() 锁在高位，还原窗口时
            # widgetResizable 受 minimumWidth 阻挡无法把内容缩回视口，右侧被裁剪。
            # 以登记的设计宽为上界：拉宽场景内容宽由 viewport 决定（>min 不冲突），
            # 还原场景 min_width 回落到设计宽，内容随之缩回。
            design_w = getattr(content, "_wide_children_design_width", 0)
            measured_w = children_rect.right() + 1
            min_width = min(measured_w, design_w) if design_w > 0 else measured_w
            min_height = children_rect.bottom() + self.content_bottom_margin()
        if content.minimumWidth() != min_width or content.minimumHeight() != min_height:
            content.setMinimumWidth(min_width)
            content.setMinimumHeight(min_height)
            content.updateGeometry()

    def setWidget(self, widget) -> None:
        """登记内容设计几何（setupUi 阶段调用，此时全部为设计器几何）。"""
        super().setWidget(widget)
        if widget is not None:
            self._register_design_geometry(widget)

    # 输入类控件：横向自适应的标准控件，无论宽窄一律拉伸跟随
    _STRETCH_WIDGET_CLASSES = (
        "QLineEdit",
        "QTextEdit",
        "QPlainTextEdit",
        "QTextBrowser",
        "QComboBox",
        "QTreeWidget",
        "QListWidget",
        "QTableWidget",
        "QTreeWidget",
    )

    # 演员库维护三行由 MainWindow._sync_actor_db_tool_layout 接管（最大化才重排，
    # 还原恢复设计几何），此处不再自动拉伸/右缘锚定，避免通用逻辑覆盖定制布局。
    # 封面补图组三枚复选框（覆盖已有图片 / 添加水印 / 刮削过程中自动创建软链接）
    # 由 MainWindow._sync_cover_backfill_option_row 接管：它们按设计几何本就判为
    # None（宽 161/191 < 340、右缘 601 < 631），此处显式登记归属，防止日后组内
    # 几何变化被通用逻辑误判为 _DOCK_RIGHT 而与定制布局打架。
    # 命名页「. 小数点」也列入：右移对齐后右缘 560+110+1=671 ≥ 组宽 720*0.9=648，
    # 会被通用逻辑误判为 _DOCK_RIGHT 而在宽态额外右移 extra，与同行的「空格」
    # （420，右缘 531 → 不登记）拉开距离，破坏「同步等距右移」的诉求。
    #
    # 反向提醒——软链接助手组的「一键创建软链接」刻意不列入：它与下方移动组的
    # 「开始移动」同设计几何（x=140、宽 351、右缘 491），按通用规则判为 _STRETCH，
    # 两按钮左右边界在任何窗宽下都恒等，最大化时同步放大（这正是用户要的）。
    # 把它改窄到内半宽 340.5 以下、或塞进本集合，都会让它悄悄脱离拉伸而与
    # 「开始移动」错开；改动前请先看 tests/test_symlink_button_width.py。
    _MANUAL_WIDGET_NAMES = frozenset(
        {
            "checkBox_cd_part_point",
            "lineEdit_actor_db_nfo_dir",
            "pushButton_actor_db_pick_nfo_dir",
            "pushButton_actor_db_update_nfo_tmdbid",
            "comboBox_actor_db_alias_source",
            "checkBox_actor_db_alias_all",
            "label_actor_db_sync_slice_hint",
            "pushButton_actor_db_stop",
            "label_actor_db_open_desc",
            "label_actor_db_note",
            "pushButton_actor_db_open",
            "pushButton_actor_db_clean_male",
            "pushButton_actor_db_fill_minnano",
            "pushButton_actor_db_verify_tmdbid",
            "pushButton_actor_db_check",
            "label_actor_db_update_nfo_desc",
            "pushButton_actor_db_sync_aliases",
            "label_actor_db_sync_offset",
            "spinBox_actor_db_sync_offset",
            "label_actor_db_sync_limit",
            "spinBox_actor_db_sync_limit",
            "label_actor_db_sync_aliases_desc",
            "pushButton_actor_db_fill_zh_javdb",
            "label_actor_db_fill_zh_javdb_desc",
            "label_actor_db_desc",
            "checkBox_cover_backfill_overwrite",
            "checkBox_cover_backfill_watermark",
            "checkBox_create_link",
        }
    )

    def _classify_inner(self, sub: QWidget, inner_w: int, box_w: int) -> str | None:
        """groupBox 内部子项分类：拉伸 / 右缘锚定 / None（不登记保持原位）。"""
        if sub.objectName() in self._MANUAL_WIDGET_NAMES:
            return None  # 演员库三行定制布局，不参与通用跟随
        if sub.layout() is not None:
            return _STRETCH  # 布局容器：拉宽后 invalidate+activate 重排列宽
        meta = sub.metaObject()
        if meta is not None and meta.className() in self._STRETCH_WIDGET_CLASSES:
            return _STRETCH  # 输入类控件（输入框/下拉/列表/树）跟随拉宽
        sg = sub.geometry()
        if sg.width() >= inner_w * 0.5:
            return _STRETCH  # 其他宽幅控件（标签/分组框）跟随拉宽
        if sg.right() + 1 >= box_w * 0.9:
            return _DOCK_RIGHT  # 右缘控件（浏览/选择按钮）右缘锚定
        return None

    def _register_design_geometry(self, content: QWidget) -> None:
        """按设计几何登记宽幅顶层容器与内容基准宽。

        登记发生在 setupUi 的 setWidget 时刻，几何必然是设计器值；
        之后 widgetResizable/本类的拉伸不会覆盖登记数据，同步幂等。

        登记结构：顶层宽幅 QGroupBox + 其内部全部直接子项（布局容器与
        绝对定位控件并存的设计器产物）按设计几何分类——布局容器（内含
        QGridLayout）与宽幅输入框拉伸、右缘贴 groupBox 内缘的控件锚定
        右缘、其余保持原位。
        """
        design_w = content.width()
        threshold = int(design_w * self._WIDE_CHILD_RIGHT_RATIO)
        from PyQt6.QtWidgets import QGroupBox

        registry: list[_WideChildEntry] = []
        for child in content.findChildren(QGroupBox):
            if child.parentWidget() is not content:
                continue
            g = child.geometry()
            if g.width() <= 0 or g.right() + 1 < threshold:
                continue
            entry = _WideChildEntry(widget=child, geometry=(g.x(), g.y(), g.width(), g.height()))
            inner_w = g.width() - 20  # groupBox 内可用宽（左右各 ~10 边距）
            for sub in child.findChildren(QWidget):
                if sub.parentWidget() is not child:
                    continue
                sg = sub.geometry()
                if sg.width() <= 0 or sg.height() <= 0:
                    continue
                kind = self._classify_inner(sub, inner_w, g.width())
                if kind is None:
                    continue
                entry.inner.append(
                    _InnerItem(widget=sub, geometry=(sg.x(), sg.y(), sg.width(), sg.height()), kind=kind)
                )
            registry.append(entry)
        setattr(content, "_wide_children_design", registry)
        setattr(content, "_wide_children_design_width", design_w)

    def sync_wide_children_width(self) -> None:
        """宽幅顶层容器宽度跟随视口：视口宽于设计宽时拉宽，窄于设计宽时缩回。

        按登记的设计几何计算 extra = 视口宽 - 设计宽，各容器宽度 = 设计宽 + extra，
        保持设计左边距与右缘边距。groupBox 内部子项按分类跟随：
        布局容器与宽幅输入框拉伸（布局容器另需 invalidate+activate 强制重排，
        否则 QGridLayout 内输入框列宽不变）；右缘控件右缘锚定平移；其余保持原位。
        无宽幅容器的滚动区（如 NFO 库 360 宽表单）登记为空自动跳过。

        议题 #82：extra<=0 必须按同一公式缩回（旧实现直接 return 只增不减）——
        否则最大化后容器宽度锁死在高位，childrenRect 撑大 → content minimumWidth
        被永久抬高 → 还原窗口后内容右侧被视口裁剪（设置/工具页内容右缘消失）。
        固定「设计几何 + extra」公式双向幂等，无累积漂移。
        """
        content = self.widget()
        if content is None:
            return
        registry: list[_WideChildEntry] | None = getattr(content, "_wide_children_design", None)
        if not registry:
            return
        viewport = self.viewport()
        if viewport is None:
            return
        design_w = getattr(content, "_wide_children_design_width", 0)
        extra = viewport.width() - design_w - self.content_right_trim()
        for entry in registry:
            x, y, w, h = entry.geometry
            box = entry.widget
            box.setGeometry(x, y, max(w + extra, w // 2), h)
            for item in entry.inner:
                sub = item.widget
                sx, sy, sw, sh = item.geometry
                if item.kind == _STRETCH:
                    sub.setGeometry(sx, sy, max(sw + extra, sw // 2), sh)
                    inner_layout = sub.layout()
                    if inner_layout is not None:
                        # 布局系统对休眠/未重绘 widget 不自动激活，容器拉宽后
                        # 必须显式重排，否则 QGridLayout 内输入框列宽不变
                        inner_layout.invalidate()
                        inner_layout.activate()
                else:  # _DOCK_RIGHT
                    sub.move(sx + extra, sy)

    # 宽幅同步之后立刻执行的对齐钩子（可选，由外部按需赋值）。
    #
    # 为什么需要：通用拉伸只保证「不越界」，它把右缘控件钉在右缘、宽幅控件按
    # 「设计宽 + extra」铺开。某些控件还要在拉伸落定后再对齐到同页别的控件
    # （设置-演员页三行要对齐「请求Graphis最新图片」）。若把这一步留给外层在
    # 下一轮事件里做，「右缘锚定」这个中间态会先被绘制出来——用户看到的就是
    # 控件「先在右边、再跳到左边」。放进同一个 resizeEvent 里两步原子完成，
    # 中间态就不会出现。钩子在拉伸之后调用，故能读到终态 extra。
    _post_wide_sync_hook = None
    _in_post_wide_sync_hook = False

    def _run_post_wide_sync_hook(self) -> None:
        """执行宽幅同步后的对齐钩子（未安装时零成本）。

        带重入保护：钩子内部会 setGeometry，一旦连带引发本滚动区再次 resize，
        没有保护就会无限递归（实测会把栈打爆）。重入时直接跳过——外层那一遍
        已经在正确的几何上跑完，对齐结果不会因此丢失。
        """
        hook = self._post_wide_sync_hook
        if hook is None or self._in_post_wide_sync_hook:
            return
        self._in_post_wide_sync_hook = True
        try:
            hook()
        finally:
            self._in_post_wide_sync_hook = False

    # 合理厚度区间：QSS 声明值只会落在 sizeHint 上，而未 polish / 未布局的滚动条
    # sizeHint 可能报出荒唐值（Qt 默认那种），必须滤掉再钉，否则会把滚动条错钉成
    # 一百多像素。8~48 覆盖平台默认（实测 12）与 QSS 声明（实测 16）。
    _SCROLLBAR_SANE_MIN = 8
    _SCROLLBAR_SANE_MAX = 48

    def sync_scrollbar_thickness(self, repolish: bool = False) -> None:
        """把本滚动区的竖向滚动条钉到 QSS 声明的厚度，并让 Qt 真的按这个厚度绘制。

        钉厚度只改几何，**不改绘制**——这才是「随机页签时宽时窄」的真正成因。
        Qt 在 polish 时把滚动条 groove / handle 的子控件矩形算好并缓存；之后把控件
        改宽（setFixedWidth）只会更新几何，那份缓存仍是抛光时的旧值，于是槽照旧按
        平台默认（实测 12px）画，而控件 `width()` 已经是 16——属性与画面对不上。
        实测：仅 `update()+repaint()` 仍是 12；`unpolish()+polish()` 后变 16；
        再 `setFixedWidth(15)` 则画 15——即绘制确实跟随宽度，但只在重新抛光之后。
        所以宽度改完必须重新抛光让缓存失效。

        哪些条是宽的，取决于它有没有被别的事件（换肤、焦点、祖先样式表变动）顺带
        重新抛光过，所以每次落在随机页签；最大化会让整棵控件树重新抛光，于是"看着
        好了"，还原后也保持——完全对得上用户现象。

        厚度来源仍是 QSS 声明的 sizeHint()，不硬编码 16：改 QSS 即改这里。
        """
        try:
            bar = self.verticalScrollBar()
            if bar is None:
                return
            bar.ensurePolished()
            declared = bar.sizeHint().width()
            if not (self._SCROLLBAR_SANE_MIN <= declared <= self._SCROLLBAR_SANE_MAX):
                return
            changed = False
            if bar.minimumWidth() != declared or bar.maximumWidth() != declared:
                bar.setFixedWidth(declared)
                changed = True
            # 已经钉死时，只有 show（repolish=True）才继续走：显示是陈旧绘制第一次
            # 真正露出来的时刻，也是唯一能保证把它刷掉的机会。resizeEvent 走这里
            # 会因未改动而直接返回，天然幂等、不会自激成 resize 回环。
            if not (changed or repolish):
                return
            bar.style().unpolish(bar)
            bar.style().polish(bar)
            bar.update()
        except Exception:
            return

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 先同步宽幅容器（含缩回），再按最新 childrenRect 补内容最小尺寸——
        # 顺序颠倒会让 min_width 吃到拉伸后的旧包围盒，还原路径锁死（议题 #82）
        self.sync_wide_children_width()
        self._run_post_wide_sync_hook()
        self.sync_content_min_height()
        self.sync_scrollbar_thickness()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_wide_children_width()
        self._run_post_wide_sync_hook()
        self.sync_content_min_height()
        self.sync_scrollbar_thickness(repolish=True)

