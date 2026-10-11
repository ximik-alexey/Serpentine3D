// C++ wrapper for STEP/IGES I/O — bypasses broken SWIG modules.
// Read: STEP/IGES file → tessellated mesh (vertices + triangles).
//       STEP also carries the assembly structure: each mesh gets the
//       product name of the part it belongs to and the parent product
//       name (empty for flat files / IGES).
// Write: stubs (mesh→BREP not available in OCCT 8.0.1)

#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <string>
#include <vector>
#include <cmath>
#include <fstream>

#include "STEPControl_Reader.hxx"
#include "IGESControl_Reader.hxx"
#include "IFSelect_ReturnStatus.hxx"
#include "TopoDS_Shape.hxx"
#include "TopoDS_Face.hxx"
#include "TopExp_Explorer.hxx"
#include "BRepMesh_IncrementalMesh.hxx"
#include "BRep_Tool.hxx"
#include "TopLoc_Location.hxx"
#include "Poly_Triangulation.hxx"
#include "gp_Ax2.hxx"
#include "gp_Pnt.hxx"
#include "gp_Dir.hxx"
#include "gp_XYZ.hxx"
#include "gp_Mat.hxx"
#include "gp_Quaternion.hxx"
#include "gp_Trsf.hxx"
// 8.0.1 STEP item model (the rep items no longer carry the shape; the
// BREP items are reached through the file text: entity label → entry →
// referenced #ids → entity)
#include "StepData_StepModel.hxx"
#include "StepRepr_Representation.hxx"
#include "StepRepr_NextAssemblyUsageOccurrence.hxx"
#include "StepBasic_ProductDefinition.hxx"
#include "StepBasic_ProductDefinitionFormation.hxx"
#include "StepBasic_Product.hxx"
#include "StepRepr_RepresentationRelationshipWithTransformation.hxx"
#include "StepRepr_ItemDefinedTransformation.hxx"
#include "StepGeom_Axis2Placement3d.hxx"
#include "StepGeom_CartesianPoint.hxx"
#include "StepGeom_Direction.hxx"
#include "StepShape_ShapeDefinitionRepresentation.hxx"
#include "StepRepr_PropertyDefinition.hxx"
#include "StepShape_BrepWithVoids.hxx"
#include "StepShape_ManifoldSolidBrep.hxx"
#include "StepShape_FacetedBrep.hxx"
#include "StepToTopoDS_Builder.hxx"
#include "Transfer_TransientProcess.hxx"
#include "BRepBndLib.hxx"
#include "Bnd_Box.hxx"

// Multi-mesh file format:
//   [4B: n_meshes]
//   per mesh: [4B nname][name bytes][4B nparent][parent bytes]
//             [4B nv][4B nt][nv*12B float xyz][nt*12B int ijk]

struct Part {
    std::string name;
    std::string parent;
    double c[3]; // world-space bbox center
};

static std::string pdef_product(const Handle(StepBasic_ProductDefinition)& pd) {
    if (pd.IsNull()) return std::string();
    Handle(StepBasic_ProductDefinitionFormation) f = pd->Formation();
    if (f.IsNull()) return std::string();
    Handle(StepBasic_Product) p = f->OfProduct();
    if (p.IsNull()) return std::string();
    return std::string(p->Name()->ToCString());
}

static Handle(Standard_Transient) find_by_label(
    const Handle(StepData_StepModel)& m, int label) {
    for (int i = 1; i <= m->NbEntities(); ++i)
        if (m->IdentLabel(m->Entity(i)) == label)
            return m->Entity(i);
    return nullptr;
}

// #ids referenced in the raw text entry of `label`
static std::vector<int> entry_refs(const std::string& text, int label) {
    std::string pat = "#" + std::to_string(label) + " = ";
    size_t pos = text.find(pat);
    if (pos == std::string::npos) return {};
    size_t end = text.find(";\n#", pos + pat.size());
    std::string body = text.substr(
        pos + pat.size(),
        end == std::string::npos ? 0 : end - pos - pat.size());
    std::vector<int> out;
    size_t q;
    while ((q = body.find("#", 0)) != std::string::npos) {
        size_t k = q + 1;
        int v = 0;
        while (k < body.size() && body[k] >= '0' && body[k] <= '9')
            v = v * 10 + (body[k++] - '0');
        if (v > 0) out.push_back(v);
        q = k;
    }
    return out;
}

// Build the local BREP shape of a geometry item (the reader's own
// internal conversion, standalone).
static TopoDS_Shape build_geo(const Handle(Standard_Transient)& e) {
    Transfer_TransientProcess tp(10000);
    Handle(Transfer_TransientProcess) th(&tp);
    if (const auto* g =
            dynamic_cast<const StepShape_BrepWithVoids*>(e.get())) {
        StepToTopoDS_Builder b;
        b.Init(Handle(StepShape_BrepWithVoids)(g), th);
        return b.Value();
    }
    if (const auto* g =
            dynamic_cast<const StepShape_ManifoldSolidBrep*>(e.get())) {
        StepToTopoDS_Builder b;
        b.Init(Handle(StepShape_ManifoldSolidBrep)(g), th);
        return b.Value();
    }
    if (const auto* g =
            dynamic_cast<const StepShape_FacetedBrep*>(e.get())) {
        StepToTopoDS_Builder b;
        b.Init(Handle(StepShape_FacetedBrep)(g), th);
        return b.Value();
    }
    return TopoDS_Shape();
}

