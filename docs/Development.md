# Development

MDCx 开发文档。记录架构、模块职责、口径与纪律。
排查过程与踩坑记录见 `docs/MEMORY.md`，版本变更记录见 `docs/Changelog.md`。

---

## 1. 项目结构

```
mdcx/
├── base/          # 基础能力：web 客户端、版本检查、通用工具
├── cmd/           # 命令行入口
├── config/        # Pydantic 配置模型
├── controllers/
│   └── main_window/   # 主窗口控制器（28 个 mixin + init/load_config）
├── core/          # 核心业务：刮削、命名、NFO、图片、翻译、马赛克、演员
├── crawlers/      # 爬虫（36 个站点）
├── gen/           # 生成物：枚举等
├── models/        # 数据模型
├── tools/         # 独立工具（Emby 演员管理）
├── ui_theme.py    # 主题与 QSS
├── utils/         # 工具函数
└── views/         # 视图组件
```

- `main_window.py` 只做类装配 + 49 个 `pyqtSignal`，业务逻辑全在 mixin 里。
- `tools/emby_actor_manager_ui.py` 已拆为 `emby_actor_clean_rules.py` / `emby_actor_source_catalog.py` / `emby_actor_ui_kit.py` / `emby_avatar_fetch.py`（依据 `docs/Decoupling-Review.md` 3.6）。
- 出厂模板在 `resources/userdata/`，运行时数据在 `manager.data_folder/userdata/`。

---

## 2. 架构

MVC 分层：UI → 控制器 → 核心业务 → 爬虫框架 → 基础设施。

数据流程：

```
文件扫描 → 番号识别 → 爬虫执行 → 数据整合 → 翻译 → 命名生成 → 资源下载 → NFO 生成 → 文件移动
```

数据模型链：`FileInfo → CrawlerInput → CrawlTask → CrawlerResult → CrawlersResult → ScrapeResult → ShowData`。

- 关键类在 `mdcx/models/model_types.py`，`CrawlerData` 在 `mdcx/crawlers/base/base_types.py`。
- `BaseCrawlerResult` 23 个字段；`CrawlersResult` 带字段来源追踪。

---

## 3. 核心模块

`core/scraper.py` 的 `Scraper` 统筹全流程，渐进式任务调度。

| 模块 | 职责 |
|---|---|
| `core/file_crawler.py` | 番号识别 + 多站并发 + 字段级优先级合并 |
| `core/naming/` | Jinja2 命名模板 |
| `core/nfo.py` | Emby/Jellyfin/Kodi 兼容 XML，30+ 字段（含 javdbid/javlibid） |
| `core/image.py` | 下载、多尺寸修复、9 宫格水印 |
| `core/translate.py` | 6 引擎（Google/Bing/Baidu/DeepL/DeepLX/LLM），字段级配置，多引擎降级 |
| `core/amazon.py` | 条码快路径 → 标题搜索 → 演员兜底 |
| `core/tmdb_actor.py` | TMDB 演员查询，令牌桶 3.5 req/s，Excel+内存双层缓存 |
| `core/face_crop.py` | OpenCV YuNet ONNX 人脸检测，裁 2:3 海报 |
| `core/mosaic.py` | `normalize_mosaic()` 归一为 有码/无码/无码破解/流出/无码流出/国产 |

### 3.1 分离模式开关口径

配置项：`separate_reuse_metadata`、`separate_overwrite_meta`（默认 False）。

- `extend.py::should_reuse_metadata(meta_root)` / `should_overwrite_meta(meta_root)`
  = `meta_root is not None and is_separate_mode() and 配置值`。
- 复用跳过条件额外含 `not overwrite_meta`（覆盖优先）。
- 界面互斥在 `settings_actions.py`：勾一个自动取消另一个；去勾选不动作。

### 3.2 分离模式 STRM

- `should_overwrite_strm()` = `is_separate_mode() and separate_generate_strm and separate_overwrite_strm`。
- `should_generate_strm(meta_root, skip_reorganize)` = 元数据根有效 + 非跳过整理 + 分离模式 + 已勾生成。
- 写入 `meta_folder`，内容为最终绝对路径：开移动写 `file_new_path`，不开写 `file_path`。
- `extend.py::normalize_strm_policy(generate, overwrite)` 是加载/保存的唯一口径。
- `migrations.py::_migrate_strm_overwrite_linkage()` 补旧配置；`SEPARATE_META_EXTS` 含 `.strm`。

### 3.3 命名系统

- Jinja2，24 个变量（number/title/actor/all_actor/studio/series/year/release…）。
- 文档与 issue 里的 `{number}` 是**排版简写**，实际模板必须写 `{{ number }}` / `{% if studio %}`；单双花括号不可互换（`{number}` 原样输出，`{%ifstudio%}` 报 unknown tag）。旧单花括号模板仅由 `migrations._migrate_builtin_naming_templates` 转写。
- `year` 刮不到留空，不写哨兵 0000；`score` 同理（`_deal_res` 把 0/0.0 归一为空）。

### 3.4 评分

- JavDB 系用共享 helper `extract_javdb_score()`：拼接文本 + 正则，兼容中文「分」、英文 points、整数分、`8.5, 120人`，无标记数字不抓。
- JavLibrary 先 strip 空白再去括号并校验数字，另用 review 块括号数字兜底。
- 非零评分追加来源站点后缀（`8.5(Javlibrary)`、`4.2(Javdb)`），站点取 `field_sources[SCORE]`，标签首字母大写（`javdb_api` → `Javdb_api`）。
- 数字消费统一走 `mdcx/utils.parse_score_number()`：NFO 只写数字、命名模板保留原文、相似推荐先去括号。

### 3.5 Amazon 图片

- 封面统一请求 `SL2560` 原图变体，输出官方下划线式 `https://m.media-amazon.com/images/I/{image_id}._SL2560_.jpg`。
- `_normalize_amazon_image_url` 处理四种输入：标准下划线式 `._AC_UL320_.jpg`、旧点号式 `.SL1500.jpg`、无后缀原图、已是目标尺寸。

### 3.6 Emby 演员工具

四模块单向依赖：`emby_shared.py` ← `emby_actor_manager.py` ← `emby_actor_image.py` / `emby_actor_info.py`。

