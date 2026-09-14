from __future__ import annotations

import argparse
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
import os
import signal
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_tools import cli
from agent_tools.cli_reference import check_reference, command_parsers, render_reference
from check_cli_docs import GUIDES, ROOT, check_examples, documented_invocations


class CliReferenceTests(unittest.TestCase):
    def test_reference_and_guides_are_current(self):
        check_reference(ROOT / "docs/cli-reference.md")
        self.assertGreater(sum(check_examples(path) for path in GUIDES), 20)

    def test_all_help_is_successful_without_operational_dispatch(self):
        with ExitStack() as stack:
            for name in ("doctor", "tools_list", "tools_status", "install_capabilities",
                         "_change_desired_capability", "_claude_code_integration_status",
                         "_change_claude_code_integration"):
                stack.enter_context(patch.object(cli, name, side_effect=AssertionError("help dispatched work")))
            parsers = tuple(command_parsers(cli.build_parser()))
            self.assertGreater(len(parsers), 10)
            for path, parser in parsers:
                self.assertTrue(parser.description, path)
                for action in parser._actions:
                    if not isinstance(action, argparse._SubParsersAction):
                        self.assertTrue(action.help, (path, action.dest))
                for flag in ("-h", "--help"):
                    with self.subTest(path=path, flag=flag), redirect_stdout(StringIO()) as output, \
                         redirect_stderr(StringIO()) as errors:
                        with self.assertRaises(SystemExit) as result:
                            cli.main([*path, flag])
                        self.assertEqual(result.exception.code, 0)
                        self.assertEqual(output.getvalue(), parser.format_help())
                        self.assertEqual(errors.getvalue(), "")

    def test_rendering_ignores_terminal_width_and_application_version(self):
        with patch.dict(os.environ, {"COLUMNS": "40"}), patch.object(cli, "_application_version", return_value="1.2.3"):
            narrow = render_reference()
        with patch.dict(os.environ, {"COLUMNS": "180"}), patch.object(cli, "_application_version", return_value="9.9.9"):
            self.assertEqual(render_reference(), narrow)

    def test_one_definition_changes_help_and_reference_and_detects_staleness(self):
        parser = cli.build_parser()
        old = render_reference(parser)
        parser.add_argument("--fixture-option", default="first", help="fixture default: %(default)s")
        first = render_reference(parser)
        self.assertNotEqual(first, old)
        self.assertIn("fixture default: first", parser.format_help())
        parser.set_defaults(fixture_option="second")
        second = render_reference(parser)
        self.assertNotEqual(first, second)
        self.assertIn("fixture default: second", second)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "reference.md"
            path.write_text(old)
            with patch("agent_tools.cli_reference.build_parser", return_value=parser):
                with self.assertRaisesRegex(ValueError, "stale CLI reference"):
                    check_reference(path)

    def test_configuration_interrupt_status_matches_help_on_each_platform(self):
        # This tests only CLI propagation/CPython exit translation. The existing
        # cooperative-cancellation fixtures test mutation recovery itself.
        cases = (
            (["tools", "enable", "bash", "--allow-config-mutation"], "set_capability"),
            (["tools", "disable", "bash", "--allow-config-mutation"], "set_capability"),
            (["integrations", "claude-code", "apply", "--allow-config-mutation"], "apply_git_bash_integration"),
            (["integrations", "claude-code", "remove", "--allow-config-mutation"], "remove_git_bash_integration"),
        )
        for args, target in cases:
            with self.subTest(args=args):
                code = (
                    "import signal, sys\n"
                    "from unittest.mock import patch\n"
                    "from agent_tools import cli\n"
                    "def interrupt(*args, **kwargs): signal.raise_signal(signal.SIGINT)\n"
                    f"with patch.object(cli, {target!r}, side_effect=interrupt):\n"
                    f"    raise SystemExit(cli.main({args!r}))\n"
                )
                result = subprocess.run([sys.executable, "-c", code],
                    capture_output=True, text=True, timeout=15)
                if sys.platform == "win32":
                    self.assertEqual(result.returncode & 0xFFFFFFFF, 0xC000013A)
                else:
                    self.assertEqual(result.returncode, -signal.SIGINT)
                self.assertIn("KeyboardInterrupt", result.stderr)
        text = render_reference()
        # Wrapping is incidental: check the common facts after normalization.
        normalized = " ".join(text.split())
        self.assertEqual(normalized.count("shell status 130"), 4)
        self.assertEqual(normalized.count("0xC000013A"), 4)

    def test_examples_are_extracted_from_guides_without_executing_shell(self):
        guide = '''```sh
agent-tools install poppler --allow-provider-mutation
"$agent_tools" tools status
```
```powershell
& $agentTools doctor
& "$(uv tool dir --bin)\\agent-tools.exe" --version
```
Use `agent-tools tools enable bash --allow-config-mutation`.
The `agent-tools install CAPABILITY [CAPABILITY ...]` syntax is a template.
The `agent-tools integrations claude-code` group is a command reference.
'''
        examples = [args for _, args in documented_invocations(guide)]
        self.assertEqual(examples, [
            ["install", "poppler", "--allow-provider-mutation"], ["tools", "status"],
            ["doctor"], ["--version"], ["tools", "enable", "bash", "--allow-config-mutation"],
        ])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "guide.md"
            path.write_text('```sh\nagent-tools renamed-command\n```\n')
            with self.assertRaisesRegex(AssertionError, "invalid CLI example"):
                check_examples(path)
            path.write_text('Use `agent-tools install bash --obsolete-option`.\n')
            with self.assertRaisesRegex(AssertionError, "invalid CLI example"):
                check_examples(path)


if __name__ == "__main__":
    unittest.main()
