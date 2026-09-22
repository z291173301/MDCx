"""AVdb 演员映射表解析与清洗工具。

数据源: https://github.com/li-peifeng/Jav-Actors-Mapping 的 actor-mapping.xml。
纯标准库实现, 无 IO/网络依赖, 符合 Windows 单 exe 打包约束。
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

_FULL_DATE_PATTERNS = (
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
    re.compile(r"(\d{4})[/.](\d{1,2})[/.](\d{1,2})"),
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
)
_YEAR_MONTH_PATTERNS = (
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月"),
    re.compile(r"(\d{4})[/.](\d{1,2})(?!\d)"),
)
_YEAR_PATTERNS = (re.compile(r"(?:出生于|出生于)?\s*(\d{4})\s*年"),)

# 出生语义锚定：只在这些上下文里识别出生日期，避免把「XX年出道」「作品发行日」误当生日。
_BIRTH_SEMANTIC_RE = re.compile(r"出生|誕生|誕生日|生年月日|生\s*日|birth|Birth", re.IGNORECASE)
_BIRTH_FULL_DATE_PATTERNS = (
    # 日期紧跟「出生/誕生」字样，或「出生」紧跟日期
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(?:出生|誕生)"),
    re.compile(r"(?:出生|誕生)[于於]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"),
    re.compile(r"生年月日[：:\s]*(\d{4})\s*[年./\-]\s*(\d{1,2})\s*[月./\-]\s*(\d{1,2})\s*日?"),
    re.compile(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})\s*(?:出生|誕生)"),
)
_BIRTH_YEAR_MONTH_PATTERNS = (
    re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(?:出生|誕生)"),
    re.compile(r"(?:出生|誕生)[于於]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月"),
)
_BIRTH_YEAR_PATTERNS = (
    re.compile(r"(\d{4})\s*年\s*(?:出生|誕生)"),
    re.compile(r"(?:出生|誕生)[于於]?\s*(\d{4})\s*年"),
)

_BIRTH_SECTION_RE = re.compile(r"\d{4}\s*[年./\-]\s*\d{1,2}\s*[月./\-]?\s*\d{0,2}\s*日?\s*出生")
_AGE_RE = re.compile(r"\d{1,3}\s*岁")
_ESCAPED_STRING_RE = re.compile(r"\\(?:u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|[nrtfv])")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1F\x7F]")


@dataclass
class AvdbActor:
    """AVdb 映射表单条演员记录。bio_graphy 保留原始文本, birth_date/bio 为解析产物。"""

    zh_cn: str = ""
    zh_tw: str = ""
    jp: str = ""
    keyword: str = ""
    tmdb_id: str = ""
    bio_graphy: str = ""
    birth_date: str = ""
    bio: str = ""


def _get_actor_node(root: ET.Element) -> ET.Element:
    if root.tag == "actor":
        return root
    if root.tag != "actor-mapping":
        raise ValueError(f"Root element must be <actor> or <actor-mapping>, got <{root.tag}>.")
    actor_nodes = [child for child in list(root) if child.tag == "actor"]
    if len(actor_nodes) != 1:
        raise ValueError(f"<actor-mapping> must contain exactly one <actor> child, got {len(actor_nodes)}.")
    return actor_nodes[0]


def extract_birth_date(bio_graphy: str) -> str:
    """从 bio_graphy 提取出生日期, 归一化为 YYYY-MM-DD / YYYY-MM / YYYY, 无则返回空串。

    宁缺毋滥：只在文本中出现出生语义（出生/誕生/生年月日/生日）时才提取，
    避免把「XX年出道」「出道作品发行日」等非出生日期误填为生日。
    """
    text = bio_graphy or ""
    if not _BIRTH_SEMANTIC_RE.search(text):
        return ""

    # 1) 出生语义锚定的完整日期
    for pattern in _BIRTH_FULL_DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year}-{month:02d}-{day:02d}"

    # 2) 出生语义锚定的年+月
    for pattern in _BIRTH_YEAR_MONTH_PATTERNS:
        match = pattern.search(text)
        if match:
            year, month = match.group(1), int(match.group(2))
            if 1 <= month <= 12:
                return f"{year}-{month:02d}"

    # 3) 出生语义锚定的年份
    for pattern in _BIRTH_YEAR_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)

    return ""


def strip_age_and_birth(bio_graphy: str, birth_date: str = "") -> str:
    """剔除 bio_graphy 中的动态年龄片段与出生日期段, 保留静态资料文本。"""
    text = bio_graphy or ""
    if not text:
        return ""
    text = _BIRTH_SECTION_RE.sub("", text)
    text = _AGE_RE.sub("", text)
    text = text.strip(" ，,。.;；:：()（）")
    return text


def clean_actor_value(value: str) -> str:
    """写入前统一转义清洗: 解码重复实体转义, 移除控制字符/换行, 剥离字面反斜杠转义串。"""
    text = str(value or "")
    for _ in range(4):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    text = text.replace("\r", "").replace("\n", "").replace("\t", "")
    text = _CONTROL_CHARS_RE.sub("", text)
    text = _ESCAPED_STRING_RE.sub("", text)
    return text.strip()


def parse_avdb_actor_mapping(xml_text: str) -> list[AvdbActor]:
    """解析 AVdb actor-mapping.xml, 忽略 <actor-blacklist>, 缺失字段一律空值化。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML: {exc}") from exc

    actor_node = _get_actor_node(root)
    actors: list[AvdbActor] = []
    for child in actor_node:
        if child.tag != "a":
            continue
        attributes = child.attrib
        bio_graphy = attributes.get("bio_graphy", "")
        actor = AvdbActor(
            zh_cn=attributes.get("zh_cn", ""),
            zh_tw=attributes.get("zh_tw", ""),
            jp=attributes.get("jp", ""),
            keyword=attributes.get("keyword", ""),
            tmdb_id=attributes.get("tmdb_id", ""),
            bio_graphy=bio_graphy,
            birth_date=extract_birth_date(bio_graphy),
            bio=strip_age_and_birth(bio_graphy),
        )
        actors.append(actor)
    return actors
