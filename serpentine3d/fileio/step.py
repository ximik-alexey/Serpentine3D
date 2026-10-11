"""STEP import/export via OCCT (ctypes C++ wrapper)."""
from __future__ import annotations

import numpy as np

from .step_iges import iges_read_mesh, mesh_write_iges, mesh_write_step, step_read_mesh


def _mesh_to_shape(verts: list[float], tris: list[int]):
    """Build a MeshShape from flat vertex/triangle lists."""
    from ..core.mesh import MeshShape
    v = np.array(verts, dtype=np.float64).reshape(-1, 3)
    t = np.array(tris, dtype=np.uint32).reshape(-1, 3)
    return MeshShape(v, t)

def import_step(path: str) -> list:
    """Read a STEP file, return a list of MeshShapes."""
    verts, tris = step_read_mesh(path)
    return [_mesh_to_shape(verts, tris)]


def export_step(shapes: list, path: str) -> int:
    """Write shapes as STEP. Returns count of skipped meshes.

    Currently only mesh export is supported (BREP export is a stub).
    """
    from ..core.mesh import MeshShape
    skipped = 0
    mesh = None
    for shape in shapes:
        if isinstance(shape, MeshShape):
            if mesh is None:
                mesh = shape
            else:
                skipped += 1
        else:
            skipped += 1
    if mesh is None:
        raise ValueError(
            "STEP export requires at least one mesh object. "
            "BREP export is not yet available.")
    mesh_write_step(
        mesh.vertices.ravel().tolist(),
        mesh.triangles.ravel().tolist(),
        path,
    )
    return skipped


def import_iges(path: str) -> list:
    """Read an IGES file, return a list of MeshShapes."""
    verts, tris = iges_read_mesh(path)
    return [_mesh_to_shape(verts, tris)]


def export_iges(shapes: list, path: str) -> int:
    """Write shapes as IGES. Returns count of skipped meshes."""
    from ..core.mesh import MeshShape
    skipped = 0
    mesh = None
    for shape in shapes:
        if isinstance(shape, MeshShape):
            if mesh is None:
                mesh = shape
            else:
                skipped += 1
        else:
            skipped += 1
    if mesh is None:
        raise ValueError(
            "IGES export requires at least one mesh object. "
            "BREP export is not yet available.")
    mesh_write_iges(
        mesh.vertices.ravel().tolist(),
        mesh.triangles.ravel().tolist(),
        path,
    )
    return skipped
