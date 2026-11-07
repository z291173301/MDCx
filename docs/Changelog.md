# Changelog

按日期分段（`## YYYY-MM-DD`，新 → 旧）。只写「做了什么 / 改了什么 / 修了什么」；原因与排查过程见 `docs/Development.md`，长期规则见 `docs/MEMORY.md`。

## 2026-11-08

### 检测网络页分组行置顶+改名

- `Official·pixelated`、`Official·uncensored` 移到下拉最上方（原来钉在 `Missav_API` 下方）。
- 改名：`Official·pixelated 官网：有码34站`、`Official·uncensored 官网：无码5站`。
- 测试：`test_network_check`＋`test_ui_structure` 全过；offscreen 实测置顶与分组展开正常。

### 检测网络页筛选文案去空格

- 「已选 71 个站点」→「已选71个站点」；「（有码官网 34 站）」→「有码官网34站」；「（无码官网 5 站）」→「无码官网5站」。
- 测试：`test_network_check`＋`test_ui_structure` 全过。

### 检测网络页开始检测按钮与两页开始按钮对齐

- 根因：`.ui` 里三按钮设计几何本就一致（680/120），但 `layout_master` 把检测页按钮运行时定在 `W-142`（右缘 `W-22`），软件界面/日志页是 `W-140`（右缘 `W-20`），差 2px。
- 改为 `W-140`、宽 120：左右边界与两页开始按钮完全对齐（各页同宽，任意窗口尺寸成立）；同行复制/重试链右移 2px，保持 10px 间隙一致。
- 测试：`test_network_check`＋`test_ui_structure` 全过。

### 检测网络页筛选行：全选/全不选合并为切换按钮

- 「全选」「全不选」合并为单个「全选/全不选」切换按钮（96 宽）：空选时点按=全选 71 站，再点=清空；半选时点按=全选。
- 删掉的按钮宽度让给下拉框：筛选框 274→328（「重试/复制/开始」位置不动）。
- 测试：`test_network_check`＋`test_ui_structure` 全过；offscreen 实测 空→71→空 切换正常。

### 检测网络页筛选行加宽：按钮收窄+弹窗按内容撑开

- 「重试失败项」110→96、「复制结果」110→90（离线量过文字+样式边距，9pt 下各需 80，仍留余量），筛选框 240→274、「全选/全不选」链整体右移一格，右侧「开始检测」位置不动。
- 弹窗按最长选项文本+复选框/图标/滚动条加宽（上限 560），框体 274 但弹窗实测 440，最长站点名不再被省略号截断。
- 测试：`test_network_check`＋`test_ui_structure` 全过；offscreen 实测弹窗 440。

### 检测网络页站点筛选：A-Z 排序+分组全选+全选/全不选

- 下拉选项按名称 A-Z（大小写不敏感）排序；框体与右侧按钮同高 40（`.ui` 设计值本就一致，`layout_master` 重定位时一并保高）。
- 占位文本由「全部站点（下拉多选）」改为「下拉多选」。
- 下拉右侧新增「全选」「全不选」按钮（各 70×40，右缘跟「重试失败项」左缘走、窄窗自适应）：全选勾选全部 71 站，全不选清空（清空=检测全部）。
- 下拉新增两个分组行（钉在 `Missav_API` 下方）：`Official·pixelated`（有码官网 34 站全选）、`Official·uncensored`（无码官网 5 站全选）；勾选分组=勾选组内成员，成员半选时分组行显示半选态；取值时分组展开为成员站（伪选项本身不进检测项）；分组徽标按组内最差状态聚合。
- 测试：`test_network_check.py` 122 项、`test_ui_structure.py` 全过；offscreen 实测 73 行（71 站+2 分组）、分组展开 34 站、全选 71 站。

### FC2偶发「未进入影片详情页」：单次毛刺内部重打+报错带页面指纹

- 根因：`Fc2Crawler._run` 单次 `get_text` 后即用 `isDetailPage`（`items_article_wrapper` + `userInfo` 双标记）定论；代理抖动/截断偶发回 200 非详情页时直接抛光秃秃的「未进入影片详情页」，网络检测两次45s/60s都在问同一毛刺，无从判断是真删号还是单次抖动。
- 修复：非详情页且非确诊下架（`isNotFoundPage` 仍首轮即定论，不浪费重打）时等待 2s 后原地址重打一次，恢复即走正常解析；仍失败才抛错，且错误携带页面指纹（`describe_fc2_page`：标题/正文长度/`wrapper`·`userInfo`有无/Cloudflare·代理错误页提示），口径沿用 `crawlers.base.base._page_fingerprint`。该串不含确定性标记，探测仍走瞬时重试，两档后终局如实带出指纹。
- 测试：`tests/crawlers/test_fc2.py` 新增持续非详情页（2 次请求、报错含指纹）/单次毛刺自愈/下架页不重试/拦截页提示用例。

### Hbox年龄门壳确诊：门壳首轮即定论，不再无脑重打+模糊报换节点

- 根因（2026-11-08 实测确诊）：用户 Hbox 行 200 三连空壳，`age_check_ok=true` 带上后直连实测 200/114KB 含作品 JSON，机制本身没坏；无 Cookie 实测 302→`/age_check`，门页是约 4KB 的 Next.js SPA 空壳（无 title、无一句日文、无链接/表单，唯一信号是`__NEXT_DATA__`里的`"page":"/age_check"`与落地 URL）。用户命中的正是该门壳=年龄验证未通过（Cookie 未生效），不是 IP 封禁（Hbox 无封禁页形态、同代理其余站全通）、不是站点挂、不是番号下架。
- 统一模块补盲：`AGE_GATE_MARKERS`新增`page":"/age_check`+`/age_check?redirect=`（门页独有，真详情页不含）；新增`is_hbox_age_gate_shell(text,final_url)`（落地 URL 含`/age_check`或命中上两标记）；门页无可点成人链接（18+是 JS 按钮写 Cookie），`extract_adult_entry_url`返回 None 属预期，Cookie 是唯一入口。
- 连通性确诊+省重试：`_classify_http_result`的 HBOX 分支先认门壳→WARNING「年龄验证未通过：详情页被跳到/age_check（age_check_ok Cookie 未生效），请检查代理是否透传 Cookie，仍不行再更换节点后重试」（含「年龄验证」，确定性首轮即定论）；`_retry_hbox_empty_shell`首响/重试命中门壳即停（省 2 个无用请求），只有认不出的非门壳（截断/抖动）才保留 2 次重试与原「多次重试」文案。
- 真实刮削同口径：`HboxCrawler._fetch_detail`循环内先认门壳→直接抛「Hbox 年龄验证未通过……」（探测经`_probe_crawler_by_run`原样带出，确定性首轮即定论）；非门壳保持 3 次重试与原错误。
- 测试：`test_age_gate.py`新增门壳识别/无入口/Cookie 唯一入口/确定性判定用例；`test_hbox.py`新增门壳直抛（仅 1 次请求）用例；`test_network_check.py`的门壳判定用例改断为「年龄验证」，新增连通性门壳不重试（calls==1）用例；旧`<html>age_check</html>`非门壳用例行为不变。

### 刮削字段表：逐站审计修正4个字段旗+2条番号级链接

- 71 站 × 13 字段全量对照代码审计：DMM_API 简介（`dmm_api.py:316-317` 字面空串）、HEYZO 系列/详情图（`uncensored/base.py:485,491` 字面空）、LibreFanza 系列（`get_series` 恒空）4 格由 ✅ 改 ❌，以 `_SITE_FIELD_OFF` 精确扣除表实现（带 file:line 证据注释）；JavFree 简介有 blockquote 解析，维持 ✅。
- 番号级链接实测修正 2 条：Faleno 含未编码空格（InvalidURL，加 `quote` 编码）、Xcity `/result/` 在默认 host 404（改用同文件 200 的 `/api/search`）；FC2 全站 `/article/` 404 系本机网络环境问题、pattern 与代码一致，不动。
- 测试：`tests/test_site_fields_export.py` 新增 4❌+JavFree✅ 锁定断言，Xcity/Faleno 链接断言同步；35 项全过。

### 设置-高级「导出字段」审计修复：补扩展名+防重入+空目录回退

