#!/usr/bin/env python
"""Move benchmark: build N torus objects, move them all by a +10 X
translation, then do a full redraw (re-mesh + re-bbox every object). Prints a
table of wall-clock time per phase with a per-object (µs) column.

Uses the branch's native path: Scene.set_transforms (carry-transforms) or
Scene.replace_shape (main).

Run with the venv python (it needs OCP):
    .venv/bin/python -m benchmarks.move
"""
try:
    from .common import run
except ImportError:      # run as a plain script: python benchmarks/move.py
    from common import run

if __name__ == "__main__":
    run("move")
