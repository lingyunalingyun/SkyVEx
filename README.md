# SkyVEx

**Convenient Visualization and Export of Sky: Children of the Light Models**

GUI frontend for batch-exporting 3D map data from *Sky: Children of the Light*.

[中文](./README-zh.md) | [English](./README.md)

## What this project is

A graphical interface that wraps the community's existing map-parsing scripts, adding:

- **One-click game directory scanning** — point at your game install, auto-discover all maps and mesh files
- **APK extraction** — open a Sky APK directly and extract game assets without a PC install
- **Tabbed resource browser** — three-tab layout (Terrain / Models / Images) with scene-grouped map tree, 4000+ individual meshes grouped by prefix, and KTX texture gallery
- **3D preview** — real-time OpenGL preview with vertex colors (terrain material blending) and top-down soft lighting; click any map or model to preview
- **2D image preview** — click any KTX texture in the Images tab to decode and preview (supports BC1/BC3/BC4/BC5/BC6H/BC7)
- **Per-material terrain export** — terrain OBJ split by material ID with shared material table (MTL), ready for Blender material assignment
- **Individual mesh export** — browse and batch-export standalone `.mesh` models (props, characters, items) to OBJ, not just terrain maps
- **Marker class scanning** — scan marker class names from `.bin` files, pick which marker types to export
- **Texture extraction** — KTX (BC6H) → PNG conversion, UV mapping in OBJ, material references in MTL
- **Pluggable backend system** — swap between pure Python and native parsers at runtime; zero dependencies by default
- **Script manager** — switch active backends, import custom scripts, view module info
- **DPI-aware rendering** — crisp UI on high-DPI / scaled displays
- **Sky-styled dark theme** — deep navy palette inspired by the game's visual identity

