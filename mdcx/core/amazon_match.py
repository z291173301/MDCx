"""
Amazon 标题匹配与置信度计算的模块级可复用函数.

从 ``mdcx.core.amazon.get_big_pic_by_amazon`` 中抽取, 将原本依赖闭包变量的嵌套函数
改造为显式传参的纯函数, 便于被批量采集脚本等外部模块独立复用与单元测试.
"""

# mypy: ignore-errors

import re
from difflib import SequenceMatcher

from ..utils import convert_half

# 媒体类型关键词, 用于 clean_amazon_title_for_compare 缺省参数时剔除标题尾部噪音.
DEFAULT_MEDIA_TITLE_KEYWORDS = [
    "dod",
    "dvd",
    "blu-ray",
    "blu ray",
    "software download",
    "ブルーレイ",
    "ブルーレイディスク",
    "ソフトウェアダウンロード",
    "[dvd]",
    "[dod]",
    "[blu-ray]",
    "［dvd］",
    "［dod］",
    "［blu-ray］",
]

_TRIM_CHARS = " 　-—｜|/／・,，、：:()（）[]【】!?！？…."


def build_number_regex(number_text: str) -> re.Pattern[str] | None:
    """根据番号文本构建番号匹配正则, 无有效番号时返回 None."""
    normalized_number = convert_half(number_text or "").upper().strip()
    if not normalized_number:
        return None
    token_list = re.findall(r"[A-Z0-9]+", normalized_number)
    if not token_list:
        return None
    pattern = r"(?<![A-Z0-9])" + r"[^A-Z0-9]*".join(re.escape(token) for token in token_list) + r"(?![A-Z0-9])"
    return re.compile(pattern, flags=re.IGNORECASE)


def text_has_target_number(text: str, number_regex: re.Pattern[str] | None) -> bool:
    """判断文本是否包含目标番号."""
    if not number_regex or not text:
        return False
    return bool(number_regex.search(convert_half(text).upper()))


def count_actor_group_matches(text: str, actor_groups_normalized: list[set[str]]) -> int:
    """统计文本中命中的演员分组数量."""
    if not actor_groups_normalized or not text:
        return 0
    normalized_text = convert_half(re.sub(r"\s+", " ", text or "")).upper()
    return sum(1 for group in actor_groups_normalized if any(alias in normalized_text for alias in group))


def strip_trailing_media_noise(base_title: str) -> str:
    """剔除标题尾部的媒介类型噪音（dvd/blu-ray/software download 等）. 纯函数."""
    title = re.sub(r"\s+", " ", base_title).strip()
    if not title:
        return ""
    trim_chars = " 　-—｜|/／・,，、：:()（）[]【】"
    trailing_media_noise = re.compile(
        r"(?:[\s　\-\—\｜\|/／・,，、：:\(\)（）\[\]［］]+)?"
        r"(?:dod|dvd|blu[- ]?ray|software\s+download|ブルーレイ(?:ディスク)?|ソフトウェアダウンロード)"
        r"(?:[\s　\-\—\｜\|/／・,，、：:\(\)（）\[\]［］]+)?$",
        flags=re.I,
    )
    while True:
        updated, count = trailing_media_noise.subn("", title)
        if count == 0:
            break
        updated = updated.strip(trim_chars)
        if not updated or updated == title:
            break
        title = updated
    return title


