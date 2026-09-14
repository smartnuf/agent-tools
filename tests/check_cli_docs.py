"""Check maintained CLI projections and parse guide examples without executing them."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_tools.cli import build_parser  # noqa: E402
from agent_tools.cli_reference import check_reference, command_parsers  # noqa: E402

GUIDES = (ROOT / "README.md", ROOT / "docs/platforms.md", ROOT / "docs/packaging.md")
# These are launcher spellings in the guides, not a command/option inventory.
LAUNCHERS = (
    '& "$(uv tool dir --bin)\\agent-tools.exe"',
    '"$(uv tool dir --bin)/agent-tools"',
    '"$agent_tools"', '& $agentTools', 'agent-tools',
)


def _arguments(text: str) -> list[str] | None:
    for launcher in LAUNCHERS:
        if text.startswith(launcher + " "):
            return shlex.split(text[len(launcher):], comments=True)
    return None


def documented_invocations(markdown: str):
    """Yield concrete fenced/inline invocations; never evaluate shell syntax.

    Inline command-path references are covered by help traversal. Inline syntax
    templates with placeholders are prose, not executable examples. Fenced
    examples must always be concrete and valid, so placeholders there fail.
    """
    paths = {path for path, _ in command_parsers(build_parser())}
    fence = None
    for number, line in enumerate(markdown.splitlines(), 1):
        marker = re.match(r"^\s*```(\w*)\s*$", line)
        if marker:
            fence = marker.group(1) if fence is None else None
            continue
        if fence in {"sh", "bash", "shell", "powershell"}:
            args = _arguments(line.strip())
            if args is not None:
                yield number, args
    # Remove fences before considering inline prose (including multiline spans).
    prose = re.sub(r"(?ms)^\s*```[^\n]*\n.*?^\s*```\s*$", "", markdown)
    for match in re.finditer(r"`([^`]+)`", prose):
        code = " ".join(match.group(1).split())
        args = _arguments(code)
        if args is None or tuple(args) in paths:
            continue
        if any(re.fullmatch(r"[A-Z][A-Z_]*", arg) for arg in args) or any(
            character in code for character in "[]<>"
        ):
            continue
        yield "inline", args


def check_examples(path: Path) -> int:
    parser = build_parser()
    count = 0
    for location, args in documented_invocations(path.read_text(encoding="utf-8")):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as errors:
            try:
                parser.parse_args(args)
            except SystemExit as error:
                if error.code != 0:
                    raise AssertionError(f"{path}:{location}: invalid CLI example {args}: {errors.getvalue()}") from error
        count += 1
    return count


def check_installed_help(executable: Path, directory: str) -> int:
    """Exercise every help entry point and compare its semantic text to source."""
    count = 0
    for path, parser in command_parsers(build_parser()):
        expected = " ".join(parser.format_help().split())
        for flag in ("-h", "--help"):
            result = subprocess.run(
                [str(executable), *path, flag], cwd=directory,
                capture_output=True, text=True, timeout=15,
            )
            assert result.returncode == 0, (path, flag, result.stderr)
            assert not result.stderr, (path, flag, result.stderr)
            assert " ".join(result.stdout.split()) == expected, (
                "installed help differs from source", path, flag, result.stdout, parser.format_help()
            )
            count += 1
    return count


def main() -> int:
    check_reference(ROOT / "docs/cli-reference.md")
    count = sum(check_examples(path) for path in GUIDES)
    print(f"CLI reference current; {count} guide invocations parsed without execution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
