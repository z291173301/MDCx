# Changelog

按日期分段（`## YYYY-MM-DD`，新 → 旧）。只写「做了什么 / 改了什么 / 修了什么」；原因与排查过程见 `docs/Development.md`，长期规则见 `docs/MEMORY.md`。

## 2026-10-29

### 「当前配置」下拉框排除 `license.json`

- 用户反馈：`license.json` 是授权文件不是配置文件，却出现在「当前配置」下拉框里，选中它等于把授权内容当配置加载。
- `mdcx/config/manager.py::ConfigManager.list_configs()` 在列出 `*.json` 时排除 `license.json`（大小写不敏感，`LICENSE.JSON` 同样排除）；其余 `.json` 仍一个不滤，保留「读不出来的那份也要能选」的逃生通道。
- 该名字与 `mdcx/utils/licensing/state.py::LICENSE_FILE_NAME` 保持一致，但不 import，避免 config 层反向依赖 licensing 层。
- 测试：`tests/test_config_list_excludes_license.py`。

### 鼠标任何情况下都不再出现手型（✋）

- 用户定规：鼠标在软件里始终保持箭头，任何控件、任何状态都不要变成 ✋。
- 新增 `mdcx/utils/qt_cursor.py::install_arrow_cursor_guard()`：在 `QApplication` 上装事件过滤器，任何控件触发 `CursorChange` 且新光标是 `PointingHandCursor` / `OpenHandCursor` / `ClosedHandCursor` 时立即改回 `ArrowCursor`。`main.py` 创建 `QApplication` 后安装。
- 该守卫专门解决「只给控件设一次箭头仍会变手」的情况：`QLabel` 富文本 `<a href>` 锚点悬停时由 `QWidgetTextControl` 自行切手型，侧栏 `[赞助作者]` 即属此类。
- 清掉代码与 `.ui` 里所有显式手型赋值：`mdcx/views/MDCx.ui`（10 处，重新生成 `MDCx.py`）、`window_ops.py`（拖窗 / 版本号）、`cut_window.py`（裁剪框拖动）、`init.py`（站点网址下拉悬停）。其它功能光标（文字 I 形、等待、分隔条调整）不受影响。
- 测试：`tests/test_license_buttons.py::test_hand_cursor_is_always_forced_back_to_arrow`、`::test_donate_link_keeps_arrow_cursor`。

## 2026-10-28

### 产品名 `CF Bypass` / `CloudFlare Bypass` 中间的空格

- 用户定规：`CFBypass` 一律显示成 `CF Bypass`、`CloudFlareBypass` 一律显示成 `CloudFlare Bypass`（两个词之间留一个空格）。
- `mdcx/utils/__init__.py::_restore_kept_gaps()` 的固定搭配新增 `CF` + `Bypass`、`Cloud[Ff]lare` + `Bypass` 两条；日志清洗删完行内空格后补回。URL 段（`https://a.com/CFBypass`）与代码标识符（`CFBypassHostIssue`）不补空格。
- 网络设置页「使用代理」提示框里写死的 `CF Bypass代理` 已从 `CFBypass代理` 改正（`mdcx/views/MDCx.ui` 与生成的 `mdcx/views/MDCx.py` 同步）。
- 测试：`tests/test_log_left_align.py::test_strip_log_spaces_keeps_cf_bypass_gap`、`::test_strip_log_spaces_does_not_touch_cf_bypass_like_text_in_url_or_identifier`。

### 日志页 / 网络检测页 / 授权弹窗的请求前缀空格（URL 转超链接后）

- 用户反馈：软件日志页及其他页面仍显示 `GEThttps://…` / `GEThttp://…`。
- 原因：URL 先被 `add_html()` / `add_html_plain_text()` 包成 `<a href="…">…</a>`，清洗时 `GET` 与 `https://…` 被整个开始标签隔开，旧的相邻字符匹配补不回空格，界面可见文字就被压成 `GEThttps://…`。
- `mdcx/utils/__init__.py::_restore_kept_gaps()` 改为穿透 HTML 标签看下一个**可见**字符：`GET <a href="…">https://…</a>` 照样在方法后补一个空格；`MDCx YYYYMMDD` 同规则。URL 路径 / 查询串里的同名串（`https://a.com/GEThttps://b`、`?q=MDCx20261027`）仍不动，重复清洗保持幂等。
- 覆盖 GET / POST / HEAD / PUT / DELETE / PATCH / OPTIONS，与 `http://`、`https://` 两种前缀。
- 测试：`tests/test_log_left_align.py::test_strip_log_spaces_keeps_request_gap_across_html_tags`、`::test_add_html_keeps_request_gap_before_link`、`::test_add_html_request_gap_is_idempotent_on_second_pass`。

### 请求前缀 `GET http(s)://` 中间的空格保留

- 用户定规：请求前缀统一写成 `GET https://…` / `GET http://…`（方法与地址之间有一个空格），日志清洗不得把它压成 `GEThttps://…` / `GEThttp://…`。
- `mdcx/utils/__init__.py::strip_log_spaces()` 删完行内空格后，对**标签外**的请求前缀（`GET` / `POST` / `HEAD` / `PUT` / `DELETE` / `PATCH` / `OPTIONS` + `http(s)://`）补回一个空格；URL 路径里的同名串不动。
- 测试：`tests/test_log_left_align.py::test_strip_log_spaces_keeps_http_request_gap`、`::test_strip_log_spaces_does_not_touch_request_like_text_in_url`。

### 版本标识 `MDCx YYYYMMDD` 中间的空格保留

