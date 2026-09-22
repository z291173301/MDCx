"""
议题 #57 回归测试：NFO 库管理保存后字段丢失检测

覆盖场景：
- P1：单条保存后 originalplot 丢失（表单没有该字段，但从空 CrawlersResult 组装时未保留原值）
- P2：get_nfo_data 读取时 outline 为空、只有 originalplot 时无法读取简介
- P3：标签顺序在 NFO 库管理保存时被 prioritize_nfo_tags 重排
"""

from types import SimpleNamespace

import pytest
from lxml import etree

from mdcx.config.enums import Language, NfoInclude
from mdcx.core import nfo as nfo_module
from mdcx.core import tag_priority
from mdcx.models.model_types import CrawlersResult, FileInfo


class _RenderedTitle:
    def __init__(self, text: str):
        self.text = text


def _build_file_info(tmp_path) -> FileInfo:
    file_info = FileInfo.empty()
    file_info.number = "ABC-123"
    file_info.file_path = tmp_path / "ABC-123.mp4"
    file_info.folder_path = tmp_path
    file_info.file_name = "ABC-123"
    return file_info


def _configure_nfo_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nfo_module.manager.config, "download_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "keep_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "outline_format", [])
    monkeypatch.setattr(nfo_module.manager.config, "main_mode", 1)
    monkeypatch.setattr(nfo_module.manager.config, "naming_media", "number title")
    monkeypatch.setattr(nfo_module.manager.config, "update_titletemplate", "number title")
    monkeypatch.setattr(
        nfo_module.manager.config,
        "nfo_include_new",
        [NfoInclude.PLOT_, NfoInclude.OUTLINE, NfoInclude.ORIGINALPLOT, NfoInclude.TAG, NfoInclude.GENRE],
    )
    monkeypatch.setattr(nfo_module.manager.config, "nfo_tag_series", "系列: series")
    monkeypatch.setattr(nfo_module.manager.config, "actor_no_name", "佚名")
    monkeypatch.setattr(nfo_module.manager.config, "read_mode", [])
    monkeypatch.setattr(
        nfo_module.manager.config.__class__,
        "get_field_config",
        lambda self, field: SimpleNamespace(language=Language.JP),
    )
    monkeypatch.setattr(nfo_module, "render_name", lambda *args, **kwargs: _RenderedTitle("ABC-123 标题"))


