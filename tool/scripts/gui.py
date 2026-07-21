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
        self.root.geometry("1060x740")
        self.root.minsize(900, 620)

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

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Sub.TLabel", font=("Segoe UI", 9), foreground="#666")
        style.configure("H.TLabel", font=("Segoe UI", 9, "bold"))
        style.configure(
            "Run.TButton", font=("Segoe UI", 10, "bold"), padding=(16, 6)
        )
        style.configure(
            "Map.Treeview", font=("Segoe UI", 9), rowheight=22
        )
        style.configure(
            "Map.Treeview.Heading", font=("Segoe UI", 9, "bold")
        )

    def _build_ui(self):
        # header
        hdr = ttk.Frame(self.root, padding=(16, 10, 16, 4))
        hdr.pack(fill="x")
        ttk.Label(hdr, text="SkyVEx", style="Title.TLabel").pack(
            side="left"
        )
        ttk.Label(
            hdr, text="光遇模型可视化便捷导出", style="Sub.TLabel"
        ).pack(side="left", padx=(10, 0), pady=(6, 0))

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
        ttk.Label(
            self.root,
            text='选择游戏安装根目录 (如 "Sky Children of the Light")，点击「扫描」自动识别地图和 Mesh',
            foreground="#888",
            font=("Segoe UI", 8),
        ).pack(anchor="w", padx=(18, 0))

        # mid section: left (maps) + right (options + markers)
        mid_frame = ttk.Frame(self.root)
        mid_frame.pack(fill="both", expand=True, padx=16, pady=(6, 0))

        # ── left: map list ──
        map_frame = ttk.LabelFrame(
            mid_frame, text="地图列表", padding=(8, 4, 8, 6)
        )
        map_frame.pack(side="left", fill="both", expand=True)

        map_toolbar = ttk.Frame(map_frame)
        map_toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(
            map_toolbar, text="全选", width=5, command=self._select_all_maps
        ).pack(side="left")
        ttk.Button(
            map_toolbar,
            text="全不选",
            width=5,
            command=self._deselect_all_maps,
        ).pack(side="left", padx=(4, 0))
        self.map_count_label = ttk.Label(
            map_toolbar, text="", foreground="#666", font=("Segoe UI", 8)
        )
        self.map_count_label.pack(side="right")

        self.map_tree = ttk.Treeview(
            map_frame, show="tree", selectmode="none", style="Map.Treeview"
        )
        map_scroll = ttk.Scrollbar(
            map_frame, orient="vertical", command=self.map_tree.yview
        )
        self.map_tree.configure(yscrollcommand=map_scroll.set)
        self.map_tree.pack(side="left", fill="both", expand=True)
        map_scroll.pack(side="right", fill="y")
        self.map_tree.bind("<Button-1>", self._on_map_click)

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
            foreground="#888",
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
            foreground="#888",
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

        mk_toolbar = ttk.Frame(marker_frame)
        mk_toolbar.pack(fill="x", pady=(0, 4))
        self.scan_mk_btn = ttk.Button(
            mk_toolbar, text="扫描", command=self._scan_markers
        )
        self.scan_mk_btn.pack(side="left")
        self.sel_all_mk_btn = ttk.Button(
            mk_toolbar,
            text="全选",
            width=5,
            command=self._select_all_markers,
        )
        self.sel_all_mk_btn.pack(side="left", padx=(6, 0))
        self.desel_all_mk_btn = ttk.Button(
            mk_toolbar,
            text="全不选",
            width=5,
            command=self._deselect_all_markers,
        )
        self.desel_all_mk_btn.pack(side="left", padx=(4, 0))

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
        self.marker_tree.bind("<Button-1>", self._on_marker_click)

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
            bg="#1e1e1e",
            fg="#dcdcdc",
            insertbackground="#dcdcdc",
            state="disabled",
            relief="flat",
            height=8,
        )
        log_scroll = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.log_text.yview
        )
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self.log_text.tag_configure("ok", foreground="#6ec86e")
        self.log_text.tag_configure("warn", foreground="#e0c040")
        self.log_text.tag_configure("err", foreground="#e05050")
        self.log_text.tag_configure("info", foreground="#60a0d0")

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
        if os.path.isdir(mesh_dir):
            self.mesh_var.set(mesh_dir)
            mesh_count = sum(
                1 for f in os.listdir(mesh_dir) if f.endswith(".mesh")
            )
            self._log(f"[OK] Mesh 目录: {mesh_count} 个 .mesh 文件\n")

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

        self._populate_map_list()
        self._log(
            f"[OK] 扫描完成: {len(self.map_entries)} 个区域, {total_maps} 张地图\n"
        )

    def _populate_map_list(self):
        self.map_tree.delete(*self.map_tree.get_children())
        self.map_data.clear()

        for scene, maps in self.map_entries.items():
            display = SCENE_DISPLAY.get(scene, scene)
            sid = self.map_tree.insert(
                "", "end",
                text=f"☑ {display} ({scene}) — {len(maps)} 张",
                open=True,
            )
            self.map_data[sid] = {"scene": scene, "selected": True}

            for name, path in maps:
                iid = self.map_tree.insert(sid, "end", text=f"☑ {name}")
                self.map_data[iid] = {
                    "name": name, "path": path, "selected": True,
                }

        self._update_map_count()

    def _on_map_click(self, event):
        iid = self.map_tree.identify_row(event.y)
        if not iid or iid not in self.map_data:
            return

        data = self.map_data[iid]
        new_val = not data["selected"]
        data["selected"] = new_val
        prefix = "☑" if new_val else "☐"
        old_text = self.map_tree.item(iid, "text")
        self.map_tree.item(iid, text=prefix + old_text[1:])

        if "scene" in data:
            for child in self.map_tree.get_children(iid):
                self.map_data[child]["selected"] = new_val
                ct = self.map_tree.item(child, "text")
                self.map_tree.item(child, text=prefix + ct[1:])

        self._update_map_count()

    def _set_all_maps(self, val):
        prefix = "☑" if val else "☐"
        for iid, data in self.map_data.items():
            data["selected"] = val
            t = self.map_tree.item(iid, "text")
            self.map_tree.item(iid, text=prefix + t[1:])
        self._update_map_count()

    def _select_all_maps(self):
        self._set_all_maps(True)

    def _deselect_all_maps(self):
        self._set_all_maps(False)

    def _update_map_count(self):
        total = 0
        selected = 0
        for data in self.map_data.values():
            if "path" in data:
                total += 1
                if data["selected"]:
                    selected += 1
        self.map_count_label.configure(text=f"已选 {selected}/{total}")

    def _get_selected_maps(self):
        return [
            (d["name"], d["path"])
            for d in self.map_data.values()
            if "path" in d and d["selected"]
        ]

    # ── marker scanning ───────────────────────────────────
    def _on_marker_toggle(self):
        state = "normal" if self.marker_var.get() else "disabled"
        self.scan_mk_btn.configure(state=state)
        self.sel_all_mk_btn.configure(state=state)
        self.desel_all_mk_btn.configure(state=state)

    def _scan_markers(self):
        selected = self._get_selected_maps()
        if not selected:
            messagebox.showwarning("提示", "请先扫描游戏目录并选择至少一张地图")
            return
        if self.running:
            return

        self.scan_mk_btn.configure(state="disabled")
        self.progress.configure(mode="determinate", maximum=len(selected), value=0)
        self._log(f"正在扫描标记类名 (0/{len(selected)})...\n")

        t = threading.Thread(
            target=self._do_scan_markers, args=(selected,), daemon=True
        )
        t.start()

    def _do_scan_markers(self, selected):
        classes = set()
        total = len(selected)
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

            json_path = bin_file + ".json"
            if not os.path.exists(json_path) and os.path.exists(
                self._bintojson_path
            ):
                subprocess.run(
                    [sys.executable, self._bintojson_path, bin_file],
                    capture_output=True,
                    cwd=path,
                )

            if not os.path.exists(json_path):
                self.root.after(0, self._scan_markers_tick, i + 1, total)
                continue

            try:
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
        self.scan_mk_btn.configure(text=f"{current}/{total}")

    def _scan_markers_done(self, class_names):
        self.progress.configure(mode="indeterminate", value=0)
        self.scan_mk_btn.configure(state="normal", text="扫描")
        self._populate_marker_checkboxes(class_names)
        self._log(f"[OK] 扫描完成: 找到 {len(class_names)} 个标记类名\n")

    def _populate_marker_checkboxes(self, class_names):
        self.marker_tree.delete(*self.marker_tree.get_children())
        self.marker_vars.clear()

        for cn in class_names:
            iid = self.marker_tree.insert("", "end", text=f"☑ {cn}")
            self.marker_vars[iid] = {"name": cn, "selected": True}

    def _on_marker_click(self, event):
        iid = self.marker_tree.identify_row(event.y)
        if not iid or iid not in self.marker_vars:
            return
        data = self.marker_vars[iid]
        data["selected"] = not data["selected"]
        prefix = "☑" if data["selected"] else "☐"
        self.marker_tree.item(iid, text=f"{prefix} {data['name']}")

    def _set_all_markers(self, val):
        prefix = "☑" if val else "☐"
        for iid, data in self.marker_vars.items():
            data["selected"] = val
            self.marker_tree.item(iid, text=f"{prefix} {data['name']}")

    def _select_all_markers(self):
        self._set_all_markers(True)

    def _deselect_all_markers(self):
        self._set_all_markers(False)

    # ── module import ──────────────────────────────────────
    SCRIPT_FILES = [
        ("batch_export.py", "导出核心"),
        ("meshtoobj.py", "Mesh 解析"),
        ("Sky_Bstbake.py", "地形解析"),
        ("bintojson.py", "Bin→JSON"),
    ]

    def _import_modules(self):
        self._export_single_map_fn = None
        self._bintojson_path = os.path.join(self._script_dir, "bintojson.py")
        try:
            import importlib.util
            import io as _io

            batch_path = os.path.join(self._script_dir, "batch_export.py")
            if os.path.exists(batch_path):
                old_out, old_err = sys.stdout, sys.stderr
                sys.stdout = _io.StringIO()
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
                finally:
                    sys.stdout, sys.stderr = old_out, old_err

            self._modules_loaded = True
            self._log(f"[OK] 模块加载完成 ({self._script_dir})\n")
        except Exception as e:
            self._log(f"[WARN] 模块加载失败: {e}\n")

    # ── script manager ─────────────────────────────────────
    def _open_script_manager(self):
        win = tk.Toplevel(self.root)
        win.title("解析模块管理")
        win.geometry("560x340")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        ttk.Label(
            win, text="解析模块", font=("Segoe UI", 12, "bold")
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
                refresh_list()

        ttk.Button(dir_frame, text="更换", width=6, command=browse_dir).grid(
            row=0, column=2
        )

        # file list
        list_frame = ttk.LabelFrame(
            win, text="脚本文件", padding=(12, 6, 12, 8)
        )
        list_frame.pack(fill="both", expand=True, padx=16, pady=(8, 0))

        def refresh_list():
            for w in list_frame.winfo_children():
                w.destroy()
            d = dir_var.get()
            for fname, desc in self.SCRIPT_FILES:
                row = ttk.Frame(list_frame)
                row.pack(fill="x", pady=2)
                fpath = os.path.join(d, fname)
                exists = os.path.exists(fpath)
                status = "✓" if exists else "✗"
                ttk.Label(
                    row,
                    text=f"{status}  {fname}",
                    font=("Consolas", 9),
                    foreground="#2a2" if exists else "#c44",
                ).pack(side="left")
                ttk.Label(
                    row, text=desc, foreground="#888", font=("Segoe UI", 8)
                ).pack(side="left", padx=(8, 0))

                def open_file(p=fpath):
                    if os.path.exists(p):
                        os.startfile(p)

                ttk.Button(
                    row,
                    text="打开",
                    width=5,
                    command=open_file,
                    state="normal" if exists else "disabled",
                ).pack(side="right")

        refresh_list()

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

        def apply_and_close():
            new_dir = dir_var.get()
            if new_dir != self._script_dir:
                self._script_dir = new_dir
                self._log(f"脚本目录已更改: {new_dir}\n")
                self._import_modules()
            win.destroy()

        ttk.Button(
            btn_frame, text="应用并关闭", command=apply_and_close
        ).pack(side="right")
        ttk.Button(
            btn_frame, text="重新加载", command=self._import_modules
        ).pack(side="right", padx=(0, 6))

    # ── export ─────────────────────────────────────────────
    def _start_export(self):
        if self.running:
            return

        selected = self._get_selected_maps()
        if not selected:
            messagebox.showwarning("提示", "请选择至少一张地图")
            return

        mesh_dir = self.mesh_var.get().strip()
        output_dir = self.output_var.get().strip() or None
        export_markers = self.marker_var.get()

        enabled_classes = None
        if export_markers and self.marker_vars:
            enabled_classes = [
                d["name"] for d in self.marker_vars.values() if d["selected"]
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
            args=(selected, mesh_dir, export_markers, enabled_classes, output_dir, image_dirs),
            daemon=True,
        )
        t.start()

    def _do_export(
        self, selected, mesh_dir, export_markers, enabled_classes, output_dir, image_dirs
    ):
        redirector = StdoutRedirector(self.log_queue)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = redirector
        sys.stderr = redirector
        try:
            if self._export_single_map_fn:
                if not output_dir:
                    game_dir = self.game_dir_var.get().strip()
                    if game_dir:
                        output_dir = os.path.join(game_dir, "Export_Output")
                    else:
                        output_dir = os.path.join(
                            os.path.dirname(selected[0][1]), "输出"
                        )
                os.makedirs(output_dir, exist_ok=True)
                self._last_output_dir = output_dir

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
                    f"\n批量导出完成: 成功 {success}/{total}，失败 {fail}\n"
                )
            else:
                self.log_queue.put("❌ 导出模块未加载\n")
        except Exception as e:
            self.log_queue.put(f"\n❌ 导出出错: {e}\n")
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            self.root.after(0, self._export_done)

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
    root = tk.Tk()
    try:
        root.iconbitmap(default="")
    except tk.TclError:
        pass
    SkyExportGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
