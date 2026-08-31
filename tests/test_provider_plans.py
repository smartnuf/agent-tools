import unittest
from dataclasses import replace

from agent_tools import capabilities
from agent_tools import provider_plans


class ProviderPlanTests(unittest.TestCase):
    def manager(self, manager, *, environment="host", architecture=None):
        executables = {
            "winget": "C:/Windows/System32/winget.exe",
            "apt": "/usr/bin/apt-get",
            "dnf": "/usr/bin/dnf",
            "pacman": "/usr/bin/pacman",
            "brew": "/opt/homebrew/bin/brew",
        }
        if architecture is None and manager == "brew":
            architecture = "arm64"
        return provider_plans.PackageManagerState(
            manager, executables[manager], environment, architecture
        )

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
            states, ("poppler", "ghostscript"), package_managers=(self.manager("apt"),)
        )
        self.assertEqual(plan.actions, ())
        self.assertFalse(plan.changes_host)
        self.assertEqual(plan.context, states[0].machine)

    def test_linux_plan_is_deterministic_and_inspectable(self):
        states = (self.state(capabilities.POPPLER), self.state(capabilities.GHOSTSCRIPT))
        plan = provider_plans.generate_provider_plan(
            states,
            ("ghostscript", "poppler", "ghostscript"),
            package_managers=(self.manager("apt"), self.manager("dnf")),
        )
        self.assertEqual(plan.requested_capabilities, ("ghostscript", "poppler"))
        self.assertEqual(tuple(action.installation_unit for action in plan.actions), ("ghostscript", "poppler-utils"))
        self.assertEqual(plan.actions[0].commands, (("/usr/bin/apt-get", "update"), ("/usr/bin/apt-get", "install", "-y", "ghostscript")))
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

    def test_package_manager_privilege_is_explicit(self):
        expected = {
            "apt": provider_plans.ExecutionPrivilege.SYSTEM,
            "dnf": provider_plans.ExecutionPrivilege.SYSTEM,
            "pacman": provider_plans.ExecutionPrivilege.SYSTEM,
            "brew": provider_plans.ExecutionPrivilege.CURRENT_USER,
            "winget": provider_plans.ExecutionPrivilege.CURRENT_USER,
        }
        for manager, privilege in expected.items():
            with self.subTest(manager=manager):
                self.assertEqual(
                    provider_plans.adapter_execution_privilege(manager), privilege
                )

    def test_windows_git_bash_uses_shared_git_package(self):
        state = self.state(capabilities.BASH, "Windows")
        plan = provider_plans.generate_provider_plan(
            (state,), ("bash",), package_managers=(self.manager("winget"),)
        )
        action = plan.actions[0]
        self.assertEqual((action.provider_id, action.installation_unit), ("git-bash", "Git.Git"))
        self.assertEqual(action.manager_state, self.manager("winget"))
        self.assertEqual(action.commands[0][0], "C:/Windows/System32/winget.exe")
        self.assertTrue(action.shared_package)
        self.assertEqual(
            action.execution_privilege, provider_plans.ExecutionPrivilege.CURRENT_USER
        )

    def test_linux_bash_is_explicitly_provisionable_on_host_and_wsl(self):
        for manager in ("apt", "dnf", "pacman"):
            for environment in ("host", "wsl"):
                machine = capabilities.MachineState("Linux", "x86_64", environment)
                state = capabilities.detect_capability(
                    capabilities.BASH, machine, locator=lambda probe, machine: None
                )
                plan = provider_plans.generate_provider_plan(
                    (state,),
                    ("bash",),
                    package_managers=(self.manager(manager, environment=environment),),
                )
                with self.subTest(manager=manager, environment=environment):
                    self.assertEqual(plan.context, machine)
                    self.assertEqual(len(plan.actions), 1)
                    action = plan.actions[0]
                    self.assertEqual(action.provider_id, "system-bash")
                    self.assertEqual(action.installation_unit, "bash")
                    self.assertEqual(
                        action.manager_state.execution_environment, environment
                    )
                    self.assertEqual(
                        action.execution_privilege,
                        provider_plans.ExecutionPrivilege.SYSTEM,
                    )

    def test_macos_prefers_existing_system_bash_without_mutation(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, machine: (
                "/bin/bash" if probe.locator_strategy == "system-bash" else None
            ),
            version_reader=lambda probe, path: "GNU bash 3.2",
        )
        plan = provider_plans.generate_provider_plan(
            (state,), ("bash",), package_managers=(self.manager("brew"),)
        )
        self.assertEqual(state.selected_provider.provider.provider_id, "system-bash")
        self.assertEqual(plan.actions, ())

    def test_macos_missing_bash_uses_distinct_unprivileged_homebrew_provider(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH, machine, locator=lambda probe, machine: None
        )
        plan = provider_plans.generate_provider_plan(
            (state,), ("bash",), package_managers=(self.manager("brew"),)
        )
        action = plan.actions[0]
        self.assertEqual(action.provider_id, "homebrew-bash")
        self.assertEqual(action.installation_unit, "bash")
        self.assertEqual(action.manager_state, self.manager("brew"))
        self.assertEqual(action.commands, (("/opt/homebrew/bin/brew", "install", "bash"),))
        self.assertEqual(
            action.manager_state.native_status(machine),
            provider_plans.NativeStatus.NATIVE,
        )
        self.assertEqual(
            action.execution_privilege, provider_plans.ExecutionPrivilege.CURRENT_USER
        )

    def test_translated_homebrew_requires_exact_visible_authorization(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH, machine, locator=lambda probe, machine: None
        )
        translated = provider_plans.PackageManagerState(
            "brew", "/usr/local/bin/brew", "host", "x86_64"
        )
        with self.assertRaisesRegex(provider_plans.PlanningError, "no supported provider plan"):
            provider_plans.generate_provider_plan(
                (state,), ("bash",), package_managers=(translated,)
            )
        plan = provider_plans.generate_provider_plan(
            (state,),
            ("bash",),
            package_managers=(translated,),
            translated_manager_fallbacks=(translated,),
        )
        action = plan.actions[0]
        self.assertEqual(action.manager_state, translated)
        self.assertIn("explicit translated package-manager fallback", action.reason)

        native = self.manager("brew")
        preferred = provider_plans.generate_provider_plan(
            (state,),
            ("bash",),
            package_managers=(translated, native),
            translated_manager_fallbacks=(translated,),
        )
        self.assertEqual(preferred.actions[0].manager_state, native)
        self.assertNotIn("translated package-manager", preferred.actions[0].reason)

    def test_unknown_homebrew_architecture_fails_closed(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH, machine, locator=lambda probe, machine: None
        )
        for architecture in (None, "unknown", "unrecognized"):
            manager = provider_plans.PackageManagerState(
                "brew", "/opt/homebrew/bin/brew", "host", architecture
            )
            with self.subTest(architecture=architecture), self.assertRaisesRegex(
                provider_plans.PlanningError, "no supported provider plan"
            ):
                provider_plans.generate_provider_plan(
                    (state,), ("bash",), package_managers=(manager,)
                )

    def test_package_manager_must_be_local_to_plan_context(self):
        machine = capabilities.MachineState("Linux", "x86_64", "wsl")
        state = capabilities.detect_capability(
            capabilities.BASH, machine, locator=lambda probe, machine: None
        )
        host_apt = self.manager("apt", environment="host")
        with self.assertRaisesRegex(provider_plans.PlanningError, "no supported provider plan"):
            provider_plans.generate_provider_plan(
                (state,), ("bash",), package_managers=(host_apt,)
            )

    def test_package_manager_evidence_validation_fails_closed(self):
        state = self.state(capabilities.POPPLER)
        missing_path = provider_plans.PackageManagerState("apt", "", "host")
        with self.assertRaisesRegex(provider_plans.PlanningError, "verified executable path"):
            provider_plans.generate_provider_plan(
                (state,), ("poppler",), package_managers=(missing_path,)
            )
        for path in ("apt-get", "tools/apt-get"):
            manager = provider_plans.PackageManagerState("apt", path, "host")
            with self.subTest(path=path), self.assertRaisesRegex(
                provider_plans.PlanningError, "not absolute"
            ):
                provider_plans.generate_provider_plan(
                    (state,), ("poppler",), package_managers=(manager,)
                )
        windows = self.state(capabilities.POPPLER, "Windows")
        relative_winget = provider_plans.PackageManagerState(
            "winget", "C:tools\\winget.exe", "host"
        )
        with self.assertRaisesRegex(provider_plans.PlanningError, "not absolute"):
            provider_plans.generate_provider_plan(
                (windows,), ("poppler",), package_managers=(relative_winget,)
            )
        first = provider_plans.PackageManagerState(
            "brew", "/opt/homebrew/bin/brew", "host", "arm64"
        )
        conflicting = provider_plans.PackageManagerState(
            "brew", "/opt/homebrew/bin/brew", "host", "x86_64"
        )
        with self.assertRaisesRegex(provider_plans.PlanningError, "conflicting"):
            provider_plans.generate_provider_plan(
                (state,), ("poppler",), package_managers=(first, conflicting)
            )

        windows_first = provider_plans.PackageManagerState(
            "winget", "C:\\Windows\\System32\\winget.exe", "host", "arm64"
        )
        windows_conflicting = provider_plans.PackageManagerState(
            "winget", "c:/windows/system32/winget.exe", "host", "x86_64"
        )
        with self.assertRaisesRegex(provider_plans.PlanningError, "conflicting"):
            provider_plans.generate_provider_plan(
                (windows,),
                ("poppler",),
                package_managers=(windows_first, windows_conflicting),
            )

        dot_segment_conflicts = (
            (
                state,
                provider_plans.PackageManagerState(
                    "brew", "/opt/homebrew/bin/../bin/brew", "host", "arm64"
                ),
                provider_plans.PackageManagerState(
                    "brew", "/opt/homebrew/bin/brew", "host", "x86_64"
                ),
            ),
            (
                windows,
                provider_plans.PackageManagerState(
                    "winget",
                    "C:\\Windows\\Temp\\..\\System32\\winget.exe",
                    "host",
                    "arm64",
                ),
                provider_plans.PackageManagerState(
                    "winget",
                    "c:/windows/system32/winget.exe",
                    "host",
                    "x86_64",
                ),
            ),
        )
        for capability_state, first_path, second_path in dot_segment_conflicts:
            with self.subTest(platform=capability_state.machine.platform), self.assertRaisesRegex(
                provider_plans.PlanningError, "conflicting"
            ):
                provider_plans.generate_provider_plan(
                    (capability_state,),
                    ("poppler",),
                    package_managers=(first_path, second_path),
                )

    def test_equivalent_manager_architecture_aliases_are_deduplicated(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH, machine, locator=lambda probe, machine: None
        )
        arm64 = provider_plans.PackageManagerState(
            "brew", "/opt/homebrew/bin/brew", "host", "arm64"
        )
        aarch64 = provider_plans.PackageManagerState(
            "brew", "/opt/homebrew/bin/brew", "host", "aarch64"
        )
        plan = provider_plans.generate_provider_plan(
            (state,), ("bash",), package_managers=(arm64, aarch64)
        )
        self.assertEqual(plan.actions[0].manager_state, arm64)

    def test_macos_missing_bash_does_not_bootstrap_homebrew(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH, machine, locator=lambda probe, machine: None
        )
        with self.assertRaisesRegex(provider_plans.PlanningError, "no supported provider plan"):
            provider_plans.generate_provider_plan(
                (state,), ("bash",), package_managers=()
            )

    def test_unsupported_unknown_and_unplannable_requests_fail(self):
        unsupported = self.state(capabilities.POPPLER, "Plan9")
        absent = self.state(capabilities.POPPLER)
        with self.assertRaisesRegex(provider_plans.PlanningError, "unsupported"):
            provider_plans.generate_provider_plan((unsupported,), ("poppler",), package_managers=(self.manager("apt"),))
        with self.assertRaisesRegex(provider_plans.PlanningError, "no detected state"):
            provider_plans.generate_provider_plan((), ("poppler",), package_managers=(self.manager("apt"),))
        with self.assertRaisesRegex(provider_plans.PlanningError, "no supported provider plan"):
            provider_plans.generate_provider_plan((absent,), ("poppler",), package_managers=())

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
            package_managers=(self.manager("winget"),),
            native_provisioning=("bash",),
        )
        self.assertEqual(plan.actions[0].displaces_verified_paths, ("C:/Git/bin/bash.exe",))
        self.assertIn("explicit native-provisioning override", plan.actions[0].reason)
        self.assertEqual(plan.actions[0].target_architecture, "arm64")
        self.assertEqual(plan.actions[0].commands[0][-2:], ("--architecture", "arm64"))

    def test_native_override_reuses_native_and_rejects_unrequested_capability(self):
        machine = capabilities.MachineState("Windows", "x86_64")
        native = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, machine: (
                "C:/tools/bash.exe"
                if probe.locator_strategy == "git-bash"
                else None
            ),
            version_reader=lambda probe, path: "GNU bash 5.2",
            architecture_reader=lambda probe, path: "x86_64",
        )
        plan = provider_plans.generate_provider_plan(
            (native,),
            ("bash",),
            package_managers=(self.manager("winget"),),
            native_provisioning=("bash",),
        )
        self.assertEqual(plan.actions, ())
        with self.assertRaisesRegex(provider_plans.PlanningError, "was not requested"):
            provider_plans.generate_provider_plan(
                (native,), ("bash",), package_managers=(self.manager("winget"),), native_provisioning=("poppler",)
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
                (state,), ("bash",), package_managers=(self.manager("winget"),), native_provisioning=("bash",)
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
                    package_managers=(self.manager("winget"),),
                    native_provisioning=("bash",),
                )

    def test_native_override_rejects_relative_displaced_provider_path(self):
        machine = capabilities.MachineState("Windows", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, machine: (
                ".\\bash.exe" if probe.locator_strategy == "git-bash" else None
            ),
            version_reader=lambda probe, path: "GNU bash 5.2",
            architecture_reader=lambda probe, path: "x86_64",
        )
        with self.assertRaisesRegex(provider_plans.PlanningError, "absolute verified"):
            provider_plans.generate_provider_plan(
                (state,),
                ("bash",),
                package_managers=(self.manager("winget"),),
                native_provisioning=("bash",),
            )

    def test_native_override_rejects_translated_homebrew_fallback(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, machine: (
                "/usr/local/bin/bash"
                if probe.locator_strategy == "homebrew-bash"
                else None
            ),
            version_reader=lambda probe, path: "GNU bash 5.2",
            architecture_reader=lambda probe, path: "x86_64",
        )
        translated = provider_plans.PackageManagerState(
            "brew", "/usr/local/bin/brew", "host", "x86_64"
        )
        with self.assertRaisesRegex(
            provider_plans.PlanningError, "no supported provider plan"
        ):
            provider_plans.generate_provider_plan(
                (state,),
                ("bash",),
                package_managers=(translated,),
                native_provisioning=("bash",),
                translated_manager_fallbacks=(translated,),
            )

    def test_native_override_reuses_another_existing_native_provider(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, machine: (
                "/bin/bash"
                if probe.locator_strategy == "system-bash"
                else "/opt/homebrew/bin/bash"
                if probe.locator_strategy == "homebrew-bash"
                else None
            ),
            version_reader=lambda probe, path: "GNU bash 5.2",
            architecture_reader=lambda probe, path: (
                "x86_64" if path == "/bin/bash" else "arm64"
            ),
        )
        plan = provider_plans.generate_provider_plan(
            (state,),
            ("bash",),
            package_managers=(self.manager("brew"),),
            native_provisioning=("bash",),
        )
        self.assertEqual(plan.actions, ())

    def test_plan_rejects_system_and_homebrew_bash_at_same_identity(self):
        machine = capabilities.MachineState("Darwin", "arm64")
        state = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, machine: (
                "/bin/bash"
                if probe.locator_strategy == "system-bash"
                else "/opt/homebrew/bin/bash"
                if probe.locator_strategy == "homebrew-bash"
                else None
            ),
            version_reader=lambda probe, path: "GNU bash 5.2",
            architecture_reader=lambda probe, path: "arm64",
        )
        homebrew_index = next(
            index
            for index, provider in enumerate(state.providers)
            if provider.provider.provider_id == "homebrew-bash"
        )
        homebrew = state.providers[homebrew_index]
        contradictory = replace(
            homebrew,
            executables=(replace(homebrew.executables[0], path="/bin/bash"),),
        )
        providers = list(state.providers)
        providers[homebrew_index] = contradictory
        contradictory_state = replace(state, providers=tuple(providers))
        with self.assertRaisesRegex(
            provider_plans.PlanningError, "conflicting provider evidence"
        ):
            provider_plans.generate_provider_plan(
                (contradictory_state,), ("bash",), package_managers=()
            )

    def test_duplicate_detected_states_are_ambiguous(self):
        state = self.state(capabilities.POPPLER)
        with self.assertRaisesRegex(provider_plans.PlanningError, "duplicate detected"):
            provider_plans.generate_provider_plan(
                (state, state), ("poppler",), package_managers=(self.manager("apt"),)
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
                    (baseline, other),
                    ("poppler", "ghostscript"),
                    package_managers=(self.manager("apt"), self.manager("brew")),
                )

    def test_equivalent_architecture_aliases_share_canonical_context(self):
        poppler = capabilities.detect_capability(
            capabilities.POPPLER,
            capabilities.MachineState("Windows", "AMD64", "host"),
            locator=lambda probe, machine: None,
        )
        ghostscript = capabilities.detect_capability(
            capabilities.GHOSTSCRIPT,
            capabilities.MachineState("Windows", "x86_64", "host"),
            locator=lambda probe, machine: None,
        )
        plan = provider_plans.generate_provider_plan(
            (poppler, ghostscript),
            ("poppler", "ghostscript"),
            package_managers=(self.manager("winget"),),
        )
        self.assertEqual(
            plan.context, capabilities.MachineState("Windows", "x86_64", "host")
        )

    def test_irrelevant_observations_do_not_change_plan_context(self):
        requested = self.state(capabilities.POPPLER)
        irrelevant = self.state(capabilities.GHOSTSCRIPT, "Darwin")
        plan = provider_plans.generate_provider_plan(
            (requested, irrelevant, irrelevant), ("poppler",), package_managers=(self.manager("apt"),)
        )
        self.assertEqual(plan.context, requested.machine)

    def test_winget_uses_manager_specific_x64_token(self):
        command = provider_plans.adapter_commands(
            "winget", "Git.Git", target_architecture="x86_64"
        )[0]
        self.assertEqual(command[-2:], ("--architecture", "x64"))

    def test_non_winget_native_replacement_does_not_use_winget_architectures(self):
        machine = capabilities.MachineState("Linux", "ppc64le")
        state = capabilities.detect_capability(
            capabilities.BASH,
            machine,
            locator=lambda probe, machine: (
                "/usr/bin/bash" if probe.locator_strategy == "system-bash" else None
            ),
            version_reader=lambda probe, path: "GNU bash 5.2",
            architecture_reader=lambda probe, path: "x86_64",
        )
        plan = provider_plans.generate_provider_plan(
            (state,),
            ("bash",),
            package_managers=(self.manager("apt"),),
            native_provisioning=("bash",),
        )
        action = plan.actions[0]
        self.assertEqual(action.target_architecture, "ppc64le")
        self.assertEqual(action.manager, "apt")
        self.assertEqual(
            action.commands,
            (("/usr/bin/apt-get", "update"), ("/usr/bin/apt-get", "install", "-y", "bash")),
        )

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
                (state,), ("custom",), package_managers=(self.manager("apt"),)
            )

    def test_aggregate_capability_availability_must_match_provider_states(self):
        available = self.state(capabilities.POPPLER, available=True)
        absent = self.state(capabilities.POPPLER)
        contradictions = (
            capabilities.CapabilityState(
                available.capability,
                available.machine,
                capabilities.Availability.ABSENT,
                available.providers,
            ),
            capabilities.CapabilityState(
                absent.capability,
                absent.machine,
                capabilities.Availability.AVAILABLE,
                absent.providers,
            ),
        )
        for state in contradictions:
            with self.subTest(availability=state.availability), self.assertRaisesRegex(
                provider_plans.PlanningError, "availability contradicts"
            ):
                provider_plans.generate_provider_plan(
                    (state,), ("poppler",), package_managers=(self.manager("apt"),)
                )

    def test_provider_availability_must_match_any_and_all_probe_evidence(self):
        cases = (
            (capabilities.POPPLER, capabilities.ProbePolicy.ALL),
            (capabilities.GHOSTSCRIPT, capabilities.ProbePolicy.ANY),
        )
        for capability, policy in cases:
            detected = self.state(capability)
            provider = detected.providers[0]
            self.assertEqual(provider.provider.probe_policy, policy)
            contradictory_provider = capabilities.ProviderState(
                provider.provider,
                capabilities.Availability.AVAILABLE,
                provider.executables,
            )
            contradictory = capabilities.CapabilityState(
                detected.capability,
                detected.machine,
                capabilities.Availability.AVAILABLE,
                (contradictory_provider, *detected.providers[1:]),
            )
            with self.subTest(policy=policy), self.assertRaisesRegex(
                provider_plans.PlanningError,
                "provider availability contradicts executable evidence",
            ):
                provider_plans.generate_provider_plan(
                    (contradictory,),
                    (capability.capability_id,),
                    package_managers=(self.manager("apt"),),
                )

    def test_valid_absolute_manager_paths_follow_plan_platform(self):
        linux = self.state(capabilities.POPPLER)
        windows = self.state(capabilities.POPPLER, "Windows")
        linux_plan = provider_plans.generate_provider_plan(
            (linux,), ("poppler",), package_managers=(self.manager("apt"),)
        )
        windows_plan = provider_plans.generate_provider_plan(
            (windows,), ("poppler",), package_managers=(self.manager("winget"),)
        )
        self.assertEqual(linux_plan.actions[0].commands[0][0], "/usr/bin/apt-get")
        self.assertEqual(
            windows_plan.actions[0].commands[0][0],
            "C:/Windows/System32/winget.exe",
        )

    def test_irrelevant_manager_translation_is_not_reported_as_fallback(self):
        machine = capabilities.MachineState("Windows", "arm64")
        state = capabilities.detect_capability(
            capabilities.POPPLER, machine, locator=lambda probe, machine: None
        )
        translated_winget = provider_plans.PackageManagerState(
            "winget",
            "C:/Windows/System32/winget.exe",
            "host",
            "x86_64",
        )
        plan = provider_plans.generate_provider_plan(
            (state,), ("poppler",), package_managers=(translated_winget,)
        )
        self.assertNotIn("translated package-manager fallback", plan.actions[0].reason)


if __name__ == "__main__":
    unittest.main()
