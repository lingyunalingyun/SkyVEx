# 光遇地图可视化导出工具套件

> 一键导出《光·遇》游戏地图数据，支持地形、模型、交互标记，适配 Blender 等 3D 软件。

[中文](./README-zh.md) | [English](./README.md)

## 📦 项目简介

本工具套件用于导出《光·遇》游戏地图的完整 3D 数据，包括：

- **地形网格** — 带法线，精细凹凸质感
- **场景模型** — 石头、建筑、蝴蝶、NPC 等静态与动态物体
- **交互标记** — 传送门、冥想区、NPC 位置等（可选小球标记）

支持所有版本的 `.meshes` 文件（v57+ 及旧版本）。


## 📁 文件结构

```
光遇地图导出工具/
├── 启动.py                    # ⭐ 单地图导出（推荐）
├── 批量地图转换.py             # 📦 批量导出
├── Sky_Bstbake.py             # 🧠 核心地形解析引擎
├── meshtoobj.py               # 🧩 .mesh 模型解析器
├── bintojson.py               # 🔄 .bin ↔ .json 转换器
├── zh字典.py                  # 🌐 中文翻译表（可选）
├── mesh/                      # 📂 存放 .mesh 模型文件
├── _meshopt/                  # 🪟 Windows 专用（meshopt2.dll）
├── README.md                  # 说明文档（当前文件）
└── README-en.md               # English version
```


## 🔧 安装依赖

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


## 🚀 使用方法

### 一、单地图导出（最常用）
```bash
python 启动.py
```

按提示输入：
1. 地图文件夹路径（包含 `Objects.level.bin` 的目录）
2. mesh 文件夹路径（存放 `.mesh` 文件的目录）
3. 是否导出标记小球（y/n）

**输出**：`地图文件夹/[地图名]_export/[地图名].obj`


### 二、批量导出
```bash
python 批量地图转换.py
```

按提示输入：
1. Level 目录路径（包含所有地图子文件夹的上级目录）
2. mesh 文件夹路径
3. 是否导出标记小球

**输出**：`Level 同级目录/输出/[地图名]/[地图名].obj`
**日志**：`Level 同级目录/输出/batch_export_时间戳.txt`


### 三、直接使用核心脚本
```bash
python Sky_Bstbake.py --unpack Dawn.meshes --export-obj
```


## 📤 输出文件说明

导出的 OBJ 文件包含三部分：

| 部分 | 说明 |
|------|------|
| **地形 (Terrain)** | 地图基础地面网格，包含顶点(v)和法线(vn)，材质 `terrain`（灰棕色） |
| **模型实例** | 场景中的石头、建筑、蝴蝶等，每个实例独立命名，已应用 Transform 矩阵，材质 `model`（浅灰色），Z 轴已翻转（适配 Blender） |
| **标记小球（可选）** | 代替 NPC、传送门、冥想区等交互点，不同类用不同颜色区分，半径 0.5 米 |


## 🎨 标记小球颜色对照表

| 类名关键词 | 颜色 |
|------------|------|
| LevelMesh | 灰色 (0.70, 0.70, 0.70) |
| Marker | 金色 (1.00, 0.80, 0.20) |
| Npc | 绿色 (0.20, 0.80, 0.20) |
| MeditationArea | 蓝色 (0.30, 0.50, 1.00) |
| Portal | 红色 (1.00, 0.30, 0.30) |
| Checkpoint | 橙色 (1.00, 0.50, 0.00) |
| Boundary | 纯红 (1.00, 0.00, 0.00) |
| Wind | 天蓝 (0.50, 0.80, 1.00) |
| Water | 深蓝 (0.20, 0.50, 1.00) |
| Timeline | 紫色 (0.80, 0.30, 0.80) |
| SoundEmitter | 青色 (0.20, 0.80, 0.80) |
| PointLight | 暖黄 (1.00, 0.90, 0.40) |
| Flame | 橙红 (1.00, 0.40, 0.10) |


## 📋 运行示例

