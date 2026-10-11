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
#include <memory>
#include <cmath>

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
#include "gp_Pnt.hxx"
#include "gp_Trsf.hxx"
// 8.0.1 STEP item model: representation items carry the label of
// the referenced entity; placement comes from the relationship's
// TransformationOperator (Geom_Transformation entity in the model).
#include "StepData_StepModel.hxx"
#include "StepRepr_Representation.hxx"
#include "StepRepr_NextAssemblyUsageOccurrence.hxx"
#include "StepBasic_ProductDefinition.hxx"
#include "StepBasic_ProductDefinitionFormation.hxx"
#include "StepBasic_Product.hxx"
#include "StepRepr_RepresentationRelationshipWithTransformation.hxx"
#include "StepRepr_ItemDefinedTransformation.hxx"
#include "Geom_Transformation.hxx"
#include "StepRepr_Transformation.hxx"
#include "StepShape_ShapeDefinitionRepresentation.hxx"
#include "StepRepr_PropertyDefinition.hxx"

// Multi-mesh file format:
//   [4B: n_meshes]
//   per mesh: [4B nname][name bytes][4B nparent][parent bytes]
//             [4B nv][4B nt][nv*12B float xyz][nt*12B int ijk]

struct Part {
    std::string name;
    std::string parent;
    double c[3]; // placement anchor (world-space)
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

// world-space bbox center of the placed part geometry. Built from
// the model's own entity graph (representation items), no raw
// text parsing.
static int item_id(
    const Handle(StepRepr_RepresentationItem)& it) {
    return atoi(it->Name()->ToCString());
}
static std::vector<Part> step_parts(
    const Handle(StepData_StepModel)& m) {
    std::vector<Part> parts;
    if (m.IsNull()) return parts;

    std::vector<std::pair<std::string, std::string>> edges;
    for (int i = 1; i <= m->NbEntities(); ++i) {
        Handle(Standard_Transient) e = m->Entity(i);
        if (!e->IsKind(
                StepRepr_NextAssemblyUsageOccurrence::get_type_descriptor()))
            continue;
        Handle(StepRepr_NextAssemblyUsageOccurrence) nao(
            reinterpret_cast<const StepRepr_NextAssemblyUsageOccurrence*>(e.get()));
        std::string pa =
            pdef_product(nao->RelatingProductDefinition());
        std::string pc =
            pdef_product(nao->RelatedProductDefinition());
        if (!pa.empty() && !pc.empty())
            edges.push_back({pa, pc});
    }

    for (int i = 1; i <= m->NbEntities(); ++i) {
        Handle(Standard_Transient) e = m->Entity(i);
        if (!e->IsKind(
                StepShape_ShapeDefinitionRepresentation::get_type_descriptor()))
            continue;
        Handle(StepShape_ShapeDefinitionRepresentation) sdr(
            reinterpret_cast<const StepShape_ShapeDefinitionRepresentation*>(e.get()));
        std::string prod = pdef_product(
            sdr->Definition().PropertyDefinition()
                ->Definition().ProductDefinition());
        if (prod.empty()) continue;
        Handle(StepRepr_Representation) rep = sdr->UsedRepresentation();
        if (rep.IsNull()) continue;

        // The transferred shapes are already placed in world
        // coordinates (8.0.1 bakes the assembly placement into
        // TransferRoots). A part's center is its placement
        // translation anchor (the local geometry origin); parts
        // without a placement sit at (0,0,0). The 8.0.1 model
        // keeps rep/transform item references by entity name only,
        // so a translation is used when resolvable, else the
        // matching falls back to file order (first-unused wins).
        double anchor[3] = {0., 0., 0.};
        for (int j = 1; j <= m->NbEntities(); ++j) {
            Handle(Standard_Transient) e2 = m->Entity(j);
            if (!e2->IsKind(StepRepr_RepresentationRelationshipWithTransformation::get_type_descriptor()))
                continue;
            Handle(StepRepr_RepresentationRelationshipWithTransformation) rr(
                reinterpret_cast<const StepRepr_RepresentationRelationshipWithTransformation*>(
                    e2.get()));
            if (rr->Rep1().IsNull() || rr->Rep1() != rep)
                continue;
            StepRepr_Transformation to = rr->TransformationOperator();
            Handle(StepRepr_ItemDefinedTransformation) idt =
                to.ItemDefinedTransformation();
            if (idt.IsNull())
                break;
            Handle(StepRepr_RepresentationItem) it1 = idt->TransformItem1();
            if (it1.IsNull())
                break;
            Handle(Standard_Transient) ent =
                find_by_label(m, item_id(it1));
            if (!ent.IsNull()
                    && ent->IsKind(Geom_Transformation::get_type_descriptor())) {
                const Geom_Transformation* gt =
                    reinterpret_cast<const Geom_Transformation*>(ent.get());
                gp_Trsf trsf = gt->Trsf();
                if (trsf.Form() != gp_Identity) {
                    anchor[0] = trsf.Value(1, 4);
                    anchor[1] = trsf.Value(2, 4);
                    anchor[2] = trsf.Value(3, 4);
                }
            }
            break;
        }

        Part p;
        p.name = prod;
        for (const auto& e2 : edges)
            if (e2.second == prod) { p.parent = e2.first; break; }
        p.c[0] = anchor[0];
        p.c[1] = anchor[1];
        p.c[2] = anchor[2];
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
            STEPControl_Reader* r = new STEPControl_Reader();
            if (r->ReadFile(path) != IFSelect_RetDone) {
                delete r;
                return 1;
            }
            collect(*r);
            parts = step_parts(r->StepModel());
            delete r;
        } else {
            IGESControl_Reader* r = new IGESControl_Reader();
            if (r->ReadFile(path) != IFSelect_RetDone) {
                delete r;
                return 1;
            }
            collect_iges(*r);
            delete r;
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

        // Match each mesh to a part. In an assembly, only child
        // parts own geometry (the parent's representation only
        // aggregates the children), so a part without a parent is
        // skipped when any part has one. Ties (all anchors equal:
        // the 8.0.1 item references carry no resolvable label)
        // fall back to file order, first-unused part wins.
        bool has_children = false;
        for (const auto& pt : parts)
            if (!pt.parent.empty()) has_children = true;
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
                if (has_children && parts[i].parent.empty()) continue;
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
