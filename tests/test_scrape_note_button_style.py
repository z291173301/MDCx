"""「刮削不到？看这里！」按钮（pushButton_scrape_note）样式回归测试。

用户需求：「当鼠标放在刮削不到？看这里！按钮上是不要出现蓝色背景」。

背景：该按钮原本与 `pushButton_field_tips_nfo` 共用同一条 QSS 规则
（`mdcx/controllers/main_window/style.py` 的三套主题各一组 base/hover/pressed），
hover 底色是品牌蓝（浅色主题 `#4C6EFF`、两套深色主题 `#6684FF`），与「网站偏好」
组内其它控件的克制配色不搭。修复方式是把该按钮从共用选择器里拆出来单列，
hover/pressed 只做中性灰的明暗变化，不再出现蓝底。

同时清掉了 `pushButton_field_tips_website`——该 objectName 在 .ui 里根本不存在
（全仓库仅出现在 style.py 的这三组选择器中），属于死选择器，删除对视觉零影响；
`pushButton_field_tips_nfo` 是真实控件（NFO 页「字段说明」按钮，有运行期定位
逻辑 `_sync_nfo_field_tips` 及 tests/test_window_state_matrix.py 的几何回归），
其蓝色 hover 保持不变，本文件同时锁定这一点防止误改。

本测试纯离线：正则解析 style.py 源文件，不启动 Qt。
"""

import re
from pathlib import Path

STYLE_PATH = Path(__file__).resolve().parent.parent / "mdcx" / "controllers" / "main_window" / "style.py"

# 曾经用于这两个按钮 hover 的品牌蓝（浅色主题 / 深色主题两组）。
_BLUE_HOVER = frozenset({"#4C6EFF", "#6684FF"})
_BLUE_PRESSED = frozenset({"#3F5FE6", "#4C6EE0"})
# 判定「蓝色」用的宽松判据：#RRGGBB 里蓝通道显著高于红通道即视为品牌蓝。
_BLUE_MIN_DELTA = 40

_SOURCE = STYLE_PATH.read_text(encoding="utf-8")

# style.py 的 QSS 模板分两种写法：经 .format() 的用 {{ }} 转义（两套深色主题），
# 未 format 的用单花括号（浅色主题）。先把 {{ }} 归一成单花括号，下面的规则解析
# 就只需处理一种形态，不会漏掉被转义的那两套主题。
_SOURCE_QSS = _SOURCE.replace("{{", "{").replace("}}", "}")

# 抽出所有以 QPushButton 开头的「选择器 + 规则体」。选择器与声明体都不含花括号，
# 因此 [^{}] 足以覆盖（含跨多行书写的选择器）。
_RULE_RE = re.compile(r"([^{}]*?QPushButton[^{}]*?)\{([^{}]*)\}")


def _state_of(selector: str) -> str:
    if ":hover" in selector:
        return "hover"
    if ":pressed" in selector:
        return "pressed"
    return "base"


def _rules_for(object_name: str) -> list[tuple[str, str, str]]:
    """返回 (选择器原文, 状态, 规则体) 三元组列表，状态为 base/hover/pressed。

    一条选择器可以点名多个 objectName（`A,B{...}`），此时对每个被点名的
    objectName 都返回一次，这样「是否与别人共用」能被直接看出。
    """
    found = []
    for selector, body in _RULE_RE.findall(_SOURCE_QSS):
        if object_name not in re.findall(r"#([A-Za-z_0-9]+)", selector):
            continue
        found.append((selector, _state_of(selector), body))
    return found


def _background(body: str) -> str | None:
    m = re.search(r"background(?:-color)?:\s*([^;]+);", body)
    return m.group(1).strip() if m else None


def _is_brand_blue(color: str | None) -> bool:
    """启发式判定：#RRGGBB 且蓝通道比红通道高 >=40 视为品牌蓝。"""
    if not color or not color.startswith("#") or len(color) != 7:
        return False
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return b - r >= _BLUE_MIN_DELTA


def test_scrape_note_has_hover_and_pressed_rules():
    """按钮必须在全部三套主题里都有 base/hover/pressed 三条独立规则。

    三套主题 = style.py 里三处出现（浅色主题 + 两套深色主题）。少一条就意味着
    某个主题下 hover 会掉回 Qt 平台默认样式，重新出现不该有的高亮。
    """
    rules = _rules_for("pushButton_scrape_note")
    states = [state for _sel, state, _body in rules]
    assert len(rules) == 9, f"应有 3 主题 × 3 状态 = 9 条规则，实际 {len(rules)} 条：{states}"
    for state in ("base", "hover", "pressed"):
        assert states.count(state) == 3, f"{state} 状态应有 3 条（每主题一条），实际 {states.count(state)}"


def test_scrape_note_is_not_sharing_selectors_with_other_buttons():
    """按钮不得再与其它按钮共用选择器。

    共用即意味着 hover 底色被绑死——这正是本次蓝色问题的根因，所以把它锁死。
    """
    for selector, state, _body in _rules_for("pushButton_scrape_note"):
        ids = re.findall(r"#([A-Za-z_0-9]+)", selector)
        assert ids == ["pushButton_scrape_note"], f"{state} 规则的选择器不应共用：{selector.strip()}"

    # 死选择器清理：field_tips_website 在 .ui 里不存在，style.py 里也不该再出现。
    assert "pushButton_field_tips_website" not in _SOURCE, (
        "pushButton_field_tips_website 不是真实控件（.ui 中无此 objectName），style.py 里的死选择器应已清理"
    )


def test_scrape_note_hover_and_pressed_have_no_blue_background():
    """hover / pressed 底色都不得是品牌蓝。"""
    for _selector, state, body in _rules_for("pushButton_scrape_note"):
        if state == "base":
            continue
        bg = _background(body)
        assert not _is_brand_blue(bg), f"{state} 底色不应为蓝色：{bg}"
        if state == "hover":
            assert bg not in _BLUE_HOVER, f"hover 底色仍是旧品牌蓝：{bg}"
        else:
            assert bg not in _BLUE_PRESSED, f"pressed 底色仍是旧品牌蓝：{bg}"


def test_field_tips_nfo_keeps_blue_hover():
    """NFO 页「字段说明」按钮是真实控件，其蓝色 hover 必须保留。

    防误伤：拆分共用选择器时容易顺手把这个也一起改掉。
    """
    rules = _rules_for("pushButton_field_tips_nfo")
    assert rules, "pushButton_field_tips_nfo 的 QSS 规则不应消失"
    hovers = [body for _sel, state, body in rules if state == "hover"]
    assert hovers, "pushButton_field_tips_nfo 应保留 hover 规则"
    assert any(_background(b) in _BLUE_HOVER for b in hovers), (
        f"pushButton_field_tips_nfo 的 hover 底色应保持 {sorted(_BLUE_HOVER)} 之一"
    )