- 用户定规：版本显示统一写成 `MDCx 20261027`（品牌名与日期之间有一个空格），日志清洗不得把它压成 `MDCx20261027`。
- `mdcx/utils/__init__.py::strip_log_spaces()` 删完行内空格后，对**标签外**的 `MDCx` + 8 位日期补回一个空格；HTML 标签属性 / URL 里的同名串不动。
- 测试：`tests/test_log_left_align.py::test_strip_log_spaces_keeps_mdcx_version_gap`、`::test_strip_log_spaces_does_not_touch_version_like_text_in_html_tag`。

### 日志行首图标与文字之间恢复一个空格

- 用户定规：日志除换行外不留多余空格，但每行行首的图标与文字之间要留一个空格（如 `🔐 授权状态：`、`📂 程序目录：`）。
- `mdcx/utils/__init__.py::strip_log_spaces()` 统一处理：删除行内多余空格 / Tab / 全角空格，保留换行、HTML 标签内部语法，并在每行行首图标后补回一个空格；`LogConsole`、`Signals`、主窗口日志页与 `add_html()` / `add_html_plain_text()` 全部走这一出口。
- 测试：`tests/test_log_left_align.py`、`tests/test_license_buttons.py`、`tests/test_base_web.py` 已同步更新。

### 工具页动作按钮一律不再自动跳到日志页

- 工具页所有动作按钮（查看本地番号、软链接、检查缺失番号、单文件刮削、移动 MP4、清理文件、加字幕、增删剧照/剧照副本/主题视频、封面补图、演员信息/头像、演员库维护等）点完都留在工具页：任务照常提交、进度与结果照常写主日志，要看日志自己点左侧「日志」。之前一点按钮界面就被强行切走，想继续在工具页操作得再切回来。
- 左侧「日志」按钮、刮削结果弹窗里的「查看日志」按钮照旧可用；`tool_page.py` / `tool_handlers.py` 里已无 `pushButton_show_log_clicked()` 调用。
- 测试：`tests/test_tool_handlers.py::TestNoAutoJumpToLog`、`tests/test_actor_missing_numbers.py::test_find_missing_number_button_stays_on_tool_page`。

### 查缺日志排版收紧：去掉多余空行与数字间空格

- 「检查缺失番号」的日志不再在每段 `>>>>` 分隔线前留空行（`>>>>` 直接接上一行），「📊 演员汇总」「🔴 未找到」「🎉 查询完毕」前也不再空行；「并行查询 6 组站点，共 10 个站点...」改为「并行查询6组共10个站点...」，「名字变体：A / B」改为「名字变体：A/B」，「N 个站点参与」改为「N个站点参与」，数字与汉字之间不留空格。
- 测试：`tests/test_actor_missing_numbers.py::test_missing_number_log_has_no_leading_blank_line`、`::test_collect_numbers_log_line_has_no_extra_spaces`。

### 工具页「检查缺失番号」右侧新增「打开目录」

- 「检查缺失番号」按钮右侧新增「打开目录」：点一下用系统文件管理器打开「本地资源目录」设定的目录。以输入框当前内容为准（手改未保存也生效），为空时回退到配置里的 `local_library`；该字段支持中英文逗号分隔多个目录，打开第一个真实存在的，目录不存在只在日志里提示。
- 布局：宽高与上方「选择目录」按钮一致（110×40），左缘与「选择目录」同列、上下与「检查缺失番号」同一行；页面拉宽/还原时逐次跟随，两枚锚点按钮自身几何不动。按钮样式（含 hover/pressed、浅色/深色主题）与同排按钮一致。
- 测试：`tests/test_tool_page_right_align.py`（三种窗宽下同列同行、不重叠）、`tests/test_actor_missing_numbers.py`（打开首个存在的目录、目录不存在只提示、空输入回退配置、`.ui`/`MDCx.py` 声明与 `init.py` 连接）。

### 未授权拦截只弹窗：不再写左下角状态栏与日志

- 未授权点工具页 / 信息管理 / 演员管理里受保护的动作时，只弹「请获取授权」弹窗；左下角状态栏不再显示「🔒 xxx：请获取授权」，主日志也不再追加带原因的同内容一行。
- 演员管理器内部写操作（数据源测试 / 数据获取 / 数据清洗 / 数据导出 / 演员同步 / 更新内容 / 获取头像 / 获取信息）同样不再往窗口日志里记「🔒 …：请获取授权」（`_premium_blocked()` 只返回拦截结果）；开窗时也不再打印「🔒 未授权：可连接 Emby…」那一行提醒。
- 额度用完的提示（「今日免费刮削额度已用完」等）保持原样：那是状态说明，不是点击拦截。
- 测试：`tests/test_license_buttons.py` 新增三条（`premium_gate()` 只弹窗、不碰状态栏与日志；演员管理器 `_premium_blocked()` 不写窗口日志；开窗日志没有「🔒 未授权…」提醒）。

### 「只获取单演员」勾选态写入配置文件

- 工具页「检查缺失番号 → 演员名选项 → 只获取单演员」的勾选态改存进配置文件的 `switch_on`（`single_actor_only`，对应 `Switch.SINGLE_ACTOR_ONLY`），重启后保持。
- 点「检查缺失番号 / 查看本地番号」时若勾选态与配置不同，会先自动保存，与演员名、本地资源库同一套逻辑。
- 旧配置没有该开关 → 按未勾选处理（行为与旧版一致），不需要手动改 JSON；在设置页或工具页保存一次即写入文件。
- 测试：`tests/test_actor_missing_numbers.py`（开关值、旧配置缺键默认不勾、load/save 双向绑定与两个入口自动保存）。

### 额度计数改用独立 license_quota.db，改成「成功一次算一次」，并防改系统时间清零

