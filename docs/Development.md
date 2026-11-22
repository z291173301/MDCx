# Development

MDCx 开发文档。记录架构、模块职责、口径与纪律；第 18 章为 2026-11-15/16 的专题调研与实现笔记（由原根目录 `development.md` 合并而来）。

> **阅读口径**：本章只记架构、模块职责与规范口径；长期规则集中在 `docs/MEMORY.md`，版本变更在 `docs/Changelog.md`，2026-11-15/16 专题调研笔记在第 18 章。章节编号被代码与测试注释引用，整理时保持不变。
排查过程与踩坑记录见 `docs/MEMORY.md`，版本变更记录见 `docs/Changelog.md`。

**章节索引**：1 项目结构 / 2 架构 / 3 核心模块 / 4 爬虫框架 / 5 网络层 / 6 缓存 / 7 配置 / 8 依赖 / 9 测试 /
10 代码规范（10.1–10.12） / 11 状态区图标 / 12 筛选框 / 13 版本号 / 14 构建发布 / 15 迁移 / 16 命令行 /
17 大图预览 / 18 专题调研笔记。编号被代码与测试注释引用，保持不变。

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
├── crawlers/      # 爬虫（37 个站点）
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

**番号格式纪律：FC2/个摄番号必须兼容 `FC2-` 与 `FC2-PPV-` 两种写法（2026-11-15 用户定规，细则见 `docs/MEMORY.md` 通用纪律）。** 归一公共件是 `utils/shared_fields.py::fc2_digits`（fc2/fc2cmadb 同源）与 `javdb_number_key`（FC2PPV 折叠成 FC2）；涉及 FC2/个摄的爬虫（fc2、fc2cmadb、javfree、7mmtv、missav、javbus、javdb/javdb_app、iqqtv、javlibrary 等）输入侧双写都要识别，输出统一标准短形 `FC2-{digits}`；站侧只认 PPV 形的（javfree 搜索、7mmtv 标题、missav 详情 slug `fc2-ppv-*`）在生成关键词/URL 时自行映射。

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
- 非零评分追加来源站点后缀（`8.5(Javlibrary)`、`4.2(Javdb)`），站点取 `field_sources[SCORE]`，标签首字母大写（`javdb` → `Javdb`）。
- 数字消费统一走 `mdcx/utils.parse_score_number()`：NFO 只写数字、命名模板保留原文、相似推荐先去括号。

### 3.5 Amazon 图片

- 封面统一请求 `SL2560` 原图变体，输出官方下划线式 `https://m.media-amazon.com/images/I/{image_id}._SL2560_.jpg`。
- `_normalize_amazon_image_url` 处理四种输入：标准下划线式 `._AC_UL320_.jpg`、旧点号式 `.SL1500.jpg`、无后缀原图、已是目标尺寸。
- **适用范围（2026-11-20 用户定规）**：日亚成人影像只收录日本有码 DVD 及其官网商品，其它类型番号实测只得到 MP3 下载/无结果，条码扫描 → 标题搜索 → 演员兜底整条链路纯属浪费。故 `core/web.py::amazon_images_allowed()` 成为唯一入口守卫，只放行 `YOUMA` / `OFFICIAL`；`_get_big_poster()` 用它决定是否调用 `get_big_pic_by_amazon()`，Thumb/Poster 候选在 `_build_poster_candidates()` / `_order_*_candidates()` 中剔除 Amazon 档（group 0）后再进入尺寸探测与下载，避免仍向 `media-amazon.com` 发请求。
- 自动判断的兜底分支（`classify_scrape_task` 末尾）把无特征前缀番号一律归为有码，欧美站点（如 ThepornDB_JSON）兜底拿到的结果因此仍带 `YOUMA` 类型。`_result_looks_like_other_type()`（日亚 / DMM 两条门禁共用）用两条信号复核：纯无码/国产马赛克，以及 number/title/originaltitle/thumb/poster 主字段来源是否落在「其它类型专属站点」集合（`TYPE_DEFAULT_SITES` 其它组站点减去有码/官网组，跨组共用的 JavDB / DMM 等不在其中）。日亚另排除里番/动漫/同人/书籍马赛克；流出/破解按有码母带口径保留日亚搜索。DMM 侧允许类型与过滤入口见「有码番号图片下载架构」章节。
- 直调 `amazon.get_big_pic_by_amazon()` 的离线测试不受守卫影响（守卫在下载层入口，不在爬虫模块内）。

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

### 3.8 NFO 写入保真（2026-11-12 用户定规）

**NFO 写入值保持从站点刮削到的原值，不做修改不做替换。** 写出路径只做 XML 编码必需的两步：`utils/xml.py::escape_xml_text()`（实体幂等化 + XML 转义）与 `build_cdata()`（实体幂等化 + `]]>` 转义）；两者对同一份原值给出同一结果，读回来再写不会把 `&amp;` 越叠越长。

- 已移除的改值点：`normalize_xml_text()` / `REP_WORD` / `XML_TEXT_FIELDS` 整体删除——它会删掉全角空格 `\u3000`、不换行空格 `\xa0`、盲文空位 `\u2800` 与 `<br/>`，并把 `・`→`·`、`“”`→`「」`、`...`→`…`；`core/nfo.py` 写入前 8 个字段的调用、`core/file_crawler.py::_deal_res()` 刮削后的同款清洗一并去掉；`<runtime>` 不再 `replace(" ", "")`。
- 上游替换表只去「美观类」（2026-11-12 用户口径）：`manual.py::ALL_REP_WORD` 删掉 `・`→`·`、`“”‘’`→`「」`、`...`/`……`→`…`、`’s`→`'s`、`! `→`！`、全角字母/数字→半角、`\t`→空格；`TITLE_REP`（标题上下集/蓝光版标记剥离）整表删除，`core/utils.py::replace_word()` 不再剥标题。**保留**：HTML 实体解码（`&lt;`→`<`、`&hellip;`→`…` 等）、`&`→`＆` / `<`→`＜` / `>`→`＞`（防 Emby 读 NFO 误判）、`<br/>` 网页残留清理、`SPECIAL_WORD` 反和谐与半角片假名还原（`強●`→`強制`、`ﾒｲﾄﾞ`→`メイド`）、字段语言选简体时的 `CHINESE_REP_WORD` 用字归一。
- 匹配键不在保真范围内：`utils.convert_half()`、`config/resources.py::_normalize_info_key()`、番号归一、标题匹配、搜索 query 里的全角转半角与去空格都是比较键，照旧。
- 保留的两类不算改值：① **解码**——`normalize_linebreaks()` 只把爬虫转义过的 `\r\n` / 字面 `\n` / `<br>` 还原成真实换行；② **既有功能**——标题命名模板、`originaltitle`/`sorttitle` 的番号前缀与 CD 后缀、tag 模板（`系列: series`）、`outline_format` 的原文拼接与「由 X 提供翻译」、`OUTLINE_NO_CDATA` 单行化、评分量纲（`parse_score_number`）、日期归一、`N/A` 导演过滤、占位简介清理，都按配置生效。
- 字段值也不在爬虫里单独删空格（`mgstage` / `prestige` 演员名，2026-11-12）。
- 回归：`tests/test_nfo_write_escape.py::test_write_nfo_keeps_scraped_values_verbatim`、`tests/test_file_crawler_runtime.py::test_deal_res_keeps_scraped_text_verbatim`、`tests/test_field_value_fidelity.py`（美观类不再替换 / 解码与 Emby 兼容保留 / 反和谐保留）。

---

## 4. 爬虫框架

- 基类 `GenericBaseCrawler[T]`（`crawlers/base/base.py`）。
- 生命周期六步：`_generate_search_url` → `_search` → `_parse_search_page` → `_detail` → `_parse_detail_page` → `post_process`。
- `CrawlerData` 25 个可选字段，默认 `NOT_SUPPORT`。
- `register_crawler()` 注册到 `crawler_registry`，站点下拉由注册表动态生成。
- **加新爬虫 6 步**：新建文件 → 继承基类 → 实现 `site`/`base_url_`/`new_context`/`_generate_search_url`/`_parse_search_page`/`_parse_detail_page` → 可选 `post_process` → `Website` 枚举加值 → `crawlers/__init__.py` 导入注册。
- 下拉能力文案短词规则（严格执行）：当前网站/指定网站下拉能力文案用短词（有码番号→有码、无码番号→无码、个摄番号→个摄、欧美番号→欧美、国产传媒→国产、国产短剧→短剧、动漫里番→动漫），与候选区悬停全称解耦；类型刮削、指定网站、当前网站三者独立互不影响。
- `DomainRotator`（`utils/domain_rotate.py`）：镜像轮询，声明 `_domains` 类属性，已接 javbus(7)/freejavbt/xcity；`_init_rotator(domains, custom_url)` 支持自定义 URL 优先。
- `AioSiteCrawler`（`crawlers/aio_site.py`）：用于 Vue SPA + JSON API，重写 `_run`，`_generate_search_url`/`_parse_search_page` 抛 `NotImplementedError`；avmoo/avsox/avheat 共享该基类。
- `check_urls()` 返回检测 URL 列表；动态域名站覆写（avmoo/avheat/avsox 用 `get_aio_domain`，javlibrary 用 `get_javlibrary_domain`）。
- **18+年龄门统一模块**（`crawlers/base/age_gate.py`）：五站成人Cookie常量（MGStage`adc=1`/Hbox`age_check_ok=true`/DMM`age_check_done=1`/GetchuDL`adult_check_flag=1`/JavBus`age=verified`片段）+`is_age_gate_page`（MGStage年齢認証/Getchu年齢認証ページ/JavBus年龄验证三站特征并集+Hbox门壳`page":"/age_check`+`/age_check?redirect=`）+`extract_adult_entry_url`（只回成人入口，剧场版/未成年分支永不返回；Hbox门页无链接，返回None属预期）+`follow_adult_entry`（命中即点选重取一次，无链接/重取失败原样交回）+`is_hbox_age_gate_shell`（落地URL含`/age_check`或命中门壳标记，供连通性与Hbox爬虫先确诊）。MGStage的`_get_page_text`经它兜底，Hbox的`_fetch_detail`先认门壳直抛年龄验证错误（非门壳才3次重试），JavBus的POST确认+验证码层保留站内实现（验证码需用户去真实浏览器过一遍）。

### 4.1 联动站点组（网页版 ⇄ JSON 通道）

同一数据源的多条访问通道登记为一个**联动组**，组内站点互为替代。实现唯一来源是 `config/models.py`：`SITE_GROUPS`（组成员，顺序即组内顺序）+ `WEB_TO_JSON_SITE`（JSON 优先方向，反转得 `JSON_TO_WEB_SITE`）；界面侧在「软件设置-刮削网站-类型刮削网站-编辑网站」弹窗。

规则（改联动行为只改这两张表，不要在 UI 层另写判断）：

1. **定义**：网页版 / JSON 通道 / 官方 API / 移动端 APP / 镜像站，只要读的是同一份数据，就登记为一组。
2. **加入补齐**：在「可用网站（按类型分组）」加入组内任一站点，同组其余站点一并加入（`expand_site_groups`；候选区没有的成员不补，避免加进无法刮削的站）。
3. **移除不复活**：加入后可在「启用网站」手动移除单个站点，移除结果原样保存，不会被自动加回。
4. **排序独立**：启用列表（从左到右优先级递减）里的手动排序对组内站点相互独立，移动一个不带动其余。
5. **移除只删选中项**：一次只删选中的那几个，不连带同组站点。
6. **JSON 优先 + 网页版兜底**：组内同时有网页版与 JSON 版时，`WEB_TO_JSON_SITE` 指定 JSON 版优先（`core/file_crawler.py::_prefer_json_site`），JSON 不可用或字段缺失时按 `JSON_TO_WEB_SITE` 回退网页版补齐。
7. **一站一组**：`_SITE_GROUP_OF` 由 `SITE_GROUPS` 派生、后写覆盖先写，同一站点只能登记在一个组里（LibreDMM 因此挂在 DMM 组、FC2 与 FC2CMADB 同组）。
8. **边界**：联动只作用于「编辑网站」的加入/移除，不改类型默认名单 `TYPE_DEFAULT_SITES`、不改检测网络的分组行与勾选展开。

新增一组时同步三处：`SITE_GROUPS` 加元组、`WEB_TO_JSON_SITE` 加映射（有 JSON 版时）、`tests/test_site_group_linkage.py` 的期望清单。当前 21 组见 `docs/MEMORY.md`「联动站点组规则」。

---

## 5. 网络层

- httpx（默认）+ curl-cffi（指纹伪装）。
- 指纹池默认 7 种画像轮换：Chrome 124/131/136 Win、Chrome 136 Mac、Firefox 133/135 Win、Safari 17.2 iOS；Amazon 用纯桌面 6 种池（不含 Safari iOS）；Madouqu / Madou.club / Lulubar / MissAV / JavDB 各有专属池（详见 §5.1）。
- 限流：并发数 + 全局线程延时；Amazon 另用 `AdaptiveRequestThrottle`（429 自动降速冷却）+ 指数退避。
- **CF Bypass** 走 `mdcx/cf_bypass/trawl_adapter.py`（TRAWL `/scrape` 或 FlareSolverr `/v1`）；JavLibrary 额外支持 Selenium+Edge（`selenium_adapter.py`）；`cf_selenium_bypass` 默认开启。内置 CF Bypass（cloakbrowser + cf_bypasser）已于 v2.0.6 移除。
- **代理路由**：按「走代理网站」域名，默认 38 域（amazon.co.jp、m.media-amazon.com、xcity.jp、minnano-av.com、avbase.net、javbus.com、javdb.com、javlibrary.com、r18.dev、mgstage.com、prestige-av.com、seesaawiki.jp、avsox.click、avsox.com、avmoo.shop、avmoo.com、avheat.shop、avheat.com、heyzo.com、caribbeancom.com、1pondo.tv、pacopacomama.com、10musume.com、mywife.cc、github.com、raw.githubusercontent.com、google.com、missav.ws、missav.live、aventertainments.com、javfree.me、7mmtv.sx、getchu.com、dl.getchu.com、jav321.com、hbox.jp）。
- **TRAWL/FlareSolverr 适配层**：对外暴露 cf_bypasser 三端点 `/cookies` `/html` `/mirror`；trawl 走原生 `/scrape`（响应无 `responseHeaders`/`body`，适配层走 html 回退）；flaresolverr 走 POST `/v1`（`cmd=request.get/post`），响应头从 `solution.headers` 还原；配置 `cf_bypass_trawl_url` + `cf_bypass_trawl_backend`（默认 trawl）；`AsyncWebClient` 自动拉起 `TrawlAdapterServer`（随机端口 + uvicorn 子进程）；回环 https 经 `normalize_trawl_url` 降回 http（否则 60s 探活失败永久禁用）；`is_proxy_host` 名单写主域时同站动态镜像自动跟随走代理，直连白名单优先。
- **动态域名**：`base/web.py::get_aio_domain(site)` 解析 `tellme.pw/{site}` 的 `__AIO_SITE_URLS__`，1 天缓存、三站互兜；`get_javlibrary_domain()` 认 zlibz.com 发布的地址图（sha256 查表）得到当前中文地址，失败回退已知镜像。
- **网络检测**（`core/network_check.py`）：检测项由 `check_urls()` 动态生成；API 类爬虫走真实刮削探测 `_probe_crawler_by_run`；探针番号优先级 `NetworkCheckSpec.probe_number` > 爬虫 `probe_number` 类属性 > 全局 `SCRAPE_PROBE_NUMBER`（默认 SSNI-647）；Official·有码 29 站与无码五站各有独立 `Website`、各带本站探测番号（`official_sites.py::OFFICIAL_SITE_SPECS`、`official_uncensored.py::UNCENSORED_OFFICIAL_SITES`）；`_DETERMINISTIC_PROBE_MARKERS` 命中即首次定论（含年龄确认页/年龄认证/年龄验证/adcCookie/AgeVerification），其余按 `SCRAPE_PROBE_ATTEMPT_TIMEOUTS`（30s→45s）递进重试；搜索探测优先经 `crawler._fetch_search`（含各站18+兜底）而非raw`client.request`；终局说明只在两档都真超时时写「均超时」，站点可达但番号不存在单独出提示不计故障；结果持久化到 `userdata/network_check_cache.json`（`merge_site_check_cache` / `load_site_check_cache`），各站以站点值为键，同一站点多条结果只在本轮内取最差。
- **检测里的 DMM GraphQL POST 是网页版探测、不是 JSON 通道**（2026-11-13 排查）：点【开始检测】后，`Website.DMM`（网页版）走真实刮削探测 → `dmm/__init__.py::fetch_digital` 打 `https://api.video.dmm.co.jp/graphql` 补简介，与 `Website.DMM_JSON` 的 affiliate ItemList 探测（hits=1）同轮并发，两条日志挨着容易被看成同一件事。`DMM_JSON` 自身带 validator，**不**走爬虫探测（`network_check.py` 的 crawl 探测分支要求 `not spec.validator`），所以这条 POST 与 JSON 通道无关，也与「查看JSON / 浏览器」按钮无关——那两个入口只在下拉框里点按钮才触发。
- **FC2 文章页必须带 fc2 Cookie**（2026-11-13 排查）：`adult.contents.fc2.com/article/{id}/` 不带 Cookie 时返回「登录 FC2」空壳页（约 14KB，无 `items_article_*` 结构、无 ld+json），DOM 与 ld+json 解析全空 → FC2_JSON 的演员/标签/发行日/时长/厂商/剧照/标题全丢。刮削器 `FC2JsonCrawler._get_cookies` 一直带配置项 `fc2` 的 Cookie；`controllers/main_window/json_view.py` 的 FC2 分支原先没带，已补（同源 `fc2_cookie_to_dict`）。

