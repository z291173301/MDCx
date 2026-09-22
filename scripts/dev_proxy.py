#!/usr/bin/env python3
"""devbox 被墙站点测试代理（开发辅助工具，不随 GUI 分发使用场景）.

用途:
    在沙箱/CI 等直连受限的环境里，用 mihomo 内核加载免费/自备节点，
    快速搭建本地 mixed-port 代理，用于测试被墙站点（heyzo/caribbean 等）
    的连通性与页面结构。

用法:
    uv run python -m scripts.dev_proxy start            # 启动（默认订阅源+7890 端口）
    uv run python -m scripts.dev_proxy start --source <订阅URL> --port 7890
    uv run python -m scripts.dev_proxy status           # 查看运行状态
    uv run python -m scripts.dev_proxy test <url>       # 走代理测一个 URL
    uv run python -m scripts.dev_proxy stop             # 停止并清理

说明:
    - 内核与配置缓存在系统临时目录 mdcx-dev-proxy/ 下，不污染工作区
    - 订阅经 proxy-providers 引用，mihomo 自带健康检查自动剔除死节点
    - 免费节点质量参差，test 连续失败时用 --source 换源或稍后重试
"""

import argparse
import os
import platform
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

MIHOMO_VERSION = "v1.19.30"
DEFAULT_SOURCES = (
    "https://raw.githubusercontent.com/shaoyouvip/free/refs/heads/main/mihomo.yaml",
    "https://sub.maflya.com",
    "https://b8xdx.no-mad-sub.one/link/8njQnx2vRKTqfvqo?clash=3&extend=1",
)
WORK_DIR = Path(tempfile.gettempdir()) / "mdcx-dev-proxy"
PORT = 7890

PROVIDER_BLOCK = """\
  {name}:
    type: http
    url: "{url}"
    interval: 3600
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 300
"""


def build_config(port: int, controller_port: int, sources: list[str], region_filter: str = "") -> str:
    filter_line = f'\n    filter: "{region_filter}"' if region_filter else ""
    providers = "".join(
        PROVIDER_BLOCK.format(name=f"subs{i}", url=url).rstrip("\n") + filter_line + "\n"
        for i, url in enumerate(sources)
    )
    used = ", ".join(f"subs{i}" for i in range(len(sources)))
    # 订阅域名直连例外：避免"拉订阅走 AUTO、AUTO 又等订阅"的死锁
    direct_rules = "".join(f"  - DOMAIN,{urlsplit(url).netloc},DIRECT\n" for url in sources)
    return f"""\
mixed-port: {port}
mode: rule
log-level: warning
external-controller: 127.0.0.1:{controller_port}
proxy-providers:
{providers}
proxy-groups:
  - name: AUTO
    type: url-test
    use: [{used}]
    url: https://www.gstatic.com/generate_204
    interval: 180
    tolerance: 100
rules:
{direct_rules}  - MATCH,AUTO
"""


