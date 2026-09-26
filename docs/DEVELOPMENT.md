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
- 修复：`_sync_nfo_title_plot_align()`（`_sync_page_layouts` 末尾调用，另接 `tabWidget.currentChanged` 下一拍，同右列对齐的休眠页补齐逻辑）。自适应钳制：先把 sorttitle/outline/plot 三前缀恢复最小宽 150→重排→量自然位置；仅当视口真正加宽（`scrollArea_13.viewport().width() - 796 > 200`，默认窗 extra≈23 恒落恢复分支，与字体无关）时设三前缀最小宽为「当前宽+位移」（d0=rd.x-ot.x，d1=rd.x-plot.x，d2=pr.x-opl.x-d1），把后继项精确钉到发行日期列；窄态恢复 150 原样不动。用当前宽而非 150 做基址：前缀 hint 随字体变化（如测试字体下 sorttitle hint 为 192），基址 150 会系统性欠 42px；当前宽基址与样式无关且天然幂等（单遍精确，无需重钉）。复选框加宽只延长点击区，视觉无变化；只碰前缀列宽，不碰 y 与其它行。
- 回归测试：`tests/test_window_state_matrix.py::test_nfo_title_plot_aligns_to_release_when_wide` 锁定「宽态三者严格对齐、前缀被加宽、二次同步幂等、窄态前缀恢复 150」。

### 设置页「命名」模板预览区按内容收缩（案例）

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
| 有新版本末行 | 🍉 | `有新版本了！（{latest}）` | `_show_version_thread` |

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
- **Cloudflare Bypass**：通过 `trawl_adapter.py` 把请求翻译给外部 CF 服务（TRAWL `/scrape` 或 FlareSolverr `/v1`），自动绕过 CF 防护页；JavLibrary 额外支持 Selenium+Edge headless fallback（`selenium_adapter.py`，cf_selenium_bypass 默认开启）
- **代理**：HTTP/HTTPS/SOCKS5，按"走代理网站"域名路由（默认含 amazon.co.jp, m.media-amazon.com, xcity.jp, minnano-av.com, avbase.net, javbus.com, javdb.com, javlibrary.com, r18.dev, mgstage.com, prestige-av.com, seesaawiki.jp, avsox.click, avsox.com, avmoo.shop, avmoo.com, avheat.shop, avheat.com, heyzo.com, caribbeancom.com, 1pondo.tv, pacopacomama.com, 10musume.com, mywife.cc, github.com, raw.githubusercontent.com, google.com, missav.ws, missav.ai, missav.live, aventertainments.com, javfree.me, 7mmtv.sx, 7tv022.com, avsex.cc, getchu.com, dl.getchu.com 共 37 域）

### TRAWL / FlareSolverr 适配层（mdcx/cf_bypass/trawl_adapter.py）

外部 CF 服务（TRAWL、FlareSolverr）与 mdcx 所需的 cf_bypasser 协议（`/cookies` `/html` `/mirror`）不兼容，适配层负责翻译：

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
- uvicorn（外部 CF 服务适配层）

## 测试

- **框架**：pytest + pytest-asyncio
- **标记**：`network`（需要联网的测试，默认跳过）、`integration`（集成测试，默认跳过）
- **运行**：
  ```bash
  uv run pytest tests/                          # 全部测试
  uv run pytest tests/ --tb=short -m "not network" -x  # 仅不联网测试
  ```
- **CI 平台分工**：Linux CI 执行 ruff、mypy、完整离线测试、数据库检查、线程安全检查和 UI 布局检查；Windows CI 在 `windows-latest` runner 上执行同一组离线 pytest，覆盖 Windows 路径和文件系统条件分支。Release 在 macOS、Windows 和 Ubuntu runner 分别构建 DMG、EXE 和 x86_64 Linux 单文件程序；手动工作流 `build-windows.yml` 与 `build-linux.yml` 可单独验证相应 PyInstaller 产物。
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

版本号有两处定义、四个同步点；任一处不一致都会被 `scripts/bump.py --check` 与 `tests/test_version_consistency.py` 判红。

**两处定义（`mdcx/consts.py`）**

- `LOCAL_VERSION`：纯数字 `YYYYMMDD`，用于版本比较、更新检查与构建；**GitHub release 的 Tag 必须是同值纯数字**（`check_version` 对 `tag_name` 做 `int()`，`vX.Y.Z` 形态的标签会被直接跳过）。
- `VERSION_NAME`：展示名 `vX.Y.Z`，界面/日志统一显示为 `VERSION_NAME (LOCAL_VERSION)`。

**四个同步点**

| 位置 | 值 |
|---|---|
| `mdcx/consts.py` 的 `LOCAL_VERSION` | `YYYYMMDD` |
| `mdcx/consts.py` 的 `VERSION_NAME` | `vX.Y.Z` |
| `pyproject.toml` 的 `version` | `X.Y.Z`（`VERSION_NAME` 去掉 `v`） |
| `docs/changelog.md` 首个版本段 `## vX.Y.Z (YYYY-MM-DD)` | 版本 = `VERSION_NAME`；日期 = `LOCAL_VERSION` 的日期 |

（`uv.lock` 里项目包 `mdcx` 的 `version` 也应与 `pyproject.toml` 一致，`uv sync` 会写回。）

**改版流程**

1. 在 `docs/changelog.md` 顶部新建目标版本段并写条目；已发版旧段保留，未发版段被后续议题取代时合并重写成最终形态。
2. `uv run bump --version <YYYYMMDD> --name X.Y.Z` 同步四处（`--dry-run` 预览、`--force` 免交互）；只校验用 `uv run bump --check`。
3. 复核 `uv run pytest tests/test_version_consistency.py tests/test_version_metadata.py`。
4. 打**纯数字** tag（= `LOCAL_VERSION`）触发 `release.yml`。「已发版」的判据是数字 tag 已推送，而非 changelog 有没有该段。

版本号归属维护者，不擅自开新段。`scripts/build.py` 与主窗口不留版本常量：build 从 `consts.py` 读 `LOCAL_VERSION`（`--version` 可覆盖），界面统一展示 `VERSION_NAME (LOCAL_VERSION)`。

## 构建

使用 PyInstaller 打包，入口文件为 `main.py`。正式 Release 会构建 macOS ARM64 DMG、Windows x86_64 EXE 与 Linux x86_64 单文件程序。

Linux 手动构建依赖 Ubuntu 的 Qt 图形运行库，完整列表见 [INSTALL.md](INSTALL.md#linux-额外步骤)。构建前安装锁定依赖，再执行：

```bash
uv sync --locked --all-extras --dev
uv run build --debug
```

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
