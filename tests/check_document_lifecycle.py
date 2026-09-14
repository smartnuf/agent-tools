"""Real-artifact document migrations and separately labelled upgrade fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

from check_document_installs import DOCUMENT_DISTRIBUTIONS
from check_release_lifecycle import PACKAGE, CONSOLE_SCRIPT, run_command, wheel_identity, write_simple_index

ROOT = Path(__file__).resolve().parents[1]


def direct(wheel: Path, documents: bool = False) -> str:
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    return f"{PACKAGE}{'[documents]' if documents else ''} @ {wheel.as_uri()}#sha256={digest}"


def tree_snapshot(roots: list[Path]) -> dict[Path, bytes | None]:
    result = {}
    for root in roots:
        if root.is_symlink():
            raise AssertionError(f"unexpected state symlink: {root}")
        if root.exists():
            result[root] = None
            for path in sorted(root.rglob('*')):
                if path.is_symlink():
                    raise AssertionError(f"unexpected state symlink: {path}")
                result[path] = None if path.is_dir() else path.read_bytes()
    return result


class Host:
    def __init__(self, root: Path, python: str, home_authorized: bool):
        self.root = root
        root.mkdir()
        self.python = python
        self.home_authorized = home_authorized
        self.env = dict(os.environ, UV_TOOL_DIR=str(root / 'tools'),
                        UV_TOOL_BIN_DIR=str(root / 'bin'),
                        XDG_CONFIG_HOME=str(root / 'config'),
                        XDG_STATE_HOME=str(root / 'state'),
                        LOCALAPPDATA=str(root / 'local'),
                        CLAUDE_CONFIG_DIR=str(root / 'claude'))
        self.executable = root / 'bin' / CONSOLE_SCRIPT
        self.tool = root / 'tools' / PACKAGE
        self.interpreter = self.tool / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.roots: list[Path] = []
        self.owned_roots: list[Path] = []
        self.snapshot: dict[Path, bytes | None] = {}
        self.bash = shutil.which('bash')
        if self.bash is None:
            raise AssertionError('external Bash is required on the disposable host')
        self.bash_version = self.command([self.bash, '--version']).stdout

    def command(self, argv, codes=frozenset({0})):
        return run_command([str(item) for item in argv], environment=self.env,
                           cwd=self.root, expected_return_codes=codes)

    def uv(self, *argv, codes=frozenset({0})):
        return self.command(['uv', '--no-config', 'tool', *argv], codes)

    def install(self, requirement: str, *options):
        self.uv('install', '--python', self.python, '--reinstall', *options, requirement)

    def evaluate(self, code: str):
        return json.loads(self.command([self.interpreter, '-I', '-c', code]).stdout)

    def inventory(self):
        return self.evaluate("import json,importlib.metadata as m; print(json.dumps({d.metadata['Name'].lower():d.version for d in m.distributions()}))")

    def assert_shape(self, version: str, documents: bool, *, legacy=False):
        inventory = self.inventory()
        assert inventory[PACKAGE] == version, inventory
        if documents:
            assert DOCUMENT_DISTRIBUTIONS.issubset(inventory), inventory
        else:
            assert inventory == {PACKAGE: version}, inventory
        output = self.command([self.executable, '--version']).stdout.strip()
        assert output == f'agent-tools {version}', output
        doctor = self.command([self.executable, 'doctor'], frozenset({0, 1}))
        assert 'Traceback' not in doctor.stderr
        if documents:
            assert 'import failed' not in doctor.stdout, doctor.stdout
        if not legacy:
            explicit = self.command([self.executable, 'doctor', '--documents'], frozenset({0, 1}))
            if documents:
                assert explicit.returncode == doctor.returncode
                assert 'documents: all library checks passed' in explicit.stdout
            else:
                assert explicit.returncode == 1
                assert 'documents: 7 library check(s)' in explicit.stdout
        self.preserved()

    def seed(self):
        paths = self.evaluate("from agent_tools.desired_state import desired_state_path; from agent_tools.managed_state import managed_state_path; import json; print(json.dumps([str(desired_state_path()),str(managed_state_path())]))")
        config, managed = map(Path, paths)
        self.roots = list(dict.fromkeys([config.parent, managed.parent]))
        if platform.system() == 'Darwin' and not self.home_authorized:
            raise AssertionError('macOS lifecycle requires --allow-home-config-mutation')
        for root in self.roots:
            if os.path.lexists(root):
                raise AssertionError(f'refusing pre-existing lifecycle state root: {root}')
        self.owned_roots = list(self.roots)
        self.command([self.executable, 'tools', 'enable', 'bash', '--allow-config-mutation'])
        managed.parent.mkdir(parents=True, exist_ok=True)
        managed.write_text(json.dumps({'schema_version': 1, 'records': [],
                                      'lifecycle_preservation_marker': 'keep this metadata'})+'\n')
        # Validate the seeded state through the installed production reader.
        self.evaluate("from agent_tools.managed_state import load_document,managed_state_path; import json; print(json.dumps(load_document(managed_state_path())))")
        if os.name == 'nt':
            settings = self.root / 'claude' / 'settings.json'
            settings.parent.mkdir()
            settings.write_text('{"unrelated": {"preserve": true}}\n')
            self.roots.append(settings.parent)
        self.freeze()

    def freeze(self):
        self.snapshot = tree_snapshot(self.roots)

    def preserved(self):
        assert tree_snapshot(self.roots) == self.snapshot, 'user state or backups changed'
        assert shutil.which('bash', path=self.env.get('PATH')) == self.bash
        assert self.command([self.bash, '--version']).stdout == self.bash_version

    def integration(self, apply: bool):
        if os.name != 'nt':
            return
        self.preserved()
        self.command([self.executable, 'integrations', 'claude-code',
                      'apply' if apply else 'remove', '--allow-config-mutation'])
        if not apply:
            settings = json.loads((self.root / 'claude' / 'settings.json').read_text())
            assert settings == {'unrelated': {'preserve': True}}, settings
        self.freeze()

    def clean(self):
        # Private temporary roots are removed by the caller. Only macOS state
        # escapes that root; delete it only after byte/directory preservation.
        if platform.system() == 'Darwin' and self.owned_roots:
            if tree_snapshot(self.roots) != self.snapshot:
                raise AssertionError('preserving changed macOS state for inspection')
            for root in self.owned_roots:
                if root.exists():
                    shutil.rmtree(root)


def migration(previous: Path, current: Path, candidate: Path, root: Path,
              python: str, home_authorized: bool, source: str, documents: bool):
    version = wheel_identity(candidate)[1]
    host = Host(root, python, home_authorized)
    try:
        host.install(direct(candidate))
        host.seed()
        index = root / 'index'
        if source == 'github':
            host.install(direct(previous))
            host.assert_shape(wheel_identity(previous)[1], True, legacy=True)
            write_simple_index(index, (current, candidate))
        else:
            write_simple_index(index, (current,))
            host.install(PACKAGE, '--index', index.as_uri())
            host.assert_shape(wheel_identity(current)[1], True, legacy=True)
            write_simple_index(index, (current, candidate))
        request = PACKAGE + ('[documents]' if documents else '')
        if source == 'pypi' and not documents:
            host.uv('upgrade', PACKAGE, '--index', index.as_uri())
        else:
            host.uv('install', '--python', python, '--upgrade', '--index', index.as_uri(), request)
        host.assert_shape(version, documents)
        host.integration(True)
        host.install(f'{request}=={version}', '--index', index.as_uri())
        host.assert_shape(version, documents)
        before_inventory = host.inventory()
        receipt = host.tool / 'uv-receipt.toml'
        before_receipt = receipt.read_bytes()
        host.uv('install', '--reinstall', '--no-index', '--find-links', index / PACKAGE,
                f'{PACKAGE}[documents]==9999.0.0', codes=frozenset({1}))
        assert receipt.read_bytes() == before_receipt
        assert host.inventory() == before_inventory
        host.assert_shape(version, documents)
        host.install(f'{PACKAGE}[documents]=={version}', '--index', index.as_uri())
        host.assert_shape(version, True)
        host.install(f'{PACKAGE}=={version}', '--index', index.as_uri())
        host.assert_shape(version, False)
        # Restore explicitly while the modern command exists, before rollback.
        host.integration(False)
        host.install(f'{PACKAGE}=={wheel_identity(current)[1]}', '--index', index.as_uri())
        host.assert_shape(wheel_identity(current)[1], True, legacy=True)
        host.install(direct(previous))
        host.assert_shape(wheel_identity(previous)[1], True, legacy=True)
        host.uv('uninstall', PACKAGE)
        assert not os.path.lexists(host.executable) and not host.tool.exists()
        host.preserved()
        print(f'REAL ARTIFACT migration passed: {source} -> {version} documents={documents}', flush=True)
    finally:
        host.clean()


def fixture_upgrade(candidate: Path, root: Path, python: str):
    """A source-version fixture, never a claim of a prior document release."""
    version = wheel_identity(candidate)[1]
    fixture_version = version + '.dev0'
    project = root / 'source-fixture'
    project.mkdir(parents=True)
    # This supplemental fixture uses current source, not altered release bytes.
    shutil.copytree(ROOT / 'src', project / 'src', ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('pyproject.toml', 'README.md', 'LICENSE'):
        shutil.copy2(ROOT / name, project / name)
    (project / 'src/agent_tools/__init__.py').write_text(f'__version__ = "{fixture_version}"\n')
    subprocess.run(['uv', 'build', '--project', str(project), '--wheel', '--out-dir', str(root / 'fixture-dist')], check=True, timeout=300)
    fixture, = (root / 'fixture-dist').glob('*.whl')
    index = root / 'fixture-index'
    write_simple_index(index, (fixture,))
    host = Host(root / 'fixture-host', python, False)
    host.install(PACKAGE+'[documents]', '--index', index.as_uri(), '--prerelease', 'allow')
    host.assert_shape(fixture_version, True)
    write_simple_index(index, (fixture, candidate))
    host.uv('upgrade', PACKAGE, '--index', index.as_uri())
    host.assert_shape(version, True)
    receipt = (host.tool / 'uv-receipt.toml').read_text()
    assert 'extras = ["documents"]' in receipt, receipt
    host.uv('uninstall', PACKAGE)
    print(f'SOURCE FIXTURE ONLY: extra retained across {fixture_version} -> {version}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-wheel', required=True, type=Path)
    parser.add_argument('--current-wheel', required=True, type=Path)
    parser.add_argument('--candidate-wheel', required=True, type=Path)
    parser.add_argument('--python', default='3.13')
    parser.add_argument('--allow-home-config-mutation', action='store_true')
    args = parser.parse_args()
    previous, current, candidate = [p.resolve() for p in (args.previous_wheel, args.current_wheel, args.candidate_wheel)]
    assert wheel_identity(previous) == (PACKAGE, '0.1.1')
    assert wheel_identity(current) == (PACKAGE, '0.1.2')
    assert wheel_identity(candidate)[0] == PACKAGE
    assert wheel_identity(candidate)[1] not in {'0.1.1', '0.1.2'}
    with TemporaryDirectory(prefix='agent-tools-lifecycle-') as temporary:
        root = Path(temporary)
        for source in ('github', 'pypi'):
            for documents in (False, True):
                migration(previous, current, candidate, root / f'{source}-{documents}',
                          args.python, args.allow_home_config_mutation, source, documents)
        fixture_upgrade(candidate, root, args.python)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
