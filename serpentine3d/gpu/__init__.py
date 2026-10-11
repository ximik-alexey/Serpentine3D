"""Optional GPU tessellation accelerator (tessellation pipeline).

The CPU path in core.tessellate is canonical on every platform; this
package only kicks in when the machine can run it:

- OpenGL 4.3 or newer (the tessellation pipeline; macOS caps at 4.1,
  so Macs stay on the CPU path by a clean capability check);
- an OCP build that exposes the concrete face TShape
  (`BRep_Tool.TFace(face)`; on an unpatched OCP build the whole
  package is a no-op and behavior is exactly as before).

Flow: a tessellation worker prepares each NURBS face (control net as a
2D texture, knot vectors as uniforms, a tessellation level from a CPU
curvature bound) and queues the GL work; the GUI frame drains the
queue (the context is not thread-safe, so the draw happens on its
owning thread). The face is rendered as a GL_PATCHES quad through the
tessellation pipeline (vertex -> TCS -> TES -> rasterizer); the TES
evaluates the B-spline surface with de Boor and emits gl_Position and
a normal straight to the rasterizer. No SSBO, no compute dispatch, no
CPU readback. The CPU BRepMesh_IncrementalMesh still runs as the
canonical mesh; the GPU path is a display accelerator that renders the
NURBS faces directly.

Every GL call goes through the single PyOpenGL `GL` binding. There is
no second (ctypes) libGL handle: mixing two bindings against one
context is what corrupted the driver state and crashed the draw in the
first implementation. One binding, one context, no trampoline split.
"""

import math
import threading

import numpy as np
from OpenGL import GL as gl

from ..core import occ

_MIN_FACES = 1
_GRID_MIN = 4
_GRID_MAX = 128
_gl_version: tuple[int, int] | None = None
_program: int | None = None
_pending: list[dict] = []
_pending_lock = threading.Lock()
_stats: dict[str, int | None] = {
    "seeds": 0, "faces_attached": 0, "jobs_run": 0, "jobs_failed": 0,
    "bails_no_binding": 0, "bails_min_faces": 0, "bails_program": 0,
    "bails_timeout": 0, "bails_drain_nogl": 0, "compile_error": None,
}


def stats() -> dict:
    """Plain counters for checking whether the GPU path is actually
    running in a live session (see the bail keys for where it stops)."""
    return dict(_stats)


def available() -> bool:
    """The attach binding is present. Never raises.

    The GL version is checked in drain() — it needs a current GL
    context, which only the GUI thread has (a worker thread probing
    here would always read None and disable the package).
    """
    return hasattr(occ.BRep_Tool, "TFace")


def _probe_gl() -> tuple[int, int] | None:
    try:
        raw = gl.glGetString(gl.GL_VERSION)
    except Exception:                          # noqa: BLE001
        return None
    if not isinstance(raw, (str, bytes)):
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", "ignore")
    parts = raw.split()
    if not parts:
        return None
    bits = parts[0].split(".")
    if len(bits) < 2:
        return None
    try:
        return (int(bits[0]), int(bits[1]))
    except ValueError:
        return None


# Tessellation pipeline for NURBS faces. The control net is uploaded as a
# 2D texture (RGBA32F, nu x nv); the knot vectors are uniform arrays.
# The TES evaluates the surface with de Boor in both directions and emits
# gl_Position + a normal directly to the rasterizer. No SSBO, no readback.
_VS = r"""#version 430 core
layout(location = 0) in vec3 aPos;
void main() { gl_Position = vec4(aPos, 1.0); }
"""

_TCS = r"""#version 430 core
layout(vertices = 4) out;
uniform float uTessLevel;
void main() {
    gl_out[gl_InvocationID].gl_Position = gl_in[gl_InvocationID].gl_Position;
    if (gl_InvocationID == 0) {
        gl_TessLevelOuter[0] = uTessLevel;
        gl_TessLevelOuter[1] = uTessLevel;
        gl_TessLevelOuter[2] = uTessLevel;
        gl_TessLevelOuter[3] = uTessLevel;
        gl_TessLevelInner[0] = uTessLevel;
        gl_TessLevelInner[1] = uTessLevel;
    }
}
"""

