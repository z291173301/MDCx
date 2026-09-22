from lxml import etree

from mdcx.crawlers import fc2, javlibrary, mgstage


def test_fc2_tags_keep_quotes_and_brackets():
    html = etree.HTML('<a class="tag tagTag">[限定]</a><a class="tag tagTag">O\'Brien</a>')

    assert fc2.getTag(html) == "[限定],O'Brien"


def test_mgstage_fields_join_multiple_values_without_list_syntax():
    html = etree.HTML(
        """
        <div id="center_column"><div><h1>[Title] O'Brien</h1></div></div>
        <table>
          <tr><th>出演</th><td><a>[Actor]</a><a>O'Brien</a></td></tr>
          <tr><th>メーカー：</th><td><a>[Studio]</a></td></tr>
          <tr><th>ジャンル：</th><td><a>[Tag]</a><a>O'Brien</a></td></tr>
        </table>
        <a id="EnlargeImage" href="https://example.test/[cover].jpg" />
        """
    )

    assert mgstage.getTitle(html) == "[Title] O'Brien"
    assert mgstage.getActor(html) == "[Actor],O'Brien"
    assert mgstage.getStudio(html) == "[Studio]"
    assert mgstage.getTag(html) == "[Tag],O'Brien"
    assert mgstage.getCover(html) == "https://example.test/[cover].jpg"


def test_javlibrary_preserves_special_actor_tag_and_release_text():
    html = etree.HTML(
        '<div id="video_cast"><span class="star"><a>[Actor]</a><a>O\'Brien</a></span></div>'
        '<div id="video_genres"><td class="text"><span><a>[Tag]</a><a>O\'Brien</a></span></td></div>'
        '<div id="video_date"><td class="text">[2026-04-03]</td></div>'
    )

    assert javlibrary.get_actor(html) == "[Actor],O'Brien"
    assert javlibrary.get_tag(html) == "[Tag],O'Brien"
    assert javlibrary.get_release(html) == "[2026-04-03]"
