#!/usr/bin/env python3
"""
批量地图导出工具 v7.0 - 自动生成颜色（不硬编码）
遍历 level 目录下的所有地图文件夹，批量导出 OBJ
输出到和 level 同级的"输出"文件夹
支持选择是否导出标记小球
"""

import os
import sys
import json
import struct
import math
import subprocess
import time
import shutil
import hashlib
from datetime import datetime
from collections import OrderedDict
from pathlib import Path

# 添加当前目录到路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# ============================================================
# 导入依赖
# ============================================================
HAS_LZ4 = False
HAS_MESHES = False
HAS_MESH = False
parse_and_split = None
_mesh_handlers = {}
HEADER_VERSION_MAP = {}

try:
    import lz4.block
    HAS_LZ4 = True
except ImportError:
    print("[WARN] lz4 未安装，地形导出将不可用")
    print("       请运行: pip install lz4")

# 导入 mesh 解析
try:
    from meshtoobj import (
        process_header_17, process_header_1A, process_header_1C,
        process_header_1E, process_header_1F, process_header_20,
        HEADER_VERSION_MAP as _HVM
    )
    HEADER_VERSION_MAP = _HVM
    _mesh_handlers = {
        b'\x17\x00\x00\x00': process_header_17,
        b'\x1a\x00\x00\x00': process_header_1A,
        b'\x1c\x00\x00\x00': process_header_1C,
        b'\x1e\x00\x00\x00': process_header_1E,
        b'\x1f\x00\x00\x00': process_header_1F,
        b'\x20\x00\x00\x00': process_header_20,
    }
    HAS_MESH = True
    print("[OK] meshtoobj.py 已加载")
except ImportError as e:
    print(f"[WARN] meshtoobj.py 导入失败: {e}")

# 导入 meshes 解析
try:
    from Sky_Bstbake import parse_and_split as _parse_and_split
    parse_and_split = _parse_and_split
    HAS_MESHES = True
    print("[OK] Sky_Bstbake.py 已加载")
except ImportError as e:
    print(f"[WARN] Sky_Bstbake.py 导入失败: {e}")

# ============================================================
# 全局颜色映射（跨地图共享）
# ============================================================
_global_color_map = {}
_global_color_list = []

def get_color_from_classname(cls_name):
    """根据类名生成稳定的颜色（使用哈希值）"""
    if cls_name in _global_color_map:
        return _global_color_map[cls_name]
    
    # 使用 MD5 哈希生成颜色
    hash_obj = hashlib.md5(cls_name.encode('utf-8'))
    hash_bytes = hash_obj.digest()
    
    # 取前3个字节作为 RGB，确保颜色明亮（值在 0.3-1.0 之间）
    r = 0.3 + (hash_bytes[0] / 255.0) * 0.7
    g = 0.3 + (hash_bytes[1] / 255.0) * 0.7
    b = 0.3 + (hash_bytes[2] / 255.0) * 0.7
    
    color = (round(r, 4), round(g, 4), round(b, 4))
    _global_color_map[cls_name] = color
    _global_color_list.append(f"{cls_name} -> ({color[0]:.4f}, {color[1]:.4f}, {color[2]:.4f})")
    return color

def save_global_color_map(color_path):
    """保存全局颜色映射文件"""
    try:
        with open(color_path, 'w', encoding='utf-8') as f:
            f.write("# 全局类名 -> RGB颜色映射表\n")
            f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("# 此映射表在批量处理所有地图时共享，保证同一类名颜色一致\n")
            f.write("#" + "=" * 78 + "\n\n")
            for line in sorted(_global_color_list):
                f.write(line + "\n")
        return True
    except Exception as e:
        print(f"❌ 保存颜色映射失败: {e}")
        return False

# ============================================================
# 颜色
# ============================================================
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

DEFAULT_COLOR = (0.5, 0.5, 0.5)