- 漏洞/错误：`export_site_fields_xlsx` 不补 `.xlsx`，非原生保存对话框（或用户删掉扩展名）会写出无扩展名文件；在导出（含 0.4s 静态收集）跑 GUI 线程期间连击会弹出两个保存对话框、第二次悄悄覆盖第一次；视频刮削目录为空串时保存对话框默认路径落到 CWD。
- 修复：后端统一落到 `.xlsx`（无后缀追加、错后缀替换、`.XLSX` 大小写保留）；UI 加 `_exporting_site_fields` 防重入标志（try/finally 必复位）；空目录回退到用户 home。
- 测试：`tests/test_site_fields_export.py` 新增扩展名归一化用例（无后缀/大写/错后缀）；5 项全过，`ruff`/`mypy` 全绿。

## 2026-11-07

### 刮削字段表导出：文件名带时分秒+列宽更新+隐藏空白列

- 文件名改为 `刮削字段表 YYYY-MM-DD HH-MM-SS.xlsx`（`default_export_filename`，时分秒用短横线，Windows 文件名禁用冒号）。
- 列宽（Excel 显示值）：网站 17.88、番号 24、链接地址 45，其余 13 列（性质/女演员/…/发行）8.22；写入值仍 +0.78 补偿缩水。
- 数据区之外（Q 列起至 XFD）的空白列整段隐藏，用户只看到 A-P 共 16 列。
- 测试：`tests/test_site_fields_export.py` 列宽断言同步新值，新增 Q 列隐藏段覆盖到 XFD 断言与文件名正则断言；35 项全过。

### 18+年龄门统一模块+MGStage探测复用真实抓取路径（年龄确认页首轮即定论）

- 根因：MGStage真实刮削经`_fetch_search/_get_page_text`（adcCookie+命中即点「はい（アダルトへ）」），但网络检测刮削探测走raw`client.request`+`_parse_search_page`，兜底永远走不到；adc失效即抛「adcCookie未生效」，且该串不在确定性标记内，被当瞬时故障白等45s/60s两档。
- 新增`mdcx/crawlers/base/age_gate.py`：五站成人Cookie常量+`is_age_gate_page`/`extract_adult_entry_url`/`follow_adult_entry`（一律选18+/成人入口，绝不进剧场版/未成年分支）；MGStage旧私有判定改为模块别名，Hbox/DMM/GetchuDL/JavBus的Cookie同源，Getchu主站「すすむ」同口径，JavBus的POST确认+验证码层保留站内实现。
- 探测改走真实路径：带`_fetch_search`的爬虫经`asyncio.wait_for(crawler._fetch_search)`探测（超时仍报「刮削探测超时」保阶梯语义），无该方法的最小替身回退raw请求；年龄确认页系特征（年龄确认页/年龄认证/年龄验证/adcCookie/AgeVerification，含JavBus验证码层）列入确定性结论，首轮即定论；MGStage年龄门报错改为「自动点选成人入口后仍被拦截，请更换节点后重试」。
- 测试：新增`tests/crawlers/test_age_gate.py`（三站判定/成人入口二选一/Cookie同源/点选跟随/探测走`_fetch_search`/确定性判定）；`test_mgstage.py`回归通过；`test_network_check.py`的7mmtv真爬虫用例补`get_text`（真实客户端本就有，旧raw探测用例不受影响）。

### Getchu 探测不再撞 DL 搜索 403（探测改打详情页直连 + 403 首轮即定论）

- 根因（2026-11-07 实测）：`dl.getchu.com/search/search_list.php` 被站方全网段封锁，任意参数/会话/Referer 均回空体 HTTP 403（无 cf-ray，非 Cloudflare 挑战）；同站首页·详情页·`/search/circle.php`·`ranking.php` 均 200，`getchu.com` 主站搜索/详情页正常。旧探测用 `probe_number=AIV` 走真实刮削，主站搜索一抖动就回退撞上必 403 的 DL 接口，白等 45s/60s 两档后报「站点无效」。
- 探测改打已知 AIV 详情页直连：GETCHU 检测项新增 `probe_url=https://www.getchu.com/item/1300711/?gc=gc`（JavLibrary/Hbox 同模式：跳过搜索、走 appoint_url 真实刮削），不再依赖主站搜索结果数与已死的 DL 搜索接口。
- `HTTP 403` 列入探测确定性结论：源站明确拒绝，同出口 IP 重试只是把同一次拒绝再问一遍，首轮即定论（CF 挑战类 403 已由「被 Cloudflare 拦截」覆盖，不受影响）。
- DL 关键词搜索撞 403 时报错直说：`getchu_dl` 明确提示「DL站搜索接口被站方拦截……DL作品请用 DLID/ITEM 编号或详情页URL直刮」（详情页直连正常），不再是笼统「请求错误」。
- 测试：`test_getchu.py` 新增 DL 搜索 403 文案用例；`test_network_check.py` 新增 GETCHU 检测项 `probe_url` 用例，403 终局用例改用 502 做瞬时错误（403 已走不到两档）；`test_network_check_official_probe.py` 确定性列表新增 DL 搜索 403 用例。

### Hbox 间歇性空壳自动重试（连通性/探测/刮削三层）

- 连通性 200 空壳（无 `gtmSetItemList` 的 age_check 壳）原地址自动再打至多 2 次（间隔 1s/2s），命中作品 JSON 即判 OK；打满仍是空壳才判 WARNING，文案改为「详情页多次重试后仍未返回作品数据……」，不再让用户为单次抖动手动换节点重测。
- 刮削探测对 Hbox 网开一面：`_is_transient_probe_result` 新增站点参数，Hbox 的「详情页未找到作品数据」「没有获取到作品标题」视为瞬时性、走满 45s/60s 两档（其它站仍首探即定论）；终局如实报「均失败，<根因>」。
- 真实刮削同补：`HboxCrawler._fetch_detail` 覆写为空壳重试（共 3 次，命中 `gtmSetItemList` 即停），打满仍是空壳才交由解析层报原错误；年龄确认 Cookie 发送逻辑不变。
- 测试：`test_network_check.py` 新增空壳重试转 OK / 三连空壳仍 WARNING（3 次请求、文案含多次重试）用例，Hbox 探测用例同步为两档重试终局「均失败」；`tests/crawlers/test_hbox.py` 新增详情页首空壳后成功 / 三连空壳保原错误用例。

### 存量超时配置自动升级 30s → 45s；JavLibrary 真实刮削只走 CN

- 存量配置自动升级：加载时 `timeout` 恰好等于旧出厂值 30 的自动改为 45（用户手动改过的值原样保留），独立标记 `request_timeout_45_migrated` 保证只跑一次，`config_version` 保持 2；迁移警告带 `[迁移]` 前缀。
- JavLibrary 真实刮削只走 CN：CN 与 JP 是同一份数据的不同语言版，`_run` 不再串行打 JP 详情页（字段配了繁中偏好时走 TW，其余一律 CN）；指定网址的非 CN 语言段自动换成目标语言段。`probe_only` 标记随之删除（探测与真实已同路径）。`originaltitle`/`originalplot` 取 CN 页标题/简介。
- 测试：新增 `tests/test_request_timeout_migration.py`（旧值升级/手改保留/幂等），JavLibrary 用例改写为 CN 单语（搜索 + CN 详情各一次）。

### 超时默认 30s → 45s；JavLibrary 探测只打 CN 详情页

- 软件设置-网络-超时时间默认由 30s 改为 45s：进度条上限同步拉到 45（范围 3~45），出厂模板与配置默认值同步；存量配置保持原值不变。
- JavLibrary 刮削探测不再串行打 JP 详情页：`CrawlerInput` 新增 `probe_only` 标记（`kw_only`，`CrawlTask` 继承不受影响），网络检测探测时置位，`_run` 置位且有指定探测页时跳过 JP、只打 CN 详情页——一次探测少一次串行请求，慢代理下省约 20s。真实刮削（指定网址）仍走 JP+CN 双语，保证 `originaltitle` 为日文原版。
- 测试：新增探测单请求用例（探测 1 次 / 真实 2 次），`test_network_check.py` 首轮文案同步 45s；文档 `Configuration.md` 默认值同步。

### 刮削探测超时阶梯 30s/45s → 45s/60s（慢代理下 JavLibrary 不再误报站点无效）

- 单站刮削探测轮内两档由 30s/45s 放宽到 45s/60s：JavLibrary 一次探测要串行打 JP 详情页 + CN 详情页（外加 DMM 高清封面升级），慢代理下单请求 ~20s、两次详情就 40s+，旧阶梯两档吃满后误报「站点无效」。连通性检测本身不受影响（仍是单请求短超时）。
- 同步更新注释与展示文案（`SCRAPE_PROBE_ATTEMPT_TIMEOUTS`、`scrape_probe_ladder_text()` 自动输出 `45s/60s`）；历史 Changelog 条目里的旧阶梯数字不动。
- 测试：`test_network_check.py` 阶梯断言（45.0/60.0、单档回退、展示文本）与「均超时/均失败」终局文案同步，`test_network_check_official_probe.py` 同步。

