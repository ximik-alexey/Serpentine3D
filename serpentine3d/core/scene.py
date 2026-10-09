"""Scene graph: object storage, naming, visibility, change notification.

Core is Qt-free; UI subscribes via plain callables.
"""

from __future__ import annotations

import itertools
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

import numpy as np
from OCP.gp import gp_Trsf
from OCP.TopLoc import TopLoc_Location

from . import geometry
from .deferred import DeferredShape
from .layers import DEFAULT_LAYER_ID, LayerManager
from .tessellate import DisplayMesh, tessellate


def _rebuild_record(rec: dict, shapes: list):
    op = rec["op"]
    p = rec.get("params", {})
    if op == "loft":
        return geometry.loft(shapes, ruled=bool(p.get("ruled")))
    if op == "extrude":
        if "result_index" in p:
            results = geometry.extrude_profiles(
                shapes, tuple(p["direction"]), float(p["dist"]),
                cap=bool(p.get("cap")))
            return results[int(p["result_index"])]
        return geometry.extrude(shapes[0], tuple(p["direction"]),
                                float(p["dist"]), cap=bool(p.get("cap")))
    if op == "revolve":
        return geometry.revolve(shapes[0], tuple(p["origin"]),
                                tuple(p["axis"]), float(p["angle"]))
    raise ValueError(f"Unknown history op '{op}'")


_TESS_GUARD = threading.Lock()
_TESS_LOCKS: dict[int, tuple] = {}      # id(shape) -> (shape, Lock)


def _tess_lock(shape) -> threading.Lock:
    with _TESS_GUARD:
        ent = _TESS_LOCKS.get(id(shape))
        if ent is None or ent[0] is not shape:
            ent = (shape, threading.Lock())
            _TESS_LOCKS[id(shape)] = ent
        if len(_TESS_LOCKS) > 1024:     # bound the registry
            for k in list(_TESS_LOCKS)[:512]:
                if not _TESS_LOCKS[k][1].locked():
                    del _TESS_LOCKS[k]
        return ent[1]

_IDENTITY = np.eye(4)


def location_matrix(loc) -> np.ndarray | None:
    """The 4x4 of a location's transformation, or None for the identity.

    A location is how this build of OCCT carries a shape's pose: the
    geometry stays in its own coordinates and the world is the location
    applied to it. `gp_Trsf` holds the 3x4 of it (the 0 0 0 1 row is
    implicit); `Value` numbers rows and columns from one.
    """
    if loc is None or loc.IsIdentity():
        return None
    t = loc.Transformation()
    return np.array([[t.Value(1, 1), t.Value(1, 2), t.Value(1, 3),
                      t.Value(1, 4)],
                     [t.Value(2, 1), t.Value(2, 2), t.Value(2, 3),
                      t.Value(2, 4)],
                     [t.Value(3, 1), t.Value(3, 2), t.Value(3, 3),
                      t.Value(3, 4)],
                     [0.0, 0.0, 0.0, 1.0]])


def _carry_box(box: tuple, m: np.ndarray) -> tuple:
    """The (lo, hi) box moved by the 4x4 `m`.

    The box is axis-aligned, so its image under a translation, rotation
    or uniform scale is the min/max of the eight carried corners — the
    tight answer for the isometries a pose is, in eight transforms
    instead of a remeasure of the shape.
    """
    lo = np.asarray(box[0], float)
    hi = np.asarray(box[1], float)
    corners = np.array([[x, y, z]
                       for x in (lo[0], hi[0])
                       for y in (lo[1], hi[1])
                       for z in (lo[2], hi[2])])
    carried = (corners @ np.asarray(m, float)[:3, :3].T
               + np.asarray(m, float)[:3, 3])
    return (tuple(carried.min(axis=0)), tuple(carried.max(axis=0)))