# ============================================================
# 工具函数
# ============================================================
def make_sphere_verts(cx, cy, cz, radius=0.5, segments=8):
    verts = []
    faces = []
    # 翻转 X 和 Z
    verts.append((-cx, cy + radius, -cz))
    verts.append((-cx, cy - radius, -cz))
    rings = segments // 2
    for i in range(1, rings):
        phi = math.pi * i / rings
        y = cy + radius * math.cos(phi)
        r = radius * math.sin(phi)
        for j in range(segments):
            theta = 2 * math.pi * j / segments
            x = cx + r * math.cos(theta)
            z = cz + r * math.sin(theta)
            verts.append((-x, y, -z))
    for j in range(segments):
        faces.append((0, 2 + j, 2 + (j + 1) % segments))
    for j in range(segments):
        faces.append((1, 2 + (segments - 1) * (rings - 1) + (j + 1) % segments,
                      2 + (segments - 1) * (rings - 1) + j))
    for i in range(rings - 2):
        for j in range(segments):
            a = 2 + i * segments + j
            b = 2 + i * segments + (j + 1) % segments
            c = 2 + (i + 1) * segments + j
            d = 2 + (i + 1) * segments + (j + 1) % segments
            faces.append((a, b, d))
            faces.append((a, d, c))
    return verts, faces

def apply_transform(verts, raw_floats):
    if len(raw_floats) < 16:
        return verts
    m = [float(x) for x in raw_floats[:16]]
    result = []
    for v in verts:
        x, y, z = v[0], v[1], v[2]
        nx = m[0]*x + m[4]*y + m[8]*z + m[12]
        ny = m[1]*x + m[5]*y + m[9]*z + m[13]
        nz = m[2]*x + m[6]*y + m[10]*z + m[14]
        # 翻转 X 和 Z
        result.append((-nx, ny, -nz))
    return result

# ============================================================
# 模糊匹配 mesh 文件
# ============================================================
def find_mesh_file(mesh_folder, resource_name):
    if not os.path.isdir(mesh_folder):
        return None
    exact_path = os.path.join(mesh_folder, f"{resource_name}.mesh")
    if os.path.exists(exact_path):
        return exact_path
    try:
        for f in os.listdir(mesh_folder):
            if f.endswith('.mesh') and resource_name in f:
                return os.path.join(mesh_folder, f)
    except:
        pass
    return None

# ============================================================
# 地形解析（修复镜像：翻转 X 和 Z）
# ============================================================
def parse_meshes_to_obj_data(meshes_file):
    if not HAS_MESHES or not HAS_LZ4:
        return [], []
    try:
        with open(meshes_file, 'rb') as f:
            data = f.read()
    except:
        return [], []
    
    if data[0:4] != b'LVL0':
        return [], []
    
    file_version = struct.unpack_from('<I', data, 0x04)[0]
    lod0_offset = lod0_length = 0
    geo0_offset = geo0_length = 0
    metr_offset = metr_length = 0
    
    for i in range(data[0x08]):
        base = 0x08 + 4 + i * 12
        name = data[base:base+4].rstrip(b'\x00').decode('ascii', errors='ignore')
        seg_offset = struct.unpack_from('<I', data, base+4)[0]
        seg_length = struct.unpack_from('<I', data, base+8)[0]
        if name == 'LOD0':
            lod0_offset, lod0_length = seg_offset, seg_length
        elif name == 'GEO0':
            geo0_offset, geo0_length = seg_offset, seg_length
        elif name == 'METR':
            metr_offset, metr_length = seg_offset, seg_length
    
    if lod0_length == 0:
        return [], []
    
    compressed = data[lod0_offset:lod0_offset + lod0_length]
    decompressed = lz4.block.decompress(compressed, uncompressed_size=0xC00000)
    geo_data = data[geo0_offset:geo0_offset + geo0_length] if (file_version >= 57 and geo0_length > 0) else None
    metr_data = data[metr_offset:metr_offset + metr_length] if (file_version >= 55 and metr_length > 0) else None
    
    try:
        result, _ = parse_and_split(decompressed, file_version, metr_data, geo_data)
    except Exception as e:
        print(f"    解析失败: {e}")
        return [], []
    
    all_verts = []
    all_faces = []
    v_offset = 0
    
    for section in ['terrain', 'skirts', 'occluder']:
        for chunk in result.get(section, []):
            if chunk.get('ib_raw') and chunk.get('patches'):
                verts = chunk.get('verts', [])
                ib_raw = chunk.get('ib_raw', b'')
                patches = chunk.get('patches', [])
                terrain_patches = [p for p in patches if p['array'] == 'A']
                
                if not verts or not ib_raw or not terrain_patches:
                    continue
                
                base_v = len(all_verts)
                vert_indices = {}
                new_idx = 0
                
                for patch in terrain_patches:
                    vs = patch['vert_start']
                    ve = patch['vert_end']
                    for vi in range(vs, ve):
                        if vi not in vert_indices:
                            vert_indices[vi] = new_idx
                            pos = verts[vi].get('pos', (0, 0, 0))
                            # 翻转 X 和 Z
                            all_verts.append((-pos[0], pos[1], -pos[2]))
                            new_idx += 1
                
                for patch in terrain_patches:
                    ib_start = patch['ib_byte_off']
                    ib_end = ib_start + patch['ib_byte_len']
                    patch_bytes = ib_raw[ib_start:ib_end]
                    tri_count = len(patch_bytes) // 3
                    if tri_count == 0:
                        continue
                    vs = patch['vert_start']
                    for ti in range(tri_count):
                        bo = ti * 3
                        i0 = vert_indices.get(patch_bytes[bo] + vs, -1)
                        i1 = vert_indices.get(patch_bytes[bo + 1] + vs, -1)
                        i2 = vert_indices.get(patch_bytes[bo + 2] + vs, -1)
                        if i0 >= 0 and i1 >= 0 and i2 >= 0:
                            all_faces.append((i0 + base_v, i2 + base_v, i1 + base_v))
                
            elif chunk.get('verts') and chunk.get('indices'):
                verts = chunk.get('verts', [])
                indices = chunk.get('indices', [])
                if not verts or not indices:
                    continue
                base_v = len(all_verts)
                for v in verts:
                    pos = v.get('pos', (0, 0, 0))
                    # 翻转 X 和 Z
                    all_verts.append((-pos[0], pos[1], -pos[2]))
                for i in range(0, len(indices), 3):
                    if i + 2 < len(indices):
                        all_faces.append((indices[i] + base_v, indices[i+2] + base_v, indices[i+1] + base_v))
                v_offset += len(verts)
    
    return all_verts, all_faces

