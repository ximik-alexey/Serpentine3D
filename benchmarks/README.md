# Benchmarks

Standalone, dependency-light benchmarks for the Serpentine3D core. They are
**not** pytest tests — run them directly with the venv python (they need OCP):

```sh
.venv/bin/python -m benchmarks.move
.venv/bin/python -m benchmarks.rotate
.venv/bin/python -m benchmarks.scale
```

(or `python benchmarks/<name>.py`). Each builds N=500 torus objects
(tessellated, i.e. an already-drawn scene), applies one operation to all of
them, then does a full redraw (re-mesh + re-bbox of every object), and prints
a table of wall-clock time per phase with a per-object (µs) column.

They use the branch's native move path: `Scene.set_transforms` when present
(`carry-transforms`), otherwise `Scene.replace_shape` (`main`). The result is
the same on both; only the cost differs, which is the point.

| benchmark | operation (all 500) |
|---|---|
| `move`   | +10 X translation |
| `rotate` | 30° about Y |
| `scale`  | uniform 1.5x |

On a 500-torus scene the total (apply + redraw) goes from ~14 s on `main` to
~0.1 s on `carry-transforms`.

`common.py` holds the shared helpers (scene build, the 4x4 builders, the
apply path, the redraw, the table printer). The three scripts are thin
wrappers over `common.run(op)`.

### Running them against `main`

The venv has `serpentine3d` installed **editable** → it always imports the
`carry-transforms` checkout. To benchmark `main` (a separate worktree, e.g.
`/tmp/serp-main`), force the import from that worktree:

```sh
PYTHONPATH=/tmp/serp-main .venv/bin/python benchmarks/move.py
```

Without `PYTHONPATH` the `main` run silently imports the `carry-transforms`
code.
