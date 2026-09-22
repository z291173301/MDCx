"""校验 scripts/check_actor_db.py 的静态检查逻辑，尤其新增的 url 错配检查。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402

from mdcx.config.resources import DB_HEADERS  # noqa: E402
from scripts import check_actor_db as mod  # noqa: E402


def _make_db(path: Path, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "演员数据库"
    ws.append(DB_HEADERS)
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()


def _run_checks(rows):
    return [
        mod._check_tmdb_url_no_id(rows),
        mod._check_tmdb_url_mismatch(rows),
        mod._check_tmdb_url_duplicate(rows),
    ]


def test_url_no_id_detected():
    """tmdbid 空但有 url 应报错。"""
    rows = [
        ["演员甲", "演员甲", "", "", "", "", "https://www.themoviedb.org/person/1001", "", ""],
    ]
    no_id, mismatch, dup = _run_checks(rows)
    assert len(no_id) == 1
    assert "tmdbid 为空" in no_id[0]


def test_url_mismatch_detected():
    """tmdbid 与 url 不匹配应报错。"""
    rows = [
        ["演员甲", "演员甲", "", "", "", "1001", "https://www.themoviedb.org/person/9999", "", ""],
    ]
    no_id, mismatch, dup = _run_checks(rows)
    assert len(mismatch) == 1
    assert "不匹配" in mismatch[0]


def test_url_duplicate_detected():
    """同一 url 多行应报错。"""
    rows = [
        ["演员甲", "演员甲", "", "", "", "1001", "https://www.themoviedb.org/person/1001", "", ""],
        ["演员乙", "演员乙", "", "", "", "1002", "https://www.themoviedb.org/person/1001", "", ""],
    ]
    no_id, mismatch, dup = _run_checks(rows)
    assert len(dup) == 1
    assert "重复" in dup[0]


def test_clean_rows_pass():
    """正常行不应报错。"""
    rows = [
        ["演员甲", "演员甲", "", "", "", "1001", "https://www.themoviedb.org/person/1001", "1990-01-01", ""],
        ["演员乙", "演员乙", "", "", "", "1002", "https://www.themoviedb.org/person/1002", "", ""],
    ]
    no_id, mismatch, dup = _run_checks(rows)
    assert no_id == []
    assert mismatch == []
    assert dup == []


def _inject_orphan_hyperlink(path: Path):
    """向 xlsx 的 sheet1.xml 注入一个引用不存在单元格的孤儿 hyperlink。"""
    import shutil
    import zipfile

    tmp = path.with_suffix(".inject.xlsx")
    shutil.copy(path, tmp)
    with zipfile.ZipFile(tmp, "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}
    sheet1 = data["xl/worksheets/sheet1.xml"].decode("utf-8")
    # 在 </hyperlinks> 前注入一个孤儿 hyperlink（引用行 99999 的 G 列）
    orphan = (
        '<hyperlink xmlns:r="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships" ref="G99999" r:id="rIdX_ORPHAN"/>'
    )
    if "</hyperlinks>" in sheet1:
        sheet1 = sheet1.replace("</hyperlinks>", orphan + "</hyperlinks>")
    else:
        sheet1 = sheet1.replace("</sheetData>", "<hyperlinks>" + orphan + "</hyperlinks></sheetData>")
    data["xl/worksheets/sheet1.xml"] = sheet1.encode("utf-8")
    # 同步补一条 rels 关系，避免 Excel 打开报缺引用（仅当 rels 存在时）
    rels_name = "xl/worksheets/_rels/sheet1.xml.rels"
    if rels_name in data:
        rels = data[rels_name].decode("utf-8")
        rels = rels.replace(
            "</Relationships>",
            '<Relationship Id="rIdX_ORPHAN" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://www.themoviedb.org/person/99999" TargetMode="External"/></Relationships>',
        )
        data[rels_name] = rels.encode("utf-8")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, data[n])
    return tmp


def test_orphan_hyperlink_detected(tmp_path):
    """引用不存在单元格的孤儿 hyperlink 应报错。"""
    p = tmp_path / "actor_database.xlsx"
    _make_db(p, [["演员甲", "演员甲", "", "", "", "1001", "https://www.themoviedb.org/person/1001", "", ""]])
    p = _inject_orphan_hyperlink(p)
    errors = mod._check_orphan_hyperlinks(p)
    assert len(errors) == 1
    assert "G99999" in errors[0]
    assert "孤儿 hyperlink" in errors[0]


def test_no_orphan_hyperlink_passes(tmp_path):
    """正常文件（无孤儿 hyperlink）不应报错。"""
    p = tmp_path / "actor_database.xlsx"
    _make_db(p, [["演员甲", "演员甲", "", "", "", "1001", "https://www.themoviedb.org/person/1001", "", ""]])
    errors = mod._check_orphan_hyperlinks(p)
    assert errors == []