def _trsf_from_matrix(m) -> gp_Trsf | None:
    """A `gp_Trsf` for a 4x4, if it is one.

    `gp_Trsf` is translation, rotation, uniform scale and mirror, and
    nothing else: a matrix whose 3x3 part is not a uniform scale of an
    orthogonal matrix (a shear, a non-uniform scale) cannot be a
    location, and `SetValues` would keep the coefficients it was given
    rather than refuse them. The answer is None in that case, and the
    caller applies the matrix to the geometry instead.
    """
    v = np.asarray(m, dtype=float)
    lin = v[:3, :3]
    norms = [float(np.linalg.norm(lin[:, i])) for i in range(3)]
    s = sum(norms) / 3.0
    if s < 1e-12:
        return None
    # Only an isometry rides a location: a scale in it is ignored by
    # `BRepBndLib` and the like, so a scaled matrix bakes instead.
    if not np.isclose(s, 1.0, atol=1e-6):
        return None
    r = lin / s
    if not np.allclose(r.T @ r, np.eye(3), atol=1e-6):
        return None
    t = gp_Trsf()
    t.SetValues(*(v[:3, :4].flatten().tolist()))
    return t

def _fold_location(shape):
    """`(geometry in world coordinates, None)`: an incoming location, applied.

    A shape can carry its own location (an imported part does). The
    object stores the geometry in world coordinates with no pose; the
    pose is what the user *moves* the object by, and that one rides a
    location from then on. Baking on the way in keeps a loaded scene on
    the unposed fast path: a pose is a per-frame cost, and a file's
    authoring transform is not one to pay on every frame, in every
    viewport.
    """
    if shape is None or isinstance(shape, DeferredShape) \
            or not hasattr(shape, "Location"):
        return shape, None
    loc = shape.Location()
    if loc.IsIdentity():
        return shape, None
    m = location_matrix(loc)
    if m is None:
        return shape, None
    # Reset the location first: `BRepBuilderAPI_Transform` keeps a shape's
    # location on the copy it makes, so baking on top of it would apply
    # the file's transform twice.
    return geometry.apply_matrix(shape.Located(TopLoc_Location()), m), None


