from pathlib import Path

p = Path("mdcx/views/MDCx.ui")
lines = p.read_text(encoding="utf-8").splitlines(keepends=True)


def chk(n, frag):
    assert frag in lines[n - 1], (n, lines[n - 1])


targets = [
    (5284, '<item row="3" column="0">'),
    (5799, '<item row="3" column="1">'),
    (5888, '<item row="4" column="1">'),
    (5930, '<item row="4" column="0">'),
    (5672, '<item row="5" column="1">'),
    (5780, '<item row="5" column="0">'),
    (5331, '<item row="6" column="1">'),
    (5761, '<item row="6" column="0">'),
    (5303, '<item row="7" column="0">'),
    (5445, '<item row="7" column="1">'),
    (5283, "</item>"),
    (5256, '<item row="2" column="0">'),
]
for n, frag in targets:
    chk(n, frag)
print("assert ok")
