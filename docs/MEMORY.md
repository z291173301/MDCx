# 用户指令记忆

只记「以后每次都该怎么做」的规则。技术原理与架构见 `docs/Development.md`，版本变更见 `docs/Changelog.md`。

> **阅读口径**：本文件只留长期规则；一次性事实写 `docs/Changelog.md`，原理与排查过程写 `docs/Development.md`。
> 同一主题只保留一条口径，旧定规被取代时并入新条目、不另起一条。

**主题索引**：协作与质量 · 检查与提交纪律 · pre-push 钩子 · 本机环境 · 议题/GitHub · 排查与本地验证 ·
Qt 生命周期 · 崩溃与内存 · UI 排错 · 并发与网络库 · 站点与网络 · Windows 打包发布 ·
版本号与配置迁移 · 视频模式与伴生文件 · 通用纪律 · 日亚 ASIN 数据库。同一主题只保留一条口径。

---

## 协作与质量

- 一律用简体中文回复；面向小白的说明按「现象和影响 → 原因 → 可执行步骤」三段写；日期时间用北京时间（UTC+8）并显式注明。
- **界面没有要求的不要自作主张修改**（2026-11-13 用户严规）：只改需求明确点名的界面部位（控件、文案、宽度、对齐、配色、字号等），没点名的一律不动——即使觉得「更一致」「顺手可优化」也不许改，下拉框/弹窗宽度与选项文案尤其不许擅自变动。认为确有必要改的，先说明理由征得同意再动手。
- **日志与界面文字：英文语境之间的空格照留，中文之间的空格不留，图标后保留一个空格**（2026-10-28 用户定规，2026-11-12 修订口径）：所有可见文字（日志窗口、日志文件、详情日志、弹窗、按钮、菜单、标签等）里的连续空格 / Tab / 全角空格算一段，**两侧都是半角可见字符（英文字母、数字、半角标点）时留一个空格**——英文单词之间 `I Want Clips:Blacked Out Fm`、单词与数字之间 `Start time` / `HTTP 403`、英文标点之后 `videos, Please` 都必须留；**只要有一侧是中文、全角标点或图标就删掉**（`连接 Gfriends 网络` → `连接Gfriends网络`），数字与汉字仍紧贴（如「10个站点」），需要停顿用冒号或顿号。另外保留空格的几处：每行行首的图标与文字之间（「🔐 授权状态：」「📂 程序目录：」）、版本标识 `MDCx YYYYMMDD`（不得压成「MDCx20261027」）、HTTP 请求前缀 `GET http(s)://`（不得压成 `GEThttps://a.com`）、产品名 `CF Bypass` / `CloudFlare Bypass`（不得压成 `CFBypass`）、URL 被 `add_html()` 包成 `<a href="…">` 后同样成立；以及 2026-10-30 定规的四处——诊断串的 `HTTP 403`、`403 body=`、URL 与「失败」之间（`…fa735 失败：`）、双引号内的原文（响应体/引用，如 `body={"message":"This action is unauthorized."}`）。后几组只补「源码里本来就写漏空格」的情况，全部幂等；出口由 `utils.strip_log_spaces()` 兜底，新文案仍不要主动加多余空格。**例外：检测网络页的检测报告**（2026-10-30 用户定规）——那是等宽表格，列间连续空格就是排版本身，`show_net_info()` 走 `add_html_plain_text(keep_spaces=True)` 保留原样，不要给它套空格清洗。**刮削到的字段值按站点实际值走，不单独删空格**（2026-11-12 用户定规）：`mgstage` / `prestige` / `prestige_web` 的演员名不再 `replace(" ", "")`（prestige_web 的 `_split_names` 也只按 `[,、，]` 分隔、不按空白切开），`美月 さくら` 这类姓名按实际保留；番号归一、标题匹配、搜索 query 里的临时去空格属匹配逻辑，不在此列。
- **NFO 写入值保持站点刮削到的原值，不做修改不做替换**（2026-11-12 用户定规）：写 NFO 只做 XML 编码必需的两步——`utils/xml.py::escape_xml_text()`（实体幂等化 + 转义）与 `build_cdata()`（实体幂等化 + `]]>` 转义），字符一个不动。全角空格 `\u3000`、不换行空格 `\xa0`、`・`、`“”`、`...` 一律原样写出，`<runtime>` 不再去空格；`normalize_xml_text()` / `REP_WORD` / `XML_TEXT_FIELDS` 已删除，`core/nfo.py` 写入前与 `core/file_crawler.py::_deal_res()` 刮削后的字符清洗都不再做。**上游替换表只去美观类**（同日用户口径）：`manual.py::ALL_REP_WORD` 不再做 `・`→`·`、`“”‘’`→`「」`、`...`/`……`→`…`、`’s`→`'s`、`! `→`！`、全角字母数字→半角、`\t`→空格，`TITLE_REP` 标题上下集/蓝光版剥离整表删除；**保留** HTML 实体解码、`&`→`＆` / `<`→`＜` / `>`→`＞`（防 Emby 读 NFO 误判）、`<br/>` 残留清理、`SPECIAL_WORD` 反和谐与半角片假名还原、简体字段用字归一。匹配键（`convert_half`、`_normalize_info_key`、番号归一、标题匹配、搜索 query）不在保真范围内。**不算改值的两类要保留**：① 解码——`normalize_linebreaks()` 把爬虫转义过的 `\r\n` / 字面 `\n` / `<br>` 还原成真实换行；② 既有功能——标题命名模板、番号前缀与 CD 后缀、tag 模板、简介原文拼接与「由 X 提供翻译」、`OUTLINE_NO_CDATA` 单行化、评分量纲、日期归一、`N/A` 导演过滤、占位简介清理。细则见 `docs/Development.md` §3.8。
- **工作日志与记忆只落两处**（2026-10-23 / 11-16 用户定规）：当天做了什么写进 `docs/Changelog.md` 的 `## YYYY-MM-DD` 段，可复用规则写进本文件；不要另建 `.workbuddy/`、` .workbuddy-ai/memory/`、`docs/YYYY-MM-DD.md` 之类旁路或按日期的记忆文件——「没人会看还占地方」。本文件只记可复用做法，不记一次性事实。
- **已推送的内容一律新开 commit，不要 `--amend`**（2026-11-16 教训）：`--amend` 会改写已推送的提交历史，本地快进不了远端、直接造成分叉。改动已推送的内容就新开一个 commit。
- **推 GitHub 优先直连，直连失败改走 7897 代理 + openssl**（2026-11-16 定规，2026-11-17 补充）：本机 git 配置里写死的 `http.proxy=127.0.0.1:7897` 会让 Schannel 握手失败，直连时用 `HTTPS_PROXY= HTTP_PROXY= git -c http.proxy= -c https.proxy= push`。若报 `Recv failure: Connection was reset` / 连接超时（2026-11-17 实测直连不通、7897 代理 curl 返回 200），改用 `HTTPS_PROXY= HTTP_PROXY= git -c http.sslBackend=openssl -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main`。两条都试过再判定网络故障。
- **多异常捕获由 ruff format 统一按 PEP 758 写 `except A, B:`**（2026-11-18 用户定规，取代 11-17 的括号写法口径）：项目锁 Python 3.15，`ruff format --target-version py315` 会把 `except (A, B):` 改写成 PEP 758 的 `except A, B:`，全仓已统一改写。`.pre-commit-config.yaml` 的 `ruff-format` hook、`scripts/check.py` 的 FAST 段、CI Pipeline 的 Run ruff format 步骤均带 `--target-version py315`；lint 仍按 3.15。手动格式化整仓也要带 `--target-version py315`。核对解释版本一律用 `.venv`（3.15）。
- **HTTP 限速档（唯一口径，2026-11-18 用户定规）**：JavDB 只保留 `javdb580.com` 一个 host 走 `web_async._PacedLimiter`：2 req/s + 120/min 双桶、`asyncio.Lock` 串行化、相邻请求 `random.uniform(0.5, 1.0)` 秒随机间隔（账号曾被判异常采集，光压总量不够）；`www.javdb580.com` 是空壳域名、App API 三域名（`apidd.czssdgz.com`/`apidd.spthgb.com`/`jdforrepam.com`）走通用档。wiki 5/180、通用 10/600、本机 300 req/s 不变，图片 CDN 不纳入。常量在 `web_async.py` 的 `_JAVDB_*` 与 `_GENERAL_RATE_*`，host 清单 `_JAVDB_PACED_HOSTS`。限速器挂在 `AsyncWebClient` 单例按 host 共享，线程数只影响排队不放大速率；界面「javdb延时(秒)」(`javdb_time`) 只存不参与限速，别再拿它换算 req/s。账号停用期间不联网实测。
- **JavDB 时长补齐只认 App 通道，且必须带登录 token**（2026-11-18 用户定规）：`/api/v2/search` 不带 `Authorization: Bearer <javdb_app_token>` 会返回 `JWTVerificationError: 請登錄帳號`，只带 `jdsignature` 不够。演员页列表卡片**没有时长**，所以导出表时长必须靠：① `enrich_missing_metadata(..., actor_names=[...])` 按演员名翻 App 搜索页建「normalize_key(番号)→duration」索引批量预填（实测 `三上悠亜` 7 页共 321 条、其中 290 条带有效时长，与演员页 321 个番号集合不完全重合，实测回填 147 / 153 行）；② 剩余行 `_collect_meta` 走 v4 详情 → 按番号搜 v2 → 网页详情最后兜底（本轮网页兜底上限 64 次）。11-17 被误删的 `_javdb_app_search_meta` 是 **JavDB 站内接口**、不违反「清单即边界」，已恢复；LibreDMM 跨站兜底不要恢复。别再用 321 次逐行详情页去补时长，那是 429 与缺口的来源。**`clean_duration` 不设上界**（2026-11-18 用户定规）：App / 站点给多少写多少，合集总时长 720 / 960 / 2091 分钟照写，只排除 0 / 负数；11-17 的 `MAX_DURATION_MINUTES=600` 已删除，别再加回来。
- **大模型输出只给改动片段**（2026-10-27 定规）：默认只返回修改后的片段，不重复输出全文；新建文件、用户明确要求全文、或只给片段会产生歧义时才输出全文。
- 改动前先说明「改什么、为什么」；遇到值得记的内容主动记入，不用等提醒；直接在当前分支操作，不擅自建分支。
- **授权/未授权文案只有三个落点**：弹窗正文 `premium_gate.premium_message()`（`<功能名>功能需要获取授权后才能使用`，句末不带句号）、额度用完正文 `premium_gate.premium_quota_message()`、状态日志 `guard.describe()`（未授权只给原因，不套「未授权（…）」）。功能名由 `premium_gate.GUARDED_ACTIONS` / `_license_gate(action)` 传入，改文案只改这几处。
- **授权弹窗只走 `premium_gate.premium_warning()`**（每日额度用完走 `premium_quota_warning()`）：标题固定「请获取授权」、正文同源，尺寸自然一致。主窗 / 工具页 / 信息管理 / 演员管理 / 机器绑定（生成授权、私钥）都不再自己写 `QMessageBox`。
- **读取模式 / 整理模式任何情况下都不弹授权窗**（2026-10-28 用户口径）：这两种模式只动本地文件，`license_gate()` 直接静默放行——不放提示、不计数、不写「请获取授权」；其它模式（正常 / 分离 / 视频 / 更新 / 补全）只有当天 10 次免费额度用完才弹一次。额度按**成功刮削次数**计（同一文件移动后再刮成功也算一次，不按番号去重），并发预留位占满不算用完；第 11 次起不再联网，直接记失败列表。「间歇刮削 → 连续刮削」设置同样受额度约束：未授权时填多少，一轮也最多连刮 10 个（`guard.rest_batch_limit()`），已授权按设置值。额度存在**独立库** `userdata/license_quota.db`（`used` 是 0~10 明文，带 HMAC 与只增不减的 `max_seen`），`userdata/scrape_state.db` 只做续刮缓存；启动与每次起任务前必须先 `quota.refresh()` 读盘再判断，禁止只凭进程内计数放行。**改系统时间不许清零额度**：时间/日期回拨一律沿用原计数并写 `quota.anomaly()` 日志，只有日期正常前进才清零；直接改库里的 `used` 会被签名校验拦下并按「已用完」处理；同一天只发一次额度（`license_quota_history` 历史表按天签名，往后拨一天用掉再拨回来也刷不出新额度）。跨天发额度前必须**联网校时**（`net_time.network_date()` 与本地日期一致才发），对不上或连不上网就当日按已用完处理——把时间往后拨任意天都刷不出额度；时间改回来按磁盘记录自动恢复，不需要重启软件。
- **演员管理器授权弹窗字号要回落**：演员管理器的 QSS 整体放大一号，授权弹窗会继承；主窗/子窗 QSS 必须拼上 `_premium_popup_qss()`（`QMessageBox, QMessageBox *` 统一用 `_ui_font_pt(0)`），否则弹窗比主界面窄。只改 QMessageBox 自身不够，内部 QLabel 仍继承放大字号。
- **账单导入与授权弹窗分文件**：账单导入只在 `bill_import_ui.py`（按钮、机器绑定轮询、导入流程），不写授权弹窗；未绑定机器的点击由 `premium_gate.MachineBoundClickGuard` 在按钮层拦，`import_bill()` 不再出现授权判断。
- **未授权 ≠ 关掉入口**（2026-10-27 口径，推翻此前「演员管理整窗拦」）：窗口能开、能连 Emby 读取、能统计；只有联网取数 / 写回服务器 / 写本地文件的动作点时才拦。独立顶层窗口（演员管理器）走 `premium_gate.premium_denied()`，主窗走 `premium_gate.premium_gate()`，两者共用同一份弹窗文案。
- **未授权点击只弹窗，不写状态栏 / 日志**（2026-10-28 用户口径）：被拦时只弹 `premium_gate.premium_warning()`，不要再 `show_scrape_info("🔒 …：请获取授权")`，也不要 `show_log_text(...)` 追加一行；演员管理器的 `_premium_blocked()` 同样不写窗口日志，开窗时也不打印「🔒 未授权…」提醒。额度用完的「今日免费额度已用完」状态提示不在此列。
- **受保护功能要拦在功能层，不只拦点击**（2026-11-17 用户口径）：GUI 层的事件过滤器（`premium_gate.GUARDED_ACTIONS`）只拦鼠标左键按下与空格/回车，程序化 `click()`、快捷键、侧栏浮标等旁路都会绕过去——凡是用户要求「只有已授权才能使用」的功能，handler 开头必须再问一次授权（主窗走 `self._premium_gate(action)`，工具页见 `tool_page.ToolPageMixin._require_license`），且被拦时**任务不提交、配置自动保存也不触发**；同一后端的所有入口（例：侧栏「查看本地番号」浮标与工具页「检查缺失番号」按钮共用 `missing.check_missing_number`）要一起拦，不能只拦其中一个入口。

