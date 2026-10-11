"""Kernel binding layer.

Serpentine3D talks to OpenCASCADE through this module only. It binds via
pythonocc-core (the Core package over the local OCCT 8.0.1 build); the class
names match the OCCT layout, so the rest of the app imports from here.
"""

from Core.BinTools import bintools as _bintools
from Core.Bnd import Bnd_Box
from Core.BRep import BRep_Tool
from Core.BRepAdaptor import BRepAdaptor_Curve
from Core.BRepBndLib import brepbndlib
from Core.BRepGProp import brepgprop
from Core.BRepLib import breplib
from Core.GeomAbs import GeomAbs_Shape
from Core.gp import (
    gp_Pnt, gp_Vec, gp_Dir, gp_Ax1, gp_Ax2, gp_Ax3, gp_Pln, gp_Trsf,
    gp_GTrsf, gp_Circ, gp_Elips, gp_XYZ, gp_Quaternion, gp_Mat,
    gp_Pnt2d,
)
from Core.GProp import GProp_GProps
from Core.TopAbs import TopAbs_ShapeEnum
from Core.TopExp import topexp as TopExp, TopExp_Explorer
from Core.TopLoc import TopLoc_Location
from Core.TopoDS import (
    TopoDS_Compound,
    TopoDS_Edge,
    TopoDS_Face,
    TopoDS_Shape,
    TopoDS_Shell,
    TopoDS_Solid,
    TopoDS_Vertex,
    TopoDS_Wire,
)
from Core.TopTools import (
    TopTools_IndexedMapOfShape,
)
from Core.BRep import BRep_Builder
from Core.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeVertex, BRepBuilderAPI_Transform,
    BRepBuilderAPI_GTransform, BRepBuilderAPI_Copy,
    BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid,
)
from Core.BRepPrimAPI import (
    BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol, BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeSphere, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeTorus,
)
from Core.BRepAlgoAPI import (
    BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut, BRepAlgoAPI_Common,
    BRepAlgoAPI_Splitter,
)
from Core.BRepOffsetAPI import (
    BRepOffsetAPI_ThruSections, BRepOffsetAPI_MakePipe,
    BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_MakeOffset,
)
from Core.GC import GC_MakeArcOfCircle, GC_MakeSegment, GC_MakeCircle
from Core.GeomAPI import GeomAPI_Interpolate, GeomAPI_PointsToBSpline
from Core.Geom import (
    Geom_BSplineCurve, Geom_Circle, Geom_TrimmedCurve, Geom_Plane,
    Geom_Ellipse, Geom_Line,
)
from Core.TColgp import TColgp_Array1OfPnt, TColgp_HArray1OfPnt
from Core.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
from Core.BRepCheck import BRepCheck_Analyzer
from Core.TopoDS import TopoDS_Iterator
from Core.BRepMesh import BRepMesh_IncrementalMesh
from Core.BRepFilletAPI import BRepFilletAPI_MakeFillet, BRepFilletAPI_MakeChamfer
from Core.ChFi2d import ChFi2d_FilletAPI
from Core.GeomAbs import GeomAbs_JoinType, GeomAbs_CurveType, GeomAbs_C2
from Core.GCPnts import GCPnts_TangentialDeflection, GCPnts_UniformDeflection
from Core.GeomConvert import geomconvert as GeomConvert
from Core.BRepTools import breptools as BRepTools
from Core.TopAbs import TopAbs_Orientation, TopAbs_State
from Core.ShapeAnalysis import ShapeAnalysis_FreeBounds
from Core.TopTools import TopTools_ListOfShape
from Core.BRepBuilderAPI import BRepBuilderAPI_MakePolygon

BACKEND = "Core"

