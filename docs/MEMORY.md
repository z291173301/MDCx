# 用户指令记忆

只记「以后每次都该怎么做」的规则。技术原理与架构见 `docs/Development.md`，版本变更见 `docs/Changelog.md`。

---

## 协作与质量

- 一律用简体中文回复；面向小白的说明按「现象和影响 → 原因 → 可执行步骤」三段写；日期时间用北京时间（UTC+8）并显式注明。
- **记忆只写这一个文件**：`D:\@Data\MDCx\DADA\MEMORY.md`。不要另建 `.workbuddy-ai/memory/` 之类的旁路记忆文件（用户 2026-10-23 要求）。本文件不受 150 行限制，只记可复用做法，不记一次性事实。
- **大模型输出只给改动片段**（2026-10-27 定规）：默认只返回修改后的片段，不重复输出全文；新建文件、用户明确要求全文、或只给片段会产生歧义时才输出全文。
- 改动前先说明「改什么、为什么」；遇到值得记的内容主动记入，不用等提醒；直接在当前分支操作，不擅自建分支。
- **授权/未授权文案只有两个落点**：弹窗正文 `premium_gate.premium_message()`（`<功能名>功能需要获取授权后才能使用`，句末不带句号）、状态日志 `guard.describe()`（未授权只给原因，不套「未授权（…）」）。功能名由 `premium_gate.GUARDED_ACTIONS` / `_license_gate(action)` 传入，改文案只改这两处。
- **授权弹窗只走 `premium_gate.premium_warning()`**（读取模式放行时的一次性说明走 `premium_reading_notice()`）：标题固定「请获取授权」、正文同源，尺寸自然一致。主窗 / 工具页 / 信息管理 / 演员管理 / 机器绑定（生成授权、私钥）都不再自己写 `QMessageBox`。
- **演员管理器授权弹窗字号要回落**：演员管理器的 QSS 整体放大一号，授权弹窗会继承；主窗/子窗 QSS 必须拼上 `_premium_popup_qss()`（`QMessageBox, QMessageBox *` 统一用 `_ui_font_pt(0)`），否则弹窗比主界面窄。只改 QMessageBox 自身不够，内部 QLabel 仍继承放大字号。
- **账单导入与授权弹窗分文件**：账单导入只在 `bill_import_ui.py`（按钮、机器绑定轮询、导入流程），不写授权弹窗；未绑定机器的点击由 `premium_gate.MachineBoundClickGuard` 在按钮层拦，`import_bill()` 不再出现授权判断。
- **未授权 ≠ 关掉入口**（2026-10-27 口径，推翻此前「演员管理整窗拦」）：窗口能开、能连 Emby 读取、能统计；只有联网取数 / 写回服务器 / 写本地文件的动作点时才拦。独立顶层窗口（演员管理器）走 `premium_gate.premium_denied()`，主窗走 `premium_gate.premium_gate()`，两者共用同一份弹窗文案。

## 检查与提交纪律

