#!/usr/bin/env python3
"""
地图可视化导出工具 v17 - 支持详细日志记录（完整记录所有模型）
"""

import sys
import os
import json
import struct
import math
import io
import importlib.util
import subprocess
import shutil
import time
from datetime import datetime
from collections import OrderedDict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# ============================================================
# 日志记录
# ============================================================
_log_lines = []
_log_models_success = []  # 记录成功加载的模型
_log_models_failed = []   # 记录失败的模型
_log_models_missing = []  # 记录缺失的模型

def log_init():
    global _log_lines, _log_models_success, _log_models_failed, _log_models_missing
    _log_lines = []
    _log_models_success = []
    _log_models_failed = []
    _log_models_missing = []
    _log_lines.append("=" * 80)
    _log_lines.append(f"地图可视化导出日志")
    _log_lines.append(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _log_lines.append("=" * 80)
    _log_lines.append("")

def log_write(msg, also_print=True):
    global _log_lines
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_msg = f"[{timestamp}] {msg}"
    _log_lines.append(log_msg)
    if also_print:
        print(msg)

def log_model_success(resource_name, verts, faces, mesh_file):
    _log_models_success.append({
        'resource_name': resource_name,
        'vertices': verts,
        'faces': faces,
        'mesh_file': mesh_file
    })

def log_model_failed(resource_name, error):
    _log_models_failed.append({
        'resource_name': resource_name,
        'error': error
    })

def log_model_missing(resource_name, expected_file):
    _log_models_missing.append({
        'resource_name': resource_name,
        'expected_file': expected_file
    })

def log_save(filepath):
    global _log_lines, _log_models_success, _log_models_failed, _log_models_missing
    
    # 添加统计信息到日志
    _log_lines.append("")
    _log_lines.append("=" * 80)
    _log_lines.append("模型加载详情")
    _log_lines.append("=" * 80)
    _log_lines.append(f"成功加载: {len(_log_models_success)} 种")
    for m in _log_models_success:
        _log_lines.append(f"  ✅ {m['resource_name']} ({m['vertices']}v, {m['faces']}t) -> {m['mesh_file']}")
    
    if _log_models_failed:
        _log_lines.append(f"\n解析失败: {len(_log_models_failed)} 种")
        for m in _log_models_failed:
            _log_lines.append(f"  ❌ {m['resource_name']} - {m['error']}")
    
    if _log_models_missing:
        _log_lines.append(f"\n文件缺失: {len(_log_models_missing)} 种")
        for m in _log_models_missing:
            _log_lines.append(f"  ⚠️ {m['resource_name']} -> {m['expected_file']}")
    
    _log_lines.append("")
    _log_lines.append("=" * 80)
    _log_lines.append(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _log_lines.append("=" * 80)
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("\n".join(_log_lines))
        return True
    except Exception as e:
        print(f"❌ 保存日志失败: {e}")
        return False

# ============================================================
# 导入
# ============================================================
try:
    import lz4.block
    HAS_LZ4 = True
    log_write("[OK] lz4")
except ImportError:
    HAS_LZ4 = False
    log_write("[WARN] lz4 未安装，地形导出将不可用")

parse_and_split = None
HAS_MESHES = False
for _name in ["Sky-Bstbake.py", "Sky_Bstbake.py", "BstBaked.py"]:
    _p = os.path.join(SCRIPT_DIR, _name)
    if os.path.exists(_p):
        _old_out, _old_err = sys.stdout, sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
        try:
            _spec = importlib.util.spec_from_file_location("_stb", _p)
            _stb = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_stb)
            parse_and_split = getattr(_stb, 'parse_and_split', None)
            if parse_and_split:
                HAS_MESHES = True
                log_write(f"[OK] {os.path.basename(_p)}")
        except Exception as e:
            log_write(f"[WARN] 导入 {_name} 失败: {e}")
        finally:
            sys.stdout, sys.stderr = _old_out, _old_err
        break

# 导入 mesh 解析函数
HAS_MESH = False
_mesh_handlers = {}
_process_single_file = None
HEADER_VERSION_MAP = {}

try:
    from meshtoobj import (
        process_header_17, process_header_1A, process_header_1C,
        process_header_1E, process_header_1F, process_header_20,
        HEADER_VERSION_MAP, process_single_file
    )
    HEADER_VERSION_MAP = HEADER_VERSION_MAP
    _process_single_file = process_single_file
    _mesh_handlers = {
        b'\x17\x00\x00\x00': process_header_17,
        b'\x1a\x00\x00\x00': process_header_1A,
        b'\x1c\x00\x00\x00': process_header_1C,
        b'\x1e\x00\x00\x00': process_header_1E,
        b'\x1f\x00\x00\x00': process_header_1F,
        b'\x20\x00\x00\x00': process_header_20,
    }
    HAS_MESH = True
    log_write("[OK] meshtoobj.py")
except ImportError as e:
    log_write(f"[WARN] meshtoobj.py 导入失败: {e}")

# ============================================================
# 标记分类定义
# ============================================================
MARKER_CATEGORIES = {
    '传送门': {'keywords': ['Portal'], 'color': (1.0, 0.3, 0.3), 'enabled': True},
    '冥想区': {'keywords': ['MeditationArea'], 'color': (0.3, 0.5, 1.0), 'enabled': True},
    'NPC': {'keywords': ['Npc'], 'color': (0.2, 0.8, 0.2), 'enabled': True},
    '检查点': {'keywords': ['Checkpoint'], 'color': (1.0, 0.5, 0.0), 'enabled': True},
    '标记点': {'keywords': ['Marker'], 'color': (1.0, 0.8, 0.2), 'enabled': True},
    '边界': {'keywords': ['Boundary'], 'color': (1.0, 0.0, 0.0), 'enabled': True},
    '风力': {'keywords': ['Wind'], 'color': (0.5, 0.8, 1.0), 'enabled': True},
    '水体': {'keywords': ['Water'], 'color': (0.2, 0.5, 1.0), 'enabled': True},
    '时间轴': {'keywords': ['Timeline'], 'color': (0.8, 0.3, 0.8), 'enabled': True},
    '启用开关': {'keywords': ['Enable'], 'color': (0.5, 0.5, 0.5), 'enabled': True},
    '粒子生成': {'keywords': ['SpawnMotes', 'Spawn'], 'color': (1.0, 1.0, 0.5), 'enabled': True},
    '音效': {'keywords': ['SoundEmitter'], 'color': (0.2, 0.8, 0.8), 'enabled': True},
    '光源': {'keywords': ['PointLight'], 'color': (1.0, 0.9, 0.4), 'enabled': True},
    '火焰': {'keywords': ['Flame'], 'color': (1.0, 0.4, 0.1), 'enabled': True},
}

def get_marker_category(cls_name):
    for cat_name, cat_info in MARKER_CATEGORIES.items():
        for keyword in cat_info['keywords']:
            if keyword in cls_name:
                return cat_name
    return None

def get_marker_color(cls_name):
    for cat_info in MARKER_CATEGORIES.values():
        for keyword in cat_info['keywords']:
            if keyword in cls_name:
                return cat_info['color']
    return DEFAULT_COLOR

# ============================================================
# 颜色
# ============================================================
CLASS_COLORS = {
    'LevelMesh':(0.7,0.7,0.7), 'Marker':(1.0,0.8,0.2), 'Npc':(0.2,0.8,0.2),
    'MeditationArea':(0.3,0.5,1.0), 'Portal':(1.0,0.3,0.3), 'Checkpoint':(1.0,0.5,0.0),
    'Boundary':(1.0,0.0,0.0), 'Wind':(0.5,0.8,1.0), 'Water':(0.2,0.5,1.0),
    'Timeline':(0.8,0.3,0.8), 'Enable':(0.5,0.5,0.5), 'SpawnMotes':(1.0,1.0,0.5),
    'SoundEmitter':(0.2,0.8,0.8), 'PointLight':(1.0,0.9,0.4), 'Flame':(1.0,0.4,0.1),
}
DEFAULT_COLOR = (0.5,0.5,0.5)

def get_class_color(cls_name):
    for key, color in CLASS_COLORS.items():
        if key in cls_name: return color
    return DEFAULT_COLOR

# ============================================================
# 小球（修复镜像：翻转 X 和 Z）
# ============================================================
def make_sphere_verts(cx, cy, cz, radius=0.5, segments=8):
    verts=[]; faces=[]
    verts.append((-cx, cy+radius, -cz))
    verts.append((-cx, cy-radius, -cz))
    rings=segments//2
    for i in range(1,rings):
        phi=math.pi*i/rings; y=cy+radius*math.cos(phi); r=radius*math.sin(phi)
        for j in range(segments):
            theta=2*math.pi*j/segments; x=cx+r*math.cos(theta); z=cz+r*math.sin(theta)
            verts.append((-x, y, -z))
    for j in range(segments): faces.append((0,2+j,2+(j+1)%segments))
    for j in range(segments): faces.append((1,2+(segments-1)*(rings-1)+(j+1)%segments,2+(segments-1)*(rings-1)+j))
    for i in range(rings-2):
        for j in range(segments):
            a=2+i*segments+j; b=2+i*segments+(j+1)%segments
            c=2+(i+1)*segments+j; d=2+(i+1)*segments+(j+1)%segments
            faces.append((a,b,d)); faces.append((a,d,c))
    return verts,faces

# ============================================================
# 变换矩阵（修复镜像：翻转 X 和 Z）
# ============================================================
def apply_transform(verts, raw_floats):
    if len(raw_floats)<16: return verts
    m=[float(x) for x in raw_floats[:16]]; result=[]
    for v in verts:
        x,y,z=v[0],v[1],v[2]
        nx=m[0]*x+m[4]*y+m[8]*z+m[12]
        ny=m[1]*x+m[5]*y+m[9]*z+m[13]
        nz=m[2]*x+m[6]*y+m[10]*z+m[14]
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
# .meshes 地形解析（修复镜像：翻转 X 和 Z）
# ============================================================
def parse_meshes_to_obj_data(meshes_file, log_entry):
    if not HAS_MESHES or not HAS_LZ4: return [],[]
    
    log_entry['terrain_decode_start'] = datetime.now().isoformat()
    
    with open(meshes_file,'rb') as f: data=f.read()
    if data[0:4]!=b'LVL0':
        log_entry['terrain_error'] = "不是有效的 LVL0 文件"
        return [],[]
    
    file_version=struct.unpack_from('<I',data,0x04)[0]
    log_entry['meshes_version'] = file_version
    log_write(f"    .meshes 版本: {file_version}")
    
    lod0_offset=lod0_length=0; geo0_offset=geo0_length=0; metr_offset=metr_length=0
    for i in range(data[0x08]):
        base=0x08+4+i*12
        name=data[base:base+4].rstrip(b'\x00').decode('ascii',errors='ignore')
        seg_offset=struct.unpack_from('<I',data,base+4)[0]; seg_length=struct.unpack_from('<I',data,base+8)[0]
        if name=='LOD0': lod0_offset,lod0_length=seg_offset,seg_length
        elif name=='GEO0': geo0_offset,geo0_length=seg_offset,seg_length
        elif name=='METR': metr_offset,metr_length=seg_offset,seg_length
    
    if lod0_length==0:
        log_entry['terrain_error'] = "找不到 LOD0 段"
        return [],[]
    
    compressed=data[lod0_offset:lod0_offset+lod0_length]
    decompressed=lz4.block.decompress(compressed,uncompressed_size=0xC00000)
    log_entry['decompressed_size'] = len(decompressed)
    
    geo_data=data[geo0_offset:geo0_offset+geo0_length] if (file_version>=57 and geo0_length>0) else None
    metr_data=data[metr_offset:metr_offset+metr_length] if (file_version>=55 and metr_length>0) else None
    
    try: 
        result,segments=parse_and_split(decompressed,file_version,metr_data,geo_data)
        log_entry['terrain_parse_success'] = True
    except Exception as e:
        log_entry['terrain_error'] = str(e)
        log_write(f"    地形解析失败: {e}")
        return [],[]
    
    all_verts=[]; all_faces=[]; v_offset=0
    patch_count = 0
    
    for section in ['terrain','skirts','occluder']:
        for chunk in result.get(section,[]):
            if chunk.get('ib_raw') and chunk.get('patches'):
                verts = chunk.get('verts', [])
                ib_raw = chunk.get('ib_raw', b'')
                patches = chunk.get('patches', [])
                terrain_patches = [p for p in patches if p['array'] == 'A']
                patch_count += len(terrain_patches)
                
                if not verts or not ib_raw or not terrain_patches:
                    continue
                
                base_v = len(all_verts)
                all_verts_needed = []
                vert_indices = {}
                new_idx = 0
                
                for patch in terrain_patches:
                    vs = patch['vert_start']
                    ve = patch['vert_end']
                    for vi in range(vs, ve):
                        if vi not in vert_indices:
                            vert_indices[vi] = new_idx
                            pos = verts[vi].get('pos', (0, 0, 0))
                            all_verts_needed.append((-pos[0], pos[1], -pos[2]))
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
                
                all_verts.extend(all_verts_needed)
                v_offset += len(all_verts_needed)
                
            elif chunk.get('verts') and chunk.get('indices'):
                verts = chunk.get('verts', [])
                indices = chunk.get('indices', [])
                if not verts or not indices: continue
                base_v = len(all_verts)
                for v in verts:
                    pos=v.get('pos',(0,0,0))
                    all_verts.append((-pos[0], pos[1], -pos[2]))
                for i in range(0,len(indices),3):
                    if i+2<len(indices): all_faces.append((indices[i]+base_v,indices[i+2]+base_v,indices[i+1]+base_v))
                v_offset+=len(verts)
    
    log_entry['terrain_patch_count'] = patch_count
    log_entry['terrain_vertices'] = len(all_verts)
    log_entry['terrain_faces'] = len(all_faces)
    log_entry['terrain_decode_end'] = datetime.now().isoformat()
    
    return all_verts,all_faces

# ============================================================
# .mesh 模型解析
# ============================================================
def parse_mesh_file(mesh_path, log_entry=None):
    if not HAS_MESH:
        return [], []
    
    try:
        with open(mesh_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        if log_entry:
            log_entry['error'] = f"读取失败: {e}"
        return [], []
    
    if len(data) < 4:
        if log_entry:
            log_entry['error'] = "文件太小"
        return [], []
    
    header = data[:4]
    version = HEADER_VERSION_MAP.get(header)
    if version is None:
        if log_entry:
            log_entry['error'] = f"未知头 {header.hex()}"
        return [], []
    
    handler = _mesh_handlers.get(header)
    if handler is None:
        if log_entry:
            log_entry['error'] = f"无处理器"
        return [], []
    
    try:
        filename = os.path.basename(mesh_path)
        
        if header == b'\x17\x00\x00\x00':
            result = handler(data, mesh_path, filename, version, False, True)
        elif header == b'\x1a\x00\x00\x00':
            result = handler(data, mesh_path, filename, version, True)
        elif header == b'\x1c\x00\x00\x00':
            result = handler(data, mesh_path, filename, version, True)
        elif header == b'\x1e\x00\x00\x00':
            result = handler(data, mesh_path, filename, version, True)
        elif header == b'\x1f\x00\x00\x00':
            result = handler(data, mesh_path, filename, version, True)
        elif header == b'\x20\x00\x00\x00':
            result = handler(data, mesh_path, filename, version, True)
        else:
            return [], []
        
        if result and len(result) >= 3:
            verts_raw = result[0]
            faces_raw = result[2]
            if verts_raw and faces_raw:
                verts = [(v[0], v[1], v[2]) for v in verts_raw]
                faces = [(f[0], f[1], f[2]) for f in faces_raw]
                if log_entry:
                    log_entry['vertices'] = len(verts)
                    log_entry['faces'] = len(faces)
                    log_entry['success'] = True
                return verts, faces
    except Exception as e:
        if log_entry:
            log_entry['error'] = str(e)
        pass
    
    return [], []

# ============================================================
# 调用单个转换.py 生成 JSON
# ============================================================
def convert_bin_to_json(bin_path, output_dir, log_entry):
    converter = os.path.join(SCRIPT_DIR, '单个转换.py')
    if not os.path.exists(converter):
        log_entry['error'] = "未找到 单个转换.py"
        return None
    
    json_path = os.path.join(output_dir, os.path.basename(bin_path) + '.json')
    if os.path.exists(json_path):
        log_entry['json_path'] = json_path
        log_entry['json_exists'] = True
        return json_path
    
    log_write(f"   ⏳ 转换 bin → JSON ...")
    result = subprocess.run(
        [sys.executable, converter, bin_path],
        capture_output=True, text=True, timeout=600,
        cwd=output_dir
    )
    
    if os.path.exists(json_path):
        log_entry['json_path'] = json_path
        log_entry['json_created'] = True
        return json_path
    
    alt_path = bin_path + '.json'
    if os.path.exists(alt_path):
        shutil.move(alt_path, json_path)
        log_entry['json_path'] = json_path
        log_entry['json_moved'] = True
        return json_path
    
    log_entry['error'] = "JSON 生成失败"
    return None

# ============================================================
# 核心：resourceName 提取
# ============================================================
def extract_resource_name_from_cls_data(cls_data):
    if not isinstance(cls_data, dict):
        return None
    
    for key, value in cls_data.items():
        key_lower = key.lower()
        if 'resourcename' in key_lower:
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
                    coords = (float(rf[12]), float(rf[13]), float(rf[14]))
                    return coords, rf
            elif isinstance(value, list) and len(value) >= 16:
                coords = (float(value[12]), float(value[13]), float(value[14]))
                return coords, value
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

def select_marker_categories():
    print("\n" + "=" * 55)
    print("   标记分类选择（输入序号切换，回车完成）")
    print("=" * 55)
    print()
    
    categories = list(MARKER_CATEGORIES.keys())
    for i, cat in enumerate(categories, 1):
        status = "✅" if MARKER_CATEGORIES[cat]['enabled'] else "❌"
        print(f"  {i:2}. {status} {cat}")
    
    print()
    print("  0. 全部启用")
    print("  a. 全部禁用")
    print()
    
    while True:
        choice = input("请输入序号 (1-14, 0, a，回车完成): ").strip()
        if choice == '':
            break
        elif choice == '0':
            for cat in categories:
                MARKER_CATEGORIES[cat]['enabled'] = True
            print("✅ 已启用所有标记分类")
        elif choice.lower() == 'a':
            for cat in categories:
                MARKER_CATEGORIES[cat]['enabled'] = False
            print("❌ 已禁用所有标记分类")
        elif choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(categories):
                cat = categories[idx-1]
                MARKER_CATEGORIES[cat]['enabled'] = not MARKER_CATEGORIES[cat]['enabled']
                status = "✅" if MARKER_CATEGORIES[cat]['enabled'] else "❌"
                print(f"  {idx:2}. {status} {cat}")
            else:
                print("❌ 无效序号")
        else:
            print("❌ 无效输入")
    
    enabled = [cat for cat in categories if MARKER_CATEGORIES[cat]['enabled']]
    print(f"\n将导出标记: {', '.join(enabled) if enabled else '无'}")
    return enabled

# ============================================================
# 主导出
# ============================================================
def export_map(map_folder, mesh_folder, export_markers=True, enabled_categories=None):
    start_time = time.time()
    map_name = os.path.basename(map_folder.rstrip('/\\'))
    
    # 创建输出目录
    work_dir = os.path.join(map_folder, f"{map_name}_export")
    os.makedirs(work_dir, exist_ok=True)
    
    # 初始化日志
    log_path = os.path.join(work_dir, f"{map_name}_export.log")
    log_init()
    log_write(f"地图名称: {map_name}")
    log_write(f"地图文件夹: {map_folder}")
    log_write(f"Mesh 文件夹: {mesh_folder}")
    log_write(f"输出目录: {work_dir}")
    log_write(f"导出标记小球: {'是' if export_markers else '否'}")
    if export_markers and enabled_categories:
        log_write(f"标记分类: {', '.join(enabled_categories)}")
    log_write("")
    
    # 查找 bin 文件
    bin_file = os.path.join(map_folder, 'Objects.level.bin')
    if not os.path.exists(bin_file):
        bfs = [f for f in os.listdir(map_folder) if f.endswith('.bin') and not f.endswith('.meshes')]
        if bfs: 
            bin_file = os.path.join(map_folder, bfs[0])
        else: 
            log_write("❌ 未找到 .bin 文件")
            log_save(log_path)
            return
    
    # 查找 meshes 文件
    meshes_file = None
    for f in os.listdir(map_folder):
        if f.endswith('.meshes'):
            meshes_file = os.path.join(map_folder, f)
            break
    
    obj_path = os.path.join(work_dir, f"{map_name}.obj")
    mtl_path = os.path.join(work_dir, f"{map_name}.mtl")
    
    # 日志条目
    export_log = {
        'map_name': map_name,
        'start_time': datetime.now().isoformat(),
        'bin_file': os.path.basename(bin_file),
        'meshes_file': os.path.basename(meshes_file) if meshes_file else None
    }
    
    # === 1. bin → JSON ===
    log_write(f"\n📖 [.bin] {os.path.basename(bin_file)}")
    
    json_log = {}
    json_path = convert_bin_to_json(bin_file, work_dir, json_log)
    export_log['json'] = json_log
    
    if json_path is None: 
        log_write("❌ JSON 生成失败")
        export_log['final_status'] = 'failed'
        export_log['error'] = json_log.get('error', 'JSON 生成失败')
        log_save(log_path)
        return
    
    log_write(f"   📄 读取 JSON...")
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f, object_pairs_hook=OrderedDict)
        export_log['json_read_success'] = True
    except Exception as e:
        log_write(f"   ❌ JSON 读取失败: {e}")
        export_log['final_status'] = 'failed'
        export_log['error'] = f"JSON 读取失败: {e}"
        log_save(log_path)
        return
    
    # === 2. 提取 LevelMesh 节点 ===
    log_write(f"   🔍 提取 LevelMesh 节点...")
    level_meshes = find_all_levelmesh_with_resources(json_data)
    
    unique_resources = set(lm['resource_name'] for lm in level_meshes)
    export_log['levelmesh_total'] = len(level_meshes)
    export_log['unique_resources'] = len(unique_resources)
    log_write(f"   找到 {len(level_meshes)} 个 LevelMesh 实例, {len(unique_resources)} 种资源")
    
    if level_meshes:
        for lm in list(level_meshes)[:10]:
            log_write(f"      {lm['resource_name']} @ ({lm['coords'][0]:.1f}, {lm['coords'][1]:.1f}, {lm['coords'][2]:.1f})")
        if len(level_meshes) > 10:
            log_write(f"      ... 共 {len(level_meshes)} 个实例")
    
    # === 3. 提取其他标记 ===
    markers = []
    markers_by_category = {cat: [] for cat in MARKER_CATEGORIES}
    
    if export_markers:
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
                    category = get_marker_category(cls_name)
                    marker = {
                        'name': node_name,
                        'class': cls_name,
                        'x': coords[0], 'y': coords[1], 'z': coords[2],
                    }
                    
                    if category:
                        markers_by_category[category].append(marker)
                    else:
                        if '其他' not in markers_by_category:
                            markers_by_category['其他'] = []
                        markers_by_category['其他'].append(marker)
        
        for cat in enabled_categories or []:
            if cat in markers_by_category:
                for m in markers_by_category[cat]:
                    m['color'] = MARKER_CATEGORIES.get(cat, {}).get('color', DEFAULT_COLOR)
                    markers.append(m)
        
        export_log['markers_total'] = len(markers)
        export_log['markers_by_category'] = {cat: len(markers_by_category[cat]) for cat in markers_by_category}
        log_write(f"   标记点: {len(markers)} 个 (已过滤)")
    
    # === 4. 地形 .meshes ===
    terrain_verts, terrain_faces = [], []
    terrain_log = {}
    
    if meshes_file and os.path.exists(meshes_file):
        log_write(f"\n📖 [.meshes] {os.path.basename(meshes_file)}")
        terrain_verts, terrain_faces = parse_meshes_to_obj_data(meshes_file, terrain_log)
        export_log['terrain'] = terrain_log
        log_write(f"   地形: {len(terrain_verts)} 顶点, {len(terrain_faces)} 三角形")
    else:
        log_write(f"\n📖 [.meshes] 未找到 .meshes 文件")
        export_log['terrain'] = {'error': '未找到 .meshes 文件'}
    
    # === 5. 模型 .mesh 加载 ===
    mesh_models = []
    loaded_resources = set()
    models_log = []
    
    if HAS_MESH and os.path.isdir(mesh_folder) and level_meshes:
        log_write(f"\n📖 [.mesh] 加载模型 (目录: {mesh_folder})")
        mesh_files_list = [f for f in os.listdir(mesh_folder) if f.endswith('.mesh')]
        log_write(f"   目录中 .mesh 文件: {len(mesh_files_list)} 个")
        log_write(f"   正在解析...")
        
        success_count = 0
        fail_count = 0
        missing_count = 0
        
        for idx, lm in enumerate(level_meshes):
            res = lm['resource_name']
            
            mesh_log = {
                'resource_name': res,
                'position': lm['coords']
            }
            
            if res in loaded_resources:
                mesh_log['status'] = 'duplicate_skipped'
                models_log.append(mesh_log)
                continue
            
            mesh_file = find_mesh_file(mesh_folder, res)
            
            if mesh_file and os.path.exists(mesh_file):
                mesh_log['mesh_file'] = os.path.basename(mesh_file)
                parse_log = {}
                verts, faces = parse_mesh_file(mesh_file, parse_log)
                mesh_log['parse'] = parse_log
                
                if verts and faces:
                    mesh_models.append({
                        'resource': res,
                        'verts': verts,
                        'faces': faces,
                        'instances': []
                    })
                    loaded_resources.add(res)
                    success_count += 1
                    mesh_log['status'] = 'success'
                    # 记录到成功列表（用于日志）
                    log_model_success(res, len(verts), len(faces), os.path.basename(mesh_file))
                    # 每50个打印一次进度
                    if success_count % 50 == 0:
                        log_write(f"      已解析 {success_count}/{len(unique_resources)} 种模型...")
                else:
                    fail_count += 1
                    mesh_log['status'] = 'failed'
                    log_model_failed(res, parse_log.get('error', '未知错误'))
            else:
                missing_count += 1
                mesh_log['status'] = 'missing'
                mesh_log['missing_file'] = f"{res}.mesh"
                log_model_missing(res, f"{res}.mesh")
            
            models_log.append(mesh_log)
        
        # 关联实例
        model_map = {m['resource']: m for m in mesh_models}
        for lm in level_meshes:
            if lm['resource_name'] in model_map:
                model_map[lm['resource_name']]['instances'].append(lm)
        
        total_instances = sum(len(m['instances']) for m in mesh_models)
        export_log['models'] = {
            'success_count': success_count,
            'fail_count': fail_count,
            'missing_count': missing_count,
            'total_instances': total_instances,
            'details': models_log
        }
        
        log_write(f"\n   统计: 成功 {success_count} 种模型, {total_instances} 个实例")
        if fail_count > 0:
            log_write(f"   解析失败: {fail_count} 种")
        if missing_count > 0:
            log_write(f"   文件缺失: {missing_count} 种")
    else:
        export_log['models'] = {'error': 'mesh 解析不可用或没有模型数据'}
    
    # === 6. 写入 OBJ ===
    log_write(f"\n📝 导出 OBJ...")
    
    with open(mtl_path, 'w', encoding='utf-8') as mf:
        mf.write("newmtl terrain\nKd 0.45 0.42 0.38\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n\n")
        mf.write("newmtl model\nKd 0.75 0.73 0.68\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n\n")
        for cat_name, cat_info in MARKER_CATEGORIES.items():
            color = cat_info['color']
            mf.write(f"newmtl marker_{cat_name}\nKd {color[0]:.4f} {color[1]:.4f} {color[2]:.4f}\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n\n")
        mf.write("newmtl default\nKd 0.5 0.5 0.5\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n")
    
    global_v = 1
    
    with open(obj_path, 'w', encoding='utf-8') as f:
        f.write(f"# Sky Map: {map_name}\n")
        f.write(f"# Exported by map_exporter v17\n")
        f.write(f"# Export markers: {export_markers}\n")
        f.write(f"mtllib {map_name}.mtl\n\n")
        
        if terrain_verts:
            f.write(f"o Terrain\nusemtl terrain\n")
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
            markers_by_cat = {}
            for m in markers:
                cat = get_marker_category(m['class'])
                if not cat:
                    cat = '其他'
                if cat not in markers_by_cat:
                    markers_by_cat[cat] = []
                markers_by_cat[cat].append(m)
            
            for cat_name, nodes in markers_by_cat.items():
                if cat_name in MARKER_CATEGORIES:
                    color_name = f"marker_{cat_name}"
                else:
                    color_name = 'default'
                
                f.write(f"o {cat_name}_Markers\nusemtl {color_name}\n")
                f.write(f"# {len(nodes)} 个 {cat_name} 标记点\n")
                for node in nodes:
                    verts, faces = make_sphere_verts(node['x'], node['y'], node['z'], 0.5)
                    for v in verts:
                        f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
                    for tri in faces:
                        f.write(f"f {tri[0]+global_v} {tri[1]+global_v} {tri[2]+global_v}\n")
                    global_v += len(verts)
                f.write("\n")
    
    elapsed = time.time() - start_time
    export_log['end_time'] = datetime.now().isoformat()
    export_log['elapsed_seconds'] = round(elapsed, 2)
    export_log['final_status'] = 'success'
    export_log['output_obj'] = obj_path
    export_log['output_mtl'] = mtl_path
    export_log['total_vertices'] = global_v - 1
    
    # 保存日志 JSON
    json_log_path = os.path.join(work_dir, f"{map_name}_export.json")
    with open(json_log_path, 'w', encoding='utf-8') as f:
        json.dump(export_log, f, ensure_ascii=False, indent=2)
    
    # 保存日志 TXT
    log_write(f"\n✅ 完成!")
    log_write(f"   地形: {len(terrain_verts):,} 顶点, {len(terrain_faces):,} 三角形")
    log_write(f"   模型: {len(mesh_models)} 种, {total_instances} 实例")
    log_write(f"   标记: {len(markers)} {'(已导出)' if export_markers else '(已禁用)'}")
    log_write(f"   OBJ: {obj_path}")
    log_write(f"   耗时: {elapsed:.1f} 秒")
    log_write(f"\n📄 文本日志: {log_path}")
    log_write(f"📋 JSON日志: {json_log_path}")
    
    log_save(log_path)
    return work_dir


def main():
    print("=" * 55)
    print("   ☁️ 地图可视化导出 v17 (详细日志)")
    print("=" * 55)
    print()
    print("标记分类说明：")
    print("  传送门、冥想区、NPC、检查点、标记点、边界、风力、水体、")
    print("  时间轴、启用开关、粒子生成、音效、光源、火焰")
    print()
    
    while True:
        path = input("地图文件夹: ").strip().strip('"').strip("'")
        if path and os.path.isdir(path):
            break
        print("❌ 无效，请重新输入")
    
    mesh_dir = input("mesh 文件夹路径 (默认: 脚本同目录/mesh): ").strip().strip('"').strip("'")
    if not mesh_dir:
        mesh_dir = os.path.join(SCRIPT_DIR, 'mesh')
    
    if not os.path.isdir(mesh_dir):
        print(f"⚠️ mesh 目录不存在: {mesh_dir}")
        confirm = input("是否继续? (y/n): ")
        if confirm.lower() != 'y':
            return
    
    export_markers_input = input("是否导出标记小球? (y/n, 默认 y): ").strip().lower()
    export_markers = export_markers_input != 'n'
    
    enabled_categories = None
    if export_markers:
        enabled_categories = select_marker_categories()
    
    export_map(path, mesh_dir, export_markers, enabled_categories)
    input("\n按回车退出...")


if __name__ == '__main__':
    main()