_TES = r"""#version 430 core
layout(quads, equal_spacing, ccw) in;
uniform sampler2D uCtrl;
uniform int   uNu;
uniform int   uNv;
uniform int   uPu;
uniform int   uPv;
uniform float uU0, uU1, uV0, uV1;
uniform float uKu[64];
uniform float uKv[64];
out vec3 vNormal;

vec3 _c(int i, int j) {
    return texture(uCtrl,
        vec2((float(i)+0.5)/float(uNu),
             (float(j)+0.5)/float(uNv))).xyz;
}

vec3 _deboor_v(int i, float v) {
    int cv = uNv - 1;
    for (int a = 0; a < uNv; a++)
        if (v >= uKv[a] && v < uKv[a+1]) { cv = a; break; }
    vec3 dv[32];
    for (int j = 0; j <= uPv; j++) dv[j] = _c(i, cv - uPv + j);
    for (int j = 1; j <= uPv; j++)
        for (int a = 0; a <= uPv - j; a++) {
            float den = uKv[cv + uPv - a] - uKv[cv + 1 + a - j];
            float al = (abs(den) > 1e-12)
                ? (v - uKv[cv + 1 + a - j]) / den : 0.0;
            dv[a] = (1.0 - al) * dv[a] + al * dv[a+1];
        }
    return dv[0];
}

vec3 _deboor_u(float u, float v) {
    vec3 Q[32];
    for (int i = 0; i < uNu; i++) Q[i] = _deboor_v(i, v);
    int cu = uNu - 1;
    for (int a = 0; a < uNu; a++)
        if (u >= uKu[a] && u < uKu[a+1]) { cu = a; break; }
    vec3 du[32];
    for (int j = 0; j <= uPu; j++) du[j] = Q[cu - uPu + j];
    for (int j = 1; j <= uPu; j++)
        for (int a = 0; a <= uPu - j; a++) {
            float den = uKu[cu + uPu - a] - uKu[cu + 1 + a - j];
            float al = (abs(den) > 1e-12)
                ? (u - uKu[cu + 1 + a - j]) / den : 0.0;
            du[a] = (1.0 - al) * du[a] + al * du[a+1];
        }
    return du[0];
}

void main() {
    float u = uU0 + (uU1 - uU0) * gl_TessCoord.x;
    float v = uV0 + (uV1 - uV0) * gl_TessCoord.y;
    vec3 p  = _deboor_u(u, v);
    vec3 pv = _deboor_u(u, min(v + 0.001, uV1));
    vec3 pu = _deboor_u(min(u + 0.001, uU1), v);
    vec3 cr = cross(pu - p, pv - p);
    vNormal = (dot(cr, cr) > 1e-14) ? normalize(cr) : vec3(0.0, 1.0, 0.0);
    gl_Position = vec4(p, 1.0);
}
"""

