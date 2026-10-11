# Migration Plan: OCP → pythonocc-core

## Rule
Same function name → keep. Different name → adapt.

## 0. Install

```bash
pip uninstall OCP -y
pip install pythonocc-core
python -c "import OCP; print(OCP.__version__)"
```

Both install as package `OCP`. All `from OCP.xxx import yyy` imports stay.

## 1. `_s` suffix methods (OCP-only, 17 occurrences)

pythonocc-core has NO `_s` suffix. All become the base name.

| OCP (current) | pythonocc-core | Arg change |
|---|---|---|
| `TopoDS.Edge_s(shape)` | `TopoDS.Edge(shape)` | same |
| `TopoDS.Face_s(shape)` | `TopoDS.Face(shape)` | same |
| `TopoDS.Wire_s(shape)` | `TopoDS.Wire(shape)` | same |
| `TopoDS.Shell_s(shape)` | `TopoDS.Shell(shape)` | same |
| `TopoDS.Solid_s(shape)` | `TopoDS.Solid(shape)` | same |
| `TopoDS.Vertex_s(shape)` | `TopoDS.Vertex(shape)` | same |
| `TopoDS.Compound_s(shape)` | `TopoDS.Compound(shape)` | same |
| `BRep_Tool.Curve_s(edge, 0, 0)` | `BRep_Tool.Curve(edge, loc, 0, 0)` | +Location |
| `BRep_Tool.Surface_s(face)` | `BRep_Tool.Surface(face, loc)` | +Location |
| `BRep_Tool.Pnt_s(vertex)` | `BRep_Tool.Pnt(vertex, loc)` | +Location |
| `BRep_Tool.Triangulation_s(face, loc)` | `BRep_Tool.Triangulation(face, loc)` | same |
| `BRep_Tool.Degenerated_s(edge)` | `BRep_Tool.Degenerated(edge)` | same |
| `BRep_Tool.IsClosed_s(shell)` | `BRep_Tool.IsClosed(shell)` | same |
| `GeomConvert.SurfaceToBSplineSurface_s(x)` | `GeomConvert.SurfaceToBSplineSurface(x)` | same |
| `GeomConvert.CurveToBSplineCurve_s(x)` | `GeomConvert.CurveToBSplineCurve(x)` | same |

**Pattern**: add `TopLoc_Location()` where required.

## 2. Handle wrapper (OCP-only)

OCP: `Handle(Geom_Curve)` wraps a curve. pythonocc: no Handle, object directly.

```python
# OCP
h = BRep_Tool.Curve_s(edge, 0, 0)
if h is not None:
    c = h()  # unwrap
    c.Value(t)

# pythonocc
c = BRep_Tool.Curve(edge, loc, 0, 0)
if c is not None:
    c.Value(t)  # direct
```

## 3. Precision (instance → class)

```python
# OCP
p = Precision()
p.Confusion()  # 0.01

# pythonocc
Precision.Confusion()  # class method
```

## 4. Same in both (NO change needed)

- `BRep_Builder`, `BRepAdaptor_Curve`, `BRepAdaptor_Surface`
- `GCPnts_TangentialDeflection`, `GCPnts_UniformAbscissa`
- `BRepMesh_IncrementalMesh` (check arg count)
- `TopExp_Explorer`, `TopoDS_Iterator`, `TopLoc_Location`
- `gp_Pnt`, `gp_Vec`, `gp_Dir`, `gp_Ax2`, `gp_Trsf`, `gp_Pln`
- `TColgp_Array1OfPnt`, `TColStd_Array1OfReal`
- `BRepAlgoAPI_Cut/Fuse/Section/Common`
- `BRepOffsetAPI_*`, `BRepFilletAPI_*`, `BRepBuilderAPI_*`
- `ShapeFix_*`, `ShapeUpgrade_*`, `BRepCheck_*`
- `HLRBRep_Algo`, `HLRBRep_HLRToShape`, `HLRAlgo_Projector`
- `BRepGProp`, `GProp_GProps`, `BRepExtrema_*`
- `Bnd_Box`, `Precision`
- `TopAbs_*` enums
- `IFSelect_ReturnStatus`, `Interface_Static`
- `Geom_*` (BSpline, Bezier, Cylindrical, Rectangular, Trimmed)
- `Geom2d_*`, `Geom2dAPI_*`, `GeomAPI_*`
- `GeomAbs_*` enums
- `BRepTools`, `BRepTools_WireExplorer`
- `TopTools_*`
- `BRepBndLib`, `BRepClass3d_*`, `BRepTopAdaptor_*`
- `ChFi2d_*`, `GC_*`
- `BRepProj_Projection`, `BRepLProp_*`
- `BinTools` (check Write signature)
- `Poly_Triangulation`

## 5. BRepMesh_IncrementalMesh (arg count)

```python
# OCP
BRepMesh_IncrementalMesh(shape, defl, False, False, False, True)

# pythonocc
BRepMesh_IncrementalMesh(shape, defl)  # 2 args
```

## 6. Files to edit (priority order)

| File | `_s` calls | Other |
|---|---|---|
| `core/geometry.py` | 6 | Handle, Precision |
| `core/occ.py` | 8 | helper wrappers |
| `core/deform.py` | 2 | GeomConvert |
| `fileio/rhino.py` | 5 | TopoDS casts |
| `gpu/__init__.py` | 1 | Surface_s |
| `core/tessellate.py` | 0 | BRepMesh args |
| `fileio/native.py` | 0 | BinTools |

## 7. Steps

1. `pip uninstall OCP -y && pip install pythonocc-core`
2. Verify import: `python -c "from OCP.BRep import BRep_Tool; print('ok')"`
3. Bulk rename `_s` → base (17 lines, 7 files)
4. Add `TopLoc_Location()` where required
5. Remove `Handle()` wrappers
6. Fix `Precision()` → `Precision.`
7. Fix `BRepMesh_IncrementalMesh` arg count
8. Run all tests
9. Benchmark test_01.serp load

## 8. Risk

- `BRep_Tool.Curve` returns `None` for degenerate edges (same as OCP)
- `BRep_Tool.Surface` requires `TopLoc_Location` arg
- `BinTools.Write` signature may differ
- Some `TColgp`/`TColStd` array methods may differ
- pythonocc-core is SWIG-based (slower than OCP's pybind11 for tight loops)
