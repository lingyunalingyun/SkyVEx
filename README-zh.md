# SkyVEx

**光遇模型可视化便捷导出**（Convenient Visualization and Export of Sky: Children of the Light Models）

《光·遇》地图 3D 数据导出工具 — 可视化界面。

[中文](./README-zh.md) | [English](./README.md)

## 这个项目是什么

一个图形化界面，封装了社区已有的地图解析脚本，额外提供：

- **一键扫描游戏目录** — 选择游戏安装路径，自动识别所有地图和 Mesh 文件
- **APK 提取** — 直接打开光遇 APK 安装包，无需 PC 端游戏即可提取资源
- **可视化地图选择** — 按场景分组的树形列表，支持单选/全选
- **标记类名筛选** — 后台扫描带进度条，自由勾选要导出的标记类型
- **纹理提取** — KTX (BC6H) → PNG 转换，OBJ 内 UV 映射，MTL 材质引用
- **解析模块管理** — 查看、打开、更换底层解析脚本
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
pip install lz4 meshoptimizer texture2ddecoder Pillow
```

`texture2ddecoder` 和 `Pillow` 仅纹理导出需要，不用纹理功能可以不装。

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
2. 在树形列表中勾选要导出的地图
3. 按需开关标记小球、纹理导出，设置输出目录
4. 点击 **开始导出**

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
│
│  [上游 + 修改 — 详见文件头注释]
├── batch_export.py            # 批量导出引擎（+ 纹理管线）
├── launcher.py                # 单地图命令行导出（+ output_dir）
│
│  [原创 — lingyunalingyun，格式研究来自 Miau]
├── bintojson.py               # TGCL .bin → .json 解析器
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
| `batch_export.py` | 添加纹理提取管线：`extract_texture_name()`、`convert_ktx_to_png()`、`find_ktx_file()`；OBJ 输出增加 `vt`（UV 坐标）和 `f v/vt` 格式；MTL 输出增加 `map_Kd` 纹理引用；`export_single_map()` 增加 `image_dirs` 参数 |
| `launcher.py` | `export_map()` 添加可选 `output_dir` 参数 |
| `Sky_Bstbake.py` | 修复 meshoptimizer 参数顺序 |

其余上游脚本均**未经修改**，与原始仓库保持一致。

## OBJ 输出内容

| 数据 | 说明 |
|------|------|
| 地形 | 地面网格，带法线和顶点颜色 |
| 模型 | 场景物体，已应用变换矩阵，Z 轴翻转适配 Blender |
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
| 缺少 `lz4` / `meshoptimizer` | `pip install lz4 meshoptimizer` |
| 地形 0 顶点 | 检查 meshoptimizer 安装；Windows 将 `meshopt2.dll` 放入 `_meshopt/` |
| 模型缺失 | 需从游戏资源包中提取 `.mesh` 文件 |
| 纹理导出失败 | `pip install texture2ddecoder Pillow` |

## 致谢

**解析脚本** 基于以下作者和项目，均以 MIT 许可证发布：

- checion (雨人) & Heriel (落秋) — [SkyBstbake](https://github.com/ThatSkyOldServer/SkyBstbake)
- Miau — TGCL 格式研究、[Sky-.bin-reader](https://github.com/Miau0x1/Sky-.bin-reader)
- potato — 脚本

**GUI、bin 解析器、纹理管线** 由 lingyunalingyun 开发。

## 许可证

SkyVEx 的 GUI 和纹理管线代码（`gui.py` 及 `batch_export.py` 中的新增部分）以 MIT 许可证发布 — 见 [LICENSE](./LICENSE)。

上游解析脚本保留其原始 MIT 许可证 — 见 [NOTICE](./NOTICE)。
