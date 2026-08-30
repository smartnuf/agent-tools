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
    args = parser.parse_args()

    first_host, first_candidates, first = python_selection.discover_verify_select(
        allow_translated=args.allow_translated
    )
    second_host, second_candidates, second = python_selection.discover_verify_select(
        allow_translated=args.allow_translated
    )

    if first_host != second_host or first != second or first_candidates != second_candidates:
        raise AssertionError("repeated read-only Python selection changed its result")
    python_selection.verify_final_environment(sys.executable, first)

    first_capabilities = capabilities.detect_capabilities()
    second_capabilities = capabilities.detect_capabilities()
    if first_capabilities != second_capabilities:
        raise AssertionError(
            "repeated read-only capability discovery changed its result: "
            f"{first_capabilities!r} != {second_capabilities!r}"
        )

    print(
        json.dumps(
            {
                "host": {
                    "platform": first_host.platform,
                    "architecture": first_host.architecture,
                    "process_architecture": first_host.process_architecture,
                    "process_translated": first_host.process_translated,
                    "execution_environment": first_host.execution_environment,
                },
                "selected_python": {
                    "path": str(Path(first.path)),
                    "architecture": first.architecture,
                    "mechanism": first.mechanism.value,
                    "native_status": first.native_status(first_host).value,
                    "version": ".".join(str(part) for part in first.version),
                },
                "translated_fallback_authorized": args.allow_translated,
                "candidate_count": len(first_candidates),
                "capabilities": {
                    state.capability.capability_id: state.availability.value
                    for state in first_capabilities
                },
                "provider_install_actions": 0,
                "hosted_arm64_claim": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
