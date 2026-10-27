# MDCx

![Crawlers](https://img.shields.io/badge/Sites-47-brightgreen.svg) 

![License](https://img.shields.io/badge/License-GPLv3-blue.svg) 

![python](https://img.shields.io/badge/Python-3.15+-3776AB.svg?style=flat\&logo=python\&logoColor=white) 

![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

<p align="center"><b>如果你觉得不错赞助500元获取授权，谢谢！ 😊</b></p>

<table align="center">  
  <tr>  
    <td align="center"><img src="https://github.com/z291173301/MDCx/raw/main/resources/Img/donate-wechat.jpg" width="180" alt="微信">   <sub>微信</sub></td>  
    <td width="40"></td>  
    <td align="center"><img src="https://github.com/z291173301/MDCx/raw/main/resources/Img/donate-alipay.jpg" width="180" alt="支付宝">   <sub>支付宝</sub></td>  
    <td width="40"></td>  
    <td align="center"><img src="https://github.com/z291173301/MDCx/raw/main/resources/Img/donate-alipay-redpacket.jpg" width="180" alt="支付宝红包">   <sub>支付宝红包</sub></td>  
  </tr>  
</table>

烧了太多Token入不敷出了，两个月连续高强度更新烧了几百亿Token投入太多没有赞助没有回报，至今为止只收到一笔共100元捐款，时间精力投入太多免费难以为继，软件转收费模式了，500元一个授权绑定机器，转授权模式后软件各项功能将继续更新，各种问题继续修复，如果有谁闲的蛋疼举报则软件随时下架，反正我自己有源代码随便修改无限使用

![image](https://github.com/user-attachments/assets/6e4a9ab3-8c28-4714-af0e-be41d5e71e67)

## MDCx 是什么

MDCx是一个桌面工具，自动从47个网站抓取视频文件的元数据（标题、演员、封面、简介等），生成标准的.nfo文件和整理好的文件夹，给Emby、Jellyfin、Kodi这类媒体服务器直接用。

一句话：把一堆乱七八糟的视频文件，变成媒体服务器能认的整齐资料库。

## 快速安装

从[GitHub Releases](https://github.com/cdlongbow/MDCx/releases)下载对应系统的安装包或可执行文件，Linux首次运行前执行`chmod +x MDCx`，再运行`./MDCx`。

详细安装说明：[docs/Install.md](docs/Install.md)

## 第一次使用

看这篇5分钟上手指南：[docs/QuickStart.md](docs/QuickStart.md)

## 文档导航

| 文档                                                      | 适合谁看              | 内容                        |
| ------------------------------------------------------- | ----------------- | ------------------------- |
| **[使用Wiki](https://github.com/cdlongbow/MDCx/wiki)**   | **新用户先看这里**       | 三分钟上手、常见问题FAQ（90%问题有答案） |
| [QuickStart.md](docs/QuickStart.md)                     | 所有人               | 5分钟上手，完成第一次刮削            |
| [Install.md](docs/Install.md)                           | 需要安装的人            | 系统要求、Release/源码两种安装方式     |
| [Features.md](docs/Features.md)                         | 想了解能做什么的人         | 全部功能、47个网站列表、六种刮削模式      |
| [User\_Guide.md](docs/User_Guide.md)                    | 日常使用的人            | 完整使用手册、常见问题、实际场景          |
| [Configuration.md](docs/Configuration.md)               | 想调设置的人            | 每个配置项是干什么的                |
| [Changelog.md](docs/Changelog.md)                       | 关注版本更新的人          | 每个版本改了啥                   |
| [Development.md](docs/Development.md)                   | 想改代码的人            | 项目架构、爬虫开发、测试、代码规范         |
| [Javdb\_App\_Signature.md](docs/Javdb_App_Signature.md) | 想改JavDB App爬虫的人 | JavDB App API签名机制与逆向域知识  |
| [Male\_Actor\_List.md](docs/Male_Actor_List.md)         | 想维护男演员名单的人        | 男演员名单格式与维护说明              |

## 核心特色

- **47个网站爬虫** — 有码、无码、FC2、国产、欧美全覆盖，部分站点免CF直连
- **智能番号识别** — 自动判断番号类型（有码/无码/个摄/国产传媒/欧美视频）
- **标准文件生成** — 30+元数据字段，Emby/Jellyfin/Kodi通用
- **多引擎翻译器** — Google、Bing、Baidu、DeepL、DeepLX、LLM共6种
- **封面图片处理** — 人脸裁剪、封面水印、Amazon优选高清封面、官方网站图源兜底（DMM高清封面自动学习厂牌前缀+MGStage素人高清海报）、JavDB系图源无水印原图（App CDN加密流自动解密）、海报图超分辨率（Real-ESRGAN 4X，低清封面自动放大补清）
- **演员名数据库** — Excel数据库+TMDB/Wikidata/Gfriends多源补全
- **头像信息管理** — 自动同步演员信息和头像（Emby 演员管理工具支持最大化/拖拽缩放，默认适配屏幕）
- **网络自检标注** — 检测网络页结果着色+按状态复制诊断报告；设置页站点下拉框回显最近一次自己网络的实测状态（✅可连通/⚠️需关注/❌连不通，悬停看检测时间与路由）；代理分流可选「全部走代理」交给Clash类软件裁决
- **异步并发刮削** — 同时刮多个文件，不卡界面
- **自动绕过CF墙** — 支持TRAWL/FlareSolverr外部CF服务自动绕过防护页；JavLibrary站专属Selenium+Edge headless fallback；部分站点免CF通道（JavDB_API、JavDB_APP、Missav_API、R18.dev、TheJavDB）

## 开发者

```bash
git clone https://github.com/cdlongbow/MDCx.git
cd MDCx
uv sync --dev
uv run python main.py
```

推送前自检：

```bash
git config core.hooksPath .githooks   # 一次性：启用 pre-push 自动快速自检
uv run check --skip-hook-install              # 快速门禁，同 pre-push（ruff + mypy + 线程安全）
uv run check --skip-hook-install --with-tests # 追加全量 pytest，想在推送前跑全量时用
```

## 贡献与提报

- 提Bug/功能请求请使用[Issue 模板](../../issues/new/choose)，一个议题说一件事，附现象、影响与复现步骤。
- 使用AI辅助撰写Issue或PR的，请阅读并按[.github/AI\_POLICY.md](.github/AI_POLICY.md)披露使用程度；是否采纳以代码与复现证据为准。