- `emby_shared.py` 提供 `_generate_server_url` / `_build_jellyfin_headers` / `_is_jellyfin_server` / `_append_query` / `_upload_actor_photo`。
- manager 提供 `get_gfriends_index` / `_parse_graphis_html` / `fill_actor_info_from_sources`（local→wiki→minnano→db）/ `build_local_avatar_index` / `search_actor_info` / `from_graphis`。
- `Minnano-av.com` 品牌显示名首字母大写（6 处），代理域名一律全小写。

### 3.7 补全模式下方选项（2026-10-23 收敛后）

补全模式（`main_mode == 7`）本身只做两件事：**本地已有优先**（nfo 字段、nfo 文件、图片、字幕、mediainfo 先读本地）+ **只补缺失**（缺的字段联网补、缺的图下载、缺的字幕从字幕目录复制）。

2026-10-23 对下方五个迁移来的选项做过一次审计并收敛为两项 + 合并策略：

| 现状 | 说明 |
|---|---|
| ① 按更新模式重新整理分类 | **保留，仍有已知冲突**：`extend.is_update_rules_active()` 为真时，`file._get_folder_path` 的 A/B/C/D 分支把基准目录换成文件当前位置，**不再指向成功输出目录**；已在成功目录内的文件走原地分支，该选项对它们无效。用户明确要求保留，改动前先确认归档位置口径 |
| ② 重新下载封面图片等文件 | 保留。关掉 `web.keep_local_image()` 的保留语义，回到「设置→下载/保留」的下载口径。**复核结论：不存在「重下不打水印」缺陷**——下载函数每成功写出一张新图都会把 `*_marked` 复位为 False，`add_mark` 照常执行；被「保留目标文件」挡住没重下的旧图标记保持 True，正好避免二次水印 |
| ③ 允许更新 NFO 文件 | **已删除**。补全模式补到空字段即写回（`update_nfo` 在合并结果处定稿），不再需要单独开关；原先由它控制的两处读侧行为改为：标题/简介按「设置→翻译」的字段语言决定取原文还是译文，tag 剥离改为「非读取模式一律剥离」（读取模式只展示、不重建标签） |
| ④ 无 NFO 按正常模式重新刮削 | **已删除**。无 nfo 时本来就无条件回退正常模式，该开关全仓无消费点 |
| ⑤ 本地 NFO 合并及策略 | 保留，**收敛为 3 档**：全新数据优先 / 合并数组去重 / 仅填补空字段（默认）。`prefer_nfo`、`preserve_existing` 已删除（与 fill_missing_only 语义重合），旧配置自动映射到 `fill_missing_only`；`fill_missing_only` 的含义改为「本地已有值一律保留，只把本地空着的字段用刮削值补上」 |

配置升级见 `config/migrations.py::_migrate_read_mode_options` / `_migrate_nfo_merge_strategy`（每次加载都跑，幂等）。

---

## 4. 爬虫框架

- 基类 `GenericBaseCrawler[T]`（`crawlers/base/base.py`）。
- 生命周期六步：`_generate_search_url` → `_search` → `_parse_search_page` → `_detail` → `_parse_detail_page` → `post_process`。
- `CrawlerData` 25 个可选字段，默认 `NOT_SUPPORT`。
- `register_crawler()` 注册到 `crawler_registry`，站点下拉由注册表动态生成。
- **加新爬虫 6 步**：新建文件 → 继承基类 → 实现 `site`/`base_url_`/`new_context`/`_generate_search_url`/`_parse_search_page`/`_parse_detail_page` → 可选 `post_process` → `Website` 枚举加值 → `crawlers/__init__.py` 导入注册。
- `DomainRotator`（`utils/domain_rotate.py`）：镜像轮询，声明 `_domains` 类属性，已接 javbus(7)/freejavbt/xcity；`_init_rotator(domains, custom_url)` 支持自定义 URL 优先。
- `AioSiteCrawler`（`crawlers/aio_site.py`）：用于 Vue SPA + JSON API，重写 `_run`，`_generate_search_url`/`_parse_search_page` 抛 `NotImplementedError`；avmoo/avsox/avheat 共享该基类。
- `check_urls()` 返回检测 URL 列表；动态域名站覆写（avmoo/avheat/avsox 用 `get_aio_domain`，javlibrary 用 `get_javlibrary_domain`）。

---

## 5. 网络层

- httpx（默认）+ curl-cffi（指纹伪装）。
- 指纹池默认 7 种画像轮换：Chrome 124/131/136 Win、Chrome 136 Mac、Firefox 133/135 Win、Safari 17.2 iOS；Amazon 用纯桌面 6 种池（不含 Safari iOS）。
- 限流：并发数 + 全局线程延时；Amazon 另用 `AdaptiveRequestThrottle`（429 自动降速冷却）+ 指数退避。
- **CF Bypass** 走 `mdcx/cf_bypass/trawl_adapter.py`（TRAWL `/scrape` 或 FlareSolverr `/v1`）；JavLibrary 额外支持 Selenium+Edge（`selenium_adapter.py`）→ Playwright+Edge（`playwright_adapter.py`，async 原生，`channel="msedge"`，goto 失败 tenacity 重放 1 次）；`cf_selenium_bypass` 默认开启。内置 CF Bypass（cloakbrowser + cf_bypasser）已于 v2.0.6 移除。
- **代理路由**：按「走代理网站」域名，默认 37 域（amazon.co.jp、m.media-amazon.com、xcity.jp、minnano-av.com、avbase.net、javbus.com、javdb.com、javlibrary.com、r18.dev、mgstage.com、prestige-av.com、seesaawiki.jp、avsox.click、avsox.com、avmoo.shop、avmoo.com、avheat.shop、avheat.com、heyzo.com、caribbeancom.com、1pondo.tv、pacopacomama.com、10musume.com、mywife.cc、github.com、raw.githubusercontent.com、google.com、missav.ws、missav.live、aventertainments.com、javfree.me、7mmtv.sx、avsex.cc、getchu.com、dl.getchu.com）。
- **TRAWL/FlareSolverr 适配层**：对外暴露 cf_bypasser 三端点 `/cookies` `/html` `/mirror`；trawl 走原生 `/scrape`（响应无 `responseHeaders`/`body`，适配层走 html 回退）；flaresolverr 走 POST `/v1`（`cmd=request.get/post`），响应头从 `solution.headers` 还原；配置 `cf_bypass_trawl_url` + `cf_bypass_trawl_backend`（默认 trawl）；`AsyncWebClient` 自动拉起 `TrawlAdapterServer`（随机端口 + uvicorn 子进程）；回环 https 经 `normalize_trawl_url` 降回 http（否则 60s 探活失败永久禁用）；`is_proxy_host` 名单写主域时同站动态镜像自动跟随走代理，直连白名单优先。
- **动态域名**：`base/web.py::get_aio_domain(site)` 解析 `tellme.pw/{site}` 的 `__AIO_SITE_URLS__`，1 天缓存、三站互兜；`get_javlibrary_domain()` 抓 github.com/javlibcom 主页 `rel="nofollow me"` 链接，失败回退已知镜像。
- **网络检测**（`core/network_check.py`）：检测项由 `check_urls()` 动态生成；API 类爬虫走真实刮削探测 `_probe_crawler_by_run`；探针番号优先级 `NetworkCheckSpec.probe_number` > 爬虫 `probe_number` 类属性 > 全局 `SCRAPE_PROBE_NUMBER`（默认 SSNI-647）；Official 五个无码官网子检测项各带带站点前缀的实存番号（`official_uncensored.py::UNCENSORED_OFFICIAL_SITES`）；`_DETERMINISTIC_PROBE_MARKERS` 命中即首次定论，其余按 `SCRAPE_PROBE_ATTEMPT_TIMEOUTS`（30s→45s）递进重试；终局说明只在两档都真超时时写「均超时」，站点可达但番号不存在单独出提示不计故障；结果持久化到 `userdata/network_check_cache.json`（`merge_site_check_cache` / `load_site_check_cache`），同一站点多条结果只在本轮内取最差，五站子检测项另以 `Official·厂牌` 为键各存一份（`_SITE_CHECK_KEY_ROLE`）。