### JavDB / JavLibrary 双站合并（网页版与 API/APP 通道二合一）

- 同一站点只留一个入口：`JavDB` 网页版逻辑删除，原 `JavDB_API`（javdb580/573/574/575 多镜像轮询 + 全走代理判定）改名接管 `JavDB`；`JavLibrary` 网页版逻辑删除，原 `Javlibrary_APP`（zlibz.com 地址图认图 + 默认中文页 /cn）改名接管 `JavLibrary`。`JavDB_APP`（移动端 API 通道）保持不动。
- 存量配置自动归一：旧 `JavDB_API`/`Javlibrary·镜像`/`Javlibrary_APP` 等写法经枚举 `_missing_` 别名与 `_SITE_RENAMES` 迁移继续可读；`_MIRROR_SITE_TARGETS` 删 `JavLibrary` 镜像项（单站直连）、`SITE_GROUPS` 删 JavLibrary 联动组（JavDB 组保留三站中的两站）。
- 注册站点 73→71：各类型默认名单（有码 57、无码 18、个摄 11、欧美 9、国产 9、动漫 5）与 `default_config.json`、帮助文案、提示文案同步；演员来源链 `JavDB_API`/`Javlibrary_APP` 条目并入 `JavDB`/`JavLibrary`。
- 文档同步：`docs/Scraper.md`、`docs/Features.md`、`docs/User_Guide.md`、`docs/Configuration.md`、`docs/Development.md`、`docs/MEMORY.md`、`README.md` 现状描述行与 wiki FAQ 第 15 条更新；历史 Changelog 条目不动。
- 测试：`tests/crawlers/test_javdb.py`（原 API 用例改名）、`tests/test_javlibrary.py`（原 APP 用例改名）、`test_network_check.py` 探测收敛用例改写单站、`test_site_group_linkage.py`（联动组 7→6）、`test_site_source_copy_menu.py`（71 站/57 组）、`test_site_default_urls.py`（默认地址 f101w.com/cn）等全量同步，全量测试通过。

### Hbox 探测改走固定详情页内容校验（不再误报超时）

- 连通性对 Hbox 详情页做内容校验：检测地址本身就是详情页（`/cid/709085`），200 但无 `gtmSetItemList` 作品 JSON（丢 Cookie / 节点 IP 被限制时回的 age_check 空壳）直接判 WARNING「详情页未返回作品数据，请更换代理节点后重试」，不再先报「连接正常」再让固定链接探测去撞「详情页未找到作品数据」。探测本身仍是固定链接直连（`probe_url`），从不走番号搜索（Hbox 不支持番号搜索）。
- 「详情页未找到作品数据」「没有获取到作品标题」列入确定性探测结论：首探即定论，不再按 30s/45s 白白重试两次后才报「均失败」。
- 测试：`test_network_check.py` 新增空壳判 WARNING / 正常页判 OK / 确定性首探即定论（单次调用、原文返回）三用例。

### 站点改名与官网独立站合并统一

- `AVEntertainments`→`AVEnter`（枚举值改名；旧值经 `_missing_` 别名与 `_SITE_RENAMES` 迁移继续可读，存量配置自动归一；`default_config.json`、帮助、提示、`docs/Features.md`、`docs/Scraper.md` 同步；候选区排序键（AVSOX 之后）按成员引用不受影响）。
- `MyWife`→`Official·MyWife`（与 Dahlia/Faleno/Prestige/MGStage 同口径的 Official 独立站）：网络页「当前网站」下拉新增 `Official·MyWife` 行（地址仍是 mywife.cc，全表 A-Z 排序）、原 `MyWife` 行消失；番号前缀表新增 `MYWIFE` 直锁（`MYWIFE-xxxx` 与 `MyWife No.1230` 双通道同归本站，共 322 个前缀）；存量 `website_single=MyWife` 偏好由迁移收拢到 `Official` 聚合。
- Dahlia/Faleno/Prestige/MGStage/MyWife 并入 `OFFICIAL_YOUMA_SITES`（29→34）：与其它官网站同等对待，可用网站聚合行、官方默认名单、有码默认名单、禁用分组、迁移分组各处不再单独并列五站；`scripts/cover_backfill.py` 封面候选优先级去掉单列的 MGSTAGE（随元组走，顺序以元组为准）。
- `Official·censored` 改回 `Official`（枚举值级别，2026-11-07 当日改回；短暂存在过的旧值仍可解析并由迁移归一，收拢标记升为 v4）：可用网站（按类型分组）与启用网站展示同步改回；`default_config.json` 20 处同步。
- 测试：`test_official_aggregate`、`test_official_disabled_scope`、`test_official_uncensored_split_migration`（v4 标记/聚合名/改名归一）、`test_site_source_type_groups`、`test_website_single_official_rows`（29 spec 站 + 5 并入站分组断言）、`test_ui_structure`、`test_site_source_copy_menu`、`test_site_combo_tooltips`、`test_config_conversion`、`test_file_crawler_runtime`、`test_cover_backfill`、`test_mywife`、`test_review_regressions` 等全量同步。

### MyWife 并入 Official·censored 有码官网组与聚合改名

- `Website.OFFICIAL` 值由 `Official` 改为 `Official·censored`：旧值经枚举 `_missing_` 别名与 `_SITE_RENAMES` 迁移继续可读，存量配置自动归一；`resources/config/default_config.json` 20 处同步；可用网站（按类型分组）与启用网站展示同步新名。
- MyWife 并入有码官网组：`OFFICIAL_SITES` 38→39 站（有码 33→34 = 29 独立站 + Dahlia/Faleno/Prestige/MGStage 四个改名站 + MyWife，无码仍 5 站）；`TYPE_DEFAULT_SITES[YOUMA]` 加入 MyWife，能力文案为「有码：官方/有码」；73 家注册站点至此全部分组归属，无标题末组清空。
- 路由与其它官网同逻辑：`resolve_official_aggregate_site` 首查 mywife 文本（`MyWife No.1230` 直调 MyWife 单站），`classify_scrape_task` 中 mywife 路径/番号归属 OFFICIAL 类型并锁定 MyWife；指定网站 `Official·censored` 聚合按番号前缀路由到 39 站之一，无命中前缀回退 39 站并发。
- 删除软件设置-刮削网站-类型刮削网站 MyWifes 行：`label_322`/`label_323` 及块间 spacer 移除，锁定类型两行上移（19/20→17/18），声明几何回收 57px（`layoutWidget_6` 619→562、`groupBox_80` 689→632、`groupBox_35` y 1088→1031、content 2218→2161，底部留白仍 130），`MDCx.py` 由 pyuic6 重编译（同步测试通过）。
- 指定网站下拉：39 家官网单站（38 家 `Official·` + MyWife）合并为一行 `Official·censored`，网络页「当前网站」仍保留 39 单站；存量 `website_single=MyWife` 由迁移收拢到聚合（`official_aggregate_collapse_migrated` 升为 v3，旧 `Official` 值同样归一，MyWife 番号仍按前缀自动路由可达）。
- 禁用名单 censored 组定义加入 MyWife（34/5 全量展开，旧 `Official` 值继续整组生效）；官方字段重置/字段行存 39 单站注释同步。
- 使用说明/提示/文档同步：帮助有码·无码名单改为收拢态聚合形态、官方网站段改为 34 站（含 MyWife 番号规则注）、MyWifes 行删除；`tips.py` 有码行改为 34 家官网（含 MyWife）、官方路由前缀 322 个（含 `MyWife No.1230`）；`docs/Features.md` 同步（有码组 59 站、34 站官网、322 前缀、八个分组标题）。
- 测试：`test_type_site_scrape_rows`（19 行表/双 spacer/几何/间隙）、`test_website_single_official_rows`（39 站/聚合行/徽标）、`test_site_combo_tooltips`（MyWife 新文案）、`test_site_source_type_groups`（聚合 34 站/单体新名/官方归属）、`test_site_source_copy_menu`（有码 59 站）、`test_official_aggregate`/`test_official_disabled_scope`/`test_official_uncensored_split_migration`（39/34 计数/v3 标记）、`test_ui_structure`、`test_config_conversion`、`test_file_crawler_runtime` 全量同步；另修复两处历史红灯（聚合入口无爬虫属设计、`validate_crawler_registry` 以 `_AGGREGATE_WEBSITES` 豁免；品牌站可用性用例按展开态断言收拢默认值）。

