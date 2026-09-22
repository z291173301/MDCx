from pathlib import Path

from mdcx.config.manager import manager
from mdcx.tools import minnano_crawler


def _mock_lookup(monkeypatch, mapping: dict[str, str]):
    """mock resources.get_actor_data 模拟反向索引查找。mapping: 任意名 -> jp。"""

    def fake_get_actor_data(name):
        jp = mapping.get(name)
        if jp is None:
            return {"has_name": False, "jp": name, "zh_cn": name, "zh_tw": name, "keyword": [name]}
        return {
            "has_name": True,
            "jp": jp,
            "zh_cn": name,
            "zh_tw": name,
            "keyword": [name],
        }

    monkeypatch.setattr(minnano_crawler.resources, "get_actor_data", fake_get_actor_data)


def test_cache_file_under_userdata_dir(monkeypatch, tmp_path: Path):
    """缓存文件应落在运行时用户数据目录（data_folder/userdata），而非硬编码相对路径。"""
    monkeypatch.setattr(manager, "data_folder", tmp_path)
    cache_path = minnano_crawler._get_cache_path()
    assert cache_path == tmp_path / "userdata" / "minnano_cache.xlsx"


def test_save_cache_row_creates_parent_dir(monkeypatch, tmp_path: Path):
    """打包后 data_folder 可能无 userdata 子目录，写入前应自动创建。"""
    monkeypatch.setattr(manager, "data_folder", tmp_path)
    row = {
        "jp": "テスト女優",
        "alias": "",
        "birthday": "1990-01-01",
        "height": "160cm",
        "bust": "",
        "waist": "",
        "hip": "",
        "cup": "",
        "place": "",
        "agency": "",
        "twitter": "",
        "career": "",
        "debut": "",
        "wiki": "",
        "minnano_url": "https://www.minnano-av.com/actress/12345.html",
    }
    ok = minnano_crawler.save_cache_row(row)
    assert ok
    cache_path = minnano_crawler._get_cache_path()
    assert cache_path.parent.exists()
    assert cache_path.exists()
    minnano_crawler._cache_data.clear()
    data = minnano_crawler.load_cache()
    assert "テスト女優" in data
    assert data["テスト女優"]["minnano_url"] == "https://www.minnano-av.com/actress/12345.html"


def test_lookup_returns_jp_for_chinese_name(monkeypatch):
    _mock_lookup(monkeypatch, {"桃園怜奈": "桃園怜奈"})
    assert minnano_crawler._lookup_japanese_name("桃園怜奈") == "桃園怜奈"


def test_lookup_returns_jp_for_alias(monkeypatch):
    _mock_lookup(monkeypatch, {"凪沢怜奈": "桃園怜奈"})
    assert minnano_crawler._lookup_japanese_name("凪沢怜奈") == "桃園怜奈"


def test_lookup_returns_none_for_unknown(monkeypatch):
    _mock_lookup(monkeypatch, {})
    assert minnano_crawler._lookup_japanese_name("不存在的演员") is None


def test_lookup_returns_jp_when_same(monkeypatch):
    _mock_lookup(monkeypatch, {"橋本ありな": "橋本ありな"})
    assert minnano_crawler._lookup_japanese_name("橋本ありな") == "橋本ありな"


def test_lookup_handles_empty_name(monkeypatch):
    _mock_lookup(monkeypatch, {})
    assert minnano_crawler._lookup_japanese_name("") is None