---

## 6. 缓存系统

- TMDB 双层缓存：Excel + 内存，限流 3.5 req/s、并发 3。
- Amazon ASIN 库 `amazon_asin_database.xlsx`：`save_asin_to_excel` 按番号去重、`query_asin_database` 查询、`update_asin_record` 原地更新 poster_url。
- 出厂库 `resources/userdata/amazon_asin_database.xlsx`（git 跟踪）+ 用户库 `userdata/amazon_asin_database.xlsx`，首启复制。
- `merge_asin_db_from_backup` 按番号合并：md5 标记跳过、只增不删、不覆盖用户已填值；新增行按番号整体重排。

---

## 7. 配置系统

- Pydantic `Config`（200+ 项）JSON，旧 INI 自动迁移。
- `ConfigManager` 单例管理加载/保存/热切换。
- `Computed` 派生对象随配置变更重建。
- 敏感字段导出脱敏为 `***`。
- `config_version` 永久固定为 2，三处必须一致：`migrations.py::CURRENT_CONFIG_VERSION`、`Config.config_version` 默认值、`resources/config/default_config.json`（`tests/test_config_conversion.py::test_config_version_frozen_at_two_everywhere` 钉死）。
- **`config_version` 不能当迁移判据**：`version >= 3` 恒假会导致每次启动重复迁移。结构性判据用 `_SEPARATE_MODE_KEYS`（`separate_success_file_move` / `separate_failed_file_move` / `separate_success_file_rename` / `separate_del_empty_folder`）。规律：判据和它的前提必须一起改。

---

## 8. 依赖

核心：PyQt6 6.11.0、httpx、curl-cffi>=0.15.0、lxml + parsel + beautifulsoup4、Pillow + opencv-contrib-python-headless、Jinja2、openpyxl、uvicorn。

**cp315 wheel 下限清单**（改依赖务必守住）：

```
aiohttp>=3.14.5      av>=19.0.2          lxml>=6.1.3
pillow>=13.0.0       numpy>=2.5.4        pyinstaller>=6.22.3,<7
aiofiles>=25.1.0     cffi>=2.1.1         jiter>=0.17.0
markupsafe>=3.0.4    pydantic-core>=2.50.1  PyQt6-sip>=13.13.0
```

- `requires-python` 固定 `>=3.15`（3.15 是当前唯一构建目标），不带 upper bound。
- 131 个锁包里 129 个有 wheel，唯一例外 pyyaml（无 cp315 wheel），靠 `PYYAML_FORCE_LIBYAML=0` 出纯 Python wheel。

---

## 9. 测试

- pytest + pytest-asyncio；标记 `network`（默认跳过）、`integration`（默认跳过）。
- 命令：`uv run pytest tests/`；离线子集 `uv run pytest tests/ --tb=short -m "not network" -x`。
- CI 分工：Linux 跑 ruff/mypy/完整离线测试/数据库检查/线程安全检查；Windows（`windows-2025`）跑同一组离线 pytest + PyInstaller 冒烟构建；Release 在 macOS/Windows/Ubuntu 分别构建 DMG/EXE/Linux 单文件。
- `ci.yaml` **只监听 `pull_request`（目标 main），不监听 push** → 直推 main 无 CI 门禁，改为两道：提交前 `uv run quick-check`，推送前 `uv run check --skip-hook-install`（守卫 `tests/test_ci_workflow_triggers.py`）。
- 主要测试文件：
  - `tests/test_ui_structure.py`：groupBox 不重叠、无负间距、objectName 唯一、`MDCx.py` 与 `.ui` 同步（pyuic6 重编译 + ruff format 后与仓库版逐字节比对）。
  - `tests/test_actor_clean.py`、`tests/test_check_actor_db.py`（jp 重复/tmdbid 重复/url 错配/孤儿 hyperlink）。
  - `tests/test_actor_db_button_consistency.py`：`_ACTOR_DB_IDLE_TEXT_MAP` ↔ `.ui` 控件 ↔ `MyMainWindow` 顶层 pyqtSignal ↔ `actor_db_finished` 四层一致。
  - `tests/test_window_state_matrix.py`：窗口状态矩阵、滚动条厚度、统计栏/NFO 各处对齐。
  - `tests/test_advanced_page_tail_align.py`、`tests/test_actor_manager_*.py`。
  - `tests/test_py315_release_workflow.py`（15 项）、`tests/test_workflow_action_pins.py`、`tests/test_sr_bundling.py`。
  - `tests/test_version_consistency.py`、`tests/test_version_metadata.py`、`tests/test_version_check_*.py`。
