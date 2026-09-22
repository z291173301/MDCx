# 男优名单 (male_actors.txt)

内置男优名单 `resources/userdata/male_actors.txt`，用于演员库的男优过滤（前置筛选）与存量清洗（剔除男演员）。

## 数据来源

名单从 **avdanyuwiki.com**（男性 AV 演员资料站）的作品 JSON 数据中提取。数据按年份分文件，命名形如 `2024_11090_avdanyuwiki.com.json`，每个文件是一个作品数组，作品记录含：

```json
{
  "banko": "1fns00211",
  "title": "...",
  "actress": "八蜜凛 女神ジュン",
  "actor": "北山シロ",
  "date": "2026/06/18",
  "director": "...",
  "maker": "FALENO",
  "tag": "..."
}
```

其中 `actor` 字段即该作品出演的男优名单。

## 清洗规则

原始 `actor` 字段含有大量噪声，提取需经过以下处理：

| 规则 | 说明 |
|---|---|
| Token 拆分 | 按逗号/顿号/斜杠/竖线/空白拆分；中文括号转半角后，括号内外分别提取 |
| 后缀清理 | 去除 `×`/`☓`（已故标记）、`？`/`。` 等标点后缀 |
| 超长剔除 | 长度 > 8 的 token 剔除（多为两个名字被漏分隔的合并名，如 `森林原人桜井ちんたろう`） |
| 标签黑名单 | 剔除混入的标签/场景词（主観、完全主観、素人、覆面、モザイク、触手 等） |
| Actress 交叉验证 | 某名在 `actress` 字段出现次数 ≥ actor 次数×0.5，或 actor≤3 但 actress>0，判定为女优/中性名剔除（宁漏勿误删） |
| AVdb 权威验证 | 低频两字名（actor≤3）仅保留被 AVdb actor-mapping 收录者 |

## 重新生成

```bash
uv run python scripts/build_male_actor_list.py \
  --json-dir /path/to/jav_db1 \
  --json-dir /path/to/jav_db2 \
  --avdb-xml /path/to/actor-mapping.xml
```

脚本输出到 `resources/userdata/male_actors.txt`。参数：

- `--json-dir`：含 `*_avdanyuwiki.com.json` 的目录，可多次指定
- `--json`：单个 JSON 文件，可多次指定
- `--avdb-xml`：AVdb actor-mapping.xml（可选，用于低频两字名验证与覆盖检查）
- `--output`：输出路径（默认 `resources/userdata/male_actors.txt`）

## 代码集成

- `mdcx/tools/actor_db_tool.py` 中的 `is_male_actor(name)`：按名单判断演员是否为男优（casefold 精确匹配）
- `sync_from_avdb(..., filter_male=True)`：同步时命中名单即跳过（不依赖 TMDB）。注：AVdb 数据质量差，「从 AVdb 同步」GUI 入口已在 v2.0.5 移除，该函数保留供脚本/测试调用
- `clean_male_actors()`：存量清洗时名单命中即删除（含无 tmdbid / TMDB gender=0 的男优）

## 注意事项

- 名单匹配为**精确匹配**（整个名字），不匹配别名/部分名，避免误删。
- 名单原则：**宁漏勿误删**。混入女优会误删女优（灾难），漏掉小众男优仅影响覆盖。
- 女优名误入名单的典型场景：レズ片、SILK 女女片把女优同时填进 `actor` 字段。