### 5.1 JavDB 专属 UA 指纹池与多 Cookie 轮换（2026-11-18）

**背景**：JavDB 有 CF 墙且风控严格，账号曾因「浏览速度远超正常用户」被临时停用。此前 JavDB 走通用默认指纹池（7 种随机）、Cookie 用单一静态值（`manager.config.javdb`），无轮换机制。

**UA 指纹池**（`mdcx/network_fingerprint.py`）：
- 新增 `_JAVDB_FINGERPRINTS` 专属池，6 种指纹：Chrome 136 Win / Chrome 131 Win / Chrome 136 Mac / Firefox 135 Win / Firefox 133 Win / Safari 17.2 iOS。
- `select_fingerprint()` 对 `javdb580.com` / `javdb.com` 及子域名命中专属池。
- 轮换由 `web_async.py` 统一驱动：lifetime 20–45 分钟 + 请求数 120–240 双重过期；CF 挑战失败时 `exclude_fingerprint_id` 排除当前指纹重试。
- 指纹与 `_solver_cookie_jar` 的 cookie 配对（CF 挑战成功后钉住），cookie 失效时解钉并轮换指纹。

**多 Cookie 轮换**（`mdcx/crawlers/javdb.py`）：
- `parse_javdb_cookies(raw)`：按换行分割、`strip()` 去空、去重保序，返回 `list[str]`。
- `JavDBCrawler.__init__`：从 cookie 池 `random.choice` 选一个作为本次刮削的会话身份（sticky per-instance），模拟单一用户连续浏览；不同文件刮削用不同 cookie 分散单账号请求压力。
- `_current_cookie()`：返回选中 cookie；`_rotate_cookie(exclude_current=True)`：登录态失效时切换到另一个。
- `_get_headers()`：返回 `{"cookie": self._current_cookie()}`，无 cookie 时返回 `None`。
- `actor_name_javdb.py::default_javdb_cookie()`：演员番号搜索也随机取 cookie。

**兼容层**：
- `core/network_check.py`：连通性检测取第一个 cookie（`parse_javdb_cookies(config.javdb)[0]`）。
- `controllers/main_window/net_check.py::_check_javdb_cookie`：UI 检测取第一个 cookie，多 cookie 时提示「共 N 个 Cookie 轮换」。
- 配置字段 `javdb` 不变（`str`），用户在文本框每行粘贴一个 cookie 即可；单 cookie 旧配置完全兼容。

**测试**：`tests/test_network_fingerprint.py`（专属池命中 + 重试排除）、`tests/test_javdb_meta_throttle.py`（cookie 解析去重、实例随机选择、轮换切换、空 cookie 4 例）。

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

核心：PyQt6 6.11.0、httpx、curl-cffi>=0.17.0、lxml + parsel + beautifulsoup4、Pillow + opencv-contrib-python-headless、Jinja2、openpyxl、uvicorn。

**cp315 wheel 下限清单**（改依赖务必守住）：

```
aiohttp>=3.14.5      av>=19.0.2          lxml>=6.1.3
pillow>=13.0.0       numpy>=2.5.5        pyinstaller>=6.22.3,<7
aiofiles>=25.1.0     cffi>=2.1.1         jiter>=0.19.0
markupsafe>=3.0.4    pydantic-core>=2.50.5  PyQt6-sip>=13.13.1
pyyaml>=6.0.4
```

- `requires-python` 固定 `>=3.15`（3.15 是当前唯一构建目标），不带 upper bound。
- **依赖升级同步军规**（真源顺序：`uv.lock` > `pyproject.toml` > `requirements.txt`；`pyproject.toml` 与 `requirements.txt` 不一致时，以 `pyproject.toml` 为准修改 `requirements.txt`，例外 cap 除外）：
  1. `pyproject.toml` 的版本要与本机保持一致：本机（`.venv`，`uv sync --locked` 之后的状态）某个包做了**升级**，`pyproject.toml` 与 `requirements.txt` 里对应包的版本下限必须同步上调到已安装版本；**降级不用理会**（不下调下限）。
  2. 标准流程：`uv lock --upgrade-package <pkg>` → `uv sync --locked` 验证 → 同步 `requirements.txt` 镜像行 → 若涉及 cp315 wheel 起步包，同步更新 `tests/test_py314_dependency_floors.py` 的声明/锁定元组/文档 → ruff 走 `python -m scripts.sync_ruff_version`（自动同步三处声明点）→ 跑通 floors/sync 相关测试。
  3. 例外 cap 保持不动：`pyqt6<6.12`（上游 .pyi 语法问题，见 `requirements.txt` 注释）、`ruff<0.18`（由同步脚本按 lock 自动推导 upper bound）。
（3.15 是当前唯一构建目标），不带 upper bound。
- 112 个锁包里 109 个有 wheel（mdcx 自身除外；sdist-only：oshash/zhconv）。pyyaml 6.0.4 起提供 cp315 wheel（含 libyaml C 扩展），dev 组显式钉 `>=6.0.4`，3.15 下直接装官方 wheel，无需纯 Python 构建的兼容开关。
- ruff 版本以 `uv.lock` 为唯一来源。升级 ruff 后运行 `python -m scripts.sync_ruff_version`，自动同步 `pyproject.toml`（`ruff>=X,<Y`）、`requirements.txt`（`ruff>=X`）和 `uv.lock` 根 metadata 的 specifier；`--check` 只校验不改文件。`scripts/check.py` 发现漂移会自动同步并以非 0 退出，提交同步结果后重跑即可。标准升级流程：`uv lock --upgrade-package ruff` → 同步脚本 → 全量 format/check；`tests/test_ruff_version_sync.py` 钉死一致性。

---

## 9. 测试

- pytest + pytest-asyncio；标记 `network`（默认跳过）、`integration`（默认跳过）。
- 命令：`uv run pytest tests/`；离线子集 `uv run pytest tests/ --tb=short -m "not network" -x`。
- CI 分工：Linux 跑 ruff/mypy/完整离线测试/数据库检查/线程安全检查；Windows（`windows-2025`）跑同一组离线 pytest + PyInstaller 冒烟构建；Release 在 macOS/Windows/Ubuntu 分别构建 DMG/EXE/Linux 单文件。
- `CI Pipeline.yaml` **只监听 `pull_request`（目标 main），不监听 push** → 直推 main 无 CI 门禁，改为两道：提交前 `uv run quick-check`，推送前 `uv run check --skip-hook-install`（守卫 `tests/test_ci_workflow_triggers.py`）。
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
- **测试文件命名禁止带日期后缀**（2026-11-18 用户定规）：测试文件一律用 `test_<功能名>.py`，禁止写成 `test_<功能名>_YYYY_MM_DD.py` 或 `test_<功能名>_YYYY_MM.py`。日期信息写进 `docs/Changelog.md` 的对应日期段，不要塞进文件名。新增测试用例优先追加到已有同主题测试文件，不另起新文件。已有的 15 个带日期后缀的测试文件已全部重命名为无日期版本。

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
- `Getchu` 对大陆 IP 过不了 CF 墙 → 前六组不收（Getchu 只随动漫里番一组）。
- `Official·有码 33 站`按番号前缀锁定对应官网，国产/欧美/个摄没有收录 → 只在有码组；无码五站只收无码 → 只在无码组。
- `MyWife` 不属于任何类型 → 七组都不该有。
- 移除站点只动默认名单，不动爬虫注册与 `Website` 枚举。

### 10.9 界面文案纪律

菜单项/提示词/状态提示/日志提示一律**不写空格、不写括号**（`（）` 与 `()` 都不行）。

**日志与所有界面文字：英文语境之间的空格照留，中文之间的空格不留，行首图标后保留一个空格**（用户 2026-10-28 定规，2026-11-12 修订口径）。日志出口统一经 `mdcx/utils/__init__.py::strip_log_spaces()` 洗一遍：`LogConsole.log_text()`、`LogConsole.add_log()`、`Signals.show_log_text()`、`LogPageMixin.show_log_text()` 以及 `add_html()` / `add_html_plain_text()` 把行内连续空白（空格 / Tab / 全角空格）当成一段再判断——两侧都是半角可见字符（英文单词之间、单词与数字之间、英文标点之后）时留一个空格（`I Want Clips:Blacked Out Fm`、`Start time`、`HTTP 403`、`videos, Please`），只要有一侧是中文、全角标点或图标就删掉（`连接 Gfriends 网络` → `连接Gfriends网络`）；同时保留 `\n`、HTML 标签内部语法（如 `<font color="red">`）、双引号里的原文（响应体/引用）、每行行首图标后的一个空格（如 `🔐 授权状态：`）、URL 与紧随其后的「失败」之间的空格，以及源码里本来就写漏空格的固定搭配（`MDCx 20261027`、`GET https://a.com`、`CF Bypass`、`HTTP 403 body=`）；新写的日志与界面文案仍不要主动加多余空格。

**刮削到的字段值按站点实际值走，不单独删空格、不做字符替换**（用户 2026-11-12 定规）。2026-11-12 起 `mgstage` / `prestige` / `prestige_web` 的演员名不再 `replace(" ", "")`（`prestige_web::_split_names` 只按 `[,、，]` 分隔、不按空白切开名字），`美月 さくら` 这类带空格的姓名按实际保留；标题/简介/系列/片商/发行写入 NFO 前也不再过 `normalize_xml_text()` 的字符清洗（细则见 §3.8）。番号归一、标题匹配、搜索 query 那类临时比较键里的去空格属匹配逻辑，不在本条范围内。

- 正例：`复制本组：30个站点`、`复制列表：45个站点`、`已启用：12个站点`。
- 反例：`复制本组：30 个站点`、`复制本组「有码」（30个站点）`、`已启用（12 个站点）`。
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
- **推送网络口径以 `docs/MEMORY.md`「协作与质量」章为准**（2026-11-17 更新）：命令行优先直连，直连失败才走 7897 代理 + openssl；下面 10.6 的门禁流程不变。

### 10.11 大模型输出纪律

默认**只返回修改后的片段**，不重复输出未改动的全文；注明文件路径与定位（函数名/小节名/行号）。
新建文件、用户明确要求全文、或只给片段会产生歧义时才输出全文。口径见 `docs/MEMORY.md`「协作与质量」。

### 10.12 共用逻辑必须单独成文件或函数

共用的功能/方法一律抽成独立文件或函数，不允许复制粘贴出第二份；跨模块复用或体量大时抽独立文件
（如 `core/file_association.py`、`tools/emby_actor_ui_kit.py`）。旧位置保留薄封装转调，改共用实现前先 `grep` 全部调用点；
共用函数要有语义化名字、写清约束的 docstring，并被至少一个回归测试覆盖。细则见 `docs/MEMORY.md`「通用纪律」。

### 10.13 xlsx 导出列宽纪律（2026-11-18 用户定规）

**设定列宽是多少，导出后打开文件看到的就必须是多少**，不允许「设定 15 导出 14.22」这类偏差。

- 根因：openpyxl 的 `column_dimensions[..].width` 写的是原始字符数，WPS/Excel 显示时会扣掉
  网格内边距，实测显示值恒比写入值小 **0.78**（2026-10-17 用 `ET.Application` COM 实测，
  见 `tools/emby_actor_export.py::WPS_COLUMN_WIDTH_OFFSET` 的注释）。
- 规则：任何写 xlsx 列宽的代码，写入值一律 = 显示设定值 + `WPS_COLUMN_WIDTH_OFFSET`，
  统一从 `tools/emby_actor_export.py` 导入该常量，禁止各处再手抄 0.78 或裸写设定值。
- 回归：`tests/test_missing_audit.py::test_excel_column_widths_written_as_displayed`
  （演员番号/缺失番号导出表）、`tests/test_actor_export.py`（演员数据表）。
- 2026-11-18 落地：「查询演员番号」/「检查缺失番号」共用的
  `tools/missing.py::_write_missing_excel` 补上补偿；同时应用户要求把时长/类型两列
  从 12 收窄为 6（`_COLUMN_WIDTHS = (15, 12, 12, 6, 6, 12, 60, 100)`）。

### 10.14 DMM 演员番号去重的联网复核与两处根因（2026-11-18）

用户质疑「三上悠亜 700 多个原始番号去重后只剩 428 个，是不是丢了」。复核不靠推断，
直接把 `actor_sources._fetch_dmm_api` 的原始返回落盘再逐条比对：

- **方法**：给 `src._http_json` 套一层 spy（记录 `{url, data}` 后转调原函数），实拉四位演员
  （三上悠亜 / 明日花キララ / 深田えいみ / 波多野結衣）的 digital + mono 两条产品线，抽出每条的
  service/cid/title/url/date/volume/actresses/maker/label/series；再按 `normalize_key` 算
  「原始键集合 − 命中键集合」得 `lost_keys`、反向得 `extra_keys`，并按标题相似度（difflib）
  把同一键下的不同标题分组，逐组人工判定是不是真不同作品。脚本与原始 JSON 落系统临时目录，不进仓库。
- **判定口径**：标题差异组只要 cid 剥壳后同键，就是介质/版本/分卷变体，不算丢番号。实测最极端的几组：
  OFJE-227（DVD4枚 vs Blu-ray4枚）、EHM-001（`h_295ehm00001` vs `n_650ehm0001`，素人厂两条厂商码）、
  VRAD-801（4 个 VR 話 + `n_1155vrad801`）、DVAJ-391（td028/037/043 三档特価 + `537dvaj391` + bod）、
  DASD-785（Standard vs High-Quality）。四位演员 `lost_keys` 全为 0，用户附件 428 行与联网结果
  双向差集为空 —— **去重本身没有丢番号**。