- `actor_db` 并发信号契约：`actor_db_finished = pyqtSignal(str)` 带 task_id；所有 `_run_actor_db_*` 走 `_run_actor_db_async(btn_attr, busy_text, log_prefix, coro_factory)` 模板，防重入靠 `_actor_db_running` 集合。
- `scripts/check_ui_layout.py` 只作手工诊断（warning 不阻断），结构约束锁在 `test_ui_structure.py`。

---

## 10. 代码规范

### 10.1 界面问题的取证与验证

1. 界面问题一律以「渲染出来的像素」为准，不以控件属性为准。量像素用 `widget.grab().toImage()`，必须从整窗合成图 `win.grab()` 取；属性全绿不构成「已修复」证据。
2. 量之前先断言目标真的显示了：`page_setting` 在 `stackedWidget` 下标 **4**（不是 2），`page_setting.isVisibleTo(win)` 不通过前任何测量都不算数；短窗口切 NFO 页（tabWidget 下标 8）会让进程崩，造溢出靠正常窗宽 + 逐页切换。
3. 「异常落在哪几个」会变 = 在和事件循环赛跑，不是病因。遇到随机性先假定竞态，把定时修复下沉到控件自身事件钩子，别挂 `QTimer.singleShot(0)`。
4. 改了几何不等于改了绘制。样式表驱动的子控件要重新 polish（`style().unpolish(w); style().polish(w)`），`update()+repaint()` 完全无效。
5. 「控件内部数据对」与「用户看到的对」是两类断言，测试各写一条。离屏 pytest 不绘制，`grab()` 拿到空后备存储，像素断言放宽为 None 或期望值。
6. 诊断脚本要自动驱动，不能依赖用户手工点。
7. 宣称「已修复」前先问「这个探针能不能判别出故障」。
8. 宣布失败要干脆。

### 10.2 高 DPI 字体取证顺序

1. 先量 `app.primaryScreen().devicePixelRatio()`（本项目 dpr=1.25，Windows 125%）。参考截图是设备像素：657×677 含 40px 原生标题栏 → 客户区 657×637 设备像素 = 524×509 逻辑像素。
2. QSS `font-size: Npx` 是逻辑像素会被 dpr 缩放；`QLabel.setFont()` 会被祖先样式表覆盖完全失效，字号只能靠 QSS 或富文本内联。
3. 别只看 `font().pixelSize()`，要量墨迹：`grab()` 取设备像素图，判 `min(R,G,B) <= 140` 求包围盒。`geometry()` 是逻辑像素、`grab()` 是设备像素，必须 × dpr 换算。
4. 区分「尺寸」（墨迹 bbox 宽高 / 每字 advance）与「墨迹密度」（墨迹像素数 ÷ bbox 面积）。
5. 同尺寸不同密度 = 字体回退 / 渲染路径差异（QPushButton 走 drawItemText + CJK 回退，density 0.409；QLabel 走 QTextDocument，density 0.364，差 12% → 同样高度但更淡）。
6. 别把富文本当嫌疑人，除非做过 A/B。
7. 颜色也改变视觉重量，要「一样大」时优先保证不小于（本项目最终取 16px）。
8. 离屏验证字体必须 `QT_QPA_PLATFORM=windows`（offscreen 下 `QFontDatabase.families()` 返回 0 个字体）。

### 10.3 离屏渲染校验流程

- monkeypatch 掉 `run_startup_health_checks` / `show_netstatus` / `check_version` / `save_remain_list` 等副作用。
- **不要 stub `set_style()`**，否则 QSS 不生效。
- `resources.qtr` 指向真实 resources 目录。
- 遍历目标尺寸区间逐档断言几何，把关键档位 `grab()` 存 PNG 肉眼复核。
- 断言落在不变量上，不要写死 y 值。

### 10.4 UI 同步军规八条

1. `setGeometry` 不触发 resizeEvent（须 `resize()`）。QStackedWidget 只 resize 当前页，`currentChanged` 要先 resize 所有 pages 再算内部几何。
2. 容器几何变化后 `invalidate()+activate()`。pyuic 生成的 QLayoutWidget 必须调在它 `.layout()` 返回的网格上，不能调在控件自身（调错会静默失效或让 pytest 进程 access violation）。
3. 一律用「设计基准坐标 + extra」固定公式，双向幂等，绝不增量累积。
4. 同步清单与设计器控件清单一一对账。
5. min 尺寸宽用 `layout.minimumSize()`、高用 `layout.sizeHint()`，禁取 childrenRect。
6. 底部余量按页属性，由 `set_content_bottom_margin()` 覆盖。
7. `.ui` 残留 maximumSize 会静默夹断自定义拉伸。
8. 改公式前 grep 公式变量名，同步既有断言。

补充约定：

- 主窗口 centralwidget 无布局、全部绝对定位。`resizeEvent` → `_sync_page_layouts`（`layout_master.py`）。设计基准宽 820，`cover_scale = 主页面宽 / 820`；两类锚定：右缘锚定、左缘对齐。
- 最大化用 `self.isMaximized()`；`changeEvent` 收到 WindowStateChange 后 `QTimer.singleShot(0, self._sync_page_layouts)` 补一次重排。
- 命名页是**有意例外**：非最大化也会随宽度上下平移。`groupBox_8` 高度 = 网格 sizeHint + `_NAMING_BOX_PAD`；预览框 `setFixedHeight(128)`；说明文字 `setFixedHeight(heightForWidth(width))` 前必须先解除上一轮固定高。
- `CustomScrollArea` 宽幅容器登记表存设计几何，`sync_wide_children_width()` 每遍按设计几何 setGeometry，**只改宽不改高**。
- 演员管理器硬规则：禁止 `setFixedHeight/setFixedSize` 锁大窗格；禁止在 resizeEvent/changeEvent 里 `setGeometry` 自身；禁止为还原/对齐留存几何快照。行数对齐只许纯内部手段（表行高 + `splitter.setSizes()`，余数进日志侧底部）。用户拖过分隔条后本次打开不再自动重排（`_user_moved_splitter`）；自有 setSizes 必须用 `_setting_splitter_sizes` 守卫包住（try/finally 复位）。
- 运行日志贴底：Qt 竖向滚动按整行换档，pageStep = (视口高-1) // 行距；末行贴底要两件事同做——压滚动上限 + 视口高吸附整行。量「内容底」用 Σ `blockBoundingRect(block).height()`；`contentOffset()` 与 `documentSize().height` 都不可用；`QScrollBar.maximum()` 单位不是像素。

