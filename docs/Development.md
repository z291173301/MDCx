# 开发者专区

给想改代码、加功能的人看的文档。合并了原仓库中所有技术文档（架构、核心模块、数据模型、爬虫系统、命名系统、缓存、测试、代码规范、迁移指南等）。

## 项目结构

```
mdcx/
├── base/              # 基础功能（文件、图片、翻译、网络请求）
├── cmd/               # 命令行工具（crawl 调试爬虫、gen_enums）
├── config/            # 配置管理（Pydantic 模型、枚举、管理器）
├── controllers/       # 控制器（主窗口、海报裁剪）
│   └── main_window/   # 主窗口逻辑（按职责拆分 11 个模块，共 ~10000 行）
├── core/              # 核心业务（刮削器、NFO、命名、图片、翻译等）
├── crawlers/          # 36 个网站爬虫 + 基类框架
├── gen/               # 自动生成的枚举
├── models/            # 数据模型（FileInfo、CrawlerResult 等）
├── tools/             # 工具（演员数据库、Emby 同步、字幕等）
├── utils/             # 工具函数（限流、日志、文件操作）
└── views/             # UI 视图（Qt Designer 生成的 .ui 和 .py）
```

## 架构

采用 MVC 分层：

```
UI 层 (PyQt6)         → 界面展示、用户操作
控制器层               → 事件处理、配置管理、信号调度
核心业务层             → 刮削器、NFO 生成、翻译、图片处理
爬虫框架               → 36 个爬虫，统一基类
基础设施层             → HTTP 客户端、文件系统、OpenCV
```

**数据流程**：

1. 文件扫描 → 番号识别 → 爬虫执行 → 数据整合 → 翻译
2. → 命名生成 → 资源下载 → NFO 生成 → 文件移动

## 主窗口 UI 布局与窗口缩放

主窗口 `centralwidget` 没有布局管理器（上游遗留），全部控件绝对定位；窗口缩放时靠 `MyMainWindow.resizeEvent` → `_sync_page_layouts`（`mdcx/controllers/main_window/main_window.py`）按设计基准手动 `move` / `resize` 同步。

**基准与公式**

- 设计基准宽 820，`cover_scale = 主页面宽 / 820`。
- 几何一律写成「设计基准 + extra」且**双向幂等**：extra 为正放大、为负缩回，绝不增量累积，否则反复缩放/切页会漂移。
- 两类锚定策略，按控件语义选择：
  - **右缘锚定**：右缘距页面右缘固定（如结果树右距 18px、统计标签右距 9px），左缘随窗口拉伸平移。
  - **左缘对齐**：左缘对齐某参照控件（如结果树左缘），右缘自由。

**最大化 / 非最大化两态**

- 用 `self.isMaximized()` 区分；非最大化（还原/最小化）保持设计位置不动，最大化按需平移/对齐。
- `changeEvent` 收到 `WindowStateChange` 后 `QTimer.singleShot(0, self._sync_page_layouts)` 重算一次，规避 `resizeEvent` 里 `isMaximized()` 状态位尚未更新的时序问题。

**统计栏（「刮削中/成功/失败」）案例**（本次经验）

- 结果树 `treeWidget_number` 右缘贴页面右 18px、宽度随 `cover_scale` 拉伸（议题 #173）。
- 统计标签 `label_result` 与结果树同属「统计栏」，但两者锚定方式不同，不能一味右锚定：
  - 非最大化：标签右缘锚定（右距 9px），保持设计位置不动；
  - 最大化：标签**左对齐到结果树左缘**（`_tree_x = max(主页面宽 - 树宽 - 18, 300)`），贴到结果树首行「成功」列正上方——若仍右锚定会停在树右上角、与「成功」错位；
  - **纵向两态同高**：统计标签 y=70、结果树/清空按钮 y=110 在最大化与还原下一致，整组始终贴住顶部分隔线下方、不随最大化下沉（否则顶部线与标签之间会留出空隙）。
- 回归测试：`tests/test_window_state_matrix.py::test_stats_label_moves_to_success_row_when_maximized` 锁定「非最大化右锚定、最大化左对齐树左缘、纵向不下沉、双向幂等」。

**设置-NFO 右列 thirds 对齐**（用户最大化截图：影评/导演/TMDB/标签被推到自定义分级/想看人数右侧两百多 px）

- 根因：`gridLayout_66` 的 `columnstretch=(1,0)` 让 C0 吃掉全部横向 surplus，C1.x 以斜率 1 右移；而 country/mpaa/customrating、year/runtime/wanted 两行 HBox 无弹簧、三项均分 surplus，thirds.x 以斜率 2/3 右移。两者只在默认宽度附近相交，窗口加宽后持续发散；纯拉伸配比定不住常数项（hints 差约 48px）。
- 修复：`_sync_nfo_right_column_align()`（`_sync_page_layouts` 末尾调用，另接 `tabWidget.currentChanged` 下一拍——切 tab 时滚动区 showEvent 会重做宽幅拉伸使 C1 重新发散）。自适应钳制：先清 C1 列最小宽→重排→量自然位置，仅当 `critic.x > custom.x`（发散态）时设 C1 列最小宽把左缘精确钉到 thirds（导演/TMDB/标签同属 C1，一并归位）；窄态保持清零、原样不动。各控件同属 `layoutWidget_10`，`.x()` 同坐标系可比；只碰列宽，不碰 y 与其它行。
- 回归测试：`tests/test_window_state_matrix.py::test_nfo_right_column_aligns_to_thirds_when_wide` 锁定「宽态四者与 thirds 严格对齐、二次同步幂等、窄态钳制清零且自然位置保留」（复现用户场景：show + 切到 NFO 页后断言）。

**设置-NFO 原标题/简介对齐发行日期列**（用户最大化截图：原标题应与发行日期上下对齐、简介与发行日期对齐、原简介与上映日期对齐）

- 根因：发行三项（release/relasedate/premiered，注意中间项对象名拼写即 `relasedate`）为 Minimum 策略，视口加宽时各自吞掉 extra/3；而原标题/简介行的 150 前缀把后继项 x 冻结在窄态位置。纯拉伸定不住三者的相对位置。
- 修复：`_sync_nfo_title_plot_align()`（`_sync_page_layouts` 末尾调用，另接 `tabWidget.currentChanged` 与 `stackedWidget.currentChanged` 下一拍排队、第二拍全量同步——后者补休眠洞：resize 时休眠 NFO 被各 sync 内 isVisibleTo 早退跳过，而切回设置页时 NFO 的 tab 索引没变、tab 钩子不触发，此前 NFO 永远停留旧几何；stacked 钩子复用同一 `_queue_nfo_post_cascade_sync`，内层守卫保证休眠 no-op）。做法：先把 sorttitle/outline/plot 三前缀恢复最小宽 150→重排→量自然位置，再按「当前宽+位移」设最小宽（g0=max(rd.x-ot.x,0)，g1=max(rd.x-plot.x,0)，g2=max(pr.x-opl.x-g1,0)，opl 永不超过 pr），把后继项精确钉到发行日期列；窄态宽态同一套公式（原 `extra > 200` 门限已删），窄态自然 d≈+29 小步右移，宽态大步右移。用当前宽而非 150 做基址：前缀 hint 随字体变化（如测试字体下 sorttitle hint 为 192），基址 150 会系统性欠 299-257=42px；当前宽基址与样式无关且天然幂等。只取正部 + opl 上限钳制：过窄窗口 d 为负时（900 宽下 rd 被挤到 ot 左边）“向右移+参照不动”几何无解，负位移钳零（前缀不动）；d2 取 pr.x-opl.x-g1 且封顶 pr（d1<0 时旧式会超调的教训）。复选框加宽只延长点击区，视觉无变化；只碰前缀列宽，不碰 y 与其它行。三行是三个独立 HBox（135/136/137），加宽 135/136 前缀天然碰不到 137 行的 rd/pr。
- 回归测试：`tests/test_window_state_matrix.py::test_nfo_title_plot_aligns_to_release_when_wide` 锁定「宽态三者严格对齐、前缀被加宽、二次同步幂等；窄态（1089/900）字体无关契约不变量：后继项只许右移、opl 永不超过 pr、rd/pr 与各行 y 逐像素不变、二次同步幂等」。注意测试字体的特殊性：set_style=None 下 sorttitle hint=192，ot 自然位 334 卡在 rd（322）右边，严格窄态对齐在此字体下可证明无解（两边都动不得），故窄态腿不断言绝对等式；生产字体（YaHei）下 st=150、ot=292<rd=321，对齐发生。`test_nfo_resyncs_after_dormant_resize_on_page_back` 锁定休眠洞修复：休眠 resize 后切回，窄态腿只断言钩子跑过（宽态残留前缀被清掉）+ opl 不超 pr + 幂等，宽态腿断言严格收敛。注意桩配置的特殊性：conftest 的 `_DummyConfig` 使冒号标定走另一分支（title=103/pad=5，lw10=(-10,625) 而非生产向的 (61,2.0)/(-60,675)），1000 宽下 rd=301 落在 ot 自然位 334 左边——窄态返回腿若断言严格必挂，这不是钩子失效，是钳制 by design；另切回级联比 tab 切换长，测试用 pump-until-stable（坐标连续两轮不变）而非固定拍数。

**设置-NFO 窄态分级信息/时长对齐发行日期列**（用户最小化截图：分级信息（mpaa）框偏左、时长（runtime）框偏右；最大化天然对齐）

- 根因：三行（h137 发行/h141 国家/h40 年份）皆左堆积无弹簧的 Minimum 行，同一起点 X0。有余量时三行均分天然对齐；容器窄到装不下 hint 总宽时 Minimum 项被挤到 hint 以下、各行按各自文本乱挤（country 短→mpaa 落下；year 比 release 抗挤→runtime 被顶出）。离屏实测（测试字体 850 宽）：rd=257、mpaa=252（左 5）、runtime=268（右 11），与用户症状（生产字体约 30/60）同向；800/760 宽方向乱跳，挤压区分配混沌、随宽度乱飘。
- 修复：`_sync_nfo_row_align()`（`_sync_page_layouts` 末尾、title_plot 之后调用，无新钩子）。四约束复位（country/year 最小宽回 0、最大宽放开）→重排+外层落定→实测；四方向条件钉死，目标一律锚定参照行 h137 实测值（rd.x − 前项.x − h137 实测间距，min=max 一次钉死，60px 地板），有界迭代 3 遍兜 ±1px 取整漂移。教训：初版三处用了 `rd.width()`（relasedate 自身宽度，挤压区比 release 宽出一截，850 宽下 133 vs 115），cap 系统性钉错位（mpaa 稳定 +2、第二遍也不自愈：cap 不 binding）；只有 year-max 支是绝对式所以 runtime 收敛了。无条件全钉死不可行：宽态 mid-cascade 误测 pin<share 会把 country 钉小、custom 左顶 10px（thirds 单跑即挂，critic=1076/custom=1066）；条件式只在错位方向触发，复位保证误触发下一拍自愈。有余量时条件皆不触发，宽态零改动。只碰列宽，行高不变故无上下移动；休眠页跳过，由现有切页钩子补齐。
- 回归测试：`tests/test_window_state_matrix.py::test_nfo_country_year_align_to_release_when_narrow` 锁定「挤压态（700/750/850，翻转方向全覆盖）三者严格 == rd.x、参照/前项/y 逐像素不变、二次同步幂等；宽态（1900）天然对齐且条件式无触发、约束零残留（country/year 最小宽 0、最大宽默认）」。

**设置-NFO 末项（自定义/想看人数）与首播日期列对齐**（用户需求：最小化时自定义（customrating）、想看人数（votes）右移到与发行日期（premiered）严格上下对齐，premiered 不动；最大化不变；只能左右移动）

- 根因：同三行左堆积 Minimum 行；800~900 宽挤压区第二项（mpaa/runtime）被挤得比 relasedate 窄（850 宽实测 mpaa.w=119、relasedate.w=133，测试字体），末项 custom/votes 落在 premiered 左边（800 宽 custom 偏左 15，850 宽 custom 偏左 14、votes 偏左 2；700/750/900+ 天然对齐）。
- 修复：`_sync_nfo_tail_align()`（`_sync_page_layouts` 末尾、row_align 之后调用，无新钩子）。只钉 mpaa/runtime 的最小/最大宽到 rd.width()（min=max 一次钉死，60px 地板），条件对称+有界迭代 3 遍。目标合法性：row_align 已把 country/year 钉到与 release 等宽（同 X0 同间距），故 custom==pr 当且仅当 mpaa.w==rd.w（850 验算 136+115+6+133+6=396=pr 精确成立）。前项与参照不动，只碰列宽；有余量时条件不触发，宽态零改动；休眠页跳过，由现有切页钩子补齐。
- 回归测试：`tests/test_window_state_matrix.py::test_nfo_tail_align_to_premiered_when_narrow` 锁定「挤压态（800/850）两者严格 == pr.x、参照/中项/y 逐像素不变、二次同步幂等；700/750/1900 天然对齐且条件式无触发、约束零残留（mpaa/runtime 最小宽 0、最大宽默认）」。