- 存储分家：额度写在 `userdata/license_quota.db` 的 `license_quota` 表（单行 `day` / `used` / `max_seen` / `sig`），`used` 就是 0~10 这个可读数字；`userdata/scrape_state.db` 恢复原职，只做断点续刮缓存，不再混放额度。
- 旧数据自动迁移：上一版存在 `scrape_state.db.license_quota` 表里的当天番号列表会折算成次数写入新库，然后把那张表 `DROP` 掉；上一版的 `license_quota.state` 旧格式镜子文件也能读懂，不会误判成「文件被改」而封掉额度。
- 计数单位由「成功番号数」改为「成功刮削次数」：移动过的文件再刮一次成功，同样占一次额度（不再按番号去重）。成功 `quota.commit()` 加一，失败/异常 `quota.release()` 归还预留位，额度用完后多余文件只记失败列表、不移动。
- 防改时间清零：记录里多存一个只增不减的 `max_seen`（见过的最晚时刻）。当前系统时间早于 `max_seen`（5 分钟容差，NTP 校时不算）或当前日期早于记录日期，即判定为回拨——**沿用原计数、绝不清零**，并在主日志写「⚠️ 检测到系统时间被回拨…」；只有日期正常前进才清零。
- 防直接改数：`used` 与 `day` / `max_seen` 一起做 HMAC 签名，手改 `used`（比如改成 0）或改日期会校验失败，按「今日额度已用完」处理（fail-closed）。
- 防「来回改日期刷额度」：额度库里多一张 `license_quota_history`（每天一行 `day` / `used` / `sig`，保留 30 天）。某一天用过多少次就永远记着——把日期往后拨一天用掉 10 次、再拨回今天、再拨回去，都不会重新发额度；手改历史表里的次数同样签名对不上，按已用完处理。
- 旧表迁移每个进程只查一次（`scrape_state.db` 刮削期间被续刮缓存占着写锁，不该每个文件都去等锁）。
- 仍保留镜子文件 `userdata/license_quota.state`（原子写，不经 SQLite）：库被删行/被换掉时读回，两份取「日期最新、次数最大」的一份；额度库与续刮缓存分家后也不会再撞 `database is locked`。
- 启动日志第二行改为按「次」显示：「🔓 今日免费刮削额度：已成功 X/10 次，剩余 Y 次」；异常时追加 `quota.anomaly()` 一行。启动与每次起任务前的 `quota.refresh()` 不变。
- 测试：`tests/test_license_quota.py` 覆盖独立库位置与可读数值、同文件二次刮削计数、重启/删行恢复、日期回拨、同日时钟回拨、日期前跳+时钟倒退、直接改 `used` 按满额、旧库/旧镜子迁移。
- 跨天必须**联网校时**才发新额度（`mdcx/utils/licensing/net_time.py`：HEAD 请求取 HTTP `Date` 头，单次 1.2 秒、总预算 2.5 秒、进程内缓存 10 分钟，按本地时区换算日期）。网络日期与本地一致才清零发当天 10 次；不一致或连不上就按「今日额度不发放」处理（fail-closed），所以把系统时间往后拨任意天，一次额度都刷不出来。`quota.anomaly()` 会写明是「时间不一致」还是「无法联网校时」，起任务被拦与授权弹窗都会带上这行 ⚠️ 提示，不会只报「额度用完」。
- 把时间改回来不用重启：`_unverified_day` 记住被拒的那个日期，日期恢复后按磁盘记录重新算回原计数。测试用 `quota._network_date_provider` 替换真实网络（`tests/conftest.py` 里 autouse 桩让网络日期等于本地日期，用例本身不发请求）。

### 整理模式免费；其它模式未授权合计每天最多成功刮削 10 个番号

- 「整理模式」不再需要授权：未授权点开始直接按整理模式跑，不联网、不计数、不弹授权提示。
- 「读取模式」「整理模式」之外的正常 / 分离 / 视频 / 更新 / 补全模式：未授权时**这些模式合计**每天最多成功刮削 **10 个番号**（共用一个额度池，不是每个模式各 10 个；按番号去重，同番号重试不重复占额）。额度计数加密写入 `userdata/scrape_state.db` 的 `license_quota` 表（HMAC-CTR + encrypt-then-MAC，密钥与每日上限按四段分片 + 掩码散在 `_quota_key` / `_quota_a..d`，防直读明文），跨重启累计、次日自动清零。
- 额度用完后，本轮多余的番号不再联网刮削，**只记入失败列表、不移动文件**，同时弹一次「请获取授权」说明额度已用完；下一次点开始若额度仍为 0，起任务闸门直接拦下并提示。
- 弹窗时机按「成功番号数」判定：并发时预留位占满不等于额度用完（可能 1 个成功、9 个还在跑），只有真的攒满 10 个成功番号、且本轮已有番号被拒才弹；第 11 个起的番号一律不再联网，直接强制停止并记入失败列表（文件留在原位置）。
- 「读取模式」「整理模式」任何情况下都不弹授权窗：`premium_gate.license_gate()` 对这两种模式直接静默放行（原读取模式首次点开始的一次性说明框已删除），只有其它模式额度用完才弹。
- 未授权时「设置→高级→间歇刮削→连续刮削」填再大也不越过额度：一轮最多连续刮 10 个番号（填 11 也只连刮 10 个），已授权按设置值；落点 `guard.rest_batch_limit()`，`core.scraper` 的休息判断与日志都改用压缩后的值。
- 授权弹窗文案按用户口径改为逐模式写全：`当前电脑没有授权文件：读取模式、整理模式可以正常使用；正常模式、分离模式、视频模式、更新模式、补全模式合计每天最多成功刮削10个番号，不会移动文件，超出部分会记入失败列表`（`premium_message()` / `premium_quota_message()` 共用新增的 `_license_notice()`）。
- 修「重启软件后额度又从 0 开始」：额度改成**双份持久化**——`userdata/scrape_state.db` 的 `license_quota` 表 + `userdata/license_quota.state` 备份文件（临时文件 + `os.replace` 原子写，不经 SQLite 锁），读回时两处取并集。原先写库撞上断点缓存的长事务（`database is locked`）会静默失败、计数只留内存，重启就丢；现在写库失败会重试并落到备份文件，删 `scrape_state.db` 重置缓存也不会把额度清零。
- 新增 `quota.refresh()`（只增不减地与磁盘对齐）：软件启动时写入主日志第二行「🔓 今日免费刮削额度：已成功 X/10 个番号，剩余 Y 个」，额度为 0 时写「🔒 已用完…需获取授权」；`guard.scrape_allowed()` / `guard.mode_allowed()`、`premium_gate.license_gate()` 判断前都先 `refresh()`，重启后点正常 / 分离 / 视频 / 更新 / 补全模式或其它需授权功能会立刻弹窗拦下。
- 新增 `mdcx/utils/licensing/quota.py`（预留—提交/释放的并发计数）、`mdcx/utils/licensing/_quota_key.py` / `_quota_a..d.py`（额度密钥与每日上限混淆）；`guard.scrape_allowed()` / `mode_allowed()`、`premium_gate.license_gate()`、`core.scraper` 逐文件路径已接入。
- 测试：`tests/test_license_quota.py`、`tests/test_license_buttons.py`。