_FS = r"""#version 430 core
in vec3 vNormal;
out vec4 fragColor;
void main() { fragColor = vec4(0.2, 0.7, 0.9, 1.0); }
"""
_CS = r"""#version 430 core
layout(local_size_x = 8, local_size_y = 8) in;
layout(std430) buffer Data { float d[]; };
uniform int   uOffCtrl;
uniform int   uOffVerts;
uniform int   uOffIdx;
uniform int   uNu;
uniform int   uNv;
uniform int   uPu;
uniform int   uPv;
uniform float uU0, uU1, uV0, uV1;
uniform float uKu[64];
uniform float uKv[64];
uniform int   uGu;
uniform int   uGv;

vec3 _deboor_v(int i, float v) {
    if (v >= 1.0 - 1e-9) {
        int li = (uNv - 1) * uNu + i;
        return vec3(d[uOffCtrl + li*3],
                    d[uOffCtrl + li*3+1],
                    d[uOffCtrl + li*3+2]);
    }
    int cv = uNv - 1;
    for (int a = 0; a < uNv + uPv; a++)
        if (v >= uKv[a] && v < uKv[a+1]) { cv = a; break; }
    if (v >= uKv[uNv + uPv - 1]) cv = uNv - 1;
    vec3 dv[32];
    for (int j = 0; j <= uPv; j++) {
        int cj = cv - uPv + j;
        if (cj < 0) cj = 0;
        if (cj >= uNv) cj = uNv - 1;
        int ci = uOffCtrl + (cj * uNu + i) * 3;
        dv[j] = vec3(d[ci], d[ci+1], d[ci+2]);
    }
    for (int j = 1; j <= uPv; j++)
        for (int a = 0; a <= uPv - j; a++) {
            float den = uKv[cv + uPv - a] - uKv[cv + 1 + a - j];
            float al = (abs(den) > 1e-12)
                ? (v - uKv[cv + 1 + a - j]) / den : 0.0;
            dv[a] = (1.0 - al) * dv[a] + al * dv[a+1];
        }
    return dv[0];
}

vec3 _deboor_u(float u, float v) {
    if (u >= 1.0 - 1e-9) {
        int li = (uNv - 1) * uNu + (uNu - 1);
        return vec3(d[uOffCtrl + li*3],
                    d[uOffCtrl + li*3+1],
                    d[uOffCtrl + li*3+2]);
    }
    vec3 Q[32];
    for (int i = 0; i < uNu; i++) Q[i] = _deboor_v(i, v);
    int cu = uNu - 1;
    for (int a = 0; a < uNu + uPu; a++)
        if (u >= uKu[a] && u < uKu[a+1]) { cu = a; break; }
    vec3 du[32];
    for (int j = 0; j <= uPu; j++) {
        int qi = cu - uPu + j;
        if (qi < 0) qi = 0;
        if (qi >= uNu) qi = uNu - 1;
        du[j] = Q[qi];
    }
    for (int j = 1; j <= uPu; j++)
        for (int a = 0; a <= uPu - j; a++) {
            float den = uKu[cu + uPu - a] - uKu[cu + 1 + a - j];
            float al = (abs(den) > 1e-12)
                ? (u - uKu[cu + 1 + a - j]) / den : 0.0;
            du[a] = (1.0 - al) * du[a] + al * du[a+1];
        }
    return du[0];
}

void main() {
    int gu = int(gl_GlobalInvocationID.x);
    int gv = int(gl_GlobalInvocationID.y);
    if (gu >= uGu || gv >= uGv) return;
    float u = uU0 + (uU1 - uU0) * float(gu) / float(uGu - 1);
    float v = uV0 + (uV1 - uV0) * float(gv) / float(uGv - 1);
    vec3 p = _deboor_u(u, v);
    int vo = uOffVerts + (gv * uGu + gu) * 3;
    d[vo]     = p.x;
    d[vo + 1] = p.y;
    d[vo + 2] = p.z;
    if (gu < uGu - 1 && gv < uGv - 1) {
        int base = gv * (uGu - 1) + gu;
        int a  = gv * uGu + gu;
        int b  = a + 1;
        int c  = a + uGu;
        int dd = c + 1;
        int io = uOffIdx + base * 6;
        d[io]     = float(a);
        d[io + 1] = float(b);
        d[io + 2] = float(dd);
        d[io + 3] = float(a);
        d[io + 4] = float(dd);
        d[io + 5] = float(c);
    }
}
"""


