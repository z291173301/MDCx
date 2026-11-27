# MDCx 自动 QA 报告

- 执行日期：2026-11-26
- 解耦实施与复验：2026-11-27
- 仓库：`D:\@Data\MDCx`
- 基线提交：`59f3609553b4a6d32c1ddf4dcf17b68980cfa2fa`
- 分支：`main`
- 执行规范：`docs/Auto-Agent-Prompt.md`

## 0. 基线

### 0.1 工作区

`git status --short --branch` 仅返回 `## main...origin/main`，没有未提交或未跟踪文件。本次审计不提交、不推送。

### 0.2 离线测试

命令：

```bash
uv run pytest tests/ -q -m "not network and not integration"
```

| 指标 | 结果 |
|---|---|
| 退出码 | 0 |
| 收集用例数 | 2,994 |
| 通过率 | 100% |
| 失败 / 错误 | 0 / 0 |
| 耗时 | 约 295.9 秒 |
| 3000 用例上限 | 未触发 |

独立收集命令 `MDCX_PYTEST_NO_FORCE_EXIT=1 uv run pytest tests/ --collect-only -q -m "not network and not integration"` 退出码为 0，确认 2,994 项。仓库的 `tests/conftest.py::pytest_sessionfinish` 在全部通过时默认主动 `os._exit(0)`；若未设置 `MDCX_PYTEST_NO_FORCE_EXIT=1`，stdout 会在缓冲区未刷新时截断。本次最初记录的 1,483 项正是截断行数，不是实际收集数，现已以关闭强制退出的独立收集结果更正。

唯一输出告警为 pytest-asyncio 未显式设置 `asyncio_default_fixture_loop_scope` 的弃用提示，不影响结果。

### 0.3 质量门禁

命令：

```bash
uv run check --skip-hook-install
```

| 检查项 | 结果 |
|---|---|
| `ruff format --check --target-version py315` | 856 个文件已合规 |
| `ruff check` | `All checks passed!` |
| `mypy mdcx/` | 356 个源文件零错误 |
| `scripts.check_thread_safety` | 无违规 |
| 退出码 | 0 |

mypy 另有未检查无类型函数体的 `annotation-unchecked` 提示，这是项目现有配置，不是错误。演员库与信息库校验因对应文件未改动而按门禁逻辑跳过。

### 0.4 Qt 环境

真实 Windows Qt 平台探针：

```bash
QT_QPA_PLATFORM=windows uv run python -c "..."
```

测得字体族 218 个、设备像素比 1.25，确认可用于真实渲染巡检；纯逻辑检查继续使用 offscreen。

## 1. 真实 Qt 自动巡检

### 1.1 执行方式与隔离

主窗口探针位于 `tests/_auto_qa_probe.py`，子窗口探针位于 `tests/_auto_qa_child_probe.py`。两个文件以下划线开头，不被默认 `test*.py` 收集，需显式运行；它们不进入生产包，也不改变应用启动入口。

巡检使用 `QT_QPA_PLATFORM=windows` 和真实 `QApplication`，而非仅离屏创建对象。为防止自动操作触发真实外部副作用，探针做了以下隔离：

- 使用临时配置目录，阻止 manager 持久化、重置和启动自动任务。
- mock 网络客户端与同步 web 请求，只允许回环地址，阻断非回环 socket/DNS。
- 阻断模态对话框、菜单、文件对话框、浏览器、`os.startfile` 和桌面 URL 打开。
- 将字体与静态资源指向仓库真实 `resources`，避免离屏字体度量和假样式干扰渲染。
- 捕获 `sys.excepthook`、逐动作异常和日志错误；动作后关闭新窗口并投递 `DeferredDelete`。
- 主窗口在每页入口冻结候选控件，每个动作前恢复页面，避免按钮切页导致后续开关、下拉框和表格被动态跳过。

这能验证真实 Qt 事件分派、控件状态、窗口构造和清理路径，但不会向真实成人站点发起请求，也不会验证需要真实账号、Emby 服务或外部授权的链路。

### 1.2 主窗口

| 指标 | 结果 |
|---|---:|
| 遍历页面 | 20 |
| 枚举 QWidget | 1,799 |
| 执行动作 | 926 |
| 跳过动作 | 4 |
| 异常 | 0 |
| 日志错误 | 0 |
| 页面截图 | 20，全部非空 |
| 清理后残留对话框 | 0 |

