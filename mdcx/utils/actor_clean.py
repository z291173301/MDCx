"""演员数据语义清洗。

在数据写入 actor_database.xlsx 前（AVdb 同步 / 刮削补充）调用，剔除
名字/别名字段中的语义噪声：系列标签、年份、标注（国籍/事务所/类型）、
作品标题、占位符、悬空斜杠等。规则与 scripts/clean_actor_db_field_noise.py 保持一致。

设计原则:
- 幂等: 对已干净数据无副作用
- 保守: 只剥离明确噪声，保留罗马音/日文映射、读音、韩文别名等合法内容
- 仅对名字/别名字段生效，不影响 tmdbid/出生日期等结构化字段
"""

from __future__ import annotations

import re

PLACEHOLDER_TERMS = [
    "素人",
    "複数",
    "复素",
    "女優情報",
    "美人な人妻",
    "人妻",
    "熟女",
    "管理者様",
    "復元してください",
    "复元してください",
    "凛女",
    "アイドル店員",
    "ツインテール",
    "元Fカップ",
    "グラドル",
    "愛奴",
    "バド部",
    "ギャル２人組",
    "ギャル2人組",
    "編集",
    "编集",
    "奥さん",
    "元Fカップグラドル",
    "FC2",
    "生意気ツインテール18ちゃん",
    "生意気ツインテール",
]

_PLACEHOLDER_RE = re.compile("|".join(map(re.escape, PLACEHOLDER_TERMS)))

_AGE_RE = re.compile(r"\d+[歳才岁歲]")

# 系列/站点标签：括号内已知非人名，剥离
_SERIES_TAG_RE = re.compile(
    r"パコパコママ|エッチな0930|エッチな4610|天然むすめ|ラグジュTV|FC2|1000人斬り|人妻斬り|ロリ主婦|人妻DX|カリビアンコムプレミアム|マドンナ|グラドル|ソープ嬢|トリプルエックス|ニューハーフ|クリスタル|GirlsDelta|無垢|カリビアン|ガチん娘|ムラムラ|DMM素人動画|FC2ライブ|元Fカップ",
    re.IGNORECASE,
)

# 年份标签：括号内纯年份，剥离
_YEAR_TAG_RE = re.compile(r"【?\d{4}年?】?")

# 标注词黑名单：括号内容命中则剥离（国籍/事务所/类型/品牌/组合/本名/年份等）
_ANNOTATION_TERMS = re.compile(
    r"英国|ハンガリー|ベトナム|イングランド|俄罗斯混血|USA|JPN|泰国|美国|韩国"
    r"|JETSTREAM|T-POWERS|HEYZO|FALENO|LINX|Gcolle|KUKI|kira☆kira|RealShodo|GOT刊|Playboy|Fleur|きらきら"
    r"|着エロ|ヌードイメージ|女王様|嫁|同人モデル|仮|TS|登録|シンデレラオーディショングランプリ"
    r"|BAND-MAID|DIALOGUE＋|本名|2代目|第\d+期生|デビュー|ニューハーフ"
)

# 作品标题特征：别名段命中则剔除
_SERIES_TITLE_RE = re.compile(
    r"ラグジュTV|ママ友喰い|VOL\.?\s*\d+|人妻湯恋旅行|おばさんを酔わせて|相席居酒屋|ナマ交尾|デカクリトリス|イン〇タ|チ〇ポ|オナホ扱い|社交辞令SEX|タダマン|立ちんぼ|美魔女|閉経|生殖活動|メンエス|回春|四畳半|生ハメ|素人限定|素人初撮り|B級熟女|B級素人|芸能人り|元地方局アナ|エッチな0930|人妻斬り|刹那的背徳旅行|パコパコママ|ロリ主婦|天然むすめ|一本道|1000人斬り|千春",
    re.IGNORECASE,
)

# 别名段含「名字+年龄」标注
_AGE_SEG_RE = re.compile(r"\d+[歳才岁歲]")

# 别名段为长日文句子（作品标题特征，真实别名不会这么长）
_LONG_SEG_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]")

# 纯标签残留（别名里单独的 人妻/着エロ/素人 等）
_PURE_TAG_RE = re.compile(r"^(人妻|訳あり人妻|熟女|素人|着エロ|人妻DX|主婦|パート)$")

# 已知真别名（括号内容应保留）
_KNOWN_ALIAS_IN_PAREN = re.compile(r"[（(](はんな|結城あかり|瑞穂このみ|アニー麗)[)）]")


