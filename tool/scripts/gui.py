#!/usr/bin/env python3
# SkyVEx — GUI frontend & texture pipeline
# Copyright (c) 2026 lingyunalingyun
# License: MIT (see LICENSE)
"""
SkyVEx — 光遇模型可视化便捷导出
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sys
import os
import re
import threading
import queue
import json
import subprocess
import zipfile
import tempfile
from collections import OrderedDict

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

SCENE_ORDER = ["dawn", "prairie", "rain", "sunset", "dusk", "night", "storm"]
SCENE_DISPLAY = {
    "dawn": "晨岛", "prairie": "云野", "rain": "雨林",
    "sunset": "霞谷", "dusk": "墓土", "night": "禁阁", "storm": "伊甸",
}


class StdoutRedirector:
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(_ANSI_RE.sub("", s))

    def flush(self):
        pass


class SkyExportGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("SkyVEx")
        try:
            import ctypes
            self._scale = ctypes.windll.user32.GetDpiForSystem() / 96
        except Exception:
            self._scale = 1.0
        w, h = int(1060 * self._scale), int(740 * self._scale)
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(int(900 * self._scale), int(620 * self._scale))

        self.running = False
        self.log_queue = queue.Queue()
        self.marker_vars = {}
        self.map_entries = OrderedDict()
        self.map_data = {}

        self._modules_loaded = False
        self._export_single_map_fn = None
        self._script_dir = SCRIPT_DIR
        self._bintojson_path = os.path.join(SCRIPT_DIR, "bintojson.py")

        self._setup_style()
        self._build_ui()
        self._poll_log()
        self._import_modules()

    # ── Sky: Children of the Light palette ───────────────
    BG       = "#0a1628"
    BG_PANEL = "#0f1e38"
    BG_ENTRY = "#162848"
    BG_BTN   = "#1a3358"
    BG_HOVER = "#224068"
    FG       = "#e8e4d8"
    FG_DIM   = "#6a7e98"
    ACCENT   = "#f0c050"
    ACCENT_H = "#ffd868"
    BORDER   = "#1a3050"
    GLOW     = "#f8d878"

    def _setup_style(self):
        C = self.__class__
        self.root.configure(bg=C.BG)

        s = ttk.Style()
        s.theme_use("clam")

        s.configure(".", background=C.BG, foreground=C.FG,
                    bordercolor=C.BORDER, darkcolor=C.BG,
                    lightcolor=C.BG_PANEL, troughcolor=C.BG_ENTRY,
                    fieldbackground=C.BG_ENTRY, insertcolor=C.FG,
                    selectbackground=C.ACCENT, selectforeground="#0a0a0a",
                    font=("Segoe UI", 9))

        s.configure("TFrame", background=C.BG)
        s.configure("TLabel", background=C.BG, foreground=C.FG)
        s.configure("TEntry", fieldbackground=C.BG_ENTRY, foreground=C.FG,
                    insertcolor=C.FG)
        s.configure("TCheckbutton", background=C.BG, foreground=C.FG,
                    indicatorcolor=C.BG_ENTRY)
        s.map("TCheckbutton",
              background=[("active", C.BG)],
              indicatorcolor=[("selected", C.ACCENT)])

        s.configure("TButton", background=C.BG_BTN, foreground=C.FG,
                    bordercolor=C.BORDER, padding=(8, 4))
        s.map("TButton",
              background=[("active", C.BG_HOVER), ("disabled", C.BG)],
              foreground=[("disabled", "#3a4a5a")])

        s.configure("TLabelframe", background=C.BG, foreground=C.FG_DIM,
                    bordercolor=C.BORDER)
        s.configure("TLabelframe.Label", background=C.BG, foreground=C.FG_DIM,
                    font=("Segoe UI", 9))

        s.configure("TScrollbar", background=C.BG_PANEL,
                    troughcolor=C.BG, bordercolor=C.BG,
                    arrowcolor=C.FG_DIM)
        s.map("TScrollbar", background=[("active", C.BG_HOVER)])

        s.configure("TProgressbar", background=C.ACCENT,
                    troughcolor=C.BG_ENTRY, bordercolor=C.BORDER)

        s.configure("Map.Treeview", background=C.BG_PANEL,
                    foreground=C.FG, fieldbackground=C.BG_PANEL,
                    rowheight=24, font=("Segoe UI", 9))
        s.map("Map.Treeview",
              background=[("selected", "#1a3860")],
              foreground=[("selected", C.GLOW)])
        s.configure("Map.Treeview.Heading", background=C.BG_BTN,
                    foreground=C.FG, font=("Segoe UI", 9, "bold"))

        s.configure("Title.TLabel", font=("Segoe UI", 18, "bold"),
                    foreground=C.ACCENT)
        s.configure("Sub.TLabel", font=("Segoe UI", 9),
                    foreground=C.FG_DIM)
        s.configure("H.TLabel", font=("Segoe UI", 9, "bold"),
                    foreground=C.FG)

        s.configure("Run.TButton", font=("Segoe UI", 10, "bold"),
                    padding=(18, 7), background=C.ACCENT, foreground="#0a1020")
        s.map("Run.TButton",
              background=[("active", C.ACCENT_H), ("disabled", C.BG_BTN)],
              foreground=[("disabled", "#3a4a5a")])

    def _build_ui(self):
        # gradient header
        hdr_h = 56
        hdr = tk.Canvas(self.root, height=hdr_h, highlightthickness=0, bd=0)
        hdr.pack(fill="x")
        def _paint_header(event=None):
            hdr.delete("bg")
            w = hdr.winfo_width() or 1060
            r0, g0, b0 = 0x08, 0x12, 0x20
            r1, g1, b1 = 0x12, 0x28, 0x48
            for y in range(hdr_h):
                t = y / max(hdr_h - 1, 1)
                r = int(r0 + (r1 - r0) * t)
                g = int(g0 + (g1 - g0) * t)
                b = int(b0 + (b1 - b0) * t)
                hdr.create_line(0, y, w, y, fill=f"#{r:02x}{g:02x}{b:02x}", tags="bg")
            title_id = hdr.create_text(18, hdr_h // 2, anchor="w",
                           text="SkyVEx", fill=self.ACCENT,
                           font=("Segoe UI", 18, "bold"), tags="bg")
            tb = hdr.bbox(title_id)
            sub_x = (tb[2] + 12) if tb else 140
            hdr.create_text(sub_x, hdr_h // 2 + 4, anchor="w",
                           text="光遇模型可视化便捷导出", fill=self.FG_DIM,
                           font=("Segoe UI", 9), tags="bg")
            hdr.create_text(w - 18, hdr_h // 2, anchor="e",
                           text="✦", fill="#2a4060",
                           font=("Segoe UI", 22), tags="bg")
        hdr.bind("<Configure>", _paint_header)
        self.root.after(10, _paint_header)

        # game directory row
        dir_frame = ttk.Frame(self.root, padding=(16, 4, 16, 0))
        dir_frame.pack(fill="x")
        dir_frame.columnconfigure(1, weight=1)
        ttk.Label(dir_frame, text="游戏目录:", style="H.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.game_dir_var = tk.StringVar()
        ttk.Entry(dir_frame, textvariable=self.game_dir_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 4)
        )
        ttk.Button(
            dir_frame, text="浏览", width=6, command=self._browse_game_dir
        ).grid(row=0, column=2)
        ttk.Button(
            dir_frame, text="扫描", width=6, command=self._scan_game_dir
        ).grid(row=0, column=3, padx=(4, 0))
        ttk.Button(
            dir_frame, text="APK", width=5, command=self._open_apk
        ).grid(row=0, column=4, padx=(4, 0))
        ttk.Label(
            self.root,
            text='选择游戏安装根目录 或 APK 安装包，点击「扫描」自动识别地图和 Mesh',
            foreground="#6b7080",
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=(18, 0))

        # mid section: left (maps) + right (options + markers)
        mid_frame = ttk.Frame(self.root)
        mid_frame.pack(fill="both", expand=True, padx=16, pady=(6, 0))

        # ── left: resource list with tabs ──
        map_frame = ttk.LabelFrame(
            mid_frame, text="资源列表", padding=(8, 4, 8, 6)
        )
        map_frame.pack(side="left", fill="both", expand=True)

        tab_bar = tk.Frame(map_frame, bg=self.BG)
        tab_bar.pack(fill="x", pady=(0, 4))

        self._tab_labels = {}
        self._tab_frames = {}
        self._tab_trees = {}
        self._active_tab = "terrain"

        for key, text in [("terrain", "地形"), ("models", "模型库"), ("images", "图片资源")]:
            lbl = tk.Label(
                tab_bar, text=text, fg=self.FG_DIM, bg=self.BG,
                font=("Segoe UI", 9), padx=10, pady=3, cursor="hand2",
            )
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, k=key: self._switch_tab(k))
            self._tab_labels[key] = lbl

        self.map_count_label = tk.Label(
            tab_bar, text="", fg="#6b7080", bg=self.BG, font=("Segoe UI", 8)
        )
        self.map_count_label.pack(side="right")

        for key in ("terrain", "models", "images"):
            frame = tk.Frame(map_frame, bg=self.BG_PANEL)
            tree = ttk.Treeview(
                frame, show="tree", selectmode="none", style="Map.Treeview"
            )
            scroll = ttk.Scrollbar(
                frame, orient="vertical", command=tree.yview
            )
            tree.configure(yscrollcommand=scroll.set)
            tree.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            tree.bind("<Button-1>", self._on_map_click)
            self._tab_frames[key] = frame
            self._tab_trees[key] = tree

        self.map_tree = self._tab_trees["terrain"]
        self._switch_tab("terrain")

        # ── right panel ──
        right_panel = ttk.Frame(mid_frame)
        right_panel.pack(
            side="right", fill="both", expand=True, padx=(8, 0)
        )

        # options
        opt_frame = ttk.LabelFrame(
            right_panel, text="选项", padding=(12, 6, 12, 8)
        )
        opt_frame.pack(fill="x")

        row0 = ttk.Frame(opt_frame)
        row0.pack(fill="x")
        row0.columnconfigure(1, weight=1)
        ttk.Label(row0, text="Mesh 文件夹:", style="H.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.mesh_var = tk.StringVar()
        ttk.Entry(row0, textvariable=self.mesh_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 4)
        )
        ttk.Button(
            row0, text="浏览", width=6, command=self._browse_mesh
        ).grid(row=0, column=2)
        ttk.Label(
            opt_frame,
            text="扫描后自动填充 | 也可手动指定 .mesh 文件所在目录",
            foreground="#6b7080",
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=(2, 0))

        row_out = ttk.Frame(opt_frame)
        row_out.pack(fill="x", pady=(4, 0))
        row_out.columnconfigure(1, weight=1)
        ttk.Label(row_out, text="输出目录:", style="H.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.output_var = tk.StringVar()
        ttk.Entry(row_out, textvariable=self.output_var).grid(
            row=0, column=1, sticky="ew", padx=(6, 4)
        )
        ttk.Button(
            row_out, text="浏览", width=6, command=self._browse_output
        ).grid(row=0, column=2)
        ttk.Label(
            opt_frame,
            text="留空则默认输出到游戏目录下的 Export_Output",
            foreground="#6b7080",
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=(2, 0))

        self.marker_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt_frame,
            text="导出标记小球",
            variable=self.marker_var,
            command=self._on_marker_toggle,
        ).pack(anchor="w", pady=(6, 0))

        self.texture_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            opt_frame,
            text="导出纹理 (KTX→PNG + UV映射)",
            variable=self.texture_var,
        ).pack(anchor="w", pady=(2, 0))

        # marker classes
        marker_frame = ttk.LabelFrame(
            right_panel, text="标记类名", padding=(8, 4, 8, 6)
        )
        marker_frame.pack(fill="both", expand=True, pady=(6, 0))

        marker_btn_row = ttk.Frame(marker_frame)
        marker_btn_row.pack(fill="x", pady=(0, 4))
        ttk.Button(
            marker_btn_row, text="扫描标记类名", width=14,
            command=self._scan_markers,
        ).pack(side="left")

        self.marker_tree = ttk.Treeview(
            marker_frame, show="tree", selectmode="none",
            style="Map.Treeview",
        )
        marker_scroll = ttk.Scrollbar(
            marker_frame, orient="vertical",
            command=self.marker_tree.yview,
        )
        self.marker_tree.configure(yscrollcommand=marker_scroll.set)
        self.marker_tree.pack(side="left", fill="both", expand=True)
        marker_scroll.pack(side="right", fill="y")

        # buttons
        btn_frame = ttk.Frame(self.root, padding=(16, 8, 16, 0))
        btn_frame.pack(fill="x")
        self.run_btn = ttk.Button(
            btn_frame,
            text="开始导出",
            style="Run.TButton",
            command=self._start_export,
        )
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(
            btn_frame,
            text="中止",
            command=self._stop_export,
            state="disabled",
        )
        self.stop_btn.pack(side="left", padx=(8, 0))
        ttk.Button(
            btn_frame, text="清空日志", command=self._clear_log
        ).pack(side="right")
        ttk.Button(
            btn_frame, text="解析模块", command=self._open_script_manager
        ).pack(side="right", padx=(0, 8))
        ttk.Button(
            btn_frame, text="打开输出目录", command=self._open_output
        ).pack(side="right", padx=(0, 8))

        # preview toggle
        self._preview_panel = None
        self._preview_frame = None
        self._preview_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            btn_frame, text="3D 预览",
            variable=self._preview_var,
            command=self._toggle_preview,
        ).pack(side="right", padx=(0, 8))

        # preview container (right of mid_frame, hidden by default)
        self._mid_frame = mid_frame
        self._preview_container = ttk.LabelFrame(
            mid_frame, text="3D 预览", padding=(0, 0, 0, 0),
        )

        # progress
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")
        self.progress.pack(fill="x", padx=16, pady=(6, 0))

        # log output
        log_frame = ttk.LabelFrame(
            self.root, text="日志输出", padding=(4, 2, 4, 4)
        )
        log_frame.pack(fill="both", expand=True, padx=16, pady=(6, 12))
        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            font=("Consolas", 9),
            bg="#081018",
            fg="#d0ccc0",
            insertbackground="#d0ccc0",
            state="disabled",
            relief="flat",
            height=8,
            selectbackground="#1a3860",
            selectforeground="#f8d878",
            highlightthickness=0,
        )
        log_scroll = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.log_text.yview
        )
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self.log_text.tag_configure("ok", foreground="#80d880")
        self.log_text.tag_configure("warn", foreground="#f0c050")
        self.log_text.tag_configure("err", foreground="#e86060")
        self.log_text.tag_configure("info", foreground="#68b8e8")

        self._last_output_dir = None

    # ── browse ─────────────────────────────────────────────
    def _browse_game_dir(self):
        p = filedialog.askdirectory(title="选择光遇游戏安装目录")
        if p:
            self.game_dir_var.set(p)
            self._scan_game_dir()

    def _browse_mesh(self):
        p = filedialog.askdirectory(title="选择 Mesh 文件夹")
        if p:
            self.mesh_var.set(p)

    def _browse_output(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.output_var.set(p)

    # ── APK extraction ────────────────────────────────────
    def _open_apk(self):
        p = filedialog.askopenfilename(
            title="选择光遇 APK 安装包",
            filetypes=[("APK / ZIP", "*.apk *.zip"), ("All files", "*.*")],
        )
        if not p:
            return
        if not zipfile.is_zipfile(p):
            messagebox.showerror("错误", "所选文件不是有效的 APK/ZIP 文件")
            return

        self._log(f"正在解析 APK: {os.path.basename(p)}\n")
        self.progress.configure(mode="determinate", value=0)
        t = threading.Thread(target=self._do_extract_apk, args=(p,), daemon=True)
        t.start()

    def _do_extract_apk(self, apk_path):
        try:
            with zipfile.ZipFile(apk_path, 'r') as zf:
                asset_entries = [e for e in zf.namelist() if e.startswith("assets/")]
                if not asset_entries:
                    self.log_queue.put("❌ APK 中未找到 assets/ 目录\n")
                    self.root.after(0, self._apk_extract_done, None)
                    return

                extract_dir = tempfile.mkdtemp(prefix="skyvex_apk_")
                fake_game = os.path.join(extract_dir, "data")
                os.makedirs(fake_game, exist_ok=True)

                total = len(asset_entries)
                self.log_queue.put(f"解压 {total} 个资源文件...\n")
                self.root.after(0, lambda: self.progress.configure(maximum=total))

                for i, entry in enumerate(asset_entries):
                    if entry.endswith('/'):
                        continue
                    dest = os.path.join(fake_game, entry)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(entry) as src, open(dest, 'wb') as dst:
                        dst.write(src.read())
                    if i % 200 == 0:
                        self.root.after(0, lambda v=i: self.progress.configure(value=v))

                self.root.after(0, lambda: self.progress.configure(value=total))
                self.log_queue.put(f"[OK] 解压完成 → {extract_dir}\n")
                self.root.after(0, self._apk_extract_done, extract_dir)

        except Exception as e:
            self.log_queue.put(f"❌ APK 解压出错: {e}\n")
            self.root.after(0, self._apk_extract_done, None)

    def _apk_extract_done(self, extract_dir):
        self.progress.configure(mode="indeterminate", value=0)
        if extract_dir:
            self.game_dir_var.set(extract_dir)
            self._scan_game_dir()

    # ── game dir scanning ──────────────────────────────────
    def _scan_game_dir(self):
        game_dir = self.game_dir_var.get().strip()
        if not game_dir or not os.path.isdir(game_dir):
            messagebox.showwarning("提示", "请先选择有效的游戏目录")
            return

        assets_dir = os.path.join(game_dir, "data", "assets")
        if not os.path.isdir(assets_dir):
            messagebox.showwarning(
                "提示",
                "未找到 data/assets 目录\n请确认选择了正确的游戏安装根目录",
            )
            return

        # auto-detect mesh dir
        mesh_dir = os.path.join(assets_dir, "meshes", "Data", "Meshes", "Bin")
        mesh_files = []
        if os.path.isdir(mesh_dir):
            self.mesh_var.set(mesh_dir)
            mesh_files = sorted(
                f for f in os.listdir(mesh_dir) if f.endswith(".mesh")
            )
            self._log(f"[OK] Mesh 目录: {len(mesh_files)} 个 .mesh 文件\n")

        # scan scenes
        try:
            entries = set(os.listdir(assets_dir))
        except OSError as e:
            messagebox.showerror("错误", str(e))
            return

        scene_list = [s for s in SCENE_ORDER if s in entries]
        for entry in sorted(entries):
            if entry not in SCENE_ORDER and entry != "meshes":
                levels = os.path.join(assets_dir, entry, "Data", "Levels")
                if os.path.isdir(levels):
                    scene_list.append(entry)

        self.map_entries.clear()
        self.map_data.clear()
        total_maps = 0

        for scene in scene_list:
            levels_dir = os.path.join(assets_dir, scene, "Data", "Levels")
            if not os.path.isdir(levels_dir):
                continue
            maps = []
            try:
                for entry in sorted(os.listdir(levels_dir)):
                    sub = os.path.join(levels_dir, entry)
                    if os.path.isdir(sub) and os.path.exists(
                        os.path.join(sub, "Objects.level.bin")
                    ):
                        maps.append((entry, sub))
            except OSError:
                continue
            if maps:
                self.map_entries[scene] = maps
                total_maps += len(maps)

        self._populate_map_list(mesh_files, mesh_dir)
        self._log(
            f"[OK] 扫描完成: {len(self.map_entries)} 个区域, {total_maps} 张地图, {len(mesh_files)} 个模型\n"
        )

    def _populate_map_list(self, mesh_files=None, mesh_dir=None):
        for tree in self._tab_trees.values():
            children = tree.get_children()
            if children:
                tree.delete(*children)
        self.map_data.clear()

        terrain_tree = self._tab_trees["terrain"]
        for scene, maps in self.map_entries.items():
            display = SCENE_DISPLAY.get(scene, scene)
            sid = terrain_tree.insert(
                "", "end",
                text=f"{display} ({scene}) — {len(maps)} 张",
                open=True,
            )
            self.map_data[f"t:{sid}"] = {"scene": scene, "selected": True}

            for name, path in maps:
                iid = terrain_tree.insert(sid, "end", text=name)
                self.map_data[f"t:{iid}"] = {
                    "name": name, "path": path, "selected": True,
                }

        if mesh_files and mesh_dir:
            self._populate_mesh_entries(mesh_files, mesh_dir)
        try:
            self._populate_image_entries()
        except Exception as e:
            self._log(f"[WARN] 图片资源扫描失败: {e}\n")

        self._update_map_count()

    def _populate_mesh_entries(self, mesh_files, mesh_dir):
        mesh_tree = self._tab_trees["models"]
        groups = OrderedDict()
        for f in mesh_files:
            name = f[:-5]
            prefix = re.match(r'^([A-Za-z]+\d*)', name)
            group = prefix.group(1) if prefix else "Other"
            groups.setdefault(group, []).append((name, os.path.join(mesh_dir, f)))

        root_id = mesh_tree.insert(
            "", "end",
            text=f"模型库 — {len(mesh_files)} 个模型",
            open=False,
        )
        self.map_data[f"m:{root_id}"] = {"mesh_root": True}

        for group, items in groups.items():
            gid = mesh_tree.insert(
                root_id, "end",
                text=f"{group} ({len(items)})",
                open=False,
            )
            self.map_data[f"m:{gid}"] = {"mesh_group": group}
            for name, path in items:
                iid = mesh_tree.insert(gid, "end", text=name)
                self.map_data[f"m:{iid}"] = {
                    "name": name, "mesh_file": path, "selected": True,
                }

    def _populate_image_entries(self):
        image_tree = self._tab_trees["images"]
        game_dir = self.game_dir_var.get().strip()
        if not game_dir:
            return
        candidates = [
            os.path.join(game_dir, "data", "assets", "initial", "Data", "Images", "Bin", "BC"),
            os.path.join(game_dir, "data", "assets", "images", "Data", "Images", "Bin", "BC"),
        ]
        total = 0
        for img_dir in candidates:
            if not os.path.isdir(img_dir):
                continue
            ktx_files = sorted(f for f in os.listdir(img_dir) if f.lower().endswith(".ktx"))
            if not ktx_files:
                continue
            rel = os.path.relpath(img_dir, game_dir)
            gid = image_tree.insert(
                "", "end",
                text=f"{rel} — {len(ktx_files)} 张",
                open=False,
            )
            self.map_data[f"i:{gid}"] = {"image_dir": img_dir}
            for f in ktx_files:
                name = os.path.splitext(f)[0]
                iid = image_tree.insert(gid, "end", text=name)
                self.map_data[f"i:{iid}"] = {
                    "name": name, "image_file": os.path.join(img_dir, f),
                }
                total += 1

    def _switch_tab(self, key):
        for k, frame in self._tab_frames.items():
            frame.pack_forget()
        self._tab_frames[key].pack(fill="both", expand=True)
        for k, lbl in self._tab_labels.items():
            if k == key:
                lbl.configure(fg=self.ACCENT, font=("Segoe UI", 9, "bold"))
            else:
                lbl.configure(fg=self.FG_DIM, font=("Segoe UI", 9))
        self._active_tab = key

    _TAB_PREFIX = {"terrain": "t", "models": "m", "images": "i"}

    def _on_map_click(self, event):
        tree = self._tab_trees.get(self._active_tab)
        if not tree:
            return
        iid = tree.identify_row(event.y)
        if not iid:
            return
        key = f"{self._TAB_PREFIX.get(self._active_tab, '')}:{iid}"
        data = self.map_data.get(key)
        if not data:
            return

        if "path" in data:
            if self._preview_panel:
                self._show_3d_preview()
                self._load_preview_for_map(data["path"])
        elif "mesh_file" in data:
            if self._preview_panel:
                self._show_3d_preview()
                self._load_preview_for_mesh(data["mesh_file"])
        elif "image_file" in data:
            if self._preview_panel:
                self._load_preview_for_image(data["image_file"], data.get("name", ""))

    def _update_map_count(self):
        maps = sum(1 for d in self.map_data.values() if "path" in d)
        meshes = sum(1 for d in self.map_data.values() if "mesh_file" in d)
        parts = []
        if maps:
            parts.append(f"{maps} 张地图")
        if meshes:
            parts.append(f"{meshes} 个模型")
        self.map_count_label.configure(text="共 " + ", ".join(parts) if parts else "")

    def _get_selected_maps(self):
        return [
            (d["name"], d["path"])
            for d in self.map_data.values()
            if "path" in d
        ]

    def _get_selected_meshes(self):
        return [
            (d["name"], d["mesh_file"])
            for d in self.map_data.values()
            if "mesh_file" in d
        ]

    # ── marker scanning ───────────────────────────────────
    def _on_marker_toggle(self):
        pass

    def _scan_markers(self):
        selected = [
            (name, path)
            for maps in self.map_entries.values()
            for name, path in maps
        ]
        if not selected:
            return

        self.progress.configure(mode="determinate", maximum=len(selected), value=0)
        self._log(f"正在扫描标记类名 (0/{len(selected)})...\n")

        t = threading.Thread(
            target=self._do_scan_markers, args=(selected,), daemon=True
        )
        t.start()

    def _do_scan_markers(self, selected):
        try:
            self._do_scan_markers_inner(selected)
        except Exception as e:
            self.log_queue.put(f"[ERR] 标记扫描线程崩溃: {e}\n")

    def _do_scan_markers_inner(self, selected):
        classes = set()
        total = len(selected)

        try:
            from bintojson import parse_bin
        except ImportError:
            parse_bin = None
            self.log_queue.put("[WARN] bintojson 导入失败，回退到 JSON 文件\n")

        for i, (name, path) in enumerate(selected):
            bin_file = os.path.join(path, "Objects.level.bin")
            if not os.path.exists(bin_file):
                for f in os.listdir(path):
                    if f.endswith(".bin") and not f.endswith(".meshes"):
                        bin_file = os.path.join(path, f)
                        break

            if not os.path.exists(bin_file):
                self.root.after(0, self._scan_markers_tick, i + 1, total)
                continue

            try:
                if parse_bin:
                    data = parse_bin(bin_file)
                else:
                    json_path = bin_file + ".json"
                    if not os.path.exists(json_path):
                        self.root.after(0, self._scan_markers_tick, i + 1, total)
                        continue
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                bst = data.get("BSTNodes", {})
                for nd in bst.values():
                    if isinstance(nd, dict):
                        for cn in nd:
                            if "LevelMesh" not in cn:
                                classes.add(cn)
            except Exception:
                pass

            self.root.after(0, self._scan_markers_tick, i + 1, total)

        result = sorted(classes)
        self.root.after(0, self._scan_markers_done, result)

    def _scan_markers_tick(self, current, total):
        self.progress.configure(value=current)

    def _scan_markers_done(self, class_names):
        self.progress.configure(mode="indeterminate", value=0)
        self._populate_marker_checkboxes(class_names)
        self._log(f"[OK] 标记扫描完成: 找到 {len(class_names)} 个标记类名\n")

    def _populate_marker_checkboxes(self, class_names):
        self.marker_tree.delete(*self.marker_tree.get_children())
        self.marker_vars.clear()

        for cn in class_names:
            iid = self.marker_tree.insert("", "end", text=cn)
            self.marker_vars[iid] = {"name": cn, "selected": True}

    # ── module import ──────────────────────────────────────

    def _import_modules(self):
        self._export_single_map_fn = None
        self._batch_mod = None
        self._bintojson_path = os.path.join(self._script_dir, "bintojson.py")
        try:
            import importlib.util
            import io as _io

            batch_path = os.path.join(self._script_dir, "batch_export.py")
            if os.path.exists(batch_path):
                old_out, old_err = sys.stdout, sys.stderr
                sys.stdout = cap = _io.StringIO()
                sys.stderr = _io.StringIO()
                try:
                    if self._script_dir not in sys.path:
                        sys.path.insert(0, self._script_dir)
                    spec = importlib.util.spec_from_file_location(
                        "_batch", batch_path
                    )
                    bmod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(bmod)
                    self._export_single_map_fn = getattr(
                        bmod, "export_single_map", None
                    )
                    self._batch_mod = bmod
                finally:
                    sys.stdout, sys.stderr = old_out, old_err

                for line in cap.getvalue().strip().splitlines():
                    self._log(line + "\n")

            self._modules_loaded = True
            self._log(f"[OK] 模块加载完成 ({self._script_dir})\n")
        except Exception as e:
            self._log(f"[WARN] 模块加载失败: {e}\n")

    # ── script manager ─────────────────────────────────────
    def _toggle_preview(self):
        if self._preview_var.get():
            self._show_preview()
        else:
            self._hide_preview()

    def _show_preview(self):
        if self._preview_panel:
            return
        try:
            from preview3d import PreviewPanel, is_available
            if not is_available():
                self._log("[WARN] PyOpenGL 未安装，无法启用 3D 预览\n")
                self._log("       pip install PyOpenGL PyOpenGL_accelerate\n")
                self._preview_var.set(False)
                return
        except ImportError:
            self._log("[WARN] preview3d.py 未找到\n")
            self._preview_var.set(False)
            return

        self._preview_container.pack(
            side="right", fill="both", expand=True, padx=(8, 0),
        )
        self._preview_panel = PreviewPanel(
            self._preview_container,
            on_close=self._on_preview_closed,
        )
        self._preview_panel.frame.pack(fill="both", expand=True)

        self._image_preview_frame = tk.Frame(self._preview_container, bg="#050d18")
        self._image_preview_label = tk.Label(
            self._image_preview_frame, bg="#050d18", anchor="center",
        )
        self._image_preview_label.pack(fill="both", expand=True)
        self._image_preview_info = tk.Label(
            self._image_preview_frame, text="", fg="#506070", bg="#0a1628",
            font=("Segoe UI", 8),
        )
        self._image_preview_info.pack(side="bottom", fill="x")
        self._image_photo = None

        self._log("[OK] 3D 预览面板已启用\n")

        selected = self._get_selected_maps()
        if selected:
            self._load_preview_for_map(selected[0][1])

    def _hide_preview(self):
        if self._preview_panel:
            self._preview_panel.destroy()
            self._preview_panel = None
        self._image_photo = None
        self._preview_container.pack_forget()

    def _on_preview_closed(self):
        self._preview_panel = None
        self._preview_container.pack_forget()
        self._preview_var.set(False)

    def _load_preview_for_map(self, map_path):
        if not self._preview_panel:
            return
        meshes_file = os.path.join(map_path, "BstBaked.meshes")
        if not os.path.isfile(meshes_file):
            self._log(f"[WARN] 未找到: {meshes_file}\n")
            return

        if self._batch_mod:
            try:
                verts, faces, colors, _mat_ids = self._batch_mod.parse_meshes_to_obj_data(meshes_file)
                if verts and faces:
                    self._preview_panel.load_mesh(verts, faces, colors=colors, flip_normals=True)
                    name = os.path.basename(os.path.dirname(map_path)) or os.path.basename(map_path)
                    self._log(f"[OK] 预览: {name} ({len(verts):,} 顶点, {len(faces):,} 面)\n")
                else:
                    self._log(f"[WARN] 解析返回空数据: verts={len(verts)}, faces={len(faces)}\n")
            except Exception as e:
                import traceback
                self._log(f"[WARN] 预览加载失败: {e}\n")
                self._log(traceback.format_exc() + "\n")

    def _load_preview_for_mesh(self, mesh_path):
        if not self._preview_panel:
            return
        if not os.path.isfile(mesh_path):
            self._log(f"[WARN] 未找到: {mesh_path}\n")
            return

        name = os.path.splitext(os.path.basename(mesh_path))[0]
        if self._batch_mod:
            try:
                verts, uvs, faces = self._batch_mod.parse_mesh_file(mesh_path)
                if not verts or not faces:
                    self._log(f"[WARN] {name}: 无法解析 (不支持的格式或空数据)\n")
                    return
                self._preview_panel.load_mesh(verts, faces)
                self._log(f"[OK] 预览: {name} ({len(verts):,} 顶点, {len(faces):,} 面)\n")
            except Exception as e:
                import traceback
                self._log(f"[WARN] {name}: 预览失败 — {e}\n")
                self._log(traceback.format_exc() + "\n")

    def _show_3d_preview(self):
        if hasattr(self, '_image_preview_frame'):
            self._image_preview_frame.pack_forget()
        if self._preview_panel:
            self._preview_panel.frame.pack(fill="both", expand=True)

    def _show_image_preview(self):
        if self._preview_panel:
            self._preview_panel.frame.pack_forget()
        if hasattr(self, '_image_preview_frame'):
            self._image_preview_frame.pack(fill="both", expand=True)

    _KTX_DECODERS = {
        0x8E8F: 'decode_bc6',  # GL_COMPRESSED_RGB_BPTC_UNSIGNED_FLOAT
        0x8E8E: 'decode_bc6',  # GL_COMPRESSED_RGB_BPTC_SIGNED_FLOAT
        0x8E8C: 'decode_bc7',  # GL_COMPRESSED_RGBA_BPTC_UNORM
        0x83F0: 'decode_bc1',  # GL_COMPRESSED_RGB_S3TC_DXT1
        0x83F1: 'decode_bc1',  # GL_COMPRESSED_RGBA_S3TC_DXT1
        0x83F3: 'decode_bc3',  # GL_COMPRESSED_RGBA_S3TC_DXT5
        0x8DBB: 'decode_bc4',  # GL_COMPRESSED_RED_RGTC1
        0x8DBD: 'decode_bc5',  # GL_COMPRESSED_RG_RGTC2
    }

    def _load_preview_for_image(self, ktx_path, name=""):
        if not self._preview_panel:
            return
        self._show_image_preview()
        try:
            import struct as _struct
            import texture2ddecoder
            from PIL import Image as PILImage, ImageTk

            with open(ktx_path, 'rb') as f:
                f.read(12 + 4 + 4 + 4 + 4)
                gl_internal_fmt = _struct.unpack('<I', f.read(4))[0]
                f.read(4)
                width = _struct.unpack('<I', f.read(4))[0]
                height = _struct.unpack('<I', f.read(4))[0]
                f.read(4 + 4 + 4 + 4)
                kvd_len = _struct.unpack('<I', f.read(4))[0]
                f.read((kvd_len + 3) & ~3)
                img_size = _struct.unpack('<I', f.read(4))[0]
                img_data = f.read(img_size)

            decoder_name = self._KTX_DECODERS.get(gl_internal_fmt)
            if not decoder_name:
                self._image_preview_label.configure(image="")
                self._image_preview_info.configure(
                    text=f"{name}  不支持的格式: 0x{gl_internal_fmt:04X}")
                self._log(f"[WARN] {name}: 不支持的 KTX 格式 0x{gl_internal_fmt:04X}\n")
                return

            decoder_fn = getattr(texture2ddecoder, decoder_name)
            decoded = decoder_fn(img_data, width, height)
            img = PILImage.frombytes('RGBA', (width, height), decoded)
            b, g, r, a = img.split()
            img = PILImage.merge('RGBA', (r, g, b, a))

            max_w = self._image_preview_label.winfo_width() or 400
            max_h = self._image_preview_label.winfo_height() or 400
            scale = min(max_w / width, max_h / height, 1.0)
            if scale < 1.0:
                img = img.resize((int(width * scale), int(height * scale)), PILImage.LANCZOS)

            self._image_photo = ImageTk.PhotoImage(img)
            self._image_preview_label.configure(image=self._image_photo)
            self._image_preview_info.configure(text=f"{name}  ({width}×{height})")
            self._log(f"[OK] 图片预览: {name} ({width}×{height})\n")
        except Exception as e:
            self._image_preview_label.configure(image="")
            self._image_preview_info.configure(text=f"解码失败: {e}")
            self._log(f"[WARN] 图片预览失败: {e}\n")

    def _open_script_manager(self):
        win = tk.Toplevel(self.root)
        win.title("解析模块管理")
        win.geometry("1100x700")
        win.resizable(True, True)
        win.minsize(800, 500)
        win.transient(self.root)
        win.grab_set()
        win.configure(bg=self.BG)

        ttk.Label(
            win, text="解析模块", font=("Segoe UI", 12, "bold"),
            foreground=self.ACCENT,
        ).pack(anchor="w", padx=16, pady=(12, 4))

        # script dir
        dir_frame = ttk.Frame(win, padding=(16, 4, 16, 0))
        dir_frame.pack(fill="x")
        dir_frame.columnconfigure(1, weight=1)
        ttk.Label(dir_frame, text="脚本目录:", style="H.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        dir_var = tk.StringVar(value=self._script_dir)
        ttk.Entry(dir_frame, textvariable=dir_var, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(6, 4)
        )

        def browse_dir():
            p = filedialog.askdirectory(
                title="选择解析脚本所在目录", parent=win
            )
            if p:
                dir_var.set(p)

        ttk.Button(dir_frame, text="更换", width=6, command=browse_dir).grid(
            row=0, column=2
        )

        # ── Backend status ──
        from backends import get_meshes_backends, get_mesh_backends

        backend_frame = ttk.LabelFrame(
            win, text="后端状态", padding=(12, 6, 12, 8)
        )
        backend_frame.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        def _get_active_name(kind):
            attr = f'_active_{kind}_backend'
            if self._batch_mod and hasattr(self._batch_mod, attr):
                ab = getattr(self._batch_mod, attr)
                if ab:
                    return ab.name
            return ""

        def _validate_file(filepath):
            ext = os.path.splitext(filepath)[1].lower()
            if ext == '.py':
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                        source = f.read()
                    compile(source, filepath, 'exec')
                    return True, None
                except SyntaxError as e:
                    return False, f"Python 语法错误: 第 {e.lineno} 行\n{e.msg}"
                except Exception as e:
                    return False, f"无法读取文件: {e}"
            elif ext == '.dll':
                try:
                    import ctypes
                    ctypes.CDLL(filepath)
                    return True, None
                except OSError as e:
                    return False, f"DLL 加载失败: {e}"
            return True, None

        def _select_file_for_backend(bk):
            src_files = getattr(bk, 'source_files', [])
            if not src_files:
                return
            exts = set()
            for f in src_files:
                ext = os.path.splitext(f)[1]
                if ext:
                    exts.add(ext)
            filetypes = []
            if '.py' in exts:
                filetypes.append(("Python 脚本", "*.py"))
            if '.dll' in exts:
                filetypes.append(("动态链接库", "*.dll"))
            filetypes.append(("所有文件", "*.*"))

            chosen = filedialog.askopenfilename(
                title=f"选择 {bk.name} 的脚本文件",
                initialdir=dir_var.get(),
                filetypes=filetypes,
                parent=win,
            )
            if not chosen:
                return

            valid, err = _validate_file(chosen)
            if not valid:
                messagebox.showerror(
                    "文件不可用",
                    f"所选文件无法作为解析模块使用:\n\n{err}",
                    parent=win,
                )
                return

            import shutil
            dest_name = os.path.basename(chosen)
            dest_path = os.path.join(self._script_dir, dest_name)
            if os.path.abspath(chosen) == os.path.abspath(dest_path):
                self._log(f"[INFO] 文件已在脚本目录中: {dest_name}\n")
                return
            try:
                shutil.copy2(chosen, dest_path)
                self._log(f"[OK] 已复制 {dest_name} → {self._script_dir}\n")
            except Exception as e:
                messagebox.showerror("复制失败", str(e), parent=win)

        def _show_backend_info(bk):
            info_win = tk.Toplevel(win)
            info_win.title(f"模块说明 — {bk.name}")
            info_win.geometry("880x640")
            info_win.resizable(True, True)
            info_win.transient(win)
            info_win.grab_set()
            info_win.configure(bg=self.BG)

            txt = tk.Text(
                info_win, wrap="word", bg=self.BG, fg="#d0d0d0",
                font=("Segoe UI", 9), relief="flat", padx=14, pady=12,
                insertbackground=self.BG,
            )
            btn_frame = ttk.Frame(info_win)
            btn_frame.pack(side="bottom", fill="x", pady=(6, 10))
            ttk.Button(
                btn_frame, text="关闭", command=info_win.destroy,
            ).pack()

            txt.pack(fill="both", expand=True, padx=8, pady=(8, 0))
            txt.configure(font=("Segoe UI", 11))
            txt.tag_configure("title", font=("Segoe UI", 16, "bold"), foreground=self.ACCENT)
            txt.tag_configure("meta", foreground="#8090a0", font=("Segoe UI", 10))

            txt.insert("end", f"{bk.name}\n", "title")
            txt.insert("end", f"{bk.description}\n\n", "meta")
            txt.insert("end", getattr(bk, 'info', '暂无说明。'))
            txt.configure(state="disabled")

        def _activate_backend(kind, name):
            if not self._batch_mod or not hasattr(self._batch_mod, '_init_backends'):
                return
            kwargs = {}
            if kind == "meshes":
                kwargs["preferred_meshes"] = name
                cur = _get_active_name("mesh")
                if cur:
                    kwargs["preferred_mesh"] = cur
            else:
                kwargs["preferred_mesh"] = name
                cur = _get_active_name("meshes")
                if cur:
                    kwargs["preferred_meshes"] = cur
            self._batch_mod._init_backends(**kwargs)
            ab = getattr(self._batch_mod, f'_active_{kind}_backend', None)
            if ab:
                self._log(f"[OK] .{kind} 后端已切换: {ab.name}\n")
            refresh_backends()

        def _make_backend_row(parent, bk, is_active, kind):
            avail = bk.is_available()
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=2, padx=(8, 0))
            row.columnconfigure(0, weight=1)

            status = "✓" if avail else "✗"
            color = self.ACCENT if is_active else ("#6ec86e" if avail else "#e05050")
            prefix = "▶ " if is_active else "  "

            lbl_frame = ttk.Frame(row)
            lbl_frame.grid(row=0, column=0, sticky="w")
            ttk.Label(
                lbl_frame, text=f"{prefix}{status} {bk.name}",
                font=("Consolas", 9, "bold" if is_active else ""),
                foreground=color,
            ).pack(side="left")
            ttk.Label(
                lbl_frame, text=f"  {bk.description}",
                foreground="#8090a0" if not is_active else "#b0c0d0",
                font=("Segoe UI", 8),
            ).pack(side="left", padx=(2, 0))

            col = 1
            if avail and not is_active:
                bk_name = bk.name
                ttk.Button(
                    row, text="启用", width=4,
                    command=lambda n=bk_name, k=kind: _activate_backend(k, n),
                ).grid(row=0, column=col, padx=(4, 0))
                col += 1

            bk_ref = bk
            ttk.Button(
                row, text="选择", width=4,
                command=lambda b=bk_ref: _select_file_for_backend(b),
            ).grid(row=0, column=col, padx=(4, 0))
            ttk.Button(
                row, text="ⓘ", width=2,
                command=lambda b=bk_ref: _show_backend_info(b),
            ).grid(row=0, column=col + 1, padx=(2, 0))

        def refresh_backends():
            for w in backend_frame.winfo_children():
                w.destroy()

            active_meshes = _get_active_name("meshes")
            active_mesh = _get_active_name("mesh")

            ttk.Label(
                backend_frame, text=".meshes 后端 (地形/关卡几何)",
                style="H.TLabel",
            ).pack(anchor="w", pady=(0, 4))

            meshes_bk = get_meshes_backends()
            for name, bk in meshes_bk.items():
                _make_backend_row(backend_frame, bk, name == active_meshes, "meshes")

            ttk.Label(
                backend_frame, text=".mesh 后端 (模型)",
                style="H.TLabel",
            ).pack(anchor="w", pady=(12, 4))

            mesh_bk = get_mesh_backends()
            for name, bk in mesh_bk.items():
                _make_backend_row(backend_frame, bk, name == active_mesh, "mesh")

        refresh_backends()

        def open_dir():
            d = dir_var.get()
            if os.path.isdir(d):
                os.startfile(d)

        # buttons
        btn_frame = ttk.Frame(win, padding=(16, 10, 16, 12))
        btn_frame.pack(fill="x")

        ttk.Button(
            btn_frame, text="打开目录", command=open_dir
        ).pack(side="left")
        ttk.Button(
            btn_frame, text="关闭", command=win.destroy
        ).pack(side="right")
        ttk.Button(
            btn_frame, text="刷新", command=refresh_backends
        ).pack(side="right", padx=(0, 6))

    # ── export ─────────────────────────────────────────────
    def _start_export(self):
        if self.running:
            return

        selected = self._get_selected_maps()
        selected_meshes = self._get_selected_meshes()
        if not selected and not selected_meshes:
            messagebox.showwarning("提示", "请选择至少一张地图或一个模型")
            return

        mesh_dir = self.mesh_var.get().strip()
        output_dir = self.output_var.get().strip() or None
        export_markers = self.marker_var.get()

        enabled_classes = None
        if export_markers and self.marker_vars:
            enabled_classes = [
                d["name"] for d in self.marker_vars.values()
            ]

        image_dirs = None
        if self.texture_var.get():
            game_dir = self.game_dir_var.get().strip()
            if game_dir:
                assets = os.path.join(game_dir, "data", "assets")
                candidates = [
                    os.path.join(assets, "initial", "Data", "Images", "Bin", "BC"),
                    os.path.join(assets, "images", "Data", "Images", "Bin", "BC"),
                ]
                image_dirs = [d for d in candidates if os.path.isdir(d)]

        self.running = True
        self.run_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.progress.start(15)

        t = threading.Thread(
            target=self._do_export,
            args=(selected, mesh_dir, export_markers, enabled_classes, output_dir, image_dirs, selected_meshes),
            daemon=True,
        )
        t.start()

    def _do_export(
        self, selected, mesh_dir, export_markers, enabled_classes,
        output_dir, image_dirs, selected_meshes=None,
    ):
        redirector = StdoutRedirector(self.log_queue)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = redirector
        sys.stderr = redirector
        try:
            if not output_dir:
                game_dir = self.game_dir_var.get().strip()
                if game_dir:
                    output_dir = os.path.join(game_dir, "Export_Output")
                elif selected:
                    output_dir = os.path.join(
                        os.path.dirname(selected[0][1]), "输出"
                    )
                elif selected_meshes:
                    output_dir = os.path.join(
                        os.path.dirname(selected_meshes[0][1]), "输出"
                    )
            os.makedirs(output_dir, exist_ok=True)
            self._last_output_dir = output_dir

            if selected and self._export_single_map_fn:
                total = len(selected)
                self.log_queue.put(f"开始导出 {total} 张地图\n\n")
                success = 0
                fail = 0

                for i, (name, path) in enumerate(selected, 1):
                    if not self.running:
                        self.log_queue.put("\n⚠️ 已中止\n")
                        break
                    self.log_queue.put(f"[{i}/{total}] {name}\n")
                    log_entry = {}
                    ok = self._export_single_map_fn(
                        path,
                        mesh_dir,
                        output_dir,
                        export_markers,
                        enabled_classes,
                        log_entry,
                        image_dirs=image_dirs,
                    )
                    if ok:
                        success += 1
                        tv = log_entry.get("terrain_verts", 0)
                        tt = log_entry.get("terrain_tris", 0)
                        mc = log_entry.get("models_count", 0)
                        mi = log_entry.get("models_instances", 0)
                        mk = log_entry.get("markers_count", 0)
                        tc = log_entry.get("textures_count", 0)
                        info = f"   ✅ 地形:{tv}v/{tt}t  模型:{mc}种/{mi}实例  标记:{mk}"
                        if tc:
                            info += f"  纹理:{tc}"
                        self.log_queue.put(info + "\n")
                    else:
                        fail += 1
                        err = log_entry.get("error", "未知")
                        self.log_queue.put(f"   ❌ {err}\n")

                self.log_queue.put(
                    f"\n地图导出完成: 成功 {success}/{total}，失败 {fail}\n"
                )

            if selected_meshes and self._batch_mod and self.running:
                self._do_export_meshes(selected_meshes, output_dir)

            if not self._export_single_map_fn and not self._batch_mod:
                self.log_queue.put("❌ 导出模块未加载\n")
        except Exception as e:
            self.log_queue.put(f"\n❌ 导出出错: {e}\n")
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            self.root.after(0, self._export_done)

    def _do_export_meshes(self, selected_meshes, output_dir):
        mesh_out = os.path.join(output_dir, "Meshes")
        os.makedirs(mesh_out, exist_ok=True)

        total = len(selected_meshes)
        self.log_queue.put(f"\n开始导出 {total} 个独立模型\n\n")
        success = 0
        fail = 0

        for i, (name, path) in enumerate(selected_meshes, 1):
            if not self.running:
                self.log_queue.put("\n⚠️ 已中止\n")
                break
            try:
                verts, uvs, faces = self._batch_mod.parse_mesh_file(path)
                if not verts or not faces:
                    self.log_queue.put(f"[{i}/{total}] {name} — ❌ 空数据\n")
                    fail += 1
                    continue

                obj_path = os.path.join(mesh_out, f"{name}.obj")
                with open(obj_path, 'w', encoding='utf-8') as f:
                    f.write(f"# Sky Mesh: {name}\n")
                    f.write(f"o {name}\n")
                    for v in verts:
                        f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
                    if uvs:
                        for uv in uvs:
                            f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
                    for tri in faces:
                        if uvs:
                            f.write(f"f {tri[0]+1}/{tri[0]+1} {tri[1]+1}/{tri[1]+1} {tri[2]+1}/{tri[2]+1}\n")
                        else:
                            f.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")

                self.log_queue.put(f"[{i}/{total}] {name} — ✅ {len(verts):,}v/{len(faces):,}t\n")
                success += 1
            except Exception as e:
                self.log_queue.put(f"[{i}/{total}] {name} — ❌ {e}\n")
                fail += 1

        self.log_queue.put(
            f"\n模型导出完成: 成功 {success}/{total}，失败 {fail}\n"
        )

    def _export_done(self):
        self.running = False
        self.run_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.progress.stop()
        self.root.bell()

    def _stop_export(self):
        self.running = False
        self._log("正在中止...\n")

    # ── log ────────────────────────────────────────────────
    def _log(self, msg):
        self.log_queue.put(msg)

    def _poll_log(self):
        batch = []
        try:
            while True:
                batch.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass

        if batch:
            self.log_text.configure(state="normal")
            for msg in batch:
                tag = None
                if "✅" in msg or "[OK]" in msg:
                    tag = "ok"
                elif "❌" in msg or "[ERR]" in msg:
                    tag = "err"
                elif "⚠️" in msg or "[WARN]" in msg:
                    tag = "warn"
                elif "📖" in msg or "📝" in msg or "🔍" in msg:
                    tag = "info"
                if tag:
                    self.log_text.insert(tk.END, msg, (tag,))
                else:
                    self.log_text.insert(tk.END, msg)
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")

        self.root.after(80, self._poll_log)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _open_output(self):
        if self._last_output_dir and os.path.isdir(self._last_output_dir):
            os.startfile(self._last_output_dir)
            return
        out = self.output_var.get().strip()
        if out and os.path.isdir(out):
            os.startfile(out)
            return
        messagebox.showinfo("提示", "没有可打开的输出目录")


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    _icon_path = os.path.join(os.path.dirname(SCRIPT_DIR), os.pardir, "icon.ico")
    if os.path.isfile(_icon_path):
        root.iconbitmap(_icon_path)
    else:
        try:
            root.iconbitmap(default="")
        except tk.TclError:
            pass
    SkyExportGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
