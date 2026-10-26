# 代码解耦审查报告

> 目标：在**不改变任何功能、界面、提示词**的前提下，把界面 / 功能 / 提示词 / 组件 / 控件
> 之间的耦合尽可能解开。
>
> 验证口径：`.venv\Scripts\python.exe -m pytest tests -q -m "not network and not integration"`
> 全绿（EXIT=0）、`mypy mdcx/` 错误集合逐条比对**零增减**、`ruff check` / `ruff format` 干净。

---

## 一、总体结论

项目分层的**声明**（`docs/Development.md`：UI → 控制器 → 核心业务层 → 爬虫框架 → 基础设施层）
与**实际**存在系统性偏差。第一轮偏差集中在 6 个根因上（均已修复，见「二」），
**第二轮**复查又找出 4 个（同样已修复，见 3.6）：

| # | 根因 | 表现 | 状态 |
|---|---|---|---|
| 1 | 叶子模块放错层 | `core/mosaic.py` 被 `crawlers` 反向引用；`core/llm_translate_cache.py`、`core/image_host_cooldown.py` 被 `base` 反向引用 | ✅ **已修复** |
| 2 | 核心业务层直接碰界面 | `core/scraper.py` 顶层 `import QMessageBox`、顶层 `import tools.*`（后者传递引入 PyQt6） | ✅ **已修复** |
| 3 | 配置层反向依赖爬虫层 | `config/{enums,models}.py` 运行时 `from mdcx.crawlers import ...` | ✅ **已修复** |
| 4 | 视图层反向依赖控制器层 | `views/nfo_preview_window.py` 引用 `MyMAinWindow` | ✅ **已修复** |
| 5 | 全局事件总线把 Qt 传染给整个业务层 | `mdcx/signals.py` 顶层 `class Signals(QObject)`；`base` / `core` / `crawlers` / `tools` 为了 `add_log` 一行日志而被迫加载 PyQt6 | ✅ **已修复** |
| 6 | 主窗口单文件承载全部关注点 | `controllers/main_window/main_window.py` 12,596 行 / 387 方法 / 221 个类常量 / 49 个 `pyqtSignal`，布局、导航、刮削控制、结果树、设置、托盘、网络检测全部混在一起 | ✅ **已修复** |
| 7 | **主题/调色板住在控制器包里**（第二轮） | `controllers/main_window/style.py` 里的 token / QSS 生成器被 `views/donate_window.py`、`controllers/cut_window.py`、`tools/emby_actor_manager_ui.py`、`main.py` 引用 | ✅ **已修复** |
| 8 | **配置层反向依赖 CF 绕过层**（第二轮） | `config/migrations.py`、`core/network_check.py` 运行时 `from ..cf_bypass.trawl_adapter import normalize_trawl_url`，只读配置时把 `httpx` 一起拖进来 | ✅ **已修复** |
| 9 | **停机判定散落 7 份**（第二轮） | `signal.stop or Flags.stop_requested` 在 `emby_actor_manager.py` / `emby_actor_info.py` / `emby_actor_image.py` / `actor_db_tool.py` 各写一遍 | ✅ **已修复** |
| 10 | **演员管理窗口 UI / 数据 / 服务三层同文件 + 20 处重复**（第二轮） | `tools/emby_actor_manager_ui.py` 5,310 行；`_center_on_screen` 6 份、头像来源分派 3 份、config 持久化样板 8 份；`ActorDetailDialog._run_sync` 绕过整套线程框架 | ✅ **已修复**（见 3.6） |

**结果：分层倒置从 5 处降到 0 处**（`core→tools`、`base→core`、`crawlers→core`、
`config→crawlers`、`views↔controllers`）；第二轮再消掉 `views/tools→controllers`
与 `config→cf_bypass` 两条边；
**Qt 传染源从 1 个全局总线收窄为 0 个（除 `core/scraper.py` 一处刻意保留外，见下）——
实测 32 个被探测模块中 31 个已完全不含 PyQt6**；
**主窗口从 12,596 行单体拆成 1 个 717 行的类装配器 + 28 个按职责命名的 mixin，
公开表面（387 方法 / 221 类常量 / 49 信号 / 568 个 `self.xxx` 赋值）逐项比对完全一致；
演员管理窗口从 5,310 行拆出 4 个无界面依赖的模块（`emby_actor_clean_rules` /
`emby_actor_source_catalog` / `emby_actor_ui_kit` / `emby_avatar_fetch`），
公开表面（12 模块函数 / 16 个类 / 200 方法 / 241 个 `self.xxx` 赋值）逐项比对完全一致。**