def _download(url: str, dest: Path, timeout: int = 90) -> None:
    print(f"[dev-proxy] 下载 {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "mdcx-dev-proxy"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, dest.open("wb") as f:
        f.write(resp.read())


def ensure_core() -> Path:
    system = platform.system().lower()  # linux / darwin / windows
    arch = "amd64" if platform.machine() in ("x86_64", "AMD64", "amd64") else "arm64"
    ext = ".exe" if system == "windows" else ""
    core = WORK_DIR / f"mihomo{ext}"
    if core.exists() and os.access(core, os.X_OK):
        return core
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    archive = WORK_DIR / "mihomo.gz"
    tag_url = (
        f"https://github.com/MetaCubeX/mihomo/releases/download/{MIHOMO_VERSION}/"
        f"mihomo-{system}-{arch}-{MIHOMO_VERSION}.gz"
    )
    try:
        _download(tag_url, archive)
    except Exception as exc:
        raise SystemExit(f"[dev-proxy] 内核下载失败（检查直连网络）: {exc}") from exc
    import gzip

    with gzip.open(archive, "rb") as src, core.open("wb") as dst:
        dst.write(src.read())
    archive.unlink()
    core.chmod(0o755)
    print(f"[dev-proxy] 内核就绪: {core}")
    return core


def instance_files(port: int) -> dict[str, Path]:
    """按端口隔离实例文件，支持多实例并存（如 7890 全节点 + 7891 日本节点）。"""
    suffix = "" if port == PORT else f"-{port}"
    return {
        "pid": WORK_DIR / f"mihomo{suffix}.pid",
        "log": WORK_DIR / f"mihomo{suffix}.log",
        "config": WORK_DIR / f"config{suffix}.yaml",
    }


def is_running(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    pid = int(pid_file.read_text().strip() or 0)
    try:
        os.kill(pid, 0)
        return pid
    except OSError:
        pid_file.unlink(missing_ok=True)
        return None


def cmd_start(args: argparse.Namespace) -> None:
    files = instance_files(args.port)
    running = is_running(files["pid"])
    if running:
        print(f"[dev-proxy] 已在运行 (pid={running})，端口 {args.port}")
        return
    core = ensure_core()
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    sources = [args.source] if args.source else list(DEFAULT_SOURCES)
    files["config"].write_text(
        build_config(args.port, args.port + 1000, sources, args.regions),
        encoding="utf-8",
    )
    log = files["log"].open("ab")
    proc = subprocess.Popen(
        [str(core), "-d", str(WORK_DIR), "-f", str(files["config"])],
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=WORK_DIR,
    )
    files["pid"].write_text(str(proc.pid))
    time.sleep(2)
    if proc.poll() is not None:
        print(f"[dev-proxy] 启动失败，日志尾部:\n{files['log'].read_text(errors='ignore')[-500:]}")
        raise SystemExit(1)
    region_note = f"，节点过滤 {args.regions}" if args.regions else ""
    print(
        f"[dev-proxy] 已启动 (pid={proc.pid})，代理地址 http://127.0.0.1:{args.port}，订阅源 {len(sources)} 个{region_note}"
    )


def cmd_stop(args: argparse.Namespace) -> None:
    files = instance_files(args.port)
    pid = is_running(files["pid"])
    if pid is None:
        print("[dev-proxy] 未在运行")
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(10):
        time.sleep(0.5)
        if is_running(files["pid"]) is None:
            break
    else:
        os.kill(pid, signal.SIGKILL)
    print("[dev-proxy] 已停止")


def cmd_status(args: argparse.Namespace) -> None:
    files = instance_files(args.port)
    pid = is_running(files["pid"])
    state = f"运行中 (pid={pid})" if pid else "未运行"
    print(f"[dev-proxy] 端口 {args.port}: {state}，代理地址 http://127.0.0.1:{args.port}")
    if pid and getattr(args, "url", None):
        cmd_test(args)


def cmd_test(args: argparse.Namespace) -> None:
    import httpx

    proxy = f"http://127.0.0.1:{args.port}"
    try:
        r = httpx.get(
            args.url,
            proxy=proxy,
            timeout=args.timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        body = r.text[:200].replace("\n", " ")
        print(f"[dev-proxy] HTTP{r.status_code} {len(r.content)}B <- {args.url}\n  {body}")
    except Exception as exc:
        print(f"[dev-proxy] FAIL {str(exc)[:150]} <- {args.url}")
        raise SystemExit(1) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="devbox 测试代理管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="启动本地代理")
    p_start.add_argument(
        "--source",
        default="",
        help="节点订阅 URL（clash/mihomo yaml 或 base64 订阅）；留空用内置双源",
    )
    p_start.add_argument("--port", type=int, default=PORT, help="本地 mixed-port（默认 7890）")
    p_start.add_argument(
        "--regions",
        default="",
        help='按地区过滤节点（正则，匹配节点名），如 --regions "jp|日本" 只用日本节点；'
        "日本厂商站（faleno/mgstage/mywife 等）有 IP 地理限制时使用。"
        "过滤实例建议换端口与全节点实例并存",
    )
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="停止代理")
    p_stop.add_argument("--port", type=int, default=PORT)
    p_stop.set_defaults(func=cmd_stop)

    p_status = sub.add_parser("status", help="查看状态")
    p_status.add_argument("--port", type=int, default=PORT)
    p_status.set_defaults(func=cmd_status)

    p_test = sub.add_parser("test", help="走代理请求一个 URL")
    p_test.add_argument("url")
    p_test.add_argument("--port", type=int, default=PORT)
    p_test.add_argument("--timeout", type=int, default=25)
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args()
    if args.command == "start" and args.source:
        print(f"[dev-proxy] 订阅源: {args.source}")
    args.func(args)


if __name__ == "__main__":
    main()
