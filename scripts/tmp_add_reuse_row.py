from pathlib import Path

p = Path("mdcx/views/MDCx.ui")
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)

renums = [
    (5284, 'row="3" column="0"', 'row="4" column="0"'),
    (5799, 'row="3" column="1"', 'row="4" column="1"'),
    (5888, 'row="4" column="1"', 'row="5" column="1"'),
    (5930, 'row="4" column="0"', 'row="5" column="0"'),
    (5672, 'row="5" column="1"', 'row="6" column="1"'),
    (5780, 'row="5" column="0"', 'row="6" column="0"'),
    (5331, 'row="6" column="1"', 'row="7" column="1"'),
    (5761, 'row="6" column="0"', 'row="7" column="0"'),
    (5303, 'row="7" column="0"', 'row="8" column="0"'),
    (5445, 'row="7" column="1"', 'row="8" column="1"'),
]
for n, old, new in renums:
    assert old in lines[n - 1], (n, lines[n - 1])
    lines[n - 1] = lines[n - 1].replace(old, new)

# col0 空 spacer：完整复用 label_strm_spacer 块(5256-5283，仅改名)
c0 = lines[5255:5283]
assert any("label_strm_spacer" in ln for ln in c0)
c0 = [ln.replace("label_strm_spacer", "label_reuse_meta_spacer") for ln in c0]
c0[0] = c0[0].replace('row="2"', 'row="3"')

I24, I26, I28, I30, I32, I34, I36 = (" " * n for n in (24, 26, 28, 30, 32, 34, 36))
new_c1 = [
    f'{I24}<item row="3" column="1">\n',
    f'{I26}<layout class="QHBoxLayout" name="horizontalLayout_reuse_meta">\n',
    f'{I28}<item>\n',
    f'{I30}<widget class="QCheckBox" name="checkBox_separate_reuse_meta">\n',
    f'{I32}<property name="sizePolicy">\n',
    f'{I34}<sizepolicy hsizetype="Fixed" vsizetype="Fixed">\n',
    f'{I36}<horstretch>0</horstretch>\n',
    f'{I36}<verstretch>0</verstretch>\n',
    f'{I34}</sizepolicy>\n',
    f'{I32}</property>\n',
    f'{I32}<property name="minimumSize">\n',
    f'{I34}<size>\n',
    f'{I36}<width>0</width>\n',
    f'{I36}<height>0</height>\n',
    f'{I34}</size>\n',
    f'{I32}</property>\n',
    f'{I32}<property name="text">\n',
    f'{I34}<string>复用数据存放目录中的元数据文件</string>\n',
    f'{I32}</property>\n',
    f'{I30}</widget>\n',
    f'{I28}</item>\n',
    f'{I28}<item>\n',
    f'{I30}<spacer name="horizontalSpacer_reuse_meta">\n',
    f'{I32}<property name="orientation">\n',
    f'{I34}<enum>Qt::Horizontal</enum>\n',
    f'{I32}</property>\n',
    f'{I32}<property name="sizeHint" stdset="0">\n',
    f'{I34}<size>\n',
    f'{I36}<width>20</width>\n',
    f'{I36}<height>20</height>\n',
    f'{I34}</size>\n',
    f'{I32}</property>\n',
    f'{I30}</spacer>\n',
    f'{I28}</item>\n',
    f'{I26}</layout>\n',
    f'{I24}</item>\n',
]

# 插到原5284行之前(0-based索引5283)
lines[5283:5283] = new_c1 + c0
p.write_text("".join(lines), encoding="utf-8")
print("ui edit ok, total lines:", len(lines))
