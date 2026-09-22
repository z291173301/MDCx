"""测试 mdcx.utils.actor_clean 语义清洗。"""

from mdcx.utils.actor_clean import clean_actor_keyword, clean_actor_name


def test_name_strip_series_tag():
    assert clean_actor_name("本田仁美(パコパコママ)") == "本田仁美"


def test_name_strip_annotation_nationality():
    assert clean_actor_name("マオ（ベトナム）") == "マオ"


def test_name_strip_annotation_office():
    assert clean_actor_name("Lisa【FALENO】") == "Lisa"
    assert clean_actor_name("上原ゆあ【HEYZO】") == "上原ゆあ"


def test_name_strip_annotation_type():
    assert clean_actor_name("HIBIKI（女王様）") == "HIBIKI"


def test_name_strip_year():
    assert clean_actor_name("可愛ゆう(2015)") == "可愛ゆう"
    assert clean_actor_name("栗田佳子[2016年]") == "栗田佳子"


def test_name_placeholder_returns_empty():
    assert clean_actor_name("素人奥様") == ""
    assert clean_actor_name("元Fカップグラドル（FC2)") == ""
    assert clean_actor_name("抜群なアイドル店員") == ""


def test_name_keeps_reading_alias():
    assert clean_actor_name("Irie Risa (入江里咲)") == "Irie Risa (入江里咲)"
    assert clean_actor_name("Tanaka Karen (田中可恋)") == "Tanaka Karen (田中可恋)"


def test_name_strip_compact_desc():
    assert clean_actor_name("巨乳女子プロレスラー凛叶") == "凛叶"
    assert clean_actor_name("ここな先生") == "ここな"


def test_name_normal_unchanged():
    assert clean_actor_name("浅野心愛") == "浅野心愛"
    assert clean_actor_name("佐々木さき") == "佐々木さき"


def test_keyword_strip_series_tag_keep_name():
    assert clean_actor_keyword("本田仁美(パコパコママ),山下,まつだ") == "本田仁美,山下,まつだ"


def test_keyword_remove_title():
    assert clean_actor_keyword("ラグジュTV 1727,安堂はるの") == "安堂はるの"
    assert clean_actor_keyword("ママ友喰い無限ループ vol.50 みはな,内田めぐみ") == "内田めぐみ"


def test_keyword_fix_dangling_slash():
    assert clean_actor_keyword("ただえりさ /,きむら") == "ただえりさ,きむら"


def test_keyword_fix_residual_bracket():
    assert clean_actor_keyword("真東愛 / Mahigashi Ai）,みお") == "真東愛 / Mahigashi Ai,みお"


def test_keyword_remove_age_tag():
    assert clean_actor_keyword("あいみ 20歳,彩華") == "彩華"


def test_keyword_strip_annotation():
    assert clean_actor_keyword("みゆき（KUKI）,はな") == "みゆき,はな"
    assert clean_actor_keyword("中島 奈緒美（本名）,ゆり") == "中島 奈緒美,ゆり"


def test_keyword_remove_pure_tag():
    assert clean_actor_keyword("人妻,浜村咲,訳あり人妻") == "浜村咲"


def test_keyword_desc_token_strip():
    assert clean_actor_keyword("門脇晶子 禁断中出し契約交尾,らん") == "門脇晶子,らん"


def test_keyword_keeps_romaji_names():
    assert clean_actor_keyword("Momozono Reina,Rena") == "Momozono Reina,Rena"