## 检查与提交纪律

- **没写明就不提交**（2026-10-23 明示，细则见 `docs/Development.md` §10.10）：需求里没有「提交 / 推送 / commit / push / 提交到 GitHub / 推到远程」字样时只改工作区；授权只对当次有效，「提交」= commit、「推送」= push。
- **界面改动默认不写 `docs/Changelog.md`**（2026-10-23 定规）：纯界面调整（位置/间距/尺寸/对齐/配色/字号/措辞）不占 Changelog 行；只有用户可观察的行为变了才写。判定表见 `docs/Development.md` §10.7。
- 改代码后跑快速门禁（format + check + mypy），提交前加跑全量 `pytest -m "not network"`；只改 `docs/*.md` 或本文件时只需 `git diff --check`。
- 全绿判定 = 退出码 0，且 `grep -E "\.py:[0-9]+: error|Found [0-9]+ error"` 无输出（mypy 输出可能被 tail 截断）。
- `ruff check` 过 ≠ `ruff format --check` 过；改了 .py 必须 `ruff format` 落地。格式化要用仓库锁定版 ruff，**`uv.lock` 是唯一版本来源**：`pyproject.toml` / `requirements.txt` / `uv.lock` 根 specifier 由 `python -m scripts.sync_ruff_version` 自动同步（`--check` 只校验；`scripts/check.py` 检测到漂移会自动改写并拦截，提交后再重跑）。升版流程：先升级 `uv.lock` 的 ruff → 跑同步脚本 → 全量 format + check；`tests/test_ruff_version_sync.py` 锁死。
- `scripts/` 也在 check 范围内。`check.py` 的 ALWAYS 段 = `ruff format --check --target-version py315` → `ruff check` → `mypy mdcx/` → `check_thread_safety`（**不含 pytest**）；要全量门禁显式加 `--with-tests`：`"C:/Program Files/Python315/python.exe" scripts/check.py --skip-hook-install --with-tests`。CI Pipeline.yaml 的 Run ruff format 步骤同样带 py315 参数。
- **测试文件命名禁止带日期后缀**（2026-11-18 用户定规）：测试文件一律用 `test_<功能名>.py`，**禁止**写成 `test_<功能名>_YYYY_MM_DD.py` 或 `test_<功能名>_YYYY_MM.py`。日期信息写进 `docs/Changelog.md` 的对应日期段即可，不要塞进文件名。已有的 16 个带日期后缀的测试文件已全部处理：15 个直接重命名为无日期版本，1 个（`tests/crawlers/test_json_channels_2026_11.py`）合并进已有的 `tests/crawlers/test_json_channels.py`。新增测试用例优先追加到已有同主题测试文件，不另起新文件。
- `check_ui_layout` 已移出门禁，只作手工诊断：`-m scripts.check_ui_layout`。xlsx 校验按路径跳过（`check_actor_db` / `check_info_db` 只在对应出厂库或校验脚本有改动时跑）。
- `CI Pipeline.yaml` 的 `on:` 只有 `pull_request: branches: [main]`，**直推 main 不触发 CI**；门禁靠「PR + 本地自检」两道。
- Linux 构建依赖统一走 `.github/actions/install-linux-deps`（`build-py315.yml` / `CI Pipeline.yaml` / `update-sr-tools.yml` 三处共用）：**不装系统 Qt6、不装 FFmpeg 开发库**（Qt 来自 pyqt6-qt6 wheel，FFmpeg 来自 av 的 abi3 wheel），且必须带 `--no-install-recommends`。三处各复制一份大清单会退回「149 个包 / 123MB / 几分钟」的老路。
- `git add -- <具体文件>`，绝不用 `git add -A`；提交前看 `git status` 的未跟踪文件，运行残留不得入库。
- **不改不是自己改的文件**（并行会话可能同时改本仓库）；暂存区里有别人的改动时，用 `git commit -- <自己的文件>` 只提交自己的。
- 提交信息不要手写 `Co-authored-by`（`prepare-commit-msg` 会无条件追加）。
- **推送方式以「协作与质量」章的「直连优先」条款为准**（2026-11-17 更新，取代 10-27 旧定规）：命令行优先直连，仅直连失败才走 7897 代理 + openssl；GitHub Desktop 不再是默认，也不再要求「先确认代理已开」。

## pre-push 钩子

- `hooksPath` 是本地 git config，环境重置后静默失效：先 `git config core.hooksPath` 验证，为空则 `git config core.hooksPath .githooks`。
- 钩子生效时流程 = quick-check → commit → push，钩子自己跑快速门禁，别手动多跑；钩子失效期间推送前手动全量 check 兜底。
- 钩子按 uv → python3 → python 兜底，PATH 里的 `python3` 若是托管版 3.13 会因 PEP 758 语法 SyntaxError 拦下推送 → 造一个 `python3` 垫片（`exec "/c/Program Files/Python315/python.exe" "$@"`）前置到 PATH，**别用 `--no-verify`**。
- `.pre-commit-config.yaml` 是历史遗留，不依赖。

## 本机环境

- **操作浏览器一律默认用 Microsoft Edge**（2026-11-16 用户定规，已按此执行）：本机路径 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`（当前 157.0.4341.60）。联网调研站点、打开搜索入口、验证页面 DOM、点选/翻页等一切需要浏览器的动作都走 Edge，不用 Chrome、不用系统默认浏览器、不用 `webbrowser.open()` 的隐式默认；Playwright / Browser Use 显式指定 `executable_path` 指向该 exe（或 `channel="msedge"`）。**Windows 上 `msedge.exe --headless --dump-dom` 实测退出码 0 但 stdout 恒为 0 字节，不能用它抓 DOM**（2026-11-16），要渲染后源码一律用 Playwright 驱动 Edge；不需要渲染的批量取数仍用项目 curl_cffi/httpx 通道，但**需要浏览器验证的结论必须以 Edge 打开为准**。本机联网固定走 `http://127.0.0.1:7897`（Playwright 用 `proxy={"server": ...}`）。
- Windows；Python 3.15 装在 `C:\Program Files\Python315`，**项目默认 3.15**（`requires-python >=3.15`，版本声明五处同步：`pyproject.toml`、`uv.lock`、`requirements.txt` 头注、README 徽章、`docs/Development.md` 第 8 节，测试里的 `skipif` 守卫同步）。仓库标准仍是 uv，别把 CI 写法改成本机口径。
- 一律用 `python main.py`、`python -m pytest tests/ --tb=short -m "not network"`、`python scripts/quick_check.py`、`python scripts/check.py --skip-hook-install`；脚本自带 `resolve_tool()` 兜底。
- GitHub：直连 TLS 被 reset、5915 代理 502，**Clash 7897 可用**（命令见上）。推送报 schannel「server closed abruptly」先查是否已推上去。
- pytest 成功时 conftest 的 `pytest_sessionfinish` 会 `os._exit(0)` 丢弃 stdout，**判定只认退出码**，要细节加 `--junitxml`。
- **全量 pytest 用 4 并发**（2026-11-21）：`python -m pytest tests/ --tb=short -m "not network and not integration" -n 4 --dist loadscope`；本机 `-n auto` worker 过多会 `MemoryError`、跑十分钟以上无结果，4 并发约 2.5 分钟且退出码可信。真实 Windows Qt 子进程由 `tests/_qt_windows.py` 用 `PYTEST_DEBUG_TEMPROOT` 隔离临时目录根，避免与主进程/xdist 共用 `pytest-of-<user>` 时批量删除保护把「清理失败」误判成用例失败。
- 沙箱陷阱：①直接调系统 python 触发 stdout 捕获异常 → 命令内 `> file 2>&1` 落盘再读；②中文 Windows 子进程默认 GBK，控制台乱码只影响显示；③用 `-m ruff` / `-m mypy` 走当前解释器。
- PowerShell 7.6.7 在 `C:\Program Files\PowerShell\7\pwsh.exe`（曾因 `AppCompatFlags\Layers` 的 RUNASADMIN 报 740，已清除；再报 740 先查这层，别用 `-Verb RunAs`）。5.1 的 `Set-Content -Encoding utf8NoBOM` 不可用；中文 commit message 一律写文件后 `git commit -F <file>`。仓库无 bash（`bash` 命令不存在。

## 议题定性

