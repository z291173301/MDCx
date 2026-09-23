"""NFO 合并策略测试：验证 5 种 MergeStrategy 的合并行为。"""

import pytest

from mdcx.config.enums import NfoMergeStrategy
from mdcx.core.nfo_merger import (
    _is_empty,
    _merge_array,
    _merge_scalar,
    merge_nfo_fields,
    should_merge_nfo,
)
from mdcx.models.model_types import CrawlersResult


def _make_result(**kwargs) -> CrawlersResult:
    """构造带指定字段的 CrawlersResult。"""
    result = CrawlersResult.empty()
    for k, v in kwargs.items():
        setattr(result, k, v)
    return result


# ---------- _is_empty ----------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", True),
        ("  ", True),
        (None, True),
        ([], True),
        ({}, True),
        ("text", False),
        (["a"], False),
        (0, False),
    ],
)
def test_is_empty(value, expected):
    assert _is_empty(value) is expected


# ---------- _merge_scalar ----------


class TestMergeScalar:
    def test_both_empty(self):
        val, src = _merge_scalar("outline", "", "", NfoMergeStrategy.PREFER_NFO)
        assert val == ""
        assert src == "empty"

    def test_scraped_empty_nfo_has_value(self):
        val, src = _merge_scalar("outline", "", "本地简介", NfoMergeStrategy.PREFER_NFO)
        assert val == "本地简介"
        assert src == "nfo"

    def test_nfo_empty_scraped_has_value(self):
        val, src = _merge_scalar("outline", "新简介", "", NfoMergeStrategy.PREFER_NFO)
        assert val == "新简介"
        assert src == "scraper"

    def test_both_have_value_prefer_scraper(self):
        val, src = _merge_scalar("outline", "新简介", "本地简介", NfoMergeStrategy.PREFER_SCRAPER)
        assert val == "新简介"
        assert src == "scraper"

    def test_both_have_value_prefer_nfo(self):
        val, src = _merge_scalar("outline", "新简介", "本地简介", NfoMergeStrategy.PREFER_NFO)
        assert val == "本地简介"
        assert src == "nfo"

    def test_both_have_value_preserve_existing(self):
        val, src = _merge_scalar("outline", "新简介", "本地简介", NfoMergeStrategy.PRESERVE_EXISTING)
        assert val == "本地简介"
        assert src == "nfo"

    def test_both_have_value_fill_missing_only(self):
        """fill_missing_only："仅填补空字段"——新数据为主，两源都有值时取新数据。

        原实现误与 preserve_existing 同分支（取本地旧值），与 UI 名称
        "仅填补空字段"/models 描述/docstring 语义矛盾，导致两个选项行为完全重复
        （全库审查 A3，测试原断言锁定的是 bug 行为，随修复反转）。
        """
        val, src = _merge_scalar("outline", "新简介", "本地简介", NfoMergeStrategy.FILL_MISSING_ONLY)
        assert val == "新简介"
        assert src == "scraper"

    def test_both_have_value_merge_arrays(self):
        val, src = _merge_scalar("outline", "新简介", "本地简介", NfoMergeStrategy.MERGE_ARRAYS)
        assert val == "新简介"
        assert src == "scraper"

    def test_critical_field_both_empty_falls_back(self):
        """关键字段（title）两源都空时返回空但标记为 empty。"""
        val, src = _merge_scalar("title", "", "", NfoMergeStrategy.PREFER_NFO)
        assert val == ""
        assert src == "empty"

    def test_critical_field_scraped_empty_uses_nfo(self):
        val, src = _merge_scalar("title", "", "本地标题", NfoMergeStrategy.PREFER_SCRAPER)
        assert val == "本地标题"
        assert src == "nfo"


# ---------- _merge_array ----------


class TestMergeArray:
    def test_both_empty(self):
        val, src = _merge_array("tags", [], [], NfoMergeStrategy.MERGE_ARRAYS)
        assert val == []
        assert src == "empty"

    def test_scraped_empty(self):
        val, src = _merge_array("tags", [], ["本地标签"], NfoMergeStrategy.MERGE_ARRAYS)
        assert val == ["本地标签"]
        assert src == "nfo"

    def test_nfo_empty(self):
        val, src = _merge_array("tags", ["新标签"], [], NfoMergeStrategy.MERGE_ARRAYS)
        assert val == ["新标签"]
        assert src == "scraper"

    def test_merge_arrays_dedup(self):
        val, src = _merge_array("tags", ["推荐", "高清"], ["推荐", "蓝光"], NfoMergeStrategy.MERGE_ARRAYS)
        assert val == ["推荐", "高清", "蓝光"]
        assert src == "merged"

    def test_merge_arrays_dedup_case_insensitive(self):
        val, src = _merge_array("tags", ["Actor"], ["ACTOR", "actor2"], NfoMergeStrategy.MERGE_ARRAYS)
        assert val == ["Actor", "actor2"]
        assert src == "merged"

    def test_prefer_scraper_for_arrays(self):
        val, src = _merge_array("tags", ["新标签"], ["本地标签"], NfoMergeStrategy.PREFER_SCRAPER)
        assert val == ["新标签"]
        assert src == "scraper"

    def test_prefer_nfo_for_arrays(self):
        val, src = _merge_array("tags", ["新标签"], ["本地标签"], NfoMergeStrategy.PREFER_NFO)
        assert val == ["本地标签"]
        assert src == "nfo"