**设置-NFO 合集两项与片商/发行商列对齐**（用户需求：最大化时合集（使用演员字段）左移到与片商（maker）严格上下对齐、合集（使用系列字段）左移到与发行商（publisher）严格上下对齐；最小化布局不动；只能左右移动）

- 根因：h114 三分、h138 四分（皆左堆积无弹簧、同一起点、无自定义间距），有余量时均分：d_aset≈W_cell/12、d_set≈W_cell/6，随宽度线性漂移（离屏实测 1900 宽 +116/+232、1400 宽 +74/+149，逐值吻合；1000/1089 宽 +41/+82、+46/+102）。
- 修复：`_sync_nfo_set_align()`（`_sync_page_layouts` 末尾、tail_align 之后调用，无新钩子）。宽态门 extra=viewport-796>200（scrollArea_13 即 NFO 设置滚动区，设计 796；不用 isMaximized，因离屏不可测；1400 中宽同样开门，属宽向无害）：关门时复位 genre/actor_set 约束并直接返回，窄态逐像素不动。开门后 3 遍有界迭代、条件左移单向（封顶前项，60 地板）：两钉必须串行——genre 钉会连带左移整块 [actor_set, set]，actor_set 钉必须用 genre 钉生效并重排后的新鲜位置计算，否则同一快照下重复扣除 genre 修正量（1900 宽实测 overshoot 116px：set 落到 publisher 左边 718 vs 834）。studio/maker/publisher 与 y 全不动；休眠页跳过，由现有切页钩子补齐。
- 回归测试：`tests/test_window_state_matrix.py::test_nfo_set_aligns_to_maker_publisher_when_wide` 锁定「1900/1400 门内两者严格 == maker.x/publisher.x、参照 studio/maker/publisher 与 y 逐像素不变、二次同步幂等；1000/1089 门外自然漂移保留、约束零残留（genre/actor_set 最小宽 0、最大宽默认）」。

**设置-NFO 字段说明按钮收进组框**（用户窄态截图：最小化时「字段说明」按钮伸出「写入NFO的字段」组框右缘）

- 根因：按钮 Fixed 80x26、设计 x=640..720；组框设计 x=30 宽 701、右缘 731，设计余量仅 11px。宽幅同步按 width=设计宽+extra 双向拉伸组框（extra<=0 时缩回）；extra<0（视口窄于设计 796）时组右缘左移而按钮不动——测试环境 1089 窗组宽 724 尚未溢出，1000 窗组宽约 635、按钮伸出约 66px。
- 修复：`_sync_nfo_field_tips()`（`_sync_page_layouts` 末尾、set_align 之后调用，无新钩子）。绝对 pin：复位 x=640→重排→按钮右缘超过（组右缘-11）才左移进去；只左移，宽态 640 不动，y 不动；同父坐标系直接可比；休眠页跳过，多拍收敛幂等。测试写法注意：goto 的 beats 会提前同步把按钮钉到 pin 位，“自然溢出”基线须先 `btn.move(640, y)` 复位再取。
- 回归测试：`tests/test_window_state_matrix.py::test_nfo_field_tips_stays_inside_group_box` 锁定「1000 窄态按钮右缘≤组右缘-11、y 不动、二次同步幂等；1900 宽态 x==640」。
- 首开跳动修复（用户报障：初次打开设置-NFO 的瞬间按钮从右边跳到左边，再次打开正常）：tab 切换只走双拍 beats（直接读 stale 几何会钉错 thirds），paint 跑在 beats 之前；首开第一拍常读到中间态视口（滚动条闪烁），trailing 定格偏窄组框，pin 误判溢出左移 → 可见跳动；第二拍落定后复位，之后 beats 全 no-op。修复 `_settle_settings_after_switch()` 直连 tab/stacked 的 currentChanged（paint 前）：至多 3 轮{全量同步+泵}至稳（快照按钮 x/组宽/视口），不进 resize 路径，beats 留兜底，休眠早退。教训：曾试 `setUpdatesEnabled` 关 paint 抑中间帧，反而扰动渲染扫描类量测致落点偏移（rd.x 203→213，country_year/tail 挂），已删。回归测试 `test_nfo_field_tips_no_jump_on_first_open`：冷窗 900 宽 + 裸切 NFO tab（零外部 beats）一次落定到诚实公式 pin 位，随后全量+beats 幂等；灵敏度已用 blockSignals 模拟修复前验证（按钮停 640 vs 期望 488，必挂）。

**设置-NFO 组框右缘看齐水印/演员（清理式终局：设计回到 701，控制器已删）**

- 根因：probe 六轮实测现树 NFO 内容设计宽恒 782=水印；差值公式 `diff=(D-701)+Δvp`；715 补偿的是一个在本树已不存在的差值（796 时代 design_w 遗物），在 Δvp≈0 的环境整整宽出 14px——用户最新“宽度大于、右缘左收”投诉即此。
- 动态控制器 `_sync_nfo_groupbox_align` 已删除：它与 wide-sync 同构（设计 701 时纯冗余），且因 tab_7(837)/内部 stacked(833) 框 confusion 用错边距 65（真值 69=837-30-738，4px 系 tabWidget pane 边）overshoot 到 742；1900 三边距乱跳另证恒定边距模型不成立。删方法+删调用点，无残留（grep 确认）。
- 修复：组框设计宽 715→701（x=30 不动；pyuic+ruff 再生 `MDCx.py`，diff 仅一行 QRect）；自然 wide-sync 在两视口相等时两组天然等宽，diff=Δvp 裸奔（测试环境 0，生产由用户截图判真值）。
- 事故教训×2：(1)`views/` 曾被整体还原，测试只保一致性不保意图，重做后以离屏实测复验为准；(2)诚实公式别漏地板——700 宽下 `max(701+extra, 701//2)`，地板 350 会 binding（组测试因此挂过一次，vp=430/dw=782 时诚实值 349 vs 实际 350）。
- 回归测试：`tests/test_window_state_matrix.py::test_nfo_groupbox_resyncs_after_stale_stretch`（故障注入改窄 64px；收敛环至多 3 轮；诚实公式 `max(701+(vp-dw),701//2)` 全实测值；跨页黑盒 1089/1900 严格等宽、700 地板 ±3；x/y/h 不动）。

**设置页各页签滚动条厚度统一（80% 分数缩放下“未点开的页更窄”）**

- 现象（用户实测四条，截图红框标出演员/网络/高级）：启动后先点开过的页正常、没点过的更窄；等 30~60 秒或最大化再还原后全部变齐；且每次异常页都不同。
- 排查排除：滚动区 `.ui` 逐项一致（几何/frameShape/lineWidth/AlwaysOn/AlwaysOff/widgetResizable，演员仅多 Sunken 装饰）；12 个滚动区全是 `CustomScrollArea`（`findChild` 无遗漏）；全库无 `setStyle`/`QScrollBar` 实例化/`setVerticalScrollBar`，策略全 AlwaysOn；QSS 滚动条规则全库唯一（`controllers/main_window/style.py:build_scrollbar_style`，`QScrollBar:vertical{width:16px}` + 满宽滑块 + `min-height:44px`，随 centralwidget 整页下发）且渲染输出合法（大括号平衡）；离屏 12 页 + 0.8 缩放 + 首开→最大化→还原三轮探针全部逐值相等。
- ~~生产取证（临时日志）~~ / ~~像素级取证~~：**这两批"12 页逐值相同、都是 16px"的证据已作废**，原因是探针根本没让设置页显示出来——`stackedWidget` 里 `page_setting` 的下标是 **4**（不是 2），按 2 进页时页面始终 `isVisibleTo=False`，滚动条从未被布局/抛光，量到的只有"恰好被布局过的那一条"是真的，其余 11 条的 `vis=False` 被当成"无需检查"跳过了。**教训：量设置页滚动条前必须先断言 `page_setting.isVisibleTo(win)`，否则整批数据作废。**
- **已定案（滚动条忽宽忽窄）**：根因是控制器读 `width()` + 取 `min`，两处叠加把一次瞬时坏读数变成全局永久降级。QSS 的权威厚度是 `QScrollBar:vertical{width:16px}`，它落在 **`sizeHint()`** 上；而 `width()` 只是控件当前几何，未 polish / 未被布局的页签停在平台默认 `PM_ScrollBarExtent`（`QT_SCALE_FACTOR=0.8` + 125% 系统缩放下实测 **12**，比 QSS 少 4）。旧代码 `min(sane)` 先取到某个未抛光页的 12，再 `setFixedWidth(12)`（min=max=12，**覆盖 QSS**）把 12 页一齐钉死——这正是"首开某页是宽的、切走再回来变窄、再也回不到 16、且每次落在随机页签"的表现。**决定性复现**：`QT_SCALE_FACTOR=0.8`、窗口 1030×650、真正进入设置页后逐页切换并对每条**可见**滚动条 `grab()` 逐像素量——修前 11 页里 **10 页渲染宽度就是 12px**（恰好落在字幕/水印/演员/网络/高级五页，与用户报的一模一样），修后 **11 页全 16px**。
- 保留兜底：`_sync_settings_scrollbar_widths()`（try/except 整体兜底，3.14t free-threading 下槽内抛异常会直接带崩进程，见 add_log 槽事故）遍历 12 页签 CustomScrollArea，`area/viewport/bar` 全部 `ensurePolished()`，厚度读数改取 **`sizeHint()`**（不受布局时序影响，12 页恒为 QSS 值），只采信 8~48px 区间读数**取最宽者** `max` 为准、sizeHint 全不可信时退回 `width()` 仍取 max、其余 `setFixedWidth(target)`，有改动则 `_sync_page_layouts()` 按新视口重排；连接用 `QTimer.singleShot(0, …)` 且排在 `_queue_nfo_post_cascade_sync` 之后（量级联终态厚度，直连会量到级联前几何，同款陷阱见字段说明那节）。已一致时零改动（幂等）。**读数来源与 max 缺一不可**：读 `width()` 会被未布局页污染，取 `min` 则一次坏读数拖着全组降级——两者任一错都会复现随机页签变窄。**判定"是否需要钉"必须看约束（`minimumWidth()/maximumWidth()`）而不是几何（`width()`）**：首开时唯一被布局过的那条 `width()` 恰好已等于 target，按几何判会放过它，它就永远只靠 QSS 撑着，后续任意一次 polish/布局都能把它打回平台默认厚度——这正是"随机页签"的残余，故逐条钉成 `min=max=target` 才是封死的终态。
- ~~第二轮判断（触发时机竞态）：挂 `QTimer.singleShot(0)` 与 polish/布局赛跑，所以异常页签每次不同~~ —— **已被下面的实测推翻**。定时器只是让"钉几何"这件事发生在随机时刻，本身不是病因。
- **最终定案（2026-10-02，第三轮）：钉几何不改变绘制，真正的原因是 Qt 在 polish 时缓存了滚动条 groove/handle 的子控件矩形。** 用整窗合成图逐像素量（不看控件属性）：控件 `width()/sizeHint()/min/max` 在**所有**页签都已是 16，但实际画出来的槽宽在字幕/水印/演员/网络/高级等页仍是 **12**，只有刮削目录/命名/翻译画成 16——**属性与画面对不上**。`setFixedWidth` 只改几何，那份抛光期缓存不失效，槽就照旧按抛光时的平台默认（`PM_ScrollBarExtent` 实测 12）画。
  - 决定性干预表（字幕页，窄态已复现）：基线 12 → `update()+repaint()` **仍 12**（单纯重绘无效）→ `unpolish()+polish()` **16** → 整窗 repaint 16 → 条 hide+show 16 → 滚动区 hide+show 16 → 祖先样式表重挂 16 → **条自身 `setFixedWidth(15)` → 画 15**（关键：绘制确实跟随宽度，但只在重新抛光之后）。
  - 由此解释了两个一直对不上的现象：①**为什么是随机页签**——一条条看起来宽，只是因为它碰巧被别的事件（换肤、焦点、祖先样式表变动）顺带重新抛光过；②**为什么最大化就好了、还原后也保持**——最大化让整棵控件树重新抛光。
  - **修法**：`CustomScrollArea.sync_scrollbar_thickness(repolish=False)`（`mdcx/views/CustomClass.py`）——`ensurePolished()` → 厚度读 QSS 声明的 `sizeHint()`（不硬编码 16）→ 只采信 8~48px 区间 → 约束不等于声明值才 `setFixedWidth(declared)` → **仅在"宽度真的改了"或"这是 show"时才 `style().unpolish()+polish()+update()` 让缓存失效**。挂在 `showEvent`（`repolish=True`，显示正是陈旧绘制第一次露出来的时刻）与 `resizeEvent`（不带 repolish，未改动即返回，天然幂等、不会自激成 resize 回环）。
  - **验证按渲染像素，不按控件属性**：`QT_SCALE_FACTOR=0.8`、窗口 1030×700、真实启动路径逐页切换后量整窗合成图。带修法连跑 3 次 `painted=16` 覆盖全部 12 页（`narrow=0`）；`git stash` 打回改动连跑 2 次 `narrow=11`。
