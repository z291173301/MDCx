"""分离模式（main_mode == 2）路径映射测试。

覆盖 mdcx/config/extend.py 的纯函数：
resolve_data_dir / ensure_data_dir / get_separate_meta_root / mirror_meta_folder / remap_meta_paths，
以及 get_movie_path_setting 在分离模式下把 meta_root 追加进 ignore_dirs 的行为，
还有 mdcx/base/file.py move_other_file 的元数据分流。
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

if importlib.util.find_spec("PyQt6") is None:
    pyqt6 = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")

    class QObject:
        pass

    class _Signal:
        def connect(self, *_args, **_kwargs):
            return None

        def emit(self, *_args, **_kwargs):
            return None

    def pyqtSignal(*_args, **_kwargs):
        return _Signal()

    qtcore.QObject = QObject
    qtcore.pyqtSignal = pyqtSignal
    sys.modules["PyQt6"] = pyqt6
    sys.modules["PyQt6.QtCore"] = qtcore


pytestmark = pytest.mark.skipif(sys.version_info < (3, 13), reason="项目配置模型需要 Python 3.13+")


def _separate_config(monkeypatch, tmp_path, *, mode=2, data_dir=None):
    from mdcx.config.manager import manager

    movie = tmp_path / "movie"
    movie.mkdir()
    data = tmp_path / "data" if data_dir is None else Path(data_dir)
    if data_dir is None:
        data.mkdir()
    monkeypatch.setattr(manager.config, "media_path", str(movie))
    monkeypatch.setattr(manager.config, "softlink_path", "softlink")
    monkeypatch.setattr(manager.config, "success_output_folder", "JAV_output")
    monkeypatch.setattr(manager.config, "failed_output_folder", "failed")
    monkeypatch.setattr(manager.config, "folders", [])
    monkeypatch.setattr(manager.config, "scrape_softlink_path", False)
    monkeypatch.setattr(manager.config, "main_mode", mode)
    monkeypatch.setattr(manager.config, "data_path", str(data))
    return movie, data


def test_resolve_data_dir_inactive_without_separate_mode(monkeypatch, tmp_path):
    from mdcx.config.extend import resolve_data_dir

    movie, _ = _separate_config(monkeypatch, tmp_path, mode=1)
    assert resolve_data_dir(movie) is None


def test_resolve_data_dir_blank_returns_none(monkeypatch, tmp_path):
    from mdcx.config.extend import resolve_data_dir

    movie, _ = _separate_config(monkeypatch, tmp_path, mode=2)
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "data_path", "")
    assert resolve_data_dir(movie) is None


def test_resolve_data_dir_missing_gets_created(monkeypatch, tmp_path):
    import mdcx.config.extend as ext
    from mdcx.config.extend import resolve_data_dir

    movie, _ = _separate_config(monkeypatch, tmp_path, mode=2, data_dir=str(tmp_path / "not-exist"))

    monkeypatch.setattr(ext, "_data_dir_logged", set())
    logs = []
    monkeypatch.setattr(ext, "_separate_log", logs.append)
    assert resolve_data_dir(movie) == tmp_path / "not-exist"
    assert (tmp_path / "not-exist").is_dir()
    assert any("新建" in message for message in logs)


def test_ensure_data_dir_existing_file_falls_back(monkeypatch, tmp_path):
    import mdcx.config.extend as ext
    from mdcx.config.extend import ensure_data_dir

    movie, _ = _separate_config(monkeypatch, tmp_path, mode=2)
    from mdcx.config.manager import manager

    busy = tmp_path / "busy.txt"
    busy.write_text("x", encoding="utf-8")
    monkeypatch.setattr(manager.config, "data_path", str(busy))
    monkeypatch.setattr(ext, "_data_dir_logged", set())
    logs = []
    monkeypatch.setattr(ext, "_separate_log", logs.append)
    assert ensure_data_dir(movie) is None
    assert any("不是目录" in message for message in logs)


def test_ensure_data_dir_uncreatable_falls_back_to_normal(monkeypatch, tmp_path):
    import mdcx.config.extend as ext
    from mdcx.config.extend import ensure_data_dir

    movie, _ = _separate_config(monkeypatch, tmp_path, mode=2, data_dir=str(tmp_path / "nope"))

    def _deny(self, *args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "mkdir", _deny)
    monkeypatch.setattr(ext, "_elevated_mkdir", lambda target: False)
    monkeypatch.setattr(ext, "_admin_mkdir_attempted", False)
    monkeypatch.setattr(ext, "_data_dir_logged", set())
    logs = []
    monkeypatch.setattr(ext, "_separate_log", logs.append)
    assert ensure_data_dir(movie) is None
    assert any("回退到正常模式" in message for message in logs)


def test_ensure_data_dir_elevated_success_only_once(monkeypatch, tmp_path):
    import os

    import mdcx.config.extend as ext
    from mdcx.config.extend import ensure_data_dir

    movie, _ = _separate_config(monkeypatch, tmp_path, mode=2, data_dir=str(tmp_path / "nope"))
    calls = []

    def _deny(self, *args, **kwargs):
        raise PermissionError("denied")

    def _fake_elevated(target):
        calls.append(str(target))
        os.makedirs(target, exist_ok=True)
        return True

    monkeypatch.setattr(Path, "mkdir", _deny)
    monkeypatch.setattr(ext, "_elevated_mkdir", _fake_elevated)
    monkeypatch.setattr(ext, "_admin_mkdir_attempted", False)
    monkeypatch.setattr(ext, "_data_dir_logged", set())
    logs = []
    monkeypatch.setattr(ext, "_separate_log", logs.append)
    assert ensure_data_dir(movie) == tmp_path / "nope"
    assert (tmp_path / "nope").is_dir()
    assert len(calls) == 1
    # 第二个建不出来的目录不再触发提权（全进程只试一次），直接回退
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "data_path", str(tmp_path / "nope2"))
    assert ensure_data_dir(movie) is None
    assert len(calls) == 1


def test_resolve_data_dir_relative_to_movie_path(monkeypatch, tmp_path):
    from mdcx.config.extend import resolve_data_dir

    movie, _ = _separate_config(monkeypatch, tmp_path, mode=2)
    (movie / "meta").mkdir()
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "data_path", "meta")
    assert resolve_data_dir(movie) == movie / "meta"


def test_get_separate_meta_root(monkeypatch, tmp_path):
    from mdcx.config.extend import get_separate_meta_root
    from mdcx.config.manager import manager

    movie, data = _separate_config(monkeypatch, tmp_path, mode=2)
    assert get_separate_meta_root(movie, movie / "JAV_output") == data / "JAV_output"
    # 非分离模式不激活
    monkeypatch.setattr(manager.config, "main_mode", 1)
    assert get_separate_meta_root(movie, movie / "JAV_output") is None


def test_get_separate_meta_root_same_as_success_folder(monkeypatch, tmp_path):
    from mdcx.config.extend import get_separate_meta_root
    from mdcx.config.manager import manager

    movie, _ = _separate_config(monkeypatch, tmp_path, mode=2)
    # 数据目录直接指向视频目录本身：meta = movie/JAV_output == success，退化为正常模式
    monkeypatch.setattr(manager.config, "data_path", str(movie))
    assert get_separate_meta_root(movie, movie / "JAV_output") is None


def test_mirror_meta_folder(monkeypatch, tmp_path):
    from mdcx.config.extend import mirror_meta_folder

    movie, data = _separate_config(monkeypatch, tmp_path, mode=2)
    success = movie / "JAV_output"
    meta_root = data / "JAV_output"
    assert mirror_meta_folder(success / "ABC-123", success, meta_root) == meta_root / "ABC-123"
    # success_folder 自身映射到 meta_root 自身
    assert mirror_meta_folder(success, success, meta_root) == meta_root
    # 视频树之外的路径原样返回
    outside = tmp_path / "elsewhere" / "x.nfo"
    assert mirror_meta_folder(outside, success, meta_root) == outside


def test_remap_meta_paths(monkeypatch, tmp_path):
    from mdcx.config.extend import remap_meta_paths

    movie, data = _separate_config(monkeypatch, tmp_path, mode=2)
    meta_folder = data / "JAV_output" / "ABC-123"
    paths = {
        "nfo": movie / "JAV_output" / "ABC-123" / "ABC-123.nfo",
        "poster": movie / "JAV_output" / "ABC-123" / "ABC-123-poster.jpg",
        "thumb": None,
    }
    remapped = remap_meta_paths(paths, meta_folder)
    assert remapped == {
        "nfo": meta_folder / "ABC-123.nfo",
        "poster": meta_folder / "ABC-123-poster.jpg",
        "thumb": None,
    }


def test_get_movie_path_setting_appends_meta_root_to_ignore_dirs(monkeypatch, tmp_path):
    from mdcx.config.extend import get_movie_path_setting

    movie, data = _separate_config(monkeypatch, tmp_path, mode=2)
    # 数据目录放在扫描树内：镜像子树必须被排除
    inner = movie / "meta"
    inner.mkdir()
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "data_path", str(inner))
    setting = get_movie_path_setting(movie / "MIAA-001.mp4")
    assert setting.success_folder == movie / "JAV_output"
    assert (inner / "JAV_output") in setting.ignore_dirs


def test_get_movie_path_setting_no_meta_outside_tree(monkeypatch, tmp_path):
    from mdcx.config.extend import get_movie_path_setting

    movie, data = _separate_config(monkeypatch, tmp_path, mode=2)
    setting = get_movie_path_setting(movie / "MIAA-001.mp4")
    # 数据目录在扫描树外：ignore_dirs 不变
    assert setting.ignore_dirs == []


def test_move_other_file_splits_meta_and_video(monkeypatch, tmp_path):
    from mdcx.base.file import move_other_file
    from mdcx.config.manager import manager

    old = tmp_path / "old"
    video_new = tmp_path / "video_new"
    meta_new = tmp_path / "meta_new"
    old.mkdir()
    video_new.mkdir()
    meta_new.mkdir()
    (old / "ABC-123.nfo").write_text("nfo", encoding="utf-8")
    (old / "ABC-123-poster.jpg").write_bytes(b"jpg")
    (old / "ABC-123.srt").write_text("sub", encoding="utf-8")

    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "main_mode", 2)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "success_file_rename", True)
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])

    asyncio.run(move_other_file("ABC-123", old, video_new, "ABC-123", "ABC-123", meta_new))

    assert (meta_new / "ABC-123.nfo").exists()
    assert (meta_new / "ABC-123-poster.jpg").exists()
    assert (video_new / "ABC-123.srt").exists()
    assert not (old / "ABC-123.nfo").exists()


def test_move_other_file_without_meta_behaves_as_before(monkeypatch, tmp_path):
    from mdcx.base.file import move_other_file
    from mdcx.config.manager import manager

    old = tmp_path / "old2"
    video_new = tmp_path / "video_new2"
    old.mkdir()
    video_new.mkdir()
    (old / "ABC-123.nfo").write_text("nfo", encoding="utf-8")

    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "main_mode", 1)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "success_file_rename", True)
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])

    asyncio.run(move_other_file("ABC-123", old, video_new, "ABC-123", "ABC-123"))

    assert (video_new / "ABC-123.nfo").exists()


def test_clean_empty_folders_allow_empty_overrides_config(monkeypatch, tmp_path):
    from mdcx.base.file import _clean_empty_folders
    from mdcx.config.manager import manager
    from mdcx.models.enums import FileMode

    movie, _ = _separate_config(monkeypatch, tmp_path, mode=2)
    empty_keep = movie / "empty_keep"
    empty_keep.mkdir()
    monkeypatch.setattr(manager.config, "del_empty_folder", True)
    asyncio.run(_clean_empty_folders(movie, FileMode.Default, allow_empty=False))
    assert empty_keep.is_dir()

    empty_drop = movie / "empty_drop"
    empty_drop.mkdir()
    monkeypatch.setattr(manager.config, "del_empty_folder", False)
    asyncio.run(_clean_empty_folders(movie, FileMode.Default, allow_empty=True))
    assert not empty_drop.exists()
    assert not empty_keep.exists()


def test_clean_empty_folders_none_falls_back_to_config(monkeypatch, tmp_path):
    from mdcx.base.file import _clean_empty_folders
    from mdcx.config.manager import manager
    from mdcx.models.enums import FileMode

    movie, _ = _separate_config(monkeypatch, tmp_path, mode=1)
    empty_dir = movie / "empty_dir"
    empty_dir.mkdir()
    monkeypatch.setattr(manager.config, "del_empty_folder", False)
    asyncio.run(_clean_empty_folders(movie, FileMode.Default))
    assert empty_dir.is_dir()

    monkeypatch.setattr(manager.config, "del_empty_folder", True)
    asyncio.run(_clean_empty_folders(movie, FileMode.Default))
    assert not empty_dir.exists()


_LEFT_FLAGS = ("success_file_move", "failed_file_move", "success_file_rename", "del_empty_folder")
_RIGHT_FLAGS = (
    "separate_success_file_move",
    "separate_failed_file_move",
    "separate_success_file_rename",
    "separate_del_empty_folder",
)
_EFF_FUNCS = (
    "eff_success_file_move",
    "eff_failed_file_move",
    "eff_success_file_rename",
    "eff_del_empty_folder",
)
_RIGHT_RADIOS_ON = (
    "radioButton_separate_mode_succ_move_on",
    "radioButton_separate_mode_fail_move_on",
    "radioButton_separate_mode_succ_rename_on",
    "radioButton_separate_mode_del_empty_folder_on",
)
_RIGHT_RADIOS_OFF = (
    "radioButton_separate_mode_succ_move_off",
    "radioButton_separate_mode_fail_move_off",
    "radioButton_separate_mode_succ_rename_off",
    "radioButton_separate_mode_del_empty_folder_off",
)


def test_is_separate_mode_only_for_main_mode_2(monkeypatch):
    from mdcx.config import extend
    from mdcx.config.manager import manager

    for mode, expected in ((1, False), (2, True), (3, False), (4, False), (5, False)):
        monkeypatch.setattr(manager.config, "main_mode", mode)
        assert extend.is_separate_mode() is expected


def test_eff_flags_follow_left_in_normal_mode(monkeypatch):
    """正常模式（main_mode=1）：右侧开关无论怎么拨，有效值都等于左侧。"""
    import mdcx.config.extend as extend
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "main_mode", 1)
    for left, right, func_name in zip(_LEFT_FLAGS, _RIGHT_FLAGS, _EFF_FUNCS, strict=True):
        monkeypatch.setattr(manager.config, left, True)
        monkeypatch.setattr(manager.config, right, False)
        assert getattr(extend, func_name)() is True
        monkeypatch.setattr(manager.config, left, False)
        monkeypatch.setattr(manager.config, right, True)
        assert getattr(extend, func_name)() is False


def test_eff_flags_follow_right_in_separate_mode(monkeypatch):
    """分离模式（main_mode=2）：视频文件操作的有效值等于右侧开关。"""
    import mdcx.config.extend as extend
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "main_mode", 2)
    for left, right, func_name in zip(_LEFT_FLAGS, _RIGHT_FLAGS, _EFF_FUNCS, strict=True):
        monkeypatch.setattr(manager.config, left, True)
        monkeypatch.setattr(manager.config, right, False)
        assert getattr(extend, func_name)() is False
        monkeypatch.setattr(manager.config, left, False)
        monkeypatch.setattr(manager.config, right, True)
        assert getattr(extend, func_name)() is True


def test_move_other_file_respects_separate_move_off(monkeypatch, tmp_path):
    """分离模式 + 右侧移动关/重命名关：其他文件留在原地（左侧开也拦不住）。"""
    from mdcx.base.file import move_other_file
    from mdcx.config.manager import manager

    old = tmp_path / "old3"
    video_new = tmp_path / "video_new3"
    meta_new = tmp_path / "meta_new3"
    old.mkdir()
    video_new.mkdir()
    meta_new.mkdir()
    (old / "ABC-123.srt").write_text("sub", encoding="utf-8")

    monkeypatch.setattr(manager.config, "soft_link", 0)
    monkeypatch.setattr(manager.config, "main_mode", 2)
    monkeypatch.setattr(manager.config, "success_file_move", True)
    monkeypatch.setattr(manager.config, "success_file_rename", True)
    monkeypatch.setattr(manager.config, "separate_success_file_move", False)
    monkeypatch.setattr(manager.config, "separate_success_file_rename", False)
    monkeypatch.setattr(manager.config, "media_type", [".mp4"])

    asyncio.run(move_other_file("ABC-123", old, video_new, "ABC-123", "ABC-123", meta_new))

    assert (old / "ABC-123.srt").exists()
    assert not (video_new / "ABC-123.srt").exists()


def test_save_load_config_wire_separate_radios():
    """回归锁：save/load 必须读写全部 8 个右侧 radio 与 4 个 separate_* 字段，防改名漂移。"""
    from pathlib import Path as _Path

    base = _Path(__file__).resolve().parents[1] / "mdcx" / "controllers" / "main_window"
    save_src = (base / "save_config.py").read_text(encoding="utf-8")
    load_src = (base / "load_config.py").read_text(encoding="utf-8")
    # 保存只读「开」按钮的 isChecked；加载要同时定位开/关按钮
    for radio in _RIGHT_RADIOS_ON:
        assert radio in save_src, f"save_config.py 未引用 {radio}"
        assert radio in load_src, f"load_config.py 未引用 {radio}"
    for radio in _RIGHT_RADIOS_OFF:
        assert radio in load_src, f"load_config.py 未引用 {radio}"
    for field in _RIGHT_FLAGS:
        assert field in save_src, f"save_config.py 未引用 {field}"
        assert field in load_src, f"load_config.py 未引用 {field}"


def test_separate_flags_inherit_left_when_missing():
    """旧 JSON 里没有 separate_* 键：默认和左侧开关一致（左关则右也关）。"""
    from mdcx.config.models import Config

    data = {
        "success_file_move": True,
        "failed_file_move": False,
        "success_file_rename": True,
        "del_empty_folder": False,
    }
    Config.update(data)
    assert data["separate_success_file_move"] is True
    assert data["separate_failed_file_move"] is False
    assert data["separate_success_file_rename"] is True
    assert data["separate_del_empty_folder"] is False
    cfg = Config.model_validate(data)
    assert cfg.separate_success_file_move is True
    assert cfg.separate_failed_file_move is False
    assert cfg.separate_success_file_rename is True
    assert cfg.separate_del_empty_folder is False


def test_separate_flags_missing_keys_default_to_true():
    """全新配置（左右键都没有）：右侧默认全开，和左侧默认一致。"""
    from mdcx.config.models import Config

    data: dict = {}
    Config.update(data)
    for field in _RIGHT_FLAGS:
        assert data[field] is True
    cfg = Config.model_validate(data)
    for field in _RIGHT_FLAGS:
        assert getattr(cfg, field) is True


def test_separate_flags_preserved_when_present():
    """已保存过的配置：右侧键已存在，用户选择不被左侧覆盖。"""
    from mdcx.config.models import Config

    data = {
        "success_file_move": True,
        "separate_success_file_move": False,
    }
    Config.update(data)
    assert data["separate_success_file_move"] is False
    assert Config.model_validate(data).separate_success_file_move is False


def test_separate_flags_json_roundtrip():
    """写入 JSON 再读回：四个右侧开关都在 JSON 里且值不变。"""
    import json

    from mdcx.config.models import Config

    data = {
        "separate_success_file_move": False,
        "separate_failed_file_move": True,
        "separate_success_file_rename": False,
        "separate_del_empty_folder": True,
    }
    Config.update(data)
    cfg = Config.model_validate(data)
    raw = json.loads(cfg.model_dump_json())
    assert raw["separate_success_file_move"] is False
    assert raw["separate_failed_file_move"] is True
    assert raw["separate_success_file_rename"] is False
    assert raw["separate_del_empty_folder"] is True
    cfg2 = Config.model_validate(raw)
    assert cfg2.separate_success_file_move is False
    assert cfg2.separate_del_empty_folder is True


def test_should_generate_strm_only_in_separate_mode(monkeypatch, tmp_path):
    """STRM 只在分离模式下生效：其他模式（1/3/4/5）即使勾选也不生成。"""
    from mdcx.config.extend import should_generate_strm
    from mdcx.config.manager import manager

    meta = tmp_path / "meta"
    meta.mkdir()
    monkeypatch.setattr(manager.config, "separate_generate_strm", True)
    for mode in (1, 3, 4, 5):
        monkeypatch.setattr(manager.config, "main_mode", mode)
        assert should_generate_strm(meta, False) is False
    monkeypatch.setattr(manager.config, "main_mode", 2)
    assert should_generate_strm(meta, False) is True


def test_should_overwrite_strm_only_in_separate_mode(monkeypatch):
    """STRM 覆盖开关只在分离模式下生效：其他模式即使勾选也不覆盖。"""
    from mdcx.config.extend import should_overwrite_strm
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "separate_overwrite_strm", True)
    for mode in (1, 3, 4, 5):
        monkeypatch.setattr(manager.config, "main_mode", mode)
        assert should_overwrite_strm() is False
    monkeypatch.setattr(manager.config, "main_mode", 2)
    assert should_overwrite_strm() is True
    monkeypatch.setattr(manager.config, "separate_overwrite_strm", False)
    assert should_overwrite_strm() is False


def test_should_reuse_metadata_only_in_separate_mode(monkeypatch):
    """元数据复用开关只在分离模式下生效：其他模式即使勾选也不复用。"""
    from mdcx.config.extend import should_reuse_metadata
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "separate_reuse_metadata", True)
    for mode in (1, 3, 4, 5):
        monkeypatch.setattr(manager.config, "main_mode", mode)
        assert should_reuse_metadata() is False
    monkeypatch.setattr(manager.config, "main_mode", 2)
    assert should_reuse_metadata() is True
    monkeypatch.setattr(manager.config, "separate_reuse_metadata", False)
    assert should_reuse_metadata() is False


def test_should_overwrite_meta_only_in_separate_mode(monkeypatch):
    """元数据覆盖开关只在分离模式下生效：其他模式即使勾选也不覆盖。"""
    from mdcx.config.extend import should_overwrite_meta
    from mdcx.config.manager import manager

    monkeypatch.setattr(manager.config, "separate_overwrite_meta", True)
    for mode in (1, 3, 4, 5):
        monkeypatch.setattr(manager.config, "main_mode", mode)
        assert should_overwrite_meta() is False
    monkeypatch.setattr(manager.config, "main_mode", 2)
    assert should_overwrite_meta() is True
    monkeypatch.setattr(manager.config, "separate_overwrite_meta", False)
    assert should_overwrite_meta() is False


def test_should_generate_strm_requires_flag_meta_and_reorganize(monkeypatch, tmp_path):
    """分离模式下：未勾选 / 元数据根无效 / 跳过整理时均不生成。"""
    from mdcx.config.extend import should_generate_strm
    from mdcx.config.manager import manager

    meta = tmp_path / "meta"
    meta.mkdir()
    monkeypatch.setattr(manager.config, "main_mode", 2)
    monkeypatch.setattr(manager.config, "separate_generate_strm", False)
    assert should_generate_strm(meta, False) is False
    monkeypatch.setattr(manager.config, "separate_generate_strm", True)
    assert should_generate_strm(None, False) is False
    assert should_generate_strm(meta, True) is False
    assert should_generate_strm(meta, False) is True


def test_strm_flags_default_false_and_roundtrip():
    """STRM 两个开关默认 False（旧配置缺键不继承左侧），JSON 往返不变。"""
    import json

    from mdcx.config.models import Config

    cfg = Config.model_validate({})
    assert cfg.separate_generate_strm is False
    assert cfg.separate_overwrite_strm is False
    assert cfg.separate_reuse_metadata is False
    assert cfg.separate_overwrite_meta is False
    cfg.separate_generate_strm = True
    cfg.separate_overwrite_strm = True
    cfg.separate_reuse_metadata = True
    cfg.separate_overwrite_meta = True
    raw = json.loads(cfg.model_dump_json())
    assert raw["separate_generate_strm"] is True
    assert raw["separate_overwrite_strm"] is True
    assert raw["separate_reuse_metadata"] is True
    assert raw["separate_overwrite_meta"] is True
    cfg2 = Config.model_validate(raw)
    assert cfg2.separate_generate_strm is True
    assert cfg2.separate_overwrite_strm is True
    assert cfg2.separate_reuse_metadata is True
    assert cfg2.separate_overwrite_meta is True
