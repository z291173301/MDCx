"""议题 #143 回归: 演员管理器计数方式持久化。

旧实现下拉框从不写配置、也不恢复, 每次重开管理器/重启都回到「原始条目数」。
现约定: 启动时按 Config.actor_count_mode 恢复下拉索引; 用户切换后持久化到配置
(写盘失败仅告警不打断刷新; 构造期 setCurrentIndex 不得先于 connect, 避免初始化误写盘)。
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace
from unittest.mock import MagicMock


def _fake_self():
    stats_calls: list[list] = []
    logs: list[str] = []
    return SimpleNamespace(
        _show_unique=False,
        _actors=[],
        _update_statistics=lambda actors: stats_calls.append(""),
        _stats_calls=stats_calls,
        log=lambda msg: logs.append(msg),
        _logs=logs,
    )


def test_count_mode_changed_persists(monkeypatch):
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    cfg = SimpleNamespace(actor_count_mode=0)
    mgr = MagicMock()
    mgr.config.model_copy.return_value = cfg
    monkeypatch.setattr("mdcx.tools.emby_actor_manager_ui.manager", mgr)

    fake = _fake_self()
    EmbyActorManagerDialog._on_count_mode_changed(fake, 1)

    assert fake._show_unique is True, "应更新内存态"
    assert len(fake._stats_calls) == 1
    assert cfg.actor_count_mode == 1, "配置字段应被写入"
    assert mgr._replace_config.call_count == 1
    assert mgr.save.call_count == 1


def test_count_mode_changed_persist_failure_does_not_break_refresh(monkeypatch):
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    mgr = MagicMock()
    mgr.save.side_effect = OSError("disk full")
    monkeypatch.setattr("mdcx.tools.emby_actor_manager_ui.manager", mgr)

    fake = _fake_self()
    _on_count_mode_changed_safe(EmbyActorManagerDialog, fake, 1)

    assert fake._show_unique is True
    assert len(fake._stats_calls) == 1, "统计刷新不得受影响"
    assert len(fake._logs) == 1 and "保存失败" in fake._logs[0]


def _on_count_mode_changed_safe(dialog_cls, fake_self, index):
    """调用真实方法, save 异常已由实现内部 catch; 外层再兜一层防语义退化吞掉断言。"""
    dialog_cls._on_count_mode_changed(fake_self, index)


def test_count_mode_changed_maps_non_one_index_to_zero(monkeypatch):
    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    cfg = SimpleNamespace(actor_count_mode=1)
    mgr = MagicMock()
    mgr.config.model_copy.return_value = cfg
    monkeypatch.setattr("mdcx.tools.emby_actor_manager_ui.manager", mgr)

    EmbyActorManagerDialog._on_count_mode_changed(_fake_self(), 0)
    assert cfg.actor_count_mode == 0, "非 1 索引必须写回 0 而非原样透传"


def test_init_restores_show_unique_from_config():
    """结构哨兵: _show_unique 初始化必须读取持久化字段(而非写死 False)。"""
    import inspect

    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    src = inspect.getsource(EmbyActorManagerDialog.__init__)
    assert "actor_count_mode" in src, "__init__ 必须从配置恢复 _show_unique"


def test_combo_restores_index_before_connect():
    """结构哨兵: 下拉框 setCurrentIndex 必须在 currentIndexChanged.connect 之前, 否则初始化误写盘。"""
    import inspect

    from mdcx.tools.emby_actor_manager_ui import EmbyActorManagerDialog

    src = inspect.getsource(EmbyActorManagerDialog)
    set_idx = src.find("self.cmb_count_mode.setCurrentIndex")
    connect = src.find("self.cmb_count_mode.currentIndexChanged.connect")
    assert set_idx != -1 and connect != -1
    assert set_idx < connect, "setCurrentIndex 必须先于 connect"