- 定性前必须看完用户全部证据（尤其每张截图），日志文本不是证据全集；「用户误读」等于断言无 bug，代价很大。
- 报错消息先验证是「真失败」还是「通知被误伤」；版本定性用状态区指纹（配置文件名 + 数值版本）+ 日志/UI 特征串反推构建落点，不信用户自报版本号；先判「待修复」还是「已修复待发版」。
- 「关工具窗连带主进程退出」两条独立根因：①主窗藏托盘后关最后可见窗 → `quitOnLastWindowClosed`；②取数中关 `WA_DeleteOnClose` 对话框 → 工作线程未等齐被拆。带工作线程的对话框 closeEvent 必须 cancel / 等齐，超时 `setParent(None)` 再放行。

## GitHub 议题处理

- 凭据：`TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')`；议题截图 `curl -sL` 下载后 Read。
- 同一报告人连续多议题先横向看历史。报告人 z291173301 用 Windows 原生边框，几何类议题先问是否默认隐藏边框。
- 回帖逐项回应、礼貌先行、简短坚定并附依据；用 JSON POST（`-d @/tmp/x.json` + `Content-Type: application/json`，勿 `-F`），多行中文用 `json.dump` 生成，发送后验证返回的 `html_url`。
- 采纳以代码/文档证据与根因为准，不以语气或坚持次数为准；**对不尊重开发者的报告人，个性需求一律不采纳，回帖引导 fork**（2026-09-20 明示）。「真 bug」= 现有功能与自身设计/数据语义矛盾或渲染错误；与个人审美不符 = 个性需求。历史上为其偏好已发版的改动不回滚，只把口径应用到新诉求。
- 诉求摇摆 = 高价值返工源：动手前先锁验收口径，同一块代码被改两次以上就停下来对齐需求；施压型 / 纯验证型诉求用实测脚本定量证伪后关单，不改代码。
- 软件内说明文本的主句结构 = 用户眼中的事实清单，覆盖面与例外写成显式注记。
- `wiki/` 是 GitHub Wiki 内容源，每次回帖后把通用答案回填 FAQ（Wiki 仓库需用户先在网页建首页才能克隆）。

## 排查与本地验证

- 仓库根的 `config.json` 是脏配置。验证配置/网络栈用 `Config()` 默认配置写临时文件再指 `manager.path`。
- 行为修复流程：先复现测试跑红 → 修 → 绿 → 反向验证（`git stash push -- <生产文件>` 后必须转红，否则是假测试）→ 反向审查边界与调用点语义。
- 测试必须喂生产形态数据，不手造；网页解析夹具用真实页面快照放 `tests/fixtures/`；结构约束类修复用 AST 哨兵锁位置并反向确认判失败。
- pytest-asyncio strict：文件内全是 async 才用顶部 `pytestmark`；混有同步测试必须逐函数加 `@pytest.mark.asyncio`。
- conftest dummy 双陷阱：实例属性会遮蔽真实 manager 属性；真实 manager 加新方法必须同步给 dummy 加同名，缺了在 Qt 测试里以 qFatal abort 爆。
- 数据质量治理前必须实证全量抽查，不靠代码推断；「功能上可达」≠「正常路径会走到」。
- `CancelledError` 在 task 收集点与 `Exception` 同级软着陆；整轮取消只由 cancel_event 分支负责，`wait_for` 的 cancel 残留不得穿透。
- Emby/Jellyfin 同步：`UpdateItem` 对缺省 `Genres`/`Tags`/`ProviderIds` 空引用，payload 三者恒非 null，日期/年份归一化收口在模型层。**`Taglines` ≠ `Tags`**：UI 的「标签」列一律指 `Taglines`。
- 持久化快照三必备：原子写（tmp + `os.replace`）、按快照比对才清 dirty、停止/退出路径强制落盘；传 `Flags` 全局列表一律 `list(...)` 快照。
- 「日志说成功但文件不存在」第一嫌疑 = 写后无回验；模板：replace 后 exists 校验，不过退直写，仍不落则抛错。
- WinError 123 先实测真实失败串：常因云盘/映射盘文件名超长，出路是降 `folder_name_max` 或先刮本地盘；番号识别第一锚点是日志 `[number]` 行。
- 「开关组合不生效」先画清每个开关的写入端与读取端。
- 测试耗时诊断：`--durations=15` → 单测 profile → 打桩计数；两大真凶 = 生产节流真实 sleep、单测偷跑网络。
- 大范围撤回用 `git revert --no-commit <多提交>` 合并成单撤销提交；同域测试文件归一。
- 打包布局与启动脚本入口假设必须端到点对账（发版前用解压后的真实布局实测一次启动）。
- cmd/bat 在 chcp 65001 下中文注释会字节错位，注释用 `rem`。
- ruff B010/B009 与 mypy attr-defined 组合写法：`obj._x = v  # type: ignore[attr-defined] # noqa: SLF001` + `getattr(obj, "_x", None)  # noqa: B009`。
- 还原/回程类回归用「三态对比探针」定性（fresh → 最大化 → 还原，并排 dump 几何）；复现 UI 几何时不得 stub QSS。
- `edit` 工具会静默忽略缩进差异，改完立刻 `read` 复核。

## Qt 生命周期

- `MyMAinWindow.closeEvent` 由 `WindowOpsMixin` 提供且末尾恒 `a0.ignore()`：要加清理绝不能新写同名方法（会遮蔽 mixin），应加在 mixin 内部（新增 `hideEvent` 安全）。查归属用 `"closeEvent" not in MyMAinWindow.__dict__`。

## UI 开发与排错

