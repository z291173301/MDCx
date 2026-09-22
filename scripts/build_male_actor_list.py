"""从 avdanyuwiki 作品 JSON 提取并清洗男优名单，输出 resources/userdata/male_actors.txt。

数据源（任选其一，可同时指定）：
  --json-dir  包含 `*_avdanyuwiki.com.json` 的目录（avdanyuwiki 按年份作品数据）
  --json      单个 JSON 文件路径（可多次指定）

辅助交叉验证源（可选，推荐提供以提高名单质量）：
  --avdb-xml  AVdb actor-mapping.xml（li-peifeng/Jav-Actors-Mapping）。
              用于 (a) 低频两字名仅保留被 AVdb 权威收录者；(b) 校验名单覆盖。

清洗规则：
  1. 拆 token：按逗号/顿号/斜杠/竖线/空白拆分，中文括号转半角后提取括号内外内容。
  2. 去除 ×/☓/？/。 等后缀，剔除超长(>8字)合并名与标签词黑名单。
  3. actress 交叉验证：某名在 actress 字段出现次数 ≥ actor 次数*0.5，或 actor≤3 但 actress>0，
     判定为女优/中性名，从名单剔除（宁漏勿误删）。
  4. 低频两字名（actor≤3）仅保留被 AVdb 映射收录者（如「テツ」）。

用法示例：
  uv run python scripts/build_male_actor_list.py --json-dir /path/to/jav_db1 --json-dir /path/to/jav_db2 --avdb-xml /path/to/actor-mapping.xml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_ROOT / "resources" / "userdata" / "male_actors.txt"

MAX_NAME_LEN = 8

# 混入 actor 字段的标签/分类/场景词黑名单
NOISE_TAGS: set[str] = {
    "主観",
    "完全主観",
    "素人",
    "素人男性",
    "黒人",
    "覆面",
    "艦長",
    "軍曹",
    "汁系",
    "レズ",
    "胸毛",
    "仮面",
    "悟空",
    "蜥蜴",
    "酔拳",
    "真琴",
    "ハメ撮り",
    "素人娘",
    "アナル",
    "男の娘",
    "老女",
    "熟女",
    "魔人",
    "人妻",
    "女子大生",
    "女教師",
    "看護師",
    "モデル",
    "秘書",
    "巨乳",
    "貧乳",
    "痴女",
    "女王様",
    "お姉さん",
    "おじさん",
    "美少女",
    "美女",
    "芸能人",
    "地下アイドル",
    "アイドル",
    "グラドル",
    "素人妻",
    "カメラマン",
    "監督",
    "スタッフ",
    "素人夫婦",
    "自宅",
    "お店",
    "温泉",
    "野外",
    "露出",
    "全裸",
    "乱交",
    "中出し",
    "素股",
    "ASMR",
    "TECH",
    "フェラ特化",
    "女優",
    "男優",
    "AV男優",
    "AV女優",
    "AV",
    "JC",
    "JS",
    "TS",
    "人妖",
    "妖怪",
    "肥満",
    "デブ",
    "スリム",
    "黒肌",
    "坊主",
    "モヒカン",
    "サラリーマン",
    "大学生",
    "浪人",
    "老人",
    "少年",
    "青年",
    "中年",
    "壮年",
    "オジサン",
    "オヤジ",
    "ジジイ",
    "ババア",
    "モザイク",
    "汁系モザイク",
    "アイマスク",
    "女性",
    "男性",
    "バイブ",
    "手コキ",
    "足コキ",
    "パイズリ",
    "単体",
    "企画",
    "シリーズ",
    "専属",
    "デビュー",
    "未満",
    "高画質",
    "顔射",
    "潮吹き",
    "失禁",
    "オナニー",
    "フェラ",
    "イラマ",
    "期間限定",
    "限定",
    "完全主観視点",
    "主観視点",
    "視点",
    "出演",
    "作品",
    "画像",
    "動画",
    "映像",
    "クンニ",
    "手マン",
    "指マン",
    "おちんちん",
    "ちんちん",
    "ペニス",
    "チンポ",
    "ナンパ",
    "素人ナンパ",
    "ギャル",
    "おっぱい",
    "パンツ",
    "スカート",
    "密室",
    "密着",
    "イチャイチャ",
    "初体験",
    "処女",
    "童貞",
    "2人きり",
    "1対1",
    "3P",
    "4P",
    "大量",
    "おまんこ",
    "まんこ",
    "ひまわり",
    "アナルセックス",
    "オラオラ",
    "ぽっちゃり",
    "細身",
    "低身長",
    "高身長",
    "毛深い",
    "ハゲ",
    "目つき",
    "関西弁",
    "ぺろぺろ",
    "エロ",
    "エロス",
    "セクシー",
    "淫乱",
    "ビッチ",
    "パンティ",
    "下着",
    "水着",
    "コスプレ",
    "ロリ",
    "ショタ",
    "おっさん",
    "おじいさん",
    "おばあさん",
    "おばさん",
    "おねえさん",
    "娘",
    "息子",
    "父",
    "母",
    "兄",
    "弟",
    "姉",
    "妹",
    "触手",
    "白髪",
    "黒縁",
    "接写",
    "若手",
    "癖毛",
    "板前",
    "仙人",
    "河童",
    "余裕",
    "穴子",
    "寿司",
    "岩石",
    "天パ",
    "白人",
    "黒子",
}

# 合法名字字符集：日文假名、汉字（含扩展）、ASCII、以及常见连接符
_NAME_CHARS = r"^\w+[\u3040-\u30ff\u4e00-\u9fff\u3400-\u4dbfa-zA-Z0-9·･ー\-]*$"


def split_tokens(raw: str):
    """把 actor/actress 原始字段拆成名字 token。

    处理：中文括号转半角；提取括号内外内容（括号注释作为独立候选）；
    按逗号/顿号/斜杠/竖线/空白拆分。
    """
    raw = raw.replace("（", "(").replace("）", ")")
    outside = re.sub(r"\([^)]*\)", "|", raw)
    inside = re.findall(r"\(([^)]*)\)", raw)
    for chunk in [outside] + inside:
        for part in re.split(r"[,，、/|\s]+", chunk):
            part = part.strip().strip("，, ")
            if part:
                yield part


def is_junk(token: str) -> bool:
    if len(token) < 2:
        return True
    if len(token) > MAX_NAME_LEN:
        return True
    if token in NOISE_TAGS:
        return True
    if re.match(r"^[A-Za-z0-9]{1,3}$", token):
        return True
    if not re.match(_NAME_CHARS, token):
        return True
    return False


def load_avdb_names(xml_path: Path) -> set[str]:
    """解析 AVdb actor-mapping.xml，返回 casefold 后的权威名字集合。"""
    names: set[str] = set()
    if not xml_path.exists():
        return names
    text = xml_path.read_text(encoding="utf-8", errors="replace")
    for entry in re.findall(r"<a\s+([^>]+)/>", text):
        for attr in ("jp=", "zh_cn=", "keyword="):
            m = re.search(attr + r'"([^"]*)"', entry)
            if m:
                for n in (m.group(1) or "").split(","):
                    if n:
                        names.add(n.casefold())
    return names


def collect_counts(json_dirs: list[Path], json_files: list[Path]) -> tuple[Counter, Counter]:
    """统计每个名字在 actor / actress 字段的出现次数。"""
    actor_counts: Counter = Counter()
    actress_counts: Counter = Counter()

    paths: list[Path] = []
    for d in json_dirs:
        paths.extend(sorted(d.glob("*_avdanyuwiki.com.json")))
    paths.extend(p for p in json_files if p.exists())

    if not paths:
        print("❌ 未找到任何 avdanyuwiki JSON 文件")
        sys.exit(1)

    for fp in paths:
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"⚠️ 跳过 {fp.name}: {e}")
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            for key, counter in (("actor", actor_counts), ("actress", actress_counts)):
                for token in split_tokens(str(item.get(key, ""))):
                    cleaned = token[:-1] if token.endswith(("×", "☓")) else token
                    if cleaned and not is_junk(cleaned):
                        counter[cleaned] += 1
    return actor_counts, actress_counts


def build_list(actor_counts: Counter, actress_counts: Counter, avdb_names: set[str]) -> dict[str, int]:
    """清洗统计结果，返回 {名字: actor出现次数}。"""
    result: dict[str, int] = {}
    for name, count in actor_counts.items():
        ac = actress_counts.get(name, 0)
        # 女优/中性名交叉验证：宁漏勿误删
        if ac > 0 and (ac >= count * 0.5 or count <= 3):
            continue
        # 低频两字名仅保留 AVdb 权威收录
        if len(name) <= 2 and count <= 3 and name.casefold() not in avdb_names:
            continue
        result[name] = count
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="从 avdanyuwiki 作品 JSON 生成男优名单")
    parser.add_argument(
        "--json-dir", action="append", default=[], type=Path, help="含 *_avdanyuwiki.com.json 的目录，可多次指定"
    )
    parser.add_argument("--json", action="append", default=[], type=Path, help="单个 JSON 文件，可多次指定")
    parser.add_argument("--avdb-xml", type=Path, default=None, help="AVdb actor-mapping.xml 路径（可选）")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="输出文件路径")
    args = parser.parse_args()

    avdb_names = load_avdb_names(args.avdb_xml) if args.avdb_xml else set()
    if args.avdb_xml:
        print(f"🔎 AVdb 权威名字集合: {len(avdb_names)} 个")

    actor_counts, actress_counts = collect_counts(args.json_dir, args.json)
    print(f"📊 原始 actor token 去重: {len(actor_counts)} 个")

    final = build_list(actor_counts, actress_counts, avdb_names)
    print(f"✅ 清洗后男优名单: {len(final)} 个")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for name in sorted(final, key=lambda x: -final[x]):
            f.write(f"{name}\n")
    print(f"💾 已写出: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