### 公开仓打包失败：workflow 不同步 + close.bat 去强制提权

- 线上打包失败（`Copy-Item scripts\windows\start-trawl.bat` 不存在）：开发仓 61e7ab1 早已改名，但公开仓跑的是自己那份旧 workflow，而 `sync-trawl-scripts.yml` 只同步 `scripts/windows/**` 不管 workflow 文件——实测公开仓 main 仍是旧版（还引用已删除的 start-trawl.bat/vbs）。本地没错，错的是公开仓掉队。
- 新增 `.github/workflows/sync-package-workflow.yml`：push 触及 `package-trawl.yml` 或手动 dispatch 时，把该单个文件同步到公开仓（同并发组防推送顶掉）。注意：历史欠账需先去 Dev Actions 手动跑一次该 workflow（选 main），之后自动跟随。
- `trawl-close.bat` 去掉启动时强制提权：自己的进程自己就能关（无管理员实测全 OK、exit 0，不弹 UAC）；只有端口确实没清掉且当前非管理员时，才在最后请求提权再跑一次。残留的 start-trawl 注释顺手改名。
- `trawl-start.vbs` 注释/MsgBox 里残留的 start-trawl 字样同步改名（执行路径早就是 trawl-start.bat）。

### TRAWL 便携包 GeoIP 数据库随包（启动不再在线下载）

- 根因：包内 `.cache/camoufox/GeoLite2-City.mmdb` 缺失（仅留 1MB 中断残留），`camoufox-js` 在启动时走 `api.github.com` 查 `P3TERX/GeoLite.mmdb` 的 release，匿名配额被限流（403）后浏览器池初始化失败（`startup failed: Failed to fetch releases ...`）；直链下载（`github.com/.../latest/download/...`）不走 API，不受影响。
- 打包工作流（`package-trawl.yml`）：GeoIP 改用 `curl` 断点续传 + 重试（45MB 下限，与 Dockerfile 同口径），失败或不完整直接中止打包；打进包前校验库完整，并剔除 `*.download` 残留。
- `scripts/windows/trawl-start.bat`：启动前预检库存在（支持放包根目录/`geoip/` 手动兜底），缺失时中文报错并给出下载链接；`USAGE.md` 补 FAQ。

### TRAWL 便携包一键彻底删除（目录“文件删光却删不掉”的终结）

- 根因（2026-11-07 实测）：空目录删不掉报“另一个程序正在使用”（`rd` exit 32），`handle64` 查到 7 个本机 MCP 服务进程 + 资源管理器各持该目录句柄；杀掉 MCP 进程后 `rd` 即成功。另实测明确两条边界：PowerShell/CMD 光 `cd` 进去不断句柄删得掉，删不掉的都是真文件句柄（跑着的进程、资源管理器已开文件夹窗口）；`node_modules` 超 260 字符长路径资源管理器删不动。
- 新增 `scripts/windows/trawl-uninstall.bat`（已进打包 zip）：复制自身到 TEMP 后脱离启动 worker 再立刻退出（实测：子进程结束后父进程再读原文件必报“找不到指定路径”，所以启动器绝不等 worker；另 `cmd /c "prog" args "more"` 多引号会被剥掉首尾引号，worker 启动必须用 `cmd /d /s /c ""prog" args"` 外层包一对引号；新文件必须 CRLF，LF 换行会被 CMD 拼行乱执行）。
- worker 四步：停进程（trawl 的 bun 按命令行过滤、`camoufox.exe` 按名、`plugin-container/firefox` 按命令行含 camoufox 过滤以免误杀用户 Firefox、Redis 只认 :6380、8191/8192/6380 端口白名单兜底，逻辑全部内联不依赖 trawl-close.bat）→ attrib 去只读/隐藏/系统 → robocopy 空目录镜像压平长路径 + `rmdir /S/Q`（3 次重试）→ 仍占用则注册重启删除（需管理员），失败给中文指引。
- 沙盒实测：只读 + 728 字符深路径一次删光；独占文件句柄 + 非管理员走重试→报错→保留目录分支；TEMP 副本自删；GBK 控制台下中文注释会报几行无害的乱码错误（逻辑行全英文不受影响，真机双击走 65001 无此问题）。
- `USAGE.md` 补“删不掉/卸载”FAQ。

## 2026-11-06

### 官网站改名与单体行调序

- 三站品牌写法改名：`Official·EBody`→`Official·E-Body`、`Official·Mko`→`Official·MKO`、`Official·Mvg`→`Official·MVG`（枚举值 + 爬虫注册名 + 定位说明 + 旧配置 `_rename_site` 兼容 + `default_config.json` 模板 + 使用说明同步）；可用站点候选区与软件设置-网络-网站设置-当前网站下拉（均取自注册爬虫站点值）同步新名。
- 其它类型编辑网站弹窗：候选区 `Official·uncensored` / `Official` 两个单体行调换位置（无码在前，紧随「无码官网」聚合行之后）。
- 测试：新增品牌改名迁移用例，单体行位置用例同步新顺序。

### 八类禁用名单相互独立与候选区聚合行改名

- 禁用按八类独立存放：官方/有码/无码/个摄/欧美/国产传媒/国产短剧/动漫里番各一份名单（有码沿用 `website_disabled`，其余各有 `website_*_disabled`），在有码里禁用某站不再影响其它任何类型；旧配置迁移（`per_type_disabled_scope_migrated` 标记，`config_version` 仍为 2）把六份新名单初值复制为主名单（行为不变，之后互不影响）。
- 其它类型编辑网站弹窗：候选区聚合行 `Official`→「有码官网」（33 站）、`Official·uncensored`→「无码官网」（无码五站），其后另起 `Official` / `Official·uncensored` 两个单体行；官方网站弹窗内两组名称不变。
- 测试：`test_official_disabled_scope` 同步八域分域/独立性/迁移播种，`test_site_source_type_groups` 与 `test_official_aggregate` 同步新标题与单体行。

### pytest conftest robustness：导入期永不炸整轮 + os._exit 让路

- `tests/conftest.py` 顶层生产 `Config()` 构造加容错：失败时退化为 `None`，缺字段访问以清晰 `AttributeError` 定位到具体用例，不再让整个 run 在 collection 阶段全灭（`ERROR tests/conftest.py`，一个用例都跑不起来）。
- `pytest_sessionfinish` 的 `os._exit(0)` 增加让路条件：xdist worker（`PYTEST_XDIST_WORKER`）、coverage 生效中、`MDCX_PYTEST_NO_FORCE_EXIT=1` 时走正常退出，避免在 IDE 测试适配器/xdist/coverage 下被报成“测试进程崩溃”；普通 CLI 全绿 run 行为不变（仍绕开 Qt 析构崩溃）。
- 新增 `tests/test_conftest_robustness.py`（5 用例）钉住上述两处；`ruff format`/`ruff check` 全绿，子集回归 120 passed。

### 官方字段重置保存无效修复与三站改名

- 修官方网站字段优先级「一键重置→保存」无效：`build/normalize` 对官方类型误用聚合收拢，38 单站存成 `Official`/`Official·uncensored` 后重开被 38 名单过滤成空行；官方类型字段行一律存 38 单站不再收拢，旧配置（已存成两聚合）下次加载自动回退为 38 单站。
- 官方网站字段优先级弹窗：可用网站与各字段行一律短名显示（去 `Official·` 前缀，悬停仍点出真实站点值；仅展示层，存盘与拖拽仍用真实值）。
- 三站改名：`Official·Hhh`→`Official·HHH`、`Official·ToSatsu`→`Official·To-satsu`、`Official·V`→`Official·V-AV`（枚举值 + 爬虫 `display_name` + 旧配置 `_rename_site` 兼容 + `default_config.json` 模板同步）；网络页「当前网站」下拉取值自注册爬虫站点值同步更新。

### 禁用名单按类型分域与 Official 整组禁用

- 禁用按类型分域：官方网站类型读写 `website_official_disabled`，其余类型共用 `website_disabled`，两域互不影响；在有码里禁用 Official 不再影响官方网站弹窗，反之亦然；旧配置迁移（`official_disabled_scope_migrated` 标记，`config_version` 仍为 2）把官方相关值复制一份到官方名单，主名单聚合值原位展开为 33/5 全量（含 Dahlia/Faleno/Prestige/MGStage，29 全量同样补齐到 33）。
- 非官方类型弹窗里右键禁用/启用聚合行（`Official`/`Official·uncensored`）即整组 33/5 站同步开关（含四个改名站）；启用列表里聚合单体在组内全被禁用时变灰；官方网站弹窗仍按单站禁用。
- 测试：`test_official_uncensored_split_migration` 同步迁移终态（38 项加官方名单复制），新增 `test_official_disabled_scope`（成员展开/聚合/分域/迁移补齐）。