- 观感调整尝试与**最终结论：不改**（用户 2026-09-27 决定放弃此问题）。两轮尝试均已回滚：`① 槽底加深（浅 #E5E7EB→#D8DEE6 / 深 #1F2937→#263241）+ 滑块定厚 10px`、用户否；`② 只把滑块改窄 8px、颜色不动`、用户试后仍无改善、否。回滚后 `build_scrollbar_style` 回到 #153 原状（槽宽 16px、滑块满宽无 width/height、最短 44px、深浅四色原样）。取证链（四路独立证据，全部指向"厚度逐页相同"）：生产逐页日志 `w=16 / sizeHint=16 / 样式类相同 / 祖先样式表 3128 字符相同 / 视口 758 / 滚动区 774`，`dpr=1.00`（80% 分数缩放猜测被否）；离屏真实 QSS 逐页 `bar.grab()` 像素指纹——12 页皆 16px 槽 + 16px 满宽滑块；整块窗口合成图回匹配（先从 `grab()` 取两种主色再回合成图找条色，容差 2）——`bar=(0,0,16,685)`、`bar_x_win=1047`、`right_gap=26`、命中条色宽度 16 逐页相等；红槽诊断（临时把 `track` 刷 #FF0000、`handle` 刷 #0000FF 截图，用户配合）——两页红槽宽度与 x 位置完全一致，**唯一差异是滑块长度**（NFO 蓝段 ~362px vs 网络页 ~262px，同一 590px 槽内；槽底红段 228 vs 328）。滑块长度由 Qt 按 内容高/视口高 算出（12 页占槽高 18%~82%），无法跨页拉平。
- 回归测试：`tests/test_window_state_matrix.py::test_settings_scrollbars_use_declared_thickness_not_stale_geometry`（给 `page_setting` 挂真实滚动条 QSS → 注入"声明 16 / 几何停在窄值"的混合态 → 调控制器 → 断言 12 页全部回到声明厚度**且逐条 min=max=target**（不留"几何恰好已等于 target 就放过"的口子）→ 切走切回复跑，断言厚度与钉死态都不降级）。另有 `test_settings_scrollbars_uniform_width_across_tabs`（先逐个点开 12 页签复刻生产"已布局"态并断言厚度统一且在 8~48 区间 → 记录 `groupBox_81` 几何 → 注入两页窄 4px → 调控制器 → 断言全页统一到 target、组框几何原样恢复、幂等）。初版控制器对全部读数取 max，被未布局页的 100 污染成 target=100（测试首跑即挂），已改为逐条过滤 sane 读数。两个测试都锁住"取最宽者"：注入窄几何后若实现取 min，全部 12 页会被统一到窄值而挂。第三个测试 `test_scroll_area_pins_scrollbar_thickness_on_show_without_timer` 锁的是**下沉修法本身**：压矮窗口让 12 页都真实溢出 → 逐页测量绘制宽度（离屏未绘制时该测量返回 `None` 并跳过）→ 注入"几何 16 / 绘制停在 12"的真实故障态（`setFixedWidth(窄值)` + `unpolish` + `polish`，复刻陈旧缓存）→ 走 `area.show()` 触发 `showEvent` 的 `repolish=True` → 断言几何与 min=max 回到 16、绘制宽度回到 16；另锁幂等。无修法时报 `AttributeError`。
- **定案验证（2026-10-02，按渲染像素）**：`QT_SCALE_FACTOR=0.8`、窗口 1030×700、真实启动路径进入设置页后逐页切换，量**整窗合成图**上的实际槽宽——带修法连跑 3 次，12 页全部 `painted=16`（`narrow=0`）；`git stash push -- mdcx/views/CustomClass.py` 打回连跑 2 次，`narrow=11`。
- **教训（本议题踩了三次）**：①量设置页滚动条前必须先断言 `page_setting.isVisibleTo(win)`（它在下标 **4**，不是 2），否则整批数据作废；②**只读控件属性会骗人**——属性全对、像素是错的，必须量渲染结果；③要求用户配合点击的诊断设计是失败的（两次日志都记到"从未进入设置页"），诊断脚本应自带导航、在真实事件循环里自动跑完。离屏 pytest 里 `grab()` 拿不到真实绘制（整行同色），绘制宽度断言需容忍这种情况。
- 另注：短窗口（1030×~330~520）下切到**NFO 页**（`tabWidget` 下标 8）会让本进程直接崩（Windows 退出码 `-1073740791`，`faulthandler` 无 Python 栈）。与本议题无关、未定位，但复现设置页滚动条取证时**不要靠压窗口高度来造溢出**，改用正常窗口 + 逐页切换（1030×650 下 11 页已自然溢出）。

**版本检查定时复查走完整提示链**（`timer_update` 12h 定时器必须走完整提示链）——与窗口布局无关，已并入下文「更新检查（客户端自动更新）」一节的不变量 ⑥，不在本节重复。

**设置-NFO 左标签冒号与组标题冒号对齐**（用户窄/宽两态截图：标题：/简介：/发行日期：/国家/分级：/年份/时长/想看：/评分：/演员/导演：/系列/标签：/风格/合集：/片商/发行商：/封面/背景/预告片：11 个左标签整体左移、冒号与「写入NFO的字段：」组标题的冒号上下对齐）

- 根因：11 个行标签是外层 grid col0 的 Fixed130 右对齐 QLabel，公共冒号 x = col0 右缘 − 右 pad；而组标题冒号 x 由标题文本宽度决定（8 个字），比最长的 11 字行标签文本更靠左。预算证明严格对齐结构性无解：不裁字要求公共冒号 x ≥ 最长标签文本宽（11 标签都以：结尾且右对齐，冒号即文本右墨点）；严格对齐要求公共冒号 x ≤ 组标题冒号 x；实测最长文本宽 > 标题冒号 x（差约 7px，任何正常字体同理）——免裁字最优只能贴到守卫极值，残差约 7px，用户已接受保留最大位移。
- 修复：`_sync_nfo_colon_align()`（`_sync_page_layouts` 最先调用）。渲染标定组标题冒号 x 与行标签右 pad（`_calibrate_nfo_colons`，结果缓存于 `_nfo_colon_cal`）；把 `layoutWidget_10` 连 x 带宽整体左移（右缘保持）使行冒号贴向组标题冒号；防裁字守卫把左移量钳在「最宽标签文本左缘禁入负区」（advance 空间 min_x 回退版——+row_pad 的精确版在某几何下 5/5 触发 0xC0000409 原生 fail-fast，几何与时序真凶未定，本次避开该几何，见代码注释）。`layoutWidget_10` 是宽幅同步容器（每次按设计几何重置 x/y/宽），move 杠杆只能在 `sync_wide_children_width` 之后生效；又因单发钩子永远跑在 deferred 宽幅/scrollbar 级联前面、会用级联中几何覆盖正确值（thirds/title 10px 漂移的教训：钩子才是破坏者），三个 tab 钩子已合并为统一的 `_queue_nfo_post_cascade_sync`——第一拍只排队、第二拍跑全量 `_sync_page_layouts`，落定后单遍收敛；thirds/title 内各留一道外层 `activate()` 做防御性刷新。
- 回归测试：`tests/test_window_state_matrix.py::test_nfo_colon_aligns_to_group_title` 锁定「11 标签右缘共线、移到守卫允许最左、墨点空间无裁字、右缘保持、y 不动、窄宽同位、幂等」。墨点断言用 `rect_right − advance + br.x()` 的 ink 空间：advance 是排版宽度，br.x() 为负的左侧轴承会虚报裁字。
- 注意：休眠 NFO 页（visible REGION 为空）量到的是冻结几何，同步必须跳过（isVisibleTo 守卫）并依赖切 tab 钩子补齐；全量 `activate()` 对「真移动」（非 stale 缓存）bit-identical 无效，不要指望它修复发散。

**设置-演员页「选择文件」/「网络头像库」两处对齐（「网络头像库」宽、窄两态各钉一次）**（用户先后给两张截图：1920 最大化，红线画在「选择目录」列，注「最大化时向右移动到这里」「最大化时向左缩进到这里」；随后又要求最小化时把「网络头像库」输入框右缘向左缩进到与两枚路径框右缘严格上下对齐。每一态都要求另一态界面、组件、控件、提示词全部保持不动）

- 两条需求根因不同，**别混为一谈**：① 「选择文件」（`pushButton_select_actor_info_db`）属于演员信息组 `groupBox_64` → `gridLayoutWidget_14` → `gridLayout_14`，而两枚「选择目录」属于头像组 `groupBox_41` → `layoutWidget_8`——**两套网格的列宽互不相关**。此前宽态把 `lineEdit_actor_db_path` 右缘钉在 A2（`checkBox_actor_photo_ne_face` 左缘，1920 实测 652），「选择文件」落在 658，与真正要对齐的「选择目录」列（1469）差 **811px**；A2 是头像组的 Graphis 三等分列，拿它当演员信息组的按钮列是跨网格误用。改法：宽度改由「选择目录」实测左缘反推（`sel_x - row.spacing() - A1`，锚点 `pushButton_select_gfriends_local`，与另一枚 `pushButton_select_actor_photo_folder` 同网格同列），窗口任意宽度成立；下限 `_ACTOR_INFO_PATH_MIN_W`=300（`.ui` 里该输入框的 minimumSize 宽），不足则不钉。② 「网络头像库」输入框 `lineEdit_net_actor_photo` 是 `layoutWidget_8` 网格的**直接项**、右侧无按钮，宽态独占整列富余宽（1920 实测 1393），比另两枚「路径框 + Fixed 110px 选择目录」水平行（1277，右缘止于按钮列 1463）宽出整整一枚按钮的宽；**左缘本就同列**（都是 col1 起点 = A1 = 186），故钉宽即可让左右缘双双相等。实现在 `_sync_actor_page_wide_a2_align` 末尾第 ⑥ 块（`lock_width` + 读回纠偏）。
- **窄态是同一根因的第二份实现，不是同一份代码**（需求⑮，`_sync_actor_page_narrow_align` 末尾第 ⑤ 块）：`_sync_actor_page_wide_a2_align` 在 `_actor_page_stretch_extra() <= 0` 时直接 return，反之亦然，两态逻辑天生互斥，无法共用一段。宽窄两份逐行镜像（先 `invalidate+activate` 落定、再量参照框终态宽、`lock_width`、一次读回纠偏），但**登记表不同**：宽态进 `_actor_wide_restores`、窄态进 `_actor_narrow_restores`，各自由对应的 `_clear_*_align()` 逆序写回原 min/max，这样对方那一态拿到的是真解锁而不是残留的 `setFixedWidth`。
- **`layoutWidget_8` 是 pyuic 生成的 QLayoutWidget：`invalidate()` / `activate()` 必须调在它 `.layout()` 返回的网格上，不能调在控件自身**（pyuic 把这两个自定义槽转发到布局；调错对象会静默失效或让整个 pytest 进程以 `Windows fatal exception: access violation` 退出、无任何用例输出）。由此派生两条硬约束：窄态清场 `_clear_actor_narrow_align()` 末尾**必须补一次网格重排**，否则 min/max 已放开、控件却仍留着上一遍的钉宽；`_sync_actor_page_narrow_align` 里原先那串带多个 `return` 的平铺需求⑨ 代码必须先收成嵌套闭包（照既有 `_shift_source_row()` 先例），否则新加的第 ⑤ 块会被早退跳过。
- **两个必须记住的时序/登记约束**：宽态方法排在 `_sync_actor_info_columns` **之后**（后者末尾 `grid.invalidate()+activate()` 会把网格直接项弹回整列宽）；钉宽必须登记进 `_actor_wide_restores`（记录原 min/max 逆序写回 = 真解锁），不能只 `setFixedWidth`。钉宽能持久是因为通用宽幅同步只拉父容器 `layoutWidget_8`（`_STRETCH` 项）、输入框自身不在 registry 里。「演员信息数据库」路径框在窄态仍由需求⑨ 的 `_ACTOR_NARROW_PATH_ROW` 负责，本条一律不碰。
- 回归测试：`test_actor_info_columns.py::test_actor_wide_net_photo_input_aligns_with_path_inputs`（**只管宽态**）+ `::test_actor_narrow_net_photo_input_aligns_with_path_inputs`（三档窄态左右缘全等 + 登记在 `_actor_narrow_restores` + 幂等 + 往返复原，末尾再回到最大化态断言整份快照 == 「摘掉 `_sync_actor_page_narrow_align` 及其清场函数」的基线，以此守住「窄态逻辑不碰最大化页面」）；需求⑥ 的断言写在 `test_actor_info_columns_align_when_wide` 里（「路径框右缘 + 行间距 == 「选择目录」左缘 == 「选择文件」左缘」，两枚「选择目录」同列同宽）。`_WIDE_WIDGETS` 收录三枚路径框 + 两枚「选择目录」，让既有 `test_actor_wide_a2_*` 的窄态「整份快照 == 基线」断言顺带守住泄漏。**断言不要写死窗口像素值**（旧版写死 `width() != 466`，窗口一改就哑），一律用「与另一态实测对比」；**对齐类断言要用相对量**（`右缘 == 「选择目录」左缘 − 行间距`），因为极窄窗口下参照行会被挤到自身 300px 下限、此时只能比「三枚等宽 + 已钉死」而不能比按钮列。

