from dataclasses import dataclass
from pathlib import Path

from ..manual import ManualConfig
from ..utils.path import is_descendant
from .enums import Website
from .manager import manager
from .models import CleanAction


@dataclass
class MoviePathSetting:
    """路径设置"""

    movie_path: Path  # 电影路径
    movie_paths: list[Path]  # 电影路径列表
    success_folder: Path  # 成功目录
    failed_folder: Path  # 失败目录
    ignore_dirs: list[Path]  # 排除目录列表
    extrafanart_folder: Path  # 剧照副本目录
    softlink_path: Path  # 软链接路径


def parse_media_paths(media_path: str | Path | None = None) -> list[Path]:
    """解析待刮削目录，支持使用英文/中文分号分隔多个目录。"""
    if media_path is None:
        media_path = manager.config.media_path
    if media_path == "":
        return [manager.data_folder]
    if isinstance(media_path, Path):
        return [media_path]

    paths: list[Path] = []
    for item in str(media_path).replace("；", ";").split(";"):
        path_text = item.strip().strip("\"'")
        if not path_text:
            continue
        path = Path(path_text)
        if path not in paths:
            paths.append(path)
    return paths or [manager.data_folder]


SEPARATE_MAIN_MODE = 2
"""分离模式的 main_mode 值：视频与元数据分开存放，其余逻辑同正常模式。"""

SEPARATE_META_EXTS = frozenset({".nfo", ".jpg", ".jpeg", ".png", ".webp"})
"""分离模式下归入数据存放目录的元数据文件扩展名（小写）。"""


def is_separate_mode() -> bool:
    """当前是否为分离模式（刮削模式 == 2）。

    分离模式下，视频刮削目录内的视频文件（移动/重命名/失败移动）走右侧
    「分离模式」开关；正常模式下全部走左侧开关（右侧开关被忽略）。
    """
    return manager.config.main_mode == SEPARATE_MAIN_MODE


def eff_success_file_move() -> bool:
    """视频文件「刮削成功后移动」生效值：分离模式取右侧，否则取左侧。"""
    return manager.config.separate_success_file_move if is_separate_mode() else manager.config.success_file_move


def eff_failed_file_move() -> bool:
    """视频文件「刮削失败后移动」生效值：分离模式取右侧，否则取左侧。"""
    return manager.config.separate_failed_file_move if is_separate_mode() else manager.config.failed_file_move


def eff_success_file_rename() -> bool:
    """视频文件「刮削成功重命名」生效值：分离模式取右侧，否则取左侧。"""
    return manager.config.separate_success_file_rename if is_separate_mode() else manager.config.success_file_rename


def eff_del_empty_folder() -> bool:
    """数据存放目录「刮削结束删除空目录」生效值：分离模式取右侧，否则取左侧。

    注意：视频刮削目录下的空目录清理永远走左侧 del_empty_folder（见调用方显式传参），
    本函数只用于数据存放目录（meta_root）一侧。
    """
    return manager.config.separate_del_empty_folder if is_separate_mode() else manager.config.del_empty_folder


def resolve_data_dir(movie_path: Path) -> Path | None:
    """解析数据存放目录；分离模式未启用/未设置/不可用时返回 None（回退正常模式）。

    目录不存在时会自动新建（见 ensure_data_dir），新建失败则回退正常模式。
    """
    if manager.config.main_mode != SEPARATE_MAIN_MODE:
        return None
    data_path = (getattr(manager.config, "data_path", "") or "").strip()
    if not data_path:
        return None
    return ensure_data_dir(movie_path)


_data_dir_logged: set[str] = set()
"""已打过新建/回退日志的数据目录（绝对路径字符串），避免每个文件重复刷屏。"""

_admin_mkdir_attempted = False
"""进程内是否已尝试过提权建目录（只弹一次 UAC，避免每个文件都弹窗）。"""


def _separate_log(text: str) -> None:
    """分离模式日志：优先走 UI 日志通道，失败时退到标准 logging（无 Qt 的测试桩环境不炸）。"""
    try:
        from ..signals import signal_qt

        signal_qt.show_log_text(text)
    except Exception:
        import logging

        logging.getLogger("mdcx.separate").warning(text)