- **没写明就不提交**（2026-10-23 明示）：需求里没有「提交 / 推送 / commit / push / 提交到 GitHub / 推到远程」这类字样时，只改工作区文件，不 `git add`、不 commit、不 push、不建分支。「改完了」「继续」「优化一下」都不算授权；授权只对当次需求有效。说「提交」= 只 commit，说「推送」才 push。
- **界面改动默认不写 `docs/Changelog.md`**（2026-10-23 定规）：纯界面调整（位置、间距、尺寸、对齐、配色、字号、措辞、控件换行/换列，用户可观察的行为没变）不占 Changelog 行，也不补「界面微调」。行为变了（增删控件改变可达路径、改默认值/分支、窄窗不可用）才按功能条目写。口径见 `docs/Development.md` 10.7。
- **本机没装 uv、也不要装**（2026-10-24）：门禁直接用系统 Python `"C:/Program Files/Python315/python.exe" -m ruff format --check mdcx tests scripts` / `-m ruff check ...` / `-m mypy mdcx/` / `-m pytest -m "not network" -q`，不要写 `uv run`。
- 改代码后跑快速门禁（format + check + mypy），提交前加跑全量 `pytest -m "not network"`；只改 `docs/*.md` 或本文件时只需 `git diff --check`。
- 全绿判定 = 退出码 0，且 `grep -E "\.py:[0-9]+: error|Found [0-9]+ error"` 无输出（mypy 输出可能被 tail 截断）。
- `ruff check` 过 ≠ `ruff format --check` 过；改了 .py 必须 `ruff format` 落地。格式化要用仓库锁定版 ruff（pyproject pin `>=0.17.1,<0.18.0`，uv.lock 实锁 0.17.1）；升版后必须 `uv lock` + `uv sync` 再全量 format + check。
- `scripts/` 也在 check 范围内。`check.py` 的 ALWAYS 段 = `ruff format --check` → `ruff check` → `mypy mdcx/` → `check_thread_safety`（**不含 pytest**）；要全量门禁显式加 `--with-tests`：`"C:/Program Files/Python315/python.exe" scripts/check.py --skip-hook-install --with-tests`。
- `check_ui_layout` 已移出门禁，只作手工诊断：`-m scripts.check_ui_layout`。xlsx 校验按路径跳过（`check_actor_db` / `check_info_db` 只在对应出厂库或校验脚本有改动时跑）。
- `ci.yaml` 的 `on:` 只有 `pull_request: branches: [main]`，**直推 main 不触发 CI**；门禁靠「PR + 本地自检」两道。
- Linux 构建依赖统一走 `.github/actions/install-linux-deps`（`build-py315.yml` / `ci.yaml` / `update-sr-tools.yml` 三处共用）：**不装系统 Qt6、不装 FFmpeg 开发库**（Qt 来自 pyqt6-qt6 wheel，FFmpeg 来自 av 的 abi3 wheel），且必须带 `--no-install-recommends`。三处各复制一份大清单会退回「149 个包 / 123MB / 几分钟」的老路。
- `git add -- <具体文件>`，绝不用 `git add -A`；提交前看 `git status` 的未跟踪文件，运行残留不得入库。
- **不改不是自己改的文件**（并行会话可能同时改本仓库）；暂存区里有别人的改动时，用 `git commit -- <自己的文件>` 只提交自己的。
- 提交信息不要手写 `Co-authored-by`（`prepare-commit-msg` 会无条件追加）。
- **提交优先用 GitHub Desktop，并尽量走代理**（2026-10-27 定规）：提交/推送前先确认代理已开；命令行直连失败用一次性代理参数（系统代理 `127.0.0.1:7897`，端口按实际改）：`git -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main`；报网络错先 `git ls-remote origin main` 对 SHA，确认没推上去再重试。

## pre-push 钩子

- `hooksPath` 是本地 git config，环境重置后静默失效：先 `git config core.hooksPath` 验证，为空则 `git config core.hooksPath .githooks`。
- 钩子生效时流程 = quick-check → commit → push，钩子自己跑快速门禁，别手动多跑；钩子失效期间推送前手动全量 check 兜底。
- 钩子按 uv → python3 → python 兜底，PATH 里的 `python3` 若是托管版 3.13 会因 PEP 758 语法 SyntaxError 拦下推送 → 造一个 `python3` 垫片（`exec "/c/Program Files/Python315/python.exe" "$@"`）前置到 PATH，**别用 `--no-verify`**。
- `.pre-commit-config.yaml` 是历史遗留，不依赖。

## 本机环境

