"""Developer projections of the public argparse tree; no operational dispatch."""
from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

from .cli import build_parser


def command_parsers(
    parser: argparse.ArgumentParser,
    path: tuple[str, ...] = (),
) -> Iterator[tuple[tuple[str, ...], argparse.ArgumentParser]]:
    """Traverse the root and nested parsers in definition order.

    argparse has no public tree iterator. Keep the narrow _actions dependency
    here, with root/nested/source/installed coverage on supported Python versions.
    """
    yield path, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                yield from command_parsers(child, (*path, name))


def render_reference(parser: argparse.ArgumentParser | None = None) -> str:
    sections = [
        "# CLI reference\n\n"
        "Generated from the public argparse definitions; do not edit by hand.\n"
        "This describes the current source/next release, not necessarily the published version.\n\n"
        "Regenerate from a development checkout with "
        "`bin/agent-python -m agent_tools.cli_reference --write docs/cli-reference.md` "
        "(Windows: use `bin\\agent-python.cmd`).\n"
    ]
    for _, command in command_parsers(parser or build_parser()):
        sections.append(f"\n## {command.prog}\n\n```text\n{command.format_help()}```\n")
    return "".join(sections)


def check_reference(path: Path) -> None:
    if path.read_text(encoding="utf-8") != render_reference():
        raise ValueError(f"stale CLI reference: regenerate {path} from agent_tools.cli_reference")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", type=Path, help="regenerate a maintained reference file")
    mode.add_argument("--check", type=Path, help="fail if the maintained reference is stale")
    args = parser.parse_args(argv)
    if args.write is not None:
        args.write.write_text(render_reference(), encoding="utf-8", newline="\n")
    else:
        check_reference(args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
