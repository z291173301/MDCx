from unittest.mock import AsyncMock, patch

import pytest

from mdcx.tools.actor_db_tool import _translate_bio_text_fields


@pytest.mark.asyncio
async def test_translate_bio_fields_info_priority():
    """事务所/标签用 info 库映射，出身/爱好用翻译引擎"""
    bio = "出身: 東京都 | 爱好: ショッピング | 事务所: マインズ | 标签: 巨乳,パイパン"

    def fake_get_info_data(info):
        mapping = {"マインズ": "Mines", "パイパン": "无毛"}
        if info in mapping:
            return {"zh_cn": mapping[info], "has_name": True}
        return {"zh_cn": info, "has_name": False}

    async def fake_translate(engine, title, outline, **kwargs):
        mapping = {"東京都": "东京都", "ショッピング": "购物"}
        out = mapping.get(title, title)
        return type("R", (), {"title": out, "error": None})()

    with (
        patch("mdcx.tools.actor_db_tool.resources.get_info_data", side_effect=fake_get_info_data),
        patch("mdcx.tools.actor_db_tool.manager.config.translate_config.translate_by", ["google"]),
        patch("mdcx.base.translate.translate_with_engine", new=AsyncMock(side_effect=fake_translate)),
        patch("mdcx.base.translate.get_translator_skip_reason", return_value=None),
    ):
        result = await _translate_bio_text_fields(bio)

    print(f"翻译结果: {result}")
    assert "出身: 东京都" in result
    assert "爱好: 购物" in result
    assert "事务所: Mines" in result
    assert "标签: 巨乳,无毛" in result
    assert "パイパン" not in result


@pytest.mark.asyncio
async def test_translate_bio_no_engine():
    """无翻译引擎时原样返回"""
    bio = "出身: 東京都"
    with patch("mdcx.tools.actor_db_tool.manager.config.translate_config.translate_by", []):
        result = await _translate_bio_text_fields(bio)
    assert result == bio


@pytest.mark.asyncio
async def test_translate_bio_no_japanese():
    """无日文假名时原样返回"""
    bio = "出身: 东京都 | 爱好: 购物"
    result = await _translate_bio_text_fields(bio)
    assert result == bio


@pytest.mark.asyncio
async def test_translate_bio_fail_keep_original():
    """翻译失败保留原文"""
    bio = "出身: 東京都 | 爱好: ショッピング"

    async def fake_translate_fail(engine, title, outline, **kwargs):
        return type("R", (), {"title": "", "error": "failed"})()

    with (
        patch("mdcx.tools.actor_db_tool.manager.config.translate_config.translate_by", ["google"]),
        patch("mdcx.base.translate.translate_with_engine", new=AsyncMock(side_effect=fake_translate_fail)),
        patch("mdcx.base.translate.get_translator_skip_reason", return_value=None),
    ):
        result = await _translate_bio_text_fields(bio)
    assert result == bio


@pytest.mark.asyncio
async def test_translate_bio_kanji_place():
    """日文汉字地名（東京都）也要翻译"""
    bio = "出身: 東京都 | 爱好: ショッピング"

    async def fake_translate(engine, title, outline, **kwargs):
        mapping = {"東京都": "东京都", "ショッピング": "购物"}
        out = mapping.get(title, title)
        return type("R", (), {"title": out, "error": None})()

    with (
        patch("mdcx.tools.actor_db_tool.manager.config.translate_config.translate_by", ["google"]),
        patch("mdcx.base.translate.translate_with_engine", new=AsyncMock(side_effect=fake_translate)),
        patch("mdcx.base.translate.get_translator_skip_reason", return_value=None),
    ):
        result = await _translate_bio_text_fields(bio)
    assert "出身: 东京都" in result
    assert "爱好: 购物" in result