## 2026-10-27

### 演员行右键菜单新增「更新内容」：改完就地提交

- 可编辑列（姓名/出生日期/出生地/详情/标签）右键菜单最上方新增「更新内容」（在「复制内容」之上）。
- 只在该行有待更新内容（`need_update_info`，即行内改过或取数带回新值）时可点；未改动时置灰，并提示「先在格子里改，改完再从这里提交」。
- 点选后弹「确认更新内容」确认框，确认即只把这一行提交到 Emby/Jellyfin（信息，不动头像/背景图），不必再大幅移动鼠标去点「开始全部更新同步」；批量同步与单行提交共用 `_start_sync()` 一套线程/收尾逻辑。
- 授权口径同批量同步：未授权点「更新内容」弹「请获取授权」并写一行日志。
- 测试：`tests/test_actor_manager_context_menu.py`（菜单四项与顺序、无改动置灰、改动后可点且只提交该行、确认答「否」不提交）。

### 「清空缓存目录」不再需要授权

- 演员管理器「清空缓存目录」移出授权闸门：只删本机已下载的头像缓存，不联网、不写回 Emby、不消耗服务，未授权点按钮直接进「确认清空缓存」对话框（确认框仍在，删前照旧问一次），答「是」即清理 `userdata/emby_actor_cache/` 与临时演员缓存目录。
- 其余写段拦法不变（数据获取 / 数据清洗 / 数据导出 / 开始全部更新同步 / 数据源测试 / 详情窗的获取头像·获取信息·同步）。
- 测试：`tests/test_actor_manager_license_gate.py` 拆出「清缓存未授权进确认框、答否不删」「答是真删」两例，数据源测试仍单独验拦。

### 未授权也能打开演员管理：连接 Emby 读取、统计演员信息

- 入口不再拦：未授权点左侧「演员管理」直接开窗（原先是弹「请获取授权」后什么都不开）。
- 只读段照常：连接 Emby/Jellyfin、获取演员列表、统计栏计数与筛选、表格浏览/复制/行内编辑、设置窗（只改本地配置）。
- 写段逐处拦：数据获取 / 数据清洗 / 数据导出 / 「开始全部更新同步」/ 数据源测试，以及演员详情窗的「获取头像·获取信息·同步」，点时才弹「请获取授权」并写一行日志；界面不置灰（沿用「点了才提示」口径）。「清空缓存目录」不拦（见下一条）。
- 开窗时日志首行写明「未授权：可连接 Emby、读取并统计演员信息；取数 / 清洗 / 同步 / 导出需获取授权」，免得点到最后才被告知。
- 新增 `license_ui.premium_denied()`：给不继承主窗 Mixin 的独立窗口（演员管理器）复用同一份弹窗文案。
- 测试：`tests/test_actor_manager_license_gate.py`（10 例）、`tests/test_license_buttons.py::test_unlicensed_actor_manager_opens_readonly`。

### 授权提示文案统一

- `license_ui._premium_message()` 固定三段：`<功能名>功能需要获取授权后才能使用`（句末不带句号） / 读取模式能做什么、不能做什么 / 获取授权四步（设置→高级→高级功能→「设备编号」导出编号 → 发作者 → `license.json` 放配置目录 → 重启）。
- 功能名按按钮语义拼接（刮削、保存NFO、演员管理…），句式统一，不再逐处手写。
- 「授权状态」日志行未授权时只显示原因：`guard.describe()` 去掉「未授权（…）」外壳，输出「🔐 授权状态：未找到授权文件」；已授权文案不变。
- 测试：`tests/test_license_system.py::test_describe_wording_without_licensed_shell`、`tests/test_license_buttons.py`。

## 2026-10-26

### 高级页新增「设备编号」按钮（导出设备 ID 的 txt）

- 位置：设置→高级「隐藏图标：」行末、「隐藏菜单图标」右侧；样式与宽度同「导入账单」，绝对定位钉在锚点右缘，不进布局。
- 点击导出 txt（设备编号 / 系统 / 计算机名 / 生成时间，UTF-8），默认 `设备编号_<计算机名>.txt` 落桌面。
- 取号口径同系统「关于」：Win11 `SQMClient\MachineId` → `MachineGuid` → DMI UUID；macOS `IOPlatformUUID`；Linux `/etc/machine-id`。全本地读取、不联网、进程内缓存。
- 不绑定机器——它就是给用户导出编号申请授权用的，人人可见。
- 测试：`tests/test_device_id_button.py`。

