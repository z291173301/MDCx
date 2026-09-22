"""失败原因聚合统计测试：文本归一 / Top N 摘要 / 调优建议。"""

from mdcx.core.fail_reason_stats import (
    classify_fail_reason,
    format_failed_summary,
    summarize_failed_list,
)


def test_classify_covers_common_failure_texts():
    """常见真实失败文案归一到可读类别"""
    assert classify_fail_reason("javdb 请求超时") == "请求超时"
    assert classify_fail_reason("connect timed out") == "请求超时"
    assert classify_fail_reason("WinError 5 拒绝访问") == "权限不足"
    assert classify_fail_reason("Thumb download failed! javdb") == "图片下载失败"
    assert classify_fail_reason("获取番号失败") == "番号未识别"
    assert classify_fail_reason("所有刮削来源均未返回可用数据") == "站点未收录"
    assert classify_fail_reason("Cloudflare 挑战页") == "被拦截"
    assert classify_fail_reason("HTTP 403") == "被拦截"
    assert classify_fail_reason("详情响应解析失败") == "解析失败"
    assert classify_fail_reason("创建文件夹失败！目标盘可能限制文件夹名的长度或字符！") == "目录名无效或过长"
    assert classify_fail_reason("创建文件夹失败！可能是目录名过长！") == "目录名无效或过长"
    assert classify_fail_reason("完全没见过的错误形态") == "其他错误"
    assert classify_fail_reason("") == "其他错误"


def test_summarize_orders_by_count_desc():
    """按数量降序、同数量按名称稳定排序；top_n 截断"""
    failed = [
        ("a.mp4", "请求超时"),
        ("b.mp4", "请求超时"),
        ("c.mp4", "站点未收录"),
        ("d.mp4", "站点未收录"),
        ("e.mp4", "站点未收录"),
        ("f.mp4", "番号未识别"),
    ]
    lines = summarize_failed_list(failed)
    assert lines[0] == "站点未收录 3 个"
    assert lines[1] == "请求超时 2 个"
    assert lines[2] == "番号未识别 1 个"
    # top_n 截断
    assert len(summarize_failed_list(failed, top_n=1)) == 1


def test_format_summary_contains_hint():
    """完整摘要含 Top N 行与对应调优建议"""
    failed = [
        ("a.mp4", "请求超时"),
        ("b.mp4", "请求超时"),
        ("c.mp4", "站点未收录"),
    ]
    text = format_failed_summary(failed)
    assert "失败原因汇总" in text
    assert "请求超时 2 个" in text
    assert "超时" in text.splitlines()[1]  # 建议行针对头部类别
    # 无失败返回空串
    assert format_failed_summary([]) == ""


def test_hint_matches_each_head_category():
    """各头部类别对应到具体建议文案，未命中类别回退通用建议"""
    assert "代理" in format_failed_summary([("a", "请求超时")]).splitlines()[1]
    assert "免 CF" in format_failed_summary([("a", "Cloudflare 拦截")]).splitlines()[1]
    assert "线程" in format_failed_summary([("a", "HTTP 429")]).splitlines()[1]
    assert "网站" in format_failed_summary([("a", "站点未收录")]).splitlines()[1]
    assert "番号" in format_failed_summary([("a", "获取番号失败")]).splitlines()[1]
    assert "目录名最大长度" in format_failed_summary([("a", "目标盘可能限制文件夹名的长度或字符")]).splitlines()[1]
    assert "重试" in format_failed_summary([("a", "完全未知的错误")]).splitlines()[1]
