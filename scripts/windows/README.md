# TRAWL Windows 便携版

基于 [germondai/trawl](https://github.com/germondai/trawl) 的 Windows 便携打包。

## 功能

- 绕过 Cloudflare Bot Management
- 支持 Akamai Bot Manager、Imperva/Incapsula
- 自动解决 CF Turnstile、reCAPTCHA、hCaptcha
- FlareSolverr 兼容 API (`/v1`)
- 原生 API (`/scrape`)
- 内置 Redis 会话缓存（Tier 2 fast-path，自动启动）
- 内置 TRAWL 稳定性补丁（Tier3/4 超时 30s → 90s，自动应用）

## 快速开始

### 1. 下载便携版

从 [Releases](../../releases) 下载 `trawl-portable-*.zip`

### 2. 解压并运行

```
解压到任意目录（如 C:\Tools\trawl）
双击 start-trawl.bat
```

启动时优先直接运行包内自带源码（打包时已应用补丁、依赖已就位），完全离线：
- 校验依赖完整性（毫秒级）
- 自动启动内置 Redis（会话缓存）

仅当包内没有源码时（裸脚本部署），才会克隆 trawl 源码到 `src\` 并安装依赖。

Camoufox 浏览器已随包附带（~663MB），无需在线下载。

### 3. 配置 MDCx

打开 MDCx → 设置 → 网络：

```
外部 CF 服务: http://localhost:8191
后端类型: trawl（默认；原生 FlareSolverr 选 flaresolverr）
```

> **注意**：填写 TRAWL 的**根地址**（如 `http://localhost:8191`），不要填 `/v1` 路径。
> MDCx 会自动在本地拉起协议适配层，把内部请求翻译成 TRAWL 的 `/scrape` 接口
> （或 FlareSolverr 的 `/v1`）；填 `/v1` 会导致健康检查失败（MDCx 检测的是
> `/cookies`/`/html`/`/mirror` 端点）。

## API 端点

| 端点 | 说明 |
|------|------|
| `http://localhost:8191/` | 首页 |
| `http://localhost:8191/health` | 健康检查 |
| `http://localhost:8191/v1` | FlareSolverr 兼容 |
| `http://localhost:8191/scrape` | 原生 API |

## 测试示例

```bash
# 测试首页
curl http://localhost:8191/health

# 测试 CF 绕过
curl -X POST http://localhost:8191/v1 \
  -H 'Content-Type: application/json' \
  -d '{"cmd":"request.get","url":"https://lulubar.co","maxTimeout":60000}'
```

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| 启动失败 | 运行 `download-bun.bat` 重新下载 Bun |
| 浏览器启动慢 | Camoufox 已随包附带，首次启动预热约 30s-1min |
| 端口冲突 | 编辑 `.env`，修改 `PORT=8191` |
| 内存不足 | 编辑 `.env`，减少 `BROWSER_POOL_SIZE=1`（默认 2） |

## 系统要求

- Windows 10/11 (x64)
- 2GB RAM 可用内存
- 1GB 磁盘空间（含 Camoufox）
- 稳定的网络连接

## 与原版的区别

| 特性 | 原版 Docker | 本便携版 |
|------|------------|---------|
| 部署方式 | Docker | 直接运行 |
| Redis | 必需 | 内置（自动启动） |
| 浏览器缓存 | Redis 持久化 | 内置 Redis（会话缓存） |
| 适用场景 | 服务器 | 个人桌面 |

## 许可

- TRAWL: AGPL-3.0
- 本打包脚本: MIT
