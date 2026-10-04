import numpy as np
import pytest
from serpentine3d.core.scene import Scene
from serpentine3d.core.picture import PictureShape
from serpentine3d.core.snaps import snap_points_for


def test_picture_carry_moves_pixels():
    s = Scene()
    pic = PictureShape({"origin": [0, 0, 0], "u": [10, 0, 0], "v": [0, 10, 0]})
    o = s.add(pic, name="pic")
    oid = o.id

    assert pic.plane["origin"][0] == 0

    seen = []
    s.add_listener(lambda *a, **k: seen.append(1), kinds=("objects",))

    m = np.eye(4)
    m[0, 3] = 30
    s.set_transforms({oid: m})

    assert len(seen) == 1

    obj = s.objects[oid]
    assert obj.shape.plane["origin"][0] == 30

    points = snap_points_for(obj.shape)
    xs = [p[0] for p, _ in points]
    assert min(xs) >= 30 - 1e-9
    assert max(xs) <= 40 + 1e-9

    assert pic.plane["origin"][0] == 0


def test_identity_transform_is_noop():
    s = Scene()
    pic = PictureShape({"origin": [0, 0, 0], "u": [5, 0, 0], "v": [0, 5, 0]})
    o = s.add(pic, name="pic")
    oid = o.id
    seen = []
    s.add_listener(lambda *a, **k: seen.append(1), kinds=("objects",))
    m = np.eye(4)
    s.set_transforms({oid: m})
    assert len(seen) == 0


def test_drag_display_no_notification_and_clear():
    s = Scene()
    pic = PictureShape({"origin": [0, 0, 0], "u": [1, 0, 0], "v": [0, 1, 0]})
    o = s.add(pic)
    oid = o.id
    rev_before = s.revision
    seen = []
    s.add_listener(lambda *a, **k: seen.append(1), kinds=("objects",))
    m = np.eye(4)
    m[0, 3] = 5
    s.set_drag_display({oid: m})
    assert s.revision == rev_before
    assert len(seen) == 0
    assert oid in s.drag_display
    s.clear_drag_display()
    assert s.drag_display == {}


def test_multi_object_one_notification():
    s = Scene()
    p1 = PictureShape({"origin": [0, 0, 0], "u": [1, 0, 0], "v": [0, 1, 0]})
    p2 = PictureShape({"origin": [0, 0, 0], "u": [1, 0, 0], "v": [0, 1, 0]})
    o1 = s.add(p1)
    o2 = s.add(p2)
    seen = []
    s.add_listener(lambda *a, **k: seen.append(1), kinds=("objects",))
    m = np.eye(4)
    m[1, 3] = 10
    s.set_transforms({o1.id: m, o2.id: m})
    assert len(seen) == 1