动作覆盖：页面切换 20、按钮 380、开关/单选框 327、文本 161、下拉框 27、表格 2、数字框 5、滑块 6、QAction 18。文本输入包含空串、4,096 字符、HTML/引号/反斜杠、中日韩文本和 Windows 媒体路径；表格执行右键、Tab 和首项定位。

原始顶层窗口快照为 21，包含 Qt 内部 `QFrame`/`QMenu`/tooltip、操作过程中打开的对话框、设计上常驻的 `CutWindow` 和探针尚未投递删除的窗口，不能直接等同于泄漏。显式关闭非常驻对话框并投递延迟删除后为 0，未确认窗口泄漏。

原始新增线程快照为 4：`AsyncBackgroundThread` 进程级单例，以及 asyncio 默认执行器的 `asyncio_0/1/2`。逐动作出现的网络检测线程均已退出，未确认每窗口 QThread 泄漏。

结果文件：

- `C:\Users\ZhouHan\AppData\Local\Temp\mdcx-auto-qa-main-window.json`
- `C:\Users\ZhouHan\AppData\Local\Temp\mdcx-auto-qa-main-contact.png`

最终摘要：

```text
QA_PROBE_SUMMARY widgets=1799 actions=926 pages=20 exceptions=0 threads=4 windows=21 post_cleanup_dialogs=0
```

### 1.3 独立子窗口

| 指标 | 结果 |
|---|---:|
| 独立业务窗口 | 14 |
| 枚举 QWidget | 651 |
| 执行动作 | 151 |
| 跳过动作 | 2 |
| 构造错误 | 0 |
| 异常 | 0 |
| 日志错误 | 0 |
| 窗口截图 | 14，全部非空 |
| 清理后残留窗口 | 0 |

覆盖窗口：`CutWindow`、`NfoPreviewWindow`、`DonateDialog`、`SimilarDialog`、`JsonViewDialog`、`LicenseDialog`、`SiteListEditorDialog`、`FieldPriorityDialog`、`LibrarySelectDialog`、`EmbyActorSettingsDialog`、`ActorCleanRulesDialog`、`ActorSourceTestDialog`、`ActorDetailDialog`、`EmbyActorManagerDialog`。

动作覆盖：按钮 90、开关/单选框 34、文本 15、表格 6、下拉框 4、滑块 2。`EmbyActorManagerDialog` 和 `EmbyActorSettingsDialog` 按各自线程关闭协议清理。清理前快照中的 1 个 `EmbyActorSettingsDialog` 在显式关闭和 `DeferredDelete` 后消失，属于探针清理时序；剩余 1 个线程仍是进程级 `AsyncBackgroundThread`，未确认子窗口线程泄漏。

结果文件：

- `C:\Users\ZhouHan\AppData\Local\Temp\mdcx-auto-qa-child-windows.json`
- `C:\Users\ZhouHan\AppData\Local\Temp\mdcx-auto-qa-child-contact.png`

最终摘要：

```text
QA_CHILD_SUMMARY windows=14 widgets=651 actions=151 exceptions=0 factory_errors=0 threads=1 remaining_windows=1 post_cleanup_windows=0
```

### 1.4 巡检结论

本轮未捕获崩溃、未处理 Qt 异常、日志错误或清理后残留窗口。线程快照中的对象均有明确生命周期解释。该结论不等于证明不存在所有 UI 缺陷：模态交互、外部站点响应、真实账号数据和需要长时间运行的媒体处理仍受沙箱限制。

## 2. 功能矩阵专项审计

按 `docs/Features.md` 与 `docs/User_Guide.md` 的功能分类，选择现有回归测试做离线端到端验证。网络、Emby HTTP、CF 回退等边界使用 mock/本地响应，不访问真实外部服务。

