"""相似算法新特征（mosaic/publisher/directors/score）的加分逻辑测试。

注意：SimilarIndex 的 tag 粗筛依赖 IDF（热门 tag 得 0 不参与召回），
小语料 + 单 tag 会让所有 tag 变热门而无候选。因此测试用多 tag 多影片语料。
"""

from mdcx.core.similar import SimilarIndex

_TAG_POOL = ["巨乳", "痴女", "レズ", "调教", "露出", "素人", "美少女", "水着"]


def _make(number, **kw) -> dict:
    base = {
        "number": number,
        "tags": kw.get("tags") or ["巨乳", "痴女"],
        "series": kw.get("series") or "",
        "studio": kw.get("studio") or "S1",
        "actors": kw.get("actors") or ["A"],
        "release": kw.get("release") or "2024-01-01",
        "runtime": kw.get("runtime") or "120",
        "mosaic": kw.get("mosaic") or "有码",
        "publisher": kw.get("publisher") or "",
        "directors": kw.get("directors") or [],
        "score": kw.get("score") or "",
    }
    return base


def _item(d: dict):
    return type("Item", (), d)()


def _index_and_rank(target: dict, corpus: list[dict]) -> dict[str, float]:
    # 语料要足够大且 tag 多样，避免全部 tag 变热门导致无候选
    index = SimilarIndex([_item(c) for c in corpus])
    ranked = index.rank(_item(target), top_n=len(corpus))
    return {c.number: round(s, 4) for c, s in ranked}


def _build_corpus(target_tags: list[str], variants: list[dict]) -> list[dict]:
    """构造多样语料：每个 variant 一种 tag 组合 + 若干陪跑影片。"""
    corpus = []
    for i, v in enumerate(variants):
        tags = list(target_tags) + [_TAG_POOL[(i + 2) % len(_TAG_POOL)]]
        d = dict(v)
        d["number"] = v["number"]
        d["tags"] = tags
        corpus.append(d)
    # 陪跑：不同 tag 组合的干扰项
    for i in range(8):
        corpus.append(
            _make(
                f"FILL-{i:02d}",
                tags=[_TAG_POOL[(i * 3) % len(_TAG_POOL)], _TAG_POOL[(i * 3 + 1) % len(_TAG_POOL)]],
            )
        )
    return corpus


def test_same_mosaic_scores_higher_than_different():
    target = _make("T-1", tags=["巨乳", "痴女"], mosaic="有码")
    same = _make("A-1", mosaic="有码")
    diff = _make("B-1", mosaic="无码")
    corpus = _build_corpus(["巨乳", "痴女"], [same, diff])
    scores = _index_and_rank(target, corpus)
    assert scores["A-1"] > scores["B-1"]


def test_same_publisher_bonus():
    target = _make("T-1", tags=["巨乳", "痴女"], publisher="DMM")
    same_pub = _make("A-1", publisher="DMM")
    diff_pub = _make("B-1", publisher="OtherPub")
    corpus = _build_corpus(["巨乳", "痴女"], [same_pub, diff_pub])
    scores = _index_and_rank(target, corpus)
    assert scores["A-1"] > scores["B-1"]


def test_shared_directors_bonus():
    target = _make("T-1", tags=["巨乳", "痴女"], directors=["北野武"])
    same_dir = _make("A-1", directors=["北野武"])
    diff_dir = _make("B-1", directors=["罗伯托"])
    corpus = _build_corpus(["巨乳", "痴女"], [same_dir, diff_dir])
    scores = _index_and_rank(target, corpus)
    assert scores["A-1"] > scores["B-1"]


def test_close_score_bonus():
    target = _make("T-1", tags=["巨乳", "痴女"], score="8.5")
    close = _make("A-1", score="8.0")
    far = _make("B-1", score="5.0")
    corpus = _build_corpus(["巨乳", "痴女"], [close, far])
    scores = _index_and_rank(target, corpus)
    assert scores["A-1"] > scores["B-1"]