__all__ = [
    "BACKEND",
    "Bnd_Box",
    "BRep_Tool",
    "BRep_Builder",
    "BRepAdaptor_Curve",
    "brepbndlib",
    "brepgprop",
    "breplib",
    "breptools",
    "GeomAbs_Shape",
    "gp_Pnt", "gp_Vec", "gp_Dir", "gp_Ax1", "gp_Ax2", "gp_Ax3", "gp_Pln",
    "gp_Trsf", "gp_GTrsf", "gp_Circ", "gp_Elips", "gp_XYZ",
    "gp_Quaternion", "gp_Mat", "gp_Pnt2d",
    "GProp_GProps",
    "TopAbs_ShapeEnum",
    "TopAbs_Orientation",
    "TopAbs_State",
    "TopExp",
    "TopExp_Explorer",
    "TopLoc_Location",
    "TopoDS_Compound",
    "TopoDS_Edge",
    "TopoDS_Face",
    "TopoDS_Shape",
    "TopoDS_Shell",
    "TopoDS_Solid",
    "TopoDS_Vertex",
    "TopoDS_Wire",
    "TopoDS_Iterator",
    "TopTools_IndexedMapOfShape",
    "TopTools_ListOfShape",
    "BRepBuilderAPI_MakeEdge",
    "BRepBuilderAPI_MakeWire",
    "BRepBuilderAPI_MakeFace",
    "BRepBuilderAPI_MakeVertex",
    "BRepBuilderAPI_Transform",
    "BRepBuilderAPI_GTransform",
    "BRepBuilderAPI_Copy",
    "BRepBuilderAPI_Sewing",
    "BRepBuilderAPI_MakeSolid",
    "BRepBuilderAPI_MakePolygon",
    "BRepPrimAPI_MakePrism",
    "BRepPrimAPI_MakeRevol",
    "BRepPrimAPI_MakeBox",
    "BRepPrimAPI_MakeSphere",
    "BRepPrimAPI_MakeCylinder",
    "BRepPrimAPI_MakeCone",
    "BRepPrimAPI_MakeTorus",
    "BRepAlgoAPI_Fuse",
    "BRepAlgoAPI_Cut",
    "BRepAlgoAPI_Common",
    "BRepAlgoAPI_Splitter",
    "BRepOffsetAPI_ThruSections",
    "BRepOffsetAPI_MakePipe",
    "BRepOffsetAPI_MakePipeShell",
    "BRepOffsetAPI_MakeOffset",
    "GC_MakeArcOfCircle",
    "GC_MakeSegment",
    "GC_MakeCircle",
    "GeomAPI_Interpolate",
    "GeomAPI_PointsToBSpline",
    "Geom_BSplineCurve",
    "Geom_Circle",
    "Geom_TrimmedCurve",
    "Geom_Plane",
    "Geom_Ellipse",
    "Geom_Line",
    "TColgp_Array1OfPnt",
    "TColgp_HArray1OfPnt",
    "TColStd_Array1OfReal",
    "TColStd_Array1OfInteger",
    "BRepCheck_Analyzer",
    "BRepMesh_IncrementalMesh",
    "BRepFilletAPI_MakeFillet",
    "BRepFilletAPI_MakeChamfer",
    "ChFi2d_FilletAPI",
    "GeomAbs_JoinType",
    "GeomAbs_CurveType",
    "GeomAbs_C2",
    "GCPnts_TangentialDeflection",
    "GCPnts_UniformDeflection",
    "GeomConvert",
    "BRepTools",
    "ShapeAnalysis_FreeBounds",
]


# --- downcasts -------------------------------------------------------------

def to_edge(shape) -> TopoDS_Edge:
    return shape

def to_wire(shape) -> TopoDS_Wire:
    return shape

def to_face(shape) -> TopoDS_Face:
    return shape

def to_shell(shape) -> TopoDS_Shell:
    return shape

def to_solid(shape) -> TopoDS_Solid:
    return shape

def to_vertex(shape) -> TopoDS_Vertex:
    return shape

def to_compound(shape) -> TopoDS_Compound:
    return shape

# --- static wrappers (pythonocc-core naming) -----------------------------

def triangulation(face, loc: TopLoc_Location):
    return BRep_Tool.Triangulation(face, loc)

def edge_adaptor(edge) -> BRepAdaptor_Curve:
    """Parametric access to an edge's curve (Value/FirstParameter/LastParameter)."""
    try:
        return BRepAdaptor_Curve(edge)
    except TypeError:
        # A generic TopoDS_Shape proxy (e.g. from .Located()): the adaptor
        # needs the edge typed back, so re-type it through the explorer.
        return BRepAdaptor_Curve(TopExp_Explorer(edge, EDGE).Current())

def point_of_vertex(vertex) -> gp_Pnt:
    return BRep_Tool.Pnt(vertex)