- **根因一（重复没去干净）**：剥壳只覆盖了 bod/dod/4k，租赁与促销版的 `r`/`x`/`f`/`re`/`redod`/`sodod`、
  総集編的 `ai`/`soai`/`mtn`/`jo01`/`sa1`、赠品的 `tk1`/`tktb`/`dl`/`dp`、分卷字母 `a`，
  以及 `td0NN` / `d1`…`d6` 促销前缀都漏了，三位演员分别残留 11 / 6 / 89 个非标准形态番号。
  **两次失败尝试**：① `(?<=\d)[a-z][a-z0-9]*$` 直接剥字母尾 → 白名单回放 73066 条回退，
  数字结尾的厂商码后面整段「厂牌+编号」都被当成标记（`h_1743aabh00001`→`H-1743`）；
  ② 收窄成 `(?<=\d)(?:[a-z]+\d{0,2})+$` → 仍 1858 条回退，2 位编号的路由组合（`h_086abba01`、`13acb01`）
  与「厂牌+标记」在字符串层面同构，靠尾部正则区分不了。**可行解**：先结构化 fullmatch 认出核心
  `((?:[hn]_\d+|\d+)?[a-z]{1,10}\d{2,7})`，剩下的才算标记；促销前缀在切分前剥、`4k` 在切分后剥
  （KIRI 厂商码恰为 4）。101146 例回放 0 回退、1263 修正、9 中性。
- **根因二（真丢番号，与去重无关）**：翻页护栏写死 `offset <= 3000`。波多野結衣 digital
  `total_count=3937`、mono `4581`，两条线各截掉 937 / 1581 部，2518 条原始记录根本没进取号流程 ——
  这才是「大目录演员导出缺号」的真凶。改成按每页 `result.total_count` 收手，护栏放宽到 20000
  只防异常跑飞。修复后波多野結衣 8518 条原始 → 4193 个番号（原 3263，找回 930 个）。
  护栏是「单演员 × 单产品线」口径、不跨演员累计：多演员在 `tools/missing.py` 的
  `for actor_name, actor_type in actor_entries:` 里串行逐个查，`offset` 每条产品线重置为 1，
  传进 `_fetch_dmm_api` 的 `names` 只是同一演员的名字变体（`_pick_name(names, 2)` 试到解析出
  actress_id 就 break）。**真正会先截断的是超时**：DMM_JSON 原先没进 `_SITE_TIMEOUTS`、
  吃 `Source.timeout` 默认 120s，照 HBOX_JSON 先例放宽到 300s；DMM 网页版仍 60s 且转调同一 fetcher。
- **回归**：`tests/test_dmm_cid_number.py` 29 → 63 例。

### 10.15 「格式化番号名」为什么接在 `_merge` 而不是取完再格式化（2026-11-18）

用户要求把 DMM/DMM_JSON 那套剥壳口径推广到**所有站点**，做成独立文件独立函数、
由工具页复选框控制、默认不勾选、旧配置自动升级。三个设计判断记录在此：

- **为什么不能只调 `display_number`**：`_merge` 本来就已经对每个站点的番号调
  `display_number`（`9SSIS287` 原样大写返回），所以「格式化」必须比它更强 ——
  真正剥壳的是 `dmm_number_from_cid`。新模块 `utils/number_format.py::format_number`
  就是「`dmm_number_from_cid` + MyWife 例外」这一层工具页策略，剥壳规则本身不搬家。
- **为什么接在 `_merge`**：grep 全部调用点确认 `_merge` 有 37 处调用，而
  `NumberHit(` 在 `mdcx/` 里只有一处构造（就在 `_merge` 内）—— 它是全部站点番号的
  唯一漏斗。在这里按 ContextVar 分流，逐站原始结果（`per_site_out`，供取号准确率对比表）
  与合并结果天然同口径。**若改成「`collect_numbers` 返回后再统一格式化一遍」会有真问题**：
  对比表里逐站番号仍是旧形态、汇总表是新形态，同一番号在两处对不上。
  漏斗口径的漏网之鱼是 MyWife：它在 `_merge` **之后**用
  `replace(hits[key], number=authority_number(...))` 把 `Mywife No.1693` 恢复成站内权威号
  （两处：WP REST 与官网兜底），因为 `display_number("Mywife No.1693")` 会压成 `MYWIFENO.1693`。
  这一处、以及「将来自己拼 `NumberHit` 不走 `_merge` 的新刮削器」，由 §10.16 的**站点出口**
  兜住 —— `format_number` 的 MyWife 分支本身就返回权威形态，出口再走一遍是幂等的，
  不会把恢复结果覆盖掉。
  ContextVar 而非参数透传，是因为 `_merge` 被 37 处 fetcher 调用，逐个加参数改动面太大；
  `asyncio.gather` 派生的子任务会 copy context，开关照样传得进去（与既有
  `_OFFICIAL_NAMES` / `_JAVDB_KEYWORD_ONLY` 同一套写法，`finally` 复位）。
- **为什么本地键也要格式化、但缓存不能**：勾选后网络番号变成 `SSIS-287`（键 `SSIS287`），
  本地若仍按原值 `9SSIS287` 算键（`9SSIS287`），去重就失效、本地已有的片被报成缺失。
  所以 `_scan_local_numbers` 的返回键与 `_report_actor_result` 的 Flags 回退集合都要过
  `format_number`。但 `Flags.local_number_set` / `local_number_cnword_set` 与
  `number_list.json` 是**其它工具共用**的，写格式化值会污染它们，故仍写原值 ——
  「比对键」与「共享数据」分开处理。`format_number` 必须幂等：写表前的
  `enrich_missing_metadata` 会再按 `normalize_key(hit.number)` 建索引，不幂等就会漂移。
- **文案与对齐**：`label_8`（移动…Movie_moved 提示）是 x=50 / 宽 591，右缘 641 ≥
  组宽 701×0.9=630.9，被 `CustomScrollArea._classify_inner` 判为 `_DOCK_RIGHT`。
  两条新提示语必须同 x 同宽，才能在页面拉宽时同样右缘锚定、保持左缘上下对齐；
  宽度改一点就会掉进 `_KEEP` 分支，宽态下与 `label_8` 错开。三枚复选框宽 112、
  右缘最大 480 < 630.9，判为 `None`（保持原位），不受拉宽影响。
- **回归**：新增 `tests/test_format_number_option.py` 69 例（§10.16 扩到 224 例）；
  既有 5 个测试文件随文案更新断言，并给 fake Ui 补上两枚新复选框属性。

### 10.16 文案遮挡的像素预算 + 70 站全部接入格式化番号名（2026-11-18 二次修订）

用户当日追加三条：①「刮削排除目录:」改中文冒号以便与「本地文件路径」「番号链接地址」
等左对齐；② 三枚复选框文案回退成 6 字，否则末字被遮挡；③ 70 个网站刮削器全部接入
格式化番号名，两个工具导出的 xlsx 都要格式化。

- **①的排查结论：冒号从来就是全角，问题是标签窄了 1px**。先 grep `.ui` 与 git 全历史，
  `label_41` 的文案一直是 `刮削排除目录：`（U+FF1A），没有任何半角版本，所以「换冒号」
  无从下手。改用 offscreen Qt 真实度量（`QFontMetrics.horizontalAdvance` + 工具页 QSS）：
  13px 字体下 7 个全角字符需 **91px**，而 `label_41` 只有 **90px** —— 冒号被裁掉，
  视觉上就成了「这个标签比别的短一截、没对齐」。兄弟标签 `label_3`（本地文件路径：）
  与 `label_10`（番号链接地址：）都是 x=46 / 宽 **94**，所以把 `label_41` 宽 90→94
  即与它们逐像素同几何。输入框 `lineEdit_escape_dir_move` x=136 不动：控件矩形虽有
  4px 重叠，但文字墨迹到 ~130px 就结束，实际不相撞。
- **②的根因：指示器边框吃掉了 2px**。工具页 QSS 只写 `* { font-size: 13px; }`，
  但 `centralwidget` 的 QSS 会 cascading 到子页，其中
  `QCheckBox::indicator{ width:14px; height:14px; border:1px solid #B8C0CC; }`
  按 Qt 盒模型实占 **16px**（14 + 左右各 1px 边框）。offscreen 量得
  `SE_CheckBoxContents` 起点 x=22、宽 **90px**（112 − 22）。7 个汉字需 **91px**，
  差 1px 裁末字；6 个汉字 **78px**，留 12px 余量。只量工具页 QSS（不带指示器边框）
  会得到「文字区 92px、7 字放得下」的错误结论 —— 这是第一次排查踩的坑，
  必须把 cascading 的那份 QSS 一起加上才复现用户看到的现象。
  修法取「改文案不改宽度」：加宽复选框会挤到右侧控件，而 6 字文案语义无损。
- **③的实现：站点出口兜底，而不是逐站改 fetcher**。审计 70 个注册刮削器后确认
  `NumberHit(` 在 `mdcx/` 里只有 `_merge` 一处构造，`_merge` 之后改 `number` 的只有
  MyWife 两处权威号回填，`enrich_hit_meta` / `enrich_missing_metadata` 只补
  release/duration/image 不动番号 —— 也就是说 §10.15 的漏斗口径**当时已经覆盖全部站点**。
  但用户要的是「70 站都接入」这条结构性保证，所以再加一道出口：
  `_run_source` 是唯一的站点结果边界（`_run_group` → `_collect_with_sources` 都经它），
  在 `if hits:` 处按 `_FORMAT_NUMBERS` 调 `_format_site_hits`，内部复用 `_merge`
  重新格式化 + 按新键去重 + 元数据按字段补齐。这样将来新增刮削器即使自己拼 `NumberHit`
  也自动接上，不必记得调 `_merge`。四个 `clean_*` 归一函数都幂等
  （`clean_meta` 逗号拼接、`clean_date` 委托 `normalize_release_date`、
  `clean_duration` 纯数字、`clean_image` 只认 http(s)），重复走不漂移；
  不勾选时出口原样返回，连这一遍都省掉。
  **刻意不放在 `collect_numbers` 返回之后**：那样 `per_site_out` 与合并结果口径会分裂（§10.15 ①）。
- **回归**：`tests/test_format_number_option.py` 69 → **224 例**。关键是把 70 站
  逐站参数化（× 开关 = 140 例），桩 fetcher **故意不走 `_merge`、直接构造 `NumberHit`**，
  再经真实的 `build_sources_for_sites` → `_run_group` → `_run_source` → `_collect_with_sources`
  跑一遍，断言逐站与合并结果的番号都格式化、演员/日期/时长/封面不丢；
  另有 70 站齐跑 × 三类型（有码/FC2/无码，三个注册表是 import 期 `{**_SITE_FETCHERS}`
  拷贝，patch 必须三份一起换）× 开关 6 例、注册表恰好 70 站、MyWife 权威号出口兜住、
  不勾选时出口 pass 被跳过（spy `_format_site_hits`）、两个工具 xlsx 番号列端到端 4 例。
  新增 `tests/test_tool_page_text_width.py` **10 例**：从 `.ui` 读设计几何与文案，
  用真实字体度量断言「文字宽 ≤ 控件文字区宽」，不写死字数 —— 换字体或改文案后
  只要放得下就通过，放不下会报出差多少像素。

### 10.17 「获取演员原名」四个设计判断（2026-11-20）

用户要求：两组各在「格式化番号名」右侧加一枚复选框；点查询按钮时先按输入框
的名字去 JavDB 取全部原名/艺名/曾用名（JavDB_JSON 优先、失败回退网页版），
用英文逗号回填输入框供直观查看，这批名字分别去各站取号、合并成一张表，
回填文本不落盘、重启恢复手动输入名。四个容易踩坑的地方记在此：

- **不新写解析器，复用 `core/actor_name_javdb.py`**。该模块原本就为「官网只认
  日文原名」而做：JavDB_JSON 的 `/api/v2/search?type=actor` 拿 id（带 token 时
  不受网页限流影响）→ 网页搜索兜底 → 抓 `/actors/{id}` 解析
  `actor-section-name` 名字块与 `section-meta` 别名，正好覆盖用户举的两个例子。
  本次只做三处增量：`JavdbActorNames` 加 `page_names` 字段保留**名字块原序**
  （`aliases` 原本把 meta 别名排在名字块其它写法之前，`candidates()` 又强制把
  日文原名排第一，两种顺序都不等于页面顺序）、新增 `all_names()` 用于展示、
  演员页被限流时直接用 App API 的 `name / name_zht / other_name` 兜出一份清单。
  `candidates()` 一字未改，官网搜索名不受影响。
- **名字变体上限用 ContextVar 而不是逐个改 fetcher**。70 个刮削器里有 25 处
  写死 `_pick_name(names, 2)`、还有 `(names, 1)`，即使把 6 个名字传进
  `collect_numbers`，每站也只吃前两个，用户拿到的 6 个名字等于白取。逐个加参数
  改动面太大且与 §10.15 的 `_FORMAT_NUMBERS` 同一套问题，故加
  `_MIN_NAME_VARIANTS`（默认 `None`），`_pick_name` 里 `limit = max(limit, floor)`；
  `collect_numbers(all_name_variants=True)` 把它设成 `len(names)` 并在 `finally`
  复位。不勾选时 ContextVar 为 `None`，所有调用点的行为一字不变。
- **回填文本是「展示态」，绝不能回流成查询输入**。`parse_actor_entries` 按逗号
  拆多个演员，若把回填的 6 个名字当输入框内容提交，就会跑 6 轮、生成 6 张表，
  与用户要的「合并一张表」相反。所以后端解析发生在**任务内部**：以
  `parse_actor_entries` 拆好的原始条目为准，把每个条目的解析结果记进
  `resolved_names`，循环里作为 `name_variants` 传给 `_fetch_actor_numbers`；
  报表仍用原始 `actor_name`（`_excel_target` / `excel_target` 都以它命名）。
  回填只发一次 `actor_names_filled(slot, text)` 信号，由主线程 `setText`。
- **「默认不保存」靠 `textEdited` 而非 `textChanged`**。`setText()` 不触发
  `textEdited`，只有用户真实手打/粘贴才更新 `_manual_actor_names` 影子值；
  `save_config` 仅当输入框当前文本**恰好等于**最近一次程序回填文本时改存影子值
  （相等说明用户没再动过），随后 `load_config` 又会 `setText` 回配置值并清空
  回填标记。用户手动改过回填内容时 `textEdited` 会清掉该槽的标记，保存与查询
  都按编辑后的文本走，不会被影子值覆盖。两个槽（`missing` / `actor_number`）
  各记各的，互不串改。

- **回归**：`tests/test_fetch_actor_names.py` 21 例，含用户举的 6 名 / 3 名顺序、
  JavDB_JSON 命中时断言不发 `/search?`、JSON 空时断言发了 `/search?`、演员页
  返回登录页时 App API 兜底、ContextVar 设置与复位、回填信号的槽位与英文逗号、
  只跑一次 `_fetch_actor_numbers`（一张表）、配置迁移幂等等。

### 10.18 「获取演员原名」独立化、四种开关组合与 xlsx 数据源下线（2026-11-20 追加）

用户追加四条：把功能做成**独立文件 / 独立函数**（以后还有别的功能要调用）、
规定两枚复选框四种组合的取号与格式化口径、并明确「`actor_database.xlsx`
数据可能有错，无论什么情况都不要再拿它取演员原名，把功能和逻辑删掉」。