### 字段优先级与启用网站的官网聚合为单个 Official

- 字段优先级弹窗（官方网站除外）：各行与可用网站里的官网收拢为单个 `Official`（有码 33 站）/ `Official·uncensored`（无码 5 站）；`Official` 只是显示名，实际刮削按组内站点值 A-Z 逐站尝试（配置里存聚合、请求时展开，禁用某家官网仍按单站过滤生效）。
- 有码编辑网站弹窗的启用网站：33 家官网合并为单个 `Official`，不再出现 30 多个同名行；其它类型同理（无码为单个 `Official·uncensored`）；缺站（摘掉过某站）不收拢，原样保留。
- 新增 `Website.OFFICIAL_UNCENSORED` 聚合枚举；旧配置迁移（`official_aggregate_collapse_migrated` 标记，`config_version` 仍为 2）：官网单站齐套即收拢为聚合，官网源与官方字段优先级保留单站，禁用名单保留单站。
- 测试：`test_official_aggregate` 新增展开/收拢/缺站保留/迁移对齐用例，`test_official_uncensored_split_migration` 同步收拢后终态。

### 官网分组改名与非官网弹窗去官方组

- 编辑官方网站源：候选区两组改名 `Official` →「有码官网」（33 有码站）、`Official·uncensored` →「无码官网」（无码五站），成员与启用网站仍短名显示，加入/复制逻辑不变。
- 其它类型编辑网站弹窗：候选区删掉「官方」组（类型标题剩有码/无码/个摄/欧美/传媒/短剧/动漫七组 + 聚合行 `Official`/`Official·uncensored`）；各组默认名单不动，有码组仍含 33 家官网单站。
- 测试：`test_official_aggregate` 新增两组新标题与去官方组断言。

### 指定网站 Official 聚合与官网展示统一

- 软件设置 → 刮削网站 → 网站偏好 → 指定网站：38 个 `Official·` 单站合并为一行 `Official`（33 有码 + 5 无码全含在内），下拉不再挤满官网；选中 `Official` 时按番号前缀自动路由到各单站刮削（品牌锁 → 有码 29 站 + Prestige → 无码 5 站），无命中前缀时回退 38 站多站并发兜底。网络页「当前网站」仍保留 38 单站（逐站检测/自定义网址按站独立）。
- 新增 `Website.OFFICIAL = "Official"` 聚合入口（仅 `website_single` 可取，不注册爬虫、不进类型默认名单、不参与网络检测与字段优先级）；旧配置 `website_single=Official` 原样保留，不再落到 `Official·S1`。
- 编辑官方网站源：候选区只有 `Official`（33 站）与 `Official·uncensored`（5 站）两组，不再摆「官方/有码/无码…」八个类型标题；成员与启用网站一律短名显示（去 `Official·` 前缀，仅展示层，枚举值与存盘不变）。
- 类型刮削网站 → 编辑网站 → 启用网站：33 有码站统一显示为 `Official`、5 无码站统一显示为 `Official·uncensored`（仅展示名，`UserRole` 仍存真实值，悬停点出真实站点，实际刮削仍按真实站点值 A-Z 顺序）。
- 测试：`test_website_single_official_rows`（指定聚合一行/网络页 38 单站/徽标按站独立）、`test_official_uncensored_split_migration`（`website_single` 保留聚合）、`test_site_source_copy_menu`（八组标题）、新增 `test_official_aggregate`（前缀路由/两组短名/启用统一展示）同步。

### Official 四站改名与可用网站聚合展示

- `Prestige`/`Faleno`/`Dahlia`/`MGStage` 改名 `Official·Prestige`/`Official·Faleno`/`Official·Dahlia`/`Official·MGStage`（枚举值 + 爬虫 `display_name` + 旧配置 `_rename_site` 兼容 + `default_config.json` 模板同步）；有码 `Official·` 系共 33 站。
- 「编辑网站」可用网站候选区：七个分组标题之后钉住两行聚合行 `Official`（33 家有码官网）、`Official·uncensored`（5 家无码官网），38 个成员不再 A-Z 单列；拖拽/双击/右键/全部添加均展开为成员，不引入伪站点，路由、检测、启用/禁用仍按站独立。
- 测试：`test_site_source_type_groups`/`test_site_source_copy_menu`/`test_site_group_linkage`/`test_site_list_editor_reorder`/`test_ui_structure` 同步；`Features`、`Scraper`、`MEMORY`、`Configuration`、关于页与 `tips.py` 文案同步。

### Official 有码本部拆成 29 个独立官网站

- 删 `OfficialCrawler` 统一路由器与 `Website.OFFICIAL`：29 家有码片商官网各立 `Website`（`Official·S1`…`Official·Hhh`）、各立爬虫（`crawlers/official_sites.py`，通用 `_OfficialSiteCrawler` + 29 薄子类）、各有官网基址与探测番号（如 S1 `SSNI-647`、Madonna `JUL-001`、Prestige 沿用既有 `Prestige` 站 `ABW-130`）。
- 路由：321 个番号前缀在 `classify_scrape_task` 直接锁定对应官网单站（与 Dahlia/Faleno 同语义，失败无回退）；prestige 系 106 前缀锁定既有 `Prestige` 站；前缀表与旧 `ManualConfig.OFFICIAL` 逐字一致（`JUSD` 归 Madonna、`JUFD`/`JFB` 归 Fitch，与旧表后写覆盖语义一致）。
- 旧配置迁移（`official_youma_split_migrated` 标记，`config_version` 仍为 2）：YOUMA 名单/全局字段优先级/type-youma 字段/`website_disabled` 里的 `Official` 原位展开成 29 站；`website_single=Official` 落到 `Official·S1`。
- 网络检测：29 站各占一行（基址 + 各自探测番号 + CF Bypass），`merge_site_check_cache` 的 `Official` 聚合特例删除；`1pondo.tv`/`heyzo.com`/`prestige-av.com` 三站维持临时直通（`TEMP_DISABLED_NETWORK_CHECK_SITES`）。
- 测试：`test_official.py` 重写（S1 实测 + 路由 + 注册表），迁移测试补 29 展开/幂等，`test_network_check`/`test_site_default_urls`/`test_ui_structure`/`test_config_conversion` 等同步；`Features`、`Scraper`（73 站）、`Development`、`MEMORY` 与关于页文案同步。

### JavDB 三站动漫条目判动漫（AMCP-261）

- 动漫在 JavDB 与 Jav321 的刮削流程与成人影片一致（番号搜索到详情页再取各字段），差别只在 `mosaic` 判定：JavDB 三站（`javdb`/`javdb_api`/`javdb_app`）`post_process` 以前只分有码/无码，動漫条目（如 `AMCP-261`，JavDB 地址 `/v/kKJ4OJ`，類別含 `Anime` 标签；Jav321 地址 `/video/h_1261amcp00261`）会被标成有码走错组。
- 新增共享判定 `base/shared_fields.is_anime_tags()`（類別/Tags 含 `Anime`/`動漫`/`动漫`/`アニメ`/`里番`即动漫），三站 `post_process` 里优先判定：命中则 `mosaic` 返回「动漫」走动漫组（JavDB 详情字段：番号 `AMCP-261`、日期、时长 20 分钟、片商 `surviveMORE`、系列 `The Motion Anime`、标题、extrafanart 剧照；Jav321 详情字段：メーカー `surviveMORE`、品番 `amcp-261`、配信開始日、DMM 图床剧照——两边字段解析不动，只改 `mosaic`）。
- 三站 `description` 由「综合：有码+无码」改为「综合：有码+无码+动漫」（悬停提示照旧隐藏「动漫」只显示类型名单，不受影响）。
- 测试：三站各新增动漫 `post_process` 单测 + `description` 断言（`test_javdb.py` 另含 `is_anime_tags` 单测）；`Features`、`Scraper` 三站说明列同步。

### Jav321 进动漫组与有码组排序调整

