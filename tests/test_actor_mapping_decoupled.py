"""结构哨兵测试：演员/信息映射与「是否写 NFO」解耦。

背景（issue #53）：视频整理模式不写 NFO，此前整个映射块被 `if not pre_data and update_nfo:`
包住，导致 `translate_actor` 被跳过，`res.actors` 保持日文原名，文件夹命名变量 `{actor}`
输出日文。演员映射同时服务于命名变量（{actor}/{first_actor}/{all_actor}）和 NFO，
不应受 NFO 开关控制。

本测试用 AST 校验调用位置，避免回归时再次把映射调用挪回 update_nfo 分支内。
"""

import ast
from pathlib import Path

SCRAPER_PATH = Path(__file__).resolve().parents[1] / "mdcx" / "core" / "scraper.py"

# 必须无条件执行（仅受 not pre_data 约束）的映射调用
MAPPING_CALLS = ("translate_actor", "translate_info", "replace_word")
# 必须保留在 update_nfo 分支内的高开销调用
NFO_ONLY_CALLS = ("translate_title_outline",)


def _called_names(nodes: list[ast.stmt]) -> set[str]:
    """收集给定语句列表中的调用名，不下探嵌套 If。"""
    names: set[str] = set()
    for node in nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.If):
                continue
            if isinstance(sub, ast.Call):
                func = sub.func
                if isinstance(func, ast.Name):
                    names.add(func.id)
                elif isinstance(func, ast.Attribute):
                    names.add(func.attr)
    return names


def _direct_body_calls(if_node: ast.If) -> set[str]:
    """收集 If body 中不在嵌套 If 内的调用名。"""
    direct = [stmt for stmt in if_node.body if not isinstance(stmt, ast.If)]
    return _called_names(direct)


def _find_mapping_block(tree: ast.Module) -> ast.If:
    """定位包含 translate_actor 调用的最内层 If 节点。"""
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and "translate_actor" in _called_names(list(node.body))
    ]
    assert candidates, "未在 scraper.py 中找到调用 translate_actor 的 if 块"
    # 取 body 中直接调用 translate_actor 的那个（最内层）
    innermost = [node for node in candidates if "translate_actor" in _direct_body_calls(node)]
    assert innermost, "translate_actor 未直接出现在任一 if 块的 body 顶层"
    return innermost[0]


def test_mapping_block_condition_excludes_update_nfo():
    """映射块的条件不得包含 update_nfo。"""
    tree = ast.parse(SCRAPER_PATH.read_text(encoding="utf-8"))
    block = _find_mapping_block(tree)
    condition_names = {node.id for node in ast.walk(block.test) if isinstance(node, ast.Name)}
    assert "update_nfo" not in condition_names, (
        f"映射块条件仍依赖 update_nfo（当前条件涉及 {sorted(condition_names)}）；"
        "演员映射服务于命名变量，整理模式不写 NFO 时也必须执行"
    )
    assert "pre_data" in condition_names, "映射块应仍受 pre_data 约束（已有刮削数据时跳过）"


def test_mapping_calls_run_unconditionally():
    """演员/信息映射调用必须位于映射块 body 顶层，而非嵌套的 update_nfo 分支内。"""
    tree = ast.parse(SCRAPER_PATH.read_text(encoding="utf-8"))
    block = _find_mapping_block(tree)
    direct = _direct_body_calls(block)
    missing = [name for name in MAPPING_CALLS if name not in direct]
    assert not missing, f"以下映射调用未无条件执行，可能被挪进了 update_nfo 分支：{missing}"


def test_expensive_translation_stays_behind_update_nfo():
    """LLM 标题/简介翻译等高开销调用必须保留在 update_nfo 分支内。"""
    tree = ast.parse(SCRAPER_PATH.read_text(encoding="utf-8"))
    block = _find_mapping_block(tree)

    nested_update_nfo = [
        stmt
        for stmt in block.body
        if isinstance(stmt, ast.If)
        and "update_nfo" in {node.id for node in ast.walk(stmt.test) if isinstance(node, ast.Name)}
    ]
    assert nested_update_nfo, "映射块内应存在 if update_nfo 分支，用于隔离高开销的翻译与 TMDB 查询"

    guarded = set()
    for stmt in nested_update_nfo:
        guarded |= _called_names(list(stmt.body))

    leaked = [name for name in NFO_ONLY_CALLS if name not in guarded]
    assert not leaked, f"以下高开销调用应保留在 update_nfo 分支内，避免整理模式额外开销：{leaked}"

    # TMDB ID 查询须在演员映射前用原始名执行，因此也必须在 update_nfo 分支内
    assert "fetch_actor_tmdb_ids" in guarded, (
        "演员 TMDB ID 查询应保留在 update_nfo 分支内（须在映射前使用日文原名查询）"
    )


def test_original_actors_saved_before_mapping():
    """原始演员名保存语句必须在 translate_actor 之前，供读取模式反向查找。"""
    tree = ast.parse(SCRAPER_PATH.read_text(encoding="utf-8"))
    block = _find_mapping_block(tree)

    save_line = None
    mapping_line = None
    for stmt in block.body:
        if isinstance(stmt, ast.If):
            continue
        segment = ast.dump(stmt)
        if "original_actors" in segment and save_line is None:
            save_line = stmt.lineno
        if "translate_actor" in segment and mapping_line is None:
            mapping_line = stmt.lineno

    assert save_line is not None, "未找到 original_actors 保存语句"
    assert mapping_line is not None, "未找到 translate_actor 调用"
    assert save_line < mapping_line, "original_actors 必须在 translate_actor 之前保存（保存映射前的原始名）"