- **独立模块的边界**：`core/actor_original_names.py` 只做「输入名 → JavDB 全部名称」
  这一件事，主函数 `fetch_actor_original_names()` 自带默认 HTTP 通道（项目通用
  `AsyncWebClient`，与取号链路共享 JavDB 限速）并允许注入 `fetch_text` /
  `fetch_json` / `javdb_api`，因此离线单测不需要网络、其它功能不需要经过工具页。
  纯解析仍在 `core/actor_name_javdb.py`（`parse_actor_page` / `JavdbActorNames`
  / `resolve_jp_names_via_javdb`），两层分工：解析层不碰网络客户端，业务层不碰
  HTML。`join_original_names()` / `actor_name_variants()` 是纯函数，调用方自己决定
  拿去回填还是拿去取号 —— 展示态和取号态不再共用一份被 `parse_actor_entries`
  误当成「多个演员」的字符串。
- **四种组合的落点只有一处**：`missing._fetch_actor_numbers` 的
  `names = list(name_variants) if name_variants else [name]`。`name_variants`
  只有勾选「获取演员原名」时才由后端解析填充；不勾选时直接 `[name]`，从而
  `resolve_actor_names`（xlsx + JavDB App + 网页演员页 + 简转繁）整条自动扩展
  链路被彻底移除。格式化仍由 `_merge` 的 `_FORMAT_NUMBERS` ContextVar 决定，
  与名字来源完全正交；`normalize_key` 去重在两种格式开关下都发生。

    | 格式化番号名 | 获取演员原名 | 各站用的名字 | 番号 | 导出 |
    |---|---|---|---|---|
    | ✗ | ✗ | 仅用户输入名 | 原展示形态，照常去重 | 一张 xlsx |
    | ✓ | ✗ | 仅用户输入名 | `format_number` 后去重 | 一张 xlsx |
    | ✗ | ✓ | 用户输入名 + JavDB 全部原名 | 原展示形态，照常去重 | 一张 xlsx |
    | ✓ | ✓ | 用户输入名 + JavDB 全部原名 | `format_number` 后去重 | 一张 xlsx |
- **xlsx 下线的连带影响**：官网 fetcher 原本靠 `_official_name_candidates` 拿
  「演员库日文原名」，删库后这条链路会整组哑火。故 `_prepare_official_names`
  从 async + xlsx 读线程 + JavDB 网络兜底，简化成同步的「本轮名字去重」，
  `_official_name_candidates` 在准备阶段没跑时直接 `_pick_name(names, limit)`。
  代价是官网（MGStage 等）不再自动把中文名转日文名，用户输入什么就搜什么 ——
  这正是用户要的口径；要用日文原名时勾「获取演员原名」即可，届时
  `_MIN_NAME_VARIANTS` 会把各站写死的 `limit=2` 抬到全部名字数。
- **没有删的东西**：`actor_database.xlsx` 本身、演员库维护 / 补全中文名 / 同步别名
  等**写入**功能全部保留（`config/resources.py`、`actor_db.py`、
  `tool_handlers.py`）；删的只是「读它做演员原名映射」这一个用途。

### 10.19 「自动判断」探测路由与站点改名（2026-11-20 第三批）

用户追加：四个复选框要对全部 70 站生效；「检查缺失番号 + 自动判断」先拿
AVMOO / AVSOX / AVHeat 探测类型，再分别跑命中的类型组、汇总成一张 xlsx；
`Mmtv_JSON` 改名 `7mmtv_JSON` 并重排刮削兜底组与下拉选项。

- **探测与取号分离**：`actor_type_probe.probe_actor_types()` 只回答「该演员
  大概率属于哪些类型」，返回的番号**不并入导出**。理由：探测站与正式取号站
  有重叠（AVMOO_JSON / AVSOX_JSON / AVHeat_JSON 本身就在各固定链里），把探测
  结果并进去会与正式结果重复、且探测时用的名字可能与正式取号不同，去重口径
  会分裂。三站并发、同站按名字串行，`_DEADLINE` 给每次探测设 60s 软超时
  （2026-11-20 由 30s 放宽；预算按「每个候选名字」计，不是整站总时限，
  6 个名字时单站最坏 6 × 60s）——探测只需要知道有没有番号，不必翻完演员的全部作品页。
- **为什么 AVSOX 要试完所有名字**：AVSOX 一个名字可能只返回非 FC2 番号，
  另一个名字才返回 FC2 番号。`_site_complete()` 对 AVSOX 要求「非 FC2 与 FC2
  都命中」才提前收手，AVMOO / AVHeat 命中一次即可停，兼顾正确性与请求数。
  实测这也正是需求 3 的关键：三上悠亚用简体输入名时 AVMOO 返回 0，换成
  JavDB 取到的「三上悠亜」后返回 417 个番号。
- **多组只出一张表**：命中 N 组就调 N 次 `_fetch_actor_numbers`（各自
  `use_config_sites=False` → `_AUTO_SITE_ORDER[类型]`），结果按
  `normalize_key` 合并去重后**一次**交给 `_report_actor_result`。因此
  「只获取单演员」「获取本地番号」的过滤/去重天然覆盖所有组的所有站点，
  不必逐组各写一张 xlsx 再让用户自己合并。四个开关在默认流程与每组取号里
  用的是同一组参数，不存在「探测路由绕过某个开关」的分支。
- **三站全空要能退回原流程**：探测全空时 `routed_types=[]`，循环走原来的
  单一 `actor_type` 分支（`use_config_sites` / `sites` / `per_site_out` 全部
  原样保留），所以「查询演员番号」工具、下拉指定类型、以及探测无结果的场景
  行为与改动前一致。
- **改名只动展示值，不动内部标识**：`Website.MMTV_JSON` 成员名保留（Python
  标识符不能以数字开头，且内部标识无需跟着 UI 文案改），只把 value 改成
  `7mmtv_JSON`；`_rename_site` 与 `Website` 别名表都保留 `"Mmtv_JSON"` 旧键，
  存量配置不会因改名被静默剔除。排序按用户口径只重排两处：`TYPE_DEFAULT_SITES`
  / `default_config.json` 的**兜底刮削组**（数字 7 开头移到 `Airav_JSON` 之前），
  以及 `JSON_VIEW_SITES` / 运行时 `_site_sort_key` 的**下拉选项**；优先刮削组
  与其它列表位置一律不动。

### 10.20 工具页输入框宽度随机缩小：滚动区独立 resize 漏跑定制对齐（2026-11-21）

- **现象**：软件工具页「本地文件路径 / 番号链接地址」输入框与「开始刮削」等宽按钮在运行一段时间后变窄约 43px，右侧按钮位置不变、行内间隙变大；重启软件恢复。
- **取证**：离屏 Qt 探针在 1080 窗宽下逐项打印滚动区视口宽、`extra`、按钮 x、输入框宽。正常态 426px（`pushButton_select_file.x() - 19 - 158`）；只要让 `scrollArea_10` 自己 `resize()` 一次、不跑 `_sync_page_layouts`，输入框立刻变 383px（`设计宽 351 + extra 32`），`extra` 与按钮 x 都没变，随后 hide/show 也不恢复，只有切页 / 改窗宽 / 重启（触发全量同步）才拉回。383 与 426 的差正是「设计间隙 62px − 目标间隙 19px」，与截图量到的 43px 一致。
- **根因**：`CustomScrollArea.resizeEvent/showEvent` 会单独跑一次 `sync_wide_children_width()`，把 `_STRETCH` 输入按「设计宽 + extra」铺开；工具页这些行的终态却由 `_sync_tool_page_input_fill` 按右侧按钮的实时位置钉到「按钮左缘 − 19」。此前只有 `_sync_page_layouts` 会在通用拉伸后补跑工具页三步对齐，而 `scrollArea_10` 不在 `tabWidget` 内、没被安装 `_post_wide_sync_hook`（演员页 / NFO 页 / 高级页等都装了），于是任何一次不经过全量同步的独立事件都把终态覆盖成通用拉伸的中间态，并一直保持。
- **修复**：新增 `LayoutActorMixin._sync_tool_page_wide_hook()` 收口三步（演员库紧凑排布 → 封面补图选项行 → 输入框右缘锚定），`main_window.__init__` 给 `scrollArea_10` 安装为 `_post_wide_sync_hook`；`layout_master._sync_page_layouts` 里显式 `sync_wide_children_width()` 之后改为调用同一个方法，两条入口共用一套顺序，日后新增对齐项不会只照顾一处。钩子自带重入保护，`setGeometry` 触发嵌套 resize 时不会递归（离屏实测嵌套场景宽度仍稳定）。
- **回归**：`tests/test_tool_page_right_align.py` 追加 6 例——钩子安装、1080/1170/1600 三档窗宽下独立 resize / hide-show / 切页后宽度逐像素不动、窗宽往返与反复全量同步不漂移；断言落在「右缘 = 同行按钮左缘 − 19」这一不变量上，不写死像素值。临时摘掉钩子后其中 4 例必红，确认测试锁住的就是修复点。70 个 GUI/布局测试文件串行全绿，ruff format/check、mypy（297 文件）、线程安全门禁全绿。

### 10.21 刮削目录页「检查待刮削目录并清理文件」右缘对齐（2026-11-21）

- **需求**：按钮右缘向右移到与「文件名包含」输入框右缘严格上下对齐，输入框位置不变；宽态（最大化）时按钮保持窄态相同的宽度，不跟着输入框拉成长条。
- **取证**：离屏 Qt 实测（box61 局部坐标，`extra = 窗宽 − 1048`）：按钮 `160,430,321,40`（右缘 481 恒定）；两处「文件名包含」输入框右缘 `565 + extra`（1000→517 / 1030→547 / 1082→599 / 1920→1437）；同行「刮削时自动清理」左缘 `571 + extra`（宽态换到记录列，1920 下 800）。两者右缘天然差 6px，与 extra 无关。
- **两个不能踩的坑**：① 按钮设计宽 321 < 组框内半宽 340.5、右缘 481 < 0.9×701，`_classify_inner` 判为 None，**通用宽幅同步从不登记/搬动它**——所以宽度只能由定制方法运行时 `setGeometry` 给；若图省事直接改 `.ui` 把宽度写到 405，就会跨过 340.5 阈值变成 `_STRETCH`，宽态被拉成 `405 + extra`，恰好违反用户第二条。② 输入框在 `_STRETCH` 布局容器里，右缘随 extra 变，右缘差值不能写死，必须每遍按运行时 `mapTo` 实测（跨分支经公共祖先 content 中转）。
- **做法**：新增 `LayoutSettingsMixin._sync_guaxiaomulu_check_button_align()`，左缘/y/高一律不动，只改宽度 = 实测输入框右缘 − 160。非宽态逐遍对齐并记录窄态宽度；宽态（`isMaximized()` 或 `extra > _GUAXIAOMULU_WIDE_EXTRA=600`，与同页「自动清理」换列共用判据）冻结该宽度，直接在最大化态启动则退到「输入框右缘 − extra」的设计态宽度。右缘守卫取「组框内缘」与「自动清理终态左缘 − 6」的较小值。挂在 `_sync_guaxiaomulu_page_align` 第三步（前两步之后才能读到自动清理终态），并在 `layout_master._sync_page_layouts` 追加同一调用，钩子/全量同步两个入口共用。
- **回归**：`tests/test_clean_check_button_align.py` 6 例——两输入框同列假设、4 档非宽态右缘严格相等且只改宽度、与「摘掉新方法」基线比对、用户窗口→最大化宽度不变且输入框确实拉宽、幂等与窄↔宽往返、只跑钩子也能补齐。临时让方法 early-return 后 4 例必红。270 例相关回归 + 71 个 GUI/布局测试文件串行全绿，静态门禁（ruff format/check、mypy 297 文件、线程安全）退出码 0。

### 10.22 「去重复番号」独立模块 + 合并键与展示形态解耦（2026-11-22）

用户要求：①「格式化番号」的去重功能**迁出**成独立的「去重复番号」选项，70 个站点
全部接入，默认不勾选、写入配置文件、旧配置自动升级；②「去重复番号」再独立成
**一个模块和一个函数**，供各站点调用；③五枚复选框改名并缩间距，保证最右一枚不
超出所在组框右缘。四个容易踩坑的地方记在此：

- **「格式化」与「去重」是两件事，不能共用一个键**。格式化决定*番号名长什么样*
  （`format_number` 剥壳：`9SSIS287` → `SSIS-287`），去重决定*哪些写法算同一部影片*
  （合并键）。若沿用旧思路「格式化时顺带合并」，就会出现「不勾去重、但格式化后
  番号名相同 → 被合并成一条」，正是用户明确要否掉的对比效果。故新模块
  `utils/number_dedupe.py` 给两套口径：`dedupe_key(raw)` = `normalize_key(format_number(raw))`
  （同一部影片的各种写法收敛成一条）、`spelling_key(raw)` = `normalize_key(display_number(raw))`
  （只归一大小写/分隔符、**不**剥厂商码），`number_key(raw, dedupe=)` 按开关二选一。
- **合并键必须从原始番号算，不能从展示形态反推**。这是本轮最容易写错的一处：
  `spelling_key` 在格式化之后会变（`spelling_key('9SSIS287') != spelling_key('SSIS-287')`），
  所以 `_merge` 必须用**入参原文** `raw` 算键
  （`number_key(raw, dedupe=_DEDUPE_NUMBERS.get())`），跨站同番号分支直接在
  `merged[key]` 上补元数据、**不再回调 `_merge` 重算键** —— 回调会把展示形态
  （可能已被格式化）当原文再算一次，键会漂。
  `dedupe_key` 幂等是「先格式化再去重」与「直接去重」得到同一个合并键的保证。
- **站点出口必须按去重开关分两条路，不能一律重跑 `_merge`**。§10.16 的出口
  `_format_site_hits` 原本无论什么开关都重跑一遍 `_merge`（那时只有格式化一个开关，
  重跑是安全的）。加上「去重」后这就是陷阱：**去重未勾选时重跑 `_merge` 会按番号
  重新合并**，把 7mmtv「同一番号的多版本（有码原版 / reduced-mosaic / 中文字幕）」
  压成一条，直接违背「未勾选就不去重」。故出口分两路：去重未勾选时**只**把展示形态
  按格式化开关改写、保留原条目与原键；去重勾选时才重跑 `_merge` 重算合并键。
  7mmtv 站内的多版本保留同理：去重未勾选时按 `detail_url` 为键保留每一条网页条目，
  勾选时才走 `_merge`。
- **「独立模块供各站点调用」的落点是 `dedupe_numbers(numbers)`**。站点自己把番号收成
  列表后过一遍即可收敛成一条（保留首次出现的写法与顺序，空串与去不出来的丢弃）。
  模块只依赖 `number_format` / `shared_fields` 两个纯字符串工具，**不反向依赖业务
  模块**，避免循环导入；70 站本身经 `_merge` 这一个漏斗接入（ContextVar
  `_DEDUPE_NUMBERS`，与 `_FORMAT_NUMBERS` 各自独立，`collect_numbers` 设置、`finally` 复位）。
- **改名的像素预算**：用户要求在「格式化番号」右侧、「获取演员名」左侧插入第五枚
  「去重复番号」，沿用旧的 6 字文案 + 112px 宽则最右一枚会超出组框右缘。故五枚统一
  改 5 字、宽 100、x=158/263/368/473/578（间距 116px → 105px），最右一枚右缘 678 <
  组框右缘 631+100=731。5 字是上限：13px 字体 + `QCheckBox::indicator` 实占 16px
  （§10.16 的 cascading 坑），100px 复选框文字区剩 84px，5 字 65px 留 19px 余量；
  6 字 78px 只剩 6px、7 字 91px 直接裁末字。