def clean_amazon_title_for_compare(title: str, suffix_cleanup_keywords: list[str] | None = None) -> str:
    """清洗标题用于比对: 剔除尾部后缀关键词（媒体类型/演员/元数据等）与多余符号."""
    keywords = suffix_cleanup_keywords if suffix_cleanup_keywords is not None else _default_cleanup_keywords()
    cleaned = re.sub(r"【.*?】", " ", title)
    cleaned = re.sub(r"[［\[]\s*(?:dvd|blu[- ]?ray|software\s+download)\s*[］\]]", " ", cleaned, flags=re.I)
    trim_chars = _TRIM_CHARS
    while True:
        changed = False
        for keyword in keywords:
            escaped_keyword = re.escape(keyword)
            for pattern in (
                rf"(?:\s|　)+{escaped_keyword}$",
                rf"(?:-|—|｜|/|／|・|,|，|、|：|:)\s*{escaped_keyword}$",
                rf"{escaped_keyword}$",
            ):
                updated = re.sub(pattern, "", cleaned, flags=re.I).strip(trim_chars)
                if updated and updated != cleaned:
                    cleaned = updated
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    return re.sub(r"\s+", " ", cleaned).strip(trim_chars)


def _default_cleanup_keywords() -> list[str]:
    """缺省后缀剔除关键词: 按长度降序去重后的媒体类型关键词."""
    return sorted(set(DEFAULT_MEDIA_TITLE_KEYWORDS), key=len, reverse=True)


def normalize_title_for_compare(title: str, number_regex: re.Pattern[str] | None = None) -> str:
    """将标题归一化为可比对形式: 全半角转换、剔除番号/括号/符号, 保留 wildcard 占位符."""
    wildcard_placeholder = "\u2606"
    wildcard_token = "MDCXWILDCARDTOKEN"
    title = re.sub(r"[●○◯〇◎◉◆◇■□△▲▽▼※＊*]", wildcard_token, title)
    normalized = convert_half(title).lower()
    if number_regex:
        normalized = number_regex.sub(" ", normalized.upper()).lower()
    normalized = re.sub(r"【.*?】", "", normalized)
    normalized = re.sub(r"[［\[]\s*(?:dvd|blu[- ]?ray|software\s+download)\s*[］\]]", "", normalized, flags=re.I)
    normalized = normalized.replace(wildcard_token.lower(), wildcard_placeholder)
    normalized = re.sub(r"[\s　\-\—\｜\|/／・,，、：:()（）\[\]【】!?！？…\.]", "", normalized)
    return normalized


def calculate_title_confidence(
    expected_title: str,
    candidate_title: str,
    number_regex: re.Pattern[str] | None = None,
    suffix_cleanup_keywords: list[str] | None = None,
) -> float:
    """计算候选标题相对期望标题的匹配置信度 (0~1)."""
    expected = normalize_title_for_compare(
        clean_amazon_title_for_compare(expected_title, suffix_cleanup_keywords), number_regex
    )
    candidate = normalize_title_for_compare(
        clean_amazon_title_for_compare(candidate_title, suffix_cleanup_keywords), number_regex
    )
    if not expected or not candidate:
        return 0.0
    if expected == candidate:
        return 1.0

    wildcard_placeholder = "\u2606"

    def _strip_wildcard(text: str) -> str:
        return text.replace(wildcard_placeholder, "")

    def _chars_match(ch_a: str, ch_b: str) -> bool:
        return ch_a == ch_b or ch_a == wildcard_placeholder or ch_b == wildcard_placeholder

    def _wildcard_contains(pattern_text: str, target_text: str) -> bool:
        if not pattern_text or not target_text or len(pattern_text) > len(target_text):
            return False
        window = len(pattern_text)
        max_start = len(target_text) - window
        for start in range(max_start + 1):
            if all(_chars_match(pattern_text[index], target_text[start + index]) for index in range(window)):
                return True
        return False

    def _wildcard_full_match(text_a: str, text_b: str) -> bool:
        if len(text_a) != len(text_b):
            return False
        return all(_chars_match(ch_a, ch_b) for ch_a, ch_b in zip(text_a, text_b, strict=False))

    contain_ratio = 0.0
    expected_plain_len = max(len(_strip_wildcard(expected)), 1)
    candidate_plain_len = max(len(_strip_wildcard(candidate)), 1)
    if _wildcard_contains(expected, candidate):
        contain_ratio = max(
            contain_ratio,
            1.0 if expected_plain_len >= 12 else min(1.0, expected_plain_len / candidate_plain_len),
        )
    if _wildcard_contains(candidate, expected):
        contain_ratio = max(
            contain_ratio,
            1.0 if candidate_plain_len >= 12 else min(1.0, candidate_plain_len / expected_plain_len),
        )

    sequence_ratio = SequenceMatcher(None, expected, candidate).ratio()
    expected_no_wildcard = _strip_wildcard(expected)
    candidate_no_wildcard = _strip_wildcard(candidate)
    if expected_no_wildcard and candidate_no_wildcard:
        sequence_ratio = max(sequence_ratio, SequenceMatcher(None, expected_no_wildcard, candidate_no_wildcard).ratio())

    def _bigrams(text: str) -> set[str]:
        if len(text) < 2:
            return {text}
        return {text[i : i + 2] for i in range(len(text) - 1)}

    bigrams_expected = _bigrams(expected_no_wildcard or expected)
    bigrams_candidate = _bigrams(candidate_no_wildcard or candidate)
    jaccard = (
        len(bigrams_expected & bigrams_candidate) / len(bigrams_expected | bigrams_candidate)
        if bigrams_expected and bigrams_candidate
        else 0.0
    )

    score = 0.6 * sequence_ratio + 0.25 * contain_ratio + 0.15 * jaccard
    if _wildcard_full_match(expected, candidate) or _wildcard_full_match(candidate, expected):
        score = max(score, 0.95)
    if contain_ratio >= 0.95 and min(len(expected), len(candidate)) >= 12:
        score = max(score, 0.92)
    return score