- 有码组默认顺序调整：`Jav321` 排到 `JavBus` 之后、`Hbox` 排到 `JavFree` 之后（`models.TYPE_DEFAULT_SITES`、`default_config.json`、`Features` 默认名单与 `test_site_source_type_groups` 期望名单同步）。
- `Jav321` 加入动漫组：动漫组默认名单变为 `Getchu、Hbox、Jav321、JavDB、JavDB_API、JavDB_APP`（5→6 站），`description` 由「有码：仅限有码」改为「综合：有码+动漫」；详情页 `/video/h_xxx` 或 DMM 图床 `digital/video/h_xxx`（如 `h_1261amcp00261` 动漫页封面 `ps.jpg`/横版 `pl.jpg`/剧照 `jp-1.jpg`、`jp-2.jpg`）即判动漫，`mosaic` 返回「动漫」走动漫组，其余仍返回「有码」。
- 测试：`tests/crawlers/test_jav321.py` 新增动漫判定与动漫详情单测；动漫组复制计数 5→6 同步（`test_site_source_copy_menu`）；`Features`、`Scraper` 动漫名单与说明同步。

### 新增 Hbox 刮削站点（hbox.jp）

- 新增 `mdcx/crawlers/hbox.py`：18 岁验证用 Cookie `age_check_ok=true` 直通；站内搜索走 `/search_result?q_array[]=<关键词>`（`q` 参数被服务端忽略，番号搜不到——成人影片用标题关键词搜，最多 3 个候选）；列表锚点 `/cid/` 按标题相似度取前 5；详情页从 `gtmSetItemList(item_list_name, 0, {...})` 内嵌 JSON 取全字段。
- 字段映射：発売日=发行日期、配信開始日=配信日期、メーカー（label_name）=制作商、maker_name=发行商、シリーズ=系列、女優/男優（casts）=演员、監督=导演、時間（秒→时:分:秒→分钟）=时长、評価（review_avg.score）=评分、タグ=标签、作品紹介（description）=简介；番号取内嵌 `product_number`（页面展示缺番号字段）；封面 `cover.jpg`、剧照 `gallery_N.jpg`（image3 域名，绝对路径拼接）；全站搜索返回混合分类，movie→有码、anime 成人向→里番。
- 成人影片无番号可查：本站搜索不支持番号，输入番号时用文件名标题候选搜全站，详情页 `product_number` 与输入番号不一致时丢弃；动漫/里番直接用标题搜。
- 接入：新增 `Website.HBOX` 并注册爬虫；有码组与动漫组默认追加到末尾，`proxy_sites` 默认追加 `hbox.jp`，`manual.WEB_DIC` 增加 `hbox`，`default_config.json` 有码/动漫默认加入 `Hbox`；探测番号 `GS-2136`（番号搜索恒返回通用列表，网络检测走回退路径告警，属已知限制）。
- 测试：新增 `tests/crawlers/test_hbox.py`（详情解析、番号不一致丢弃、空搜索、动漫分类、注册与 Cookie 单测）；有码组 29→30、动漫组 4→5 等计数同步。
- 文档/UI同步：`Features`、`Scraper`、`Development`、`Configuration`、`User_Guide`、`MEMORY` 与关于页有码/动漫名单；版本号保持 `v3.0`，`LOCAL_VERSION` 不变。

### 新增 Jav321 刮削站点（jav321.com）

- 新增 `mdcx/crawlers/jav321.py`：站内搜索走 `POST /search`（字段 `sn`）；精确番号直回详情页，非精确命中按 `/video/<cid>` 反查番号后跟进详情；详情页判定要求 `h3` 标题块与品番行同时存在。
- 字段映射：出演者=演员、メーカー=制作商、品番=番号、配信開始日=日期；封面/剧照走 DMM（`ps.jpg`/`pl.jpg`/`jp-N.jpg`），预告走 DMM 预告链；探测番号 `SNOS-484`。
- 接入：新增 `Website.JAV321` 并注册爬虫；有码组默认追加到末尾，`proxy_sites` 默认追加 `jav321.com`，`manual.WEB_DIC` 增加 `jav321`，`default_config.json` 有码默认加入 `Jav321`。
- 测试：新增 `tests/crawlers/test_jav321.py`（精确直达、列表跟进、指定 URL、空结果、注册与解析单测）；DMM 升级覆盖增至 11 站，有码组 28→29、复制列表 43→44 等计数同步。
- 文档/UI同步：`Features`、`Scraper`、`Development`、`Configuration`、`User_Guide`、`MEMORY` 与关于页有码名单；版本号保持 `v3.0`，`LOCAL_VERSION` 不变。

### 下线 AVSEX 站（avsex.cc 失联）

- 删除爬虫 `mdcx/crawlers/avsex.py` 及其测试 `tests/crawlers/test_avsex.py`；移除 `crawlers/__init__.py` 注册、`Website.AVSEX` 枚举、`enums._missing_` / `migrations._SITE_RENAMES` 旧值映射、`manual.WEB_DIC` 的 `9sex`/`avsex` 入口。
- 默认配置清掉该站：`models.proxy_sites` 默认代理名单去掉 `avsex.cc`（36 域）；`v1.py` 有码/素人/中文标题/中文简介/海报/剧照排除/评分/导演/系列/工作室/发行商 11 处默认值去掉 `avsex`（`studio_website_exclude` 清空）。
- 素人番号前缀剥离只保留 MGStage 特例（`file_crawler.py`、`file.py` 注释同步）；`tips.py` 有码/无码/国产三行文案去掉该站；`site_priority_dialog.py` 三处注释同步。
- 存量旧配置里的 `avsex` 站点值按未知站点过滤（与其它已下线站点同规则），不再单独迁移。
- 测试同步：`test_dmm_upgrade_coverage` 推广名单 11→10 站；`test_cf_proxy_routing` 默认名单断言改用 `getchu.com`；`test_cf_transport_fallback` 通用 URL 改用 `example.com`；`test_network_check` 示例改用 `avsox.click`；`test_site_combo_tooltips` 去掉 AVSEX 断言；`test_site_list_normalize` 示例改用 `AVSOX.CLICK`；`test_site_source_type_groups` 无标题组只剩 `MyWife`；`test_site_source_copy_menu` 复制列表计数 44→43 站。
- 文档同步：`Features` 站点表删行（综合/国产两组去掉该站，候选区 44→43 站）、`Scraper` 总表 38→37 站、`Development` 代理默认 37→36 域、`Configuration`/`User_Guide` 代理名单、`MEMORY` 爬虫计数 36→35。
- 版本号 `LOCAL_VERSION` 由 `20261105` 升到 `20261107`。

### 高级页：删「保存重启程序生效」、“获取视频时长”改名、新增强制校验时长

- 软件设置 → 高级 → 高级功能：删除分屏缩放行「保存重启程序生效」标签（改缩放仍需重启程序，`QT_SCALE_FACTOR` 在启动时读取）。
- 「获取视频时长」复选框改名为「补全时长字段」；生效范围明确为正常 / 分离 / 视频 / 更新 / 补全模式，整理 / 读取模式不生效。
- 分屏缩放行下拉框右侧新增「校验时长字段」复选框（默认不勾选，勾选状态写入配置文件；旧配置自动兼容）。勾选后用 OpenCV 读取视频实际时长，与刮削到的时长字段四舍五入后对比，相差超过 5 分钟则判定数据不一致：番号记入失败列表，视频及已刮削数据保留在原目录，不移动到成功输出目录。仅正常 / 分离 / 视频 / 更新 / 补全模式生效；文件名含分集命名规则识别出的分集字符时跳过比较（分集单集时长必与整部刮削时长不一致），STRM 文件不获取实际时长也不比较。
- 分屏缩放行对齐：下拉框左缘与「隐藏演员管理」严格上下对齐（隐藏演员管理位置不变），「校验时长字段」与「使用暗黑模式」严格上下对齐（使用暗黑模式位置不变）。
- 分屏缩放行下拉框右边界向左缩进、右侧与「隐藏演员管理」这几个字的右边界严格上下对齐（2026-11-06 晚再次按用户截图修正口径）：nav 行复选框会被行布局拉宽，控件框右缘远在文字右边，照控件右缘钉宽会让下拉框视觉上明显偏右；改为按样式 `SE_CheckBoxContents` 左缘 + `fontMetrics` 字宽算文字右缘，把下拉框钉成「文字右缘 − 下拉框左缘」。校验框仍在下拉框后插间隔补到暗黑竖线。
- 「校验视频时长」复选框文案改为「校验时长字段」（`tests/test_advanced_page_hint_align.py` 同步断言）。
- 测试：`tests/test_advanced_scale_combo_width.py`（新口径重写）、`tests/test_advanced_page_hint_align.py`、`tests/test_advanced_dialog_row_align.py`、`tests/test_get_video_duration.py`。

