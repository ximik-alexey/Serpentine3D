import numpy as np
import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from serpentine3d.core.scene import Scene

def test_set_transforms_carries_geometry():
    s = Scene()
    box = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
    o = s.add(box, name="box")
    seen = []
    s.add_listener(lambda *a, **k: seen.append(1), kinds=("objects",))
    m = np.eye(4)
    m[0, 3] = 30.0
    s.set_transforms({o.id: m})

    min_pt, max_pt = s.objects[o.id].bbox()
    assert min_pt[0] == pytest.approx(30.0, abs=1e-6)
    assert max_pt[0] == pytest.approx(40.0, abs=1e-6)

    bb = Bnd_Box()
    BRepBndLib.Add_s(box, bb)
    ox0, _, _, ox1, _, _ = bb.Get()
    assert ox0 == pytest.approx(0.0, abs=1e-6)
    assert ox1 == pytest.approx(10.0, abs=1e-6)

    o2 = s.objects[o.id]
    # The mesh stays in local coordinates; the pose is in _transform.
    assert o2.mesh.vertices[:, 0].min() == pytest.approx(0.0, abs=1e-6)
    assert o2._transform[0, 3] == pytest.approx(30.0, abs=1e-6)

    assert len(seen) == 1


def test_a_move_stale_composed_cache_catches_up_without_a_reread_block():
    """A move no longer drops the composed-shape cache. A move of up to
    25 objects re-composes at once, so a read right after the commit is
    at the new pose; a bigger one leaves the caches stale — a read is a
    cheap hit at the previous pose, and _recompose_shape is the only
    thing that re-composes. A real geometry replacement still
    hard-invalidates."""
    from serpentine3d.core import geometry
    s = Scene()
    box = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
    o = s.add(box, name="box")
    m = np.eye(4)
    m[0, 3] = 30.0
    s.set_transforms({o.id: m})
    o = s.objects[o.id]
    assert not o._shape_stale
    assert geometry.bbox(o.shape)[0][0] == pytest.approx(30.0, abs=1e-6)

    extra = [s.add(BRepPrimAPI_MakeBox(10, 10, 10).Shape(), name=f"b{i}")
             for i in range(30)]
    m2 = np.eye(4)
    m2[0, 3] = 50.0
    s.set_transforms({o.id: m2, **{b.id: m2 for b in extra}})
    o = s.objects[o.id]
    assert o._shape_stale
    # a read right after the commit: the previous pose, a cache hit
    assert geometry.bbox(o.shape)[0][0] == pytest.approx(30.0, abs=1e-6)

    o._recompose_shape()
    assert not o._shape_stale
    assert geometry.bbox(o.shape)[0][0] == pytest.approx(80.0, abs=1e-6)

    o.shape = BRepPrimAPI_MakeBox(5, 5, 5).Shape()
    assert o._shape_composed is None
    assert o._shape_stale is False
    assert geometry.bbox(o.shape)[0][0] == pytest.approx(0.0, abs=1e-6)