- 改 UI 先改 `.ui`（唯一权威源）→ `"C:/Program Files/Python315/python.exe" -m PyQt6.uic.pyuic`（相对路径）→ `scripts/fix_qt_enums.py` → `ruff format` → `tests/test_ui_structure.py`。禁止手工改 `MDCx.py`。
- 布局问题先写最小复现脚本验证 Qt 原生行为。常见根因是 BoxLayout / QGridLayout 缺末尾 Expanding 间隔（`setVisible(False)` 管不到 QSpacerItem）；末尾 Expanding 的 `sizeHint` 必须写 `0x0`，否则末行下方留死空白。
- 富余高度被吃掉两种：①灌给该行唯一控件（wordWrap 标签，表现为文字垂直居中留白 + 后续行被下推）→ .ui 补垂直 Expanding + 运行期把容器高钉成 `layout.sizeHint().height()`；②在顶/行间/底均分 → 把行首留白折进 `contentsMargins`，组高按「容器底 + 固定底留白」收紧。
- 通用宽幅同步只改宽不改高：wordWrap 组拉宽后变矮，空白堆在网格底部 → 挂 `_post_wide_sync_hook`，按 `childrenRect().bottom() + 1` 量真实底边并同步平移其后各组，窄态显式复位。
- **凡「通用宽幅同步 + 页面定制对齐」两层叠加的滚动区，定制对齐必须挂 `CustomScrollArea._post_wide_sync_hook`，不能只写在 `_sync_page_layouts` 里**（2026-11-21 工具页输入框缩小事故）：滚动区自身 resizeEvent/showEvent 会单独跑 `sync_wide_children_width()`，不经过主窗全量同步；只写在全量同步里的对齐会在那一拍被通用拉伸覆盖，留下「控件停在窄/错位中间态、切页或重启才恢复」的幽灵 bug。钩子内按拉伸落定后的实时锚点重算绝对几何（幂等），并在 `_sync_page_layouts` 显式拉伸后调用**同一个**收口方法，两个入口不许各写一份；顺带留一条「摘掉钩子用例必红」的回归守护。详见 `docs/Development.md` §10.20。
- **绝对定位控件改宽前先算 `_classify_inner` 阈值**（2026-11-21 清理按钮）：`sg.width() >= inner_w*0.5` 判 `_STRETCH`、`右缘+1 >= box_w*0.9` 判 `_DOCK_RIGHT`、都不满足才是 None（通用同步完全不碰，宽度只能定制方法运行时 `setGeometry` 给）。把按钮设计宽从 321 直接写进 `.ui` 改成 405 会跨过 340.5 阈值变 `_STRETCH`，宽态被拉成 `405+extra`——用户要的「宽态保持窄态宽度」立刻破功。对齐 `_STRETCH` 输入框右缘时差值随 `extra` 变，一律运行时 `mapTo` 实测、不写死；宽态要冻结宽度就记录非宽态基准，判态门限与同页其它按态换列逻辑共用一个常量。详见 `docs/Development.md` §10.21。
- 重影/重叠先问「渲染层还是定义层」：定义层同 cell 多控件用 .ui 文本级哨兵 grep 该 grid 全部 `<item row=` 确认严格递增。实机截图是最终判据。
- 行首「空 QLabel 做缩进」是对齐的隐形敌人（grep 文案搜不到，最小宽改 0 也不行——spacing 还会留 6px）：要左对齐直接从 .ui 删那枚 item。
- 把末位项右移到锚点竖线：在前插 `Fixed` `QSpacerItem`，宽度 = 锚点 x − 前导右缘 − spacing，并夹到 `[0, slack]`；收到 0 仍偏右再逐像素压 `row.setSpacing()`（每遍先复位设计值）。别用 `_pin_row_lead_width` 钉前导控件（下拉框被撑成几百像素、复选框吞掉留白区）。
- 间隔插在前导控件之前时，禁止用实测坐标反推同一行后续间隔（那一拍还挂着上一遍的宽间隔），必须用本遍刚算出的 gap，并写进产生 gap 的那个方法内部。
- 位置类需求判据只用锚点 `sizeHint()`，**不要加「不裁字」下限**：`max(锚点宽, minimumSizeHint())` 在 80% 界面缩放下会右出约 20px。宽度小于 minimumSizeHint 是用户自己选的取舍。
- 「文字右缘」≠ widget 右缘：QCheckBox 用 `style().subElementRect(SE_CheckBoxContents, opt, box).x() + horizontalAdvance(text)`；QLabel 用 `x + horizontalAdvance(text)`。
- QBoxLayout 的 spacing 不在 spacer 相邻侧生效（4 枚复选框 = 3 段），按 `count()-1` 算会把行撑破。
- 删 `.ui` 控件 = 删代码里的 `ui.<name>`：先 grep 控制器 / `_snapshot` / 行内最小宽算式，删完重跑 pyuic 与 `test_ui_structure`；参与「行内最小宽」的项要同步去掉它的 sizeHint。
- 删某行唯一可拉伸项前先确认该行还有伸展能力，否则整列被压到 sizeHint、整页右移（补一枚 0×0 Expanding 间隔）。
- 主窗最小尺寸是动态的（`_adaptive_window_sizes` 按屏幕可用区算）：矮窗几何测试先 `setMinimumSize(0, 0)`，断言裁切用 `win.height()` 而非目标 resize 值。
- 要真机字体度量别用 offscreen（`QFontDatabase.families()` 返回 0 字族）：按 `test_window_state_matrix.py` 的 `win` fixture 思路 monkeypatch 掉启动自检再 `grab().save(png)` 对拍。
- 窗口状态汇聚点审计：grep `setWindowState|activateWindow|showNormal|show|hide` 全库枚举，逐一加「可见且未最小化」守卫；配置保存/加载等业务函数不得操控窗口状态；托盘隐藏后 eventFilter 不得自动 `show()`。
- PyQt6 测试纪律：含 Qt 的文件顶部（PyQt6 导入前）自持 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`；fixture 构造后立即停全部 QTimer；qFatal abort（栈无 Python 行号）查 QTimer 槽与 dummy 桩缺方法；隔离配置目录用 `monkeypatch.chdir(tmp_path)`。
- 极窄窗宽下的对齐判据写「不劣于关掉本功能的基线」，不要写绝对 `width >= sizeHint`（会得到永远红的假用例）。
- 造「本需求之前」的基线：把该需求的唯一落点入口桩成 no-op 最省；入口被多处共用时要同时断言「目标确实被搬走了」。
- **程序回填输入框的内容不许写进配置，也不许回流成查询输入**（2026-11-20「获取演员原名」定规）：用 `textEdited` 记「用户最后手动输入名」（`setText()` 不触发该信号），`save_config` 仅当输入框文本恰好等于最近一次回填文本时改存影子值，用户手改后 `textEdited` 清掉该槽标记即按当前文本正常保存；查询提交同样取影子值，否则逗号分隔的展示文本会被 `parse_actor_entries` 拆成多个演员、各出一张表。跨线程回填一律走 Qt 信号到主线程 `setText`。

## 并发与网络库

- curl_cffi 0.16 流式关闭 = `quit_now.set()` + `await aclose()`（单独 aclose 会拉满响应体阻塞，单独 close 后 cleanup 抛 TypeError）。同步 `close()` 只是发起 abort。
- 「Task was destroyed」第一怀疑 = 某个 cancel 没人消费或内部任务没人等（shield 模式 cancel 后必须 gather）。
- 内网/自建服务（Emby/Jellyfin）不得复用爬虫重型指纹栈（只对 127.0.0.1 免检）；控制面 API 用轻量 httpx 直连客户端，返回形状对齐 `(data, error)`。
- 「取消打断收尾」租约泄漏：双残留 = Computed 级、单残留 = CrawlerProvider 级；防护三件套 = 释放路径 shield / try-finally 恒释放 / 逐实例 suppress。
- LogBuffer 任务树归因：写入按 `_ROOT` contextvar，`process_one_file` 入口 `new_root()` 切断兄弟继承。
- 后台线程跑异步一律走全局 `AsyncBackgroundExecutor`，禁用 QThread 内自建一次性 loop（curl_cffi 定时器注册到死 loop → Windows 弹 Python-CFFI error）；AST 哨兵锁方法内不得出现 `new_event_loop` / `run_until_complete`。
- 并发范式：文件间 `asyncio.wait(FIRST_COMPLETED)` 滑动窗口，文件内多站点 `gather`；后台协程走 `utils/qt_thread.py::run_in_background`，结果经 Qt signal 回主线程；新增后跑 `scripts/check_thread_safety.py`。
- `AsyncBackgroundExecutor` 的 default executor 与主 loop 是两个池，「嵌套 to_thread 死锁」先实测两池是否同一个。devbox 代理 127.0.0.1:7890 可能无进程。

## 站点与网络

- 各站探测番号与收录依据见爬虫类注释；JavDB 仅 FC2 系列需要 Cookie。
- **查缺站点入口按实测表改，不凭猜**（2026-11-16）：9 个聚合/综合站的搜索 URL、番号位置、分页与不可用结论都记在 `docs/Development.md` 第 18 章「聚合/综合站「按演员名搜番号」调研」，新增或修改 `actor_sources.py` 的 fetcher 前先按该表复核；URL 变更要用 Edge 实际打开验证，HTTP 200 不等于入口可用（AVBase 会回 200 但 `works` 为空、Lulubar `bysearch` 稳定 403 CF）。自动判断固定链由 `test_auto_site_chains_match_user_spec` 精确钉死，新增站点走「指定类型」配置组，不要顺手改固定链。
- **查缺主流程三条硬口径**（2026-11-16 审查定稿）：① 本地番号对比只用**本次扫描的 `local_movies` 快照**，绝不用跨次不清空的全局 `Flags.local_number_set`；② `number_list.json` 只在**扫描循环结束后写一次**，不在每部影片里全量重写整份 JSON；③ 番号前缀只削开头数字（`_strip_number_prefix`），保留 `-2`/`-C` 分集后缀与 `FC2-PPV-` 多连字符。站点级异常必须写日志，不能压成空结果后照常打印「查询完毕」。
- **厂牌官网查缺入口**（2026-11-16 实测）：29 家同源 CMS 厂牌官网 + DAHLIA 统一用 `{base}/search/list?keyword={关键字}&countup=0`，番号在 `/works/detail/{番号}` 末段（**站内多为无连字符**，`normalize_key` 能与本地库对齐），分页追加 `&page=N`；演员名可直接当关键字。**另两家独立系统**：MGStage 用 `search/cSearch.php?type=top&page=N&list_cnt=120&actor[]={演员名}_0`（**必须日文原字/繁体名**，简体不命中；首次可能撞年龄门，走 `crawlers/base/age_gate.py` 的成人入口），Faleno 用 `wp-json/wp/v2/works?search={演员名}`（WordPress，命中 `acf.出演女優`）。三处站都是繁体站，**名字要试原样/繁体/简体三种**。改这些站点的入口前先按 `docs/Development.md` 第 18 章「厂牌官网按演员名搜番号」复核。
- 站点 API 坑：missav_api 的 Recombee 仅 POST；DMM Affiliate v3 必需 site/service/floor 且 keyword 用 content_id 形态；madouqu 域名动态维护（24h 缓存）；madou_club 番号无横杠；parsel `Selector.get()` 纯 JSON 返回 dict（解析兼容 str/dict/Selector 三态）。
- 站点收录边界：AVEntertainments 只在无码组；Getchu 大陆 IP 过不了 CF 故从六组移除；Official·有码 29 站只在有码组、无码五站只在无码组。
- **类型默认名单排序**（2026-11-12 用户口径）：有码/无码组移除官网组（见下条「官网路由无条件优先」），其余各组全部 JSON 站 A-Z、其余站 A-Z；欧美组与动漫里番组全组 A-Z。实现只在 `models.TYPE_DEFAULT_SITES` 一处排序，其它名单（`default_config.json`、使用说明、`docs/Features.md`、测试期望）全部同源跟随。
- **Official 聚合：JSON 优先 + 成员边界**（2026-11-13 / 11-18 用户口径，原两条合并）：`Official`（MyWife_JSON/PRESTIGE_JSON + 34 有码官网，`Prestige_JSON` 已并入下拉、存量偏好迁移收拢）与 `Official·uncensored`（3 家 JSON + 5 网页站）都先打 JSON 版；单站 JSON 有数据但缺字段时由对应网页版只补空字段（标题/番号以 JSON 为准，番号对不上不补，仅官网体系生效）。成员按 `OFFICIAL_CENSORED_GROUP_SITES` 过滤：有码 34 家归 `Official`（能力文案「官网：有码」），无码官网及对应 JSON 归 `Official·uncensored`；`resolve_official_aggregate_site` 仍解析全部 39 站，由调用方按组过滤。
- **官网路由无条件优先 + 类型名单剔除官网组 + 级联兜底**（2026-11-12 用户口径）：番号前缀命中路由表（`site_routes.collect_site_routes` 即「路由列表」导出源）即先刮对应官网（含其 JSON 版），**自动判断与锁定有码/无码同口径**（锁定分支也先 `resolve_official_aggregate_site`）；官网被禁用/无结果/字段不全由该类型启用网站补齐（`_official_route_fallback_classification`，不再以「启用名单含官网组」为前提），兜底名单剔除整个官网组（同源不重请），直接从 7mmtv_JSON 及之后的启用网站刮削。自动判断下官网+有码/无码组都无数据时依次 **国产传媒→国产短剧→个摄→欧美** 级联兜底（`_official_route_cascade`，前缀与有码/无码重复尤其国产传媒最严重；锁定类型不级联）。**有码/无码等七类类型名单与「编辑网站」可用网站/启用网站不再含 `Official`（Official·pixelated）/`Official·uncensored` 聚合与官网单站**：`TYPE_DEFAULT_SITES` 有码组移除 34 有码站 + MyWife_JSON/Prestige_JSON、无码组移除 5 网页站 + 5 JSON 版，`_open_site_editor` 候选区过滤官网成员，存量配置由 `_migrate_official_groups_removed`（标记键 `official_groups_removed_migrated`）剔除；官网单站只在「官方网站」源窗口编辑，指定网站下拉/检测网络分组/禁用名单/全局字段优先级保留官网值。FC2/FC2-/FC2-PPV/FC2PPV 仅当位于**文件名首位**才路由个摄番号组，MyWife 仅当位于文件名首位才路由官网 MyWife/MyWife_JSON；均不区分大小写、-/_ 通用，含在文件名中间不再命中（`file_crawler._name_starts_with`，无文件名时退回番号首位判断）。
- **图片来源优先级 = Amazon > DMM > 官方网站 > 其他（2026-11-20 用户定规，取代 11-12 口径）**：设置项文案「优先从Amazon、DMM、官方网站下载图片」（`Config.field_priority_image_source_priority` / `MDCx.ui` / `MDCx.py` 同源）。字段优先模式下，有码/官方网站的 `web.image_source_group` 档位为 Amazon(0) > DMM 站(1) > DMM CDN 直构(2) > 对应官网(3) > MGStage 官方直构(4) > 其他站点(5)；官网档只认番号路由到的那家官网及其配对 JSON 版（`web._official_image_sources`，与刮削路由 `resolve_official_aggregate_site` 同源），其它官网降入其他站点档——只从对应官网下载，不从其他官网下载。优先档按「档位 → 尺寸」选优后按序下载，第一个成功即停（已下到封面图/缩略图就不再下载其他网站），优先档全部下载失败才降级到队尾的其他站点候选——**不再预先过滤 group 5**（11-12 的 `_prune_*_priority_only` 已删）。无码只保留对应官网 > 其他站点，其它类型不按来源重排、只按尺寸选优；组内选优、失败降级、勾选本地文件直接跳过下载均不变。
- **DMM / DMM CDN 图片仅限有码/动漫里番/官方网站**（2026-11-21 用户定规，当日追加官方网站档）：`web.dmm_images_allowed` 放行 `YOUMA`/`DONGMAN`/`OFFICIAL`（官方网站档与日亚门禁一致），其它类型（含自动判断未定）不下载、不探测、不直构 DMM 站(group 1) 与 DMM CDN(group 2) 的封面图/缩略图/剧照；入口覆盖 `_order_*_candidates`、`_build_poster_candidates`、`extrafanart_download`（主候选与 fallback）、`_direct_image_candidates`、`_build_dmm_poster_candidates`、thumb 的 `find_valid_dmm_cover` 兜底。自动判断误归有码按 `web._result_looks_like_other_type` 复核（纯无码/国产马赛克 + 主字段来源属于「其它类型专属站点」），与 Amazon 门禁共用；MGStage 与 Amazon 校验用的 DMM 内存参考图不受影响。爬虫层 `upgrade_dmm_cover` 生成的 awsimgsrc URL 由下载层统一拦截，不逐站改。
- **Official· 前缀界面显示规则**（2026-11-12 用户口径）：界面仅三个站点下拉保留 Official·——指定网站（`Official` 聚合显示为 `Official·pixelated`，`_SITE_DISPLAY_ALIASES`，UserRole/存盘仍 `Official`）、网络检测、当前网站；其余界面（图片来源标签 `image.py`、字段来源/站点摘要 `show_result`、评分来源后缀、刮削日志 `file_crawler._display_site`、检测日志 `log_console.with_site_prefix`）一律去 Official· 显示短名。官网单站定位说明（crawler `description`）统一「官网：有码」/「官网：无码」，禁带 ·站点名 后缀与（JSON API）/（JSON-LD）括号技术说明——网络检测下拉文案与候选区悬停同源。网络检测筛选弹窗右缘钉死对齐全选/全不选按钮右缘（`_layout_net_filter_popup`），不随选项文案长短加宽缩窄。
- **NO_PROXY 兼容基线**（2026-11-13）：宿主机代理工具（Clash 等）把 IPv6 回环写成 `[::1]` 塞进 NO_PROXY，httpx 0.28 不认带方括号 IPv6 → 非法挂载键 `all://*[::1]` → trust_env 客户端构造抛 `InvalidURL: Invalid port`。修复在 `mdcx/proxy_compat.py::normalize_no_proxy_env`，`mdcx/__init__.py` 导入即把 `[host]` 归一成 `host`（httpx 会自动补回方括号），进程级覆盖全部 httpx 客户端创建点；新增 httpx 客户端无需各自设防，测试桩（`httpx._utils.getproxies` 置空）只作跨机器确定性兜底。
- **指定网站聚合行徽标**（2026-11-11）：`Official` / `Official·uncensored` 不是真实站点、没有自己的检测键，状态圆圈按成员站检测结果聚合（成员名单与刮削展开同源 `OFFICIAL_CENSORED_GROUP_SITES` / `OFFICIAL_UNCENSORED_GROUP_SITES`）：成员同色→该色、颜色不一→黄、没测过→无圈，与检测网络筛选框分组行同规则；悬停取成员里最新一次检测时间。实现 `init._aggregate_site_check_entry`，初始填充与检测后刷新共用 `_site_check_entry` 取条目。
- **联动站点组规则**（2026-11 用户定规；实现唯一来源 `models.SITE_GROUPS` + `models.WEB_TO_JSON_SITE`，界面在「编辑网站」弹窗）：
  1. **定义**：同一数据源的多条访问通道（网页版 / JSON 通道 / 官方 API / 移动端 APP / 镜像站）登记为一个联动组，组内站点互为替代、算同一份数据。
  2. **加入补齐**：在「可用网站（按类型分组）」里加入组内任一站点，同组其余站点一并加入（`expand_site_groups`，候选区里没有的成员不补）。
  3. **移除不复活**：加入后可在「启用网站」手动移除单个站点，移除结果原样保存，不会被再次自动加回。
  4. **排序独立**：启用列表（从左到右优先级递减）里的手动排序对组内站点相互独立，移动一个不带动其余。
  5. **移除只删选中项**：一次只删选中的那几个，不连带同组站点。
  6. **JSON 优先 + 网页版兜底**：组内同时有网页版与 JSON 版时，`WEB_TO_JSON_SITE` 指定 JSON 版优先（`file_crawler._prefer_json_site`），JSON 不可用或字段缺失时按 `JSON_TO_WEB_SITE` 回退网页版。
  7. **一站一组**：`_SITE_GROUP_OF` 由 `SITE_GROUPS` 派生、后写覆盖先写，同一站点只能登记在一个组里（LibreDMM 因此挂在 DMM 组、FC2 与 FC2CMADB 同组）。
  8. **边界**：联动只作用于「编辑网站」的加入/移除，不改类型默认名单 `TYPE_DEFAULT_SITES`、不改检测网络的分组行与勾选展开。
  当前 21 组：DMM⇄DMM_JSON⇄LibreDMM⇄LibreDMM_JSON、FC2⇄FC2_JSON⇄FC2CMADB⇄FC2CMADB_JSON、7mmtv⇄7mmtv_JSON、Airav.cc⇄Airav_JSON、Official·HEYZO⇄HEYZO_JSON、Official·Caribbeancom⇄Caribbeancom_JSON、Missav⇄Missav_JSON、AVMOO⇄AVMOO_JSON、AVSOX⇄AVSOX_JSON、JavFree⇄JavFree_JSON、AVBase⇄AVBase_JSON、Official·1Pondo⇄1Pondo_JSON、Official·Pacopacomama⇄Pacopacomama_JSON、Official·10Musume⇄10Musume_JSON、ThepornDB_JSON⇄AVheat⇄AVHeat_JSON、JavDB⇄JavDB_JSON、Madou.club⇄Madouqu⇄Madouqu_JSON、Official·Prestige⇄Prestige_JSON、Official·MyWife⇄MyWife_JSON、R18.dev⇄R18_JSON、TheJavDB⇄TheJavDB_JSON。
