"""Sentinel regression test: no QTextBrowser in MDCx.ui ships designer-empty
paragraph html (issue #121 blank space above logs).

Designer saves 12 empty 13pt paragraphs into a browser's html property when the
document had manual empty lines at save time. That html is baked into MDCx.py,
so the browser starts with ~300-400px of leading blanks; appended log entries
land below the blanks instead of at the top (screenshot in issue #121: first
log line "当前配置" sits ~60% down the page).

Real content (e.g. textBrowser_about usage manual) is allowed; only the
all-paragraphs-empty residue pattern is banned.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import re
import xml.etree.ElementTree as ET

MDCX_UI = "mdcx/views/MDCx.ui"

# 12 empty designer paragraphs: 10 bare empty <p>s + 2-3 whitespace spans.
_EMPTY_P = re.compile(r"<p[^>]*>\s*</p>")


def _collect_empty_para_browsers() -> dict[str, int]:
    root = ET.parse(MDCX_UI).getroot()
    hit: dict[str, int] = {}
    for w in root.iter("widget"):
        if w.get("class") != "QTextBrowser":
            continue
        html_el = w.find("property/[@name='html']/string")
        if html_el is None:
            continue
        text = html_el.text or ""
        n = len(_EMPTY_P.findall(text))
        if n >= 10:  # designer residue always comes as a 12-block batch
            hit[w.get("name") or "(unnamed)"] = n
    return hit


def test_no_designer_empty_paragraph_residue():
    hit = _collect_empty_para_browsers()
    assert not hit, (
        f"QTextBrowser(s) {hit} carry designer empty-paragraph html "
        "(issue #121: leading blanks push log content down the page). "
        "Remove the empty <p> blocks from the html property in MDCx.ui; "
        "keep real content."
    )