# ---------- merge_nfo_fields ----------


class TestMergeNfoFields:
    def test_prefer_scraper_returns_scraped_directly(self):
        """prefer_scraper 策略直接返回 scraped（保持现有行为）。"""
        scraped = _make_result(title="新标题", outline="新简介", tags=["新标签"])
        nfo = _make_result(title="本地标题", outline="本地简介", tags=["本地标签"])

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.PREFER_SCRAPER)

        assert result.title == "新标题"
        assert result.outline == "新简介"
        assert result.tags == ["新标签"]

    def test_prefer_nfo_uses_local_values(self):
        scraped = _make_result(title="新标题", outline="新简介", tags=["新标签"], runtime="120")
        nfo = _make_result(title="本地标题", outline="本地简介", tags=["本地标签"], runtime="")

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.PREFER_NFO)

        assert result.title == "本地标题"
        assert result.outline == "本地简介"
        assert result.tags == ["本地标签"]
        # runtime 本地为空，用新数据
        assert result.runtime == "120"

    def test_fill_missing_only_preserves_all_existing(self):
        """fill_missing_only 策略：新数据为主，刮削结果为空才从本地补。"""
        scraped = _make_result(title="新标题", outline="", runtime="120", studio="新片商")
        nfo = _make_result(title="本地标题", outline="本地简介", runtime="", studio="")

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.FILL_MISSING_ONLY)

        # 两源都有值：新数据
        assert result.title == "新标题"
        assert result.runtime == "120"
        assert result.studio == "新片商"
        # 刮削结果为空：从本地补
        assert result.outline == "本地简介"

    def test_preserve_existing_differs_from_fill_missing(self):
        """preserve_existing（本地为主）与 fill_missing_only（新数据为主）标量行为相反。"""
        scraped = _make_result(title="新标题", outline="新简介", runtime="120")
        nfo = _make_result(title="本地标题", outline="本地简介", runtime="")

        preserved = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.PRESERVE_EXISTING)
        assert preserved.title == "本地标题"
        assert preserved.outline == "本地简介"
        assert preserved.runtime == "120"

        filled = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.FILL_MISSING_ONLY)
        assert filled.title == "新标题"
        assert filled.outline == "新简介"
        assert filled.runtime == "120"

    def test_merge_arrays_combines_tags_and_actors(self):
        """merge_arrays 策略：数组字段合并去重，标量用新数据。"""
        scraped = _make_result(title="新标题", tags=["推荐", "高清"], actors=["演员A"])
        nfo = _make_result(title="本地标题", tags=["推荐", "蓝光"], actors=["演员B"])

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.MERGE_ARRAYS)

        # 标量用新数据
        assert result.title == "新标题"
        # 数组合并去重
        assert result.tags == ["推荐", "高清", "蓝光"]
        assert result.actors == ["演员A", "演员B"]

    def test_merge_with_none_nfo(self):
        """nfo 为 None 时直接返回 scraped。"""
        scraped = _make_result(title="新标题")

        result = merge_nfo_fields(scraped, None, NfoMergeStrategy.PREFER_NFO)

        assert result.title == "新标题"

    def test_merge_preserves_actor_tmdb_ids(self):
        """合并 actor_tmdb_ids：保留两源的 TMDB ID。"""
        scraped = _make_result()
        scraped.actor_tmdb_ids = {"演员A": 123}
        nfo = _make_result()
        nfo.actor_tmdb_ids = {"演员B": 456}

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.PREFER_NFO)

        assert result.actor_tmdb_ids == {"演员A": 123, "演员B": 456}

    def test_merge_does_not_mutate_original(self):
        """合并不修改原始 scraped 对象。"""
        scraped = _make_result(title="新标题", tags=["新标签"])
        nfo = _make_result(title="本地标题", tags=["本地标签"])

        result = merge_nfo_fields(scraped, nfo, NfoMergeStrategy.PREFER_NFO)

        # 原始 scraped 不变
        assert scraped.title == "新标题"
        assert scraped.tags == ["新标签"]
        # 合并结果是新对象
        assert result.title == "本地标题"
        assert result.tags == ["本地标签"]


# ---------- 配置项测试 ----------