# ============================================================
# 模型解析
# ============================================================
def parse_mesh_file(mesh_path):
    if not HAS_MESH:
        return [], []
    try:
        with open(mesh_path, 'rb') as f:
            data = f.read()
    except:
        return [], []
    
    if len(data) < 4:
        return [], []
    
    header = data[:4]
    version = HEADER_VERSION_MAP.get(header)
    if version is None:
        return [], []
    
    handler = _mesh_handlers.get(header)
    if handler is None:
        return [], []
    
    try:
        filename = os.path.basename(mesh_path)
        if header == b'\x17\x00\x00\x00':
            result = handler(data, mesh_path, filename, version, False, True)
        else:
            result = handler(data, mesh_path, filename, version, True)
        
        if result and len(result) >= 3:
            verts = [(v[0], v[1], v[2]) for v in result[0]]
            faces = [(f[0], f[1], f[2]) for f in result[2]]
            return verts, faces
    except:
        pass
    
    return [], []

# ============================================================
# JSON 解析和资源提取
# ============================================================
def convert_bin_to_json(bin_path, output_dir):
    converter = os.path.join(SCRIPT_DIR, 'bintojson.py')
    if not os.path.exists(converter):
        return None
    
    json_path = os.path.join(output_dir, os.path.basename(bin_path) + '.json')
    if os.path.exists(json_path):
        return json_path
    
    try:
        result = subprocess.run(
            [sys.executable, converter, bin_path],
            capture_output=True, text=True, timeout=300,
            cwd=output_dir
        )
        if os.path.exists(json_path):
            return json_path
        alt_path = bin_path + '.json'
        if os.path.exists(alt_path):
            shutil.move(alt_path, json_path)
            return json_path
    except:
        pass
    
    return None

def extract_resource_name_from_cls_data(cls_data):
    if not isinstance(cls_data, dict):
        return None
    for key, value in cls_data.items():
        if 'resourcename' in key.lower():
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for sub_k, sub_v in value.items():
                    if isinstance(sub_v, str) and sub_v.strip():
                        return sub_v.strip()
    for key, value in cls_data.items():
        if isinstance(value, dict):
            result = extract_resource_name_from_cls_data(value)
            if result:
                return result
    return None

