"""Verify optional-document transitions from a published wheel or PyPI request."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import os

from check_document_lifecycle import Host, PACKAGE, direct
from check_release_lifecycle import wheel_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--wheel', type=Path)
    source.add_argument('--pypi-version')
    parser.add_argument('--python', default='3.13')
    parser.add_argument('--allow-home-config-mutation', action='store_true')
    args = parser.parse_args()
    wheel = args.wheel.resolve() if args.wheel else None
    if wheel:
        name, version = wheel_identity(wheel)
        assert name == PACKAGE, name
    else:
        version = args.pypi_version
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        parser.error('expected a three-component release version')
    if tuple(map(int, version.split('.'))) < (0, 2, 0):
        print('Legacy release: optional documents do not exist; historical smoke covers its mandatory stack.')
        return 0
    with TemporaryDirectory(prefix='agent-tools-published-documents-') as temporary:
        host = Host(Path(temporary) / 'host', args.python, args.allow_home_config_mutation)
        def requirement(documents):
            return direct(wheel, documents) if wheel else f"{PACKAGE}{'[documents]' if documents else ''}=={version}"
        try:
            host.install(requirement(False))
            host.assert_shape(version, False)
            host.seed()
            host.integration(True)
            host.install(requirement(True))
            host.assert_shape(version, True)
            # Exact published pin/source reconciliation, not a version upgrade claim.
            host.uv('upgrade', PACKAGE)
            host.assert_shape(version, True)
            host.install(requirement(True))
            host.assert_shape(version, True)
            host.install(requirement(False))
            host.assert_shape(version, False)
            host.uv('uninstall', PACKAGE)
            assert not os.path.lexists(host.executable) and not host.tool.exists()
            host.preserved()
            print(f'Artifact documents lifecycle passed: {version}; source={"wheel" if wheel else "PyPI"}')
        finally:
            host.clean()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