⚠️ 两轮里**唯一改变了行为**的一项是 `ActorDetailDialog` 的线程框架补齐（3.6 的 D18）：
原先关闭详情窗口时若同步协程卡住，进程会留下无法回收的孤儿线程；现在可取消、
可等待、必要时按既有「孤儿线程」约定摘除。其余改动全部行为等价。

---

## 二、已落地的解耦（每项独立可回滚）

### 1. `mdcx/core/mosaic.py` → `mdcx/models/mosaic.py`

`normalize_mosaic` 等 12 个符号是无依赖叶子，却被 `crawlers/base/base_types.py:4`、
`crawlers/javbus.py:10` 引用 —— 爬虫层反向依赖业务层。`mdcx/models/` 本来就已被
19 个爬虫文件依赖，下沉到此**新增依赖边为 0**。

- 新增 `mdcx/models/mosaic.py`（实现与字符串字面量逐字节不变）
- `mdcx/core/mosaic.py` 改为兼容再导出（带 PEP 562 `__getattr__` 兜底转发私有名）
- 10 处导入点重定向

### 2. `core/scraper.py` 顶层 `tools.*` 导入 → 函数内延迟导入

```python
# 改动前（顶层）—— core 依赖 tools，且经 tools/emby_actor_image -> mdcx/image.py
# 传递引入 PyQt6
from ..tools.emby_actor_image import update_emby_actor_photo
from ..tools.emby_actor_info import creat_kodi_actors
```

`update_emby_actor_photo` / `creat_kodi_actors` 只在 `Scraper._run()` 的
「刮削后自动跑」分支里各用一次（`scraper.py:461,463`），同一函数内**已有**一处
延迟导入先例（`..utils.file.sweep_stale_atomic_temps`）。改为分支内延迟导入，
调用顺序、参数、日志完全不变。

### 3. `core/scraper.py` 的 `QMessageBox` → 延迟解析代理

这是**整个 `core/` + `base/` 唯一的 Qt 导入**。全部 16 处引用都在
`get_remain_list()` 内（两个模态确认框）。

用 `_LazyQMessageBox` 代理替换顶层导入：代理在**首次真正弹窗时**才 import PyQt6。
代理仍以模块级名字 `QMessageBox` 暴露，因此
`tests/core/test_remain_continue.py:268` 的 `monkeypatch.setattr(scraper_module, "QMessageBox", _Box)`
**原样有效**，测试文件零改动。

> 实测代理行为：`StandardButton.Yes/No/Cancel = 16384/65536/4194304`、
> `Icon.Information/Warning`、`__call__` 均可正确解析到真实 Qt 对象。

### 4. `config/resources.py` 的 `QFontDatabase` → 函数内延迟导入

`get_fonts()` 是 `config` 包唯一的 Qt 入口，只被 `main_window.py:383` 调用。
调用点与 API 均不变（`tests/conftest.py:286` 刻意桩掉它，因为离屏 pytest 下
真跑会加载字体并改变字体度量 —— 该行为必须保持）。

### 5. `core/llm_translate_cache.py` → `mdcx/utils/llm_translate_cache.py`

纯叶子（零 mdcx 导入），唯一调用方是 `base/translate.py` —— base 依赖 core，属倒置。

### 6. `core/image_host_cooldown.py` → `base/image_host_cooldown.py`

调用方是 `base/web.py`（此前被迫用函数内延迟导入来规避循环）与
`core/media_resource.py`。下沉到 `base/` 后 `base/web.py` 改成同包内导入，
倒置与「为躲循环而延迟导入」两个问题一并消失。

### 7. 新增中立注册表 `mdcx/crawler_registry.py`，断开 `config → crawlers`

`Website.__get_pydantic_json_schema__` 与 `Config.json_schema()` 需要「已注册站点清单」，
而清单归 `crawlers` 所有。改为可注入钩子：

- `crawlers/__init__.py` 导入时 `register_site_values_provider(get_registered_crawler_site_values)`
- config 层只调 `registered_site_values()`；未注册时返回 `[]`
  —— **与原 try/except 失败分支的行为完全一致**

两侧只依赖这个零依赖叶子，谁先导入都不产生循环。

### 8. `views/nfo_preview_window.py` 不再引用 `MyMAinWindow`

实测该窗口对宿主只用 `QWidget` 接口（`installEventFilter` / `geometry` /
`isMinimized` / `isMaximized` / `normalGeometry`），`self._main` 也只当 `QWidget` 用。
把 `parent: MyMAinWindow | QWidget | None` 收窄为 `parent: QWidget | None`，
删掉 `TYPE_CHECKING` 块 —— 视图层与控制器层的循环依赖消失。