@pytest.mark.asyncio
async def test_nfo_save_preserves_originalplot(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """P1：保存后 originalplot 不应丢失。表单没 originalplot 字段时，应保留原值。"""
    _configure_nfo_writer(monkeypatch)

    # 先写入含 originalplot 的 NFO
    file_info = _build_file_info(tmp_path)
    file_info.file_path.write_bytes(b"")
    data = CrawlersResult.empty()
    data.number = "ABC-123"
    data.title = "标题"
    data.originaltitle = "原标题"
    data.outline = "中文简介"
    data.originalplot = "日文简介"
    nfo_file = tmp_path / "ABC-123.nfo"
    await nfo_module.write_nfo(file_info, data, nfo_file, tmp_path, update=True, skip_merge=True)

    # 读回来
    loaded, _ = await nfo_module.get_nfo_data(file_info.file_path, "ABC-123")
    assert loaded is not None
    assert loaded.outline == "中文简介"
    assert loaded.originalplot == "日文简介"

    # 模拟单条保存（复刻 _collect_form_data 修复后行为：表单字段只填表单可见的，
    # 表单没有的字段从原数据继承）
    new_data = CrawlersResult.empty()
    new_data.number = loaded.number
    new_data.title = loaded.title
    new_data.originaltitle = loaded.originaltitle
    new_data.outline = "用户在GUI里手动改的简介"
    new_data.originalplot = loaded.originalplot  # _collect_form_data 会从 _nfo_lib_original_data 继承
    await nfo_module.write_nfo(file_info, new_data, nfo_file, tmp_path, update=True, skip_merge=True)

    # 修复后：originalplot 应被保留
    reloaded, _ = await nfo_module.get_nfo_data(file_info.file_path, "ABC-123")
    assert reloaded is not None
    assert reloaded.outline == "用户在GUI里手动改的简介"
    assert reloaded.originalplot == "日文简介", "P1 bug: originalplot 被丢失"


@pytest.mark.asyncio
async def test_nfo_read_falls_back_to_originalplot(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """P2：plot/outline 为空时，简介应 fallback 到 originalplot。"""
    _configure_nfo_writer(monkeypatch)
    monkeypatch.setattr(nfo_module.manager.config, "read_mode", [])

    video_path = tmp_path / "ABC-123.mp4"
    video_path.write_bytes(b"")
    nfo_path = tmp_path / "ABC-123.nfo"
    nfo_path.write_text(
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>ABC-123 标题</title>
  <originaltitle>ABC-123 原标题</originaltitle>
  <num>ABC-123</num>
  <originalplot>只有日文原文，没有中文翻译</originalplot>
</movie>
""",
        encoding="utf-8",
    )

    data, _ = await nfo_module.get_nfo_data(video_path, "ABC-123")
    assert data is not None
    assert data.originalplot == "只有日文原文，没有中文翻译"
    # outline 为空，应 fallback 到 originalplot
    assert data.outline == "只有日文原文，没有中文翻译"


@pytest.mark.asyncio
async def test_nfo_save_preserves_user_tag_order(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """P3：NFO 库管理保存后标签顺序不应被 prioritize_nfo_tags 重排。"""
    _configure_nfo_writer(monkeypatch)
    # 确保 priority mapping 不是空的（否则不会触发重排）
    monkeypatch.setattr(
        tag_priority.resources,
        "info_mapping_data",
        etree.fromstring(
            """
            <info>
              <a zh_cn="M女" zh_tw="M女" jp="M女" keyword=",M女," />
              <a zh_cn="巨乳" zh_tw="巨乳" jp="巨乳" keyword=",巨乳," />
            </info>
            """.encode(),
        ),
    )
    # random.shuffle 结果跨平台不一致（OS entropy），与 test_nfo_tag_priority 对齐统一反向
    monkeypatch.setattr(tag_priority.random, "shuffle", lambda items: items.reverse())
    tag_priority.clear_priority_tag_cache()

    data = CrawlersResult.empty()
    data.number = "ABC-123"
    data.title = "标题"
    data.originaltitle = "原标题"
    # 用户手动排的顺序：巨乳、M女 —— prioritize_nfo_tags 应将 M女 前置
    data.tags = ["巨乳", "M女", "其他标签"]

    file_info = _build_file_info(tmp_path)
    file_info.file_path.write_bytes(b"")
    nfo_file = tmp_path / "ABC-123.nfo"

    # 主刮削流程：preserve_tag_order=False (默认) 应触发 prioritize 重排 — M女 前置
    await nfo_module.write_nfo(file_info, data, nfo_file, tmp_path, update=True, skip_merge=True)
    root = etree.fromstring(nfo_file.read_text(encoding="utf-8").encode("utf-8"))
    tag_texts = root.xpath("//tag/text()")
    assert tag_texts[0] == "M女", f"主刮削路径标签应重排优先, 实际: {tag_texts}"
    assert tag_texts == ["M女", "巨乳", "其他标签"]

    # NFO 库管理场景：用户手动把"其他标签"调整到最后 -> 保存后顺序不变
    loaded, _ = await nfo_module.get_nfo_data(file_info.file_path, "ABC-123")
    assert loaded is not None
    # 模拟用户在表单中把 tag 改为 "巨乳,M女,其他标签"（把 M女 放巨乳后）
    loaded.tags = ["巨乳", "M女", "其他标签"]
    await nfo_module.write_nfo(
        file_info, loaded, nfo_file, tmp_path, update=True, skip_merge=True, preserve_tag_order=True
    )
    root2 = etree.fromstring(nfo_file.read_text(encoding="utf-8").encode("utf-8"))
    tag_texts2 = root2.xpath("//tag/text()")
    # NFO库管理保存后顺序应被完整保留（哪怕 M女 在优先级列表中仍被 Relocate 到前部）
    assert tag_texts2 == ["巨乳", "M女", "其他标签"], f"NFO库管理应保留用户顺序, 实际: {tag_texts2}"
