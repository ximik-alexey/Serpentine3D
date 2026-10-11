"""STEP import/export via OCCT (ctypes C++ wrapper)."""
from __future__ import annotations

import numpy as np

from .step_iges import iges_read_meshes, step_read_meshes


def _to_mesh_shape(verts: np.ndarray, tris: np.ndarray):
    """Build a MeshShape from (vertices, triangles) arrays."""
    from ..core.mesh import MeshShape
    v = np.ascontiguousarray(verts, np.float64)
    t = np.ascontiguousarray(tris, np.uint32)
    return MeshShape(v, t)


def import_step(path: str) -> list[tuple[str, str, object]]:
    """Read a STEP file, return (name, parent, MeshShape) per part.

    name is the product name from the file, parent its assembly's
    product name; both empty when the file has no assembly structure.
    """
    meshes = step_read_meshes(path)
    return [(n, p, _to_mesh_shape(v, t)) for n, p, v, t in meshes]


def export_step(shapes: list, path: str) -> int:
    """Write shapes as STEP. Returns count of skipped meshes.

    Currently raises NotImplementedError (BREP export is a stub).
    """
    raise NotImplementedError(
        "STEP export (mesh→BREP) not yet available in OCCT 8.0.1. "
        "Export to OBJ, STL or 3MF instead.")


def import_iges(path: str) -> list[tuple[str, str, object]]:
    """Read an IGES file, return (name, parent, MeshShape) per part.

    Names are empty: IGES has no assembly structure.
    """
    meshes = iges_read_meshes(path)
    return [(n, p, _to_mesh_shape(v, t)) for n, p, v, t in meshes]


def export_iges(shapes: list, path: str) -> int:
    """Write shapes as IGES. Returns count of skipped meshes.

    Currently raises NotImplementedError (BREP export is a stub).
    """
    raise NotImplementedError(
        "IGES export (mesh→BREP) not yet available in OCCT 8.0.1. "
        "Export to OBJ, STL or 3MF instead.")
