import re
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

app = typer.Typer(
    name="bump",
    help="MDCx 版本号管理工具",
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()


def get_project_root() -> Path:
    """获取项目根目录"""
    current = Path(__file__).resolve()
    # 从 scripts/bump.py 往上找到项目根目录
    while current.parent != current:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    raise FileNotFoundError("无法找到项目根目录（包含 pyproject.toml 的目录）")


def get_consts_file() -> Path:
    """获取 consts.py 文件路径"""
    project_root = get_project_root()
    consts_file = project_root / "mdcx" / "consts.py"
    if not consts_file.exists():
        raise FileNotFoundError(f"找不到 consts.py 文件: {consts_file}")
    return consts_file


def get_pyproject_file() -> Path:
    project_root = get_project_root()
    return project_root / "pyproject.toml"


def get_changelog_file() -> Path:
    project_root = get_project_root()
    return project_root / "docs" / "changelog.md"


def get_current_version() -> int:
    """从 consts.py 中获取当前 LOCAL_VERSION"""
    consts_file = get_consts_file()
    content = consts_file.read_text(encoding="utf-8")

    match = re.search(r"LOCAL_VERSION\s*=\s*(\d+)", content)
    if not match:
        raise ValueError("在 consts.py 中找不到 LOCAL_VERSION")

    return int(match.group(1))


def get_current_name() -> str:
    """从 consts.py 中获取当前 VERSION_NAME（形如 v2.1.0）"""
    content = get_consts_file().read_text(encoding="utf-8")
    match = re.search(r'VERSION_NAME\s*=\s*"([^"]+)"', content)
    if not match:
        raise ValueError("在 consts.py 中找不到 VERSION_NAME")
    return match.group(1)


def _normalize_name(name: str) -> str:
    """把展示版本名规范为 vX.Y.Z 形态。"""
    name = name.strip()
    if not name.startswith("v"):
        name = "v" + name
    if not re.fullmatch(r"v\d+\.\d+\.\d+", name):
        raise ValueError(f"展示版本名格式无效（应为 vX.Y.Z）: {name}")
    return name


def update_local_version(new_version: int) -> Path:
    """更新 consts.py 中的 LOCAL_VERSION。"""
    consts_file = get_consts_file()
    content = consts_file.read_text(encoding="utf-8")

    pattern = r"(LOCAL_VERSION\s*=\s*)\d+"
    new_content = re.sub(pattern, rf"\g<1>{new_version}", content)
    if new_content == content:
        raise ValueError("版本号替换失败，请检查 consts.py 文件格式")

    consts_file.write_text(new_content, encoding="utf-8")
    return consts_file


def update_display_name(new_name: str) -> tuple[Path, Path]:
    """更新 consts.py 的 VERSION_NAME 与 pyproject.toml 的 version。"""
    consts_file = get_consts_file()
    content = consts_file.read_text(encoding="utf-8")
    new_content = re.sub(r'(VERSION_NAME\s*=\s*)"[^"]+"', rf'\g<1>"{new_name}"', content)
    if new_content == content:
        raise ValueError("VERSION_NAME 替换失败，请检查 consts.py 文件格式")
    consts_file.write_text(new_content, encoding="utf-8")

    pyproject = get_pyproject_file()
    py_content = pyproject.read_text(encoding="utf-8")
    py_new = re.sub(
        r'(?m)^(version\s*=\s*)"[^"]+"',
        rf'\g<1>"{new_name.removeprefix("v")}"',
        py_content,
        count=1,
    )
    if py_new == py_content:
        raise ValueError("pyproject.toml 版本号替换失败")
    pyproject.write_text(py_new, encoding="utf-8")
    return consts_file, pyproject


def update_changelog_date(new_local_version: int, display_name: str) -> Path | None:
    """把 changelog 首个版本段的日期同步为 LOCAL_VERSION 对应的日期。

    仅当首个版本段的版本号与 display_name 一致时才更新（否则说明段标题尚未
    为本次发布准备，跳过并提示）。
    """
    changelog = get_changelog_file()
    if not changelog.exists():
        return None
    content = changelog.read_text(encoding="utf-8")

    match = re.search(r"(?m)^##\s+(v\d+\.\d+\.\d+)\s+\((\d{4})-(\d{2})-(\d{2})\)", content)
    if not match:
        return None
    if match.group(1) != display_name:
        console.print(
            f"[yellow]⚠ changelog 首个版本段是 {match.group(1)}，与当前展示版本 {display_name} 不一致，"
            "跳过日期同步（请先为该版本创建 changelog 段）[/yellow]"
        )
        return None

    date_str = f"{str(new_local_version)[:4]}-{str(new_local_version)[4:6]}-{str(new_local_version)[6:8]}"
    new_content = content[: match.start()] + f"## {display_name} ({date_str})" + content[match.end() :]
    changelog.write_text(new_content, encoding="utf-8")
    return changelog


def check_consistency() -> list[str]:
    """校验四处版本点是否一致，返回问题列表（空表示一致）。"""
    issues: list[str] = []
    local = get_current_version()
    name = get_current_name()

    pyproject = get_pyproject_file()
    py_content = pyproject.read_text(encoding="utf-8")
    py_match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', py_content)
    if not py_match or py_match.group(1) != name.removeprefix("v"):
        issues.append(f"pyproject.toml version={py_match.group(1) if py_match else '?'} 与 VERSION_NAME={name} 不一致")

    changelog = get_changelog_file()
    if changelog.exists():
        content = changelog.read_text(encoding="utf-8")
        head = re.search(r"(?m)^##\s+(v\d+\.\d+\.\d+)\s+\((\d{4})-(\d{2})-(\d{2})\)", content)
        if not head:
            issues.append("changelog 首个版本段格式异常（应为 '## vX.Y.Z (YYYY-MM-DD)'）")
        else:
            if head.group(1) != name:
                issues.append(f"changelog 首个版本段 {head.group(1)} 与 VERSION_NAME={name} 不一致")
            date_digits = head.group(2) + head.group(3) + head.group(4)
            if date_digits != str(local):
                issues.append(f"changelog 版本段日期 {date_digits} 与 LOCAL_VERSION={local} 不一致")
    return issues


@app.command()
def main(
    version: Annotated[int | None, typer.Option("--version", "-v", help="新 LOCAL_VERSION（纯数字 YYYYMMDD）")] = None,
    increment: Annotated[int, typer.Option("--increment", "-i", help="LOCAL_VERSION 增量")] = 1,
    name: Annotated[
        str | None,
        typer.Option(
            "--name", "-N", help="新展示版本名（如 2.1.2 或 v2.1.2）；给出时同步 VERSION_NAME 与 pyproject.toml"
        ),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="预览模式")] = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="强制执行")] = False,
    check: Annotated[bool, typer.Option("--check", "-c", help="仅校验四处版本点是否一致")] = False,
) -> None:
    """
    更新 LOCAL_VERSION（发版日），可选同步展示版本名与 changelog 段日期。

    [bold green]示例:[/bold green]

    • [cyan]python bump.py --check[/cyan] - 校验四处版本点一致
    • [cyan]python bump.py[/cyan] - LOCAL_VERSION +1
    • [cyan]python bump.py --version 20260918[/cyan] - 设为指定日期版本号
    • [cyan]python bump.py --version 20260918 --name 2.1.2[/cyan] - 同时升展示版本
    • [cyan]python bump.py --dry-run[/cyan] - 预览模式
    """
    try:
        if check:
            issues = check_consistency()
            if issues:
                for issue in issues:
                    console.print(f"[red]✗ {issue}[/red]")
                raise typer.Exit(1)
            console.print("[green]✓ 四处版本点一致[/green]")
            return

        current_version = get_current_version()
        current_name = get_current_name()

        if version is not None:
            new_version = version
        else:
            new_version = current_version + increment

        new_name = _normalize_name(name) if name else current_name

        console.print(
            Panel.fit(
                f"[bold]当前版本:[/bold] [yellow]{current_version}[/yellow]（{current_name}）\n"
                f"[bold]新版本:[/bold] [green]{new_version}[/green]（{new_name}）",
                title="[bold blue]版本信息[/bold blue]",
                border_style="blue",
            )
        )

        if new_version == current_version and new_name == current_name:
            console.print("[yellow]版本号没有变化，无需更新[/yellow]")
            return

        if dry_run:
            console.print("[cyan]预览模式：不会实际修改文件[/cyan]")
            console.print(
                "[dim]将修改: consts.py 的 LOCAL_VERSION"
                + (" + VERSION_NAME、pyproject.toml version" if name else "")
                + f"、changelog 段日期（若段标题为 {new_name}）[/dim]"
            )
            return

        if not force:
            if not Confirm.ask(f"确认将版本更新为 {new_version}（{new_name}）？"):
                console.print("[yellow]操作已取消[/yellow]")
                return

        changed = [update_local_version(new_version)]
        if name:
            changed.extend(update_display_name(new_name))
        changelog = update_changelog_date(new_version, new_name)
        if changelog:
            changed.append(changelog)

        console.print(
            Panel.fit(
                f"[bold green]✓[/bold green] 版本已更新：[yellow]{current_version}[/yellow] → [green]{new_version}[/green]"
                f"（{new_name}）",
                title="[bold green]更新完成[/bold green]",
                border_style="green",
            )
        )
        for path in changed:
            console.print(f"[dim]已修改文件: {path}[/dim]")

    except Exception as e:
        console.print(
            Panel.fit(f"[bold red]错误:[/bold red] {e}", title="[bold red]操作失败[/bold red]", border_style="red")
        )
        raise typer.Exit(1) from e


if __name__ == "__main__":
    app()
