#!/usr/bin/env python
"""Move benchmark: build N torus objects, move them all by a translation, then
do a full redraw (re-mesh + re-bbox every object). Reports the cost of each
phase in a table, with a per-object (µs) column.

Works on both branches: uses scene.set_transforms if present
(carry-transforms), otherwise scene.replace_shape (main). The move result is
the same on both (objects end up +10 in X); only the cost differs, which is
the point.

Run with the venv python (it needs OCP):
    .venv/bin/python benchmarks/move.py
"""
import time

import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene

N = 500


def build_scene(n):
    """Create n torus objects and tessellate them (a drawn scene)."""
    scene = Scene()
    objs = []
    for i in range(n):
        # spread the tori so their boxes are real, not stacked at the origin
        torus = g.make_torus(
            (i * 3.0, (i % 10) * 3.0, 0.0), 2.0, 0.5)
        objs.append(scene.add(torus))
    for o in objs:          # force tessellation: simulate an already-drawn scene
        _ = o.mesh
    return scene, objs


def move_all(scene, objs, m):
    """Move every object by the 4x4 `m`, via the branch's native path."""
    if hasattr(scene, "set_transforms"):
        scene.set_transforms({o.id: m for o in objs})
    else:
        for o in objs:
            scene.replace_shape(o.id, g.apply_matrix(o.shape, m))


def full_redraw(scene):
    """The redraw: re-mesh + re-bbox every object."""
    for o in scene.all():
        _ = o.mesh
        _ = o.bbox()


def print_table(rows, n):
    """rows: list of (label, seconds). Prints a clean table with a
    per-object (µs) column."""
    headers = ("Operation", "Time (s)", "µs/object")
    times = [f"{r[1]:.3f}" for r in rows]
    pers = [f"{r[1] * 1e6 / n:.1f}" for r in rows]
    w0 = max(len(headers[0]), max(len(r[0]) for r in rows))
    w1 = max(len(headers[1]), max(len(t) for t in times))
    w2 = max(len(headers[2]), max(len(p) for p in pers))
    print()
    print(f"  {headers[0]:<{w0}}  {headers[1]:>{w1}}  {headers[2]:>{w2}}")
    print(f"  {'-' * w0}  {'-' * w1}  {'-' * w2}")
    for (label, _), t_s, p_s in zip(rows, times, pers):
        print(f"  {label:<{w0}}  {t_s:>{w1}}  {p_s:>{w2}}")
    print()


def main():
    t0 = time.perf_counter()
    scene, objs = build_scene(N)
    build_t = time.perf_counter() - t0

    mode = "carry (set_transforms)" if hasattr(scene, "set_transforms") \
        else "main (replace_shape)"
    print(f"Move benchmark — {N} torus objects. Mode: {mode}")

    m = np.eye(4)
    m[0, 3] = 10.0         # move everything +10 along X

    t0 = time.perf_counter()
    move_all(scene, objs, m)
    move_t = time.perf_counter() - t0

    t0 = time.perf_counter()
    full_redraw(scene)
    redraw_t = time.perf_counter() - t0

    print_table([
        (f"build (create + tessellate x{N})", build_t),
        (f"move all {N} by +10 X", move_t),
        (f"full redraw (mesh+bbox x{N})", redraw_t),
        ("TOTAL (move + redraw)", move_t + redraw_t),
    ], N)


if __name__ == "__main__":
    main()