### 10.5 改 UI 的标准流程

改 `.ui`（唯一权威源）→ `uv run python -m PyQt6.uic.pyuic`（相对路径）→ `scripts/fix_qt_enums.py` → `ruff format` → `tests/test_ui_structure.py`。禁止手工改 `MDCx.py`。

### 10.6 质量门禁

- ruff 行宽 120（isort/pyupgrade/flake8）。
- mypy 全项目零 `disable_error_code`。`mdcx/controllers/main_window/` 下 28 个 `*Mixin` + `init.py` + `load_config.py` + `views/` + `gen/` 用 `pyproject.toml` 的 `[[tool.mypy.overrides]] module=[...] ignore_errors=true` 豁免（**不是 exclude**，mypy 对被 import 的模块不认 exclude），CI 强制执行。pyright 只在 pyproject 保留配置，不入 CI。
- Git 钩子：仓库自带 `.githooks/`（`pre-push` 快速门禁 + `prepare-commit-msg` 自动追加 co-author 署名），一次性启用 `git config core.hooksPath .githooks`。
  - **Windows 四坑**：①Git Bash 里没有 `python3` 只有 `python.exe`，钩子做 `uv` → `python3` → `python` 三级探测；②`.githooks/*` 在 `.gitattributes` 钉 `text eol=lf`（否则 core.autocrlf=true 让 sh 钩子静默失效）；③两钩子入库模式必须 100755（100644 时 Linux/macOS 静默跳过、Windows 反而照跑掩盖问题）；④Windows 上 pip 常把 exe 装进 `%APPDATA%\Python\Python315\Scripts`（不在 PATH），`check.py` / `quick_check.py` 用 `resolve_tool()` 兜底退回「当前解释器 `-m ruff` / `-m mypy`」。
  - 不要求 pre-commit（`.pre-commit-config.yaml` 是历史遗留）。

### 10.7 变更日志纪律

> **铁律（2026-10-23 用户定规）**：**界面改动默认不写 `docs/Changelog.md`**。只有需求里明确出现
> 「写进 changelog / 记一条变更日志 / 更新变更日志」这类字样时才写；没写明就一律不占 Changelog 行，
> 哪怕改动量很大、截图对比很显眼。判定口径见下表。

**只记功能逻辑的变更。** 判定标准只有一条：改完之后用户可观察到的行为是否变化。行为没变就是纯界面，不写。

| 类别 | 是否写入 | 例子 |
|---|---|---|
| 纯界面 | 不写 | 按钮平移若干像素、间距调整、setGeometry 常量微调、QSS 配色/字号/圆角、图标替换、控件 z 序、提示词措辞、控件 id/类名整理 |
| 界面 + 行为 | 写 | 增删/隐藏控件改变可达路径、改点击后的默认值或分支、新布局导致窄窗不可用、顺带加了状态记忆 |
| 纯功能 | 写 | 抓取/翻译/命名/图片/网络/配置字段/依赖等任何逻辑或行为变更 |

配套规则：

- 纯界面改动仍要按 10.1 取证并留回归测试，只是**不写 Changelog**（用户 2026-10-23 定规）。
- 拿不准是「纯界面」还是「界面 + 行为」时，按「用户能不能察觉到行为变化」判断；只是控件换了位置/间距/措辞，一律算纯界面。
- 顺带改到功能语义时按功能条目写。
- 同一日期段已有功能条目提到该界面区域时并进那条。
- 历史段不动，本纪律只对新增条目生效。
- Changelog 每条只写「做了什么 / 改了什么 / 修了什么」，不写原因与排查过程；原因与过程写进本文件与 `docs/MEMORY.md`。

### 10.8 站点收录边界

改 `TYPE_DEFAULT_SITES` 七组默认名单前先问「这站在这一类番号上真的有条目吗」：

- `AVEntertainments` 只无码番号（正規無修正 DVD 販売/配信商城）→ 只在无码组。
- `Getchu`、`AVSEX` 对大陆 IP 过不了 CF 墙 → 前六组不收（Getchu 只随动漫里番一组）。
- `Official` 按番号前缀路由到片商官网，国产/欧美/个摄没有收录 → 只在有码/无码两组。
- `MyWife` 不属于任何类型 → 七组都不该有。
- 移除站点只动默认名单，不动爬虫注册与 `Website` 枚举。

### 10.9 界面文案纪律

菜单项/提示词/状态提示/日志提示一律**不写空格、不写括号**（`（）` 与 `()` 都不行）。

**日志与所有界面文字：不留多余空格，行首图标后保留一个空格**（用户 2026-10-28 定规）。日志出口统一经 `mdcx/utils/__init__.py::strip_log_spaces()` 洗一遍：`LogConsole.log_text()`、`LogConsole.add_log()`、`Signals.show_log_text()`、`LogPageMixin.show_log_text()` 以及 `add_html()` / `add_html_plain_text()` 都会删掉行内多余空格，但保留 `\n`、HTML 标签内部语法（如 `<font color="red">`）以及每行行首图标后的一个空格（如 `🔐 授权状态：`）；新写的日志与界面文案也不要主动加多余空格。

- 正例：`复制本组：29个站点`、`复制列表：44个站点`、`已启用：12个站点`。
- 反例：`复制本组：29 个站点`、`复制本组「有码」（29个站点）`、`已启用（12 个站点）`。
- 数字与「个/次/条/项」之间不留空格，需要停顿用冒号或顿号。
- 界面文案没有 lint 守，靠测试按字面逐字比对（如 `tests/test_site_source_copy_menu.py`）。
- 本纪律属纯界面措辞，不单独占 Changelog 一行；但版本段里已有条目若引用这些文案要一并更新。

### 10.10 提交与推送纪律

**默认不碰 git。** 只有需求里明确出现「提交」「推送」「commit」「push」「提交到 GitHub」「推到远程」这类字样时，才允许动 git；「改完了」「修好了」「继续」「优化一下」都不构成授权。

