// C++ wrapper for STEP/IGES I/O — bypasses broken SWIG modules.
// Read: STEP/IGES file → tessellated mesh (vertices + triangles)
// Write: mesh file → planar-face BREP → STEP/IGES file

#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <vector>
#include <cmath>

#include "STEPControl_Reader.hxx"
#include "STEPControl_Writer.hxx"
#include "IGESControl_Reader.hxx"
#include "IGESControl_Writer.hxx"
#include "IFSelect_ReturnStatus.hxx"
#include "TopoDS_Shape.hxx"
#include "TopoDS_Face.hxx"
#include "TopoDS_Shell.hxx"
#include "TopoDS_Solid.hxx"
#include "TopExp_Explorer.hxx"
#include "BRepMesh_IncrementalMesh.hxx"
#include "BRep_Tool.hxx"
#include "TopLoc_Location.hxx"
#include "Poly_Triangulation.hxx"
#include "BRepBuilderAPI_MakeEdge.hxx"
#include "BRepBuilderAPI_MakeFace.hxx"
#include "BRepBuilderAPI_MakeShell.hxx"
#include "Geom_Plane.hxx"
#include "BRepBuilderAPI_MakeSolid.hxx"
#include <fstream>

// Multi-mesh file format:
//   [4B: n_meshes]
//   per mesh: [4B nv] [4B nt] [nv*12B float xyz] [nt*12B int ijk]

static int read_to_meshes(const char* path, const char* out_path,
                          bool is_step) {
    try {
        std::vector<TopoDS_Shape> shapes;
        auto collect = [&](STEPControl_Reader& r) {
            r.TransferRoots();
            for (int i = 1; i <= r.NbShapes(); ++i) {
                TopoDS_Shape s = r.Shape(i);
                if (s.IsNull()) continue;
                if (s.ShapeType() == TopAbs_COMPOUND) {
                    TopExp_Explorer it(s, TopAbs_SOLID);
                    bool found = false;
                    while (it.More()) {
                        shapes.push_back(it.Current());
                        found = true;
                        it.Next();
                    }
                    if (!found) shapes.push_back(s);
                } else {
                    shapes.push_back(s);
                }
            }
        };
        auto collect_iges = [&](IGESControl_Reader& r) {
            r.TransferRoots();
            for (int i = 1; i <= r.NbShapes(); ++i) {
                TopoDS_Shape s = r.Shape(i);
                if (s.IsNull()) continue;
                if (s.ShapeType() == TopAbs_COMPOUND) {
                    TopExp_Explorer it(s, TopAbs_SOLID);
                    bool found = false;
                    while (it.More()) {
                        shapes.push_back(it.Current());
                        found = true;
                        it.Next();
                    }
                    if (!found) shapes.push_back(s);
                } else {
                    shapes.push_back(s);
                }
            }
        };
        if (is_step) {
            STEPControl_Reader r;
            if (r.ReadFile(path) != IFSelect_RetDone) return 1;
            collect(r);
        } else {
            IGESControl_Reader r;
            if (r.ReadFile(path) != IFSelect_RetDone) return 1;
            collect_iges(r);
        }
        if (shapes.empty()) return 1;

        // Tessellate each shape independently
        struct MeshData {
            std::vector<float> verts;
            std::vector<int> tris;
        };
        std::vector<MeshData> meshes;

        TopLoc_Location loc;
        for (const auto& s : shapes) {
            BRepMesh_IncrementalMesh(s, 0.005, false, 0.35, true);
            MeshData md;
            TopExp_Explorer exp(s, TopAbs_FACE);
            while (exp.More()) {
                Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(
                    *reinterpret_cast<const TopoDS_Face*>(&exp.Current()), loc);
                if (!tri.IsNull()) {
                    int nn = tri->NbNodes();
                    int nt_ = tri->NbTriangles();
                    int base = (int)md.verts.size() / 3;
                    for (int i = 1; i <= nn; ++i) {
                        const gp_Pnt& p = tri->Node(i);
                        md.verts.push_back((float)p.X());
                        md.verts.push_back((float)p.Y());
                        md.verts.push_back((float)p.Z());
                    }
                    for (int i = 1; i <= nt_; ++i) {
                        int a = tri->Triangle(i).Value(1);
                        int b = tri->Triangle(i).Value(2);
                        int c = tri->Triangle(i).Value(3);
                        md.tris.push_back(base + a - 1);
                        md.tris.push_back(base + b - 1);
                        md.tris.push_back(base + c - 1);
                    }
                }
                exp.Next();
            }
            if (!md.verts.empty())
                meshes.push_back(std::move(md));
        }
        if (meshes.empty()) return 1;

        // Write multi-mesh file
        std::ofstream ofs(out_path, std::ios::binary);
        if (!ofs) return 1;
        int nm = (int)meshes.size();
        ofs.write((const char*)&nm, 4);
        for (const auto& md : meshes) {
            int nv = (int)md.verts.size() / 3;
            int nt = (int)md.tris.size() / 3;
            ofs.write((const char*)&nv, 4);
            ofs.write((const char*)&nt, 4);
            ofs.write((const char*)md.verts.data(), nv * 12);
            ofs.write((const char*)md.tris.data(), nt * 12);
        }
        return 0;
    } catch (...) { return 1; }
}

extern "C" int step_read(const char* p, const char* m) {
    return read_to_meshes(p, m, true);
}
extern "C" int iges_read(const char* p, const char* m) {
    return read_to_meshes(p, m, false);
}
extern "C" int mesh_write_step(const char* m, const char* p) {
    (void)m; (void)p;
    return 1; // TODO: mesh→BREP→STEP (API 8.0.1)
}
extern "C" int mesh_write_iges(const char* m, const char* p) {
    (void)m; (void)p;
    return 1; // TODO: mesh→BREP→IGES (API 8.0.1)
}