def test_build_bio_line_full_fields():
    """完整字段（七瀬いおり 样例）应拼成 `键: 值 | ...` 一行，含标签。"""
    from mdcx.tools.actor_db_tool import _build_bio_line

    parsed = {
        "name": "七瀬いおり",
        "aliases": ["七瀬香", "姫野友紀"],
        "birthday": "1993-11-23",
        "height": "164",
        "bust": "88",
        "waist": "60",
        "hip": "93",
        "cup": "F",
        "blood": "",
        "place": "宮城県",
        "agency": "JETSTREAM(元・VERGER)",
        "hobby": "下着集め、お酒、競馬",
        "career": "2020年 -",
        "debut": "新人 七瀬いおり デビュー",
        "tags": ["巨乳", "巨尻", "美人"],
    }
    bio = _build_bio_line(parsed)
    assert "身高: 164cm" in bio
    assert "罩杯: F" in bio
    assert "三围: 88/60/93" in bio
    assert "生涯: 2020~" in bio
    assert "出身: 宮城県" in bio
    assert "事务所: JETSTREAM(元・VERGER)" in bio
    assert "爱好: 下着集め、お酒、競馬" in bio
    assert "出道: 新人 七瀬いおり デビュー" in bio
    assert "标签: 巨乳,巨尻,美人" in bio
    assert "血型" not in bio


def test_build_bio_line_partial_fields():
    """缺字段时应跳过对应段；无任何身体数据时返回空串。"""
    from mdcx.tools.actor_db_tool import _build_bio_line

    partial = {"name": "某女優", "height": "160", "cup": "", "bust": "", "waist": "", "hip": ""}
    bio = _build_bio_line(partial)
    assert bio == "身高: 160cm"

    empty = {"name": "某女優"}
    assert _build_bio_line(empty) == ""


def test_build_bio_line_drops_clean_empty_segments():
    """三围只填部分时按已有值拼接；血型/事务所/爱好等缺失段不产生占位。"""
    from mdcx.tools.actor_db_tool import _build_bio_line

    parsed = {"bust": "88", "waist": "", "hip": "93", "career": "2015年01月 - 2023年", "place": ""}
    bio = _build_bio_line(parsed)
    assert "三围: 88/93" in bio
    assert "生涯: 2015~2023" in bio
    assert "出身" not in bio

    # career 非年份（事务所误归 career）→ 丢弃该段
    parsed2 = {"career": "KRONE(クローネ)", "bust": "", "waist": "", "hip": ""}
    assert _build_bio_line(parsed2) == ""

    # 出道长标题（>=15字）→ 不产生出道段
    parsed3 = {"debut": "新人 恥じらい笑顔のFカップ美くびれ AV DEBUT", "height": "160"}
    bio3 = _build_bio_line(parsed3)
    assert "出道" not in bio3
    assert "身高: 160cm" in bio3


def test_clean_struct_segments():
    """_clean_struct_segments 规范化结构化字段段：出道长标题删、三围单值删、前缀剥离、连续标点合并。"""
    from mdcx.tools.actor_db_tool import _clean_struct_segments

    # 出道长标题整段删除
    assert _clean_struct_segments("身高: 160cm | 出道: 新人 恥じらい笑顔のAV DEBUT 2024") == "身高: 160cm"
    # 出道短值保留
    assert _clean_struct_segments("出道: 新人18岁") == "出道: 新人18岁"
    # 三围单值删除
    assert _clean_struct_segments("罩杯: F | 三围: 100") == "罩杯: F"
    # 三围配对保留
    assert _clean_struct_segments("三围: 88/60/88") == "三围: 88/60/88"
    # 事务所前缀剥离
    assert _clean_struct_segments("事务所: 事务所KRONE") == "事务所: KRONE"
    assert _clean_struct_segments("事务所: 为SELECTION") == "事务所: SELECTION"
    assert _clean_struct_segments("事务所: 事务所为SELECTION") == "事务所: SELECTION"
    # 爱好前缀剥离
    assert _clean_struct_segments("爱好: 爱好是按摩") == "爱好: 按摩"
    assert _clean_struct_segments("爱好: 爱好：卡拉OK") == "爱好: 卡拉OK"
    # 连续标点合并
    assert _clean_struct_segments("标签: 熟女。。。巨乳") == "标签: 熟女。巨乳"


