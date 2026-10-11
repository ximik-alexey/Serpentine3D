"""STEP/IGES I/O via ctypes C++ wrapper (bypasses broken SWIG modules).

Exchange format: multi-mesh file.
  [4B n_meshes]
  per mesh: [4B nv][4B nt][nv*12B float xyz][nt*12B int ijk]
"""
from __future__ import annotations

import ctypes
import struct
import tempfile
from pathlib import Path

import numpy as np

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


def _read_multi_mesh(path: str) -> list[tuple[np.ndarray, np.ndarray]]:
    """Read a multi-mesh file, return list of (vertices, triangles) arrays."""
    with open(path, "rb") as f:
        raw = f.read()
    n_meshes = struct.unpack_from("i", raw, 0)[0]
    results = []
    off = 4
    for _ in range(n_meshes):
        nv, nt = struct.unpack_from("ii", raw, off)
        off += 8
        verts = np.frombuffer(raw, dtype=np.float32, count=nv * 3,
                              offset=off).reshape(nv, 3).copy()
        off += nv * 12
        tris = np.frombuffer(raw, dtype=np.int32, count=nt * 3,
                             offset=off).reshape(nt, 3).copy()
        off += nt * 12
        results.append((verts, tris))
    return results


def _write_multi_mesh(path: str,
                      meshes: list[tuple[np.ndarray, np.ndarray]]) -> None:
    """Write a multi-mesh file from list of (vertices, triangles) arrays."""
    with open(path, "wb") as f:
        f.write(struct.pack("i", len(meshes)))
        for v, t in meshes:
            nv, nt = len(v), len(t)
            f.write(struct.pack("ii", nv, nt))
            f.write(np.ascontiguousarray(v, np.float32).tobytes())
            f.write(np.ascontiguousarray(t, np.int32).tobytes())


def step_read_meshes(path: str) -> list[tuple[np.ndarray, np.ndarray]]:
    """Read a STEP file, return list of (vertices, triangles) per shape."""
    with tempfile.NamedTemporaryFile(suffix=".mesh", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        rc = _lib.step_read(path.encode(), tmp_path.encode())
        if rc != 0:
            raise OSError(f"Could not read STEP file: {path}")
        return _read_multi_mesh(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def mesh_write_step(
        meshes: list[tuple[np.ndarray, np.ndarray]], path: str) -> None:
    """Write mesh data as a STEP file (stub)."""
    raise NotImplementedError(
        "STEP export (mesh→BREP) not yet available in OCCT 8.0.1")


def iges_read_meshes(path: str) -> list[tuple[np.ndarray, np.ndarray]]:
    """Read an IGES file, return list of (vertices, triangles) per shape."""
    with tempfile.NamedTemporaryFile(suffix=".mesh", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        rc = _lib.iges_read(path.encode(), tmp_path.encode())
        if rc != 0:
            raise OSError(f"Could not read IGES file: {path}")
        return _read_multi_mesh(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def mesh_write_iges(
        meshes: list[tuple[np.ndarray, np.ndarray]], path: str) -> None:
    """Write mesh data as an IGES file (stub)."""
    raise NotImplementedError(
        "IGES export (mesh→BREP) not yet available in OCCT 8.0.1")
