#!/usr/bin/env python3
# [Upstream] bstbake_standalone — standalone terrain export launcher
# Source: https://github.com/ThatSkyOldServer/SkyBstbake
# Authors: checion (雨人) & Heriel (落秋)
# License: MIT (see NOTICE)
"""
启动器：用于调用 Sky_Bstbake.py 解析 .meshes，并导出绕序正确的 OBJ
"""

import os
import sys
import struct
import lz4.block

# ------------------------------------------------------------
# 设置环境：将脚本所在目录加入 sys.path，并切换工作目录
# ------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
os.chdir(SCRIPT_DIR)  # 保证相对路径（如 _meshopt 库）能正确加载

# 从 Sky_Bstbake 导入核心解析函数（不导入其有问题的导出函数）
try:
    from Sky_Bstbake import parse_and_split, SEGMENT_NAMES_V3
except ImportError as e:
    print(f"[ERROR] 无法导入 Sky_Bstbake.py: {e}")
    print("请确保该脚本与 Sky_Bstbake.py 在同一目录下。")
    sys.exit(1)

# ------------------------------------------------------------
# 修正后的 OBJ 导出函数（绕序为 i0, i2, i1）
# ------------------------------------------------------------
def export_obj_corrected(result, output_dir, base_name):
    """从 parse_and_split 的 result 导出正确的 OBJ/MTL"""
    obj_path = os.path.join(output_dir, f"{base_name}.obj")
    mtl_path = os.path.join(output_dir, f"{base_name}.mtl")

    # 简单材质
    with open(mtl_path, 'w', encoding='utf-8') as mf:
        mf.write("newmtl default\nKd 0.8 0.8 0.8\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n")

    with open(obj_path, 'w', encoding='utf-8') as f:
        f.write(f"# Exported from .meshes\nmtllib {base_name}.mtl\n\n")
        global_v = 1  # OBJ 顶点索引从 1 开始

        # ---------- 1. 处理 Terrain（含 GEO0 新格式和旧格式） ----------
        for t_idx, terrain_chunk in enumerate(result.get('terrain', [])):
            verts = terrain_chunk.get('verts', [])
            ib_raw = terrain_chunk.get('ib_raw')
            patches = terrain_chunk.get('patches', [])
            indices = terrain_chunk.get('indices', [])

            # ----- GEO0 新格式 (v57+)：有 patches 和 ib_raw -----
            if ib_raw and patches:
                # 只取地形 patch (array == 'A')，忽略云 patch
                t_patches = [p for p in patches if p.get('array') == 'A']
                if not t_patches:
                    continue

                f.write(f"o Terrain_{t_idx}\nusemtl default\n")
                base_v = global_v

                # 写入所有顶点（包括未使用的，简化索引映射）
                for v in verts:
                    pos = v.get('pos', (0, 0, 0))
                    # 坐标翻转：X取反，Z取反（适配游戏坐标系）
                    f.write(f"v {-pos[0]:.6f} {pos[1]:.6f} {-pos[2]:.6f}\n")
                global_v += len(verts)

                # 写入三角形（绕序修正：i0, i2, i1）
                for patch in t_patches:
                    ib_start = patch['ib_byte_off']
                    ib_end = ib_start + patch['ib_byte_len']
                    patch_bytes = ib_raw[ib_start:ib_end]
                    tri_count = len(patch_bytes) // 3
                    vs = patch['vert_start']  # 本 patch 在 verts 中的起始偏移
                    for ti in range(tri_count):
                        bo = ti * 3
                        i0 = patch_bytes[bo] + vs
                        i1 = patch_bytes[bo + 1] + vs
                        i2 = patch_bytes[bo + 2] + vs
                        # 关键修复：交换 i1 和 i2
                        f.write(f"f {i0 + base_v} {i2 + base_v} {i1 + base_v}\n")
                f.write("\n")

            # ----- 旧格式 (v56-)：使用 indices 数组 -----
            elif indices and verts:
                f.write(f"o Terrain_{t_idx}\nusemtl default\n")
                base_v = global_v
                for v in verts:
                    pos = v.get('pos', (0, 0, 0))
                    f.write(f"v {-pos[0]:.6f} {pos[1]:.6f} {-pos[2]:.6f}\n")
                global_v += len(verts)

                for i in range(0, len(indices), 3):
                    if i + 2 < len(indices):
                        i0, i1, i2 = indices[i], indices[i+1], indices[i+2]
                        # 关键修复：交换 i1 和 i2
                        f.write(f"f {i0 + base_v} {i2 + base_v} {i1 + base_v}\n")
                f.write("\n")

        # ---------- 2. 处理 Skirt ----------
        for s_idx, skirt in enumerate(result.get('skirts', [])):
            verts = skirt.get('verts', [])
            indices = skirt.get('indices', [])
            if not verts or not indices:
                continue
            f.write(f"o Skirt_{s_idx}\nusemtl default\n")
            base_v = global_v
            for v in verts:
                pos = v.get('pos', (0, 0, 0))
                f.write(f"v {-pos[0]:.6f} {pos[1]:.6f} {-pos[2]:.6f}\n")
            global_v += len(verts)
            for i in range(0, len(indices), 3):
                if i + 2 < len(indices):
                    i0, i1, i2 = indices[i], indices[i+1], indices[i+2]
                    f.write(f"f {i0 + base_v} {i2 + base_v} {i1 + base_v}\n")
            f.write("\n")

        # ---------- 3. 处理 Occluder ----------
        for o_idx, occ in enumerate(result.get('occluder', [])):
            verts = occ.get('verts', [])
            indices = occ.get('indices', [])
            if not verts or not indices:
                continue
            f.write(f"o Occluder_{o_idx}\nusemtl default\n")
            base_v = global_v
            for v in verts:
                pos = v.get('pos', (0, 0, 0))
                f.write(f"v {-pos[0]:.6f} {pos[1]:.6f} {-pos[2]:.6f}\n")
            global_v += len(verts)
            for i in range(0, len(indices), 3):
                if i + 2 < len(indices):
                    i0, i1, i2 = indices[i], indices[i+1], indices[i+2]
                    f.write(f"f {i0 + base_v} {i2 + base_v} {i1 + base_v}\n")
            f.write("\n")

    print(f"  [导出] OBJ: {obj_path}")
    return obj_path


