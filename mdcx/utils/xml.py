REP_WORD = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&apos;": "'",
    "&quot;": '"',
    "&lsquo;": "\u300c",
    "&rsquo;": "\u300d",
    "&hellip;": "\u2026",
    "<br/>": "",
    "\u30fb": "\u00b7",
    "\u201c": "\u300c",
    "\u201d": "\u300d",
    "...": "\u2026",
    "\xa0": "",
    "\u3000": "",
    "\u2800": "",
}

ESCAPE_WORD = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&apos;",
    '"': "&quot;",
}

XML_TEXT_FIELDS = [
    "title",
    "originaltitle",
    "number",
    "outline",
    "originalplot",
    "series",
    "studio",
    "publisher",
]


def normalize_xml_text(raw: str) -> str:
    for key, value in REP_WORD.items():
        raw = raw.replace(key, value)
    return raw


# 实体反转义：写入前先把已存在的实体还原，再统一转义，避免用户手写的 &amp; 被双重转义成 &amp;amp;
_REVERSE_ESCAPE = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&apos;": "'", "&quot;": '"'}


def escape_xml_text(raw: str) -> str:
    # 写入路径只做实体幂等化 + XML 转义，不做 normalize_xml_text：后者会把全角空格(\\u3000)、
    # 不换行空格(\\xa0) 等合法字符删掉、把 &amp;lt; 二次反转义，破坏数据保真（写入/读取不对称）。
    for key, value in _REVERSE_ESCAPE.items():
        raw = raw.replace(key, value)
    for key, value in ESCAPE_WORD.items():
        raw = raw.replace(key, value)
    return raw


def build_cdata(raw: str) -> str:
    # 同 escape_xml_text：不做字符清洗，只转义 CDATA 结束符
    return "<![CDATA[" + raw.replace("]]>", "]]]]><![CDATA[>") + "]]>"