### 赞助窗口接入微信 / 支付宝账单：新增「导入账单」（绑定本机 CPU）

- 位置：设置→高级→高级功能「隐藏信息管理」右侧，与「显示字段内容信息」上下对齐；绝对定位游离子项，几何由 `_sync_advanced_page_bill_button` 按锚点钉死。
- 绑定：`machine_binding.py` 取 `ProcessorId` 算 SHA-256 与内置名单比对，仓库只存哈希；后台线程探测，未绑定机器按钮不显示。
- 解析：`tools/bill_import.py` 按列名识别微信支付 / 微信经营账户 / 支付宝三类账单，只统计收入，捐助者名取「来自 xxx」尾巴。
- 落盘：`resources/donate_records.json`（随包）+ `userdata/donate_records.json`（本机生效），读取取并集去重。
- 榜单：新人榜 = 最近 10 位、土豪榜 = 金额前 10，均按人去重；今年显示 `10-25 20:23`、跨年显示 `2026-10-25`。
- 测试：`test_bill_import_parse.py`、`test_donate_window_ranks.py`、`test_bill_import_button_align.py`、`test_bill_import_flow.py`。

## 2026-10-25

### 「检查演员缺失番号」改为多站点汇总 + 归一化对比 + Excel 输出

- 站点链按类型固定（有码 DMM→DMM_API→LibreDMM→JavDB→JavDB_API→JavDB_APP→Javlibrary·镜像→JavLibrary→JavBus，无码 / FC2 / 欧美 / 国产 / 动漫各有定稿链），顺序即优先级。
- `tools/actor_sources.py` 重写为「站点注册表 + 归一化」：`ssis00006` / `SSIS-006` 先 `normalize_key()` 折叠再比对，`display_number()` 还原展示。
- 同域名组串行、跨域名并发，每站最多 2 次请求；演员名先经 JavDB 演员库解析日文原名再查。
- 输出 `演员名.xlsx`（番号 / 网站 / 链接地址），日志只留命中与缺失统计。
- 表由 3 列扩到 7 列：番号 / 演员 / 日期 / 时长 / 类型 / 网站 / 链接；文件名带时间戳；日期写 Excel 日期型、时长写分钟。
- 站点清单两条路：**自动判断**走固定链；**指定类型**走「类型刮削网站」对应组（组内顺序即优先级，禁用站点仍参与查缺）。
- 工具页新增「类型」下拉（自动判断 + 六类），几何由 `_sync_tool_page_input_fill` 钉死；`comboBox_actor_type` 加 QSS 限定规则解决「自动判断」末字被裁。
- 新增「只获取单演员」复选框：只保留演员表恰好一个演员的番号。
- 标题抽番号收紧：字母段与数字段有分隔符、或无分隔符但数字 ≥3 位才算番号（`SKE48` 不再误判，`TEK-067` 照取）。
- JavBus 12 个内置镜像实测删 4 个（`busjav.bond` / `seejav.cyou` / `javbus.bond` 返回跳转壳、`buscdn.bond` 404）。

### 信息管理切换番号时封面/缩略图不跟着换

- 根因：预览同步只在「缩放后尺寸变化」时 `setPixmap`，同尺寸（如 FC2 的 1:1 封面）被判为「图没变」。
- 修复：`_sync_nfo_lib_preview_pixmaps()` 新增 `force` 参数，换图后强制重设；无图番号显示占位并清理旧图。
- 测试：`tests/test_nfo_library_maximize_preview.py::test_switch_nfo_refreshes_same_size_preview_images`。

## 2026-10-24

### 站点地址：默认一律不带 `www.`（唯一例外 MGStage）

- 所有 `base_url_()` 默认值去掉 `www.`；`MGStage` 按用户要求保留 `https://www.mgstage.com`。自定义网址也不再自动补 www（`normalize_custom_url()`）。
- 四个站点换址：JavLibrary → `javlibrary.com/cn`、IQQTV → `iqqr1.org/cn`、JavFree → `javfree.me`、Madouqu → `madouqu.shop`；Missav 系列改 `missav.live/dm247/cn`（必须带语言段，否则 302 到英文页）。
- JavDB 默认 `javdb580.com`（`javdb.com` 降为镜像）；JavBus 四条并列线路、每条只打一次（`_MULTI_ADDRESS_SITE_TARGETS`），爬虫内部不再自建轮换。
- 删失效域名：`c97k.com`、`7tv022.com`、`missav.ai`、`freejavbt22.cc`、IQQTV 三个旧域名（连带镜像轮换一起删）。
- 新增 `base/web.py::site_root()`：带语言段的入口地址先收敛成 `scheme://host` 再拼路径。

### JavBus 四条线路改用 www 入口：网络检测不再误报「Cookie 可能无效」

- 四个裸域全部 301 到 www，跨主机跳转丢 Cookie → 检测看到匿名用户。地址统一改 www 变体，`cookie_checks.py` 补全四线路。
- `network_check._classify_http_result` 加「跳转丢 Cookie」保护：落地 host 变了就提示改网址，不再算 Cookie 的锅。

### JavDB / JavDB_API 换域名后的检测失败与探测超时

- 新增 `utils/site_url.py`（`without_www` / `strip_redundant_www`）；`network_check` 遇空壳 200（正文 < 64 字符）自动改打去 www 地址，不再判「连接正常」。
- `javdb_api._try_mirrors()` 候选改为「配置地址 → 去 www → `javdb580.com` → 旧镜像」，改走全局代理。实测检测 66.7s 超时 → 4.2s 正常。

