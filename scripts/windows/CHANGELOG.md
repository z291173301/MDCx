# TRAWL 便携包打包变更记录

记录 `scripts/windows/` 打包脚本与 `package-trawl.yml` 工作流的变更。
上游 TRAWL 本体的变更见 [germondai/trawl](https://github.com/germondai/trawl) 的 CHANGELOG。

## 2026-11-07

### Fixed

- GeoIP 数据库（`GeoLite2-City.mmdb`，约 50MB）随包，不再启动时在线下载：
  此前包内缺失该库，`camoufox-js` 在启动时走 `api.github.com` 查
  `P3TERX/GeoLite.mmdb` 的 release，匿名配额易被限流（403），导致浏览器池
  初始化失败、`[api] startup failed: Failed to fetch releases ...`。
  直链下载（`github.com/.../latest/download/...`）不走 API，不受此影响。
- 打包工作流（`package-trawl.yml`）：GeoIP 下载改用 `curl` 断点续传 + 重试，
  失败或小于 45MB 直接中止打包，不再静默产出启动即崩的包；打进包前校验库
  完整，并剔除中断残留的 `*.download` 文件。
- `trawl-start.bat`：启动前预检库是否存在（支持放包根目录/`geoip/` 手动兜底），
  缺失时中文报错并给出下载链接，不再抛堆栈。
- `USAGE.md`：补充该报错的 FAQ 条目。