def _elevated_mkdir(target: Path) -> bool:
    """提权新建目录：Windows 用 runas 拉起 UAC 并等待完成，POSIX 用 sudo -n（免交互，失败即放弃）。"""
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class SHELLEXECUTEINFOW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("fMask", ctypes.c_ulong),
                    ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR),
                    ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int),
                    ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR),
                    ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD),
                    ("hIcon", wintypes.HANDLE),
                    ("hProcess", wintypes.HANDLE),
                ]

            sei = SHELLEXECUTEINFOW()
            sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
            sei.fMask = 0x40  # SEE_MASK_NOCLOSEPROCESS：拿到进程句柄以便等待完成
            sei.lpVerb = "runas"
            sei.lpFile = "cmd.exe"
            sei.lpParameters = f'/c mkdir "{target}"'
            sei.nShow = 0  # SW_HIDE
            if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
                return False
            try:
                ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, 60000)
                ctypes.windll.kernel32.CloseHandle(sei.hProcess)
            except Exception:
                return False
        else:
            result = subprocess.run(["sudo", "-n", "mkdir", "-p", str(target)], timeout=60, capture_output=True)
            if result.returncode != 0:
                return False
    except Exception:
        return False
    return target.is_dir()


def ensure_data_dir(movie_path: Path) -> Path | None:
    """确保数据存放目录可用：不存在则新建；新建失败则尝试提权新建；仍失败返回 None（回退正常模式）。"""
    global _admin_mkdir_attempted
    if manager.config.main_mode != SEPARATE_MAIN_MODE:
        return None
    data_path = (getattr(manager.config, "data_path", "") or "").strip()
    if not data_path:
        return None
    data_dir = Path(data_path)
    if not data_dir.is_absolute():
        data_dir = movie_path / data_dir
    if data_dir.is_dir():
        return data_dir
    key = str(data_dir)
    if data_dir.exists():
        if key not in _data_dir_logged:
            _data_dir_logged.add(key)
            _separate_log(f"⚠️ 数据存放目录已存在但不是目录：{data_dir}，本次回退到正常模式")
        return None
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if data_dir.is_dir():
        if key not in _data_dir_logged:
            _data_dir_logged.add(key)
            _separate_log(f"📁 数据存放目录不存在，已自动新建：{data_dir}")
        return data_dir
    if not _admin_mkdir_attempted:
        _admin_mkdir_attempted = True
        _separate_log(f"⚠️ 无权限新建数据存放目录，尝试以管理员权限新建：{data_dir}")
        try:
            _elevated_mkdir(data_dir)
        except Exception:
            pass
        if data_dir.is_dir():
            if key not in _data_dir_logged:
                _data_dir_logged.add(key)
                _separate_log(f"📁 已以管理员权限新建数据存放目录：{data_dir}")
            return data_dir
    if key not in _data_dir_logged:
        _data_dir_logged.add(key)
        _separate_log(f"⚠️ 数据存放目录无法新建（管理员权限也失败）：{data_dir}，本次回退到正常模式")
    return None


def get_separate_meta_root(movie_path: Path, success_folder: Path) -> Path | None:
    """分离模式元数据根目录 = 数据目录/success_folder 名；无效时返回 None。"""
    data_dir = resolve_data_dir(movie_path)
    if data_dir is None:
        return None
    meta_root = data_dir / success_folder.name
    if meta_root == success_folder:
        return None
    return meta_root


def mirror_meta_folder(folder: Path, success_folder: Path, meta_root: Path) -> Path:
    """把视频输出目录映射为数据目录下的镜像目录；映射失败回退原目录。"""
    try:
        rel = folder.relative_to(success_folder)
    except ValueError:
        return folder
    if not rel.parts:
        return meta_root
    return meta_root / rel


def remap_meta_paths(paths: dict[str, Path | None], meta_folder: Path) -> dict[str, Path | None]:
    """保留文件名、把元数据路径换到镜像目录下（None 保持 None）。"""
    return {key: (meta_folder / path.name if path is not None else None) for key, path in paths.items()}


def _select_movie_path(movie_paths: list[Path], file_path: Path | None) -> Path:
    if not file_path:
        return movie_paths[0]
    for movie_path in movie_paths:
        if is_descendant(file_path, movie_path):
            return movie_path
    if manager.config.scrape_softlink_path:
        for movie_path in movie_paths:
            end_folder_name = movie_path.name
            softlink_path = Path(manager.config.softlink_path.replace("end_folder_name", end_folder_name))
            if not softlink_path.is_absolute():
                softlink_path = movie_path / softlink_path
            if is_descendant(file_path, softlink_path):
                return movie_path
    return movie_paths[0]


