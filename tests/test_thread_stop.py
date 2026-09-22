from types import SimpleNamespace

from mdcx import utils


def test_kill_a_thread_injects_once_without_wait(monkeypatch):
    injected: list[tuple[int | None, type]] = []
    thread = SimpleNamespace(ident=123, is_alive=lambda: True)

    def fake_async_raise(thread_id, exception_type):
        injected.append((thread_id, exception_type))

    monkeypatch.setattr(utils, "_async_raise", fake_async_raise)

    utils.kill_a_thread(thread, timeout=0.0)

    assert injected == [(123, SystemExit)]


def test_kill_a_thread_skips_finished_thread(monkeypatch):
    thread = SimpleNamespace(ident=123, is_alive=lambda: False)
    monkeypatch.setattr(utils, "_async_raise", lambda *args: (_ for _ in ()).throw(AssertionError("should not run")))

    utils.kill_a_thread(thread, timeout=0.0)
