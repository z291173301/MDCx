"""议题 #164: 演员「重复」计数的同名去重回归测试。

背景(真机 http://192.168.0.101:8096 实测):
- 勾选「仅演员」重复 40, 不勾选 41 —— 这本身**不是 bug**:
  `张磊` 是两个不同的人(Emby Id 74547 / 115591, Bangumi 40272 / 73024),
  只有 Id 74547 有 Actor 演出, 服务端 personTypes=Actor 过滤掉另一条,
  于是 `张磊` 在不勾选档是重名组(贡献 1), 在勾选档只剩一条(贡献 0)。
  `重复 = 原始条目数 − 唯一名字数` 在两档都严格成立。
- 但顺着这条线查出两个**真 bug**:
  1. 去重键原是原始 Name, 全角/半角写法差异的同一个人不会合并,
     重复因此少报(真机: `小松（17）`vs`小松(17)`、`［Jo］Style`vs`[Jo]Style`、
     `ﾘﾅ･ﾃﾞｨｿﾝ`vs`リナ・ディソン`)。
  2. 去重是"先到先得", 同一人的多条里若第一条资料更差(无头像),
     合并结果会凭空缺头像, 统计栏把ta 误判成「全缺」(真机: `Sunshine`)。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mdcx.tools import emby_actor_manager as eam

# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #


def _person(
    name: str,
    pid: str = "",
    *,
    image: bool = False,
    overview: str = "",
    backdrop: bool = False,
    provider_ids: dict | None = None,
) -> dict:
    """构造一条 /Persons 记录(只含 fetch_all_actors 会读的字段)。"""
    return {
        "Name": name,
        "Id": pid or f"id-{name}",
        "ServerId": "srv",
        "Type": "Person",
        "Taglines": [],
        "ImageTags": {"Primary": "abc"} if image else {},
        "BackdropImageTags": ["bd"] if backdrop else [],
        "ProviderIds": provider_ids or {},
        "Overview": overview,
        "ProductionYear": 2020,
    }


class _Lease:
    """最小化的 compute-lease 替身, 让 get_emby_actor_list 能跑完。"""

    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return MagicMock(async_client=self._client)

    async def __aexit__(self, *exc):
        return False


def _patch_persons(monkeypatch: pytest.MonkeyPatch, persons: list[dict]) -> None:
    """把 get_emby_actor_list 用到的取数层换成内存数据。"""

    async def _fake_list(filter_actor_only: bool = True):
        if filter_actor_only:
            # 模拟服务端 personTypes=Actor: 只回 Type 非导演/编剧的记录
            return [p for p in persons if p.get("Role") not in {"Director", "Writer", "Producer"}]
        return list(persons)

    monkeypatch.setattr(eam, "get_emby_actor_list", _fake_list)
    monkeypatch.setattr(eam, "manager", MagicMock())
    monkeypatch.setattr(eam.manager, "config", MagicMock(server_type="emby", api_key="k"))


async def _patch_stats(
    monkeypatch: pytest.MonkeyPatch,
    counts: dict | None = None,
    titles: dict | None = None,
) -> set:
    """替换出演统计, 返回被当作交集集合的 key 集合。"""
    person_names = set(counts or {})
    if not person_names:
        for p in getattr(_patch_stats, "_last_persons", []):
            person_names.add(eam._actor_dedup_key(p["Name"]))

    async def _fake_stats(parent_ids=None, filter_actor_only=True, page_limit=500):
        return dict(counts or {}), dict(titles or {}), set(person_names)

    monkeypatch.setattr(eam, "fetch_person_item_stats", _fake_stats)
    return person_names


async def _run(monkeypatch, persons, *, counts=None, dedup=True, filter_actor_only=False):
    _patch_stats._last_persons = persons
    _patch_persons(monkeypatch, persons)
    await _patch_stats(monkeypatch, counts)
    return await eam.fetch_all_actors(
        filter_actor_only=filter_actor_only,
        deduplicate=dedup,
    )


# --------------------------------------------------------------------------- #
# 1. 去重键: 只统一写法差异, 绝不误合并不同的人
# --------------------------------------------------------------------------- #


class TestDedupKey:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("小松（17）", "小松(17)"),  # 全角/半角括号(真机)
            ("［Jo］Style", "[Jo]Style"),  # 全角/半角方括号(真机)
            ("ﾘﾅ･ﾃﾞｨｿﾝ", "リナ・ディソン"),  # 半角/全角片假名(真机)
            ("ＨＤ", "HD"),  # 全角/半角字母(模块既有文档场景)
            ("波多野 結衣", "波多野 結衣"),  # 含空格的名字要稳定
            ("Chris", "chris"),  # 大小写
        ],
    )
    def test_写法差异归一到同一键(self, a: str, b: str):
        assert eam._actor_dedup_key(a) == eam._actor_dedup_key(b)

    @pytest.mark.parametrize(
        "a,b",
        [
            ("May A", "Maya"),  # 真机误合并样本: 去空格会变成同一个键
            ("Buddha D", "BuddhaD"),
            ("Ariel A", "Ariela"),
            ("张磊甲", "张磊乙"),
        ],
    )
    def test_不同的人绝不能归一到同一键(self, a: str, b: str):
        """去重键删除空白会误合并真人, 这是本模块最危险的回归点。"""
        assert eam._actor_dedup_key(a) != eam._actor_dedup_key(b)

    def test_保留名字内部空白(self):
        """`_normalize_actor_name` 会删光空白, 不能拿来做去重键。"""
        assert eam._actor_dedup_key("  Ada   Lovelace  ") == "ada lovelace"
        assert eam._actor_dedup_key("Ada Lovelace") != eam._actor_dedup_key("AdaLovelace")

    def test_空名与None安全(self):
        assert eam._actor_dedup_key("") == ""
        assert eam._actor_dedup_key(None) == ""
        assert eam._actor_dedup_key("   ") == ""

    def test_不与GFriends模糊键混用(self):
        """既有 `_normalize_actor_name` 必须保持原语义(删光空白), 两者不可混用。"""
        assert eam._normalize_actor_name("May A") == eam._normalize_actor_name("Maya")


# --------------------------------------------------------------------------- #
# 2. _person_merge_rank: 资料越全越该保留
# --------------------------------------------------------------------------- #


class TestMergeRank:
    def test_有头像排最前(self):
        with_img = _person("A", image=True, overview="x", backdrop=True)
        without = _person("B", image=False, overview="x", backdrop=True)
        assert eam._person_merge_rank(with_img) > eam._person_merge_rank(without)

    def test_无图时比简介(self):
        a = _person("A", image=True, overview="", backdrop=True, provider_ids={"T": "1"})
        b = _person("B", image=True, overview="有简介", backdrop=True, provider_ids={"T": "1"})
        assert eam._person_merge_rank(b) > eam._person_merge_rank(a)

    def test_空白简介不算有简介(self):
        a = _person("A", image=True, overview="   ", backdrop=True, provider_ids={"T": "1"})
        b = _person("B", image=True, overview="   ", backdrop=True, provider_ids={"T": "1"})
        assert eam._person_merge_rank(a) == eam._person_merge_rank(b)

    def test_同等资料比ProviderIds数量(self):
        a = _person("A", image=True, overview="x", backdrop=True, provider_ids={"T": "1"})
        b = _person("B", image=True, overview="x", backdrop=True, provider_ids={"T": "1", "X": "2"})
        assert eam._person_merge_rank(b) > eam._person_merge_rank(a)

    def test_完全相同则相等(
        self,
    ):
        a = _person("A", image=True, overview="x", backdrop=True, provider_ids={"T": "1"})
        b = _person("B", image=True, overview="x", backdrop=True, provider_ids={"T": "1"})
        assert eam._person_merge_rank(a) == eam._person_merge_rank(b)

    def test_缺字段的脏记录不崩(self):
        assert eam._person_merge_rank({}) == (0, 0, 0, 0)
        assert eam._person_merge_rank({"ImageTags": None, "ProviderIds": None}) == (0, 0, 0, 0)


# --------------------------------------------------------------------------- #
# 3. 去重择优: 不能再丢掉带头像的那条(真机 Sunshine)
# --------------------------------------------------------------------------- #


class TestDedupPicksRichest:
    @pytest.mark.asyncio
    async def test_sunshine场景保留带头像的记录(self, monkeypatch):
        """真机: Sunshine 三条 Id 217087/219491/219809, 第一条无头像第三条有。

        先到先得会把 ta 判成「全缺」, 择优后应为「缺简介」。
        """
        persons = [
            _person("Sunshine", "217087", image=False),
            _person("Sunshine", "219491", image=False),
            _person("Sunshine", "219809", image=True),
        ]
        actors, _raw = await _run(monkeypatch, persons)

        assert len(actors) == 1
        assert actors[0].actor_id == "219809"
        assert actors[0].has_image is True

    @pytest.mark.asyncio
    async def test_后出现的更优记录会替换但保持原位置(self, monkeypatch):
        persons = [
            _person("A", "1", image=False),
            _person("B", "2", image=True),
            _person("A", "3", image=True),
        ]
        actors, _raw = await _run(monkeypatch, persons)

        assert [a.name for a in actors] == ["A", "B"]  # 顺序不被替换打乱
        assert actors[0].actor_id == "3"
        assert actors[0].has_image is True

    @pytest.mark.asyncio
    async def test_后来的更差记录不会降级已有结果(self, monkeypatch):
        persons = [
            _person("A", "1", image=True, overview="有简介"),
            _person("A", "2", image=False),
        ]
        actors, _raw = await _run(monkeypatch, persons)

        assert len(actors) == 1
        assert actors[0].actor_id == "1"
        assert actors[0].has_image is True


# --------------------------------------------------------------------------- #
# 4. 计数与 raw 语义: 重复 = 被丢弃条目数
# --------------------------------------------------------------------------- #


class TestDuplicateCount:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "names,expected_rows,expected_raw",
        [
            (["小松（17）", "小松(17)"], 1, 2),
            (["[Jo]Style", "［Jo］Style"], 1, 2),
            (["リナ・ディソン", "ﾘﾅ･ﾃﾞｨｿﾝ"], 1, 2),
            (["May A", "Maya"], 2, 2),  # 不同的人, 不能合
            (["A", "A", "A"], 1, 3),
        ],
    )
    async def test_去重后行数与raw(self, monkeypatch, names, expected_rows, expected_raw):
        persons = [_person(n, str(i)) for i, n in enumerate(names)]
        actors, raw = await _run(monkeypatch, persons)
        assert len(actors) == expected_rows
        assert raw == expected_raw

    @pytest.mark.asyncio
    async def test_关闭去重时保留全部条目(self, monkeypatch):
        persons = [_person("小松（17）", "1"), _person("小松(17)", "2")]
        actors, raw = await _run(monkeypatch, persons, dedup=False)
        assert len(actors) == 2
        assert raw == 2

    @pytest.mark.asyncio
    async def test_重复数等于被去重丢弃的条目数(self, monkeypatch):
        """统计栏「重复」= raw − 唯一名字数, 必须等于实际丢弃数。"""
        persons = [_person(f"A{i}", str(i)) for i in range(5)]
        persons += [_person("B0", "90"), _person("Ｂ0", "91"), _person("b0", "92")]
        actors, raw = await _run(monkeypatch, persons)

        unique = {a.name for a in actors}
        assert raw - len({eam._actor_dedup_key(a.name) for a in actors}) >= 2
        # 三个 B 写法异体合并成 1 行, 丢弃 2 条
        assert sum(1 for a in actors if eam._actor_dedup_key(a.name) == "b0") == 1
        assert raw == 8
        assert len(actors) == 6
        assert unique  # 集合非空


# --------------------------------------------------------------------------- #
# 5. 统计映射同口径: 换了去重键不能把关联影片弄丢
# --------------------------------------------------------------------------- #


class TestStatsKeyAlignment:
    @pytest.mark.asyncio
    async def test_异体拼写能取到同一部影片的关联计数(self, monkeypatch):
        persons = [_person("小松（17）", "1"), _person("小松(17)", "2")]
        counts = {"小松(17)": 7}
        titles = {"小松(17)": ["[电影] xxx"]}

        _patch_stats._last_persons = persons
        _patch_persons(monkeypatch, persons)
        await _patch_stats(monkeypatch, counts, titles)
        actors, _raw = await eam.fetch_all_actors(filter_actor_only=False, deduplicate=True)

        assert len(actors) == 1
        assert actors[0].movie_count == 7
        assert actors[0].movie_titles == ["[电影] xxx"]

    @pytest.mark.asyncio
    async def test_取不到计数时为0而非报错(self, monkeypatch):
        persons = [_person("Zed", "1")]
        _patch_stats._last_persons = persons
        _patch_persons(monkeypatch, persons)
        await _patch_stats(monkeypatch, {}, {})
        actors, _raw = await eam.fetch_all_actors(filter_actor_only=False, deduplicate=True)
        assert actors[0].movie_count == 0
        assert actors[0].movie_titles == []


# --------------------------------------------------------------------------- #
# 6. 交集过滤也用归一化键(否则异体拼写的人会被误判为"不在库中")
# --------------------------------------------------------------------------- #


class TestIntersectionUsesNormalizedKey:
    @pytest.mark.asyncio
    async def test_异体拼写的人不会被交集过滤误删(self, monkeypatch):
        """影片 People 里写作 `小松(17)`, 但 /Persons 里是 `小松（17）`。

        两者归一到同一键, 因此不会被当成"不在所选库出演"而丢弃。
        """
        persons = [_person("小松（17）", "1")]
        _patch_stats._last_persons = persons
        _patch_persons(monkeypatch, persons)
        await _patch_stats(monkeypatch, {"小松(17)": 3})
        actors, raw = await eam.fetch_all_actors(filter_actor_only=True, deduplicate=True)

        assert len(actors) == 1
        assert raw == 1
        assert actors[0].name == "小松（17）"  # 保留服务端原名展示


# --------------------------------------------------------------------------- #
# 7. 日志用服务端原名, 不给用户看归一化后的小写键
# --------------------------------------------------------------------------- #


class TestLogUsesDisplayName:
    @pytest.mark.asyncio
    async def test_重复明细打印原名而非归一化键(self, monkeypatch):
        from mdcx.signals import signal

        seen: list[str] = []
        monkeypatch.setattr(signal, "show_log_text", lambda t: seen.append(t))

        persons = [_person("ChiChi", "1"), _person("ＣＨＩＣＨＩ", "2"), _person("ＣhichI", "3")]
        await _run(monkeypatch, persons)

        dup_logs = [t for t in seen if "重复明细" in t]
        assert dup_logs, f"没有输出重复明细日志: {seen}"
        text = dup_logs[0]
        assert "重复条目=2" in text
        # 日志里出现的是服务端原名, 不是 'chichi'
        assert "chichi" not in text

    @pytest.mark.asyncio
    async def test_跳过日志打印原名(self, monkeypatch):
        from mdcx.signals import signal

        seen: list[str] = []
        monkeypatch.setattr(signal, "show_log_text", lambda t: seen.append(t))

        # 交集集合为空 -> 不触发跳过; 构造一个"库里没有"的人
        persons = [_person("游离人员", "1")]
        _patch_stats._last_persons = persons
        _patch_persons(monkeypatch, persons)
        await _patch_stats(monkeypatch, {"某人": 1})
        await eam.fetch_all_actors(filter_actor_only=True, deduplicate=True)

        skip_logs = [t for t in seen if "跳过" in t]
        assert skip_logs
        assert "游离人员" in skip_logs[0]


# --------------------------------------------------------------------------- #
# 8. 统计扫描: 同一个条目里同一人异体拼写只计一次
# --------------------------------------------------------------------------- #


class TestStatsScanDedup:
    @pytest.mark.asyncio
    async def test_同一条目内异体拼写只记一次(self, monkeypatch):
        item = {
            "Id": "item1",
            "Name": "某电影",
            "Type": "Movie",
            "People": [
                {"Name": "小松（17）", "Type": "Actor"},
                {"Name": "小松(17)", "Type": "Actor"},
            ],
        }
        pages = [
            {"Items": [item], "TotalRecordCount": 1, "StartIndex": 0},
        ]

        async def _fake_request(method, path, **kw):
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value=pages.pop(0))
            resp.aread = AsyncMock(return_value=b"{}")
            return resp, ""

        monkeypatch.setattr(eam, "_emby_request", _fake_request)
        monkeypatch.setattr(eam, "_is_stop_requested", lambda: False)

        counts, titles, names = await eam.fetch_person_item_stats(filter_actor_only=True)
        assert counts == {"小松(17)": 1}
        assert list(names) == ["小松(17)"]
        assert len(titles["小松(17)"]) == 1
