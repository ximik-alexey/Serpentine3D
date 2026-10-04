import numpy as np
from serpentine3d.core.scene import Scene
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox


def test_drag_display_is_display_only_until_release():
    s = Scene()
    box = BRepPrimAPI_MakeBox(10, 10, 10).Shape()
    o = s.add(box, name="box")
    obj_id = o.id

    seen = []
    s.add_listener(lambda *a, **k: seen.append(1), kinds=("objects",))

    rev_before = s.revision
    m = np.eye(4)
    m[0, 3] = 1.0
    m[1, 3] = 2.0
    m[2, 3] = 3.0

    s.set_drag_display({obj_id: m})
    assert s.revision == rev_before
    assert len(seen) == 0
    assert obj_id in s.drag_display

    s.clear_drag_display()
    assert s.drag_display == {}

    s.set_drag_display({obj_id: m})
    rev_before2 = s.revision
    seen.clear()

    s.set_transforms({obj_id: m})
    assert s.revision != rev_before2
    assert len(seen) == 1
    assert obj_id in s.drag_display

    s.clear_drag_display()
    assert s.drag_display == {}