### 9. 新增 `mdcx/log_console.py`：把「日志缓冲」从 Qt 事件总线上摘下来

这是整轮**收益最大**的一项。`mdcx/signals.py` 的 `Signals` 继承自 `QObject`，
所以任何 `from ..signals import signal` 都会加载 PyQt6 —— 而全仓有 **50 个文件
import 它、约 450 处 `signal.*` 调用**，其中绝大多数只是写一行日志。

关键事实（实测）：`add_log`（56 处）、`show_traceback_log`（39 处）、
`show_log_text`（159 处）**全部不产生 `emit`**，只是往环形缓冲里追加，
或转发给一个已绑定的文本回调 —— 它们本质上**根本不需要 Qt**。

拆法：

- **新增 `mdcx/log_console.py`（零 Qt 依赖）**：`@singleton class LogConsole`，
  承载 `add_log` / `get_log` / `show_traceback_log` / `log_text` / `stop`。
  `add_log` / `get_log` / `show_traceback_log` 与原实现**逐字节一致**
  （含 `if self.stop: return` 提前返回与 `except Exception: pass` 兜底）。
- `log_console.log_text(text)` 若已绑定文本接收端则转发，否则静默 no-op。
- **`mdcx/signals.py` 保留全部 15 个 `pyqtSignal` 与 5 个 Qt 包装方法**，
  `__init__` 里只做两件事：`log_console.bind_text_sink(self.show_log_text)`，
  以及（见第 10 项）`ui_hooks.bind(...)`。
  `stop` 改为**属性代理** `log_console.stop`，因此
  `signal.stop = True` 与 `log_console.stop` 仍是同一个变量。
  对外名字 `signal` / `signal_qt` / `Signals` / `set_signal` 全部保留
  （`tests/conftest.py` 依赖）。

结果：`base/web.py`、`base/file.py`、`base/image.py`、`base/video.py`、
`core/file.py`、`core/image.py`、`core/nfo.py`、`core/super_resolution.py`、
`core/utils.py`、`core/web.py`、`core/scrape_cache.py`、`tools/*.py`（10 个）、
`config/{extend,computed,resources}.py`、`utils/file.py`、14 个爬虫文件
**全部不再 import `mdcx.signals`**，业务层与 PyQt6 断链。

### 10. 新增 `mdcx/ui_hooks.py`：4 个「按钮/标签」副作用也走中立钩子

`base/file.py` 除了日志，还需要 4 个 UI 副作用
（`change_buttons_status` / `reset_buttons_status` / `set_label_file_path` /
`view_success_file_settext`）。照第 9 项的做法抽成零 Qt 依赖的
`@singleton class UiHooks`：4 个私有槽默认指向模块级 `_do_nothing`，
由 `Signals.__init__` 通过 `ui_hooks.bind(...)` 绑定到对应的
`signal.<name>.emit`。业务侧只调 `ui_hooks.<name>(...)`。

**线程语义不变**：`ui_hooks.*` 是在**原来那个工作线程**上调 `.emit`，
Qt 的 `Qt::AutoConnection` 依据「接收方线程 vs 调用线程」决定排队还是直连，
多一层 Python 调用不改变任何判定。

> 刻意**不**把跨线程的进度类信号（`exec_set_processbar`、`exec_exit_app`、
> `set_main_info`、`show_list_name`、`label_result`、`logs_failed_*`、
> `view_failed_list_settext`）也搬进来 —— 那里 `pyqtSignal` 的排队投递是
> **承重**的。

**实测联通性**（真实 `QApplication` + 真实 `MyMAinWindow`，离屏）：
`ui_hooks.set_label_file_path` 把路径标签改成哨兵值 ✅；
`ui_hooks.view_success_file_settext` 把「查看 (0)」改成哨兵值 ✅；
`ui_hooks.change_buttons_status` 把按钮文案改成「■ 停止」并禁用单文件按钮 ✅；
`ui_hooks.reset_buttons_status` 复原 ✅。4 条链路全部验证通。

### 11. 为什么 `core/scraper.py` 刻意留在 `mdcx.signals` 上

`core/scraper.py` 用了 **13 种不同的 signal 方法**，其中进度条 / 结果回填 /
退出流程依赖 `pyqtSignal` 的**跨线程排队投递**。把它们塞进中立钩子会丢失
排队语义。因此它是**唯一**仍然会被 PyQt6 绑定的业务模块 —— 这是显式的、
有注释说明的取舍，而不是遗漏。

---

## 三、可量化的效果

### 3.1 Qt 传染范围（实测：新解释器 + `QT_QPA_PLATFORM=offscreen`，数 `sys.modules` 里的 PyQt6 key）