// Part table of a STEP file: product name, parent product name,
// world-space bbox center of the placed part geometry.
static std::vector<Part> step_parts(
    const std::string& text, const Handle(StepData_StepModel)& m) {
    std::vector<Part> parts;
    if (m.IsNull()) return parts;

    std::vector<std::pair<std::string, std::string>> edges;
    for (int i = 1; i <= m->NbEntities(); ++i) {
        Handle(Standard_Transient) e = m->Entity(i);
        const auto* nao_p =
            dynamic_cast<const StepRepr_NextAssemblyUsageOccurrence*>(
                e.get());
        if (!nao_p) continue;
        Handle(StepRepr_NextAssemblyUsageOccurrence) nao(nao_p);
        std::string pa =
            pdef_product(nao->RelatingProductDefinition());
        std::string pc =
            pdef_product(nao->RelatedProductDefinition());
        if (!pa.empty() && !pc.empty())
            edges.push_back({pa, pc});
    }

    for (int i = 1; i <= m->NbEntities(); ++i) {
        Handle(Standard_Transient) e = m->Entity(i);
        const auto* sdr_p =
            dynamic_cast<const StepShape_ShapeDefinitionRepresentation*>(
                e.get());
        if (!sdr_p) continue;
        Handle(StepShape_ShapeDefinitionRepresentation) sdr(sdr_p);
        std::string prod = pdef_product(
            sdr->Definition().PropertyDefinition()
                ->Definition().ProductDefinition());
        if (prod.empty()) continue;
        Handle(StepRepr_Representation) rep = sdr->UsedRepresentation();
        if (rep.IsNull()) continue;

        // local geometry bbox
        Bnd_Box lbb;
        bool have_geo = false;
        for (int id : entry_refs(text, m->IdentLabel(rep))) {
            Handle(Standard_Transient) g = find_by_label(m, id);
            if (g.IsNull()) continue;
            TopoDS_Shape s = build_geo(g);
            if (s.IsNull()) continue;
            Bnd_Box b;
            BRepBndLib::Add(s, b);
            if (!b.IsVoid()) {
                lbb = b;
                have_geo = true;
            }
            break;
        }
        if (!have_geo) continue;

        // placement of the part in the assembly (identity if the
        // relationship carries none)
        gp_Ax2 ax;
        bool have_ax = false;
        for (int j = 1; j <= m->NbEntities() && !have_ax; ++j) {
            Handle(Standard_Transient) e2 = m->Entity(j);
            const auto* rr_p =
                dynamic_cast<const StepRepr_RepresentationRelationshipWithTransformation*>(e2.get());
            if (!rr_p) continue;
            Handle(StepRepr_RepresentationRelationshipWithTransformation)
                rr(rr_p);
            if (rr->Rep1().IsNull() || rr->Rep1() != rep)
                continue;
            for (int id : entry_refs(text, m->IdentLabel(e2))) {
                Handle(Standard_Transient) idt = find_by_label(m, id);
                const auto* idt_p =
                    dynamic_cast<const StepRepr_ItemDefinedTransformation*>(
                        idt.get());
                if (!idt_p) continue;
                Handle(StepRepr_ItemDefinedTransformation) idth(idt_p);
                Handle(StepGeom_CartesianPoint) pt(
                    dynamic_cast<const StepGeom_CartesianPoint*>(
                        idt.get()));
                if (pt.IsNull()) continue;
                gp_Pnt loc(pt->CoordinatesValue(1),
                           pt->CoordinatesValue(2),
                           pt->CoordinatesValue(3));
                gp_Dir z(0., 0., 1.), x(1., 0., 0.);
                Handle(StepGeom_Axis2Placement3d) to(
                    dynamic_cast<const StepGeom_Axis2Placement3d*>(
                        idt.get()));
                if (!to.IsNull()) {
                    if (to->HasAxis()) {
                        auto d = to->Axis()->DirectionRatios();
                        z = gp_Dir(d[0], d[1], d[2]);
                    }
                    if (to->HasRefDirection()) {
                        auto d = to->RefDirection()->DirectionRatios();
                        x = gp_Dir(d[0], d[1], d[2]);
                    }
                }
                ax = gp_Ax2(loc, z, x);
                have_ax = true;
                break;
            }
        }

        // world bbox: transform the 8 local corners
        double x0, y0, z0, x1, y1, z1;
        lbb.Get(x0, y0, z0, x1, y1, z1);
        double wx0 =  1e30, wy0 =  1e30, wz0 =  1e30,
               wx1 = -1e30, wy1 = -1e30, wz1 = -1e30;
        for (int cx = 0; cx <= 1; ++cx)
        for (int cy = 0; cy <= 1; ++cy)
        for (int cz = 0; cz <= 1; ++cz) {
            gp_Pnt c(cx ? x1 : x0, cy ? y1 : y0, cz ? z1 : z0);
            gp_Pnt w = c;
            if (have_ax) {
                gp_Dir y(ax.Direction().Crossed(ax.XDirection()));
                gp_Mat m;
                m.SetRows(gp_XYZ(ax.XDirection().X(), ax.XDirection().Y(),
                                ax.XDirection().Z()),
                         gp_XYZ(y.X(), y.Y(), y.Z()),
                         gp_XYZ(ax.Direction().X(), ax.Direction().Y(),
                                ax.Direction().Z()));
                gp_Trsf trf;
                trf.SetTranslation(gp_Pnt(0., 0., 0.), ax.Location());
                trf.SetRotationPart(gp_Quaternion(m));
                w.Transform(trf);
            }
            wx0 = std::min(wx0, w.X());
            wy0 = std::min(wy0, w.Y());
            wz0 = std::min(wz0, w.Z());
            wx1 = std::max(wx1, w.X());
            wy1 = std::max(wy1, w.Y());
            wz1 = std::max(wz1, w.Z());
        }

        Part p;
        p.name = prod;
        for (const auto& e2 : edges)
            if (e2.second == prod) { p.parent = e2.first; break; }
        p.c[0] = (wx0 + wx1) / 2;
        p.c[1] = (wy0 + wy1) / 2;
        p.c[2] = (wz0 + wz1) / 2;
        parts.push_back(p);
    }
    return parts;
}

