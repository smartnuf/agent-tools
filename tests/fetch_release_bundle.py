"""Download a GitHub release bundle and verify its published checksum manifest."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from release import verify_checksums


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag')
    parser.add_argument('directory', type=Path)
    parser.add_argument('--repository', default='smartnuf/agent-tools')
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=False)
    subprocess.run(['gh', 'release', 'download', args.tag, '--repo', args.repository,
                    '--dir', str(args.directory), '--pattern', '*.whl',
                    '--pattern', '*.tar.gz', '--pattern', 'SHA256SUMS'],
                   check=True, timeout=180)
    verify_checksums(args.directory / 'SHA256SUMS')
    print(f'Published bundle checksums verified: {args.tag}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
