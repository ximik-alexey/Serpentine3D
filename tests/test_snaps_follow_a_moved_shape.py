import numpy as np
import pytest
from serpentine3d.core.scene import Scene
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from serpentine3d.core.snaps import snap_points_for
from serpentine3d.core.picture import PictureShape


def test_brep_box_carry_moves_snaps():
    s = Scene()
    box_shape = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
    o1 = s.add(box_shape, name="box1")
    o2 = s.add(box_shape, name="box2")
    id1 = o1.id
    id2 = o2.id

    snaps_before = snap_points_for(s.objects[id1].shape)
    xs_before = [float(p[0]) for p, _ in snaps_before]
    assert any(0 <= x <= 10 for x in xs_before)

    seen = []
    s.add_listener(lambda *a, **k: seen.append(1), kinds=("objects",))

    m = np.eye(4)
    m[0, 3] = 30.0
    s.set_transforms({id1: m, id2: np.eye(4)})

    assert len(seen) == 1

    obj1 = s.objects[id1]
    verts = obj1.mesh.vertices
    xs = verts[:, 0]
    assert xs.min() >= 30 - 1e-6
    assert xs.max() <= 40 + 1e-6

    normals = obj1.mesh.normals
    norms = np.linalg.norm(normals, axis=1)
    assert np.allclose(norms, 1.0)

    min_pt, max_pt = obj1.bbox()
    assert min_pt[0] == pytest.approx(30.0, abs=1e-4)
    assert max_pt[0] == pytest.approx(40.0, abs=1e-4)

    snaps_after = snap_points_for(obj1.shape)
    xs_after = [float(p[0]) for p, _ in snaps_after]
    assert any(30 <= x <= 40 for x in xs_after)
    assert not any(0 <= x <= 10 for x in xs_after)
