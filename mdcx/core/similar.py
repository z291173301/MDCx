"""相似片推荐（本地离线规则，无网络/无模型）。

移植自 OpenAver 的 core/similar（MIT License）设计：
- tag IDF 加权 Jaccard 相似度作为基础分
- 系列/片商/年份/时长/演员组合作为加分项
- MMR 重排避免推荐结果彼此过于同质
- 全程本地计算，输入即刮削结果（BaseCrawlerResult / CrawlersResult）

用法：先用一批刮削结果建索引，再对单个目标求相似。

    index = SimilarIndex(results)
    for cand, score in index.rank(target, top_n=12):
        print(cand.number, cand.title, round(score, 3))
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Protocol, TypeVar

# 热门 tag 阈值：出现比例超过该值视为“无区分度”的常见标签，IDF 记为 0（不参与排序）
IDF_HOT_THRESHOLD = 0.25

# 番号前缀提取（支持 FC2-PPV 等多段前缀）
_PREFIX_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z][A-Za-z0-9]*)*)(?=-?\d)", re.IGNORECASE)


class _SimilarItem(Protocol):
    number: str
    tags: list[str]
    series: str
    studio: str
    actors: list[str]
    release: str
    runtime: str
    mosaic: str
    publisher: str
    directors: list[str]
    score: str


T = TypeVar("T", bound=_SimilarItem)


def _tag_set(tags: Iterable[str]) -> set[str]:
    """去空 + 去重，返回规范化 tag 集合。"""
    return {str(t).strip() for t in tags if t and str(t).strip()}


def _extract_year(release: str) -> int | None:
    if not release:
        return None
    m = re.match(r"^(\d{4})", str(release).strip())
    return int(m.group(1)) if m else None


def _duration_bucket(runtime: str) -> int | None:
    """片长分三桶（<=20 / 20-60 / 60+）；无法解析返回 None。"""
    if not runtime:
        return None
    try:
        minutes = int(float(str(runtime).strip()))
    except (TypeError, ValueError):
        return None
    if minutes <= 0:
        return None
    if minutes <= 20:
        return 0
    if minutes <= 60:
        return 1
    return 2


def _cast_bucket(actors: Iterable[str]) -> str:
    """演员组合桶：none / solo / duo / multi。"""
    n = len([a for a in actors if a and str(a).strip()])
    if n <= 0:
        return "none"
    if n == 1:
        return "solo"
    if n == 2:
        return "duo"
    return "multi"


def _parse_score(score: str) -> float | None:
    """解析评分字符串（如 "8.5" / "8.5分" / "8,5"），解析失败返回 None。"""
    if not score:
        return None
    try:
        cleaned = str(score).strip().replace("分", "").replace(",", ".").replace("　", "")
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _score_proximity(target_score: str, cand_score: str, tolerance: float = 1.0) -> float:
    """评分接近度：两者都有效且差距在容差内返回 1.0，否则 0.0。"""
    ts = _parse_score(target_score)
    cs = _parse_score(cand_score)
    if ts is None or cs is None:
        return 0.0
    return 1.0 if abs(ts - cs) <= tolerance else 0.0


def extract_prefix(number: str) -> str | None:
    """提取番号前缀（如 SONE-205 -> SONE, FC2-PPV-1234 -> FC2-PPV）。"""
    if not number:
        return None
    m = _PREFIX_RE.match(str(number).strip())
    return m.group(1).upper() if m else None


def build_idf(corpus_tags: list[set[str]]) -> dict[str, float]:
    """基于语料构建 tag IDF 表。出现比例超过热阈值的 tag 得 0。"""
    n = len(corpus_tags)
    if n == 0:
        return {}
    df = Counter(t for tags in corpus_tags for t in tags)
    if not df:
        return {}
    result: dict[str, float] = {}
    for tag, count in df.items():
        if count / n > IDF_HOT_THRESHOLD:
            result[tag] = 0.0
        else:
            result[tag] = math.log((n + 1) / (count + 1)) + 1
    return result


def idf_jaccard(a: set[str], b: set[str], idf_table: dict[str, float]) -> float:
    """IDF 加权 Jaccard：分子为交集 tag 的 IDF 和，分母为并集 tag 的 IDF 和。"""
    numerator = sum(idf_table.get(t, 0.0) for t in a & b)
    denominator = sum(idf_table.get(t, 0.0) for t in a | b)
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def gaussian_year_proximity(target_year: int | None, cand_year: int | None, sigma: float = 4.0) -> float:
    if target_year is None or cand_year is None:
        return 0.0
    diff = cand_year - target_year
    return math.exp(-0.5 * (diff / sigma) ** 2)


class SimilarIndex[T: _SimilarItem]:
    """对一批刮削结果建立相似索引，支持对单条结果求相似。"""

    def __init__(self, corpus: Iterable[T]) -> None:
        self._corpus: list[T] = list(corpus)
        self._canon_tags: list[set[str]] = [_tag_set(item.tags) for item in self._corpus]
        self._idf_table = build_idf(self._canon_tags)
        # 倒排索引：tag -> 视频下标（全部 tag 入索引，热门 tag 只影响排序不影响召回）
        self._inverted: dict[str, list[int]] = defaultdict(list)
        for i, tags in enumerate(self._canon_tags):
            for t in tags:
                self._inverted[t].append(i)

    def _useful_tags(self, tags: Iterable[str]) -> set[str]:
        return {t for t in _tag_set(tags) if self._idf_table.get(t, 0.0) > 0}

    def _retrieve(self, target: T, top_n: int = 100) -> list[T]:
        """倒排检索候选（基于全部 tag 的召回，IDF 权重仅用于 _score 精排）。"""
        all_tags = _tag_set(target.tags)
        if not all_tags:
            return []
        scores: dict[int, float] = defaultdict(float)
        for t in all_tags:
            idf = self._idf_table.get(t, 0.0)
            # 热门 tag（IDF=0）权重按 1 计入召回分，保证同热门 tag 的影片仍能召回
            weight = idf if idf > 0 else 1.0
            for i in self._inverted.get(t, []):
                scores[i] += weight
        target_number = getattr(target, "number", None)
        # 用番号主键排除 target 自身：语料混合了当次结果对象与缓存摘要对象时，
        # 同一影片可能是不同对象实例，`is not` 身份比较会失效导致"自己推荐自己"。
        filtered = [
            (i, s)
            for i, s in scores.items()
            if self._corpus[i] is not target and getattr(self._corpus[i], "number", None) != target_number
        ]
        filtered.sort(key=lambda kv: kv[1], reverse=True)
        return [self._corpus[i] for i, _ in filtered[:top_n]]

    def _score(self, target: T, cand: T) -> float:
        target_canon = _tag_set(target.tags)
        cand_canon = _tag_set(cand.tags)
        rel = idf_jaccard(target_canon, cand_canon, self._idf_table)

        # 马赛克类型（有码/无码）是决定性维度：相同大幅加分，不同明显惩罚
        if target.mosaic and target.mosaic == cand.mosaic:
            rel += 0.35
        elif target.mosaic and cand.mosaic:
            rel -= 0.30

        if cand.series and cand.series == target.series:
            rel += 0.30
        if cand.studio and cand.studio == target.studio:
            rel += 0.20
        # 发行商与制作商是两个维度（如 DMM 发行 vs 各厂制作），一致时单独加分
        if cand.publisher and cand.publisher == target.publisher:
            rel += 0.15
        # 导演风格信号：有交集加分
        if set(target.directors) & set(cand.directors):
            rel += 0.15
        rel += 0.15 * gaussian_year_proximity(_extract_year(target.release), _extract_year(cand.release))
        rel += 0.05 * _score_proximity(target.score, cand.score)

        tgt_bucket = _duration_bucket(target.runtime)
        cand_bucket = _duration_bucket(cand.runtime)
        if tgt_bucket is not None and tgt_bucket == cand_bucket:
            rel += 0.10

        tgt_cast = _cast_bucket(target.actors)
        cand_cast = _cast_bucket(cand.actors)
        if tgt_cast == cand_cast and tgt_cast in ("duo", "multi"):
            rel += 0.20

        if set(target.actors) & set(cand.actors):
            if cand.series and cand.series == target.series:
                rel -= 0.15
            else:
                rel -= 0.50

        return rel

    def _sim(self, a: T, b: T) -> float:
        """演员相似度（供 MMR 使用）：演员 Jaccard * 0.7 + 片商一致 * 0.3。"""
        sa, sb = set(a.actors), set(b.actors)
        actress_jac = len(sa & sb) / len(sa | sb) if (sa or sb) else 0.0
        maker_match = 1.0 if (a.studio and a.studio == b.studio) else 0.0
        return actress_jac * 0.7 + maker_match * 0.3

    def _mmr_rerank(self, target: T, candidates: list[T], top_k: int = 12) -> list[tuple[T, float]]:
        """MMR 重排：在相关性与多样性间平衡，避免推荐结果全是同一演员/片商。"""
        if not candidates or top_k <= 0:
            return []
        lambda_ = 0.7
        rel_cache = {id(c): self._score(target, c) for c in candidates}
        remaining = list(candidates)
        selected: list[T] = []
        while remaining and len(selected) < top_k:
            best = None
            best_score = float("-inf")
            for c in remaining:
                rel = rel_cache[id(c)]
                max_sim = max((self._sim(c, s) for s in selected), default=0.0)
                mmr = lambda_ * rel - (1 - lambda_) * max_sim
                if mmr > best_score:
                    best_score = mmr
                    best = c
            if best is None:
                break
            selected.append(best)
            remaining.remove(best)
        return [(c, rel_cache[id(c)]) for c in selected]

    def rank(self, target: T, top_n: int = 12) -> list[tuple[T, float]]:
        """返回与 target 最相似的结果列表（(item, score)，按综合分降序）。

        top_n 为最终返回条数；内部粗筛取 top_n*4 再精排，兼顾召回与性能。
        """
        candidates = self._retrieve(target, top_n=top_n * 4)
        if not candidates:
            return []
        return self._mmr_rerank(target, candidates, top_k=top_n)