- Windows；Python 3.15 装在 `C:\Program Files\Python315`，**项目默认 3.15**（`requires-python >=3.15`，版本声明五处同步：`pyproject.toml`、`uv.lock`、`requirements.txt` 头注、README 徽章、`docs/Development.md` 第 8 节，测试里的 `skipif` 守卫同步）。仓库标准仍是 uv，别把 CI 写法改成本机口径。
- 一律用 `python main.py`、`python -m pytest tests/ --tb=short -m "not network"`、`python scripts/quick_check.py`、`python scripts/check.py --skip-hook-install`；脚本自带 `resolve_tool()` 兜底。
- GitHub：直连 TLS 被 reset、5915 代理 502，**Clash 7897 可用**（命令见上）。推送报 schannel「server closed abruptly」先查是否已推上去。
- pytest 成功时 conftest 的 `pytest_sessionfinish` 会 `os._exit(0)` 丢弃 stdout，**判定只认退出码**，要细节加 `--junitxml`。
- 沙箱陷阱：①直接调系统 python 触发 stdout 捕获异常 → 命令内 `> file 2>&1` 落盘再读；②中文 Windows 子进程默认 GBK，控制台乱码只影响显示；③用 `-m ruff` / `-m mypy` 走当前解释器。
- PowerShell 7.6.7 在 `C:\Program Files\PowerShell\7\pwsh.exe`（曾因 `AppCompatFlags\Layers` 的 RUNASADMIN 报 740，已清除；再报 740 先查这层，别用 `-Verb RunAs`）。5.1 的 `Set-Content -Encoding utf8NoBOM` 不可用；中文 commit message 一律写文件后 `git commit -F <file>`。仓库无 bash（`bash` 命令不存在）。

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
- **subagent 结论不可直接采信**（22 项宣称中 11 项编造/夸大）：要求它输出「已排除假设清单 + 理由」，修复前每条独立复现。
- 数据质量治理前必须实证全量抽查，不靠代码推断；「功能上可达」≠「正常路径会走到」。
- `CancelledError` 在 task 收集点与 `Exception` 同级软着陆；整轮取消只由 cancel_event 分支负责，`wait_for` 的 cancel 残留不得穿透。
- **误判家族四条**：①「未命中/空结果」是业务常态，不得与「通道故障」混用（真实限流信号只有 403/429/连接异常）；②模型哨兵默认值（如 `"0000-00-00"`）是 truthy 会被放行，下发前按格式白名单归一化；③集合合并类 bug 第一嫌疑永远是有无 dedupe；④「不标来源就报结果」的日志/汇总字段是诊断盲区。
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
- 门禁已知遗留红（2026-10-19 实测）：`tests/test_advanced_page_tail_align.py::test_wide_nav_row_survives_deferred_stage_one[1920-1170]` 在干净树上必红。合格线 =「除这条外全绿」；先跑干净树对照，别当元凶，也别顺手去「修」。

## Qt 生命周期

- 测试里 `w.deleteLater()` ≠ 销毁：`processEvents()` 不投递 DeferredDelete，须显式 `sendPostedEvents(None, QEvent.Type.DeferredDelete)`。全仓 92 处 deleteLater 原先都没生效。
- 从未 `show()` 过的窗口，`close()` 不发 `hideEvent`。
- `MyMAinWindow.closeEvent` 由 `WindowOpsMixin` 提供且末尾恒 `a0.ignore()`：要加清理绝不能新写同名方法（会遮蔽 mixin），应加在 mixin 内部（新增 `hideEvent` 安全）。查归属用 `"closeEvent" not in MyMAinWindow.__dict__`。

## 崩溃与内存

- access violation 根因（2026-10-17 已修）：deleteLater 未生效 → 40+ 测试文件各自造窗口泄漏 → 每窗挂 100ms 热表等 4 个定时器 → 后续任意 processEvents 派发陈旧回调 → AV；拦路虎是 `_SiteComboTipFilter.eventFilter` 无限递归爆栈。
- 三条走不通的路（别再试）：补 sendPostedEvents 真析构、`TerminateProcess(GetCurrentProcess())`、DLL pinning。
- 已落地三处缺一不可：`483cee1` 重入守卫、`bab49bd` 隐藏/关闭时停四个轮询定时器、`conftest._teardown_qt()` 补 `sendPostedEvents` + `list(topLevelWidgets())`。
- 崩溃分 A/B 面：A 面（processEvents 里 AV、退出码非 0）必须治；B 面（`os._exit(0)` 内部析构导致 AV、退出码仍 0）对门禁无害。间歇性原生崩溃不适合靠反复全量跑验证，要在单文件上做因果验证再下沉 conftest。

## UI 开发与排错

- 改 UI 先改 `.ui`（唯一权威源）→ `"C:/Program Files/Python315/python.exe" -m PyQt6.uic.pyuic`（相对路径）→ `scripts/fix_qt_enums.py` → `ruff format` → `tests/test_ui_structure.py`。禁止手工改 `MDCx.py`。
- 布局问题先写最小复现脚本验证 Qt 原生行为。常见根因是 BoxLayout / QGridLayout 缺末尾 Expanding 间隔（`setVisible(False)` 管不到 QSpacerItem）；末尾 Expanding 的 `sizeHint` 必须写 `0x0`，否则末行下方留死空白。
- 富余高度被吃掉两种：①灌给该行唯一控件（wordWrap 标签，表现为文字垂直居中留白 + 后续行被下推）→ .ui 补垂直 Expanding + 运行期把容器高钉成 `layout.sizeHint().height()`；②在顶/行间/底均分 → 把行首留白折进 `contentsMargins`，组高按「容器底 + 固定底留白」收紧。
- 通用宽幅同步只改宽不改高：wordWrap 组拉宽后变矮，空白堆在网格底部 → 挂 `_post_wide_sync_hook`，按 `childrenRect().bottom() + 1` 量真实底边并同步平移其后各组，窄态显式复位。
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

