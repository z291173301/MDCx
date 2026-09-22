from mdcx.core.amazon_match import (
    build_expected_titles,
    build_number_regex,
    calculate_title_confidence,
    clean_amazon_title_for_compare,
    count_actor_group_matches,
    get_best_title_confidence,
    get_media_priority,
    is_supported_pic_ver,
    normalize_title_for_compare,
    strip_trailing_media_noise,
    text_has_target_number,
)


def test_build_number_regex_matches_separated_tokens():
    # convert_half 会移除连字符等符号并大写, 因此对 "SSNI-804" 生成单 token 正则
    regex = build_number_regex("SSNI-804")
    assert regex is not None
    assert regex.search("SSNI804")
    assert regex.search("ssni804")
    assert not regex.search("SSNI8045")
    assert not regex.search("XSSNI804")

    regex2 = build_number_regex("SSNI 804")
    assert regex2 is not None
    assert regex2.search("SSNI804")


def test_build_number_regex_returns_none_for_empty():
    assert build_number_regex("") is None
    assert build_number_regex(None) is None


def test_text_has_target_number():
    # convert_half 去掉标点/空格并大写; 番号后跟日文等非 ASCII 字母数字时可匹配
    regex = build_number_regex("SSNI-804")
    assert text_has_target_number("SSNI804", regex) is True
    assert text_has_target_number("SSNI-804 タイトル", regex) is True
    assert text_has_target_number("unrelated title", regex) is False
    assert text_has_target_number("SSNI-804 title", None) is False


def test_count_actor_group_matches():
    groups = [{"ALICE", "BOB"}, {"CAROL"}]
    assert count_actor_group_matches("contains ALICE here", groups) == 1
    assert count_actor_group_matches("contains ALICE and CAROL", groups) == 2
    assert count_actor_group_matches("nothing", groups) == 0
    assert count_actor_group_matches("anything", []) == 0


def test_strip_trailing_media_noise():
    assert strip_trailing_media_noise("Title DVD") == "Title"
    assert strip_trailing_media_noise("Title Blu-ray") == "Title"
    assert strip_trailing_media_noise("Title software download") == "Title"
    assert strip_trailing_media_noise("Title ソフトウェアダウンロード") == "Title"
    assert strip_trailing_media_noise("Title  [DVD]") == "Title"
    assert strip_trailing_media_noise("") == ""


def test_clean_amazon_title_for_compare_default_keywords():
    assert clean_amazon_title_for_compare("Title DVD") == "Title"
    assert clean_amazon_title_for_compare("Title Blu-ray") == "Title"
    assert clean_amazon_title_for_compare("Title [dvd]") == "Title"


def test_clean_amazon_title_for_compare_custom_keywords():
    assert clean_amazon_title_for_compare("Title 主演: 女優名", ["主演: 女優名"]) == "Title"
    assert clean_amazon_title_for_compare("Title StudioName", ["StudioName"]) == "Title"


def test_normalize_title_for_compare_strips_noise():
    # convert_half 去掉符号/括号/空格并大写, number_regex 在番号独立出现（后无 ASCII 字母数字）时移除
    regex = build_number_regex("SSNI-804")
    normalized = normalize_title_for_compare("ＳＳＮＩ－８０４ 【特典】", regex)
    assert "ssni804" not in normalized
    assert normalize_title_for_compare("Title", None) == "title"


def test_normalize_title_for_compare_wildcard():
    normalized = normalize_title_for_compare("ABC●XYZ")
    assert "\u2606" in normalized
    assert "●" not in normalized


def test_calculate_title_confidence_exact_match():
    assert calculate_title_confidence("Same Title", "Same Title") == 1.0


def test_calculate_title_confidence_wildcard_full_match():
    # ● 转为 wildcard 占位符, 与任意单字符匹配时触发 full match 高分
    score = calculate_title_confidence("Title●Limited", "TitlexLimited")
    assert score >= 0.95
    assert calculate_title_confidence("Title●Limited", "TitleyLimited") >= 0.95


def test_calculate_title_confidence_unrelated_low():
    score = calculate_title_confidence("Completely Different Title A", "Unrelated Title B")
    assert score < 0.7


def test_get_best_title_confidence_uses_max():
    expected = ["Expected One", "Target Title"]
    score = get_best_title_confidence("Target Title", expected)
    assert score == 1.0
    assert get_best_title_confidence("", expected) == 0.0
    assert get_best_title_confidence("Anything", []) == 0.0


def test_get_best_title_confidence_extra_titles():
    score = get_best_title_confidence("Extra Title", [], None, None, "Extra Title")
    assert score == 1.0


def test_get_media_priority_ordering():
    assert get_media_priority("") == 2
    assert get_media_priority("DVD") == 3
    assert get_media_priority("Software Download") == 2
    assert get_media_priority("Blu-ray") == 1
    assert get_media_priority("unknown") == 0


def test_is_supported_pic_ver():
    assert is_supported_pic_ver("")
    assert is_supported_pic_ver("DVD")
    assert is_supported_pic_ver("Blu-ray")
    assert not is_supported_pic_ver("unknown-format")


def test_build_expected_titles_with_series():
    titles = build_expected_titles(
        "シリーズ名 Title raw",
        "シリーズ名",
        "Title mapped",
        "",
    )
    assert "シリーズ名 Title raw" in titles
    assert "Title raw" in titles
    assert "Title mapped" in titles


def test_build_expected_titles_dedup():
    titles = build_expected_titles("Same", "", "Same", "")
    assert titles == ["Same"]


def test_module_reusable_without_closure_state():
    """模块级函数不依赖闭包, 可被任意脚本独立调用."""
    number_regex = build_number_regex("FC2-1234")
    expected = build_expected_titles("FC2-1234 Title", "", "", "")
    score = get_best_title_confidence("FC2-1234 Title DVD", expected, number_regex, None)
    assert score > 0.9
