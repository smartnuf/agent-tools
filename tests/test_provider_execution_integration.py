import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_tools import capabilities
from agent_tools import provider_execution
from agent_tools import provider_plans


class ProviderExecutionIntegrationTests(unittest.TestCase):
    """Exercise the executor against a disposable filesystem-backed host."""

    def test_real_subprocess_install_rediscovery_and_repeat(self):
        machine = capabilities.MachineState("Linux", "x86_64")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "gs"
            helper = root / "package_manager.py"
            helper.write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "marker = Path(sys.argv[1])\n"
                "if 'install' in sys.argv[2:]:\n"
                "    marker.write_text('installed', encoding='utf-8')\n",
                encoding="utf-8",
            )

            def detect(capability, context):
                return capabilities.detect_capability(
                    capability,
                    context,
                    locator=lambda probe, current: (
                        str(marker)
                        if probe.name == "gs" and marker.is_file()
                        else None
                    ),
                    version_reader=lambda probe, path: "Ghostscript 1.0",
                )

            absent = detect(capabilities.GHOSTSCRIPT, machine)
            manager = provider_plans.PackageManagerState(
                "apt", "/verified/apt-get", "host", "x86_64"
            )
            plan = provider_plans.generate_provider_plan(
                (absent,),
                ("ghostscript",),
                package_managers=(manager,),
            )
            subprocess_calls = []

            def run(reviewed_argv, timeout):
                actual = (
                    sys.executable,
                    str(helper),
                    str(marker),
                    *reviewed_argv[1:],
                )
                subprocess_calls.append(actual)
                return subprocess.run(
                    actual,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

            arguments = {
                "allow_provider_mutation": True,
                "current_context": lambda: machine,
                "manager_verifier": lambda state, context: True,
                "privilege_resolver": lambda action: "",
                "detector": detect,
                "runner": run,
            }
            first = provider_execution.execute_provider_plan(plan, **arguments)
            self.assertEqual(first.outcome, provider_execution.PlanOutcome.SUCCEEDED)
            self.assertTrue(marker.is_file())
            self.assertEqual(len(subprocess_calls), 2)

            repeated = provider_execution.execute_provider_plan(plan, **arguments)
            self.assertEqual(repeated.outcome, provider_execution.PlanOutcome.SUCCEEDED)
            self.assertEqual(
                repeated.actions[0].outcome,
                provider_execution.ActionOutcome.ALREADY_SATISFIED,
            )
            self.assertEqual(len(subprocess_calls), 2)


if __name__ == "__main__":
    unittest.main()
