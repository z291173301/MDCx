Token烧了太多入不敷出了，连续高强度更新两个月时间烧了几百亿Token精力投入太多没有赞助没有回报，软件转收费授权模式了,至今为止只收到一笔共100元捐款，500元一个授权绑定机器，转授权模式后功能将继续更新，如果有谁闲的蛋疼举报则软件随时下架，反正我自己有源码随便改无限使用
</table>
<img width="1280" height="680" alt="image" src="https://github.com/user-attachments/assets/00d89bd5-6089-44a8-8fbd-f1de02710cfe" />

# 工作流说明

本仓库的构建与发版流程已改造：私有开发仓 MDCx-Dev 负责构建，使用私有仓源代码（通过 checkout 私有仓代码）构建后直接发布到本公开仓库，不再需要原来的 mirror-release 环节。构建时使用 MDCX_SOURCE_TOKEN 和 MDCX_SOURCE_REPO（变量与 Secret）实现跨仓库发布。完整的 .github/workflows 文件在私有仓中维护。