def extract_transform_from_cls_data(cls_data):
    for key, value in cls_data.items():
        if 'transform' in key.lower():
            if isinstance(value, dict):
                rf = value.get('_raw_floats', [])
                if len(rf) >= 16:
                    return (float(rf[12]), float(rf[13]), float(rf[14])), rf
            elif isinstance(value, list) and len(value) >= 16:
                return (float(value[12]), float(value[13]), float(value[14])), value
    return None, None

def find_all_levelmesh_with_resources(json_data):
    results = []
    bst_nodes = json_data.get('BSTNodes', {})
    
    for node_name, node_data in bst_nodes.items():
        if not isinstance(node_data, dict):
            continue
        for cls_name, cls_data in node_data.items():
            if not isinstance(cls_data, dict):
                continue
            if 'LevelMesh' not in cls_name:
                continue
            resource_name = extract_resource_name_from_cls_data(cls_data)
            if not resource_name:
                continue
            coords, raw_floats = extract_transform_from_cls_data(cls_data)
            if coords is None:
                continue
            results.append({
                'node_name': node_name,
                'class_name': cls_name,
                'resource_name': resource_name,
                'coords': coords,
                'raw_floats': raw_floats
            })
    return results

def find_all_markers(json_data):
    """提取所有非 LevelMesh 的有坐标节点"""
    markers = []
    bst_nodes = json_data.get('BSTNodes', {})
    
    for node_name, node_data in bst_nodes.items():
        if not isinstance(node_data, dict):
            continue
        for cls_name, cls_data in node_data.items():
            if not isinstance(cls_data, dict):
                continue
            if 'LevelMesh' in cls_name:
                continue
            
            coords, _ = extract_transform_from_cls_data(cls_data)
            if coords:
                markers.append({
                    'name': node_name,
                    'class': cls_name,
                    'x': coords[0], 'y': coords[1], 'z': coords[2],
                })
    
    return markers

def select_marker_categories(markers):
    """让用户选择要导出的标记类名"""
    if not markers:
        return []
    
    # 收集所有类名并去重排序
    class_names = sorted(set(m['class'] for m in markers))
    
    print("\n" + "=" * 55)
    print("   标记类名选择（输入序号切换，回车完成）")
    print("=" * 55)
    print()
    print("  提示：所有类名都会自动生成颜色，无需预设")
    print()
    
    # 显示类名列表
    selected = {cn: True for cn in class_names}
    
    for i, cn in enumerate(class_names, 1):
        status = "✅" if selected[cn] else "❌"
        # 截断过长的类名
        display_cn = cn if len(cn) <= 40 else cn[:37] + "..."
        print(f"  {i:3}. {status} {display_cn}")
    
    print()
    print("  0. 全部启用")
    print("  a. 全部禁用")
    print()
    
    while True:
        choice = input("请输入序号 (1-{0}, 0, a，回车完成): ".format(len(class_names))).strip()
        if choice == '':
            break
        elif choice == '0':
            for cn in class_names:
                selected[cn] = True
            print("✅ 已启用所有类名")
            for i, cn in enumerate(class_names, 1):
                status = "✅" if selected[cn] else "❌"
                print(f"  {i:3}. {status} {cn[:40]}")
        elif choice.lower() == 'a':
            for cn in class_names:
                selected[cn] = False
            print("❌ 已禁用所有类名")
            for i, cn in enumerate(class_names, 1):
                status = "✅" if selected[cn] else "❌"
                print(f"  {i:3}. {status} {cn[:40]}")
        elif choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(class_names):
                cn = class_names[idx-1]
                selected[cn] = not selected[cn]
                status = "✅" if selected[cn] else "❌"
                print(f"  {idx:3}. {status} {cn[:40]}")
            else:
                print("❌ 无效序号")
        else:
            print("❌ 无效输入")
    
    enabled = [cn for cn in class_names if selected[cn]]
    print(f"\n将导出标记: {len(enabled)} 个类名")
    if enabled and len(enabled) <= 20:
        for cn in enabled:
            print(f"    - {cn[:50]}")
    elif enabled:
        print(f"    ... 共 {len(enabled)} 个类名")
    return enabled

