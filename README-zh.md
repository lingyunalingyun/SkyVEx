# SkyVEx

**光遇模型可视化便捷导出**（Convenient Visualization and Export of Sky: Children of the Light Models）

《光·遇》地图 3D 数据导出工具 — 可视化界面。

[中文](./README-zh.md) | [English](./README.md)

## 这个项目是什么

一个图形化界面，封装了社区已有的地图解析脚本，额外提供：

- **一键扫描游戏目录** — 选择游戏安装路径，自动识别所有地图和 Mesh 文件
- **APK 提取** — 直接打开光遇 APK 安装包，无需 PC 端游戏即可提取资源
- **分页资源浏览** — 三个标签页（地形 / 模型库 / 图片资源），按场景分组的地图树、按前缀分组的 4000+ 独立模型、KTX 纹理图库
- **3D 预览** — 实时 OpenGL 预览，支持地形顶点着色（材质混合 + AO）和顶部柔光；点击任意地图或模型即可预览
- **2D 图片预览** — 在图片资源标签页点击任意 KTX 纹理即可解码预览（支持 BC1/BC3/BC4/BC5/BC6H/BC7）
- **按材质分组地形导出** — 地形 OBJ 按材质 ID 拆分，共享材质表（MTL），可直接在 Blender 中分配材质
- **独立模型导出** — 浏览并批量导出单个 `.mesh` 模型（道具、角色、物件）为 OBJ，不限于地形地图
- **标记类名扫描** — 从 `.bin` 文件扫描标记类名，自由勾选要导出的标记类型
- **纹理提取** — KTX (BC6H) → PNG 转换，OBJ 内 UV 映射，MTL 材质引用
- **可插拔后端系统** — 运行时切换纯 Python / 原生解析器，默认零依赖
- **解析模块管理** — 切换后端、导入自定义脚本、查看模块说明
- **高 DPI 适配** — 高分屏 / 缩放显示下界面清晰不模糊
- **光遇风格暗色主题** — 深蓝配色，还原游戏视觉风格

