from dataclasses import dataclass, field

from mdcx.core.similar import SimilarIndex, build_idf, extract_prefix, idf_jaccard


@dataclass
class _Fake:
    number: str = ""
    title: str = ""
    tags: list[str] = field(default_factory=list)
    series: str = ""
    studio: str = ""
    actors: list[str] = field(default_factory=list)
    release: str = ""
    runtime: str = ""
    mosaic: str = ""
    publisher: str = ""
    directors: list[str] = field(default_factory=list)
    score: str = ""


def _item(number: str, tags: list[str], **kw) -> _Fake:
    return _Fake(number=number, tags=tags, **kw)


def test_extract_prefix():
    assert extract_prefix("SONE-205") == "SONE"
    assert extract_prefix("FC2-PPV-1854491") == "FC2-PPV"
    assert extract_prefix("") is None


def test_build_idf_hot_tag_gets_zero():
    corpus = [
        {"巨乳", "痴女", "レズ"},
        {"巨乳", "痴女", "調教"},
        {"巨乳", "痴女", "露出"},
        {"巨乳", "痴女", "スレンダー"},
    ]
    idf = build_idf(corpus)
    # 巨乳/痴女 出现比例 100% > 0.25 阈值 → 0
    assert idf["巨乳"] == 0.0
    assert idf["痴女"] == 0.0
    # 只出现一次的长尾 tag → 高 IDF
    assert idf["レズ"] > 0.0
    assert idf["レズ"] == idf["調教"]


def test_idf_jaccard_basic():
    idf = {"a": 1.0, "b": 2.0, "c": 3.0}
    # 完全交集
    assert idf_jaccard({"a", "b"}, {"a", "b"}, idf) == 1.0
    # 无交集
    assert idf_jaccard({"a"}, {"c"}, idf) == 0.0
    # 部分交集：(1)/(1+2+3)
    assert abs(idf_jaccard({"a", "b"}, {"a", "c"}, idf) - 1.0 / 6.0) < 1e-9


def test_rank_returns_similar_first():
    # 语料需足够大，否则所有 tag 都成 hot（IDF=0）导致无候选——与真实全库索引行为一致
    tags_pool = ["巨乳", "痴女", "レズ", "調教", "露出", "スレンダー", "素人", "美少女", "水着", "美脚"]
    corpus = []
    for i in range(60):
        tags = [tags_pool[i % 10], tags_pool[(i + 1) % 10]]
        corpus.append(
            _item(
                f"STAR-{i:03d}",
                tags,
                series="",
                studio="MOODYZ",
                actors=[f"B{i}"],
                release=f"201{0 + i % 10}-01-01",
                runtime="60",
            )
        )
    target = _item(
        "SONE-100",
        ["巨乳", "痴女", "レズ"],
        series="エスワン",
        studio="S1 NO.1 STYLE",
        actors=["A"],
        release="2024-01-01",
        runtime="120",
    )
    corpus.append(target)
    # 高度相似：同系列同片商同演员
    corpus.append(
        _item(
            "SONE-101",
            ["巨乳", "痴女", "レズ", "調教"],
            series="エスワン",
            studio="S1 NO.1 STYLE",
            actors=["A"],
            release="2024-02-01",
            runtime="119",
        )
    )
    index = SimilarIndex(corpus)
    ranked = index.rank(target, top_n=2)
    assert ranked, "应至少返回一条相似结果"
    # 同系列同片商同演员的 SONE-101 应排最前
    assert ranked[0][0].number == "SONE-101"
    # 评分应为正
    assert ranked[0][1] > 0.0


def test_rank_excludes_target_itself():
    target = _item("SONE-100", ["巨乳", "痴女"])
    corpus = [target, _item("SONE-101", ["巨乳", "痴女", "調教"])]
    index = SimilarIndex(corpus)
    ranked = index.rank(target, top_n=5)
    assert all(item.number != "SONE-100" for item, _ in ranked)


def test_rank_empty_corpus_returns_empty():
    target = _item("SONE-100", ["巨乳"])
    assert SimilarIndex([]).rank(target) == []


def test_rank_no_shared_tag_returns_empty():
    target = _item("SONE-100", ["巨乳"])
    corpus = [_item("STAR-200", ["素人"])]
    index = SimilarIndex(corpus)
    assert index.rank(target) == []
