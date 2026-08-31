#!/usr/bin/env python3
"""Thin CLI wrapper so `python scripts/generate_dataset.py ...` works from repo root,
matching the exact command in the spec (section 15 / section 44)."""
import os
import runpy

_target = os.path.join(os.path.dirname(__file__), "..", "data", "generators", "generate_dataset.py")
runpy.run_path(_target, run_name="__main__")
