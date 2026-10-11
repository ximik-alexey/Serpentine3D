// _mesh_extract.cpp — batch mesh extraction from OCCT.
// extract(): single shape or compound. For compounds, returns per-child
// offsets so Python can slice the flat arrays back per-object.

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>

#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Iterator.hxx>
#include <TopExp_Explorer.hxx>
#include <TopAbs_ShapeEnum.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRep_Tool.hxx>
#include <Poly_Triangulation.hxx>
#include <TopLoc_Location.hxx>
#include <gp_Trsf.hxx>
#include <gp_Pnt.hxx>
#include <set>
#include <GCPnts_TangentialDeflection.hxx>
#include <BRepAdaptor_Curve.hxx>

#include <vector>
#include <cstring>
#include <cmath>

namespace py = pybind11;

py::tuple extract_mesh(py::object shape_obj, double deflection, bool do_mesh) {
    const TopoDS_Shape& shape = py::cast<const TopoDS_Shape&>(shape_obj);
    if (do_mesh) {
        BRepMesh_IncrementalMesh mesher(shape, deflection, false, 0.35, true);
    }

    std::vector<float> verts, norms, edges;
    std::vector<uint32_t> tris;
    std::vector<int64_t> child_v, child_t, child_e;  // per-child start offsets

    bool is_compound = (shape.ShapeType() == TopAbs_COMPOUND);
    const gp_Trsf& shape_trsf = shape.Location().Transformation();

    if (is_compound) {
        // Record child count for offsets
        TopoDS_Iterator it(shape);
        int nchild = 0;
        while (it.More()) { (void)it.Value(); it.Next(); nchild++; }
        child_v.resize(nchild, -1);
        child_t.resize(nchild, -1);
        child_e.resize(nchild, -1);

        // Faces: track which child each face belongs to
        {
            int child_idx = -1;
            TopoDS_Iterator cit(shape);
            while (cit.More()) {
                child_idx++;
                const TopoDS_Shape& child = cit.Value();
                int v_start = int(verts.size() / 3);
                int t_start = int(tris.size() / 3);
                child_v[child_idx] = v_start;
                child_t[child_idx] = t_start;

                TopExp_Explorer fexp(child, TopAbs_FACE);
                uint32_t voffset = uint32_t(verts.size() / 3);
                while (fexp.More()) {
                    TopoDS_Face face = TopoDS::Face(fexp.Current());
                    TopLoc_Location loc;
                    Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(face, loc);
                    if (!tri.IsNull()) {
                        int n = tri->NbNodes();
                        int m = tri->NbTriangles();
                        const gp_Trsf& trsf = loc.Transformation();
                        const bool rev = (face.Orientation() == TopAbs_REVERSED);
                        for (int i = 1; i <= n; ++i) {
                            gp_Pnt p = tri->Node(i).Transformed(trsf);
                            verts.push_back(float(p.X()));
                            verts.push_back(float(p.Y()));
                            verts.push_back(float(p.Z()));
                        }
                        for (int i = 1; i <= m; ++i) {
                            const Poly_Triangle& t = tri->Triangle(i);
                            uint32_t a = uint32_t(t.Value(1)) - 1 + voffset;
                            uint32_t b = uint32_t(t.Value(2)) - 1 + voffset;
                            uint32_t c = uint32_t(t.Value(3)) - 1 + voffset;
                            if (rev) {
                                tris.push_back(a); tris.push_back(c); tris.push_back(b);
                            } else {
                                tris.push_back(a); tris.push_back(b); tris.push_back(c);
                            }
                        }
                        voffset += uint32_t(n);
                    }
                    fexp.Next();
                }
                cit.Next();
            }
        }

        // Edges
        {
            int child_idx = -1;
            TopoDS_Iterator cit(shape);
            while (cit.More()) {
                child_idx++;
                const TopoDS_Shape& child = cit.Value();
                int e_start = int(edges.size() / 6);
                child_e[child_idx] = e_start;

                std::set<size_t> seen_edges;
                TopExp_Explorer eexp(child, TopAbs_EDGE);
                while (eexp.More()) {
                    TopoDS_Edge edge = TopoDS::Edge(eexp.Current());
                    size_t key = std::hash<TopoDS_Shape>{}(edge);
                    if (seen_edges.count(key)) { eexp.Next(); continue; }
                    seen_edges.insert(key);
                    TopLoc_Location eloc;
                    double first, last;
                    Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, eloc, first, last);
                    if (!curve.IsNull()) {
                        BRepAdaptor_Curve adaptor(edge);
                        GCPnts_TangentialDeflection gpts(adaptor, deflection, deflection);
                        int npts = gpts.NbPoints();
                        if (npts < 2) npts = 2;
                        const gp_Trsf etrf = gp_Trsf();
                        gp_Pnt prev = gpts.Value(1).Transformed(etrf);
                        for (int i = 2; i <= npts; ++i) {
                            gp_Pnt p = gpts.Value(i).Transformed(etrf);
                            edges.push_back(float(prev.X()));
                            edges.push_back(float(prev.Y()));
                            edges.push_back(float(prev.Z()));
                            edges.push_back(float(p.X()));
                            edges.push_back(float(p.Y()));
                            edges.push_back(float(p.Z()));
                            prev = p;
                        }
                    }
                    eexp.Next();
                }
                cit.Next();
            }
        }
    } else {
        // Non-compound: flat iteration
        uint32_t voffset = 0;
        TopExp_Explorer fexp(shape, TopAbs_FACE);
        while (fexp.More()) {
            TopoDS_Face face = TopoDS::Face(fexp.Current());
            TopLoc_Location loc;
            Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(face, loc);
            if (!tri.IsNull()) {
                int n = tri->NbNodes();
                int m = tri->NbTriangles();
                const gp_Trsf& trsf = loc.Transformation();
                const bool rev = (face.Orientation() == TopAbs_REVERSED);
                for (int i = 1; i <= n; ++i) {
                    gp_Pnt p = tri->Node(i).Transformed(trsf);
                    verts.push_back(float(p.X()));
                    verts.push_back(float(p.Y()));
                    verts.push_back(float(p.Z()));
                }
                for (int i = 1; i <= m; ++i) {
                    const Poly_Triangle& t = tri->Triangle(i);
                    uint32_t a = uint32_t(t.Value(1)) - 1 + voffset;
                    uint32_t b = uint32_t(t.Value(2)) - 1 + voffset;
                    uint32_t c = uint32_t(t.Value(3)) - 1 + voffset;
                    if (rev) {
                        tris.push_back(a); tris.push_back(c); tris.push_back(b);
                    } else {
                        tris.push_back(a); tris.push_back(b); tris.push_back(c);
                    }
                }
                voffset += uint32_t(n);
            }
            fexp.Next();
        }

        std::set<size_t> seen_edges;
        TopExp_Explorer eexp(shape, TopAbs_EDGE);
        while (eexp.More()) {
            TopoDS_Edge edge = TopoDS::Edge(eexp.Current());
            size_t key = std::hash<TopoDS_Shape>{}(edge);
            if (seen_edges.count(key)) { eexp.Next(); continue; }
            seen_edges.insert(key);
            TopLoc_Location eloc;
            double first, last;
            Handle(Geom_Curve) curve = BRep_Tool::Curve(edge, eloc, first, last);
            if (!curve.IsNull()) {
                BRepAdaptor_Curve adaptor(edge);
                GCPnts_TangentialDeflection gpts(adaptor, deflection, deflection);
                int npts = gpts.NbPoints();
                if (npts < 2) npts = 2;
                const gp_Trsf etrf = gp_Trsf();
                gp_Pnt prev = gpts.Value(1).Transformed(etrf);
                for (int i = 2; i <= npts; ++i) {
                    gp_Pnt p = gpts.Value(i).Transformed(etrf);
                    edges.push_back(float(prev.X()));
                    edges.push_back(float(prev.Y()));
                    edges.push_back(float(prev.Z()));
                    edges.push_back(float(p.X()));
                    edges.push_back(float(p.Y()));
                    edges.push_back(float(p.Z()));
                    prev = p;
                }
            }
            eexp.Next();
        }
    }

    // Normals
    int nv = int(verts.size() / 3);
    norms.assign(nv * 3, 0.0f);
    for (size_t i = 0; i < tris.size(); i += 3) {
        int a = tris[i], b = tris[i+1], c = tris[i+2];
        float e1x=verts[b*3]-verts[a*3], e1y=verts[b*3+1]-verts[a*3+1], e1z=verts[b*3+2]-verts[a*3+2];
        float e2x=verts[c*3]-verts[a*3], e2y=verts[c*3+1]-verts[a*3+1], e2z=verts[c*3+2]-verts[a*3+2];
        float nx=e1y*e2z-e1z*e2y, ny=e1z*e2x-e1x*e2z, nz=e1x*e2y-e1y*e2x;
        norms[a*3]+=nx; norms[a*3+1]+=ny; norms[a*3+2]+=nz;
        norms[b*3]+=nx; norms[b*3+1]+=ny; norms[b*3+2]+=nz;
        norms[c*3]+=nx; norms[c*3+1]+=ny; norms[c*3+2]+=nz;
    }
    for (int i = 0; i < nv; ++i) {
        float x=norms[i*3], y=norms[i*3+1], z=norms[i*3+2];
        float len=std::sqrt(x*x+y*y+z*z);
        if (len > 1e-12f) { norms[i*3]=x/len; norms[i*3+1]=y/len; norms[i*3+2]=z/len; }
    }

    // Build return arrays
    size_t nv2 = verts.size() / 3;
    size_t nt2 = tris.size() / 3;
    size_t ne2 = edges.size() / 6;
    py::array_t<float> varr(nv2 * 3);
    std::memcpy(varr.mutable_data(), verts.data(), verts.size() * sizeof(float));
    py::array_t<float> narr(nv2 * 3);
    std::memcpy(narr.mutable_data(), norms.data(), norms.size() * sizeof(float));
    py::array_t<uint32_t> tarr(nt2 * 3);
    std::memcpy(tarr.mutable_data(), tris.data(), tris.size() * sizeof(uint32_t));
    py::array_t<float> earr(ne2 * 6);
    std::memcpy(earr.mutable_data(), edges.data(), edges.size() * sizeof(float));

    // Child offsets (empty for non-compound)
    py::array_t<int64_t> cv(child_v.size());
    if (!child_v.empty())
        std::memcpy(cv.mutable_data(), child_v.data(), child_v.size() * sizeof(int64_t));
    py::array_t<int64_t> ct(child_t.size());
    if (!child_t.empty())
        std::memcpy(ct.mutable_data(), child_t.data(), child_t.size() * sizeof(int64_t));
    py::array_t<int64_t> ce(child_e.size());
    if (!child_e.empty())
        std::memcpy(ce.mutable_data(), child_e.data(), child_e.size() * sizeof(int64_t));

    return py::make_tuple(varr, narr, tarr, earr, cv, ct, ce);
}

PYBIND11_MODULE(_mesh_extract, m) {
    m.def("extract", &extract_mesh,
          py::arg("shape"), py::arg("deflection"), py::arg("do_mesh") = true,
          "Batch → (verts, norms, tris, edges, child_v, child_t, child_e)");
}