### Hbox/Jav321 探测地址修正（详情页直连 + www 主域）

- Hbox：`/search_result?q_array[]=GS-2136` 实测无内容（搜番号恒回未过滤通用列表），探测改打已知详情页 `/category/movie/av/=/cid/709085`；`probe_number` 换为该页番号 `FTHTD-227`（详情页番号交叉校验用）。
- Jav321：裸域 `https://jav321.com/video/*` 301 到首页空页（旧探测号 `SNOS-484` 报「没有获取到番号标题」），默认基址切到 `https://www.jav321.com`（`POST /search` 在 www 下 301 直达详情页）；`probe_number` 换为站内核验的 `SNOS-460`（`/video/snos00460`，2026-11-06 发行）。
- 机制：`NetworkCheckSpec` 新增 `probe_url`（设置后跳过番号搜索、用 `_run` 的 `appoint_url` 分支真实刮削探测）；Hbox 检测项地址即详情页（进 `SPECIAL_CHECK_PATHS`，自带 `age_check_ok=true` Cookie，免 302 到验证页）。
- 测试：`test_jav321.py` 重写为 SNOS-460 实测数据 + www 断言；`test_hbox.py` 探测号断言同步；`test_network_check.py` 新增 Hbox 检测项与 `probe_url` 直连探测单测。
- 文档同步：`Scraper` 探测表两行、`Features` Jav321 域名。

### JavLibrary / LibreDMM / Madouqu 刮削探测修正（详情页直连 + 新版解析兼容）

- JavLibrary：原站 `https://javlibrary.com/cn` 有 CF 墙，刮削探测 2 次 30s/45s 均超时；探测改打镜像详情页 `https://f101w.com/cn/javli6qwtu.html`（`DEFAULT_SITE_URLS[JAVLIBRARY]` 改为 `https://f101w.com`，`SPECIAL_CHECK_PATHS` 改为 `/cn/javli6qwtu.html`，`probe_url` 复用 `appoint_url` 分支跳过 `SSNI-647` 搜索直打详情页）。
- LibreDMM（现 LibreFanza）：`www` 探测 `https://www.libredmm.com/movies/IPX-535` 报「未获取到 title」——站点已换新版 LibreFanza 版式（`h1` 只剩番号、标题移到 `h2.detail-title`、封面 `div.detail-artwork`、演职员 `dl+metadata-tags`、演员 `article.card h3`），旧 xpath 全取空；`libredmm.py` 与 `shared_fields.libredmm_detail_image` 加新版兼容（旧版照常通过）。
- Madouqu：`?s=` 搜索经代理超时（探测 2 次 30s/45s 均失败），探测改打详情页 `https://madouqu.shop/video/mdx0216/`（`MADOUQU` 新增 `probe_url`）；新版主题（搜索 `article.resource-card a.cover-link`、详情 `header.entry-header h1`/`div.entry-content`/`a.category-label`）搜索与详情解析同步兼容。
- 测试：`test_libredmm` + `test_madouqu` 12 项、`test_network_check` 全量 115 项、`field_crawl_retry`/`javlibrary_app`/`custom_site_url` 55 项通过。

### LibreDMM 改名 LibreFanza（域名不变）

- 站点已更名为 LibreFanza（页面标题/站点头图；`Scraper` 站点说明列原本就写「LibreFanza，DMM/FANZA 开源镜像」）：`Website.LIBREDMM` → `Website.LIBREFANZA`，值 `"LibreDMM"` → `"LibreFanza"`；旧值经 `enums._missing_` 与 `migrations._SITE_RENAMES` 映射兼容（`LibreDMM`/`libredmm` 均可解析），域名 `libredmm.com` 不变。
- 爬虫类 `LibreDMMCrawler` → `LibreFanzaCrawler`（模块 `libredmm.py` 保留）；界面按钮「补全LibreDMM链接」→「补全LibreFanza链接」；`Features`、`Scraper`、`User_Guide`、`default_config.json`（33 处）同步；`Changelog` 历史条目保留原名。
- 测试：相关 299 项通过（含 Qt 分组联动、配置迁移、演员库工具）。

## 2026-11-05

### 新增「获取视频时长」开关（OpenCV 兜底写 NFO）

- 软件设置 → 高级新增「获取视频时长」复选框（默认不勾选，勾选状态写入配置文件；旧配置不会自动开启，取消后保存也不会被重新勾上）。
- 勾选后，所有站点都刮削不到时长时，对真实视频文件用 OpenCV 读取时长（分钟）并写入 NFO 的 `<runtime>`；PyAV / ffprobe 仅作兜底。`.strm` 只含链接、播放器/解码器无法据此取时长，明确排除。
- 仅在会写 NFO 的刮削/补全流程触发，读取/整理模式不改 NFO。
- 测试：`tests/test_get_video_duration.py`。

### ruff 版本声明自动跟随 `uv.lock`

- 新增 `scripts/sync_ruff_version.py`：以 `uv.lock` 为唯一来源，同步 `pyproject.toml`、`requirements.txt` 与 `uv.lock` 根 metadata 的 ruff 版本声明；`--check` 可只校验。
- `scripts/check.py` 启动时自动同步；检测到漂移会改写文件并以非 0 退出，提交同步结果后重跑即可。
- `tests/test_ruff_version_sync.py` 钉死三处声明一致；ruff 锁版本由 0.17.1 升到 0.17.3。
- 版本号 `LOCAL_VERSION` 由 `20261104` 升到 `20261105`（实际提交日期）。

## 2026-11-04

### 补全模式右侧「?」按钮点击无反应

- 用户反馈：软件设置 → 刮削模式 → 补全模式，右侧说明「?」按钮点了没反应，要求与其它模式一样弹出说明窗。
- 原因：`pushButton_tips_complete_mode` 只在 `init.py` 里设了图标与 tooltip，漏了 `clicked` 信号连接，`tips.py` 也没有对应槽函数；其余六个模式的按钮都接了 `_show_tips(...toolTip())`。
- `mdcx/controllers/main_window/tips.py` 新增 `pushButton_tips_complete_mode_clicked()`；`init.py` 补上 `clicked.connect(...)`。tooltip 里两处旧控件名同步为当前界面文案（「本地信息文件有链接，重新下载封面图与缩略图」「本地信息合并及策略」）。
- 测试：`tests/test_settings_mode_tips_buttons.py` 锁死七个模式说明按钮都存在于 `.ui`、都有槽函数、都在 `init.py` 里接上 `clicked`，且槽函数确实把 tooltip 交给说明弹窗。
- 版本号 `LOCAL_VERSION` 由 `20261030` 升到 `20261104`（实际提交日期）。

## 2026-10-30

### ThePornDB 站点检测改打主站首页 `https://theporndb.net/`

- 用户反馈：ThepornDB 的站点网络检测要用 `https://theporndb.net/`；打 `https://api.theporndb.net/` 会报 HTTP 404。
- 原因：API 子域**没有根路由**——`GET https://api.theporndb.net/` 本来就 404，拿它当「站点通不通」的检测地址必然误报红点。此前该站直接从「站点检测」组里跳过，检测页只剩「账号/API」组的一条 Token 项，站点本身可不可达反而看不出来。
- `mdcx/utils/theporndb_token.py` 新增 `WEB_BASE = "https://theporndb.net"`（主站基址，`TOKEN_PAGE` 由它拼出），与 `API_BASE` 各司其职。
- `mdcx/core/network_check.py::_build_site_specs()`：ThepornDB 不再整站跳过，改为产出一条「站点检测」项 `ThepornDB → https://theporndb.net`；不走 `base_url_()`／用户自定义 URL（那两者都是 API 子域），也不跑爬虫刮削探测（探测打的是 API、还要 Token）。
- `NetworkCheckSpec` 新增 `crawl_probe: bool = True`：连通后是否再用爬虫实探「能不能刮」。仅 ThepornDB 站点行置 `False`，其余站点默认行为不变；探测条件相应加 `and spec.crawl_probe`。
- 职责划分：站点行判「主站能不能上」（200 → 连接正常），接口/Token 能不能用仍由「ThePornDB Token」项（`api.theporndb.net/scenes/hash/…`）判定，两条结果都带 `site=ThepornDB`，缓存按「本轮最差」聚合回标网站设置下拉。
- 测试：`tests/test_network_check.py::test_theporndb_site_spec_probes_main_site_not_api_root`。

### ThePornDB 接口基址回到 `api.theporndb.net`（主域 `/api` 降为备用）

