"""A move carries the object by a TopLoc location, not a copy of the B-rep.

The geometry stays in its own coordinates; the pose is a location on top
of it. A move composes that location, which is what keeps a move cheap
(the TShape is shared, the tessellation is not redone) and what makes
`shape` hand back the world geometry without it being rebuilt.
"""

import numpy as np
import pytest

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt

from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.commands.base import (
    CommandContext, CommandProcessor,
)


def _scene():
    scene = Scene()
    selection = SelectionManager(scene)
    ctx = CommandContext(scene, selection, History(scene))
    ctx.replay_cplane = CPlane(origin=(0, 0, 0), normal=(0, 0, 1),
                              xdir=(1, 0, 0))
    return scene, selection, ctx


def _box(scene, at=(0, 0, 0), size=(10, 20, 30)):
    shape = BRepPrimAPI_MakeBox(gp_Pnt(*at), *size).Shape()
    return scene.add(shape)


def _translation(offset):
    m = np.eye(4)
    m[:3, 3] = offset
    return m


def test_a_move_composes_a_location():
    scene, _selection, _ctx = _scene()
    obj = _box(scene)

    scene.set_transforms({obj.id: _translation((5, 0, -2))})

    assert obj._location is not None and not obj._location.IsIdentity()
    lo, hi = obj.bbox()
    assert tuple(lo) == pytest.approx((5, 0, -2), abs=1e-6)
    assert tuple(hi) == pytest.approx((15, 20, 28), abs=1e-6)


def test_a_move_keeps_the_same_geometry():
    scene, _selection, _ctx = _scene()
    obj = _box(scene)
    shape = obj._shape
    tshape = shape.TShape()

    scene.set_transforms({obj.id: _translation((5, 0, -2))})

    assert obj._shape is shape
    assert obj._shape.TShape() is tshape


def test_repeated_moves_compose():
    scene, _selection, _ctx = _scene()
    obj = _box(scene)

    scene.set_transforms({obj.id: _translation((5, 0, 0))})
    scene.set_transforms({obj.id: _translation((0, 7, 0))})

    lo, hi = obj.bbox()
    assert tuple(lo) == pytest.approx((5, 7, 0), abs=1e-6)
    assert tuple(hi) == pytest.approx((15, 27, 30), abs=1e-6)


def test_a_turn_rides_the_location_and_a_scale_bakes():
    scene, _selection, _ctx = _scene()
    obj = _box(scene)
    from serpentine3d.utils.math3d import rotation_matrix, scale_matrix

    scene.set_transforms(
        {obj.id: rotation_matrix((0, 0, 0), (0, 0, 1), 90)})
    assert obj._location is not None
    # a +90-degree turn about z carries x to y and y to -z
    lo, hi = obj.bbox()
    assert tuple(lo) == pytest.approx((-20, 0, 0), abs=1e-6)
    assert tuple(hi) == pytest.approx((0, 10, 30), abs=1e-6)

    # a scale cannot ride a location — `BRepBndLib` ignores a scale in
    # one — so it is applied to the geometry instead
    old_shape = obj._shape
    scene.set_transforms(
        {obj.id: scale_matrix((0, 0, 0), 2.0)})
    assert obj._shape is not old_shape
    assert obj._location is None
    lo, hi = obj.bbox()
    assert tuple(lo) == pytest.approx((-40, 0, 0), abs=1e-6)
    assert tuple(hi) == pytest.approx((0, 20, 60), abs=1e-6)


def test_a_matrix_a_location_cannot_carry_is_baked():
    scene, _selection, _ctx = _scene()
    obj = _box(scene)
    old_shape = obj._shape
    obj.mesh                       # tessellate, so a bake has something to clear

    shear = np.eye(4)
    shear[0, 2] = 0.5
    scene.set_transforms({obj.id: shear})

    assert obj._shape is not old_shape
    assert obj._location is None
    assert obj._transform is None
    assert obj._mesh is None
    # and the world geometry is what the matrix said
    lo, hi = obj.bbox()
    assert tuple(lo) == pytest.approx((0, 0, 0), abs=1e-6)
    assert hi[0] == pytest.approx(10 + 0.5 * 30, abs=1e-6)


def test_the_shape_property_is_the_world_view():
    scene, _selection, _ctx = _scene()
    obj = _box(scene)
    scene.set_transforms({obj.id: _translation((5, 0, -2))})

    world = obj.shape
    assert not world.Location().IsIdentity()
    lo, hi = g.bbox(world)
    assert tuple(lo) == pytest.approx((5, 0, -2), abs=1e-6)
    assert tuple(hi) == pytest.approx((15, 20, 28), abs=1e-6)


def test_replacing_the_shape_takes_the_pose_from_the_geometry():
    scene, _selection, _ctx = _scene()
    obj = _box(scene)
    scene.set_transforms({obj.id: _translation((5, 0, -2))})

    new = scene.replace_shape(obj.id,
                             BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0),
                                                  1, 1, 1).Shape())

    # a replaced geometry is a new world geometry: its location is its
    # pose, and a bare one is the identity
    assert new is not obj
    assert new._location is None
    lo, hi = new.bbox()
    assert tuple(lo) == pytest.approx((0, 0, 0), abs=1e-6)
    assert tuple(hi) == pytest.approx((1, 1, 1), abs=1e-6)


def test_the_transform_view_of_the_pose():
    scene, _selection, _ctx = _scene()
    obj = _box(scene)
    assert obj.transform is np.eye(4) or np.array_equal(
        obj.transform, np.eye(4))

    m = _translation((5, 0, -2))
    scene.set_transforms({obj.id: m})
    assert obj.transform == pytest.approx(m)


def test_a_move_does_not_re_tessellate():
    scene, _selection, _ctx = _scene()
    obj = _box(scene)
    obj.mesh                       # the tessellation of the local geometry
    mesh = obj._mesh
    assert mesh is not None

    scene.set_transforms({obj.id: _translation((5, 0, -2))})

    assert obj._mesh is mesh


def test_the_move_command_composes_a_location():
    scene, selection, ctx = _scene()
    obj = _box(scene)
    selection.set([obj.id])
    proc = CommandProcessor(ctx)
    assert proc.run("move")
    proc.provide_text("0,0,0")
    proc.provide_text("5,0,0")
    assert not proc.busy

    assert obj._location is not None
    lo, hi = obj.bbox()
    assert tuple(lo) == pytest.approx((5, 0, 0), abs=1e-6)
    assert tuple(hi) == pytest.approx((15, 20, 30), abs=1e-6)