- 各站探测番号与收录依据见爬虫类注释；javdb 仅搜 FC2 时需要 Cookie。
- 站点 API 坑：missav_api 的 Recombee 仅 POST；DMM Affiliate v3 必需 site/service/floor 且 keyword 用 content_id 形态；madouqu 域名动态维护（24h 缓存）；madou_club 番号无横杠；parsel `Selector.get()` 纯 JSON 返回 dict（解析兼容 str/dict/Selector 三态）。
- **当前注册爬虫 36 个**（`docs/Features.md` 同步）；数字开头模块名（`7mmtv.py`）用 `importlib.import_module` 加载。
- 站点收录边界：AVEntertainments 只在无码组；Getchu、AVSEX 大陆 IP 过不了 CF 故从六组移除；Official 只在有码/无码两组。
- 「素人番号」已改名「国产短剧」（枚举值/字段名仍是 `SUREN` / `website_suren`），默认名单只剩 JavDay；短剧无番号格式，只有锁定类型才走这一组。
- 七组名 = 有码番号/无码番号/个摄番号/欧美视频/国产传媒/国产短剧/动漫里番；下拉八项多一个「自动判断」。组名与下拉文案、chip 短名、`PALETTE_GROUP_TYPES` 组序同源；下拉下标↔值映射读 `FixedScrapingType.dropdown_values()`（顺序源 `dropdown_order()`，不能写成类体常量——Enum 会报 TypeError）。
- 「锁定类型」运行期只有一张真相表 `models.SCRAPING_TYPE_SITE_FIELDS`；保留 `getattr(config, field, None)` 惰性取值；锁定分支只给 `GUOCHAN` 硬塞 `mosaic="国产"`；回退类型名单必须用有序的 `get_type_sites()`，不能用 `list(set)`（Website 枚举 str 的 hash 每进程随机化）。
- 无码官网五站由 `official_uncensored.py` 统一路由，均需代理；1pondo / pacopacomama / 10musume 的 dyn/phpauto JSON API 直通。
- 被墙站测试：`-m scripts.dev_proxy start|status|test <url>|stop`，日本 IP 限制站用 `--port 7891 --regions "jp|日本"`；连通性验证必须用 curl_cffi impersonate；批量探测要校验 `data.title` 防假阳性。
- HTTP 4xx/5xx 错误串必须携带截断响应体（保留 `"HTTP {status}"` 前缀）。
- 番号归一化：前导单数字双重语义（studio 名单数字保留 vs DMM 预约版 `9` 前缀剥掉），改正则前 grep 全部分支。
- 站点域名优先级与删站属产品取舍，查证给方案不擅动；删站影响面 = 注册表 + Website 枚举 + 默认 proxy 列表 + `migrations.py` 清洗 + UI 列表。
- **站点默认地址一律不带 `www.`，唯一例外 MGStage**（2026-10-24 定规）：`base_url_()` 默认值、AIO `fallback_domain`、`DEFAULT_SITE_URLS` 都不加，自定义网址也不再自动补 www。改默认地址一并核对 `docs/Scraper.md` 两张表。
- **失效域名直接删，不留兜底**（2026-10-24）：删到只剩一个地址的站点（7mmtv / IQQTV / freejavbt）连镜像轮换一起删。
- **JavBus 四条线路、一个地址一次**：`www.javbus.com` → `www.dmmsee.casa` → `www.javsee.cyou` → `www.cdnbus.bond`，由 `_MULTI_ADDRESS_SITE_TARGETS` 派发，爬虫内部不再自建轮换。JavDB 默认 `javdb580.com`、第 2/4 次回退 `javdb.com`。
- 「当前网站」下拉网址列显示一律去 www（`init._display_site_url`，只改显示）；新增配置 `last_custom_website`，交互中只置脏标记、`exit_app` 时落盘（别在交互里 `manager.save()`）。
- 带语言段的入口地址不能直接当前缀拼：`base/web.py::site_root()` 先收敛成 `scheme://host`；missav 默认地址固定带 `/dm247/cn`，不带会被 302 到英文页。
- javdb 三源：javdb（网页）/ javdb_api（镜像站）/ javdb_app（App API，免 CF 最稳）；thejavdb 与 javdb 无关。App 签名见 `docs/Javdb_App_Signature.md`，排障锚点 = 三主机同时 4xx 或 InvalidSignature；搜索 limit ≤ 50，分页须 `movie_sort_by=release`。
- javdb 图源无水印体系：`tp.spfcas.com` 是 App 专用（单字节 XOR），`c0.jdbstatic.com` 带水印；解密集中在 `base/web.py`。加密流尺寸探测 (0,0) 属预期。

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
- **尚未落地（别当成已修）**：①`load_config()` 的填表仍在 `if errors: ... return` 之后（`load_config.py:91-103`），必须提到 errors 分支之前（`_refresh_config_file_combos()` **并不存在**）；②下标查找仍是裸 `all_config_files.index("config.json")`，缺文件时 ValueError，应逐级兜底。
- **⚠️ 互调型递归必须自带重入保护**（2026-10-19 诊断完成、修复未落地）：`load_config()` ↔ `pushButton_init_config_clicked()` 互调，终止只靠「下一轮文件已存在」，可 `reset()` 补的文件不保证同一路径 → 约百次后 `RecursionError`；代码里**没有** `_creating_config` 标志。配套纪律：判循环别看栈尾；一处崩溃可能长期掩盖另一处；本地状态文件会被探针污染（`MDCx.config` 残留 Temp 路径会「启动即崩」）。
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
- **刮削模式值全表**（2026-10-23 起）：1 正常 / 2 分离 / 3 视频 / 4 更新 / 5 读取 / 6 整理 / 7 补全。改动模式必须同步：`config/extend.py` 常量与 `is_xxx_mode()`、`load_config.py` / `save_config.py` 的 `mode_mapping` 与 radio 映射、`MDCx.ui` 单选项与说明、`core/file.py` 的模式元组、`base/file.py::get_movie_list`、`core/scraper.py` 的续刮排除与扫描排除、`init.py` 提示词、软件内使用说明。

