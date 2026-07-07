#!/usr/bin/env python3
"""Compatibility alias for patcher_file_replacement.py."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

TOOL = Path(__file__).with_name("patcher_file_replacement.py")
if not TOOL.exists():
    raise SystemExit(f"missing canonical file replacement patcher: {TOOL}")

sys.argv[0] = str(TOOL)
runpy.run_path(str(TOOL), run_name="__main__")