@dataclass
class SceneObject:
    id: str
    name: str
    # The geometry, in its own coordinates, without the pose. A shape can
    # arrive carrying a location (an imported part); the scene folds that
    # into `_location` on the way in, and what is stored stays local.
    # Read it through `shape`, which converts what it finds and hands
    # back the world geometry; the underscore is here so that property
    # can exist at all.
    _shape: object
    kind: str          # curve | surface | solid | point | compound | mesh | pointcloud
    layer_id: str
    visible: bool = True
    locked: bool = False               # visible but unselectable
    group_id: str | None = None        # objects sharing an id select together
    block_id: str | None = None        # instance of a block definition
    color: tuple[float, float, float] | None = None   # None -> layer color
    # {"metallic","roughness","opacity"} and optionally "color", which only
    # rendered mode reads — see Scene.render_color_of
    material: dict | None = None
    clip_plane: dict | None = None     # {"enabled": bool}: sections the view
    annotation: dict | None = None     # {"text": str}: model-space dot label
    linetype: str = "ByLayer"          # dash style; ByLayer -> use the layer's
    draw_order: int = 0                # higher draws on top (breaks depth ties)
    _mesh: DisplayMesh | None = field(default=None, repr=False, compare=False)
    _bounds: tuple | None = field(default=None, repr=False, compare=False)
    # The box of the local geometry, in the geometry's own coordinates.
    # Survives a pose change, which only moves the world box: a move
    # must not cost a remeasure of the geometry.
    _local_bounds: tuple | None = field(default=None, repr=False,
                                        compare=False)
    # The pose, as a TopLoc location. Composing a location is a reference
    # to a transformation, not a copy of the geometry, which is what
    # makes a move cheap: the TShape stays shared.
    _location: object = field(default=None, repr=False, compare=False)
    # The 4x4 view of `_location` for the numpy world (mesh upload,
    # culling, picking). None means the identity pose.
    _transform: object = field(default=None, repr=False, compare=False)
    # The scene holding this object, so a bare `.shape` read on something
    # deferred can go through `Scene.realise` and get the whole job — an
    # object that converts to nothing removed, one that converts to two
    # given its sibling — rather than only the shape.
    _scene: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        # The world view of the pose, built once per (geometry, pose)
        # pair and handed out as the same object until the pair
        # changes, so a reader that compares by identity sees the same
        # shape until somebody edits it.
        self._shape_view = None
        self._shape_view_for = None
        self._shape_view_loc = None

    def _view_stale(self):
        self._shape_view = None
        self._shape_view_for = None
        self._shape_view_loc = None

    @property
    def shape(self):
        """This object's geometry in the world, converting it first if it
        has not been.

        Every reader goes through here, which is the point: there is no
        call site left that can be handed a placeholder by mistake. The
        pose rides out as a location when it is not the identity, so a
        reader gets the world geometry without it being copied.
        """
        held = self._shape
        if isinstance(held, DeferredShape):
            scene = self._scene
            if scene is not None:
                scene.realise(self.id)
            else:
                shapes = held.shapes()
                self._shape = shapes[0] if shapes else None
            held = self._shape
        if held is None:
            return None
        loc = self._location
        if loc is not None and not loc.IsIdentity():
            if (self._shape_view is not None
                    and self._shape_view_for is held
                    and self._shape_view_loc is loc):
                return self._shape_view
            # A Python-subclass shape (text, hatch) loses its type in
            # the C++ .Located() copy; readers that isinstance on the
            # shape would stop seeing them once posed. Re-wrap the same
            # local geometry in the type, over the located copy.
            if hasattr(held, "rewrap"):
                self._shape_view = held.rewrap(loc)
            else:
                self._shape_view = held.Located(loc)
            self._shape_view_for = held
            self._shape_view_loc = loc
            return self._shape_view
        self._shape_view = None
        return held

    @shape.setter
    def shape(self, value):
        # A shape can arrive carrying its own location (an imported part).
        # The pose is held in `_location`, the stored geometry stays
        # local, and whatever pose this object already had is applied to
        # the new geometry rather than dropped.
        loc = None
        if value is not None and not isinstance(value, DeferredShape) \
                and hasattr(value, "Location") \
                and not value.Location().IsIdentity():
            loc = value.Location()
            value = value.Located(TopLoc_Location())
        pose = self.transform
        if value is not None and not np.array_equal(pose, _IDENTITY):
            value = geometry.apply_matrix(value, pose)
        self._shape = value
        self._location = loc
        self._transform = location_matrix(loc)
        self._view_stale()

    @property
    def transform(self) -> np.ndarray:
        """The 4x4 of this object's pose; the identity when it has none."""
        if self._transform is None:
            self._transform = location_matrix(self._location)
        return self._transform if self._transform is not None else _IDENTITY

    @property
    def shape_ready(self) -> bool:
        """Whether the geometry exists, as opposed to a promise of it.

        Asking does not convert anything, which is what makes it usable in
        the places that must not: the sync key, the tests above it.
        """
        return not isinstance(self._shape, DeferredShape)

    def bbox(self) -> tuple[tuple, tuple]:
        """This object's world bounding box, worked out at most once.

        Measuring a B-rep walks the whole shape and a mesh reads every
        vertex — about 100us an object, which is nothing until something
        asks for all of them every frame. The gumball does exactly that,
        and on the cave file it cost 747 ms of every frame you orbited
        with the drawing selected.

        Keyed on the shape it measured and the pose it was measured
        under, rather than cleared by hand: both are swapped for new
        objects when they change, so the answer expires by itself and
        there is no invalidation to forget at a call site. A pose change
        alone does not invalidate the geometry: the local box is kept in
        `_local_bounds` and carried to the new pose, so a move costs an
        8-corner transform, not a remeasure of the shape.
        """
        shape = self.shape
        if shape is None:
            return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        cached = self._bounds
        if (cached is not None and cached[0] is self._shape
                and cached[1] is self._location):
            return cached[2]
        local = self._local_bounds
        if (local is not None and local[0] is self._shape
                and self._location is not None
                and not self._location.IsIdentity()):
            m = location_matrix(self._location)
            if m is not None:
                box = _carry_box(local[1], m)
                self._bounds = (self._shape, self._location, box)
                return box
        box = geometry.bbox(shape)
        # The box of the geometry in its own coordinates: the world box
        # carried back by the inverse location. One extra 8-corner pass on
        # first measure, so a later pose change never needs the OCC.
        if self._location is not None:
            inv = location_matrix(self._location)
            if inv is not None:
                inv = np.linalg.inv(inv)
                local_box = _carry_box(box, inv)
            else:
                local_box = box
        else:
            local_box = box
        self._local_bounds = (self._shape, local_box)
        self._bounds = (self._shape, self._location, box)
        return box

    @property
    def mesh(self) -> DisplayMesh:
        # None is what a deferred object that converted to nothing is left
        # holding. The scene drops it, but whoever was already iterating
        # still has it and will ask; an empty mesh draws nothing, which is
        # the right picture, where the kernel would raise on the way there.
        # The mesh is of the local geometry: the pose carries it to the
        # world at draw time, so the tessellator is handed the shape
        # without its location, not the located view.
        shape = self.shape
        if shape is None:
            return DisplayMesh()
        if self._mesh is None:
            with _tess_lock(self._shape):
                if self._mesh is None:
                    self._mesh = tessellate(self._shape)
        return self._mesh

    @property
    def mesh_ready(self) -> bool:
        return self._mesh is not None

    def clone(self) -> "SceneObject":
        if self.kind == "picture":
            return replace(self, _shape=self.shape.copy())
        return replace(self)


