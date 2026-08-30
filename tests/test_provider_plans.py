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
        self.assertEqual(plan.context, states[0].machine)

    def test_linux_plan_is_deterministic_and_inspectable(self):
        states = (self.state(capabilities.POPPLER), self.state(capabilities.GHOSTSCRIPT))
        plan = provider_plans.generate_provider_plan(
            states, ("ghostscript", "poppler", "ghostscript"), available_managers=("apt", "dnf")
        )
        self.assertEqual(plan.requested_capabilities, ("ghostscript", "poppler"))
        self.assertEqual(tuple(action.installation_unit for action in plan.actions), ("ghostscript", "poppler-utils"))
        self.assertEqual(plan.actions[0].commands, (("apt-get", "update"), ("apt-get", "install", "-y", "ghostscript")))
        self.assertTrue(all(action.shared_package for action in plan.actions))
        self.assertEqual(
            plan.actions[0].verification,
            provider_plans.VerificationRequirement(
                capabilities.GHOSTSCRIPT.providers[0].probes,
                capabilities.ProbePolicy.ANY,
            ),
        )
        self.assertEqual(
            plan.actions[1].verification,
            provider_plans.VerificationRequirement(
                capabilities.POPPLER.providers[0].probes,
                capabilities.ProbePolicy.ALL,
            ),
        )
        poppler_probe = plan.actions[1].verification.probes[0]
        self.assertEqual(poppler_probe.version_args, ("-v",))
        self.assertEqual(poppler_probe.locator_strategy, "path")
        self.assertEqual(poppler_probe.nonzero_version_pattern, r"\bversion\b")

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

    def test_native_provisioning_override_names_displaced_translated_provider(self):
        machine = capabilities.MachineState("Windows", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, machine: (
                "C:/Git/bin/bash.exe" if probe.locator_strategy == "git-bash" else None
            ),
            version_reader=lambda probe, path: "GNU bash 5.2",
            architecture_reader=lambda probe, path: "x86_64",
        )
        plan = provider_plans.generate_provider_plan(
            (state,),
            ("bash",),
            available_managers=("winget",),
            native_provisioning=("bash",),
        )
        self.assertEqual(plan.actions[0].displaces_verified_paths, ("C:/Git/bin/bash.exe",))
        self.assertIn("explicit native-provisioning override", plan.actions[0].reason)
        self.assertEqual(plan.actions[0].target_architecture, "arm64")
        self.assertEqual(plan.actions[0].commands[0][-2:], ("--architecture", "arm64"))

    def test_native_override_rejects_native_or_unrequested_capability(self):
        native = self.state(capabilities.BASH, "Windows", available=True)
        with self.assertRaisesRegex(provider_plans.PlanningError, "not a verified translated"):
            provider_plans.generate_provider_plan(
                (native,), ("bash",), available_managers=("winget",), native_provisioning=("bash",)
            )
        with self.assertRaisesRegex(provider_plans.PlanningError, "was not requested"):
            provider_plans.generate_provider_plan(
                (native,), ("bash",), available_managers=("winget",), native_provisioning=("poppler",)
            )

    def test_native_override_rejects_unknown_host_architecture(self):
        machine = capabilities.MachineState("Windows", "unknown")
        state = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, machine: "C:/Git/bin/bash.exe" if probe.locator_strategy == "git-bash" else None,
            version_reader=lambda probe, path: "GNU bash 5.2",
            architecture_reader=lambda probe, path: "x86_64",
        )
        with self.assertRaisesRegex(provider_plans.PlanningError, "known host architecture"):
            provider_plans.generate_provider_plan(
                (state,), ("bash",), available_managers=("winget",), native_provisioning=("bash",)
            )

    def test_native_override_rejects_unknown_provider_architecture(self):
        machine = capabilities.MachineState("Windows", "arm64")
        for architecture in (None, "unknown", "unrecognized"):
            state = capabilities.detect_capability(
                capabilities.BASH,
                machine,
                locator=lambda probe, machine: (
                    "C:/Git/bin/bash.exe" if probe.locator_strategy == "git-bash" else None
                ),
                version_reader=lambda probe, path: "GNU bash 5.2",
                architecture_reader=lambda probe, path, value=architecture: value,
            )
            with self.subTest(architecture=architecture), self.assertRaisesRegex(
                provider_plans.PlanningError, "not a verified translated"
            ):
                provider_plans.generate_provider_plan(
                    (state,),
                    ("bash",),
                    available_managers=("winget",),
                    native_provisioning=("bash",),
                )

    def test_duplicate_detected_states_are_ambiguous(self):
        state = self.state(capabilities.POPPLER)
        with self.assertRaisesRegex(provider_plans.PlanningError, "duplicate detected"):
            provider_plans.generate_provider_plan(
                (state, state), ("poppler",), available_managers=("apt",)
            )

    def test_requested_states_must_share_one_complete_execution_context(self):
        baseline = self.state(capabilities.POPPLER)
        variants = (
            capabilities.MachineState("Darwin", "x86_64", "host"),
            capabilities.MachineState("Linux", "arm64", "host"),
            capabilities.MachineState("Linux", "x86_64", "wsl"),
        )
        for machine in variants:
            other = capabilities.detect_capability(
                capabilities.GHOSTSCRIPT, machine, locator=lambda probe, machine: None
            )
            with self.subTest(machine=machine), self.assertRaisesRegex(
                provider_plans.PlanningError, "multiple execution contexts"
            ):
                provider_plans.generate_provider_plan(
                    (baseline, other), ("poppler", "ghostscript"), available_managers=("apt", "brew")
                )

    def test_irrelevant_observations_do_not_change_plan_context(self):
        requested = self.state(capabilities.POPPLER)
        irrelevant = self.state(capabilities.GHOSTSCRIPT, "Darwin")
        plan = provider_plans.generate_provider_plan(
            (requested, irrelevant, irrelevant), ("poppler",), available_managers=("apt",)
        )
        self.assertEqual(plan.context, requested.machine)

    def test_winget_uses_manager_specific_x64_token(self):
        command = provider_plans.adapter_commands(
            "winget", "Git.Git", target_architecture="x86_64"
        )[0]
        self.assertEqual(command[-2:], ("--architecture", "x64"))

    def test_caller_owned_catalogue_metadata_is_rejected(self):
        custom = capabilities.CapabilitySpec(
            "custom",
            "custom",
            False,
            (
                capabilities.ProviderSpec(
                    "custom-provider",
                    "custom provider",
                    frozenset({"Linux"}),
                    frozenset({"host"}),
                    (capabilities.ExecutableProbe("custom", ("--version",)),),
                    capabilities.ProbePolicy.ANY,
                    packages=(
                        capabilities.ProviderPackage("apt", "arbitrary", frozenset({"Linux"})),
                    ),
                ),
            ),
        )
        state = capabilities.detect_capability(
            custom,
            capabilities.MachineState("Linux", "x86_64"),
            locator=lambda probe, machine: None,
        )
        with self.assertRaisesRegex(provider_plans.PlanningError, "unknown built-in"):
            provider_plans.generate_provider_plan(
                (state,), ("custom",), available_managers=("apt",)
            )


if __name__ == "__main__":
    unittest.main()
