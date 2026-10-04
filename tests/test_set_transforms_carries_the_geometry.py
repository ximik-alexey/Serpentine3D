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
