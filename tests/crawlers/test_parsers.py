import pytest

from mdcx.crawlers import dmm, javdb
from tests.crawlers.parser import ParserTestBase


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name, parser_class",
    [
        ("dmm/mono", dmm.MonoParser),
        ("dmm/digital", dmm.DigitalParser),
        ("dmm/rental", dmm.RentalParser),
        ("javdb", javdb.Parser),
    ],
)
async def test_parsers(name, parser_class, overwrite, parser_names):
    if parser_names and name not in parser_names:
        pytest.skip(f"跳过解析器: {name}")
    t = ParserTestBase(name, parser_class, overwrite)
    success = await t.run_all_tests()
    assert success, "所有测试应该通过"