def _strip_series_year(name: str) -> str:
    """剥离名字中的系列标签和年份，如 本田仁美(パコパコママ) -> 本田仁美"""
    s = str(name)
    s = re.sub(
        r"[\(（]([^\(（）]*?)[\)）]",
        lambda m: "" if (_SERIES_TAG_RE.search(m.group(1)) or _YEAR_TAG_RE.fullmatch(m.group(1))) else m.group(0),
        s,
    )
    s = re.sub(r"[\(（\[]\d{4}年?[\)）\]]", "", s)
    s = re.sub(r"[【\[]\d{4}年?[】\]]", "", s)
    s = re.sub(r"\d{4}年?$", "", s)
    s = re.sub(r"FC2ライブ$", "", s)
    s = re.sub(r"元Fカップグラドル$", "", s)
    return s.strip()


def _strip_annotation(name: str) -> str:
    """剥离名字/别名中的标注括号（国籍/事务所/类型/品牌等），保留别名/读音括号。

    HIBIKI（女王様） -> HIBIKI；Tanaka Karen (田中可恋) 保留（读音/别名）
    """
    s = str(name).strip()
    s = s.replace("【", "[").replace("】", "]").replace("（", "(").replace("）", ")")

    def _should_strip(inner: str) -> bool:
        inner = inner.strip()
        if not inner:
            return True
        if _YEAR_TAG_RE.fullmatch(inner):
            return True
        if _SERIES_TAG_RE.search(inner):
            return True
        if _ANNOTATION_TERMS.search(inner):
            return True
        if re.search(r"[\u3040-\u30ff\uac00-\ud7af]", inner):
            return False
        return False

    s = re.sub(r"\[([^\[\]]*)\]", lambda m: "" if _should_strip(m.group(1)) else m.group(0), s)
    s = re.sub(r"\(([^()]*)\)", lambda m: "" if _should_strip(m.group(1)) else m.group(0), s)
    if s.count("[") != s.count("]") or s.count("(") != s.count(")"):
        s = re.sub(r"[\[\]\(\)]", "", s)
    s = s.replace("登録", "").replace("女王様", "")
    return s.strip()


def _is_placeholder_name(name: str) -> bool:
    """整个名字都是占位符/描述词才返回 True（如 素人/美人な人妻/抜群なアイドル店員）"""
    if not name:
        return False
    s = str(name).strip()
    for term in (
        "生意気ツインテール18ちゃん",
        "抜群なアイドル店員",
        "複数の素人娘",
        "复数の素人娘",
        "美人な人妻",
        "元Fカップグラドル",
        "モデルボディーの女",
        "地味な眼鏡の巨乳妻",
        "訳アリ巨乳JD",
        "定時制ギャル",
        "ギャルママ柔道家",
        "生意気ツインテール",
        "人妻湯恋旅行",
    ):
        if term in s:
            return True
    body = re.sub(r"[\(（][^\(（）]*?[\)）]", "", s).strip()
    if _AGE_RE.search(body):
        return True
    if len(body) <= 4 and _PLACEHOLDER_RE.search(body):
        return True
    if _PLACEHOLDER_RE.search(body) and len(re.sub(r"[\u3040-\u30ff\u4e00-\u9fff·・\s]", "", body)) <= 1:
        return True
    return False


def _is_noise_segment(seg: str) -> bool:
    if not seg:
        return False
    if len(seg) <= 5:
        return False
    if _AGE_SEG_RE.search(seg):
        return True
    if _SERIES_TITLE_RE.search(seg):
        return True
    if len(seg) > 20 and _LONG_SEG_RE.search(seg):
        return True
    return False


# 别名段 = '名字 + 作品/描述' 污染（空格分隔）
_DESC_TOKEN_RE = re.compile(
    r"店の女|契約|交尾|プロレスラー|の女|禁断|巨乳|耳かき|バニーコレクション|の妻|ナンパ|愛人|の義母|の生徒|の同僚|の幼馴染|の彼女|顔出し|ギャル|制服|メイド|看護師|店員|先生|会長|の娘|素人|熟女|人妻|ランジェリーナ|世田谷の妻|淫乱|レーベル|在宅ワーカー|家賃滞納|いいなり|温泉旅行|ワリキリ|ワリキリバイト|バイト|湘南の女|発禁|患者|万引き娘|夫から逃げる"
)

