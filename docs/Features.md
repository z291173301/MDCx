# 功能总览

MDCx 支持的功能全景。只想快速上手的话，先看 [QuickStart.md](QuickStart.md)。

## 一、刮削系统

### 自动识别番号

从文件名提取番号（如 `ABP-123.mp4` 或 `ABP-123`），并自动判断类型：

| 类型 | 番号格式 | 例子 |
|------|---------|------|
| 有码 | 英文-数字 | ABP-123、SSIS-456 |
| 无码 | HEYZO-/Carib- 等 | HEYZO-123、Carib-123 |
| FC2 | FC2-PPV-数字 | FC2-PPV-1234567 |
| 国产 | MD-/MKY- 等 | MD-0123 |
| 欧美 | 数字.数字.数字.数字 | 123.45.67.89 |
| 国产短剧 | 无统一番号格式 | （按剧名搜索，如 JavDay，条目只有站内随机 ID）|

### 全部 36 个爬虫

> 「说明」列与软件内「设置→刮削网站」下拉框显示的爬虫定位标签一一对应（取自各爬虫类的 `description`）。

| 爬虫名 | 数据源 | 说明 |
|--------|-------|------|
| DMM | dmm.co.jp | 有码：仅限有码 |
| DMM_API | DMM 官方 Affiliate API | 有码：仅限有码 |
| TheJavDB | thejavdb.net | 有码：仅限有码 |
| JavDB | javdb.com | 综合：有码/无码 |
| JavDB_API | JavDB 镜像站 | 综合：有码/无码 |
| JavDB_APP | JavDB 移动端 API | 综合：有码/无码 |
| JavBus | javbus.com | 综合：有码/无码 |
| JavLibrary | javlibrary.com | 有码：仅限有码 |
| Javlibrary·镜像 | zlibz.com 公布的镜像（默认 www.f101w.com/cn） | 有码：仅限有码 |
| Missav | missav.ws | 综合：有码/无码 |
| Missav_API | Recombee API | 综合：有码/无码 |
| MGStage | mgstage.com | 有码：有码素人 |
| Prestige | prestige-av.com | 有码：有码素人 |
| R18.dev | r18.dev | 有码：仅限有码 |
| Official | 各官网（有码片商） | 官网：有码 |
| Official·10Musume | 10musume.com | 官网：无码 |
| Official·1Pondo | 1pondo.tv | 官网：无码 |
| Official·Caribbeancom | caribbeancom.com | 官网：无码 |
| Official·HEYZO | heyzo.com | 官网：无码 |
| Official·Pacopacomama | pacopacomama.com | 官网：无码 |
| AVBase | av-base.net | 有码：有码素人 |
| FreeJavBT | freejavbt.com | 有码：仅限有码 |
| MyWife | mywife.cc | 独立系列：人妻・熟女（单独指定，不进任何类型组） |
| Getchu | getchu.com | 综合：有码游戏+视频 |
| LibreDMM | libredmm.com | 有码：仅限有码 |
| Xcity | xcity.jp | 有码：仅限有码 |
| AVSOX | avsox.click | 无码：仅限无码 |
| AVMOO | avmoo.shop | 有码：仅限有码 |
| AVEntertainments | aventertainments.com | 无码：仅限无码 |
| AVheat | avheat.shop | 欧美：欧美番号 |
