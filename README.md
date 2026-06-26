# Sky: Children of the Light — Map Visualization Export Toolkit

> One-click export of Sky game map data, supporting terrain, models, and interactive markers. Compatible with Blender and other 3D software.

[中文](./README-zh.md) | [English](./README.md)

## 📦 Project Overview

This toolkit exports complete 3D data from *Sky: Children of the Light* maps, including:

- **Terrain Mesh** — with normals for fine bump texture
- **Scene Models** — rocks, buildings, butterflies, NPCs, and more
- **Interaction Markers** — portals, meditation areas, NPC positions (optional spheres)

Supports all `.meshes` file versions (v57+ and legacy).


## 📁 File Structure

```
SkyMapExport/
├── 启动.py                    # ⭐ Single map export (recommended)
├── 批量地图转换.py             # 📦 Batch export
├── Sky_Bstbake.py             # 🧠 Core terrain parsing engine
├── meshtoobj.py               # 🧩 .mesh model parser
├── bintojson.py               # 🔄 .bin ↔ .json converter
├── zh字典.py                  # 🌐 Chinese translation table (optional)
├── mesh/                      # 📂 Store .mesh model files
├── _meshopt/                  # 🪟 Windows-specific (meshopt2.dll)
├── README.md                  # Chinese documentation
└── README-en.md               # English documentation (this file)
```


## 🔧 Installation

### Termux (Android)
```bash
pkg update && pkg upgrade
pkg install python clang cmake make binutils git
pip install lz4 meshoptimizer
```

### Windows / Linux / Mac
```bash
pip install lz4 meshoptimizer
```


## 🚀 Usage

### 1. Single Map Export (Recommended)
```bash
python 启动.py
```

Follow the prompts:
1. Map folder path (contains `Objects.level.bin`)
2. Mesh folder path (contains `.mesh` files)
3. Export marker spheres? (y/n)

**Output**: `[map_folder]/[map_name]_export/[map_name].obj`


### 2. Batch Export
```bash
python 批量地图转换.py
```

Follow the prompts:
1. Level directory path (parent of all map subfolders)
2. Mesh folder path
3. Export marker spheres? (y/n)

**Output**: `[level_parent]/输出/[map_name]/[map_name].obj`
**Log**: `[level_parent]/输出/batch_export_timestamp.txt`


### 3. Direct Core Script Usage
```bash
python Sky_Bstbake.py --unpack Dawn.meshes --export-obj
```


## 📤 Output Description

The exported OBJ file contains three parts:

| Part | Description |
|------|-------------|
| **Terrain** | Base ground mesh with vertices (v) and normals (vn), material `terrain` (grey-brown) |
| **Model Instances** | Rocks, buildings, butterflies, etc. Each instance named separately. Transform matrix applied. Material `model` (light grey). Z-axis flipped (Blender-compatible) |
| **Marker Spheres (optional)** | Replace NPCs, portals, meditation areas, etc. Different colors per class. Radius 0.5m |


## 🎨 Marker Color Reference

| Class Keyword | Color |
|---------------|-------|
| LevelMesh | Grey (0.70, 0.70, 0.70) |
| Marker | Gold (1.00, 0.80, 0.20) |
| Npc | Green (0.20, 0.80, 0.20) |
| MeditationArea | Blue (0.30, 0.50, 1.00) |
| Portal | Red (1.00, 0.30, 0.30) |
| Checkpoint | Orange (1.00, 0.50, 0.00) |
| Boundary | Pure Red (1.00, 0.00, 0.00) |
| Wind | Sky Blue (0.50, 0.80, 1.00) |
| Water | Deep Blue (0.20, 0.50, 1.00) |
| Timeline | Purple (0.80, 0.30, 0.80) |
| SoundEmitter | Cyan (0.20, 0.80, 0.80) |
| PointLight | Warm Yellow (1.00, 0.90, 0.40) |
| Flame | Orange-Red (1.00, 0.40, 0.10) |


## 📋 Example Run

```
☁️ Map Visualization Export v18 (Auto-generated colors)

Marker Info:
  - Spheres replace NPCs, portals, meditation areas, etc.
  - Exporting spheres helps locate interaction points
  - Choose 'n' if you only need terrain and models

Map folder: /storage/maps/Dawn
Mesh folder (default: ./mesh): /storage/mesh
Export markers? (y/n, default y): n

📖 [.bin] Objects.level.bin
   ⏳ Converting bin → JSON ...
   ✅ JSON generation complete
   📄 Reading JSON...
   🔍 Extracting LevelMesh nodes...
   Found 790 LevelMesh instances, 211 unique resources

📖 [.meshes] BstBaked.meshes
   [GEO0] verts=109912, index_bytes=505071, tris=168357
   meshopt VB OK (109912 verts)
   Terrain: 5978 vertices, 11890 triangles

📖 [.mesh] Loading models (dir: /storage/mesh)
   ✅ AP07Butterfly (82v, 68t)
   ✅ S28_MigrationBoat_Busted (1837v, 1797t)
   ... (209 total successful)

📝 Exporting OBJ...

✅ Complete!
   Terrain: 5,978 vertices, 11,890 triangles
   Models: 209 types, 786 instances
   Markers: 2842 (disabled)
   OBJ: /storage/maps/Dawn/Dawn_export/Dawn.obj
```


## 🔄 Script Interface Translation Reference

Since the scripts are written in Chinese, here is the translation table for all user-facing interfaces:

### Main Scripts