# ------------------------------------------------------------
# 核心处理函数
# ------------------------------------------------------------
def process_meshes(input_path, output_dir):
    """
    处理单个 .meshes 文件，输出到指定目录。
    """
    if not os.path.isfile(input_path):
        print(f"  [跳过] 文件不存在: {input_path}")
        return

    with open(input_path, 'rb') as f:
        data = f.read()

    # 校验 LVL0 头
    if data[0:4] != b'LVL0':
        print(f"  [跳过] {input_path} 不是有效的 LVL0 文件")
        return

    file_version = struct.unpack_from('<I', data, 0x04)[0]
    print(f"  [处理] {os.path.basename(input_path)} (版本 {file_version})")

    # 解析 TOC
    toc_entry_count = data[0x08]
    geo0_offset = geo0_length = 0
    lod0_offset = lod0_length = 0
    metr_offset = metr_length = 0

    for i in range(toc_entry_count):
        base = 0x08 + 4 + i * 12
        name = data[base:base+4].rstrip(b'\x00').decode('ascii', errors='ignore')
        seg_offset = struct.unpack_from('<I', data, base + 4)[0]
        seg_length = struct.unpack_from('<I', data, base + 8)[0]
        if name == 'GEO0':
            geo0_offset, geo0_length = seg_offset, seg_length
        elif name == 'LOD0':
            lod0_offset, lod0_length = seg_offset, seg_length
        elif name == 'METR':
            metr_offset, metr_length = seg_offset, seg_length

    if lod0_length == 0:
        print(f"  [错误] 找不到 LOD0 段")
        return

    # 解压 LOD0
    compressed = data[lod0_offset:lod0_offset + lod0_length]
    try:
        decompressed = lz4.block.decompress(compressed, uncompressed_size=0xC00000)
    except Exception as e:
        print(f"  [错误] LZ4 解压失败: {e}")
        return

    # 提取 GEO0 和 METR
    geo_data = None
    if file_version >= 57 and geo0_length > 0:
        geo_data = data[geo0_offset:geo0_offset + geo0_length]

    metr_data = None
    if file_version >= 55 and metr_length > 0:
        metr_data = data[metr_offset:metr_offset + metr_length]

    # 调用解析
    try:
        result, segments = parse_and_split(decompressed, file_version, metr_data, geo_data)
    except Exception as e:
        print(f"  [错误] 解析失败: {e}")
        return

    # 准备输出子目录（以输入文件名命名）
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    out_subdir = os.path.join(output_dir, base_name)
    os.makedirs(out_subdir, exist_ok=True)

    # 写入分段文件（可选）
    for seg_name in SEGMENT_NAMES_V3:
        if seg_name in segments:
            with open(os.path.join(out_subdir, seg_name), 'wb') as f:
                f.write(segments[seg_name])

    # 导出修正后的 OBJ
    export_obj_corrected(result, out_subdir, base_name)
    print(f"  [完成] 输出到 {out_subdir}")


