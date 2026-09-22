# TRAWL Windows 便携版使用指南

## 快速开始

### 1. 下载

从 [Releases](https://github.com/cdlongbow/mdcx-diy/releases) 下载最新版本的 `trawl-portable-*-windows.zip`

### 2. 解压

```powershell
# 建议解压到 Program Files 或用户目录
Expand-Archive -Path "trawl-portable-1.4.0-windows.zip" -DestinationPath "C:\Tools\"
cd C:\Tools\trawl-portable-1.4.0-windows
```

### 3. 启动

双击 `start-trawl.bat`

**首次启动**会：
- 检查 Bun 运行时（如有需要运行 `download-bun.bat`）
- 校验依赖完整性（优先使用包内自带源码，完全离线）
- 检查 Camoufox 浏览器（从 `.cache/camoufox` 加载）
- 启动服务，监听 `http://localhost:8191`

**预期输出**：
```
[api] TRAWL starting on :8191  (pool: 1 browsers)
[api] session cache connected  (Tier 2 fast-path enabled)
```

## 配置 MDCx

1. 打开 MDCx → 设置 → 网络
2. 在 "外部 CF 服务" 输入框中填写 TRAWL 服务地址：`http://localhost:8191`
3. 右侧后端类型保持默认 `trawl`（走 TRAWL 原生 `/scrape` 接口）
4. 保存设置

> **注意**：请填写 TRAWL 的**根地址**（如 `http://localhost:8191`），**不要**填写 `/v1` 路径。
> MDCx 会在本地自动拉起协议适配层，把内部请求翻译成 TRAWL 的 `/scrape` 接口，
> 填 `/v1` 反而会导致健康检查失败（MDCx 检测的是 `/cookies`/`/html`/`/mirror` 端点）。

> 若你用的是原生 **FlareSolverr**，在后端类型下拉框选择 `flaresolverr`，
> 适配层会改走 FlareSolverr 的 `POST /v1` 兼容接口。

## 稳定性优化

### 内置 Redis（自动生效）

便携包已内置 Redis，`start-trawl.bat` 启动时自动拉起（端口 6380），为 TRAWL 启用
**Tier 2 会话缓存**：同一域名第二次起的请求复用已解出的 cf_clearance cookie，不再重复
解挑战，显著提升速度与稳定性。启动日志出现
`session cache connected (Tier 2 fast-path enabled)` 即生效。

### 内置补丁（自动生效）

便携包源码打包时已应用 `trawl-goto-timeout.patch`，把 TRAWL Tier3/4 的页面加载
超时上限从 30s 提升到 90s，改善 JS 渲染站点（如 lulubar 搜索页）的挑战通过率。
`start-trawl.bat` 启动时还会检测包内 `trawl-goto-timeout.patch`，对未应用补丁的
源码（如用户单独 clone 的源码）兜底应用；已应用或无法应用时自动跳过。

### 浏览器池

默认 `BROWSER_POOL_SIZE=2`（稳定性/内存折中）。内存充裕可编辑 `.env` 提高（如 3），
内存紧张可降到 1。

> 若内置 Redis 启动失败（端口被占用等），TRAWL 会以无缓存模式运行，功能不受影响，
> 只是每个域名首次请求较慢。

## API 端点

| 地址 | 说明 |
|------|------|
| `http://localhost:8191/` | 首页 |
| `http://localhost:8191/health` | 健康检查 |
| `http://localhost:8191/v1` | FlareSolverr 兼容 API |
| `http://localhost:8191/scrape` | 原生 API |

### 测试示例

```bash
# 健康检查
curl http://localhost:8191/health

# 测试 Cloudflare 绕过
curl -X POST http://localhost:8191/v1 `
  -H 'Content-Type: application/json' `
  -d '{"cmd":"request.get","url":"https://lulubar.co","maxTimeout":60000}'
```

## 常见问题

### Q: 启动失败，提示 "Bun not found"？
A: 运行 `download-bun.bat` 下载 Bun 运行时

### Q: 启动失败，提示 "Camoufox not found"？
A: 
1. 检查 `.cache/camoufox` 目录是否存在
2. 如不存在，手动下载：
   ```powershell
   bunx camoufox-js fetch
   ```

### Q: 端口 8191 被占用？
A: 编辑 `.env` 文件，修改：
```
PORT=8192
```
然后更新 MDCx 配置为 `http://localhost:8192/v1`

### Q: 启动慢（>2分钟）？
A: 正常。首次启动需：
- 加载 Camoufox 浏览器 (~30s)
- 预热浏览器池 (~30s)
- 建立 Redis 连接 (~5s)

### Q: 内存占用高？
A: 编辑 `.env`，减少浏览器池：
```
BROWSER_POOL_SIZE=1
```

## 目录结构

```
trawl-portable-1.5.0-windows/
├── start-trawl.bat          # 启动脚本
├── download-bun.bat         # Bun 下载脚本
├── trawl-goto-timeout.patch # 稳定性补丁（Tier3/4 超时 30s→90s）
├── README.md                # 本说明
├── .env                     # 配置文件
├── .env.example             # 配置示例
├── bun/                     # Bun 运行时 (~50MB)
│   └── bun.exe
├── redis/                   # 内置 Redis（会话缓存，自动启动）
│   └── redis-server.exe
├── .cache/
│   └── camoufox/            # Camoufox 浏览器 (~663MB)
├── apps/                    # TRAWL 源码（api 应用）
├── packages/                # TRAWL 源码（共享包）
└── node_modules/            # 依赖（各应用局部依赖在 apps/api/node_modules）
```

## 系统要求

- **OS**: Windows 10/11 (x64 或 ARM64)
- **RAM**: 2GB 可用内存
- **Disk**: 1GB 空间
- **Network**: 稳定连接（首次需下载浏览器）

## 更新版本

1. 下载新版本 zip
2. 备份 `.env` 配置
3. 解压覆盖原目录
4. 恢复 `.env` 配置

## 许可

- TRAWL: AGPL-3.0
- Bun: MIT
- Camoufox: MIT

---

原版项目: https://github.com/germondai/trawl
打包维护: https://github.com/cdlongbow/mdcx-diy
