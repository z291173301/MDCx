"""临时插件：把提示标签宽度还原为设计宽 211px，验证相关红测与本次改动无关（验证完删除）。

用法：pytest -p zz_probe_restore_hint tests/...
"""

from mdcx.controllers.main_window.main_window import MyMAinWindow


def pytest_configure(config):
    MyMAinWindow._actor_db_slice_hint_width = classmethod(
        lambda cls, hint: cls._ACTOR_DB_TOOL_DESIGN["label_actor_db_sync_slice_hint"][2]
    )