- 「素人番号」已改名「国产短剧」（枚举值/字段名仍是 `SUREN` / `website_suren`），默认名单为 JavDay + Lulubar；短剧无番号格式，只有锁定类型才走这一组。
- 七组名 = 有码番号/无码番号/个摄番号/欧美番号/国产传媒/国产短剧/动漫里番；下拉八项多一个「自动判断」。组名与下拉文案、chip 短名、`PALETTE_GROUP_TYPES` 组序同源；下拉下标↔值映射读 `FixedScrapingType.dropdown_values()`（顺序源 `dropdown_order()`，不能写成类体常量——Enum 会报 TypeError）。
- 下拉能力文案与候选区悬停解耦（严格执行）：候选区悬停用全称（有码番号/无码番号/个摄番号/欧美番号/国产传媒/国产短剧/动漫里番），当前网站/指定网站下拉用短词（有码/无码/个摄/欧美/国产/短剧/动漫）防挤压右侧地址列；类型刮削、指定网站、当前网站三者显示互不影响，改一处不联动另一处。
- 官网能力文案（2026-11-10 用户口径）：官网单站名单里不再写「官方」——有码官网「官网：有码」、无码官网「官网：无码」，候选区全称分别为「官网：有码番号」「官网：无码番号」；Dahlia/Faleno/MyWife/Prestige/MGStage 等改名站也统一用「官网：」前缀。
- 「锁定类型」运行期只有一张真相表 `models.SCRAPING_TYPE_SITE_FIELDS`；保留 `getattr(config, field, None)` 惰性取值；锁定分支只给 `GUOCHAN` 硬塞 `mosaic="国产"`；回退类型名单必须用有序的 `get_type_sites()`，不能用 `list(set)`（Website 枚举 str 的 hash 每进程随机化）。
- 有码 29 站由 `official_sites.py` 统一路由（321 前缀锁定），与 `Official·Dahlia`/`Official·Faleno` 同单站锁定语义；改名的四站（Dahlia/Faleno/MGStage/Prestige）已并入候选区 `Official` 聚合行。
- 被墙站测试：`-m scripts.dev_proxy start|status|test <url>|stop`，日本 IP 限制站用 `--port 7891 --regions "jp|日本"`；连通性验证必须用 curl_cffi impersonate；批量探测要校验 `data.title` 防假阳性。
- HTTP 4xx/5xx 错误串必须携带截断响应体（保留 `"HTTP {status}"` 前缀）。
- 番号归一化：前导单数字双重语义（studio 名单数字保留 vs DMM 预约版 `9` 前缀剥掉），改正则前 grep 全部分支。**DMM cid → 番号（`shared_fields.dmm_number_from_cid`）要剥掉厂商码与版本标记**（2026-11-18）：mono 线 `9ssis287` / `77midv400` 的前导数字是厂商码，`4kssni989` 的 `4k` 是 Ultra HD Blu-ray 版，`mide599bod` / `hoiz155dod` 的 `bod` / `dod` 是 Blu-ray / DVD On Demand 版，素人厂商前缀 `h_` / `n_` 同理；剥完才与 digital 线 `ssis00287` 同键，演员番号导出才不会一个番号两行。唯一例外 KIRI（厂商码恰为 4，cid=`4kiri00001`）不剥 `4k`。改这条正则一律拿 `resources/userdata/dmm_cid_routes.json` 的白名单 + 系列路由组合全量回放，比对旧实现确认 0 回退。**尾部标记与促销前缀口径（2026-11-18 联网复核补全）**：必须先用结构化 fullmatch 把核心 `((?:[hn]_\d+|\d+)?[a-z]{1,10}\d{2,7})` 与标记 `((?:[a-z]+\d{0,2})+)` 切开再剥，不能直接按「数字后的字母尾」剥——那样 `h_1743aabh00001` 被切成 `H-1743`（实测 73066 条回退），2 位编号路由组合 `h_086abba01` 与「厂牌+标记」同构会被整段吃掉（收窄成 `(?:[a-z]+\d{0,2})+$` 仍有 1858 条）。标记含 `r`/`x`/`f`/`re`/`redod`/`sodod`（租赁/特価）、`ai`/`soai`/`mtn`/`jo01`/`sa1`（AI リマスター/総集編/まとめ）、`tk1`/`tktb`/`dl`/`dp`/`b`（赠品）、分卷字母 `a`；促销前缀 `td0NN`（特価）与 `d1`…`d6`（FANZA 限定赠品版）在切分**前**剥，`4k` 在切分**后**剥。厂牌本身含数字（`h_1337wvr9c00018`）认不出结构就原样大写返回，不猜。
- **DMM 演员目录翻页必须以 `result.total_count` 收手**（2026-11-18）：`actor_sources._fetch_dmm_api` 的固定 `offset <= 3000` 护栏会静默截断大目录（波多野結衣 digital 3937 / mono 4581，两条线共丢 2518 条原始记录、930 个番号）。改成 `offset > total_count` 即停，`_DMM_OFFSET_CEILING=20000` 只作 total_count 异常时的跑飞护栏、不是目录上限。核验口径：两条产品线实拉条数必须各自等于 total_count。护栏是「单演员 × 单产品线」口径、不跨演员累计（多演员在 `tools/missing.py` 串行逐个查，`offset` 每线重置为 1，传入的 `names` 只是同一演员的名字变体）。**配套超时**：DMM_JSON 在 `_SITE_TIMEOUTS` 单独放宽到 300s（照 HBOX_JSON 先例）——默认 120s 会让大目录在翻完前被 `_out_of_time()` 收手，缺号表现与 offset 截断一样；DMM 网页版仍 60s 且转调同一个 `_fetch_dmm_api`。
- **工具页「去重复番号」是独立模块 + 合并键与展示形态解耦**（2026-11-21 用户定规）：去重实现只在 `mdcx/utils/number_dedupe.py`，四个公开函数——`dedupe_key(raw)`（去重口径键，`normalize_key(format_number(raw))`，同一部影片的各种写法收敛成一条）、`spelling_key(raw)`（不去重口径键，`normalize_key(display_number(raw))`，只归一大小写/分隔符、**不**剥厂商码）、`number_key(raw, dedupe=)`（按开关二选一）、`dedupe_numbers(numbers)`（给站点自己收番号列表时直接调用，返回保留首次写法的去重列表）。模块只依赖 `number_format` / `shared_fields` 两个纯字符串工具，不反向依赖业务模块。**它与「格式化番号」是两件独立的事**：「格式化番号」只决定*番号名长什么样*（勾选走 `format_number` 剥壳，不勾选保持各站 `display_number` 原形态）；「去重复番号」只决定*哪些写法算同一部影片*（勾选时合并键按去重口径收敛成一条，不勾选时各站原写法各占一条、即便格式化后番号名相同也照样分行）。四种组合的期望行为：格式化+去重 = 先格式化、格式化完成后再对番号去重；只格式化 = 只格式化不去重；只去重 = 只去重不格式化；都不勾 = 既不格式化也不去重。**合并键必须从「传入的原始番号」算，不能从展示形态反推**：`spelling_key` 在格式化后会变（`spelling_key('9SSIS287') != spelling_key('SSIS-287')`），所以 `actor_sources._merge` 用 `number_key(raw, dedupe=_DEDUPE_NUMBERS.get())`（`raw` 是入参原文），跨站合并的同番号分支直接在 `merged[key]` 上补元数据，不再回调 `_merge` 重算键；`dedupe_key` 幂等是「先格式化再去重」与「直接去重」同口径的保证。ContextVar `_DEDUPE_NUMBERS` 与 `_FORMAT_NUMBERS` 各自独立，由 `collect_numbers(dedupe_numbers=...)` 设置并在 `finally` 复位。**站点出口 `_format_site_hits` 按去重开关分两条路**：去重未勾选时**只**把展示形态按格式化开关改写、**不重新按番号合并**（否则 7mmtv 那种「同一番号多版本：有码原版/reduced-mosaic/中文字幕」会被压成一条，违背「未勾选不去重」），且要保留原条目与原键；去重勾选时才走 `_merge` 重算合并键。7mmtv 站内的多版本保留同理：去重未勾选时按 `detail_url` 为键保留每一条网页条目，勾选时才走 `_merge`。本地比对键要同口径：`_scan_local_numbers` 返回的键与 `_report_actor_result` 的 Flags 回退集合都按 `number_key(n, dedupe=dedupe_numbers)` 算；但 `Flags.local_number_set` / `local_number_cnword_set` 与 `number_list.json` 缓存**仍写原值**（其它工具共用，不能被本工具开关改写）。两枚复选框各写各的 `missing_dedupe_number` / `actor_number_dedupe_number`，默认不勾选，旧配置缺键由 `_migrate_dedupe_number_checkboxes` 补 `False`（幂等，用户显式写过的 true/false 一律原样保留），`config_version` 保持 2。
- **工具页「格式化番号名」是独立模块 + 唯一漏斗 + 站点出口兜底**（2026-11-18 用户定规）：格式化实现只在 `mdcx/utils/number_format.py::format_number(raw)`（内部复用 `dmm_number_from_cid`，MyWife 走 `mywife_number` 权威形态归一化），排查/修改只动这一处，别在各站 fetcher 里各写一份。接线点两处：`actor_sources._merge` 是全部站点番号的唯一漏斗（37 处调用、`NumberHit` 只在此构造），按 ContextVar `_FORMAT_NUMBERS` 决定 `format_number` 还是 `display_number`；`_run_source` 的 `if hits:` 出口再调 `_format_site_hits`（内部复用 `_merge`）兜一次，保证 **70 个注册刮削器**无论内部怎么拼番号都同口径——MyWife 那两处在 `_merge` 之后恢复权威号的逻辑、以及将来自己构造 `NumberHit` 的新站，都靠这个出口接上（`format_number` 对 `Mywife No.1693` 幂等，不会覆盖权威形态）。开关由 `collect_numbers(format_numbers=...)` 设置并在 `finally` 复位。**不要改成「`collect_numbers` 返回后再统一格式化一遍」**：那样 `per_site_out` 逐站结果与合并结果口径不一致，逐站取号量/独占番号统计也会失真。不勾选时出口原样返回，不多跑一遍 `_merge`。`format_number` 必须幂等（补齐阶段会再走一遍）。两枚复选框各写各的 `missing_format_number` / `actor_number_format_number`，默认不勾选，旧配置缺键由 `_migrate_format_number_checkboxes` 补 `False`（`[迁移]` 前缀必须带，否则 `manager.load()` 不回写反而进 `_failed.json` 保护），`config_version` 保持 2。
- **工具页查缺两组复选框文案与提示语对齐**（2026-11-18 用户定规，2026-11-21 三改）：文案是「获取单演员」「读本地番号」「格式化番号」「去重复番号」「获取演员名」，**一律 5 个汉字**，五枚同行、x=158/263/368/473/578、宽 100。缩间距 + 加第五枚是同一次改动：用户要求在「格式化番号」右侧、「获取演员名」左侧插入「去重复番号」，若沿用旧的 6 字文案与 112px 宽，最右一枚会超出所在组框右缘，所以同批把五枚文案改成 5 字、间距由 116px 收到 105px、宽度收到 100px。**5 字是新上限**：工具页 QSS 字体 13px，`centralwidget` 的 `QCheckBox::indicator{width:14px;border:1px}` cascading 下来指示器实占 16px，100px 复选框的文字区剩 84px，5 字 65px 留 19px 余量；6 字要 78px 只剩 6px 余量、加到 7 字要 91px 直接裁掉末字。同理 `label_41`「刮削排除目录：」7 个全角字符需 91px，宽度必须 ≥94（与 `label_3`/`label_10` 同 x=46、同宽 94），90px 会裁掉全角冒号、看着像没跟其它路径标签左对齐。回归见 `tests/test_tool_page_text_width.py`（真实字体度量 + `.ui` 设计几何，不写死字数）与 `tests/test_format_number_option.py`（文案、位置、组框不重叠）。「本地资源库和演员名都可以填写多个，以中英文逗号分开」提示语在复选框**下一行**，x=50 / 宽 591，与「移动…Movie_moved」提示 `label_8` 完全同几何——左缘上下对齐是用户明确要求，宽度也必须一致：`CustomScrollArea` 按右缘比例分类跟随，宽度不同会让两条提示一条右缘锚定、一条保持原位，页面拉宽后对齐就散了。改这两组高度要同步下移组内按钮与后续 `groupBox_19` / `groupBox_scrape_cache` 及内容总高，组间距保持 20px。
- 站点域名优先级与删站属产品取舍，查证给方案不擅动；删站影响面 = 注册表 + Website 枚举 + 默认 proxy 列表 + `migrations.py` 清洗 + UI 列表。
- **站点默认地址一律不带 `www.`，唯一例外 Official·MGStage**（2026-10-24 定规）：`base_url_()` 默认值、AIO `fallback_domain`、`DEFAULT_SITE_URLS` 都不加，自定义网址也不再自动补 www。改默认地址一并核对 `docs/Scraper.md` 两张表。
- **失效域名直接删，不留兜底**（2026-10-24）：删到只剩一个地址的站点（7mmtv / IQQTV / freejavbt）连镜像轮换一起删。
- 「当前网站」下拉网址列显示一律去 www（`init._display_site_url`，只改显示）；新增配置 `last_custom_website`，交互中只置脏标记、`exit_app` 时落盘（别在交互里 `manager.save()`）。
- 带语言段的入口地址不能直接当前缀拼：`base/web.py::site_root()` 先收敛成 `scheme://host`；missav 默认地址为 `https://missav.live/cn`（2026-11-09 用户指定去掉每片轮换的 dm 段，请求时站点 302 到当片 `/dmXX/cn/` canonical；旧 `/dm79/cn` 硬编码已废弃），不带语言段会被 302 到英文页。
- JavDB 两源：javdb（网页/镜像站轮询，与旧 JavDB_API 同实现）/ javdb_app（App API，免 CF 最稳）；thejavdb 与 javdb 无关。App 签名见 `docs/Javdb_App_Signature.md`，排障锚点 = 三主机同时 4xx 或 InvalidSignature；搜索 limit ≤ 50，分页须 `movie_sort_by=release`。
- javdb 图源无水印体系：`tp.spfcas.com` 是 App 专用（单字节 XOR），`c0.jdbstatic.com` 带水印；解密集中在 `base/web.py`。加密流尺寸探测 (0,0) 属预期。
- **ThePornDB 口径（2026-10-30 / 11-09 定规，原三条合并）**：接口基址 `api.theporndb.net`，主域 `/api` 仅在连接层失败或 Cloudflare 挑战页时由 `with_fallback_base()` 兜底一次（真 403 / 404 不重试）。401 = Token 不存在/失效；403 = Token 有效但无该接口权限，绝不能提示「检查网络或代理」，哈希直查 403 退到标题搜索；判定与文案只在 `mdcx/utils/theporndb_token.py`。「站点检测」行打 ALDN-494 的 JSON 详情 `https://api.theporndb.net/jav/568c12b8-756f-4d01-bb6c-cdc9d7382451`，`probe_url` 走 appoint_url 真实刮削并带 Bearer Token，番号/uuid 单一来源 `ThepornDB_JSONCrawler.probe_number` / `probe_uuid`。
- **18+年龄门一律选成人入口**（2026-11-07用户定规，MGStage误报根因）：凡遇「18岁以上/はい（アダルトへ）/すすむ/確認」一律点成人入口，绝不进「いいえ/MGSシアター/未成年/否」分支。实现只在`mdcx/crawlers/base/age_gate.py`（判定`is_age_gate_page`+提取`extract_adult_entry_url`+点选`follow_adult_entry`+五站成人Cookie常量），各站只调模块不得自写一套（MGStage旧私有判定已改为别名，Hbox/DMM/GetchuDL/JavBus的Cookie同源，Getchu主站「すすむ」同口径，JavBus的POST确认+验证码层保留站内实现）。
- **刮削探测必须复用真实抓取路径**（2026-11-07与上条同因）：`_probe_crawler_capability`对带`_fetch_search`的爬虫一律经`asyncio.wait_for(crawler._fetch_search)`探测（含各站年龄门兜底），不得另起raw`client.request`绕过；无`_fetch_search`的最小替身才回退raw路径。仍过不去的年龄确认页（年龄确认页/年龄认证/年龄验证/adcCookie/AgeVerification，含JavBus验证码层）是确定性结论，首轮即定论，不走45s/60s递进。
- **刮削探测全站直达详情页、搜索优先直连为例外**（2026-11-09 用户定规）：所有站点的网络检测探测必须落到详情页真实刮削。默认走 `_generate_search_url` → `_fetch_search` → `_parse_search_page` 番号搜索链路，且搜索必须能解析出详情链才算 OK（否则回退整站 `_run`）；只有搜索落不到详情页的站才允许在 `network_check._build_site_specs` 写死 `probe_url` 直达详情（例外须同步进 `site_fields.DIRECT_PROBE_SITES`，`test_probe_mode_matches_network_check_probe_urls` 钉死两集合相等；刮削字段表“方式”列直连填“直连”、搜索填“搜索”）。当前 24 个直连例外均为用户实测“搜索不可用”、逐站指定详情地址（Hbox 无番号搜索；Jav321 搜索是 POST 表单 URL 表述不了；Madou.club `?s=` LIKE 搜不到 MD332；FC2 无搜索实现；AVEntertainments 搜索页撞 verifybot 墙；AVheat/AVMOO/AVSOX POST JSON + Cookie 预热 + tellme 动态域；R18.dev 网页版无搜索页；TheJavDB 网页版 SPA + CF 无真搜索；JavLibrary 搜索页常年被 CF 墙挡；IQQTV uuid 不透明；7mmtv 含站内 ID 100674；Airav.cc hid 不透明；AVBase 名寄せ ID 含 maker 前缀；DMM 详情 host 为 video.dmm.co.jp；JavDB /v/5nnDEY 不透明 ID（探针号 DASS-481）；JavDay /videos/ADN384/；Getchu 探针号 AIV-10、详情 /item/1300711/；LibreDMM /movies/IPX-535；Lulubar id 不透明；FreeJavBT /zh/IPX-826；Madouqu /video/mdx0216/；JavFree /452656/abf-398；ThepornDB_JSON（用户 2026-11-09 指定：探测号 ALDN-494 直达 JSON 详情 /jav/568c12b8-…，uuid 不透明无法拼接），不要改回搜索。