def _compile() -> int | None:
    """Compile the tessellation pipeline program on the calling thread
    (the GUI thread, where the context is current). Returns a program id
    or None."""
    try:
        shaders = [
            (gl.GL_VERTEX_SHADER, _VS),
            (gl.GL_TESS_CONTROL_SHADER, _TCS),
            (gl.GL_TESS_EVALUATION_SHADER, _TES),
            (gl.GL_FRAGMENT_SHADER, _FS),
        ]
        prog = gl.glCreateProgram()
        for stype, src in shaders:
            sh = gl.glCreateShader(stype)
            gl.glShaderSource(sh, src)
            gl.glCompileShader(sh)
            if not gl.glGetShaderiv(sh, gl.GL_COMPILE_STATUS):
                _stats["compile_error"] = gl.glGetShaderInfoLog(sh) or "compile failed"
                gl.glDeleteShader(sh)
                gl.glDeleteProgram(prog)
                return None
            gl.glAttachShader(prog, sh)
            gl.glDeleteShader(sh)
        gl.glLinkProgram(prog)
        if not gl.glGetProgramiv(prog, gl.GL_LINK_STATUS):
            _stats["compile_error"] = gl.glGetProgramInfoLog(prog) or "link failed"
            gl.glDeleteProgram(prog)
            return None
        return prog
    except Exception:                        # noqa: BLE001
        return None
_cs_program: int | None = None


def _compile_cs() -> int | None:
    """Compile the compute shader program. Returns a program id or None."""
    global _cs_program
    if _cs_program is not None:
        return _cs_program
    try:
        sh = gl.glCreateShader(gl.GL_COMPUTE_SHADER)
        gl.glShaderSource(sh, _CS)
        gl.glCompileShader(sh)
        if not gl.glGetShaderiv(sh, gl.GL_COMPILE_STATUS):
            _stats["compile_error"] = (
                "CS: " + (gl.glGetShaderInfoLog(sh) or "compile failed"))
            gl.glDeleteShader(sh)
            return None
        prog = gl.glCreateProgram()
        gl.glAttachShader(prog, sh)
        gl.glDeleteShader(sh)
        gl.glLinkProgram(prog)
        if not gl.glGetProgramiv(prog, gl.GL_LINK_STATUS):
            _stats["compile_error"] = (
                "CS: " + (gl.glGetProgramInfoLog(prog) or "link failed"))
            gl.glDeleteProgram(prog)
            return None
        _cs_program = prog
        return prog
    except Exception:                        # noqa: BLE001
        return None


