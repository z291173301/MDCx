"""赞助账单解析：把微信/支付宝**官方导出**的个人对账单 CSV 转成榜单记录。

为什么必须走账单导出
--------------------
个人收款码（微信「收款码」/ 支付宝个人码）**没有任何官方 API 能把付款人昵称返回给收款方**。
微信开放社区 000ae4c2958e1010c13ebe62a51400 的官方答复原话是「不支持获取，如果需要用户填写
信息，建议做成下单支付模式」。所以榜单里的昵称只能从账单反推。好在两家 App 都提供官方账单
导出，而导出文件里有「交易对方」列：

* 对方用**转账**付款 → 「交易对方」就是付款人的真实昵称 ✓
* 对方**扫个人收款码**付款 → 「交易对方」通常是空的（微信侧甚至填 ``/``） ✗

第二种是赞助场景的常态，所以赞助说明里必须写一句「请在备注里写下你的昵称」。本模块的昵称
取值链就是 ``交易对方 → 备注 → 匿名``。

导出入口（均为官方、免费、无需商户资质）
----------------------------------------
* 微信：我 → 服务 → 客服中心 → 下载账单 →「用于个人对账」（3 个月/次）或「用做证明材料」
  （1 年/次）→ 填邮箱 → 收到压缩包，**解压密码由「微信支付」公众号的服务通知下发**。
  微信电脑版「设置 → 通用设置 → 账单与交易 → 导出账单」可直存本地，免邮箱免密码。
* 支付宝：我的 → 账单 → 右上角 ··· → 开具交易流水证明 → 用于个人对账 → 填邮箱。
  **解压码在支付宝消息里**（不是支付密码）。

两种格式的差异
--------------
==========  ======  ==========================  =====================  ==========  ==========
平台        编码    收入列                       对方昵称列              去重键       金额列
==========  ======  ==========================  =====================  ==========  ==========
微信支付    GBK     ``收/支 == 收入``            ``交易对方``            交易单号      金额(元)
支付宝      GBK     ``收/支出 == 收入``          ``交易对方``            交易订单号    金额
==========  ======  ==========================  =====================  ==========  ==========

**表头行号刻意不写死。** 网上流传的 ``skiprows=16``（微信）/ ``skiprows=24``（支付宝）只对
某一版导出的说明段行数成立，而微信改过好几次说明段。本模块扫前 ``_HEADER_SCAN_ROWS`` 行，
取第一行同时能解析出「时间列」与「金额列」的当表头，格式再变也解得出。

编码同理不写死 ``gbk``：支付宝某些版本导出的是 UTF-8，先试 UTF-8 再退 GB18030
（GB18030 是 GBK 的超集，能多认一些生僻字）。

榜单口径（对齐参考图 ``resources/Img/@赞助.png``）
------------------------------------------------
* **新人榜Top10**：按付款时间倒序取前 10（参考图左列 8-28 14:04 → 8-27 19:44 正是时间倒序）
* **土豪榜Top10**：按金额倒序取前 10（参考图右列 200.00 → 101.00 正是金额倒序），
  金额相同时按时间倒序（同额新记录在前）
* **昵称脱敏**：参考图里显示的是 ``G*T`` / ``*活`` 这种打码，不是原样昵称。公开他人真实
  昵称/微信号有隐私风险，本模块默认脱敏后展示；``mask_name`` 的规则见其 docstring。
"""

import csv
import json
import os
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path

# 榜单条目数（榜单框固定 10 行，见 mdcx/views/donate_window.py 的 _RANK_ROWS）
TOP_N = 10

# 「交易对方」为这些值时视为「没给出昵称」，继续回落到备注
_BLANK_NAMES = frozenset({"", "/", "-", "--", "无", "未知", "对方", "微信支付", "支付宝", "null", "None"})

# 昵称完全取不到时的占位
ANONYMOUS = "匿名"

# 扫前这么多行找表头（微信说明段约 16 行、支付宝约 24 行，留足余量）
_HEADER_SCAN_ROWS = 80

# 列名候选（**精确匹配**，按顺序取第一个命中的；长的写前面避免前缀歧义）
_COL_TIME = ("交易时间", "交易创建时间", "付款时间", "交易日期")
_COL_AMOUNT = ("金额(元)", "金额（元）", "金额", "交易金额")
_COL_NAME = ("交易对方", "对方名称", "交易方名称")
_COL_REMARK = ("备注", "留言", "附言")
_COL_ORDER = ("交易单号", "交易订单号", "订单号", "交易号")
_COL_DIRECTION = ("收/支出", "收/支")

