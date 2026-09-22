"""从 AVWikiDB 男优一览页（mhtml）提取男优名并追加到 male_actors.txt。

数据源：AVWikiDB「AV男優一覧」各页保存的 .mhtml 文件（浏览器整页另存）。

清洗规则：
1. 提取页面所有 <a> 链接文本（男优名），过滤导航/按钮词
2. 清理括号别名标注（しみけん（清水健）→ しみけん），取主名
3. 过滤已知噪声标签（TECH/艦長/軍曹/酔拳/真琴 等）
4. 与现有名单求差集，追加（不排序，保持追加式维护风格）

用法:
    python scripts/add_male_actors_from_wiki.py --dir <mhtml目录>
    python scripts/add_male_actors_from_wiki.py --dir <目录> --apply   # 写入文件
"""

from __future__ import annotations

import argparse
import re
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT_ROOT / "resources" / "userdata" / "male_actors.txt"

# 导航/按钮/无关链接文本
_NAV = {
    "Skip to main content",
    "FANZA素人",
    "FANZAビデオ",
    "FANZA VR動画",
    "MGS動画",
    "AV女優",
    "AV男優",
    "AV監督",
    "メーカー",
    "シリーズ",
    "情報提供",
    "コメント",
    "ログイン",
    "登録",
    "検索",
    "男優",
    "女優",
    "トップ",
    "運営者情報",
    "FANZA Webサービス",
    "FANZA動画",
    "AVメーカー",
    "立即登录",
    "重试",
    "お問い合わせ",
}

# 已知噪声标签（被现有 build_male_actor_list 判定为非人名的词）
_NOISE = {"AKATAKA", "TECH", "艦長", "軍曹", "酔拳", "真琴", "ひまわり", "HMP"}


def extract_names(mhtml: Path) -> set[str]:
    """从单个 mhtml 提取男优主名集合。"""
    msg = BytesParser(policy=policy.default).parsebytes(mhtml.read_bytes())
    names: set[str] = set()
    for part in msg.walk():
        if part.get_content_type() != "text/html":
            continue
        body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="ignore")
        for text in re.findall(r">([^<>\s][^<>]{1,30}?)</a>", body):
            name = text.strip()
            if not name or name in _NAV or len(name) <= 1:
                continue
            main = re.split(r"[（(]", name)[0].strip()
            if main in _NOISE:
                continue
            names.add(main)
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 AVWikiDB mhtml 提取男优名追加到名单")
    parser.add_argument("--dir", type=Path, required=True, help="含 *.mhtml 的目录")
    parser.add_argument("--apply", action="store_true", help="写入 male_actors.txt")
    args = parser.parse_args(argv)

    mhtmls = sorted(args.dir.glob("*.mhtml"))
    if not mhtmls:
        print(f"❌ 目录无 mhtml: {args.dir}")
        return 1

    all_names: set[str] = set()
    for m in mhtmls:
        names = extract_names(m)
        print(f"  {m.name}: {len(names)} 个男优名")
        all_names |= names

    existing = {line.strip() for line in OUTPUT.read_text(encoding="utf-8").splitlines() if line.strip()}
    new_names = all_names - existing
    print(f"\n网页共 {len(all_names)} 个，现有名单 {len(existing)} 个，新增 {len(new_names)} 个")

    if not new_names:
        print("无新增。")
        return 0

    for n in sorted(new_names):
        print(f"  + {n}")

    if not args.apply:
        print("\n（预览模式，加 --apply 追加到 male_actors.txt）")
        return 0

    with open(OUTPUT, "a", encoding="utf-8") as f:
        for n in sorted(new_names):
            f.write(f"{n}\n")
    print(f"✅ 已追加 {len(new_names)} 个到 {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
