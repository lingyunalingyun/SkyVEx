#!/usr/bin/env python3
# SkyVEx — OpenGL 3D model preview panel (VBO accelerated)
# Copyright (c) 2026 lingyunalingyun
# License: MIT (see LICENSE)

import tkinter as tk
import math
import ctypes
import sys
import array

try:
    import OpenGL
    OpenGL.ERROR_CHECKING = False
except ImportError:
    pass

_gl_available = None

def is_available():
    global _gl_available
    if _gl_available is None:
        try:
            from OpenGL import GL
            _gl_available = True
        except ImportError:
            _gl_available = False
    return _gl_available


class PreviewPanel:
    """OpenGL 3D preview embedded in a tkinter Frame, VBO accelerated."""

    BG = "#0a1628"
    ACCENT = "#f0c050"

    def __init__(self, parent, on_close=None):
        self.parent = parent
        self._on_close = on_close
        self._display_list = 0
        self._display_list_wire = 0
        self._has_mesh = False
        self._rot_x = 25.0
        self._rot_y = 35.0
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._last_mouse = None
        self._center = (0.0, 0.0, 0.0)
        self._scale = 1.0
        self._gl_inited = False
        self._wireframe = False
        self._render_pending = False
        self._destroyed = False
        self._has_colors = False

        self.frame = tk.Frame(parent, bg=self.BG, bd=1, relief="sunken")

        toolbar = tk.Frame(self.frame, bg="#0d1e35")
        toolbar.pack(fill="x")

        tk.Label(
            toolbar, text="3D 预览", fg=self.ACCENT, bg="#0d1e35",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=8)

        tk.Button(
            toolbar, text="×", fg="#d0d0d0", bg="#0d1e35",
            activebackground="#1a3050", activeforeground="#ffffff",
            bd=0, font=("Consolas", 11, "bold"), width=3,
            command=self._close,
        ).pack(side="right")

        self._wire_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            toolbar, text="线框", variable=self._wire_var,
            fg="#a0b0c0", bg="#0d1e35", selectcolor="#0d1e35",
            activebackground="#0d1e35", activeforeground="#d0d0d0",
            font=("Segoe UI", 8), command=self._toggle_wireframe,
        ).pack(side="right", padx=4)

        tk.Button(
            toolbar, text="重置视角", fg="#a0b0c0", bg="#0d1e35",
            activebackground="#1a3050", activeforeground="#ffffff",
            bd=0, font=("Segoe UI", 8),
            command=self._reset_view,
        ).pack(side="right", padx=4)

        self._canvas = tk.Canvas(
            self.frame, bg="#050d18", highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True)

        self._info_label = tk.Label(
            self.frame, text="无模型", fg="#506070", bg=self.BG,
            font=("Segoe UI", 8),
        )
        self._info_label.pack(side="bottom", fill="x")

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonPress-3>", self._on_press)
        self._canvas.bind("<B3-Motion>", self._on_pan)
        self._canvas.bind("<MouseWheel>", self._on_scroll)
        self._canvas.bind("<Configure>", self._on_resize)
        self._canvas.bind("<Map>", self._on_resize)

        self._setup_gl()

    # ── GL init (Win32) ─────────────────────────────────────

    def _setup_gl(self):
        if not is_available():
            self._show_fallback("PyOpenGL 未安装\npip install PyOpenGL")
            return
        try:
            if sys.platform == "win32":
                self._setup_gl_win32()
            else:
                self._show_fallback("仅支持 Windows")
        except Exception as e:
            self._show_fallback(f"OpenGL 初始化失败:\n{e}")

    def _setup_gl_win32(self):
        self._canvas.update_idletasks()
        hwnd = self._canvas.winfo_id()

        from ctypes import windll, wintypes, Structure, byref, sizeof

        gdi32 = windll.gdi32
        user32 = windll.user32
        opengl32 = windll.opengl32

        class PIXELFORMATDESCRIPTOR(Structure):
            _fields_ = [
                ("nSize", wintypes.WORD), ("nVersion", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("iPixelType", wintypes.BYTE),
                ("cColorBits", wintypes.BYTE),
                ("cRedBits", wintypes.BYTE), ("cRedShift", wintypes.BYTE),
                ("cGreenBits", wintypes.BYTE), ("cGreenShift", wintypes.BYTE),
                ("cBlueBits", wintypes.BYTE), ("cBlueShift", wintypes.BYTE),
                ("cAlphaBits", wintypes.BYTE), ("cAlphaShift", wintypes.BYTE),
                ("cAccumBits", wintypes.BYTE),
                ("cAccumRedBits", wintypes.BYTE), ("cAccumGreenBits", wintypes.BYTE),
                ("cAccumBlueBits", wintypes.BYTE), ("cAccumAlphaBits", wintypes.BYTE),
                ("cDepthBits", wintypes.BYTE), ("cStencilBits", wintypes.BYTE),
                ("cAuxBuffers", wintypes.BYTE), ("iLayerType", wintypes.BYTE),
                ("bReserved", wintypes.BYTE),
                ("dwLayerMask", wintypes.DWORD), ("dwVisibleMask", wintypes.DWORD),
                ("dwDamageMask", wintypes.DWORD),
            ]

        pfd = PIXELFORMATDESCRIPTOR()
        pfd.nSize = sizeof(PIXELFORMATDESCRIPTOR)
        pfd.nVersion = 1
        pfd.dwFlags = 0x00000004 | 0x00000020 | 0x00000001
        pfd.iPixelType = 0
        pfd.cColorBits = 24
        pfd.cDepthBits = 24
        pfd.cStencilBits = 8

        self._hdc = user32.GetDC(hwnd)
        fmt = gdi32.ChoosePixelFormat(self._hdc, byref(pfd))
        gdi32.SetPixelFormat(self._hdc, fmt, byref(pfd))

        self._hglrc = opengl32.wglCreateContext(self._hdc)
        opengl32.wglMakeCurrent(self._hdc, self._hglrc)

        self._hwnd = hwnd
        self._opengl32 = opengl32
        self._gdi32 = gdi32
        self._user32 = user32
        self._gl_inited = True

        self._init_gl()
        self._render()

    def _make_current(self):
        if self._gl_inited:
            new_hwnd = self._canvas.winfo_id()
            if new_hwnd != self._hwnd:
                self._user32.ReleaseDC(self._hwnd, self._hdc)
                self._hwnd = new_hwnd
                self._hdc = self._user32.GetDC(new_hwnd)
            self._opengl32.wglMakeCurrent(self._hdc, self._hglrc)

    def _swap_buffers(self):
        if self._gl_inited:
            self._gdi32.SwapBuffers(self._hdc)

    def _init_gl(self):
        from OpenGL import GL
        GL.glClearColor(0.02, 0.05, 0.09, 1.0)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_LIGHTING)
        GL.glEnable(GL.GL_LIGHT0)
        GL.glEnable(GL.GL_COLOR_MATERIAL)
        GL.glColorMaterial(GL.GL_FRONT_AND_BACK, GL.GL_AMBIENT_AND_DIFFUSE)
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_POSITION, [0.0, 1.0, 0.0, 0.0])
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_DIFFUSE, [0.55, 0.55, 0.52, 1.0])
        GL.glLightfv(GL.GL_LIGHT0, GL.GL_AMBIENT, [0.35, 0.35, 0.38, 1.0])


    def _show_fallback(self, msg):
        self._canvas.delete("all")
        w = self._canvas.winfo_width() or 200
        h = self._canvas.winfo_height() or 150
        self._canvas.create_text(
            w // 2, h // 2,
            text=msg, fill="#506070", font=("Segoe UI", 11),
        )

    # ── Mesh loading (display list) ──────────────────────────

    def load_mesh(self, verts, faces, uvs=None, colors=None, flip_normals=False):
        if not self._gl_inited:
            return

        nv = len(verts)
        nf = len(faces)
        has_colors = colors and len(colors) == nv
        self._has_colors = has_colors

        normals = self._compute_normals(verts, faces, flip=flip_normals)
        self._compute_bounds(verts)

        self._make_current()
        from OpenGL import GL

        if self._display_list:
            GL.glDeleteLists(self._display_list, 1)
        if self._display_list_wire:
            GL.glDeleteLists(self._display_list_wire, 1)

        cx, cy, cz = self._center
        s = self._scale
        scaled = [(0.0, 0.0, 0.0)] * nv
        for i in range(nv):
            vx, vy, vz = verts[i]
            scaled[i] = ((vx - cx) * s, (vy - cy) * s, (vz - cz) * s)

        valid_faces = [(a, b, c) for a, b, c in faces if a < nv and b < nv and c < nv]

        self._display_list = GL.glGenLists(1)
        GL.glNewList(self._display_list, GL.GL_COMPILE)
        GL.glBegin(GL.GL_TRIANGLES)
        for a, b, c in valid_faces:
            for idx in (a, b, c):
                if has_colors:
                    GL.glColor3f(*colors[idx])
                GL.glNormal3f(*normals[idx])
                GL.glVertex3f(*scaled[idx])
        GL.glEnd()
        GL.glEndList()

        self._display_list_wire = GL.glGenLists(1)
        GL.glNewList(self._display_list_wire, GL.GL_COMPILE)
        GL.glBegin(GL.GL_LINES)
        for a, b, c in valid_faces:
            for i0, i1 in ((a, b), (b, c), (c, a)):
                GL.glVertex3f(*scaled[i0])
                GL.glVertex3f(*scaled[i1])
        GL.glEnd()
        GL.glEndList()

        self._has_mesh = True
        self._center = (0.0, 0.0, 0.0)
        self._scale = 1.0

        self._reset_view()
        self._info_label.config(text=f"顶点: {nv:,}  面: {nf:,}")

    def _compute_bounds(self, verts):
        if not verts:
            self._center = (0, 0, 0)
            self._scale = 1.0
            return
        min_x = min_y = min_z = float('inf')
        max_x = max_y = max_z = float('-inf')
        for x, y, z in verts:
            if x < min_x: min_x = x
            if x > max_x: max_x = x
            if y < min_y: min_y = y
            if y > max_y: max_y = y
            if z < min_z: min_z = z
            if z > max_z: max_z = z
        self._center = ((min_x+max_x)/2, (min_y+max_y)/2, (min_z+max_z)/2)
        span = max(max_x-min_x, max_y-min_y, max_z-min_z)
        self._scale = 2.0 / max(span, 0.001)

    def _compute_normals(self, verts, faces, flip=False):
        nv = len(verts)
        accum = [[0.0, 0.0, 0.0] for _ in range(nv)]

        for a, b, c in faces:
            if a >= nv or b >= nv or c >= nv:
                continue
            v0 = verts[a]; v1 = verts[b]; v2 = verts[c]
            e1x = v1[0]-v0[0]; e1y = v1[1]-v0[1]; e1z = v1[2]-v0[2]
            e2x = v2[0]-v0[0]; e2y = v2[1]-v0[1]; e2z = v2[2]-v0[2]
            nx = e1y*e2z - e1z*e2y
            ny = e1z*e2x - e1x*e2z
            nz = e1x*e2y - e1y*e2x
            for idx in (a, b, c):
                accum[idx][0] += nx
                accum[idx][1] += ny
                accum[idx][2] += nz

        sign = -1.0 if flip else 1.0
        normals = []
        for ax, ay, az in accum:
            ln = math.sqrt(ax*ax + ay*ay + az*az)
            if ln > 0:
                normals.append((sign*ax/ln, sign*ay/ln, sign*az/ln))
            else:
                normals.append((0.0, 1.0, 0.0))
        return normals

    # ── Rendering (VBO draw) ────────────────────────────────

    def _schedule_render(self):
        if self._render_pending or self._destroyed:
            return
        self._render_pending = True
        self.frame.after(16, self._do_render)

    def _do_render(self):
        self._render_pending = False
        if not self._destroyed:
            self._render()

    def _render(self):
        if not self._gl_inited or self._destroyed:
            return
        self._make_current()

        from OpenGL import GL

        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w < 2 or h < 2:
            return

        GL.glViewport(0, 0, w, h)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        # projection
        GL.glMatrixMode(GL.GL_PROJECTION)
        GL.glLoadIdentity()
        aspect = w / max(h, 1)
        fov = 45.0
        near, far = 0.01, 100.0
        f = 1.0 / math.tan(math.radians(fov) / 2)
        GL.glLoadMatrixf([
            f/aspect, 0, 0, 0,
            0, f, 0, 0,
            0, 0, (far+near)/(near-far), -1,
            0, 0, 2*far*near/(near-far), 0,
        ])

        # modelview
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glLoadIdentity()
        GL.glTranslatef(self._pan_x, self._pan_y, -3.0 / self._zoom)
        GL.glRotatef(self._rot_x, 1, 0, 0)
        GL.glRotatef(self._rot_y, 0, 1, 0)

        # draw mesh
        if self._has_mesh:
            if self._wireframe:
                GL.glDisable(GL.GL_LIGHTING)
                GL.glColor3f(0.4, 0.6, 0.8)
                GL.glCallList(self._display_list_wire)
                GL.glEnable(GL.GL_LIGHTING)
            else:
                if not self._has_colors:
                    GL.glColor3f(0.55, 0.6, 0.7)
                GL.glCallList(self._display_list)

        self._swap_buffers()

    # ── Controls ────────────────────────────────────────────

    def _reset_view(self):
        self._rot_x = 25.0
        self._rot_y = 35.0
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._schedule_render()

    def _toggle_wireframe(self):
        self._wireframe = self._wire_var.get()
        self._schedule_render()

    def _on_press(self, event):
        self._last_mouse = (event.x, event.y)

    def _on_drag(self, event):
        if self._last_mouse:
            dx = event.x - self._last_mouse[0]
            dy = event.y - self._last_mouse[1]
            self._rot_y += dx * 0.5
            self._rot_x += dy * 0.5
            self._rot_x = max(-90, min(90, self._rot_x))
        self._last_mouse = (event.x, event.y)
        self._schedule_render()

    def _on_pan(self, event):
        if self._last_mouse:
            dx = event.x - self._last_mouse[0]
            dy = event.y - self._last_mouse[1]
            self._pan_x += dx * 0.005 / self._zoom
            self._pan_y -= dy * 0.005 / self._zoom
        self._last_mouse = (event.x, event.y)
        self._schedule_render()

    def _on_scroll(self, event):
        if event.delta > 0:
            self._zoom *= 1.15
        else:
            self._zoom /= 1.15
        self._zoom = max(0.1, min(50.0, self._zoom))
        self._schedule_render()

    def _on_resize(self, event):
        self._schedule_render()

    def _close(self):
        self.destroy()
        if self._on_close:
            self._on_close()

    def destroy(self):
        self._destroyed = True
        if self._gl_inited:
            try:
                self._make_current()
                from OpenGL import GL
                if self._display_list:
                    GL.glDeleteLists(self._display_list, 1)
                if self._display_list_wire:
                    GL.glDeleteLists(self._display_list_wire, 1)
                self._opengl32.wglMakeCurrent(0, 0)
                self._opengl32.wglDeleteContext(self._hglrc)
                self._user32.ReleaseDC(self._hwnd, self._hdc)
            except Exception:
                pass
            self._gl_inited = False
        self.frame.destroy()