| 功能域 | 主要覆盖 |
|---|---|
| 番号、扫描与续跑 | `test_number_definition.py`、`test_file_crawler_runtime.py`、`test_scrape_cache.py`、`test_remain_continue.py` |
| 刮削模式 | `test_normal_mode_association.py`、`test_separate_mode.py`、`test_organize_mode.py`、`test_complete_mode.py` |
| 命名与配置转换 | `core/test_naming_template.py`、`test_config_conversion.py` |
| NFO 生成、合并与回写 | `test_nfo_save_roundtrip.py`、`test_nfo_merger.py`、`test_nfo_library_filter_fields.py`、`test_nfo_library_maximize_preview.py` |
| 图片源与封面补全 | `test_image_source_priority.py`、`test_cover_backfill.py` |
| 翻译与缓存 | `test_translate_llm.py`、`test_llm_translate_cache.py` |
| 演员库与 Emby | `test_actor_db_tool.py`、`test_actor_db_filter_male.py`、`test_emby_local_backfill.py`、`test_emby_actor_manager_http.py` |
| 网络检测与生命周期 | `test_network_check.py`、`test_network_lifecycle.py` |
| CF 绕过与站点解析 | `test_cf_transport_fallback.py`、`crawlers/test_javlibrary.py` |
| 工具入口 | `test_tool_handlers.py` |

结果：**410 passed，退出码 0**。本轮没有从功能矩阵测试中确认可复现的生产功能缺陷。

未覆盖的真实外部链路包括：在线站点可用性、真实 JavDB App CDN、真实 Emby/Jellyfin 服务、付费/授权站点、系统浏览器和长时段媒体转码。这些需要单独授权测试环境和账号，不能由离线通过结果推断。

## 3. 已确认发现

### F1：模式数量与读取/补全说明漂移

- `docs/Features.md:151` 标题仍为“六种刮削模式”，但同文档 `docs/Features.md:263` 已定义第 7 种“补全模式”。
- `docs/User_Guide.md:80-106` 仍以“六种模式”组织，表格漏掉补全模式；`docs/User_Guide.md:89` 把“维护已有媒体库，补刮或更新”归给读取模式。
- 实际读取模式只读展示，不联网、不下载、不写 NFO、不移动；补刮/补图属于补全模式。代码依据为 `mdcx/config/extend.py:65-70`、`mdcx/config/extend.py:151-179`。

影响：用户可能选错模式，误以为读取模式会更新媒体库。属于文档缺陷，不需要改变运行行为。

### F2：自动休息最小值仍写成 40 秒

- `docs/Features.md:169` 写“自动休息最小值为 40 秒”。
- `docs/User_Guide.md:135` 写“最小值固定为 40 秒”。
- 实际下限是 0 秒，默认值仍为 40 秒；负值才归一到 0。依据为 `mdcx/config/models.py:40-51`、`mdcx/config/models.py:2013-2018`。

影响：文档混淆“默认值”和“允许最小值”，会误拒合法的 0–39 秒配置。属于文档缺陷。

### F3：视频模式移动策略默认值自相矛盾

- `docs/Features.md:189` 写“覆盖旧文件 / 保留旧文件……默认都不勾选”。
- 同文档 `docs/Features.md:167`、`docs/Features.md:280-290` 写“必须勾选其中一个，默认保留旧文件”。
- 默认配置确实包含 `Switch.MOVE_KEEP`，迁移在两者都未选时补 `move_keep`。依据为 `mdcx/config/models.py:1650`、`mdcx/config/migrations.py:1747-1751`。

影响：用户对同名文件是覆盖还是留在源目录会产生错误预期。属于文档缺陷。

### F4：解耦审查快照已滞后

`docs/Decoupling-Review.md` 记录的是历史第三轮结果。当前代码规模和公开表面已随后续功能增长，不能继续把旧数字当成本轮审计结果；但历史快照本身不应被改写成“当时不存在的数据”。2026-11-27 已按建议追加本轮复查，保留全部历史记录。

## 4. 解耦审计

本节保留解耦前的审计快照，用于解释 A1–A4 的立项依据；实施后的最终指标见第 7 节。

### 4.1 导入矩阵与 Qt 传染

对 `mdcx` 下 376 个 Python 文件做 AST 解析和导入边核对，区分顶层导入、函数内延迟导入与 `TYPE_CHECKING`。

