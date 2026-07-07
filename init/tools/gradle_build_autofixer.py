#!/usr/bin/env python3
"""Compatibility wrapper for the canonical Gradle patcher."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

TOOL = Path(__file__).with_name("gradle_patcher.py")
if not TOOL.exists():
    raise SystemExit(f"missing canonical Gradle patcher: {TOOL}")

sys.argv[0] = str(TOOL)
runpy.run_path(str(TOOL), run_name="__main__")