**设置-高级页窄态「每次间隔」右缘对齐（唯一一处对齐右缘而非左缘的需求）**（用户最小化截图，红线横跨两行画在 `20` 框右缘处、注「向左缩进到这里」；锚点行及其余控件一律不许动，最大化态一个像素都不碰）

- 根因是**两行长短不同、而只有输入框能被压缩**，不是控件位置错了：「间歇刮削」行 `horizontalLayout_109` 五项、按真实字体需 579px；「每次间隔」行 `horizontalLayout_104` 三项、需 543px。三个 `QLabel` 的 `minimumSizeHint == sizeHint`（**压不动**），三枚 `QLineEdit` 是 Fixed/Fixed 但只有 `minimumSizeHint`（29px）可让——窗口一窄，**先溢出的必然是更长的 109 行**，Qt 把富余差只摊到它那两枚输入框上，104 行还装得下、保持满宽，于是 `lineEdit_timed_interval` 的右缘越过 `lineEdit_rest_count` 的右缘。实现在 `_sync_advanced_page_rest_interval_align(wide)`。
- **这类「比右缘」的对齐，锚点必须取运行时右缘**（`col_x(anchor) + anchor.width()`），不能取控件宽度更不能写死像素：右缘随字体度量浮动，写死必哑。**沿用 `_sync_advanced_page_debug_row` 的惯用法**「先解除上一轮钉宽并重排 → 量锚点 → 再钉 → 重排 → 读回纠偏」；钉宽复用既有的 `_pin_row_lead_width(box, width)` 静态辅助（它本来就已被用在尾部两枚「关」按钮上，`None` 即真解锁）。**只在 `0 < want < 目标现宽` 且 `want >= 目标 minimumSizeHint 宽` 时才钉**——「行还装得下就不钉、绝不撑宽」同样是需求的一部分。
- **挂载点必须在 `_sync_advanced_page_align(adv_scroll)` 之后、且挂在它外面**：那个方法末尾有一批 `gridLayout_20.invalidate()+activate()`，提前量到的是过期几何；它还自带多处早退分支（`if anchor <= row_x or col_w <= 0: return` 等），从内部挂钩子不可靠。故新方法在 `_sync_page_layouts()` 里紧跟其后单独调用，`wide` 由 `self._scroll_stretch_extra(self._adv_scroll) > 0` 判定（该辅助对 `None` 滚动区安全）。最大化分支**只解除、不钉**：那一态两行都不溢出、右缘本就相等。
- **无头环境测不出这条需求**：`QT_QPA_PLATFORM=offscreen` 下 `QFontDatabase.families()` 为空，所有字形退化成同一个内置 Sans Serif、中文与数字同为 13px 前进宽，两行都不溢出，两个框天生等宽等缘（实测全窗口宽度下 delta 恒 0）——照现状断言等于什么都没测。回归测试 `tests/test_advanced_page_tail_align.py`（44 → 55 项）**显式制造压缩**（`anchor.setFixedWidth(sizeHint - 24)`）再断言右缘等齐，并顺带断言锚点自身 x/y/w/h 未动、目标框 `min == max == 压缩量`（真钉宽而非碰巧）。另外三个守卫用例分别守住「装得下时不钉」「绝不撑宽」「宽态整份两行快照 == 摘掉本方法的基线」；`_baseline_without_rest_interval_align` **必须另开一扇窗口**构造（已解除的钉宽会随调用残留，同窗重摘钩子会把基线算歪），`_unpin` 用 `setMinimumWidth(0)` + `setMaximumWidth(QWIDGETSIZE_MAX)` 而非 `setFixedWidth(0)`（后者会把最大宽一并钉成 0）。



命名页「视频命名规则」（`groupBox_8`）是绝对定位页内的 `QGridLayout`：说明文字 `label_66` 顶端对齐且可换行，「模板预览」多行框垂直策略为 `Expanding`。两者叠加产生两个问题：说明文字行高按更窄宽度的 `sizeHint` 计算（大于当前宽度实际换行高度）→「视频文件名」上方留白；预览框吃满网格剩余空间 → 被撑得过高。

`_sync_naming_template_section()`（由 `_sync_page_layouts()` 末尾调用，并监听 `tabWidget.currentChanged`、在 `label_66` 上装 eventFilter 捕获宽度变化，均在事件循环下一拍重算）按三步处理：

1. 解除上一轮固定高度后再 `setFixedHeight(heightForWidth(width))`，让说明文字精确贴合（必须先解除，否则 `QLabel.heightForWidth` 会回落到被钉住的旧值）；
2. 预览 `setFixedHeight(_NAMING_PREVIEW_H = 128)`，不再吸收剩余空间；
3. `groupBox_8` / `gridLayoutWidget_8` 高度按网格 `sizeHint` + `_NAMING_BOX_PAD` 重算，其后的 `groupBox_40/77/46/38/37/62/65/67` 用「设计基准 + 增量」整体平移，保持 19px 间距。

**与上文的例外**：本节控件在**非最大化状态**下也会随窗口宽度变化上下平移——窗口越宽文字换行越少、组高越小，后续分组必须同步上移，否则会重新出现大片空白。这是对「非最大化保持设计位置不动」的有意例外。

**登记表高度同步**：`CustomScrollArea` 的宽幅容器登记表存的是设计几何，`sync_wide_children_width()` 会按登记高度复位 `groupBox_8` / `gridLayoutWidget_8`；本方法在这两项高度变化后同步更新登记高度，再调用 `scrollArea_7.sync_content_min_height()`。

回归：`test_ui_structure` / `test_ui_geometry` / `test_window_state_matrix` / `test_main_window_startup`。

### 左下角状态区图标规范

主界面左下角状态区（`label_show_version`，`show_scrape_info` 组装文本后经
`label_show_version` 信号 `setText`）每行行首带一个 emoji 图标，图标种类与
位置与 `mdcx-diy-main` 完全对齐。修改任一图标前先通读本节，改完跑
`tests/test_left_status_icons.py`。

**图标对照表**（实现：`mdcx/controllers/main_window/main_window.py`）

| 位置 | 图标 | 文本 | 源码锚点 |
|---|---|---|---|
| 单文件模式首行 | 💡 | `单文件刮削` | `show_scrape_info` |
| 刮削模式行 | 💠 | `{main_mode} · {站点/字段}` | `show_scrape_info` |
| 单站刮削首行 | 💡 | `{website_single} 刮削` | `show_scrape_info` |
| 软/硬链接行 | 🍯 | `软链接 · 开` / `硬链接 · 开` | `show_scrape_info` |
| 配置文件行 | 🛠 | `{manager.file}` | `show_scrape_info` |
| 版本行 | 🐰 | `MDCx {localversion}` | `show_scrape_info` |
| 默认末行 | 🔍 | `点击检查最新版本` | `__init__` 的 `new_version` 初值 |
| 有新版本末行 | 🍉 | `有新版本了！<font color="red">{latest}</font>`（版本号相同仅日期更新时日期包含在红字范围内） | `_show_version_thread` |

**四条硬规则**

1. `before_info` 只做 `strip()`，**不得过滤 emoji**：调用方传的
   `💡/🔎/🎉/⛔/✅`（刮削中/完成/停止/提示）是首行图标，过滤即丢失。
   已删除的 `SCRAPE_INFO_EMOJI_RE` 不得加回来。
2. 仓库地址不硬编码：版本检查跳转（`label_version_clicked`）、日志下载链接、
   `check_version` 的 API、`GITHUB_ISSUES_URL` 全部由 `mdcx/consts.py` 的
   `GITHUB_REPO`（当前 `z291173301/MDCx`）派生；使用说明页
   （`MDCx.ui` / `MDCx.py`「十二、获取帮助」）硬编码同一仓库地址。
   改 UI 一律先改 `MDCx.ui` 再用 pyuic 重编译 + `ruff format`，不要手工改 `MDCx.py`。
3. **每行必须图标 + 文字同时存在**：不允许光杆图标（如 `💠 ·` 后面无文案），
   也不允许光杆文字（行首无图标）。模式行文案来自
   `Flags.main_mode_text` / `Flags.scrape_like_text`，二者是配置派生的展示态
   （`load/save_config` 从持久化配置写入），`Flags.reset()` 不得清空——
   刮削启停调 `reset()` 后文案必须保留，否则刮削完成后的状态区（读取/正常/
   整理/更新所有模式）模式行只剩图标。教训：`reset()` 曾清空二者，
   导致 `🎉 刮削完成` 之后模式行显示为 `💠 ·`。
4. 改本节规范时同步改 `tests/test_left_status_icons.py` 的
   `_REQUIRED_ICON_LITERALS`，文档与测试二者必须一致。

回归：`tests/test_left_status_icons.py`（图标逐字存在、`SCRAPE_INFO_EMOJI_RE`
不得复活、`GITHUB_REPO`/帮助页地址指向自有仓库、`reset()` 不得清空模式文案）。

### 信息管理筛选框匹配规则（改前必读）

实现：`mdcx/controllers/main_window/nfo_library.py`（入口
`lineEdit_nfo_lib_filter_changed`，拆词 `_split_keyword`、日期归一
`_token_variants`、慢路径分流 `_nfo_matches`、索引
`_parse_nfo_search_text` + `_nfo_lib_search_text`）。回归：
`tests/test_nfo_library_filter_fields.py`（14 项）。

**最终契约（改任何一条必须同步改测试与占位符）**

1. **拆词**：关键词按逗号/顿号/分号/空白/斜杠拆，全角标点先归一到半角
   （`_FULLWIDTH_MAP`，归一先于拆词）；`_DATE_PIECE_RE` 先把日期片段
   （`Y-M-D` 各种分隔符、`YYYYMMDD`/`YYMMDD`）整体抠出，`/` 不再切断日期；
   空段一律丢弃（首尾/连续逗号与 `A,B` 等价）；多词 AND、顺序无关。
2. **文件名快路径**：列表项文本只有番号（stem），任一候选子串命中即显示，
   免磁盘 IO（`261` 定位 `ARM-261`；`_haystack_matches`）。
3. **NFO 慢路径按词形分流**（`_nfo_matches`，索引是 `(文本, 数字集, 发行日集)`
   三元组，按 mtime 缓存）：
   - **日期形词**：`_token_variants()` 展开 `[原串, YYYY-MM-DD, YY-MM-DD]`
     候选（两位年份同时展 19xx/20xx），与发行日集（release/releasedate/
     premiered）**精确比对**，任一命中即算该词命中；
   - **纯数字词**（`_NUMERIC_TOKEN_RE`）：只与数字集（year/runtime/rating，
     `criticrating` 按 core 逻辑换算回 10 分制一并收录）**精确相等**；
   - **其他文字词**：在文本池（`_NFO_TEXT_XPATHS` = 演员名/标签值 +
     title/originaltitle/director/studio/maker/publisher/label/
     plot/outline/originalplot）内**子串匹配**。
