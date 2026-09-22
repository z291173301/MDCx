#!/usr/bin/env python3
import json
import os
import platform
import sys

from PIL import ImageFile
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from mdcx.consts import IS_DOCKER, IS_MAC, IS_NFC, IS_PYINSTALLER, IS_WINDOWS, MAIN_PATH
from mdcx.controllers.main_window.main_window import MyMAinWindow
from mdcx.controllers.main_window.style import apply_application_palette
from mdcx.core.tmdb_actor import flush_tmdb_query_cache
from mdcx.utils.video import get_video_backend

ImageFile.LOAD_TRUNCATED_IMAGES = True


def _apply_ui_scale_factor():
    """读取用户配置的 UI 缩放比例并应用到 QT_SCALE_FACTOR。

    在 main() 早期执行，文件不可读/解析失败均不应阻断启动。
    """
    try:
        mark_file = MAIN_PATH / "MDCx.config"
        if not mark_file.is_file():
            return
        with open(mark_file, encoding="UTF-8") as f:
            config_path = f.read().strip()
        if not config_path or not os.path.isfile(config_path):
            return
        with open(config_path, encoding="UTF-8") as f:
            config = json.load(f)
        scale = config.get("ui_scale_factor", 0.0)
        if scale > 0:
            os.environ["QT_SCALE_FACTOR"] = str(scale)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print(f"[warn] _apply_ui_scale_factor skipped: {e}")


def show_constants():
    """显示所有运行时常量"""
    constants = {
        "MAIN_PATH": MAIN_PATH,
        "IS_WINDOWS": IS_WINDOWS,
        "IS_MAC": IS_MAC,
        "IS_DOCKER": IS_DOCKER,
        "IS_NFC": IS_NFC,
        "IS_PYINSTALLER": IS_PYINSTALLER,
        "VIDEO_BACKEND": get_video_backend(),
    }
    print("Run time constants:")
    for key, value in constants.items():
        print(f"\t{key}: {value}")


def _create_application() -> tuple[QApplication, MyMAinWindow]:
    # Qt6 默认把非整数系统缩放（Windows 125%/150% 等）取整到整数倍，导致界面模糊或过大；
    # PassThrough 保留真实缩放因子，配合 ui_scale_factor 配置项工作正常。
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    # 议题 #159：Qt 默认在「最后一个可见顶层窗口」被关闭时自动退出；主窗经托盘
    # 隐藏后不再计入可见窗口，此时关闭演员管理器（无父级、非模态顶层窗口）会
    # 直接炸掉整个进程。托盘驻留应用的退出不应由任意工具窗口驱动，退出统一
    # 走主窗 exit_app()/托盘菜单的显式 QApplication.quit()。
    app.setQuitOnLastWindowClosed(False)
    if platform.system() != "Windows":
        app.setStyle("Fusion")
    apply_application_palette(False)
    if platform.system() != "Windows":
        # 用 resources.icon_ico（已处理 PyInstaller _MEIPASS）而非相对 CWD 路径，
        # 否则冻结包双击运行时 CWD 不同会丢任务栏图标。
        from mdcx.config.resources import resources

        app.setWindowIcon(QIcon(resources.icon_ico))  # 设置任务栏图标

    ui = MyMAinWindow()
    ui.show()
    app.installEventFilter(ui)
    return app, ui


def _enable_crash_dump() -> None:
    """注册崩溃转储：Python 异常 traceback 写入 MAIN_PATH/crash/ 目录。

    用于诊断程序静默退出的问题。仅诊断用，失败不阻断启动。
    crash 目录仅在程序实际崩溃时才创建，正常运行时不产生任何文件。
    """
    try:
        import traceback as _tb
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # C 层崩溃 (segfault) 堆栈：尝试启用，无 stderr 时静默跳过
        # （打包 windowed 模式下 sys.stderr 可能不可用，segfault 堆栈无法落盘）
        try:
            import faulthandler

            faulthandler.enable()
        except Exception:
            pass

        # Python 未捕获异常：崩溃时才懒创建目录和文件
        def _hook(etype, evalue, etb):
            try:
                text = "".join(_tb.format_exception(etype, evalue, etb))
                crash_dir = MAIN_PATH / "crash"
                crash_dir.mkdir(parents=True, exist_ok=True)
                with open(crash_dir / f"crash_{ts}_py.log", "a", encoding="utf-8") as f:
                    f.write(text)
            except Exception:
                pass
            try:
                sys.__excepthook__(etype, evalue, etb)
            except Exception:
                pass

        sys.excepthook = _hook
    except Exception:
        pass


def _ensure_stdio() -> None:
    """PyInstaller windowed 模式下 sys.stdout/stderr 可能为 None，导致 print() 崩溃。

    重定向到 devnull（不创建任何文件），excepthook 仍能在崩溃时懒创建 crash 目录写文件。
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # type: ignore[assignment]


def _ensure_block_auto_relaunch() -> bool:
    """拦截「MDCx 自身代码再 exec main.py」导致的自动二次启动，放行手工多开。

    标记机制：
    - MDCx 首次启动时设置环境变量 MDCX_IS_FIRST_INSTANCE=1
    - 检测网络/外部 CF 适配层等路径再次 exec main.py 时，继承该环境变量
    - 再次 exec 的进程检测到 MDCX_IS_FIRST_INSTANCE 已存在 → 自动拦截，直接退出
    - 用户手工双击/命令行新开（全新进程树，环境变量未继承）→ 放行，不限多开
    返回 True = 放行；False = 拦截（调用方应直接退出）。
    """
    if os.environ.get("MDCX_IS_FIRST_INSTANCE") == "1":
        print("[MDCx] 检测到由已运行 MDCx 自动拉起的二次启动，拦截（手工多开不受限）")
        return False
    # 首次启动（或手工多开）：标记本进程树，供后续自动 exec 继承
    os.environ["MDCX_IS_FIRST_INSTANCE"] = "1"
    return True


def main() -> int:
    _enable_crash_dump()
    _ensure_stdio()
    if not _ensure_block_auto_relaunch():
        return 0
    show_constants()
    _apply_ui_scale_factor()
    app, _ui = _create_application()
    try:
        return_code = app.exec()
        return return_code
    except Exception as e:
        print("MAIN EXCEPTION:", e)
        try:
            import traceback as _tb

            _tb.print_exc()
        except Exception:
            pass
        return 1
    finally:
        flush_tmdb_query_cache()


if __name__ == "__main__":
    sys.exit(main())
