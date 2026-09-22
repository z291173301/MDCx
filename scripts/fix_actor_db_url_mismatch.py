"""修复出厂库 6/7 列错配：清空「无 tmdbid 但有 tmdb url」的 url 列。

背景：10944 行存在 tmdbid 为空但 tmdb url 有值的错配——url 指向的 TMDB 人物
与行名不一致（抽样全错），且大量行共享同一 url（复制污染）。这些 url 无意义
且误导，清空使行回到「有名字无 id」的干净状态，可后续按名重搜补回。

用法:
    python scripts/fix_actor_db_url_mismatch.py            # 预览
    python scripts/fix_actor_db_url_mismatch.py --apply    # 执行
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import openpyxl

from mdcx.config.resources import get_actor_db_sheet  # noqa: E402
from scripts.db_guard import clear_tmdb, validate_after_save  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "resources" / "userdata" / "actor_database.xlsx"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清空无 id 但有 url 的 url 列")
    parser.add_argument("--apply", action="store_true", help="执行")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="目标库")
    args = parser.parse_args(argv)

    db_path = args.db
    if not db_path.exists():
        print(f"数据库不存在: {db_path}")
        return 1

    wb = openpyxl.load_workbook(db_path)
    ws = get_actor_db_sheet(wb)

    fix_rows: list[tuple[int, str]] = []  # 无 id 有 url：清空 url
    del_rows: list[int] = []  # 无 jp 有 url：整行删除（无有效数据的垃圾行）
    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        jp = str(row[0] or "").strip()
        tid = str(row[5] or "").strip() if len(row) > 5 else ""
        url = str(row[6] or "").strip() if len(row) > 6 else ""
        if not jp:
            # 无 jp 的行全是垃圾（可能只有 url 或全空），整行删除
            del_rows.append(row_idx)
        elif not tid and url:
            fix_rows.append((row_idx, jp))
    print(f"无 id 但有 url 的行（清空 url）: {len(fix_rows)}")
    print(f"无 jp 的垃圾行（整行删除）: {len(del_rows)}")
    if not args.apply:
        print("\n（预览模式，加 --apply 执行）")
        wb.close()
        return 0

    shutil.copy(db_path, Path(tempfile.gettempdir()) / "actor_db_before_url_fix.xlsx")
    for row_idx, _jp in fix_rows:
        clear_tmdb(ws, row_idx)  # 成对清空 id+url（防单独清 url 留 id 错配）
    for row_idx in sorted(del_rows, reverse=True):
        ws.delete_rows(row_idx, 1)
    wb.save(db_path)
    wb.close()
    ok = validate_after_save(db_path)
    print(f"✅ 已清空 {len(fix_rows)} 行 url、删除 {len(del_rows)} 行无 jp 垃圾行")
    if not ok:
        print("⚠️ 保存后校验发现 error 级问题，请检查！")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
