"""Real hosted-provider evidence, using the installed artifact's isolated Python."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from email.parser import BytesParser
import importlib.metadata
import json
import os
import runpy
from pathlib import Path
import subprocess
import sys
import traceback
from zipfile import ZipFile

import agent_tools
from agent_tools import capabilities, desired_state, managed_state, native_setup, provider_execution


def encode(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(type(value).__name__)


def write(root, name, value):
    path = root / (name + ".json")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, default=encode)
        stream.write("\n")


def snapshot(names):
    machine = capabilities.current_machine()
    states = capabilities.detect_capabilities([capabilities.get_capability(name) for name in names], machine)
    return {"machine": asdict(machine), "python": sys.version, "python_executable": sys.executable,
            "package": agent_tools.__file__, "version": agent_tools.__version__,
            "capabilities": {state.capability.capability_id: {
                "availability": state.availability.value,
                "providers": [asdict(provider) for provider in state.providers],
            } for state in states}}


def validate_mutation_records(records, expected, manager):
    # The production reader validates schema and command/verification consistency;
    # this oracle additionally demands actual successful requests for this test.
    assert len(records) == len(expected)
    assert {record["capability_id"] for record in records} == set(expected)
    for record in records:
        assert record["ownership"] is False
        assert record["verification"]["outcome"] == "succeeded"
        assert record["verification"]["verified_paths"]
        assert record["package_manager"]["name"] == manager
        assert record["command_evidence"]
        assert all(command["returncode"] == 0 for command in record["command_evidence"])


def rediscovery_environment():
    environment = dict(os.environ)
    if os.name == "nt":
        environment["PATH"] = provider_execution._windows_persisted_path()
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    read_only = parser.add_mutually_exclusive_group()
    read_only.add_argument("--snapshot", nargs="+")
    read_only.add_argument("--capture-after", type=Path)
    parser.add_argument("--fixture-outcome", default="unknown")
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manager")
    parser.add_argument("--allow-provider-mutation", action="store_true")
    parser.add_argument("capabilities", nargs="*")
    args = parser.parse_args()
    if args.capture_after:
        # This separate recorder process uses the same installed refresh policy
        # as rediscovery/repeat; no persistent or parent PATH is changed.
        os.environ.update(rediscovery_environment())
        recorder = Path(__file__).with_name("capture_native_evidence.py")
        sys.argv = [str(recorder), "--phase", "after", "--evidence-class", "native-mutation-observation",
                    "--fixture-outcome", args.fixture_outcome, "--output", str(args.capture_after)]
        runpy.run_path(str(recorder), run_name="__main__")
        return 0
    if args.snapshot:
        print(json.dumps(snapshot(args.snapshot), default=encode))
        return 0
    if not (args.allow_provider_mutation and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"):
        parser.error("mutation evidence requires explicit authorization on a disposable GitHub-hosted runner")
    if not all((args.executable, args.wheel, args.output, args.manager, args.capabilities)):
        parser.error("provide executable, wheel, output, manager and named capabilities")
    checkout = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    if Path.cwd().is_relative_to(checkout) or Path(agent_tools.__file__).resolve().is_relative_to(checkout):
        parser.error("run the installed artifact outside the checkout with isolated Python")
    args.output.mkdir(parents=True, exist_ok=False)
    owned_state = False
    try:
        with ZipFile(args.wheel) as archive:
            metadata_files = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            assert len(metadata_files) == 1
            metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
        assert metadata["Name"] == "smartnuf-agent-tools"
        assert metadata["Version"] == importlib.metadata.version("smartnuf-agent-tools") == agent_tools.__version__
        write(args.output, "artifact", {"wheel": args.wheel.name, "version": metadata["Version"],
              "sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
              "checkout_sha": os.environ.get("GITHUB_SHA")})
        before = snapshot(args.capabilities)
        write(args.output, "before", before)
        machine = capabilities.current_machine()
        desired = desired_state.desired_state_path(platform_name=machine.platform)
        managed = managed_state.managed_state_path(platform_name=machine.platform)
        roots = set((desired.parent, managed.parent))
        if any(os.path.lexists(path) for path in roots):
            raise AssertionError("pre-existing Agent Tools state must be preserved")
        owned_state = True
        unsatisfied = [name for name, state in before["capabilities"].items() if state["availability"] != "available"]
        write(args.output, "coverage", {"unsatisfied": unsatisfied,
              "already_satisfied": [name for name in args.capabilities if name not in unsatisfied]})
        if not unsatisfied:
            raise AssertionError("coverage gap: image has no unsatisfied target; no mutation credit")

        def command(label, *operands, environment=None):
            # M3 owns manager deadlines, cancellation and provenance finalization.
            # Do not kill that cleanup owner with a second parent-only timeout.
            # The explicit CI step/job limits remain infrastructure backstops;
            # their cancellation is incomplete evidence, never mutation success.
            result = subprocess.run([str(args.executable), *operands],
                                    stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, env=environment)
            write(args.output, label, {"argv": operands, "returncode": result.returncode,
                                      "stdout": result.stdout, "stderr": result.stderr})
            print(result.stdout, flush=True)
            assert result.returncode == 0, (label, result.stderr)
            return result.stdout

        command("dry-run", "install", *args.capabilities, "--dry-run")
        assert not any(os.path.lexists(path) for path in roots)
        plan = native_setup.build_install_plan(args.capabilities)
        write(args.output, "plan", asdict(plan))
        assert {action.capability_id for action in plan.actions} == set(unsatisfied)
        assert all(action.manager == args.manager for action in plan.actions)
        command("install", "install", *args.capabilities, "--allow-provider-mutation")
        records = managed_state.load_document(managed)
        write(args.output, "provenance", records)
        validate_mutation_records(records["records"], unsatisfied, args.manager)
        original = managed.read_bytes()
        refreshed = rediscovery_environment()
        fresh = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve()), "--snapshot", *args.capabilities],
                               capture_output=True, text=True, check=True, timeout=60, env=refreshed)
        after = json.loads(fresh.stdout)
        write(args.output, "after", after)
        assert all(state["availability"] == "available" for state in after["capabilities"].values())
        repeated = command("repeat", "install", *args.capabilities, environment=refreshed)
        assert "no host changes required" in repeated and "    command:" not in repeated
        assert "Managed provenance: not-required" in repeated
        assert managed.read_bytes() == original and not os.path.lexists(desired)
        write(args.output, "result", {"status": "passed", "mutated_capabilities": unsatisfied})
        return 0
    except Exception:
        write(args.output, "failure", {"traceback": traceback.format_exc()})
        # Never export a pre-existing user's state after refusing the fixture.
        if owned_state and os.path.lexists(managed):
            try:
                observed = {"document": managed_state.load_document(managed)}
            except Exception as error:
                observed = {"reader_error": str(error)}
            write(args.output, "failure-provenance", observed)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