def bbox_add(shape, box: Bnd_Box):
    # Triangulation carries its meshing deflection as an isotropic gap, so a
    # shape's reported bounds used to grow after it had first been drawn.
    # Geometry bounds must stay tied to the B-rep and independent of display.
    # Include the B-rep's own modelling tolerance so mathematically exact
    # extents do not land a fraction below their boundary through conversion.
    brepbndlib.AddOptimal(shape, box, False, True)

def ensure_curves3d(shape):
    """Materialize pcurve-only edges before a native consumer reads them.

    HLR can leave projected B-splines without a 3D curve. OCCT's linear
    properties then dereference a null curve instead of raising an error.
    Build from the existing pcurves, preserving their projected geometry.
    Degenerate edges at sphere poles legitimately have no curve to build.
    """
    if breplib.BuildCurves3d(shape):
        return
    explorer = TopExp_Explorer(shape, EDGE)
    while explorer.More():
        edge = to_edge(explorer.Current())
        if (not BRep_Tool.Degenerated(edge)
                and BRep_Tool.Curve(edge, TopLoc_Location())[0] is None):
            raise ValueError("A curve has no 3D geometry and could not be reconstructed")
        explorer.Next()


def linear_properties(shape) -> GProp_GProps:
    # Also protect projected curves saved by older versions, which bypass
    # the repaired HLR output when their drawing is reopened.
    ensure_curves3d(shape)
    props = GProp_GProps()
    brepgprop.LinearProperties(shape, props)
    return props

def without_creases(shape):
    """`shape` with every face whose surface has a crease in it split there.

    The default integration below samples each face as one smooth piece.
    A surface built as a chain of patches meeting at creases (knots at full
    multiplicity, as Rhino writes a revolved profile) is not one: the sample
    points fall mostly in the long parameter spans and miss the short ones,
    and a mug's body read 20% short, a synthetic one 98% (#34). Split at
    the creases, each piece is smooth and the same method is exact.

    A shape with no creased face comes back as it is, so everything else
    measures exactly as before and pays nothing for the check.
    """
    creased = False
    exp = TopExp_Explorer(shape, FACE)
    while exp.More() and not creased:
        surf = BRep_Tool.Surface(exp.Current(), TopLoc_Location())
        creased = surf is not None and surf.Continuity() == GeomAbs_Shape.GeomAbs_C0
        exp.Next()
    if not creased:
        return shape
    from Core.ShapeUpgrade import ShapeUpgrade_ShapeDivideContinuity
    try:
        split = ShapeUpgrade_ShapeDivideContinuity(shape)
        split.SetBoundaryCriterion(GeomAbs_Shape.GeomAbs_C1)
        split.SetPCurveCriterion(GeomAbs_Shape.GeomAbs_C1)
        split.SetSurfaceSegmentMode(True)
        split.Perform()
        out = split.Result()
    except Exception:                                       # noqa: BLE001
        return shape
    return shape if out is None or out.IsNull() else out

def surface_properties(shape) -> GProp_GProps:
    props = GProp_GProps()
    brepgprop.SurfaceProperties(without_creases(shape), props)
    return props

def volume_properties(shape) -> GProp_GProps:
    props = GProp_GProps()
    brepgprop.VolumeProperties(without_creases(shape), props)
    return props

def brep_write(shape, path: str):
    _bintools.Write(shape, path)

def brep_read(path: str) -> TopoDS_Shape:
    shape = TopoDS_Shape()
    _bintools.Read(shape, path)
    return shape

def map_shapes(shape, kind) -> TopTools_IndexedMapOfShape:
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes(shape, kind, m)
    return m

# shape-type enum shortcuts
VERTEX = TopAbs_ShapeEnum.TopAbs_VERTEX
EDGE = TopAbs_ShapeEnum.TopAbs_EDGE
WIRE = TopAbs_ShapeEnum.TopAbs_WIRE
FACE = TopAbs_ShapeEnum.TopAbs_FACE
SHELL = TopAbs_ShapeEnum.TopAbs_SHELL
SOLID = TopAbs_ShapeEnum.TopAbs_SOLID
COMPSOLID = TopAbs_ShapeEnum.TopAbs_COMPSOLID
COMPOUND = TopAbs_ShapeEnum.TopAbs_COMPOUND