- 授权只对当次需求有效，不跨需求延续。下一轮需求默认重新回到「只改工作区、不动 git」。
- 未获授权时交付口径是「文件已改好 + 未提交」，不 `git add`、不 `git commit`、不 `git push`，也不擅自建分支。
- 说「提交」= 只 `git commit`；说「推送」「推到 GitHub」「推远程」才 `git push`。两件事不合并推断。
- 理由：本仓库直推 `main` 不触发 CI（见 10.6），误提交会直接进主干历史；事后回滚要 `git revert` 甚至 `reset`，恢复成本远高于少提交一次。
- 获授权后的动作仍守 10.6 门禁与 `docs/MEMORY.md` 的「检查与提交纪律」：`git add -- <具体文件>`、提交前看 `git status` 查残留、按需 `uv run quick-check` / `uv run check --skip-hook-install`。
- **提交优先用 GitHub Desktop**（用户 2026-10-27 定规）：人工提交、推送默认走 GitHub Desktop；批量或脚本化时才用命令行 `git`。
- **提交 / 推送一律尽量走代理**（用户 2026-10-27 定规）：无论用 GitHub Desktop 还是命令行工具，操作前先确认代理已开。命令行直连失败时用一次性代理参数（本机系统代理 `127.0.0.1:7897`，端口按实际替换）：`git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main`；报网络错先用 `git ls-remote origin main` 对 SHA，确认没推上去再重试。

### 10.11 大模型输出纪律

用户 2026-10-27 定规：每次与大模型对话默认**只返回修改后的片段**，不重复输出未改动的全文，尽量节省 token。

- 只贴发生变化的函数、类、配置段或文档段落，并注明文件路径与定位（函数名、小节名或行号）。
- 新建文件、用户明确要求全文、或只给片段会产生歧义时，才输出全文。
- 说明优先写「改了什么、为什么、怎么验证」，不复述整份文件。
- 需要用户确认时只引用关键几行，不把整份文件再贴一遍。

### 10.12 共用逻辑必须单独成文件或函数

用户 2026-10-27 定规：**共用的功能/方法一律抽成独立的文件或函数**，不允许复制粘贴出第二份。

- 同一段逻辑出现在两处（或明确预见会出现第二处）时，抽成独立函数；跨模块复用或体量较大时抽成独立文件（如 `core/file_association.py`、`tools/emby_actor_ui_kit.py`、`tools/emby_actor_source_catalog.py`）。
- 判定为「共用」的典型信号：同一份常量表/映射在读两遍、同一套校验或格式化写两遍、两个窗口各写一份同样的控件/线程收尾、同一段网络或文件操作复制到第二个入口。
- 抽出的位置按「谁最稳定放谁那里」：纯数据与规则放模型/规则模块，跨 UI 的控件放 `*_ui_kit.py`，跨模式的文件操作放 `core/`。
- 原位置的旧引用保留薄封装转调新实现，避免同一规则出现两个版本；改共用实现前先 `grep` 全部调用点。
- 共用函数要有名字讲清语义、写明 docstring（约束/口径/失败行为），并被至少一个回归测试直接覆盖。
- 新增需求时先找现成实现，再决定「调用」还是「抽取」；不要为了省事在调用处再写一遍。

---

## 11. 左下角状态区图标规范

实现文件：`mdcx/controllers/main_window/layout_actor.py`。

| 场景 | 图标 | 文案 |
|---|---|---|
| 单文件模式首行 | 💡 | `单文件刮削` |
| 刮削模式行 | 💠 | `{main_mode} · {站点/字段}` |
| 单站刮削首行 | 💡 | `{website_single} 刮削` |
| 软/硬链接行 | 🍯 | — |
| 配置文件行 | 🛠 | — |
| 版本行 | 🐰 | `MDCx {localversion}` |
| 默认末行 | 🔍 | `点击检查最新版本` |
| 有新版本末行 | 🍉 | `有新版本了！<font color="red">{latest}</font>` |

五条硬规则：

1. `before_info` 只 `strip()`，不得过滤 emoji（已删的 `SCRAPE_INFO_EMOJI_RE` 不得复活）。
2. 仓库地址不硬编码，全部由 `consts.py::GITHUB_REPO`（`z291173301/MDCx`）派生。改 UI 先改 `.ui` 再 pyuic + ruff format。
3. 每行必须图标+文字同时存在，不允许 `💠 ·` 这样的光杆。`Flags.reset()` 不得清空 `main_mode_text` / `scrape_like_text`，但必须清空 `mode_text_override`（单次运行态）。
4. 改规范须同步 `tests/test_left_status_icons.py` 的 `_REQUIRED_ICON_LITERALS`。
5. `mdcx/utils/path.py::is_descendant()` 必须用 realpath 默认 `strict=False` 语义 + 词法基准（abspath + normcase）兜底；跨盘符 `commonpath` 抛 ValueError 按「不是后代」处理（否则网盘上整理模式认不出「已在成功输出目录内」）。

---

## 12. 信息管理筛选框匹配规则

文件：`nfo_library.py`。关键函数：`lineEdit_nfo_lib_filter_changed` / `_split_keyword` / `_token_variants` / `_nfo_matches` / `_parse_nfo_search_text` / `_nfo_lib_search_text`。回归：`tests/test_nfo_library_filter_fields.py`（14 项）。

1. **拆词**：按逗号/顿号/分号/空白/斜杠切分；全角标点先归一（`_FULLWIDTH_MAP`）再拆。`_DATE_PIECE_RE` 先把日期片段整体抠出，`/` 不切断日期；空段丢弃。多词 AND，顺序无关。
2. **文件名快路径**：列表项文本只有番号（stem），任一候选子串命中即显示（`261` 能定位 `ARM-261`）。
3. **NFO 慢路径按词形分流**：
   - 日期形词：`_token_variants()` 展开 [原串, YYYY-MM-DD, YY-MM-DD]，与发行日集（release/releasedate/premiered）**精确比对**。
   - 纯数字词（`_NUMERIC_TOKEN_RE`）：只与数字集（year/runtime/rating，criticrating 换算回 10 分制）**精确相等**。
   - 其他文字词：在文本池 `_NFO_TEXT_XPATHS`（演员名/标签值 + title/originaltitle/director/studio/maker/publisher/label/plot/outline/originalplot）内**子串匹配**。