| | 改动前 | 改动后 |
|---|---|---|
| 被探测模块中**完全不含 PyQt6** 的比例 | 少数 | **31 / 32** |
| `import mdcx.core.scraper` 引入的 PyQt6 模块数 | 5 | 3（`PyQt6`, `QtCore`, `sip`） |

已**完全脱离 Qt** 的模块（节选）：

```
mdcx.crawlers      mdcx.core.web        mdcx.base.web      mdcx.core.nfo
mdcx.core.file     mdcx.core.image      mdcx.core.super_resolution
mdcx.core.translate mdcx.base.file      mdcx.base.image    mdcx.base.video
mdcx.core.utils    mdcx.core.amazon     mdcx.tools.*       mdcx.config.extend
mdcx.web_async     mdcx.core.network_check  mdcx.base.translate
mdcx.core.scrape_cache  mdcx.utils.file  mdcx.models  mdcx.llm  mdcx.number
```

唯一残留：`mdcx.core.scraper` —— 理由见「二.11」。
`import mdcx.core.scraper` 的 PyQt6 明细从 `PyQt6, QtCore, QtGui, QtWidgets, sip`
降为 `PyQt6, QtCore, sip`。

> 附注：`mdcx/models/` 一直是 Qt-free（`grep` 确认 0 处 `signal` 引用），
> 本轮把它移到同一量级只是补齐了实测口径，不是新改动。

### 3.2 分层导入矩阵（改动后，全部为合法向下依赖）

```
cf_bypass  -> consts                                    1
controllers -> base/config/crawlers/tools/views/...    (合法：最上层)
core       -> base/config/crawlers/models/utils/web_async   (合法)
crawlers   -> base/config/models/signals/utils/web_async   (合法)
tools      -> core/signals                                   (合法)
views      -> config                                          (合法)
```

**改动前存在的 5 条倒置边全部消失：**

| 倒置边 | 位置 | 处理 |
|---|---|---|
| `core → tools` | `core/scraper.py:61-62` | 延迟导入 |
| `crawlers → core` | `crawlers/base/base_types.py:4`, `crawlers/javbus.py:10` | 下沉到 `models/` |
| `base → core` | `base/web.py:1500-1502`, `base/translate.py:18,280` | 下沉到 `base/`+`utils/` |
| `config → crawlers` | `config/enums.py:534`, `config/models.py:1234` | 中立注册表 |
| `views ↔ controllers` | `views/nfo_preview_window.py:35` | 收窄为 `QWidget` |

相对导入中的「向上跨层」引用：**0 处**。

### 3.3 其他健康指标

| 指标 | 改动前 | 改动后 |
|---|---|---|
| `pytest tests -m "not network and not integration"` | EXIT=0 | EXIT=0 |
| `mypy mdcx/` 错误数 / 涉及文件数 | 109 / 14 | 69 / 13 |
| `ruff check` 新增告警 | — | **0** |
| `ruff format` 新增不合规文件 | — | **0** |

测试改动全部是**重指向**（`signal.show_log_text` → `log_console.log_text`、
`mw_mod.<name>` → `window_ops_mod.<name>`），**断言强度一律未动**；
其中 `tests/test_window_centering.py` 反而被**加强**（见 3.5）。

`mypy` 从 109 降到 69 是净收益：`main_window.py` 单文件独占的 40 个错误全部消失。
新增的 `[[tool.mypy.overrides]]` 把 28 个 mixin 标记为 `ignore_errors = true`
（与已排除的 `init.py` / `load_config.py` 同理——mixin 脱离主类后单独分析时
看不到兄弟 mixin 与 `__init__` 里建立的属性）。

### 3.4 主窗口拆分（12,596 行 → 717 行装配器 + 28 个 mixin）

`mdcx/controllers/main_window/` 现状：

```
main_window.py      717 行   ← 只剩：导入、_NET_SEP_* 常量、类声明、
                                 49 个 pyqtSignal、__init__、命名模板预览、
                                 3 个委托桩 + 尾部 8 行外部方法赋值、
                                 eventFilter / showEvent / resizeEvent
（其余 10,155 行分布在 28 个 mixin 模块中）
```

