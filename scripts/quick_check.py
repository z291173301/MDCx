#!/usr/bin/env python3
"""快速检查（日常用，秒级）：只跑格式 + lint + 类型检查，不跑全量测试。

完整检查（含 1490 个测试，约 2 分钟）留给提交前跑一次：
    uv run check --skip-hook-install

日常改完代码后跑本脚本，快速确认没有格式/语法/类型错误：
    uv run quick-check

退出码: 任一检查失败返回 1，否则 0。
"""

import subprocess
import sys

COMMANDS = [
    ["ruff", "format", "--check"],
    ["ruff", "check"],
    [sys.executable, "-m", "mypy", "mdcx/"],
]


def main() -> int:
    for command in COMMANDS:
        print(f"[quick-check] running: {' '.join(command)}")
        result = subprocess.run(command)
        if result.returncode != 0:
            print("[quick-check] 有报错，请先修复后重跑（错误见上方红字）")
            return result.returncode
    print("[quick-check] 快速检查全部通过！")
    print("[quick-check] 提交前记得跑完整检查: uv run check --skip-hook-install")
    return 0


if __name__ == "__main__":
    sys.exit(main())