- **JSON 通道「浏览器」按钮只打开 http:// 或 https:// 地址**（2026-11-13 用户定规）：对 FC2_JSON / AVBase_JSON / 7mmtv_JSON 等站点，浏览器按钮直接打开目标网页/接口地址（`http(s)://...`），不落临时文件；「查看JSON」仍展示合并后的完整字段。实现统一在 `json_view.request_json_browser` 的站点分支里，新增 JSON 站点默认也走临时文件，除非明确加入该分支。分支里的站点名必须写 `Website` 枚举的 **value**（`Hbox_JSON`，不是枚举名 `HBOX_JSON`）：写错大小写不报错，只会静默退回临时文件（2026-11-13 修 Hbox_JSON 时踩到）。分支成员清单在 `json_view._JSON_BROWSER_DIRECT_SITES`（2026-11-13 起 21 站）。**临时文件只留给浏览器打不开原始数据的两类**：ThepornDB_JSON（接口只认 Authorization 头，URL 带 token 一律 401）与 AVMOO/AVSOX/AVHeat_JSON（只收 POST，浏览器只会发 GET）；Missav_JSON 开详情页。**临时文件会被浏览器会话恢复**——下次浏览器启动自动又打开那个 `file:///…/mdcx-xxx-xxxx.json` 标签页，看着像软件无缘无故弹窗，所以新增 JSON 站点一律直开 http(s)，别再落临时文件。