def process_directory(input_dir, output_dir, recursive=True):
    """批量处理目录下的所有 .meshes 文件。"""
    if not os.path.isdir(input_dir):
        print(f"[错误] 目录不存在: {input_dir}")
        return

    meshes_files = []
    if recursive:
        for root, _, files in os.walk(input_dir):
            for f in files:
                if f.endswith('.meshes'):
                    meshes_files.append(os.path.join(root, f))
    else:
        for f in os.listdir(input_dir):
            if f.endswith('.meshes') and os.path.isfile(os.path.join(input_dir, f)):
                meshes_files.append(os.path.join(input_dir, f))

    if not meshes_files:
        print(f"[提示] 在 {input_dir} 中未找到 .meshes 文件")
        return

    print(f"\n找到 {len(meshes_files)} 个 .meshes 文件，开始处理...\n")
    for idx, mf in enumerate(meshes_files, 1):
        print(f"[{idx}/{len(meshes_files)}]")
        process_meshes(mf, output_dir)
        print()


# ------------------------------------------------------------
# 交互菜单
# ------------------------------------------------------------
def interactive_menu():
    print("=" * 55)
    print("   🧊 .meshes → OBJ 启动器 (绕序修正版)")
    print("=" * 55)
    print()

    while True:
        print("请选择模式：")
        print("  1. 单文件转换")
        print("  2. 批量转换（目录）")
        print("  3. 退出")
        choice = input("请输入数字 (1/2/3): ").strip()

        if choice == '3':
            print("退出。")
            break

        if choice not in ('1', '2'):
            print("无效输入，请重新选择。\n")
            continue

        # 获取输入路径
        if choice == '1':
            src = input("请输入 .meshes 文件路径: ").strip().strip('"').strip("'")
            if not os.path.isfile(src):
                print("文件不存在，请重新输入。\n")
                continue
            src_list = [src]
        else:  # 批量
            src = input("请输入包含 .meshes 文件的目录路径: ").strip().strip('"').strip("'")
            if not os.path.isdir(src):
                print("目录不存在，请重新输入。\n")
                continue
            rec = input("是否递归子目录？(y/n，默认 y): ").strip().lower()
            recursive = rec != 'n'
            src_list = []
            if recursive:
                for root, _, files in os.walk(src):
                    for f in files:
                        if f.endswith('.meshes'):
                            src_list.append(os.path.join(root, f))
            else:
                for f in os.listdir(src):
                    if f.endswith('.meshes') and os.path.isfile(os.path.join(src, f)):
                        src_list.append(os.path.join(src, f))
            if not src_list:
                print("未找到任何 .meshes 文件。\n")
                continue

        # 获取输出目录
        default_out = os.path.join(SCRIPT_DIR, 'output')
        out_dir = input(f"请输入输出目录 (直接回车使用默认: {default_out}): ").strip().strip('"').strip("'")
        if not out_dir:
            out_dir = default_out
        os.makedirs(out_dir, exist_ok=True)

        # 确认
        print(f"\n即将处理 {len(src_list)} 个文件，输出到: {out_dir}")
        confirm = input("确认？(y/n，默认 y): ").strip().lower()
        if confirm == 'n':
            print("已取消。\n")
            continue

        # 开始处理
        print("\n开始处理...\n")
        for idx, mf in enumerate(src_list, 1):
            print(f"[{idx}/{len(src_list)}]")
            process_meshes(mf, out_dir)
            print()

        print("\n所有任务完成！\n")


if __name__ == '__main__':
    try:
        interactive_menu()
    except KeyboardInterrupt:
        print("\n\n用户中断。")
    except Exception as e:
        print(f"\n发生未预期错误: {e}")
        import traceback
        traceback.print_exc()
    input("\n按 Enter 键退出...")