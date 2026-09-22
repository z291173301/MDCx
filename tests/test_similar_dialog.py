import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from mdcx.models.model_types import CrawlersResult, ScrapeResult
from mdcx.views.similar_window import SimilarDialog

_app = None


def _app_instance() -> QApplication:
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication([])
    return _app


def _make(number: str, tags: list[str], **kw) -> CrawlersResult:
    r = CrawlersResult.empty()
    r.number = number
    r.title = kw.get("title") or number
    r.tags = tags
    r.actors = kw.get("actors") or ["A"]
    r.series = kw.get("series") or ""
    r.studio = kw.get("studio") or "S1"
    r.release = kw.get("release") or "2024-01-01"
    r.runtime = kw.get("runtime") or "120"
    return r


def _large_corpus(target: CrawlersResult) -> list[CrawlersResult]:
    pool = ["巨乳", "痴女", "レズ", "调教", "露出", "素人", "美少女", "水着", "美脚", "女仆"]
    corpus = []
    for i in range(60):
        corpus.append(_make(f"STAR-{i:03d}", [pool[i % 10], pool[(i + 1) % 10]]))
    corpus.append(target)
    return corpus


def test_collect_corpus_filters_empty_results():
    d = {
        "SONE-100": ScrapeResult(None, _make("SONE-100", ["巨乳", "痴女"]), None),
        "SONE-101": ScrapeResult(None, _make("SONE-101", ["巨乳", "痴女", "调教"]), None),
        "EMPTY": ScrapeResult(None, CrawlersResult.empty(), None),
    }
    corpus = SimilarDialog.collect_corpus(d)
    assert [c.number for c in corpus] == ["SONE-100", "SONE-101"]


def test_dialog_lists_ranked_similar():
    _app_instance()
    target = _make("SONE-100", ["巨乳", "痴女", "レズ"], series="エスワン")
    corpus = _large_corpus(target)
    corpus.append(_make("SONE-101", ["巨乳", "痴女", "レズ", "调教"], series="エスワン"))

    dlg = SimilarDialog(corpus, target, top_n=5)
    assert dlg._list.count() >= 1
    # 同系列同片商同演员的 SONE-101 应排最前
    assert "SONE-101" in dlg._list.item(0).text()
    dlg.close()


def test_dialog_handles_tiny_corpus():
    _app_instance()
    target = _make("SONE-100", ["巨乳"])
    corpus = [target, _make("STAR-200", ["素人"])]
    dlg = SimilarDialog(corpus, target, top_n=5)
    # 语料太小（2 部）时不应崩溃，显示占位提示
    assert dlg._list.count() == 1
    assert "暂无" in dlg._list.item(0).text()
    dlg.close()


def test_collect_corpus_from_cache_returns_summary_items():
    import tempfile
    from pathlib import Path

    from mdcx.core.scrape_cache import ScrapeStateCache
    from mdcx.views.similar_window import _SummaryItem

    with tempfile.TemporaryDirectory() as d:
        cache = ScrapeStateCache(Path(d) / "scrape_state.db")
        assert cache.open() is True
        cache.set_done(
            Path(d) / "a.mp4",
            mtime=1.0,
            number="ABC-1",
            summary={"number": "ABC-1", "title": "T1", "tags": ["巨乳"], "series": "S", "studio": "ST"},
        )
        corpus = SimilarDialog.collect_corpus_from_cache(cache)
        cache.close()
        assert len(corpus) == 1
        item = corpus[0]
        assert isinstance(item, _SummaryItem)
        assert item.number == "ABC-1"
        assert item.tags == ["巨乳"]
        assert item.series == "S"


def test_collect_corpus_from_cache_none_cache_returns_empty():
    assert SimilarDialog.collect_corpus_from_cache(None) == []