4. **两个"不在池内"的字段**：`series` 不在文本池，经由 `系列：xxx` 标签命中；
   `criticrating` 只进数字集不进文本。增删可搜字段只改三个 XPATHS 常量，
   不要动分流逻辑。
5. **占位符必须与实际能力一致**（当前「筛选：番号/标题/演员/导演/片商/发行商/
   简介/标签/发行日/年份/时长/评分（逗号分隔）...」）。改 `.ui` 后一律
   `pyuic` 重生成 `MDCx.py` + `ruff format`，绝不手改（`test_ui_structure.py`
   会逐字节比对）。

**两次把搜索改崩的教训（禁令）**

1. **数字与日期永远精确比对，禁止 `startswith`/子串碰数字集与发行日集**：
   纯数字词曾允许"发行日前缀"口子（`2017-08-04`.startswith(`2`)），导致
   `ポルノスター,ABP,园田美樱,2` 误命中 ABP-622——`2` 落空整条才是正确行为
   （`test_filter_stray_digit_kills_match` 锁定）。以后任何"宽松一点"的想法
   （如年份前缀、时长区间）都必须先加测试再放行，默认不加。
2. **`_DATE_PIECE_RE` 的分隔符不含空白**：含空白的写法退化成三词 AND
   （宽松但可用），且能避免 `238 5.0` 被误抠成日期导致回归；`5.0`/`238`/
   `2013` 这类非日期数字不受归一化影响（`test_filter_release_date_formats`
   末尾有回归断言）。
3. **文字池收敛与恢复**：文字池曾收敛到仅演员/标签（标题/导演/片商/发行商/
   简介直搜彻底失效），后应用户要求加回。如再被要求收窄，必须同步改占位符
   并把旧用例更名为 `*_not_searched` 反向锁定，而不是直接删断言。

## 数据模型

完整数据流转链路：

```
FileInfo → CrawlerInput → CrawlTask
              ↓
          CrawlerResult ← 单个爬虫返回
              ↓
          CrawlersResult ← 多站聚合
              ↓
          ScrapeResult ← 最终刮削结果
              ↓
          ShowData ← 界面展示
```

关键数据类在 `mdcx/models/model_types.py`（CrawlerData 另见 `mdcx/crawlers/base/base_types.py`）：

- **FileInfo**：视频文件信息（番号、路径、分辨率等）
- **CrawlerInput**：爬虫输入参数（番号、语言、指定 URL）
- **CrawlTask**：完整刮削任务，继承 CrawlerInput
- **BaseCrawlerResult**：23 个字段（标题、演员、海报、评分等）
- **CrawlerResult**：单站结果，增加 source 和 external_id
- **CrawlersResult**：多站聚合结果，含字段来源追踪
- **ScrapeResult**：最终结果 = file_info + data + other_info

## 核心模块

### 主刮削器（mdcx/core/scraper.py）

`Scraper` 类统筹整个刮削流程：扫描文件 → 调度爬虫 → 聚合结果 → 翻译 → 下载 → 生成 NFO → 移动文件。使用渐进式任务调度，支持大量文件不溢出。

### 分离模式元数据复用/覆盖与冲突处理（改前必读）

- **两个开关**：`separate_reuse_metadata`（复用数据存放目录中的元数据文件：目标已存在则跳过图片下载与 NFO 写入）与 `separate_overwrite_meta`（覆盖本地保存的视频元数据文件：存在也重下重写），默认 False，`save_config.py` / `load_config.py` 接线并写入 JSON。
- **仅分离模式 + 数据存放目录有效时生效**：`extend.py: should_reuse_metadata(meta_root) / should_overwrite_meta(meta_root)` 均为 `meta_root is not None and is_separate_mode() and 配置值`——`meta_root` 无效（data_path 为空/不可创建、元数据退回视频目录）时没有「数据存放目录」可复用/可覆盖，若仍生效会让复用开关在回退路径上误跳图片下载与 NFO 写入；`scraper.py` 复用跳过条件额外含 `not overwrite_meta`，故手改 JSON 把两项都写成 true 时运行时仍以覆盖优先为准，不会出现既跳过又重写的不确定行为（`load_config` 读到双开时也以覆盖为准落盘显示）。
- **界面互斥**：`checkBox_separate_reuse_meta_changed / checkBox_separate_overwrite_meta_changed`（`main_window.py`）在勾选时自动取消另一项，去勾选不动作（无回环）；`init.py` 接 `toggled` 信号。
- **对齐**：覆盖框与「覆盖本地已存在的STRM链接文本」框上下严格对齐，由 `_sync_reuse_meta_gap_align()`（`main_window.py`，`_sync_page_layouts` 尾部调用）按两框实测 x 差闭环收敛钉死 gap 宽，窄宽往返冻结；行内子项顺序与文案由 `tests/test_ui_structure.py` 锁定。

### 分离模式 STRM 生成/覆盖的前置依赖（改前必读）

- **两个开关**：`separate_generate_strm`（为本地视频文件生成STRM链接文本）与 `separate_overwrite_strm`（覆盖本地已存在的STRM链接文本），默认 False。
- **覆盖以生成为前提**：`extend.py: should_overwrite_strm()` = `is_separate_mode() and separate_generate_strm and separate_overwrite_strm`。不生成 STRM 自然不存在「覆盖」，故未勾选生成时勾选覆盖不生效（其他模式同理不生效，调用方不得直读 `manager.config.separate_overwrite_strm`）。
- **生成条件**：`should_generate_strm(meta_root, skip_reorganize)` = 元数据根有效 + 非跳过整理 + 分离模式 + 已勾选生成。写入位置为元数据镜像目录 `meta_folder`（与 nfo/封面同目录），内容为视频最终绝对路径：开移动写 `file_new_path`，不开移动写 `file_path`（此时 `file_new_path` 指向未使用的目标目录）。
- **界面联动**：`checkBox_separate_generate_strm_changed`（`main_window.py`）在生成框勾选状态变化时置灰/恢复 `checkBox_separate_overwrite_strm`（只改 enabled，保留其勾选值，故重新勾选生成即恢复）；`init.py` 接 `toggled`，`load_config.py` 回读后同步 enabled 状态；tooltip 写明前置条件。
- **.strm 属元数据**：`SEPARATE_META_EXTS` 含 `.strm`，`move_other_file` 因此把源目录已有 .strm 搬进数据目录而非跟随视频。

### 文件爬虫（mdcx/core/file_crawler.py）

`FileScraper` 处理单个文件，负责番号识别、多站并发请求、字段级优先级合并。

### NFO 生成（mdcx/core/nfo.py）

生成 Emby/Jellyfin/Kodi 兼容的 XML NFO 文件，30+ 字段，含外部 ID（javdbid、javlibid 等）。

### TMDB 演员（mdcx/core/tmdb_actor.py）

通过 TMDB API 查询演员信息，日文名/中文名/繁体名多语言搜索。令牌桶限流（3.5 req/s），双层缓存（Excel + 内存）。

### Amazon 集成（mdcx/core/amazon.py）

从 Amazon 搜索高清封面，EAN-13 条码检测 → ASIN 映射。三层搜索策略：条码快路径 → 标题搜索 → 演员兜底。

- **封面下载尺寸规范**：统一请求 SL2560 原图变体。`_convert_to_target_size` 默认 `target_size="SL2560"`，输出 Amazon 官方下划线式 `https://m.media-amazon.com/images/I/{image_id}._SL2560_.jpg`（旧逻辑的点号式 `.SL1500.` 非官方格式，只拿到 1500 档）。`_normalize_amazon_image_url` 处理四种输入形态——标准下划线式（`._AC_UL320_.jpg`）、旧点号式（`.SL1500.jpg`，库内历史存量即此格式）、无后缀原图、已是目标尺寸（直接返回，点号式顺手规范为下划线式）；非 `m.media-amazon.com/images/I/` 链接原样返回。实测同图对照（SNOS-447，`81WvzlDdZOL`）：`._SL1500_.jpg` → 1055×1500/147KB，`._SL2560_.jpg` → 1778×2529/340KB。库内旧后缀行在下次缓存命中时经该函数自动升级，无需重新搜索。

### 人脸裁剪（mdcx/core/face_crop.py）

基于 OpenCV YuNet ONNX 模型，自动检测人脸并裁剪为 2:3 海报。

### 图片处理（mdcx/core/image.py）

图片下载、多尺寸修复、水印添加（9 宫格位置，支持文字水印）。

### 翻译（mdcx/core/translate.py）

6 个翻译引擎（Google/Bing/Baidu/DeepL/DeepLX/LLM），字段级翻译配置，多引擎降级。

### 命名系统（mdcx/core/naming/）

Jinja2 模板引擎，支持条件渲染、智能截断。三类命名目标：文件夹、文件名、NFO 标题。

命名变量：number、title、actor、all_actor、studio、series、year、release 等 24 个字段。

### 马赛克标准化（mdcx/core/mosaic.py）

`normalize_mosaic()` 将各类标签归一化为：有码、无码、无码破解、流出、无码流出、国产。

### Emby 演员工具（mdcx/tools/）

四个模块协同实现 Emby/Jellyfin 演员头像与简介的匹配、预览、同步：

- **emby_shared.py**：纯工具函数模块，5 个共用函数——`_generate_server_url`（地址拼接）、`_build_jellyfin_headers`（Jellyfin 鉴权头）、`_is_jellyfin_server`（服务器类型判断）、`_append_query`（URL 查询参数拼接）、`_upload_actor_photo`（头像上传）。被其余三模块共同导入，无循环依赖
- **emby_actor_manager.py**：管理器核心——`get_gfriends_index`（Gfriends JSON 索引，含版本检测+缓存刷新+展开写回）、`_parse_graphis_html`（Graphis 页面解析，manager 与 image 共用）、`fill_actor_info_from_sources`（统一信息补全链路 local→wiki→minnano→db）、`build_local_avatar_index`（预扫描本地头像目录建立文件名索引）、`search_actor_info`/`from_graphis` 等
- **emby_actor_image.py**：内置头像补全——`_get_gfriends_actor_data`（简化为 wrapper 调 manager 版）、`_get_graphis_pic`（调共用 `_parse_graphis_html`）、5 个 API 函数从 emby_shared 导入并 re-export（`# noqa: F401`）
- **emby_actor_info.py**：内置信息补全——`_process_actor_async` 调 `fill_actor_info_from_sources` 统一链路，`_BIO_TAG_PATTERNS`/`_extract_bio_tags` 移至 manager 模块

依赖方向：`emby_shared.py` ← `emby_actor_manager.py` ← `emby_actor_image.py` / `emby_actor_info.py`（单向，无循环）。

## 爬虫框架

### 基类

`GenericBaseCrawler[T]` 在 `mdcx/crawlers/base/base.py` 中定义，泛型抽象基类，所有爬虫继承。

**爬虫生命周期**：
1. `_generate_search_url()` — 生成搜索 URL
2. `_search()` — 请求搜索页
3. `_parse_search_page()` — 解析搜索页，拿详情页 URL
4. `_detail()` — 请求详情页
5. `_parse_detail_page()` — 解析详情页，返回 CrawlerData
6. `post_process()` — 后处理，返回 CrawlerResult

### CrawlerData

爬虫解析的中间数据，所有字段默认 `NOT_SUPPORT`（表示本站不支持此字段）。可选字段包括 title、actors、poster、outline、score、tags、series 等 25 个。

### 注册机制

爬虫通过 `register_crawler()` 注册到 `crawler_registry`，站点下拉框由注册表动态生成。需要在 `mdcx/crawlers/__init__.py` 中导入，并在 `Website` 枚举中添加。

### 添加新爬虫的步骤

1. 在 `mdcx/crawlers/` 下新建 .py 文件
2. 继承 `BaseCrawler` 或 `GenericBaseCrawler`
3. 实现抽象方法：`site()`、`base_url_()`、`new_context()`、`_generate_search_url()`、`_parse_search_page()`、`_parse_detail_page()`
4. 可选重写 `post_process()` 做后处理
5. 在 `mdcx/config/enums.py` 的 `Website` 枚举中加新值
6. 在 `mdcx/crawlers/__init__.py` 中导入并注册

### 镜像域名轮询

