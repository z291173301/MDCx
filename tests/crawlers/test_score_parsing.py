"""评分抓取回归测试.

背景: JavDB 系详情页是多行 pretty-printed HTML, ``score-stars`` 父容器的首个
直接文本子节点只是换行空白——旧写法 ``extract_text(.../../text())`` 取首节点
拿到空串, 有评分也抓不到. JavLibrary 同理, ``span.score`` 文本节点常带换行
缩进, 旧写法 ``.strip("()")`` 去不掉空白导致 ``float()`` 失败漏抓.
"""

from lxml import etree
from parsel import Selector

from mdcx.crawlers.base.parser import extract_javdb_score
from mdcx.crawlers.javlibrary import get_score


def test_javdb_score_multiline_zh():
    html = Selector(text='<span class="value">\n  <span class="score-stars"></span>\n  4.25分, 由356人评价\n</span>')
    assert extract_javdb_score(html) == "4.25"


def test_javdb_score_english_locale():
    html = Selector(text='<span class="value"><span class="score-stars"></span> 4.25 points, by 356 users</span>')
    assert extract_javdb_score(html) == "4.25"


def test_javdb_score_integer():
    html = Selector(text='<span class="value"><span class="score-stars"></span>4分</span>')
    assert extract_javdb_score(html) == "4"


def test_javdb_score_comma_voters_without_suffix():
    html = Selector(text='<span class="value"><span class="score-stars"></span> 8.5, 120人</span>')
    assert extract_javdb_score(html) == "8.5"


def test_javdb_score_unrated_is_empty():
    html = Selector(text='<span class="value"><span class="score-stars"></span>暫無評分</span>')
    assert extract_javdb_score(html) == ""


def test_javdb_score_missing_container_is_empty():
    # 无评分容器时不得误抓页内其他数字(如时长 120分钟)
    html = Selector(text="<div>no score here, 120分钟</div>")
    assert extract_javdb_score(html) == ""


def _lxml_tree(inner: str):
    return etree.fromstring(f"<div>{inner}</div>", etree.HTMLParser())


def test_javlibrary_score_multiline():
    tree = _lxml_tree(
        '<div id="video_review">\n  <table><tr><td><span class="score">\n  (8.13)\n</span></td></tr></table>\n</div>'
    )
    assert get_score(tree) == "8.13"


def test_javlibrary_score_plain():
    tree = _lxml_tree('<div id="video_review"><span class="score">(4.20)</span></div>')
    assert get_score(tree) == "4.20"


def test_javlibrary_score_missing_is_empty():
    tree = _lxml_tree('<div id="video_review"></div>')
    assert get_score(tree) == ""
