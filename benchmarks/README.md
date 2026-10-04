# Benchmarks

Standalone, dependency-light benchmarks for the Serpentine3D core. They are
**not** pytest tests — run them directly with the venv python (they need OCP):

```sh
.venv/bin/python -m benchmarks.move
# or
.venv/bin/python benchmarks/move.py
```

Each benchmark prints a table of wall-clock time per operation, with a
per-object (µs) column.

## `move`

Builds N=500 torus objects (tessellated, i.e. an already-drawn scene), moves
them all by a +10 X translation, then does a full redraw (re-mesh + re-bbox of
every object). It reports the cost of each phase.

It uses the branch's native move path: `Scene.set_transforms` when present
(`carry-transforms`), otherwise `Scene.replace_shape` (`main`). The move result
is identical on both (objects end up +10 in X); only the cost differs, which is
the point. On a 500-torus scene the total (move + redraw) goes from ~14 s on
`main` to ~0.1 s on `carry-transforms`.

### Running it against `main`

The venv has `serpentine3d` installed **editable** → it always imports the
`carry-transforms` checkout. To benchmark `main` (a separate worktree, e.g.
`/tmp/serp-main`), force the import from that worktree:

```sh
PYTHONPATH=/tmp/serp-main .venv/bin/python /path/to/benchmarks/move.py
```

Without `PYTHONPATH` the `main` run silently imports the `carry-transforms`
code.
