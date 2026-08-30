"""Report repeatable selection evidence from an already-bootstrapped runner."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path

from agent_tools import capabilities
from agent_tools import python_selection


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument(
        "--allow-translated",
        action="store_true",
        help="explicitly authorize a translated fallback for this evidence run",
    )
    parser.add_argument("--capabilities-only", action="store_true")
    parser.add_argument("--require-native", action="store_true")
    parser.add_argument("--require-system-native-python", action="store_true")
    args = parser.parse_args()

    first_host = first_candidates = first = None
    if not args.capabilities_only:
        first_host, first_candidates, first = python_selection.discover_verify_select(
            allow_translated=args.allow_translated
        )
        second_host, second_candidates, second = python_selection.discover_verify_select(
            allow_translated=args.allow_translated
        )

        if first_host != second_host or first != second or first_candidates != second_candidates:
            raise AssertionError("repeated read-only Python selection changed its result")
        python_selection.verify_final_environment(sys.executable, first)
        if args.require_system_native_python and (
            first.mechanism is not python_selection.ProviderMechanism.SYSTEM
            or first.native_status(first_host) is not python_selection.NativeStatus.NATIVE
        ):
            raise AssertionError("pre-seeded native system Python was not selected")

    first_capabilities = capabilities.detect_capabilities()
    second_capabilities = capabilities.detect_capabilities()
    def snapshot(states: tuple[capabilities.CapabilityState, ...]) -> tuple[object, ...]:
        return tuple(
            (
                state.capability.capability_id,
                state.availability.value,
                state.selected_provider.provider.provider_id
                if state.selected_provider is not None
                else None,
                tuple(
                    item.path
                    for provider in state.providers
                    for item in provider.executables
                    if item.verified
                ),
            )
            for state in states
        )

    if snapshot(first_capabilities) != snapshot(second_capabilities):
        raise AssertionError("repeated read-only capability selection changed its result")

    by_id = {state.capability.capability_id: state for state in first_capabilities}
    bash_provider = by_id["bash"].selected_provider
    expected_bash = "git-bash" if sys.platform == "win32" else "system-bash"
    if bash_provider is None or bash_provider.provider.provider_id != expected_bash:
        raise AssertionError(f"pre-seeded {expected_bash} was not selected")
    if args.require_native:
        for capability_id, provider_id in (
            ("poppler", "host-poppler"),
            ("ghostscript", "host-ghostscript"),
        ):
            provider = by_id[capability_id].selected_provider
            if provider is None or provider.provider.provider_id != provider_id:
                raise AssertionError(f"pre-seeded {provider_id} was not selected")

    python_report = None
    host_report = None
    if first is not None and first_host is not None and first_candidates is not None:
        host_report = {
            "platform": first_host.platform,
            "architecture": first_host.architecture,
            "process_architecture": first_host.process_architecture,
            "process_translated": first_host.process_translated,
            "execution_environment": first_host.execution_environment,
        }
        python_report = {
            "path": str(Path(first.path)),
            "architecture": first.architecture,
            "mechanism": first.mechanism.value,
            "native_status": first.native_status(first_host).value,
            "version": ".".join(str(part) for part in first.version),
        }

    print(
        json.dumps(
            {
                "host": host_report,
                "selected_python": python_report,
                "translated_fallback_authorized": args.allow_translated,
                "candidate_count": len(first_candidates) if first_candidates is not None else None,
                "capabilities": {
                    state.capability.capability_id: state.availability.value
                    for state in first_capabilities
                },
                "provider_install_actions": 0,
                "required_native_providers": args.require_native,
                "required_system_native_python": args.require_system_native_python,
                "hosted_arm64_claim": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
