import numpy as np
import pytest

from benchmarks.common import (
    GRID,
    N,
    apply_op,
    build_scene,
    full_redraw,
    make_matrix,
)
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene


def test_build_scene():
    _, objs = build_scene()
    assert len(objs) == N
    assert GRID == (10, 10, 5)
    for o in objs:
        assert o.kind == "solid"
        assert o.mesh_ready is True


def test_make_matrix_move():
    m = make_matrix("move")
    assert m[0, 3] == pytest.approx(10)
    assert m[1, 3] == pytest.approx(0)
    assert m[2, 3] == pytest.approx(0)
    assert np.allclose(m[:3, :3], np.eye(3))


def test_make_matrix_rotate():
    m = make_matrix("rotate")
    angle = np.deg2rad(30)
    c = np.cos(angle)
    s = np.sin(angle)
    assert m[0, 0] == pytest.approx(c)
    assert m[0, 2] == pytest.approx(s)
    assert m[2, 0] == pytest.approx(-s)
    assert m[2, 2] == pytest.approx(c)
    assert np.allclose(m[:3, 3], 0)


def test_make_matrix_scale():
    m = make_matrix("scale")
    assert m[0, 0] == pytest.approx(1.5)
    assert m[1, 1] == pytest.approx(1.5)
    assert m[2, 2] == pytest.approx(1.5)
    assert np.allclose(m[:3, 3], 0)


def test_apply_op_move():
    scene = Scene()
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    apply_op(scene, [box], make_matrix("move"))
    bbox = scene.all()[0].bbox()
    min_corner = bbox[0] if isinstance(bbox, (tuple, list)) else bbox.min
    assert min_corner[0] == pytest.approx(10)


def test_full_redraw_no_error():
    scene = Scene()
    box = g.make_box((0, 0, 0), 1, 1, 1)
    scene.add(box)
    full_redraw(scene)