```
☁️ 地图可视化导出 v18 (自动生成颜色)

标记小球说明：
  - 小球是代替 NPC、传送门、冥想区等交互点的标记
  - 导出小球可以帮助定位这些交互点的位置
  - 如果只需要地形和模型，可以选择不导出小球

地图文件夹: /storage/maps/Dawn
mesh 文件夹路径 (默认: 脚本同目录/mesh): /storage/mesh
是否导出标记小球? (y/n, 默认 y): n

📖 [.bin] Objects.level.bin
   ⏳ 转换 bin → JSON ...
   ✅ JSON 生成完成
   📄 读取 JSON...
   🔍 提取 LevelMesh 节点...
   找到 790 个 LevelMesh 实例, 211 种资源

📖 [.meshes] BstBaked.meshes
   [GEO0] verts=109912, index_bytes=505071, tris=168357
   meshopt VB OK (109912 verts)
   地形: 5978 顶点, 11890 三角形

📖 [.mesh] 加载模型 (目录: /storage/mesh)
   ✅ AP07Butterfly (82v, 68t)
   ✅ S28_MigrationBoat_Busted (1837v, 1797t)
   ...（共 209 种成功）

📝 导出 OBJ...

✅ 完成!
   地形: 5,978 顶点, 11,890 三角形
   模型: 209 种, 786 实例
   标记: 2842 (已禁用)
   OBJ: /storage/maps/Dawn/Dawn_export/Dawn.obj
```


## ❓ 常见问题

| 问题 | 解决方法 |
|------|----------|
| **Q1: 提示"缺少 lz4 库"** | 运行 `pip install lz4` |
| **Q2: 提示"meshoptimizer 模块未找到"** | 运行 `pip install meshoptimizer`；Termux 需先安装 `clang/cmake` |
| **Q3: 地形为 0 顶点** | meshopt 解码失败，检查 meshoptimizer 是否正确安装 |
| **Q4: 模型缺失（.mesh 不存在）** | 需要从游戏资源包中提取对应的 `.mesh` 文件 |
| **Q5: Windows 上 meshopt 解码失败** | 将 `meshopt2.dll` 放入 `_meshopt/` 文件夹 |
| **Q6: 批量导出时某些地图失败** | 查看生成的 `batch_export_*.txt` 日志文件 |


## 🛠️ 技术信息

| 项目 | 说明 |
|------|------|
| 支持版本 | LVL04 – LVL0D（v57+ 完整支持） |
| 解码库 | meshoptimizer（官方 Python 绑定） |
| 压缩 | LZ4 block |
| 格式 | TGCL (BSTNodes) + GEO0 (meshopt) |


## 🙏 致谢

| 贡献者 | 贡献 |
|--------|------|
| 雨人 (checion) | 部分脚本 |
| 落秋 (Heriel) | 部分脚本 |
| potato | 部分脚本 |
| Miau | 部分脚本 |
| 十二 | 制作整合 |

**参考项目：**
- [SkyBstbake](https://github.com/ThatSkyOldServer/SkyBstbake) — meshes 解析（雨人 & 落秋）
- [Sky-.bin-reader-python-zh](https://github.com/skyIshier/Sky-.bin-reader-python-zh) — bin 解析（十二）
- [Sky-.bin-reader](https://github.com/Miau0x1/Sky-.bin-reader) — bin 解析（Miau）


## 📄 许可证

本工具套件使用**自定义许可证**，简单来说：

| 行为 | 是否允许 |
|------|----------|
| 个人学习、研究使用 | ✅ 允许 |
| 非商业修改、二次开发 | ✅ 允许 |
| 免费分享（保持完整） | ✅ 允许 |
| 商业使用（卖钱、收费） | ❌ 禁止 |
| 倒卖、转售 | ❌ 禁止 |
| 删除版权声明 | ❌ 禁止 |

**商业授权请联系：** 3787533101@qq.com

完整许可证请查看项目根目录的 `LICENSE` 文件。

© 2026 光遇地图工具套件