def get_movie_path_setting(
    file_path: Path | None = None, movie_path_override: str | Path | None = None
) -> MoviePathSetting:
    movie_paths = parse_media_paths(movie_path_override)  # 用户设置的扫描媒体路径
    movie_path = _select_movie_path(movie_paths, file_path)
    end_folder_name = movie_path.name
    # 用户设置的软链接输出目录
    softlink_path = Path(manager.config.softlink_path.replace("end_folder_name", end_folder_name))
    # 用户设置的成功输出目录
    success_folder = Path(manager.config.success_output_folder.replace("end_folder_name", end_folder_name))
    # 用户设置的失败输出目录
    failed_folder = Path(manager.config.failed_output_folder.replace("end_folder_name", end_folder_name))
    # 用户设置的排除目录, 转换相对路径
    ignore_dirs = []
    for f in manager.config.folders:
        p = Path(f.replace("end_folder_name", end_folder_name))
        if not p.is_absolute():
            p = movie_path / p
        ignore_dirs.append(p)
    # 用户设置的剧照副本目录
    extrafanart_folder = Path(manager.config.extrafanart_folder)

    # 转换相对路径
    if not softlink_path.is_absolute():
        softlink_path = movie_path / softlink_path
    if not success_folder.is_absolute():
        success_folder = movie_path / success_folder
    if not failed_folder.is_absolute():
        failed_folder = movie_path / failed_folder

    if file_path:
        file_path = Path(file_path)
        temp_path = movie_path
        if manager.config.scrape_softlink_path:
            temp_path = softlink_path
        if "first_folder_name" in success_folder.as_posix() or "first_folder_name" in failed_folder.as_posix():
            try:
                first_folder_parts = file_path.relative_to(temp_path).parts
            except ValueError:
                first_folder_parts = ()
            first_folder_name = first_folder_parts[0] if first_folder_parts else ""
            success_folder = Path(success_folder.as_posix().replace("first_folder_name", first_folder_name))
            failed_folder = Path(failed_folder.as_posix().replace("first_folder_name", first_folder_name))

    # 分离模式：数据目录落在扫描树内时，把元数据镜像根目录加入排除，避免二次扫描
    meta_root = get_separate_meta_root(movie_path, success_folder)
    if meta_root is not None and meta_root not in ignore_dirs and is_descendant(meta_root, movie_path):
        ignore_dirs.append(meta_root)

    return MoviePathSetting(
        movie_path=movie_path,
        movie_paths=movie_paths,
        success_folder=success_folder,
        failed_folder=failed_folder,
        ignore_dirs=ignore_dirs,
        extrafanart_folder=extrafanart_folder,
        softlink_path=softlink_path,
    )


def need_clean(file_path: Path, file_name: str, file_ext: str) -> bool:
    # 判断文件是否需清理
    if not manager.computed.can_clean:
        return False

    # 不清理的扩展名
    if CleanAction.CLEAN_IGNORE_EXT in manager.config.clean_enable and file_ext in manager.config.clean_ignore_ext:
        return False

    # 不清理的文件名包含
    if CleanAction.CLEAN_IGNORE_CONTAINS in manager.config.clean_enable:
        for each in manager.config.clean_ignore_contains:
            if each in file_name:
                return False

    # 清理的扩展名
    if CleanAction.CLEAN_EXT in manager.config.clean_enable and file_ext in manager.config.clean_ext:
        return True

    # 清理的文件名等于
    if CleanAction.CLEAN_NAME in manager.config.clean_enable and file_name in manager.config.clean_name:
        return True

    # 清理的文件名包含
    if CleanAction.CLEAN_CONTAINS in manager.config.clean_enable:
        for each in manager.config.clean_contains:
            if each in file_name:
                return True

    # 清理的文件大小<=(KB)
    if CleanAction.CLEAN_SIZE in manager.config.clean_enable:
        try:  # 路径太长时，此处会报错 FileNotFoundError: [WinError 3] 系统找不到指定的路径。
            return file_path.stat().st_size <= manager.config.clean_size * 1024
        except Exception:
            pass
    return False


def deal_url(url: str) -> tuple[str | None, str]:
    # 先 strip 再补 scheme，避免带首尾空格的 URL 补成 "https:// example.com"（中间含空格失效）
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    for key, site in ManualConfig.WEB_DIC.items():
        if key.lower() in url.lower():
            return site.value, url

    # 自定义的网址
    for site in Website:
        if (r := manager.config.site_configs.get(site)) and r.custom_url:
            if str(r.custom_url) in url:
                return site.value, url

    return None, url