`mdcx/utils/domain_rotate.py` 的 `DomainRotator` 提供镜像域名轮询：声明类属性 `_domains` 后，请求失败（连接/SSL/超时等可重试错误）自动切换下一镜像域名重试。`_init_rotator(domains, custom_url)` 支持用户自定义 URL 优先。已接入：javbus（7 个镜像）、freejavbt、xcity。

### API 类爬虫（AioSiteCrawler）

部分站点是 Vue SPA + JSON API（页面 HTML 只是壳），无法用 `_parse_search_page` 解析 HTML。此类爬虫重写 `_run` 完全自定义流程，`_generate_search_url`/`_parse_search_page` 抛 `NotImplementedError` 占位。

- **AioSiteCrawler**（`mdcx/crawlers/aio_site.py`）：tellme.pw AIO 系列站点（avmoo/avsox/avheat）共享基类，封装 search（POST JSON 数组 body）+ getMovie（movieId）两步 API 流程、动态域名解析、字段映射。子类只需指定 `namespace`/`domain_site`/`mosaic`/`fallback_domain`。
- 参考实现：`missav_api.py`（Recombee API）、`aio_site.py`。

### 网络检测（check_urls）

`GenericBaseCrawler.check_urls()` 返回网络检测用的 URL 列表，默认返回 `_domains` 镜像列表或 `base_url_()`；动态域名站点覆写返回动态解析地址（avmoo/avheat/avsox 用 `get_aio_domain`，javlibrary 用 `get_javlibrary_domain`）。`mdcx/core/network_check.py` 据此对镜像/动态站点生成多地址检测项。

## 缓存系统

### TMDB 缓存

双层缓存：Excel 文件（持久化）+ 内存 dict（加速）。查询策略：先查内存→再查 Excel→再调 TMDB API。限流 3.5 req/s，并发数 3。

### Amazon 缓存

ASIN 数据库（Excel `amazon_asin_database.xlsx`），搜索到的 ASIN 与番号对应关系持久化，避免重复搜索。
- **读写**（`mdcx/core/amazon_database.py`）：`save_asin_to_excel` 写入按番号去重（同番号跳过）；`query_asin_database` 按番号/ASIN 查询；`update_asin_record` 原地更新 poster_url。
- **出厂库/用户库两层**：出厂库 `resources/userdata/amazon_asin_database.xlsx`（git 跟踪，按番号前缀字母+数字排序），用户库 `userdata/amazon_asin_database.xlsx`；首启不存在则复制出厂库，之后启动时 `merge_asin_db_from_backup` 按番号把出厂新增/修正合并进用户库（md5 标记跳过、只增不删、不覆盖用户已填值）；合并产生新增行时按番号整体重排并重新格式化（纯字段补全不重排）。

## 网络层

- **异步 HTTP**：httpx（默认）+ curl-cffi（指纹伪装）
- **浏览器指纹**：curl-cffi 模拟浏览器 TLS 指纹，默认池 7 种画像（Chrome 124/131/136 Win、Chrome 136 Mac、Firefox 133/135 Win、Safari 17.2 iOS）按请求轮换；Amazon 刮削用纯桌面池 6 种（不含 Safari iOS，避免偶发返回移动版页面）
- **限流**：并发数与全局线程延时控制请求节奏；Amazon 等高风控源使用自适应退避（`AdaptiveRequestThrottle`，命中 429 自动降速冷却），失败指数退避重试
- **Cloudflare Bypass**：通过 `trawl_adapter.py` 把请求翻译给外部CF服务（TRAWL `/scrape` 或 FlareSolverr `/v1`），自动绕过 CF 防护页；JavLibrary 额外支持 Selenium+Edge headless fallback（`selenium_adapter.py`，cf_selenium_bypass 默认开启）
- **代理**：HTTP/HTTPS/SOCKS5，按"走代理网站"域名路由（默认含 amazon.co.jp, m.media-amazon.com, xcity.jp, minnano-av.com, avbase.net, javbus.com, javdb.com, javlibrary.com, r18.dev, mgstage.com, prestige-av.com, seesaawiki.jp, avsox.click, avsox.com, avmoo.shop, avmoo.com, avheat.shop, avheat.com, heyzo.com, caribbeancom.com, 1pondo.tv, pacopacomama.com, 10musume.com, mywife.cc, github.com, raw.githubusercontent.com, google.com, missav.ws, missav.ai, missav.live, aventertainments.com, javfree.me, 7mmtv.sx, 7tv022.com, avsex.cc, getchu.com, dl.getchu.com 共 37 域）

### TRAWL / FlareSolverr 适配层（mdcx/cf_bypass/trawl_adapter.py）

外部CF服务（TRAWL、FlareSolverr）与 mdcx 所需的 cf_bypasser 协议（`/cookies` `/html` `/mirror`）不兼容，适配层负责翻译：

- **协议转换**：暴露 cf_bypasser 三端点，内部按后端调用外部服务并归一化为统一结构。
  - `trawl` 后端：走 TRAWL 原生 `/scrape` API（返回 url/html/cookies/userAgent/statusCode 等；注意原生响应没有 `responseHeaders`/`body` 字段，适配层走 `html` 回退）。
  - `flaresolverr` 后端：走 POST `/v1`（`cmd=request.get/post`），从 `solution.headers` 还原响应头。
- **启用**：配置 `cf_bypass_trawl_url` + `cf_bypass_trawl_backend`（默认 trawl），`AsyncWebClient` 自动在本地拉起 `TrawlAdapterServer`（随机端口 + uvicorn 子进程）。回环地址的 `https` 会经 `normalize_trawl_url` 降回 `http`（FlareSolverr/TRAWL 本地实例只 serving 纯 HTTP，否则适配层 60s 探活失败并永久禁用）。
- **代理路由**：`is_proxy_host` 域名条目会反查站点归属——名单写主域（如 `javlibrary.com`）时，同站点的动态镜像/备用域（如 f101w/c97k、GitHub 学习到的新域）自动跟随走代理；直连白名单仍优先。
- **架构**：web_async 的 `_try_bypass_cloudflare` 只通过 `cf_bypass_url` 调本地 ASGI 服务端点，不区分内置/外部——`_ensure_local_bypass` 统一拉起适配层后设置 `cf_bypass_url`。
- 内置 CF Bypass（cloakbrowser + cf_bypasser）已移除（v2.0.6），过 CF 统一走外部服务。

### 动态域名

- `mdcx/base/web.py::get_aio_domain(site)`：从 `tellme.pw/{site}` 导航页解析 `__AIO_SITE_URLS__`，带 1 天缓存、三站互相兜底，供 avmoo/avsox/avheat 使用。
- `mdcx/base/web.py::get_javlibrary_domain()`：抓取 github.com/javlibcom 主页 `rel="nofollow me"` 链接提取最新直连地址，失败回退已知镜像。

### 网络检测（mdcx/core/network_check.py）

- 站点检测项由爬虫 `check_urls()` 动态生成（见"爬虫框架"章节）。
- API 类爬虫（重写 `_run`）走真实刮削探测：`_probe_crawler_by_run` 直接 `crawler.run(input)` 验证刮削能力，而非解析 HTML。
- 探针番号用 `SCRAPE_PROBE_NUMBER`（默认 SSNI-647），站点有收录类型限制时用爬虫 `probe_number` 类属性覆盖（如 avsox 用无码番号、avheat 用欧美番号）。

## 配置系统

基于 Pydantic 的 `Config` 模型（200+ 配置项），JSON 格式存储。旧版 INI 格式自动迁移。

`ConfigManager` 单例管理加载/保存/热切换。`Computed` 派生对象（HTTP 客户端、LLM 客户端等）在配置变更时自动重建。

敏感字段（API Key）导出时自动脱敏为 `***`。

## 依赖

从 `pyproject.toml` 读取，核心依赖：
- PyQt6 6.11.0（UI 框架）
- httpx（HTTP 客户端）
- curl-cffi >=0.15.0（TLS 指纹模拟；0.12 起 sentinel 更名已兼容）
- lxml + parsel + beautifulsoup4（HTML/XML 解析）
- Pillow + opencv-contrib-python-headless（图片处理）
- Jinja2（命名模板）
- openpyxl（Excel 读写）
- uvicorn（外部CF服务适配层）

## 测试

- **框架**：pytest + pytest-asyncio
- **标记**：`network`（需要联网的测试，默认跳过）、`integration`（集成测试，默认跳过）
- **运行**：
  ```bash
  uv run pytest tests/                          # 全部测试
  uv run pytest tests/ --tb=short -m "not network" -x  # 仅不联网测试
  ```
- **CI 平台分工**：Linux CI 执行 ruff、mypy、完整离线测试、数据库检查和线程安全检查；Windows CI 在 `windows-2025` runner 上执行同一组离线 pytest 并做一次 PyInstaller 冒烟构建，覆盖 Windows 路径和文件系统条件分支。正式 Release 在 macOS、Windows 和 Ubuntu runner 分别构建 DMG、EXE 和 x86_64 Linux 单文件程序。
- **CI 触发方式**：`ci.yaml` **只监听 `pull_request`（目标分支 main），不监听 `push`**。日常用 GitHub Desktop 直接把提交同步到 main，挂着 `push: main` 会让每次同步都在 Actions 列表里多出一条 `CI/CD Pipeline`；主干没有 PR 流程时这条 run 只是噪声。因此质量门禁改为「PR + 本地自检」两道：提交前必须过 `uv run quick-check`（ruff format/check + mypy），推送前过 `uv run check --skip-hook-install`（再加 pytest + check_thread_safety）。守卫见 `tests/test_ci_workflow_triggers.py`（锁"无 push 触发"+"PR 门禁与 ruff/mypy/pytest 步骤仍在"）。
- **覆盖**：tests/crawlers/ 爬虫测试、tests/core/ 核心测试、NFO 测试、配置测试、`tests/test_ui_structure.py`（UI 结构）、`tests/test_actor_clean.py`（演员数据语义清洗）等
- **演员数据清洗测试**（`tests/test_actor_clean.py`）：验证 `mdcx/utils/actor_clean.py` 对名字/别名字段的语义清洗——系列标签/年份/国籍/事务所标注剥离、作品标题剔除、悬空斜杠修复、占位符识别置空，同时确保罗马音/日文映射、读音、韩文别名等合法内容不被误伤。新数据写入（刮削写入 `update_actor_db_row`）前统一经此模块清洗
- **演员库完整性测试**（`tests/test_check_actor_db.py`）：验证 `scripts/check_actor_db.py` 对出厂 `actor_database.xlsx` 的完整性检查——jp 重复、tmdbid 重复、url 错配、**孤儿 hyperlink**（XML 层解析 `<c>` 定义集合与 `<hyperlink>` ref 差集）等。`clean_actor_db_non_actors.py` 删行后按 cell 实际坐标重建超链接，配合保存后校验防止孤儿 hyperlink 进入仓库
- **UI 结构测试**（`tests/test_ui_structure.py`）：解析 `mdcx/views/MDCx.ui`，离线验证
  - groupBox 同父容器内不重叠、无负间距、不超出滚动区高度
  - 用户控件 objectName 唯一（重复控件是无用残留的信号）
  - `MDCx.py` 与 `MDCx.ui` 同步：用 pyuic6 重编译 + ruff format 后与仓库版文本一致，防止只改 `.py` 不同步 `.ui` 或改 `.ui` 后忘重编译
  - **规则**：改动 UI 一律先改 `MDCx.ui`，再运行
    `/workspace/.venv/bin/python3 -m PyQt6.uic.pyuic mdcx/views/MDCx.ui -o mdcx/views/MDCx.py`
    及 `uv run ruff format mdcx/views/MDCx.py`，不要手工改 `MDCx.py`
- **演员工具页按钮一致性测试**（`tests/test_actor_db_button_consistency.py`）：纯静态校验（无需 Qt 运行时），锁定 `_ACTOR_DB_IDLE_TEXT_MAP` ↔ `MDCx.ui` 中控件 ↔ `MyMainWindow` 顶层 `pyqtSignal(str)` 声明 ↔ `actor_db_finished` 信号契约四层一致。按钮改名、漏声明信号、map 漏收等漂移在 CI 即可捕获
- **actor_db 并发信号契约**：`actor_db_finished = pyqtSignal(str)` 带 task_id；所有 `_run_actor_db_*` 走 `_run_actor_db_async(btn_attr, busy_text, log_prefix, coro_factory)` 通用模板，防重入依赖 `_actor_db_running` 集合，跨任务误恢复由 `reset_buttons_status` 与 `_on_actor_db_finished` 共同规避
- **推送前自检**：修改代码后先运行 `uv run quick-check`（ruff format/check + mypy）；提交推送前运行 `uv run check --skip-hook-install`（ruff format/check + mypy + pytest + check_thread_safety；出厂演员库/信息库或其校验脚本有改动时才跑 `check_actor_db` / `check_info_db`）。`scripts/check_ui_layout.py` 只作手工诊断（warning 不阻断），结构约束由 `tests/test_ui_structure.py` 锁定。

