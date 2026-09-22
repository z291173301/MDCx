"""归档目录创建失败的错误识别测试（议题 #96）。

映射云盘（115/夸克等）对单个文件夹名的长度/字符限制比本地 NTFS 严，目录名超限时
系统返回 WinError 123；必须与真正的权限不足（WinError 5）区分开。
"""

from mdcx.core.file import _is_invalid_name_error


def test_detects_winerror_123_via_winerror_attribute():
    error = OSError(123, "文件名、目录名或卷标语法不正确")
    error.winerror = 123
    assert _is_invalid_name_error(error) is True


def test_detects_winerror_123_via_message():
    error = OSError("[WinError 123] 文件名、目录名或卷标语法不正确。: 'Z:\\\\dir'")
    assert _is_invalid_name_error(error) is True

    chinese = OSError("文件名、目录名或卷标语法不正确。: 'Z:\\\\dir'")
    assert _is_invalid_name_error(chinese) is True


def test_does_not_match_permission_or_other_errors():
    assert _is_invalid_name_error(OSError(5, "拒绝访问")) is False
    assert _is_invalid_name_error(PermissionError("access denied")) is False
    assert _is_invalid_name_error(FileNotFoundError("missing")) is False