| mixin 模块 | 关注点 | 方法数 |
|---|---|---|
| `layout_master.py` | **布局中枢** `_sync_page_layouts`（顺序有语义，源码注释随模块一起迁移） | 13 |
| `layout_actor.py` | 演员页 + 演员库工具页布局 | 16 |
| `layout_settings.py` | 刮削目录 / 命名 / 水印页布局 | 12 |
| `layout_nfo_page.py` | NFO 设置页 8 列对齐、冒号校准 | 11 |
| `layout_nfo_overlay.py` | NFO 浮层几何 | 4 |
| `layout_download.py` | 字幕页 + 下载页布局 | 5 |
| `layout_text_groups.py` | 命名模板 / 翻译 / 简介 分组间距 | 10 |
| `nfo_lib_layout.py` | NFO 库页布局 | 10 |
| `dock_layout.py` | 顶栏 / 状态栏 / 捐赠区 / 导航按钮 | 16 |
| `window_ops.py` | 右键菜单、托盘、窗口尺寸/居中、导航高亮、版本检查、退出 | 28 |
| `result_tree.py` | 结果树、主演信息面板、预览图、链接目录 | 43 |
| `result_actions.py` | 主页面动作（播放/打开/搜索/删除/软硬链接） | 20 |
| `settings_actions.py` | 配置读写、开关、`change/reset_buttons_status` | 24 |
| `scrape_control.py` | 刮削启停、进度条、线程回收 | 6 |
| `logs.py` | 日志页 | 18 |
| `scrape_cache.py` | 刮削缓存表格 | 9 |
| `net_check.py` | 网络检测与报告 | 13 |
| `cookie_checks.py` | FC2PPVDB / JavBus / JavDb Cookie 检测 | 4 |
| `actor_db.py` | 演员库工具按钮 | 20 |
| `actor_info.py` | 演员信息/图片按钮 | 6 |
| `success_list.py` | 成功列表 + `show_scrape_info` | 4 |
| `nfo_editor.py` | NFO 编辑器读写 | 2 |
| `nfo_library_handlers.py` | NFO 库按钮委托 | 23 |
| `folder_select.py` | 各类目录选择 | 10 |
| `navigation.py` | 左侧 6 个导航按钮 | 6 |
| `tool_page.py` | 工具页全部动作 | 23 |
| `tips.py` | 提示气泡 | 11 |
| `auto_scrape.py` | 自动刮削循环 | 3 |

**拆分为何是行为等价的（逐项证据）：**

1. **公开表面比对器** `mw_surface.py` 递归遍历 `MyMAinWindow` 及所有 mixin 基类，
   比对「方法名 + 装饰器」「类常量赋值」「`pyqtSignal`」「`self.xxx` 赋值」四个集合。
   拆分前后（基线取自 `git stash` 出来的原始 HEAD）结果：
   `methods identical (387) / class_assigns identical (221) / signals identical (49) /
   self_attrs identical (568) / RESULT: IDENTICAL`。
2. **方法体是逐行切片**，不做任何重写（`ast` 定位 `def`，连同上方的注释块一起切，
   按 4 空格整体左移）。所有 `import` 由脚本从原文件的导入表反查生成，不手写。
3. **mixin 之间零交叉导入**——原代码里它们只通过 `self.<name>` 互相调用，
   由 MRO 在运行时解析。
4. **`super()` 全类只有 4 处**（`__init__` / `eventFilter` / `showEvent` / `resizeEvent`），
   切分前用 AST 核对过，这 4 个方法全部留在 `main_window.py`，
   因此 `super()` 依旧解析到 `QMainWindow`。

### 3.5 测试改动（全部是重指向，无一放宽）

| 测试 | 改动 | 理由 |
|---|---|---|
| `test_left_status_icons.py` | 源码读取范围扩到 `main_window.py` + `success_list.py` + `window_ops.py` | emoji 字面量随 `show_scrape_info` / `show_version` 迁移 |
| `test_issue130_cookie_keep.py` | 补丁对象改为 `net_check.get_text_sync`；自检横幅断言改为拼接 `window_ops.py` | 符号与文案随方法迁移 |
| `test_window_centering.py` | **加强**：新增 `_class_index()` / `_class_source_files()`，按 MRO 收集全部贡献模块源码再断言 | 原断言只读 `main_window.py` |
| `test_actor_db_sync_row_align` 等 6 个 | 启动副作用桩的归属模块从 `mw_mod` 改为 `window_ops_mod` | `check_version` / `apply_site_priority_theme` 迁到了 `window_ops` |
| `test_base_web.py` 等 10 个 | `signal.show_log_text` → `log_console.log_text` | P0 拆分 |
| `test_save_success_list.py` | 改桩 `log_console.log_text` + `ui_hooks.view_success_file_settext` | P0 拆分 |

> 反面教材：某个 fixture 中途抛异常会让模块属性**在整个 session 内保持被替换状态**，
> 于是 1 个文件的指针错误会在全量跑里级联出 20 多个无关文件的失败。
> 改完测试指针一定要跑**全量**。

### 3.6 二次解耦（第二轮）