def test_parse_minnano_page_accepts_4row_profile_table(monkeypatch):
    """部分演员页个人信息表只有 4 行（无生日行），也应能被识别为 profile table。"""
    html = """
    <html><head><title>阿部涼音（あべすずね）AV女優プロフィール</title></head>
    <body>
    <table>
      <tr><td><h2>阿部涼音 （あべすずね / Abe Suzune）</h2></td></tr>
      <tr><td><span>サイズ</span><p>T157 / B88(Bカップ) / W58 / H87 / S24.5</p></td></tr>
      <tr><td><span>趣味・特技</span><p>器械体操</p></td></tr>
      <tr><td><span>タグ</span><p>巨乳、美少女</p></td></tr>
    </table>
    <div class="tagarea"><a>巨乳</a><a>美少女</a></div>
    </body></html>
    """
    parsed = minnano_crawler.parse_minnano_page(html, "45598")
    assert parsed is not None
    assert parsed["name"] == "阿部涼音"
    assert parsed["height"] == "157"
    assert parsed["cup"] == "B"
    assert parsed["bust"] == "88"
    assert parsed["waist"] == "58"
    assert parsed["hip"] == "87"


def test_extract_bio_fields_from_free_text():
    """reformat_minnano 从自由中文简介抽字段，多种格式都能识别。"""
    from mdcx.tools.actor_db_tool import _build_bio_line, _extract_bio_fields

    # 无冒号 B/W/H 前缀 + 籍贯 + 标签
    p = _extract_bio_fields("身高172cm，三围B111/W66/H92，罩杯I。籍贯大分县。标签：美巨乳")
    assert p["height"] == "172"
    assert p["cup"] == "I"
    assert (p["bust"], p["waist"], p["hip"]) == ("111", "66", "92")
    assert p["place"] == "大分县"
    assert p["tags"] == ["美巨乳"]
    assert "身高: 172cm" in _build_bio_line(p)

    # 全角冒号 B/W/H 前缀 + 出身于 + 血型B型 + 爱好
    p = _extract_bio_fields("出身于东京都；身高152cm，三围：B79/W57/H77，罩杯C，血型B型；爱好：散步")
    assert p["height"] == "152"
    assert p["place"] == "东京都"  # 出身于 不应抽出"于东京都"
    assert p["blood"] == "B型"
    assert p["hobby"] == "散步"
    assert p["cup"] == "C"

    # 已带 | 分隔的两段式三围
    p = _extract_bio_fields("三围: 60/89 | 出身: 宮崎県 | 血型: A型 | 标签: 天然むすめ")
    assert (p["bust"], p["waist"]) == ("60", "89")
    assert p["place"] == "宮崎県"
    assert p["blood"] == "A型"

    # 只有名字 → 无可抽字段
    p = _extract_bio_fields("愛田千紘（あいだれいか，Aida Reika），，。")
    assert p["height"] == "" and p["cup"] == "" and p["place"] == ""

    # 出道：短值保留，出道作品长标题丢弃
    p = _extract_bio_fields("出道：人妻の色香")
    assert p["debut"] == "人妻の色香"
    p = _extract_bio_fields("出道作品：新人×ギリギリモザイク（2010年）")
    assert p["debut"] == ""


def test_extract_name_alias():
    """merge_name_alias 从 `日文名（假名 / 罗马音）` 提取别名。"""
    from mdcx.tools.actor_db_tool import _extract_name_alias

    assert _extract_name_alias("阿久津華（あくつはな / Akutsu Hana）") == ["あくつはな", "Akutsu Hana"]
    # 逗号分隔
    assert _extract_name_alias("愛田千紘（あいだれいか，Aida Reika）") == ["あいだれいか", "Aida Reika"]
    # 未闭合括号
    assert _extract_name_alias("愛川沙羅（あいかわさら / Aikawa Sara") == ["あいかわさら", "Aikawa Sara"]
    # 无括号 → 空
    assert _extract_name_alias("阿部珠緒") == []
    # 别名：整段多值
    assert _extract_name_alias("岸本百華，别名：あすか苺") == ["あすか苺"]
    assert _extract_name_alias("菜月もな，别名：菜月もえ、セナ、菜月せな") == ["菜月もえ", "セナ", "菜月せな"]
    # 姓名：前缀 + 别名
    assert _extract_name_alias("姓名：北村亜樹，别名：橘裕佳子") == ["橘裕佳子"]


