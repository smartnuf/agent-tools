import unittest

from agent_tools import capabilities
from agent_tools import provider_plans


class ProviderPlanTests(unittest.TestCase):
    def state(self, capability, platform="Linux", *, available=False):
        machine = capabilities.MachineState(platform, "x86_64")
        return capabilities.detect_capability(
            capability,
            machine,
            locator=(lambda probe, machine: f"/tools/{probe.name}" if available else None),
            version_reader=lambda probe, path: "1.0",
        )

    def test_all_satisfied_plan_has_zero_actions(self):
        states = (self.state(capabilities.POPPLER, available=True), self.state(capabilities.GHOSTSCRIPT, available=True))
        plan = provider_plans.generate_provider_plan(
            states, ("poppler", "ghostscript"), available_managers=("apt",)
        )
        self.assertEqual(plan.actions, ())
        self.assertFalse(plan.changes_host)

    def test_linux_plan_is_deterministic_and_inspectable(self):
        states = (self.state(capabilities.POPPLER), self.state(capabilities.GHOSTSCRIPT))
        plan = provider_plans.generate_provider_plan(
            states, ("ghostscript", "poppler", "ghostscript"), available_managers=("apt", "dnf")
        )
        self.assertEqual(plan.requested_capabilities, ("ghostscript", "poppler"))
        self.assertEqual(tuple(action.installation_unit for action in plan.actions), ("ghostscript", "poppler-utils"))
        self.assertEqual(plan.actions[0].commands, (("apt-get", "update"), ("apt-get", "install", "-y", "ghostscript")))
        self.assertTrue(all(action.shared_package for action in plan.actions))

    def test_platform_adapters_render_expected_argv(self):
        cases = {
            "winget": ("winget", "install", "--id", "unit"),
            "apt": ("apt-get", "update"),
            "dnf": ("dnf", "install", "-y", "unit"),
            "pacman": ("pacman", "-S", "--needed", "--noconfirm", "unit"),
            "brew": ("brew", "install", "unit"),
        }
        for manager, prefix in cases.items():
            with self.subTest(manager=manager):
                self.assertEqual(provider_plans.adapter_commands(manager, "unit")[0][:len(prefix)], prefix)

    def test_windows_git_bash_uses_shared_git_package(self):
        state = self.state(capabilities.BASH, "Windows")
        plan = provider_plans.generate_provider_plan(
            (state,), ("bash",), available_managers=("winget",)
        )
        action = plan.actions[0]
        self.assertEqual((action.provider_id, action.installation_unit), ("git-bash", "Git.Git"))
        self.assertTrue(action.shared_package)

    def test_unsupported_unknown_and_unplannable_requests_fail(self):
        unsupported = self.state(capabilities.POPPLER, "Plan9")
        absent = self.state(capabilities.POPPLER)
        with self.assertRaisesRegex(provider_plans.PlanningError, "unsupported"):
            provider_plans.generate_provider_plan((unsupported,), ("poppler",), available_managers=("apt",))
        with self.assertRaisesRegex(provider_plans.PlanningError, "no detected state"):
            provider_plans.generate_provider_plan((), ("poppler",), available_managers=("apt",))
        with self.assertRaisesRegex(provider_plans.PlanningError, "no supported provider plan"):
            provider_plans.generate_provider_plan((absent,), ("poppler",), available_managers=())

    def test_unknown_adapter_fails_without_execution(self):
        with self.assertRaisesRegex(provider_plans.PlanningError, "unsupported package manager"):
            provider_plans.adapter_commands("unknown", "unit")


if __name__ == "__main__":
    unittest.main()
