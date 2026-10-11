"""STEP/IGES I/O via ctypes C++ wrapper (bypasses broken SWIG modules).

Exchange format: mesh (vertices + triangles) written to a temp file.
"""
from __future__ import annotations

import ctypes
import struct
import tempfile
from pathlib import Path

_LIB = Path(__file__).parent / "_step_iges.so"
_lib = ctypes.CDLL(str(_LIB))

_lib.step_read.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
_lib.step_read.restype = ctypes.c_int
_lib.iges_read.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
_lib.iges_read.restype = ctypes.c_int
_lib.mesh_write_step.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
_lib.mesh_write_step.restype = ctypes.c_int
_lib.mesh_write_iges.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
_lib.mesh_write_iges.restype = ctypes.c_int


def _read_mesh_file(path: str) -> tuple[list[float], list[int]]:
    """Read a mesh file: (vertices as flat float list, triangles as flat int list)."""
    with open(path, "rb") as f:
        raw = f.read()
    nv, nt = struct.unpack_from("ii", raw, 0)
    verts = list(struct.unpack_from(f"{nv*3}f", raw, 8))
    tris = list(struct.unpack_from(f"{nt*3}i", raw, 8 + nv * 12))
    return verts, tris


def _write_mesh_file(path: str, verts: list[float], tris: list[int]) -> None:
    """Write a mesh file from flat lists."""
    nv, nt = len(verts) // 3, len(tris) // 3
    with open(path, "wb") as f:
        f.write(struct.pack("ii", nv, nt))
        f.write(struct.pack(f"{nv*3}f", *verts))
        f.write(struct.pack(f"{nt*3}i", *tris))


def step_read_mesh(path: str) -> tuple[list[float], list[int]]:
    """Read a STEP file, return (vertices, triangles) mesh data."""
    with tempfile.NamedTemporaryFile(suffix=".mesh", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        rc = _lib.step_read(path.encode(), tmp_path.encode())
        if rc != 0:
            raise OSError(f"Could not read STEP file: {path}")
        return _read_mesh_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def mesh_write_step(verts: list[float], tris: list[int], path: str) -> None:
    """Write mesh data as a STEP file."""
    with tempfile.NamedTemporaryFile(suffix=".mesh", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _write_mesh_file(tmp_path, verts, tris)
        rc = _lib.mesh_write_step(tmp_path.encode(), path.encode())
        if rc != 0:
            raise OSError(f"Could not write STEP file: {path}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def iges_read_mesh(path: str) -> tuple[list[float], list[int]]:
    """Read an IGES file, return (vertices, triangles) mesh data."""
    with tempfile.NamedTemporaryFile(suffix=".mesh", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        rc = _lib.iges_read(path.encode(), tmp_path.encode())
        if rc != 0:
            raise OSError(f"Could not read IGES file: {path}")
        return _read_mesh_file(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def mesh_write_iges(verts: list[float], tris: list[int], path: str) -> None:
    """Write mesh data as an IGES file."""
    with tempfile.NamedTemporaryFile(suffix=".mesh", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        _write_mesh_file(tmp_path, verts, tris)
        rc = _lib.mesh_write_iges(tmp_path.encode(), path.encode())
        if rc != 0:
            raise OSError(f"Could not write IGES file: {path}")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