- **回归**：新增 `tests/test_number_dedupe.py`（四个公开函数 + 「展示键与合并键解耦」
  这条设计不变量 + 模块独立性）；`tests/test_format_number_option.py` 补四种组合矩阵、
  70 站注册表共享键、全部 70 站同开同关、文案改名与位置、配置默认值与旧配置升级
  幂等、load/save 接线、工具页三入口传参等用例。

### 10.23 开关边界收口：入口预先剥壳、键漂移、按名命中即停（2026-11-22）

§10.22 把两个开关接进了 `_merge` 与站点出口，但**漏斗之前**、**键的算法**和**名字
维度**上仍有绕过开关的地方，全量审计 70 站 + 联网实测 32 种组合才暴露出来：

- **站点在入口就剥壳，等于两个开关都被抢先执行**。`_fetch_dmm_api` 原来传
  `_dmm_number_from_cid(cid)` 给 `_merge`：未勾「格式化番号」也剥了壳，更糟的是
  `9ssis287`（mono）与 `ssis00287`（digital）剥完是同一个番号，未勾「去重复番号」
  也被压成一条。改为**传原始 cid**，剥壳与合并全交给开关。实测 `白上咲花`
  DMM_JSON 由「剥壳后与 JavDB 大量重合」变成 224 条独立条目（digital + mono 两线），
  未勾格式化时导出表直接显示 `9FWAY031` / `301MBDD02141` 这类原始 cid。
  同理 `_fetch_aventertainments` 的 `re.sub(r"^DL", "", raw)`：DL 是下载版标记，
  无条件剥掉会让 DVD 原版与下载版同品番合并，故**只在勾选去重时剥**。
  判断口径：站点入口只准交「站点原样的番号」，任何剥壳/归一都属于两个开关的职责。
- **`dedupe_key` 必须经得起 `display_number`，否则出口重算键就漂**。§10.22 说
  「`dedupe_key` 幂等」，但那只对 `format_number` 自己的输出成立：`display_number`
  会把 `h_346rebd00872` 的下划线换成连字符，而剥壳正则只认 `[hn]_`，于是
  `dedupe_key(display_number(cid))` = `H346REBD00872` ≠ `dedupe_key(cid)` = `REBD872`。
  站点出口 `_format_site_hits` 勾去重时只剩展示形态可用，键一漂就漏合并。修法是在
  `dmm_number_from_cid` 入口把 `h-`/`n-` 还原成 `h_`/`n_`（只动厂商码分隔符，其余
  正则不变），而不是去掉出口的重算——出口重算还要兜住「不走 `_merge`、自拼
  NumberHit」的刮削器。按 `dmm_cid_routes.json` 全表构造 11327 个 cid 校验：修复前
  3818 个漂移（全是 h_/n_），修复后 0 个；实测 `白上咲花` 勾去重不勾格式化由 133 行
  收敛到 125 行。**教训：幂等性要按「链路上真实会经过的变换」验证，不是只看函数自身。**
- **补齐元数据不能按番号建索引回填**。`enrich_missing_metadata` 原来用
  `{normalize_key(hit.number): hit}` 反查，未勾去重时同一展示名可以有多行
  （各站原写法 / 同站多版本），这些行会互相顶替——`merged[0]` 直接被换成另一行
  （站点/链接/时长全串台）。改为**按行号回填**：`todo_index` 记下待补行的下标，
  `gather` 结果按 `zip(todo_index, enriched)` 写回。行号是唯一稳定的身份，番号不是。
- **「命中即停」让曾用名下的作品整批漏掉**。各 fetcher 都是「按名字顺序试、命中即
  返回」，所以 §10.22 抬 `_MIN_NAME_VARIANTS` 上限只解决了「名字被截断」，没解决
  「只用第一个命中的名字」。新增 ContextVar `_ALL_NAME_VARIANTS`，由 `_run_source`
  把整份名单拆成**逐个名字的多轮请求**再归总（`_accumulate_hits` 只按原键累加、
  不重算键，理由同 §10.22）。三个配套细节：① 每个名字独享一份 `source.timeout`
  预算，某个名字超时只跳过它；② 官网 fetcher 读 `_OFFICIAL_NAMES` 而不是入参，
  每轮必须把它收窄成 `(name,)`，否则每轮都把全部名字重搜一遍；③ 这条路径**不再
  整站重试**——每个名字各有一次完整机会，全空说明站点不可达，再跑一遍只翻倍耗时。
  落点选在 `_run_source` 而不是逐个 fetcher：70 站自动接入，新增刮削器也自动生效。
- **未勾去重时 7mmtv 不与别站合并是预期结果**。7mmtv 按 `detail_url` 为键保留每条
  网页条目（§10.22），URL 键与其它站的 spelling 键天然不相等，所以它的条目全部
  独立成行、日志里「独占」数等于取号数。这是「不去重」的字面效果，不是漏合并。
- **已知未改**：ThePornDB 的 `get_number` 用「厂牌.年.月.日」构造欧美番号，同厂牌
  同日的多部 scene 会共用一个番号。那是全 App 的欧美命名约定（NFO/文件名同源），
  不是去重开关的职责，改它会牵动刮削主链路，故本轮不动。

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
- **发布目标只有公开仓库**：默认 `z291173301/MDCx`，可用仓库变量 `MDCX_PUBLIC_REPO` 覆盖；目标分支默认 `main`，可用 `MDCX_PUBLIC_BRANCH` 覆盖。私有开发仓 `MDCx-Beta` **不创建 Release**，本仓库 `GITHUB_TOKEN` 只有 `contents: read`；跨仓库写全程用 PAT `MDCX_SYNC_TOKEN`。
- **产物绝不能走 Actions artifacts（账户级配额硬阻断）**：Actions artifact 存储是**账户级**、按整个计费周期的 **GB-小时累计**（Free 500MB，与 Packages 共享）。删产物、设 `retention-days: 1` 只降低当前占用，**不退还本周期已累计用量**，配额 6–12 小时重算的也是累计值；账户无有效支付方式时，配额耗尽会硬阻断上传直到下个计费周期，报 `Artifact storage quota has been hit. Unable to upload any new artifacts.`——重试/清理/缩短保留期都解不开。
  - 唯一根治：**发版链路完全不调用 `actions/upload-artifact` / `download-artifact`**。改用公开仓库一个临时 **draft Release** 做中转：Release assets 不计入 Actions/Packages 存储配额。
  - 流程：`init-matrix` 建草稿（`tag=mdcx-staging-<run_id>-<run_attempt>`，draft、非纯数字 tag 会被客户端 `check_version` 跳过，也不进 latest/atom），输出 `staging_tag` / `staging_release_id`；三平台构建后按 **release id** 直传 `uploads.github.com`；`publish-release` 按 **asset id** 走 REST + curl 下载到 `dist/`（草稿没有 git tag，按 tag 上传/下载都不可靠）；后续核对、重命名、正文、删旧建新逻辑不变；`cleanup-staging` 用 `always()` 无论成败都删掉草稿与残留 tag。
  - 「删旧 Release」的过滤显式跳过 `mdcx-staging-*` 前缀，避免误删中转草稿。守卫 `test_build_assets_bypass_actions_artifact_quota`。
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
- PyYAML 6.0.4 起已有 cp315 wheel（含 libyaml C 扩展），dev 组显式钉 `>=6.0.4`，3.15 下直接装官方 wheel；`PYYAML_FORCE_LIBYAML` 兼容开关已从所有工作流移除。工作流另设 `UV_NO_SYNC: "1"`。

### 14.4 五条护栏

1. **缺产物不发版**：`build-app` 不设 continue-on-error（设了会让 `needs.build-app.result` 恒为 success，上传全失败仍会触发发版）；其余腿不阻塞靠 `strategy.fail-fast: false`。`publish-release` 用 `if: !cancelled() && needs.build-app.result == 'success'`，从草稿中转 Release 下载后先核对三平台产物非空，再删旧 Release、建正式 Release。
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

---

## 18. 专题调研与实现笔记（2026-11-15 ~ 2026-11-16）

> 本章由仓库根目录 `development.md` 于 2026-11-18 整体合并而来，原文件已删除。
> 内容是按日期的专题调研、实测结论与实现记录，与前面 1–17 章的架构说明与纪律口径互补；
> 章节标题保留原始日期，层级整体下移一级，正文未作删改。

### AIO 三站（AVMOO / AVSOX / AVHeat）的错误信封与重试（2026-11-16）

tellme.pw AIO 平台（avmoo.shop / avsox.click / avheat.shop）是一套 Yii2 后端，三站接口形状一致：

```
POST {root}/{namespace}/data/api/search          body=[{"search": 番号, "lang": "cn"}, 60, 1]
POST {root}/{namespace}/data/api/getMovie        body={"movieId": ...}
POST {root}/{namespace}/data/api/getFilterMovies body=["star", starId, "cn", 60, page]
```

命名空间按站分：`jav`（有码，AVMOO）、`javu`（无码，AVSOX）、`wav`（欧美，AVHeat）。

**错误信封（关键）**：后端处理不过来时返回的是 **HTTP 200 + 应用级错误体**：

```json
{"code": 500, "message": "Unable to complete the request. Please try again later.", "data": null}
```

这是本平台最容易踩的坑，三条推论：

1. **HTTP 层不会重试**——状态码是 200，传输层只看 5xx/网络异常/挑战页。必须由业务层识别 `code`。
2. **不能当成「查无此片」**——`data` 是 `null` 不是空列表，按「空结果」处理会把后端抖动当成查无此番。
3. **不能只看 body 里有没有 `"data"` 字符串**——错误信封恰好带 `"data": null`，任何 `"data" in text` 的判定都会把故障误判成正常。

三条已修的地方：

| 位置 | 旧行为 | 现行为 |
|------|--------|--------|
| `crawlers/aio_api.py`（新增协议层） | 无 | 识别错误信封 + 异步/同步两套退避重试（1s / 2.5s，共 3 次） |
| `controllers/main_window/json_view.py` 查看JSON | 一次裸 POST 到写死域名，无 Cookie、无重试 | 动态域名（tellme.pw 发布）优先 + 静态/用户配置域名兜底，GET 预热 `_csrf` Cookie 后 POST，命中信封退避重试，失败给可读文案 |
| `core/network_check.py` `_classify_aio_api` | `'"data"' in text` 即判「连接正常，刮削正常」 | 按 `code` 判定，`code != 200` 判为异常并带出后端原文 |
| `crawlers/av{moo,sox,heat}_api.py` | 后端抖动 → 「未找到匹配: XXX」 | 走同一协议层重试 |
| `tools/actor_sources.py` AIO fetcher | 翻页遇错 → 直接 break，**静默少一批番号** | 识别信封重试，中断时写日志报原因 |

**实测特性**：AIO 平台被并发打满时会直接掐 TLS（`curl: (35) BoringSSL SSL_connect: Connection closed abruptly`），单站顺序请求稳定返回 `code=200`。所以「Official·JSON」批量点「查看JSON」一次开二十多个窗口时，这三站最容易翻车——**别把并发度当成无成本的事**。

**域名**：三站地址由 tellme.pw 的 `__AIO_SITE_URLS__` 发布（`base/web.py::get_aio_domain`，1 天内存缓存）。爬虫走动态域名；查看JSON 现在也走（`base/web_sync.py::get_aio_domain_sync`）。

### 浏览器操作默认使用 Microsoft Edge（2026-11-16 用户定规）

凡是需要操作浏览器的动作——联网调研站点搜索入口、打开搜索页验证参数、查看渲染后的 DOM、点选年龄门 / 翻页、核对详情页链接——**一律默认使用 Microsoft Edge**，不用 Chrome、不用系统默认浏览器、也不用 `webbrowser.open()` 的隐式默认浏览器。

| 项 | 值 |
|----|----|
| 可执行文件 | `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` |
| 本机版本 | 157.0.4341.60（2026-11-16 实测） |
| 代理 | Playwright `proxy={"server": "http://127.0.0.1:7897"}`；命令行 `--proxy-server=http://127.0.0.1:7897` |
| Playwright / Browser Use | 显式 `executable_path=EDGE`（或 `channel="msedge"`） |

具体用法：

- **首选（2026-11-16 本机实测可用）**：用 Playwright 驱动本机 Edge，指定 `executable_path`：

  ```python
  from playwright.sync_api import sync_playwright

  EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
  with sync_playwright() as p:
      b = p.chromium.launch(
          executable_path=EDGE,
          headless=True,
          proxy={"server": "http://127.0.0.1:7897"},
          args=["--no-sandbox", "--disable-gpu", "--disable-blink-features=AutomationControlled"],
      )
      pg = b.new_page()
      pg.goto(url, wait_until="domcontentloaded", timeout=25000)
      html = pg.content()  # 渲染后 DOM
  ```

  SPA（Next.js `__NEXT_DATA__` / RSC payload）站点必须走这条路，纯 curl 只能拿到空壳。
- **命令行 headless 取 DOM 不可用（同日实测）**：`msedge.exe --headless=new --dump-dom <url>` 退出码 0 但 stdout 恒为 0 字节（`--screenshot` 也不落盘），**不要用它抓页面**；自动化一律走上一条 Playwright。
- **人工可见验证**：`headless=False` 起真实 Edge 窗口，按页面实际呈现确认搜索框、参数、分页与入口。
- **不需要渲染的批量取数**：仍用项目既有的 `curl_cffi` / `httpx` 通道（爬虫与 `actor_sources` 同口径），但**「这个入口能不能用」的结论必须以 Edge 打开验证为准**，不能只凭 HTTP 200 下结论。
- 本规则同时写入 `docs/MEMORY.md`「本机环境」段；两处口径一致，改动时同步。

### 聚合/综合站「按演员名搜番号」调研（2026-11-16，Edge 实测）

本轮 9 站：`FreeJavBT`、`Jav321`、`Lulubar`、`AVEntertainments`、`R18.dev`、`AVBase`、`7mmtv`、`Airav.cc`、`Xcity`。
全部结论由 Microsoft Edge（headless + 本机代理 7897）实际打开页面得到，不凭 HTTP 200 下结论；
成果落在 `mdcx/tools/actor_sources.py` 的 `_SITE_FETCHERS`（「检查演员缺失番号」工具），
URL 模板同时可供刮削层 `_generate_search_url` 复用。

#### 否定结论：R18.dev 不用管

**`R18.dev` / `R18_JSON` 没有通过演员名搜索番号的功能，不实现 fetcher、不再调研**
（用户 2026-11-16 定规，同日 Edge 实测确认，已同步写入 `docs/MEMORY.md`）：

| 试过的入口 | 结果 |
|------------|------|
| `/videos/vod/movies/search/-/keyword=<名字>/json` | 404 Not Found |
| `/videos/vod/actress/list/-/page=1/json` | 404 Not Found |
| `/videos/vod/actress/detail/-/name=<名字>/json` | 404 Not Found |
| 首页 `/videos/vod/movies/list/?id=<id>&type=actress` | 存在，但只认**已知 actress id**，站点没有「演员名 → id」的查询接口 |

站点能力只有按番号直连详情 `/videos/vod/movies/detail/-/dvd_id=…/json`（`crawlers/r18dev.py` 已实现），
刮削行为保持不变；查缺工具不为它注册 `_SITE_FETCHERS`，构建源时按既有逻辑跳过并在日志说明。

#### 逐站实测结论（URL 模板可供刮削层复用）