| Chinese Script | English Name | Function |
|----------------|--------------|----------|
| `启动.py` | `launch.py` | Single map export (recommended entry point) |
| `批量地图转换.py` | `batch_convert.py` | Batch export all maps in a directory |
| `Sky_Bstbake.py` | `Sky_Bstbake.py` | Core terrain parsing engine |
| `meshtoobj.py` | `meshtoobj.py` | .mesh model file parser |
| `bintojson.py` | `bintojson.py` | .bin ↔ .json converter |
| `zh字典.py` | `zh_dict.py` | Chinese translation table (optional) |

### User Prompts (启动.py / launch.py)

| Chinese Prompt | English Translation |
|----------------|---------------------|
| 地图文件夹 | Map folder path |
| mesh 文件夹路径 (默认: 脚本同目录/mesh) | Mesh folder path (default: ./mesh) |
| 是否导出标记小球? (y/n, 默认 y) | Export marker spheres? (y/n, default y) |

### User Prompts (批量地图转换.py / batch_convert.py)

| Chinese Prompt | English Translation |
|----------------|---------------------|
| Level 目录路径 | Level directory path |
| Mesh 文件夹路径 | Mesh folder path |
| 是否导出标记小球? (y/n, 默认 y) | Export marker spheres? (y/n, default y) |
| 标记类名选择 | Marker class selection |
| 请输入序号 (1-X, 0, a，回车完成) | Enter number (1-X, 0, a, Enter to finish) |
| 全部启用 | Enable all |
| 全部禁用 | Disable all |
| 是否开始批量导出? (y/n) | Start batch export? (y/n) |

### Output Messages

| Chinese Message | English Translation |
|-----------------|---------------------|
| 正在转换 bin → JSON | Converting bin → JSON |
| JSON 生成完成 | JSON generation complete |
| 读取 JSON | Reading JSON |
| 提取 LevelMesh 节点 | Extracting LevelMesh nodes |
| 加载模型 | Loading models |
| 导出 OBJ | Exporting OBJ |
| 完成! | Complete! |
| 地形 | Terrain |
| 顶点 | vertices |
| 三角形 | triangles |
| 模型 | Models |
| 实例 | instances |
| 标记 | Markers |
| 成功 | Success |
| 失败 | Failed |
| 未知错误 | Unknown error |

### Log File Contents

| Chinese Term | English Translation |
|--------------|---------------------|
| 批量地图导出日志 | Batch Map Export Log |
| 导出时间 | Export time |
| Level 目录 | Level directory |
| Mesh 目录 | Mesh directory |
| 输出目录 | Output directory |
| 导出标记 | Export markers |
| 总地图数 | Total maps |
| 成功数 | Success count |
| 失败数 | Failed count |
| 成功率 | Success rate |
| 总耗时 | Total time |
| 详细列表 | Detailed list |
| 输出 | Output |
| 错误 | Error |

### Command Line Arguments (Sky_Bstbake.py)

| Argument | Description |
|----------|-------------|
| `--unpack` | Specify .meshes file or directory to unpack |
| `-r / --recursive` | Recursively process directories |
| `--export-obj` | Export OBJ file during unpack |
| `--out` | Specify output file path (for repack) |


## ❓ FAQ

| Question | Solution |
|----------|----------|
| **Q1: "lz4 library not found"** | Run `pip install lz4` |
| **Q2: "meshoptimizer module not found"** | Run `pip install meshoptimizer`; on Termux, install `clang/cmake` first |
| **Q3: Terrain has 0 vertices** | meshopt decoding failed; check meshoptimizer installation |
| **Q4: Models missing (.mesh not found)** | Extract corresponding `.mesh` files from game resources |
| **Q5: meshopt decoding fails on Windows** | Place `meshopt2.dll` in `_meshopt/` folder |
| **Q6: Some maps fail during batch export** | Check the generated `batch_export_*.txt` log |


## 🛠️ Technical Information

| Item | Details |
|------|---------|
| Supported Versions | LVL04 – LVL0D (v57+ fully supported) |
| Decoding Library | meshoptimizer (official Python bindings) |
| Compression | LZ4 block |
| Format | TGCL (BSTNodes) + GEO0 (meshopt) |


## 📧 Contact & Contributions

If you have improved versions, bug fixes, or feature enhancements, please feel free to reach out:

📧 **Email**: 3787533101@qq.com

We welcome:
- Bug reports with detailed reproduction steps
- Pull requests or patches
- Translation improvements
- New feature suggestions
- Compatibility fixes for new game versions


## 🙏 Credits

| Contributor | Contribution |
|-------------|--------------|
| 雨人 (checion) | Scripts |
| 落秋 (Heriel) | Scripts |
| potato | Scripts |
| Miau | Scripts |
| 十二 | Integration & packaging |

**Reference Projects:**
- [SkyBstbake](https://github.com/ThatSkyOldServer/SkyBstbake) — meshes parsing (雨人 & 落秋)
- [Sky-.bin-reader-python-zh](https://github.com/skyIshier/Sky-.bin-reader-python-zh) — bin parsing (十二)
- [Sky-.bin-reader](https://github.com/Miau0x1/Sky-.bin-reader) — bin parsing (Miau)


## 📄 License

This toolkit uses a **Custom License**. In short:

| Action | Allowed? |
|--------|----------|
| Personal learning and research | ✅ Yes |
| Non-commercial modification | ✅ Yes |
| Free distribution (keep intact) | ✅ Yes |
| Commercial use (selling, charging) | ❌ No |
| Reselling or redistribution for profit | ❌ No |
| Removing copyright notices | ❌ No |

**For commercial licensing, contact:** 3787533101@qq.com

See the full `LICENSE` file for details.

© 2026 Sky Map Toolkit