# ============================================================
# 单个地图导出
# ============================================================
def export_single_map(map_folder, mesh_folder, output_base_dir, export_markers, enabled_classes, log_entry):
    map_name = os.path.basename(map_folder)
    output_dir = os.path.join(output_base_dir, map_name)
    os.makedirs(output_dir, exist_ok=True)
    
    log_entry['map_name'] = map_name
    log_entry['map_path'] = map_folder
    log_entry['output_path'] = output_dir
    log_entry['export_markers'] = export_markers
    log_entry['start_time'] = datetime.now().isoformat()
    
    # 查找文件
    bin_file = None
    meshes_file = None
    try:
        for f in os.listdir(map_folder):
            if f.endswith('.bin') and not f.endswith('.meshes'):
                bin_file = os.path.join(map_folder, f)
            elif f.endswith('.meshes'):
                meshes_file = os.path.join(map_folder, f)
    except:
        pass
    
    if not bin_file:
        log_entry['status'] = 'failed'
        log_entry['error'] = '未找到 .bin 文件'
        return False
    
    log_entry['bin_file'] = os.path.basename(bin_file)
    log_entry['meshes_file'] = os.path.basename(meshes_file) if meshes_file else None
    
    # 1. 转换 JSON
    json_path = convert_bin_to_json(bin_file, output_dir)
    if not json_path:
        log_entry['status'] = 'failed'
        log_entry['error'] = 'JSON 转换失败'
        return False
    
    # 2. 读取 JSON
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f, object_pairs_hook=OrderedDict)
    except:
        log_entry['status'] = 'failed'
        log_entry['error'] = 'JSON 读取失败'
        return False
    
    # 3. 提取 LevelMesh
    level_meshes = find_all_levelmesh_with_resources(json_data)
    unique_resources = set(lm['resource_name'] for lm in level_meshes)
    log_entry['levelmesh_count'] = len(level_meshes)
    log_entry['unique_resources'] = len(unique_resources)
    
    # 4. 提取标记
    markers = []
    if export_markers and enabled_classes:
        all_markers = find_all_markers(json_data)
        enabled_set = set(enabled_classes)
        markers = [m for m in all_markers if m['class'] in enabled_set]
    log_entry['markers_count'] = len(markers)
    
    # 5. 地形
    terrain_verts, terrain_faces = [], []
    if meshes_file and HAS_MESHES and HAS_LZ4:
        terrain_verts, terrain_faces = parse_meshes_to_obj_data(meshes_file)
    log_entry['terrain_verts'] = len(terrain_verts)
    log_entry['terrain_tris'] = len(terrain_faces)
    
    # 6. 模型加载
    mesh_models = []
    loaded_resources = set()
    success_count = 0
    fail_count = 0
    missing_count = 0
    
    if HAS_MESH and os.path.isdir(mesh_folder) and level_meshes:
        for lm in level_meshes:
            res = lm['resource_name']
            if res in loaded_resources:
                continue
            mesh_file = find_mesh_file(mesh_folder, res)
            if mesh_file and os.path.exists(mesh_file):
                verts, faces = parse_mesh_file(mesh_file)
                if verts and faces:
                    mesh_models.append({
                        'resource': res,
                        'verts': verts,
                        'faces': faces,
                        'instances': []
                    })
                    loaded_resources.add(res)
                    success_count += 1
                else:
                    fail_count += 1
            else:
                missing_count += 1
        
        model_map = {m['resource']: m for m in mesh_models}
        for lm in level_meshes:
            if lm['resource_name'] in model_map:
                model_map[lm['resource_name']]['instances'].append(lm)
        
        total_instances = sum(len(m['instances']) for m in mesh_models)
        log_entry['models_success'] = success_count
        log_entry['models_failed'] = fail_count
        log_entry['models_missing'] = missing_count
        log_entry['models_instances'] = total_instances
        log_entry['models_count'] = len(mesh_models)
    
    # 7. 写入 OBJ
    obj_path = os.path.join(output_dir, f"{map_name}.obj")
    mtl_path = os.path.join(output_dir, f"{map_name}.mtl")
    
    # 收集所有需要写入 MTL 的材质（标记类名）
    marker_classes = set(m['class'] for m in markers) if markers else set()
    
    try:
        with open(mtl_path, 'w', encoding='utf-8') as mf:
            mf.write("# Sky Map Materials (Auto-generated colors)\n")
            mf.write("# Colors are generated from class name hash\n\n")
            mf.write("newmtl terrain\nKd 0.45 0.42 0.38\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n\n")
            mf.write("newmtl model\nKd 0.75 0.73 0.68\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n\n")
            
            for cls_name in sorted(marker_classes):
                color = get_color_from_classname(cls_name)
                safe_name = cls_name.replace(' ', '_').replace('(', '_').replace(')', '_').replace('>', '_').replace('<', '_')
                mf.write(f"newmtl {safe_name}\nKd {color[0]:.4f} {color[1]:.4f} {color[2]:.4f}\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n\n")
        
        global_v = 1
        
        with open(obj_path, 'w', encoding='utf-8') as f:
            f.write(f"# Sky Map: {map_name}\n")
            f.write(f"# Export markers: {export_markers}\n")
            f.write(f"mtllib {map_name}.mtl\n\n")
            
            if terrain_verts:
                f.write("o Terrain\nusemtl terrain\n")
                for v in terrain_verts:
                    f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
                for tri in terrain_faces:
                    f.write(f"f {tri[0]+global_v} {tri[1]+global_v} {tri[2]+global_v}\n")
                global_v += len(terrain_verts)
                f.write("\n")
            
            for model in mesh_models:
                for inst in model['instances']:
                    raw_floats = inst.get('raw_floats')
                    if raw_floats:
                        transformed = apply_transform(model['verts'], raw_floats)
                    else:
                        transformed = [(-v[0], v[1], -v[2]) for v in model['verts']]
                    
                    f.write(f"o {model['resource']}\nusemtl model\n")
                    for v in transformed:
                        f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
                    for tri in model['faces']:
                        f.write(f"f {tri[0]+global_v} {tri[1]+global_v} {tri[2]+global_v}\n")
                    global_v += len(transformed)
                f.write("\n")
            
            if export_markers and markers:
                markers_by_class = {}
                for m in markers:
                    cls = m['class']
                    if cls not in markers_by_class:
                        markers_by_class[cls] = []
                    markers_by_class[cls].append(m)
                
                for cls_name, nodes in sorted(markers_by_class.items()):
                    safe_name = cls_name.replace(' ', '_').replace('(', '_').replace(')', '_').replace('>', '_').replace('<', '_')
                    f.write(f"o {safe_name}_Markers\nusemtl {safe_name}\n")
                    f.write(f"# {len(nodes)} 个 {cls_name} 节点\n")
                    for node in nodes:
                        verts, faces = make_sphere_verts(node['x'], node['y'], node['z'], 0.5)
                        for v in verts:
                            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
                        for tri in faces:
                            f.write(f"f {tri[0]+global_v} {tri[1]+global_v} {tri[2]+global_v}\n")
                        global_v += len(verts)
                    f.write("\n")
        
        log_entry['status'] = 'success'
        log_entry['obj_path'] = obj_path
        log_entry['total_vertices'] = global_v - 1
        return True
        
    except Exception as e:
        log_entry['status'] = 'failed'
        log_entry['error'] = str(e)
        return False