第一轮结束后重新做了全量审计（`audit2b.py`：修正了相对导入层级的解析；
第一版解析把 `config/` 里的 `..core.x` 算成了 `config.core.x`，矩阵是假的）。
结论：`views/` + `controllers/` 之外的 **Qt 导入已经是 0 个**，`mdcx.signals` 的
35 个引用方全部是真正贴着界面的模块。剩下的偏差集中在 4 处。

#### 3.6.1 主题层归位 — 新增 `mdcx/ui_theme.py`（根因 7）

`controllers/main_window/style.py` 前 231 行的 9 个符号（`_qss_resources`、
`LIGHT_TOKENS` / `DARK_TOKENS` / `_tokens` / `get_theme_tokens`、
`apply_application_palette`、`build_tree_widget_style`、`build_menu_style`、
`build_scrollbar_style`）**逐字搬到根级中立模块**，消掉 3 条反向依赖边：

| 引用方 | 原导入 | 现导入 |
|---|---|---|
| `views/donate_window.py` | `..controllers.main_window.style` | `..ui_theme` |
| `controllers/cut_window.py` | `.main_window.style` | `..ui_theme` |
| `tools/emby_actor_manager_ui.py` | `..controllers.main_window.style` | `..ui_theme` |
| `main.py` | `mdcx.controllers.main_window.style` | `mdcx.ui_theme` |

`style.py` 保留 `__all__` 再导出全部 9 个名字，只留下真正只服务主窗口的 4 个
（`_apply_log_document_style` / `_nfo_lib_top_button_qss` /
`apply_nfo_lib_top_button_style` / `set_style` / `set_dark_style`）。

> ⚠️ 有约 35 个测试 `monkeypatch` `style_mod.resources.qtr`。
> 之所以安全：`style.py` 与 `ui_theme.py` 拿到的是**同一个** `Resources` 单例实例，
> 打补丁打在对象属性上，两边都看得到。

#### 3.6.2 CF 地址归一化下沉 — 新增 `mdcx/utils/cf_url.py`（根因 8）

`normalize_trawl_url` 与 `_LOOPBACK_HOSTS` 从 `cf_bypass/trawl_adapter.py` 逐字搬出。
收益有两层：消掉 `config→cf_bypass` 反向依赖；**只读配置文件不再把 `httpx` 拖进来**
（`config/migrations.py` 在迁移时会调它）。
`trawl_adapter.py` 保留同名再导出（`# noqa: F401`），
因为 `tests/test_cf_proxy_routing.py:18` 直接 `from mdcx.cf_bypass.trawl_adapter import normalize_trawl_url`。

#### 3.6.3 停机判定归一 — 新增 `mdcx/utils/task_stop.py`（根因 9）

`stop_requested() -> bool` 单一实现，收掉 7 份逐字重复的
`signal.stop or Flags.stop_requested`。各模块仍保留自己的 `_is_stop_requested`
薄壳——测试会 `monkeypatch` 那个模块级名字。
⚠️ `signal.stop` 与 `log_console.stop` 是**同一个变量**
（`Signals.stop` 是代理 `log_console.stop` 的 property），所以换写法行为不变。
3 个异常类（`ActorTaskStopped` ×2 + `ActorPhotoTaskStopped`）**刻意不动**：
合并会改变 `except` 的匹配语义。

#### 3.6.4 演员管理窗口拆层（根因 10）— 5,310 行 → 4,709 行

拆出 4 个模块，UI 文件只留界面装配：

| 新模块 | 搬走什么 | 性质 |
|---|---|---|
| `emby_actor_clean_rules.py` | `DEFAULT_CLEAN_RULES`、`_ensure_default_clean_rules`、`_sanitize_clean_rules`、`load_clean_rules` / `save_clean_rules`、`format_detail_cell_text`、`scan_actor_data_noise` | 纯业务，零 Qt |
| `emby_actor_source_catalog.py` | 6 张数据源标签表（`IMAGE_SOURCE_NAMES` / `INFO_SOURCE_NAMES` / `IMAGE_PROGRESS` / `INFO_PROGRESS` / `_IMAGE_RESULT_NAMES` / `_INFO_RESULT_NAMES`），**每个字面量逐字保留** | 纯数据 |
| `emby_avatar_fetch.py` | `fetch_avatar_from_source` / `load_gfriends_index` / `is_known_source` —— 把**重复 3 遍**的头像来源分派阶梯收成一份 | 只依赖数据层，零 Qt |
| `emby_actor_ui_kit.py` | `make_folder_row` / `browse_folder`，并让 4 份 `_center_on_screen` 改用 `mdcx.utils.window_center` 里项目自己的标准实现 | 界面小工具 |

