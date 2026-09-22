"""失败原因聚合统计：刮削结束时把失败列表按可读类别归一，输出 Top N 摘要。

用户痛点：大批量刮削后失败列表几十上百条自由文本，逐条翻看才知道该调代理还是换网站源。
聚合后一眼看到主要矛盾（如"超时 23 / 番号未识别 15 / 图片下载失败 8"）。
"""

from __future__ import annotations

from collections import Counter

# 文本归一规则：按顺序匹配首个命中即归类（规则顺序影响输出稳定性，保持固定）
# 关键词取自真实失败文案：LogBuffer.error 聚合串 + file_crawler/scraper 的固定提示
_REASON_RULES: list[tuple[str, str]] = [
    ("超时", "请求超时"),
    ("timeout", "请求超时"),
    ("timed out", "请求超时"),
    ("WinError 5", "权限不足"),
    ("Permission", "权限不足"),
    ("目标盘可能限制文件夹名", "目录名无效或过长"),
    ("目录名过长", "目录名无效或过长"),
    ("权限", "权限不足"),
    ("图片下载失败", "图片下载失败"),
    ("Thumb download failed", "图片下载失败"),
    ("Poster download failed", "图片下载失败"),
    ("水印", "图片处理失败"),
    ("裁剪", "图片处理失败"),
    ("未识别", "番号未识别"),
    ("获取番号失败", "番号未识别"),
    ("not_found", "站点未收录"),
    ("未找到匹配", "站点未收录"),
    ("未返回可用数据", "站点未收录"),
    ("无可用数据", "站点未收录"),
    ("blocked", "被拦截"),
    ("Cloudflare", "被拦截"),
    ("403", "被拦截"),
    ("429", "请求过快被限流"),
    ("404", "站点未收录"),
    ("解析失败", "解析失败"),
    ("parse_error", "解析失败"),
]

_MAX_TOP_N = 8


def classify_fail_reason(reason: str) -> str:
    """把聚合失败文本归一到可读类别；未命中规则返回"其他错误"。

    防御：输入已是归一类别名（如二次聚合场景）时直接返回自身。
    """
    text = str(reason or "")
    lowered = text.lower()
    for keyword, label in _REASON_RULES:
        if keyword in text or keyword.lower() in lowered:
            return label
    if text in {label for _keyword, label in _REASON_RULES}:
        return text
    return "其他错误"


def summarize_failed_list(failed_list: list[tuple[str, str]], top_n: int = _MAX_TOP_N) -> list[str]:
    """按类别统计失败列表，返回可读摘要行（类别 N 个），数量降序、同数按名称稳定排序。"""
    counter = Counter(classify_fail_reason(reason) for _path, reason in failed_list)
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [f"{label} {count} 个" for label, count in ordered[:top_n]]


def format_failed_summary(failed_list: list[tuple[str, str]]) -> str:
    """生成失败原因摘要的完整日志块（无失败返回空串）。"""
    if not failed_list:
        return ""
    lines = summarize_failed_list(failed_list)
    summary = f" 📊 失败原因汇总（Top {len(lines)}）：{' ｜ '.join(lines)}"
    hint = _tuning_hint(lines)
    return summary + (f"\n 💡 {hint}" if hint else "")


def _tuning_hint(lines: list[str]) -> str:
    """根据头部类别给出一条可操作建议。"""
    if not lines:
        return ""
    head = lines[0]
    if "超时" in head:
        return "以超时为主：优先检查代理稳定性或到「设置→网络」调大超时/重试次数"
    if "拦截" in head:
        return "以被拦截为主：站点可能需要更新 Cookie 或改用免 CF 通道（javdb_api/javdb_app 等）"
    if "限流" in head:
        return "以限流为主：降低「线程数量」或增加「线程延时」后再刮"
    if "未收录" in head:
        return "以未收录为主：多数番号不在所选站点库中，可到「设置→刮削网站」调整来源顺序或补开综合站"
    if "番号未识别" in head:
        return "以番号未识别为主：文件命名不符合番号规范，可手动指定番号或整理命名"
    if "目录名" in head:
        return (
            "以目标盘目录名限制为主：网盘/映射盘（115/夸克等）对单个文件夹名更严，"
            "可调小「设置→命名→目录名最大长度」或先刮到本地盘再同步"
        )
    if "权限" in head:
        return "以权限不足为主：尝试以管理员身份运行并关闭占用文件的程序"
    if "图片下载失败" in head or "图片处理失败" in head:
        return "以图片处理失败为主：可稍后用「一键刮削失败列表」单独补图（已有数据不会重复刮）"
    return "可用「一键刮削失败列表」重试，网络波动类失败通常重刮即可恢复"
