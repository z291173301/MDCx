import re
import tomllib
from pathlib import Path

from mdcx.consts import VERSION_NAME


def test_package_version_matches_display_version():
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    package_version = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]["version"]
    display_version = VERSION_NAME.removeprefix("v")

    assert re.fullmatch(r"\d+\.\d+\.\d+", display_version)
    assert package_version == display_version