| 检查项 | 当前结果 | 说明 |
|---|---:|---|
| 顶层禁止分层边 | 1 | `mdcx/tools/actor_search/fetch_avbase_json.py:3` 的 `tools → crawlers` |
| `TYPE_CHECKING` 禁止边 | 0 | 未发现 |
| `core → tools` 延迟边 | 3 | 含已接受的 scraper 边界 |
| `crawlers → core` 延迟边 | 2 | 需保留循环约束 |
| `config → crawlers` 延迟边 | 1 | 注册表/延迟路径 |
| `tools → crawlers` 唯一边 | 21 | 共 31 处函数内延迟导入 |
| Qt-free 复建探针 | 28 / 32 | 1 项是已接受的 `core/scraper.py`，另 3 项需复查 |

三个非预期 Qt 传染点：

- `mdcx/tools/emby_actor_image.py:16-17`：经 `mdcx.image` 与 `mdcx.signals` 引入 Qt。
- `mdcx/tools/emby_actor_info.py:23-27`：直接导入 `signals` 和演员图片模块。
- `mdcx/tools/subtitle.py:9-11`：导入 `core.scraper` 与 `signals`。

因此当前并未满足历史报告的“31/32 Qt-free”。应优先恢复这 3 项到 31/32；`core/scraper.py` 的已接受边界不因本轮审计擅自改变。

`fetch_avbase_json.py` 的顶层爬虫导入是新出现的口径回归：它不一定造成当前功能故障，但违反了第三轮已经清零的顶层 `tools → crawlers` 边界。最小候选是移到函数内延迟导入；若需进一步解耦，再单独评估注册表/协议注入，不在同一改动里扩大范围。

### 4.2 单体与重复实现

| 位置 | 当前规模 | 判断 |
|---|---:|---|
| `mdcx/views/MDCx.py` | 15,867 行 | 生成文件，不手改；只作为 UI 源码产物观察 |
| `mdcx/tools/emby_actor_manager_ui.py` | 7,194 行 | 当前最大手写文件，仍是后续拆分候选 |
| `EmbyActorManagerDialog` | 3,504 行、121 个直接方法 | UI、线程、服务与持久化仍集中 |
| `AsyncWebClient` | 2,485 行、87 个直接方法 | 大类，但本轮未确认必须拆分的功能缺陷 |
| `controllers/main_window/main_window.py` | 1,033 行、34 个 mixin、35 个 bases | 已是装配器，不应回退为单体 |
| `mdcx/crawler_registry.py` | 42 行 | 不是单体问题 |

`avheat_api.py`、`avmoo_api.py`、`avsox_api.py` 中 `_api_search`、`_api_get_movie`、`_run` 各三份，函数体归一化后精确相同；每组 75 行，三组共 225 行，除保留一份外约 150 行冗余。适合抽到共享 mixin/基类，但必须保持三个爬虫的公开方法和站点差异不变。

### 4.3 公开表面比对

- 历史主窗口 `99be7300^ → 99be7300`：方法名+装饰器 387、类赋值 221、信号 49、self 引用 568、严格 self 赋值 126，逐项等价。
- 当前主窗口类/mixin：478 个方法、199 个非信号类常量、56 个信号、706 个 self 引用、159 个严格 self 赋值。数量增长来自后续功能，不能直接与历史快照做“零差异”判断。
- 当前演员管理器：22 个模块函数、18 个类、219 个方法名+装饰器键、266 个直接定义、28 个类常量、13 个信号、178 个 self 赋值。
- 演员管理器历史 `44e585b4^ → 44e585b4` 的差异来自已记录的 D18 线程取消/等待行为，不是本轮新增缺陷。

任何后续拆分都必须重新比较方法名+装饰器、类常量、`pyqtSignal`、`self.xxx` 引用和严格赋值，不能只比较方法数量。

## 5. 拟改动清单（A1–A4 已授权，D1–D3 未授权）

用户已明确授权“开始解耦”，因此 A1–A4 已实施并复验；D1–D3 仅保留为审计发现，本轮不修改。实施证据见第 7 节。