| 站 | 搜索入口 | 番号位置 | 分页 | 本轮处理 |
|----|----------|----------|------|----------|
| FreeJavBT | `GET /zh/search/{kw}?page=N`（表单另有 `/zh/search?wd=`） | 详情链接末段 `…/IPX-605` | `page=N`；白峰美羽 44 页，page=1/2 内容不同 | ✅ 复核通过，页上限 10 → `_MAX_PAGES` |
| Jav321 | 搜索框**只收番号**（`POST /search` 字段 `sn`）；演员入口是 `/star/{star-id}/{page}`，star-id 从详情页「出演者」链接 `/star/1066537/1` 取 | `div.thumbnail//a` 文本末尾番号（`pbd-529`） | `<li class="next">`，实测 `/star/1066537/2` → `/3` | ✅ 复核通过（两步法依赖 JavDB 可达），页上限放宽 |
| Lulubar | `GET /video/bygirldetail?name={演员名}&page=N`（等价 `?id={id}`，索引页 `/video/bygirl?page=N`）；**`/video/bysearch?search=` 稳定 403 CF，不可用** | `a.imgBoxW > img` 的 `alt`/`title` 开头 `ADN-814 - …`，详情链接 `/video/detail?id=…` | `page=N` | 🆕 新增 `_fetch_lulubar` |
| AVEntertainments | `GET /dvd/search?lang=2&cat=29&keyword={名}&searchby=starring&page=N`（等价 `/dvd/idoldetail?lang=2&cat=29&idol={名}`） | 搜索页 `pro=<id>` 是站内 ID；番号在详情页 `//span[@class="tag-title"]`（`GLDV-006`，与爬虫同去 `DL` 前缀） | `page=N` | 🆕 新增 `_fetch_aventertainments`（并发 5，共用 `manager.config.aventertainments` verifybot Cookie） |
| R18.dev | 无 | — | — | ❌ 不接入（见上） |
| AVBase | `GET /works?q={kw}&page=N`，Next.js SSR | `<script id="__NEXT_DATA__">` 的 `props.pageProps.works[]`（`work_id` 优先）＋ `href="/works/{番号}"` 回退；`pageProps` 另带 `total` / `page` | `page=N` | 🔧 重写分页与内嵌 JSON 解析；连打会 CF 403，空结果不得把 `urbopack-25` 之类 CSS 类名当番号 |
| 7mmtv | `GET /zh/searchform_search/all/index.html?search_keyword={kw}&search_type=searchall&op=search` | 详情链接末段 `/…/ATID-705.html` | 站内分页 | ✅ 复核通过（200，8 个番号） |
| Airav.cc | `GET /cn/search_result?kw={kw}` | `div.oneVideo-body//h5` 文本开头番号（实测 60 条）；`hid=QC-BT-…` 是广告/内部 ID，不能当番号 | 站内分页 | ✅ 复核通过；`Website.AIRAV`（值 `airav`）复用同 fetcher 只改标注 |
| Xcity | `GET /api/search?q={日文名}&type=0&page=N` | `frontprogramlist.program[].itemcode` | `page_ctrl.has_next` | ✅ 复核通过（鈴村 愛里 返回 50KB）；中文名/假名返回 `{"frontprogramlist":null}` 属数据问题，不是接口故障 |

补充说明：

- **刮削层暂未改动**：`mmtv_json.py` / `avbase_json.py` / `airav_json.py` 的 `_generate_search_url` 目前是 `NotImplementedError`（刮削走详情直连，由 `DIRECT_PROBE_SITES` 钉死）。上表 URL 模板可直接复用到这三个爬虫，本轮只落在 `actor_sources.py`，避免牵动网络检测探测口径。
- **自动判断固定链不动**：`_AUTO_SITE_ORDER` 由 `tests/test_actor_missing_numbers.py::test_auto_site_chains_match_user_spec` 精确钉死；新站走「指定类型 → 类型刮削网站」配置组生效（默认无码组含 `AVEntertainments` / `Lulubar`，有码组含 `FreeJavBT` / `Jav321` / `7mmtv` / `Airav` / `Xcity` / `AVBase`）。2026-11-17 起 `build_sources` 不再给固定链追加官网 JSON 版，固定链即全部请求范围（官网只在「官方网站」类型下补齐）；元数据补齐也只打本行来源站详情页，见 `tests/test_actor_sources_filter.py`。
- **既有硬约束不变**：每站最多重试一次（`collect_numbers` 统一控制）、各站番号先 `normalize_key()` 归一再与本地库比较（`DSOD-012` → `DSOD12`，写断言时别按展示形拼 key）。
- **测试夹具**：`tests/crawlers/data/actor_sources/` 下的 `lulubar_girl.html` / `avent_search.html` / `avent_detail.html` / `avbase_works.html` 均由 Edge 打开真实页面后裁剪得到；回归在 `tests/test_actor_sources_sites.py`。

### 「检查演员缺失番号」全链路审查与修复（2026-11-16）

本轮又用 Edge 抽查了 IQQTV / JavDay / Madou.club / FC2 / FC2CMADB / JavFree / JavBus 的搜索页与分页形态，
沿「工具页入口 → `missing.py` → `actor_sources.collect_numbers` → 各站 fetcher」逐层审查。
下表只列**代码里能指出确凿证据**并已修复的条目，回归见 `tests/test_missing_audit.py`：

| # | 问题（ Evidence ） | 修复 |
|----|---------------------|------|
| 1 | 本地对比用全局 `Flags.local_number_set`，该集合跨次运行从不 `clear()`；删片或换库后旧番号仍被当成「本地已有」→ 漏报缺失 | `_check_missing_number_impl` 用本次 `local_movies` 构造 `local_keys`，传给 `_report_actor_result`（不传时保留旧回退） |
| 2 | `number_list.json` 空文件 / 写了一半的 JSON / 非字典内容会让 `json.loads` 抛异常；`executor` 不读 Future 异常 → 任务崩溃但界面「点了没反应」 | 读取包 `except (OSError, ValueError, TypeError)`，回退空缓存并打日志；首次写 `"{}"` 失败也不会连锁 `FileNotFoundError` |
| 3 | 扫描循环里**每部影片都全量重写整份缓存 JSON**（1000 部 = 1000 次整文件写），两个并发查缺任务还会各持快照互相 `os.replace` 覆盖 | 循环内只累积，循环结束后一次性 `_try_write_cache_async` |
| 4 | 前缀剥离 `re.findall(r"\d{3,}([a-zA-Z]+-\d+)")` 把 `300ABCD-123-2` 截成 `ABCD-123`、对 `123FC2-PPV-1234567` 完全不去前缀 | 抽 `_strip_number_prefix()`，用 `^\d{3,}(?=[A-Za-z])` 只削开头数字，保留分集后缀与多连字符番号 |
| 5 | FC2 类型填的是**卖家名**（文件头与 `_parse_actor_entry` 都写明），却与动漫不同、被兜底写进 Excel「演员」列 | `_TYPES_WITHOUT_ACTOR_FALLBACK` 补 `FC2` |
| 6 | `Website.MYWIFE` / `MYWIFE_JSON` 未登记 `_SITE_GROUPS`，`_run_group` 的 `fallback_for` 短路只看组内结果 → JSON 已命中时网页版仍重复请求同一后端 | 两者登记为同组 `mywife` |
| 7 | `_run_source` 把一切异常压成 `{}`，页面改版 / `KeyError` 被显示成「该站未取到番号」；`missing.py` 演员级异常只打 `str(e)` 就 `continue`，末尾照常打印「查询完毕」 | 异常写主日志（站点名 + 异常类型）；演员级异常追加 `traceback.format_exc()` 并标红 |
| 8 | JavDay 只取搜索第一页；Edge 实测分页 `/search/page/{n}/wd/{kw}/` 共 4 页，第 2 页番号（`WAAA-576` 等）与首页完全不重叠 | `_fetch_javday` 加分页循环，无新番号即停；真实两页裁剪成 `javday_p1/p2.html` 夹具 |
| 9 | FC2 站内搜索不带 Cookie 直接 302 到 `fc2.com/cn/login.php`；`crawlers/fc2_json.py` 早有同款 Cookie 口径但查缺没用 | `_fetch_fc2` 复用 `manager.config.fc2` → `fc2_cookie_to_dict()`，搜索页与卖家页都带上 |
| 10 | `_cell_date` 的 `except TypeError, ValueError:` 是 Python 3 合法的 tuple 写法（AST / 导入均正常），但极易被误读成 Python 2 语法 | 括号化 `except (TypeError, ValueError):`，不改行为 |
| 11 | 工具页类型下拉新增「官方网站」后要有完整链路 | `MDCx.ui` → `MDCx.py`（pyuic6 + ruff format 最小 diff）；`_FORCED_TYPE_BY_COMBO` / `_ACTOR_TYPE_TO_SCRAPING[官方网站]=OFFICIAL` / `_TYPE_DISPLAY` / Excel 类型列同步。官网组 34 站里 32 个 studio 详情页无演员索引会被跳过并在日志说明，实际可用 6 源 |

**刻意未改（记录口径，别当漏项）**：

- 重试模型：`_run_source` 重试的是**整段 fetch**（含翻页 / 名字变体 / 详情页），`_fetch_xcity` 内部还有单页 3 次重试，与文件头「每站最多两次请求机会」的措辞不完全一致。改它会动到所有站的可用性与超时预算，本轮不动，只留此说明。
- FC2CMADB `/search?keyword=` 实测返回 39 字节空响应、Madou.club `?s=` 对日文演员名返回无结果页、JavBus `/searchstar/白峰美羽` 404（该站用日文名）：属站点数据 / 反爬 / 名字写法问题，代码均已优雅降级返回空，不改解析。
- 协作式取消与 `finally` 里的全局按钮复位涉及 UI 信号与并发任务状态，用户未点名，按「界面没有要求的不要自作主张修改」保留。

### 厂牌官网按演员名搜番号（2026-11-16，Edge + curl_cffi 实测）

「官方网站」类型下拉此前只能查到 5 家无码官网 JSON 版 + MyWife，34 家有码厂牌官网全是
studio 详情页、没有演员入口，查缺时全部被跳过。本轮给厂牌官网补上「按演员名列全部作品」。

#### 入口表：29 家同源 CMS（`mdcx/crawlers/sites_official/` 29 家）+ DAHLIA

这些站共用同一套 CMS，站内搜索形态完全一致：

| 项 | 实测值 |
|----|--------|
| 搜索入口 | `{base}/search/list?keyword={关键字}&countup=0`（SSR 直出结果，无需浏览器渲染） |
| 作品链接 | `{base}/works/detail/{番号}`，**番号在 URL 末段且多为无连字符形态**（`ONSD340` / `DLDSS581` / `IPX-605`） |
| 分页 | 同一 URL 追加 `&page=N`，每页 30 条 |
| 演员名 | **演员名可直接当关键字**，命中该演员全部作品（无需先找演员 id） |
| 名字写法 | 站是繁体站 → 依次试「原样 → 繁体 → 简体」三种写法（`_brand_name_variants`） |
| 编号对齐 | 站内无连字符 vs 本地库带连字符，`normalize_key()` 两侧都能对齐（`ONSD340` == `ONSD-340`） |

覆盖清单（29 家同源 + DAHLIA = 30 站）：S1S1S1 / Moodyz / Madonna / Wanz / Ideapocket /
Kirakira / E-Body / Bi / Premium / Miman / Tameikegoro / Fitch / Kawaii / Befree / Muku /
Attackers / MKO / Dasdas / MVG / Opera / Oppai / V-AV / To-satsu / Bibian / Honnaka /
Rookie / Nanpa / Hajimekikaku / HHH / Dahlia。

实现落在 `actor_sources._official_brand_fetcher(site, base)` 工厂 + `_OFFICIAL_BRAND_SITES` 表，
注册进 `_SITE_FETCHERS`（在 `_SITE_FETCHERS_FC2` / `_WUMA` 两个变体字典之前 update，
免得 FC2 / 无码组漏掉）。各站域名不同 → 不进 `_SITE_GROUPS`，默认各自独立组并发。

**证据强度**（分两档，如实记录）：

- 29 家**搜索路径全部用站内探测番号实测可用**（`/search/list?keyword=` 200 且有作品链接）。
- 其中 23 家另用「详情页取到的站内真实演员名」实测命中（例：S1「橋本ありな」→ 178 个番号、
  Attackers「夏目彩春」、Madonna「水戸かな」、Premium「山岸逢花」、Dasdas「水川スミレ」…）。
- 余下 6 家（Kirakira / V-AV / To-satsu / Nanpa / Hajimekikaku / HHH）没有女优索引页
  （`/actress/a` 恒 404），详情页「女優」行结构与其它站不同，没能取到名字做端到端验证；
  它们的搜索路径已用番号验证可用，且实现与其它 23 家是同一份代码。

#### 端到端实测（真实网络）

```
collect_numbers("官方网站", ["波多野结衣"], use_config_sites=True)
→ 38 个站点参与（37 组并发），36.9 秒，合并去重后 1453 个番号，25 个站点有贡献
```

单站耗时参考：S1S1S1 178 个番号 / 4.3 秒、Madonna 261 个 / 6.8 秒、MGStage 366 个 / 4.3 秒、
Faleno 27 个 / 1 秒、Kawaii 12 个 / 2.2 秒；30 家厂牌官网同时并发总耗时 13.4 秒（无卡死站点）。

**单站超时上限**（`_SITE_TIMEOUTS`）：厂牌官网 45 秒、MGStage 60 秒（每页约 1MB、要翻 4 页）、
Faleno 45 秒。超时由 `_run_source` 直接收手**且不重试**，个别站卡住不会把整轮查缺拖成好几分钟。

#### 另外两家：独立系统（不是 S1 系同源 CMS），单独实现

| 站 | 演员名入口 | 番号位置 | 备注 |
|----|------------|----------|------|
| `Official·MGStage` | 主入口 `https://www.mgstage.com/search/cSearch.php?search_word={演员名}&type=top&list_cnt=120&page={n}`（站内关键字搜索）；兜底 `…/cSearch.php?type=top&list_cnt=120&actor[]={演员名}_0&page={n}` | 作品链接 `/product/product_detail/{番号}`（番号带连字符，如 `287HZGD-285`） | **必须用日文原名**：繁体「波多野結衣」命中 120 条，简体「波多野结衣」一条不中（站是日文繁体站）→ 查缺侧用 `_official_name_candidates` 依次试「用户输入的写法（原样/繁/简）→ 演员库的日文原名」。**以关键字搜索为准**：演员筛选（`actor[]=`）对「涼森れむ」只给 150 部，站内关键字搜索给 152 部（少的 2 部 KRNK-005 / KRNK-010 确实是她的作品，作品页出演者里有她，只是演员筛选没收进去），与页面标称「152タイトル中　1～120タイトル　1ページ目を表示」一致。首次访问可能返回年龄认证页，按 `crawlers/base/age_gate.py` 的成人入口规则点一次（只选 18+ 入口）后**必须回头重取原来的搜索页**——成人入口指向首页（`./`），直接解析它的内容会拿到首页推荐番号（152 → 149、首页 120 → 117） |
| `Official·Faleno` | `https://faleno.jp/top/wp-json/wp/v2/works?search={演员名}&per_page=100&page={n}` | `acf_custom_images.main_photo_url` 里的标准形态（`FNS-277`），取不到用 slug 还原（`fns277` → `FNS-277`） | 站点是 WordPress，`search` 能命中 `acf.出演女優`（实测「つばさ舞」27 条、「藤沢なみえ」1 条，与演员页列出的作品数一致） |

实测：MGStage「波多野结衣」366 个番号、Faleno「つばさ舞」27 个番号；
官网组从 6 个源涨到 **38 个源**、`skipped` 清零（34 家厂牌官网全部可按演员名查缺）。

