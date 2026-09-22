"""LLM 翻译结果缓存（同批次内复用）。

痛点：系列片/合集片标题高度相似（同番号系列前缀 + 相同副标题模式），
重刮与一键重刮失败列表时也会翻译完全相同的文本；LLM 按 token 计费，
重复翻译是纯浪费。

设计：key = (prompt_template, target_language, text) → 进程内缓存。
并发去重：相同 key 的并发请求共享同一 in-flight Future（合并等待），
完成后落缓存。容量 LRU 有界，失败结果不缓存（下次重试）。
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict

_MAX_ENTRIES = 512


class LLMTranslateCache:
    """带 in-flight 合并的有界 LRU 翻译缓存（单事件循环内使用）。"""

    def __init__(self, max_entries: int = _MAX_ENTRIES):
        self._max = max(int(max_entries), 1)
        self._cache: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        self._inflight: dict[tuple[str, str, str], asyncio.Future[str | None]] = {}

    @staticmethod
    def make_key(prompt_template: str, target_language: str, text: str) -> tuple[str, str, str]:
        return (str(prompt_template), str(target_language), str(text))

    async def get_or_translate(
        self,
        key: tuple[str, str, str],
        translate_fn,
    ) -> str | None:
        """命中缓存直接返回；否则执行 translate_fn（可返回 None 表示失败）。

        相同 key 的并发调用合并为一次实际翻译。
        """
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        future = self._inflight.get(key)
        if future is not None:
            # 已有相同文本在翻译中：合并等待
            return await asyncio.shield(future)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._inflight[key] = future
        try:
            result = await translate_fn()
            if result is None:
                # 失败不缓存：让后续调用重试
                if not future.done():
                    future.set_result(None)
                return None
            self._store(key, result)
            if not future.done():
                future.set_result(result)
            return result
        except Exception as e:
            if not future.done():
                future.set_exception(e)
            raise
        finally:
            self._inflight.pop(key, None)

    def _store(self, key: tuple[str, str, str], value: str) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()
        self._inflight.clear()

    def __len__(self) -> int:
        return len(self._cache)