class Scene:
    def __init__(self):
        self.objects: dict[str, SceneObject] = {}
        self._order: list[str] = []
        self.layers = LayerManager()
        self.layers.on_shown = self.realise_layer
        self._counters = {}
        self._listeners: list = []
        self._batch_depth = 0           # see batched()
        self._batched_kinds: set[str] = set()
        self.revision = 0               # bumped on every change notification
        # In-flight previews (a command dragging a whole object, a gumball
        # drag): id -> 4x4. Display only, see set_drag_display.
        self.drag_display: dict = {}
        self.named_views: dict = {}     # name -> camera params
        # Objects showing their control points. Kept here rather than on a
        # viewport because points on is something the drawing is doing: turn
        # a curve's points on in the Top view and its corners are there to
        # pick in the Right view too. See Viewport.cv_enabled.
        self.cv_enabled: set[str] = set()
        # Objects showing direction arrows, for the same reason and for as
        # long as `dir` runs. Which way a curve runs is a fact about the
        # drawing, not about the pane you happened to ask in.
        self.dir_enabled: set[str] = set()
        self.layouts: list = []         # drafting sheets (core/layout.py)
        self.units: str = "mm"          # document units (utils/units.py)
        self.block_defs: dict = {}      # id -> {"name", "shapes": [TopoDS]}
        self.annot_styles: dict = {}    # name -> text/dim style overrides
        self.record_history = False     # new surfaces remember their inputs
        self.history_records: list = []   # {"op", "inputs", "output", ...}
        self._regen_active = False
        # What a scan session's .serp carries beside its point clouds
        # (protocol/SERP-SESSION-RECORD.md): camera trajectories, one dict
        # per stream, and the session record. Held as the plain dicts the
        # file gave, so a save writes them back unchanged; nothing here
        # draws or edits them yet.
        self.trajectories: list = []
        self.session: dict | None = None

    # -- notification --
    @property
    def image_planes(self):
        """Legacy file representation; pictures themselves are scene objects."""
        return [obj.shape.plane for obj in self.all() if obj.kind == "picture"]

    @image_planes.setter
    def image_planes(self, planes):
        from .picture import PictureShape
        for obj in list(self.all()):
            if obj.kind == "picture":
                self.remove(obj.id)
        for plane in planes:
            self.add(PictureShape(plane), name=plane.get("name"))

    def add_listener(self, fn, kinds: tuple | None = None):
        """Subscribe; kinds limits calls to those change categories
        ("objects", "layers", "layouts") — "all" changes always fire."""
        self._listeners.append((fn, frozenset(kinds) if kinds else None))

    @contextmanager
    def batched(self):
        """Hold the notifications until the whole change is made.

        Listeners answer a change by reading the scene, and two of them read
        all of it — the layers panel rebuilds its tree and counts objects per
        layer, the status bar counts objects. One notification per object
        added therefore makes bulk work cost objects squared: 0.08 ms an
        object into an empty scene, 0.71 ms into one already holding 4000,
        about 4.7 seconds of opening the 522 MB cave file.

        Nobody wants the states in between. What comes out is the finished
        scene, once, and still sorted by kind so a listener that only asked
        about layouts is not woken by objects arriving.

        Notifications go out even if the body raises: a half-read file still
        changed the scene, and a panel showing what was there before is worse
        than one showing the half. `revision` still moves inside the batch,
        so a cache rebuilt part-way through can tell the scene shifted.
        """
        self._batch_depth += 1
        try:
            yield self
        finally:
            self._batch_depth -= 1
            if not self._batch_depth and self._batched_kinds:
                kinds, self._batched_kinds = self._batched_kinds, set()
                if "all" in kinds:
                    self._fire("all")       # already reaches everyone
                else:
                    for kind in sorted(kinds):
                        self._fire(kind)

    def notify(self, kind: str = "all"):
        self.revision += 1
        if self._batch_depth:
            self._batched_kinds.add(kind)
            return
        self._fire(kind)

    def _fire(self, kind: str):
        for fn, kinds in self._listeners:
            if kinds is None or kind == "all" or kind in kinds:
                fn()

    # -- object management --
    def _auto_name(self, kind: str) -> str:
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        return f"{kind.capitalize()} {n:02d}"

    def add(self, shape, name: str | None = None,
            layer_id: str | None = None) -> SceneObject:
        # A DeferredShape is geometry the file described and nothing has
        # converted. It answers for its own kind, because working the kind
        # out from the shape is exactly the conversion being put off.
        kind = (shape.kind if isinstance(shape, DeferredShape)
                else geometry.shape_kind(shape))
        _shape, _loc = _fold_location(shape)
        obj = SceneObject(
            id=uuid.uuid4().hex[:8],
            name=name or self._auto_name(kind),
            _shape=_shape,
            kind=kind,
            layer_id=layer_id or self.layers.current_id,
            _location=_loc,
            _transform=location_matrix(_loc),
            _scene=self,
        )
        self.objects[obj.id] = obj
        self._order.append(obj.id)
        self.notify("objects")
        return obj

    def add_from(self, shape, like: SceneObject) -> SceneObject:
        """Add a shape carrying over another object's display attributes
        (layer, colour, material, annotation, group)."""
        obj = self.add(shape, layer_id=like.layer_id)
        fields = {}
        if like.color is not None:
            fields["color"] = like.color
        if like.material:
            fields["material"] = dict(like.material)
        if like.annotation:
            fields["annotation"] = dict(like.annotation)
        if like.group_id:
            fields["group_id"] = like.group_id
        if fields:
            obj = self.update(obj.id, **fields)
        return obj

    # -- converting what was only read (see core/deferred.py) --

    def realise(self, obj_id: str) -> SceneObject | None:
        """Convert an object's deferred geometry, now.

        One Rhino object is usually one shape, but not always, and the two
        exceptions are why this is the scene's job rather than the object's.
        Roughly a sixth of the hidden objects in a real survey file convert
        to nothing at all, and an eager import made no object for those, so
        neither can this one. A few convert to two — a sewn brep and the
        mesh fallback for the faces that would not sew — and eager import
        made two objects, so this adds the sibling.

        Returns the object, or None if the geometry turned out to be
        nothing and it has been dropped.
        """
        obj = self.objects.get(obj_id)
        if obj is None or obj.shape_ready:
            return obj

        held = obj._shape
        shapes = held.shapes()
        if not shapes:
            # Emptied as well as dropped: something may still be holding
            # this object, and a placeholder that has already been asked
            # and answered nothing is worse to hand back than nothing.
            obj._shape = None
            self.remove(obj_id)
            return None

        _shape, _loc = _fold_location(shapes[0])
        obj._shape = _shape
        if _loc is not None:
            old = obj._location
            obj._location = (old.Multiplied(_loc)
                            if old is not None and not old.IsIdentity()
                            else _loc)
            obj._transform = location_matrix(obj._location)
        obj._mesh = None
        # The file's word on the kind was a guess made without the geometry.
        obj.kind = geometry.shape_kind(shapes[0])
        obj._view_stale()
        for extra in shapes[1:]:
            self.add(extra, layer_id=obj.layer_id)
        self.notify("objects")
        return obj

    def realise_layer(self, layer_id: str) -> int:
        """Convert everything still deferred on a layer. Returns how many.

        This is what a layer being switched back on calls: doing the whole
        layer in one pass means the file behind it is opened once, and it
        keeps the cost where the user can see they asked for it.
        """
        pending = [o.id for o in self.all()
                   if o.layer_id == layer_id and not o.shape_ready]
        if not pending:
            return 0
        with self.batched():
            for obj_id in pending:
                self.realise(obj_id)
        return len(pending)

    def remove_layer(self, layer_id: str) -> list[str]:
        """Delete a layer and the layers under it. Returns what went.

        Whatever was drawn on any of them moves to the default layer
        first. The work is still the user's, and an object pointing at a
        layer that is gone is a crash on the next redraw.
        """
        going = {layer_id,
                 *(la.id for la in self.layers.descendants(layer_id))}
        orphans = [o.id for o in self.all() if o.layer_id in going]
        if orphans:
            self.update_many(orphans, layer_id=DEFAULT_LAYER_ID)
        return self.layers.remove(layer_id)

    def remove(self, obj_id: str):
        if obj_id in self.objects:
            del self.objects[obj_id]
            self._order.remove(obj_id)
            self.notify("objects")

    def replace_shape(self, obj_id: str, shape) -> SceneObject:
        """Swap an object's geometry (transform, boolean result, ...).

        The result of an operation on a located shape is itself located,
        and the location of a rebuilt geometry is not a pose to keep: it
        is folded in, the stored geometry stays local, and the pose the
        object had is what the new geometry already contains.
        """
        old = self.objects[obj_id]
        _shape, _loc = _fold_location(shape)
        new = replace(old, _shape=_shape, kind=geometry.shape_kind(shape),
                      _mesh=None, _location=_loc,
                      _transform=location_matrix(_loc))
        self.objects[obj_id] = new
        self._regenerate_dependents(obj_id)
        self.notify("objects")
        return new

    def set_transforms(self, transforms: dict) -> int:
        """Move objects by their 4x4 poses, carried as TopLoc locations.

        A location is a reference to a transformation, not a copy of the
        geometry: composing it leaves the TShape shared, so moving a
        thousand objects costs a thousand matrix multiplies, not a
        thousand B-rep copies. A matrix `gp_Trsf` cannot hold — a shear,
        a non-uniform scale — is applied to the geometry instead, which
        is the old cost and the new location is the identity.

        Returns how many of the objects were found.
        """
        moved = 0
        for obj_id, m in transforms.items():
            obj = self.objects.get(obj_id)
            if obj is None:
                continue
            if self._carry_one(obj, np.asarray(m, dtype=float)):
                moved += 1
        if moved:
            self.notify("objects")
        return moved

    def set_drag_display(self, transforms):
        """Show `transforms` (id -> 4x4) while the shapes stand where they
        were. Display only: no revision, no notification — a drag of a few
        hundred objects must not wake the scene on every mouse move."""
        self.drag_display = {k: np.asarray(v, float)
                             for k, v in transforms.items()}

    def clear_drag_display(self):
        """The drag is over; the carried shapes are the truth again."""
        self.drag_display = {}

    def _carry_one(self, obj, m) -> bool:
        """Apply `m` to one object's pose. False if it has no geometry."""
        if obj._shape is None:
            return False
        if isinstance(obj._shape, DeferredShape):
            # a move that lands on a promise converts it first: the pose
            # is for the geometry, and the geometry is not there yet.
            self.realise(obj.id)
            if obj._shape is None:
                return False
        trsf = _trsf_from_matrix(m)
        # Read the pose before the location changes: the `transform`
        # property caches on first read, and a read after the new
        # location is in place would cache the move as the old pose.
        old = obj._location
        old_m = obj.transform
        if trsf is not None and hasattr(obj._shape, "Located"):
            # The pose is composed, the geometry is not touched. The
            # location is built as m @ old, the same order as `_transform`
            # below, so both keep describing the one pose: `Multiplied`
            # applies the argument first, then itself, which is the old
            # pose with the move applied after it.
            obj._location = (TopLoc_Location(trsf).Multiplied(old)
                            if old is not None and not old.IsIdentity()
                            else TopLoc_Location(trsf))
            obj._transform = m @ old_m
            obj._bounds = None
            obj._view_stale()
            # The mesh is of the local geometry, and the local geometry
            # has not moved, so it stays.
            return True
        # Not a location — a shear, a non-uniform scale, or a shape that
        # cannot carry one: apply it to the geometry and start from the
        # identity, the way a rebuilt geometry does.
        obj._shape = geometry.apply_matrix(obj._shape, m @ old_m)
        obj._location = None
        obj._transform = None
        obj._mesh = None
        obj._bounds = None
        obj._view_stale()
        return True

    def add_record(self, op: str, inputs: list, output: str, **params):
        """Remember how an object was built (record history)."""
        self.history_records.append({"op": op, "inputs": list(inputs),
                                     "output": output, "params": params})

    def _regenerate_dependents(self, changed_id: str):
        """Rebuild recorded outputs whose inputs changed, transitively."""
        if self._regen_active or not self.history_records:
            return
        self._regen_active = True
        try:
            queue = [changed_id]
            seen = set()
            while queue:
                cid = queue.pop(0)
                for rec in self.history_records:
                    if cid not in rec["inputs"] or rec["output"] in seen:
                        continue
                    seen.add(rec["output"])
                    old = self.objects.get(rec["output"])
                    parents = [self.objects.get(i) for i in rec["inputs"]]
                    if old is None or any(p is None for p in parents):
                        continue
                    try:
                        shape = _rebuild_record(rec,
                                                [p.shape for p in parents])
                    except Exception:              # noqa: BLE001
                        continue                   # keep the stale child
                    self.objects[rec["output"]] = replace(
                        old, _shape=shape, kind=geometry.shape_kind(shape),
                        _mesh=None)
                    queue.append(rec["output"])
        finally:
            self._regen_active = False

    def update(self, obj_id: str, **fields) -> SceneObject:
        was_visible = self.objects[obj_id].visible
        new = replace(self.objects[obj_id], **fields)
        self.objects[obj_id] = new
        # Most of what a real drawing defers is hidden object by object on a
        # layer that is switched on, so this is the trigger that does the
        # work, not the layer one. Here rather than when the viewport gets
        # round to it: converting can leave nothing and remove the object,
        # and the middle of a draw is no place to discover that.
        if new.visible and not was_visible and not new.shape_ready:
            if self.realise(obj_id) is None:
                return new
        self.notify("objects")
        return new

    def update_many(self, ids, **fields) -> int:
        """Change the same fields on every object in `ids`. Returns how many.

        One notification for the lot, not one an object: hiding a thousand
        objects is one change to the drawing and should cost the listeners
        what hiding one does.
        """
        ids = list(ids)
        with self.batched():
            for obj_id in ids:
                self.update(obj_id, **fields)
        return len(ids)

    def get(self, obj_id: str) -> SceneObject | None:
        return self.objects.get(obj_id)

    def find_by_name(self, name: str) -> SceneObject | None:
        for obj in self.all():
            if obj.name.lower() == name.lower():
                return obj
        return None

    def all(self) -> list[SceneObject]:
        return [self.objects[i] for i in self._order]

    def visible_objects(self) -> list[SceneObject]:
        # is_visible, not the layer's own switch: a layer under a parent
        # that is off is off, whatever its own switch says.
        return [o for o in self.all()
                if o.visible and self.layers.is_visible(o.layer_id)]

    def selectable_objects(self) -> list[SceneObject]:
        return [o for o in self.visible_objects()
                if not o.locked and not self.layers.is_locked(o.layer_id)]

    def is_selectable(self, obj_id: str) -> bool:
        obj = self.get(obj_id)
        return (obj is not None and obj.visible and not obj.locked
                and self.layers.is_visible(obj.layer_id)
                and not self.layers.is_locked(obj.layer_id))

    def expand_group_ids(self, ids: list[str]) -> list[str]:
        """Grow a selection to whole groups."""
        groups = {self.objects[i].group_id for i in ids
                  if i in self.objects and self.objects[i].group_id}
        if not groups:
            return list(ids)
        out = list(ids)
        for o in self.selectable_objects():
            if o.group_id in groups and o.id not in out:
                out.append(o.id)
        return out

    def color_of(self, obj: SceneObject) -> tuple[float, float, float]:
        return obj.color or self.layers.get(obj.layer_id).color

    def print_width_of(self, obj: SceneObject) -> float:
        """The pen width, in mm, a plot draws this object with.

        Taken off the layer: an object plots at its layer's print width, and
        0 means the device default, the same as Rhino's PlotWeight.
        """
        return self.layers.get(obj.layer_id).print_width

    def hatch_of(self, obj: SceneObject) -> str:
        """The fill a cut through this object is drawn with, or nothing.

        Taken off the layer, the way the print width is: what a thing is
        made of belongs to the layer it is on, so a section through it
        reads as concrete or as steel without anybody hatching it by hand.
        """
        return self.layers.get(obj.layer_id).hatch

    def render_color_of(self, obj: SceneObject) -> tuple[float, float, float]:
        """The colour rendered mode draws the object's surfaces in.

        An object carries two colours, the way it does in Rhino: the one it
        displays, which is the layer's unless it says otherwise, and the one on
        its material. A drawing set up for rendering usually leaves every
        object on its layer colour and puts the real colours on materials, so
        the two are meant to differ (#4). Materials made in the app have no
        colour of their own, and those objects render the colour they display.
        """
        return (obj.material or {}).get("color") or self.color_of(obj)

    def clear(self):
        self.objects.clear()
        self._order.clear()
        self._counters.clear()
        self.layers = LayerManager()
        self.layers.on_shown = self.realise_layer
        self.named_views = {}
        self.layouts = []
        self.block_defs = {}
        self.annot_styles = {}
        self.image_planes = []
        self.history_records = []
        self.trajectories = []
        self.session = None
        # units are a user preference as much as a document property: keep
        self.notify()

    def format_length(self, value: float) -> str:
        from ..utils.units import format_length
        return format_length(value, self.units)

    def bbox(self) -> tuple[tuple, tuple] | None:
        objs = self.visible_objects()
        if not objs:
            return None
        boxes = np.array([o.bbox() for o in objs], float)
        return (tuple(boxes[:, 0].min(axis=0)),
                tuple(boxes[:, 1].max(axis=0)))

    # -- snapshot (undo/redo) --
    def snapshot(self) -> dict:
        import copy
        return {
            "units": self.units,
            "objects": {k: v.clone() for k, v in self.objects.items()},
            "order": list(self._order),
            "counters": dict(self._counters),
            "layers": self.layers.snapshot(),
            "named_views": copy.deepcopy(self.named_views),
            "layouts": [lay.clone() for lay in self.layouts],
            "block_defs": {k: dict(v) for k, v in self.block_defs.items()},
            "annot_styles": {k: dict(v) for k, v in self.annot_styles.items()},
            "image_planes": copy.deepcopy(self.image_planes),
            "history_records": copy.deepcopy(self.history_records),
            # By reference, not deep-copied: a trajectory is tens of
            # thousands of poses that nothing in the app edits, and undo
            # takes a snapshot every command.
            "trajectories": self.trajectories,
            "session": self.session,
        }

    def restore(self, snap: dict):
        import copy
        self.units = snap.get("units", self.units)
        self.objects = {k: v.clone() for k, v in snap["objects"].items()}
        self._order = list(snap["order"])
        self._counters = dict(snap["counters"])
        self.layers.restore(snap["layers"])
        self.named_views = copy.deepcopy(snap.get("named_views", {}))
        self.layouts = [lay.clone() for lay in snap.get("layouts", [])]
        self.block_defs = {k: dict(v) for k, v in
                           snap.get("block_defs", {}).items()}
        self.annot_styles = {k: dict(v) for k, v in
                             snap.get("annot_styles", {}).items()}
        if not any(obj.kind == "picture" for obj in self.all()):
            self.image_planes = copy.deepcopy(snap.get("image_planes", []))
        self.history_records = copy.deepcopy(
            snap.get("history_records", []))
        self.trajectories = snap.get("trajectories", [])
        self.session = snap.get("session")
        self.notify()