#### 官网按名字查：只用日文原名 + JavDB 兜底（2026-11-16 改）

官网的站内搜索基本只认**日文原名**：用户填「凉森玲梦」这种中文名时，MGStage 一条都搜不到
（该站演员栏写的是「涼森れむ」，中文名 / 繁体名 / 别名一律 0 命中）。既然输入原名注定 0 结果，
就没有必要先拿它去 30 多家官网各发一轮请求——**直接跳过**。

现在的流程（`mdcx/tools/actor_sources.py`）：

1. `collect_numbers` 在并发跑站点**之前**调 `_prepare_official_names()` 统一解析一次名字，
   结果放进 ContextVar `_OFFICIAL_NAMES`，各 fetcher 通过 `_official_name_candidates()` 同步读取
   （避免 30+ 个官网各自重复发 JavDB 请求）。名字变体通常只是同一人的不同写法，
   JavDB 兜底一轮只做一次。
2. `userdata/actor_database.xlsx` 能转出日文原名 → **以它为首位**（输入名本来就是日文原名时也用它，
   两者相等，语义一致），不再拼用户输入的原样/繁简变体。
   若同一行 keyword 里还有**汉字+假名的日文艺名别名**，排在后面兜底：库的「日文原名」列
   可能是旧艺名（实测「新有菜」→「橋本ありな」），而官网按现艺名「新ありな」收录，
   只用库给的值会漏。别名经 `_official_jp_aliases` 严格过滤：排除输入原名及繁简变体、
   排除纯假名读音（すずもり れむ）与罗马字（Arina Hashimoto）——这些不是官网搜索写法，
   加进去只会凭空多一轮翻页请求，最多取 2 个。
3. 库里查不到 → 新增的 `mdcx/core/actor_name_javdb.py` 走 **JavDB / JavDB_JSON** 兜底：
   - JavDB_JSON 移动端签名 API `/api/v2/search?q={名}&type=actor`（需登录 token）直接给演员 id；
     API 不可用/未登录时退回网页搜索 `/search?q={名}&f=actor` 取 `/actors/{id}`
     （该页偶发被限流跳登录页，故按输入名 + 繁简变体依次重试，并用标题识别登录页）；
   - 抓演员页解析：`<span class="actor-section-name">新有菜, 新ありな</span>` → 日文原名
     `新ありな`（优先含假名且与输入名不同的项；两个都不含假名时按 JavDB 显示名取），
     `<span class="section-meta">橋本ありな, 上乃木まな, …</span>` → 别名，
     `325 部影片` → 作品数（仅用于日志核对）；
   - 候选顺序 = 日文原名 → 别名（最多 3 个），**用户输入的原名一律剔除**，
     各官网「按候选顺序搜、命中即返回」，所以别名只在日文原名搜不到时才用上。
4. 演员库和 JavDB 都拿不到 → 保留一条输入名兜底并在日志里明确说明，避免官网组整轮 0 结果。

> **【已废止】2026-11-20 用户定规**：``actor_database.xlsx`` 的数据可能有错，
> 「从它取演员原名」的功能与逻辑已整体删除（``mdcx/core/actor_name_map.py`` 移除，
> ``actor_sources`` 里 4 处调用、``resolve_actor_names`` 自动扩展、官网 JavDB 兜底
> 一并删除）。因此上面 1–4 的官网候选来源不再成立：现在官网搜索名直接取本轮名字，
> 未勾「获取演员原名」只有用户手动输入名，勾选时是它加上 JavDB 取到的全部原名。

两个独立模块（其它功能/函数可直接 import）：

```python
from mdcx.core.actor_original_names import fetch_actor_original_names, actor_name_variants, join_original_names
from mdcx.core.actor_name_javdb import parse_actor_page, parse_actor_api, resolve_jp_names_via_javdb

names = await fetch_actor_original_names("新有菜")  # → 6 个名称（JavDB_JSON 优先、网页版兜底）
actor_name_variants("新有菜", names)  # → 用户输入名 + 全部原名（取号用）
join_original_names(names)  # → "新有菜,新ありな,..."（英文逗号回填输入框用）
```

实测（真实 HTTP 通道 + 代理 7897）：MGStage 用「涼森れむ」拿到 **152 部**（首页 120 + 次页 32），
与站点标称一致。另：系统代理模式下所有有码官网均可正常访问，S1 搜索页「波多野結衣」0 结果
是她已引退下架，不是网络问题——现役「白上咲花」同接口能搜到 30 部。

#### HTTP 传输层错误透传

`_http_text` / `_http_json` / `_http_json_list` / `_http_post_json` 原先丢弃底层 `_error`，
代理端口写错时 30+ 站点全部静默返回空，界面只显示「0 个番号」。现在经 `_report_http_error`
把 `curl: (7) Failed to connect ... over proxy` 原文送到日志面板，并提示核对代理端口
（Clash 默认 7890 / mihomo 常用 7897）；按错误指纹去重，一轮查缺同类错误只报一次、
总数封顶 8 条，避免刷屏。超时、组内单站异常、站点组整体异常也都记日志，且不会让整轮查缺崩掉。

#### 与刮削层的关系

厂牌官网爬虫的 `_generate_search_url` 是「按番号搜详情页」，与演员名搜索是两回事，**本轮未改刮削层**；
上表的 URL 模板（S1 系 `{base}/search/list?keyword=`、MGStage `cSearch.php?search_word=`（兜底 `…&actor[]=`）、
Faleno `wp-json/wp/v2/works?search=`）可直接复用，后续要在刮削层支持关键字检索时直接用。

### UI 生成流程（MDCx.ui → MDCx.py）

`mdcx/views/MDCx.py` 和 `mdcx/views/posterCutTool.py` 是 Qt Designer 生成的 Python 代码，**禁止手动编辑**。修改 UI 文案/布局后必须立即执行：

```bash
pyuic6 mdcx/views/MDCx.ui -o mdcx/views/MDCx.py
pyuic6 mdcx/views/posterCutTool.ui -o mdcx/views/posterCutTool.py
python scripts/fix_qt_enums.py mdcx/views/MDCx.py mdcx/views/posterCutTool.py
```

最后一步 `fix_qt_enums.py` 修复 PyQt6 6.11+ 的枚举兼容性（旧 pyuic6 生成 flat enums 会在新 PyQt6 上报 AttributeError）。

**注意**：只改 `.ui` 文件不重新生成 `.py` 会导致界面看起来完全没变——这是最常见的 UI 修改踩坑。

**生成到临时文件、比对后再替换（2026-11-16 定规）**：本机 pyuic6 生成的代码与入库版本会差一两行无关内容（生成器版本不同带来的路径写法等）。直接覆盖会把这些无关差异一起带进 diff。正确做法是先生成到临时文件、格式化后比对，确认只多出本次改动再替换，并手工还原生成器带来的无关差异：

```bash
pyuic6 mdcx/views/MDCx.ui -o /tmp/MDCx.py   # 生成到临时文件
ruff format /tmp/MDCx.py                     # 与入库版本同样式
diff /tmp/MDCx.py mdcx/views/MDCx.py         # 确认只多出本次改动
```

### 站点分组常量（config/models.py）

删除或重命名官网站点后，以下常量必须同步更新，否则 Official·uncensored / Official·pixelated 分组行显示 0 站：

| 常量 | 内容 | 使用场景 |
|------|------|----------|
| `OFFICIAL_CENSORED_SITES` | 33 家有码官网**网页版**（无 JSON 站） | `OFFICIAL_CENSORED_GROUP_SITES` 的网页部分 |
| `OFFICIAL_CENSORED_JSON_SITES` | `Official·MyWife_JSON`（唯一有码官网 JSON 版） | 与网页版合成展示组 |
| `OFFICIAL_CENSORED_GROUP_SITES` | = `CENSORED_JSON_SITES + CENSORED_SITES`（34 站） | **指定网站 `Official` 聚合展开、字段优先级、官方网站源候选区**；网络检测页同名分组行**不用**它 |
| `OFFICIAL_UNCENSORED_SITES` | 无码官网网页版（已删 → **空 tuple**） | 仅兼容 |
| `OFFICIAL_UNCENSORED_JSON_SITES` | TENMUSUME / CARIBBEANCOM / HEYZO / PACOPACOMAMA 共 4 个 | **实际使用** |
| `OFFICIAL_UNCENSORED_GROUP_SITES` | = `UNCENSORED_SITES + UNCENSORED_JSON_SITES`（4 站） | Official·uncensored 分组成员 |

**四个下拉分组的成员选择**（`_net_filter_group_members()`，`init.py`）：

| 分组 | 成员常量 | 按钮通道 |
|------|----------|----------|
| Official·HTML | `html_all_members()`（动态，全部网页） | 保存HTML + 浏览器 |
| Official·JSON | `json_group_members()`（动态，JSON_VIEW_SITES A-Z，**24 站**） | 查看JSON + 浏览器 |
| Official·pixelated | **`html_view._html_group_members()[HTML_GROUP_PIXELATED]`（33 网页，不含 MyWife_JSON）** | 保存HTML（批量同源 33 网页） + 浏览器 |
| Official·uncensored | **必须** `OFFICIAL_UNCENSORED_GROUP_SITES`（4 站 JSON） | 查看JSON + 浏览器 |

**关键约束**（2026-11-15 全量核对后定稿，同日二次口径修订）：

- **两个「有码官网」名单刻意不同，别混**：指定网站下拉的 `Official` 聚合用
  `OFFICIAL_CENSORED_GROUP_SITES`（34 站＝33 网页 + `Official·MyWife_JSON`），
  服务于刮削展开/字段优先级；网络检测页的 `Official·pixelated` 分组行只收
  **33 家网页官网**，成员直接复用 `_html_group_members()[HTML_GROUP_PIXELATED]`。
  用户 2026-11-15 要求把 `Official·MyWife_JSON` 从网络检测页该组移除：它独立行右侧是
  「查看JSON」，混在官网组里会与本组的「保存HTML」批量冲突。
  注册表里所有 `Official·` 开头的真实站点必须恰好落进两个**刮削组**之一，
  由 `tests/test_official_group_coverage.py` 双向钉死。
- `Official·MyWife_JSON` 仍**同时**属于 `Official·JSON`（24 站）与刮削层
  `OFFICIAL_CENSORED_GROUP_SITES`（34 站），跨组复用是刻意的：按 JSON 通道检测、
  按官网通道路由。`Official·JSON` 恒等于「全部已注册 `***_JSON` 刮削器」，
  加入 MyWife_JSON 后仍是 24 站，不要重复加。
- 网络检测页分组行成员（33）与「保存HTML」批量成员（33）**必须相同**：
  `init._net_filter_group_members()` 复用 `_html_group_members()`，
  后者从 `OFFICIAL_CENSORED_GROUP_SITES` 里剔除所有 `JSON_VIEW_SITES` 成员，
  于是勾选展开、行标题计数、批量保存三处永远同源，新增有码官网 JSON 版也不会被误当网页站保存。
- `Official·MyWife` 网页版单站行右侧是「保存HTML」+「浏览器」：
  `row_has_html_view()` 用 `include_hidden=True` 全量注册表判断（与该行所在下拉同源），
  因此按钮绘制、`html_view_target()`（链接地址 `https://mywife.cc/teigaku/model/no/2306`）、
  `request_html_save()` / `request_html_browser()` 一起接通；它不是 JSON 站，
  不会与 `Official·MyWife_JSON` 的「查看JSON」通道冲突。`_batch_members()` 同样用全量注册表
  校验成员存在性，避免分组行标题写 33 站却因开关关闭漏存 MyWife。
- Official·uncensored 是**纯 JSON 分组**，不再画保存HTML 按钮——必须在 `row_has_html_view()` / `row_has_html_batch()` / `_html_group_members()` 三处排除它；同时在 `row_has_json_batch()` / `row_has_json_button()` / `request_json_view_all()` / `request_json_browser_all()` 四处加入它

核心文件：