def _cleanup_apply(bio: str, jp: str = "") -> str:
    """应用 cleanup_bio 的同一套清理规则（与 run_actor_db_xlsx 里实现保持一致）。"""
    import re

    m = re.search(r"(\d{4})年(?:\d{1,2}月)?\s*出道", bio)
    if m:
        career = f"{m.group(1)}~"
        if career not in bio:
            bio = f"生涯: {career} | {bio}" if bio else f"生涯: {career}"
        bio = re.sub(r"[，,。;；]?\s*\d{4}年(?:\d{1,2}月)?\s*出道[，,。;；]?", "", bio)
        rest = bio.replace(f"生涯: {career} |", "", 1).strip()
        if rest and re.search(r"[（()）]|别名|出道作", rest):
            bio = f"生涯: {career}"
    bio = re.sub(r"[，,。;；]?\s*(?:出道作品|参演作品|出道作为|作品仅出演过|作品为|作品)\s*[:：]?[^|]*", "", bio)
    bio = re.sub(r"[，,。;；\s]*サイズ\s*[:：]?\s*[A-Za-z0-9.]*[，,。;；,]?", "", bio)
    if re.fullmatch(r"(?:三围|三圍|バスト)\s*[:：]?\s*\d{2,3}\s*", bio.strip()):
        bio = ""
    bio = re.sub(r"[，,。;；]?\s*(?:标签|出道|背景|备注)\s*[:：]?\s*(?=\||$)", "", bio)
    cleaned = bio.strip(" |,").strip()
    m2 = re.fullmatch(r"(?:姓名|氏名|名字)\s*[:：]?\s*([\u4e00-\u9fffA-Za-z0-9]+)", cleaned)
    if m2 and m2.group(1) == jp:
        return ""
    if re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9]+", cleaned) and cleaned == jp:
        return ""
    return cleaned


def test_cleanup_bio_rules():
    """cleanup_bio 四类规则：抽生涯/删作品长标题/清日文尺寸/清三围孤值/清空标签。"""
    # 规则 1: xxx年出道 -> 生涯
    assert _cleanup_apply("谷間田みお，2026年出道") == "生涯: 2026~ | 谷間田みお"
    # 规则 2: 出道作品长标题删除
    assert _cleanup_apply("木下千夏参演作品:《若妻的母乳如何?》") == "木下千夏"
    # 规则 3: 日文尺寸残段清理
    assert _cleanup_apply("高宮慶子サイズ：S") == "高宮慶子"
    assert _cleanup_apply("中川知里サイズ:S") == "中川知里"
    # 规则 4: 三围孤值清空
    assert _cleanup_apply("三围: 90") == ""
    assert _cleanup_apply("三围: 112") == ""
    assert _cleanup_apply("三围: 60/89") == "三围: 60/89"  # 配对值保留
    # 规则 5: 空标签清理
    assert _cleanup_apply("菅家美和子 标签:") == "菅家美和子"
    # 组合：出道+作品长标题
    assert _cleanup_apply("姓名：宮本冷子。作品仅出演过「エロ年増18」") == "姓名：宮本冷子"
    # 规则 6: 纯名字清空（与日文名相同）
    assert _cleanup_apply("高宮慶子", jp="高宮慶子") == ""
    assert _cleanup_apply("姓名：宮本冷子", jp="宮本冷子") == ""