- **JSON 刮削器字段必须与对应网页版对齐**（2026-11-13 用户定规）：JSON 通道的刮削结果与「查看JSON」展示都必须包含网页版刮削器已有或可获取的全部字段；凡网页版能取到、而 JSON 通道未返回的字段，必须修改代码从详情页 DOM 或网页版同款解析逻辑获取并补充到 JSON（FC2 的演员/标签/发行/时长/publisher/extrafanart，7mmtv 的 runtime/release 等），新增 JSON 通道时先对比网页版与 JSON 版字段矩阵，把缺失字段在刮削与查看 JSON 两条链路一并补全，避免“网站 JSON 没返回”就缺字段。浏览器按钮仍只打开 http(s) 地址（见上条）。

### 无码官网爬虫硬约束与约定（2026-11-14 从 Trae project_memory 合并）

- Heyzo 相关爬虫必须使用 **HEYZO-3669** 作为官方站点探测番号，使用 **HEYZO-3980** 作为 Heyzo_JSON 探测番号，对应网页地址分别为 `https://www.heyzo.com/movie/3669` 和 `https://www.heyzo.com/movie/3980`
- Heyzo 爬虫采用 **API 优先、HTML SPA DOM 回退** 的策略获取元数据，优先调用 `https://www.heyzo.com/api/v1/movie/{movie_seq}` 端点获取结构化数据
- Heyzo 时长转换规则：将 HH:MM:SS 格式的时长转换为整数分钟，**秒数 ≥ 30 则进 1 分钟**，最低保底为 1 分钟，优先使用 `download.whole` 数组的 `duration` 字段，`movie_files` 数组的 ISO 格式时长作为回退
- 直接解析 heyzo SPA 页面 DOM 无法获取 runtime 字段，该字段仅在前端播放器渲染后才会显示，无法从页面源码中提取
- 所有 JSON 版刮削器与对应的网页版刮削器必须**完全解耦**：JSON 版不得依赖对应网页版的 DOM 辅助函数，网页版也不得依赖对应 JSON 版的工具函数，所有跨配对依赖的逻辑必须在各自文件内另行实现，保持字段口径完全一致
- **7 对官网网页版 = 界面隐藏的 JSON 兜底（2026-11-14 用户严规，勿再改回可见）**：解耦只管「字段获取互不 import」，不代表网页版可以删。七个网页刮削器（10Musume / 1Pondo / Caribbeancom / HEYZO / MyWife / Pacopacomama / Prestige）一律 `hidden_in_ui() -> True`（5 个无码官网统一写在 `sites_official_uncensored/base.py::_OfficialUncensoredCrawler`，MyWife / Prestige 各自覆写），核心刮削、探测番号、封面/海报/剧照下载能力**全部保留**；配对写进 `AIO_JSON_WEB_FALLBACK`（`AIO_WEB_FALLBACK_SITES` / `AIO_WEB_TO_JSON_SITE` 自动派生）。口径统一为「JSON 优先、网页版仅在失败或字段不全时兜底」：单站路径走 `_call_specific_crawler` 的 `JSON_TO_WEB_SITE` 回退 + `_supplement_missing_fields`（含图片字段）；多站/速度优先路径把名单里残留的网页版归一为 JSON 版，再由 `_with_aio_fallback` / `AIO_JSON_WEB_FALLBACK` 追加网页版到末尾。**导出刮削字段表必须用 `include_hidden=True` 全量列出七行**；网络检测用默认视图 + `AIO_WEB_FALLBACK_SITES` 双重拦截跳过七网页版（JSON 版照常检测）；设置页官网行 `load_config` 把隐藏网页版显示成 JSON 版、`save_config` 与 `site_priority_dialog._open_site_editor` 过滤隐藏网页版；「检查演员缺失番号」`build_sources` 曾给两条路径都追加官网链，**2026-11-17 起撤销（用户定规：清单即边界）**：只有 `actor_type == "官方网站"` 才补五家官网 JSON 版，自动判断与其它指定类型一站不加，免得清单外网站被请求并把 404/403 刷进日志；写缺失表前的元数据补齐同样只打本行来源站详情页，不再按番号跨站猜 LibreDMM。「单文件刮削」靠 `deal_url` + `_prefer_json_site` 升级到 JSON。回归测试见 `tests/test_actor_sources_filter.py`。

### JSON/网页 刮削器配对解耦总原则（2026-11-14 用户严规，适用于全仓所有配对）

每一对 `XXX` 网页刮削器 ↔ `XXX_JSON` 刮削器必须满足：

1. **独立搜索番号**：各自实现自己的搜索逻辑，不走对方的搜索函数或复用对方的搜索入口 URL
2. **独立获取字段**：每个爬虫文件内持有自己完整的解析逻辑——DOM 取值函数、API 端点拼接、时长归一、日期归一、演员名分割、URL 拼接等全部在本文件或通用 base 模块内声明，**绝不** `from .xxx_web import` / `from .xxx_json import` / `from .sites_official_uncensored.base import` 对方通道的取值辅助函数
3. **独立下载图片**：封面 / poster / extrafanart 的 URL 拼接规则在各自文件内独立维护，图片下载走通用 web_sync 即可，但 URL 生成逻辑不复用对方实现
4. **字段口径对齐**：JSON 版刮削结果的 **每个字段** 必须 ≥ 网页版能拿到的字段集合；反之亦然。网页版能从 DOM/API 抠到的字段，JSON 版必须能从自己的数据源（JSON API、DOM、固定规则）独立拿到；JSON 版能拿到的字段（如 HEYZO API 的正片时长），网页版也必须能从自己的数据源独立拿到（SPA DOM 回退）
5. **查看JSON 按钮对齐**：每个 JSON 爬虫的 `build_view_payload` 函数（供「查看JSON」按钮展示）必须复刻爬虫同款取数路径——API 优先就走 API，API + DOM 合并就两个都调，DOM-only 就只走 DOM——展示的字段集合与爬虫刮削结果 **完全一致**，不得只展示 API 原始 JSON 而漏了爬虫额外补充的字段
6. **互不影响**：一方改动（如改某个站点的 DOM 选择器、加新字段、换 API 端点）**绝不**影响另一方的运行结果；修改必须在各自文件内独立落地、分别测试

**已验证彻底解耦的配对（import 零交叉）**：

| 配对 | 状态 |
|------|------|
| Caribbeancom ↔ Caribbeancom_JSON | ✅ 完全解耦，JSON 版自实现全部 DOM movie-spec 取值 |
| HEYZO ↔ HEYZO_JSON | ✅ 完全解耦，JSON 版自实现 API 优先 + SPA DOM 回退 |
| 1Pondo ↔ 1Pondo_JSON | ✅ 完全解耦，JSON 版自实现 gallery 补充 extrafanart |
| Pacopacomama ↔ Pacopacomama_JSON | ✅ 完全解耦 |
| 10Musume ↔ 10Musume_JSON | ✅ 完全解耦 |
| MyWife ↔ MyWife_JSON | ✅ 完全解耦 |
| Prestige ↔ Prestige_JSON | ✅ 完全解耦 |
| TheJavDB ↔ TheJavDB_JSON | ✅ 完全解耦 |
| FC2 ↔ FC2_JSON | ✅ 完全解耦，JSON 版自实现 FC2 API + article widget 合并 |
| LibreDMM ↔ LibreDMM_JSON | ✅ 完全解耦，JSON 版自实现 LibreDMM API + DOM 字段合并 |
| 7mmtv ↔ 7mmtv_JSON | ✅ 完全解耦 |
| Airav.cc ↔ Airav_JSON | ✅ 完全解耦 |
| Missav ↔ Missav_JSON | ✅ 完全解耦 |
| JavFree ↔ JavFree_JSON | ✅ 完全解耦 |
| Madouqu ↔ Madouqu_JSON | ✅ 完全解耦 |

**通用工具函数例外**：`iso8601_minutes`（时长归一）、`normalize_release`（日期归一）、`split_names`（演员分割）这类纯工具函数可以跨文件调用——只要调用的是**独立声明在某一方文件顶部、与该方网站无耦合**的函数。例如 `heyzo_json.iso8601_minutes` 是独立的 ISO-8601 → 分钟工具，`caribbeancom_json` 调它不构成配对耦合。

- **演员原名/别名/艺名/曾用名只从 JavDB 取，不准读 `actor_database.xlsx`**（2026-11-20 用户定规）：该库数据可能有错，`core/actor_name_map.py` 及取号链路里所有读它做名字映射的逻辑（含 `resolve_actor_names` 自动扩展、官网 JavDB 自动兜底）已整体删除。任何功能需要这批名字一律走独立模块 `core/actor_original_names.fetch_actor_original_names()`（JavDB_JSON 优先、失败回退网页版 JavDB），未勾选「获取演员原名」时各站只用用户手动输入的名字，不自动扩展繁简/日文写法。xlsx 仍用于演员库维护、补全中文名、同步别名等**写入**场景，两者不要混。


## Windows 打包与发布

- 只有「字符串动态导入」才必须显式 `--hidden-import`；`tests/test_build_hidden_imports.py` 哨兵锁定全仓动态导入 ⊆ hidden-import，CI 有 PyInstaller 冒烟。
- **一体包硬失败后，所有调用 `scripts/build.py` 的工作流必须先 `fetch_sr_tools`**（`test_sr_bundling.py` 锁顺序）；目录存在但缺 realesrgan / waifu2x 子目录同样硬失败。
- 内置资源运行时查找必须 fail-loud：查找失败给原因码 + 结论日志；释放后校验可执行文件真的落盘；清理旧目录**禁用 `shutil.rmtree(..., ignore_errors=True)`**（改用 `onexc` 收集失败项后抛错并点名）。回归在 `tests/test_super_resolution.py`。
- EXCLUDED_MODULES 中 rich/typer 只供构建/CLI；Windows 上 curl_cffi.libs 需显式 `--add-binary`。
- GitHub Actions 两坑：runner 标签会整体下线（不再用 macOS Intel）；`astral-sh/setup-uv` 无裸主版本浮动标签。
- **Release**：唯一工作流 `build-py315.yml`；推纯数字 tag `2*` 自动发正式版，或 `workflow_dispatch` 手动补发（tag 留空取 `LOCAL_VERSION`）。资产名 `MDCx-<tag>-<平台>-<arch>-<40位sha>.<exe|dmg>`，标题 `MDCx <日期版本号>`；tag 必须纯数字。**只在公开仓库 `z291173301/MDCx` 发 Release，私有仓不建**；同 tag 已有 Release 先 `gh release delete --cleanup-tag` 再重建（PAT 用 `MDCX_SYNC_TOKEN`）。Windows zip 版走 `package-trawl.yml`。
- **Release 正文只能按文件写**（2026-10-27 起用 `gh release create --notes-file`）：不得经 step output 塞进 action 的 `body`（runner 把 `with:` 变成 `INPUT_*`，Linux 单环境变量上限 128 KiB）。
- **docs 同步**：`sync-docs.yml` 在 push main 且 `docs/*.md` 变化时按本次 diff 只复制/删除改动到的文件；手动 dispatch 才全量同步。
- Actions 版本：统一 `actions/cache@v6`（v5 起 node24 runtime），最低 runner ≥ 2.327.1。