- [init.py](file:///d:/@Data/MDCx/mdcx/controllers/main_window/init.py) `_net_filter_group_members()` — 分组成员
- [html_view.py](file:///d:/@Data/MDCx/mdcx/controllers/main_window/html_view.py) — 保存HTML 按钮行判断
- [json_view.py](file:///d:/@Data/MDCx/mdcx/controllers/main_window/json_view.py) — 查看JSON 按钮行判断 + 批量入口

**下拉排序键**（2026-11-15 用户指定）：

| 下拉 | 排序键 | 说明 |
|------|--------|------|
| 「当前网站」`comboBox_custom_website` | `_net_display_sort_key()` | 按**实际显示名** A-Z |
| 网络检测筛选 `comboBox_net_site_filter` | `_net_display_sort_key()` | 同上；四个分组行仍置顶不参与排序 |
| 「指定网站」/「不走代理」 | `_site_sort_key()` | 按去前缀展示名 A-Z |

5 个官方 JSON 站在前两个下拉里保留 `Official·` 前缀（`_NET_KEEP_OFFICIAL_PREFIX_JSON`）。
若误用 `_site_sort_key()`（内部会去前缀），它们会被打散到 10/C/H/M/P 各段，与整齐排在
O 段的官网网页站混在一起，视觉乱序且看起来像「少了某站」。

**成员来源**：这两个下拉统一用 `_prefix_combo_site_values()` 取站点（已按显示名排好序），
不要用裸的 `get_registered_crawler_site_values()`。它以 `include_hidden=True` 的
全量注册表（70 站）为底，由「显示网页站点」开关决定 `DMM` / `JavDB` /
`Official·MyWife` 三站的显隐：**勾选 70 站 / 未勾选 67 站**，两态都严格 A-Z
（用户 2026-11-15 二次口径，取代上一版「MyWife 无条件显示」）。
其余界面（指定网站、编辑网站候选区、类型名单、网络检测探测项）仍走各自的开关过滤，
不受这份名单影响（下拉可见 ≠ 参与检测，两条口径不要混）。
分组行勾选展开也只覆盖下拉里真实存在的行：关闭态 DMM/JavDB 无行，
故 `Official·HTML` 批量勾选不会把它们凭空选进来。

### 「显示网页站点」/「启用刮削兜底」两个开关（2026-11-15）

用户指定两个开关共同控制 DMM / JavDB / Official·MyWife 三个**网页版**刮削器
（`Website.DMM` / `Website.JAVDB` / `Website.MYWIFE`，即 `Official·MyWife`）。

| 开关 | 关闭时 | 开启时 |
|------|--------|--------|
| `Switch.SHOW_WEB_SITES`（显示网页站点） | 三个网页版从**所有站点选择窗口**消失 | 三个网页版照常显示，排序口径不变 |
| `Switch.ENABLE_WEB_FALLBACK`（启用刮削兜底） | 三对 JSON→网页版**完全不兜底** | JSON 刮不到数据 / 字段不全时由网页版补全，图片候选随之降级下载 |

#### 涉及的常量（mdcx/config/models.py）

| 常量 | 当前值 | 说明 |
|------|--------|------|
| `SHOW_WEB_SITES_ONLY_WEB` | `{DMM, JavDB, MYWIFE}` | 「显示网页站点」关闭时要藏起来的三个网页版 |
| `SHOW_WEB_SITES_JSON_FALLBACK` | `{DMM_JSON: DMM, JavDB_JSON: JAVDB, MYWIFE_JSON: MYWIFE}` | 三对 JSON→网页版配对 |
| `AIO_JSON_WEB_FALLBACK` | = 上面三对 | 兜底配对表（`aio_web_fallbacks` / `actor_sources` 据此追加网页版） |
| `AIO_JSON_SITES` | = 三对的 JSON 键 | JSON 优先区判定；`file_crawler` 的字段补齐白名单之一 |
| `AIO_WEB_FALLBACK_SITES` | **空**（刻意） | 它会把网页版从网络检测探测项与 `Official·HTML` 组里排除——本轮三站仍要参与，故留空 |
| `AIO_WEB_FALLBACK_HIDDEN_UI_SITES` | **空**（刻意） | UI 隐藏名单改由 `SHOW_WEB_SITES_ONLY_WEB` 单独控制，不牵连其它网页版 |
| `AIO_WEB_TO_JSON_SITE` | **空**（刻意） | 它会把用户显式启用的网页版归一成 JSON 版，与「网页版仍是独立可勾选站点」相反 |

`hidden_web_sites_for_ui(show_web_sites=...)` 是 UI 隐藏的唯一口径：开关关闭返回
`SHOW_WEB_SITES_ONLY_WEB`，开启返回空集。

#### 显隐链路

`_current_hidden_web_sites()`（site_priority_dialog.py）→ `hidden_web_sites_for_ui()`，
三个站点选择窗口都在**名单构建处**过滤，而不是在渲染层过滤：

- 「可用网站：按类型分组」/「启用网站：从左到右优先级递减」→ `_open_site_editor()`
- 字段优先级弹窗顶部「可用网站」面板 + 标题/原标题/简介/原简介等每个字段行 → `_open_priority_editor()`
  （面板与各字段行的允许集合同源于 `type_sites`）
- 候选区分组 `grouped_palette_groups()` 也会剔除隐藏站，避免被分组名单重新带出来

过滤只减不增：勾选态名单与改动前逐项同序（`_sort_sites_for_priority()` 口径不变）。

**连带效应**（改配置时注意）：

- `_parse_sites()` 是所有站点名单解析的统一入口，它会剔除 `_current_hidden_web_sites()`
  里的站点。因此「显示网页站点」关闭时，设置页行输入框、编辑网站弹窗、字段优先级弹窗
  拿到的名单都不含这三个网页版。
- `_refresh_site_priority_line_edits()`（`init.py`）在保存末尾把过滤后的名单写回
  `manager.config.website_*`——即「隐藏即视为未启用」，配置里也会掉这三站；
  重新勾选开关时 `_augment()` 会按 `AIO_JSON_WEB_FALLBACK` 把网页版自动补回
  （`DMM_JSON→DMM`、`JavDB_JSON→JavDB`、`MYWIFE_JSON→Official·MyWife`），不会真的丢失。
- 这段写回发生在 `save_config.save()` 的**末尾**，会落在未授权锁的还原之后。
  故 `save_config.py` 把还原抽成 `_restore_website_snapshot()`，在解析后与
  `refresh_site_combos_after_switch()` 之后各还原一次，避免未授权时改写刮削网站配置。

#### 兜底链路

`web_fallback_for(json_site, switch_on=...)` 是受开关门控的唯一入口：开关关闭返回 `None`，
开关开启返回 `SHOW_WEB_SITES_JSON_FALLBACK` 里的网页版（LibreDMM 等其它配对不在此表内，
调用方直接查 `JSON_TO_WEB_SITE`，行为不变）。

接入点：

- `file_crawler._call_specific_crawler()` —— JSON 无数据时的**整站回退**
- `file_crawler._supplement_missing_fields()` 链路 —— JSON 有数据但缺字段时的**字段补齐**
  （封面/海报/剧照随之进入图片候选，由 `web.py` 依次降级下载）
- `file_crawler.aio_web_fallbacks(sites, enable=...)` —— 完整 / 速度优先路径把网页版追加到末尾
- `actor_sources._order_aio_sources()` —— 演员番号检查的 JSON→网页版链路

### 站点优先级排序规则

排序入口：`mdcx/controllers/main_window/site_priority_dialog.py` → `_sort_sites_for_priority()`

| 刮削类型 | 排序规则 |
|----------|----------|
| OFFICIAL（官方网站） | 全部站点 A-Z |
| OUMEI（欧美番号） | 全部站点 A-Z |
| YOUMA / WUMA / FC2 / SUREN / GUOCHAN / OUMEI / DONGMAN | 全组站点 A-Z |

JSON 刮削器判断条件：站点 value 以 `_JSON` 结尾 **或** 在 `_ALL_JSON_SITES` 集合（26 家）里。

应用位置：编辑网站对话框（`_open_site_editor`）、字段优先级对话框（`_open_priority_editor`）的 `selected_sites` / `all_sites` / `type_sites` / 每字段 `site_prority`。

### 配置版本

| 文件 | 说明 |
|------|------|
| `mdcx/config/v2.py` | Legacy INI 格式读取器（含 `ConfigV1` dataclass + `load_v1()`） |
| `mdcx/config/models.py` | Pydantic `Config` 模型，`config_version` 默认值 = 2 |
| `mdcx/config/migrations.py` | `CURRENT_CONFIG_VERSION = 2`，迁移入口 |
| `mdcx/consts.py` | `LOCAL_VERSION`（数值日期 YYYYMMDD，每发版 bump）、`VERSION_NAME`（展示名） |

跨文件引用 `mdcx.config.v1.*` 已全部改为 `mdcx.config.v2.*`，类名 `ConfigV1` / 函数名 `load_v1` 保留。

### 高级页 6 按钮布局（绝对定位）

6 枚功能按钮（网站列表 / 生成授权 / 生成私钥 / 设备编号 / 导入账单 / 路由列表）全部用绝对定位锚在 `gridLayoutWidget_20` 的 row 10~15 锚点中线，纵向间距由 `_even_button_centers(host)` 做 6 点等差数列，浮点 step = 35.2px，取整后 5 段 gap 为 [35, 35, 36, 35, 35]。各 `_sync_advanced_page_*_button` 方法按按钮对应的 row index 取 `centers[i]`。

| 按钮 | row index | 锚点控件 |
|------|-----------|----------|
| 网站列表 | 0 | `checkBox_hide_dock_icon` |
| 生成授权 | 1 | `checkBox_hide_window_title` |
| 生成私钥 | 2 | `checkBox_dialog_qt` |
| 设备编号 | 3 | `comboBox_ui_scale` |
| 导入账单 | 4 | `checkBox_hide_nfo_nav` |
| 路由列表 | 5 | `checkBox_show_web_sites` |

所有按钮左缘锚 `checkBox_show_data_log` 的 x（同一条竖线）。

### 跨分支 import 规范

- 同分支内部可以自由 import
- 配对刮削器（JSON ↔ 网页）**禁止**跨分支 import，各自实现 `build_view_payload`
- 共享基类 / 工具模块（`AIO_JSON_WEB_FALLBACK`、`models.py`、`consts.py`）允许跨分支引用

### 有码番号图片下载架构（2026-11-15 / 2026-11-20 改序）

#### 核心策略

有码番号（YOUMA / OFFICIAL 类型）的 poster / thumb 采用「优先档按来源选优 → 按序下载成功即停 → 全部失败才降级」：

1. **优先档**（group 0~4）：Amazon → DMM 站 → DMM CDN 直构 → 官方网站（番号对应官网 + 配对 JSON 版）→ MGStage 官方直构
2. **其他档**（group 5）：AVMOO_JSON, AVSOX_JSON, JavDB, JavBus, JavLibrary, Madou.club, Lulubar, Xcity 等综合站，保留在队尾

**逻辑流程**：
- 刮削阶段：`file_crawler.py` 的 `_run_scrape_type` 正常收集**所有站点**的 poster_list / thumb_list（不做静态过滤）
- 类型门禁：`amazon_images_allowed()` 对非「有码番号 / 官方网站」的结果剔除 Amazon 候选（见 §3.5）
- 选优阶段：`_rank_image_indices()` 对全部候选按 **来源档优先 → 尺寸更大** 排序；其他站点档排最后，组内仍按尺寸选优
- 下载阶段：按序尝试，第一个下载成功即返回——优先档拿到封面图/缩略图后不再下载其他网站；优先档全部下载失败才轮到 group 5
- `wuma` 只保留官网(3) + 其他(5) 两档；`ordered`（其它类型）不按来源重排

> 2026-11-20 取代 11-12 口径：原先 `_prune_priority_only()` / `_prune_poster_priority_only()` 在排序阶段就把 group 5 候选删掉，优先档全部下载失败时只能靠 `fallback_fetch` 按需补刮；现在保留队尾候选，降级直接可用，两个裁剪函数已删除。

#### 档位定义（`image_source_group`，返回 0~5）

| Group | 来源 | 识别方式 |
|-------|------|----------|
| 0 | Amazon | source 含 `amazon` 或 URL 含 `media-amazon` |
| 1 | DMM 站 | source ∈ DMM 来源集 或 URL 含 `dmm.co.jp` |
| 2 | DMM CDN 直构图 | URL 含 `awsimgsrc` 或 source 为 `dmm_direct/dmm_fallback/dmm_cdn` |
| 3 | 官方网站 | source ∈ `official_sources`（番号对应的官网 + 其 JSON 版） |
| 4 | MGStage | source 或 URL 含 `mgstage` |
| 5 | 其他站点 | 以上均不匹配（含其它官网，见 `_official_image_sources`） |

#### 关键函数位置

| 函数 | 文件 | 职责 |
|------|------|------|
| `image_source_group(source, url, official_sources)` | `core/web.py` | 单条候选 → 0~5 档位 |
| `image_source_plan(result)` | `core/web.py` | 返回 `"youma"` / `"wuma"` / `"ordered"` / `""` |
| `amazon_images_allowed(result)` | `core/web.py` | 是否允许该结果走 Amazon 图片链路 |
| `_drop_amazon_cover_candidates` / `_drop_amazon_poster_candidates` | `core/web.py` | 非允许类型剔除 Amazon 候选（尺寸探测前） |
| `_order_cover_candidates(result, covers, ctx)` | `core/web.py` | Thumb 完整排序列表（含队尾降级候选） |
| `_order_poster_candidates(result, candidates, ctx)` | `core/web.py` | Poster 完整排序列表 |
| `_rank_image_indices(sources, urls, plan, ctx)` | `core/web.py` | 按档 + 尺寸选优排序 |

#### Amazon 封面来源

Amazon 不是常规爬虫，封面由下载层通过条码匹配额外获取：`_get_big_poster()` 在构建候选列表时通过 `extra_candidates` 传入，source 为 `"Amazon"`，在 `image_source_group` 中被识别为 group 0（优先档首位）。非有码/官方网站类型不再调用 `_get_big_poster()` 的搜索分支，已有 Amazon 候选也在构建/定序前剔除。

#### DMM / DMM CDN 图片门禁（2026-11-21）

`amazon_images_allowed()` 与 `dmm_images_allowed()` 共用 `_result_looks_like_other_type()`：自动判断末尾把无特征前缀番号默认归为 YOUMA，欧美站点兜底拿到的结果会带错误类型，故用纯无码/国产马赛克与主字段来源（「其它类型专属站点」= `TYPE_DEFAULT_SITES` 其它组减有码/官网组）复核。两条门禁共用复核但允许类型略有不同：日亚是 `YOUMA`/`OFFICIAL`（另排除里番/动漫等马赛克），DMM 是 `YOUMA`/`DONGMAN`/`OFFICIAL`（官方网站档 2026-11-21 当日追加，两边都放行）。

`_is_dmm_image_candidate()` 复用 `image_source_group` 的 group 1（DMM 站 / `dmm.co.jp` / `pics.dmm.co.jp`）与 group 2（`awsimgsrc` / `dmm_direct` / `dmm_fallback` / `dmm_cdn`）。三个入口在尺寸探测与下载前过滤：Thumb 走 `_order_cover_candidates()`，Poster 走 `_build_poster_candidates()` + `_order_poster_candidates()`，ExtraFanart 走 `extrafanart_download()`（主候选与 `fallback_fetch` 补刮后的两组都过滤，按来源/URL 逐条剔除）。此外 `_direct_image_candidates()`、`_build_dmm_poster_candidates()` 不再为非允许类型生成 CDN 直构候选，thumb 的 `find_valid_dmm_cover()` 兜底也加守卫。爬虫层 `upgrade_dmm_cover()` 产生的 awsimgsrc URL 仍在下载层统一拦截，无需逐站改。MGStage（group 4）与 Amazon 校验用的 DMM 内存参考图不在门禁范围内。

#### extrafanart 不参与来源档排序

extrafanart 从所有站点下载，不经过上述优先档定序/裁剪逻辑；但仍按类型门禁过滤 Amazon 与 DMM / DMM CDN 图源（见上一节），过滤后的候选才进入 `download_extrafanart_task()`。

#### 未来拆分方向

当前定序函数直接写在 `core/web.py` 中。按用户要求，理想架构应将以下职责拆分成独立函数放独立模块（如 `core/image_source.py`）：

1. **Amazon 封面获取函数**：通过条码匹配 Amazon 页面，提取 largest 尺寸封面 URL
2. **DMM 封面候选构建函数**：`_build_dmm_poster_candidates()` + `_sized_poster_candidates()`
3. **官方网站封面候选函数**：从 result.poster + result.poster_list 提取 official_sources 范围内的候选
4. **其他站点封面候选函数**：AVMOO_JSON, JavDB 等综合站
5. **优先档/降级定序函数**：`_order_cover_candidates()` / `_order_poster_candidates()` + `_rank_image_indices()`（原 `_prune_*_priority_only()` 已于 2026-11-20 删除）
6. **尺寸校验函数**：`image.py` 中 `_replace_if_poster_bigger()` + `web.py` 中 `_download_image` 尺寸探测
7. **最终选优函数**：`_rank_image_indices()` 按档 + 尺寸综合排序

### 排查结论与历史状态归档（原 `docs/MEMORY.md` 一次性条目，2026-11-18 移入）

> 以下为某次排查/调研的事实与历史状态，不是「以后每次都该怎么做」的规则；
> 对应改动见 `docs/Changelog.md`，长期规则仍只写 `docs/MEMORY.md`。

- subagent 复盘（2026-11）：宣称 22 项中 11 项编造/夸大；要求先列「已排除假设 + 理由」再逐条独立复现。
- 误判家族（2026-11）：「未命中/空结果」是业务常态，不得当通道故障；空壳 200、哨兵默认值、多节点投票都曾造成误判。
- 2026-11 时点注册爬虫 86 个；数字开头模块名（7mmtv.py）用 importlib 动态导入。
- 【已废止】JavBus 四条线路轮换：2026-11-17 已删除全部回退/镜像，只保留 https://www.javbus.com/。
- Hbox 门壳（2026-11-08）：无 Cookie 回 302 到 /age_check，约 4KB 空壳页不是作品数据；首轮即定论，别重复打节点。
- JavDB 预告片（2026-11-09 线上 JS 实锤）：新版详情页 <video> 的登录态由 preview_url 接口决定。
- 2026-11-14 里程碑：10Musume/1Pondo 等 7 对官网网页版与 JSON 爬虫彻底解耦；网页版改为界面隐藏的 JSON 兜底。
- 【历史状态】2026-11 待办：load_config 填表位置、empty keys 补全等三项尚未落地，别当成已修。
- 【历史状态】2026-10-19 诊断：load_config ↔ pushButton 互调型递归需重入保护，当时修复未落地。
- R18.dev 调研（2026-11-16 Edge 实测）：没有「演员名 → actress id」搜索入口，按番号直连详情；不进查缺 fetcher。
- 【已过时】2026-10-24 曾记录本机无 uv；当前仓库已用 .venv + uv 标准工具链，门禁以 scripts/check.py 为准。
