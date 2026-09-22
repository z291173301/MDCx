import os
import time
from unittest.mock import patch

import pytest

from mdcx.controllers.main_window import tool_handlers

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class _FakeLineEdit:
    def __init__(self, text=""):
        self._text = text

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text

    def strip(self):
        return self._text.strip()


class _FakeButton:
    def __init__(self):
        self._enabled = True
        self._text = ""

    def setEnabled(self, enabled):
        self._enabled = enabled

    def setText(self, text):
        self._text = text


class _FakeUi:
    def __init__(self):
        self.lineEdit_actor_photo_folder = _FakeLineEdit()
        self.lineEdit_gfriends_local_path = _FakeLineEdit()
        self.label_gfriends_update_time = _FakeLineEdit()
        self.pushButton_sync_gfriends = _FakeButton()


class _FakeWindow:
    def __init__(self):
        self.Ui = _FakeUi()
        self.saved = False
        self.show_log_called = False
        self.options = None

    def _get_select_folder_path(self, line_edit):
        return "/selected/path"

    def pushButton_save_config_clicked(self):
        self.saved = True

    def pushButton_show_log_clicked(self):
        self.show_log_called = True


class TestPickFolder:
    def test_pick_folder_sets_text_and_saves(self):
        win = _FakeWindow()
        tool_handlers.pushButton_select_actor_photo_folder_clicked(win)
        assert win.Ui.lineEdit_actor_photo_folder._text == "/selected/path"
        assert win.saved is True

    def test_pick_folder_skips_when_no_path(self):
        win = _FakeWindow()

        def no_path(_):
            return None

        win._get_select_folder_path = no_path
        tool_handlers.pushButton_select_actor_photo_folder_clicked(win)
        assert win.Ui.lineEdit_actor_photo_folder._text == ""
        assert win.saved is False

    def test_all_directory_pickers_delegate_to_pick_folder(self):
        pickers = [
            ("pushButton_select_softlink_folder_clicked", "lineEdit_movie_softlink_path"),
            ("pushButton_select_sucess_folder_clicked", "lineEdit_success"),
            ("pushButton_select_failed_folder_clicked", "lineEdit_fail"),
            ("pushButton_select_subtitle_folder_clicked", "lineEdit_sub_folder"),
            ("pushButton_select_actor_photo_folder_clicked", "lineEdit_actor_photo_folder"),
            ("pushButton_select_local_library_clicked", "lineEdit_local_library_path"),
            ("pushButton_select_netdisk_path_clicked", "lineEdit_netdisk_path"),
            ("pushButton_select_localdisk_path_clicked", "lineEdit_localdisk_path"),
            ("pushButton_select_media_folder_clicked", "lineEdit_movie_path"),
        ]
        for func_name, attr in pickers:
            ui = _FakeUi()
            setattr(ui, attr, _FakeLineEdit())
            win = _FakeWindow()
            win.Ui = ui

            getattr(tool_handlers, func_name)(win)
            assert getattr(win.Ui, attr)._text == "/selected/path"
            assert win.saved is True


class TestSyncGfriends:
    def test_sync_gfriends_no_path_shows_warning(self):
        win = _FakeWindow()
        win.Ui.lineEdit_gfriends_local_path = _FakeLineEdit("")

        with patch.object(tool_handlers.QMessageBox, "warning") as mock_warning:
            tool_handlers.pushButton_sync_gfriends_clicked(win)
            mock_warning.assert_called_once()

    def test_sync_gfriends_success_updates_label(self, qapp):
        win = _FakeWindow()
        win.Ui.lineEdit_gfriends_local_path = _FakeLineEdit("/some/path")

        with (
            patch("mdcx.tools.sync_gfriends.sync_gfriends", return_value=(True, "ok")),
            patch.object(tool_handlers.signal_qt, "show_scrape_info") as mock_info,
            patch.object(tool_handlers, "get_current_time", return_value="2026-01-01"),
        ):
            tool_handlers.pushButton_sync_gfriends_clicked(win)
            deadline = time.monotonic() + 5
            while not mock_info.called and time.monotonic() < deadline:
                qapp.processEvents()
                time.sleep(0.02)
            mock_info.assert_called_once_with("✅ ok")
            assert win.Ui.label_gfriends_update_time._text == "最后更新: 2026-01-01"

    def test_sync_gfriends_failure_shows_dialog(self, qapp):
        win = _FakeWindow()
        win.Ui.lineEdit_gfriends_local_path = _FakeLineEdit("/some/path")

        with (
            patch("mdcx.tools.sync_gfriends.sync_gfriends", return_value=(False, "error msg")),
            patch.object(tool_handlers.QMessageBox, "warning") as mock_warning,
            patch.object(tool_handlers, "get_current_time", return_value="2026-01-01"),
        ):
            tool_handlers.pushButton_sync_gfriends_clicked(win)
            deadline = time.monotonic() + 5
            while not mock_warning.called and time.monotonic() < deadline:
                qapp.processEvents()
                time.sleep(0.02)
            mock_warning.assert_called_once()
            assert win.Ui.label_gfriends_update_time._text == "最后更新: 2026-01-01"


class TestActorDbSelect:
    def test_select_actor_info_db_opens_dialog_and_sets_path(self):
        win = _FakeWindow()
        win.Ui.lineEdit_actor_db_path = _FakeLineEdit()

        with patch.object(tool_handlers.QFileDialog, "getOpenFileName", return_value=("/db.xlsx", "")):
            tool_handlers.pushButton_select_actor_info_db_clicked(win)
            assert win.Ui.lineEdit_actor_db_path._text == "/db.xlsx"
            assert win.saved is True

    def test_select_actor_info_db_skips_when_cancelled(self):
        win = _FakeWindow()
        win.Ui.lineEdit_actor_db_path = _FakeLineEdit()

        with patch.object(tool_handlers.QFileDialog, "getOpenFileName", return_value=("", "")):
            tool_handlers.pushButton_select_actor_info_db_clicked(win)
            assert win.Ui.lineEdit_actor_db_path._text == ""
            assert win.saved is False