# ============================================================
# 批量处理
# ============================================================
def find_map_folders(level_dir):
    map_folders = []
    if not os.path.exists(level_dir):
        return map_folders
    for item in os.listdir(level_dir):
        item_path = os.path.join(level_dir, item)
        if os.path.isdir(item_path):
            try:
                has_bin = any(f.endswith('.bin') and not f.endswith('.meshes') for f in os.listdir(item_path))
                if has_bin:
                    map_folders.append(item_path)
            except:
                continue
    return map_folders

def get_available_classes(level_dir):
    """从第一个地图获取可用的类名列表（用于交互式选择）"""
    map_folders = find_map_folders(level_dir)
    if not map_folders:
        return []
    
    # 尝试第一个地图
    for map_folder in map_folders[:3]:  # 尝试前3个地图
        bin_file = None
        for f in os.listdir(map_folder):
            if f.endswith('.bin') and not f.endswith('.meshes'):
                bin_file = os.path.join(map_folder, f)
                break
        
        if bin_file:
            temp_dir = os.path.join(map_folder, '.temp')
            os.makedirs(temp_dir, exist_ok=True)
            json_path = convert_bin_to_json(bin_file, temp_dir)
            if json_path:
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        json_data = json.load(f)
                    markers = find_all_markers(json_data)
                    if markers:
                        # 清理临时文件
                        try:
                            shutil.rmtree(temp_dir)
                        except:
                            pass
                        return sorted(set(m['class'] for m in markers))
                except:
                    pass
                try:
                    shutil.rmtree(temp_dir)
                except:
                    pass
    
    return []

