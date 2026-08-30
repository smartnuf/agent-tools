#!/usr/bin/env python3
"""Run the source-tree Python selector before the project environment exists."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_tools.python_selection import main  # noqa: E402


raise SystemExit(main())