| 编号 | 范围 | 最小改动 | 验证 |
|---|---|---|---|
| D1 | 文档模式 | 修正 `Features.md` 的“六种”标题；`User_Guide.md` 增加补全模式并改正读取模式说明 | 对照 `COMPLETE_MAIN_MODE`/`READ_MAIN_MODE` 与现有模式测试 |
| D2 | 文档休息时间 | 将两处“最小值 40 秒”改为“最小值 0 秒、默认 40 秒” | 配置模型边界测试、UI 回显检查 |
| D3 | 文档移动策略 | 将视频模式“默认都不勾选”改为“默认保留旧文件、二者必须选一” | 现有配置迁移和移动策略测试 |
| D4 | 解耦报告 | 在 `Decoupling-Review.md` 追加 2026-11-26 复查，不改写历史快照 | 数字和路径与本报告一致 |
| A1 | 顶层导入边界 | 将 `fetch_avbase_json.py:3` 爬虫导入移到函数内，保持签名和调用顺序 | 演员检索相关测试、导入矩阵、mypy |
| A2 | Qt 传染 | 分别处理演员图片、演员信息、字幕 3 个模块；优先用既有中立钩子/延迟导入，不改变 `core/scraper.py` 接受边界 | Qt-free 复建、演员库/字幕测试、真实 Qt 探针 |
| A3 | API 爬虫重复 | 为三个爬虫提取共享 `_api_search`/`_api_get_movie`/`_run` 实现，保留公开表面 | 三个爬虫测试、番号检索测试、公开表面比对 |
| A4 | 演员管理器继续拆分 | 先拆线程生命周期/服务边界，再拆 UI；作为独立阶段设计 | 线程关闭、Emby HTTP、演员库测试和窗口泄漏探针 |

不在本轮候选内：手改 `MDCx.ui`/`MDCx.py`；修改 `log_console.py`、`ui_hooks.py` 中立枢纽；调整 `config/enums.py` 枚举顺序；改动 `tests/conftest.py` 冻结的 manager/resources/signals 导入路径；全树 ruff 自动修复。Git 提交与推送在用户明确授权“完成后提交到 github”后执行。

## 6. 审计阶段门禁与状态

| 检查 | 结果 |
|---|---|
| 全量离线 pytest | 2,994 项，100%，退出码 0 |
| 功能矩阵专项 pytest | 410 项通过，退出码 0 |
| `uv run check --skip-hook-install` | 退出码 0 |
| ruff format | 856 个文件合规 |
| ruff check | `All checks passed!` |
| mypy | 356 个源文件零错误 |
| 线程安全脚本 | 无违规 |
| 两个 QA 探针 | 显式 ruff 检查、格式化、编译和运行通过 |

审计阶段在用户授权前停在“审计结果 + 拟改动清单”。用户随后授权“开始解耦”，A1–A4 的实施、回归和修复后门禁见第 7 节；D1–D3 仍未实施。

## 7. A1–A4 实施与复验（2026-11-27）

### 7.1 实施内容

| 编号 | 落地改动 | 边界保持 |
|---|---|---|
| A1 | `fetch_avbase_json.py` 的 `AVBaseJsonCrawler` 导入移到 `_fetch_avbase_json()` 内 | 函数签名、配置读取顺序、实例化参数不变 |
| A2 | 新增共享 `utils/lazy_signal.py`；演员图片、演员信息、字幕改用惰性 signal；图片函数和 `start_new_scrape` 使用同名延迟包装器 | 真实 signal 读写转发、monkeypatch 路径、包装器签名和返回语义不变 |
| A3 | 新增 `crawlers/aio_api_crawler.py`，收敛三个 AIO 爬虫的 `_api_search`、`_api_get_movie`、`_extract_movie_id`、`_run` | 各站 namespace、域名、Cookie 预热、请求体、字段映射和 fallback 顺序不变 |
| A4 | 新增 `tools/emby_actor_threads.py`，下沉取消异常、孤儿集合、阻塞线程池、卸父级函数和可取消 QThread 基类 | UI 模块显式再导出同一对象；五个工作线程的关闭编排和槽绑定未移动 |

`emby_actor_manager_ui.py` 从 7,194 行降至 7,114 行；线程运行时为 99 行。A3 三个爬虫共删除约 270 行重复实现，新增 119 行共享基类，净减少约 150 行。

### 7.2 等价性与导入边界