### JavDB Cookie 检测：多节点投票 + 详情页登录态判定

- 新增 `classify_javdb_login_state()`：详情页标记 / `/logout` → 已登录；登录表单 / `href="/login"` → 未登录；CF 挑战页 → 拦截；空壳页 → 判不了。
- 候选地址逐节点实测取最高可信票，任一有效即收工；只有 `valid` 才写盘，其余只告警并保留用户 Cookie。

### 其他

- 禁用站点照样参与网络检测（刮削侧「禁用即不请求」不变）。
- 「当前网站」下拉网址列一律不显示 www（只影响显示，实际访问仍用真实地址）；新增 `last_custom_website` 记住上次使用的站点，`exit_app` 时落盘。
- 「自定义网址」只回显真正改过的站点，与默认地址相同按「没自定义」处理；刮削时全程只打自定义地址，不切内置镜像。
- 请求次数封顶：普通站点一个番号最多 3 次，JavDB / JavBus / JavLibrary 源镜像交替最多 4 次（`use_base_url()` 钉住地址、关掉内部轮换）。
- 补全模式：13 项关键字段齐全时直接进成功列表，一次请求都不发。
- 新增 `core/outline_guard.py`：简介/原简介里的「发行日期」「看更多」判为占位，不用来回填。
- JavBus 默认站点改回主站，防屏蔽地址换 `dmmsee.casa`；默认配置里 JavBus 的 `custom_url` 清空。

## 2026-10-23

### 伴生文件搬移全面改为「番号关联 + 事务 + 回滚」

- 正常 / 分离 / 更新三模式勾选「刮削成功后移动文件」时，先建整库归属索引（`_prepare_organize_index`），逐文件判定归属，任一失败整体回滚（`OrganizeTransaction`）。
- 字幕 / 种子 / bif / json 改由 `organize_companion_files` 统一搬运，替换 `move_sub` / `move_torrent` / `move_bif` / `move_other_file`。
- 分离模式用 `asset_root=meta_folder` 让剧照目录落数据目录；软链接/硬链接模式不搬伴生文件。
- 视频模式删掉两个互斥选项（`Switch.SORT_DEL` / `SORT_MOVE`），固定「搬视频 + 删属于该视频的伴生文件 + 删空目录」。
- 索引排除系统目录（`@eaDir` / `#recycle` / `$RECYCLE.BIN` / `Thumbs.db` 等），排除目录比较改归一化路径（大小写不敏感）。

### 新增补全模式（`main_mode == 7`），读取模式收敛为只读展示

- 补全模式：本地有值一律保留、只补空字段；无 nfo 回退正常模式；图片缺哪张补哪张；字幕按番号复制；伴生文件事务式搬运；已在成功输出目录内的走 `complete_inplace_locked`（只补内容不移动）。
- 读取模式：只读 nfo 字段与本地封面/缩略图/背景图，不联网、不下载、不写 nfo、不移动文件；原有 5 个选项迁到补全模式。
- 补全模式选项精简：删「允许更新 NFO 文件」「无 NFO 按正常模式重新刮削」（连同两个枚举值）；NFO 合并策略 5 档 → 3 档，默认「仅填补空字段」；旧配置由 `_migrate_read_mode_options` / `_migrate_nfo_merge_strategy` 清理。
- 新增高级功能「任务模式」：本地存储文件（整理不设间隔）/ 网盘存储文件（按自动休息间隔），旧整理模式的两个 bool 键自动迁移。

### 其他

- `core/file_association.py` 承载全部「番号 ↔ 伴生文件」关联，`core/organize.py` 只留「移动计划 + 事务 + 回滚」。
- 版本号纪律：改代码即把 `consts.py::LOCAL_VERSION` 同步成当天日期，`docs/Development.md` 第 13 章与 `docs/MEMORY.md` 同步。
- 运行环境升到 Python 3.15（`requires-python`、`uv.lock`、`requirements.txt`、README 徽章、Development.md 同步）。
- 界面：补全模式单选项改黑色字体、提示词改绿色；高级页「任务模式」「隐藏窗口」「分屏缩放」「提示词右移」等一批对齐修复。

## 2026-10-22

### 新增

- 主页缩略图、封面图支持 gif 动图（自动播放、随窗口缩放）。
- 界面图片格式扩充到 bmp / jpg / jpeg / jfif / png / gif / webp / tif / tiff / tga / ico / pcx / avif（Qt 无插件的由 Pillow 兜底）。
- Release 标题改为 `MDCx <日期版本号>`，资产名去掉展示版本号段。
- 高级页新增「移动文件」策略（覆盖 / 保留旧文件），整理与视频模式共用。

### 改进

- 编辑 NFO 窗口文本字段改为从左展示。
- poster / thumb / fanart 支持其它格式，搬走时保留原扩展名。
- 整理模式按「成功输出目录」自动分模式（已在目录内 → 按读取模式处理）。
- 托盘右键「隐藏到托盘」去掉快捷键后缀；演员管理器可编辑列右键菜单化（复制 / 编辑 / 查看详情）。
- 旧配置启动时自动补齐缺失顶层键并落盘。
- 「指定网站」下拉补上 Official 旗下 5 个无码官网；JavBus Cookie 检查真正校验登录态；Official 六行检测各自独立。

### 修复

- 读取模式能显示 gif / webp 等非 jpg 主图（此前只认 .jpg）。
- 编辑 NFO 标题不再重复叠加命名模板的 release / number。
- 发版流水线遇超长变更日志段不再崩。

## 2026-10-21

