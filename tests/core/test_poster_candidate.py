from mdcx.core.web import PosterCandidate, _select_best_poster_candidate


def _candidate(source: str, w: int, h: int) -> PosterCandidate:
    return PosterCandidate(source=source, url=f"https://example.test/{source}.jpg", image_download=True, size=(w, h))


def test_select_best_poster_returns_portrait_when_crop_size_known():
    candidates = [_candidate("landscape", 840, 568), _candidate("portrait", 640, 900)]
    result = _select_best_poster_candidate(candidates, (100, 150))
    assert result is not None
    assert result.source == "portrait"


def test_select_best_poster_returns_none_when_all_landscape():
    candidates = [_candidate("landscape1", 840, 568), _candidate("landscape2", 1280, 720)]
    result = _select_best_poster_candidate(candidates, (100, 150))
    assert result is None


def test_select_best_poster_picks_smallest_landscape_when_all_landscape_and_crop_larger():
    candidates = [_candidate("big", 1920, 1080), _candidate("small", 640, 480)]
    result = _select_best_poster_candidate(candidates, (100, 150))
    assert result is None


def test_select_best_poster_returns_best_portrait_when_mixed():
    candidates = [
        _candidate("landscape", 840, 568),
        _candidate("small_portrait", 400, 600),
        _candidate("big_portrait", 800, 1200),
    ]
    result = _select_best_poster_candidate(candidates, (100, 150))
    assert result is not None
    assert result.source == "big_portrait"


def test_select_best_poster_filters_portrait_even_when_crop_size_unknown():
    candidates = [_candidate("landscape", 840, 568), _candidate("portrait", 640, 900)]
    result = _select_best_poster_candidate(candidates, (0, 0))
    assert result is not None
    assert result.source == "portrait"


def test_select_best_poster_returns_none_when_all_landscape_and_crop_unknown():
    candidates = [_candidate("landscape1", 840, 568), _candidate("landscape2", 1280, 720)]
    result = _select_best_poster_candidate(candidates, (0, 0))
    assert result is None


def test_select_best_poster_returns_none_when_no_known_sizes():
    candidates = [_candidate("unknown", 0, 0)]
    result = _select_best_poster_candidate(candidates, (100, 150))
    assert result is None


def test_select_best_poster_returns_none_when_empty():
    result = _select_best_poster_candidate([], (100, 150))
    assert result is None