## 版本号与配置迁移

- **改代码就把 `consts.py::LOCAL_VERSION` 改成当天 `YYYYMMDD`**（2026-10-23 定规，取代 10-19 旧口径）。多个展示版本号共用同一 `LOCAL_VERSION`、同 tag 先删旧 Release 再重建、`check_version()` 取数字 tag 最大值——这三类疑问一律先问用户，别写进文档/changelog/commit message。要守的是同步点一致（`scripts/bump.py --check` + `test_version_consistency.py` + `test_version_metadata.py`）。
- 提交前把变更写进当天日期段；用 `scripts/bump.py --version`（升展示版本号有坑：`LOCAL_VERSION` 未变会误报，需手改三处）。Windows 跑 `bump.py` 需设 `PYTHONIOENCODING` 并 `stdout.reconfigure`。「已发版」判据 = 数字 tag 已推送。
- **`config_version` 永久固定为 2**（三处一致，`test_config_conversion.py` 钉死）→ **它不能再当迁移判据**：`_migrate_main_mode()` 改用结构性判据 `_SEPARATE_MODE_KEYS`。规律：版本号一旦冻结，一切依赖它的判据都要换成结构性判据。
- 已删除的符号（别照着记忆去找）：`Config.factory_defaults()`、`migrations.backfill_missing_keys()`、`NEW_LIST_ITEMS`、`ConfigManager._needs_upgrade_persist()`、`tests/test_config_auto_upgrade.py`。取「字段声明层默认值」只能遍历 `Config.model_fields`，**绝不能用 `Config().model_dump()`**（`model_post_init` 会覆盖用户自定义的 `type_field_configs`）。
- 撤销范围不明的工作区改动一律 `git revert --no-commit <sha>` 让 Git 算，复现的 diff 必须逐条核对来源。
- **功能开关类配置项不得充当「逃生通道」过滤器**：「当前配置」下拉必须列出目录下每一个 `.json`，不做有效性过滤（`load()` 出错会切到 `_failed.json`，下拉框是唯一切回通道）。
- **配置加载路径上的对象构造必须「无前置条件」**：`Computed()` 在 `ConfigManager.load()` 里同步构造、`manager` 是模块级实例化，任何外部客户端构造失败都会让软件起不来。`LLMClient.__init__` 缺凭据就不构造客户端（`self.client = None` + `close()` 空值保护）。**可选功能（LLM / Emby / 同步）的凭据永远不能是启动前置条件。**
- 用户在安装目录自维护的 `actor.json` / `default.json` / `studios.json` / `theporndb.json` 是不同命名方式的独立配置，不是出厂数据；看到同名 json 先看有没有 `config_version` / `main_mode`。`list_configs()` 无差别列 `.json` / `.ini` 是既有设计。
- 手工改用户真配置按字节级单行替换（无 BOM、纯 CRLF），改完回验：JSON 可解析、行为字段未变、键集合一致、差异行只有目标行、CRLF 计数不变。

## 视频模式与伴生文件

- **视频模式固定「搬视频 + 删伴生文件」**（`Switch.SORT_DEL` / `SORT_MOVE` 已删，老配置由 `_migrate_sort_mode_switches` 清理）：`move_movie` → `organize.delete_companion_files`（按归属索引删）→ 删空目录；索引不可用时回退固定路径清理。软链接/硬链接模式不删。
- 正常 / 分离 / 更新模式的伴生文件搬移走 `deal_old_files(index=...)`（返回三元组 `(ok, pic_catched, single_catched)`，`ok=False` 表示已回滚、本次放弃处理）；后半段字幕/种子/bif/json 复用 `organize_companion_files`，`move_sub` / `move_torrent` / `move_bif` / `move_other_file` 只服务读取模式等残留分支，别再往搬文件分支里加。
- **索引必须在任何文件被搬走之前建好**（`_prepare_organize_index` 覆盖整理/补全/视频/正常/分离/更新）；正常/分离/更新为此多付一次全库扫描，别改成按目录懒建（同目录并发时会误判归属）。
- 系统目录不进索引（`@eaDir` / `#recycle` / `.@__thumb` / `$RECYCLE.BIN` / `Thumbs.db` / `.DS_Store` 等），由 `file_association._is_system_entry` 排除。
- **番号 ↔ 伴生文件关联只在 `core/file_association.py`**，`core/organize.py` 只留「移动计划 + 事务 + 回滚」；改归属规则只改前者。
- **补全模式的「先搬后补」顺序不能反**：先补再搬会把刚写好的 nfo 当旧 nfo 再搬一次。已在成功输出目录内的走 `complete_inplace_locked`。
- 补全模式选项 2026-10-23 已收敛（删两项 + 合并策略 5→3 档，旧配置自动迁移）；**仍保留的已知冲突只有「按更新模式重新整理分类」**（会把文件放到成功输出目录之外）。
- 「重新下载封面图片等文件」不存在「重下不打水印」缺陷：下载函数每写出一张新图都把 `*_marked` 复位为 False；给已存在图预标记 True 只是防二次水印，别加 `READ_DOWNLOAD_AGAIN` 条件。

## 通用纪律

- 把常量/枚举值当判据时，改那个值必须连带 grep 所有读它的地方。没有幂等保护的迁移就是定时炸弹。
- 写死数字前 grep 代码核实。高频漂移锚点：默认网站源顺序、代理域名列表、命名变量表、设置 Tab 名、字段优先级数、演员库列、指纹池、主窗口行数。README 爬虫数四处同步，Features.md 标题是独立第五处。
- 长时间任务：后台终端 + checkpoint 断点续传 + 分批落盘 + wrapper 45-50 分钟自重启；进度看落盘文件，不看终端日志（stdout 全缓冲可能 0 字节）。
- 功能移除类需求先调研证据（活跃度、共享依赖、移除成本）；用户转述与代码证据矛盾时以代码为准。
- **共用功能/方法必须单独成文件或函数（2026-10-27 用户定规）**：同一段逻辑出现第二处（或预见会出现）就抽出来，跨模块/体量大时抽独立文件（`core/file_association.py`、`tools/emby_actor_ui_kit.py`、`tools/emby_actor_source_catalog.py` 是现成范式）；旧入口保留薄封装转调，改共用实现前 grep 全部调用点，并留回归测试。
- **xlsx 导出列宽纪律（2026-11-18 用户定规）**：**设定列宽是多少，导出后打开文件看到的就必须是多少**。根因是 openpyxl 写入的 width 是原始字符数，WPS/Excel 显示时扣掉网格内边距，显示值恒小 0.78（2026-10-17 `ET.Application` COM 实测）。规则：写 xlsx 列宽的代码一律写入 `显示设定值 + WPS_COLUMN_WIDTH_OFFSET`（常量在 `tools/emby_actor_export.py`，统一导入复用，禁止手抄 0.78 或裸写设定值）；回归看 `tests/test_missing_audit.py::test_excel_column_widths_written_as_displayed` 与 `tests/test_actor_export.py`。本次落地：`tools/missing.py::_write_missing_excel`（查询演员番号/检查缺失番号共用导出）补补偿，时长/类型列宽 12→6。
- **FC2/个摄番号必须兼容 `FC2-` 与 `FC2-PPV-` 两种写法（2026-11-15 用户定规）**：涉及 FC2/个摄的刮削器，输入侧两种前缀都要识别、输出统一归一为标准短形 `FC2-{digits}`（`utils/shared_fields.py::fc2_digits` 是归一公共件，`javdb_number_key` 把 `FC2PPV` 折叠成 `FC2`）；站侧要求 PPV 形的（javfree 搜索、7mmtv 标题、missav 详情 slug `fc2-ppv-*`）在生成搜索关键词/URL 时自行映射，绝不能因输入写法不同而搜不到。改任何 FC2 判定前闭眼兼容双写，别再写 `update("FC2-", "FC2-PPV ")` 这类会叠成 `FC2-PPV PPV-` 的替换（7mmtv.get_real_url 2026-11-15 修的真 bug）。
- **刮削模式值全表**（2026-10-23 起）：1 正常 / 2 分离 / 3 视频 / 4 更新 / 5 读取 / 6 整理 / 7 补全。改动模式必须同步：`config/extend.py` 常量与 `is_xxx_mode()`、`load_config.py` / `save_config.py` 的 `mode_mapping` 与 radio 映射、`MDCx.ui` 单选项与说明、`core/file.py` 的模式元组、`base/file.py::get_movie_list`、`core/scraper.py` 的续刮排除与扫描排除、`init.py` 提示词、软件内使用说明。

## 日亚 ASIN 数据库

- **日亚图片仅限有码番号/官方网站**（2026-11-20 用户定规）：`web.amazon_images_allowed` 只放行 `FixedScrapingType.YOUMA` / `OFFICIAL`；其它类型（无码/欧美/国产/个摄/动漫/FC2/自动判断未定）不再发起日亚搜索，也不下载或探测 `media-amazon` 图片。自动判断会把无特征前缀番号默认归为有码，须再按马赛克（纯无码/国产/里番动漫/同人书籍）与主字段来源（number/title/originaltitle/thumb/poster）是否属于「其它类型专属站点」（`TYPE_DEFAULT_SITES` 其它组减有码/官网组，跨组共用的 JavDB/DMM 等不拦）复核；流出/破解按有码母带口径保留日亚搜索。设置页说明同源标注「仅有码番号/官方网站生效」。
- 证据强度：tenhow cid 结构化映射 > EAN/JAN 条码 > 标题 NFKC 系列互含 > 图像相似度（`_cover_similarity` 三阈值 0.82 / 0.86 / 0.70，只能兜底）。
- 软校验：条码/EAN 与 ASIN 库命中免验；软匹配走 v2 三步链（cid 旁证 → 标题门 + 真合集词一票否决 → 图像兜底）；演员名兜底是错挂重灾区，全链必走。
- 出厂库合并：同番号覆盖用户库 5 列，用户独有保留，出厂独有追加；出厂库更新须用户明确确认。
- 待修正 sheet 三分类（主表已有同番号→删、番号不同→反查标题裁决、主表未有→标题法/cid 反查）；批量行先按 ASIN 去重。
- 列写入走显式列号映射，不手数 index；入库后 sanity check `r[1]` 是纯 ASIN。
- cid → 番号规则 `^(\d*)([a-z]+)(\d+)([a-z]?)$` → `系列大写-{int:03d}`；离线索引 `resources/userdata/tenhow_asin_cids.json`（36441 条）。
- DMM cid 结构：前缀映射 + 数字双态（5 位补零 digital 与 3 位 mono 同系列可并存）+ 双路径。DMM 图床下架时 CDN 不删对象，占位图 200+ 且 <4KB 已拒收。
- 日亚图 SL1500 物理无条码；老商品标题是半角片假名（NFKC 必做）；日亚 DVD 封与 DMM digital 封版本不同（相似度天花板 ~0.62）；tenhow.net 图床 `images/{ASIN}.jpg` 与日亚 SL1500 同源，免代理直取。
- 工程散点：数据治理前先 `Counter` 关键列识别导入批次残留；openpyxl 迭代中 `delete_rows` 会跳行（读出→去重→清空重写）；javbus 搜索不识别 ASIN；**合并判定禁用 or 链**（短路吞判定值、带副作用的 `pop` 不执行）；外部 API 错误码取响应原文字面值。