4. `series` 不在文本池（经「系列：xxx」标签命中）；`criticrating` 只进数字集不进文本。增删可搜字段只改三个 XPATHS 常量。
5. 占位符必须与实际能力一致：`筛选：番号/标题/演员/导演/片商/发行商/简介/标签/发行日/年份/时长/评分（逗号分隔）...`。改 `.ui` 后必须 pyuic 重生成 + ruff format。

三条禁令：

- 数字与日期永远精确比对，禁止用 startswith / 子串去碰数字集与发行日集。
- `_DATE_PIECE_RE` 的分隔符不含空白。
- 文字池如再被要求收窄，必须同步改占位符，并把旧用例改名 `*_not_searched` 反向锁定。

---

## 13. 版本号管理

> **铁律（2026-10-23 用户定规，取代 2026-10-19 的「LOCAL_VERSION 领先当天是既定口径、不许顺手改」）**：
> 只要改了软件代码，`mdcx/consts.py::LOCAL_VERSION` 就必须同步成**当天日期** `YYYYMMDD`。
> 例：代码里是 `20261022`、当天是 2026-10-23，就改成 `20261023`；跨天多次改动按最后一次的日期。
> 改完再按 §13.2 复核四个同步点、§13.3 复核测试。**不需要用户每次提醒，改代码即自动同步。**

### 13.1 两处定义

`mdcx/consts.py`：

- `LOCAL_VERSION`：纯数字 `YYYYMMDD`（GitHub release tag 必须同值纯数字，`check_version` 对 `tag_name` 做 `int()`）。
- `VERSION_NAME`：展示名 `vX.Y[.Z]`，v3.0 起固定 `v3.0`，不再随发布递增。界面/日志显示 `VERSION_NAME (LOCAL_VERSION)`，更新检查时也作为版本号维度参与比较。

### 13.2 四个同步点

1. `consts.py::LOCAL_VERSION`
2. `consts.py::VERSION_NAME`
3. `pyproject.toml` 的 `version`（去 v 前缀）
4. `uv.lock` 根包 `mdcx` 的 `version`（CI `uv sync --locked` 强校验）

`docs/Changelog.md` 自 v3.0 起按**日期**分段（`## YYYY-MM-DD`），不再是版本号同步点，只与 LOCAL_VERSION 对**日期**（必须有与当天同日期的段）。

> 事故记录（2026-09-27）：只升 pyproject 漏同步 uv.lock，四个构建腿齐刷刷在 Install locked dependencies exit 1。

### 13.3 改版流程

0. 改完代码先把 `LOCAL_VERSION` 同步成**当天日期**（见本章开头的铁律），再往下走。
1. 在 Changelog 顶部按日期写条目（当天没段就新建，有段就并进）。
2. `uv run bump --version <YYYYMMDD>`（`--dry-run` 预览、`--force` 免交互；只有真要改展示版本号才加 `--name X.Y[.Z]`）。
3. 复核 `uv run pytest tests/test_version_consistency.py tests/test_version_metadata.py`。
4. 打纯数字 tag 触发 `build-py315.yml`。

「已发版」判据 = 数字 tag 已推送。版本号归属维护者，不擅自开新段。`scripts/build.py` 与主窗口不留版本常量。

### 13.4 更新检查六条不变量

代码：`mdcx/base/web.py::check_version()` / `is_remote_version_newer()`，主窗口 `window_ops.py::_show_version_thread()`。

1. 取 tag 最大的 release：遍历全部条目收集 `tag_name.isdigit()` 取 `max`（`/releases?per_page=10` 按 created_at 倒序不按 tag 倒序，补发会顶到第一位）。
2. 版本号优先，版本号相等才比日期；任一侧解析不出退回只比日期。刻意不做字面 OR（会提示降级）。
3. 源码版本号高于线上时不提示（`LOCAL_VERSION` 常先于线上 release bump）。
4. API 失败必须回退 `GITHUB_RELEASES_ATOM`（`github.com/releases.atom`；匿名 api.github.com 配额 60 次/小时/出口 IP 共享）。atom 侧用 `parse_release_atom()` 同样取最大 tag，标题过 `html.unescape()`。
5. 结果落 6 小时本地缓存 `userdata/version_check_cache.json`（`_VERSION_CACHE_TTL = 6*3600`，tmp + `os.replace` 原子写，路径走 `resources.u()`）。新鲜命中不发请求；网络失败回退任意年龄缓存；缓存损坏静默降级为纯联网。`_read_version_cache(max_age)` 刻意不给默认参数（避免 def 时绑死 TTL），写测试必须把 `_version_cache_path` monkeypatch 到 `tmp_path`。
6. 12h `timer_update` 改连 `self.show_version` 走完整提示链，`_notified_new_version` 做 transition 去重；提示副作用（红字日志、下载链接、标签刷新）必须整体进 gate。

返回类型是 `RemoteVersion(tag, name)` NamedTuple（带 `display` 属性），测试桩有 12 处 `lambda: None`。

---

## 14. 构建与发布

### 14.1 本地构建

PyInstaller，入口 `main.py`。Linux 手动构建依赖见 `Install.md#linux-额外步骤`。
`uv sync --locked --all-extras --dev` → `uv run build --debug`。

### 14.2 唯一发版工作流

`.github/workflows/build-py315.yml`（Build and Release Python3.15），三平台矩阵：macOS ARM64 / Windows x86_64 / Linux x86_64。