> **底层的解析脚本（地形、模型、bin 转换）不是本项目原创。**
> 它们来自 [致谢](#致谢) 和 [NOTICE](./NOTICE) 中列出的开源项目。
> 本项目仅提供 GUI 界面和纹理提取管线。

## 截图

![SkyVEx GUI](./screenshot.png)

## 依赖

Python 3.8+

```bash
pip install texture2ddecoder Pillow PyOpenGL PyOpenGL_accelerate
```

`texture2ddecoder` 和 `Pillow` 仅纹理导出需要。

`PyOpenGL` 和 `PyOpenGL_accelerate` 仅 3D 预览需要。

`lz4` 和 `meshoptimizer` 为可选依赖 — SkyVEx 内置纯 Python 回退，开箱即用无需额外安装。

<details>
<summary>Termux (Android) — 仅命令行脚本，无 GUI</summary>

```bash
pkg update && pkg upgrade
pkg install python clang cmake make binutils git
pip install lz4 meshoptimizer
```
</details>

## 使用方法

### GUI（推荐）

**Windows：** 双击项目根目录的 `SkyVEx.exe` 即可启动。

或通过命令行运行：

```bash
cd tool/scripts
python gui.py
```

1. **浏览** 选择游戏安装目录，点击 **扫描** — 或点击 **APK** 直接打开 APK 安装包
2. 通过标签页浏览资源：**地形** 查看地图、**模型库** 查看独立模型、**图片资源** 查看 KTX 纹理
3. 勾选 **3D 预览** 实时查看任意地图或模型的 OpenGL 渲染效果；点击图片可查看 2D 预览
4. 点击 **扫描标记类名** 发现标记类型，按需开关标记小球、纹理导出，设置输出目录
5. 点击 **开始导出** — 同时导出选中的地图和独立模型

### 命令行（原始脚本）

原始命令行脚本仍可独立使用：

```bash
python launcher.py        # 单地图导出（交互式）
python batch_export.py    # 批量导出
python Sky_Bstbake.py --unpack BstBaked.meshes --export-obj  # 仅地形
python bintojson.py Objects.level.bin   # bin → json
```

## 文件结构与版权归属

```
SkyVEx.exe                         # Windows 启动器（由 SkyVEx.py 构建）
SkyVEx.py                          # 启动器入口脚本
│
tool/scripts/
│
│  [原创 — lingyunalingyun]
├── gui.py                     # 可视化界面 & 纹理管线
├── preview3d.py               # OpenGL 3D 预览面板
│
│  [上游 + 修改 — 详见文件头注释]
├── batch_export.py            # 批量导出引擎（+ 纹理管线）
├── launcher.py                # 单地图命令行导出（+ output_dir）
│
│  [原创 — lingyunalingyun，格式研究来自 Miau]
├── bintojson.py               # TGCL .bin → .json 解析器
│
│  [原创 — lingyunalingyun]
├── backends.py                # 可插拔后端注册层
├── mesh_parser.py             # 纯 Python .mesh 解析器（全版本）
│
│  [上游 — that-sky-project, LGPL 2.1]
├── meshes2obj_json.py         # 纯 Python .meshes 解析器（GEO0 段）
│
│  [上游 — 原作者，详见 NOTICE]
├── Sky_Bstbake.py             # 核心地形解析器
├── sky_mesh_to_obj.py         # .mesh 解析器 v2 (v31/v32)
├── meshtoobj.py               # .mesh 解析器旧版 (v23–v30)
├── bstbake_standalone.py      # 独立地形导出
└── _meshopt/
    └── meshopt2.dll           # meshopt 解码库 (Windows)
```

每个脚本文件头部都标注了来源和许可证，详细的上游许可证信息请参见 [NOTICE](./NOTICE)。

## 对上游脚本的修改说明

以下上游文件经过修改，所有改动均在文件头注释中标明。

| 文件 | 修改内容 |
|------|---------|
| `batch_export.py` | 添加纹理提取管线：`extract_texture_name()`、`convert_ktx_to_png()`、`find_ktx_file()`；OBJ 输出增加 `vt`（UV 坐标）和 `f v/vt` 格式；MTL 输出增加 `map_Kd` 纹理引用；`export_single_map()` 增加 `image_dirs` 参数；改为通过 backends.py 分发解析任务，不再硬编码导入 |
| `launcher.py` | `export_map()` 添加可选 `output_dir` 参数 |
| `Sky_Bstbake.py` | 修复 meshoptimizer 参数顺序 |

其余上游脚本均**未经修改**，与原始仓库保持一致。

## OBJ 输出内容

| 数据 | 说明 |
|------|------|
| 地形 | 地面网格按材质 ID 拆分，共享 MTL 材质表，顶点着色 + AO |
| 模型（地图内） | 场景物体，已应用变换矩阵，Z 轴翻转适配 Blender |
| 模型（独立） | 单个 `.mesh` 文件导出至 `Meshes/` 子文件夹，含 UV |
| 标记 | 交互点位置的彩色球体（可选） |
| 纹理 | PNG 文件 + MTL 材质引用（可选） |

## 构建 exe

需要 [PyInstaller](https://pyinstaller.org/)：

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --icon=icon.ico --name SkyVEx SkyVEx.py
```

生成的 `dist/SkyVEx.exe` 放到项目根目录即可。目标机器仍需安装 Python — exe 只是启动器，不是独立打包。

## 常见问题

| 问题 | 解决 |
|------|------|
| 缺少 `lz4` / `meshoptimizer` | 可选: `pip install lz4 meshoptimizer`（不装也能用，内置纯 Python 回退） |
| 地形 0 顶点 | 检查 meshoptimizer 安装；Windows 将 `meshopt2.dll` 放入 `_meshopt/` |
| 模型缺失 | 需从游戏资源包中提取 `.mesh` 文件 |
| 纹理导出失败 | `pip install texture2ddecoder Pillow` |
| 3D 预览不可用 | `pip install PyOpenGL PyOpenGL_accelerate` |

## 致谢

**解析脚本** 基于以下作者和项目，均以 MIT 许可证发布：

- checion (雨人) & Heriel (落秋) — [SkyBstbake](https://github.com/ThatSkyOldServer/SkyBstbake)
- Miau — TGCL 格式研究、[Sky-.bin-reader](https://github.com/Miau0x1/Sky-.bin-reader)
- potato — 脚本
- that-sky-project — [that-sky-level-meshes](https://github.com/that-sky-project/that-sky-level-meshes)（meshes2obj_json.py, LGPL 2.1）
- kfhammond — [SkyModelViewer](https://github.com/kfhammond/SkyModelViewer)（mesh_parser.py 的格式参考）

**GUI、3D 预览、bin 解析器、纹理管线、后端系统、mesh_parser** 由 lingyunalingyun 开发。

## 许可证

SkyVEx 的 GUI 和纹理管线代码（`gui.py` 及 `batch_export.py` 中的新增部分）以 MIT 许可证发布 — 见 [LICENSE](./LICENSE)。

上游解析脚本保留其原始 MIT 许可证 — 见 [NOTICE](./NOTICE)。

`meshes2obj_json.py` 以 LGPL 2.1 许可证发布 — 详见文件头注释。