## 代码规范

### 界面问题的取证与验证（2026-10-02 立规）

下列各条来自「设置页滚动条忽宽忽窄」一案——该案连续三轮改错方向、每轮都「验证通过」，直到用户实测两遍才发现没修好。根子不在手笨，在于**取证方式本身有系统性盲区**，故立规。

- **界面问题一律以「渲染出来的像素」为准，不以控件属性为准。** 属性（`width()` / `sizeHint()` / `min` / `max`）描述控件**认为自己**多大，绘制结果才是用户**看到**多大，二者可以完全不一致——本案的终局正是「12 个页签属性全对 16，实际画出来 11 个是 12」。量像素用 `widget.grab().toImage()`，且**必须从整窗合成图 `win.grab()` 取**（对未绘制的隐藏控件单独 `grab()` 只会拿到陈旧的后备存储像素）。**属性全绿不构成「已修复」的证据。**
- **量之前先断言目标真的显示了。** 本案探针按 `stackedWidget` 下标 2 进设置页，而 `page_setting` 实际在 **4**，页面全程 `isVisibleTo=False`、控件从未被布局/抛光，于是 11 条滚动条的「不可见」被当成「无需检查」跳过，整批数据作废。**断言 `page_setting.isVisibleTo(win)` 通过之前，任何测量结果都不算数。** 另：短窗口下切 NFO 页（`tabWidget` 下标 8）会让进程直接崩（无 Python 栈），造溢出要靠正常窗宽 + 逐页切换，不要压窗口高度。
- **「异常落在哪几个」会变，说明在和事件循环赛跑，不是在修病因。** 第一轮坏的是字幕/水印/演员/网络/高级，第二轮变成下载/刮削网站/刮削模式——**换了一批坏的就等于没修**。遇到随机性先假定有竞态，把定时的修复下沉到控件自身的事件钩子，别挂 `QTimer.singleShot(0)`。
- **改了几何不等于改了绘制；样式表驱动的子控件要重新 polish。** Qt 在 polish 时算好并缓存 groove/handle 等子控件矩形，之后 `setFixedWidth` 只更新几何、不作废缓存，绘制仍按旧值走。**症状是 `update()+repaint()` 完全无效**，必须 `style().unpolish(w); style().polish(w)`。判据：改宽度后画面对不上，先试重新 polish（本案实测 `setFixedWidth(15)` 画 15、`(16)` 画 16，但都得先 polish）。
- **区分「某控件内部数据对」和「用户看到的对」是两类断言，测试要各写一条。** 离屏 pytest 不绘制，`grab()` 拿到的是空后备存储（整行同色），此时像素断言只能**放宽为 `None` 或期望值**；真正的像素验证放在带真实事件循环的探针里做。
- **诊断脚本要自动驱动，不能依赖用户手工点。** 两轮让用户自己操作采集的日志都是废的（一次 11 秒内从未进过设置页，一次进程 150ms 就结束）。探针应复刻真实启动路径后自行遍历全部状态并输出可判读的结论。
- **宣称「已修复」前先问一句：这个探针能不能判别出故障？** 若把有 bug 的代码喂给它也返回「一切正常」，说明它没有判别力，此时的「通过」是假阳性。本案靠这一条才逼出真因。
- **宣布失败要干脆。** 用户实测没变化就直说没修好，别用「属性已全部正确」之类的读数去解释成成功。

### 「这个字看起来比那个小」——高 DPI 下字体大小问题的取证顺序（2026-10 立规）

用户报「`[赞助作者]` 看着比 `软件设置`/`使用说明` 小」，第一直觉是「某个控件没跟着系统缩放」。**这个直觉通常是错的**，照着它改会白改几轮。按下面顺序查：

1. **先量系统缩放，别猜。** `app.primaryScreen().devicePixelRatio()`。本项目开发机的 dpr = **1.25**（Windows 125%），用户提供的参考截图 `@赞助.png`（657×677）也是 125% 截图——含约 40px 原生标题栏，故其**客户区 657×637 是设备像素**（= 524×509 逻辑像素）。**拿设备像素的参考图去对逻辑像素的布局，等于凭空差 25%。**
2. **QSS 里的 `font-size: Npx` 是逻辑像素，会被 dpr 自动缩放**，不存在「这个控件没缩放、那个缩放了」的情况。`QLabel.setFont()` 会被祖先样式表覆盖而**完全失效**，字号只能靠 QSS 或富文本内联 `font-size` 写——先确认写的那一处真的生效（见第 3 条），再谈数值。
3. **别只看 `font().pixelSize()`，要量墨迹。** `widget.grab().toImage()` 取**设备**像素图，逐像素判 `min(R,G,B) <= 140`（避开抗锯齿灰边与 ClearType 色边）求包围盒。**注意 `geometry()` 是逻辑像素、`grab()` 是设备像素，必须 × dpr 换算**——本项目曾因漏换算把别的控件当成按钮文字，测出「18.00 px/字」的假数据，绕了一整轮。
4. **区分「尺寸」与「墨迹密度」两个独立量。** 尺寸 = 墨迹 bbox 宽高 / 每字 advance；密度 = 墨迹像素数 ÷ bbox 面积。**同尺寸、不同密度 ⇒ 观感上的「大小」差异来自笔画粗细，不是字号。**
5. **同尺寸但密度不同，多半是字体回退/渲染路径差异，不是字号没设上。** QPushButton 走 `QStyle::drawItemText` + CJK 回退字体，QLabel 走 QTextDocument；同一 14px 下按钮 density **0.409**（ink 487）、QLabel **0.364**（ink 427），少 12% ⇒ 同样高度但更淡，肉眼就读成「字更小」。`font().family()` 两者都是 `Consolas`（无 CJK，走回退）且 `adv('赞')` 都是 14，正说明**尺寸确实相同、都已被 dpr 缩放**。
6. **别把富文本当嫌疑人，除非做过 A/B。** 同一 QLabel 纯文本 vs `<a href>` 包裹实测逐像素一致（427/427），两条渲染路径无差异，可直接排除。
7. **颜色也会改变视觉重量。** 浅蓝 `#0078D7` 的链接比纯黑 `color: black` 的按钮淡一档，叠加笔画更细，观感差被放大。**要「一样大」时，优先保证不小于**（本项目最终取 16px：w 63.2 vs 按钮 56、h 16.0 vs 13.6），而不是纠结 14 还是 15。
8. **离屏验证字体必须用真实平台插件。** `QT_QPA_PLATFORM=offscreen` 下 `QFontDatabase.families()` 返回 **0 个字体**，中文全是豆腐块或空白——截图会「看起来正常」而毫无内容。**测字体一律 `QT_QPA_PLATFORM=windows`。** 同理，探针里 stub 掉 `set_style()` 会让样式表从不生效（`font().pixelSize()` 返回 -1），此时量到的全是无样式状态。

### 离屏渲染校验流程（字体/几何类改动）

1. 探针里 monkeypatch 掉联网/落盘的副作用方法（`run_startup_health_checks` / `show_netstatus` / `check_version` / `save_remain_list` 等）为 lambda。
2. **不要 stub `set_style()`**——否则 QSS 不生效，量到的字号/配色全错。要拦的是它内部的网络与主题部分（如 `apply_site_priority_theme`）。
3. `resources.qtr` 指向真实 resources 目录，否则图片加载失败会走降级文本分支。
4. 遍历目标尺寸区间逐档断言几何（不重叠、不越界、留白恒定），并**把关键档位 `grab()` 存 PNG 肉眼复核**。
5. 断言要落在**不变量**上（底边贴底、间距恒定、边长恒定），不要写死具体 y 值——否则改一次设计就得改一次测试。

- **格式化**：ruff（行宽 120，启用 isort/pyupgrade/flake8）
- **类型检查**：mypy（全项目零 `disable_error_code`；`mdcx/controllers/main_window/init.py`、`load_config.py`、`views/`、`gen/` 等豁免，CI `ci.yaml` 强制执行）；pyright 仅在 `pyproject.toml` 中保留配置，未纳入 CI 门禁
- **Git 钩子**：项目不要求安装 pre-commit；统一使用 `uv run quick-check` 和 `uv run check --skip-hook-install` 完成检查
- **检查和修复**：
  ```bash
  uv run ruff check .          # 代码检查
  uv run ruff check . --fix    # 自动修复
  uv run ruff format .         # 格式化
  ```

## 版本号管理

版本号有两处定义、五个同步点；任一处不一致都会被 `scripts/bump.py --check` 与 `tests/test_version_consistency.py` 判红。

**两处定义（`mdcx/consts.py`）**

- `LOCAL_VERSION`：纯数字 `YYYYMMDD`，用于版本比较、更新检查与构建；**GitHub release 的 Tag 必须是同值纯数字**（`check_version` 对 `tag_name` 做 `int()`，`vX.Y.Z` 形态的标签会被直接跳过）。唯一发版工作流 `build-py314.yml` 遵守这一条，没有非纯数字 tag 的例外，详见「构建」一节。
- `VERSION_NAME`：展示名 `vX.Y.Z`，界面/日志统一显示为 `VERSION_NAME (LOCAL_VERSION)`；更新检查时它也作为**版本号维度**参与比较（见下节），不再纯装饰。

**五个同步点**

| 位置 | 值 |
|---|---|
| `mdcx/consts.py` 的 `LOCAL_VERSION` | `YYYYMMDD` |
| `mdcx/consts.py` 的 `VERSION_NAME` | `vX.Y.Z` |
| `pyproject.toml` 的 `version` | `X.Y.Z`（`VERSION_NAME` 去掉 `v`） |
| `docs/Changelog.md` 首个版本段 `## vX.Y.Z (YYYY-MM-DD)` | 版本 = `VERSION_NAME`；日期 = `LOCAL_VERSION` 的日期 |
| `uv.lock` 根包 `mdcx` 的 `version` | `X.Y.Z`（与 `pyproject.toml` 一致；CI 全平台 `uv sync --locked` 强校验，脱节即构建失败） |

**事故记录（2026-09-27）**：曾只升 `pyproject.toml` 到 2.1.4、漏同步 `uv.lock`（根包仍锁 2.1.3），发版工作流四个构建腿（windows-2025 / macos-latest / macos-15-intel / ubuntu-latest）齐刷刷在 `Install locked dependencies` 步 exit 1。教训：改版本号/日期必须走 `bump`（现已自动同步 lock），且以 `bump --check` + 版本一致性测试为准，不要手改单点。

**改版流程**

1. 在 `docs/Changelog.md` 顶部新建目标版本段并写条目；已发版旧段保留，未发版段被后续议题取代时合并重写成最终形态。
2. `uv run bump --version <YYYYMMDD> --name X.Y.Z` 同步五处（`--dry-run` 预览、`--force` 免交互；`--name` 会连带同步 `uv.lock` 根包版本）；只校验用 `uv run bump --check`。
3. 复核 `uv run pytest tests/test_version_consistency.py tests/test_version_metadata.py`。
4. 打**纯数字** tag（= `LOCAL_VERSION`）触发 `.github/workflows/build-py314.yml`。「已发版」的判据是数字 tag 已推送，而非 changelog 有没有该段。同一版本号重复触发会覆盖更新同一条 Release（`overwrite: true`），不会多出第二条。

版本号归属维护者，不擅自开新段。`scripts/build.py` 与主窗口不留版本常量：build 从 `consts.py` 读 `LOCAL_VERSION`（`--version` 可覆盖），界面统一展示 `VERSION_NAME (LOCAL_VERSION)`。

### 更新检查（客户端自动更新）

代码在 `mdcx/base/web.py` 的 `check_version()`（拉取）与 `is_remote_version_newer()`（比较），主窗口侧是 `main_window.py` 的 `_show_version_thread()`。有六条不变量，改任一处都要连带另几处。

**① 取 tag 最大的 release，不是列表第一条。** `/releases?per_page=10` 按 `created_at` 倒序返回，**不按 tag 倒序**；而本工作流四个 `Create Release` 步骤用同一 tag + `overwrite: true`（`svenstaro/upload-release-action` 先删后建），任何一次补发/重跑都会把那条 release 的 `created_at` 刷成"当前时间"、顶到第一位。原实现取第一条，于是**手动补发一次旧 tag 就让所有用户从此看不到新版本提示且无任何报错**。修法是遍历全部条目收集所有 `tag_name.isdigit()` 的值取 `max`（`tests/test_version_check_pick_latest.py` 守卫）。tag 必须纯数字这条硬约束不变，非纯数字 tag 照旧跳过。

