# 工作流说明

本仓库的构建与发版流程已改造：私有开发仓 MDCx-Dev 负责构建，使用私有仓源代码（通过 checkout 私有仓代码）构建后直接发布到本公开仓库，不再需要原来的 mirror-release 环节。构建时使用 MDCX_SOURCE_TOKEN 和 MDCX_SOURCE_REPO（变量与 Secret）实现跨仓库发布。完整的 .github/workflows 文件在私有仓中维护。