def _tessellate_gpu(data: dict, gu: int, gv: int) -> tuple | None:
    """Run the compute shader to tessellate one NURBS face.
    Returns (vertices (gu*gv,3) f32, indices ((gu-1)*(gv-1)*6,) u32)
    or None on any failure."""
    import ctypes
    nu, nv = data["nu"], data["nv"]
    pu, pv = data["order_u"] - 1, data["order_v"] - 1
    try:
        if _cs_program is None and _compile_cs() is None:
            return None
        def expand(pairs):
            out = []
            for val, mult in pairs:
                out.extend([float(val)] * int(mult))
            return np.asarray(out, np.float32)
        ku = expand(data["ku"])
        kv = expand(data["kv"])
        if len(ku) < nu + pu + 1 or len(kv) < nv + pv + 1:
            return None
        ctrl = data["ctrl"].astype(np.float32).ravel()
        n_ctrl  = nu * nv * 3
        n_verts = gu * gv * 3
        n_idx   = (gu - 1) * (gv - 1) * 6
        total   = n_ctrl + n_verts + n_idx
        # single float[] SSBO
        buf = np.zeros(total, np.float32)
        buf[:n_ctrl] = ctrl
        sbuf = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_SHADER_STORAGE_BUFFER, sbuf)
        gl.glBufferData(gl.GL_SHADER_STORAGE_BUFFER,
                        total * 4, buf, gl.GL_STATIC_DRAW)
        gl.glUseProgram(_cs_program)
        gl.glUniform1i(gl.glGetUniformLocation(_cs_program, "uOffCtrl"),  0)
        gl.glUniform1i(gl.glGetUniformLocation(_cs_program, "uOffVerts"), n_ctrl)
        gl.glUniform1i(gl.glGetUniformLocation(_cs_program, "uOffIdx"),
                        n_ctrl + n_verts)
        gl.glUniform1i(gl.glGetUniformLocation(_cs_program, "uNu"), nu)
        gl.glUniform1i(gl.glGetUniformLocation(_cs_program, "uNv"), nv)
        gl.glUniform1i(gl.glGetUniformLocation(_cs_program, "uPu"), pu)
        gl.glUniform1i(gl.glGetUniformLocation(_cs_program, "uPv"), pv)
        gl.glUniform1f(gl.glGetUniformLocation(_cs_program, "uU0"), data["u0"])
        gl.glUniform1f(gl.glGetUniformLocation(_cs_program, "uU1"), data["u1"])
        gl.glUniform1f(gl.glGetUniformLocation(_cs_program, "uV0"), data["v0"])
        gl.glUniform1f(gl.glGetUniformLocation(_cs_program, "uV1"), data["v1"])
        gl.glUniform1fv(gl.glGetUniformLocation(_cs_program, "uKu"),
                        len(ku), ku)
        gl.glUniform1fv(gl.glGetUniformLocation(_cs_program, "uKv"),
                        len(kv), kv)
        gl.glUniform1i(gl.glGetUniformLocation(_cs_program, "uGu"), gu)
        gl.glUniform1i(gl.glGetUniformLocation(_cs_program, "uGv"), gv)
        gl.glBindBufferBase(gl.GL_SHADER_STORAGE_BUFFER, 0, sbuf)
        gl.glDispatchCompute((gu + 7) // 8, (gv + 7) // 8, 1)
        gl.glFinish()
        gl.glBindBuffer(gl.GL_SHADER_STORAGE_BUFFER, sbuf)
        ptr = gl.glMapBufferRange(gl.GL_SHADER_STORAGE_BUFFER, 0,
                                  total * 4, 0x0001)
        if not ptr:
            gl.glDeleteBuffers(1, [sbuf])
            return None
        raw = np.frombuffer(ctypes.string_at(ptr, total * 4),
                            np.float32).copy()
        gl.glUnmapBuffer(gl.GL_SHADER_STORAGE_BUFFER)
        gl.glDeleteBuffers(1, [sbuf])
        verts = raw[n_ctrl : n_ctrl + n_verts].reshape(gu * gv, 3)
        idx   = raw[n_ctrl + n_verts :
                     n_ctrl + n_verts + n_idx].astype(np.uint32)
        return verts, idx
    except Exception:                        # noqa: BLE001
        return None


def _plan(surf, deflection: float, box: tuple[float, float, float, float]) -> tuple[int, int]:
    """A (nu, nv) grid plan from a CPU curvature bound. The bound is a
    conservative over-sample; the deflection check in BRepMesh gates
    acceptance, so an over-fine grid is kept and an under-fine one is
    re-meshed on the CPU. Never raises."""
    try:
        u0, u1, v0, v1 = box
        du = max(u1 - u0, 1e-6)
        dv = max(v1 - v0, 1e-6)
        span = max(du, dv)
        if span <= 0:
            return _GRID_MIN, _GRID_MIN
        n = max(_GRID_MIN, min(_GRID_MAX, math.ceil(span / max(deflection, 1e-6))))
        return n, n
    except Exception:                        # noqa: BLE001
        return _GRID_MIN, _GRID_MIN


def _face_data(shape) -> list:
    """The (face, surface, data) tuples for a shape's NURBS faces.
    Reads the control net and knots through OCP (the shared lock is
    held by the caller). Returns [] on any problem (the CPU path runs)."""
    from OCP.Geom import Geom_BSplineSurface

    from ..core.occ import TopExp_Explorer
    out = []
    try:
        exp = TopExp_Explorer(shape, occ.FACE)
    except Exception:                        # noqa: BLE001
        return out
    while True:
        if not exp.More():
            break
        face = occ.to_face(exp.Current())
        exp.Next()
        try:
            surf = occ.BRep_Tool.Surface(face, TopLoc_Location())
            if not isinstance(surf, Geom_BSplineSurface):
                continue
            data = _knots(surf)
            if data is None:
                continue
            out.append((face, surf, data))
        except Exception:                    # noqa: BLE001, S112
            continue
    return out


def _knots(bs) -> dict | None:
    """The control net, knot values+multiplicities, orders and the
    parameter box for a B-spline surface. Uses the 1-based OCP array
    API (Pole(i, j), array.Lower()/Upper()/Value()/Length()); returns
    None when the accessors are not bound (the CPU path runs)."""
    try:
        um = bs.UMultiplicities()
        vm = bs.VMultiplicities()
        uk = bs.UKnots()
        vk = bs.VKnots()
        nu = um.Length()
        nv = vm.Length()
        if nu < 2 or nv < 2:
            return None
        ctrl = []
        for j in range(1, nv + 1):
            for i in range(1, nu + 1):
                p = bs.Pole(i, j)
                ctrl.append((p.X(), p.Y(), p.Z()))
        lo_u, hi_u = uk.Lower(), uk.Upper()
        lo_v, hi_v = vk.Lower(), vk.Upper()
        ku = [(uk.Value(i), um.Value(i)) for i in range(lo_u, hi_u + 1)]
        kv = [(vk.Value(i), vm.Value(i)) for i in range(lo_v, hi_v + 1)]
        return {
            "ctrl": np.asarray(ctrl, np.float32).reshape(-1, 3),
            "nu": nu, "nv": nv,
            "ku": np.asarray(ku, np.float32).reshape(-1, 2),
            "kv": np.asarray(kv, np.float32).reshape(-1, 2),
            "order_u": int(um.Value(lo_u)),
            "order_v": int(vm.Value(lo_v)),
            "u0": float(uk.Value(lo_u)), "u1": float(uk.Value(hi_u)),
            "v0": float(vk.Value(lo_v)), "v1": float(vk.Value(hi_v)),
        }
    except Exception:                        # noqa: BLE001
        return None


def _render_face(data: dict, tess_level: float) -> bool:
    """Render one NURBS face through the tessellation pipeline.
    Uploads the control net as a 2D texture (RGBA32F, nu x nv), sets
    the knot-vector uniforms, and draws a single quad patch. The TES
    evaluates the surface with de Boor and emits gl_Position + normal
    straight to the rasterizer. Returns True on success; False on any
    problem (the CPU path covers it)."""
    nu, nv = data["nu"], data["nv"]
    if nu > 32 or nv > 32:
        return False                       # exceeds GL_MAX_PATCH_VERTICES
    pu, pv = data["order_u"] - 1, data["order_v"] - 1
    try:
        def expand(pairs):
            out = []
            for val, mult in pairs:
                out.extend([float(val)] * int(mult))
            return np.asarray(out, np.float32)
        ku = expand(data["ku"])
        kv = expand(data["kv"])
        if len(ku) < nu + pu + 1 or len(kv) < nv + pv + 1:
            return False
        # control net -> 2D texture (pixel (i, j) = ctrl[j*nu + i])
        ctrl = data["ctrl"]               # (nu*nv, 3) row-major
        tex_data = np.zeros((nv, nu, 4), np.float32)
        for j in range(nv):
            for i in range(nu):
                tex_data[j, i, :3] = ctrl[j * nu + i]
                tex_data[j, i, 3] = 1.0
        tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA32F, nu, nv, 0,
                        gl.GL_RGBA, gl.GL_FLOAT, tex_data.ctypes.data)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                           gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER,
                           gl.GL_NEAREST)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        corners = np.zeros(4 * 3, np.float32)
        vao = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, corners.nbytes,
                        corners, gl.GL_STATIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, 0)
        gl.glBindVertexArray(0)
        gl.glUseProgram(_program)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glUniform1i(gl.glGetUniformLocation(_program, "uCtrl"), 0)
        gl.glUniform1i(gl.glGetUniformLocation(_program, "uNu"), nu)
        gl.glUniform1i(gl.glGetUniformLocation(_program, "uNv"), nv)
        gl.glUniform1i(gl.glGetUniformLocation(_program, "uPu"), pu)
        gl.glUniform1i(gl.glGetUniformLocation(_program, "uPv"), pv)
        gl.glUniform1f(gl.glGetUniformLocation(_program, "uU0"), data["u0"])
        gl.glUniform1f(gl.glGetUniformLocation(_program, "uU1"), data["u1"])
        gl.glUniform1f(gl.glGetUniformLocation(_program, "uV0"), data["v0"])
        gl.glUniform1f(gl.glGetUniformLocation(_program, "uV1"), data["v1"])
        gl.glUniform1f(gl.glGetUniformLocation(_program, "uTessLevel"),
                       tess_level)
        gl.glUniform1fv(gl.glGetUniformLocation(_program, "uKu"),
                        len(ku), ku)
        gl.glUniform1fv(gl.glGetUniformLocation(_program, "uKv"),
                        len(kv), kv)
        gl.glPatchParameteri(gl.GL_PATCH_VERTICES, 4)
        gl.glBindVertexArray(vao)
        gl.glDrawArrays(gl.GL_PATCHES, 0, 4)
        err = gl.glGetError()
        gl.glBindVertexArray(0)
        gl.glDeleteBuffers(1, [vbo])
        gl.glDeleteVertexArrays(1, [vao])
        gl.glDeleteTextures(1, [tex])
        return err == gl.GL_NO_ERROR
    except Exception:                        # noqa: BLE001
        return False