## 日亚 ASIN 数据库

- 证据强度：tenhow cid 结构化映射 > EAN/JAN 条码 > 标题 NFKC 系列互含 > 图像相似度（`_cover_similarity` 三阈值 0.82 / 0.86 / 0.70，只能兜底）。
- 软校验：条码/EAN 与 ASIN 库命中免验；软匹配走 v2 三步链（cid 旁证 → 标题门 + 真合集词一票否决 → 图像兜底）；演员名兜底是错挂重灾区，全链必走。
- 出厂库合并：同番号覆盖用户库 5 列，用户独有保留，出厂独有追加；出厂库更新须用户明确确认。
- 待修正 sheet 三分类（主表已有同番号→删、番号不同→反查标题裁决、主表未有→标题法/cid 反查）；批量行先按 ASIN 去重。
- 列写入走显式列号映射，不手数 index；入库后 sanity check `r[1]` 是纯 ASIN。
- cid → 番号规则 `^(\d*)([a-z]+)(\d+)([a-z]?)$` → `系列大写-{int:03d}`；离线索引 `resources/userdata/tenhow_asin_cids.json`（36441 条）。
- DMM cid 结构：前缀映射 + 数字双态（5 位补零 digital 与 3 位 mono 同系列可并存）+ 双路径。DMM 图床下架时 CDN 不删对象，占位图 200+ 且 <4KB 已拒收。
- 日亚图 SL1500 物理无条码；老商品标题是半角片假名（NFKC 必做）；日亚 DVD 封与 DMM digital 封版本不同（相似度天花板 ~0.62）；tenhow.net 图床 `images/{ASIN}.jpg` 与日亚 SL1500 同源，免代理直取。
- 工程散点：数据治理前先 `Counter` 关键列识别导入批次残留；openpyxl 迭代中 `delete_rows` 会跳行（读出→去重→清空重写）；javbus 搜索不识别 ASIN；**合并判定禁用 or 链**（短路吞判定值、带副作用的 `pop` 不执行）；外部 API 错误码取响应原文字面值。