def run_batch(level_dir, mesh_dir, output_dir, export_markers, enabled_classes):
    print(f"\n{Colors.BOLD}📂 Level 目录: {level_dir}{Colors.END}")
    print(f"{Colors.BOLD}📦 Mesh 目录: {mesh_dir}{Colors.END}")
    print(f"{Colors.BOLD}📁 输出目录: {output_dir}{Colors.END}")
    print(f"{Colors.BOLD}🏷️  导出标记: {'是' if export_markers else '否'}{Colors.END}")
    if export_markers and enabled_classes:
        print(f"{Colors.BOLD}📌 标记类名数量: {len(enabled_classes)}{Colors.END}")
    print()
    
    map_folders = find_map_folders(level_dir)
    if not map_folders:
        print(f"{Colors.RED}❌ 未找到任何地图文件夹{Colors.END}")
        return
    
    print(f"{Colors.CYAN}📋 找到 {len(map_folders)} 个地图:{Colors.END}")
    for mf in map_folders[:20]:
        print(f"   - {os.path.basename(mf)}")
    if len(map_folders) > 20:
        print(f"   ... 共 {len(map_folders)} 个")
    print()
    
    confirm = input(f"{Colors.YELLOW}是否开始批量导出? (y/n): {Colors.END}").strip().lower()
    if confirm != 'y':
        print("已取消")
        return
    
    os.makedirs(output_dir, exist_ok=True)
    
    log_data = {
        'export_time': datetime.now().isoformat(),
        'level_dir': level_dir,
        'mesh_dir': mesh_dir,
        'output_dir': output_dir,
        'export_markers': export_markers,
        'enabled_classes': enabled_classes if export_markers else [],
        'total_maps': len(map_folders),
        'success_count': 0,
        'fail_count': 0,
        'maps': []
    }
    
    start_all = time.time()
    
    for i, map_folder in enumerate(map_folders, 1):
        map_name = os.path.basename(map_folder)
        print(f"\n[{i}/{len(map_folders)}] {map_name}")
        
        log_entry = {}
        success = export_single_map(map_folder, mesh_dir, output_dir, export_markers, enabled_classes, log_entry)
        
        if success:
            log_data['success_count'] += 1
            print(f"   {Colors.GREEN}✅ 成功{Colors.END}")
            print(f"      地形: {log_entry.get('terrain_verts', 0)}v, {log_entry.get('terrain_tris', 0)}t")
            print(f"      模型: {log_entry.get('models_count', 0)}种, {log_entry.get('models_instances', 0)}实例")
            print(f"      标记: {log_entry.get('markers_count', 0)} {'(已导出)' if export_markers else '(已禁用)'}")
        else:
            log_data['fail_count'] += 1
            print(f"   {Colors.RED}❌ 失败: {log_entry.get('error', '未知错误')}{Colors.END}")
        
        log_entry['end_time'] = datetime.now().isoformat()
        log_data['maps'].append(log_entry)
    
    elapsed_all = time.time() - start_all
    log_data['total_elapsed_seconds'] = round(elapsed_all, 2)
    log_data['success_rate'] = f"{log_data['success_count']/log_data['total_maps']*100:.1f}%" if log_data['total_maps'] > 0 else "0%"
    
    # 保存日志
    log_dir = output_dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    json_path = os.path.join(log_dir, f"batch_export_{timestamp}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)
    
    txt_path = os.path.join(log_dir, f"batch_export_{timestamp}.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("批量地图导出日志\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"导出时间: {log_data['export_time']}\n")
        f.write(f"Level 目录: {log_data['level_dir']}\n")
        f.write(f"Mesh 目录: {log_data['mesh_dir']}\n")
        f.write(f"输出目录: {log_data['output_dir']}\n")
        f.write(f"导出标记: {'是' if export_markers else '否'}\n")
        if export_markers and enabled_classes:
            f.write(f"标记类名数量: {len(enabled_classes)}\n")
        f.write(f"总地图数: {log_data['total_maps']}\n")
        f.write(f"成功数: {log_data['success_count']}\n")
        f.write(f"失败数: {log_data['fail_count']}\n")
        f.write(f"成功率: {log_data['success_rate']}\n")
        f.write(f"总耗时: {elapsed_all:.1f} 秒\n\n")
        
        f.write("=" * 80 + "\n")
        f.write("详细列表\n")
        f.write("=" * 80 + "\n\n")
        
        for m in log_data['maps']:
            status = "✅" if m['status'] == 'success' else "❌"
            f.write(f"{status} {m['map_name']}\n")
            if m['status'] == 'success':
                f.write(f"   输出: {m.get('obj_path', 'N/A')}\n")
                f.write(f"   地形: {m.get('terrain_verts', 0)}v, {m.get('terrain_tris', 0)}t\n")
                f.write(f"   模型: {m.get('models_count', 0)}种, {m.get('models_instances', 0)}实例\n")
                f.write(f"   标记: {m.get('markers_count', 0)}\n")
            else:
                f.write(f"   错误: {m.get('error', '未知')}\n")
            f.write("\n")
    
    # 保存全局颜色映射
    color_path = os.path.join(log_dir, f"colors_{timestamp}.txt")
    save_global_color_map(color_path)
    
    print(f"\n{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}📊 批量导出完成！{Colors.END}")
    print(f"{Colors.BOLD}{'='*60}{Colors.END}")
    print(f"   总地图数: {log_data['total_maps']}")
    print(f"{Colors.GREEN}   成功: {log_data['success_count']}{Colors.END}")
    print(f"{Colors.RED}   失败: {log_data['fail_count']}{Colors.END}")
    print(f"   成功率: {log_data['success_rate']}")
    print(f"   总耗时: {elapsed_all:.1f} 秒")
    print(f"   颜色映射: {len(_global_color_map)} 种颜色")
    print(f"\n📝 日志文件:")
    print(f"   TXT: {txt_path}")
    print(f"   JSON: {json_path}")
    print(f"🎨 颜色映射: {color_path}")

# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 55)
    print("   批量地图导出工具 v7.0 - 自动生成颜色")
    print("   输出到和 level 同级的'输出'文件夹")
    print("=" * 55)
    print()
    print("说明：")
    print("  - 标记类名会自动从地图 JSON 中提取")
    print("  - 每个类名自动生成颜色（基于哈希值）")
    print("  - 可自由选择要导出的类名")
    print("  - 颜色映射表会保存到输出目录")
    print()
    
    level_dir = input(f"{Colors.CYAN}Level 目录路径: {Colors.END}").strip().strip('"').strip("'")
    if not os.path.isdir(level_dir):
        print(f"{Colors.RED}❌ Level 目录不存在{Colors.END}")
        return
    
    mesh_dir = input(f"{Colors.CYAN}Mesh 文件夹路径: {Colors.END}").strip().strip('"').strip("'")
    if not mesh_dir:
        mesh_dir = os.path.join(SCRIPT_DIR, 'mesh')
    if not os.path.isdir(mesh_dir):
        print(f"{Colors.RED}❌ Mesh 目录不存在: {mesh_dir}{Colors.END}")
        return
    
    export_markers_input = input(f"{Colors.CYAN}是否导出标记小球? (y/n, 默认 y): {Colors.END}").strip().lower()
    export_markers = export_markers_input != 'n'
    
    enabled_classes = None
    if export_markers:
        print(f"\n{Colors.CYAN}正在扫描地图获取可用的类名...{Colors.END}")
        all_classes = get_available_classes(level_dir)
        if all_classes:
            enabled_classes = select_marker_categories(
                [{'class': c} for c in all_classes]
            )
        else:
            print(f"{Colors.YELLOW}⚠️ 无法获取类名列表，将导出所有标记{Colors.END}")
            enabled_classes = None
    
    # 输出目录：和 level 同级的"输出"文件夹
    level_parent = os.path.dirname(level_dir.rstrip('/\\'))
    output_dir = os.path.join(level_parent, "输出")
    print(f"{Colors.CYAN}输出目录: {output_dir}{Colors.END}")
    
    run_batch(level_dir, mesh_dir, output_dir, export_markers, enabled_classes)
    
    input(f"\n{Colors.CYAN}按回车退出...{Colors.END}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}程序被中断{Colors.END}")
        sys.exit(0)