# 紧凑式描述污染（无空格）：前缀/后缀描述词 + 名字
_DESC_PREFIX_RE = re.compile(
    r"^(巨乳女子プロレスラー|巨尻女子プロレスラー|巨乳ヒール女子プロレスラー|女子プロレスラー|素人|S級素人|S級色白美肌の素人|淫乱変態ＪＤ|モデルボディーの女|地味な眼鏡の巨乳妻|ギャルママ柔道家|訳アリ巨乳JD|定時制ギャル|複数の素人|复数の素人|色白美巨乳Gカップ美女|美人な人妻|抜群なアイドル店員|ギャル２人組|ギャル2人組|素人美熟女ナンパ|素人庭園|しろハメ素人|俺の素人-Z-|E★人妻DX|泌尿器科女医|幼稚園先生|メイドカフェ店員|♀\d+メイドカフェ店員|巨乳アパレル店員|可愛すぎるス○バ店員|色白152cmあざと可愛いコスメ店員)"
)
_DESC_SUFFIX_RE = re.compile(
    r"(先生|女医|メイドカフェ店員|ス○バ店員|アパレル店員|コスメ店員|店員|幼稚園先生|美人妻|人妻看護婦|妻たち|人妻|プロレスラー)$|^(幼なじみの|アラフィフ|五十路|三十六歳|36歳)"
)
_DESC_PURE_RE = re.compile(
    r"^(定時制ギャル|訳アリ巨乳JD|モデルボディーの女|地味な眼鏡の巨乳妻|ギャルママ柔道家|美人な人妻|複数の素人娘|复数の素人娘|抜群なアイドル店員|ギャル２人組|ギャル2人組|四十路人妻|素人美熟女ナンパ|S級素人|S级素人|素人奥様|素人不明|素人多数|素人娘|素人娘达|素人娘達|素人品評会|素人妻|素人人物不明|素人１|素人1|素人患者|素人 患者|素人 万引き娘)$"
)


def _strip_desc_tokens(seg: str) -> str:
    """剥离段中命中的描述/作品 token，保留名字部分。如 門脇晶子 禁断中出し契約交尾 -> 門脇晶子"""
    parts = [p.strip() for p in seg.split(" ") if p.strip()]
    kept = [p for p in parts if not _DESC_TOKEN_RE.search(p)]
    if kept:
        return " ".join(kept)
    return ""


def _strip_compact_desc(seg: str) -> str:
    """剥离紧凑式描述污染：巨乳女子プロレスラー凛叶 -> 凛叶；ここな先生 -> ここな"""
    if not seg:
        return seg
    if _DESC_PURE_RE.match(seg):
        return ""
    s = seg
    m = _DESC_PREFIX_RE.match(s)
    if m:
        s = s[m.end() :].strip()
    m2 = _DESC_SUFFIX_RE.search(s)
    if m2:
        s = s[: m2.start()].strip()
    return s.strip()


def _fix_dangling_slash(seg: str) -> str:
    """修复别名段中的悬空斜杠或残括号：ただえりさ / -> ただえりさ；真東愛 / Mahigashi Ai） -> 真東愛 / Mahigashi Ai"""
    if not seg or ("/" not in seg and "／" not in seg):
        return seg
    s = seg
    for slash in ("/", "／"):
        if slash in s:
            lhs, _, rhs = s.partition(slash)
            rhs = rhs.strip()
            if not rhs or rhs in {")", "）", "]", "】"}:
                s = lhs.strip()
            else:
                s = f"{lhs.strip()} {slash} {re.sub(r'[）)】\]\s]*$', '', rhs).strip()}"
            break
    return s.strip()


def _clean_aliases(alias: str) -> str:
    """清洗整段别名（逗号分隔），返回清洗后的逗号串。"""
    parts = [p.strip() for p in str(alias).split(",")]
    clean = []
    for p in parts:
        if not p:
            continue
        if _PURE_TAG_RE.match(p):
            continue
        # 先剥离系列标签/标注（如 本田仁美(パコパコママ) -> 本田仁美）
        stripped = _strip_series_year(p)
        stripped = _strip_annotation(stripped)
        # 再判断剩余是否纯噪声
        if _is_noise_segment(stripped):
            continue
        stripped = _fix_dangling_slash(stripped)
        if " " in stripped and not re.search(r"[A-Za-z]", stripped):
            desc_stripped = _strip_desc_tokens(stripped)
            if desc_stripped and desc_stripped != stripped:
                stripped = desc_stripped
            elif not desc_stripped:
                continue
        if not re.search(r"[A-Za-z]", stripped):
            compact_stripped = _strip_compact_desc(stripped)
            if compact_stripped != stripped:
                if not compact_stripped:
                    continue
                stripped = compact_stripped
        clean.append(stripped)
    return ",".join(clean)


def clean_actor_name(name: str) -> str:
    """清洗单个演员名字字段（日文原名/中文名/繁体名）。返回 '' 表示纯占位符应置空。

    处理: 剥离系列标签/年份/标注/描述污染；整名是占位符时返回空串。
    """
    if not name:
        return ""
    s = str(name).strip()
    cleaned = _strip_series_year(s)
    cleaned = _strip_annotation(cleaned)
    cleaned = _strip_compact_desc(cleaned)
    if not cleaned:
        return ""
    if _is_placeholder_name(cleaned):
        return ""
    return cleaned.strip()


def clean_actor_keyword(keyword: str) -> str:
    """清洗别名字段（逗号分隔），返回清洗后的逗号串。"""
    if not keyword:
        return ""
    return _clean_aliases(str(keyword))