- 新增整理模式「间隔时间」（本地不设间隔 / 网盘按自动休息间隔，最小 40 秒）。
- 迁移到 Python 3.15：新增 `build-py315.yml`、删除 `build-py314.yml`、CI 与类型检查目标同步；带原生扩展的传递依赖钉到首个有 cp315 wheel 的版本。
- 依赖全量升到 PyPI 最新；openai 3.x 传输层换 httpx2。
- 演员管理器「数据清洗规则」改为空白区单击新增、编辑完成自动保存、右键删除。
- 修复：整理模式下文件已在成功输出目录时左下角不切「读取模式」；整理后再点开始报「共 0 个文件」；读取模式两行选项被裁切重叠；ThePornDB 刮削 URL 编码与解析错误；只改 UI 文案却显示 `_failed.json`。

## 2026-10-20

- 新增「整理模式」：先直接移动，失败番号最后统一重试；支持分批与全有或全无事务。
- 站点可禁用（右键「启用 / 禁用站点」），七个类型组共享一份禁用名单；「指定网站」不受禁用名单影响。
- Official 旗下五个无码官网拆成独立站点；新增独立站点 `Javlibrary·镜像`。
- 七组类型改名换序：FC2→个摄、国产→传媒、短剧移到传媒之后、动漫里番独立；「素人番号」改名「国产短剧」，默认名单收缩到只剩 JavDay。
- 演员库并发写安全（进程级锁 + 原子写）、损坏时降级只读；刮削失败站点改为逐字段重试。
- 修复：Lulubar 解析误报「站点无效」、MissAV_API 假成功、ThePornDB 同名作品误匹配、JavBus Cookie 误报、没填 LLM 密钥整个软件起不来、Qt 收尾原生崩溃（access violation）根除等。

## 2026-10-18

- 日志页新增刷子按钮，一键清空显示、不动 log 文件。
- 演员库分片行提示词改写；最小化态「全量更新并入」整行右移对齐「覆盖已有图片」。

## 2026-10-13

- 修复：站点下拉右键点网址后网址消失、选中行白底白字、提示去重与收窄；超分黑图漏检与重试；AIO 系站点（avsox / avmoo / avheat）字段错位与 403 卡住；javdb 样图抽取器把 CDN 占位当图片。
- CI：Linux 依赖缺失、Python 版本漂移导致 jiter 编译失败。

## 2026-10-12

- 新增超分工具及并发控制；超分产物全黑检查与重试。
- 改进：HTTP 404 日志膨胀、进度分隔线、主页状态行文案、运行时防御性加固。

## 2026-10-11

- 演员详情与演员管理器改为互不干扰的独立窗口；演员详情三栏 1:2:1、默认 1080x720。
- 演员管理器最大化 / 最小化 / 还原改为系统原生行为，列宽按窗口状态切换，最小尺寸 1080x720 且启动居中。

## 2026-10-10

- 演员管理器统计栏文案统一并新增「总数」，8 个计数器口径统一。
- 「获取演员类型」勾选 / 不勾选两档数据审计与修复。

## 2026-10-08

- 新增：刮削网站页「锁定类型」下拉、高级页「不限次数刮削」复选框。
- 改进：刮削探测未通过时检测行压到一行；评分抓取追加来源后缀；年份 / 年评分缺失留空不再写哨兵 0；信息管理页三栏 3:4:3。
- 修复：最大化时收款码块上移过多、读取模式首行被盖；`MDCx.py` 与 `MDCx.ui` 漂移；软链接助手按钮右缘对齐；检测新版本时有时无；STRM 写入旧路径；DeepL / DeepLX 调用 5 处修复。

## 2026-10-07

- 左侧导航「使用说明」下方新增微信收款二维码与「赞助作者」入口，新增独立赞助窗口（含支付宝红包码），按参考截图复刻版式。
- 收款码底部锚定、边长恒 180、两侧留 15px；赞助窗口放大到 657x677；演员管理器字体放大一号。

## 2026-10-06

- 分离模式新增「为本地视频文件生成 STRM 链接文本」「复用 / 覆盖数据存放目录元数据」等复选框，右侧四个开关正式生效。
- 四个组框标题右侧加提示与开 / 关按钮；左下角新版本提示改为「🍉 有新版本了！（日期 tag）」。

## 2026-10-04

- 信息管理顶栏目录框与筛选框恒等宽，目录框支持手输回车；裁剪封面后不再跳主页。
- 右键菜单「删除nfo文件」改名「删除NFO文件」；大图预览还原按钮修复。

## 2026-10-03

- 信息管理页点右侧图片弹出大图预览（任务栏独立图标）。
- 修复：底部提示行居中、还原后预览与主窗叠偏、关闭预览连带关主窗、预览按钮失灵。

## 2026-10-02

- 信息管理页最大化时筛选输入框等比例加宽；选目录后自动展示第一个番号。
- 顶栏顺序改为「目录 → 选择目录 → 共 N 个 → 筛选 → 刷新」；批量保存 / 保存当前 NFO 改蓝底主按钮。
- 修复：更新检测改取 tag 最大的 release 并同时比版本号与日期；信息管理表单 16 行间凭空多一行空白；QSS 逗号选择器丢前缀导致 hover 常态生效。

## 2026-10-01

- 读取模式与演员页多处文案改写；命名页、主页左侧栏、演员页多处最大化 / 最小化对齐修复。

## 2026-09-30

- 软件工具页演员库分组重排；翻译页、命名页、字幕页间距收紧。
- 修复：长提示词尾字被裁；最大化时四周先黑屏；控件先落错位再跳目标位；界面缩放调大后状态行压住按钮；`MDCx.py` 与 `MDCx.ui` 失同步。

## 2026-09-28