- 用户反馈（换了 API key 仍是同一条 403）：「一直是这样，已经换了 API key 了，正确的地址是 `https://api.theporndb.net/scenes/hash/8679fcbdd29fa735`」。
- 回滚 2026-10-29 的「API 迁到主域 `/api`」：`mdcx/utils/theporndb_token.py::API_BASE` 改为 `https://api.theporndb.net`（`HASH_PROBE_URL` / `LIST_PROBE_URL` 随之生效）；`mdcx/crawlers/theporndb.py::base_url_()`、`read_data()` 的 `real_url`、`get_real_url()` 的 `res_id_url` 一并回到子域；`mdcx/tools/actor_sources.py::_THEPORNDB_API` 同步。
- 新增 `API_BASE_FALLBACK = "https://theporndb.net/api"` 与 `with_fallback_base()` / `should_try_fallback()` / `looks_like_api_body()`：子域**连接层失败**（超时/解析不到，取不到状态码）或 **403 但响应体不是本站 JSON**（被 Cloudflare 挑战页顶掉）时，自动换主域 `/api` 重试一次；真 403 JSON、404（哈希未命中）不重试。三处共用：设置页「检测」、检测网络页「ThePornDB Token」项、爬虫 `_get_json()`。
- `appoint_url` 归一化改用 `_APPOINT_URL_RE`：`theporndb.net/x`、`www.theporndb.net/x`、`theporndb.net/api/x`、`api.theporndb.net/api/x` 四种写法统一收敛到 `https://api.theporndb.net/x`。
- 测试：`tests/test_theporndb_token.py`（基址断言、`with_fallback_base` / `should_try_fallback` / `looks_like_api_body`、子域超时与 403 挑战页两种兜底、检测页兜底）、`tests/crawlers/test_theporndb.py::test_theporndb_subdomain_dead_falls_back_to_main_domain`。
- 注：本机 `curl https://api.theporndb.net/scenes/hash/…` 实测超时（status=000），主域 `/api` 返回 401 JSON；两条路在不同网络环境下可通性不同，故保留兜底而不是单点依赖。

### 检测网络页恢复等宽表格对齐（回到 2026-10-28 之前的样式）

- 用户反馈：检测网络页的检测报告挤成一串（`200927ms代理连接正常`、`代理状态已启用`、表头「状态站点状态码耗时路由信息」连在一起），要回到 2026-10-28 之前的对齐样式。
- 原因：2026-10-28 起的「日志不留多余空格」规则在 `utils.strip_log_spaces()` 里统一执行，检测页出口 `show_net_info()` → `add_html_plain_text()` 也走了这道清洗；而这份报告的各列全靠连续空格排版（`_format_header()` 表头四列按真机实测校准的间隙、`format_result_line()` 的 `_pad_left/_pad_right` 固定列宽、`基础环境` 的 `_pad_right(…, 16)`），空格被删光后列位信息就没了。
- `mdcx/utils/__init__.py::add_html_plain_text()` 新增 `keep_spaces` 参数（默认 `False`，软件日志页行为不变）；`mdcx/controllers/main_window/net_check.py::show_net_info()` 改为 `keep_spaces=True`，检测页原样渲染。复制到剪贴板的报告本来就是原始行，不受影响。
- 测试：`tests/test_log_left_align.py::test_net_check_page_keeps_report_alignment`（表头与数据行渲染后空格一个不少，同一段文字走日志页仍被清洗）。
- 版本号 `LOCAL_VERSION` 由 `20261028` 升到 `20261030`（实际提交日期）。

### ThePornDB 403 不再误报成「连接失败」

- 用户反馈：设置页「检测」报 `❌ ThePornDB连接失败:GET https://theporndb.net/api/scenes/hash/8679fcbdd29fa735失败:HTTP403body={"message":"This action is unauthorized."}`。
- 实测确认 403 的真实含义（当日判断：`api.theporndb.net` 子域整体 403、API 已迁到主域 `/api`；该判断当天即按用户确认回滚，见上一条）：不带 Token 或 Token 不存在/失效 → `401 {"message":"Unauthenticated."}`；Token **通过身份验证但没有该接口权限** → `403 {"message":"This action is unauthorized."}`。即 403 既不是网络故障也不是 Token 填错，而是「这个 Token 没哈希直查权限」，提示「请检查网络或代理设置」会把人带偏。
- 新增 `mdcx/utils/theporndb_token.py`：接口地址（`HASH_PROBE_URL` / `LIST_PROBE_URL` / `TOKEN_PAGE`）、`http_status_from_error()`（4xx/5xx 时 `web_async.request()` 只回 `(None, "GET … 失败: HTTP 403 body=…")`，状态码只能从错误串取）、`token_issue_message()` / `token_issue_short()` 三处共用文案。
- `mdcx/base/web.py::check_theporndb_api_token()`：哈希 403 时再用标题查询复核——能过就报「✅ 连接正常（哈希直查无权限，刮削会自动改用标题搜索）」；两个接口都 403（或其它状态码）则按原文打印 `❌ 连接失败：GET …失败：HTTP 403 body={…}`。顺带 `.strip()` 掉粘贴时带的空白/换行。
- `mdcx/core/network_check.py`：「ThePornDB Token」项 403 记警告（`Token 无该接口权限（403），刮削会自动改用标题搜索`）、401 记失败，不再把原始 body 当网络故障。
- `mdcx/crawlers/theporndb.py`：哈希直查 403 明确记一行「哈希直查无权限(403)，改用标题搜索」后继续刮；标题查询/详情请求遇 401/403 抛出同一条可执行提示（不再甩 `body=` 原文）。`_headers()` 同样 strip Token。
- 测试：`tests/test_theporndb_token.py`（状态码解析、检测按钮四种结局、检测页 403/401 分类）、`tests/crawlers/test_theporndb.py::test_theporndb_hash_403_falls_back_to_search`、`::test_theporndb_search_403_reports_token_permission`。

### ThePornDB 检测失败行改成可读的诊断原文

- 用户 2026-10-30 定规：这一行要长成
  `❌ ThePornDB连接失败：GET https://theporndb.net/api/scenes/hash/8679fcbdd29fa735失败：HTTP 403 body={"message":"This action is unauthorized."}`
  而不是 `❌ ThePornDB连接失败:GET …失败:HTTP403body={"message":"Thisactionisunauthorized."}`。
- 三处问题：① 站点名重复（文案里写了一遍 `ThePornDB`，`with_site_prefix()` 又补一遍，成了 `ThePornDBThePornDB`）；② 冒号是半角；③ `HTTP 403` 与响应体里的空格被 `strip_log_spaces()` 删光。
- `mdcx/utils/__init__.py::strip_log_spaces()`：**双引号里的内容原样保留空格**（响应体/引用原文，`body={"message":"This action is unauthorized."}` 不能再压成 `Thisactionisunauthorized.`），引号状态每行重置；`_restore_kept_gaps()` 新增 `HTTP 403`（状态码与 `HTTP` 之间）与 `403 body=`（状态码与响应体之间）两条补空格规则，且都幂等——日志页要过 `log_console.log_text()`、`show_log_text()`、`add_html()` 三道清洗，每道都成立才不会被后一道吃掉。
- `mdcx/base/web.py`：失败文案统一成 `❌ 连接失败：…`（站点名交给 `with_site_prefix()` 补，不再重复），新增 `_format_theporndb_error()` 只把 `失败: ` 的冒号换成全角 `失败：`，其余（含 URL 与「失败」之间的空格）原样保留。
- 用户第二轮定规：URL 与「失败」之间**要**留一个空格（`…fa735 失败：HTTP 403`），故 `strip_log_spaces()` 再加一条「URL 后接失败」规则——`_prev_visible_char()` 反向跳过 `<a>…</a>` 标签找 URL 末字符，只在同一条 URL 后面补空格，`ThePornDB连接失败`、`CloudFlare Bypass失败` 这类不受影响。
- 测试：`tests/test_theporndb_token.py::test_failed_log_line_keeps_raw_body_readable`（断言日志窗口那一行的完整形态）、`tests/test_log_left_align.py::test_strip_log_spaces_keeps_quoted_content`、`::test_strip_log_spaces_keeps_http_status_gap`。

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

- 站点链按类型固定（有码 DMM→DMM_API→LibreDMM→JavDB→JavDB_API→JavDB_APP→Javlibrary_APP→JavLibrary→JavBus，无码 / FC2 / 欧美 / 国产 / 动漫各有定稿链），顺序即优先级。
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
- Official 旗下五个无码官网拆成独立站点；新增独立站点 `Javlibrary_APP`。
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