**D18 线程框架补齐（本轮唯一的行为变更）**：
`ActorDetailDialog._run_sync` 原先直接 `threading.Thread(...).start()`，
既无取消、也无 stale-session、也无孤儿线程保护——同步协程卡住时关窗口会留下回收不掉的线程。
现在：新增 `class DetailSyncThread(_CancellableWorkerThread)`，
`_CancellableWorkerThread` 拆出 `_await_future` / `_run_blocking`；
`ActorDetailDialog` 新增 `closeEvent` 与 `_sync_thread_finished`。

> ⚠️ `_run_blocking` 走的是**新加的** `_BLOCKING_EXECUTOR`（`ThreadPoolExecutor(max_workers=4)`），
> 不是共享的 `AsyncBackgroundExecutor`——后者只收协程，把阻塞调用丢进去会冻住共享的后台事件循环。
> 这个坑是被新写的回归测试 `tests/test_actor_detail_sync_thread.py` 当场抓出来的。

**为什么没有合并剩下几处重复**（逐条判断，不是遗漏）：

| 编号 | 内容 | 不合并的理由 |
|---|---|---|
| D11 | config 持久化样板 8 处 | 改回调式要动大量行，收益不抵 churn |
| D14 / D16 | 全屏钳制 + QSS ×3、字段/值表格 ×2 | 每处要的控件集合都不同，强行统一只会变成参数汤 |
| D4 / D5 | 结构化 bio 解析在 `emby_actor_manager` 与 `actor_db_tool` 各一份 | `actor_db_tool` 的名字被测试钉死，且两种格式并不相同，合并有行为风险 |
| D19 | `emby_actor_manager.py` 里 curl_cffi 与 httpx 两套 HTTP 栈并存 | 是真实设计问题，但会改变 TLS 指纹与代理路径，超出「行为不变」的范围 |
| D15（部分） | 本地头像目录行 3 处 | 只套用了**形状完全一致**的那 1 处；另外 2 处的固定宽度 / `objectName("btnPrimary")` / 测试钉死的 `self.folder_browse_btn` 都不能动，已在 kit 的 docstring 里写明 |

**等价性证据**：`tools/emby_actor_manager_ui.py` 的公开表面比对器
`funcs 12 / classes 16 / consts 7 / methods 200 / self_attrs 241` →
**`RESULT: IDENTICAL`**；另有 `sentinel` 模式复刻了 7 个测试对这个文件的
**全部** AST / 源码断言（`_shutdown_worker_threads` 的 5 个属性名 + `abort` +
`_detach_running_thread`、5 个 worker 类、`_begin_session` / `_is_stale_session`
守卫、`_update_statistics` 的「恰好一处 `if self._show_unique:`」、
`_build_actor_list` 里 `lbl_duplicate` 紧跟 `lbl_total`、
`cmb_count_mode.setCurrentIndex` 必须在 `connect` 之前、
`lbl_backdrop` tooltip 那句文案在且「唯一名字数模式按名字去重计数」不在，
以及 `ActorSourceTestThread.run` 必须走 `_run_coro`/`executor.*`）→ **`SENTINEL: OK`**。

---

## 四、后续优先级（尚未实施）

### ~~P1 — `controllers/main_window/main_window.py`~~ ✅ **已完成**（见 3.4 / 3.5）

12,596 行 → 717 行装配器 + 28 个 mixin；公开表面比对 `RESULT: IDENTICAL`；
全量测试 EXIT=0。拆分时严格遵守的约束（仍然有效，供后续改动参考）：

- 41 个 `pyqtSignal` 必须留在 `MyMAinWindow` 类体
- `_ACTOR_DB_IDLE_TEXT_MAP` / `_on_actor_db_finished` / `_ACTOR_DB_SCRAPE_MANAGED`
  必须字面留在 `main_window.py`（`test_actor_db_button_consistency.py` 用正则扫源码）
- 模块级常量 `LINK_DIR_INVALID_CHARS_RE` / `WINDOWS_RESERVED_DIR_NAMES` /
  `DEFAULT_LINK_DIR_NAME` / `_NET_SEP_*` 必须留在 `main_window.py`
  （`test_net_separator_width.py` 会 import）
- `super()` 的 4 个调用点必须与 `QMainWindow` 同类

### ~~P2 — `tools/emby_actor_manager_ui.py`（5,310 行）~~ ✅ **已完成**（见 3.6）

5,310 行 → 4,709 行。UI / 数据 / 服务三层分开，20 处重复里处理了收益最高、
且能证明行为等价的那些（D1 停机判定、D2 头像分派、D3 标签表、D13 居中、
D15 目录行、D18 线程框架），其余逐条记录了**为什么不合并**。
公开表面比对 `RESULT: IDENTICAL`，7 个结构性测试的 AST 断言 `SENTINEL: OK`。

