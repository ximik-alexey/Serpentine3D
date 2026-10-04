#!/usr/bin/env python
"""Scale benchmark: build N torus objects, scale them all by a uniform 1.5x,
then do a full redraw (re-mesh + re-bbox every object). Prints a table of
wall-clock time per phase with a per-object (µs) column.

Uses the branch's native path: Scene.set_transforms (carry-transforms) or
Scene.replace_shape (main).

Run with the venv python (it needs OCP):
    .venv/bin/python -m benchmarks.scale
"""
try:
    from .common import run
except ImportError:      # run as a plain script: python benchmarks/scale.py
    from common import run

if __name__ == "__main__":
    run("scale")
