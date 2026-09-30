"""Python 3.14 依赖下限守卫（配合 `.github/workflows/build-py314.yml`）。

背景：3.14 流水线靠 `python-version: 3.14` + `uv sync --locked` 验证兼容性，
其中三处依赖下限是被 3.14 核对抬上来的，回退会让该流水线硬失败：

- `pyinstaller`：`6.14.2` 的元数据是 `requires-python = ">=3.8,<3.14"`，3.14 上装不上；
- `av`：`15.0.0` 只有 cp39~cp313 的 wheel，3.14 上会退回源码编译（需 FFmpeg 开发库）；
- `aiofiles`：`25.1.0` 起上游才测试并支持 3.14（`24.1.0` 早于 3.14）。

同时校验 `pyproject.toml` 与 `uv.lock` 的依赖声明不脱节：`uv sync --locked` 在
CI 里强校验 lock 是否与 manifest 一致，改依赖后忘了 `uv lock` 会直接 exit 1。
其余依赖（`pyqt6` cp310-abi3、`opencv-contrib-python-headless` cp37-abi3、
`curl-cffi` cp310-abi3、`oshash`/`zhconv` 纯 Python 等）无需设下限，见
`docs/Development.md`「构建」段。
"""

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).parent.parent

# 包名 -> 必须保持的版本声明（回退即视为 3.14 不兼容）
_REQUIRED_SPECIFIERS = {
    "aiofiles": "==25.1.0",
    "av": ">=15.1.0",
    "pyinstaller": ">=6.16.0,<7",
}

# 已锁定的解析版本下限（uv.lock 实际 pin 的版本也必须够新）
_REQUIRED_LOCKED = {
    "av": (15, 1),
    "pyinstaller": (6, 16),
}


def _pyproject() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _declared_specifiers() -> dict[str, str]:
    """把 pyproject.toml 里的 dependencies + dev 组解析成 {包名: 版本声明}。"""
    project = _pyproject()["project"]
    declared: dict[str, str] = {}
    for raw in list(project["dependencies"]) + list(_pyproject()["dependency-groups"]["dev"]):
        match = re.match(r"([A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*(\S+)$", raw.strip())
        assert match is not None, f"无法解析依赖声明：{raw}"
        declared[match.group(1).lower().replace("_", "-")] = match.group(2)
    return declared


def _lock_root_metadata() -> str:
    """取 uv.lock 里根包（mdcx）的 [package.metadata...] 整段，含 requires-dist 与 requires-dev。"""
    content = (_ROOT / "uv.lock").read_text(encoding="utf-8")
    for block in content.split("\n[[package]]\n"):
        if "\n[package.metadata]\n" in block:
            return block
    return ""


def test_314_critical_specifiers_present():
    """三个包的版本声明不得被回退到不支持 3.14 的老版本。"""
    declared = _declared_specifiers()

    for name, expected in _REQUIRED_SPECIFIERS.items():
        assert name in declared, f"pyproject.toml 缺少依赖 {name}"
        assert declared[name] == expected, (
            f"{name} 的版本声明是 {declared[name]}，3.14 需要 {expected}；"
            "回退会让 build-py314.yml 的 `uv sync --locked` 失败，理由见 tests/test_py314_dependency_floors.py 文档"
        )


def test_uv_lock_metadata_matches_pyproject():
    """uv.lock 根包的 [package.metadata] 必须与 pyproject.toml 同步。

    CI 用 `uv sync --locked` 强校验，两者脱节时该步直接 exit 1（全平台）。
    """
    metadata = _lock_root_metadata()
    assert metadata, "uv.lock 中找不到根包的 [package.metadata] 段"

    for name, expected in _REQUIRED_SPECIFIERS.items():
        assert re.search(
            rf'(?m)^\s*\{{ name = "{re.escape(name)}", specifier = "{re.escape(expected)}" \}},$',
            metadata,
        ), (
            f"uv.lock 的 metadata 里没有 {name} = {expected}；"
            "请执行 `uv lock` 重新生成 lock，否则 CI 的 `uv sync --locked` 会失败"
        )


def test_locked_versions_admit_python_314():
    """uv.lock 实际 pin 的版本也必须够新（av 要有 cp314 wheel，pyinstaller 要允许 3.14）。"""
    content = (_ROOT / "uv.lock").read_text(encoding="utf-8")

    for name, floor in _REQUIRED_LOCKED.items():
        match = re.search(rf'(?m)^\[\[package\]\]\nname = "{re.escape(name)}"\nversion = "([^"]+)"', content)
        assert match is not None, f"uv.lock 中找不到包 {name}"
        version = tuple(int(part) for part in match.group(1).split(".")[:2])
        assert version >= floor, (
            f"uv.lock 里 {name} 锁的是 {match.group(1)}，低于 3.14 需要的 {'.'.join(str(p) for p in floor)}；"
            "请执行 `uv lock --upgrade-package " + name + "`"
        )


def test_requires_python_has_no_upper_bound():
    """`requires-python` 不能带 upper bound，否则 3.14 直接不是合法解释器。"""
    requires_python = _pyproject()["project"]["requires-python"]

    assert "<" not in requires_python, (
        f'requires-python = "{requires_python}" 带 upper bound，会把 Python 3.14 排除在外，'
        "build-py314.yml 与 pyproject 前提冲突"
    )
