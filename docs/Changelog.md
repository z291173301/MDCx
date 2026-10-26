# Changelog

按日期分段记录（`## YYYY-MM-DD`，新 → 旧）。每条只写「做了什么 / 改了什么 / 修了什么」，原因与排查过程见 `docs/Development.md` 与 `DADA/MEMORY.md`。

## 2026-10-26

### 高级页「隐藏图标」行右侧新增「设备编号」按钮（导出设备 ID 的 txt）

- 设置 → 高级 的「隐藏图标：」行末（「隐藏菜单图标」右侧）新增「设备编号」按钮：样式与宽度同「导入账单」（共用 `ui_theme.build_setting_button_style`，同一套自然宽 92~128 与窄窗收窄公式），纵向与「隐藏菜单图标」同行同高、间距 10px。按钮同样是 `gridLayoutWidget_20` 的绝对定位游离子项，几何由 `_sync_advanced_page_device_id_button` 每遍按「隐藏菜单图标」的实测右缘钉死，不进 `horizontalLayout_dock`、不改任何既有控件坐标。
- 点击后取本机设备编号（`mdcx/utils/device_id.py`）并弹保存对话框让用户选 txt 存放位置，默认文件名 `设备编号_<计算机名>.txt`、默认落在桌面；正文四行「设备编号 / 系统 / 计算机名 / 生成时间」，UTF-8 写出。
- 取号口径与系统「关于」页一致：Windows 11 取 `HKLMSOFTWAREMicrosoftSQMClient` 的 `MachineId`（即「设置→系统→关于→设备 ID」，带花括号），读不到退回 `CryptographyMachineGuid` 或 DMI 整机 UUID；macOS 取 `ioreg` 的 `IOPlatformUUID`（硬件 UUID），退回 `system_profiler`；Linux / Ubuntu 取 `/etc/machine-id`，退回 `dbus` 的 machine-id 或 `/sys/class/dmi/id/product_uuid`。全本地读取、不联网，结果进程内缓存。
- 与「导入账单」不同：本按钮不绑定机器——它就是给用户导出编号、发给作者申请授权用的，人人都该点得到。
- 测试：`tests/test_device_id_button.py`（按钮在「隐藏菜单图标」右侧不重叠且同行同高、宽度与「导入账单」一致、未绑定机器仍显示、显隐前后既有控件坐标不变、导出写 txt / 用户取消 / 取不到编号三条路径、Windows 取号与注册表值一致）。

### 赞助窗口接入微信 / 支付宝账单：新增「导入账单」入口（绑定本机 CPU 编号）

- 设置 → 高级 → 高级功能 的「隐藏信息管理」右侧新增「导入账单」按钮：左缘与「显示字段内容信息」严格上下对齐（两者 x 相等）、纵向与「隐藏信息管理」同行同高，「显示字段内容信息」位置保持不变。按钮是 `gridLayoutWidget_20` 的绝对定位游离子项、不进任何布局（与 `comboBox_actor_type` 同一套路子），几何由 `_sync_advanced_page_bill_button` 每遍按两个锚点的实测坐标钉死，因此不会把整页列宽连同锚点一起推走。
- 入口绑定本机 CPU 编号：`mdcx/utils/machine_binding.py` 取 `Win32_Processor.ProcessorId`（先 wmic，Win11 上退回 PowerShell 的 `Get-CimInstance`）算 SHA-256 与内置名单比对，仓库里只存哈希。探测在后台线程跑（PowerShell 冷启动约 1 秒，不能卡首屏），结果由 QTimer 轮询；未绑定的机器按钮从头到尾不显示，点击入口也会再校验一次。
- 点击后选 xlsx 账单，`mdcx/tools/bill_import.py` 按列名（不按列序号）识别三类账单：微信支付账单明细（`收/支` + `金额(元)`）、微信经营账户明细（`收支类型` + `明细名称` + `金额`）、支付宝交易记录明细（`收/支` + `金额`）。只统计收入——支出、退款、不计收支全部跳过；捐助者名优先取「明细名称」里「来自 xxx」的尾巴（经营账户账单的写法）。
- 记录落盘 `resources/donate_records.json`（随包分发，所有用户都能在赞助窗口看到）与 `userdata/donate_records.json`（打包运行时 `_MEIPASS` 只读，用户数据目录那份负责本机即时生效）；读取时两份取并集并按「姓名+时间+金额」去重。
- 赞助窗口榜单填数：新人榜 = 最新 10 个捐助者（时间倒序）、土豪榜 = 金额最大的 10 个人（金额倒序），两个榜都按捐助者去重（同一人只占一行，新人榜留最近一笔、土豪榜留最大一笔）。日期列只有 94px，故今年的记录显示成 `10-25 20:23`、跨年的显示 `2026-10-25`，完整时间进单元格 tooltip。
- 已导入 `经营账户明细20261001-20261026.xlsx`（1 笔收入：z*n / ¥100.00 / 2026-10-25 20:23:18）。
- 测试：`tests/test_bill_import_parse.py`（三类账单解析、收入过滤、榜单排序去重、落盘并集）、`tests/test_donate_window_ranks.py`（榜单填数与异常降级）、`tests/test_bill_import_button_align.py`（按钮对齐、未绑定不显示、显隐前后既有控件坐标不变）、`tests/test_bill_import_flow.py`（点按钮 → 选文件 → 落盘 → 赞助窗口出榜的端到端）。

## 2026-10-25

（内容过大，已截断为占位内容，完整内容在本地文档中）