- 发版工作流收敛为唯一构建发布流水线；新增 Python 3.14 兼容性构建工作流。
- `actions/cache` 升 @v6；`ci.yaml` 只保留 pull_request 门禁；`pyproject.toml` 依赖按 3.14 核对抬高 3 处下限；重试次数滑动条放开到 1~3。

## 2026-09-27

- Amazon 封面改请求 SL2560 原图；左下角状态区图标对齐、版本检查跳转改自有仓库。
- 修复：刮削后左下角模式行只剩光杆图标；「使用代理」不再联动 CF Bypass；CF 挑战页识别补「Verify you are human」；missav 默认地址改 `missav.ws`；镜像轮询 404 误判；Trawl 后端四处修复。

## 2026-09-24

- CF Bypass 自动适配层三处修复；`/html` 路未解开的挑战页不再冒充成功；aventertainments 两类「假 200」点名报错。
- 网络请求超时 45s → 30s、重试 4 次 → 3 次；检测报告根因新增「CF Bypass 已尝试但未解开」；missav / avsex / getchu / javlibrary / r18dev 代理路由修复。

## 2026-09-22

- 修复：统计标签最大化后错位；文件名带 CRACKED 未识别为无码破解；取数中关闭演员管理器导致主程序退出；数据清洗误删合法结构；演员详情简介把 `<br>` 显示成字面文本；DMM 图床探测提速与失败冷却；海报超分增强。

## 2026-09-19

- 新增调试日志三开关与字段来源排障块；演员管理器「获取数据」支持按模式筛子集；网络设置新增「直连白名单」。
- 修复：主页「编辑 NFO」铺满整页；主窗隐藏托盘后关演员管理器连带退出；「只看演员」从未生效；选择媒体库 20 行只显示 19 行；Emby / Jellyfin 连接与取库耗时且无日志；批量同步 HTTP 400（哨兵生日、null source）；剧照 20 张只留 4 张；Jellyfin 12 演员列表恒为 0。

## 2026-09-12

- 修复：欧美 ThePornDB 同日多发刮错、单文件填网址取不到数据；TRAWL 便携版打包布局与首次启动；亚马逊刮削整体失败；单数字前缀番号被误剥；字母+数字系列番号误识别；命名模板超宽缩短。

## 2026-09-06

- 全量检查提速 3 倍。
- 修复：默认代理列表 `seesaawiki.jp` 拼写；部分站点仍直连；fanart 变临时文件且假报成功；演员管理器与主窗状态互相干扰；欧美 theporndb 指定网址刮不出。

## 2026-09-05

- 新增 7mmtv 聚合站爬虫与三个爬虫，精简 15 个冗余 / 失效爬虫。
- JavDB 全系图源无水印升级；DMM 高清直链推广到 11 个聚合站；无码官网五站接入默认代理；刮削进度加预计剩余时间与失败原因 Top N。
- 修复：三页内容最大化后横向不跟随；刮削速度退化三层修复；检测页中途异常中断；保存设置 / 停止刮削后内存占满；失败列表跨影片污染；LogBuffer 内存泄漏；全库审查 26 项缺陷。

## 2026-08-23

- 新增 NFO 库管理页面、字段级跳过抓取、NFO 合并策略、爬虫镜像 / 域名轮询。
- 新增 avmoo / avheat 爬虫，avsox 改 API；dmm_api 换 DMM 官方 Affiliate API；新增 thejavdb_api；MGStage 官方图源直构双兜底。
- 接入 TRAWL / FlareSolverr 外部 CF 服务适配层，移除内置 CF Bypass。
- 界面缩放比例配置、跨线程 Qt 安全收口、UI 收口到 .ui + 几何回归测试、quick-check 与 mypy 启用。
- 修复：主窗口启动崩溃、设置页滚动与底部留白、单 exe 按钮无提示退出、日志通道不通、演员管理器多处崩溃与无响应。

## 2026-08-15

- 新增 DMM 高清图识别去重、ASIN 出厂库增量合并、相似片推荐、SQLite 刮削状态缓存、结果摘要缓存、CF Bypass 健康状态机、Emby 演员缓存持久化。
- 改进：相似推荐特征与召回、文件写入原子化、LogBuffer 并发安全、读模式 tmdbid 落盘、打包与 CI 加固。

## 2026-08-14

- 新增 DMM 官方高清直链（覆盖九个爬虫）、同番号结果 TTL 缓存、R18.dev 英文标题掩蔽还原、演员库维护工具、Emby 演员管理器。

## 2026-08-03 / 2026-08-02

- 演员库维护工具改为直接操作 xlsx；同步别名与刮削共用同一规则；工具页工具排序与槽函数抽取。
- 修复：单 exe 按钮无提示退出、`executor.submit` 传参错误、跨线程 Qt 不安全操作、日志通道不通。

## 2026-08-01

- 新增演员库维护工具、Emby 演员管理器（选库 / 表格查看）、封面补图工具、失败原因记录、自动海报选优、界面缩放比例配置。
- 修复：Windows 路径超限、中文字幕标签误添加、`explorer /select` 路径未引号、Emby 4.9 剧照显示。

## 2026-07-18

- 新增 R18.dev / JavDB API / missav_api 爬虫，四种刮削模式，字段级优先级与标签优先级，24 个命名模板字段，演员 NFO 生成，海报裁剪，网络连通性检查，软链接，明暗主题，成功 / 失败列表，配置迁移与热切换。
- 修复 30 个第三方库安全隐患；无码官网爬虫与 official 前缀路由；域名级独立限流与连接池管理。
- 修复：网络标签页按钮重叠、Windows 启动崩溃、多任务同时刮串数据、正则安全、被吞掉的错误日志。
