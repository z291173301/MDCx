# JavDB App API 签名机制与轮换预案

## 签名算法

每个请求必须携带 `jdsignature` 请求头：

```
jdsignature = "{ts}.{suffix}.{md5(ts + prefix)}"
```

- `ts`：Unix 秒级时间戳
- `prefix`（代码中 `_SIG_PREFIX`）：MD5 盐，128 位 hex 字符串
- `suffix`（代码中 `_SIG_SUFFIX`）：签名中间段固定字符串

实现在 `mdcx/crawlers/javdb_app.py` 的 `make_signature()`。

## 常量来源（逆向推导链）

1. native 层 `SecurityUtil.getSecret()` 读取 APK 自身签名证书，取 DER 前 5 个 hex 字符作为解密 key（防重打包校验）。
2. Dart 层 `getSignature()` 用该 key 对两段 base64 常量做 `MD5(key)` 逐字节减法解密，得到：
   - `STR1` = prefix（MD5 盐）
   - `STR2` = suffix（签名中间段）
3. 最终拼接为 `jdsignature`。

## 服务器校验顺序

统一响应包裹：`{"success": 0|1, "action": <错误动作码>, "message": <提示>, "data": <业务数据>}`。

Query 参数按顺序校验：`platform` → `app_channel` → `app_version` → `app_version_number`，缺一返回 `ParameterInvalid`。

常见错误 action：`InvalidSignature`（签名错误，HTTP 400）、`ParameterInvalid`
（缺参数）、`ResourceNotFound`（资源不存在，HTTP 404）。

## 失效征兆

JavDB App 发新版时可能轮换签名常量（STR1/STR2 内嵌于 APK）。届时所有接口主机会同时返回签名/鉴权类失败：

- HTTP 400（`InvalidSignature`）/ 401 / 403
- 200 响应体含 `ParameterInvalid`、`InvalidSignature`、`Unauthorized` 等错误标记

mdcx 会在三个接口主机全部返回签名类失败时输出明确诊断日志（fail-fast），
而不是笼统的"搜索失败"。

## 轮换应对

1. **优先**：升级 mdcx 到包含新常量的版本。
2. **临时**：不改代码，用环境变量覆盖：

| 环境变量 | 覆盖项 | 默认值来源 |
|---|---|---|
| `MDCX_JAVDB_APP_SIG_PREFIX` | MD5 盐（prefix） | `_SIG_PREFIX` |
| `MDCX_JAVDB_APP_SIG_SUFFIX` | 签名中间段（suffix） | `_SIG_SUFFIX` |
| `MDCX_JAVDB_APP_VERSION_NUMBER` | App 版本号 | `1.9.35` |

空值视为未设置，回落默认值。`network_check` 的连通性检测与爬虫共用
`make_signature()`，环境变量对两者同时生效。

3. 常量轮换后需重新逆向 APK（反编译 libapp.so / libsecurity.so）获取新
   STR1/STR2。逆向工件（反汇编、证书、探测脚本）维护在独立私有仓库，
   不随本项目分发。

## 图片 CDN 与加密流解密

两个图片 CDN 的分工：

| CDN | 内容 | 水印 |
|---|---|---|
| `tp.spfcas.com`（App 专用） | 加密流（`application/octet-stream`） | 无 |
| `c0.jdbstatic.com`（网页版） | 普通 JPEG | 含 javdb.com 水印 |

App CDN 加密流格式（`covers/`、`small_covers/`、`samples/` 路径通用）：

- 首字节为随机 XOR key `K`（每次请求变化）
- 其余字节 = 明文逐字节 XOR `K`
- 解密后明文应以 JPEG SOI（`FF D8`）起始，作为有效性校验

本项目实现（`mdcx/base/web.py`）：

- `is_spfcas_image_url`：按域名判定（路径中段可能随服务端调整变更）
- `decrypt_spfcas_image`：单字节 XOR 解密 + SOI 校验
- `decode_spfcas_image_content`：统一解密入口，非 App CDN 内容原样透传

解密注入于全部图片落盘路径（`MediaResourceContext._fetch_image`、
`download_file_with_filepath`、`download_content_with_filepath`），
下载层透明解密，解密失败按下载失败处理并走后续降级链。

## 安全注意

逆向与验证过程中产生的账号、密码、token 等凭据严禁写入本仓库代码、
文档或测试数据。
