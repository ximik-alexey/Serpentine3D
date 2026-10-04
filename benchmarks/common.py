"""Shared helpers for the standalone benchmarks.

Each benchmark builds N torus objects (tessellated, i.e. an already-drawn
scene), applies one operation to all of them, then does a full redraw
(re-mesh + re-bbox of every object), and prints a table of wall-clock time
per phase with a per-object (µs) column.

They use the branch's native move path: ``Scene.set_transforms`` when present
(carry-transforms), otherwise ``Scene.replace_shape`` (main). The result is
the same on both; only the cost differs, which is the point.
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
    for o in objs:          # force tessellation: a drawn scene
        _ = o.mesh
    return scene, objs


def make_matrix(op):
    """The 4x4 for each operation (all similarities, about the origin). The
    anchor does not change the cost; a 4x4 is a 4x4 either way."""
    m = np.eye(4)
    if op == "move":
        m[0, 3] = 10.0                       # +10 along X
    elif op == "rotate":
        a = np.deg2rad(30.0)                # 30° about Y
        m[0, 0], m[0, 2] = np.cos(a), np.sin(a)
        m[2, 0], m[2, 2] = -np.sin(a), np.cos(a)
    elif op == "scale":
        m[0, 0] = m[1, 1] = m[2, 2] = 1.5   # uniform 1.5x
    return m


def apply_op(scene, objs, m):
    """Apply the 4x4 `m` to every object, via the branch's native path."""
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


def mode():
    probe = Scene()
    return "carry (set_transforms)" if hasattr(probe, "set_transforms") \
        else "main (replace_shape)"


def bench(op):
    """Build a scene, apply `op` to all N, then a full redraw. Returns
    (apply_t, redraw_t) in seconds."""
    scene, objs = build_scene(N)
    m = make_matrix(op)
    t0 = time.perf_counter()
    apply_op(scene, objs, m)
    apply_t = time.perf_counter() - t0
    t0 = time.perf_counter()
    full_redraw(scene)
    redraw_t = time.perf_counter() - t0
    return apply_t, redraw_t


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


def run(op):
    """Run one benchmark and print its table."""
    print(f"Transform benchmark — {N} torus objects. Mode: {mode()}")
    apply_t, redraw_t = bench(op)
    print_table([
        (f"{op} apply to {N}", apply_t),
        (f"{op} full redraw (mesh+bbox x{N})", redraw_t),
        (f"TOTAL ({op} + redraw)", apply_t + redraw_t),
    ], N)