static int read_to_meshes(const char* path, const char* out_path,
                          bool is_step) {
    try {
        std::vector<TopoDS_Shape> shapes;
        std::vector<Part> parts;
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
            std::ifstream ifs(path, std::ios::binary);
            std::istreambuf_iterator<char> eof;
            std::string text(std::istreambuf_iterator<char>(ifs), eof);
            parts = step_parts(text, r.StepModel());
        } else {
            IGESControl_Reader r;
            if (r.ReadFile(path) != IFSelect_RetDone) return 1;
            collect_iges(r);
        }
        if (shapes.empty()) return 1;

        // Tessellate each shape independently
        struct MeshData {
            std::string name;
            std::string parent;
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
                        gp_Pnt p = tri->Node(i).Transformed(loc);
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
            if (md.verts.empty()) continue;
            meshes.push_back(std::move(md));
        }
        if (meshes.empty()) return 1;

        // Match each mesh to the nearest part (world bbox center).
        // OCCT does not guarantee the mesh order equals the file's
        // product order, so the geometry decides.
        std::vector<bool> used(parts.size(), false);
        for (auto& md : meshes) {
            double x0 =  1e30, y0 =  1e30, z0 =  1e30;
            double x1 = -1e30, y1 = -1e30, z1 = -1e30;
            for (size_t i = 0; i < md.verts.size(); i += 3) {
                x0 = std::min(x0, (double)md.verts[i]);
                y0 = std::min(y0, (double)md.verts[i + 1]);
                z0 = std::min(z0, (double)md.verts[i + 2]);
                x1 = std::max(x1, (double)md.verts[i]);
                y1 = std::max(y1, (double)md.verts[i + 1]);
                z1 = std::max(z1, (double)md.verts[i + 2]);
            }
            double cx = (x0 + x1) / 2, cy = (y0 + y1) / 2,
                   cz = (z0 + z1) / 2;
            int best = -1;
            double best_d = 0;
            for (size_t i = 0; i < parts.size(); ++i) {
                if (used[i]) continue;
                double dx = parts[i].c[0] - cx;
                double dy = parts[i].c[1] - cy;
                double dz = parts[i].c[2] - cz;
                double d = dx * dx + dy * dy + dz * dz;
                if (best < 0 || d < best_d) { best = (int)i; best_d = d; }
            }
            if (best >= 0) {
                used[best] = true;
                md.name = parts[best].name;
                md.parent = parts[best].parent;
            }
        }

        // Write multi-mesh file
        std::ofstream ofs(out_path, std::ios::binary);
        if (!ofs) return 1;
        int nm = (int)meshes.size();
        ofs.write((const char*)&nm, 4);
        for (const auto& md : meshes) {
            std::string nb = md.name;
            std::string pb = md.parent;
            int nname = (int)nb.size();
            int nparent = (int)pb.size();
            int nv = (int)md.verts.size() / 3;
            int nt = (int)md.tris.size() / 3;
            ofs.write((const char*)&nname, 4);
            ofs.write(nb.data(), nname);
            ofs.write((const char*)&nparent, 4);
            ofs.write(pb.data(), nparent);
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
