#!/usr/bin/env python
"""Rotate benchmark: build N torus objects, rotate them all 30° about Y,
then do a full redraw (re-mesh + re-bbox every object). Prints a table of
wall-clock time per phase with a per-object (µs) column.

Uses the branch's native path: Scene.set_transforms (carry-transforms) or
Scene.replace_shape (main).

Run with the venv python (it needs OCP):
    .venv/bin/python -m benchmarks.rotate
"""
try:
    from .common import run
except ImportError:      # run as a plain script: python benchmarks/rotate.py
    from common import run

if __name__ == "__main__":
    run("rotate")