> **The parsing scripts (terrain, mesh, bin) are NOT written by us.**
> They come from the open-source projects listed in [Credits](#credits) and [NOTICE](./NOTICE).
> We only provide the GUI wrapper and the texture extraction pipeline.

## Screenshot

![SkyVEx GUI](./screenshot.png)

## Requirements

Python 3.8+

```bash
pip install texture2ddecoder Pillow PyOpenGL PyOpenGL_accelerate
```

`texture2ddecoder` and `Pillow` are only needed for texture export.

`PyOpenGL` and `PyOpenGL_accelerate` are only needed for 3D preview.

`lz4` and `meshoptimizer` are optional — SkyVEx includes pure Python fallbacks that work out of the box.

<details>
<summary>Termux (Android) — CLI scripts only, no GUI</summary>

```bash
pkg update && pkg upgrade
pkg install python clang cmake make binutils git
pip install lz4 meshoptimizer
```
</details>

## Usage

### GUI (recommended)

**Windows:** Double-click `SkyVEx.exe` in the project root.

Or run from the command line:

```bash
cd tool/scripts
python gui.py
```

1. **Browse** to your game install directory, click **Scan** — or click **APK** to open an APK file directly
2. Browse resources using tabs: **Terrain** for maps, **Models** for individual meshes, **Images** for KTX textures
3. Toggle **3D Preview** to preview any map or model with real-time OpenGL rendering; click any image to see a 2D preview
4. Click **Scan Marker Classes** to discover marker types, then toggle markers, textures, and adjust output directory
5. Click **Start Export** — exports both selected maps and individual models

### CLI (original scripts)

The original command-line scripts still work independently:

```bash
python launcher.py        # Single map (interactive prompts)
python batch_export.py    # Batch export
python Sky_Bstbake.py --unpack BstBaked.meshes --export-obj  # Terrain only
python bintojson.py Objects.level.bin   # bin → json
```

## File structure & copyright

```
SkyVEx.exe                         # Windows launcher (build from SkyVEx.py)
SkyVEx.py                          # Launcher entry point
│
tool/scripts/
│
│  [Original — lingyunalingyun]
├── gui.py                     # GUI frontend & texture pipeline
├── preview3d.py               # OpenGL 3D preview panel
│
│  [Upstream + Modified — see headers for details]
├── batch_export.py            # Batch export engine (+ texture pipeline)
├── launcher.py                # Single map CLI export (+ output_dir)
│
│  [Original — lingyunalingyun, format research by Miau]
├── bintojson.py               # TGCL .bin → .json parser
│
│  [Original — lingyunalingyun]
├── backends.py                # Pluggable backend registry
├── mesh_parser.py             # Pure Python .mesh parser (all versions)
│
│  [Upstream — that-sky-project, LGPL 2.1]
├── meshes2obj_json.py         # Pure Python .meshes parser (GEO0 segment)
│
│  [Upstream — original authors, see NOTICE]
├── Sky_Bstbake.py             # Core terrain parser
├── sky_mesh_to_obj.py         # .mesh parser v2 (v31/v32)
├── meshtoobj.py               # .mesh parser legacy (v23–v30)
├── bstbake_standalone.py      # Standalone terrain export
└── _meshopt/
    └── meshopt2.dll           # meshopt decoder (Windows)
```

Every script file contains a header comment indicating its source and license. Please refer to those headers and the [NOTICE](./NOTICE) file for upstream licensing details.

## Modifications to upstream scripts

The following upstream files were modified. All changes are clearly marked in the file headers.

| File | What was changed |
|------|-----------------|
| `batch_export.py` | Added texture extraction pipeline: `extract_texture_name()`, `convert_ktx_to_png()`, `find_ktx_file()`; OBJ output now includes `vt` (UV coords) and `f v/vt` format; MTL output includes `map_Kd` texture references; `export_single_map()` accepts `image_dirs` parameter; refactored to delegate parsing through backends.py instead of hardcoded imports |
| `launcher.py` | Added optional `output_dir` parameter to `export_map()` |
| `Sky_Bstbake.py` | Fixed meshoptimizer parameter order |

All other upstream scripts are included **unmodified** from their original repositories.

## OBJ output

| Data | Description |
|------|-------------|
| Terrain | Ground mesh split by material ID, with shared MTL material table, vertex colors and AO |
| Models (in-map) | Scene objects with transforms applied, Z-flipped for Blender |
| Models (standalone) | Individual `.mesh` files exported to `Meshes/` subfolder with UVs |
| Markers | Colored spheres at interaction points (optional) |
| Textures | PNG files + MTL material references (optional) |

## Building the exe

Requires [PyInstaller](https://pyinstaller.org/):

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --icon=icon.ico --name SkyVEx SkyVEx.py
```

The output `dist/SkyVEx.exe` can be placed in the project root. Python must still be installed on the target machine — the exe is just a launcher, not a standalone bundle.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `lz4` / `meshoptimizer` not found | Optional: `pip install lz4 meshoptimizer` (pure Python fallbacks work without them) |
| Terrain 0 vertices | Check meshoptimizer install; Windows: put `meshopt2.dll` in `_meshopt/` |
| Models missing | Need `.mesh` files extracted from game assets |
| Texture export fails | `pip install texture2ddecoder Pillow` |
| 3D preview not available | `pip install PyOpenGL PyOpenGL_accelerate` |

## Credits

**Parsing scripts** are based on work by the following authors and projects — all originally released under the MIT license:

- checion (雨人) & Heriel (落秋) — [SkyBstbake](https://github.com/ThatSkyOldServer/SkyBstbake)
- Miau — TGCL format research, [Sky-.bin-reader](https://github.com/Miau0x1/Sky-.bin-reader)
- potato — scripts
- that-sky-project — [that-sky-level-meshes](https://github.com/that-sky-project/that-sky-level-meshes) (meshes2obj_json.py, LGPL 2.1)
- kfhammond — [SkyModelViewer](https://github.com/kfhammond/SkyModelViewer) (format reference for mesh_parser.py)

**GUI, 3D preview, bin parser, texture pipeline, backend system, and mesh_parser** by lingyunalingyun.

## License

The SkyVEx GUI and texture pipeline code (`gui.py` and additions to `batch_export.py`) are released under the MIT License — see [LICENSE](./LICENSE).

The upstream parsing scripts retain their original MIT licenses — see [NOTICE](./NOTICE) for details.

`meshes2obj_json.py` is licensed under LGPL 2.1 — see its file header for details.