class TestNfoMergeStrategyConfig:
    def test_default_value(self):
        from mdcx.config.models import Config

        config = Config()
        assert config.nfo_merge_strategy == NfoMergeStrategy.PREFER_SCRAPER

    def test_set_strategy(self):
        from mdcx.config.models import Config

        config = Config()
        config.nfo_merge_strategy = NfoMergeStrategy.FILL_MISSING_ONLY
        assert config.nfo_merge_strategy == NfoMergeStrategy.FILL_MISSING_ONLY

    def test_serialization(self):
        from mdcx.config.models import Config

        config = Config()
        config.nfo_merge_strategy = NfoMergeStrategy.MERGE_ARRAYS
        data = config.model_dump()
        assert data["nfo_merge_strategy"] == NfoMergeStrategy.MERGE_ARRAYS

    def test_deserialization(self):
        from mdcx.config.models import Config

        data = {"nfo_merge_strategy": NfoMergeStrategy.PREFER_NFO}
        config = Config.model_validate(data)
        assert config.nfo_merge_strategy == NfoMergeStrategy.PREFER_NFO


def test_nfo_merge_strategy_enum_values():
    """NfoMergeStrategy 枚举值与预期一致。"""
    assert NfoMergeStrategy.PREFER_SCRAPER.value == "prefer_scraper"
    assert NfoMergeStrategy.PREFER_NFO.value == "prefer_nfo"
    assert NfoMergeStrategy.MERGE_ARRAYS.value == "merge_arrays"
    assert NfoMergeStrategy.PRESERVE_EXISTING.value == "preserve_existing"
    assert NfoMergeStrategy.FILL_MISSING_ONLY.value == "fill_missing_only"


# ---------- 本地NFO合并策略勾选框（should_merge_nfo）----------
# 勾选框未勾选（enabled=False）时不执行下拉框选项，直接用新数据覆盖本地 NFO；
# 勾选后按下拉框所选策略合并。以下覆盖成功 / 失败 / 回归三类场景。


class TestShouldMergeNfo:
    # ---- 成功：勾选 + 非 PREFER_SCRAPER 策略 + 本地有 NFO → 执行合并 ----
    @pytest.mark.parametrize(
        "strategy",
        [
            NfoMergeStrategy.PREFER_NFO,
            NfoMergeStrategy.MERGE_ARRAYS,
            NfoMergeStrategy.PRESERVE_EXISTING,
            NfoMergeStrategy.FILL_MISSING_ONLY,
        ],
    )
    def test_success_enabled_merges(self, strategy):
        assert should_merge_nfo(enabled=True, strategy=strategy, nfo_exists=True) is True

    # ---- 失败：勾选框未勾选 → 一律不合并，直接用新数据覆盖 ----
    def test_failure_disabled_skips_merge(self):
        assert should_merge_nfo(enabled=False, strategy=NfoMergeStrategy.PREFER_NFO, nfo_exists=True) is False

    # ---- 失败：策略为 PREFER_SCRAPER（全新数据优先）→ 无需读本地 NFO ----
    def test_failure_prefer_scraper_skips_merge(self):
        assert should_merge_nfo(enabled=True, strategy=NfoMergeStrategy.PREFER_SCRAPER, nfo_exists=True) is False

    # ---- 失败：本地无 NFO 文件 → 无内容可合并 ----
    def test_failure_no_local_nfo_skips_merge(self):
        assert should_merge_nfo(enabled=True, strategy=NfoMergeStrategy.PREFER_NFO, nfo_exists=False) is False

    # ---- 失败：skip_merge（NFO 库表单编辑保存）→ 跳过合并 ----
    def test_failure_skip_merge_flag(self):
        assert (
            should_merge_nfo(
                enabled=True,
                strategy=NfoMergeStrategy.PREFER_NFO,
                nfo_exists=True,
                skip_merge=True,
            )
            is False
        )

    # ---- 回归：勾选（enabled=True）时按下拉框策略合并，行为与改造前一致 ----
    def test_regression_enabled_preserves_old_behavior(self):
        assert should_merge_nfo(enabled=True, strategy=NfoMergeStrategy.PREFER_NFO, nfo_exists=True) is True
        assert should_merge_nfo(enabled=True, strategy=NfoMergeStrategy.MERGE_ARRAYS, nfo_exists=True) is True


class TestNfoMergeEnabledConfig:
    """勾选框开关配置项（nfo_merge_enabled）的成功 / 失败 / 回归。"""

    def test_default_disabled(self):
        from mdcx.config.models import Config

        # 默认不勾选：不执行下拉框选项，直接用新数据覆盖本地 NFO
        config = Config()
        assert config.nfo_merge_enabled is False

    def test_set_enabled(self):
        from mdcx.config.models import Config

        config = Config()
        config.nfo_merge_enabled = True
        assert config.nfo_merge_enabled is True

    def test_serialization_round_trip(self):
        from mdcx.config.models import Config

        config = Config()
        config.nfo_merge_enabled = True
        data = config.model_dump()
        assert data["nfo_merge_enabled"] is True
        restored = Config.model_validate(data)
        assert restored.nfo_merge_enabled is True

    def test_regression_missing_key_defaults_disabled(self):
        from mdcx.config.models import Config

        # 旧配置无 nfo_merge_enabled 字段 → 默认不勾选（不合并）
        config = Config.model_validate({"nfo_merge_strategy": NfoMergeStrategy.PREFER_NFO})
        assert config.nfo_merge_enabled is False