def get_media_priority(pic_ver: str) -> int:
    """获取图片媒介类型优先级 (DVD>software download>blu-ray)."""
    if not pic_ver:
        return 2
    version_text = pic_ver.strip().lower()
    if "dvd" in version_text:
        return 3
    if "software download" in version_text:
        return 2
    if any(each in version_text for each in ["blu-ray", "blu ray", "ブルーレイ", "ブルーレイディスク"]):
        return 1
    return 0


def is_supported_pic_ver(pic_ver: str) -> bool:
    """判断图片媒介类型是否受支持."""
    return get_media_priority(pic_ver) > 0 or not pic_ver


def build_expected_titles(
    originaltitle_amazon_raw: str,
    series_raw: str,
    originaltitle_amazon: str,
    series: str,
) -> list[str]:
    """构造期望标题候选列表（含剔除系列名后的简化标题）."""
    expected_titles: list[str] = []
    expected_title_set: set[str] = set()
    for title_text, fallback_series in [
        (originaltitle_amazon_raw, series_raw),
        (originaltitle_amazon, series),
    ]:
        title_text = re.sub(r"\s+", " ", title_text).strip()
        if title_text and title_text not in expected_title_set:
            expected_titles.append(title_text)
            expected_title_set.add(title_text)
        if fallback_series and fallback_series in title_text:
            stripped_title = re.sub(re.escape(fallback_series), " ", title_text, count=1)
            stripped_title = re.sub(r"\s+", " ", stripped_title).strip()
            if stripped_title and stripped_title not in expected_title_set:
                expected_titles.append(stripped_title)
                expected_title_set.add(stripped_title)
    return expected_titles


def get_best_title_confidence(
    candidate_title: str,
    expected_titles: list[str],
    number_regex: re.Pattern[str] | None = None,
    suffix_cleanup_keywords: list[str] | None = None,
    *extra_titles: str,
) -> float:
    """取候选标题相对期望标题列表的最大置信度."""
    title_candidates = [each for each in [*expected_titles, *extra_titles] if each]
    if not title_candidates or not candidate_title:
        return 0.0
    return max(
        calculate_title_confidence(
            each_title, candidate_title, number_regex=number_regex, suffix_cleanup_keywords=suffix_cleanup_keywords
        )
        for each_title in title_candidates
    )
