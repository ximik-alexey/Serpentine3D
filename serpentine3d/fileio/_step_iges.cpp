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

// Mesh file format:
//   [4B: n_verts] [4B: n_tris]
//   [n_verts * 12B: x,y,z float]
//   [n_tris * 12B: i,j,k int]

static bool write_mesh_file(const char* path, const std::vector<float>& v,
                            const std::vector<int>& t) {
    std::ofstream ofs(path, std::ios::binary);
    if (!ofs) return false;
    int nv = (int)v.size() / 3, nt = (int)t.size() / 3;
    ofs.write((const char*)&nv, 4);
    ofs.write((const char*)&nt, 4);
    ofs.write((const char*)v.data(), nv * 12);
    ofs.write((const char*)t.data(), nt * 12);
    return true;
}

static bool read_mesh_file(const char* path, std::vector<float>& v,
                           std::vector<int>& t) {
    std::ifstream ifs(path, std::ios::binary);
    if (!ifs) return false;
    int nv, nt;
    ifs.read((char*)&nv, 4);
    ifs.read((char*)&nt, 4);
    v.resize(nv * 3);
    t.resize(nt * 3);
    ifs.read((char*)v.data(), nv * 12);
    ifs.read((char*)t.data(), nt * 12);
    return true;
}

static int read_to_mesh(const char* path, const char* mesh_path, bool is_step) {
    try {
        std::vector<TopoDS_Shape> shapes;
        if (is_step) {
            STEPControl_Reader r;
            if (r.ReadFile(path) != IFSelect_RetDone) return 1;
            r.TransferRoots();
            for (int i = 1; i <= r.NbShapes(); ++i)
                if (!r.Shape(i).IsNull()) shapes.push_back(r.Shape(i));
        } else {
            IGESControl_Reader r;
            if (r.ReadFile(path) != IFSelect_RetDone) return 1;
            r.TransferRoots();
            for (int i = 1; i <= r.NbShapes(); ++i)
                if (!r.Shape(i).IsNull()) shapes.push_back(r.Shape(i));
        }
        if (shapes.empty()) return 1;

        std::vector<float> verts;
        std::vector<int> tris;
        TopLoc_Location loc;
        for (const auto& s : shapes) {
            BRepMesh_IncrementalMesh(s, 0.005, false, 0.35, true);
            TopExp_Explorer exp(s, TopAbs_FACE);
            while (exp.More()) {
                Handle(Poly_Triangulation) tri = BRep_Tool::Triangulation(
                    *reinterpret_cast<const TopoDS_Face*>(&exp.Current()), loc);
                if (!tri.IsNull()) {
                    int nn = tri->NbNodes();
                    int nt_ = tri->NbTriangles();
                    int base = (int)verts.size() / 3;
                    for (int i = 1; i <= nn; ++i) {
                        const gp_Pnt& p = tri->Node(i);
                        verts.push_back((float)p.X());
                        verts.push_back((float)p.Y());
                        verts.push_back((float)p.Z());
                    }
                    for (int i = 1; i <= nt_; ++i) {
                        int a = tri->Triangle(i).Value(1);
                        int b = tri->Triangle(i).Value(2);
                        int c = tri->Triangle(i).Value(3);
                        tris.push_back(base + a - 1);
                        tris.push_back(base + b - 1);
                        tris.push_back(base + c - 1);
                    }
                }
                exp.Next();
            }
        }
        if (verts.empty()) return 1;
        return write_mesh_file(mesh_path, verts, tris) ? 0 : 1;
    } catch (...) { return 1; }
}

extern "C" int step_read(const char* p, const char* m) {
    return read_to_mesh(p, m, true);
}
extern "C" int iges_read(const char* p, const char* m) {
    return read_to_mesh(p, m, false);
}
extern "C" int mesh_write_step(const char* m, const char* p) {
    (void)m; (void)p;
    return 1; // TODO: mesh→BREP→STEP (API 8.0.1)
}
extern "C" int mesh_write_iges(const char* m, const char* p) {
    (void)m; (void)p;
    return 1; // TODO: mesh→BREP→IGES (API 8.0.1)
}