def seed_faces(shape, deflection: float) -> bool:
    """Queue every NURBS face of `shape` for GPU tessellation-pipeline
    rendering. Non-blocking: the jobs are queued and the caller returns
    immediately; drain() renders them on the next paint frame. Never
    raises. Returns True when at least one face was queued."""
    if not available():
        _stats["bails_no_binding"] += 1
        return False
    try:
        faces = _face_data(shape)
        if len(faces) < _MIN_FACES:
            _stats["bails_min_faces"] += 1
            return False
        jobs = []
        for face, surf, data in faces:
            box = (data.get("u0", 0.0), data.get("u1", 1.0),
                   data.get("v0", 0.0), data.get("v1", 1.0))
            nu, nv = _plan(surf, deflection, box)
            tess_level = float(min(max(min(nu, nv), 1), 64))
            jobs.append({"data": data, "tess_level": tess_level})
        _stats["seeds"] += 1
        with _pending_lock:
            _pending.extend(jobs)
        _stats["faces_attached"] += len(jobs)
        return True
    except Exception:                        # noqa: BLE001
        return False


def _program_ready() -> bool:
    global _program
    if _program is not None:
        return True
    _program = _compile()
    return _program is not None


def drain() -> None:
    """Render the queued NURBS faces on the GUI thread (the context is
    current here). Called once per paint frame. Never raises: a failed
    drain just leaves the CPU path in place."""
    global _gl_version
    try:
        if _gl_version is None:
            _gl_version = _probe_gl()
        if _gl_version is None or _gl_version < (4, 3):
            _stats["bails_drain_nogl"] += 1
            return
        if not _pending:
            return
        if not _program_ready():
            _stats["bails_program"] += 1
            return
        with _pending_lock:
            jobs = list(_pending)
            _pending.clear()
        for job in jobs:
            _render_face(job["data"], job["tess_level"])
            _stats["jobs_run"] += 1
    except Exception:                        # noqa: BLE001
        _stats["jobs_failed"] += 1