- 对 `mdcx` 下 379 个 Python 文件重新做 AST 导入边核对：顶层 `tools → crawlers` 为 **0**。
- 三个 AIO 爬虫各保持 23 个方法；方法签名、装饰器、11 个有效类赋值、19 个 self 引用和信号表面与拆分前一致。有效类赋值按 MRO 合并，子类覆盖共享基类标注。
- `EmbyActorManagerDialog` 拆分前后均为 128 个方法、24 个类赋值、3 个信号、240 个 self 引用、84 个严格 self 赋值，逐项 `IDENTICAL`。
- 五个线程运行时对象在 UI 与 helper 之间保持同一身份：`_ORPHAN_WORKER_THREADS`、`_BLOCKING_EXECUTOR`、`_CancellableWorkerThread`、`_WorkerCancelled`、`_detach_running_thread`。
- 所有既有模块函数签名不变；`cut_pic`、`fix_pic_async`、`start_new_scrape` 包装器与原子函数签名一致。
- 32 个代表业务模块独立子进程 Qt-free 探针为 **31/32**；唯一非 Qt-free 项仍是已接受的 `mdcx.core.scraper`。三个目标工具模块均不再在导入期加载 PyQt6。

### 7.3 最终门禁

| 检查 | 结果 |
|---|---|
| 全量离线 pytest | **2,999 passed，115 warnings，269.08 秒，退出码 0** |
| 用例预算 | 2,999 < 3,000；本轮新增语义合并后仅净增 5 项 |
| 聚焦回归 | 50 passed，退出码 0 |
| `uv run check --skip-hook-install` | 退出码 0 |
| ruff format | 860 个文件合规 |
| ruff check | `All checks passed!` |
| mypy | 359 个源文件零错误 |
| 线程安全脚本 | 无违规 |
| `git diff --check` | 通过 |

115 个警告均为已有的 pytest-asyncio 配置、测试标记、`datetime.utcfromtimestamp` 弃用和测试桩未 awaited 提示，没有失败或错误。

### 7.4 真实 Qt 复验

| 探针 | 最终结果 |
|---|---|
| 主窗口 | 20 页、1,799 个 QWidget、926 个动作；异常 0、日志错误 0、清理后残留对话框 0 |
| 独立子窗口 | 14 个窗口、651 个 QWidget、151 个动作；构造错误 0、异常 0、日志错误 0、清理后残留窗口 0 |
| 线程快照 | 主窗口剩余进程级 `AsyncBackgroundThread` 与 asyncio 执行器线程；子窗口仅剩进程级 `AsyncBackgroundThread`，未确认泄漏 |

结果 JSON 仍写入 `C:\Users\ZhouHan\AppData\Local\Temp\mdcx-auto-qa-main-window.json` 与 `mdcx-auto-qa-child-windows.json`。

### 7.5 变更文件清单

生产代码修改：

- `mdcx/crawlers/avheat_api.py`
- `mdcx/crawlers/avmoo_api.py`
- `mdcx/crawlers/avsox_api.py`
- `mdcx/tools/actor_search/fetch_avbase_json.py`
- `mdcx/tools/emby_actor_image.py`
- `mdcx/tools/emby_actor_info.py`
- `mdcx/tools/emby_actor_manager_ui.py`
- `mdcx/tools/subtitle.py`

生产代码新增：

- `mdcx/crawlers/aio_api_crawler.py`
- `mdcx/tools/emby_actor_threads.py`
- `mdcx/utils/lazy_signal.py`

测试与巡检：

- 修改 `tests/test_actor_manager_close_threads.py`、`tests/test_actor_sources_sites.py`、`tests/test_aio_json_view.py`、`tests/test_subtitle_file_index.py`
- 新增 `tests/test_tool_import_boundaries.py`
- 新增 `tests/_auto_qa_probe.py`、`tests/_auto_qa_child_probe.py`

文档：

- 新增 `docs/Auto-QA-Report.md`
- 追加 `docs/Decoupling-Review.md` 第 7 节，保留历史快照

### 7.6 剩余风险与未实施项

- D1–D3 三处文档功能缺陷未获得授权，本轮没有修改 `Features.md` 或 `User_Guide.md`。
- 离线测试和真实 Qt 巡检不等同于真实站点、账号、Emby/Jellyfin、付费服务或长时段媒体处理验证。
- 惰性 signal 只消除导入期 Qt 负载；首次访问 signal 或执行图片处理时仍会正常加载 Qt。
- `emby_actor_threads.py` 仍依赖 QThread，这是线程运行时的固有依赖，不声称其为 Qt-free。
- 测试预算只剩 1 项余量；后续新增用例应优先合并语义相同或相近的现有测试。