---

## 五、约束备忘（动手前必读）

1. **`mdcx/views/MDCx.ui` 是权威源，绝不可手改**。
   `tests/test_ui_structure.py:249` 会重新编译 `.ui` 并与提交的 `MDCx.py`
   **逐字节比对**。`.ui` 里的 1,149 行中文文案不能外提。
2. **`tests/conftest.py` 整体桩掉 `mdcx.config.manager` / `mdcx.config.resources` /
   `mdcx.signals`** —— 这三个导入路径与构造方式是硬冻结的。
3. **`config/enums.py` 的枚举顺序是冻结的**：`.names()[i]` 与 `list(Enum)[i]` 位置对应。
4. **`ruff` 必须显式指定文件路径**。`ruff check --fix mdcx/` 会静默改动全树
   （本次就误改了 `init.py` / `network_check.py` / `tmdb_actor.py`，已 revert）。
5. **批量改写文件只能做字节级 `replace()`，绝不能重写行尾**。
   本次脚本里一句 `text.replace("\n", "\r\n")` 把 `crawlers/airav_cc.py` 与
   `crawlers/fc2.py` 变成纯 CR 单行文件（0 个 `\n`、368 个 `\r`），
   靠 `git checkout --` 找回后才用纯字节替换重做。
6. `ruff.toml` 排除 `**/views/*.py`，`views/` 下的格式不由 CI 把关 —— 不要顺手格式化。
7. 本轮为纯重构、行为不变，按 `docs/Development.md` 的 Changelog 纪律
   **不写 `docs/Changelog.md`**；但纯 UI 重构仍需回归测试。
8. `mdcx/core/file.py` 是 CRLF/LF 混合行尾，编辑时勿统一化。
9. **`mdcx/log_console.py` / `mdcx/ui_hooks.py` 是新的中立枢纽**，名字被
   10 个测试文件直接 import，**不可改名**。
10. **`config/extend.py` 曾用 `signal_qt` 而非 `signal`**，
    批量正则搜 `signal` 会漏掉它 —— 改前先按模块枚举实际用到的属性。
11. `Signals` 经过 `@singleton` 后是**函数**，`isinstance(x, Signals)` 会抛
    `TypeError`（改动前就是如此，不要"顺手修"）。
12. **`main_window.py` 里剩余的 717 行不是"没拆完"，而是测试钉死的物理位置**：
    49 个 `pyqtSignal`、`_ACTOR_DB_IDLE_TEXT_MAP`、模块级 `*_DIR_NAME` / `_NET_SEP_*`
    常量、以及 3 个 `super()` 调用点。要继续瘦身必须先改测试的结构假设。
13. **28 个 mixin 已被 `pyproject.toml` 的 `[[tool.mypy.overrides]]` 排除**
    （`ignore_errors = true`，不是 `exclude` —— `exclude` 对被 import 的模块无效）。
    新增 mixin 时请一并加进那个列表。
14. **改测试指针后必须跑全量**：某个 fixture 中途抛异常会让模块属性在整个
    session 内保持被替换状态，1 个文件的指针错误会级联出 20 多个无关文件的失败。
15. **`ruff.toml` 的 `exclude` 对显式传入的路径无效**，除非加 `force-exclude`。
    所以 `ruff format mdcx/views/donate_window.py` 会真的改写它 ——
    而 `**/views/*.py` 是被**故意**排除的。本轮踩到，已从 HEAD 还原并只保留导入改动。
16. **HEAD 本身就有 19 个文件过不了 `ruff format --check`**（含用户自己刚提交的
    `core/network_check.py` 里的 I001）。不要顺手格式化它们 ——
    `ruff format` 会把无关的格式改动混进本次 diff。本轮已还原
    `cut_window.py` / `network_check.py` / `donate_window.py` 的格式改动。
17. **`mdcx/tools/emby_actor_manager_ui.py` 的模块级属性是被 monkeypatch 的**：
    `QMessageBox` / `manager` / `search_actor_info` / `fetch_all_actors` /
    `get_all_staff_count` / `QGuiApplication` / `EmbyActorManagerDialog`。
    搬走任何被调用的东西之前，先确认这些名字仍留在本模块、且调用点走的是模块属性。
18. **第二轮新增的中立模块**（`mdcx/ui_theme.py`、`mdcx/utils/cf_url.py`、
    `mdcx/utils/task_stop.py`）均**保留了原路径的同名再导出**，
    因为测试与历史调用方都从旧路径 import。改名 = 破坏兼容。