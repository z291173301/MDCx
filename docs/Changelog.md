# Changelog

## v2.2.5 (2026-10-08)

### 修复

- **检测新版本「一会儿能检测到、一会儿检测不到」（用户反馈：运行 20261006 版却时有时无地提示新版本，而检测新版本的代码没动过）**：根因是 `check_version()` 只有一条取版本的路——`https://api.github.com/repos/z291173301/MDCx/releases?per_page=10`，而它**不带任何凭据**，GitHub 对匿名 REST API 的配额是 **60 次 / 小时 / 出口 IP**（不是 60 次/小时/用户，也不是每个 MDCx 实例各算一份）——同一出口 IP（家用宽带 CGNAT、公司/学校/机场/代理出口）下的**所有用户、所有 MDCx 实例共享同一个计数桶**。本机实测 2026-10-05 07:04：`GET https://api.github.com/rate_limit` → `200`，`X-RateLimit-Limit: 60`、`X-RateLimit-Remaining: 0`、`X-RateLimit-Used: 60`、`X-RateLimit-Resource: core`、`X-RateLimit-Reset: 1791156189`（本地 07:23:09 重置），同一时刻 `Invoke-RestMethod .../releases?per_page=10` 已返回 **403**。配额耗尽后 `check_version()` 拿到 403 → 记一条限流日志 → 返回 `None` → 主窗口把它当成「没查到新版本」，走绿色分支打「你使用的是最新版本！🎉」；等下一个整点配额重置，又恢复正常，于是用户看到的就是「时灵时不灵」。**与检测逻辑本身无关**：`is_remote_version_newer()` 是确定性的，20261006/v2.2.3 对 v2.2.4/20261007 必然判出新版本；即使 12h 定时复查也救不回来，因为每一次复查都在消耗同一个桶里的份额。三处修复：
  - **① atom 源兜底**（`consts.py` 新增 `GITHUB_RELEASES_ATOM = https://github.com/z291173301/MDCx/releases.atom`）：`api.github.com` 因 403 限流 / 超时 / 5xx / 响应格式异常而拿不到结果时，自动改请求 **`github.com` 站点的 releases.atom**——该源**不受** 60 次/小时 API 配额约束（站点页面走的是 CDN 与独立的匿名限流）。解析集中在公开函数 `parse_release_atom(text)`（`base/web.py`，公开是为了能脱离网络单测）：逐个 `<entry>` 取出 `releases/tag/(\d+)` 的**纯数字** tag 与 `html.unescape()` 之后的 `<title>` 作为 release 标题，**同样取最大 tag 而不是第一条**——`/releases` 与 atom 都按发布时间倒序，而发版工作流的四个 `svenstaro/upload-release-action` 步骤用**同一 tag + `overwrite: true`**（该 action 是先删后建），任何一次补发/重跑都会把那条 release 的 `created_at` 刷成当前时间、顶到列表第一位，详见 `tests/test_version_check_pick_latest.py` 里记录的这个坑（那三个文件级注释就是为它写的）。实测该源在 API 配额**已经耗尽**（`remaining=0`、同源请求已 403）时依然稳定返回 `v2.2.4 (20261007)` / `v2.2.3 (20261006)` / `v2.2.2 (20261004)` 三条，等配额重置后与 API 路径解析出的 `RemoteVersion(tag=20261007, name='v2.2.4 (20261007)')` **逐字段一致**，因此版本号维度与日期维度的比较（`is_remote_version_newer`）与左下角提示文案都不受取数路径影响。兜底成功时详情日志记 `🔄 GitHub API 暂不可用（<原因>），已改用 releases.atom 获取最新版本: <版本>`，用户能一眼看出这次走了哪条路
  - **② 6 小时本地缓存**（`userdata/version_check_cache.json`，`_VERSION_CACHE_TTL = 6 * 3600`）：一次检查成功后把 `{tag, name, checked_at}` 原子落盘（先写 tmp 再 `os.replace`，沿用 `core/image_host_cooldown.py` 的 `resources.u()` 运行时文件约定——缓存是运行时状态，不进配置文件也不进 git）；6 小时内再查**一个网络请求都不发**，直接用缓存并记 `ℹ️ 使用本地缓存的最新版本记录（<检查时间> 检查）: <版本>`。这一条同时解决两个问题：「一天开几十次 MDCx 把同出口 IP 的 60 次配额瞬间打光」与「配额已经耗尽时也照样能稳定提示」。网络失败时若存在**任意年龄**的缓存则回退用之（`_read_version_cache(float("inf"))`，记 `🔶 获取最新版本失败（<原因>），改用上次成功记录: <版本>`），于是「左下角会不会冒出🍉」不再取决于那一刻的网络与配额状态。缓存文件损坏 / 字段缺失 / 路径不可写 / 无缓存时一律静默降级为纯联网，绝不抛异常打断启动自检。**坑**：`_read_version_cache(max_age)` **刻意不写默认参数**——默认值会在函数定义时把 TTL 绑死，之后 `monkeypatch` 掉 `_VERSION_CACHE_TTL` 就完全不起作用（TTL 用例会假通过），故所有调用方显式传入 `_VERSION_CACHE_TTL`（新鲜判定）或 `float("inf")`（不限年龄的兜底）
  - **③ 失败原因分类**（`_describe_github_http_error()`）：`403` 且 `x-ratelimit-remaining == "0"` 记 `GitHub API 限流（403，剩余 0，预计重置 HH:MM:SS）`（用 `x-ratelimit-reset` 换算成本地时间；该响应头缺失时降级为不带时间的 `GitHub API 限流（403，剩余 0）`）；**不带 `remaining: 0` 的裸 403** 记 `HTTP 403（可能被 GitHub 或代理拦截）`——与限流区分开，避免把代理/防火墙拦截误读成配额问题；其余状态码记 `HTTP <code>`；JSON 不是数组记 `响应格式异常（非数组）`；atom 源解析不出结果记 `atom 源解析异常`。原有「未找到 MDCx 版本发布（最近发布: …）」「获取最新版本失败」两条文案保持不变（既有断言依赖）
- **代理回退链与超时判定抽成 `_github_request()`**：原实现把 `httpx.Client(...)` 的构造内联在 API 分支里，atom 分支要复制一份；现抽成单一入口（`timeout` / `follow_redirects=True` / 可选 `proxy`），两条源共用同一套「先配置代理、再直连」顺序，行为与改动前逐条一致
- **分离模式「覆盖本地已存在的STRM链接文本」必须以「为本地视频文件生成STRM链接文本」为前提（用户反馈：不勾生成时勾覆盖也不该生效）**：`extend.py: should_overwrite_strm()` 此前只有 `is_separate_mode() and separate_overwrite_strm`，两个开关被当成彼此独立——但不生成 STRM 自然不存在「已存在的 STRM」可覆盖，覆盖语义无对象。改为 `is_separate_mode() and separate_generate_strm and separate_overwrite_strm`。界面同步联动：新增 `checkBox_separate_generate_strm_changed`（`main_window.py`）在生成框勾选状态变化时 `setEnabled()` 置灰/恢复覆盖框（**只改 enabled、不动其 checked**，故用户先前勾好的覆盖值在重新勾选生成后立即恢复，不必重勾），`init.py` 接 `toggled` 信号、`load_config.py` 回读后同步 enabled；覆盖框 tooltip 改为「需先勾选「为本地视频文件生成STRM链接文本」；勾选后…」。配置 JSON 仍原样保存两个勾选值（不被界面联动改写），运行时由判定函数兜底，故手改配置也无法绕过该依赖。详见 `docs/Development.md`「分离模式 STRM 生成/覆盖的前置依赖（改前必读）」一节

### 分离模式 STRM 链路的三处修复（同批）

- **STRM 内容可能写入视频的旧路径**：原用 `Path(file_info.file_path) if eff_success_file_move() else Path(file_path)`，而 `file_info.file_path` 只在 `core/file.py: move_movie()` 的部分分支被改写——命中 `other.dont_move_movie`（目标已存在且同源）时**提前 return 且不更新**，于是 STRM 里存的是移动前的旧路径，播放库点开即失效。改为直接取 `file_new_path if eff_success_file_move() else Path(file_path)`：开移动时 `file_new_path` 恒为目标落点（与 `move_movie` 的所有成功分支一致），不开移动时视频原地不动、必须用 `file_path`（此时 `file_new_path` 指向从未使用过的目标目录）
- **同步 `write_text` 阻塞事件循环**：STRM 写入改 `await asyncio.to_thread(...)`，与本仓库其它落盘操作一致；异常捕获由 `OSError` 放宽到 `Exception` 并把异常信息与实际路径一并记进日志（原日志只有路径、无原因，且 `meta_folder` 与 `naming_rule` 拼接重复了一遍 `.strm`）
- **`.strm` 未被归入数据存放目录**：`SEPARATE_META_EXTS` 只含 `.nfo/.jpg/.jpeg/.png/.webp`，`base/file.py: move_other_file()` 据此分流，于是源目录里已有的 `.strm` 会**跟随视频**被搬进视频输出目录，与「STRM 与 nfo/封面同属元数据、放在数据存放目录」的约定直接冲突（重跑时还会和刚生成的 STRM 打架）。把 `.strm` 加入该集合，并补注释说明理由
- **「复用/覆盖元数据」在数据存放目录无效时仍生效（回退路径上的静默跳过）**：`should_reuse_metadata() / should_overwrite_meta()` 原签名不收 `meta_root`，只要 `main_mode == 2` 且勾选就返回 true。但 `data_path` 为空或不可创建时 `get_separate_meta_root()` 返回 `None`，`meta_folder` 退回视频目录——此时「复用**数据存放目录**中的元数据文件」根本无对象，若仍生效，`reuse_images` 会因视频目录里恰好有 poster/thumb/fanart 而**静默跳掉整轮图片下载**、nfo 也一并跳过（`not (reuse_meta ... and nfo_new_path.is_file())`），刮削「成功」却什么元数据都没写。两个判定函数改为收 `meta_root` 并加 `meta_root is not None` 前置条件（与 `should_generate_strm()` 同门），`scraper.py` 两处调用点传 `meta_root`；回退到正常模式布局时按正常模式行为照常下载/写入
- **`tests/test_scraper_remain_list.py` 三项长期失败的桩已跟上生产侧形参**：`_clean_empty_folders` 早已新增 `allow_empty` 形参（分离模式对数据存放目录另传右侧开关那次引入），而该文件的 `fake_clean_empty_folders(_path, _file_mode)` 桩没跟，导致三个用例自那以后一直以 `TypeError: ... got an unexpected keyword argument 'allow_empty'` 失败。桩补上 `allow_empty=None` 后三项转绿（此前全量 `pytest` 的固定 3 failed 由此清零），本轮改动本身与该失败无关

### 界面调整

- **软件设置-刮削网站页「类型刮削网站」组行距收紧：六条番号的绿色说明各上移一行（24px → 7px），国产 / 动漫里番 / MyWifes / 锁定类型四块之间的说明间距由 51px 收到 16px（≈ 一行汉字）**：用户两张标注截图（① 三处红字「间隔一行汉字的高度」，② 六处红字「向上移动一行」）。**根因是「声明高度远超自然高度」+「两段说明挂着 84px 硬最小高」**：`layoutWidget_6` 在 `.ui` 里声明高 930，而 `gridLayout_36` 的自然高只有 618，多出的 **312px 余量被 QGridLayout 均摊到每一行**（实测每行 +18px），于是「输入框 → 说明文字」被撑到 24px；同时 `label_318` / `label_323` 各挂着 `minimumSize 0x84`，行高被硬撑到 84，把「国产说明 → 动漫里番」「动漫说明 → MyWifes」「MyWifes 说明 → 锁定类型」三处块间间隙顶到 51px。**改法（全部落在 `.ui`，`MDCx.py` 由 pyuic6 重编译，同步关系由 `test_ui_structure.py::test_mdcx_py_in_sync_with_ui` 钉死）**：① `gridLayout_36` 显式 `verticalSpacing = 7`——单行说明行的行高 = 文字高，故「输入框 → 说明」与「说明 → 下一组控件」两侧都精确等于 7px（`24 − 17 = 7`，**恰好一行汉字**，即需求②的「上移一行」）；② 三段会换行的说明（`label_232` 国产 / `label_318` 动漫里番 / `label_323` MyWifes）所在行锚死在 **34px = 两行文字**（主题字体下一行文字 17px）：三者都加 `maximumSize 16777215x34`，并删掉 `label_318` / `label_323` 的 84px 硬最小高，行高改由同行的 `label_316` / `label_322`（最小高 30）兜底；③ 国产说明 / 动漫里番 / MyWifes / 锁定类型四个块之间各插一行**固定 9px 的 `QSpacerItem`**（`QSizePolicy::Fixed` + `colspan="4"`，否则余量会把它重新撑开），块间总间隙 = 7 + 9 = **16px ≈ 一行汉字**（需求①）；④ 声明几何同步收敛：`layoutWidget_6` 930→558、`groupBox_80` 970→628、分隔线 y 1289→976、后续组 `groupBox_35` y 1340→1027、`scrollAreaWidgetContents_guaxiaowangzhan` 高 2470→2157（底部留白仍 130）。**这五处几何不是随手填的数**：绝对定位容器的高度只要大于网格自然高，`QGridLayout` 就会把富余摊进 `verticalSpacing`（整 1px 步进），行距会随容器高度漂移。实测（真实主窗口 + 主题字体）：**1014 宽**（用户截图宽度）输入框→说明 **7px**、说明→下一控件 **7px**、三处块间 **18 / 18 / 16px**，三段说明各 34px 恰好装下两行不截字；**1400 宽**为 8px 与 17 / 17 / 17px；**860 宽**（content 设计宽）为 7px 与 18 / 18 / 16px。**已知取舍**：窗口窄于约 980 时三段说明需要三行（51px），被钉在 34px 会截掉第三行；窗口很宽时三段只剩一行，34px 行高会在文字下方留约 17px 死白、块间视觉间隙相应变大——两者都是换取默认宽度下 7px / 16px 稳定紧凑排布的刻意取舍。运行期逻辑未加任何同步，只改了 `main_window.py` 里 `_SITE_PREF_COMBO_REF` 旁的一行注释（「锁定类型（row 14 col 1」→「row 17 col 1」，行号因新增三行 spacer 而下移）。**顺带修正 MyWifes 块说明里番号规则的品牌大小写**（用户指定）：`label_323` 末句由「Mywife番号规则：Mywife No.1230」改为「**MyWife番号规则：MyWife No.1230**」——前半句「指定Mywife或文件路径含有Mywife时，将自动使用Mywife刮削」按用户要求原样保留（那里的 Mywife 指站点/路径关键字，与 `Website.MYWIFE = "mywife"` 一致，改了会与实际匹配逻辑脱节），只把「番号规则」那半句的品牌写法统一成站点自己的写法 `MyWife`（`mdcx/crawlers/mywife.py` 的类名与 description 即 `MyWife No.`）。只动 `label_323` 的 `text`，`.ui` 与 pyuic6 重编译后的 `MDCx.py` 同步，布局不受影响
- **软件设置-演员页最大化时「选择文件」右移到与「选择目录」严格上下对齐、「演员信息数据库」显示框同步向右拓展（最小化/还原态保持不变）**：用户 1920 宽最大化截图上红线画在两枚「选择目录」按钮所在列、旁注「最大化时向右移动到这里」，「选择目录」自身位置保持不变。**根因不是控件位置而是两个 groupBox 各用各的网格**：`pushButton_select_actor_info_db`（「选择文件」）在演员信息组 `groupBox_64` → `gridLayoutWidget_14` → `gridLayout_14` 的 `horizontalLayout_155` 行里，而两枚「选择目录」在头像组 `groupBox_41` → `layoutWidget_8` 的网格里，**两套网格的列宽互不相关**；此前宽态把路径框右缘钉在 **A2（`checkBox_actor_photo_ne_face`「使用 Graphis 头像」左缘，1920 实测 652）**，「选择文件」因此落在 658，与真正要对齐的「选择目录」列（1920 实测 1469）差 **811px**——A2 是头像组的 Graphis 三等分列，与演员信息组的按钮列没有半点关系。**改法**：路径框宽度不再由 Graphis 列反推，改由**两枚「选择目录」之一的实测左缘**反推（`sel_x - row.spacing() - A1`，行内 spacing 一并算进去，按钮即正落在那一列），窗口任意宽度都成立、不写死常数；锚点取 `pushButton_select_gfriends_local`（与另一枚 `pushButton_select_actor_photo_folder` 在同一网格的同一列，两态右缘恒等）。`want_w` 低于 `_ACTOR_INFO_PATH_MIN_W`（=300，取 `.ui` 里 `lineEdit_actor_db_path` 的 minimumSize 宽）时宁可不钉，交给通用布局，避免极窄窗口下把框钉到夹不住文字。实测 2560 / 2200 / 1920 / 1600 / 1366 / 1280 / 1100 / 1060 八档宽态「选择文件」左缘与两枚「选择目录」**逐档完全相等**（1920 皆 1469），路径框右缘恒 = 按钮左缘 − spacing；行尾本就有的 Expanding 间隔 `horizontalSpacer_actorInfoTail155` 吸收零余量，故无需再插间隔。**窄态完全不动**：窄态该行由需求⑨ 的既有钉宽（`_ACTOR_NARROW_PATH_ROW` + `_ACTOR_NARROW_PATH_MIN_W`）负责，实测 1030 / 1000 两档「选择文件」仍在 579 / 549，与改动前逐像素一致
- **软件设置-演员页最大化时「网络头像库」显示输入框缩到与「Gfriends 本地仓库」「本地头像库」两行显示输入框上下对齐（最小化/还原态保持不变）**：同一张截图上「网络头像库」行旁注「最大化时向左缩进到这里」。**根因**：三枚输入框**左缘本就同列**（都在 `layoutWidget_8` 网格 col1 起点 = A1 = 186，实测两态恒等），但「Gfriends 本地仓库」「本地头像库」两行是「输入框 + Fixed 110px 的选择目录按钮」的水平行，网格排完即止于按钮列、右缘停在 1463；而 `lineEdit_net_actor_photo` 是网格里的**直接项、右侧没有按钮**，宽态下独占整列富余宽 1393、右缘顶到 1579，比另两枚宽出**整整一枚按钮的宽**（110 + spacing 6 = 116）——正是截图里那截参差。**改法**：在 `_sync_actor_page_wide_a2_align` 末尾新增第 ⑥ 块，量 `lineEdit_gfriends_local_path` 的**运行时终态宽**、把网络头像库输入框钉成同宽（`lock_width` + 一次读回纠偏吸收 1px 取整误差），三枚输入框于是左缘、右缘双双相等。**为什么钉宽能持久**：通用宽幅同步 `sync_wide_children_width` 只按设计宽拉伸它的**父容器** `layoutWidget_8`（`_STRETCH` 项），输入框自身不在 registry 里，钉住的宽不会被每遍同步抹掉。**为什么必须排在 `_sync_actor_info_columns` 之后**（`_sync_actor_page_wide_hooks` 四拍顺序的最后一拍）：该方法末尾的 `grid.invalidate()+activate()` 会把网格里的直接项弹回整列宽。**还原是真解锁**：钉宽登记进 `_actor_wide_restores`（记录原 min/max，由 `_clear_actor_wide_align` 逆序写回），实测窄态 `minimumWidth` 回到 300、`maximumWidth` 回到 `QWIDGETSIZE_MAX`，整份快照与「只有通用逻辑」的基线逐像素一致；窄态第一步清干净即 return，**最小化态一个像素都不碰**（窄态下三枚宽度仍 503/473 对 387/357 的原样参差是用户明确要保留的）。实测八档宽态三枚输入框宽度完全相等（1920 皆 1277、右缘皆 1463）
- **软件设置-演员页最小化时「网络头像库」显示输入框右缘向左缩进到与「Gfriends 本地仓库」「本地头像库」两行显示输入框严格上下对齐（最大化态保持不变）**：最小化截图上红线画在两枚路径框右缘处、旁注「向左缩进到这里」，两行路径框自身位置保持不变。**根因与上一条完全相同**（`lineEdit_net_actor_photo` 是 `layoutWidget_8` 网格 col1 里的直接项、右侧没有按钮，于是独占整列富余宽），只是**上一条按需求⑭ 只在宽态钉了宽，窄态那截参差被用户明确要求保留——本次把它补上**。**改法**：在 `_sync_actor_page_narrow_align()` 末尾新增第 ⑤ 块，与宽态第 ⑥ 块逐行镜像（`grid.invalidate()+activate()` 先落定 → 量 `lineEdit_gfriends_local_path` 终态宽 → `lock_width` 钉宽 → 一次读回纠偏吸收 1px 取整误差）。窄态钉宽登记进 `_actor_narrow_restores`，由 `_clear_actor_narrow_align` 逆序写回原 min/max，故**最大化态是真解锁**：实测 1920 宽态 `_actor_narrow_restores` 为空、`minimumWidth` 回到 300，整份快照与「只有通用逻辑」的基线逐像素一致。**顺带一处结构性修正**：窄态原有的需求⑨（`_ACTOR_NARROW_PATH_ROW`「选择文件」对齐「选择目录」）是一串带多个 `return` 的平铺代码，新增第 ⑤ 块会被这些早退跳过，故照既有 `_shift_source_row()` 的先例收成嵌套闭包 `_shift_actor_db_path_row()` 再调用。**一个会直接把测试进程打死的坑**：`layoutWidget_8` 是 pyuic 生成的 **QLayoutWidget**，`invalidate()` / `activate()` 必须调在它**返回的 `.layout()`** 上而不是控件本身（调在控件上会让整个 pytest 进程以 `Windows fatal exception: access violation` 退出、无任何用例输出），`_clear_actor_narrow_align()` 末尾因此新增「解锁后让网格重排一次」这一步，否则 min/max 已放开但控件仍留着上一遍的宽。实测 1030 / 1000 两档窄态三枚输入框宽度完全相等（右缘 573 / 543，恰为「选择目录」左缘 579 / 549 减去行间距 6），与最大化态 1463 / 1143 / 823 的相对关系一致；**两枚「选择目录」按钮列在三档窄态下逐档不动**。极窄窗口（实测 900 宽、extra −152）时参照行已被需求⑨ 挤到它 300px 的最小宽，此时网络头像库框钉到 300 即为下限（`want >= net.minimumWidth()` 才钉），「演员信息数据库」框则按既有需求⑨ 规则退到 257——这一档不做右缘对齐断言，测试里按 `ref.width() > ref.minimumWidth()` 条件跳过
- **软件设置-高级页最小化时「每次间隔」时长输入框右缘向左缩进到与「间歇刮削」文件数输入框右缘严格上下对齐（最大化态保持不变）**：用户最小化截图上红线横跨两行画在 `20` 那个框的右缘处、旁注「向左缩进到这里」（**不是**「间歇刮削」里 `00:01:00` 那个框的右缘），「间歇刮削」一行自身位置保持不变。**根因是两行长短不同、而只有输入框能被压缩**：`gridLayout_20` 里「间歇刮削」行 `horizontalLayout_109` 有五项（`checkBox_rest_scrape`「连续刮削」+ `lineEdit_rest_count` + `label_52`「个文件后，自动休息」+ `lineEdit_rest_time` + `label_71`「（时:分:秒）」），按真实字体实测需要 579px；「每次间隔」行 `horizontalLayout_104` 只有三项（`checkBox_timed_scrape`「每次间隔」+ `lineEdit_timed_interval` + `label_84`），需要 543px。三个 `QLabel` 的 `minimumSizeHint` 与 `sizeHint` 相等（**压不动**），三枚 `QLineEdit` 的 sizePolicy 又是 Fixed/Fixed、只有 `minimumSizeHint`（29px）可让——于是窗口一窄，**先溢出的一定是更长的 `horizontalLayout_109`，Qt 只会把富余差摊到它的两枚输入框上**，而 `horizontalLayout_104` 那行还装得下、`lineEdit_timed_interval` 保持满宽 141，于是它的右缘越过 `lineEdit_rest_count` 的右缘（截图里 `00:40:00` 明显更靠右）。**改法**：新增 `_sync_advanced_page_rest_interval_align(wide)`，沿用 `_sync_advanced_page_debug_row` 那套「**先解除上一轮钉宽并重排 → 量锚点 → 再钉 → 重排 → 读回纠偏**」的惯用法；锚点取 `lineEdit_rest_count` 的**运行时右缘**（`col_x(anchor) + anchor.width()`），不写死像素——它随字体度量变，写死必哑；只在 `0 < want < 目标现宽` 且 `want >= 目标 minimumSizeHint 宽` 时才钉（行还装得下就不钉、绝不做「把窄的一行撑宽」的倒向调整）。复用既有的 `_pin_row_lead_width(box, width)` 静态辅助（它本来就已被用在尾部两枚「关」按钮上），`None` 即真解锁。**最大化态只解除不钉**：那一态两行都不溢出、右缘本就相等，故 `wide` 分支直接 return 并顺手把可能残留的钉宽解开，实测四档宽态（1920 / 1600 / 1366 / 1100）目标框 `minimumWidth == 0`、`maximumWidth == QWIDGETSIZE_MAX`，整份两行快照与「摘掉本方法」的基线逐像素一致。**挂载点必须在 `_sync_advanced_page_align(adv_scroll)` 之后、且挂在它外面**：那个方法末尾有一批 `gridLayout_20.invalidate()+activate()`，提前量到的是过期几何；它还自带多处早退分支，从内部挂钩子不可靠，故新方法在 `_sync_page_layouts()` 里紧跟其后单独调用

### 测试

- **「类型刮削网站」组行距的回归**：新增 `tests/test_type_site_scrape_rows.py`（**23 项全过**）。静态侧把 `gridLayout_36` 的 19 行行号表（0..18，含三行块间 spacer 与整体下移三行的锁定类型块）、`verticalSpacing = 7`、三个块间 spacer 的 `QSizePolicy::Fixed` + 9px 固定高 + `colspan="4"`、三段说明的 `maximumSize` 高 34 与「`label_318` / `label_323` 不再保留 84px 硬最小高」，以及 `layoutWidget_6` 661x558 / `groupBox_80` 701x628 / `groupBox_35` y=1027 / content 860x2157 四组几何（含「底部留白仍 130」）全部锁死——`.ui` 全文有 11 处同名 `layoutWidget`（Qt Designer 命名残留、pyuic 会自动改成 `layoutWidget_2`…），故几何只断言本组四个唯一名控件。运行期用真实主窗口离屏 + 加载主题字体（不加载 QSS 时裸脚本量到的行高是 15px、不是用户的 17px，故数据只能取 pytest 环境），在 1400 / 1014 / 860 三档宽下断言「输入框 → 说明」「说明 → 下一控件」各约 7px、三处块间约 16px、块标签与自家说明顶边同行、`layoutWidget_6` 高度不被网格撑大且内容不越过组框与下一组，并在 ≥1014 宽下断言三段说明高度 ≥ `heightForWidth()`（不截字；860 宽处 51px 的三行排版落在已知取舍里，见上一条）。**容差是量出来的不是拍的**：「输入框 → 说明」两侧用 ±2（单行说明行行高恰为文字高，间隙实测精确等于 7）；「说明 → 下一块」用 ±4——换行说明所在行的行高取 `max(sizeHint)`，而 wordWrap `QLabel` 的 `sizeHint` 是文字包围盒高（可带小数），同一段文字在 339 / 341px 宽下包围盒高就差 1~2px（实测行高 34↔36、块间 18↔20），属亚行级抖动，不影响观感。夹具沿用 `tests/test_site_pref_row_order.py` 的做法（monkeypatch `run_startup_health_checks` / `show_netstatus` / `check_version` / `save_remain_list`、把 `style_mod.resources.qtr` 指向真实资源以便加载主题、停掉四个定时器、切页后跑四轮 `_sync_page_layouts()`）。另加一条**文案回归锁** `test_wrapped_desc_texts_regression`：三段换行说明的完整文案逐字比对 `.ui` 里的富文本（先反转义 `&lt;` `&gt;` `&amp;` 再比，`label_232` 用的是 `<span>`、`label_318` / `label_323` 用的是 `<p>`，两种都要能解析），把「MyWife番号规则：MyWife No.1230」的大小写钉死，防止日后无声改回 Mywife。UI 结构 22 项 + 本组 23 项 + `test_site_pref_row_order` / `test_window_state_matrix` 7 项全过（共 **124 项**，收尾时的 `Windows fatal exception: access violation` 是本仓既有的 Qt 析构噪声，与断言结果无关）
- **高级页窄态「每次间隔」右缘对齐的回归**：新增 `tests/test_advanced_page_tail_align.py::test_timed_interval_right_edge_matches_rest_count`（**核心难点是无头/离屏环境根本不会触发那条压缩路径**：`QT_QPA_PLATFORM=offscreen` 下 `QFontDatabase.families()` 为空、所有字形退化成同一个内置 Sans Serif、中文与数字同为 13px 前进宽，两行都不溢出，实测 `lineEdit_rest_count` 与 `lineEdit_timed_interval` 天生就等宽等缘——真按现状断言等于什么都没测。故用例**显式制造压缩**：把锚点 `anchor.setFixedWidth(max(anchor.minimumSizeHint(), anchor.sizeHint() - 24))` 钉窄来模拟生产的挤压缩，再断言同步后① 锚点自身 x/y/w/h 一律未动（证明是「跟着缩」而不是「把锚点也拉走」）② `right(目标) == right(锚点)` ③ 目标框 `minimumWidth == maximumWidth == 压缩量`（证明是真钉宽、不是碰巧等宽）④ 解除锚点钉宽后两次 resize 仍等缘），该文件 44 → **55 项全过**。另有四个守卫用例：`test_timed_interval_not_pinned_when_row_fits`（把锚点撑到比目标 sizeHint 还宽 60px，此时目标框必须 min 0 / max MAX——**「不钉」也是需求的一部分**，否则会把布局硬掰成一行比一行窄）、`test_timed_interval_never_widened`（900 / 820 两档极窄下 `目标宽 <= 目标 sizeHint 宽`，杜绝倒向撑宽）、`test_timed_interval_untouched_in_wide`（四档宽态整份两行快照 == 「摘掉 `_sync_advanced_page_rest_interval_align`」的第二扇窗口基线，且 min/max 为 (0, MAX) 真解锁）、`test_rest_interval_alignment_survives_round_trip`（窄态压缩 → 宽态解锁 → 回窄态复现）。**按需构造的回归基线必须另开一扇窗口**、不能在同一扇窗上摘钩子重跑——已解除的钉宽会随调用残留，会把基线本身算歪。新增模块级辅助 `_right` / `_rest_row_snapshot`（两行全部 9 枚控件的几何快照）/ `_baseline_without_rest_interval_align` / `_unpin`（用 `setMinimumWidth(0)` + `setMaximumWidth(QWIDGETSIZE_MAX)`，**不是** `setFixedWidth(0)`，后者会把最大宽也钉成 0）。**反向验证**：把新方法临时改成开头即 `return`（验证后从备份恢复）后跑 `pytest -k "timed_interval or rest_interval"` 得 **3 failed**（右缘 438 对 414，正好吃掉那 24px 压缩量）/ 8 passed，说明新用例确有鉴别力；另三个守卫用例两种实现下都通过，属设计如此。演员页 / 高级页 / UI 结构三套件合跑 89 项全过
- **演员页窄态（最小化）「网络头像库」输入框右缘对齐的回归**：新增 `tests/test_actor_info_columns.py::test_actor_narrow_net_photo_input_aligns_with_path_inputs`（1030 / 1000 / 940 三档窄态下三枚路径输入框左缘、宽、右缘三者全等 + `minimumWidth == maximumWidth == 参照框终态宽`（钉宽确实落在窄态自己的登记表里、不是残留在宽态）+ 钉进 `_actor_narrow_restores` + 右缘 == 「选择目录」左缘 − 行间距，**最后再回到最大化态断言整份快照 == 「摘掉 `_sync_actor_page_narrow_align` 及其清场函数」的基线**，以此证明窄态新逻辑一个像素都不碰最大化页面），该文件 17 → **18 项全过**。既有的 `test_actor_wide_net_photo_input_aligns_with_path_inputs` 改写为「只管宽态」：删掉签名上已无用的 `monkeypatch`，补一条「宽态钉宽确实登记进 `_actor_wide_restores`」，并把窄态段落里原先两条**已被需求⑮ 推翻**的断言（「窄态 `_actor_wide_restores` 为空且 min/max 真解锁」「窄态网络头像库框比参照框宽」）改成「宽态登记表在窄态必须为空、网络头像库框改为登记在 `_actor_narrow_restores`、往返后重新钉上」——钉宽按需求设计就该在两态各自成立，旧断言已不再是正确期望。**记一个真实的踩坑**：`layoutWidget_8` 是 pyuic 生成的 QLayoutWidget，`invalidate()` / `activate()` 调在**控件**上（而不是它 `.layout()` 返回的网格上）会让整个 pytest 进程以 `Windows fatal exception: access violation` 退出且不打印任何用例结果——排查这类「没有失败列表的整场消失」时应优先怀疑 Qt 虚函数错调。全量 `pytest tests --ignore=tests/crawlers -q` **1995 passed / 3 failed / 1 skipped**，3 个失败仍是既有的 `tests/test_scraper_remain_list.py`
- **演员页两条新对齐的回归**：新增 `tests/test_actor_info_columns.py::test_actor_wide_net_photo_input_aligns_with_path_inputs`（宽态三枚输入框左右缘全等 + 缩进量恰为一枚按钮宽加行间距、幂等、窄态与「只有通用逻辑」的基线逐像素一致且 min/max 真解锁、窄宽两向往返复原），该文件 16 → **17 项全过**。`test_actor_info_columns_align_when_wide` 的需求⑥ 断言由「右缘 == A2 / 按钮 ≥ A2」改为「路径框右缘 + 行间距 == 「选择目录」左缘 == 「选择文件」左缘 == 另一枚「选择目录」左缘」；另把两处写死的宽态像素值 `466` 换成「与宽态实测对比」的相对断言（窗口尺寸无关）。`_WIDE_WIDGETS` 补入三枚路径框与两枚「选择目录」，使既有 `test_actor_wide_a2_*` 的「窄态整份快照 == 只有通用逻辑的基线」断言顺带覆盖新钉宽是否泄漏到窄态。UI/布局相关 20 个套件 301 项全过（1 skipped）
- **新增 `tests/test_version_check_fallback.py`（23 项，atom 兜底 + 本地缓存回归）**：桩掉 `base_web.httpx.Client` 为一个按 URL 分发响应的 `_FakeClient`（记录每次请求的 URL 与所用代理）、另备一个 `get()` 直接抛 `OSError` 的 `_BoomClient` 模拟断网。覆盖：① **配额耗尽时走 atom**——API 返 `403 + x-ratelimit-remaining: 0` 且 atom 有内容时结果正确，且**同时断言详情日志里出现 `releases.atom` 与「限流」**（否则「兜底悄悄生效」无人知晓）；② 参数化的兜底触发条件 `500` / 裸 `403`（非限流）/ 返回 JSON 非数组 / 200 但全是非数字 tag / API 直接超时，五种都必须由 atom 兜住；③ **atom 侧同样取最大 tag**（把旧 tag 放在第一条的 feed 里仍返回最大那条，不重蹈 `/releases` 顺序坑）+ `<title>` 的 HTML 实体反转义 + `parse_release_atom()` 对空串 / `<html>404</html>` / 全无数字 tag 三种脏输入返回 `None`；④ **API 成功时一个 atom 请求都不许发**（断言请求 URL 列表长度为 1 且是 API 域名，这条防止有人把 atom 无脑挪到主路径上再请求一遍）；⑤ atom 请求同样遵循「配置代理优先、再直连」的顺序；⑥ **缓存**：新鲜缓存命中时**再发一次零请求**且正确写出 JSON、TTL 过期后（monkeypatch `_VERSION_CACHE_TTL = 60`）会重新走网络、断网时回退到 30 天前的老缓存、无缓存且断网返回 `None`、五种损坏/残缺 JSON 一律忽略、缓存路径不可写不致命、`update_check=False` 时**即便有合法缓存也不读不发**；⑦ 自带 autouse fixture 把 `_version_cache_path` 指向 `tmp_path`——**这不是洁癖而是必需**：否则某个用例刚写下的新鲜缓存会让下一个用例直接短路返回、把网络断言全部架空（`tests/test_version_check_pick_latest.py` 同样补了同名 fixture，理由相同）
- **回归结果**：版本检查五个套件（`test_version_check_fallback` / `test_version_check_pick_latest` / `test_version_check_compare` / `test_version_consistency` / `test_version_metadata`）**58 项全过**（23 + 原有 35）；`tests/test_base_web.py` 一并加入后 89 项全过；GUI 侧 `tests/test_version_check_notify.py` 4 项全过（提示链、去重、12h 周期均未受影响——本次没有改 `_show_version_thread`）；`ruff check` 对 `mdcx/base/web.py` / `mdcx/consts.py` 与两个测试文件干净。全量 `pytest tests --ignore=tests/crawlers -q`（`--ignore` 是因为 `tests/crawlers` 里有真实联网用例）**1993 passed / 3 failed / 1 skipped**，1993 = 上次基线 1970 + 本次新增 23；3 个失败全是既有的 `tests/test_scraper_remain_list.py`（`mdcx/core/scraper.py:396` 的 `TypeError: fake_clean_empty_folders() got an unexpected keyword argument 'allow_empty'`，测试桩没跟上生产侧新增的 `allow_empty` 形参），已 `git stash` 后在干净树上跑同一命令复现，确认与本次改动无关。会话收尾的 `Windows fatal exception: access violation` 为既有问题（崩在 `conftest.py::pytest_sessionfinish` 的后台线程收尾）
- **联网端到端验证**（临时探针脚本，跑完即删）：① **API 配额耗尽**（`rate_limit` 回 `remaining=0`、同源 `releases?per_page=10` 已 403）时直接请求 `releases.atom`，解析出的条目标题为 `v2.2.4 (20261007)` / `v2.2.3 (20261006)` / `v2.2.2 (20261004)` …（atom 源最多暴露最近 10 条），最新一条的 tag 与链接 `releases/tag/20261007` 均正确；② 配额重置后走 API 路径 → `RemoteVersion(tag=20261007, name='v2.2.4 (20261007)')`，与 atom 路径解析结果逐字段相同；③ 完整 `check_version()` 连续两次调用，第二次直接复用刚写入的缓存（无新请求），返回同一个 `RemoteVersion`；④ `is_remote_version_newer(remote, 20261007, "v2.2.4")` → `False`（同版本不误报「有新版本」，语义正确）

### 文档

- **`docs/Development.md`「版本号管理 → 更新检查（客户端自动更新）」不变量由三条补到六条**（原有 ①②③ 保留，编号续接为 ④⑤⑥）：④ 记录 60 次/小时/出口 IP 的匿名配额事实与「任何一次 API 失败都必须回退 `releases.atom`」，并强调不变量 ①「取最大 tag」对 API 与 atom **两条源同时成立**、改一条必须同时改另一条；⑤ 记录缓存的三条行为（新鲜不发请求 / 失败回退任意年龄缓存 / 损坏静默降级）、`_read_version_cache` 不给默认参数的理由（def 时绑死 TTL 会让 monkeypatch 失效、用例假通过），以及**写 `check_version()` 测试必须把 `_version_cache_path` 指向 `tmp_path`**（否则上一个用例的缓存会把下一个的网络断言架空）；⑥ 顺带把原先错放在「主窗口 UI 布局与窗口缩放」一节的「版本检查定时复查走完整提示链」（12h `timer_update` 直连裸 `check_version`、阻塞主线程且返回值被丢弃）整段搬进本节，与布局无关的内容不再留在布局章节

## v2.2.4 (2026-10-07)

### 新增

- **左侧导航栏「使用说明」按钮下方新增微信收款二维码 + `[赞助作者]` 链接（点击弹出赞助窗口）**：二维码与链接由 `main_window.py` 在运行时注入 `widget_setting`（`label_donate_qr` / `label_donate_link`，`raise_()` 压在 `left_backgroud_widget` 之上），**刻意不改 `.ui` / `MDCx.py`**，避免 pyuic 同步测试受影响。链接为富文本 `<a href="#donate">`，亮色 `#0078D7` / 暗黑 `#4DA6FF`（`_DONATE_LINK_COLOR` / `_DONATE_LINK_COLOR_DARK`），`linkActivated` 接 `show_donate_dialog()`。定位逻辑 `_layout_donate()` 挂在 `_sync_dock_layout()` 的空间充足/过矮两条路径上，极矮窗口另有 `_hide_donate()` 兜底。尺寸常量集中在 `# region 侧栏「使用说明」下方…` 内：`_DONATE_QR_SIZE=180`、`_DONATE_QR_MIN=40`、`_DONATE_LINK_H=22`、`_DONATE_LINK_GAP=2`、`_DONATE_PAD=2`、`_DONATE_TEXT_GAP=10`。**布局军规**：任何窗口高度下二维码、链接、状态文字三者包围盒两两不相交，且左下角「正常模式·字段优先 / actor.json / 版本号」永不被裁——实测 600~1200 全区间重叠面积 0
- **新增独立赞助窗口 `mdcx/views/donate_window.py`（`DonateDialog`）**：展示微信/支付宝两张收款码 + 新人榜Top10 / 土豪榜Top10 两个 10 行 3 列（用户名 / 日期时间 / 金额）榜单 + 底部一行说明。榜单按配置渲染真实数据，无数据时复刻空表框架。窗口 `setFixedSize(657, 637)`（客户区），整窗正好 657×677，与参考截图 1:1。`resources.py` 新增 `donate_wechat_icon` / `donate_alipay_icon` 两个资源属性（`tests/conftest.py` 的 `_DummyResources._ICON_ATTRS` 同步补齐）。**未照抄参考图里 BTSOU 的群号**，底部改为 MDCx 自有群号文案「官方交流群：把酒问青天[1108931283]-密码[MDCx]，进群后必须遵守法律法规」
- **赞助弹窗新增第三张收款码「支付宝红包」**（`resources/Img/donate-alipay-redpacket.jpg`，`resources.py` 新增 `donate_redpacket_icon`，`donate_window.py` 的收款码槽位 `_CARD_COUNT` 由 2 改 3）：`_INTRO_TEXT` 本就写着「3.拿支付宝红包」，此前只有前两张码有对应图；README 顶部赞助表格同步加第三列。**码图本身不是截图直接缩放**——支付宝红包收款截图带「支付宝」logo /「推荐使用支付宝支付」蓝底横幅 / 白色圆角卡片 /「信诚水果超市(*涵)」「¥10.00」，直接用既难看又扫不出（文字压在码区里），故按**模块网格重建**：实测定位图形边长 112px → 模块 16px，二维码包围盒 656×658 → 41×41（QR version 6），逐模块取均值二值化后**整数倍放大重绘**（980×980 画布 / 模块 20px / 码 820×820 居中 / 四周 80px = 4 模块标准静区），边缘零锯齿。**中心头像换成红包图标**时按 9×9 模块下取，原图被旧头像破坏的区域是 7×7（模块 17~23 行/列），新图标覆盖 16~24 完全包住，图标本体 140px + 四周 20px 纯白隔离带（沿用 donate-wechat 那种「码上留白圈」的观感）；cv2 实测 980/400/300/210/180/150px 全部解出 `https://qr.alipay.com/fkx18247u7zrmypdwnk2ud0`（对照组：现有 `donate-alipay.jpg` 在 180px 就已解不出，新图更耐缩放）。**排版按新版参考图 `@赞助.png` 重测**：卡 192×197 → **198×198**、卡间距 23 → **16**、`_CARD_Y` 67 → **66**，左缘**不再按总宽居中取整**而固定 `_CARD_X = 16`（`(657-3*198-2*16)/2 = 15.5` 取整得 15，会让整排码比下面榜单框 `_RANK_LEFT_X=16` 左移 1px，参考图里两者左缘严格对齐）；实测三卡 x=16/230/444 与参考图逐像素一致。**取图用 `getattr(resources, name, "")` 兜底**而非直接取属性（新增 `_donate_icons()`）：旧资源对象与测试替身可能还没有第三个属性，缺图时显示「二维码加载失败」占位而不是抛异常，且槽位数恒为 3、后面几张码不会因前面缺图而整体错位。`tests/conftest.py` 的 `_ICON_ATTRS` 同步补 `donate_redpacket_icon`；新增 `tests/test_donate_window_cards.py`（5 条）钉死槽位数、三卡几何、左缘对齐与缺图降级

### 界面调整

- **「下载」页两行复选框严格上下对齐：「下载」行 7 项逐项钉到「保留旧文件」行同位项**（`main_window.py` 新增类常量 `_XIAZAI_ROW_ALIGN_PAIRS` 与 `_sync_xiazai_row_align()`，钩子装在下载滚动区 `scrollArea_6` 的 `_post_wide_sync_hook` 上并在 `_sync_page_layouts()` 末尾再调一次）：用户反馈「压缩」页的复选框要向下与上方「保留旧文件」严格上下对齐，「保留旧文件」的位置保持不变（最小化与最大化两个态都要）。**根因是两项均分的布局 + 项数不同**：`下载`（`groupBox_24` / `horizontalLayoutWidget_14` / `horizontalLayout_16`）7 项、`保留旧文件`（`groupBox_33` / `horizontalLayoutWidget_18` / `horizontalLayout_23`）8 项，第 7 项文案还不同（「压缩」对「剧照副本」，其后另有「主题视频」）。`QBoxLayout` 在无 stretch、无 expanding 项时把余量**均分**给各项，第 k 项左缘 = 行首 + Σ(前 k 项自然宽 + spacing) + k·余量/项数，于是项数少的那一行每一项都落在 8 项那行的右侧——实测逐项偏 **+6~+160px 且越往右越多**（600 宽 +6~+34、900 宽 +7~+52、1032 宽 +12~+69、1200 宽 +14~+83、1500 宽 +20~+115、1920 宽 +27~+160），正是截图里「越往右偏得越开」的形状。**「压缩」对应「剧照副本」是用户截图红框指定的位置**；「封面图」是两行共同的首项、x 天然同位，实测各宽度偏差恒 0。**为什么宽度也必须一起跟**：只 `move` x 的话左邻仍停在自己的布局位置上，而被拉宽的控件里画的是**左对齐**文字——实测窗口 1200 宽时「压缩」被移到 671，左邻「nfo」的控件在 644、文字画到 687，**字形直接压在一起**（1200/1500/1920 各压 16~28px）。把宽度也重钉成参照行同项宽度后，每项右缘正好止于下一项左缘（那正是参照行自身的排布），极窄窗口下文字被裁的宽度也与参照行一致，**各宽度字形重叠实测恒为 0**。**纵向一字未动**：两个行容器在 content 里同 x=90、同高 31，两行复选框同高 17，只重钉 x 与宽，`y`/高度全部交给各自布局。**只向左**：两行首项同起点、下载行项数更少，实测每一项的目标 x 都在自身当前位置左侧（偏差恒为正），故本改动在任何窗口宽度下都是左移。**对齐量必须经公共祖先 content 归一后比较**——两个复选框分属不同 `groupBox`，直接比 `widget.x()` 拿到的是「相对各自行容器」的局部坐标，会把真偏差算成 0（与 `verify_actor_mapto` 同一坑）。**挂在拉伸之后的钩子上**：通用宽幅同步会把两个行容器按「设计宽 + extra」拉宽并 `invalidate+activate()` 重排，钩子跑在其后才是终态几何，同一拍完成、不会被绘制出「先在右边、再向左跳」的中间态；**休眠页直接 return**（量到的是陈旧几何），由切 tab 的 `showEvent` 补齐。**未动**：`.ui` / `MDCx.py`（`MDCx.py` 禁止手改且有 `test_mdcx_py_in_sync_with_ui` 钉死）、「保留旧文件」行自身几何、各控件的勾选状态与信号连接、末项「主题视频」
- **刮削番号「数字」项提示补上 `-3`**（`MDCx.ui` `label_349`「数字，-1、-2」→「数字，-1、-2、-3」）：只改 `.ui` 源文件，再按 `tests/test_ui_structure.py::test_mdcx_py_in_sync_with_ui` 的流程用 pyuic6 相对路径重编译 + `ruff format` 生成 `MDCx.py`（**不手改 `.py`**），重编译产物与仓库版逐行比对确认**仅此一行差异**，即两文件同步无其他漂移
- **最小化（还原）状态下「点击下载字幕包」左移到与「视频文件名」严格上下对齐**（`main_window.py` 新增类常量 `_ZIMU_LINK_ALIGN = AlignLeft|AlignVCenter`，`_sync_zimu_row_align()` 的窄态分支改用它，宽态分支改引用同一常量、行为不变）：用户反馈「软件设置-字幕最小化时将点击下载字幕包向左移动到与视频文件名严格上下对齐的位置，视频文件名位置保持不变，最大化时页面、布局、控件、提示词等等均保持不变」。**根因不是控件位置而是文字对齐**——下载行 `horizontalLayout_10` 是「两项均分布局」，窄态下提示文字「下载字幕包解压，填写字幕文件目录的路径」与链接同行均分，链接格子被拉到 84~250px 宽；格子左缘本就与「视频文件名」（`checkBox_filename`）左缘同位（同宽时实测 content 坐标都是 433），但 `label_download_sub_zip` 的设计态是 `setAlignment(AlignCenter)`（`.ui` 生成代码 `MDCx.py` L7951，**未改**），把可见文字整体右移了 `(格子宽-文字宽)/2`——用户环境格子约 200px、文字 105px，右移约 47px，看上去就「比视频文件名右移一大截」。改左对齐后可见文字左缘 == 链接格子左缘，两行同位时即严格对齐；**全程不移动任何控件、不改提示文字、不动 `.ui`**（文字位置以外的几何零变化），最大化态一字未改。**残留残差不修，几何上无法两全**：「视频文件名」行（`groupBox_20` 里的 `gridLayout_17`/`horizontalLayout_26`）也是两项均分，其第二项起点 = 行首 + 半行宽；而下载行第二项起点 = 提示词自然宽 + 间距。窗口够宽时两者相等 → 严格对齐（本仓默认字体 Sans Serif 9pt / offscreen 96dpi 实测窗口 ≥ 1000px 残差 **0**，含用户截图的 1014x730）；更窄时提示词宽于半行宽（`2*228+6 > 行宽`），链接格子只能停在提示词右侧，残差 19~49px（800/900/950 宽实测 49/44/19）。要消除它只能压窄提示词（用户明确要求不动提示词）或让链接压住提示词，两者都拒，故保留残差并在测试里逐值锁定。**注意**：早先用独立离屏探针脚本量的字体度量（提示 133px / 链接 49px）是错的，本条所有数字取自 pytest 环境（裸 `QApplication` 默认字体，实测提示 228px / 链接 84px / 行高 12，与用户截图的链接 105px 物理像素吻合）
- **演员管理器字体整体放大一号（随系统字号浮动，缺省 9pt → 10pt）**：主窗与「设置 / 数据源测试 / 演员详情 / 选择媒体库」四个子窗口内的**全部**控件（按钮含「设置」「清空缓存文件夹」「数据源测试」、输入框、各下拉、演员表格、统计标签、运行日志、状态栏、灰色提示文字）统一大一号，看不清的问题一并解决。**例外只有左上角窗口标题「Emby/Jellyfin演员管理器」与设置窗口标题「Emby/Jellyfin 演员设置」**——这两处由系统窗口框绘制，样式表天然不覆盖，无需额外排除代码（测试把两条标题文案钉住，防止有人改用「换标题」绕开）。实现上新增模块级 `_FONT_SIZE_STEP = 1` 与 `_ui_font_pt()`，`EmbyActorManagerDialog._load_stylesheet()` 的**首条规则**改为 `QWidget { font-size: Npt; }`。**为什么走 QSS 而不是 `setFont()`**（离屏实测，`QT_QPA_PLATFORM=offscreen` 默认字体 9pt）：① `setFont` 只对**子控件**生效——`QDialog(parent)` 是独立顶层窗口，Qt 对顶层窗口不走父控件字体继承，故「设置 / 数据源测试 / 演员详情 / 选择媒体库」四个子窗口实测仍是 9pt；样式表则沿 QObject 父子链级联，实测四个子窗口内的 QLabel/按钮/表格/编辑框全部 10pt。② QSS 的 `font-size` 本就优先于控件字体（`donate_window` 早前已踩过这条坑）。**基准不写死**：`QApplication.font()` 取应用默认字号 +1，系统改字号时跟随浮动；应用若用像素字号（`pointSize <= 0`）按 96dpi 折算成磅值，两者都取不到才回落 9pt。**两处必须跟着改的配套项**：① 灰色提示文字「使用说明：①…」「双击行可编辑」原本在控件自身样式表里写死 `font-size: 12px`——**控件自身样式表优先级高于对话框样式表，会把放大后的字号盖回 12px**，故改为只留颜色；② 「使用说明」这行单行长文本开启自动折行：不折行时它的 `sizeHint` 就是整个对话框的最小宽度（放大后 1128 → 1222px），1280 宽的小屏会被撑出屏外；折行后最小宽度回到按钮行决定（对话框 `minimumSizeHint` 1266 → **1207px**，放大前为 1172px），且窗口宽 ≥1280 时实测仍单行显示（标签高 17px 一行，仅 1207 及以下才折成两行）。**未动**：表格定宽列 `_FIXED_COLUMN_WIDTHS`（被 `test_main_window_startup` 钉死，放大后「出生日期」表头仍远小于 110px 列宽）与获取模式下的拉定宽 220px（放大后 `sizeHint` 199px < 220px，仍不裁字）；`QWidget` 规则只带 `font-size` 不带 `font-weight`，分组框标题加粗保留（实测 `bold=True`）
- **软件界面左侧导航栏背景色统一为「软件设置」页的 `#EEF3FF`**：此前主界面用 `#F5F5F6` + `#EDEDED` 边框、设置页用 `#EEF3FF` + `#D8E2FF`，来回切页时侧栏底色会跳变。现 `main_window.py::pushButton_main_clicked()` 与 `pushButton_setting_clicked()` 完全一致，`style.py` 的 `QWidget#widget_setting` 同步改 `#EEF3FF`，消除 `left_backgroud_widget` 未覆盖处的露底断层；暗黑模式分支未动
- **赞助窗口按参考截图 1:1 复刻版式、字体与配色**：客户区 `657×637`，背景 `#F0F0F0`；全部子控件绝对定位，坐标直接取自参考图像素。三处关键取证：① 参考图是 **125% DPI 截图**（标题栏高约 40px、客户区 657×637 是**设备**像素），换算 `logical_x = ref_x / 1.25`、`logical_y = (ref_y - 40) / 1.25`；② 正文是**微软雅黑**而非宋体（早先误判成宋体，见下一条）；③ **Qt 样式表会覆盖 `setFont()`**，`_style_dialog()` 改用 `QPalette`（Window/WindowText）+ `setAutoFillBackground(True)` 且必须在 `_build_ui()` 之前调用，`_label()` 的文字颜色也走 label 自己的 `QPalette`。字号按「墨迹宽 + 墨迹高」双指标标定（`_FONT_SPECS`），行距与列落位照抄参考图：行距 28.8 vs 28.78、金额列右端 308.9 vs 309
- **赞助窗口字体与字号（历次 7 轮调整合并为一条，终态：微软雅黑常规体 / 说明行 19px · 灰色小字 14px · 榜单标题 16px · 数据行 13px · 底部一行 16px）**：
  - **字体判定**：参考图 `001.png` 字形无衬线、字面率高，实为**微软雅黑**而非宋体（早先误判）。用真实控件管线（`DonateDialog.grab()`，125% DPI 下 821×796 设备像素）与参考图**整行**做位移搜索 IoU：Microsoft YaHei 11px 得 0.8934 断层第一（SimHei 0.8295 / Microsoft JhengHei 0.8173 / DengXian 0.8053 / SimSun·NSimSun·Tahoma·Segoe UI 均 0.5734 / FangSong 0.5386 / KaiTi 0.4551），放大目视也无宋体衬线、数字 `1` 无底衬。雅黑与「Microsoft YaHei UI」度量完全一致、两者可互换；非 Windows 平台无此字体会自动回退到系统默认无衬线字体
  - **为什么走 `QPalette` 而不是 `setFont()`**：**Qt 样式表会覆盖 `setFont()`**，`_style_dialog()` 改用 `QPalette`（Window/WindowText）+ `setAutoFillBackground(True)`，且**必须在 `_build_ui()` 之前调用**；`_label()` 的文字颜色也走 label 自己的 `QPalette`
  - **字号标定方法**：「渲染真实控件 → 与参考图逐行量墨迹 bbox」。参考图 dpi 元数据 119.99 ≈ 125%，其字号是**设备**像素，本窗是**逻辑**像素，故 `geometry()` 与 `grab()` 之间必须 ×dpr 换算；判墨迹用 `min(R,G,B)<=140` 逐像素扫行带
  - **终态字号**（`_FONT_SPECS`，全部微软雅黑**常规体 weight 400 / 非粗体**）：`intro`（顶部说明行）**19px**、`hint`（灰色小字「您的支持是我最大的动力…」）**14px**、`rank_title`（新人榜/土豪榜 Top10）**16px**、`row`（数据行）**13px**、`footer`（底部一行「官方交流群…」）**16px**；行距：intro +2% 字距、其余 0
  - **调整轨迹（7 轮，含两处主动偏离参考图与一处撤销）**：①**初标**：按墨迹对齐参考图取 `intro` 15 / `hint` 11 / `rank_title` 14 / `row` 13 / `footer` 13——**其中 `rank_title`/`row` 的基准在②④两步被主动上调，`hint` 的基准被②③两步上调**；②**「三行整宽文字定字号」**：`intro` 15→**19**（字距仍 +2%）、`hint` 12→**16**、`footer` 13→**16**。判据是 `QFontMetrics.horizontalAdvance(整行) ≤ _DIALOG_W(657 逻辑像素)`——超宽就折行、并被固定高度（`_INTRO_H=36` / `_HINT_H=28` / `_FOOTER_H=34`）裁掉，故每行各有独立上限：`intro` 19px → 588（余 34；上限 21px=650，22px 起 681）、`footer` 16px → 569（余 44；上限 18px=640，19px 起 675）、`hint` 16px → 624（余 17，**该行 39 字、17px 起 663 就超宽**，所以「比说明行小一号」= 18px 在此行放不下，16px 即其上限）。中间态曾按「放大到单行极限」取 21/12/18、再按「缩小一号」取 20/10/17，均因用户反馈太小/太大而调整；③**灰色小字「改小两号」16→14**：中文字号阶梯三号 16 → 小三 15 → 四号 14，用户要「小两号」即落到四号 14px（**此前取 16px 是被「单行不折行」的上限顶住的结果、并非用户的目标值**）。缩小不引入折行风险：`horizontalAdvance` 624 → **546**（左右留白 16.5 → 各 55.2），仍单行居中；④**榜单标题「与底部一行完全一致」14→16**：`rank_title` 现与 `footer` 同为雅黑 16px 常规（weight 400 / letterSpacing 100 即 0%）。**这是偏离参考图的主动改动**——14px 是①按墨迹对齐参考图标定的基线，用户实测后判定偏小；同批的 `row` 13px 未动（用户只点名标题与底部一行对齐）；⑤**三处加粗**（说明行 / 底部一行 / 两个榜单标题置 `bold=True`，灰色小字与数据行保持常规）：**⑤已于⑥撤销，仅留作过程记录**；⑥**撤销加粗**、五行最终全部非粗体，与①的原始标定结论「参考图正文无粗体」一致。**依据**：雅黑里加粗几乎只改观感不改版式——CJK 的 advance 恒等于像素数（实测「赞」在 14/16/19px 下常规与粗体都是 14/16/19），只有含拉丁字母的部分变宽（`MDCx` 43→49 @14px、47→49 @16px、55→58 @19px），故加粗版与常规版**都不会引起折行或裁字**，撤销同样安全
  - **撤销后的逐行实测**（`QT_QPA_PLATFORM=windows`，125% DPI）：advance `intro` **569**（单行上限 21px=629，22px 起 659 折行）/ `hint` **546**（上限 16px=624，17px 起 663）/ `footer` **569**（上限 18px=640，19px 起 675）/ `rank_title` **95**；墨迹（`grab()` 821×796 设备像素，行带 clamp 到图内判 `min(R,G,B)<=140`）`intro` 568.8×18.4（711×23）/ `hint` 546.4×15.2（683×19）/ `footer` 568.0×16.8（710×21）/ `rank_title` 94.4×17.6（118×22），四行行内无空断（确为单行），`lineSpacing` 25/19/21/21 ≤ 各自 label 高 36/28/34/28。**`rank_title` 墨迹比 `footer` 高 0.8 是字形差异不是字号差异**——「Top10」里字母 `p` 有降部、纯汉字的底部一行没有，两者字号/字体完全相同
  - **连带影响 `rank_title` 底色块**（不透明块，用来在文字两侧截断框的上边线）：宽度 = `horizontalAdvance + _RANK_TITLE_PAD_R`，83+4=87 → **95+4=99**，右缘由 框左+99 移到 **框左+111**（框宽 309，仍余 198，框右与竖线均不受影响）；上边线可见段变为 框左..框左+12 与 框左+111..框右，截断效果不变。标题带 `_RANK_TITLE_DY=-11` + `_RANK_TITLE_H=28` 覆盖 y 272..300，表格自 y=301 起，互不相交
  - **顺手更正两处陈旧注释数字**：`intro` advance 原写 588（实为旧文案 36 字时的值，现文案 35 字 = 汉字 26 + 拉丁/数字/空格 9 → **569**）、`rank_title` 墨迹原写 82.4×15.2（那是 14px 时的值，16px 应为 94.4×17.6）、`hint` 该行共 **39 字**（上一轮误记 38 字，16px 时 39×16=624 与实测一致）
  - **四个坑**（沿用本条各轮）：① `_FS_ROW` 是模块级常量，改 `_FONT_SPECS["row"]` 不会改变表格字号（QSS 用 `_FS_ROW`），量测时须同步改；② 墨迹行带的 y 区间必须 clamp 到图像高度内，`QImage.pixelColor()` 越界返回无效 `QColor`(0,0,0)，会被 `min(R,G,B)<=140` 判成墨迹而量出「整行满宽」的假数据（`_FOOTER_Y + _FOOTER_H = 639` 已超出客户区 637）；③ 中文指令里的「号」是中文字号阶梯（初号/小初/一号/…/三号 16px/小三 15px/四号 14px），不是「px 数」，实测后要按阶梯换算再落值；④ 「这个字看起来比那个小」的读数未必是尺寸差——见下方「修复」条 `[赞助作者]` 的墨迹密度结论
- **榜单去掉「微信支付 / 支付宝付款」标题，卡片改为纯白无边框方块**：与参考图一致（卡片只是白方块直接放在灰底上，无圆角无描边）
- **榜单框内不画横线与竖线**：`QTableWidget` 设 `showGrid=False` + `NoFrame` + 隐藏表头 + 关闭滚动条，只保留 1px `#DCDCDC` 外框；10 行全是数据行（参考图无表头），列对齐为用户名左 / 日期时间居中 / 金额右
- **榜单标题框线在字体两侧截断**：标题改为**不透明底色块**（`QPalette` 设 `Window` = 底色 + `setAutoFillBackground(True)`），宽度按 `QFontMetrics.horizontalAdvance()` 只包住文字，不再拉满整条边线。**坑**：底色块左缘最初对齐框左（`_RANK_TITLE_DX=0`），把左竖线在标题带内整段盖掉了；逐像素探针打印才发现参考图的左竖线在标题带内是完整的、只有上边线被遮，故底色块必须内缩（`_RANK_TITLE_DX=12`）。实测左框上边线 16..27 可见 → 28..133 截断 → 134 起恢复（参考 16..24 → 137 起恢复），四角与左竖线均完整
- **赞助窗口从 524×509 放大到整窗 657×677**（参考截图的实际大小）
- **收款码与 `[赞助作者]` 改为底部锚定，随窗口高度下移**：此前二维码块顶对齐在导航区下方，多余空间全落下方，而状态文字在矩形内是 `AlignBottom`（矩形越高文字越靠下），两边叠加导致最大化时「`[赞助作者]`」与「正常模式·字段优先」的间距从 17px 暴涨到 **331px**。现改为从状态文字往上倒推（`status_bottom → text_top → link_bottom → qr_bottom`），间距恒定。新增 `_dock_status_text_h()` 按字体度量算状态文字块高——**坑**：`show_scrape_info()` 构造的文本以 `\n` 开头（`f"\n{scrape_info}…"`），那一行是空的、只在块顶部留白而无墨迹，不扣掉会多算一整行高（间距变 31.6 而非 17）；且文案行数随刮削进度变化、还有 `\n` ↔ `<br>` 两种写法，故必须动态算不能写死。实测各高度间距恒定（`_DONATE_TEXT_GAP`，后续由二维码放大需求收窄到 10）
- **二维码边长恒定 180、两侧固定留 15px**（原 168 / 留白 21）：按「默认窗口下二维码尽量大」倒推高度预算 `avail = 198 − max(TEXT_GAP, PAD + STATUS_H_MIN − text_h) − LINK_GAP − PAD`（198 = `status_bottom 690 − text_h 60 − LINK_H 22 − nav_bottom 410`），把三处缝隙收窄——二维码↔链接 `_DONATE_LINK_GAP` 6→**2**、与导航/状态区内边距 `_DONATE_PAD` 6→**2**、链接↔状态文字 `_DONATE_TEXT_GAP` 17→**10**——得 `avail = 198 − 14 − 2 − 2 = 180`。**没有下移状态文字**：实测默认窗口（1030x700）下状态文字底边只剩 10px 余量，再下移会被窗底裁掉；而收窄缝隙是零代价的（`gap` 的另一个来源 `STATUS_H_MIN + PAD − text_h` 也随 `_DONATE_PAD` 一起下降）。`_DONATE_QR_SIZE=180` **必须等于默认窗口下的实测 `avail`**，否则两态留白会不一致：上限小于它则最大化时涨不上去、大于它则最大化时涨到上限而留白变小（实测上限 176 时最大化留白 17px 而还原 21px，**差 4px**，175 这类奇数边长还会左右差 1px）。只在窗口比默认更矮时才等比缩小（下限 `_DONATE_QR_MIN=40`）。实测 693 / 700 / 737 / 800 / 816（最大化） / 1080 / 1170 / 1200 全区间左右留白恒为 15px；理论上限 186（`PAD`/`LINK_GAP` 全 0 时），再大就必须牺牲状态文字位置或留白

- **最大化时微信码上方新增一张支付宝收款码**（`resources/Img/donate-alipay.jpg`，宽度与微信码**严格一致**，由同一个 `qr_size` 驱动）——**并修掉「最大化后界面没变化」的时序 bug**：`changeEvent` 收到 `WindowStateChange` 时原先只 `QTimer.singleShot(0, self._sync_page_layouts)`，侧栏那条链没走；而窗口管理器最大化时**先发尺寸、后发状态标志**，`resizeEvent` 那一拍 `isMaximized()` 还是 `False`，于是支付宝码在 `resizeEvent` 里被判为不显示、之后状态位虽已生效却再没人重算侧栏，用户看到的就是「最大化没变化」（用户实测反馈）。现补 `QTimer.singleShot(0, self._sync_dock_layout)`，状态位可靠后重算一次即可出现——同一文件里 `_actor_page_stretch_extra` / `_scroll_stretch_extra` / NFO 隐藏入口等处早就因为同一个时序坑改用「几何拉伸量」判态，侧栏这条链是漏网的一条：控件 `label_donate_alipay` 同样走运行时注入（`raise_()` 顺序 `qr → alipay → link`），受 `self.isMaximized()` 门控——**非最大化一律不显示，侧栏其余一切（控件顺序、提示词、间距、状态文字）保持原样不变**。摆放 `alipay = [qr_bottom − 2s − PAD, +s]`、`qr = [qr_bottom − s, +s]`，即微信码下沿不动、支付宝码填上方空隙；等宽约束由 `qr_bottom − 2s − PAD ≥ nav_bottom + PAD` 推出 `s ≤ (qr_bottom − nav_bottom − 2*PAD) / 2`，实现里再压到 `_DONATE_QR_SIZE` 上限——**不能只按几何算**，否则最大化会变成满宽 210 / 留白 0，与普通窗口的 180 / 留白 15 不一致（第九轮反馈过这类两态不一致）。三级降级：够放两张 `_DONATE_QR_SIZE` 就都保持设计边长 → 不够则**两张一起等比缩小**到能放下的最大边长（不能像最初写法那样让支付宝码独自缩成一条缝，那样屏上扫不出来）→ 连 `_DONATE_ALIPAY_MIN=90` 都放不下则只显示微信码、且微信码仍为 `_DONATE_QR_SIZE`（不因多一张码而缩小）。缩放结果按边长缓存（`_donate_alipay_cache` / `_donate_alipay_cache_size`），拖窗口不重复解码 980×980 源图；`_hide_donate()` 一并纳入该控件。实测最大化（窗口 1536×793、`availableGeometry()` 816）得 `alipay=(45,413,120,120)`、`qr=(45,535,120,120)`：同宽同列、padL=padR=45、支付宝顶 413 ≥ 末个导航按钮底 376（不压导航）、四组包围盒重叠均为 0；`showNormal()` 还原后支付宝码重新隐藏、微信码回 180 / 留白 15（双向幂等）。非最大化 693 / 700 / 737 / 900 / 1080 / 1200 六档实测微信码恒 180 / 留白 15 且 `alipay.isHidden()`，与改动前逐值一致
- **`[赞助作者]` 字号提到 16px**：见下方「修复」条的实测结论

### 修复

- **`[赞助作者]` 看起来比「软件设置 / 使用说明」小**：先按「某个控件没跟着 125% 缩放」排查，**实测证伪**——`font().pixelSize()` 两侧都是 14，`font().family()` 都是 `Consolas`、`horizontalAdvance('赞')` 都是 14，14px 时两侧墨迹高**完全相同**（都是 13.60 逻辑px）。真实差异是**墨迹密度**：`QPushButton` 走 `QStyle::drawItemText` + CJK 回退，`QLabel` 走 `QTextDocument`，同一 14px 解析出的实际字形不同——按钮 ink 487 / density 0.409，链接 ink 427 / density 0.364（**少 12%**），放大后肉眼可见链接汉字笔画明显更细，故读成「字更小」；链接的浅蓝 `#0078D7` 也比按钮的纯黑淡，进一步压低视觉重量。又做了 A/B 排除富文本：同一 QLabel 纯文本 vs `<a href>` 包裹逐像素一致（427/427），**富文本不是原因**。处理：字号提到 16px（w=63.2 比按钮 56 宽 13%、h=16.0 比按钮 13.6 高 18%，肉眼可辨「不小于」），`style.py` 明暗两处 `widget_setting` 样式表新增 `QLabel#label_donate_link{font-size:16px}`——**注意 `QLabel.setFont()` 会被样式表覆盖失效**（实测 `setFont(QFont(px=16))` 后 `font().pixelSize()` 仍是原值），只有 QSS 或富文本内联 `font-size` 起作用，故 `_style_donate_link()` 只管颜色、字号统一交给 QSS
- **wiki UA 两个用例断言失效**：`tests/test_wiki_rate_limit.py::test_wiki_headers_use_identifiable_user_agent` 与 `test_search_wiki_sends_identifiable_user_agent` 断言 UA 里必须含 `"mdcx-diy"`，但 #183 已把仓库从 `cdlongbow/mdcx-diy` 换成 `z291173301/MDCx`，这两个断言是当时漏改的旧字面量。改为断言 `mdcx.consts.GITHUB_REPO`（单一来源），以后再换仓库不会失效；生产代码 `mdcx/tools/wiki.py` 的 `_WIKI_USER_AGENT` 未动

### 测试

- **新增 `tests/test_window_state_matrix.py::test_xiazai_download_row_aligns_to_keep_old_row`（参数化 6 档窗口尺寸）+ `test_xiazai_row_align_idempotent_and_survives_tab_switch` + `test_xiazai_row_align_hook_installed_on_scroll_area`**（下载页两行复选框对齐回归，模块级新增 `_XIAZAI_ALIGN_PAIRS` 映射表）：① 参数化 600x600 / 700x620 / 900x700 / 1032x737 / 1500x900 / 1920x1170 六档（覆盖最小尺寸、用户默认尺寸、宽态两端），逐项断言 `mapTo(content)` 归一后 **`dx == 0`**（严格上下对齐）**且 `width` 与参照行同项相同**（宽度不跟就会与左邻字形重叠，见界面调整那条），并断言高度未被改动（纵向零变化）；② 逐档断言**相邻两项字形不重叠**（前一项可见内容右缘 ≤ 后一项左缘），把「宽度必须一起跟」这条钉死——只对齐 x 的实现会在这里失败；③ 幂等（连跑三次 `_sync_xiazai_row_align()` 几何逐值不变）+ 休眠页不动（切到别的 tab 后改窗口尺寸，本页几何逐值不变）+ 切回下载页同拍完成对齐（断言对齐不变量，且切回后再 `_sync_page_layouts()` 几何逐值不变、无跳帧残留）；④ 钩子安装断言：按**内容控件名** `scrollAreaWidgetContents_xiazai` 认出滚动区（不写死 `scrollArea_6` 对象名）且 `_post_wide_sync_hook` 正是 `_sync_xiazai_row_align`、`win._xiazai_scroll` 指向它、映射表与测试侧一致（含「压缩」对「剧照副本」）。**顺带修掉一处既有的 `NameError` 隐患**：`test_left_dock_adapts_to_large_ui_scale` 的断言消息里写的是裸 `_DONATE_TEXT_GAP`（应为 `win._DONATE_TEXT_GAP`），一旦该断言失败会抛 `NameError` 而不是给出失败信息（`ruff check` 的 F821）
- **回归结果**：`tests/test_window_state_matrix.py` **72 项全过**（含新增 9 项）；`ruff check` 对 `main_window.py` 与本测试文件干净。全量 `pytest tests --ignore=tests/crawlers`（`--ignore` 是因为 `tests/crawlers` 里有真实联网用例）**1970 passed / 3 failed / 1 skipped**，3 个失败全是既有的 `tests/test_scraper_remain_list.py`（`mdcx/core/scraper.py:396` 的 `TypeError`，早前任务已在干净树上复现过），1970 = 上次基线 1962 + 本次新增 8 个用例，无新增回归。会话收尾的 `Windows fatal exception: access violation` 为既有问题（崩在 `conftest.py::pytest_sessionfinish`，与改动无关）
- **新增 `tests/test_window_state_matrix.py::test_zimu_download_link_aligns_to_filename_when_narrow`（最小化态链接对齐回归）**：遍历 800 / 900 / 950 / 1000 / 1014 / 1030 六档窗口宽，① 断言窄态链接文字对齐恒为 `AlignLeft|AlignVCenter`——这是修复本体，回到 `AlignCenter` 立即失败；② 断言可见文字左缘 == 链接格子左缘 == 「提示词右缘 + 间距」，即**不留任何居中偏移、也不额外右移**；③ 断言提示词 `minimumWidth/maximumWidth` 仍是 `(0, 16777215)`、下载行仍是 2 项（不钉宽、不插间隔项），确保本次改动没碰提示词与布局；④ **残差逐值锁定**（800→49 / 900→44 / 950→19 / 1000→0 / 1014→0 / 1030→0 px），把「≥1000px 严格对齐、更窄时残差 = 不截断提示词的最小残差」这条契约钉死；⑤ 同尺寸反复 `_sync_page_layouts()` 几何逐值不变（幂等）；⑥ 宽态（1920×1170）链接仍与文件名同位、下载行仍是 3 项，往返回窄态后 9 项快照逐值复原。**另给既有的 `test_zimu_rows_align_to_filename_when_wide` 补两处窄态断言**（窄态基线处 + 宽态往返后各一次：链接文字左对齐且与「视频文件名」左缘同位、「视频文件名」自身几何不变），原断言 `link.alignment() == base["link_align"]` 改为显式比对 `AlignLeft|AlignVCenter`——否则基线本身随实现漂移，回归钉不住
- **新增 `tests/test_actor_manager_font_size.py`（10 项，演员管理器字号放大回归）**：① `_ui_font_pt()` = 应用默认字号 +1 且带 `pt` 单位（不是写死绝对值）；② 主窗 14 类代表控件（连接/数据源测试/清空缓存文件夹/设置/同步按钮、三个下拉、两个输入框、演员表格、运行日志、状态栏、统计标签）字号全等于放大后的磅值；③ 两处灰色提示文字样式表里**不得**出现 `font-size`（控件自身样式表会盖回 12px）且实际字号已是放大值；④ 分组框标题保持加粗（`QWidget` 规则不得带 `font-weight`）；⑤ 样式表必须含 `QWidget { font-size: Npt; }` 规则——这是四个子窗口能继承到放大字号的唯一机制（改回 `setFont` 立即失效）；⑥ 参数化 4 项覆盖「设置 / 数据源测试 / 演员详情 / 选择媒体库」子窗口内的 QLabel 字号（`ActorDetailDialog` 用 `has_image=False` 的演员构造，测试不触网）；⑦ 两条窗口标题文案保持原样（对应用户点名的不放大项）
- **回归结果**：`pytest -k "actor or emby"` 全过（含新增 10 项）；会话收尾的 `Windows fatal exception: access violation` 为既有问题——`git stash` 后在干净树上跑同一命令同样复现（崩在 `conftest.py::pytest_sessionfinish` 的后台线程收尾，非本次改动引入）
- **新增 `tests/test_window_state_matrix.py::test_donate_block_is_centered_and_keeps_text_gap_at_any_height`**：遍历 693 / 700 / 737 / 900 / 1080 / 1200 六档窗口高（含实际默认高度 693 与最大化高度），断言二维码左右留白相等（奇数边长差 ≤1px）、`qr.width() <= _DONATE_QR_SIZE`、高度 ≥ 默认窗口时 `qr.width() == _DONATE_QR_SIZE` 且 `pad_l == (side_w - _DONATE_QR_SIZE) // 2`；并断言「`[赞助作者]` 底边到状态文字首行」的间距**与二维码左右留白**都跨高度**恒定**（这两条正是用户两次反馈的回归点）、间距 ≥ `_DONATE_TEXT_GAP`；文字在矩形内底对齐，故文字顶 = 矩形底 − `_dock_status_text_h()`；三者包围盒两两不相交
- **新增 `tests/test_window_state_matrix.py::test_donate_alipay_qr_only_appears_when_maximized`**：① 非最大化时支付宝码隐藏、微信码可见且不超过设计边长并居中；② `showMaximized()` 后支付宝码出现，与微信码**同宽同列**（`alipay.width() == qr.width()`、x 相同）、边长在 `[_DONATE_ALIPAY_MIN, _DONATE_QR_SIZE]` 区间、排在其上方且顶边不低于导航容器底（不压「使用说明」）、与微信码/链接/状态文字两两不相交；③ `showNormal()` 还原后支付宝码重新隐藏、微信码恢复居中（双向幂等，用 `try/finally` 保证异常路径也会还原）。**顺带修掉两处环境相关的绝对值断言**：本文件 `win` fixture 把 `set_style` stub 成 lambda，QSS 的 13px 不生效，`_dock_status_text_h()` 得 64（真实运行 60）使测试环境可用高度比真实运行少 4px，故 `qr.width() == _DONATE_QR_SIZE` 这类写死绝对边长的断言在本环境必然失败；已改为断言 `qr.width() <= _DONATE_QR_SIZE` + `qr.x() == (side_w - qr.width()) // 2`（居中，与字体无关），**真实边长由 `pads` 的跨高度恒定性保证**——边长一旦随窗口高度变化，左右留白必变

- **两个旧用例的断言从「写死实现细节」改为「断言不变量」**：`test_left_status_badges_follow_window_bottom` 原断言 `label_show_version.y() == 929`（依赖 201 高的矩形，底对齐锚定后矩形高随文案行数变化），改为断言底边贴底 `status.y() + status.height() == height - _DOCK_STATUS_BOTTOM_PAD`；`test_left_dock_adapts_to_large_ui_scale` 的导航设计态断言（`spacing()==8` / `height()==40` / `y()==index*48` / `[0,48,96,…]` / `1170-201-40`）全部改为从 `_DOCK_*` 常量推导（`step = _DOCK_NAV_BTN_H + _DOCK_NAV_SPACING`），以后再调设计不必改测试
- **回归结果**：UI + wiki 六个套件（`test_window_state_matrix` / `test_ui_geometry` / `test_ui_structure` / `test_left_status_icons` / `test_main_window_startup` / `test_wiki_rate_limit`）**105 项全过**；全量 **2399 passed / 6 failed / 5 skipped**，6 个失败与改动前完全相同（3 个 `tests/crawlers/test_aventertainments.py` 联网 curl 35 Connection was reset、3 个 `tests/test_scraper_remain_list.py` 的 `fake_clean_empty_folders() got an unexpected keyword argument 'allow_empty'`），均为预先存在的问题，无新增回归

### 文档

- **`docs/Development.md` 新增两节界面取证规范**：① 「『这个字看起来比那个小』——高 DPI 下字体大小问题的取证顺序」8 条（先量 `devicePixelRatio()` 别猜；QSS 的 `font-size: Npx` 是逻辑像素会被 dpr 自动缩放，「没缩放」这个假设通常是错的；别只看 `font().pixelSize()`，要 `grab()` 取设备像素图逐像素判 `min(R,G,B)<=140` 量墨迹 bbox，且 `geometry()` 是逻辑、`grab()` 是设备必须 ×dpr 换算；区分**尺寸**与**墨迹密度**；同尺寸不同密度 ⇒ 字体回退/渲染路径差异；别把富文本当嫌疑人除非做过 A/B；颜色也改变视觉重量；测字体必须 `QT_QPA_PLATFORM=windows`，offscreen 下 `QFontDatabase.families()` 返回 0 个字体、中文空白但截图「看起来正常」）；② 「离屏渲染校验流程（字体/几何类改动）」5 条（monkeypatch 掉联网/落盘副作用；**不要 stub `set_style()`**，否则 QSS 从不生效、`font().pixelSize()` 返回 -1；`resources.qtr` 指向真实 resources 否则走降级文本；遍历尺寸区间逐档断言几何并把关键档位 `grab()` 存 PNG 肉眼复核；断言落在不变量上而非写死 y 值）

## v2.2.3 (2026-10-06)

### 新增

- **软件设置-刮削模式-分离模式下方新增「为本地视频文件生成STRM链接文本」复选框**：位于分离模式正下方，与「删除本地已下载的图片和nfo文件」行上下严格对齐（col0 80px 空位 + col1 复选框；右侧绿色提示已按要求删除；主复选框右侧新增「覆盖本地已存在的STRM链接文本」复选框（`checkBox_separate_overwrite_strm`，同处 row=2 HBox 内主框右侧；对应配置项 `separate_overwrite_strm`默认 False、不勾选时已存在的 .strm 保留不覆盖；load/save 已接线并写入 JSON）。主复选框保持 HBox 首位、左缘与「删除本地已下载的图片和nfo文件」复选框严格上下对齐，并由 `tests/test_ui_structure.py::test_strm_checkboxes_text_order_and_alignment_locked` 锁定文案/行内顺序/行列位置/两行 col=0 同宽 80，任何移动改动都会导致测试失败。）。勾选后，分离模式下为视频刮削目录中的视频文件生成 STRM 文件：STRM 文件与封面图/缩略图/nfo 文件放在同一目录（即元数据镜像目录 `meta_folder`），文件名取 `naming_rule + .strm`，文件内容写入视频文件移动后的本地绝对路径及文件名（如 `D:\新建文件夹\JAV_output\…\SNOS-447.mp4`）。实现：配置项 `separate_generate_strm`（默认 False，旧配置缺键时不继承左侧、写入 JSON 配置、重启保持，`save_config.py` / `load_config.py` 接线）；`core/scraper.py` 在成功路径 `move_movie` 之后生成（判定函数 `extend.py: should_generate_strm()` 锁定：仅分离模式 + 已勾选 + `meta_root` 有效 + 非跳过整理时生效，正常/视频/更新/读取模式下即使勾选也不生成；视频模式自动跳过，写入失败只记日志不中断刮削）。`MDCx.ui` 改源 + pyuic 重生成 `MDCx.py`（`groupBox` 高 461→491、滚动区 2040→2070、后续各组下移 30px）。验证：`tests/test_separate_mode.py` 30 通过（含新增 `test_should_generate_strm_only_in_separate_mode`、`test_should_generate_strm_requires_flag_meta_and_reorganize`、`test_strm_flags_default_false_and_roundtrip`）；`tests/test_ui_structure.py` 新增 `test_strm_checkboxes_text_order_and_alignment_locked` 锁定 STRM 行位置；`tests/test_ui_structure.py` 仅 `test_read_mode_ui_texts_regression` 失败（干净树同样失败，预先存在、与本次无关）

- **软件设置-刮削模式-分离模式新增「复用数据存放目录中的元数据文件」「覆盖本地保存的视频元数据文件」复选框**：复用框位于 STRM 行下方独立一行（`checkBox_separate_reuse_meta`，`gridLayout_2` row=3），左缘与生成 STRM/删除行复选框严格对齐；覆盖框位于复用框同行右侧（`checkBox_separate_overwrite_meta`），与「覆盖本地已存在的STRM链接文本」框上下严格对齐（`_sync_reuse_meta_gap_align()` 按实测 x 差闭环收敛钉死，窄宽往返冻结），两覆盖框各右移一空格（STRM 行 spacing 10→14）。配置项 `separate_reuse_metadata / separate_overwrite_meta`（默认 False，写入 JSON，`save_config.py` / `load_config.py` 接线）。行为：仅分离模式生效（`extend.py: should_reuse_metadata() / should_overwrite_meta()`）；复用=目标已存在则跳过图片下载与 NFO 写入，覆盖=存在也重下重写。冲突处理：界面互斥（勾选其一自动取消另一；`load_config` 双开时以覆盖为准），运行时覆盖优先（复用跳过条件含 `not overwrite_meta`），手改 JSON 双 true 也不出现不确定行为，详见 `docs/Development.md`「分离模式元数据复用/覆盖与冲突处理」一节。验证：`tests/test_separate_mode.py` 新增 `test_should_reuse_metadata_only_in_separate_mode`、`test_should_overwrite_meta_only_in_separate_mode`；`tests/test_guaxiaomoshi_align.py` 新增复用/覆盖对齐与互斥测试；三套件（+`test_ui_structure.py`）全过

- **软件设置-刮削模式-分离模式右侧四个开/关开关正式生效**：此前右侧四组开关（分离模式刮削成功重命名文件 / 成功后移动文件 / 失败时移动文件 / 结束删除空目录）只是摆设——点选不保存、行为仍走左侧开关。现新增 4 个配置项 `separate_success_file_move / separate_failed_file_move / separate_success_file_rename / separate_del_empty_folder`（默认 True，与左侧一致），写入 JSON 配置、切换配置/重启后保持；`save_config.py` / `load_config.py` 接线右侧 8 个 radio。行为规则：① 分离模式（main_mode==2）下视频文件的移动/重命名/失败移动走**右侧**开关；② 视频刮削目录下的空文件夹清理永远走**左侧**开关；③ 数据存放目录下的空文件夹清理走**右侧**开关；④ 正常模式下右侧开关被忽略，一切走左侧。实现：`extend.py` 新增 `is_separate_mode()` + 4 个 `eff_*()` 生效值函数（非分离模式直接返回左侧值，故正常/视频/更新/读取模式行为与之前完全一致）；`base/file.py`、`core/file.py`、`core/scraper.py` 的移动/重命名/失败移动守卫全部改读生效值；刮削结束清理与手动清理在扫描目录传左侧值、在元数据根目录传右侧值。旧配置升级：JSON/ini 里缺这 4 个键时自动继承当时的左侧值（`Config.update()` 统一钩子），不是一刀切 True；一旦保存过，用户选择永久保留。`tests/test_separate_mode.py` 新增 9 项（生效值 mode 1/2 选择、`move_other_file` 遵从右侧关闭、存取接线锁、缺键继承左侧、缺键默认 True、已存在保留、JSON 往返），26 项全过

### 界面调整

- **刮削模式页四个组框标题右侧各加一条「分离模式…」提示**：分离模式刮削成功重命名文件 / 成功后移动文件 / 失败时移动文件 / 结束删除空目录，右对齐、字体颜色大小格式与标题完全一致（无本地样式表，全部继承）；右内边距与标题左内边距对称（windows11 风格下均为 14px）
- **四个组框右侧各加一对开/关按钮**：与左侧开/关水平齐平、四组严格上下对齐成一列；开/关二字在指示圈左侧；右侧离右边界与左侧离左边界各 50px 对称；每对包在独立容器里，与左侧互斥组隔离、互不干扰
- **三处绿色说明文案精简**：「刮削成功时，按照「视频文件名」重新命名」（去「对文件」）、「刮削成功时，不移动文件位置，仍在原目录」（去后半句场景说明）、「本地刮削成功的文件，按更新模式重新整理分类」（去「规则」）
- **读取模式与刮削网站页文案统一**：`可无需联网重新整理`→`可无需联网重新整理分类`；`按Emby标题、设置-翻译、NFO页设置利用本地nfo更新`→`按Emby标题、设置-翻译、NFO设置利用本地NFO更新`；`允许更新nfo文件/本地没有nfo的文件/本地nfo内有链接/本地nfo合并及策略`统一为大写 `NFO`；`重新下载图片等文件`→`重新下载封面图片等文件`；`将按「设置」-「下载」更新`→`将按设置 -「下载」更新`；`设置 javdb 延时可降低 javdb 被封概率，将在1/2延时-1延时之间随机。`→`设置Javdb延时可以降低Javdb被风控概率，将在1/2延时-1延时之间随机选择`（`MDCx.ui` 与 `MDCx.py` 同步）
- **左下角新版本提示改为 `🍉 有新版本了！（日期tag）` 样式**：保留左侧 🍉 图标与感叹号，只显示日期 tag 全角括号红字，不再显示 `vX.Y.Z`；红字日志仍展示 release 标题
- **刮削模式页 Javdb 延时提示上移一行字高**：`设置Javdb延时…随机选择`（`label_26`）移出 `gridLayout_15`、独立为多线程组直接子件（设计 y 160，上移一行 = `fontMetrics` 高 14），下方 7 个组框与滚动内容同步上收 14px；grid 内 0-2 行保持不动。运行时 `_sync_javdb_tip_pos()` 钉死：x 与分离模式描述文本左缘精确相等、y 按 row2底+spacing+share−h 公式收敛（no-op 即停，休眠跳过）。验证：`tests/test_guaxiaomoshi_align.py` 新增静态结构与运行时冻结测试；三套件全过
- **刮削模式页多线程组底部空白收窄两行字高**：`groupBox_53` 高 221→193（提示下空白 33px→5px），下方 7 个组框与滚动内容同步上收 28px；组框间距、列对齐与提示钉死均不受影响。验证：静态测试断言同步更新；三套件全过

## v2.2.2 (2026-10-04)

### 修复

- **本轮筛选匹配规则总览（最终行为）**：关键词按逗号/顿号/分号/空白/斜杠拆词（全角标点归一到半角，日期片段整体保留，空段丢弃），多词 AND 且顺序无关。两条路径：①文件名快路径原子串匹配（番号如 `261` 定位 `ARM-261`，免磁盘 IO）；②NFO 慢路径按词形分流——日期形词与发行日精确比对（`13-06-08 / 2013.06.08 / 2013·06·08 / 2013年06月08日 / 20130608` 等归一到 `YYYY-MM-DD`）；纯数字词只与年份/时长/评分精确相等（`2`≠2017/120/3.2，含 `2` 的粘贴整条落空，`238 / 5.0 / 2009` 照样命中）；其他文字词在标题/导演/片商/发行商/简介/演员名/标签值内子串匹配）。索引按 mtime 缓存。回归三套共 57 项 56 通过 1 跳过零失败（`test_nfo_library_filter_fields.py` 14 + `test_nfo_library_maximize_preview.py` 28 + `test_ui_structure.py` 15；进程尾部 `access violation` 系 conftest 退出阶段已知老问题，与本次改动无关）。匹配规则的完整契约与两次改崩教训见 `docs/Development.md`「信息管理筛选框匹配规则（改前必读）」一节，后续改动以该节为准

- **筛选框匹配规则 8 轮迭代的历程与被撤销项（合并为一条；终态行为见上方「本轮筛选匹配规则总览」与 `docs/Development.md`「信息管理筛选框匹配规则（改前必读）」）**：
  - ①**按演员/标题搜不到结果**：根因是 `lineEdit_nfo_lib_filter_changed()` 只比对列表项文本（即 NFO 文件名/番号），占位符承诺的「筛选番号/演员/标题」中演员与标题根本没进比对。修法：新增 `_parse_nfo_search_text()` 按 `num/title/originaltitle/actor/name` 解析 NFO 拼成小写可搜索文本、`_nfo_lib_search_text()` 按文件 mtime 缓存（改动后自动重解析，扫描目录时剪掉无效键）；筛选先走文件名快路径（番号命中免磁盘 IO），否则比对缓存文本。首次按演员/标题筛选会对未缓存文件做一次性同步解析（大库首搜略有停顿，之后走缓存）
  - ②**多演员/多关键词搜不到结果**：`川上优,矢沢りょう` 这类带分隔符的整体字符串在可搜索文本里永远不存在（演员名之间是换行分隔），子串匹配必然落空。修法：关键词按逗号/顿号/分号/空白/斜杠（中英文）拆词，多词之间 AND（要求同一 NFO 内全包含），也支持番号+演员混合如 `ARM-261 川上优`
  - ③**全字段扩展**：搜索索引从番号/标题/演员扩到导演/片商（含 maker）/发行商（含 label）/系列/时长/评分（含 criticrating 换算回 10 分制）/标签/简介（plot+outline+originalplot）/发行日/年份，与 `core/nfo.py` 读取标签保持一致；占位符同步更新；新增 `tests/test_nfo_library_filter_fields.py` 首批 10 用例
  - ④**首尾/连续逗号容错**：粘贴 `,园田美樱,ABP，…，` 这类带首尾多余逗号、连续逗号、全角半角混用的多词时，空段一律丢弃不参与 AND（与 `A,B` 等价；全是逗号视为空搜索显示全部）；标签与演员走同一套全字段匹配逻辑，无需分开处理。`_split_keyword()` docstring 明确该约定，测试追加 `test_filter_stray_commas_ignored`（含截图同款「有效词+首尾空段」与开头数字词用例）
  - ⑤**杂散数字不再捞回结果**：`口交,系列: ポルノスター,1` 这类粘贴里 `1` 不在演员/标签里就必须整条落空。修法：NFO 慢路径按词形分流——日期形词与发行日精确比对；纯数字词（`1 / 238 / 5.0 / 2017`）只与数字字段精确相等（年份/时长/评分），不做全文子串；其他词仍全文子串，番号/标题/日期/时长/评分/年份搜索不受影响；文件名快路径保持原子串（`261` 照样定位 `ARM-261`）。另全角冒号/逗号等归一到半角，`系列: ポルノスター` 能命中 `系列：ポルノスター`。`_parse_nfo_search_text` 返回 `(全文, 数字集, 发行日集)` 三元组（mtime 缓存同步），测试追加 `test_filter_stray_digit_kills_match`，`1,青木玲,MIBD` 断言反转为 `[]`
  - ⑥**发行日期多写法归一**：NFO 内发行日按 core 逻辑存为规范 `YYYY-MM-DD`，手写 `YY-MM-DD / YYYY.MM.DD / YY.MM.DD / YYYY·MM·DD / YYYY/MM/DD / YYYY年MM月DD日 / YYYYMMDD / YYMMDD` 等都展开成规范形再比对，不区分大小写；两位年份同时展开 19xx/20xx。实现：`_DATE_PIECE_RE` 先于拆词把日期片段整体抠出（`/` 不再切断日期；**分隔符不含空白，避免 `238 5.0` 被误抠**），`_token_variants()` 产出 `[原串, YYYY-MM-DD, YY-MM-DD]` 候选任一命中即算该词命中，词间仍是 AND。测试追加 `test_filter_release_date_formats` 覆盖 12 种写法 + 混合词 + 回归断言
  - ⑦**已被下一条撤销的一轮（留档）**：`ポルノスター,ABP,园田美樱,2` 误命中 ABP-622 的根因是上一轮留的「纯数字词发行日前缀」口子（`2017-08-04`.startswith(`2`)）。当时按用户要求把文字词收敛到**只匹配演员名/标签值**（`_NFO_ACTOR_TAG_XPATHS` 仅 `actor/name` + `tag`）、标题/导演/片商/发行商/简介等字段彻底退出匹配，占位符改为「番号/演员/标签/发行日/年份/时长/评分」
  - ⑧**恢复标题/导演/片商/发行商/简介搜索（⑦的撤销）**：应用户要求把五个字段加回文字词匹配池（`_NFO_ACTOR_TAG_XPATHS` 更名为 `_NFO_TEXT_XPATHS`，新增 title/originaltitle/director/studio/maker/publisher/label/plot/outline/originalplot），与演员名/标签值同池子串比对；纯数字词仍只与年份/时长/评分精确相等、日期形词仍与发行日精确比对，`2` 落空整条的修复不受影响。**同一轮里真正落地且未被撤销的三项**：纯数字词的发行日前缀口子移除、`criticrating` 只进数字集不再进文本、NFO 文件名 stem 移出文本索引（番号只走快路径）。占位符改为「番号/标题/演员/导演/片商/发行商/简介/标签/发行日/年份/时长/评分（逗号分隔）...」（`.ui` 改完按规矩 `pyuic + ruff format` 重生成 `MDCx.py`，diff 仅占位符一行）。测试：四个 `*_not_searched` 恢复为命中断言并更名，夹具补 `maker/label/outline` 字段，`2009-12-29,MOODYZ` 改为 `2009-12-29,打手枪`，`test_filter_stray_digit_kills_match` 追加用户原样 `作品集,打手枪,青木玲,2 → []` 对照组，新增 `test_filter_title`，`tests/test_nfo_library_filter_fields.py` 达 14 用例
- **信息管理顶栏目录显示框与筛选框改为恒等宽**：应用户要求（截图批注"设置一样的宽度"），两框在布局里各占一份拉伸（`.ui` 里两 `QLineEdit` 的 `sizePolicy` 均改为 `Expanding/Fixed` + `horstretch=1`，筛选框 180 上限删除），剩余空间永远平分，两态恒等宽；删除 `_sync_nfo_lib_top_bar()` 及其 0.5 比例换算常量（最大化加宽/还原复位 180 的旧逻辑，连同自反馈抖动问题一并消失）。**教训**：`layoutStretch` 走不通——pyuic6 会把它塞进 `retranslateUi` 当可翻译字符串传给 `setLayoutStretch`，运行时类型错误；逐控件 `horstretch` 才是 Designer 原生支持的写法。`MDCx.py` 按规矩重生成（diff 仅两处 sizePolicy + 删一行上限）。旧用例 `test_maximized_filter_box_scales_with_dir_box` 改写为 `test_dir_box_and_filter_box_share_equal_width`（窄态/最大化/还原往返严格相等 + 反复同步不漂移）
- **信息管理页裁剪封面完成后不再跳主页、自动刷新本页图片**：根因是 `cut_window.to_cut()` 收尾无条件 `change_to_mainpage.emit("")`（主流程需要跳回主页看预览，但信息管理页发起的裁剪也被连带切走）。修法：`CutWindow` 新增 `_nfo_lib_source` 标记来源（`showimage` 内复位，信息管理页发起时在 `showimage` 之后置为当前 nfo 路径，主流程调用点不动即为 None）；`to_cut()` 末尾分支——信息管理页来源只发新信号 `nfo_lib_images_changed`（`main_window.py` 新增同名 `pyqtSignal` + 透传槽，`init.py` 接线），槽函数 `on_nfo_lib_images_changed` 校验仍是当前番号后只重载两张预览图（`_refresh_nfo_lib_previews` 按 `_resolve_nfo_image` 从磁盘重读，`QPixmap` 不缓存路径；表单不动，保留用户未保存的编辑；用户已切走则忽略）；主流程保持原行为（跳主页 + 刷主页预览）。新增 `test_crop_from_nfo_lib_stays_and_refreshes`（来源标记 + 同步跑完 `to_cut`：`nfo_lib_images_changed` 发射、`change_to_mainpage` 未发射、页码不变、预览 pixmap 重载）

- **信息管理目录框支持手动输入、回车确认（带路径校验）**：`lineEdit_nfo_lib_dir` 去掉只读，手动输入目录后回车即扫描展示（与"刷新"走同一 `_scan_nfo_directory` 链路，含自动选中首个番号；`main_window.py` 按既有模式加透传，`init.py` 接 `returnPressed` 信号）。新增 `_resolve_nfo_lib_dir()` 校验——去首尾空白与成对引号、`~` 展开家目录，分隔符原样交 pathlib（不自行替换斜杠，避免破坏 UNC 前导双反斜杠）；不存在/非目录只记日志，列表与计数保持不动。占位符同步改为「点击"选择目录"或手动输入目录后回车」（`.ui` 改完按规矩重生成 `MDCx.py`，`User_Guide.md` 同步）。新增 `test_dir_box_manual_input_confirmed_by_enter`、`test_dir_box_enter_invalid_dir_keeps_old_list`、`test_dir_box_manual_input_accepts_quoted_and_slash_forms`
- **右键菜单「删除nfo文件」改名为「删除NFO文件」**：`listWidget_nfo_lib_context_menu()` 的 `act_delete` 文案与其 docstring 同步（多选后缀「（N 个）」拼接逻辑不变）；使用说明富文本（`.ui` 改完按规矩重生成 `MDCx.py`）、`docs/User_Guide.md`、`docs/Features.md`、`TODO.md` 同步；`tests/test_nfo_lib_context_menu_text.py` 断言同步更新。删除确认框标题「删除 NFO」等其余三处刻意不动

- **大图预览还原按钮有时不能正常缩小到主页面大小**：根因是预览窗 `close()` 不重置 `windowState`——最大化态关闭后隐藏态仍带着 `Maximized`，下次 `show_matching()` 在隐藏态直接 `setGeometry` 写不进还原矩形，Windows 下点还原按钮就缩到旧尺寸/极小尺寸；普通态关闭则正常，所以时好时坏。修法：`_place_matching()` 隐藏分支先 `setWindowState(WindowNoState)` 落回普通态再写还原矩形；可见已最大化分支除过小外，新增 `_restore_rect_mismatch()`（与主窗口还原尺寸差 >2px 才修）处理主窗口还原尺寸已变而预览留旧值的陈旧情况，一致时不动避免每次点图闪一下；`_enforce_cover()` 最小化还原后同款比对，保证后续还原按钮正确。离屏验证：关闭时 `isMaximized()` 仍为 True、二次打开还原矩形与主窗口一致、主窗口还原尺寸变化后二次点图能跟上

## v2.2.1 (2026-10-03)

### 新增

- **大图预览窗口任务栏独立图标**：封面/缩略图预览跟主窗口分成左右两个图标（MDCx 图标），各自点各自最小化/还原；鼠标悬停可见两个窗口各自的实时缩略图，点任意缩略图切换到该窗口；主窗口经托盘隐藏再显示后依然分开
- **底部提示行整行居中**：信息＋键位图标作为一组放底部中间，最大化/普通态一致

### 修复

- **任务栏还原后预览与主窗口叠偏**：从最小化还原出来重新严丝合缝盖住主窗口（最大化恢复最大化，普通态重合主窗口）；手动点的还原按钮不受影响
- **关闭预览连带关主窗口**：关闭预览只关自己（主窗口在托盘里也不退出）；关闭/收起主窗口时把预览连带关闭
- **预览最大化/最小化/还原按钮失灵与还原尺寸过小**：还原下来回到主窗口启动时的大小；反复切换后按钮不再点不动

### 测试

- 新增 `test_preview_window_has_own_taskbar_app_id`：锁定预览独立 AppID、主窗口没有、托盘收放后还在（需真实 Windows，离屏跳过）

## v2.2.0 (2026-10-02)

### 新增

- **信息管理页点击右侧图片弹出大图预览窗口**：左键单击「海报预览」/「缩略图预览」即弹出与主窗口**完全重合**的预览窗口（`mdcx/views/nfo_preview_window.py` 的 `NfoPreviewWindow(QDialog)`，NFO 库页与信息管理页共用一个类），继承 **窗口状态直通**（不含置顶、不接受拖拽移出、`showMinimized()`/`showMaximized()`/`showNormal()`/`setGeometry(parent.geometry())` 在 **左 / 右 / 双** 三侧都与主窗口完全对称），**左 / 右** 两态之间同一次点击切换同一张图不重新取图（走前后缓存）、左右方向键切换图；主界面数字键输入对应番号的预览可复用（如 ABP-123 输入完整番号预览，Abo 化后不同番号则跳提示图，同一缩略图点击时同图）；方向键缩放、**Esc 关闭**；缩略图不跟随 NFO 设置里缩略图缩放。图片列表由函数 `_nfo_lib_image_entries()` 返回 `[(nfo_path, [poster?, thumb?])]`（不依赖目录结构与 `rglob`，只有海报的图保留海报），配 `nfo_index_changed` 信号通知重扫，同 NFO 只扫一次。预览窗与主窗之间的任务栏与窗口状态契约见 `docs/Development.md`「大图预览窗口任务栏与窗口状态」
- **信息管理页最大化时「筛选番号/演员/标题」输入框等比例加宽**：新增 `_sync_nfo_lib_top_bar()`（`main_window.py`），以「选择目录」显示框的实测宽度 × `_NFO_LIB_FILTER_SCALE`(0.5) 换算筛选框上限，钳制在 `_NFO_LIB_FILTER_MIN_W`(180) ~ `_NFO_LIB_FILTER_MAX_W_CAP`(620)；未最大化时原样复位 180，**最小化态逐像素不变**。**关键坑：必须先把筛选框临时按设计宽度复位再量目录框**——上一遍加宽的筛选框已经把目录框挤窄，直接量会自反馈成震荡（实测 552→534→545→538→543→540 循环抖动，复位后稳定）。**刻意不加 `setStretch(0, 1)`**：那会让最大化时的加宽饿死，筛选框正是靠「剩余空间瓜分」实现的
- **信息管理页选择目录确定后（或刷新后）自动展示目录内第一个番号的信息**：`_scan_nfo_directory(..., select_first=True)` 新增参数 + 新增 `_select_first_nfo()`（选中第 0 行并 `scrollToItem`，靠已有的 `itemSelectionChanged` → `listWidget_nfo_lib_item_clicked` → 异步 `get_nfo_data` 链路填满 15 个字段和两张预览图；选中状态未生效时兜底直接调一次加载）。刷新同样需要重选，否则表单里留着上一个番号的陈旧数据。目录为空时仍只显示「未找到 NFO 文件」提示行，不会误选

### 修复

- **信息管理页最大化时表单 16 行之间凭空多出约一行宽的空白**：根因是 `QFormLayout` 把内容区富余高度**平均分给所有「还能长高」的行**——单行输入框 `sizeHint` 只有 22px 却分到 54px，于是发行日/年份之间出现一整行空白（1030×700 时行距 32，1920×1080 时被撑到 54）。「简介/标签」两个多行框的 `maximumHeight` 被钉在 60px 吸收不了，剩下的全被其他行分走。修法：`_pin_nfo_lib_form_rows(pinned)` 在最大化时把除「简介/标签」外每行控件的 `maximumHeight` 钉死为 `max(sizeHint().height(), minimumHeight())`（原值缓存在 `_nfo_lib_row_max_heights`，退出最大化时还原），富余高度全交给「简介/标签」（`_NFO_LIB_FIELD_MAX_H` = 300 上限）；仍有余量时给 `scrollAreaWidgetContents_nfo_lib` 设 `maximumHeight`，把剩余空间收成底部一条空白而非行间空隙（**只钉多行框上限不行**，实测行距会反弹到 40、缝隙 14~18px）。实测最大化后每行行距恒为 **26px**（22 字段 + 4 间距），1920×1080 时简介/标签各 300px、1366×768 时各 146px、2560×1440 时内容高锁在 990；**最小化态逐像素不变**（1030×700 仍 32、1920×1080 非最大化仍 54、简介/标签仍 60），最大化↔还原往返后与全新小窗快照完全一致
- **信息管理页选中 NFO 后点「裁剪封面」毫无反应（功能已实现，是静默异常）**：`nfo_library.py` 里 `self.cutwindow.showimage(str(poster_path), None)` 把 **str** 传给了签名要求 `Path` 的 `CutWindow.showimage()`（内部按 `img_path.as_posix()` / `.parent` / `.stem` 使用），抛 `AttributeError: 'str' object has no attribute 'as_posix'`；而 PyQt6 里槽函数抛出的异常只打到 **stderr**，打包成 exe 后用户完全看不到 —— 表现为「点了没反应」，连提示框都没有。同一函数在 `main_window.py` 另外两处调用（`pushButton_pic_main_clicked`、成功列表重开）传的都是 `Path`，只有信息管理这一处传错。修法：改传 `poster_path`，并补 `raise_()` + `activateWindow()` 保证裁剪窗口盖到主窗口前面（主窗口是 frameless 的，`show()` 有时会被压在后面）
- **QSS 逗号选择器列表丢前缀会让 hover 样式退化成常态生效**：本轮给信息管理顶栏「选择目录」「刷新」统一样式时写成 `QPushButton:hover#a,#b`，Qt 会把 `:hover` 当成整组共用条件，于是「刷新」按钮**常态显示 hover 的蓝底**（截图里一眼可见）。修法：每个选择器都写全前缀（`QPushButton:hover#a,\nQPushButton:hover#b`），并在测试里加了一条**直接比对两个按钮渲染出的像素底色**的用例锁死该回归

### 界面调整

- **软件设置-命名页「.小数点」复选框窄宽两态都与「不获取分辨率」严格上下对齐（锚点保持不动）**：新增 `_move_naming_point_to_none()`（`mdcx/controllers/main_window/main_window.py`），量出 `radioButton_videosize_none` 在公共祖先 `scrollAreaWidgetContents_mingming` 里的实时左缘，把 `checkBox_cd_part_point` 直接 `move(x)` 过去（只改 x 不碰 y/宽高；方向由运行时几何决定——量到在哪边就往哪边移：离屏实测窄态差 -15、宽态差 -63）。窄态由 `_sync_naming_narrow_align` 末尾调用，宽态由 `_sync_naming_definition_align` 的间隔收敛循环之后调用（none 的位置由该循环刚定下，此时量到的是终态）。**取代旧约定**：此前「小数点与空格保持 140 设计间距、等距右随」在窄态下本来也从未成立——空格被窄态分支左移 47 而小数点纹丝不动（point-space 实测 187 ≠ 140），正是旧回归测试 `test_naming_filename_checkboxes_column_align[1000]` 挂掉的原因。**越界判据用 `sizeHint` 宽（实测 59）而非控件全宽 110**：窄态父组框被宽幅同步收窄（1000 宽窗口下 `groupBox_38` 仅 649，目标局部 x=575，575+110=685 会误判越界），而实际内容（勾选框 + “.小数点”文字）仅 59 宽，575+59=634 完全可见。复位记录复用 `_naming_narrow_restores`（每遍先清后建，幂等往返自愈）；小数点已在 `CustomScrollArea._MANUAL_WIDGET_NAMES` 里，通用宽幅同步不会登记/搬动它。**测试取证坑**：独立探针脚本与 pytest 环境字体度量不同（conftest 把 `get_fonts` 桩掉致 `QFontDatabase.families()` 为 0），前者量到窄态 path/space/none 在 403/403/605，后者是 388/388/575——实现与断言必须只用「运行时换算、不写死坐标」，下划线断言也因此从「与 space 差 -260」（只在宽态成立）改为「局部 x 恒为 160」。验证：`test_naming_filename_checkboxes_column_align[1000/1920]` 改断言为 point==none + 下划线原位 + 锚点纳入复位快照，两态通过，**此前既有失败 [1000] 本轮被顺带修复**；全矩阵 59 项、关联 46 项全过，`ruff` 全过
- **软件设置-刮削网站页「指定网站」下拉框右缘收缩到「锁定类型」下拉框右缘**：新增 `_sync_site_pref_combo_width()`（`mdcx/controllers/main_window/main_window.py`，在 `_sync_page_layouts()` 里排在「水印页」之后、「NFO 页」之前），量出参考框 `comboBox_fixed_scraping_type` 在公共祖先 `scrollAreaWidgetContents_guaxiaowangzhan` 里的实时右缘，换算成 `comboBox_website_all` 的宽度上限并 `setMaximumWidth` 钉住。**根因**：两个下拉框分属不同组框的不同网格——`gridLayout_28`（「网站偏好」组）只有 2 列，`gridLayout_36`（「类型刮削网站」组）有 4 列（多出「编辑网站」「网站优先」两个按钮列），列宽因此天然差 111px，「指定网站」下拉框比「锁定类型」多出 111px 右缘（离屏实测窄态 689 vs 578、宽态 1579 vs 1468，**两态差值恒等**，故不是比例问题而是列数差）。**为什么不用 `move()`/`setGeometry()`**：两者都在 `QGridLayout` 里，layout 重新 `activate()` 会直接覆盖绝对坐标（同 `_pin_row_lead_width` 的结论），宽度上限是布局本身遵守的约束。**三条实测得来的边界**（都写进代码注释与测试）：① 必须先显式重跑 `scroll.sync_wide_children_width()` 再量——首次打开本页签时宽幅同步还没跑，两个框停在未布局的默认宽度（实测 100~219px），此刻量到的是中间态假读数，一旦据此钉上限就与布局形成自锁、宽度永久钉死在 147px 再也张不开；② 对休眠页签做 `isVisibleTo` 早退，未布局页签的读数同样是假值（实测两框恒 100px 宽、右缘差 30），整段不碰任何约束；③ 视口窄到「锁定类型」所在四列网格先被挤瘪时（720×680 窗口实测对齐目标仅 93px < 本框 `minimumSizeHint` 147px），目标不可达，钉低于自身最小尺寸的上限只会与布局互相拉扯，故交回设计上限放弃本轮对齐。设计态上限取 `.ui` 声明的 `maximumSize` 宽 16000 并在首次进入时记下（` _site_pref_combo_design_max`），「读数无意义」分支据此原样交回，不拿 `QWIDGETSIZE_MAX` 顶替以免永久改掉设计约束。验证：`tests/test_window_state_matrix.py` 新增 3 项（`test_site_pref_combo_right_aligns_to_fixed_type[1030/1920]` 窄宽两态右缘严格相等 + 只钉上限不钉下限 + 参考框未被写入约束 + 二次同步不漂移；`test_site_pref_combo_ignored_until_tab_opened` 休眠不写上限、首次打开立刻对齐），该文件当时 58 项通过（唯一失败 `test_naming_filename_checkboxes_column_align[1000]` 为改动前既有失败，**已在本轮小数点对齐改动中被顺带修复**，现全矩阵 59 项通过）
- **信息管理页列表右键菜单两项文案改名：「重新刮削」→「重新刮削番号」、「删除 NFO」→「删除nfo文件」**：`listWidget_nfo_lib_context_menu()`（`mdcx/controllers/main_window/nfo_library.py`）的 `act_rescrape` / `act_delete` 文本与其 docstring 同步修改（「打开所在目录」不变），多选时的后缀「（N 个）」拼接逻辑保持原样。**文案同步范围**：软件内「使用说明」富文本（`mdcx/views/MDCx.ui` 与 `mdcx/views/MDCx.py` **两边同改**，`tests/test_ui_structure.py::test_mdcx_py_in_sync_with_ui` 会重新编译 `.ui` 逐字节比对）、`docs/User_Guide.md` 第 26 行、`docs/Features.md` 第 236 行、`TODO.md` 第 78 行。**刻意不改的三处**（均非本菜单，属独立控件）：删除确认框标题 `QMessageBox("删除 NFO", ...)`（`nfo_library.py`）、重新刮削时弹出的输入框标题 `QInputDialog("输入番号重新刮削", ...)`、以及刮削结果树右键菜单的「  重新刮削\tN」（`main_window.py`，与「输入网址重新刮削」成对），另外 `User_Guide.md` 第 78/186 行的「重新刮削」指的是结果树那一项。新增 `tests/test_nfo_lib_context_menu_text.py`（3 项：三个菜单项文案精确锁定 / 多选时删除项带「（N 个）」后缀 / 未选中时不弹菜单），`ruff` 全过
- **信息管理页顶栏顺序改为「目录显示框 → 选择目录 → 共 N 个 → 筛选 → 刷新」**：只改 `mdcx/views/MDCx.ui` 里 `nfo_lib_top_layout` 的两个 `<item>` 块顺序，再用 `python -m PyQt6.uic.pyuic` 重新生成 `MDCx.py` 并 `ruff format`（**`MDCx.py` 绝不能手改**——`tests/test_ui_structure.py::test_mdcx_py_in_sync_with_ui` 会重新编译 `.ui` 并逐字节比对，最终 diff 只有控件创建顺序与 `_translate` 顺序两处各 5 行）。按钮紧贴显示框右侧、再紧贴「共 N 个」左侧；显示框排在最左自动吃满余量宽度（1030×700 时 359px、1920×1080 最大化时 809px，左缘恒为布局边距 9）。**刻意不加 `setStretch`**：加了会让最大化的筛选框加宽饿死
- **信息管理页顶栏「选择目录」「刷新」改用「软件设置-高级-选择目录」同款样式，宽高不变**：新增 `style_mod._nfo_lib_top_button_qss(dark)` + `apply_nfo_lib_top_button_style(self, dark)`（`mdcx/controllers/main_window/style.py`），规则与 `pushButton_select_config_folder` 所在规则组完全一致（浅色底 `rgba(220,220,220,255)` / 暗色 `...50`、`font-size:14px`、`border-width:8px`、`border-radius:20px`，含同款 hover / pressed），分别由 `set_style()` / `set_dark_style()` 末尾下发。**为什么单独下发而不直接加进全局规则组**：QSS 的 `padding` 会改控件 `sizeHint`（实测收窄约 8px），直接套用会让整个顶栏重新排版；helper 先量出原始尺寸 `max(sizeHint, minimumSize)`、套完样式再 `setFixedSize()` 钉回。实测两个按钮恒为 **80x32、顶栏高 50**，明暗主题来回切三轮不漂移。顺带实测确认：QSS 的 `border-width` 不带 `border-style` 时**根本不绘制**（按钮渲染成普通灰色圆角块）
- **信息管理页「批量保存」「保存当前nfo文件」改用软件设置主页面保存按钮的蓝底，「裁剪封面」同款且上下高度对齐**：三个按钮都加进 `QPushButton#pushButton_save_config` 的规则组（明暗两套，含 hover / pressed），`color: white` + `background-color:#4C6EFF` + `border-radius:25px`。两个保存按钮在布局里本就跨列，宽度由布局撑满（一度尝试按「文字宽度 + 左右各一个汉字宽度」收窄到 48/88px，用户要求改回铺满边框，已复位 `maximumWidth` 为 `QWIDGETSIZE_MAX`）；「裁剪封面」原本没有最小高度，现由新增的 `_sync_nfo_lib_action_buttons()`（`main_window.py`，在 `_sync_page_layouts()` 里紧跟顶栏同步调用）把 `minimumHeight` 对齐到「批量保存」的 36px，保证上下留白一致
- **大图预览窗口的按键提示改用图标键帽而非文字**：底部信息行改为 `← →` 相同番号图片　`↑ ↓` 不同番号图片　`Esc` 关闭；底栏与信息管理页底栏 `一致文字 / 一致间距 / 一致图片`，说明为「← / → 切换图片、Esc 关闭」。样式从**原生弱边框**（`QFrame.Box` + `Sunken`）改为与主界面其余区域一致的**无边框风格**、外边距 12px 顶栏（自绘分隔标签）
- **软件设置-翻译页最大化时「显示翻译来源」「使用演员映射表翻译演员」左移到与「中文繁体」对齐、「日语+中文」右移到与「中文繁体」对齐、「关闭」右移到与「日语」对齐（最小化态整页保持不变）**：四个锚点（简介/演员两组的「中文繁体」、「简介-日语」）自身一律不动。改的是已有的 `_sync_fanyi_trans_align()`（`mdcx/controllers/main_window/main_window.py`，此前只处理窄态左移、宽态直接 return），补上宽态分支：四个目标按锚点 content-x 精确对齐（方向不限，`mapTo` 一律经 `scrollAreaWidgetContents_fanyi` 中转；`wide` 判据沿用 `_scroll_stretch_extra(...) > 0` 而非 `isMaximized()`，与本页既有逻辑同源）。宽态独有两个坑：① 「双语显示」行的 `frame_5`（设计 661）与 `layoutWidget_24`（设计 521）是绝对定位、通用宽幅同步不拉宽——不先加宽就 `move()` 会把单选框钉到父容器之外被裁掉（子控件超出父矩形不绘制），故先加宽（`frame = 组宽 − 2×20`、`lw24 = frame 宽 − 140`，设计边距），窄态交还设计值；② 加宽后 HBox 会把多余宽度均分到三个单选身上（离屏实测被拉到 460 宽）并把首项顶到中间（x=288），故宽态把三单选钉为自然宽（`sizeHint`，随字号/缩放自适应）、「中文+日语」每遍钉回 x=0 保持设计位置，窄态解除钉宽（`min 0 + max 16777215`，`.ui` 里三者本就无此约束）。复选框那两对无需加宽——其父容器（`layoutWidget_13/20`）本就被通用同步拉宽，目标落在容器内。每遍重钉、数值相符即 no-op，天然幂等。验证：1000/1400/1920 三档四组 content-x 与锚点精确相等、「中文+日语」顶左自然宽、宽→窄往返后容器与钉宽全部回到设计值、截图与用户标注一致。新增 `tests/test_fanyi_wide_align.py`（6 项：宽态四组对齐[1400/1920]、容器加宽公式、中文+日语顶左自然宽、宽态反复同步不漂移、先宽后窄还原且窄态仍对齐），`git stash` 回退 `main_window.py` 后 5 项立刻报红；`ruff` 全过

- **软件设置-翻译页最小化时「显示翻译来源」「日语+中文」左移到与「中文繁体」严格上下对齐、「使用演员映射表翻译演员」「关闭」左移到与「日语」严格对齐（最大化界面/控件/提示词等保持不变）**：四个锚点（两组的「中文繁体」与「日语」）自身一律不动。排查确认翻译页简介/演员组为固定几何 + QHBoxLayout 左对齐，窄态与宽态相对偏移一致；离屏实测第一项（144/180px）比中文简体（72px）宽，单纯左移第二项理论上有重叠风险，经用户确认无遮盖。方案采用运行时窄态对齐、宽态原样返回——新增 `_align_fanyi_pairs()`（`mdcx/controllers/main_window/main_window.py`），仅面板宽 ≤462px 时钉四对左缘，宽态直接返回；**不改 `.ui` / `MDCx.py`**，避免影响最大化。验证：窄态四对严格对齐、宽态零移动；`ruff` 与 `tests/test_ui_structure.py` 全过
- **软件设置-演员页最小化时「中文繁体」右移到与「使用Graphis头像」严格上下对齐、「日语」右移到与「请求Graphis最新图片」严格上下对齐（最大化保持不变）**：两锚点（A2 `checkBox_actor_photo_ne_face`、A3 `checkBox_actor_photo_ne_new`）自身不动。排查：语言行 `horizontalLayout_92` 为 [简/繁/日 + Expanding 尾间隔]，宽态本就简/繁/日 = A1/A2/A3；离屏实测 1000 宽时简 186 / 繁 244 / 日 302、A1 = 186 / A2 = 346 / A3 = 505，行尾 Expanding 可吸收位移（序贯 pin 后总插入 203px）。方案：在 `_ACTOR_INFO_NARROW_TARGETS` 加 `horizontalLayout_92` 条目（繁→A2、日→A3），复用 `pin()` 右移机制，宽态逻辑不动。验证：窄态 940/1000/1030 三宽度下繁 = A2、日 = A3 精确对齐、简体保持 A1 不动，宽态无变化且往返幂等；`tests/test_actor_info_columns.py` 16 项全过（窄态测试加繁/日对齐断言，往返测试的过时「还原态零间隔」断言改为与初态一致）
- **软件设置-水印页最大化时 thumb 与「固定一个位置」右移到与右上对齐、fanart 与「固定不同位置」右移到与右下对齐（最小化整页逐像素不变）**：四目标为 `checkBox_thumb_mark` / `radioButton_fixed_corner` → 不固定位置组的 `radioButton_top_right`，`checkBox_fanart_mark` / `radioButton_fixed_position` → `radioButton_bottom_right`，两锚点自身保持不动。改的是已有的 `_sync_watermark_colon_align()`（`mdcx/controllers/main_window/main_window.py`，冒号对齐之后追加）：在目标所属行（`horizontalLayout_7` / `horizontalLayout_5`，类常量 `_WATERMARK_SHIFT_ROWS` 登记「行、目标、锚点」三元组）目标前插 Fixed 固定间隔，行尾已有 Expanding 尾间隔吸收富余，故间隔只把目标右推、行内其余项宽度不动；每行按从左到右顺序收敛（先推前一个、再推后一个）、每项插完回读三轮收敛，只允许右移（锚点在左则保持 0 宽）、越出内容区则放弃。离屏实测 1920×1170：thumb/固定一个位置 x=537=右上，fanart/固定不同位置 x=887=右下，间隔宽 245/244/286/278；窄态拉伸量 ≤ 0 时第一步清干净即 return。`_clear_watermark_colon_align()` 同步扩展为每遍先清后建（右移间隔 + 尾部间隔 + 列钉死），幂等往返自愈
- **软件设置-水印页最大化时「破解」右移到与右上对齐、「无码」右移到与右下对齐、「4K/8K」右移到与左下对齐（有码与三锚点不动，最小化逐像素不变）**：三目标为水印类型行（`horizontalLayout_14`，顺序为字幕-有码-破解-流出-无码-4K/8K）的 `checkBox_umr` → `radioButton_top_right`、`checkBox_uncensored` → `radioButton_bottom_right`、`checkBox_hd` → `radioButton_bottom_left`，复用上一条的间隔收敛机制、按从左到右追加三项。**结构性冲突**：破解右移到右上（+263）必然把同行其后的流出从 318 连带推到 581，「破解→右上」与「流出不动」在同一线性布局里不可能同时成立——离屏几何取证后经用户确认按「三项对齐、流出跟随」实现。离屏实测 1920×1170：破解 537、无码 887、4K/8K 1238，字幕/有码在其左保持不动
- **软件设置-水印页最大化时「有码」右移到左上与右上中间、「流出」右移到右上与右下中间（左上/右上/右下不动，最小化逐像素不变）**：两目标为 `checkBox_censored` → (`radioButton_top_left`, `radioButton_top_right`) 中点、`checkBox_leak` → (`radioButton_top_right`, `radioButton_bottom_right`) 中点，锚点写法扩展为「两控件名的元组、取两者左缘中点 `(x1+x2)//2` 实时计算」，`_WATERMARK_SHIFT_ROWS` 按从左到右补到五项（有码-破解-流出-无码-4K/8K），顺序收敛自动把破解间隔从 263 收为 132、总量仍被尾部间隔吸收。**取证过程**：流出按字面应去左上右下中点 (186+887)//2=536，但它被钉在右上（537）的破解挡住、最小只能到 581，差 45px 不可达——几何证明后用户改定为右上右下中点 712，各间隔 131/132/131/131/307 全 ≥ 0，两态皆可行。离屏实测 1920×1170：有码 361、流出 712，破解/无码/4K8K 既有对齐（537/887/1238）与字幕（186）纹丝不动
- **软件设置-NFO 页最大化时十个字段复选框分两组左移到标签行的演员列 / 清晰度列（四锚点不动，最小化逐像素不变）**：A 组「原标题/简介/发行日期/分级/时长」→ 演员列（`checkBox_tag_actor`），B 组「原简介/首播/自定义评分/想看人数/影评评分/导演/演员 TMDB ID/标签」→ 清晰度列（`checkBox_tag_definition`），四锚点（演员/剧集/清晰度/工作室）自身一律不动。新增 `_sync_nfo_target_column_align()`（`mdcx/controllers/main_window/main_window.py`，挂 NFO 链尾）：五 HBox 行按「首项钉宽 = 锚A.x − 首项.x − 间距、第 2 项钉宽 = 锚B.x − 锚A.x − 间距」钉死（min=max），`gridLayout_66` 的 C1 列最小宽沿用右列控制器同款镜像公式；任一钉宽低于 `max(文本 hint, 60)` 即整单放弃防裁字；两项行（`horizontalLayout_135`）两项全钉死后补 Expanding 尾间隔吸收富余——**离屏实测 QHBoxLayout 会把富余均摊进前/中/后三个间隙**（双 364 在 1473 行里落到 246/862，纯 Qt 最小复现确认与业务代码无关）。窄态清掉本钉宽/尾间隔/C1 最小宽后重跑右列/标题/行/尾四个控制器还原。**三个实锤根因**（症状都是「循环里量到 481、落定 488/501」）：① `_sync_page_layouts` 每遍直调右列控制器且跑在钩子链之后、开头的清零洗掉本钉宽——以 `_nfo_target_col_active` 归属权标志声明，生效中右列直接返回，窄态/复位时清标志再调它接管；② 旧的先清再量等于量倒带后的世界——改不清直接量热值（锚点从未被钉），≤6 轮激活→测量→比对闭环，泵事件验证后才退出；③ 内容宽退出后还在长（`layoutWidget_10` 宽 1509→1589）——慢路径动过手必排一拍 NFO 链 trailing（`singleShot(0)` 直接排链，不能排全量同步因无拉伸时到不了本方法，上限 8 拍），下一拍快路径收敛即停排。验证：离屏 1920×1170 原标题=演员=501 精确对齐；`tests/test_window_state_matrix.py` 61 项全过、NFO 相关 6 文件 52 项全过，`ruff check` + `format` 全过

### 测试

- `tests/test_naming_watermark_align.py` 扩到 9 项：原有 6 项（命名页画质行对齐 + 水印页冒号对齐 + 窄态逐像素 + 幂等往返）之上，新增 `test_watermark_shift_aligns_to_corners_when_wide`（thumb/固定一个位置 → 右上、fanart/固定不同位置 → 右下，四目标精确对齐、两锚点用参照断言锁定不动、宽态确有右移间隔注入）、`test_watermark_type_shift_aligns_when_wide`（破解 → 右上、无码 → 右下、4K/8K → 左下，字幕与三锚点对照「去掉水印类型行右移项」的同步基线逐项一致）、`test_watermark_midpoint_shift_when_wide`（有码 → 左上右上中点、流出 → 右上右下中点，既有三项对齐不受影响、字幕与三锚点对照同款基线一致）；旧冒号对齐用例里被右移接管的五项改由新用例锁定，不再要求左移；窄态用例补「无右移/尾部间隔残留」断言
- `tests/test_window_state_matrix.py` 新增 NFO 页 2 项（`test_nfo_targets_align_to_tag_columns_when_wide`：1900/1600/1366/1100 四档十目标精确落列 + 四锚点与参照件不动 + 窄态逐像素 + 幂等往返；`test_nfo_resyncs_after_dormant_resize_on_page_back`：休眠 resize 残留钉宽、回页钩子重跑归位；dormant 测试的过期「宽态前缀 >400」前置改为与本方法宽态钉宽逐值比对——标题控制器的旧大前缀已被接管）

- 新增 `tests/test_nfo_library_maximize_preview.py`（28 项）：覆盖最大化行距（无行间空白、表单不溢出滚动视口、最小化态逐像素不变且往返复原）、筛选框等比加宽、顶栏控件顺序与相邻关系、大图窗口（几何完全覆盖主窗口、状态跟随、← → 同番号切换、↑ ↓ 切番号并保留图片类型、环绕、Esc 关闭、提示用图标、缩略图优先、无选中时不开窗、图片随窗口缩放）、按钮样式与尺寸（选择目录/刷新同款且宽高不变、两按钮渲染底色一致、保存按钮铺满边框、裁剪封面与批量保存同高、蓝底规则入表）、选择目录/刷新自动展示第一个番号、裁剪窗口能弹出且未选中时给出提示。配套 `tests/test_window_state_matrix.py` / `test_ui_structure.py` / `test_ui_geometry.py` / `test_ui_scale_options.py` / `test_cover_info_maximize.py` / `test_nfo_save_roundtrip.py` 共 **121 项通过**，唯一失败 `test_naming_filename_checkboxes_column_align[1000]` 为改动前既有失败
- 记录两条测试侧踩坑：① 离屏测试环境无 CJK 字体且 `QFontDatabase.families()` 被桩成 0，NFO 测试数据**必须带 `<title>`**——`mdcx/core/nfo.py:462` 在缺 title 时返回 `(None, None)`，表单永远填不上内容；② **NFO 加载是异步的**（`executor.submit` → `nfo_lib_data_loaded` 信号），断言前要用轮询 `processEvents()` 等到数据落地，不能只 `processEvents()` 一次

## v2.1.9 (2026-10-02)

### 修复

- **更新检测改取 tag 最大的 release，不再取 `/releases` 列表第一条（补发/重跑旧 tag 会让所有用户从此看不到任何新版本提示）**：`mdcx/base/web.py` 的 `check_version()` 原本 `for release in releases: if tag.isdigit(): return int(tag)` 直接返回列表里第一个纯数字 tag，但 GitHub `/releases` 是按 **`created_at` 倒序**而非 tag 倒序返回的，而唯一发版工作流 `build-py314.yml` 的四个 `Create Release` 步骤用的是**同一 tag + `overwrite: true`**（`svenstaro/upload-release-action` 是先删后建）——任何一次 `workflow_dispatch` 补发或失败重跑，都会把那条 release 删掉重建、`created_at` 刷成"当前时间"并顶到列表第一位。于是手动补发一次旧 tag（如 20260930）之后，`check_version()` 会永远返回那个旧版本号，**所有用户从此收不到新版本提示，且没有任何报错**，这正是"有时候启动检测不到新版本、有时候又能检测到"这个长期现象的根因（与网络无关）。修法：遍历全部 `per_page=10` 条，收集所有 `tag_name.isdigit()` 的值并取 **max**，非纯数字 tag 仍照旧跳过（tag 纯数字这条硬约束不变，见 `tests/test_py314_release_workflow.py`）；同一 tag 重复出现取首次见到的标题，不报错。新增 `tests/test_version_check_pick_latest.py`（7 项：补发旧 tag 顶到第一位仍取最大、列表升序仍取最大、非纯数字 tag 排在第一位也不能提前返回、同 tag 重复不报错、缺标题时 `display` 退回纯数字 tag、全非数字 tag 返回 None 并记日志、关掉「检查更新」开关时一个请求都不发）。检测失败时的行为按需求保持原样（不新增"版本检测失败"提示、不加结果缓存、每次启动照常检测）。不变量 ① 的完整论证与后续两条修补（见 v2.2.5）见 `docs/Development.md`「版本号管理 → 更新检查（客户端自动更新）」
- **更新检测同时对比版本号与日期（原先只比纯数字日期，同一天发两版永远认不出第二版）**：比较仍以纯数字 `LOCAL_VERSION` 与 release tag 为基础，但把展示用 `VERSION_NAME` 也纳入维度——`mdcx/base/web.py` 新增 `parse_release_version()`（从 release 标题 `v2.1.8 (20261001)` 解析三元组，认不出返回 `None`）与 `is_remote_version_newer(remote, local_tag, local_name)`：**版本号不同则由版本号决出（远端更高即有新版本），版本号相等才比日期（远端日期更新即有新版本），任一侧版本号解析不出来则退回只比日期**。两条并列才覆盖得住：只比日期则"当天先发 v2.1.8 再发 v2.1.9、两个 tag 同一天"永远认不出第二版；只比版本号则"同版本号跨日期补发修复版"会漏判。刻意**不做字面 OR**（不让"日期更新"在版本号更低时也触发）——那会提示用户降级，且仓库里 `LOCAL_VERSION` 常先于线上发布 bump（源码已 20261002 而线上还是 20261001），开发版会对着已发布的历史版本反复提示「请及时更新」。`check_version()` 返回值随之由 `int` 改为 `RemoteVersion(tag, name)` NamedTuple（带 `display` 属性），红字提示与左下角「🍉 有新版本了！」文案从裸数字 tag 改为 release 标题 `v2.1.8 (20261001)`，无标题时退回纯数字 tag。新增 `tests/test_version_check_compare.py`（24 项：版本号解析 8 种输入、三条比较规则各自的正反用例、本仓库源码已 bump 到未发布版本时不应被提示而 v2.1.7 用户应被提示等），`tests/test_version_check_notify.py` 的桩与断言同步换成 `RemoteVersion` 并新增 2 项（提示文案展示 release 标题、同 tag 更高版本号仍须提示），另两个既有 GUI 用例（`test_main_window_startup.py` 等 12 处 `lambda: None` 桩）不受影响。不变量 ②③ 的完整理由见 `docs/Development.md`「版本号管理 → 更新检查（客户端自动更新）」
- **软件设置各页签的竖向滚动条启动时忽宽忽窄（每次落在随机页签，最大化后才统一且保持）**：QSS 里 `build_scrollbar_style` 声明的 `QScrollBar:vertical{width:16px}` 只落在 `sizeHint()` 上，而滚动条**实际画多宽由 polish 时刻缓存的 groove/handle 子控件矩形决定**——`setFixedWidth(16)` 只更新几何、不作废那份缓存，于是槽照旧按平台默认宽度绘制（125% 系统缩放 × 80% 高分屏缩放下 `PM_ScrollBarExtent` 实测 **12**），控件 `width()` 却是 16，**属性全对、画面是 12**，肉眼即"窄了一条白边"。哪些条看起来是宽的，取决于它有没有被别的事件（换肤、焦点变化、祖先样式表变动）顺带重新抛光过，故每次落在随机页签；最大化会让整棵控件树重新抛光，于是在宽态"看着好了"、还原后也保持——与用户现象逐条吻合。修法：新增 `CustomScrollArea.sync_scrollbar_thickness(repolish=False)`（`mdcx/views/CustomClass.py`），厚度取 QSS 声明的 `sizeHint()`（不硬编码 16，改 QSS 即改这里）、只采信 8~48px 区间（未 polish 时可能报出 Qt 默认的荒唐值），需要时 `setFixedWidth` 后**必定 `unpolish()+polish()+update()` 让绘制真正跟上**；挂 `resizeEvent`（未改动即返回，幂等、不自激成 resize 回环）与 `showEvent`（传 `repolish=True`——显示正是陈旧绘制第一次露出来的时刻），下沉到控件自身即与"页签是否被访问过""定时器先后"彻底解耦。控制器 `_sync_settings_scrollbar_widths()` 保留为兜底并同步改为读 `sizeHint()`、取 `max`、按约束而非几何判是否需要钉。**逐项干预实测**（字幕页复现窄态后，量实际渲染宽度）：基线 12 → `update()+repaint()` **12**（重绘无用）→ `unpolish()+polish()` **16** → `setFixedWidth(15)` **15**（绘制确实跟随宽度，但只在重新抛光之后）。**定案验证**（真实启动路径、`QT_SCALE_FACTOR=0.8`、量整窗合成图的渲染像素而非控件属性）：打回改动连跑 2 次每次 `narrow=11/12`，带上修法连跑 3 次每次 `narrow=0/12`；抗压序列（明暗主题切换 ×2、逐页快速点开 3 轮、最大化/还原、连续 4 次改窗高、离开设置页再回来）8 个检查点全部 `width==sizeHint==min==max`。新增 `tests/test_window_state_matrix.py::test_scroll_area_pins_scrollbar_thickness_on_show_without_timer`（直接调控件方法、不经控制器与定时器，注入"钉死 + 重新抛光"复现陈旧缓存后经 `show()` 触发修复，断言几何、`min=max` 与渲染宽度三者都回到 16 且幂等；无修法时报 `AttributeError`），另两个既有滚动条回归用例同步更新。完整取证链（含两批已作废的取证、页面可见性陷阱、量化手段）与「以渲染像素为准」的立规见 `docs/Development.md`「主窗口 UI 布局与窗口缩放 → 设置页各页签滚动条厚度统一」及「代码规范 → 界面问题的取证与验证」

### 界面调整

- **软件设置-高级页最大化时三处控件右移到指定锚点上下严格对齐（最小化态整页逐像素不变）**：需求为三条——①「保存日志」「检查更新」两行的「关」右移到与「隐藏NFO库管理」（`checkBox_hide_nfo_nav`）上下严格对齐；②「隐藏窗口」行的「点最小化按钮」（`radioButton_hide_mini`）右移到与「显示字段来源信息」（`checkBox_show_from_log`）上下严格对齐；③ 同一行最右侧的「无」（`radioButton_hide_none`）右移到与「显示字段内容信息」（`checkBox_show_data_log`）上下严格对齐。三个锚点自身一律不动，最小化态页面、布局、控件、提示词等全部保持原样。三处根因不同、手法也不同，故 `mdcx/controllers/main_window/main_window.py` 新增 `_sync_advanced_page_tail_align()` 逐处处理：① 两行的容器 `horizontalLayoutWidget_11` / `_7` 是 `groupBox_17` / `_4` 的**直接子项**，被通用宽幅同步判成 `_STRETCH`、行内两个单选均分余量，于是「关」的左缘随窗宽漂移；锚点自身也在同一次拉伸里被摆好，故只需**钉死前导项「开」**（`_pin_row_lead_width`，宽度取「锚点 x −「开」x − spacing」），末位「关」的左缘即恒等于锚点。②③ `layoutWidget_17`（`frame_3` 的子控件、`frame_3` 又是 `gridLayoutWidget_20` 的子控件）**完全不参与拉伸**——通用同步只登记「顶层组框的直接子项」——故它四个尺寸下恒为 551×32、行内三个单选恒按 551 均分（实测 180/179/180，宽窄两态一模一样），而两个锚点却在另一组框 `groupBox_3` 里随该组被拉伸，彼此毫无联动；只能**钉死前两项 + 把容器加宽**（钉「点关闭按钮」= m−spacing、钉「点最小化按钮」= n−m−spacing，容器宽取 n + 「无」的 `sizeHint`，手法与外观行加宽 `layoutWidget5` 同款）。三条关键取舍：① **调用点必须排在 `gridLayout_20.activate()` 之后**——需求①的锚点正是那批 `activate` 才定下的最终 x，提前量到的是它被等分推到右缘的旧值，用户截图红框里那两个「关」此前就是这么被钉歪的；`changed` 为假时网格几何本就是终态，照量不误。② **容器宽下界只能取 `layoutWidget_17.sizeHint()`（168 = 三个单选 hint 之和 + 两个间隔），不能取设计宽 551**——`extra` 刚转正时 `want_w` 只有 400 出头（1100×800 实测 457 < 551），拿 551 卡门会让「刚过最大化线的那一大段窗宽」全部漏排，此坑由该尺寸档测试抓出。上界取 `frame_3.width()`，超出即越出父控件绘制区被裁掉。③ **`wide` 判据用几何拉伸量 `_scroll_stretch_extra(...) > 0` 而非 `isMaximized()`**：窄态 1030×753 实测「关」= 393 反而在锚点 313 的**右侧** 80px，没有这个判据就会把需求「向右移动」反向实现成左移；沿用与本页既有的「隐藏NFO库管理」「暗黑模式」同款理由（窗口管理器最大化时先发尺寸、后发状态标志）。三处落点全部运行时 `mapTo` 实测、不写死像素，`mapTo` 一律经公共祖先 `scrollAreaWidgetContents_gaoji` 中转（目标分属 `groupBox_17`/`_4` 与 `frame_3`，跨分支 `mapTo` 是未定义行为）。验证（`adv_measure.py` 逐档几何 + `adv_paint.py` 给目标与锚点装 `eventFilter` 记录**每一次 Paint 的实际坐标**）：1920 宽态三处 857/857/589/1088、1600 为 697/697/482/875、1366 为 580/580/404/719、1100 为 447/447/316/541，**四档全部精确对齐**；1030×753 与改动前逐像素相同；paint 中间态帧数为 **0**（无「先在原位、再跳到对齐位」的可见中间态）；宽→窄往返 3 轮后窄态几何快照与 `text`/`toolTip`/`sizeHint` 全部不变，重复同步幂等。新增 `tests/test_advanced_page_tail_align.py`（12 项：四档宽态对齐、宽态绝不动锚点且绝不裁字并给出「摘掉新方法」的对照基线、窄态基线 + 往返逐像素比对 + 钉宽已解除 + 容器回 551、往返稳定、重复同步幂等）
- **软件设置-高级页最大化时七项控件左移到与「显示字段来源信息」严格上下对齐（最小化态整页逐像素不变）**：需求为「刮削结束后自动退出软件、停止刮削时、隐藏菜单栏图片（Mac）、暗黑模式、隐藏NFO库管理、仅隐藏入口功能本身保留保存后立即生效、关、关**向左**移动到与显示字段来源信息严格上下对齐的位置，显示字段来源信息位置保持不变」——红框 3 那句「隐藏NFO库管理 仅隐藏入口…」是同一个复选框的完整文案，故共七项：`checkBox_auto_exit` / `checkBox_show_dialog_stop_scrape` / `checkBox_hide_menu_icon` / `checkBox_dark_mode` / `checkBox_hide_nfo_nav` / `radioButton_log_off` / `radioButton_update_off`，新锚点是 `checkBox_show_from_log`，自身不动。与上一条（右移组）同页同锚点，两组在宽态下同时成立：`checkBox_hide_nfo_nav` 先随本组左移到新竖线，再被上一条的两枚「关」拉回它右侧，于是那两枚「关」最终也精确落在新竖线上。改的是 `_sync_advanced_page_align` 本体——本页原有的竖线基准正是目标①`checkBox_auto_exit`，要让它自己左移只能先钉同行的前导项，故拆成**两阶段**：阶段一按新锚点算出落点并钉死 `checkBox_auto_start`（改动后立刻 `activate` 并重取行左缘/列宽），阶段二沿用原有的四段（钉「退出软件时」/ 插固定间隔推「隐藏菜单栏图标」/ 加宽 `layoutWidget5`/ 钉「隐藏 Emby 演员管理」）只是把量到的竖线换成「重新量一次 `checkBox_auto_exit`」——阶段一钉完后它恰等于新锚点，于是两种窗宽状态共用同一份代码、天然幂等、无循环依赖，也避开「还原时先量到上一次宽态钉宽」的一帧错位。三处关键取舍：① **竖线取法必须分两态**——最大化取 `checkBox_show_from_log`，还原态仍取 `checkBox_auto_exit` 的自然位；否则窄态下这五项会从 412 被左移到 292（实测 1030×753 `from_log`=292 vs 旧基准 412），直接违反「最小化时逐像素不变」。也试过「窄态一律解除钉宽」，走不通：第 8 行解除后「隐藏菜单栏图标」从 412 掉到 353、第 9 行 `layoutWidget5` 从 588 掉到 550（`_ADV_FRAME_LW_W`）连带「暗黑模式」掉到 393。② **新锚点跨分支**——它在 `groupBox_3` 里、不是 `gridLayoutWidget_20` 的后代，`mapTo(host, ...)` 是未定义行为，须经公共祖先 `scrollAreaWidgetContents_gaoji` 中转再减去宿主的 content 坐标。③ **上一条的 `_sync_advanced_page_tail_align` 无需改代码**——它量的是 `nfo_x`，nfo 落到新竖线后两枚「关」自动跟到（钉宽 `nfo_x − 90 − 6` = 220/308/386/493 ≥ hint 31，余量充足）。验证（`adv_paint.py` 给九个目标与锚点装 `eventFilter` 记录**每一次 Paint 的实际坐标**）：1920/1600/1366/1100 四档宽态下七项全部精确等于 `from_log`（589/482/404/316），paint 中间态帧数为 **0**，宽→窄往返 3 轮后窄态几何与 `text`/`toolTip` 全部不变、重复同步幂等。测试侧踩了两个坑并已修：① `_without_feature` 原来在**同一个窗口**上摘掉方法再跑一次同步当基线，但摘掉后就没人解除上一轮留下的钉宽（`setFixedWidth` 落在控件自身的 min/max 上、跨调用留存），量到的「基线」带着新竖线，比对成了自己比自己；改为**另起一个窗口**全程摘掉两个控制器后取基线。② **离屏测试环境的字体度量既不真实也不稳定**，`tests/conftest.py` 把 `get_fonts` 桩掉 → `QFontDatabase.families()` 为 0、「Sans Serif」解析不到任何字族；而 `resources/fonts/` 只有 Consolas 与 Segoe UI Emoji、**没有任何 CJK 字体**，真跑 `get_fonts` 时 CJK 全部落到 `.notdef`（`horizontalAdvance("隐藏Dock图标（Mac）")` 只剩 91px）。两个环境给出的前缀宽度差约 1.5 倍，于是「隐藏菜单栏图标」那一行放不放得下在测试环境与生产结论不同——该行改为按实测可行性分别断言（放得下必须精确对齐，放不下必须整行放弃且不裁字、不压住 Fixed 前缀），其余六项仍钉死像素；「向左」也改用与环境无关的「新竖线严格在旧竖线（只有通用逻辑时 `checkBox_auto_exit` 的自然位）左侧」来断言。`tests/test_advanced_page_tail_align.py` 扩到 24 项全绿；另把宽态下**刻意**改宽的中间量（钉宽的前导项、被收窄/加宽的容器）从「整块几何不许动」清单里拆成 `_REFS_X_ONLY`（只卡左缘），从动项拆成 `_FOLLOWERS`（只在窄态与往返用例里比对）
- **软件设置-高级页最小化时「点最小化按钮」与两枚「关」左移到「隐藏NFO库管理」、「无」左移到「显示字段内容信息」（最大化时页面、布局、控件、提示词等均保持不变）**：与前两条是同一处代码的**镜像方向**——前两条管最大化右移，本条管最小化左移，且要求最大化态的结果逐位不变。锚点仍是 `checkBox_hide_nfo_nav`（隐藏NFO库管理）与 `checkBox_show_data_log`（显示字段内容信息），「显示刮削过程信息」同样全程不动。改的是 `_sync_advanced_page_tail_align()` 里两处判据：① 「保存日志」「检查更新」两行的「关」去掉 `wide` 判据改为**两态都生效**（宽态计算与原实现逐位相同；窄态把「关」从自然位 393 钉到 313，钉死前导项「开」为 `nfo_x − 「开」x − spacing` = 217）；② 「隐藏窗口」行的落点改为**按态取锚点**——`m = (cx(src_from) if wide else nfo_x) - base`，即最大化对齐「显示字段来源信息」、最小化对齐「隐藏NFO库管理」；而「无」的落点 `n = cx(src_data) - base` 两态同锚、不需分叉。容器宽度仍是 `want_w = n + 「无」sizeHint`，窄态下**由 551 收窄到 411**（实测），三项各自的钉宽仍 ≥ 自身 `sizeHint` 故不裁字，也未越出 `frame_3`。三条取舍：① **`wide` 判据只能从「关」这一处摘掉、不能整段摘掉**——`ok_h` 里那五项（`m > spacing`、`n > m`、两枚钉宽 ≥ sizeHint、`sizeHint ≤ want_w ≤ frame_3.width()`）是「放不下就整行放弃、不裁字」的防线，与态无关；窄态实测 `w_close`=192、`w_mini`=176、`want_w`=411 全落在 `[168, 588]` 内，故不走放弃分支。② **窄态「点最小化按钮」的锚点是 nfo 而非 from_log**，两者窄态分处 313 / 292，取错会让它在还原后停在 292、与两枚「关」差 21px——这正是需求①与②要求窄态落到同一条竖线的用意。③ **方向（左/右）依赖字体度量、不写进断言**：离屏环境里 `mini`(301) / `none`(486) 的自然位反而在锚点(313/495)**左侧**，与用户真实环境（截图中二者在锚点右侧、故看到的是左移）相反；跨环境都成立的硬性质只有「精确落在锚点左缘」，故代码与测试一律只按锚点对齐、不按方向。验证（`adv_paint3.py`，给四个目标 + 两个锚点装 `eventFilter` 记录**每一次 Paint 的实际坐标**）：窄态 1030×753 为 `mini`/`log_off`/`update_off`=313、`none`=495，1000×700 为 303/303/303/475，与两锚点逐位相等；四档宽态 316/404/482/589 与本条改动前**逐位相同**（最大化不受影响）；窄→宽 8~10 帧、宽→窄 3~4 帧，**中间态帧数全为 0**；往返 3 轮窄态几何与 `text`/`toolTip`/`sizeHint` 全不变、重复同步幂等、窄态三项均未裁字（192/176/31 ≥ sizeHint）且未越出 `frame_3`。`tests/test_advanced_page_tail_align.py` 把已过期的「窄态整页逐像素不变」用例按第三组重写为五项：窄态四处对齐、窄态不裁字且容器宽恰为落点+「无」sizeHint（不多留空白）、窄态锚点与全部参照件整块几何不动而搬运工/容器只许改宽度、第二组六项在窄态仍须退让（两枚「关」已排除，它们现在是第三组的窄态目标）、窄↔宽往返逐像素一致且钉宽状态正确（第三组钉 `log_on`/`update_on`/`hide_close`/`hide_mini`，第二组的 `auto_start`/`hide_actor_nav`/`hide_nfo_nav` 仍须解除）；幂等用例也补上两档窄态。测试文件共 32 项全过，相关既有 GUI 用例 122 项通过（唯一失败 `test_naming_filename_checkboxes_column_align[1000]` 为改动前既有失败），`ruff` 全过、`mypy` 零新增
- **软件设置-高级页最小化时「显示字段来源信息」右移到「隐藏NFO库管理」、「停止刮削时」/「隐藏菜单栏图标（Mac）」/「暗黑模式」/两枚「关」右移到「显示字段内容信息」（最大化时页面、布局、控件、提示词等均保持不变）**：与上两条同为镜像方向——上一条管最小化**左**移到 nfo，本条管最小化**右**移到「显示字段内容信息」，两条在同一批控件上方向相反，本条是后一条需求，故窄态以本条为准（宽态两条仍然同时成立）。两枚锚点 `checkBox_hide_nfo_nav`、`checkBox_show_data_log` 全程不动。需求①落在 `groupBox_3`（调试模式）自己的 `horizontalLayout_29` 里，与其余几行不在同一个 grid，故新增独立方法 `_sync_advanced_page_debug_row(wide)`，并**排在 `_sync_advanced_page_align` 取锚点之前**——它的钉宽会改变「显示字段内容信息」的坐标，顺序反了会量到旧值。四处改动：① **前两项一起钉**。该行三项**等分余量**（实测 1030×753 各 196/197/196、1920×1170 各 493），钉住任何一项都会把后面几项一起挪动；只钉前导项「显示刮削过程信息」也能让「显示字段来源信息」落到锚点上，但末位会被重新等分推着右移 ~10px（495 → 505），违反「显示字段内容信息位置保持不变」。改为「钉 web = 锚点 − 行左缘 − spacing」定住目标左缘、「钉 from = content原位 − 锚点 − spacing」定住目标右缘，末位不设钉宽只吃余量，其左缘恒等于「行左缘 + 钉web + 间隔 + 钉from + 间隔」= 原位，**「位置保持不变」是构造上成立的**（容器宽的增减全被末位吸收，与两条钉宽无关），故改窗宽也不会让末位漂移。② **量自然位前必须无条件复位**：带着上一遍的钉宽量到的是自己的落点，而 `pin_from = data_x − nfo_x − spacing` 与 `data_x = nfo_x + pin_from + spacing` 互为反函数会**自我强化成错值**——实测把「显示字段内容信息」从 495 一路拉到 408、目标钉宽缩到 89px。故本方法固定「解除 → `activate` → 量 → 钉 → `activate`」，代价是本行两次重排（行内只有 3 项），且全程在绘制之前完成。③ **`_sync_advanced_page_align` 里「界面外观行」改成甲/乙双路**：宽态仍是「加宽容器 + 两项均分」（保持既有几何），窄态锚点换到更靠右的「显示字段内容信息」后 `2*(锚点−行左缘)−spacing` 实测 644~684 而 `frame` 只有 523~553，甲路必然越界，故改走乙路「钉前导项 `checkBox_hide_window_title` = 锚点 − 容器左缘 − spacing，容器保持 `_ADV_FRAME_LW_W`=550」，容器宽度与右缘与改动前完全相同，不新增任何越界。④ 两枚「关」的落点 `off_x = nfo_x if wide else data_x`。最大化态该方法只做解除——那时「显示字段来源信息」与「隐藏NFO库管理」本就同在一条竖线上（1100×800 起四档全部相等），钉不钉一样。验证（`adv_paint4.py`，给 11 个目标 + 锚点装 `eventFilter` 记录**每一次 Paint 的实际坐标**，再与该步目标态坐标逐帧比对）：窄态 1030×753 `from_log`=313=`nfo_x`、`data_log`=495 **逐位未动**、五项全部 =495、1000×700 同为 303 / 475；宽态 1100/1366/1600/1920 的 8 项与本条改动前**逐位相同**；采样 274 帧、**中间态帧数 0**；往返 3 轮窄态几何与 `text`/`toolTip`/`sizeHint` 全不变、重复同步幂等、窄态十项均未裁字。测试文件扩到 36 项（新增 `test_narrow_debug_row_keeps_content_info_in_place`：对照「只有通用宽幅逻辑」的基线逐位断言「显示字段内容信息」的 x 与 width 都不变，并核对目标钉宽恰为「末位原左缘 − 锚点 − 间隔」），`_dock_row` 改为按态传锚点名、`test_menu_icon_row_aligns_or_defers` 扩到两态、`checkBox_show_from_log` 从「整块不许动」的参照表移入窄态目标表。测试侧踩了一个坑：`checkBox_show_data_log` 判「钉宽已解除」必须查 `maximumWidth() == 16777215`，不能查 `minimumWidth() == 0`——它在 `.ui` 里就写死了 `setMinimumSize(QSize(100, 30))`，min 恒为 100。相关既有 GUI 用例 126 项通过（唯一失败 `test_naming_filename_checkboxes_column_align[1000]` 为改动前既有失败），`ruff` 全过、`mypy` 零新增
- **软件设置-高级页最小化时「刮削结束后自动退出软件」右移到「隐藏菜单栏图标（Mac）」（最大化时页面、布局、控件、提示词等均保持不变）**：锚点 `checkBox_hide_menu_icon` 自身不动，且它是上一条需求②的窄态落点、本条的落点与它逐位相等（实测 1030×753 = 435、1000×700 = 415），宽态它与「刮削结束后自动退出软件」本来就同在「显示字段来源信息」那条竖线上（1100×800 起四档全等），故最大化态一行代码都不用改。改动全在 `_sync_advanced_page_align()` 里：把原先的「阶段一」（钉 `checkBox_auto_start` 把「刮削结束后自动退出软件」搬到新锚点）**按态拆成两半**——宽态那半留在原处（目标即 `checkBox_show_from_log`，逻辑逐位不变），窄态那半**挪到方法末尾、`gridLayout_20.activate()` 之后**新增的「窄态阶段一」块：`menu_x = col_x(menu_icon)`、`pin_m = menu_x − row_x − spacing`、`ok_m` 判三件事（钉宽 ≥ `checkBox_auto_start` 的 sizeHint、让出钉宽后余量 ≥ `checkBox_auto_exit` 的 sizeHint、`menu_x > row_x` 防越界），通过才钉并重排。**为什么窄态那半必须排在末尾**：窄态下「隐藏菜单栏图标（Mac）」的左缘并不是自然位，而是由第 8 行那个插入的固定间隔 `gap_b` 推出来的，而 `gap_b` 又由本方法的 `anchor` 算出——只有本方法中间那批 `invalidate()+activate()` 跑完，它才是终态坐标（实测 1030×753 的 435）；在 activate 之前量到的是上一遍的旧值，会造成一帧错位。反过来钉 `checkBox_auto_start` 只改 (2,1) 那一格的格内几何（第 2 行与第 8 行是不同格），不会把第 8 行的坐标再推走，故两者无循环依赖，天然幂等。窄态进入这一段前先**无条件解除** `checkBox_auto_start` 可能残留的宽态钉宽，否则会量到带钉宽的坐标（同 _sync_advanced_page_debug_row 的教训）。验证（`adv_paint5.py`，给 12 个目标 + 锚点装 `eventFilter` 记录**每一次 Paint 的实际坐标**，再与该步目标态坐标逐帧比对）：窄态 1030×753 `auto_exit`=435=`menu_icon`（`auto_start` 钉宽 374，让出后余量 208 ≥ sizeHint 101）、1000×700 为 415/354/198；宽态 1100/1366/1600/1920 的 8 项与本条改动前**逐位相同**，其余控件（from/data/nfo/stop/dm/off/mini/none）全部未动；采样 258 帧、**中间态帧数 0**；往返 3 轮窄态几何与 `text`/`toolTip`/`sizeHint` 全不变、重复同步幂等、窄态十项均未裁字。测试文件扩到 38 项（新增 `test_narrow_auto_exit_lands_on_menu_icon`：断言两者严格对齐、Fixed 前缀「隐藏Dock图标（Mac）」与「保存重启软件生效」逐位不动、三者宽度均 ≥ sizeHint、且 `checkBox_auto_start` 的钉宽恰为「目标列 − 行左缘 − 间隔」不多留也不压缩），并把 `checkBox_hide_menu_icon` 补进 `_REFS_X_ONLY`（`_snapshot` 原本不含它，取基线会 KeyError）。测试侧踩了两个坑：① 新增的窄态落点表必须写成**元组的元组**（`(("checkBox_auto_exit", "checkBox_hide_menu_icon"),)`），直接写 2 元组会被与 `_NARROW_TARGETS` 拼接后的逐元素解包报 `ValueError: too many values to unpack`；② 别把 `checkBox_hide_menu_icon` 误列进「必须等于通用逻辑基线」的名单——它是上一条需求的窄态目标（离屏 450→495），与基线比必然红。相关既有 GUI 用例 128 项通过（唯一失败 `test_naming_filename_checkboxes_column_align[1000]` 为改动前既有失败），`ruff` 全过、`mypy` 零新增

## v2.1.8 (2026-10-01)

### 修复

- **软件设置-命名页最小化时视频文件名（上下两个）与空格左移到与「使用路径中包含的画质信息」严格上下对齐**：最小化（窄态，拉伸量 <= 0）时把 `checkBox_filename_mosaic`（马赛克组视频文件名）/`checkBox_cd_part_space`（分集分隔符空格）/`checkBox_filename_4k`（画质组视频文件名）向左移动到与 `radioButton_videosize_path`（使用路径中包含的画质信息）上下严格对齐的位置，锚点自身位置保持不变（窄态实测三项 `420→373`、abs `450→403` 与锚点 `403` 一致）；最大化时页面布局、控件、提示等均保持不变（宽态仍走原 `_sync_naming_definition_align` 把 path 右移到 `450` 与视频文件名列对齐，三项恢复设计位置，`_naming_narrow_restores` 为空）。三目标均为组框内绝对定位项，直接 `move(nx, y)` 只改 x 不碰 y/宽高，跨组 `mapTo` 经公共祖先 `scrollAreaWidgetContents_mingming` 中转，越界放弃；`_clear_naming_defn_align` 首行即清窄态登记，保证宽态量到设计锚点且基线为真设计，每遍先清后建、幂等往返自愈。`tests/test_naming_watermark_align.py::test_naming_leaves_narrow_untouched` 同步更新为新断言（三项对齐到 path 列、path 与基线一致、无宽态残留且有窄态登记），宽态对齐与往返用例不变
- **版本号五处对齐到 2.1.8**：`LOCAL_VERSION` 20260930 → 20261001，`VERSION_NAME` v2.1.7 → v2.1.8，与 `pyproject.toml` / `uv.lock` 根包 / changelog 首段五处一致，`scripts/bump.py --check` 与 `test_version_consistency` 全过
- **主页面最大化后左侧栏下方背景与上方颜色断层**：`left_backgroud_widget` 是 `widget_setting` 的子项、`.ui` 设计高仅 700，而 `resizeEvent` 里只同步了父项 `ui.widget_setting.setGeometry(0, 0, 210, height)`，背景条自身滞留 700 高，窗口拉高后底部露出父项底色、与上部各页配色断层。修复紧跟父项同步之后补一行 `ui.left_backgroud_widget.setGeometry(0, 0, 210, height)`（`try/except` 兜底）。实测 1030×753 → 背景条 753、1920×1170 → 1170，往返一致；新增 `tests/test_window_state_matrix.py::test_left_background_follows_sidebar_height` 断言背景条高恒等于侧栏高
- **软件设置-演员页最大化时最下方「开始补全」按钮与上方两个宽度不一致**：需求要改的是最下方按钮 `pushButton_add_actor_pic_kodi` 追平上方 `pushButton_add_actor_pic`，而 `_sync_actor_page_wide_a2_align` 里早已存在同名后缀的局部变量 `kodi = checkBox_actor_photo_kodi`（**复选框**「刮削结束后自动创建」），最初改错对象导致条件全部满足但宽度纹丝不动。在该方法末尾（kodi 复选框右移块之后）新增第 ④ 块：以 `pushButton_add_actor_pic.width()` 为 `target_w`，越界校验通过后先 `("geometry", …)` 登记、再 `lock_width`、再 `setGeometry`（登记顺序 geometry 先 / size 后，窄态逆序还原时 size 先解锁、geometry 最后落定），上方按钮自身不动。实测窄态 130 不变、宽态三枚全 261、宽→窄往返复原 130；新增 `test_actor_kodi_button_matches_upper_width_when_wide`（含「不得连带加宽复选框 `checkBox_actor_photo_kodi`」断言）

### 界面调整

- **软件设置-演员页 Gfriends 相关三处文案调整**：「网络头像库（Gfriends）」去全角括号改为「网络头像库Gfriends」（`radioButton_actor_photo_net`）；「更新 Gfriends」改为「更新Gfriends Inputer」（`pushButton_sync_gfriends`）；「最后更新: -」去掉 `-` 占位符改为「最后更新: 」（`label_gfriends_update_time`），与运行时拼接格式 `f"最后更新: {get_current_time()}"` 对齐，未同步过时显示为空而非多余的破折号。`.ui` 与 `MDCx.py` 同改（`test_ui_structure.py::test_mdcx_py_in_sync_with_ui` 依赖两边一致），`tests/test_actor_info_columns.py` 的 `_WIDE_LEAD_ITEMS` 期望文案同步更新。顺带修一处运行时跳字：`tool_handlers.pushButton_sync_gfriends_clicked` 的 `_done` 回调里复原文案硬编码为「同步 Gfriends」，与设计态的「更新 Gfriends」本就不一致，同步完一次按钮就跳回旧名（同 v2.1.6「按钮与提示文案批量调整」里 `_ACTOR_DB_IDLE_TEXT_MAP` 那个坑），一并改为「更新Gfriends Inputer」。文案变短不引起几何错位——该单选宽度由布局自适应，窄态另有「前导项收窄让位」逻辑锁宽，宽/窄两态对齐照常成立；`tests/test_tool_handlers.py` / `test_ui_structure.py` / `test_actor_info_columns.py` 共 38 项全过
- **软件设置-演员页最小化时上方两个「开始补全」按钮缩到与最下方同宽**：新增 `_ACTOR_NARROW_ADD_BTN_TARGETS = ("pushButton_add_actor_info", "pushButton_add_actor_pic")`，基准取最下方 `pushButton_add_actor_pic_kodi` 的运行时宽度 130（宽态自然回到设计值 261）。因两者都是组框内绝对定位件，只解锁 min/max 不会自动缩回，故给 `_clear_actor_narrow_align` 补 `kind == "geometry"` 分支做几何写回
- **软件设置-演员页最小化时七枚控件左移到与「使用Graphis头像」严格上下对齐**（锚点由 v2.1.7 的「补全完成后自动补全演员头像」改为 A2 列的 `checkBox_actor_photo_ne_face`，锚点自身不动）：三枚绝对定位复选框 `checkBox_actor_info_photo` / `checkBox_actor_photo_auto` / `checkBox_actor_photo_kodi` 直接 `setGeometry` 左移（通用宽幅同步每遍按 `design_x + extra` 重置，天然幂等且无需登记还原）；三枚单选 `radioButton_actor_info_miss` / `radioButton_actor_photo_miss` / `radioButton_server_jellyfin` 走「前导项收窄让位」（`_ACTOR_NARROW_LEFT_PULL_ROWS`，把 Emby 与两个「所有演员」钉窄到让目标左缘正好落在 A2 上的宽度）；来源行 `radioButton_actor_photo_local`（本地头像库）结构不同（`horizontalLayout_95` 的前导项 `radioButton_actor_photo_net` 带 GrowFlag 会自己涨、行尾 `horizontalLayout_97` 是嵌套子布局），另走「stretch 挪给行尾 + 前导项钉窄」（`_ACTOR_NARROW_SOURCE_PULL`），`label_download_actor_zip`（点击下载头像包）随之左移、不独立对齐。三处关键坑：① `anchor_x` 必须在复选框左移**之后**重取，否则后续各行按旧锚点右移会错开 102px；② Qt 会把收窄前导项腾出的余量摊回带 GrowFlag 的项（实测 253→164 又被摊回 222），hl101 尾项 `radioButton_actor_info_miss` 被 `_sync_actor_info_columns` 钉死 `min == max == 252` 吸不走余量、必须插 Expanding 行尾间隔，而 hl96/hl103 尾项可涨、插了反而把文字压回 sizeHint，故 spacer 插入条件按 `minimumWidth() < maximumWidth() and 带 GrowFlag` 判定；③ 前导项收窄下限由 150 降到 130（`QRadioButton` 的 sizeHint 实测仅 52px），让 940 窄态也能对齐。顺带把原「来源行」的就地 `return` 收成闭包 `_shift_source_row()`——原先 `need <= 0` 会连带 `return` 掉后面的「路径行」，导致「选择文件」再也对不到「选择目录」。实测 940/1030 下七枚 == A2 锚点、1920 宽态逐项与改动前一致、窄→宽→窄幂等；`tests/test_actor_info_columns.py` 15 项全过（新增 `test_actor_narrow_controls_land_on_a2_column` / `test_actor_narrow_add_buttons_shrink_to_bottom_button`，`test_actor_narrow_jellyfin_aligns_to_anchor` 改写为对 A2 锚点）
- **读取模式勾选项文案去掉多余的「已」字**：`checkBox_read_has_nfo_update` 由「本地已刮削成功的文件，按更新模式规则重新整理分类」改为「本地刮削成功的文件，按更新模式规则重新整理分类」，读取模式帮助提示（`main_window/init.py`）里两处「本地已刮削成功的文件，重新整理分类」同步去掉「已」。`.ui` 与 `MDCx.py` 同改并保持 `test_mdcx_py_in_sync_with_ui` 通过，`tests/test_ui_structure.py` 的文案回归锁同步更新
- **软件设置-演员页最大化时「清除所有.actors文件夹」右缘对到「选择目录」按钮右缘**：目标 `pushButton_del_actor_folder` 是 groupBox_68 内 `_DOCK_RIGHT` 绝对定位项，宽态被通用宽幅同步钉到 `design_x + extra` 的右缘；而锚点 `pushButton_select_actor_photo_folder`（「本地头像库」行的「选择目录」）随 layoutWidget_8 拉伸，两者右缘在宽态恒差 20px（1920 1559 vs 1579 / 1600 1239 vs 1259 / 1366 1005 vs 1025 / 1100 739 vs 759），窄态则反多 7px，故只需在宽态补这段右移。在 `_sync_actor_page_wide_a2_align` 末尾新增第 ⑤ 块，量出右缘差后 `setGeometry` 右移（与该方法 ① 同款手法）。三条取舍：① **只平移不改宽度**——需求说的是「右侧向右移动」，而两者设计宽本就不同（171 vs 110），拉宽会把按钮撑成另一种长相；② **不登记 `_actor_wide_restores`**——目标是 `_DOCK_RIGHT` 绝对定位项，通用宽幅同步每遍都按 `design_x + extra` 钉回，天然幂等且窄态往返自愈（与 `_ACTOR_PAGE_A2_TARGETS` 同理）；③ 锚点取「本地头像库」行那枚，另一个 `pushButton_select_gfriends_local` 与它在 gridLayout 里同列、窄态 689 / 宽态 1579 两态右缘恒等。实测 1920 / 1600 / 1366 / 1100 四档宽态右缘全对齐、窄态 1030 逐像素不变且往返复原。`tests/test_actor_info_columns.py` 里该按钮原被 `_WIDE_REFS` 锁成「宽态不得移动」，按新需求移出该表、改由新增的 `test_actor_del_folder_button_right_edge_aligns_to_select_folder` 专项覆盖（含窄态不动 / 四档宽态对齐 / 只平移不改宽 / 幂等 / 往返复原 / 两个「选择目录」右缘恒等六项断言），该文件 16 项全过
- **刮削页读取模式区说明文案改写**：「按Emby标题、设置-翻译、NFO等设置利用本地nfo更新nfo信息」（`label_37`）改为「按Emby标题、设置-翻译、NFO页设置利用本地nfo更新」。原文案「NFO等设置」会被读成「NFO 等设置项」，而实际指的是设置页的 NFO 页，故点明为「NFO页」；句尾重复的「nfo信息」一并删去（前半句已说明是「利用本地nfo更新」）。`.ui`（`&lt;p&gt;` 转义形式）与 `MDCx.py` 同改并保持 `test_mdcx_py_in_sync_with_ui` 通过，`tests/test_ui_structure.py` 的 `_READ_MODE_UI_TEXTS` 回归锁同步更新。该标签是 `gridLayoutWidget_2` 内 `horizontalLayout_128` 的富文本标签（横向 Minimum / 纵向 Fixed），不进 `_naming_label_painted_height` 那套渲染测高链路，文案变短不引起任何布局同步变化。`main_window/init.py` 使用说明里「软件将按照…「设置→NFO」等的设置项，利用本地 nfo 更新 nfo 信息。」是另一处独立散文（词序与标点不同、nfo 两侧带空格），不在本次范围，未动
- **演员页「补全Kodi/Plex/Jvedio演员头像」组说明与对应运行日志文案统一**：设置页提示 `label_414` 由「将为待刮削目录的每个视频在同目录创建一个 .actors 文件夹，并将该视频的演员图片放在该文件夹中」改为「将为等待刮削目录的每个视频在同目录创建一个.actors文件夹，并将该视频的演员图片放在该文件夹中」（「待刮削」改「等待刮削」以免与「刮削目录」设置项混读，`.actors文件夹` 去掉两侧空格、与同组按钮「清除所有.actors文件夹」写法一致）；运行日志 `tools/emby_actor_info.py` 里那条同义提示同步改成「💡 将为等待刮削目录中的每个视频创建.actors文件夹，并补全演员图片到.actors文件夹中」，两处说法从此一致。净字数 −1，`label_414` 是 `groupBox_68` 内绝对定位件（`50,20,631,41`、`wordWrap` + `heightForWidth`）、宽度固定，折行行为不变，几何无需调整；`.ui` 与 `MDCx.py` 同改并保持 `test_mdcx_py_in_sync_with_ui` 通过。`ruff check mdcx/tools/emby_actor_info.py` 全过，`tests/test_ui_structure.py` 15 项与 `tests/test_emby_actor_manager.py` 42 项全过

## v2.1.7 (2026-09-30)

### 修复

- **最大化时窗口四周先出现一大圈黑屏、然后才放大（视觉不连续）**：离屏实测（`maxperf.py`，1030×753 还原态 → 最大化）——`showMaximized()` 在 **+4.9ms** 返回（窗口矩形此刻已经是目标尺寸），`resizeEvent` 却同步阻塞 **383ms**（内含两次 `_sync_page_layouts` 218.6 + 382.9ms），主窗口**第一次 Paint** 要等到 **+609ms**，全部落定 +617ms。也就是说系统已经把窗口置成最大尺寸、Qt 一次都没绘制，新露出的那一圈自然是黑的，与用户描述完全吻合。cProfile 最大一笔是 `{built-in method pixelColor}`——**422,572 次调用 / 0.180s tottime**，全部来自命名页为模板预览加的 `_naming_label_painted_height`（把标签渲染到白底 pixmap 再从底部回扫文字下沿，一次最多 2000 行 × 600 列逐像素）。两条修法：① `_sync_naming_template_section` 加可见性守卫 `if not box.isVisibleTo(self): return`，命名页不可见时整段跳过（省掉两次 pixmap 渲染扫描 + 网格重排 + 后续 6 个 groupBox 的 move），切到该 tab 的 `currentChanged`→`QTimer.singleShot(0, …)` 与滚动区 `showEvent` 本就会补齐；② `_naming_label_painted_height` 改用原始字节回扫——`convertToFormat(Format_Grayscale8)` + `constBits().asstring()` 取缓冲后按行做 bytes 切片整体比较（纯 C 层），取样规则仍是 `x` 从 0 到 width 步进 2，与旧逐像素实现结果逐位一致（`cmp_scan.py` 实测 `label_66` 382/382、`label_name_template_preview_result` 65/65、`label_176` 18/18、`label_249` 279/279），并保留逐像素旧路径作兜底。实测 `resizeEvent` 阻塞 383ms → **36.2ms**（命名页，最重）/ **1.0ms**（其它页），首次绘制 +609ms → **+52ms** / **+7ms**；逐页扫最大化与还原两向，最重的信息管理与命名页也只到 ~50ms 出图。**顺带排除掉一个错误方向**：初版按「`WA_TranslucentBackground` 分层窗口 + DWM 无法采样导致过渡动画前几帧全黑」猜，加了 `DwmSetWindowAttribute(DWMWA_TRANSITIONS_FORCEDISABLED)`；实测生效配置是 `D:\@Data\MDCx\actor.json` 的 `window_title = "show"`（`window_radius=0`、`window_border=0`、`WA_TranslucentBackground=False`、`FramelessWindowHint=False`），根本不是分层窗口，那段已撤除。另记一条 PyQt6 坑：`bytes(img.constBits())` 抛 `IndexError: voidptr object has an unknown size`，必须 `constBits().asstring(size)`——第一版就踩了这个导致优化静默退回慢路径，靠性能数据才暴露出来
- **三页（演员 / NFO / 高级）最大化或还原时控件先落错位、再跳到目标位（合并为一条，三者同病同源）**：
  - **共因（演员页证据最完整）**：`CustomScrollArea.sync_wide_children_width()` 只保证「不越界」——右缘控件按 `_DOCK_RIGHT` 钉在右缘、宽幅控件按「设计宽 + extra」铺开，而对齐目标要等**下一轮事件**里才对齐到基准线，于是「右缘锚定」这个中间态先被绘制出来（演员页表现为「先在右边、再跳到左边」，NFO 页与高级页方向相反：NFO 页「先在左边、再跳到右边」，高级页是最大化 `hide_nfo_nav`=448 vs anchor 624、还原 `checkBox_dark_mode`=624 vs anchor 371——用户说的「最小化时暗黑模式会从右侧漂移到当前位置」）
  - **共修①**：`CustomScrollArea` 新增 `_post_wide_sync_hook` + `_run_post_wide_sync_hook()`，在 `resizeEvent` / `showEvent` 里**紧跟** `sync_wide_children_width()` 调用，使「拉伸 + 对齐」在同一个事件内原子完成，中间态没有机会被绘制；带重入保护 `_in_post_wide_sync_hook`——钩子内部 `setGeometry` 一旦连带引发本滚动区再次 resize，没有保护会无限递归（实测会把栈打爆），重入时直接跳过（外层那一遍已在正确几何上跑完，结果不会丢）。演员页挂「三行控件对齐」、NFO 页挂 `_sync_nfo_page_align()`（把七个 NFO 对齐控制器 `_sync_nfo_colon_align` / `_sync_nfo_right_column_align` / `_sync_nfo_title_plot_align` / `_sync_nfo_row_align` / `_sync_nfo_tail_align` / `_sync_nfo_set_align` / `_sync_nfo_field_tips` 整条重跑；七者都是纯函数、双向幂等，重复调用安全，休眠页直接 return）、高级页挂零参钩子 `_sync_advanced_page_wide_hook()` 调 `_sync_advanced_page_align(self._adv_scroll, wide_synced=True)`——新增的 `wide_synced` 参数让从钩子进来时跳过递归再跑一次 `sync_wide_children_width()`（宽幅同步刚在 `_run_post_wide_sync_hook` 里做完，列宽已是终态）。NFO 页原 hook 是 no-op（没挂钩子）恰是错过补救机会的铁证：离屏事件序列 `wide(0,918,498)` 拉伸后已发散 → `hook` 无操作 → 下一拍才 `rca(0,950,498)→(675,498,498)` 补上
  - **共修②·判据换成几何量**：一律不用 `isMaximized()`，改用几何拉伸量 `_actor_page_stretch_extra()` / `_scroll_stretch_extra(scroll)`（= `viewport.width() - content._wide_children_design_width - scroll.content_right_trim()`，与 `sync_wide_children_width()` 同公式；「被拉宽」这件事只有一个判据来源，`_actor_page_stretch_extra()` 改为委托给共用静态方法）。窗口管理器最大化时**先发尺寸、后发状态标志**，那一拍 `isMaximized()` 还是 False，改用几何量后拉伸与对齐永远发生在同一拍，与标志到达顺序无关；还原态拉伸量为负时**直接 return，一个 setGeometry 都不发**
  - **共修③·跨父控件坐标一律经公共祖先归一**：跨分支 `QWidget.mapTo` 要求目标是调用者祖先、直接映射得未定义值（离屏恒偏 +302），一律经公共祖先 content 中转。演员页曾直接比 `widget.x()` 误报「恒差 20px 未对齐」，改 `mapTo` 归一到 content 坐标系后才对上；页面也一律按**内容控件名**认（演员页 `scrollAreaWidgetContents_yanyuan`、NFO 页 `scrollAreaWidgetContents_nfo`），不写死滚动区对象名（演员页是 `scrollArea_12` 而 `scrollArea_9` 是字幕页，写死会装错地方静默失效）
  - **验证（中间态是否被绘制是唯一硬证据）**：演员页用 `verify_actor_mapto.py`（最大化三场景 targets `[860,860,860]` == anchor `860`；还原态 `[454,454,494]`/523 与设计几何逐像素一致；`checkBox_actor_photo_kodi` rect 恒 `(300,130,141,40)`）；NFO 页用 `probe_2tasks.py`（`hook(after)` 同拍完成对齐，最终 `critic == custom` 严格同列、gap=0；还原态 `colMinW1=0` / `critic=444` / `custom=492` 与修复前完全一致）；高级页用 `adv_paint.py`（给两个控件装 eventFilter 记录**每一次 Paint 时的实际坐标**：最大化 4 帧全是 `(624, 624, 624)` 三者已对齐、还原 4 帧全是 `(371, 238, 371)`，**中间态一次都没被画出来**；还原态 `lw_w=542` / `extra=-26` 与修复前逐像素相同）
  - **与同族其它对齐议题的共性**：本页三条与同版本其它页的「最大化对齐」条目（字幕页、刮削目录页、命名页画质行与水印页）共享同一套根因与手法——钩子必须排在宽幅同步**之后**、休眠页直接 return、判态用几何拉伸量、跨控件坐标经公共祖先归一；各页具体锚点与手法见各自条目
- **演员页「点击下载演员数据库」被推到很远**：根因不是对齐逻辑而是 sizePolicy——标签横向策略是 `Minimum`，`horizontalLayout_159` 把 306px 剩余空间**全给了它**（它 sizeHint 只有 117px），而标签是 `AlignCenter`，文字被推到单元格中央。`.ui` 与 `MDCx.py` 同改横向为 `Fixed`，剩余空间无人吸收，标签自然贴紧文字。实测两态间距均为 6px（还原态复选框右缘 430 → 标签 x436；最大化 768 → 774），`w=117` 恒等于 `text_hint`
- **翻译页「简介」「演员」两组间距收紧**：根因是 Qt 把「容器多出来的高度」在顶/行间/底之间均分——`layoutWidget_20` 高 418 而 `gridLayout_50` 的 sizeHint 只有 352，多出的 66px 被均分成顶 16 / 行间各 +16 / 底 18，说明文字行顶落到 120（低了一行多），且 14 行文字 × 20px 正好 = 280 = 标签高，最后一行贴住框内框。简介组内「翻译方式」与「双语显示」之间同理（`label_176` 的 `sizeHint=(273,34)` 但只画 24px，富文本 `<p>` 段落边距吃掉 17px）。修法：新增 `_sync_fanyi_group_spacing()` 整条重算——先解除 `label_176` / `label_249` 的固定高度再 `grid.invalidate()+activate()`（否则量到的是被裁的残缺高度，会越量越小最后裁字），用 `_naming_label_painted_height` 量真实绘制高度（复用命名页已有的渲染扫描法，不写死行数；富文本必须取 `heightForWidth`，`QFontMetrics` 对 HTML 无效），容器高度按网格 sizeHint 定、组高 = 容器底 + `_FANYI_BOX_BOT_PAD`(9)，`groupBox_85..89` 按设计基准减增量上移（幂等无累积漂移）。`_FANYI_ACTOR_TOP_PAD=30` 使说明文字行顶落在 102，正好上移一行 20px；`_FANYI_INTRO_GRID_GAP=10` 管简介组内间距。实测还原态 `groupBox_83 (30,1125,675,190)`、`layoutWidget_13` h=90、`frame_5` y=130、`label_176 (136,72,499,18)`、`groupBox_84 (30,1335,675,414)`、`layoutWidget_20` h=383、`label_249 (136,102,499,281)`、后续组 y=1769/1940/2111/2282/2453、内容高 2675，painted 16≤18 与 279≤281 **无裁字**；最大化态列宽变宽折行变少，`label_249` h=181、`groupBox_84` h=314、内容高 2583；连跑 3 遍几何完全一致（幂等）
- **各页组框底部空白批量收紧，设计几何与后续组同步上移**：命名页 `groupBox_8` 1051→820（`_NAMING_PREVIEW_H` 模板预览框 128→64，`groupBox_46` 501→475）；NFO 页 `groupBox_81` 1071→978；字幕页 `groupBox_45` 451→425；下载页 `groupBox_44` 301→210、`groupBox_52` 277→235；翻译页 `groupBox_84` 520→440、`groupBox_85..89` 1905→1825 … 2589→2509；命名页 `groupBox_40/77/62/65/67/37/38/14/34/51/66` 按同一增量整体上移保持设计间距。滚动内容高度同步下调：`scrollAreaWidgetContents_mingming` 3840→3555、`_fanyi` 2854→2774、`_nfo` 1200→1107、`_wangluo` 1916→1755、`_xiazai` 1732→1690、`_zimu` 860→834。`label_name_template_preview_result` 底部留白改由 `_update_name_template_preview()` 在三个退出点重新同步（该标签 painted 65 / hFW 82 / sh 99 / 旧 minimumSize 还钉着 82，钉高必须按 painted，否则下方留白；同类的 `label_66` 是 painted 282 / hFW 287 / sh 387）。顺带修掉一处崩溃：命名页曾调用已从 PyQt6 移除的 `documentLayoutBlockContentsRect`
- **命名页同步不得加「输入指纹相同就整体返回」的短路（反例留档）**：`sync_wide_children_width()` 会把 `groupBox_8` 与后续 groupBox 按**登记的设计几何复位**，若在其后用「标签宽度/文字未变」当指纹早退，会留下「`groupBox_8` 已收缩、后续组仍在设计位」的错位缝（实测 `box_h=737` 而 `follows` 仍是 `[859,1289,1659]`）。正确做法只用可见性守卫，`_sync_naming_template_section` 里已留注释警示
- **补回 `MDCx.py` 与 `MDCx.ui` 的失同步（`test_ui_structure` 长期红的真因）**：v2.1.6 那条「更新nfo文件TMDB ID字段（140→170 向右拓展）」只改了 `.ui` 的 `pushButton_actor_db_update_nfo_tmdbid` 宽度、没有重编译 `MDCx.py`，两边宽度长期不一致（`.ui`=170 / `.py`=140），`tests/test_ui_structure.py::test_mdcx_py_in_sync_with_ui` 因此一直失败。按 `.ui` 把 `MDCx.py` 补成 170。**剩余差异与本条无关**：用测试完全相同的流程（`python -m PyQt6.uic.pyuic` + `uv run ruff format`）重编译比对，14240 行 vs 14232 行、全部差异均为 ruff 折行策略（`_translate(...)` 单行 vs 折行、`setStyleSheet` 位置），源于本机 ruff 0.15.12 与生成仓库版时的 ruff 版本不同，非内容不一致；若要彻底转绿需在目标 ruff 版本下重新 `pyuic6` + `ruff format` 全量重生成 `MDCx.py`（会产生大量纯格式 diff），本次不做
- **点击「软件设置-翻译」「软件设置-NFO」有几率进程直接退出（`crash/` 下无新日志）**：是**栈溢出**而不是异常。`faulthandler` 抓到的当前线程栈是 `_naming_label_painted_height`（`main_window.py:2509`）与 `eventFilter`（`main_window.py:642`）无限互调——`_naming_label_painted_height()` 内部 `lbl.render(pixmap)` 会向 `label_66` 派发 `QEvent.Resize`，而 `__init__` 里 `ui.label_66.installEventFilter(self)` 的 Resize 分支又同步回调同名方法，两者互为递归且**没有任何标志拦得住**（原有的 `_naming_resyncing` 只在 `_sync_naming_template_section` 内部置位，拦不住 eventFilter 这条独立进来的路径），最终 `STATUS_STACK_OVERFLOW`（`0xC00000FD`，进程退出码 `-1073741571`）。栈溢出不是 Python 异常，`sys.excepthook` 抓不到，所以 `crash/` 下不会有日志——最初翻到的 4 份 `crash_20260930_12{323,331,335,350}_py.log` 全是 `AttributeError: 'QAbstractTextDocumentLayout' object has no attribute 'documentLayoutBlockContentsRect'` 的**旧账**（v2.1.6 及更早的启动期崩溃：时间早于相关提交 3 小时、堆栈行号 2372 与现码 2493~2540 对不上、当前代码 `grep` 与 `git log -S` 均零匹配），与本次无关，保留不删。最小复现序列：切翻译 tab(5) → `showMaximized()` → 切 NFO tab(8) → `showNormal()`（`so_repro.py`，修复前第一个 cycle 就爆）。修法三处配套：① `__init__` 状态区新增 `self._naming_scanning` 重入门闩；② `_naming_label_painted_height` 由 `@staticmethod` 改为**实例方法的门闩包装**（重入时返回 `lbl.height()` 这个中性值，不误触发外层重排判断），实体下沉为新的 `@staticmethod _measure_painted_height()`；③ `eventFilter` 的 label_66 Resize 分支守卫补上 `and not self._naming_scanning`。所有调用点均已核对为实例调用（`_sync_naming_template_section` / `_sync_fanyi_group_spacing` / `eventFilter`）。验证：最小复现序列跑完 `DONE OK`、faulthandler 日志为空；`crashstress.py` 五阶段压力测试全过——① 9 个设置 tab 来回切 40 轮；② 翻译↔NFO + 最大化/还原 12 轮；③ 连续 resize 30 次；④ 设置页↔主界面 + 最大化/还原 15 轮；⑤ 7 档窄宽（700/760/820/880/940/1000/1030）强制折行，`label_249` 高 460→281 随宽度递减、`groupBox_84` 593→414，符合预期。命名页/翻译页/演员页几何回归与修复前基线**逐项完全一致**（命名页 820/382 → 705/282 → 769/331、翻译页 `groupBox_83` 194 / `groupBox_84` 314、演员页 `targets=[830,830,830]`、`kodi=(419,130,141,40)`）
- **版本号五处对齐到 2.1.7**：`VERSION_NAME` v2.1.6 → v2.1.7，与 `pyproject.toml` / `uv.lock` 根包 / changelog 首段五处一致（`bump.py` 因 `LOCAL_VERSION` 已是 20260930、重复替换无变化会抛「版本号替换失败」，故三处直接改），`scripts/bump.py --check` 报「五处版本点一致」、`test_version_consistency` 3 项全过
- **字幕页最大化时两处控件左对齐到「视频文件名」、空白纵向铺平**：① 「新添加字幕的视频在结束后重新刮削」复选框被通用宽幅同步判为 `_DOCK_RIGHT`（右缘 661 ≥ 组宽 701×0.9）飞到右缘，现宽态按「视频文件名」左缘 `move()` 回来（只改 x，y/宽高不动，越界放弃）；「点击下载字幕包」是横向均分布局内控件，`setGeometry` 会被 layout 覆盖，改走高级页同款 `insertSpacing` + `changeSize` 固定间隔 + `label_102` 钉回 `sizeHint` 宽（只允许左移），且该 `QLabel` 设计态是 `AlignCenter`（格子拉宽后左缘对了、可见文字仍居中偏右），宽态同步改 `AlignLeft|AlignVCenter`、窄态恢复 `AlignCenter`。跨分支 `QWidget.mapTo` 要求目标是调用者祖先、直接映射得未定义值（离屏恒偏 +302），一律经公共祖先 content 中转。② 底部空白：内容短于视口是结构性的，填充量经统一公式 `_zimu_wide_rows` 按 `filler//8` 纵向均匀铺进行距（上方网格四行各增一行最小高、长按钮/复选框行/绿色说明同步下移，余量作组内底垫），组框高度按绿色说明底部贴合（`min(425+filler, teal底+12)`，组间距保持设计值 19 不放大），不再出现单块大空白；窄态/最小化清零行最小高、复位复选框行 y，其余由通用同步按设计几何复位，逐像素不变。只改 `main_window.py` 运行时几何，`.ui` 未动。验证：`tests/test_window_state_matrix.py::test_zimu_rows_align_to_filename_when_wide`（宽态对齐/铺排/贴合/幂等、窄态逐值复原）通过，全矩阵 49 通过、仅剩预存无关失败 `test_setting_all_tabs_wide_boxes_fill_viewport`（高级页 `groupBox_83`，干净树已确认）

- **软件设置-演员页最大化/最小化两态下九个控件没有与各自锚点上下对齐**（窄态 `_sync_actor_page_narrow_align` + 宽态 `_sync_actor_page_wide_a2_align` 两个方法，四拍串联）：「仅缺少信息的演员」「仅缺少头像的演员」「本地头像库」「点击下载头像包」没有与「补全完成后自动补全演员头像」上下对齐；「选择文件」没有与「选择目录」上下对齐、且「演员信息数据库」显示框右侧没有拓展到右移后的「选择文件」按钮左侧；「Jellyfin」没有与「补全完成后自动补全演员头像」上下对齐。锚点是 `checkBox_actor_info_photo`（`groupBox_64` 内绝对定位、`_DOCK_RIGHT` 右缘锚定，窄态 `abs = 480 + extra`，随窗口拉伸量线性移动）与「选择目录」按钮（`pushButton_select_gfriends_local`，两个「选择目录」按钮窄态 abs 恒为 `601 + extra`），而各目标分属五行布局、容器宽度各不相同，现状分别是 445 / 449 / 408 / 492 / 441（1030×753 实测）。新增 `_sync_actor_page_narrow_align()`（挂在 `_sync_actor_page_wide_hooks` 第三拍与 `_sync_page_layouts()` 尾部，保证窄态第一帧就对），判据沿用几何量 `_actor_page_stretch_extra() <= 0` 而非 `isMaximized()`，`need <= 0` 一律不动（窗口比 extra < -35 的更窄时目标已在锚点右侧，需求只说「向右移动」，间隔只能右推不能左拉），宽态第一步清干净即 return，**最大化态一个像素不碰**。第二组需求是**最大化态**把六个控件对到 A2 列（「使用Graphis头像」`checkBox_actor_photo_ne_face`，实测 abs 1920=652 / 1600=546 / 1366=468 / 1100=379，一律运行时 `mapTo` 实测不写死）：「Jellyfin」「补全完成后自动补全演员头像」「本地头像库」「点击下载头像包」「刮削结束后自动补全演员头像」左移，「仅缺少头像的演员」「刮削结束后自动创建」右移，该锚点自身不动、最小化态布局控件组件全不变。新增 `_sync_actor_page_wide_a2_align()` 与 `_clear_actor_wide_align()`，登记走第三套`_actor_wide_restores`（`size`/`geometry`/`stretch` 三类，同样逆序写回），窄态第一步清干净即 return、只把 `layoutWidget_12` 按设计几何还原（它不进任何 registry，通用同步不会自愈）。四类控件四种手法：① 两个「自动补全演员头像」是 `_DOCK_RIGHT` 的绝对定位项，通用宽幅同步每遍都按 `design_x + extra` 钉回右缘，故用 `shift_to` 同款 `setGeometry` 左移，越界则放弃；②「点击下载头像包」不是独立目标——它在 hl95 尾部子布局 hl97 内，跟着「本地头像库」的尾部 stretch 走即自动到位（1920 实测 local=652 / zip=717）；③ hl103（服务类型行）与 hl95（来源行）容器都是随窗口变的一整列，用**前导项收窄让位**——把目标前的末项钉到「让目标左缘正好落在锚点上」的宽度，并把 stretch 从头一项挪给目标之后的尾项（否则 Qt 把余量摊回头一项、钉窄失效）；④ hl96（仅缺少头像的演员）所在 `layoutWidget_12` 恒为 511，塞不下 203px 右移量，先把容器加宽到 `2×目标相对位置 + spacing` 让两等分项各占一半，让位量低于 `_ACTOR_PAGE_A2_MIN_LEAD_W=150` 时宁可不移。「刮削结束后自动创建」kodi 未进 registry，必须跟 `miss` 一起到位，故这一段排在 hl96 循环**之后**（量到的是 miss 移动后的新 x），且只认 `dx > 0`——需求②说的是「向右移动」，窗口不够宽时 A2 反而在 kodi 左侧（1100 宽实测 A2=379 < 原位 449），此时必须原地不动而非反向拖走。**四拍顺序坑（本条最关键的一处）**：`_sync_actor_page_wide_a2_align` 必须排在 `_sync_actor_info_columns` **之后**——后者末尾 `grid.invalidate()+activate()` 会把 `_DOCK_RIGHT` 的绝对定位项重新钉回右缘，把①刚对好的两个「自动补全演员头像」弹回 1348/1028/794（实测确认）；也正因如此①的 `setGeometry` 从 `_sync_actor_page_align` 挪进了本方法。同理本方法内刻意**不**调 `actor_scroll.sync_wide_children_width()`，那会把①的成果整个抹掉。实测（`probe18.py`，同宽度下摘掉本方法取基线，正确区分「让位项只让宽度」与「真回归」，1920/1600/1366/1100/1920回/1030窄/1000窄 七档全部 OK）：宽态四个左移项 abs 全 == A2（652/546/468/379）、zip 紧随 local、两个右移项 need>0 时落到 A2 / need<=0 时原地不动且无左拉；三个让位项（Emby/所有演员/网络头像库）**左缘纹丝不动**只让宽度；锚点三兄弟与「仅缺少信息的演员」「清除所有.actors 文件夹」「补全范围：」的 x 与 width 全不变；窄态 `layoutWidget_12` 复原 511。验证：`tests/test_actor_info_columns.py` 累计 12 项全过（本条补 3 项：宽态四目标 == A2 + 让位项左缘不动 + 锚点不动 + 只右移不左拉、「窄态与摘掉宽态那一拍的基线逐项相等」、「幂等 + 宽→窄→宽往返复原」），摘掉 `main_window.py` 改动后 4 项即红、装回去全绿；相关 53 项回归与全量 `pytest tests/` 2186 项过（5 项预存的真实联网用例失败与本次无关：`aventertainments` 连接被重置 ×3、`wiki_rate_limit` UA 断言 ×2；`pytest_sessionfinish` 里的 `PreviewImageLoader` 线程 access violation 是干净树预存的退出期噪声）三行三条不同的让位手法，共同前提是 **`QSpacerItem` 的 `minimumSize` 是 (0,0)，行内需求超出可用宽时它第一个被压扁**（实测 `hl101` 插 13px 间隔、目标只走了 6px），所以每行都得先给目标右侧腾出等量宽度再插固定间隔：① `hl101`（`layoutWidget_15`，容器宽每遍被 `_sync_actor_info_columns` 重设为设计值 511、加宽会溢出组框右缘）用「目标收窄 + 同行 `setSpacing(6+need)` 撑开」，让位量由「容器可用宽」反推以保证行内总需求恒等于容器宽——这一点是必须的，用固定间隔时即便算出精确宽度，行内总需求与容器宽仍有 ±2px 偏差，Qt 会把富余摊到行首、令同排的「所有演员」整体右移 2px（实测 186→188）；② `hl96`（`layoutWidget_12`，容器恒 511）同 ①；③ `hl95`（`layoutWidget_8` 的来源行，容器是随窗口变的一整列、没有可收窄的固定容器）改用 **stretch 让位法**——把 stretch 从前导项挪给行尾 `hl97`「点击下载头像包」（stretch=0 的 `Minimum` 项回到自己的 sizeHint，「网络获取头像」实测 216→129 即其 sizeHint），行里凭空多出的宽度全被 hl97 吸收，此时插入的固定间隔才不会被挤瘦；「点击下载头像包」右缘停在原处、只有左缘右移，其文字实测为左对齐（`.ui` 写的是 RTL 方向的 `Qt::AlignLeading|Qt::AlignLeft`，实测 `AlignLeft` 生效），故文字随左缘右移。每行插完都实测回读一次并按差值修正（间距与让位量同步增减 / `spacer.changeSize` 三轮收敛），不依赖 Qt「有富余就分给可拉伸项」模型的细节；让位后目标会窄到夹住自己的文字（`_ACTOR_NARROW_MIN_DONOR_W = 150`）时宁可不右移。第二轮补的两处各有特殊之处：④ `hl103`（`groupBox_43`/`gridLayoutWidget_25` 的服务类型行，「Jellyfin」）用 ① 的手法，但**行宽随窗口变**（col1 = 503/473/1393）、两个单选是「均分可用宽」关系而非固定设计宽，故钉宽值必须取当前实宽（`_ACTOR_NARROW_SCOPE_ROWS` 的 locks 里写 `None` 即表示钉到当前宽），且**可用宽必须取行自身矩形宽而不是容器宽**——容器 639 而行只有 503，取容器宽会把「Emby」推出 136px，这是本条最容易踩空的一处；⑤ `hl155`（`gridLayoutWidget_14` 的路径行，「选择文件」）用「路径框钉到『选择目录』按钮左缘减行间距」——该行尾部本就有一个 Expanding 间隔，故「路径框 + 按钮 + 间隔」恒等于行宽，按钮即落到那一列；两个按钮设计宽同为 110px，「与选择目录左缘对齐」和「右缘对齐」在这里是同一件事（用户截图上的红色竖线画在按钮右缘，按左缘对齐即同时满足两种解读）。路径框收窄到 `_ACTOR_NARROW_PATH_MIN_W = 200` 以下时宁可不右移。**登记与还原单独建 `_actor_narrow_spacers` / `_actor_narrow_restores`**、不复用 `_actor_info_width_locks`：后者还原写的是 `setFixedWidth(saved)` 永不真解锁，且本方法跑在 `_sync_actor_info_columns` 之后、真解锁会顺手拆掉那一拍刚钉在 253/252 的锁；**还原必须逆序**（同一控件一趟里被钉两次：先钉设计宽、再钉让位后的收窄宽，正序写回会让中间值覆盖原值、把控件永久钉死在窄态的收窄宽上——实测 `hl96` 的「仅缺少头像的演员」卡在 237 再也回不去，宽态随之被带歪）。实测（`probe9.py`/`probe13.py`，确定性宽度序列 1000×700 → 1030×753 → 1000×700 → 1920×1170 → 1366 → 1030×753 → 940×700 ×2 → 1600 → 1030×753 → 1100 → 1030×753 → 1920×1170 → 1030×753，与修复前输出逐行 diff 共 70 行差异**全部落在窄态**，宽态 1920/1366/1600/1100 **零差异**）：1030 宽下三目标 445/449/408 → **458/458/458**（= 锚点）、「点击下载头像包」473 → 523、hl101 spacing 6→19、hl96 6→15、hl95 count 3→4 且 stretch=(0,0,0,1)；第二轮 1030 宽下「选择文件」492 → **579 = 「选择目录」579**、路径框 300 → **387**（右缘 573 + 间距 6 = 579，与按钮左缘严丝合缝）、「Jellyfin」441 → **458 = 锚点**、「Emby」保持 186；1000 宽下「选择文件」→ 549 = 「选择目录」549、路径框 357、「Jellyfin」→ 428 = 锚点，两个 `miss` 的 `need` 已为负故原地不动；940 宽下「选择文件」→ 489 = 「选择目录」489、路径框 297、「Jellyfin」need 已为负原地不动，三个原目标全在锚点右侧故一个都不动；重复出现的 1030 段数值完全一致（幂等 + 窄↔宽往返自愈）。参照控件全程不动：`checkBox_actor_info_photo`、`radioButton_actor_info_all`(186)、`radioButton_actor_photo_all`(190)、`label_299`、`radioButton_actor_photo_net` 左缘 186、`radioButton_server_emby`(186)、`pushButton_select_gfriends_local`（「选择目录」自身）、路径框左缘 186。验证：`tests/test_actor_info_columns.py` 补 5 项（窄态 940/1000/1030 三档「对齐锚点 + 参照控件纹丝不动 + 只右移不左拉 + zip 与 local 同进退」、「最大化态与摘掉新逻辑的基线逐项相等（含 width/spacing/stretch）」、「幂等 + 窄→宽→窄往返复原」、「「选择文件」与「选择目录」左缘对齐 + 路径框右缘拓展到按钮左缘 + 只扩不缩 + 基准按钮不动」、「「Jellyfin」与锚点对齐 + Emby 不动 + 只右移不左拉」），摘掉 `main_window.py` 改动后这 5 项即红、装回去全绿；`test_window_state_matrix.py` 等相关 49 项、`test_actor_info_columns.py` 9 项全过，全量 `pytest tests/` 2183 项过（5 项预存的真实联网用例失败与本次无关：`aventertainments` 连接被重置 ×3、`wiki_rate_limit` UA 断言 ×2；`pytest_sessionfinish` 里的 `PreviewImageLoader` 线程 access violation 是干净树预存的退出期噪声）
- **软件设置-刮削目录页两处横向没有与各自锚点上下对齐**（新增 `_sync_guaxiaomulu_checkbox_align()`，与同页既有的文件清理提示对齐并列成两拍）：① 最大化/最小化时「获取软链接指向的原文件的分辨率」左移到与「记录刮削成功的文件列表」严格上下对齐（两态都做，实测两态都是 -58px）；② 最大化时「刮削时自动清理」左移到与「记录刮削成功的文件列表」严格上下对齐；③ 最小化时「刮削时自动清理」右移到与「启用」严格上下对齐。三个锚点自身（`checkBox_record_success_file` 与 `checkBox_clean_file_ext` 所在的「启用」列）均保持不动。实测几何（abs = 相对滚动内容左缘，1030×753 窄态 / 1920×1170 宽态）：窄态 record 383 / definition 441 / 前导项 186 / auto_clean 528 / 启用 579，宽态 record 828 / definition 886 / 前导项 186 / auto_clean 1418 / 启用 1469——需求①两态右移量同为 58px（锚点列随窗口右移，而软链接行的前导项恒钉在 col1 起点），故实现不能写死偏移量，一律运行时 `mapTo` 实测。**两条手法（根因不同，勿混用）**：① 「获取软链接指向的原文件的分辨率」所在的 `horizontalLayout_115` 是 `gridLayout_19` col1 里的子布局，两项都是 `Minimum` 策略且总需求恰好等于 col1 宽（窄 504 / 宽 1394）——既不能用 `setGeometry`（会被下次 layout 激活覆盖），也不能只插固定间隔（行内总需求一旦小于容器宽，Qt 会把富余摊给其余 `Minimum` 项、目标立刻弹回原位，实测 hl101 插 13px 间隔、目标只走了 6px 就是同一个坑）；只能「前导项收窄让位」——把「检查并清理失效的软链接」钉到 `锚点x - 前导项x - 行间距 - 中间项宽之和`，目标作为行内唯一的可拉伸项正好吃光剩余宽度，左缘即落在锚点上。**钉宽必须每遍先真解锁**（`setMinimumWidth(0)` + `setMaximumWidth(QWIDGETSIZE_MAX)`）再量，否则拿上一遍的钉宽算让位量、误差逐遍累积（同 `_actor_info_width_locks` 用 `setFixedWidth(saved)` 永不真解锁那条坑），故这里不用登记/还原列表而是「先解锁→activate→量→钉宽→activate→回读修正」。让位量低于 `_GUAXIAOMULU_MIN_LEAD_W=150` 时保持解锁、不右移：低于此值会夹住前导项自己的文字（实测其 sizeHint 宽 101），窗口窄于约 960 时该守卫生效（850×650 实测 definition 351 ≠ 锚点 298），宁可不满足也不夹字。② 「刮削时自动清理」是 `groupBox_61` 内的**绝对定位项**、不受任何布局管理，`move` 即可；但通用宽幅同步每遍会按 `_DOCK_RIGHT` 把它钉回「`设计x + extra`」（窄态 498 / 宽态 1388），所以本方法必须排在 `sync_wide_children_width()` **之后**（滚动区的 `_post_wide_sync_hook` 与 `_sync_page_layouts()` 尾部两处调用都满足，与同页文件清理提示对齐同款排布，且排在它之后——前者的宽态分支内部会重跑一次宽幅同步），否则宽态的左移会被立刻抹掉。只改 x，y 与宽高（141×41）保持不动（需求只说左右移动）。判态用几何拉伸量 `_scroll_stretch_extra() > 0` 而非 `isMaximized()`（窗口管理器最大化时先发尺寸、后发状态标志，那一拍 `isMaximized()` 还是 False，用户会看到「先在右边、再跳到左边」，同 `_sync_actor_page_align` 的理由）。**跨分支 mapTo 坑**：`record` 在 `groupBox_32`、而移动目标在 `groupBox_61`，二者是兄弟，`src.mapTo(box61, …)` 是未定义行为（实测宽态会把「刮削时自动清理」放到 1130 而非锚点 828），必须经公共祖先 `scrollAreaWidgetContents_guaxiaomulu` 中转再换算回 `groupBox_61` 的局部坐标。另加不越界守卫：目标右缘不得越过滚动内容右缘（否则内容最小宽被抬高、冒出一条水平滚动条）。幂等：每遍先解锁再按当前几何重算，双向幂等、窄↔宽往返自愈；休眠页零成本，由切 tab 的 `showEvent` 补齐。验证：新增 `tests/test_guaxiaomulu_align.py` 5 项（宽窄五档「目标精确落在锚点列 + 前导项左缘与基线一致且不低于下限」、「宽态对 record / 窄态对启用 + 只动 x」、「与摘掉新方法的基线逐项比对，只有三个目标变化、锚点与十个参照控件逐像素不变」、「幂等 + 窄↔宽往返复原」、「极窄窗口守卫生效且需求③仍生效」），摘掉 `main_window.py` 改动后 4 项即红（幂等项因无改动而恒真）、装回去全绿；`test_window_state_matrix` 等相关 24 项全过；`ruff format` / `ruff check` 通过、`mypy mdcx/` 仍是 51 errors 与改动前基线完全一致（零新增）。离屏渲染复核：窄态与宽态截图里三处竖线均已对齐，「检查并清理失效的软链接」两态都只让宽度、左缘不动

- **软件设置-命名页画质行与水印页水印设置组最大化时没有与各自锚点上下对齐**（新增 `_sync_naming_definition_align()` 与 `_sync_watermark_colon_align()`，分别挂在 `_sync_page_layouts()` 尾部 `_sync_definition_group_spacing()`、`_sync_fanyi_group_spacing()` 之后；命名/水印页没有滚动区钩子，尾部调用即是既定模式）：① 最大化时把「使用路径中包含的画质信息」向右移动到与下方「视频文件名」严格上下对齐的位置，「不获取分辨率」同步向右移动，「视频文件名」位置保持不变，最小化时逐像素不变；② 最大化时把「添加水印的图片」「水印大小」「水印类型」「水印位置」向左移动到与「首个水印位置：」严格上下对齐的位置（对齐冒号），「首个水印位置：」保持不动，右侧复选框/滑杆/提示词同步左移，最小化时逐像素不变。实测几何（abs = 相对滚动内容左缘）：命名页 video 200 / path 403 / none 605 / filename_4k 450 在窄 1030×753 与宽 1920×1170 下完全一致（通用宽幅同步不碰 layoutWidget_26，frame_6 只被拉宽、内部 471 宽的行原地不动），故 need 恒 47（仍运行时 mapTo 实测、不写死）；水印页窄态四标签右缘全 180 == 锚点右缘 180（天然对齐），宽态四标签右缘全 452 vs 锚点 180（col0 被 QGridLayout 摊了 +272 富余）。**手法**：① horizontalLayout_112 三项 Minimum/Minimum/Fixed、总需求恰好等于容器宽，与刮削目录 horizontalLayout_115 同构——「容器加宽 need + 目标前插 need - spacing 宽的固定间隔」（多出的一项引入一个新间距），行内总需求恒等于容器宽。**三个单选必须全钉死在当前宽再插间隔**：插入间隔会触发 QHBoxLayout 重新分配富余，Minimum 项宽度会被重算（各环境字体不同、结果不可预测，pytest 环境一遍能把 path 从 197 压到 184）；且第三个单选 none 的宽度也要实测加总（pytest 环境 hint 99、开发机 66，靠估算一定对不上），容器宽按「三项实宽 + 间隔 + 3×spacing」逐项加总而非 holder + need。插完回读、spacer 与 holder 联动增减三轮收敛。**holder 是绝对定位容器**：只恢复 min/max 收不回宽度（widget 保持当前宽），还原必须先真解锁再按记录原宽写回，否则加宽量逐遍累积（实测 holder 471→559 越垒越高，窄态也要不回来）。② gridLayout_24 的 col0 钉死 130 + stretch 全给 col1（演员页 gridLayout_14 的 col0 同款根因），但光钉拉不动——col1 行内多为 Maximum 策略（capped 在 sizeHint）或 Fixed 宽（滑杆 400~500、LCD 70），无处吸收富余时多出的宽度会溢回 col0；必须在 col1 四行（horizontalLayout_7/15/14/5）尾部补 Expanding 间隔让 col1 无界吸收，行内原有项宽度纹丝不动（基线里富余由 Minimum 项自己吃掉、checkbox 会被拉宽，加上尾部间隔后它们回到 hint 宽，这是修复的应有之义）。两方法都只在拉伸量 > 0 时动手，窄态第一步清干净即 return。验证：新增 tests/test_naming_watermark_align.py 6 项（宽态 1920/1600/1366/1100 对齐 + 前导/锚点不动 + 同步移动 + 窄态与基线逐项一致 + 幂等往返），摘掉实现 5 项即红；窄态 1000/1030 与基线逐像素一致；测试里参照断言带 ±1px 的 x 容差（不同字体/DPI 下布局引擎 qreal 舍入的 phantom，子像素级不可见，真回归都是 10px 以上；宽度仍精确比对）。

## v2.1.6 (2026-09-30)

- **软件工具页演员库分组布局重排与紧凑化**：新增 `MyMAinWindow._sync_actor_db_tool_layout` 接管组内 27 个控件——常态按 `_ACTOR_DB_TOOL_DESIGN` 紧凑几何摆放（中文名缺项/打开库说明合并为一条紧贴 LibreDMM 按钮右侧、minnano 说明紧贴补全按钮右侧、nfo 输入框缩为拉伸后一半且两按钮紧随其右、别名下拉右缘与 nfo 输入框对齐、全量更新复选框移到下拉外侧、起始行提示紧贴 5000 调整框、停止按钮移到 LibreDMM 列下方、提示条移到顶部说明下方单行、链接缺项说明删除、打开行 140→112、剔除行及以下整体上移删空行），最大化在此基础上拉宽宽幅行；`CustomScrollArea._MANUAL_WIDGET_NAMES` 登记这些控件，不再参与通用拉伸/右缘锚定。`CustomScrollArea` 新增 `set_content_right_trim`，工具页 `scrollArea_10` 内收 4px——离线实测 800~2200 八档窗宽下工具页卡片右缘比设置页同类卡片恒宽 4px（与 DPI 无关），左缘 x30 不动、设置页零改动，最大化定制布局读实时盒宽自动相干
- **长提示词尾字被裁根治（`默认/钮/日`消失）**：根因是 `QLabel.heightForWidth(221)` 实测返回 26（单行高度，拿到的是陈旧 sizeHint），而同字体同宽度下 `QTextDocument` 量出合并提示词 50、minnano 说明 36——之前按前者算高恒等于固定值，字一多就从尾部裁掉。新增 `wrapped_label_height`（与 QLabel 同一排版引擎实测 + 6px 余量，底边封顶不侵入下一行：合并提示词封顶 136、minnano 封顶 196），两条提示词改左上对齐（默认垂直居中会把字往下顶，顶边贴住按钮顶边）；`QLabel.heightForWidth` 全仓库不再用于该场景。新增 `tests/test_actor_db_hint_height.py`（高度必覆盖三条真实文案、底边不侵入下一行、20px 大字号也被封顶）与 `tests/test_tool_page_right_align.py`（1170/1600 两档断言工具/设置卡片右缘相等、左缘为 30），同类问题由单测先拦
- **按钮与提示文案批量调整**：校验 tmdbid 有效性→校验TMDB ID有效性、补全 LibreDMM 链接→补全LibreDMM链接、minnano 补全→Minnano-av补全、JavDB 中文名→JavDB中文名、更新 nfo tmdbid→更新nfo文件TMDB ID字段（140→170 向右拓展）、选择 nfo 目录→选择nfo目录（含文件选择框标题）；`.ui` 与 `MDCx.py` 同改，使用说明页相关描述同步；任务完成后按钮文案由 `_ACTOR_DB_IDLE_TEXT_MAP` 恢复，四个改名按钮的映射同步更新，否则跑一次任务文案就被改回旧名（校验按钮此前已踩过这个坑）。演员库分组 10 个灰色说明改设置页同款绿 `rgb(8,128,128)`（橙色提示条按既有要求保持不变）；工具页 `label_41`（刮削排除目录）右缘被输入框盖住 10px 导致冒号不显示，左移加宽到 `(50,30,90,30)`（右缘与输入框贴齐，离线实测 84px 文本装入 90px）。其余多为提示词措辞微调（中文名→中文姓名、TMDB ID 大小写、标点），高度自适应兜底，不断尾
- **版本号五处对齐到 2.1.6**：`LOCAL_VERSION` 20260928 → 20260930，`VERSION_NAME` v2.1.5 → v2.1.6，与 `pyproject.toml` / `uv.lock` 根包 / changelog 首段五处一致（`scripts/bump.py --version 20260930 --name 2.1.6`），`test_version_consistency` 全过

### 修复

- **高分屏缩放补 300% 档，放不下当前屏幕的档位自动隐藏**：下拉原最高只到 200%，屏幕特别大的用户嫌小；现补 `300%`，共 9 档（跟随系统 / 80% / 90% / 100% / 125% / 150% / 175% / 200% / 300%）。同时按反馈根治「选了大缩放率 → 界面撑出屏幕 → 左下角状态行压住导航按钮」这类误操作：每次显示窗口时（换屏、改 DPI 同样会重算）把当前屏幕**放不下的档位从下拉里隐藏**，用户根本选不到。判据是该档位下窗口最小尺寸 850×650 是否还装得进屏幕可用区，两侧都换算成物理像素比较（`可用区 × devicePixelRatio` vs `档位 × 850/650`），因此与当前已生效的缩放率无关；「跟随系统」永不隐藏。1920×1080 隐藏 175%/200%/300%（最高只能选 150%）、2560×1440 系统 150% 时隐藏 300%（200% 仍可选）、4K 全档保留。**只隐藏不删除**：换大屏或拔掉外接屏后重新显示窗口，档位自动回来；下拉 tooltip 与设置页说明同步写明「放不下当前屏幕的档位会自动隐藏」。`load_config` / `save_config` 原先两段手写阈值链改为共用 `ui_scale_index` / `ui_scale_value`（旧阈值 0.85→80%、1.9→175%、2.5→200% 的就近取档行为逐位保留，配置文件里存的仍是数值、不受隐藏影响）。验证：新增 `tests/test_ui_scale_options.py` 10 项（下拉 9 档与 `.ui` 逐字对齐、取档往返、1080p/1440p/4K/离屏四组隐藏结果、隐藏行上的当前选中项不受影响、换大屏后档位恢复）

- **启动时窗口正好落在屏幕正中（默认初始宽高不变）**：此前 `showEvent` 里只调 `resize()`、定位一概不管，窗口落在系统给的默认位置而非屏幕正中；现按屏幕可用区算完尺寸后额外居中一次——用 `frameGeometry()` 对 `screen.availableGeometry()` 求偏移（Qt 6 下 `move()` 收的是外框左上角，故不做边框补偿；`windowHandle()` 尚未就绪时用 `QTimer.singleShot(0)` 延后一次），任意分辨率、任意缩放率下启动都居中。**默认初始宽高按反馈保持原样**（`min(1030, 可用宽*0.9) × min(700, 可用高*0.85)`，最小 850×650），80% 缩放率下与改动前逐像素一致；先前尝试过的「等比缩放保持宽高比」已撤回（缩放率调大后界面撑爆屏幕的问题改由上一条的下拉自动隐藏超屏档位来根治）。验证：`tests/test_window_state_matrix.py` 49 项全过（12 档分辨率的「不超可用区 / 不小于最小尺寸」矩阵断言、「手动拖动后再次 resize 重新居中」、「居中误差 ≤1px」）

- **界面缩放调大后左下角状态行压住「检测网络 / 使用说明」按钮（175%）**：1920×1080 系统缩放 175%（窗口 741×504）时，左下角「正常模式 / 字段优先 / actor.json / 版本号 / 点击检查最新版本」整块盖在最后两个导航按钮上。根因是状态区在 `resizeEvent` 里按 `min(max(高度-201-40, 489), 高度-201)` 定位：窗口一矮就把 201px 高的状态块硬拽上去，而 390px 高的导航容器纹丝不动（设计稿整列需 50+390+49+201+40=730px）。现新增 `_sync_dock_layout()` 统一排布导航坞与贴底状态区：高度充裕时（≥700）逐像素沿用设计稿几何（状态块 y=489、按钮高 40、间距 8，存量行为零改动）；不够时先压导航间距（8→2）再压按钮高（40→36）腾地方，状态块紧贴导航下方并按剩余高度收缩（不足 72px 才隐藏），导航按钮始终完整可见。175% 实测导航占 50..419、状态块 y=431 高 73，互不重叠；窗口拉回 1920×1170 完整还原设计稿几何；压到 450×306 时状态区让位、8 个按钮仍全部可见。验证：`tests/test_window_state_matrix.py` 新增短窗口 / 大缩放 / 隐藏可选导航按钮三组断言，原「左下角徽标在矮窗口内完整可见」用例补上不压导航的条件

- **命名页说明文案收紧与行间距对齐**：主题视频（`label_87`）、剧照副本（`label_59`）、附加内容（`label_333`）三处绿色说明去掉了中英文之间的空格与设计期硬换行，合并为单行（`backdrops` / `behind the scenes` / `Emby` 前后的空格及行间 `<br>` 删除，句尾多余句号一并去掉）；`label_59` 首句措辞改为「在Emby中，剧照图片将作为背景显示」；`label_68`（Emby视频标题说明）去掉 `(title)格式` 后的逗号。间距：`Emby视频标题` 与 `防屏蔽字符` 行之间比 `视频文件名` 与 `Emby视频标题` 之间宽，根因是 `label_68` 设了最小高度 40 而同类说明 `label_61` 没有——删掉该约束，两行说明都贴合文本高度，间距一致。`MDCx.ui` 与 `MDCx.py` 同改
- **软件工具页最大化时校验行两说明单行显示**：最大化后「失效ID清除后自动按名字重搜补新ID，搜索不到则保持无ID刮削兜底」「检查格式错误和数据异常，安全项自动修复，TMDB给出人工修复步骤」两条说明去硬换行单行显示；右列四个按钮（补全LibreDMM链接、停止当前维护任务、Minnano-av补全、检查用户库）及右侧两条提示（顶部合并提示、minnano 说明）同步右移——右列左缘 = 左说明右缘 + 20px，按钮宽 200 不变只平移，提示紧贴按钮右侧、右缘收到组框内缘。单行宽按实际字体 `horizontalAdvance` 实测（离屏 12px 下 verify 404px、check 392px，右列 x=464）；组框过窄（<874px，如窄屏最大化）时回落双列双行不溢出；还原/最小化时按钮几何、双行原文、`wordWrap` 全部复位，最小化布局逐像素不变。只改 `main_window.py` 的 `_sync_actor_db_tool_layout`，`.ui` / `.py` 静态布局不动。校验：`py_compile` 通过、`tests/test_actor_db_hint_height.py` 4 项全过、离屏 1000~1920 四档盒宽单行不断尾不重叠、说明底边 246 不侵入 nfo 行 252

## v2.1.5 (2026-09-28)

- **`actions/cache` 由 `@v4` 全量升到 `@v6`，消掉每次构建的 Node.js 20 弃用警告**：`build-py313` / `build-py314` 四个构建腿每次都刷 `Node.js 20 is deprecated. The following actions target Node.js 20 but are being forced to run on Node.js 24: actions/cache@v4`（2025-09-19 起 GitHub 弃用 Node 20 runtime，runner 强制改跑 Node 24）。核实过再改：查 `actions/cache` release——`v5.0.0` 就是「Upgrade to use node24」，`v6.0.0` 只多一层 ESM 迁移（`migrate to ESM`），两版 release note 均未改输入契约；拉 `action.yml@v6` 确认 `runs.using: node24` 且 `path` / `key` / `restore-keys` / `fail-on-cache-miss` 全部保留，本仓库六处缓存（`update-sr-tools.yml`、`ci.yaml`、`build-windows.yml`、`build-linux.yml`、`build-py313.yml`、`build-py314.yml`）只用到 `path` + `key`，逐字兼容。`package-trawl.yml` 本来就是 `@v6`，现全仓库七个缓存点统一。**唯一硬约束**：v5 起要求 Actions Runner ≥ `2.327.1`（仅自建 runner 需升级），本仓库全为 GitHub 托管 runner（`macos-latest` / `macos-15-intel` / `windows-2025` / `ubuntu-latest`），无影响。顺带确认其余 action pin 均已是现代版（`checkout@v7`、`setup-python@v7`、`upload-artifact@v7`、`download-artifact@v8`、`github-script@v9`、`stale@v11`），无第二个 Node 20 源

- **发版工作流收敛为唯一构建发布流水线 `build-py314.yml`（删除 `build-py313.yml` / `build-windows.yml` / `build-linux.yml`）**：原有三个 3.13 构建工作流 + 一个 3.14 试验工作流（重复跑同一版本、互相覆盖、同一 tag 重复创建 Release 偶发 422、每个平台两次构建、平移字段无意义、artifact 撞名、平台数不一致、维护两条分支）→ 合并为唯一一条流水线（**同一 `release.yml` 与 `build-py313.yml`，`git show --stat` 为证**：合并为删动作，5 个平台 7 个 job）：`build-py313.yml` 改名为 `build-py314.yml`、前者收敛为**唯一**的 `push: tags: ['2*']` 触发器（此前只有 `workflow_dispatch`，因为 tag 必须先构建 3.13 流水线）、`Resolve release metadata` 原硬编码工作流名改为读取 `github.ref_name`（兼容支持 tag 取值逻辑，同时保留 `workflow_dispatch` 的字段 `tag` 不读取 `LOCAL_VERSION`、`prerelease` 只按 `event_name` 判断，tag 不产生预发布）；显示名统一为 `Build and Release (Python 3.14)`；并发组从 `build-py314-` 收为 `build-release-`；Python 3.14 之前创建的 tag 不会命中（tag 本就在 3.14 之后创建）；顺序保证 3 个前提（`!cancelled() && needs.build-app.result == 'success'` + 串行 + 缺产物即失败、无条件回退串行构建、取消任务绝不回退并发组），`cancel-in-progress: false`；四个 `Create Release` 步骤 `overwrite: true`（tag 已存在只 `::warning::` 放行）。另 `build-py313.yml` 的硬引用**无重复残留**。四平台 runner 更新与删除动作等历史一并写在「**老开发文档删除**」。测试侧：`build-py314.yml` 断言重写为 10 项（原先断言已删工作流「存在」的用例只改为断言已被删除，如 `test_asset_names_match_release_workflow` 无改动、`test_workflow_does_not_listen_to_tags` 转为 `test_workflow_listens_to_numeric_tag_pushes`；新增/更新断言覆盖三平台矩阵、`test_prerelease_only_applies_to_manual_dispatch`、`test_removed_workflows_are_gone` 钉死三个已删工作流、`tests/test_sr_bundling.py::test_packaging_workflows_fetch_sr_tools_before_build` 拉取清单调整为 `ci.yaml` + `build-py314.yml`、快速工作流只剩 `tests/test_workflow_action_pins.py`）。更新动作表**明确**：`Development.md` 逐条更新为「唯一开发文档 + 注释」后 CI 平台禁止再触发相关流程，且已删文档 **不再输出**到 CI 平台；同时在 PR + 主干的 `uv run quick-check` / `uv run check --skip-hook-install` 门禁下验证（10 工作流断言 + 6 个相关用例共 36 项全过、YAML 全部通过、ruff format/check 通过）。发版工作流的现状契约（触发方式、3.14 专属三处、三条护栏）见 `docs/Development.md`「构建」

- **`ci.yaml` 不再监听 `push`，只保留 `pull_request` 门禁；顺带修掉让主干 CI 必红的 ruff / mypy 积压**：日常用 GitHub Desktop 把提交直接同步到 main，`push: branches: [main]` 会让每次同步都在 Actions 列表里多出一条 `CI/CD Pipeline`（主干不走 PR 流程，纯噪声；截图里 22be40e / a4e0b29 两次同步各挂一条）。现删掉 `push` 触发块，只留 `pull_request → main`（`opened` / `synchronize` / `reopened` / `ready_for_review`），质量门禁改为「PR + 本地自检」两道：`uv run quick-check`（ruff format/check + mypy）在提交前、`uv run check --skip-hook-install`（再加 pytest + check_thread_safety）在推送前，`Development.md`「测试」段同步写明。`gh` 拉 run `36365943885` 日志定位到必红真因：`Code Quality` job 第 5 步 `ruff format --check` 就 exit 1（`Windows Compatibility and Build` 是成功的），5 个文件没格式化——`scripts/bump.py`、`tests/test_cf_transport_fallback.py`、`tests/test_py314_dependency_floors.py`、`tests/test_ui_structure.py`、`tests/test_version_consistency.py`，已 `uv run ruff format`。**潜伏更久的第 7 步 mypy 两条错这次一并修掉**（CI 一直没跑到那步所以从未暴露）：`mdcx/tools/sync_gfriends.py:30` 空 `kwargs = {}` 被推断成 `dict[str, int]`，`**kwargs` 展开后匹配不上 `subprocess.run` 的任何重载 → 显式标注 `dict[str, Any]`；`mdcx/core/network_check.py:1322` 动态挂 `_bypass_serial_lock`（自定义属性，`AsyncWebClient` 上无声明）在 `AsyncWebClient | Any` 联合上报 `union-attr` → `run_client` 显式标注 `Any`。另修 `tests/test_py314_release_workflow.py` 的 `F541`（无占位符的 f-string）；`mdcx/core/asin_cid_index.py:52` 的 `cid_to_number` 文档字符串非 raw，写着形态正则 `^(\d*)([a-z]+)(\d+)([a-z]?)$`，每次导入都吐 `SyntaxWarning: "\d" is an invalid escape sequence`（Python 未来会升为硬错误），加 `r` 前缀消掉。新增 `tests/test_ci_workflow_triggers.py` 四项守卫（无 `push` 触发块、`pull_request` 门禁与 main 目标分支仍在、`ruff format --check` / `ruff check` / `mypy mdcx/` / `pytest tests/` 四个门禁命令未丢），防止有人顺手把 `push` 触发加回来。验证：YAML 解析通过、`ruff format --check` 416 files already formatted、`ruff check` All checks passed、`mypy mdcx/` Success: no issues found in 148 source files、`check_thread_safety` 无违规、离线全量 `uv run check --skip-hook-install` 2148 项（4 skip，0 失败）；**GitHub 端已确认生效**：`gh api actions/runs?head_sha=8a787db…` 返回 `total_count=0`（同接口对 22be40e 返回 1，证明接口非恒 0），推 main 后 Actions 列表不再出现 `CI/CD Pipeline`

- **`build-py314.yml` 改为与 `build-py313.yml` 同构的 3.14 发版流程（当时的对照流程 `build-py313.yml` 已在同版本内被删除，见上方条目）**：3.14 已在四平台实测构建通过，正式发版流程随之与 3.13 主流程对齐——纯数字 tag（取 `mdcx/consts.py` 的 `LOCAL_VERSION`，不再用 `py314-<版本号>` 前缀）、资产名 `MDCx-<版本>-<平台>-<架构>-<sha>`、产物名 `mdcx-*`、标题 `VERSION_NAME (版本号)` 全部与 `build-py313.yml` 一致。与当时对照流程的四处差异：`python-version: 3.14`、工作流级 `UV_PYTHON: 3.14`、构建前 `sys.version_info[:2] == (3, 14)` 断言（防 uv 悄悄挑到别的解释器，编出来的还是 3.13）、`uv sync --locked` 失败自动回退 `uv sync` 重新解析（`uv.lock` 未必有 cp314 wheel；只改 CI 临时工作树，不动仓库 lock）。输入精简为「版本号（留空取 `LOCAL_VERSION`）」与 `prerelease` 两项，与 `build-py313.yml` 相同：**删掉** `platforms`（四平台固定全量构建）、`publish` 勾选（发不发成了每次必发）、`allow_relock` 的 true/false 开关（3.14 恒允许回退）。**代价与相应约束**：两条流程现在共用纯数字 tag 命名空间且都是 `overwrite: true`，同一版本号只存在一条 Release，因此同一版本号只能用其中一条流程发版——`build-py314.yml` 当时只监听 `workflow_dispatch`、不监听 tag（tag `2*` 推送归 `build-py313.yml`），并发时两者会同时 `POST /releases` 撞 422；`build-py314.yml` 在 tag 已存在时打 `::warning::` 提醒这是覆盖更新而非新建。保留三处比 `build-py313.yml` 更严的护栏：`concurrency` 按 ref 分组且 `cancel-in-progress: false`（半路取消会留下缺资产的 Release）、`build-app` 带 `continue-on-error` + `publish-release` 用 `if: !cancelled() && needs.build-app.result == 'success'` 把关（不能写 `success()`：`needs` 里任一失败腿都会让它整体跳过）、上传前核对四平台产物齐全，不留半成品 Release。`permissions` 为 `contents: write`（仅此一项）。3.14 全平台转正后原计划把 `build-py313.yml` 切到 3.14、删掉本文件；实际走的是反过来的路，见上方删除条目。`Development.md`「构建」段改写为两工作流分工 + 四处差异 + 三条护栏，去掉原「tag 命名空间隔离 / 不发 Latest / 只允许手动发版 / 资产隔离 / 预览占用更新检查窗口」等基于 `py314-` 前缀的约定，「版本号管理」段同步删掉非纯数字 tag 的例外说明；`tests/test_py314_release_workflow.py` 按新设计重写为 8 项守卫（纯数字 tag 且资产名无 `py314-` 段、不监听 tag、只剩 tag/prerelease 两个输入、四平台矩阵与产物名同 `build-py313.yml`、3.14 三处 pin 与 relock 回退、产物齐备才发、与 `build-py313.yml` 资产命名逐条对齐），仍为纯文本断言不引入 yaml 依赖。验证：YAML 解析通过、与 `build-py313.yml` 的 `diff` 逐条核对确认只有预期差异、四个 Create Release 步骤的输入键值与 `build-py313.yml` 逐字相同、`fetch_sr_tools` 先于 `build.py` 的顺序断言（`test_sr_bundling.py`）本地手工复算通过、本地实跑 `uv run pytest tests/test_py314_release_workflow.py` 5 项全过；GitHub 端实际发版效果需手动触发一次 `build-py314.yml` 确认

- **新增 Python 3.14 兼容性构建工作流（`build-py314.yml`；对照的 `build-py313.yml` 作为同版本存在并删除）**：`pyproject.toml` 的 `requires-python` 上限 `>=3.13.4` 放开、只锁最低版本，此前 3.14 未公开发布时只走 3.13 流水线；3.14 需另装编译依赖跑第一道 `uv sync --locked`（3.14 无可用 cp314 wheel 时会失败，失败时 `::warning::` 放行 `uv sync` 让包管理器回退，最大时间上限）；自建版本检查确保 cp314 wheel 存在时由锁文件命中，缺少对应 wheel 时仍能在稳定时间窗内失败（既不掩盖 3.14 未覆盖到的事实，也不无界等待）；矩阵按平台钉版本而非钉分支：macos-latest aarch64 / macos-15-intel x86_64 / windows-2025 / ubuntu-latest 配 `python-version: 3.14` + 触发器 `UV_PYTHON: 3.14` 双保险，跑一道 `sys.version_info[:2] == (3, 14)` 的断言失败时在打包前中止（让主分支至少构建一条 3.14 分发物、`uv sync --locked` 缺 cp314 wheel 的失败也立刻中止而不是降级回退）；超时 `build-app` 用 `continue-on-error: true`（3.14 未发布即允许单平台失败）；`fetch_sr_tools` 在 `build.py` 之前平滑接入，`tests/test_sr_bundling.py` 9 项全过。**新增说明与禁止项**已收敛进「**发版工作流收敛为一条**」与 `docs/Development.md`（构建发布节的禁止项 4 条为：只直接推 tag 到 `build-py314.yml`、部分平台构建失败即不发版、支持并发绝不互杀）

- **`pyproject.toml` 依赖逐条按 Python 3.14 核对并抬高 3 处下限/pin**（配合上一条的 3.14 流水线；修正上一条里「写死版本的包无 cp314 wheel 会硬失败」的说法：`opencv-contrib-python-headless==4.13.0.92` 是 `cp37-abi3`，在 3.14 上照常安装）。核对方法：逐包查 PyPI JSON 的 `releases[版本].urls`，看 tag 是否落在 `cp314-*` / `*-abi3-*` / `*-none-*`（这三类在 3.14 可用），并读 `requires_python` 上界。结果：**① `pyinstaller>=6.14.2,<7` → `>=6.16.0,<7`** —— 6.14.2 的元数据是 `requires-python = ">=3.8,<3.14"`，3.14 上根本装不上（6.15.0 起才放开 `<3.15`），这是唯一会让 3.14 流水线硬失败的 dev 依赖；**② `av>=15.0.0` → `>=15.1.0`** —— 15.0.0 只有 cp39~cp313，3.14 上会退回源码编译（要 FFmpeg 开发库，基本必炸），15.1.0 起才有 cp314 wheel；**③ `aiofiles==24.1.0` → `==25.1.0`** —— 24.1.0（2024-06）早于 3.14，上游 25.1.0（2025-10-09）changelog 明写「add Python v3.14 support」；仓库只用到 `aiofiles.open` 与 `aiofiles.os.*`（exists/remove/listdir/makedirs/islink/getsize/stat），这些 API 在 25.x 未变。**最大的一处虚惊是 `oshash` 与 `zhconv`**：两者 PyPI 上只有 sdist（无任何 wheel），一度判为「C 扩展需在 3.14 源码编译」的高风险项；实际拉上游仓库确认 `oshash/api.py` 只 import `os`/`struct`、`zhconv/zhconv.py` 是纯 Python + MediaWiki JSON 词表，master 的 `setup.py` 连 `ext_modules` 都没有，sdist 大小（3.4KB / 212KB）也对得上——**不需要编译，3.14 无风险**。逐一确认无需改动者：`pyqt6==6.11.0`（cp310-abi3）、`opencv-contrib-python-headless==4.13.0.92`（cp37-abi3，2026-02 发布，晚于 3.14.0）、`curl-cffi`（cp310-abi3）、`aiohttp`/`lxml`/`numpy`/`pillow`/`pydantic-core`/`mypy` 均有 cp314、`pyinstaller`/`ruff` 是 `py3-none`、其余（`httpx`/`parsel`/`jinja2`/`openpyxl`/`defusedxml`/`uvicorn`/`openai`/`beautifulsoup4`/`rich`/`typer`/`pytest*`/`pre-commit`/`ipykernel`/`pyright`/`tornado`/`setuptools`）纯 Python 或有兜底 wheel。**刻意不动**：`openai==1.91.0`（最新 3.19.2 是跨大版本破坏性升级，`mdcx/llm.py` 在用，纯 Python 无 3.14 阻塞）、`beautifulsoup4==4.13.4`（纯 Python）、`ruff` 的 `<0.16.0` 上限（wheel 是 `py3-none-<平台>`，装在 3.14 上无碍；且仓库无 `[tool.ruff]` 段，target-version 由 `requires-python` 推导为 py313）。`requires-python` 保持 `>=3.13.4` 不变（3.14 是追加支持，3.13 仍为基线），`[tool.pyright]`/`[tool.mypy]` 的 3.13 也不同步。`uv.lock` 同步手改：根包 `aiofiles` 条目 24.1.0 → 25.1.0（URL/sha256/size 取自 PyPI simple index，`upload-time` 按 uv 惯例截到毫秒）+ `[package.metadata]` 三处 specifier；`av`/`pyinstaller` 已锁版本（16.0.1 / 6.16.0）本就满足新下限，故不重新解析。新增 `tests/test_py314_dependency_floors.py` 守住这三条下限（4 项：三条 specifier 逐字比对、`uv.lock` 的 `[package.metadata]` 与 `pyproject.toml` 同步、lock 里 `av`/`pyinstaller` 实际 pin 版本够新、`requires-python` 不带 upper bound），改依赖想回退即本地判红。验证（本机 Python 3.14.7 + uv 0.12.19）：`uv lock` 后 `git diff --stat uv.lock` 无任何输出，手改的 lock 与 uv 重新生成的结果逐字节一致；`uv run pytest` 在 3.14.7 上实跑，125 个依赖解析通过、78 个 wheel 装入 `.venv`（含 pyinstaller 6.16.0 / av 16.0.1 / aiofiles 25.1.0），新测试 4 项 + `test_version_consistency` 3 项共 7 项全过 —— 「整份依赖在 3.14 装得上」已由实跑确认，不再只是发布元数据推论

- **文档写明「网络重试次数默认就是 3 次」**：核实重试默认值四处均为 3、无 5 的来源 —— `mdcx/config/v1.py`（`retry: int = 3`）、`mdcx/config/models.py`（`Field(default=3)`）、设置页 `horizontalSlider_retry`（1~3、默认 3）、`load_config` 加载钳位 `min(max(retry,1),3)`；`handlers.py` 的「检测网络」表头直接读 `manager.config.retry`，无任何硬编码。故此前看到的「重试：5」是本条修复（v2.1.5 滑条放开 1~3 + 加载钳位）之前旧版本的行为，重启即恢复 3。`Configuration.md` 重试次数行改为显式「默认就是 3 次（出厂默认，不会变成 5）」，并顺带修正过期的「拉动条上限 3（2 / 3 二档可选）」为「范围 1~3（1 / 2 / 3 三档可选）」、补默认值定义位置与钳位说明。无代码改动

- **CI 全平台构建失败修复：`uv.lock` 根包版本漏同步**：`pyproject.toml` 升到 2.1.4 后 `uv.lock` 根包仍锁 2.1.3，`build-py313.yml` 四个构建腿（windows-2025 / macos-latest / macos-15-intel / ubuntu-latest）齐在 `Install locked dependencies`（`uv sync --locked`）步 exit 1。现 `uv lock` 重生成（diff 仅根包一行），`uv lock --check` 通过。根治：`scripts/bump.py` 的 `--name` 升版同步追加 `uv.lock` 根包版本（`sync_uv_lock_version`），`--check` 升级为五处校验；`tests/test_version_consistency.py` 新增 `test_uv_lock_root_version_matches_display_name`（过期 lock 本地 0.4s 即红，无需等 CI）；`Development.md`「版本号管理」同步点四→五并记录本次事故。回归：版本一致性 3 项 + `test_version_metadata` 1 项 + `bump --check` 全过

- **重试次数滑动条放开到 1~3、保存配置即重建网络客户端**：`horizontalSlider_retry` 最小值 2 → 1（最大值确认本来就是 3，默认值 3 不变，`MDCx.ui` 与 `MDCx.py` 同改）；`load_config` 加载时把重试值钳位到 [1,3]，旧配置越界值进不了界面与检测显示。另修复保存不断连但不生效的问题：此前 `save_config` 只改 `manager.config` 内存值 + 落盘，而 `AsyncWebClient` 的重试/超时/代理在构造时固化，检测网络实际仍用旧值（表头数字与实际行为脱节，需重启才生效）。现保存按钮处理在 `save/load_config` 后调 `manager._replace_config(manager.config)` 原子切换新客户端，旧客户端由持有方租约保护、空闲后关闭（检测进行中点保存不断连）；改完重试条点保存，下次检测即用新次数。超时滑动条无需改动：诊断项每次请求显式传 `timeout=_diagnostic_timeout()`（实时读配置，已实测 30/10/5 逐一对应），`test_ui_structure`（含 `.ui`→`.py` 同步）15 项 + `test_network_check` 等 94 项全过

- **版本号五处对齐到 2.1.5**：`pyproject.toml` 由 2.1.4 升到 2.1.5，与 `VERSION_NAME` / `LOCAL_VERSION` / `uv.lock` 根包 / changelog 首段对齐；`uv.lock` 有过一次漏同步（`sync_uv_lock_version` 之前漏了根包元数据），此时被压测用例提前拦下，详见 `docs/Development.md`「版本号管理」的五个同步点表与改版流程

## v2.1.4 (2026-09-27)

- **Amazon 封面下载改请求 SL2560 原图变体（对齐 mdcx-diy-main 实际下载尺寸）**：此前缓存命中走 tenhow 图床直连（约 1055×1500），且 `_convert_to_target_size` 默认转 SL1500、输出非标准的点号式后缀（`.SL1500.`），同是 SNOS-447（ASIN `B0HDYHZ7MX`）只能下到 1055×1500/147KB，而 diy 下到 1778×2529/340KB。现删除 tenhow 探测分支（`TENHOW_IMAGE_URL_TEMPLATE` / `_probe_tenhow_image`），缓存命中直接返回库内 `poster_url`；默认目标尺寸改 `SL1500` → `SL2560`，输出修正为 Amazon 官方下划线式 `._SL2560_.jpg`（已实测同图 `._SL2560_.jpg` 返回 1778×2529/349028B，与 diy 截图逐字节量级一致）。`_normalize_amazon_image_url` 重写：兼容剥离 `._AC_UL320_.` / `._SL1500_.` / 点号式 `.SL1500.` / 无后缀原图四种形态后统一重加，库内历史旧后缀行下次缓存命中自动升级、无需重新搜索；非 Amazon 链接原样返回，显式 `target_size` 参数保留。`tests/test_amazon_trusted_read.py` 注释同步（库命中 reason 只剩 `cache`）。回归：`test_amazon_trusted_read` + `test_amazon_database` 18 项全过；下载规范见 `Development.md`「Amazon 集成」

- **刮削后左下角模式行只剩 `💠 ·` 光杆图标（读取/正常/整理/更新模式全中）**：`Flags.reset()` 原实现整行清空再展示，把 `main_mode_text` / `scrape_like_text` 两个展示量也一并抹掉，于是 `reset()` 之后 `show_scrape_info` 的读取/正常/整理/更新四种模式只剩图标、文本两行直接消失；`load/save_config` 侧标志没问题但展示层也没恢复，模拟「设置-刮削模式改动」「保存-重启软件生效」时状态看着是「`💠 ·` + 空白」，简介/标签两行位置不明（changelog #86）。`Development.md` 已列为永久规则：底部状态栏必须**每行一个图标 + 对应文字**、图标与文字**同时存在**，不用 `reset()` 的那条『文本置空』路径掉进空壳。现加 `reset_flags_preserving_single_file_inputs()`：`reset()` 前备份 `main_mode_text` / `scrape_like_text` 两个展示量、各自置空、调用 `reset()`、再恢复两个展示量发 `show_scrape_info`，并把 `load/save_config` 与标志位同步无关的四条分支补齐（测试断言关模式与 save/restore 路径的全字段值相等）。图标字面量与源码锚点见 `docs/Development.md`「左下角状态区图标规范」

- **#183 左下角状态区图标对齐 mdcx-diy-main + 版本检查跳转改自有仓库**：`mdcx/controllers/main_window/main_window.py` 的 `show_scrape_info` 由 `mdcx-diy-main` 同位置的四个图标（`💡 日志信息` / `💠 站点信息` / `🍯 获取模式 + 字段信息` / `🍯 输出/输入详细信息` / `🐰 MDCx 版本`）改为 `new_version` 消息的 `🍉 有新版本了！` + 无新版本时 `🔍 点击检查最新版本`；`before_info` 用 `SCRAPE_INFO_EMOJI_RE` 过滤，否则 `🍉/💡/💠/🐰/🔍` 七个图标都会显示成删不掉的字符。顺带把 `mdcx/consts.py` 的 `GITHUB_REPO` 由 `cdlongbow/mdcx-diy` 改为 `z291173301/MDCx`，并在「设置/关于」补仓库地址（可点击）；`label_version_clicked` 的日志、状态信息、点击后打开 `check_version` 用的 API、Issues 链接均同步指向本仓库；使用说明主页下方新增「获取新版本」引导页 / Release 页说明文字，首页与仓库地址同步改为本仓库。`.ui` 改完按规矩重生成 `MDCx.py`，并同步更新 `tests/test_left_status_icons.py`（4 项：9 个状态图标的字面量与位置、`SCRAPE_INFO_EMOJI_RE` 恰好滤掉这七个、`GITHUB_REPO`/首页/仓库地址指向本仓库）。图标规范与四条硬规则见 `docs/Development.md`「左下角状态区图标规范」

- **「使用代理」开关不再联动 CF Bypass 代理**：`checkBox_use_proxy` 此前会连带关闭 Bypass 专用代理，现仅控制常规网络请求代理；CF Bypass 代理改由 `cf_bypass_proxy` 独立生效（`_resolve_cf_bypass_proxy` 去掉 `use_proxy` 门控，未配置时仍为空），mirror 的 `x-proxy` 头 / bypass html 的 `proxy` 参数、检测页 bypass 项均不再受该开关影响。设置页文案随之一并统一：网络页「CF Bypass代理」标签改「Bypass代理」、「外部 CF 服务」改「外部CF服务」，使用代理勾选框补 tooltip「仅控制常规网络请求代理开关，不控制CF Bypass代理」及说明段，帮助文档「CF Bypass 代理」条目同步改「Bypass代理」。`tests/test_ui_structure.py` 补文案回归（tooltip / 两个标签 / 说明段 / 帮助文本，`.ui` 与 `.py` 由既有同步测试把关）

### 修复

- **诊断表格与表头按显示宽度对齐（历次 10 轮微调合并为一条）**：①**按显示宽度补齐**（根因：中文站名 `madouqu·镜像` 与 emoji 状态图标在等宽字体下占 2 列，旧模板按字符数补空格导致状态码/耗时/信息三列错位）——改用 `unicodedata.east_asian_width` 计宽、结合符零宽；站点列 20 列、状态码列右对齐 6 列、耗时列右对齐 10 列、列间距 2 → 3 空格；`official·caribbean` 不再被截成 `official·caribbea`。②**表头逐段收敛**（数据行列为不动基准：数据名字 @9、数字右缘独占 40、耗时右缘独占 53；状态码与耗时前后紧邻，动其一必顶其二，故只在状态码/路由/信息三段左右微调）——历次轨迹：状态码表头 37→36（前后间隔由 6+6 重分为 5+7）→ 36→37（回到 6+6）→ 38→36（7+5 重分为 5+7）→ 36→38（1+6 重分为 0+5）→ 35→36；路由 63→62 → 61→63 → 59→61（数据同步 +2，elapsed 后 6→8 空格）→ 57→59（数据同步 +2）→ 定在 57 并去前导空格与「代理/直连」左对齐；信息 72→71 → 70→72 → 68→70（数据同步 +2）→ 66→68（数据同步 +2）→ 定在 66；耗时表头由居中改右对齐（右缘独占 53，与 `309 ms` 等数据右缘对齐）。末轮断言：表头 @2/@10/@36/@49/@57/@66，数据名字 @9、数字右缘独占 40、耗时右缘独占 53、路由 @57、信息 @66，`330162 ms` 等长耗时不断列。③**站点列加宽到 22 列**：20 → 22（`official·caribbeancom` / `official·pacopacomama` 为 21 列，此前各被截一字），表头与数据行同步加宽，耗时及后序列整体右移两格。④**列间距**：耗时→路由、路由→信息两处间隔 3 → 4 空格（状态码/耗时紧邻不动）。⑤**分隔线与横幅**：报告内 `基础环境` 下的 84 虚线改 88 等号；检测前 UI 日志横幅（日期居中 80 列、首尾 80 等号）同步改 88 列，与报告内横幅同长。⑥**基础环境标签**：7 个标签原按字符数补宽（`CF Bypass` 等中英混排比纯中文标签窄），改按显示宽度补宽、值统一同起于显示列 18；该轮信息列起点读数为 63，加宽轮为 65，表头主线末轮为 66——三者为不同轮次读数，以最后一次断言为准。每轮均由程序按显示宽度断言把关（各表头与数据列对齐、数字区独占、耗时右缘独占、长耗时不断列）

- **CF 挑战页识别补"Verify you are human"复选框文案（freejavbt 覆盖）**：freejavbt.com 现挂 CF 复选框挑战（"Verify you are human / 正在验证您是否是真人"），旧识别表只有 just a moment/cf-chl 等英文老文案——若挑战页不带这些串，挑战判定漏检、bypass 永不触发。现两处识别表（`web_async._is_cf_challenge_response`、检测页 `_is_cloudflare_challenge`，后者强标记本就有 `challenges.cloudflare.com`）补 `verify you are human` / `正在验证`（另给前者补 `challenges.cloudflare.com`）：误伤面不变（请求侧仍要求 403/429/503 + CF 头，检测侧仍要求 cloudflare 字样）。另说明：freejavbt 无需"加入"bypass 名单——代码里没有按站点的 bypass 名单，bypass 全局自动（freejavbt 爬虫走默认 `enable_cf_bypass=True`、检测通用项同样开启）；freejavbt22.cc 的 522 系源站超时（CF 边缘都连不上源站，bypass 救不了），由镜像轮询切到 freejavbt.com 处理（仅真 404 停轮，522 照转）。回归：请求侧 2 项（复选框页命中 / 纯 nginx 403 不误判）+ 检测侧 1 项

- **missav 默认地址由 missav.ai 改为 missav.ws，镜像抽样改为 missav.live**：missav.ai 已不可访问（浏览器打开空白 / 被 SmartScreen 拦截），missav.ws 与 missav.live 实测正常。`_MISSAV_DOMAINS` 顺序调整为 ws → live → ai：默认地址、镜像轮换起点、网络检测主项跟随 ws，检测镜像抽样项跟随 live（此前抽到已死的 ai 而误报），ai 沉底仅作最后备用。`Features.md` 站点表同步；**详情页 URL 改用站点规范式（`/cn/SSNI-647`、`/dm79/cn/SSNI-647`）**：`_ensure_cn_detail_url` 原把语言码拼在末尾（`/{番号}/cn`，能打开但非规范），现插到 slug 之前，末尾式/规范式输入均归一且幂等（主站与镜像项同走该函数，一并生效）。`tests/crawlers/test_missav.py` 补 6 组用例

- **检测整轮持有 computed 租约（"网络客户端已关闭"修复）**：检测此前裸用共享网络客户端（无租约），检测期间点"保存"替换配置时旧客户端在连接池空闲瞬间即被关闭，排队/重试中的项全报"网络客户端已关闭"（串行 bypass 排队者零占用、死得最先；13 分钟长轮尾部 avsex/javlibrary/xcity/missav 实证）。现整轮 `acquire_computed()` 持有租约、结束归还（取消路径同样释放），旧客户端等本轮结束再关。`tests/test_network_check.py` 补租约回归（取/用/还顺序 + 用租约客户端 + 串行锁已摘）

- **镜像轮询 404 误判修复（番号含 404 时跳过存活镜像）**：`_get_text_with_rotate` 与演员库 javbus 轮询用裸 `"404" in error` 判断页面不存在，但 `request` 的最终 error 永远内嵌请求 URL（`"{method} {url} 失败: ..."`）——番号/ID 含 404（如 FC2-PPV-404xxxx）在首个镜像遇传输失败（RST/超时）时会被误判为真 404，直接放弃其余存活镜像。现改为精确匹配 `HTTP 404` 状态前缀（真 404 必带该前缀，传输错误不可能带），行为其余不变。`tests/crawlers/test_compat.py` 补 2 项回归（URL 含 404 仍轮询 / 真 HTTP 404 首个镜像即停）

- **站点名单存盘归一化（使用代理网站 / 直连白名单）**：此前两名单无归一化，填了带 `http(s)://` 前缀或路径的条目会静默失效（路由只认裸 host）。现存盘与加载统一归一化：去 scheme、去路径/查询/尾斜杠只留 host（可带端口），中文逗号（，/、）转英文逗号，去空去重保序；站点值（如 `javdb`）与 `*` 原样保留。设置页保存后输入框即回显归一化结果。`tests/test_site_list_normalize.py` 4 项回归

- **检测页 bypass 串行化（TRAWL 浏览器池已饱和）**：检测组内并发跑项，直连失败站同时触发 bypass 兜底占浏览器，池满后集体 502。现单 run 在 run 客户端上挂一把 `_bypass_serial_lock`，所有 bypass（显式兜底 + 探测内部挑战/传输兜底）必经 `_try_bypass_cloudflare` 包装器串行，同一时刻只占一个浏览器；run 结束摘锁，正常刮削不设锁、走快路径零变化。代价：直连失败站的检测耗时由并发改为串行累加。`tests/test_bypass_serial.py` 3 项回归（并发互斥 max_active=1 / 快路径透传 / run 挂载+摘除）

- **Trawl 后端四处修复（对照 TRAWL 官方原生 `/scrape` schema）**：① `_call_trawl` 以前每次都带 `method`/`body` 字段，但原生 `ScrapeRequest` 里根本没有这两个字段（只有 url/maxTimeout/skipHttp/maxTier/sessionId/headers/proxy 等）——服务端默认剥离未知字段，导致 POST 这类非 GET 请求被**静默降级成 GET**，返回错误内容却报成功。现非 GET/HEAD 直接返回明确错误（POST 请用 flaresolverr 后端走 `/v1 request.post`），payload 不再带 schema 外字段；② 适配层 ASGI 分发是 `try...finally` 缺 `except`，handler 内任何异常（TRAWL 返回非 dict JSON、异常 statusCode、非 latin-1 响应头）都会直接抛给 uvicorn，调用方看到连接重置而不是结构化错误，现包一层 `except` 返回 502 JSON；③ 检测页「外部 CF 服务」项：TRAWL 预热期 `GET /health` 返回 503 是正常现象（浏览器池初始化中），以前按「站点服务异常 HTTP 503」报 FAILED 红灯误导改配置，现报 WARNING「正在启动，稍候重测」；④ `_call_trawl` 非 200 错误里带上 TRAWL 服务端回的 `error`/`message` 文本，方便定位（如代理格式不对）。`tests/test_trawl_adapter.py` 补 2 项（POST 明确拒绝且不发往 TRAWL / 非 dict 响应转结构化 502，既有 `method == GET` 断言改为 `method 不在 payload`），`tests/test_network_check.py` 补 1 项（外部 CF 服务 503 → WARNING）。另确认无 bug：`GET /health` 是 TRAWL 真实端点（`GET /` 是 FlareSolverr 风格就绪信息，检测页按后端二选一正确）；原生 `proxy` 就是 string 形式，现状直传正确（与 flaresolverr 要对象不同）；原生响应本就没有 `responseHeaders`/`body` 字段，`headers={}` + `html` 回退路径正确；`_call_bypass_mirror` 回环请求硬 `proxy=None`，检测页传 `use_proxy=True` 也不会把 127.0.0.1 送进代理

## v2.1.3 (2026-09-24)

### 修复

- **Bypass `/html` 路未解开的挑战页不再冒充成功（修 javlibrary"配了外部 CF 却没救回来"）**：`_call_bypass_mirror` 早有"返回仍是挑战页则判失败"的检查，`_call_bypass_html` 却缺了——FlareSolverr 没解开挑战时，200 + 挑战页 HTML 被当成功返回，上游直接拿去分类，报出自相矛盾的"请去配置外部 CF 服务"（明明已配置且已运行）。现两路对齐：未解开的挑战页一律判失败、走重试/回退；检测侧 bypass 跑过但仍是挑战页时，报错改为"已尝试 CF Bypass，但返回仍是 Cloudflare 挑战页（FlareSolverr 未能解开该站验证）"，不再甩锅给配置。新增 3 项回归（html 拒收挑战页 / 整轮不冒充成功 / 检测点名准确），相关套件全过

- **aventertainments 搜索页两类"假 200"点名报错**：该站把人机验证墙（`/cart/verifybot` + reCAPTCHA"我不是机器人"，手工都难过去）与 404 下架页都按 HTTP 200 返回，旧解析一律报"搜索页未解析到结果"误导用户去查番号。现 `_parse_search_page` 先检出这两类页面并抛明因异常（验证墙→"被站点人机验证拦截，需手工过验证"；404→"探测番号可能已下架或未收录"），诊断报告直接显示真因。注意：Google reCAPTCHA 复选框 FlareSolverr 也解不了，该站自动化刮削在站点撤墙前处于不可用状态，非配置问题。新增两项回归（验证墙/404 各一），既有解析用例全过

- **「跳过前置 Poster 大小校验」提示文案合并为一段**：把「不因当前 Poster 已达标跳过 Amazon（…）」与「将从日亚官网搜索高清封面图；…」两条独立提示合并为一条，紧跟勾选框之后、按需自动换行；删除冗余的 `label_92`，并上移「官方图源兜底」「海报超分」消除空档。UI 结构测试补「红/黄/绿」三回归用例（合并文案 + 自动换行 / 内联于勾选框后 / 删除冗余 label 且文案不重复）

- **#182 演员设置页 Gfriends 本地仓库「选择目录」按钮与本地头像库样式不一致**：两按钮在 `MDCx.ui` / `MDCx.py` 定义已完全一致（Fixed、110x40、「选择目录」、无本地样式覆盖），差异在 `style.py` 全局药丸按钮选择器只含 `pushButton_select_actor_photo_folder`、漏了 `pushButton_select_gfriends_local`，Gfriends 按钮回退为默认方块样式。现浅色/深色主题 normal/hover/pressed 六处选择器一并补上，`.ui` / `.py` 无需改动。UI 结构测试补「红/黄/绿」三回归用例（全局样式六处全含 / 两按钮 ui+py 定义一致且无本地覆盖 / 修复前缺席形态不再出现）

- **#181 命名页 / 读取模式等界面文案与布局整理**：命名页「视频命名规则」模板预览高度固定为约原来的 1/3，说明文字按当前宽度精确贴合，「视频文件名」上方的大片空白消除，组高随内容收缩、后续分组同步上移（保持 19px 间距）；命名页各「命名规则」分组右边框与「下载」「翻译」页对齐（左缘不变、缩放时保持对齐）；「演员名加入字符」改为「演员名末端插入」并给「等演员」输入框补上左侧标签、拉到与同类输入框等长；马赛克命名规则四条说明（无码破解 / 无码流出 / 无码 / 有码）文案更新，修复「有码」「无码流出」说明显示不全、无码说明压到两行；字段说明里 `four_4K` 更正为 `definition`；下载页「有时图片已被源网站删除，此时下载图片大概率失败」「有且仅限有码类型的番号，直下/搜图/右裁剪会选优」「有码番号缩略图可以裁剪，如果不想被裁剪可以勾选」及「剧照图：」等文案调整；读取模式区勾选项与说明文案重排（「本地已刮削成功的文件，按更新模式规则重新整理分类」「本地没有nfo的文件，按正常模式规则重新刮削」「允许更新nfo文件」「本地nfo内有链接，重新下载图片等文件」「本地nfo合并策略」「删除本地已下载的图片和nfo文件」，说明段去掉冗余换行与空格）；「排除目录」改为「刮削排除目录」。新增文案回归测试（`tests/test_ui_structure.py`：读取模式 / 排除目录精确文案 + 马赛克命名规则四条说明），改回旧措辞即报红

- **CF Bypass 自动适配层三处逻辑修复**：复核设置页文案「CF Bypass 地址留空、配了下方外部 CF 服务则自动启动适配层，两者均空则关闭」——主链路已实现（`AsyncWebClient` 按 `cf_bypass_url` / `cf_bypass_trawl_url` 推导 `_cf_bypass_enabled` / `_trawl_adapter_enabled`，前者优先、后者懒启动）。本次修复：① `mdcx/cmd/crawl.py` 两处新建 `AsyncWebClient` 漏传 `cf_bypass_trawl_url` / `cf_bypass_trawl_backend`，命令行调试爬虫走不到自动适配，现补齐；② `request` 原来每次请求无条件等待 `_ensure_local_bypass`（最长约 60s，失败还永久禁用适配层），现仅在命中 CF 挑战页时才阻塞拉起并复用单次判定结果，普通请求不再被拖慢；③ 传输层失败（`resp is None`）时仍取 `resp.status_code` 做挑战判定导致误报，现加空守卫、传输失败直接走重试；④ `_ensure_local_bypass` 锁内补查适配开关，防并发竞态下已禁用仍拉起。回归测试 `test_web_async_cf_bypass` / `test_trawl_adapter` / `test_network_check` / `test_web_async_limiter` 全过

- **missav / avsex / getchu / javlibrary / r18dev 代理路由与外部 CF 回环地址修复**：诊断里这几站直连即被 RST（curl 35/56，无 HTTP 响应——bypass 只能救挑战页，救不了传输层失败），根因在代理路由而非 bypass：① 默认走代理名单漏了 `avsex.cc` / `getchu.com` / `dl.getchu.com`（默认 34 域 → 37 域）；② 名单写主域 `javlibrary.com` 时动态镜像（f101w/c97k、GitHub 学习到的新域）既不相等也非子域、全部逃逸直连，现 `is_proxy_host` 加域名反查站点归属分支、同站镜像自动跟随（直连白名单仍优先）；③ `r18dev` 搜索/详情硬编码 `use_proxy=False`，路由表写了也白写，现交由请求层按配置判定；④ `getchu` 的 `base_url_` 改走 `get_site_url`，支持站点自定义 URL；⑤ 外部 CF 服务填 `https://127.0.0.1:8191` 这类回环 https 时 FlareSolverr（纯 HTTP）TLS 握手失败、适配层 60s 探活失败永久禁用且检测红灯，现 `normalize_trawl_url` 在适配层/配置迁移/检测三处统一降回 `http`，非回环 https 不动。新增 `tests/test_cf_proxy_routing.py`（27 项：归一化 + 默认路由 + 白名单优先 + r18dev/getchu 哨兵），既有 `test_r18dev` / `test_getchu` / `test_network_check` / cf bypass 相关用例全过

- **直连传输失败（RST/超时、无响应）时 bypass 兜底一次**：强制直连站点在墙内直连即被 RST 时（curl 35/56，无 HTTP 响应），挑战判定永不触发、bypass 从未被咨询，外部 CF 服务等于摆设。现 `request()` 在整轮重试一次响应都没拿到、且配了 bypass（外部 CF 服务/手动地址）时，给 bypass 一次兜底机会（真浏览器指纹可能通过 curl 指纹被 RST 的链路）；仅彻底失败后触发一次，正常通过的请求走不到这里。限制：仅 GET/HEAD、非流式、`enable_cf_bypass` 开启且未超 bypass 轮次预算；兜底失败保留原始传输错误为主错误。检测链路同步：`run_network_check_item` 在 `response is None` 时同样试一次 bypass，成功则标注「连接正常，已通过 CF Bypass（mirror）」。新增 `tests/test_cf_transport_fallback.py`（7 项：兜底成功/失败保原始错误/开关关闭不兜底/有响应不兜底/POST 不兜底/检测侧成功与失败）

- **FlareSolverr /v1 proxy 参数改传对象形式**：适配层此前把「Bypass 独立代理」字符串（如 `http://127.0.0.1:7897`）原样塞进 `/v1` 的 `proxy` 字段，而 FlareSolverr 只接受 `{"url", "username"?, "password"?}` 对象——配了独立代理反而整单失败/被忽略。现 `_flaresolverr_proxy_object` 自动转换（含 `user:pass@` 拆分），无代理时不带该字段。`tests/test_trawl_adapter.py` 补 7 项（格式转换 + /v1 实发断言）

- **外部 CF 适配层启动探针改查 /healthz（修"适配层启动失败"）**：此前 `_wait_ready` 用 `GET /cookies?url=http://example.com` 做就绪探针，每次都会触发一次真实 FlareSolverr 会话（冷启动常需 5 秒以上），而探针超时只有 5 秒 + 0.5 秒轮询——重叠请求把 FlareSolverr 单浏览器队列越压越慢，60 秒永远等不到 200（日志里全是 `ReadTimeout`，且 `str(e)` 为空导致报错尾巴无信息）。现适配层新增不碰后端的 `/healthz` 轻量探活，启动探针只查它（本机实测 0.6 秒就绪，原来 60 秒超时）；探针失败信息带上异常类型。另补 `GETCHU` 检测项漏掉的 `enable_cf_bypass=True`（此前 getchu 直连 RST 时两处兜底都进不去）。新增 `test_healthz_returns_ok_without_touching_backend` 与 `test_getchu_spec_enables_cf_bypass` 回归；lulubar 的 403 CF 挑战页走既有挑战 bypass 链路，适配层能启动后即由 FlareSolverr 真浏览器解（重跑检测验证）

- **网络请求超时/重试语义写明 + 两次上调（后于下一条回退，见合并记录）**：①把「请求超时 × 重试次数 + 递增退避」的语义写进 `Configuration.md`——每次尝试最多等满超时秒（如直连被 RST 每次都要等满），重试之间按 2s / 5s / 8s… 递增等待；`timeout` 30s × `retry` 3 次约 97s、5 次约 176s。②`retry` 3 → 4（`actor.json`，代码默认仍为 3；重试滑杆上限 5 → 4，`.ui` 与生成的 `MDCx.py` 同改），30s × 4 约 135s，多花时间换连接质量。③`timeout` 30 → 45（`actor.json`；代码默认同步上调 `models.py` 10 → 45、`default_config.json` 同步；超时滑杆上限 30 → 45，否则设置页存盘会把 45 钳回 30），45s × 4 约 195s。④同期网络检测的**刮削探测**超时由 30s → 45s → 60s 三轮改为 30s → 45s 两轮（单站最坏等待由 135s 降到 75s；`SCRAPE_PROBE_ATTEMPT_TIMEOUTS` 元组派生全部文案与测试）。**终态见「网络请求超时/重试三改两复」条：超时回退 30s、重试回退 3 次。**

- **检测报告根因分组新增「CF Bypass 已尝试但未解开」**：此前 bypass 兜底失败（返回仍是挑战页）的站点会被计入「Cloudflare 拦截」，建议语却是"请配置外部 CF 服务"——服务明明已配好并实际尝试过，白让人配一遍。现按文案中的"兜底亦失败 / 已尝试 CF Bypass"单独成组，建议改为关代理干净直连重测或换节点。同时 `avsex` 搜索页加 CF 挑战页点名（`just a moment` / `cf-chl` / `challenge-platform`），挑战页不再混进"搜索页未解析到结果"。测试：`test_avsex.py` 新建 4 项（注册/挑战点名/正常解析/真无结果），`test_format_summary_groups_failure_causes` 加未解开用例

- **超时 45s → 30s、重试 4 次 → 3 次（检测提速，本组四次调整的终态）**：javlibrary / missav 类直连站点每次尝试都要等满超时，45s × 4 最坏约 195s，整轮检测被拖慢。改回 **30s × 3**（单请求最坏约 97s）。同步：`actor.json`（timeout / retry）、`models.py` 默认超时 30、`default_config.json`、设置页两拉动条上限（超时 45 → 30；重试上限改为 3，即 2 / 3 二档可选）、`Configuration.md` 超时/重试两行重算

## v2.1.2 (2026-09-22)

### 修复

- **#181 软件界面「刮削中/成功/失败」统计标签最大化后与结果树「成功」错位**：窗口最大化时统计标签右对齐到结果树右上角，与结果树首行「成功」错开。现最大化时统计标签左对齐到结果树左缘（贴到「成功」列正上方），纵向与还原/最小化一致、不下沉；非最大化（还原/最小化）窗口保持设计位置不变，界面不做任何改动

## v2.1.1 (2026-09-22)

### 文档

- **UI 文案与文档对齐**：使用说明/刮削网站弹窗补上默认源 7mmtv；NFO 合并策略改用界面下拉中文名；Cookie 步骤改为「浏览器」；设置路径「界面外观」改为「高级」；读取模式提示对齐勾选项名称。Wiki FAQ 启动自检改为五项、维基限速改为 5 次/秒 + 180 次/分；新手上手补 macOS Intel 产物。配置参考把「刮削模式」与「网站偏好」分开写，代理改为一行地址并补直连白名单

### 开发

- **本地/CI 自检减负**：推送仍跑全量测试；出厂演员库/信息库校验只在对应 xlsx 或校验脚本改动时执行；`check_ui_layout` 移出门禁（结构约束由现有 UI 结构测试锁定，该脚本改为手工诊断）

### 修复

- **文件名带 `CRACKED` 未识别为无码破解**：海外包常见 `ABF-131-CRACKED.mp4` / `ABF-131.CRACKED.mp4` 这类英文标记，此前只认 `-uncensored.`、`.restored`、中文「破解/克破」、`UMR.` 和 `-U`/`-UC`，这类文件会被当成普通有码去刮、重命名也不带破解后缀。现路径中独立的 `CRACKED`（大小写不敏感，前后须是分隔符）一律按无码破解处理，与设置里的说明同步

- **窗口偏矮时导航栏左下角状态信息被裁**：窗口高度不足 730 时，左下角状态文字从「配置文件名 / 版本号」起被窗底裁掉看不清。现状态区保证完整落在窗口内。一并把窗口尺寸策略改为按屏幕自适应：启动尺寸不再固定 1030×700——主流大屏（1080p 及以上）默认放大到 1280×860，封面与信息区同比例放大、观感明显改善，小屏/高缩放自动收窄进屏内；最小尺寸全平台统一生效（原先 Windows 之外无下限）——1080p 下最小高 550 提到 650，主界面底部字段不再被裁到够不着；125% 缩放下仍可缩到 648，不回到"锁死无法缩小"的老问题

- **设置→网络→网站设置 清除残留说明**：删除「必须安装 Chrome 浏览器。可处理某些无法获取的网站，内存占用会显著提高」一行——它是旧「浏览器模式」开关下线后遗留的孤儿说明（对应控件已不存在），内容也与现行实现（Selenium+Edge 过 Cloudflare / TRAWL 外部服务）不符

- **#175 正在获取数据时关闭演员管理器，主程序一起退出**：空闲关闭大多没事，取数中途关窗却会把还在跑的后台线程连窗口一起拆掉——Windows 上整进程直接中止，日志是空的。现关闭前会取消并等待全部工作线程（取列表/获取数据/同步/清洗/自动刷新）；等不及的线程脱离窗口再自行结束，主程序保持运行。正常退出入口不变（主界面关闭按钮、托盘菜单「退出 MDCx」）

- **#171 数据清洗误删合法结构（换行/段标题）**：#149 清洗规则把 `<br>`/换行/`=====` 段落标题一并压成中文逗号，导致 Jellyfin/Emby 客户端演员简介从分行列表退化成"一坨文字"。根因是 #149 把 wiki 源拼接的合法结构误判为"噪声"——`<br>` 与 `=====` 是客户端渲染分行所依赖的结构，不应压平。现收窄清洗出口 `clean_overview_text` 至**仅清 minnano 占位文案**，`<br>`/换行/段标题原样保留；`dump()` 与 `update_person_info` 同步套用，存量占位随下次同步自愈，合法结构不再被误删

- **#173 软件界面「结果树/统计栏」固定 202 宽，最大化后与缩略图间距过远**：结果树（刮削中/成功/失败统计栏）此前宽写死 202px、右缘贴页面右 18px，窗口拉宽时左缘不跟随，最大化（1920）下统计栏左缘离缩略图右缘 280px——右边贴了、左边空一大块，与还原窗口（间距 20px）观感不一致。现结果树宽随 `cover_scale`（`窗口宽/820`）等比拉伸，右缘仍贴页面右 18px、左缘贴向缩略图右缘，最大化间距从 280px 收窄到 ~62px，还原窗口不变（cover_scale=1 时宽仍 202）；右缘锚定与 NFO 伴侣面板右缘（取缩略图右缘）均不受影响

- **#177 点导航按钮切页后编辑 NFO 面板浮在功能页上盖住内容**：编辑 NFO 面板（`widget_nfo`）是主窗口顶层控件、不随功能页切换，点「软件日志/软件工具」等导航按钮切页后面板仍浮在新页上盖住内容（#166/#168/#169/#173 中反复反馈的"切页后面板盖住右侧"观感根因）。现切到非主界面页时自动**暂隐**面板（非关闭——表单值与结果树选中态保留在内存），切回主界面自动恢复；切页时有未保存 NFO 改动先弹「保存/丢弃/取消」确认，取消则留在主界面继续编辑、面板保持打开。由此替代了此前「面板左缘贴导航最左、盖住左侧按钮」的诉求——那方案会让编辑 NFO 期间无法切页，本方案不盖导航、可切页、切页后面板自然隐藏，两全

- **#174 网络检测后网站设置下拉里 theporndb 仍无绿/黄/红圆点**：#129 已让「账号/API」组结果回标下拉，但 ThePornDB Token 检测项漏挂站点归属（`site=theporndb`），缓存写不进去，网络设置「当前网站」和刮削网站「指定网站」两处都空着。现补上站点归属，有 Token 且检测通过标绿、未填 Token 标黄；`thejavdb_api` 在 #129 已挂站点归属，与启动自检里的 JavDb（javdb.com cookie）不是同一项

- **#176 全量获取演员资料时大量「wiki 个人资料表格列数不匹配」警告，生日/出生地丢失**：infobox 解析此前把全表的 `th` 与「无样式无跨列」的 `td` 各自攒成两个列表再比长度——日文演员信息框的数据格统一带对齐样式（一个都收集不到）、表头/页脚跨列行又造成错位，正常页面也被判「列数不匹配」整表跳过，生日/出生地/简介里的个人资料段全部丢失。现改为**逐行配对**（行内键格配该行数据格），标题行/分区行/页脚行天然不成对直接跳过、互不干扰；同时识别「出生地」标签（旧只认「出身地」），出身地值先剥离前导「日本」与紧随标点再取地名（「日本 埼玉县」不再被当纯国名丢弃）。另说明：「跳过 N 个不在所选媒体库影片中出演(Actor)的人员」为 #157 的预期行为——Emby 接口不支持按角色过滤，软件与库内影片演职员表中角色=演员的人名集合取交集，导演/配音等未以演员身份出演库内影片的人员会被剔除

- **#179 工具页「刮削缓存管理」失败列表：小窗出横向滚动条、最大化右侧大片空白**：表格列宽此前固定 5×130=650，窗口缩放表格跟着变而列不动——窄于此值出横向滚动条、宽于此值右侧留白；点「刷新统计」后按内容撑列更会失控（长错误信息实测列总宽超 3 倍视口）。现文件名/最后错误两列随视口分摊剩余宽度、其余三列按内容收缩，列总宽恒铺满表格且永不超出视口，两种现象同时消除，刷新后也不再撑破

- **#180 演员详情「现有数据」简介把 `<br>` 显示为字面文本**：Emby 服务器上的简介以 `<br>` 分行（客户端渲染需要，数据本身正确），但 MDCx 详情对话框按纯文本直出，用户看到满屏 `<br>` 标签。现仅展示层把 `<br>`（含 `<BR>`/`<br/>`/`<br />`）还原为换行，写回服务器仍保持原样。诉求 2（清洗删段标题/`<br>`→逗号）在 #171 已整体移除，清洗现只删 minnano 占位文案，合法结构一律不动

- **#30 DMM 图床链接探测提速**：图片候选存在性校验此前每次完整下载整图（实测一批 15+ 候选各 3-4 秒，站点吞吐成为批刮瓶颈）；现改为带 `Range: bytes=0-1023` 的流式探测——只传 1KB 响应头即判定存在与总大小（206 取 Content-Range、200 取 Content-Length），占位图阈值判定逻辑不变；个别服务器不给任何大小头时自动回退一次完整下载，行为与旧版一致（借鉴 dmm-proxy-api 项目的探测思路）

- **#21 图床失败自动冷却**：某图床连续返回服务器侧错误（403/429/5xx/Cloudflare 拦截）时，此前每次刮削都会重新逐一撞一遍死图床，白白拖慢整批。现新增图床级冷却：60 秒窗口内同图床累计 3 次服务器侧失败即冷却 2 分钟，期内该图床的图片候选直接跳过、自动改用备用图源；冷却状态持久化到磁盘，**程序重启/断点续刮后依然生效**；成功下载即解除冷却与失败计数。本地网络问题（超时/连接重置等传输层错误）与 404 未收录不计入，不会误伤图床

- **#25 演员管理器「停止获取」后立即重开，旧任务残留结果覆盖新任务**：点「停止获取」取消取数后，旧线程已排入事件队列的进度/完成回调会晚于新任务启动到达——表现为进度条被旧值跳变、演员列表被取消前的半成品结果覆盖。现引入任务会话代数：每次发起/取消任务递增代数，线程回调携带颁发时的代数，过期回调整体作废直接丢弃；取消后界面即时恢复可操作，不再等旧线程收尾信号

- **#26 海报超分增强（实验性）**：老片/下架图常只剩 147x200 级低清封面，此前"高清升级"只能靠站内换源，全网无高清就没办法。现对落盘海报做 AI 超分辨率放大（Real-ESRGAN 4x / waifu2x 2x 两档预设，仅当最长边低于阈值（默认 800px）时触发）；**开关默认开启**（设置 → 下载 → 下载高清图 组，"海报超分"，与 Amazon 高清图、官方图源兜底同组同风格，绿色说明直接写出阈值/内置或首次下载/失败保持原图）。工具获取方式：Windows / Linux 打包版已内置，首次使用时释放到 `userdata/sr/tools/<tool>/`；macOS 打包版与源码运行首次使用时从官方 GitHub Release 下载（约 30-60MB，仅一次），下载后校验 sha256 确认是官方原包。下载失败、无 Vulkan 环境或超时均静默保持原图，不影响刮削结果。Windows / Linux 打包版因内置工具，安装包体积约增加 100MB。（该版本首个 20260921 构建因打包脚本提前清空 `build/` 目录，工具未真正打进安装包；已修复为清理时保留 `build/sr_tools`，且 Windows/Linux 缺工具或空目录直接构建失败，不再静默降级。CI 冒烟与手动打包工作流同步补上构建前拉取步骤，避免缺工具把主干 CI 打红。此前即使打开开关也不会生效：Linux 资产名与实际二进制名均不匹配，工具始终识别为未就绪。）预设与阈值可再经配置 json `poster_sr_preset` / `poster_sr_max_dim` 细调

## v2.1.0 (2026-09-19)

### 修复

- **#166 主页「编辑 NFO」铺满整页、切番号会关掉面板**：覆盖层此前铺到窗口右缘，把结果树和播放/文件夹按钮一起盖住，点另一部番号只能先关面板。现改为主页伴侣面板：左贴导航、右收到缩略图右缘（不盖番号树），还原/最大化共用同一套锚点；面板开着时切番号会同步刷新标题/简介等字段，有未保存改动先确认保存/丢弃/取消。标题居中，保存与关闭成对居中（间距 108px），演员/标签的「多个以逗号隔开」改到输入框提示，网页地址下方不再留大块空白

- **#165 Official 站点说明与「检测网络」覆盖面易被误读为只有无码路由**：official 抓取一直是"有码 30 家厂牌官网 + 无码 5 站官网"综合按前缀路由（使用说明所述准确），但站点悬停说明主句只列无码五站、有码塞在句尾，且 #129 检测改造仅覆盖无码五站——两处叠加容易读成"official 没有有码路由"。现重写站点说明为三档结构（有码 30 家/无码 5 站/检测覆盖面注记），网络检测与抓取范围一目了然；使用说明保持原样

- **#164 演员管理器「获取数据」下拉重排与「重新获取所有演员简介」新模式**：下拉项按「单缺字段 → 双缺 → 并集 → 重新获取组」范围递增重新排序（仅缺失简介 / 仅缺失头像 / 头像和简介都缺 / 缺失头像或缺失简介 / 重新获取所有演员详情 / 重新获取简介 / 头像 / 头像和简介），去掉「（并集）（交集）」标注——名称已自明，集合术语保留在悬浮说明；默认项显式锚定并集，打开管理器仍是最通用的缺失补全模式。新增「重新获取所有演员简介」：全量重新获取但**只回写简介**，出生日期/出生地/标签/头像/影片数一律不动——适合只想刷简介、又怕覆盖手动修正过的其他字段的场景（与「重新获取所有演员详情」的区别在悬浮说明中标注）

- **#162 数据清洗失败「只见计数不见原因」，且完成后误以为还要点同步**：清洗是直接改写服务器的（不经取数/同步流程），但旧版失败原因被丢弃——日志只有「失败: N」计数，无名字无原因；清洗完成后无待同步项，「开始全部更新同步」按钮禁用又被误读为"没反应"。现清洗失败逐条落日志（演员名+服务器返回原因），完成弹窗列出失败者名单并提示「再点一次数据清洗即可仅重试失败项」；全部成功时明确告知「已直接写入服务器，无需再点同步」。字段范围审查结论（应要求复核）：清洗仅写详情与出生日期两字段，出生地/标签/头像/影片数/姓名均不在清洗 payload 内。确认框改造为可编辑规则表（含用户自定义规则持久化、中文化、最大化等比缩放）为独立增强需求，另见议题 #163

- **#160 演员管理器最大化后底部出现横向滚动条**：演员列表的「详情/标签」列宽只在窗口 `resizeEvent`/`showEvent` 时按视口宽度重算，而纵向滚动条在演员数量变多时出现只会让表格视口变窄、并不会触发窗口的 resize 事件——列宽仍按变窄前的视口分配，于是各列总宽超出视口，底部横向滚动条随之出现（窗口越大、演员越多越明显）。现额外监听表格视口的尺寸变化事件，在纵向滚动条显隐、窗口缩放、DPI 变化等任何视口几何改变之后都按真实视口宽重算列宽，使各列总宽始终铺满视口、不再产生横向滚动条

- **#159 主窗隐藏到托盘后，关闭演员管理器会连带整个程序退出**：演员管理器是独立窗口，Qt 默认「最后一个可见窗口被关闭时程序自动退出」——主窗隐藏后它就成了最后一个可见窗口，随手关掉演员管理器等于关掉整个软件（此时主窗仅最小化则不受影响）。现起软件不再因关闭任何工具窗口而退出：无论演员管理器开着、关着、最大化还是缩放，隐藏主窗期间关闭它都只关它自己；正常退出入口不变（主界面关闭按钮退出确认、托盘菜单「退出 MDCx」）

- **演员管理器「获取数据」下拉模式的四轮演进（#127 / #147 / #155 / #158 合并为一条）**：四条是同一功能区域的连续演进，终态是**四个缺失类模式与统计栏四类分项严格对账**——缺头像/缺简介的判定抽成单一函数，统计栏与取数模式共用同一口径。
  - **① #127 按模式筛子集，不再默认全量遍历**：此前无论模式如何都逐人遍历全库——已有简介的演员仍每人发一次服务器详情核对（万人库每次白白多打数千请求），进度分母始终是演员总数、观感如同全量获取。现启动前按模式先筛出目标演员，进度按子集计数：「仅全部缺失头像+简介」= 缺任一字段者的并集（头像缺失者补头像、简介缺失者补简介），「仅缺失头像/简介」各取对应缺失者，「重新获取」三档保持全量（用户显式意图）；简介为「无维基百科信息」占位文案的按缺简介处理（重新补全为既有设计）。「缺失」类模式自始至终只写缺失字段、不覆盖服务器旧数据。万级库的重复获取从几十分钟降至秒级（首轮仍为真实缺失人数 × wiki 限速，属必要成本）
  - **② #147 统一缺失口径，计数对不上**：统计栏此前按「有无头像/有无简介」做互斥分类，而下拉模式把简介仅为「无维基百科信息」占位文案的演员也按「缺简介」处理——同一批人统计栏算「完整」、取数模式却去重抓，于是出现「统计分项之和 7257 ≠ 取数候选 7404」这种对不上的现象。现把「缺头像/缺简介」的判定抽成单一函数，统计栏、取数筛选、补全逻辑三处共用同一套口径（占位简介按缺处理），统计分项之和与选「仅缺失头像或缺简介」时实际取出的人数必然一致。四个分类用回归测试锁定「占位简介计入缺简介、不入完整」
  - **③ #155 新增「仅缺失头像且简介（交集）」模式**：②统一口径后，缺失类下拉只有并集（缺任一即取）与单字段两档，想只处理统计栏「全缺」那批演员没有对应入口。现新增交集模式——只选取头像和简介都缺的演员（占位简介按缺处理，人数与统计栏「全缺」分项严格一致），头像与简介两路同时获取。至此下拉与统计栏四类完全对账：完整+缺头像+缺简介+全缺=总数，并集=前三缺项之和，交集=全缺
  - **④ #158 下拉项文案优化**：「仅缺失头像或缺简介」→「缺失头像或缺失简介（并集）」、「仅缺失头像且简介（交集）」→「头像和简介都缺（交集）」（与统计栏「全缺」分项直接对应）、「全部头像+简介（重新获取）」→「重新获取全部头像和简介」、「全部头像（重新获取）」→「重新获取全部头像」，并集/交集成对标注、与统计栏四类分项对账一目了然。其中「重新获取全部简介」一名未采纳：该模式实际更新简介/出生日期/出生地/标签而非仅简介，#149 已定名「更新所有演员数据（不含头像/影片数）」，保持不动

- **#157 演员管理器「只看演员」在 Emby 服务器上从未生效，导演/编剧等非演出角色混入列表；统计栏新增「重复」分项**：Emby 的演员列表接口不支持按角色类型过滤（官方文档中该参数仅在查询特定人物时生效），服务端把全部演职人员一并返回——用户拿浏览器直查接口得到的总数与软件对不上即此背景（该数字同样含非演出角色，并非"真实演员数"）。现改为与「所选媒体库（缺省为全部库）影片演职员表中角色=演员的人名集合」取交集过滤，升级后列表数将更接近真实演员数；出演统计整体失败时自动跳过过滤以防误删。另在统计栏「总数」后新增「重复: N」分项（= 原始条目数 − 唯一名字数，同名多余条目一目了然，可在「设置」中用「重复演员去重（按名称合并）」合并）

- **#156 选择媒体库 20 行只显示 19 行、合集库混入列表**：①对话框的行高预算此前用「复选框高度/字体高/26px」估算，但列表行高实际由默认代理字号决定（从未给条目设置 sizeHint），两者无确定关系——Windows 上实际行高大于预算，20 行预算只容得下 19 行，长库名触发横向滚动条还会再吃掉约一行。现把每个条目的 sizeHint 钉死为复选框高度，行高预算直接取真实行高，并预留横向滚动条空间，各平台行数一致。②「合集 [boxsets]」是 Emby 自动创建的空壳库（无内容/演员/标签），现默认从列表隐藏并在计数中注明「已隐藏 N 个合集库」；极端情况下全部库都是合集时回退展示原始列表，避免空对话框

- **#149 演员管理器新增「数据清洗」：清理占位简介、`0000-00-00` 生日等历史噪声**：这类噪声全部来自软件自身的写入链路——wiki 源拼简介时插入 `===== 个人资料/外部链接 =====` 标题并把换行转成 `<br>`，minnano 命中无简介时写入占位文案，旧版本把哨兵生日原样写入服务器。现新增「数据清洗」按钮（位于「根据设定获取数据」与「开始全部更新同步」之间），点击后先扫描并列出身中噪声的演员与前 5 条清洗前后对照，确认后直接改写服务器：占位简介清空、非法生日重置为服务器未设置零值；头像与影片数不受影响。清洗规则收口在模型层单一函数，内置补全与管理器同步出口同步套用，未来写入不再产生同类噪声；minnano 命中无简介时也不再写入占位文案（此前占位被判为缺简介后每次取数又写回，形成死循环）。原「全部简介（重新获取）」更名为「更新所有演员数据（不含头像/影片数）」，明确它会全量刷新简介/出生日期/出生地/标签且不动头像与影片数，便于清洗后做全量刷新

- **演员管理器最大化后的封面缩放与简介/标签/NFO 编辑器布局（#144 / #152 / #154 合并为一条）**：三条都在修「最大化后显示量不增加、行被推出页底」，#152 的「行数随高度增长」方案被 #154 实测推翻，终态是**简介/标签行高恒定 40px、最多两行、按标签当前宽度做省略号截断**。
  - **① #144 封面/缩略图不随框放大**：出图流程残留设计尺寸硬编码（`resize(156×220 / 328×220)`），切封面时把已经放大的框砸回原尺寸，且窗口缩放只改框、不重新渲染图片。现缓存原图并在框几何变化时按宽高比 + 平滑缩放重渲染，切封面/缩放/还原三态一致，出图不再改写框几何
  - **② #152 简介/标签改为整行换行**：上一版（#144）用「每行增高 60px」的方式让空间，在真实 1080p 最大化下仍被压缩成单行；现改为「每行恒定 40px、自动换行、行数随窗口高度真实余量增长（最多 4 行）」，下方日期/导演/制作等行保持 40px 固定不变、随之下移不重叠（设计窗口与最小化时仍为单行、双向幂等）。同时修「编辑 NFO」编辑器：此前固定几何、主窗放大后滞留左上角，现改为铺满侧栏右侧内容区、内部滚动区随窗放大，最大化后无需横向滚动即可边编辑边看更多字段
  - **③ #154 复测推翻 ②，行高改恒定**：简介/标签此前按最小化宽度做固定字数截断（简介 38 字、标签 76 字），窗口放大后右侧大片留白、内容并不比小窗多；②让行高随窗口增高，在 1080p 最大化时又把下方日期/导演/制作行推出页底。现简介/标签行高恒定为设计 40px、最多两行，超长文本按标签当前宽度做两行省略号截断——宽度越大每行容纳越多，最大化自然比最小化显示更多，其下各行只随封面增高量下移、不再出页底。另修「编辑 NFO」覆盖层：内容区此前固定 860×1300、19 个字段绝对定位，最大化后字段仍定宽（右侧大片留白），保存/关闭按钮固定在 y=630 中部、放大后悬在中间；现内容区改为行式布局、字段随宽度拉伸，保存/关闭钉底右下，且首次打开（不经窗口 resize）也会同步几何
  - **验收边界**：最小化小窗为验收边界，布局保持设计稿不变

- **#133 连接 Emby/Jellyfin 服务器与获取媒体库列表耗时几分钟、且日志无任何提示**：此前工具把这些自建媒体服务当外部反爬站点处理，所有请求都走了为对抗指纹检测设计重型握手与连接池（只对 `127.0.0.1` 免检），真实主机（内网 IP / NAS / Tailscale 等）每次都会被拖到秒到分钟级；同一请求第三方工具用普通 HTTP 却几乎瞬间连通。现对 Emby/Jellyfin 的连接、取媒体库、批量统计与上传/删除头像等控制类接口改用轻量直连客户端（无指纹握手、不建连接池、显式带超时），并对这类接口补了耗时/失败日志——连接与取媒体库应恢复到秒级，若仍有卡点也能在日志看到具体卡在哪里

- **#153 演员管理器出生日期靠左显示、右侧竖直滚动条过细镂空**：①「出生日期」为定宽列，现与其他列一样居中显示；②竖直滚动条原本是极浅色 10px 圆角细条、在浅色界面下几乎"隐形"，现加宽到 16px、改直角实心、滑块加高并给轨道加底色，更接近浏览器滚动条（深色模式同样生效）




- **演员管理器批量同步 HTTP 400 的两轮根因（#126 / #145 / #148 合并为一条）**：批量同步 400 前后有两个互不相干的根因，生日归一化也经历「严格→宽松」两轮。
  - **① #126 根因一：哨兵生日 `"0000-00-00"`/`"0000"` 是 truthy 字符串**：随 `dump()` 一路带进同步 payload，服务器（Emby/Jellyfin）把非法日期当无效数据拒收整条请求——批量同步中「有生日的成功、无生日的全失败」即此根因。现对下发前的出生日期/年份做归一化：哨兵值与非法日期（如 `1990-13-40`、截断串）一律不下发，合法日期统一补全为服务器规范 ISO 格式，年份强制转整数；手动编辑与批量同步共用同一出口，一并生效
  - **② #145 根因一的补漏：非零填充合法写法被整条丢弃**：①的归一化只认严格 ISO，`1990-1-2`/`1990/5/12` 等合法写法被当非法略过。现改为宽松解析：支持 `- / .`、年月日、空白等分隔符与紧凑 `YYYYMMDD`，补零后用真实日历校验（仍拒绝 13 月、2 月 30 等），统一输出规范 ISO；管理器的日期归一化与内置补全的 `dump()` 出口合并为同一模型层函数，两条同步路径行为一致
  - **③ #148 根因二（①修复后仍整条失败）：`Value cannot be null. (Parameter 'source')`**：未收录简介/标签的演员同步仍失败，根因在服务器侧——Emby/Jellyfin 的 `UpdateItem` 把请求体里缺省的 `Genres`/`Tags`/`ProviderIds` 反序列化为 null 后直接 `Distinct()`/`ToList()`（上游 Jellyfin issue #17366 / 修复 PR #17370）。软件此前发的 payload 是「有才发」的局部字段，恰好触发；内置补全路径的 `dump()` 恒带这三个字段所以从不触发。现批量同步出口恒回填三者：无新值用服务器已有值、`ProviderIds` 合并新旧并丢弃空值——既不覆盖旧数据，也消除服务端空引用，对已修复的新版服务端同样无害
  - **终态**：两个根因各自消除后，批量同步对「无生日」「非 ISO 生日」「无简介/无标签」三类演员都能一次成功



- **统计栏「原始条目数 / 唯一名字数」切换（#113 新增 / #143 持久化，合并为一条）**：用于分辨演员总数差异是去重导致还是真实数据差异。#113 让切换即时刷新并随同步回写；#143 补上「此前只影响当次显示，关闭管理器或重启后回退到默认『原始条目数』」的缺口——现启动时恢复上次选择、切换时立即保存（写入失败仅提示、不影响计数显示），与其余设置项行为一致

- **#146 演员管理器「选择媒体库」窗口过小，媒体库多时半屏滚不完**：对话框默认只开到 420×320 的最小尺寸、从未自适应，二十多个库每次要看 7 滚 7。现按库数自适应初始大小：同时可见最多 20 行（库少时窗口相应小，不撑大片空白），宽度按 16:9 配合放宽，整体不超过屏幕可用区的 85%（小屏笔记本不会出界），窗口仍可自由拖拽调整；隐藏边框与否两种模式下表现一致

- **#129 网络检测完成后，网站设置下拉中 dmm_api/thejavdb_api/missav_api/theporndb/official 五项不标注状态**：①前四项其实一直有检测（诊断报告"账号/API"组），但状态缓存只收集"刮削站点"分组——放宽为凡有站点归属的检测结果都回标到网站设置下拉；②official（无码官网五站统一路由）原以"无固定检测入口"整体跳过，现改为逐站子检测（报告按 official·1pondo 等五站各出一行），下拉徽标按"五站取最差"聚合——整条路由依赖五个官网，任一不可达即标注黄/红

- **#128 网络诊断三站探测失败处理与「搜索失败」报错无因问题**：①mywife 的探测番号 1500 对应页面已被站点下架（HTTP 500），换为实测有效的 model 番号；②爬虫「搜索失败」报错现在聚合每个搜索页的真实原因（请求失败的具体错误 / 页面可达但未解析到结果）——旧版只报"搜索失败"四个字，站点风控挑战页与未收录无从区分，用户拿到诊断报告也无从自查；③r18dev 的搜索/详情请求 URL 改为跟随站点自定义域名设置（旧版硬编码主域，「设置」里改了自定义 URL 对 r18dev 不生效）；④aventertainments 与 r18dev 经实测站点、接口与探测番号均正常（个别网络环境下探测超时/失败与代理节点路由有关，升级后可凭新报错细节判断）



- **#140 发布工作流 macOS Intel 构建永远排队**：GitHub 已于 2025-12-04 下线 `macos-13` runner 镜像，macOS x86_64 构建 job 无 runner 可接、停在 Queued。现替换为官方 Intel 接替镜像 `macos-15-intel`，并升级 actions 到原生 Node 24 版本（checkout v7 / setup-python v7 / setup-uv v10.1.0 / upload-artifact v7 / download-artifact v8 / cache v6 / stale v11 / github-script v9 / action-gh-release v3），Node.js 20 弃用警告随之消除（Intel runner 2027 年秋季将整体退役，届时 x86_64 mac 产物停止提供）

- **Dependabot/OSV 安全告警：soupsieve 2.8.4 → 2.9.2**（beautifulsoup4 的传递依赖，生产依赖）：2.8.x 在 selector 正则上存在两处多项式时间 ReDoS（O(n²)，CVSS Low，仅可用性）。CSS 选择器由代码固定、并非来自被抓取内容，实际可利用性很低，但升级零成本且向下兼容，现升级到 2.9.2；升级后 OSV 复扫 123 个锁定依赖 **0 已知漏洞**

- **Dependabot/OSV 安全告警：anyio 4.11.0 → 4.14.2**（httpx 的传递依赖，生产依赖）：两条公告均修复于 4.14.2——①CRITICAL（CVE-2026-63374）TLSStream 按 IDNA 2003 编码主机名，可致 TLS 证书欺骗；②MODERATE（CVE-2026-64847）进程池 worker 的 stderr 未排空时可无限阻塞。软件网络栈以 httpx/curl_cffi 为主，TLS 路径可触达①，故直接升级；4.x 内补丁级升级零 API 变更，升级后全量测试通过、OSV 复扫 124 个锁定依赖 **0 已知漏洞**

- **#130 启动自检纳入 FC2PPVDB，且 cookie 检查只告警不清空**：启动自检由「数据库 / ThePornDB / JavDb / JavBus」扩展为含 **FC2PPVDB** cookie 有效性检测（未填写时不发请求），并在日志输出其连接状态。同时修正 javdb cookie 检查"自动清空保存"的激进行为——网络/站点不可达、或页面未出现 `/logout` 只说明"未检测到登录态"，都不构成 cookie 失效的确凿证据：现一律**只告警、保留 cookie**，由用户手动替换。另修正 fc2cmadb 实际下发的会话 cookie 名为 `fc2cmadb-session`（连字符）而白名单只列了下划线写法的问题

- **#132 托盘隐藏主窗后操作演员管理器仍会弹出主窗**：`eventFilter` 在应用激活时对「非最小化隐藏态」调用 `show()`，托盘隐藏（`hide()`）后操作演员管理器即把主窗拉出。现移除该自动 `show()`，恢复显示只由托盘图标/菜单负责（最小化态由 Qt 自行保持）

- **#134/#136 演员管理器列表优化**：在「详情」与「标签」之间新增「出生日期」「出生地」列（取 Emby `PremiereDate` 前 10 位与 `ProductionLocations`，未设置生日按空值）；「详情」「标签」两列宽度按 3:1 分配剩余空间（标签约为原等分宽度的一半、余量给更需要的详情），各列总宽仍铺满窗口

- **#131 剧照下载失败后回退下一剧照网站**：按剧照字段优先级收集各来源地址，逐来源整组下载，成功即原子替换、失败换下一来源、全部失败沿用本地旧文件（原实现只试单一来源）

- **#125/#137 维基百科/维基数据刮削限速**：此前 wiki 域名沿用通用 8 req/s，批量补全演员信息时会触发维基媒体的速率限制（429）。现对 wikidata/wikipedia 域名用「双桶」限速——每秒 5 req/s（允许短时突发）+ 每分钟 180 req/min（滚动总量，贴官方 200/min 并留余量），并把 wiki 请求 UA 改为带项目地址的可识别 UA，归入 200 请求/分档；等效持续约 3 req/s

- **#124/#135/#141 最大化后封面/缩略图黑框盖住下方信息区字段**：封面区按窗口宽度横向放大后，下方简介/标签/日期/导演/制作等字段与勾选框仍停在设计纵坐标，被放大后的黑框压叠。现信息区保持设计左列（与「番号/标题/封面」竖向对齐，不再右移），并按封面框增高量整体下移、尺寸文字与勾选框跟随封面框底边；下划线/值列同步等比例加长——简介/标签与右列（时长/系列/发行）下划线右缘延伸到「缩略图框右缘」，左列窄字段（日期/导演/制作）按窗口比例加长，右列整体随比例右移避免重叠

- **#123 网络设置页「CF Bypass 代理」与「超时时间」文字重叠**：#114 新增「直连白名单」行后，下方超时/重试行未随之后移、叠进同一格。现整体后移一行并同步加高分组与滚动区，新增结构回归测试锁定「同一网格单元格不得叠放多个控件」

- **#121 日志页日志上方一大片空白**：界面文件里日志文本框残留约 12 个设计器空段落，日志被排在空段落之后。现清空残留空段落（含「成功列表」「说明」两个弹窗文本框），日志从顶部开始显示；「使用说明」为真实手册内容、保留不动

- **#122 使用说明展开 Official 官网清单**：把 Official 黑盒展开为有码片商官网 30 家 + 无码官网 5 站 + DLDSS/FNS/JIMMY 前缀路由到 Dahlia/Faleno，并订正收录数（35→36）；同步更新 `docs/Features.md`

- **#117 信息管理页小窗时表单被裁、保存按钮看不见**：小窗时右侧表单列被滚动条挤掉十几像素、保存按钮被推出视口。现小窗时自动压缩「简介/标签」多行框高度（60→最低 40px）换取整表免滚动，空间充足（含最大化）时布局不变

- **#115/#118 刮削探测超时 15s→30s 并自动递进重试**：单站按 30s → 45s → 60s 最多探 3 次，任一次通过即定论；仅超时/请求失败等**瞬时性**结果重试，「未收录」「被 Cloudflare 拦截」首次即定论。结果汇总新增「刮削探测多次超时」根因分组，与「未收录」「连不上」区分开

- **#114 网络设置新增「直连白名单」**：优先级高于原「使用代理网站」列表，命中白名单的站点强制直连、其余仍按原列表决定是否走代理；默认留空，旧配置行为不变


- **有码封面裁剪后仍输出横版（MGStage 等「有码但源图为横版直出」站点）**：非 VR 有码在任一直下成品为横版且本地有 thumb/fanart 时按有码右裁重裁并替换海报（普通直下与 MGStage 兜底两路均接入）；选优路径竖版过滤改为无条件执行，避免横版候选漏出直下。无码/素人/VR/本地无图源不受影响

- **#100-① 再次刮削失败文件被重复计数**：扫描到的失败文件与断点缓存自动恢复的同一批被重复入队（11→22），现恢复去重

- **#100-③ 「图片已被网站删除」日志不标来源站点**：图片校验失败日志统一附 `[host]` 标签，一眼锁定图床来源

- **#100-② 连续失败 3 次不再自动重刮的提示不明确**：提示改为直给入口「软件日志页点『失败』展开失败列表，点『一键重新刮削当前失败文件』」

- **#101 字段来源表「已失败」不区分失败类因**：失败标记附「请求超时 / 被站点拦截 / 请求异常」，一眼分辨站点连不上与未收录

- **映射云盘原子写入静默丢失（日志「Nfo done!」但盘上无文件）**：映射云盘上 `os.replace` 会返回成功但目标未落盘。现文本原子写（NFO / 演员库 / Emby 演员等）在 `os.replace` 后强制校验目标存在，校验不过自动退回直写并告警，直写仍不落则报错——绝不假报成功

- **调试日志三开关与字段来源排障块（#98-1 / 「显示字段来源信息输出精简」合并为一条）**：关闭「刮削过程信息」原本会连字段来源/内容块一起丢弃。现新增独立过程明细通道，三开关任意组合独立生效，关键节点行恒定可见；逐字段排障块一并归入该通道，`show_from_log` 开启时保持站点摘要精简形态


- **#98-2 停止后「继续刮削剩余任务」丢失任务**：五处同源修复——剩余任务原子写入、落盘竞态按快照比对清标志、停止时强制落盘、续刮不再误清子集外断点、启动传列表快照

- **大批量刮削的收尾期资源归还（#98 的三条合并为一条；原「#98-3」编号与「显示字段来源信息输出精简」条目重号，此处一并厘清）**：三条是同一收尾阶段的三处资源清理缺陷。
  - **① `Task was destroyed but it is pending!`**：流式响应中断后给内部任务 0.5s 退场宽限（超时才取消），影片处理结束等待共享图片任务收尾完成再退出
  - **② curl_cffi `cleanup TypeError`（连续报）**：关闭流式响应改为先中止传输、再交 curl_cffi 自身归还句柄，根除 `curl_multi_remove_handle` 收到失效句柄
  - **③ 停止/收尾后偶发「残留租约 1，等待空闲超 300 秒」**：取消恰好打断收尾的 await 导致租约永不归零。现三处加固——异步释放不可被取消打断、收尾异常不阻断租约归还、退出时恒归还连接

- **#96 网盘/映射盘目录创建失败被误报「权限不足」**：云盘对文件夹名长度/字符限制更严，超限返回 `WinError 123`。现识别后提示「目标盘可能限制文件夹名的长度或字符」，失败汇总归为「目录名无效或过长」，并建议调小目录名最大长度或先刮到本地盘

- **Lulubar（撸撸吧）网络检测误报「测试番号未被收录」**：探针番号改用该站确认收录的 IPZZ-547，并修正搜索结果番号的大小写匹配（标题大写番号前缀此前一律匹配失败）



- **#102 主界面三项 UI 交互修复**：①最小化主窗后操作演员管理器被拉出前台（`ApplicationActivate` 对隐藏/最小化主窗无条件 `show()`）；②封面区最大化后停留设计 220px 高不随窗口放大（改为按设计宽 820 横向等比缩放）；③左侧状态提示浮框最大化贴底太靠下（贴底预留 40px）。注：①后续由 #132 进一步修正为不再自动弹出

- **Linux 构建支持**：新增 Ubuntu x86_64 手动构建与正式 Release 产物（锁定依赖与 PyQt6 系统库），Linux 打包跳过 macOS 专用 `.icns` 参数

- **拦截自动二次启动（放行手工多开）**：用环境变量 `MDCX_IS_FIRST_INSTANCE` 区分「自动 exec 二次启动」与「用户手工多开」，前者拦截退出、后者不受影响

- **#106-① 带 DMM `z` 尾缀番号在 javdb/javbus 搜不到**：提取番号时剥掉 `z` 尾缀按基础番号搜索与命名落库，搜索/匹配也接受去尾缀变体

- **#106-② 剧照 20 张只保留 4 张（DMM 占位图字节阈值误杀真图）**：剧照缩略图真实体积仅 2.8–4.5KB，被 `<4096B` 阈值误杀。现阈值降到 2048，只兜住无跳转的垃圾响应（占位约 1.5KB）

- **#103 Jellyfin 12 演员列表恒为 0**：列表端点从 `/Items?includeItemTypes=Person` 回退 `/Persons`（`/Items` 下 Person 实体被层级过滤静默滤空），保留完整鉴权头避免 401

- **#106-③ 剧照改「有就下、没有就没有」**：不再按缩略图字节猜占位图，`_sanitize_extrafanart_urls` 只做无水印域名升级（全量、不抽检、不预下载），AWS 下载失败回退 `pics.dmm.co.jp` 带水印原图（新增反向映射，mono 老片补 `/adult/` 前缀）

### 优化

- **UI 文案体检修正**：修正指向不存在设置项的引导（「设置-目录」→「刮削目录」、「设置-其他」→「高级」、「设置-元数据」→「网络-网站设置」、「设置-刮削」→「刮削模式」等）；修正错别字「trilaer」→「trailer」、「请上方失败详情」→「请查看上方失败详情」；NFO 写入项「背景（cover）」按实现改为「缩略图（cover）」；演员管理器统一为「Emby/Jellyfin」；统一术语（海报/缩略图、演员、片商、想看人数、发行日期、多分集），刮削类型列举补上「素人」

### 文档与构建

- **文档纠偏**：`Development.md` 爬虫数 35→36、主窗口模块数改 11 个约 10000 行；`README.md` 去掉 INSTALL 不存在的 Docker 声明并补两篇文档导航；FAQ 启动自检项改为实际的「数据库 / ThePornDB / JavDb / JavBus」；`Configuration.md`/`User_Guide.md` 代理清单补齐 `7mmtv.sx`/`7tv022.com`、「设置→站点」修正为「设置→刮削网站」、演员库字段与默认端口 7890 订正
- **发版流程加固**：`scripts/bump.py` 支持 `--name` 同步展示版本名（`VERSION_NAME` + `pyproject.toml`）与 changelog 段日期、新增 `--check` 校验四处版本点；新增 `test_version_consistency.py` 把版本一致性纳入常规回归
- **打包与发布**：release 新增 macOS Intel（x86_64）构建与产物（DMG 按架构命名避免冲突，`Install.md` 同步）；CI 增加 PyInstaller 冒烟构建把打包参数回归前置到 PR/主干；release 构建 job 增加超时；`main.py` 任务栏图标改用 `resources.icon_ico`（修正冻结包内相对路径失效）；PyInstaller 锁定 `<7`；扩展 hidden-import 哨兵覆盖全仓动态导入

## v2.0.9 (2026-09-12)

### 修复

- **议题 #94 欧美（ThePornDB）同日多发刮错作品（张冠李戴）**：厂商+日期搜索若返回同一天的多个作品（如 FapHouse 2025-06-28 同时有 Wanilianna 与 Comatozze 的作品），此前一律按「日期桶」第一眼命中记录详情，碰上厂牌主名与站点短名不一致（Faphouse vs HobbyPorn）就会刮成同日的另一部作品。现采纳顺序改为「标题/演员精确命中 > 日期桶」并把日期桶降为兜底：多候选时按与文件名的相似度裁决、且设阈值把关，宁可报「未找到」也不乱配；裸番号文件（文件名无标题信息）不再凭日期押宝。指定网址刮（slug 直查）不受影响；新增 4 条回归测试锁定该样例

- **TRAWL 便携版打包依赖布局修正**：打包时的 `bun install` 改用 `--linker hoisted`（传统 npm 式平铺布局，全真目录无链接）。上一版 zip 里 elysia 等包只有符号链接、实际文件落在 `node_modules/.bun/` 隐藏仓，Windows 上 `Compress-Archive` 打包/解压过程按链接布局展开后，elysia 内部的 `node_modules` 相对路径错位，运行时缺 `@sinclair/typebox` 类 peer 依赖无法启动；hoisted 布局下每个目录都是真实文件，杜绝此问题。同批次把启动脚本的中文注释改为英文（规避 chcp 65001 下 cmd 对多字节注释偏移截断为「幽灵命令」的告警行）
- **TRAWL 便携版首次启动失败（`Cannot find package 'elysia'`）**：便携包把源码和依赖都打在解压根目录（elysia 等应用局部依赖在 `apps\api\node_modules`），而启动脚本硬编码从 `src\` 子目录找源码，全新解压后找不到就现场克隆上游最新版运行——克隆副本从未安装过依赖（安装步骤跑在包根、被随包依赖"无变化"校验跳过），向上也解析不到包根的局部依赖，首启必然报错。现启动脚本优先直接运行包内自带源码（打包时已应用超时补丁、依赖布局正确、完全离线）；克隆路径仅作兜底，且依赖安装改在所运行源码目录内执行、仅缺依赖时才安装（zip 出厂已带齐依赖则不重装，避免 bat 每次启动触发 bun 把 hoisted 布局重构回 isolated 链接模式）

- **议题 #91 亚马逊刮削时整体失败（亚马逊高清封面获取）**：日志显示 `TypeError: create_candidate() missing 1 required keyword-only argument: 'detail_url'`——抓取亚马逊任一影片的高清封面时，一处代码路径（搜索候选新建分支）在模块重构中被漏传 `detail_url` 参数，与该参数后来的「必填」签名不匹配，刮削走到这条路径时整体中断。已直接补传参数并新增同分支回归测试，亚马逊封面获取恢复正常
- **议题 #86 主界面放大后左侧状态区滞留中部**：主界面左侧导航栏底部的「正常模式/字段优先/配置文件/当前版本/点击检查最新版本」状态块与角落数字浮标原本按设计尺寸固定坐标，窗口拉高（如最大化）后滞留在侧栏上半部、下方露出大片空白。现随窗口底部同步下移贴底，放大后状态块与数字浮标紧贴侧栏底部，侧栏背景色一并铺满整列
- **议题 #84 单数字前缀番号被误剥（3DSVR 搜成 DSVR）**：刮削 `3DSVR-1234` 这类「单数字 + 字母厂牌」番号时，归一化规则把前导的 `3` 当成可剥离的数字前缀丢掉了，实际按 `DSVR-1234` 搜索导致搜不到或误配。已让该形态保留前导单数字（`3DSVR`、`7PPP` 等），同时把 DMM 预约版 `9` 前缀的剥离规则扩展到带横杠写法（`9SSIS-001`），两者不再互相误伤
- **议题 #87 演员管理「数据源测试」弹 Python-CFFI error**：点「数据源测试」时后台线程自建一次性事件循环并复用共享 curl_cffi 网络客户端，线程结束关闭循环后 curl 的内部定时器仍触发，抛 `Event loop is closed`，Windows 上弹出 CFFI 错误框。现改为走全局后台执行器（与「获取演员列表/同步」同款持久循环），弹窗根除
- **议题 #88 演员管理日志位置与命名 / Emby 同步 400 排查**：①演员管理器日志原本单独塞在 `userdata/logs/actor_manager.log`（历次会话追加同名文件），现与主程序日志同目录（`Log/`）并按打开时刻加时间戳命名（如 `2026-09-07-05-13-17 actor_manager.log`）；②Emby 演员信息同步偶发 `HTTP 400` 时，此前错误信息只有状态码、丢掉了服务器返回的校验错误详情，无从定位。现 4xx/5xx 响应会在错误信息里附带截断的响应体（保留 `HTTP {状态码}` 前缀，兼容既有失败分类），便于回报真实校验错误
- **议题 #90 站点未收录不再永久跳过（逐字段重试）**：刮削按字段合并按站点优先级取数时，某站点「连通但没收录该条目」（请求成功、无数据）会被当成站点故障记入失败集，后续所有字段都不再访问它——导致「A 站拿演员、B 站拿介绍、再回 A 站」这类跨字段穿梭被一刀切断。现只有真正的站点级故障（请求超时/请求异常）才跳过该站；「未收录」保留供后续字段重试，准确度优先
- **议题 #92 字母+数字系列番号误识别（T38-041 → 38-041）**：刮削 `T38-041` 这类「单个字母 + 数字厂牌」番号时，归一化误把前导字母 `T` 丢掉、按 `38-041` 搜索导致搜不到。现保留完整前缀（`T38-041`、`MIDA`/`MIDV` 等不受影响），纯数字番号（1pondo/10musume 等）识别保持不变
- **命名模板超宽智能缩短的三次修补（#93 / #95 目录 / #95 文件名，合并为一条；同一模板例 `{{ series }}/{{ actor }}/[{{ release }}]{{ number }}~{{ title }}`）**：
  - ①**#93 目录名/文件名超长缩短误删演员目录**：按固定优先级逐字段截断，但 `actor` 排在 `series` 之前、且无分隔符的单个演员值会被 `_clip_list` 直接清空——导致系列名很长时反而把 `{{ actor }}` 一级目录删掉，简介/原标题等模板里根本没用的字段还被列进「已智能缩短」日志误导排查。修法：描述性长字段（系列/片商/发行商/标题等）提到前、`actor`/`all_actor` 随 `number` 一起放到最后缩短；无分隔符的单演员值改为按字符截断（不再整段清空丢目录）；且只对模板实际用到的字段做缩短，日志不再误报模板外字段
  - ②**#95 目录缩短误伤系列目录（同系列被分到不同文件夹）**：`series` 排在 `title` 之后、`studio/publisher/director` 之前参与截断。当「除标题外的模板前缀」本身已超最大长度时，标题被整段清空、剩余溢出量直接从 `series` 尾部啃掉；而**啃掉多少取决于该文件其它字段（演员/片商/导演等）的长度**——同系列的两个文件因此得到不同的 `series` 一级目录名（实测 MIDA-209 恰好比 MIDV-757 多截 1 个字符，结尾「。」被吃掉，两部片子落到不同系列文件夹）。修法：目录级字段（模板里构成路径一级的 series/actor 等）改为按「稳定预算」截断，预算只取决于模板结构与最大长度、**与同批次其它文件的字段长度无关**，同一 series/actor 值恒定截成同一目录名；目录级字段只按稳定预算截断、不再参与溢出量分摊。设置页「目录名最大长度」说明文案同步补充该行为
  - **①②两条的共性教训**：缩短策略的截断顺序与「谁承担溢出量」必须与**同批次其它文件无关**，否则同一逻辑值会落进不同目录——这是比「截断顺序」更根本的一层
- **议题 #94 欧美（ThePornDB）单文件「填网址刮削」取不到数据**：单文件模式的输入（选中文件 / 指定网址 / 指定网站）写在共享 `Flags` 上，而刮削入口 `Flags.reset()` 在开跑前把它们连同运行态一起清空，真正执行时 `appoint_url` 与单文件路径已变空，「填网址刮削」永远取不到网址（欧美等所有站点单文件模式同受影响）。现 reset 前快照、reset 后恢复这三项单文件输入，其余运行态照常清空。另：ThePornDB 接口当前对未带 Token 的请求一律返回 401（#81 里「slug 端点免 Token」的前提已失效），欧美刮削需配置有效 API Token；若配了 Token 仍刮不到，请附日志中 ThePornDB 请求的 URL 与返回码、以及「检测网络」里 ThePornDB Token 项的校验结果

- **议题 #95 文件名带标题时 T38-041 识别失败并跳过 avbase**：`T38-041` 这类「单个字母 + 两位数字厂牌」番号，在 #92 的修复里只在文件名恰好就等于番号时碰巧正确（靠兜底分支整段返回）。文件名带后续日文标题时，所有正则都不命中，兜底把清洗后的整个文件名当成番号 → avbase 搜索失败 → avbase/thejavdb_api 被判「已失败」跳过（实测 `T38-041__田舎に帰省した...` 显示 `[number]` 为整段文件名）。现新增「单字母 + 两位数字厂牌」匹配分支并收窄头数字长度，避开 `H264-1080`/`x264-10` 一类编码串误伤；带标题文件名可正确提取 `T38-041`

## v2.0.8 (2026-09-06)

### 修复

- **默认代理列表 seesaawiki.jp 拼写错误**：默认配置误写为 `seesawiki.jp`（少一个 a），与 mywife 爬虫实际请求域名不符，该默认项自始不生效；新装/重置配置已修正，存量配置自动迁移修正。「走代理网站」使用说明同步补全 7mmtv 双域名，并说明可直接填数据源名（站点及其镜像整体走代理）
- **发版后验证性修复：设置页最大化三件事**（同源修复，对应 Windows 原生边框下未勾选「隐藏边框」的场景）：①软件设置页的内容拉宽不齐——除「刮削目录」外，其它 tab 的 groupBox 在最大化后只拉伸到 860 设计宽就停（右侧大片空白，同页内「多线程刮削」拉满而「刮削模式」停在半截）——根因是设计器在 34 处 groupBox 上遗留了 860 的宽度上限，`setGeometry` 被它静默夹断；上游代表「刮削目录」页没有此上限所以一直正常。修复是从 .ui 删除全部 34 处上限；②浮框文字「当前配置:」悬空——浮框组 6 个控件里有 5 个已被贴底同步，唯独「当前配置:」标签被漏同步，最大化后悬停在内容中部；已随浮框带一起锚定贴底；③设置页内容滚动到底时最后一行文字从底部浮框带后透出——内容底部余量 60px 不足以避开浮框带的 63px 侵入，且 layout 驱动页（NFO）从未加余量。现余量提到 72px 且两种内容分支统一处理
- **议题 #83 「走代理网站」下拉框按数据源名称选择，但部分站点仍直连**：代理路由原来按实际请求域名匹配，数据源名称到域名的映射只靠静态表 + 六个常用后缀兜底，`.ai/.ws/.app/.cc/.sx/.club` 等域名和完全不同的镜像域名（如 7mmtv 的 7tv022.com、javlibrary 的 f101w.com）全部匹配失败——UI 里明明选了走代理，实际请求仍直连。修复后代理路由直接读取各爬虫自己声明的权威域名（默认主域 + 镜像列表 + 用户自定义站点 URL，javlibrary 另含动态学习的最新直连地址），站点换域名时代码更新即自动跟随
- **议题 #82 原生边框下三处窗口/布局问题**（报告人未勾选「隐藏边框」，此前最大化相关修复主要在无边框路径验证）：①主窗最小化到托盘期间，任何配置保存/加载（如刮削完成后的自动保存）都会把主窗强制弹出激活——配置保存/加载末尾的「还原窗口+激活」现只在主窗可见时执行，最小化期间主窗保持安静；②软件界面最大化后「时长」字段错位滞留原位（下半区右列平移清单漏了时长行，系列/发行正常、唯独时长没跟上），已补齐；③软件设置/软件工具/信息管理最大化后再还原，内容右缘被裁剪、信息管理「保存 NFO」按钮消失——根因是滚动区宽幅容器最大化时拉宽后还原不缩回、内容最小尺寸被最大化期间的膨胀值锁死；现几何伸缩双向幂等、内容最小尺寸按设计基准计算，最大化→还原后与全新打开完全一致
- **fanart 变临时文件且假报成功**（用户实测：正常刮削完成但只剩 `.fanart.jpg.xxx.tmp`，无 fanart.jpg）：thumb 复制为 fanart 时改名步骤被 Windows 瞬时占用挡下（杀软扫描/缩略图索引），复制失败——旧代码不查复制结果照打「Fanart done!」成功日志，表现为「一切正常但 fanart 缺失」。修复三层：①复制失败真实报错（不再假成功，两条复制路径同修）；②改名被挡自动重试 3 次（秒级占用自愈）；③每次刮削结束自动清理孤儿临时文件（形态精确匹配，不误删正常文件，清理结果进日志）。深度复现用户同盘再现：新增第四层——Z 盘等网络映射盘上 `os.path.samefile` 假阳性（会把 thumb.jpg 与 .fanart.jpg.xxx.tmp `判成同一文件抛 SameFileError），复制改用字节流 `shutil.copyfileobj` 绕开该判定，彻底免疫。
- **议题 #79 演员管理器与主窗状态互相干扰**（主窗最小化后演员管理器最大化/展示会把主窗也拉起）：根因是工具按钮槽函数里的 `raise_()` + `activateWindow()` 在 Windows 原生边框下会联动恢复最小化的主窗。改为只在主窗可见时提前台，主窗最小化时仅恢复对话框自身状态，两个窗口的展示/最小化/最大化状态完全独立
- **议题 #78 信息管理（NFO 库管理）页最大化布局三问题**：①最大化后表单右侧残留约 194px 空白（布局在休眠页 resize 时态下不激活，现 resize 时同步 invalidate+activate）；②最大化后再最小化「保存当前 NFO」消失（简介/标签多行框超视口挤压保存按钮，现将这两个多行框高度压至 60px——用户理性建议方向一致：配合垂直间距 4px 求得，保存按钮永远落在视口内、无需滚动）；③「下拉栏」纵向滚动条一并消除。简介/标签现压缩到与小字段同列，不再侵占整窗滚动高度
- **议题 #81 欧美 theporndb 指定网址刮不出（未配置 Token 场景）**：爬虫 `_headers()` 此前在任何入口都先校验 Token，未配置直接拒发请求——即便用户明确给了网址；而 ThePornDB 的公开 slug 端点（`/scenes/{slug}`）本身不需要 Bearer 认证。修复后 appoint_url 场景改用公开端点；未配 Token 时的「直接刮削」仍会提示需 Token（行为不变）
- **议题 #77 检测网络多处误报与引导不足**：①airav_cc/javdb/javbus 搜索探测误报（检测把带探测路径的 URL 当爬虫主站地址拼出畸形搜索链接，例如 airav_cc 出现 `/playon.aspx?hid=44733/cn/search_result` 的错乱拼接），现探测一律还原回域名；②已配置「外部 CF 服务」但检测页 CF Bypass 仍显示「未配置」，且检测链路不触发 bypass——bypass 判断改为「显式 CF Bypass 地址或外部 CF 服务二选一」；③镜像抽样项（如 xcity·镜像）此前按主站模式做刮削探测，xcity.jp 上并无 /api/search 必然误报——镜像项现只验连通性；④失败/警告提示按根因给出可执行指引：Cloudflare 拦截（提示配置外部 CF 服务）/ 节点出口 IP 被封（换节点）/ TLS 握手中断（换节点）/ DNS 等，检测总结末尾附按根因分组的计数

### 优化

- **全量检查提速 3 倍（146s → 45s）**：①javdb_app 测试 patch 反爬节流的随机 3-8s 真实等待（单条 40s → 0.5s）；②爬虫测试默认断网 check_url（DMM 图床升级链此前逐候选真实联网超时，15+ 条用例各拖 3.6s 且随网络环境抖动）——显式 mock 的测试不受影响，真网络验证走 network marker；③UI 几何测试归一：纯文本哨兵 test_ui_resize_sync（被行为测试完全覆盖）删除，最大化内容跟随用例并入窗口状态矩阵（115 → 113 个测试文件）
- **xcity 爬虫新增 HTML 备用刮削路径**：原 xcity 仅经 tc.xcity.jp 的 JSON API 刮削；主站挂掉时此前轮换到 xcity.jp 也无意义（该站无 /api/search）。现发现 xcity.jp 有完整 HTML 刮削路径（`/result/?q=` 搜索 + `/avod/detail/?id=` 详情页），已按双链路接入——主用 tc API（可拿中文翻译标题），TC 不可用时自动切 HTML 路径（此时标题为日文原标题）；中文与日本内容、爬虫注释均已说明

## v2.0.7 (2026-09-05)

### 修复

- **三页内容最大化后横向不跟随**（软件界面/软件工具/软件设置，Windows 原生边框与隐藏边框均受影响）：软件界面页 48 个绝对定位组件此前无任何缩放逻辑——宽幅控件（文件路径、分隔线）现拉伸贴右缘、右缘列（开始按钮/结果树/清空按钮）锚定右缘平移；工具/设置页滚动区视口虽跟随但内部宽幅表单组永远停在 860 设计宽、右侧大片留白——现于滚动区登记设计几何并随视口拉伸宽幅表单组（窄表单项保持原位，NFO 库窄表单自动跳过）
- **隐藏导航入口后的间隙不齐 + 导航按钮改名（#72 / #74 / #76 合并为一条）**：
  - **间隙问题的两轮定位**：#72 首轮症状是隐藏「演员管理」「信息管理」后按钮间残留 16px 空洞且间距不一致（按钮间的**固定 spacer 不受隐藏开关控制**），改为布局统一间距、隐藏后剩余按钮间距自动恢复一致；#74 是二轮——按「spacer 残留」的思路修完间隙**仍摊大**（实测 8→22px），实锤根因是**导航容器的 layoutWidget 固定 380px 高而 `QVBoxLayout` 缺少底部 Expanding spacer**，隐藏按钮后多余空间被摊进可见按钮间隙。最终修法：导航布局末尾加 Expanding spacer 吸收多余空间，隐藏后按钮保持紧凑的 8px 间距；新增 `test_nav_gap_uniform_when_entries_hidden` 实测锁定（show 后断言按钮间隙等于 spacing）。**教训：固定高度容器 + 无底部 Expanding 项时，隐藏子项必然把余量摊进可见项间隙**
  - **导航改名的两半**：#76 改「主界面」→「软件界面」、「日志」→「软件日志」、「工具」→「软件工具」、「设置」→「软件设置」；#72 改「Emby演员管理」→「演员管理」、「NFO库管理」→「信息管理」——同一次改名的六个按钮被拆在两条里。配套：使用指南与快速上手文档同步；弹窗指引、错误提示等全部用户可见文案中的旧导航名同步统一（如「到设置-下载勾选…」→「软件设置」）
- **刮削速度退化的三层修复**①curl_cffi ctype 竞态 TypeError 一律重试，每次多耗 0.6-1.2s，逢库必中；现识别后不再重试。②前置学习表 CID 污染：mono/movie/adult 路径的老片前缀前缀（如 77ssis、88ssis）被错误归纳应用到新片，搜教程学习只有 digital/video 路径写入 `dmm_prefix_learned.json`。③路由表死链批量清理：libredmm 3745 个系列实测后确认 89.4%（3260）的纯 mono pad-3 组合返回占位图（已下架老物），不再可用——全部清理（删 2291 个系列、4501 个污染组合），用户可删除 `userdata/dmm_prefix_learned.json` 后立即见效
- **议题 #73 检测网络页中途异常中断**：检测跑到中途弹出「网络检测出现异常：」（空消息）后整轮停止，后续站点不再检测。根因有两层：① 主循环对单项任务的逃逸异常（如空消息的裸 TimeoutError）没有兜底；② 初次修复中对 CancelledError 的错误穿透——单个任务内部协程被底层取消后，冒泡到主循环又触发整轮终止。修复：主循环对所有异常统一软着陆，单项失败/取消各归该项不再炸整轮，异常携带类型名与 traceback「复制结果」可直接回传定位；空消息异常不再空白。启动自检开头另加范围说明（自检固定四项，全量检测请到「检测网络」页）
- **议题 #71 左侧导航入口可隐藏**：「设置 → 高级」新增「隐藏入口」开关，勾选后左侧导航对应入口即刻隐藏，取消勾选即恢复，保存后立即生效。仅隐藏入口，功能本身完整保留
- **议题 #69 恢复系统最大化按钮 + 修复「不能切换配置」**：① 恢复主窗口最大化按钮（#62/#66/#68 的最大化布局错乱根因已修，无需再禁用）；② 含旧配置键（如 `amazon_strict_pic_verify`）的配置迁移时，迁移警告被误判为校验失败，配置被误指 `_failed.json` 表现为"不能切换配置"——迁移警告与真校验错误分离标记，旧配置切换恢复正常
- **议题 #67 检测网络页按钮悬浮遮挡日志**：日志文本区下移避开顶部按钮；删除与设置页重复的「打开网络设置」按钮；「重试失败项」按钮缩放后不再散开
- **议题 #68 Windows 原生边框下缩放/切页布局错乱**：先缩放窗口再切页时，休眠页组件全部停留在设计尺寸（日志页大片空白、按钮飘出页面）。切页与缩放统一同步，所有页面跟随窗口尺寸
- **议题 #61 Emby 演员管理器与 NFO 管理体验**：演员管理器单例化（重复点击还原已有窗口，不再多开互相干扰）、独立顶层窗口（最小化进任务栏、最大化不再带出主窗口）；NFO 管理加「全选/全不选」按钮、长文本不再把保存按钮挤出可视区、禁用横向滚动条
- **议题 #32 Jellyfin/Emby 演员刮取系列修复**（真机验证四轮反馈）：Jellyfin 10.11+ 连接失败（补全 MediaBrowser 设备标识头）；Jellyfin 12 演员列表 401/超时（列表端点改走 `/Items`）；大媒体库统计超时只认到单库（`Limit=100000` 全量拉取改 500 条分页，单库失败只跳过不阻断）
- **议题 #56 Emby/Jellyfin 演员信息更新与图片上传失败**（Emby 4.9.5.0 真机）：401（Emby 分支鉴权头被条件分支置空）、400（POST 缺 Content-Type）、500（图片上传须 Base64 编码 body 而非原始二进制）三处修复
- **议题 #57 NFO 库管理三个症状**：保存后表单外字段不再丢失（从原数据继承）；简介只存 originalplot 时可正常读取；标签保存后顺序不再被重排；批量保存路径防御对齐
- **议题 #62 / #66 窗口最大化后内容不跟随缩放**：`_sync_page_layouts()` 统一同步绝对定位组件与非当前标签页，最大化/拖拽缩放后所有页面与 12 个设置 tab 正确跟随
- **议题 #55 保存设置/停止刮削后内存占满卡死**：停止刮削会误取消网络栈租约释放任务，租约永不归零导致保存设置时旧网络栈无限轮询累积。释放走关键任务通道不被取消 + 关闭轮询加 300 秒超时兜底；配置迁移补齐 2026-08 精简的 15 个旧站点值清洗（旧配置残留会整体校验失败表现为"保存不生效"）
- **议题 #53 整理模式演员名不映射中文**：演员/标签/系列映射服务于命名变量而非仅服务 NFO，与 update_nfo 解耦——整理模式下 `{actor}/{tag}/{series}` 等命名变量输出中文名
- **全库审查 26 项缺陷修复**（两批，全部先复现验证再修）：**数据正确性**：v1 旧配置迁移崩溃（自定义站点键致整个应用启动失败且原配置丢失）、无码番号前缀丢弃误路由（`1pondo-072625_101` 被错误刮成 pacopacomama 的数据）、`fill_missing_only` 语义反转（实为"本地覆盖新数据"，修正为仅填补空字段）、空番号共享缓存串味（指定 URL 重刮第二个文件张冠李戴）、FC2 搜索兜底归一不对称。**可靠性**：流式请求 CF 挑战页判定失效、av-wiki 空响应打穿整片刮削、失败原因被正常日志稀释、extrafanart 部分失败静默吞、`file_done_dic` 六处锁外竞态、保存设置非法输入半写状态（清空输入框点保存不再残留半套配置）、≥24h 定时间隔保存归零、ASIN 数据库非原子保存（进程中断不再损坏用户库）与并发写互斥、断点缓存 commit 失败无 rollback、mosaic 采信非确定性（重刮归类翻转）、missav 截断 FC2 长 ID（7 位数番号）、Emby 分页大库漏页、`_failed.json` 保护分支永久劫持原配置、FILL 合并 number 死代码清理
- **五项数据丢失/性能缺陷**：同路径移动删源（更新模式扫已整理目录会把源影片删成死链）；同名静默覆盖（移动目标已存在时先保留旧文件为 `_conflict` 副本）；流式响应关闭退化成全量下载（提前放弃的 4MB 响应不再拉满整图）；NFO 评分恒为 0.0（真实评分被空对象默认值丢弃）；并发建目录竞态（批量 extrafanart 下载不再偶发 FileExistsError）
- **失败列表跨影片错误污染**：并发刮削的失败原因互相混入且日志缓冲随刮削量无界增长——按任务树归因隔离，失败列表只含本影片错误
- **LogBuffer 内存泄漏**：兄弟任务 buffer 残留整树回收
- **网络检测多项修复**：搜索解析无结果的爬虫自动回退真实刮削路径探测消除误报；missav_api 检测改走真实搜索；dmm_api 检测补全必需参数；javlibrary 自定义 URL 不再强制直连阻断 CF Bypass；探测失败提示携带实际番号
- **DMM 图占位图误判**：DMM 图床对无效对象返回 200+小体积垃圾体，此前被当真实封面入库——低于 4KB 直接判失败
- **official 无码官网 studio 字段污染**：1pondo/10musume/pacopacomama 的 UCNAME 键实为分类标签，误作厂牌产出脏值——归正为 Maker/Studio 取值，UCNAME 归入标签
- **Dependabot 安全警报 3 项**（tornado 6.5.7 → 6.5.8）：均为 dev 依赖组 Jupyter 工具链传递依赖，生产无影响；升级后 OSV 复扫 123 个锁定依赖 0 已知漏洞
- **CI Windows charmap 崩溃**：测试脚本读源文件补 `encoding="utf-8"`

### 功能

- **新增 7mmtv 聚合站爬虫**（移植自 Hazard804/mdcx）：7mmtv.sx 有码/无码/素人/FC2 剧照与元数据刮削，加入有码/无码/素人/FC2 四个默认源列表；HEYZO 剧照场景适用。双镜像域名轮询（7mmtv.sx → 7tv022.com 失败自动切换），两域名默认加入「走代理网站」列表（老配置需在设置→网络手动补充）；旧配置中残留的 7mmtv 站点值自动恢复有效。打包构建显式收录该动态注册模块（防 PyInstaller 静态分析漏收导致打包版刮削崩溃，附一致性哨兵测试）
- **新增三个爬虫**：javfree（javfree.me 有码/无码/FC2，默认加入有码+FC2 源）；aventertainments（无码 DVD+PPV，覆盖 caribbeancom/1pondo 两厂牌）；madou_club（麻豆系国产番号）
- **精简 15 个冗余/失效爬虫**：失效站与需外部 CF Bypass 服务站移除，数据重复站被 DMM 系覆盖；注册爬虫 48 → 33；旧配置中的已删站点自动跳过
- **JavDB 全系图源无水印升级**：App 专用 CDN 加密流（单字节 XOR）解密后为无水印原图，网页版带水印 URL 自动升级到无水印变体、失败回退；中段路径变更由响应学习自愈
- **无码官网五站接入默认代理列表**（caribbeancom/heyzo/1pondo/pacopacomama/10musume 及 mywife 实测需代理）

### 优化

- **DMM 直构静态路由种子 v2**：libredmm 全站 58.9 万「番号↔cid」对归纳为离线路由表（随包分发），路由命中的系列首候选直达真实 cid、全链路零额外请求；append 分级模式保高频系列候选顺序零污染、老片 3 位 cid 兜底
- **ASIN 数据库读零校验**：库命中直接采信高清封面不再逐次软校验（省每片 1-2 次参考图下载）；新发现 ASIN 入库走 v2 三步证据链（cid 旁证→标题门含合集词一票否决→图像兜底），错配从源头拦截；特典/限定版同番号让位规则（正品替换特典）
- **ASIN 数据库性能**：查询全量解析 4 万行 xlsx（2.2 秒/次）改内存双索引（0.08ms，约 3 万倍加速）；出厂库扩容 26620 行（四源校验工程全量净化，同番号 ASIN 唯一），合并升级为"出厂库权威"覆盖纠正历史错挂；ASIN 缓存命中优先走 tenhow 免代理图床直连下图；软校验参考图缺失时按番号直构 DMM 官方图兜底
- **刮削失败原因 Top N 摘要**：大批量刮削结束输出按类别聚合的摘要行（如"请求超时 23 个｜站点未收录 15 个"）+ 每类可操作建议，不用逐条翻几十条失败日志
- **刮削进度预计剩余时间**：状态栏显示"已刮削 320/5000 · 剩余约 2 小时 15 分"（滑动窗口速率估算，样本不足不出估算）
- **LLM 翻译同批次缓存**：系列片/失败列表重刮的相同文本直接复用译文（并发相同请求合并为一次调用），显著省 token；缓存绑定 LLM 配置指纹，切换模型自动失效
- **DMM 高清直链升级推广到 11 个聚合站爬虫**：airav_cc/avbase/avsex/freejavbt/iqqtv/javday/javfree/lulubar/missav_api/thejavdb_api/xcity——其中多数爬虫首次获得竖版高清海报
- **字段来源日志降噪**：同一失败站点的跳过标记单文件内重复 20+ 次（占日志 17%），改站点级去重降噪 99%，信息无损
- **javdb_app 签名失效 fail-fast 诊断**：签名常量轮换时给出明确诊断与三个环境变量免改码覆盖出口；搜索补 `type=movie` 与 `limit=50`（超限静默截断）
- **检测网络页**：结果按状态着色；三站点下拉框显示最近实测状态圆点（tooltip 附检测时间与路由）；检测进度实时显示 `done/total`；复制结果自动附带脱敏诊断头；401/403/429 文案拆分具体动作引导；站点选择列表标注「日本IP限定/勿用日本节点」
- **「全部走代理」开关**（默认关）：所有请求交代理软件分流裁决，「走代理网站」列表不再生效
- **LLM 翻译关闭思考模式**（#54）：按服务商自动下发关闭参数（硅基流动/百炼/火山方舟/Ollama/Gemini），参数不兼容自动去参重试
- **madouqu 动态域名**：接入官方发布页实时解析（24h 缓存+静态回退），搜索失败自动切换镜像
- **站点级 CF 指纹池扩充**：lulubar 与 missav 全镜像专属指纹池，重试轮换排除失败指纹
- **其他**：高分屏非整数倍缩放默认启用（125%/150% 不再模糊）；有限收录站点用各站实测番号探测消除误报；Emby 演员管理器可最大化拖拽缩放（初始尺寸适配屏幕 80%）；javbus 镜像池清理失效镜像；getchu_dmm 合并进 getchu；r18dev 解析兼容 parsel JSON 三态；「成功后不移动文件」时不创建视频目录

### 文档

- 文档与 UI 文案全面对齐代码（注册爬虫数/命名变量表/代理域名列表/演员库列/Tab 名称/release 产物名等 20+ 处）；README Telegram 群地址更新；「跳过前置 Poster 校验」说明对齐实际三分支；使用说明内容全面更新

### 工程

- **修复打包脚本 Windows runner 因 GBK 解码崩溃**：`build.py::_run_command` 的 `subprocess.run(text=True)` 未显式指定编码，Windows 默认 GBK/charmap 解码 PyInstaller 输出时含 UTF-8 字节即 `UnicodeDecodeError`，首轮 release 构建直接失败。补 `encoding="utf-8", errors="replace"`，新增哨兵测试锁定

## v2.0.6 (2026-08-23)

### 功能

- **NFO 库管理页面**：左侧导航新增「NFO库管理」，目录 `.nfo` 批量编辑（15 字段）+ 字段级 diff 预览 + 批量操作（替换演员/加删标签/统一系列）+ 右键重新刮削/打开目录/删除
- **字段级跳过抓取**：字段优先级对话框每字段可勾选「跳过」，该字段不从任何来源抓取
- **NFO 合并策略（5 种）**：写入前按策略（prefer_scraper/prefer_nfo/merge_arrays/keep_existing/fill_missing_only）与现有 NFO 合并，关键字段双重保护
- **爬虫镜像/域名轮询**：新增通用 DomainRotator，javbus（12 镜像）/freejavbt/7mmtv/xcity/IQQTV/missav（3 域名）请求失败自动切换；javlibrary 动态获取最新直连地址
- **avmoo/avheat 新增爬虫 + avsox 改 API**：三站同属 tellme.pw AIO 平台（Vue SPA + JSON API），新增共享基类 AioSiteCrawler 统一封装；tellme.pw 动态地址统一获取
- **dmm_api 换 DMM 官方 Affiliate API + 新增 thejavdb_api**：dmm_api 由 JavDB 第三方 API 换为官方 API（老配置零迁移）；原 JavDB API 独立为 thejavdb_api 爬虫（默认未启用）
- **MGStage 官方图源直构双兜底**：站点图源全失败时按番号直构 MGStage 官方 CDN 高清图（`pb_e` 横版作封面、`pf_e` 竖版作海报，系列映射表实测 8 系列），补 DMM 不收录的素人番号
- **JavLibrary CF bypass + DMM 高清升级 + xpath 兼容**：新增 Selenium+Edge headless 过 CF JS 挑战（可选依赖自动安装）；刮削后自动升级 DMM 高清封面；xpath 兼容 Selenium tbody
- **TRAWL/FlareSolverr 外部 CF 服务适配层**：适配层暴露 cookies/mirror/html 端点统一调用 TRAWL `/scrape` 或 FlareSolverr `/v1`；便携版内置 Redis 并自动跟随上游版本
- **移除内置 CF Bypass 服务**：删除 cloakbrowser + cf_bypasser 内置服务，过 CF 统一走外部服务，打包体积与内存显著减小
- **演员库增强**：JavDB 中文名补全（免 TMDB Key）、补全别名新增 JavDB 数据源（NFKC 归一化 + 繁简转换 + 异体字统一）、cleanup_aliases 别名清洗、剔除男优支持别名匹配
- **检查演员缺失番号多数据源重写**：按演员类型分四路数据源（有码 libredmm / 无码 avsox / 欧美 avheat / 国产 iqqtv），支持括号标注类型
- **站点定位说明**：全部爬虫新增 description 定位说明，站点列表悬停展示 tooltip
- **图片下载大小上限**：图片链路统一 50MB 上限，防异常大文件拖死磁盘

### 重构

- **爬虫文件去 `_new` 后缀**：`dmm_new`→`dmm`、`javdb_new`→`javdb`、`avbase_new`→`avbase`；JavDB App 类名统一
- **JavDB App 签名简化 + 设备参数补全**：硬编码已验证签名常量，补全设备标识参数降低风控概率
- **移植 sakuramediabe 4 项改进**：番号清洗去域名干扰、jsdelivr CDN 加速、NFKC 归一化匹配、stale 缓存降级
- **Emby 演员管理器入口移到左侧导航**
- **Amazon 标题匹配函数抽为模块级**（`core/amazon_match.py`，可被批量采集脚本复用）

### 修复

- **Windows CI 离线测试全量适配（30 项）**：硬编码 `/tmp` 路径改 `tempfile.gettempdir()`（脚本+测试）；AST exec 补 `Path` 到 globals；`.read_text()` 统一加 `encoding="utf-8"`（Windows cp1252 解码失败）；`read_link_sync` 剥离 `\\?\` 长路径前缀（含环检测 early return）；pyuic6 产物与仓库版两边做相同路径分隔符归一化
- **主窗口启动崩溃修复**：NFO 库页三栏布局用了 PyQt5 才有的 `QLayout.setStretchFactor(index, stretch)`，PyQt6 严格重载下启动即抛 TypeError（Windows 打包版首发暴露）；改用 `QBoxLayout.setStretch(index, stretch)`
- **设置页与工具页滚动修复**：新增 `CustomScrollArea`，在 `widgetResizable=true` 下按绝对定位子控件包围盒同步内容最小宽高，恢复设置页、工具页和 NFO 编辑页的滚动；NFO 设置页宽度统一为 701，修复右侧 94px 截断；NFO 编辑器修复内容宽度被压缩到 98px 的问题
- **设置页底部留白修复**：滚动内容底部安全余量从 20px 提高到 60px，避免最后一行文字或控件贴近边框后在字体基线、滚动条和 DPI 缩放下显示不全
- **NFO 库管理三栏修复**：移除中间 NFO 表单滚动区的 380px 最小宽度约束，使左侧列表、中间表单和右侧海报/缩略图预览在 800px 内容区内不重叠，保存当前 NFO 按钮不再被右侧预览遮挡
- **NFO 库管理批量提示修复**：提高左侧“批量保存”下方换行提示的最小高度，避免 Windows 字体和 DPI 缩放下文字底部显示不全
- **全模块审查修复（35 项）**：数据损坏级 6 项（翻译映射清空/简繁失效/tmdbid 错配/迁移丢图/同路径误删/字符清洗）、功能失效级 7 项（断点续刮/间歇刮削/共享番号/数据源/wiki/minnano/相似自推荐）、性能健壮性与并发安全 22 项
- **Emby 演员管理器 15 项修复/优化 + 窗口遮挡（issue #38）**：连接/同步/上传/缓存/背景图/过滤器/详情 TTL 等；模态改非模态 + 后台执行
- **全页面 UI 布局批量修复**：13 个滚动区 widgetResizable→true（高 DPI 横向裁切）、33 个 GroupBox 限宽 739→860、60 个长文本 QLabel 补 wordWrap；NFO 设置页 26 个超长 CheckBox 硬截断修复；网络设置说明文字截断/重影修复；配套 check_ui_layout 静态检查纳入 CI，三项清零验证
- **其他 UI 修复**：左侧导航 Emby 按钮（误删信号残留）、演员库维护 group 裁剪、网络设置 group 重影/超时滑块重叠、批量操作面板迁移到 NFO 库页左栏、NFO 库页三栏自适应 + 批量面板默认折叠 + 预览框边框、空列表占位提示、配置项说明补齐、类型刮削说明空白补 colspan
- **网络检测增强 6 项**：代理故障提示、镜像抽样、单厂牌提示、重试失败项/复制结果按钮、DMM 误报修复
- **翻译修复**：Bing 端点改 cn.bing.com（原返回空响应体）；百度翻译 appid/key strip 修复签名错误
- **CLI 修复**：crawl 代理白名单失效、失败退出码、javdb_api 搜索 q 参数丢失
- **爬虫修复**：dmm 双重重试/番号匹配/评分/日期截断、javbus 搜索镜像轮换、minnano 标题校验/缓存 key、MGStage/Jav321/FC2Club/FC2Hub/JavLibrary 字段解析保留引号方括号、FC2Hub 缺失节点容错、FC2 时长/无修正判定、prestige 字段防护、javdb_app year 推导
- **版本检查日志刷屏修复**：失败时不再把整个 GitHub API JSON 倒进日志；改用 releases 列表 API 遍历找纯数字 tag（正确跳过 TRAWL 发布），错误只输出简洁说明。后续该链路又修了「取列表第一条而非最大 tag」与匿名 API 60 次/小时/出口 IP 配额耗尽导致时灵时不灵两个问题，完整不变量见 `docs/Development.md`「版本号管理 → 更新检查（客户端自动更新）」
- **下载/文件修复**：分块下载断点续传（.part + .part.meta）、文件复制原子替换、移动文件拒绝目录目标、图片 50MB 限制与同 URL 并发复用、extrafanart 替换原子化、符号链接解析与跨目录重复跳过、move_file 先删目标、成功列表记录新路径、fanart 失败不再静默
- **崩溃容错**：get_new_release 日期格式、parse_runtime 时长解析、hdouban 秒数、强杀线程单次注入与全局停止超时保护
- **并发/性能**：is_proxy_host O(1) 映射、镜像轮询重试去重、AVdb 并发预热、连接池锁外清理、Flags 重置保持异步锁身份稳定、TMDB 演员库并发写保护、女优信息库加锁
- **Windows 体验**：保存配置黑色控制台窗口（SYSTEM_INFO 替代 platform()）、配置保存拒绝访问多级回退、翻译说明文字重影
- **其他**：DMM 9 前缀番号识别、CF 指纹轮换（safari17_2_ios）、读取模式不受断点缓存干扰、打包 hidden-import 补齐、配置保存竞态/重试链、优雅退出、ComputedLease 非阻塞、UI 与文档一致性（网站数量 48/missav.live/MGStage/thejavdb_api）

### 工程质量

- **CI 双平台门禁**：新增 Windows 离线测试 job；Linux 继续执行完整质量检查，Windows 实际覆盖路径/文件系统条件分支；PyInstaller EXE 由 Release 和手动打包工作流验证（CI 分工与门禁口径见 `docs/Development.md`「测试」）
- **GUI 启动冒烟测试**：offscreen 下完整构造主窗口（setupUi→Init_Singal→Init_Ui→load_config 全链路）与 Emby 演员管理器两个对话框，PyQt6 签名不兼容/属性缺失类问题在 CI 双平台拦截，不再推迟到用户运行时暴露（离屏渲染校验流程见 `docs/Development.md`「代码规范 → 离屏渲染校验流程」）
- **打包与 Release 工作流收口**：Windows 构建显式使用 Release Tag 版本；矩阵构建先上传 artifact，再由串行任务统一创建 Release；Release 权限、Tag 来源、对应版本 checkout 和当前版本 changelog 提取统一校验（发版工作流与护栏见 `docs/Development.md`「构建」）
- **quick-check 快速检查命令 + mypy 类型检查启用修复**（两条合并为一条）：quick-check（ruff + mypy 秒级自检）改用 `sys.executable -m mypy`；重命名与标准库冲突的 types 模块（108 处引用同步改写），mypy 完整检查全部 151 个源文件（ruff / mypy 口径见 `docs/Development.md`「代码规范」）
- **CI/Release 工作流修复**：release.yml tag 触发 `220*`→`2*`（YYYYMMDD tag 不以 220 开头，旧模式永不触发发布）；CI ruff 改 `uv run ruff` 消除版本漂移
- **UI 布局静态检查脚本**：新增 `scripts/check_ui_layout.py`，扫描 `.ui` 中滚动区 widgetResizable、GroupBox 限宽、QLabel wordWrap 等打包后才暴露的隐患（wordWrap 误用 critical 阻断）；纳入 `uv run check` 与 CI
- **跨线程 Qt 安全收口**：提取 `run_in_background` 通用工具 + `check_thread_safety` AST 扫描（0 违规）
- **UI 收口到 .ui + 几何回归测试**：百度翻译/网站优先级/fc2ppvdb Cookie 写进 MDCx.ui（唯一权威源，改 `.ui` 后须 pyuic6 + ruff，不得手改生成的 `.py`）；offscreen 遍历断言无重叠
- **刮削缓存管理 UI**：工具页新增缓存统计/失败列表/导出 CSV/重置/清空（缓存分层约定见 `docs/Development.md`「缓存系统」）
- **死代码清理**：删零调用函数/死变量（avsex get_poster 等）、无引用 ping3 依赖、AVWikiDB 别名查询、文件移动冗余分支、Gfriends 缓存重复写入、CF 后退避死分支、javdb_api 不可达代码
- **回归测试**：新增 review_regressions/save_success_list/UI 几何/avsox 系/Amazon 匹配等多批
- **版本元数据统一**：Python 包版本同步 GUI 展示版本，回归测试防再分裂（五处同步点与改版流程见 `docs/Development.md`「版本号管理」）
- **静态质量收口**：清理 B005/B007/B904 等高价值 Ruff 告警，异常链保留根因，补目录删除安全测试
- **性能优化与启动提速（两条合并为一条）**：PNG 压缩级别 6、convert_half 翻译表、剩余任务快照写盘、水印缓存、asyncio.Event 唤醒、ActressDB 参数化、缓存 WAL+批量提交、内存上限、UA 池更新至 Chrome 115-135；启动侧本地数据库延迟加载（后台线程 + 就绪屏障），启动检查配置目录可写/TMDB Key/代理可达性且不阻塞启动

## v2.0.5 (2026-08-15)

### 功能

- **DMM 高清图识别与去重的三次收紧（三条合并为一条）**：DMM 竖图普遍 <400KB，字节阈值把它误判成「不够清晰」而误走日亚搜索；三次改动逐步把判据从「字节体积」换成「真实分辨率」，并顺带消除重复探测。
  - **① 探测去重**：`upgrade_dmm_cover` 增加进程内 TTL 缓存（按规范化番号，成功缓存高清 URL、失败缓存 None）+ 同事件循环 in-flight 合并，JavBus / JavDB 三站 / R18.dev 等站点并行刮削同一番号时不再对相同 DMM 候选重复探测（未知系列全 404 场景从每站点 ~20 次请求降为全程一次）
  - **② 判据换成分辨率**：`_should_skip_amazon_for_existing_poster` 对 awsimgsrc DMM 高清图改为按分辨率直接放行（宽≥700），同时 `upgrade_dmm_cover` 增加分辨率校验、过滤 147x200 缩略图占位图，避免把海报覆盖成低清缩略图
  - **③ 门槛由 1024 降到 700**：`POSTER_DMM_MIN_WIDTH` 与 `_DMM_HD_MIN_WIDTH` 同步下调，MILK 系列 745x1081 等中尺寸图也能升级为海报并跳过日亚，进一步减少日亚请求；588x800 及 147x200 窄图/缩略图仍被拦截
- **ASIN 数据库写入去重**：`save_asin_to_excel` 写入前按番号去重，同番号已存在时跳过不写，避免重复行
- **ASIN 出厂库的三步落地（三条合并为一条）**：出厂库随版本带新番号，用户库是长期积累的手工数据，两者要合并而不是覆盖；落地分「建合并机制 → 补数据 → 修合并副作用」三步。
  - **① 增量合并机制**：新增 `merge_asin_db_from_backup`（仿演员库，出厂库 md5 标记 `.asin_db_merge_marker` 未变则跳过；按番号并集合并——新增番号追加、已有字段空缺补全，不覆盖用户已填值、不删行），软件更新后老用户启动时自动把出厂库新增/修正数据合并进用户库
  - **② 出厂库更新**：出厂 ASIN 库合并最新数据至 9699 个番号（净新增 4616），按番号（前缀字母 + 数字）排序
  - **③ 修合并副作用**：①合并产生新增行时，旧实现按追加顺序落表导致顺序错乱；现合并后按番号整体重排并重新格式化（重建工作簿避免 `delete_rows` 的 `max_row` 虚高）；纯字段补全不改变行数与顺序，不重排
- **相似片推荐**：新增 `mdcx/core/similar.py`（借鉴 OpenAver 设计）——基于 tag IDF 加权 Jaccard + 系列/片商/年份/时长/演员组合评分 + MMR 重排的本地离线相似算法，零网络零模型；主界面结果树右键「查看相似片推荐」弹出对话框，双击可跳转
- **SQLite 刮削状态缓存（断点续刮）**：新增 `mdcx/core/scrape_cache.py`（标准库 sqlite3 + WAL），持久化每个源文件的刮削状态（done/failed + mtime + 失败计数），实现断点续刮与失败跨会话重试（上限 3 次，成功清零）；数据库损坏自动回退内存模式；重启后自动跳过已完成且未变化的文件、恢复上次失败未超限文件
- **结果摘要缓存**：`scrape_state` 表新增 `summary_json` 列（旧表自动迁移），刮削成功时存储相似推荐所需字段；相似推荐语料 = 历史成功结果（SQLite）+ 当次刮削结果，重启后仍可基于全历史推荐
- **相似推荐特征扩展与召回修复**：结果摘要新增 `mosaic`（有码/无码）、`publisher`（发行商）、`directors`（导演）、`score`（评分）四个特征，算法加分项同步扩展——马赛克类型相同 +0.35 / 不同 -0.30（有码无码不再混淆推荐）、发行商一致 +0.15、导演有交集 +0.15、评分接近 +0.05；同时修复召回缺陷：热门标签（IDF=0）不再被排除出候选召回、只影响精排权重，解决「目标片全是常见标签时完全推荐不出结果」的问题（算法主体见上方「相似片推荐」条）
- **CF Bypass 落地域名白名单**：新增配置 `cf_bypass_trusted_hosts`（逗号分隔，支持 `*.example.com` 子域通配），校验 Bypass 服务落地/重定向后的最终域名，防第三方服务被劫持时把恶意页面当数据；设置页新增「Bypass 白名单」输入框
- **本地 Bypass 服务健康状态机**：新增 `_local_bypass_health`（idle/ready/dead），连续请求失败达阈值（3 次）标记 dead 并解除转发（不再空等假死服务超时），冷却 300s 后自动重试，请求成功自动恢复
- **Emby 演员管理器修复**：修复「连接 Emby」无反应的根因（`ComputedManager` 模块不存在致 ModuleNotFoundError 被静默吞掉）、`_is_jellyfin_server` 恒 False 的判断 bug；修复 `search_actor_info` 键大小写不匹配导致简介/信息抓取完全失效、DELETE 404 被当失败致无头像演员传不上头像；`PreparePreviewThread` 加顶层异常处理并真正 emit error（原 worker 调用不存在的 `self.log` 致线程静默死亡）；并发模型由「10 线程各自 event loop」改为单 loop + `asyncio.Semaphore(10)`；头像/背景上传统一复用 `_upload_actor_photo`；Emby 分支补 `personTypes=Actor` 过滤；`sync_actor` 单演员异常不再中断整批、`update_person_info` 不再用空值覆盖服务器已有字段
- **Emby 演员管理器新功能**：新增「设置」对话框（数据源优先级拖拽排序、演员类型过滤/去重、本地头像目录、Gfriends、使用数据库）；「数据源测试」窗口（按配置优先级逐源验证头像/简介并展示结果，含字段/值信息表与快速设置面板）；演员详情编辑对话框（左栏现有数据、右栏可编辑简介/信息表、快速设置面板、单独同步头像/简介）；快速设置面板（测试/详情窗口内改即自动保存）；「清空缓存文件夹」按钮；底部状态栏（连接/操作状态）；同步完成后 3 秒自动重新获取演员列表
- **Emby 演员管理器健壮性**：头像补全主循环逐演员容错、backdrop 按索引删除、Gfriends commits 解析失败降级、时区偏差修复、缓存文件名防碰撞、`src[jp_name.index()]` 越界防护、按钮状态机修正、Dialog 关闭安全（`closeEvent` 等待线程）、清理死代码（`_avatar_cache`/无效 checkbox/重复 layout 等）
- **爬虫类型分类校准**：按站点性质校准各刮削类型默认网站源——仅能有码（dmm、dmm_api、libredmm、r18dev、avbase、faleno、giga、dahlia、xcity、prestige、mgstage、fantastica、cableav、getchu、getchu_dmm、javlibrary、jav321、freejavbt、lulubar）、无码专属（avsox、kin8）、综合有码+无码（javbus、javdb 系、missav 系、javday、7mmtv、airav_cc、avsex、official、iqqtv）、素人（含 mywife、iqqtv）、FC2（含 javdb 系）、欧美（仅 theporndb）、国产（含 iqqtv、hscangku）；同步默认配置模板与 FEATURES 文档标注；「刮削不到？看这里！」弹窗网站列表改为动态生成（随爬虫注册自动更新）。爬虫框架与站点注册机制见 `docs/Development.md`「爬虫框架」
- **Emby 演员缓存持久化**：演员头像缓存从临时目录（`tempfile.gettempdir()`）改为持久化目录 `userdata/emby_actor_cache/`，与 gfriends.json/minnano_cache.xlsx 一致，重启后可复用缓存避免重复下载

### 修复

- **图片尺寸探测失效**：`_read_stream_size`/`get_imgsize` 对 curl_cffi 同步生成器产出 bytes 误用 `await` 恒抛 TypeError，改为 `aiter_content` 异步迭代；修正测试 mock 与线上行为对齐（此前测试掩盖 bug，Amazon 高清择优/尺寸校验静默失效）
- **GUI 状态卡死**：`_move_file_thread` 移动完成后按钮永久卡禁用（补 `reset_buttons_status` + try/finally）；非刮削状态点「停止演员库维护」后 `signal_qt.stop`/`Flags.stop_requested` 永不复位导致日志静默、下一任务秒停（`_on_actor_db_finished` 复位）
- **停止标志 / 跨线程 Qt**：`_show_version_thread` 移除 worker 线程直接操作 QWidget（`setCursor`/cookie 检查改经 `version_check_done` 信号回主线程）；`network_check` 按钮状态经信号回主线程 + 防重入 + 删重复 setText；`to_cut` 后台线程读 QWidget 改为主线程采集 `mark_list` 传入、`_set_pixmap` 跨线程改 UI 经信号回主线程
- **trailer 旧文件复用**：`deal_old_files` 带文件名时用旧 `file_name` 构造目标路径，与 `trailer_download` 的 `naming_rule` 命名不一致导致旧 trailer 无法复用/孤立文件，新增 `naming_rule` 参数对齐
- **Amazon ASIN 记录丢失**：低清兜底路径 `asyncio.create_task` fire-and-forget（事件循环关闭时 pending task 销毁），改为 `await`
- **爬虫修复**：`get_amazon_data` 删除对恒为 None 的 `html_info` 提取 session 的死逻辑；`get_avsox_domain` 布尔优先级错误（or→and）；`check_url` `max_retries` 1→3 启用真实退避重试；非数字评分 `float()` 崩溃防御；`translate_actor` 空演员名误替换全部演员；missav 冒号格式时长解析（1:30:00）；missav URL slug 非番号格式不覆盖番号；javbus 搜索结果相对路径补全绝对 URL；javdb XPath 作用域逃逸；r18dev dvd_id 补零比较
- **读模式 tmdbid 不落盘**：xlsx 缓存命中 tmdbid 立即回写 `res.actor_tmdb_ids`，修复 `still_missing` 为空时 NFO 缺 tmdbid
- **文件写入原子化**：NFO 与配置保存改为临时文件 + `os.replace` 原子写入（防写入中断损坏），推广到 missing 番号清单、gfriends JSON、actor_db 断点文件、amazon_database 报告等
- **LogBuffer 并发安全**：`write`/`clear` 加锁、`get` 遍历浅拷贝，修复并发 append 时 `list changed size during iteration`
- **死代码清理**：删除 `image.py:get_pixmap`（无调用且读取失败会删除源图）、amazon 4 个未用函数、`parse_fanza_resp`、`save_asin_to_excel` 未实现的 `max_rows` 参数、`query_asin_database` 重复 import 死分支、`Config.from_legacy` `type(timedelta)` 恒 False 等
- **Emby 演员管理器 Event loop is closed**：9 处 `new_event_loop()`+`close()` 改用全局 `executor` 常驻 event loop，避免 curl_cffi AsyncSession 跨 loop 复用报错
- **Emby 演员管理器获取列表无反应**：`QDialogButtonBox.Ok` → `StandardButton.Ok`（PyQt6 6.4+ 扁平枚举已改嵌套）；site_priority_dialog 两处补 `manager.save()` 修复网站优先级拖拽排序后不落盘
- **Emby 演员管理器设置保存不生效**：`EmbyActorSettingsDialog._save` 及两处 `_save_quick_settings` 补 `manager.save()`，修复设置弹窗修改后不写盘
- **Emby 设置弹窗 QListWidget 遍历崩溃**：PyQt6 QListWidget 不可直接 `for item in self.list` 迭代（抛 TypeError），改用 `item(i)` 索引遍历
- **Emby 数据源测试跨线程 UI 崩溃**：`ActorSourceTestDialog` 在后台线程直接操作 QWidget 导致崩溃，改用 `QThread` + 信号回调模式（`ActorSourceTestThread` 发 `result`/`error` 信号回主线程）
- **翻译页 label_60 文字被覆写**：翻译页百度提示文字覆写了 label_60 原有文字导致重影，新建 `label_baidu_hint` 独立显示
- **网络设置 groupBox 重影**：网络设置页 `trusted_hosts` 输入框与超时行 cell 冲突（同一 gridLayout cell 放了两个 widget），`trusted_hosts` 移到 row=10，`groupBox_28` 高度 400→480
- **MDCx.ui 重复 objectName 消除**：4 对重复 objectName（label_81/60/423/424 第二次出现）重命名，消除运行时控件查找歧义
- **label_601 死引用删除**：`main_window.py` 引用不存在的 `label_601`，运行时必崩
- **Courier 字体替换**：117 处 `font:"Courier"` → `font:"Courier New"`，修复中文环境字体名匹配失败导致文字显示为方框

### 工程质量

- **测试增强**：新增 Amazon 跳过逻辑测试（DMM 高清/中尺寸放行、缩略图/窄图拦截、非 DMM 字节阈值保留、Amazon 来源不跳过）；新增 `upgrade_dmm_cover` 缓存行为测试（命中零探测、失败缓存保留原图、并发 in-flight 去重）；更新 JavBus / R18.dev 受影响升级测试
- **ASIN 库测试增强**：新增 4 个测试（同番号去重、批量去重、出厂合并行为、md5 标记跳过）
- **新功能测试增强**：新增相似算法 7 测试、相似对话框 5 测试、`ScrapeStateCache` 15 测试、CF 白名单 6 测试 + 4 集成测试、本地 Bypass 健康状态机 8 测试；修正 `test_media_resource` mock 与线上 curl_cffi 行为对齐
- **打包与 CI 加固**：`build.py` 显式收集 `curl_cffi.libs` 防打包后 TLS 指纹库丢失；`ci.yaml` 补 `check_info_db` 步骤；移除 `libs/` 下 OpenSSL 1.1 死数据；`main.py` stderr 重定向仅 IS_PYINSTALLER 时生效
- **Emby 数据源实现合并**：`emby_actor_manager.py`/`emby_actor_image.py`/`emby_actor_info.py` 三模块间重复的 Gfriends 索引解析、Graphis HTML 解析、信息补全链路合并——`get_gfriends_index` 增强为完整版（版本检测+缓存刷新+展开写回）、抽出 `_parse_graphis_html`/`fill_actor_info_from_sources` 共用函数、`_BIO_TAG_PATTERNS`/`_extract_bio_tags` 统一移至 manager 模块
- **Emby API 共用函数提取**：新建 `emby_shared.py`，移入 5 个共用函数（`_generate_server_url`/`_build_jellyfin_headers`/`_is_jellyfin_server`/`_append_query`/`_upload_actor_photo`），两模块从中导入并 re-export（`# noqa: F401`）保持向后兼容
- **本地头像预扫描索引**：新增 `build_local_avatar_index` 预扫描本地头像目录建立文件名索引，`from_local_avatar` 加 `pre_scanned_index` 参数，N 次逐演员全树遍历降为 1 次预扫描 + N 次字典查找；新增 6 个测试

## v2.0.4 (2026-08-14)

### 功能

- **DMM 官方高清直链**：新增番号→DMM cid 候选构造器 `dmm_direct`（前缀映射表覆盖 110+ 主流系列，含 `h_xxx`/数字特殊前缀与跨厂商附加前缀，用 dmmapi/avbase 实测校准，配套 `dmm-probe` 探测工具）；封面补全所有爬虫失败时走官方直链兜底（竖版 `ps` 高清作海报优先，横版 `pl` 裁剪兜底，无码番号跳过）
- **DMM 高清覆盖九个爬虫**：LibreDMM / R18.dev / JavBus / JavDB 三站 / DMM / DMM API / avbase 刮削时直接把低清/水印图升级为 DMM 官方高清（统一 `upgrade_dmm_cover` + 前缀表候选，check_url 验证，失败回退原图）；开启「Poster 选优」时自动注入 DMM 高清候选按尺寸选优；DMM 图下载失败自动重试一次
- **同番号刮削结果 TTL 缓存**：同批次相同番号文件（多 CD/重复文件）直接复用刮削结果，避免重复请求所有站点，TTL 90 秒 + 容量上限自动淘汰
- **R18.dev 英文标题掩蔽还原**：日文标题缺失时用服务端 `title_en_uncensored` 还原掩蔽字段（`Sex S***e` → `Sex Slave`）
- **补别名/补全功能调整**：补别名来源切换为内置 minnano 爬虫（无 CF 拦截、命中质量高），新增「全量更新」开关与「起始行/限量」分片续跑；新增「minnano 补全」按钮（补缺生日/简介，日文自动翻译）
- **演员库维护工具健壮性**：新增「检查用户库」（扫描格式/结构/数据异常，安全项一键自动修复）与独立停止按钮；联网工具统一滑动窗口并发（TMDB 5 / LibreDMM 2）+ 限量分片 + 断点续跑；LibreDMM 补链接加限流与共享会话
- **info 库重构与同步**：三语言列、五源标签收集、cn 翻译优化；出厂库合并用户库机制（cn 合并键 + md5 marker）；actor 库标签/事务所/生涯日文残留清理与同步；check_actor_db 检查项整合
- **Emby 演员管理器增强**：信息补全与管理器接入本地演员库（最高优先，离线可用）；新增 graphis 头像/背景图来源；跳过逻辑精确化（识别"无维基百科信息"占位符）

### 修复

- **打包与网络**：PyInstaller 补充 minnano 爬虫 hidden-import；默认走代理列表补 `minnano-av.com` 且裸 session 按配置走代理；JavDB 图片域名归一（水印 `tp.spfcas.com` → 无水印 `c0.jdbstatic.com`）
- **Emby 演员管理器**：「仅补缺失演员」不再拉全库、详情并发拉取、删除图按响应状态判定；移植版 import 修复、空响应不再误报失败、缓存导入路径修复
- **演员库维护工具**：新增「更新 nfo tmdbid」与「校验 tmdbid 有效性」按钮；TMDB 演员匹配优化（繁→简转换、adult 权重优先、候选放宽 + 命中变体排序）；actor_db 并发 UX 修复（信号带 task_id、通用模板消重）
- **UI 与布局**：工具页/设置页 groupBox 重叠连锁修复；删除无效单选按钮；MDCx.py 文案漂移回写 MDCx.ui；`validate_crawler_registry` 误报修复
- **网络诊断**：站点超时改用用户配置值；新增"路由"列显示代理/直连
- **安全**：修复 `shell=True` 注入风险、移除 11 处 `?api_key=` 暴露、修复 5 处静默异常 + 下载 URL 白名单
- **minnano 路径 bug**：日文名查找与缓存文件改用运行时用户数据目录（打包后 CWD 失效问题）
- **其他**：爬虫 xpath 防御下沉（10 处）、`update_nfo_tmdb_ids` 类型防御、UI 缩放异常不阻断启动、异常日志通道修复

### 工程质量

- **mypy 严格化**：移除全部 19 项 `disable_error_code`，全项目零抑制通过；`BaseCrawler` 泛型化等修复 43+ 处类型错误，顺带修复 5 个隐藏 bug
- **测试增强**：UI 结构自动化测试、`validate_crawler_registry` 测试、Emby HTTP 测试、actor_db 按钮一致性测试；ruff 自动修复 138 处
- **其他**：单站失败原因结构化分类（`FailureReason`）、死代码清理、`_download_chunk` 返回类型修正

### 文档

- 使用说明 tab 与 README/INSTALL/FEATURES/USER_GUIDE 等更新（仓库链接修复、新功能描述）

## v2.0.3 (2026-08-03)

### 功能

- **演员库维护工具改为直接操作 xlsx**：移除「输入演员名单 / 选择 nfo 目录」输入方式，新增三个独立按钮——补全中文名（按已有 TMDB ID 补中/英繁体翻译）、补全 LibreDMM 链接（补信息链接）、同步别名（用 TMDB 最新 also_known_as 刷新 keyword 列），统一扫描 `actor_database.xlsx`，每个按钮带独立防重入
- **同步别名与刮削共用同一规则**：`run_actor_db_xlsx` 的 `sync_aliases` 改为复用 `_merge_keyword_values`，与刮削写入 actor 库的别名合并逻辑保持一致，永不同步偏差
- **工具页工具排序调整**：按用户偏好重排为 Emby 演员管理 → 演员库维护 → 单文件刮削 → 裁剪图片 → 封面补图 → 软链接助手 → 移动视频字幕 → 检查演员缺失番号
- **打开演员数据库按钮**：演员库维护工具新增「打开演员数据库」按钮，用系统默认程序打开 `actor_database.xlsx` 供查看与手工编辑；文件不存在或打开失败时提示先安装 Excel/WPS 等办公软件
- **并发提速**：演员库维护（补全中文名/链接/同步别名）改为滑动窗口并发模式，TMDB 请求并发 5、LibreDMM 请求并发 2，串行 150s+ 降至约 30s

### 修复

- **单 exe 按钮无提示退出**：修复「打开演员数据库」按钮点击后程序直接退出（根因：`_open_actor_db_file` 误作实例方法调用导致 AttributeError，被 onefile 无控制台吞掉为静默退出）
- **executor.submit 传参错误**：`AsyncBackgroundExecutor.submit()` 只接受单协程参数，`executor.submit(asyncio.run, run())` 写法导致 TypeError。修复 `main_window.py` 的 `_run_actor_db_tool` 及 `tool_handlers.py` 的 cover_backfill 两处同源 bug
- **跨线程 Qt 不安全操作**：`_run_actor_db_tool` 协程内直接 `btn.setEnabled()` 跨线程操作 QWidget。改为 `actor_db_finished` pyqtSignal 主线程恢复，消除潜在 segfault 风险
- **日志通道不通**：`_log_line` 仅写内存 LogBuffer，不显示在 GUI 日志页/文件，用户看到「开始扫描」后无后续输出误以为卡死。改为同时调用 `signal_qt.show_log_text` 实时显示

### 工程质量

- **崩溃转储埋点**：`main.py` 注册 faulthandler + sys.excepthook + stdout/stderr 重定向到 `MAIN_PATH/crash/` 目录， onefile 无控制台环境下的 Python 异常不再被静默吞掉
- **死代码清理**：移除 `init.py` 重复 `setText` 接线、`tool_handlers.py`/`main_window.py` 旧 `pushButton_actor_db_pick_dir/start_clicked` 引用已删除控件的死代码
- **记忆文件写入**：`.monkeycode/MEMORY.md` 记录 9 条经验：onefile 静默退出诊断方法、日志通道一致性、executor.submit 正确用法、跨线程 Qt 安全模式、刮削并发架构参考

## v2.0.2 (2026-08-02)

### 重构

- **工具页槽函数抽取**：将 `main_window.py` 中的 21 个工具/设置页槽函数抽取至独立模块 `tool_handlers.py`，`main_window.py` 从 3539 行减至约 3350 行
- **目录选择模式统一**：新增 `_pick_folder` 公共 helper，9 个目录选择方法统一为一行 delegate 调用
- **删除 2 个废弃 import**：`emby_actor_image`/`emby_actor_info` 改为延迟导入

### 性能

- **行索引缓存**：`update_actor_db_row` 新增 `_ACTOR_DB_ROW_INDEX` 全局索引（jp_name → row_index），消除 O(n²) workbook 全表扫描，三个调用点（actor_db_tool/tmdb_actor/scraper）直接受益
- **读取模式批量落盘**：`scraper.py` 读取模式下演员 TMDB ID 补充改为共享 workbook，集中一次落盘，避免每个演员独立 load/save
- **格式化跳过**：`_format_db_worksheet` 检测表头是否已格式化，首次后跳过边框/字体/列宽设置，每次 save 减少 5 次全表遍历，CI 测试耗时从 20.8s 降至 10.7s

### 工程质量

- **测试基线治理（三条合并为一条）**：先把假联网测试放回 CI、再修陈旧 mock、最后才是补新用例——CI 离线通过数从 **530 提升至 635**（+105），全量 627 passed / 4 skipped。
  - **① 移除 7 个文件的 network 标记**：`test_tmdb_actor.py` 等 7 个文件的 93 个测试全部为纯离线 mock 测试，移除 `pytestmark = pytest.mark.network` 使其进入 CI
  - **② 修复 9 个预存陈旧测试**：`test_network_lifecycle.py` 的 `_FakeLimiter`/`_FakeResponse` mock 修复（添加 async context manager 支持）、`test_web_amazon_data.py` 的 mock 路径修正（`mdcx.utils.rate_limit.random`）、`test_amazon_database.py` freeze_panes assert 修正
  - **③ 新增 14 个测试用例**：行索引缓存 6 个、`_load_actor_db_wb`/`_flush_actor_db_wb` 4 个、目录选择/gfriends 同步 8 个
- **打包配置补充**：`build.py` 新增 `mdcx.tools.emby_actor_image`/`emby_actor_info`/`sync_gfriends`/`scripts.cover_backfill` 的 hidden-import，排除 6 个开发期包（playwright/setuptools/mypy 等），预估单 exe 体积减少约 200MB

## v2.0.1 (2026-08-01)

### 新增功能

- **演员库维护工具**：工具页新增"演员库维护"功能，可对已有 TMDB ID 的演员批量补全中文/繁体翻译和 LibreDMM 链接，支持输入演员名单或选择 nfo 目录自动收集演员
- **刮削流程精简**：更新模式刮削时不再自动为已有演员补全翻译/LibreDMM 链接（该能力移至独立的"演员库维护"工具），加快刮削速度、减少不必要的网络请求
- **Emby 演员管理器**：工具页新增"Emby 演员管理器"按钮，打开独立对话框，可连接 Emby 服务器获取演员列表、多源匹配头像（Gfriends/minnano-av/本地文件夹）和简介（minnano-av/Wiki/本地数据库），支持批量同步到 Emby
- **Emby 演员管理器 - 选库**：点击"获取演员列表"时弹出媒体库选择对话框，可按需勾选要管理的库
- **Emby 演员管理器 - 表格查看**：演员列表表格展示头像/简介/背景图/影片数状态，支持按缺失情况筛选和搜索
- **封面补图工具**：工具页新增"封面补图"功能，输入番号即可自动刮削并补齐缺失的 `poster.jpg` 和 `thumb.jpg`，复用当前配置的站点优先级、命名、裁切、水印规则，支持批量输入与覆盖已有图片
- **封面补图独立脚本**：`scripts/cover_backfill.py` 支持命令行批量和自定义参数，可在打包外独立运行
- **JIMMY 前缀路由**：`JIMMY-003` 等番号自动路由到 FALENO 官网获取资料
- **失败原因记录**：所有刮削来源均失败时，日志会列出各站点的具体失败原因（超时/搜索未匹配等），便于定位问题

### 改进

- **自动海报选优**：不再将横向海报作为最终 Poster，候选图全为横图时自动改用缩略图右裁切，修复 ABF-371 一类封面未裁剪问题

### 修复

- **Windows 路径超限**：`{{ series }}` 系列名过长导致完整路径超 MAX_PATH(260) 时，自动缩短目录名，修复刮削后文件夹无法打开的问题（#19）
- **中文字幕标签误添加**：共享数据路径中未检查 `nfo_tag_include` 配置，关闭后仍会添加"中文字幕"标签，现已修复（#20）
- **explorer /select 路径未引号**：含空格或特殊字符的路径无法用 `explorer /select` 打开，已修复为加引号调用
- **Emby 4.9 剧照显示**：`extrafanart_extras_copy` 将 .jpg 改为 .mp4 时使用 move 而非 copy，导致 `behind the scenes` 目录下只保留 .mp4，Emby 4.9 无法识别。改为 copy 同时保留 .jpg 和 .mp4（#17）

### 工程质量

- 测试基线：新增 2 个模块，596 个测试用例（583 通过，13 个为既有环境性网络用例失败，与本次改动无关）；无新增第三方依赖，兼容 Windows 打包
- 本轮新增用例（三条合并为一条）：JIMMY 前缀路由、失败原因记录、海报横向过滤（7 个覆盖 portrait 选优逻辑），以及演员库维护相关用例（nfo 目录收集/去重、空名单、翻译/链接开关控制、翻译与链接补全）

## v2.0.0 (2026-07-18)

MDCx v2.0.0 全新出发。

### 新增爬虫

- **R18.dev 爬虫**：新增 `r18dev` 刮削源，走 R18.dev 的 JSON 接口直连，不需要翻墙，番号自动补零适配，支持 dvd_id 和 content_id 两种查询方式
- **JavDB API 爬虫**：新增 `javdb_api` 刮削源，走 JavDB 镜像站 HTML 直连，不用 CF 代理，带演员名简繁转换和异体字修正（筱→篠、穗→穂等），可选镜像站地址
- **MissAV免防护墙爬虫 missav_api**：原MissAV爬虫常被防护墙挡住；现在多了一条免防护墙通道，不用费力绕墙也能直接刮到它的影片信息

### 新增功能

- **界面缩放比例配置**：在"设置 → 界面外观 → 高分屏缩放"设置区域新增缩放比例下拉框，支持"跟随系统"/80%/90%/100%/125%/150%/175%/200% 共 8 档选项（含非整数倍缩放）。选择非默认值时通过 `QT_SCALE_FACTOR` 环境变量（Qt6 原生机制）精确控制界面缩放，解决高分屏字体过大或过小的问题，并可配合暗色模式使用。保存后重启软件生效
- **内置 CF Bypass（零配置）**：新增"启用内置 Bypass"选项，勾选后 MDCx 自动在后台启动本地旁路服务（基于隐身浏览器），无需手动搭建外部服务。
- **新增设置项**：`cf_bypass_auto`（bool，默认 false），与外部 `cf_bypass_url` 互斥，地址为空时方能启用本地服务

### 刮削系统

- **四种刮削模式**：正常模式（全新刮削：扫描→刮数据→下图片→生成NFO→重命名→移动）/ 整理模式（仅归类文件，不下载图片不生成NFO）/ 更新模式（调整已有文件的目录结构）/ 读取模式（维护补刮，4个独立选项自由组合）
- **字段级优先级配置**：每个字段（标题、简介、演员、海报、评分等）可独立配置来源网站顺序和翻译开关，不同刮削类型还可设置不同的字段优先级
- **刮削模式**：支持 info（信息优先）、speed（速度优先）、single（单站快速）三种模式
- **刮削类型独立配置**：有码/无码/FC2/国产/欧美/素人每种类型可分别设置网站源列表
- **马赛克标准化**：自动将各类标签归一化为有码、无码、无码破解、流出、无码流出、国产
- **标签优先级系统**：基于 info_database.xlsx 的标签优先级排序，优先级标签→系列标签→其他标签

### 网络与反爬

- **CF Bypass 双模式**：支持 Mirror 模式（外部 bypass 服务代理请求）与 HTML 模式（调用 bypass 服务 `/html` 端点）
- **域名级独立限流**：每个网站独立令牌桶限流，默认 8 req/s，失败自动退避重试（403/429/500/502/503/504）
- **连接池管理**：三级连接池（HostPool → ConnectionPool → Session），域名级并发控制，Session 热更新，空闲自动回收
- **网络连通性检查**：内置一键测试各网站可达性工具
- **软链接支持**：可选择不移动原文件，创建软链接到目标目录

### 界面与工具

- **暗色/亮色主题切换**：内置完整双主题支持
- **海报裁剪工具**：图形化界面，鼠标拖拽选择裁剪区域，支持 2:3 标准比例
- **缺失文件检测**：检查媒体库中哪些文件缺失
- **成功/失败文件列表**：自动记录处理结果，支持断点续刮
- **多CD分集支持**：多碟片文件自动合并为一条记录
- **额外剧照处理**：自动下载多张剧照并管理副本
- **图片修复**：自动修复下载的图片（尺寸、格式等）
- **24 个命名模板字段**：番号、标题、演员、系列、制作商、分辨率、编码等，Jinja2 条件渲染
- **演员 NFO 生成**：生成 Kodi 兼容的演员信息文件（.actors 目录）
- **内置资源管理**：演员数据库、ASIN 数据库、NFO 信息数据库、字体等资源统一管理

### 配置系统

- **配置自动迁移**：旧版 INI 格式配置文件在加载时自动转换为 JSON 格式
- **配置热切换**：修改配置后自动生效，无需重启
- **敏感字段脱敏**：API Key 等敏感字段在导出时自动替换为 `***`

### 修复

- **网络标签页按钮重叠**：修复了设置页面里网络标签页的控件叠到一起、显示不全的问题，调整了各区域的高度和位置
- **Windows 下启动崩溃**：修复了 Windows 版打开时因 `topLevelItem(1)` 为空导致闪退的问题
- **R18.dev 补零位数**：番号标准化从 3 位补零改为 5 位，跟 R18.dev 数据库实际格式一致
- **fc2cmadb 演员数据爬取修复**：Inertia.js Deferred Props 导致的演员数据缺失问题。修复逻辑改为 Inertia JSON 解析后若 actresses 为空则回退到 HTML table 解析补充，同时增强 Inertia partial reload 请求头（注入 X-Inertia-Version 和 X-XSRF-TOKEN），解决已登录但爬不到演员的问题
- **fc2ppvdb Cookie 检查优化**：域名迁移至 fc2cmadb 后，Cookie 检查不再依赖 `fc2ppvdb_session` 关键字
- **刮削失败标题被日志污染**：修复 `main_window.py:1180` 中刮削失败后标题回退到 `LogBuffer.error().get()` 的问题——该函数会跨任务聚合其他任务的 TMDB 演员处理日志（如 `[演员数据库] 已新增 ... 并写入 tmdbid=...`）作为标题。改为使用文件名兜底
- **刮削过程更稳**：修好了多个任务同时刮时偶尔"串数据"的老毛病，演员信息写入也更省系统资源
- **修好 30 个第三方库的安全隐患**：把软件用到的外部工具库都升级到安全版本，整体更安全

### 改进

- **绕过网站防护墙更稳更快**：后台服务重写，启动不发呆、不卡死；安装包里直接带好隐身浏览器，装完即用，不用额外下载和配置
- **界面缩放优化**：放宽 Windows 窗口最小尺寸限制（从硬锁定 1089x700 改为 QSize(850, 550)），解决 1920x1080 125% 缩放下界面过大且无法缩小的问题

### 工程质量

- **推送前自动跑测试**：新增 pytest 推送前自检，`uv run check` 会自动执行 ruff 格式检查 + ruff 代码规范 + pytest 单元测试，格式不对、代码存在隐患、有测试没通过会直接卡住提交（门禁与 CI 分工见 `docs/Development.md`「测试」）
- **新增一批测试用例**：R18.dev 14 个测试 + JavDB API 18 个测试，覆盖番号解析、字段映射、搜索匹配等工作

### 其他

- 软件内"使用说明"的内容已更新，过时的信息换成了最新的
- 新增一批自动测试，防止上面的问题以后又冒出来

## v1.4.0 (2026-07-07)

### 新增功能

- **Bing 翻译引擎**：新增 Bing 翻译选项，免费免配置，与 Google 一样自动爬取翻译接口，支持中/英/日互译
- **无码官网爬虫**：official 源扩展支持 Caribbeancom、HEYZO、1Pondo、Pacopacomama、10Musume 五个无码官网，番号自动路由到对应站点
- **official 官网前缀路由**：FNS/FALENO 与 DLDSS/DAHLIA 番号前缀自动委派给对应的子爬虫，扩大官网覆盖范围
- **fc2ppvdb 适配 fc2cmadb**：基础 URL 迁移至 `fc2cmadb.com`，新增 Inertia.js JSON + HTML 双模式解析，不再依赖旧版 fc2ppvdb XHR 接口

### 修复

- **avsex 更新修复**: 兼容 /cn/ 简体中文页面，修复 title/actor/tag/outline/extrafanart XPath 提取
- **iqqtv 标题清理**：去除标题末尾的 `caribbeancom_番号` / `1pondo_番号` 等站点前缀，避免污染无码影片标题
- **fix**: 图片简化命名(poster.jpg)在 skip_reorganize 和不移动文件路径下被忽略

## v1.3.3 (2026-06-23)

### 修复

- **xcity 刮不出中文**：修复了 xcity 刮出来全是英文的问题（加了请求头让网站返回繁体中文，再自动转成简体）
- **多任务同时刮会串数据**：修复了同时刮多个影片时，xcity 的数据会串到别的影片上的问题
- **预置4个默认代理**：amazon.co.jp、m.media-amazon.com、xcity.jp、dmm.co.jp 保障正常刮削 dmm、xcity及下载日亚高清封面

### 日志精简

- **日志去重**：同一行重复的日志不再刷屏了
- **去掉没意义的"(old)"日志**：之前每个文件都会刷"Poster done! (old)"这类消息（意思是"文件已经有了，跳过下载"），现在不显示了，日志减少了将近一半
- **报错提示不再重复弹**：图片下载失败时，"去设置里勾选xxx"的提示只出现一次，不再日志和错误提示各出现一次
- **翻译跳过不再逐行输出**：如果多个翻译引擎都不可用或跳过，现在汇总成一行显示，不再每个引擎占一行

### 日志合并

- **Poster 裁剪日志合并为一行**：以前裁剪海报时先输出"开始处理"，再输出"用了什么策略"，现在合并为一行，信息量不变
- **Poster 直复制缩略图日志合并**：策略说明和完成报告合并为一行

### 开发者工具

- **添加类型检查工具**：新增 pyright 配置，后续开发时能自动发现潜在的类型错误，减少发布后出问题的概率

## v1.3.2 (2026-06-22)

### 功能增强

- **刮削速度优化**：图片下载改成并行模式，缩略图下载完后，海报、剧照等会同时下载，不用排队等了
- **演员 TMDB ID 查询加速**：从 TMDB 查演员信息时，多个演员同时查（以前是排着队一个一个查），补演员改名翻译和网址也合并到一块写入硬盘，减少重复读写

### 界面调整

- **代理设置更清晰了**：原来的"不使用代理"改成了"使用代理"。现在只对你填进去的网站走代理，其他网站默认直连，不会出现代理影响国内网站的尴尬。默认预填了 `amazon.co.jp` 和 `m.media-amazon.com`

### 修复

- **Excel 字体大小不一致**：修复了往演员数据库和 Amazon ASIN 数据库添加新数据时，字体默认变成 12 号，和原来 11 号不统一的问题

## v1.3.1 (2026-06-20)

### 新增功能

- **新爬虫：JavDB APP版接口**：新增 `javdb_app` 刮削源，走的是 JavDB App 的接口，有码/无码/素人/FC2/欧美都能用，配置里对应的分类已默认加上

### 修复

- **欧美影片刮着刮着就超时**：修复了一个代码缩进错误。以前日系番号（如 `SSNI-111`）正常，但欧美番号（如 `Viv-thomas.24.12.20`）因为名字里带点号，程序错误地进入了"等待同番号"的死循环，干等 300 秒后超时报错。现在欧美番号也能正常刮了

### 界面调整

- **可用网站列表刷新**："可用网站"弹窗和"指定网站"下拉框现在和实际注册的爬虫保持一致，移除了已停用的 `avsex`、`love6`
- **无码分类编辑框不再出现有码站**：`javlibrary`、`libredmm`、`dmm_api` 不会再出现在无码的编辑网站对话框里

### 日志优化

- **分隔线不再用满屏 emoji**：以前每个任务开始和结束用 50 个连续 emoji（`👆`×50、`👇`×50）做分隔线，在某些电脑上显示为乱码方框，且日志文件体积巨大。改为 40 个等号 `====`，清爽多了

## v1.3.0 (2026-06-18) 重磅更新

### 新增功能

- 演员日文名更准了：以前填演员表用的是搜索用的中文名，现在改用 TMDB 返回的日文原名（像"三上悠亜"这种）
- 自动补演员网址：刮削完会自动检查哪些演员有 TMDB ID 但没网址，用日文名去 LibreDMM 找到网址填上
- 重磅更新,读取模式下，向已刮削的影片的NFO中补全写入演员tmdbid
- 前提条件：
  - 1.设置网络页面填入TMDB API KEY（没有的要去TMDB申请）
  - 2.设置NFO页面勾选"为演员写入TMDB ID"
  - 3.设置刮削模式为选读取模式，并勾选"允许更新 nfo文件"
  - 4.TMDB上要有这个演员的信息资料
- 注意：如果不想在补全演员tmdbid后，改变nfo中的演员名，请不要勾选设置翻译页面的"使用演员映射表翻译演员"
- 好消息：AVdb的LEO、龙王大佬们在持续补充 TMDB 女优资料中，lsj可以定期用读取模式去获取新增加女优的tmdbid了，不用重新刮削

### 读取模式改进

- **选项更灵活了**：4 个选项现在互不绑定。可以只勾"有 NFO 时更新"不勾"更新 NFO"，就只整理文件不改 NFO；也可以只勾"更新 NFO"不勾"有 NFO 时更新"，就只改 NFO 内容不挪文件

### 修复

- **NFO 里的 `<![CDATA[...]]>`** 改用正规解析，不会再因为内容里恰好有 `]]>` 而出错
- **正则表达式安全**：文件名中的特殊字符会先转义再匹配，不会崩
- **并发请求异常**：演员名查询时如果某个请求出错，不会让整个任务崩溃
- **被悄悄吞掉的错误日志**：演员数据查询中隐蔽的异常现在会写入日志

## v1.2.1 (2026-06-17)

### 修复

- 修复传统窗口模式下（未勾选"隐藏边框"），点击原生标题栏关闭按钮无响应问题
- 修复反序设置导致已有超链接单元格样式标记丢失

### 功能增强

- 完善 LibreDMM 演员链接自动补全功能
- xlsx 冻结窗格从 `A2` 改为 `B2`，同时固定表头行和第1列（番号列），横向滚动时始终可见
- 传统窗口模式下，点击关闭按钮同样遵循 `HIDE_CLOSE` 配置，支持"关闭时隐藏到系统托盘"

### UI 改进

- 更新设置翻译页面提示词，反映 xlsx 数据库格式和 TMDB 自动填充功能

## v1.2.0 (2026-06-16)

### 架构改进

- 将 `_read_actor_db_xlsx` 及列常量从 `tmdb_actor.py` 迁移至 `resources.py`，彻底消除模块初始化阶段的循环导入依赖

### 修复

- **#consts.py** `IS_DOCKER` 改为检测 `/.dockerenv` 文件，避免 Linux 桌面环境误判为 Docker
- **#number.py** `get_number_first_letter("")` 加空字符串保护，防止 `IndexError` 崩溃
- **#tmdb_actor.py** `_tmdb_request()` curl_cffi 分支补上 `follow_redirects` 参数，统一两种 HTTP 后端的重定向行为

### 功能增强

- **#file_crawler.py** `_normalize_release_value()` 增加 `YYYYMMDD` 无分隔符日期格式兼容
- **#tmdb_actor.py** 演员数据库首次发现为 `None` 时自动重试加载（延迟加载兜底），减少不必要的 TMDB API 请求
- **#tmdb_actor.py** 对 `update_actor_db_row()` 增加 `asyncio.Lock()` 防止并发写 xlsx 导致文件损坏
- **#resources.py** `reload_actor_db()` 文件不存在时不再重置 `actor_db` 为 `None`；异常时恢复旧值保留缓存；异常信息同步写入主日志和 traceback 日志

### 代码精简

- **#resources.py** `_get_mark_icon()` 7 处重复的 if-not-isfile-copy 合并为数据驱动循环
- **#number.py** FC2 / HEYZO 番号提取两个几乎相同的 elif 分支合并为一个，区分前缀和最小位数
- **#crawlers/** 12 个爬虫文件各自定义的 `split_csv` 函数统一为 `crawlers/base/types.py` 的共享函数，各文件 import 使用
- **#pyproject.toml** 添加 `[build-system]` 段，符合 PEP 517/518 打包规范

### 线程安全

- **#log_buffer.py** `all_buffers` 字典所有读写操作增加 `threading.Lock` 保护，消除多协程并发时字典损坏风险

## v1.1.0 (2026-06-13)

### 新增功能

- **Minnano-av 演员信息刮削源**
  - 新增 `minnano_crawler.py` 模块，支持从 みんなのAV 网站抓取演员信息
  - 支持中文→日文演员名映射（通过 `actor_database.xlsx` 查找日文原名后再搜索）
  - 实现模糊搜索匹配策略：精确匹配优先，其次多字符公共子串匹配，最后五十音回退搜索
  - 详情页加了标题核对，避免匹配到错误的演员

- **Emby 演员信息增强**
  - 在 Wikipedia 之前优先查询 Minnano-av 数据源，补充 Emby 演员元数据
  - Minnano-av 缓存文件 `minnano_cache.xlsx` 集成，避免重复请求
  - 缓存表头冻结、数据行全边框、URL 超链接，便于用户手动审查

- **Gfriends 头像本地仓库**
  - UI 新增"Gfriends 设置"区域：可以选择本地仓库路径、点按钮更新（拉取最新头像）、显示最后更新时间
  - 有本地仓库时优先从本地读取，不联网；本地没配置时才从 GitHub 网络下载
  - 更新按钮在没选路径或正在更新时禁用，防止误操作
  - 保存配置时，如果本地和网络都没填会弹窗提醒

- **Gfriends 头像升级：AI 修复版优先**
  - 找Gfriends 头像时优先用 `AI-Fix-名字.jpg`（AI 修复增强版），再找普通版

- **搜索链接中文兼容**
  - Graphis、Minnano-av、Wikidata 搜索时，演员名字自动做编码转换，解决日语名字搜索失败的问题

### 配置变更

- 新增 `gfriends_local_path` 配置项：填本地 Gfriends 文件夹路径即可启用本地模式

## v1.0.0 (2026-06-11)

MDCx-DIY 首个正式发布版，基于Hazard804改良的mdcx项目制作，对前辈表示衷心感谢！！！

### 刮削引擎

- 40+ 网站爬虫（有码/无码/FC2/国产/欧美）
- 新增 libredmm 刮削源（可刮削dmm下架影片）
- GenericBaseCrawler 统一框架 + 上下文隔离
- 智能番号识别与自动分类（用户预定义）
- 异步并发架构（asyncio + 渐进式任务调度）
- curl-cffi 浏览器指纹伪装

### TMDB 演员

- 新增 NFO 女优 TMDB ID 功能
- NFO 女优 TMDB ID 写入（需在 NFO 设置勾选 + 填入 API Key）
- 日文原名搜索，日本出生地 + 女性/未指定性别 + 精确名匹配过滤
- 多候选按 popularity 排序取最优，失败不阻塞刮削
- 令牌桶限流器（3.5 req/s，突发 10），并发 3 查询
- TMDB adult 候选自动跳过，搜索候选数优化为 5
- actor_database.xlsx用于nfo增加tmdbid和演员映射功能，反向搜索 + 增量写入，已预置部分女优数据，后续随软件使用动态更新（新演员若TMDB有数据就在表中追加数据，表中演员若TMDB数据更新，表中相关数据会追加）
- 超链接一致性校验与自动修复

### Amazon 高清封面

- ASIN 条码识别 + 三层搜索策略
- 封面 poster 固定 1500 尺寸（平衡质量和大小）
- 新增Amazon ASIN 缓存功能，通过Excel 缓存（amazon_asin_database.xlsx）
- 缓存去重逻辑，保护高置信度数据
- ASIN 缓存Excel随软件使用动态追加（同个影片二次刮削时不用再去Amazon查找，直接用表中数据下载高清封面）

### 数据源迁移

- actor_mapping XML + TMDB 缓存合并为 actor_database.xlsx
- mapping_info.xml 迁移为 info_database.xlsx
- 内置 xlsx 数据库，支持表头冻结，筛选、超链接等，用户可自行编辑或通过超链接审查数据

### 代理与网络

- HTTP/SOCKS5 代理配置
- 新增"不使用代理"网站选择器：40+ 刮削源下拉快速选择，智能域名匹配
- 默认 api.tmdb.org 不走代理

### 元数据与媒体

- NFO 生成器，30+ 字段，兼容 Kodi/Emby/Jellyfin
- 多语言翻译（Google/Bing/百度/DeepL/DeepLX/LLM 六引擎）
- Jinja2 命名模板引擎
- OpenCV 人脸检测智能裁剪
- 海报/背景图/预告片自动获取
- 字幕管理与缺失检测
- Emby/Jellyfin 演员信息补全 + 头像同步

### 界面与工具

- PyQt6 桌面图形界面
- 命令行工具（crawl、gen_enums）
- 构建工具链（build、bump、changelog、check）

### 工程质量

- 70+ 个测试文件覆盖核心模块
- CI：ruff format + ruff check
- Release：macOS DMG + Windows EXE
- 新增29 篇技术文档（架构、模块、API、迁移指南等）