# 微信独有列 / 支付宝独有列，用于判定来源（仅用于展示，不影响解析）
_WECHAT_ONLY = ("交易单号", "商户单号", "当前状态", "支付方式")
_ALIPAY_ONLY = ("交易分类", "商家订单号", "交易状态", "收/付款方式")

# 时间列格式。微信导出是 "2025-08-28 14:04:33"，支付宝是 "2025-08-28 14:04:33"，
# 少数字段带毫秒/用斜杠，故多给几个候选而不是只认一种。
_TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d",
)

_AMOUNT_JUNK = re.compile(r"[¥￥,\s元]")


@dataclass(frozen=True)
class DonateRecord:
    """一笔赞助记录。

    ``order_id`` 是去重键：同一条流水在多次导出（重叠时间区间）里会重复出现，
    按它去重才能让「新增数」和榜单都稳定。
    """

    name: str  # 昵称取值链解析后的结果（未脱敏，脱敏只在渲染时做）
    paid_at: datetime
    amount: Decimal
    order_id: str
    source: str  # "微信" / "支付宝"

    def to_row(self, *, mask: bool = True) -> dict[str, str]:
        """渲染成榜单一行（用户名 / 日期时间 / 金额），字段与参考图三列一一对应。"""
        return {
            "name": mask_name(self.name) if mask else self.name,
            "time": format_time(self.paid_at),
            "amount": format_amount(self.amount),
        }

    def to_dict(self) -> dict[str, str]:
        """持久化形态。金额存字符串：JSON 没有 Decimal，float 会引入二进制误差
        （0.1+0.2 那种），而榜单是按金额排序的，误差会让「土豪榜」偶尔错位。"""
        return {
            "name": self.name,
            "time": self.paid_at.strftime("%Y-%m-%d %H:%M:%S"),
            "amount": f"{self.amount:.2f}",
            "order_id": self.order_id,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DonateRecord:
        return cls(
            name=str(data.get("name") or ""),
            paid_at=parse_time(str(data.get("time") or "")),
            amount=parse_amount(data.get("amount")) or Decimal("0"),
            order_id=str(data.get("order_id") or ""),
            source=str(data.get("source") or ""),
        )


@dataclass(frozen=True)
class ImportReport:
    """一次导入的结果，供 UI 提示文案用。"""

    added: int  # 新增（此前库里没有的订单）
    skipped: int  # 因订单号重复而跳过的
    parsed: int  # 从文件里解析出的有效收入笔数（含重复）
    files: int  # 成功解析的文件数
    failed: tuple[str, ...]  # 解析失败的文件名（不中断其余文件）


# ------------------------------------------------------------------ 格式化


def mask_name(name: str) -> str:
    """昵称脱敏，规则照抄参考图：``G*T``（3 字）、``*活``（2 字）。

    统一表述是「**永远保留末字**；首字只在中间还塞得下一个 ``*`` 时才保留」：

    * 1 字 → ``*``
    * 2 字 → ``*`` + 末字（参考图的 ``*活``）
    * ≥3 字 → 首字 + ``*`` × (长度-2) + 末字（参考图的 ``G*T``）
    """
    name = (name or "").strip()
    n = len(name)
    if n <= 1:
        return "*" * max(n, 1)
    if n == 2:
        return "*" + name[1]
    return name[0] + "*" * (n - 2) + name[-1]


def format_time(value: datetime) -> str:
    """日期列格式 ``8-28 14:04``：月/日不补零，时分补零（照抄参考图）。"""
    return f"{value.month}-{value.day} {value.hour:02d}:{value.minute:02d}"


def format_amount(value: Decimal) -> str:
    """金额列格式 ``¥10.00``：两位小数、千分位不加（参考图 ``¥188.88`` 无逗号）。"""
    return f"¥{value:.2f}"


# ------------------------------------------------------------------ 字段解析


def parse_time(text: str) -> datetime:
    """解析账单里的时间列，失败回落到 Unix 纪元（排序时沉底，不打断整表解析）。"""
    raw = (text or "").strip()
    if not raw:
        return datetime(1970, 1, 1)
    # 支付宝部分行带 ".000" 毫秒尾巴
    if "." in raw:
        raw = raw.split(".", 1)[0].strip()
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return datetime(1970, 1, 1)


def parse_amount(text: object) -> Decimal | None:
    """解析金额列：剥掉 ``¥``/``￥``/千分位逗号/单位「元」/空白后转 Decimal。

    用 Decimal 而非 float：榜单要按金额排序，还要输出两位小数的字符串，float 的
    0.1+0.2 类误差会让 ``¥188.88`` 变 ``¥188.87999…``。
    """
    if isinstance(text, Decimal):
        return text
    cleaned = _AMOUNT_JUNK.sub("", str(text or ""))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def resolve_name(counterparty: str, remark: str) -> str:
    """昵称取值链：``交易对方`` → ``备注`` → :data:`ANONYMOUS`。

    扫个人码付款时「交易对方」是空的，所以绝大多数情况下真正起作用的是备注——
    这也是赞助说明里一定要写「请在备注里写下你的昵称」的原因。
    """
    for candidate in (counterparty, remark):
        cleaned = (candidate or "").strip()
        if cleaned and cleaned not in _BLANK_NAMES:
            return cleaned
    return ANONYMOUS


# ------------------------------------------------------------------ 账单解析


def read_bill_text(path: str | Path) -> str:
    """按字节读账单再试编码：UTF-8(带 BOM) → GB18030 → 兜底 replace。

    GB18030 是 GBK 的超集，用它兜底比 GBK 多认一批生僻字（转账人昵称里常出现）。
    """
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", errors="replace")


def _find_header(rows: list[list[str]]) -> tuple[int, list[str]] | None:
    """在前若干行里找表头：能同时解析出时间列与金额列的那一行。"""
    for index, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        if not row:
            continue
        if _pick_column(row, _COL_TIME) is None or _pick_column(row, _COL_AMOUNT) is None:
            continue
        # 表头名通常不带 ¥ / 数字，金额列是纯名字（值在数据行）
        return index, [cell.strip() for cell in row]
    return None


def _pick_column(header: list[str], candidates: Iterable[str]) -> int | None:
    """按候选名**精确**匹配列下标（候选顺序即优先级）。

    必须精确匹配而非子串：支付宝的 ``收/支出`` 以 ``收/支`` 开头，子串匹配会让
    收/支 列错位到另一列上，收入笔数直接归零。
    """
    for name in candidates:
        for index, cell in enumerate(header):
            if cell.strip() == name:
                return index
    return None


def detect_source(header: list[str]) -> str:
    """按平台独有列判定来源，只用于展示，不影响解析（解析是列名驱动的）。"""
    names = {cell.strip() for cell in header}
    if names & set(_ALIPAY_ONLY):
        return "支付宝"
    if names & set(_WECHAT_ONLY):
        return "微信"
    return "未知"


def parse_bill(path: str | Path) -> list[DonateRecord]:
    """解析一个账单文件，自动适配微信/支付宝两种表头，返回**收入**记录。"""
    return parse_bill_text(read_bill_text(path))


def parse_bill_text(text: str) -> list[DonateRecord]:
    """从账单文本解析收入记录（纯函数，便于单测直接喂样本）。"""
    rows = list(csv.reader(StringIO(text)))
    found = _find_header(rows)
    if found is None:
        raise ValueError("找不到表头行（需同时含「交易时间」与「金额」两列）")
    header_index, header = found

    col_time = _pick_column(header, _COL_TIME)
    col_amount = _pick_column(header, _COL_AMOUNT)
    assert col_time is not None and col_amount is not None  # _find_header 已保证
    col_name = _pick_column(header, _COL_NAME)
    col_remark = _pick_column(header, _COL_REMARK)
    col_order = _pick_column(header, _COL_ORDER)
    col_direction = _pick_column(header, _COL_DIRECTION)
    source = detect_source(header)

    def cell(row: list[str], index: int | None) -> str:
        if index is None or index >= len(row):
            return ""
        return row[index]

    records: list[DonateRecord] = []
    for row in rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            continue
        # 尾部「合计」「电子回单」等页脚行时间列解析不出真日期，直接跳过
        paid_at = parse_time(cell(row, col_time))
        if paid_at == datetime(1970, 1, 1):
            continue
        # 收支方向：缺列时不过滤（假定导出就是筛选过的对账单），有列时只收「收入」
        direction = cell(row, col_direction).strip()
        if col_direction is not None and direction and "收入" not in direction:
            continue
        amount = parse_amount(cell(row, col_amount))
        if amount is None or amount <= 0:
            continue
        records.append(
            DonateRecord(
                name=resolve_name(cell(row, col_name), cell(row, col_remark)),
                paid_at=paid_at,
                amount=amount,
                order_id=cell(row, col_order).strip(),
                source=source,
            )
        )
    return records


# ------------------------------------------------------------------ 合并 / 榜单


def dedupe(records: Iterable[DonateRecord]) -> list[DonateRecord]:
    """按订单号去重，同号保留**首次**出现的那条。

    没订单号的记录（个别导出缺该列）不参与去重——否则它们会互相吞掉，只剩一条。
    """
    seen: set[str] = set()
    result: list[DonateRecord] = []
    for record in records:
        if record.order_id:
            if record.order_id in seen:
                continue
            seen.add(record.order_id)
        result.append(record)
    return result


def sort_records(records: Iterable[DonateRecord]) -> list[DonateRecord]:
    """默认排序：付款时间倒序（新的在前）。"""
    return sorted(records, key=lambda record: record.paid_at, reverse=True)


def build_ranks(records: Iterable[DonateRecord], *, mask: bool = True, top: int = TOP_N) -> dict[str, list[dict]]:
    """生成两个榜单，各至多 ``top`` 行，字段与参考图三列一一对应。

    ``新人榜`` 按时间倒序（参考图左列）；``土豪榜`` 按金额倒序、同额按时间倒序
    （参考图右列）。行内容由 :meth:`DonateRecord.to_row` 产出。
    """
    unique = dedupe(records)
    newbie = sort_records(unique)[:top]
    rich = sorted(unique, key=lambda record: (record.amount, record.paid_at), reverse=True)[:top]
    return {
        "newbie": [record.to_row(mask=mask) for record in newbie],
        "rich": [record.to_row(mask=mask) for record in rich],
    }


# ------------------------------------------------------------------ 持久化

# 记录文件的 schema 版本；结构不兼容变更时 +1 并在读取处显式拒绝旧版
RECORDS_VERSION = 1
_RECORDS_FILENAME = "donate_records.json"


def records_path() -> Path:
    """记录文件路径：``<配置文件目录>/userdata/donate_records.json``。

    刻意放在 userdata 下——``.gitignore`` 第 184 行已忽略整个 ``/userdata/``，
    里面全是真实付款人昵称，绝不能进版本库。

    resources 延迟到调用时才 import：本模块其余部分是纯逻辑（scripts/ 下的命令行
    入口也要用它），不该因为取个路径就把 Qt 与整套配置单例拖进来。
    """
    from ..config.resources import resources

    return resources.u(_RECORDS_FILENAME)


def load_records(path: str | Path | None = None) -> list[DonateRecord]:
    """读记录文件；文件不存在/损坏返回空列表（赞助窗口只是少几行数据，不该崩）。"""
    target = Path(path) if path is not None else records_path()
    try:
        payload = json.loads(target.read_text(encoding="UTF-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("version") != RECORDS_VERSION:
        return []
    raw_records = payload.get("records")
    if not isinstance(raw_records, list):
        return []
    return [DonateRecord.from_dict(item) for item in raw_records if isinstance(item, dict)]


def save_records(records: Iterable[DonateRecord], path: str | Path | None = None) -> Path:
    """原子写记录文件，返回落盘路径。

    这里自己写 tmp + ``os.replace`` 而不调 :func:`mdcx.utils.file.write_file_atomic`：
    那个函数会 import ``mdcx.signals``（PyQt6 QObject 单例），而本模块要被
    ``scripts/import_donate_bills.py`` 当纯逻辑用，命令行入口不该拖 Qt 进来。
    """
    target = Path(path) if path is not None else records_path()
    ordered = sort_records(dedupe(records))
    payload = {
        "version": RECORDS_VERSION,
        "records": [record.to_dict() for record in ordered],
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="UTF-8") as handle:
            handle.write(content)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target


def import_bills(paths: Iterable[str | Path], target: str | Path | None = None) -> ImportReport:
    """导入若干账单文件并合并入库，返回 :class:`ImportReport`。

    语义刻意是「**累加**」而不是「覆盖」：每次导出通常只覆盖最近 1~3 个月，
    而榜单要留住历史，所以按订单号与库里的旧记录合并。单个文件解析失败不影响
    其余文件（失败名进 ``failed``）。
    """
    existing = load_records(target)
    merged = list(existing)
    known = {record.order_id for record in existing if record.order_id}
    added = skipped = parsed = files = 0
    failed: list[str] = []

    for path in paths:
        candidate = Path(path)
        try:
            found = parse_bill(candidate)
        except (OSError, ValueError):
            failed.append(candidate.name)
            continue
        files += 1
        parsed += len(found)
        for record in found:
            if record.order_id and record.order_id in known:
                skipped += 1
                continue
            if record.order_id:
                known.add(record.order_id)
            merged.append(record)
            added += 1

    save_records(merged, target)
    return ImportReport(
        added=added,
        skipped=skipped,
        parsed=parsed,
        files=files,
        failed=tuple(failed),
    )