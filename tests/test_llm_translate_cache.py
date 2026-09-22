"""LLM 翻译缓存测试：命中 / 并发合并 / 失败不缓存 / LRU 有界。"""

import asyncio

from mdcx.core.llm_translate_cache import LLMTranslateCache


def _key(text: str, prompt: str = "p", lang: str = "简体中文") -> tuple[str, str, str]:
    return LLMTranslateCache.make_key(prompt, lang, text)


def test_cache_hit_avoids_retranslate():
    """相同 key 第二次调用不再触发翻译函数"""
    cache = LLMTranslateCache()
    calls = []

    async def translate_fn():
        calls.append(1)
        await asyncio.sleep(0.01)
        return "译文"

    async def main():
        r1 = await cache.get_or_translate(_key("原文"), translate_fn)
        r2 = await cache.get_or_translate(_key("原文"), translate_fn)
        assert r1 == r2 == "译文"
        assert len(calls) == 1  # 只翻译了一次
        # 不同 prompt/lang 是不同 key
        await cache.get_or_translate(_key("原文", prompt="p2"), translate_fn)
        assert len(calls) == 2

    asyncio.run(main())


def test_concurrent_calls_merge_into_one():
    """并发相同 key 只执行一次翻译，多个等待者拿到同一结果"""
    cache = LLMTranslateCache()
    calls = []

    async def slow_translate():
        calls.append(1)
        await asyncio.sleep(0.05)
        return "合并译文"

    async def main():
        results = await asyncio.gather(*[cache.get_or_translate(_key("同文本"), slow_translate) for _ in range(5)])
        assert all(r == "合并译文" for r in results)
        assert len(calls) == 1  # 5 个并发只翻译一次

    asyncio.run(main())


def test_failure_not_cached():
    """翻译失败返回 None 不落缓存：下次调用重新执行"""
    cache = LLMTranslateCache()
    calls = []

    async def fail_then_success():
        calls.append(1)
        if len(calls) == 1:
            return None  # 第一次失败
        return "重试成功"

    async def main():
        r1 = await cache.get_or_translate(_key("原文"), fail_then_success)
        assert r1 is None
        r2 = await cache.get_or_translate(_key("原文"), fail_then_success)
        assert r2 == "重试成功"
        assert len(calls) == 2

    asyncio.run(main())


def test_lru_evicts_oldest():
    """超过容量逐出最旧条目"""
    cache = LLMTranslateCache(max_entries=2)
    calls = []

    async def translate_fn():
        calls.append(1)
        return f"译{len(calls)}"

    async def main():
        await cache.get_or_translate(_key("A"), translate_fn)
        await cache.get_or_translate(_key("B"), translate_fn)
        # 访问 A 让 B 变最旧
        await cache.get_or_translate(_key("A"), translate_fn)
        assert len(cache) == 2
        await cache.get_or_translate(_key("C"), translate_fn)  # 逐出 B
        assert len(cache) == 2
        # A 仍在缓存（命中），B 需重译
        a_calls = len(calls)
        await cache.get_or_translate(_key("A"), translate_fn)
        assert len(calls) == a_calls
        await cache.get_or_translate(_key("B"), translate_fn)
        assert len(calls) > a_calls

    asyncio.run(main())


def test_concurrent_merge_failure_propagates():
    """并发合并时失败传播给所有等待者，且不落缓存"""
    cache = LLMTranslateCache()

    async def always_fail():
        return None

    async def main():
        results = await asyncio.gather(*[cache.get_or_translate(_key("X"), always_fail) for _ in range(3)])
        assert all(r is None for r in results)
        assert len(cache) == 0

    asyncio.run(main())