- tag 为纯数字 `LOCAL_VERSION`。
- **发布目标只有公开仓库**：默认 `z291173301/MDCx`，可用仓库变量 `MDCX_PUBLIC_REPO` 覆盖；目标分支默认 `main`，可用 `MDCX_PUBLIC_BRANCH` 覆盖。私有开发仓 `MDCx-Dev` **不创建 Release**，本仓库 `GITHUB_TOKEN` 只有 `contents: read`。
- 跨仓库写用 Secrets 里的 `MDCX_SYNC_TOKEN`（公开仓库 Contents: Read and write）。未配置时发布步骤直接报错，不会退回私有仓库。
- 资产名 `MDCx-<tag>-<平台>-<架构>-<40位sha>.<ext>`（2026-10-22 起去掉展示版本号段；客户端只读 `tag_name` 不解析资产名，故零影响）。资产名同时写在本文档与 `tests/test_py315_release_workflow.py::_EXPECTED_ASSETS`，**三处同改**。
- Release 标题 `MDCx <日期版本号>`，日期取自源码 `consts.py::LOCAL_VERSION`；补发旧 tag 时按 tag 取日期并告警。由 `test_asset_names_and_release_title` 与 `test_release_title_date_comes_from_source_code` 钉住。
- **重名先删后建**：公开仓库已有同 tag 或同标题的 Release 时，先 `gh release delete <tag> --cleanup-tag`，再 `gh release create`；旧 tag 没有 Release 时也要清掉残留 tag。删除发生在三平台产物核对、正文截断、资产重命名之后，构建失败不会先删线上版本。
- 2026-10-20 起 macOS Intel 腿退役（macos-15-intel / x86_64）：**矩阵项、产物核对项、资产重命名项三处必须同删**。只删矩阵项会因核对项永远缺 `dist/MDCx-x86_64.dmg` 而 exit 1 卡死全平台。守卫 `test_macos_intel_leg_is_gone`。
- 触发方式：push tag `2*`（如 20260928）自动发正式版，prerelease 一律 false；`workflow_dispatch` 手动补发（tag 留空取 `consts.py::LOCAL_VERSION`，prerelease 由输入决定）。
- 2026-09-28 删除 `build-py313.yml` / `build-windows.yml` / `build-linux.yml`，2026-10-21 删除 `build-py314.yml`，2026-10-27 删除 `mirror-release.yml` → **发版路径自始至终只有一条**。

### 14.3 Python 3.15 专属

- `python-version: 3.15`、`UV_PYTHON: 3.15`、构建前断言 `sys.version_info[:2] == (3, 15)`。
- `uv sync --locked` 失败自动回退 `uv sync`（只改 CI 临时工作树）。
- PyYAML 无 cp315 wheel → 设 `PYYAML_FORCE_LIBYAML: "0"` 从 sdist 出纯 Python wheel（`uv sync` 与 `pip install -r requirements.txt` 都认；本机同理 `setx PYYAML_FORCE_LIBYAML 0`）。工作流另设 `UV_NO_SYNC: "1"`。

### 14.4 五条护栏

1. **缺产物不发版**：`build-app` 带 continue-on-error，`publish-release` 用 `if: !cancelled() && needs.build-app.result == 'success'`，不能写 `success()`；发布前再核对三平台产物非空。
2. **并发不互杀**：`concurrency` 按 ref 分组 + `cancel-in-progress: false`。
3. **重跑幂等**：公开仓库同 tag 或同标题的旧 Release 先删再建；残留 tag 一并清理。
4. **Release 正文按文件写**：`Extract current changelog` 落 `release-notes.md`，截断后写 `release-body.md`，用 `gh release create --notes-file` 一次写入；不再使用会覆盖正文的 `svenstaro/upload-release-action`。
5. **正文长度上限**：125,000 字符，超了 API 422。写入前按行截到 120,000 并注明「完整内容见 docs/Changelog.md 的 ## <日期> 段」，截断用 `python3`（找不到则跳过并告警）。

### 14.5 文档同步

`.github/workflows/sync-docs.yml` 把私有仓 `docs/*.md` 的改动同步到公开仓库（默认 `z291173301/MDCx`，变量 `MDCX_PUBLIC_REPO` / `MDCX_PUBLIC_BRANCH` 可覆盖）。

- push 到 `main` 且命中 `docs/*.md` / `docs/**/*.md`（含大写 `.MD`）时，按 `github.event.before..github.sha` 的 diff 只处理本次改动/新增/删除的文件；未改动的文档不覆盖公开仓。
- 手动 `workflow_dispatch`、首次推送或 force push 找不到父提交时，才全量同步 `docs` 下的 md。
- 目标文件内容已一致时不产生空提交；源文件删除时同步删除公开仓对应文件。
- 需要 Secrets 里的 `MDCX_SYNC_TOKEN`（公开仓 Contents: Read and write）；未配置直接失败，避免“以为同步了其实没同步”。

---

## 15. 迁移指南

- 旧函数式爬虫 → `GenericBaseCrawler`（5 步）。
- PyQt5 → PyQt6：枚举用 Enum 风格，`QRegExp` → `QRegularExpression`。
- 配置 v1 INI → v2 JSON，由 `migrations.py` 自动转换。

---

## 16. 支持的命令行

| 命令 | 用途 |
|---|---|
| `uv run crawl` | 爬虫调试 |
| `uv run gen_enums` | 生成枚举 |
| `uv run build` | 打包 |
| `uv run bump` | 版本号管理 |
| `uv run changelog` | 生成变更日志 |

---

## 17. 大图预览窗口任务栏与窗口状态

v2.2.1 起。

- `NfoPreviewWindow` 必须 `super().__init__(None)`；对主窗口只保留只读引用，绝不 `setParent` 挂回。
- 图标用 `resources.icon_ico`（延迟导入防循环）。
- 独立 AppUserModelID 固定 `MDCx.NfoPreview`，首次显示前设置。
- **ctypes 三铁律**（都出过访问违例）：`windll` 函数显式声明签名；COM 接口指针先解一层再取虚表函数；`GetValue` 的指针用 `CoTaskMemFree`（同样先声明签名）。
- `showEvent` 读回校验，AppUserModelID 丢了就补 `_ensure_taskbar_app_id`。
- **还原后严丝合缝盖住主窗口**：`changeEvent` 只认「从最小化出来」（最大化状态从 `event.oldState()` 取）；还原时最大化恢复最大化，普通态 `showNormal + setGeometry(主窗口几何)`；最大化盖普通不动、不抢焦点；主窗口还在最小化则挂起 `_cover_pending` 由 eventFilter 执行；`show_matching` 全程 `_placing`（try/finally）；最大化前先钉还原矩形到启动尺寸并泵一次事件。
- **关闭语义**：预览 `WA_QuitOnClose=False`；主窗口 `closeEvent` 收起分支连带 `close()` 预览。再报「关预览退进程」先查构建落点再查事件查看器异常代码，不要直接动代码。