**② 版本号优先，版本号相等才比日期。** 两侧版本号都能解析时：不同 → 由版本号决出（远端更高即有新版本）；相等 → 比日期（远端更新即有新版本）。任一侧解析不出（标题非 `vX.Y.Z` 形态）→ 退回只比日期。两条并列才覆盖得住：只比日期则"当天发两版、两个 tag 同一天"认不出第二版；只比版本号则"同版本号跨日期补发"会漏判。

刻意**不做字面 OR**（不让"日期更新"在版本号更低时也触发）：那会提示用户**降级**，且 `LOCAL_VERSION` 常先于线上发布 bump（源码已 20261002 而线上还是 20261001），开发版会对着已发布的历史版本反复提示「请及时更新」。

**③ 源码版本号高于线上时不提示。** `LOCAL_VERSION` 是发版日，通常先于线上 release bump，故拿当前源码打包自测**永远不会**看到新版本提示——这是正确的，不是 bug。要测提示链得拿**上一个已发布 tag** 的包去比线上最新。

**④ API 失败必须回退到 `releases.atom`（v2.2.5 起，治「时灵时不灵」）。** `check_version()` 主路径是匿名 `api.github.com`，配额 **60 次/小时/出口 IP**（不是/用户、不是/实例）——同一出口 IP 下所有 MDCx 用户共享一个计数桶，耗尽即 403 → 返回 `None` → 主窗口打绿色「你使用的是最新版本！🎉」，用户观感就是「一会儿能检测到一会儿检测不到」。故任何一次 API 失败（403 限流 / 超时 / 5xx / 非数组 JSON / 全非数字 tag）都必须再走 `github.com` 站点的 `GITHUB_RELEASES_ATOM`（`consts.py`，**不受该配额约束**）。atom 侧用 `parse_release_atom()` 解析，同样**取最大 tag**——不变量 ① 对两条源同时成立，改一条必须同时改另一条。atom 解析入口是公开函数（便于脱离网络单测），标题要过 `html.unescape()`。

**⑤ 结果要落 6 小时本地缓存（v2.2.5 起）。** `userdata/version_check_cache.json`（`_VERSION_CACHE_TTL = 6 * 3600`），写入用 tmp + `os.replace` 原子替换，路径走 `resources.u()`（运行时状态不进配置也不进 git，约定同 `core/image_host_cooldown.py`）。三条行为：**新鲜缓存命中 → 一个请求都不发**；**网络失败 → 回退用任意年龄的缓存**（`_read_version_cache(float("inf"))`）；**缓存损坏 / 路径不可写 → 静默降级为纯联网**，绝不抛异常打断启动自检。`_read_version_cache(max_age)` **刻意不给默认参数**——默认值会在 def 时把 TTL 绑死，之后 monkeypatch `_VERSION_CACHE_TTL` 失效、TTL 用例假通过；所有调用方显式传 `_VERSION_CACHE_TTL` 或 `float("inf")`。写 `check_version()` 相关测试时**必须**把 `_version_cache_path` monkeypatch 到 `tmp_path`，否则上一个用例刚写的缓存会让下一个用例直接短路返回、把网络断言全部架空。

**⑥ 12h 定时复查必须走完整提示链。** `timer_update` 曾直连裸 `check_version`——阻塞主线程做网络 I/O，返回的版本号无处消费，定时检查永远不产生提示，只有启动 `show_version()` 那一次会提示。修法：定时器改连 `self.show_version`（网络回工作线程，结果走比较+提示链）；`_show_version_thread` 内用 `_notified_new_version` 做 transition 去重——仅首次发现该新版本时执行提示块（红字日志、下载链接、左下角标签刷新），同一版本重复检查不再刷屏，出现更新的版本自动再次提示；`version_check_done` 原样发射（cursor 设置幂等，cookie 检查顺带保鲜）。**提示副作用必须整体进 gate**：初版曾把 gate 只套在 `_notified` 赋值上、红字与下载链接露在外面，被回归测试当场抓获。回归测试 `tests/test_version_check_notify.py`（fixture 照 matrix 配方，另桩 `show_version` 禁启动线程抢读桩、`check_theporndb_api_token`/`ActressDB.init_db`/三 cookie 检查禁网络，`signal_qt.show_log_text` 计数红字）：新版本提示一次→同版本复查零新增→更新的版本再提示→已是最新走绿色；另锁定定时器周期仍为 12h。

`check_version()` 的返回值是 `RemoteVersion(tag, name)` NamedTuple（带 `display` 属性：无标题时退回纯数字 tag），不是裸 `int`；调用方与测试桩都要跟着换。主窗口侧 `_notified_new_version` 也存 `RemoteVersion`，用于 12h `timer_update` 复查的 transition 去重。改返回类型时注意 `tests/` 下另有 12 处 `lambda: None` 桩（桩成 `None` 的不受影响，桩成版本号数值的会挂）。

## 构建

使用 PyInstaller 打包，入口文件为 `main.py`。正式 Release 会构建 macOS ARM64 DMG、Windows x86_64 EXE 与 Linux x86_64 单文件程序。

Linux 手动构建依赖 Ubuntu 的 Qt 图形运行库，完整列表见 [Install.md](Install.md#linux-额外步骤)。构建前安装锁定依赖，再执行：

```bash
uv sync --locked --all-extras --dev
uv run build --debug
```

正式发版只有一条工作流：`.github/workflows/build-py314.yml`（**Build and Release (Python 3.14)**），四平台矩阵（macOS ARM64 / macOS Intel / Windows x86_64 / Linux x86_64）全量构建，创建 tag 为纯数字 `LOCAL_VERSION` 的 Release，资产名 `MDCx-<版本>-<平台>-<架构>-<sha>`。**客户端自动更新只看这个 Release，资产名与 tag 形态都是对外契约，别动它。**

两种触发方式：

| 触发 | tag 取值 | prerelease |
| --- | --- | --- |
| `push` tag `2*`（如 `20260928`） | 推送的 ref | 一律 `false` |
| `workflow_dispatch` 手动补发 | 输入的 `tag`，留空则取 `consts.py` 的 `LOCAL_VERSION` | 由 `prerelease` 输入决定 |

2026-09-28 起本工作流接过了原 3.13 主流程（`build-py313.yml`，更早叫 `release.yml`）的全部职责，那两个文件连同单平台手动构建的 `build-windows.yml` / `build-linux.yml` 一并删除——四平台矩阵已完全覆盖后两者的功能，3.13 侧不再需要独立流程。

3.14 专属三处：`python-version: 3.14`、`UV_PYTHON: 3.14`、构建前用 `sys.version_info[:2] == (3, 14)` 断言解释器（防 uv 悄悄挑到别的版本），以及 `uv sync --locked` 失败自动回退 `uv sync` 重新解析（`uv.lock` 未必有 cp314 wheel；只改 CI 临时工作树，不动仓库 lock）。另有三处护栏：

1. **缺产物不发版**：`build-app` 带 `continue-on-error`，`publish-release` 用 `if: !cancelled() && needs.build-app.result == 'success'` 把关（不能写 `success()`：`needs` 里任一失败腿都会让它整体跳过），并在上传前核对四个平台产物齐全——半成品 Release 比不发更糟。
2. **并发不互杀**：`concurrency` 按 ref 分组且 `cancel-in-progress: false`，半路取消会留下缺资产的 Release。
3. **重跑幂等**：四个 Create Release 步骤都带 `overwrite: true`，同一版本号重复发版只更新同名资产，不新建。

上述约定由 `tests/test_py314_release_workflow.py`（10 项）与 `tests/test_workflow_action_pins.py` 守住（纯文本断言，不引入 yaml 依赖），改工作流后请一并跑 `uv run pytest tests/test_sr_bundling.py tests/test_py314_release_workflow.py tests/test_workflow_action_pins.py`。


依赖版本下限按 Python 3.14 抬过三处，改依赖时务必守住（否则 3.14 流水线的 `uv sync --locked` 会硬失败）：

- `pyinstaller>=6.16.0,<7`：6.14.2 的元数据是 `requires-python = ">=3.8,<3.14"`，3.14 上装不上。
- `av>=15.1.0`：15.0.0 只有 cp39~cp313 的 wheel，3.14 上会退回源码编译（需 FFmpeg 开发库）。
- `aiofiles==25.1.0`：25.1.0 起官方测试并支持 3.14。

其余依赖已逐条核对，3.14 直接可用、无需动：`pyqt6`（cp310-abi3）、`opencv-contrib-python-headless`（cp37-abi3）、`curl-cffi`（cp310-abi3）、`aiohttp`/`lxml`/`numpy`/`pillow`/`pydantic-core`/`mypy`（有 cp314 wheel）、`pyinstaller`/`ruff`（`py3-none`）、`oshash`/`zhconv`（PyPI 上只有 sdist，但上游是**纯 Python**、无 C 扩展，不会编译）。核对口径：看 PyPI `releases[版本].urls` 的 tag 是否为 `cp314-*` / `*-abi3-*` / `*-none-*`，并读 `requires_python` 上界。改完依赖记得 `uv lock`（CI 用 `uv sync --locked` 强校验），`requires-python` 保持 `>=3.13.4`（不能带 upper bound），3.13 仍是基线。`tests/test_py314_dependency_floors.py` 守着上述三条下限、`uv.lock` 与 `pyproject.toml` 的声明同步、以及 `requires-python` 无上界。

## 迁移指南

### 旧版爬虫 → GenericBaseCrawler

旧版函数式刮削器迁移步骤：
1. 创建新文件继承 BaseCrawler
2. 将搜索逻辑移入 `_search()` + `_parse_search_page()`
3. 将详情逻辑移入 `_detail()` + `_parse_detail_page()`
4. 使用 `CrawlerData` 代替手动构造字典
5. 注册到 `crawlers/__init__.py`

### PyQt5 → PyQt6

主要变更：QtCore.pyqtSignal → QtCore.pyqtSignal（相同），枚举使用 Enum 风格，QRegExp → QRegularExpression。

### 配置 v1 (INI) → v2 (JSON)

通过 `migrations.py` 自动转换，旧版 INI 配置在加载时自动迁移为 JSON。

## 支持的命令行

```bash
uv run crawl           # 命令行爬虫调试
uv run gen_enums       # 生成枚举
uv run build           # PyInstaller 打包
uv run bump            # 版本号更新
uv run changelog       # 生成变更日志
```

## 大图预览窗口任务栏与窗口状态（v2.2.1 起）

### 独立顶层窗口

- `NfoPreviewWindow` 必须 `super().__init__(None)`，对主窗口只保留只读引用（`self._main`）；绝不再 `setParent` 挂回去。图标用 `resources.icon_ico`（延迟导入防循环）。

### 独立 AppUserModelID

- 预览固定 `MDCx.NfoPreview`，首次显示前设置，之后不动标记/父子关系。
- ctypes 三铁律（都出过访问违例血案）：`windll` 函数显式声明签名；COM 接口指针先解一层再取虚表函数；`GetValue` 的指针 `CoTaskMemFree`（同样先声明签名）。
- `showEvent` 读回校验丢了就补（`_ensure_taskbar_app_id`）；回归测试锁 ID 存在＋主窗口无＋hide/show 后还在（真实 Windows，离屏跳过）。

### 还原后严丝合缝盖住

- `changeEvent` 只认“从最小化出来”：是否最大化从 `event.oldState()` 取；还原时最大化恢复最大化，普通态 `showNormal + setGeometry(主窗口几何)`；最大化盖普通不动；不抢焦点。
- 主窗口还在最小化则挂起（`_cover_pending`），由装在主窗口上的 `eventFilter` 在其回来时执行；`_restore_after_parent_restore` 两拍 timer 保留，互斥幂等。
- `show_matching` 全程 `_placing`（`try/finally`）；手动还原、拖动一律不动；`closeEvent` 清标记。
- 最大化前先钉还原矩形到启动尺寸，几何只在普通态写、泵一次事件（还原按钮点不动的根因）。

### 关闭语义

- 预览 `WA_QuitOnClose=False`；主窗口 `closeEvent` 收起分支连带 `close()` 预览。
- 再报“关预览退进程”先查构建落点（一个图标＝老构建）再查事件查看器异常代码，不要直接动代码（`quitOnLastWindowClosed` 全局已关＋AST 锁定）。
