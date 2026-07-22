#!/usr/bin/env python3
# [Upstream + Modified] launcher — single map CLI export
# Original authors: checion (雨人), Heriel (落秋), potato
# License: MIT (see NOTICE)
# Modified by lingyunalingyun: 添加 output_dir 参数支持
"""
地图可视化导出工具 v18
"""

import sys
import os
import json
import struct
import math
import io
import re
import importlib.util
import subprocess
import shutil
import time
import hashlib
from datetime import datetime
from collections import OrderedDict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# ============================================================
# 日志记录
# ============================================================
_log_lines = []
_log_models_success = []
_log_models_failed = []
_log_models_missing = []
_color_map = {}  # 存储类名对应的颜色
_color_list = []  # 用于输出颜色映射文件

def log_init():
    global _log_lines, _log_models_success, _log_models_failed, _log_models_missing, _color_map, _color_list
    _log_lines = []
    _log_models_success = []
    _log_models_failed = []
    _log_models_missing = []
    _color_map = {}
    _color_list = []
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

def get_color_from_classname(cls_name):
    """根据类名生成稳定的颜色（使用哈希值）"""
    if cls_name in _color_map:
        return _color_map[cls_name]
    
    # 使用 MD5 哈希生成颜色
    hash_obj = hashlib.md5(cls_name.encode('utf-8'))
    hash_bytes = hash_obj.digest()
    
    # 取前3个字节作为 RGB，确保颜色明亮（值在 0.3-1.0 之间）
    r = 0.3 + (hash_bytes[0] / 255.0) * 0.7
    g = 0.3 + (hash_bytes[1] / 255.0) * 0.7
    b = 0.3 + (hash_bytes[2] / 255.0) * 0.7
    
    color = (round(r, 4), round(g, 4), round(b, 4))
    _color_map[cls_name] = color
    _color_list.append(f"{cls_name} -> ({color[0]:.4f}, {color[1]:.4f}, {color[2]:.4f})")
    return color

def save_color_map(color_path):
    """保存颜色映射文件"""
    try:
        with open(color_path, 'w', encoding='utf-8') as f:
            f.write("# 类名 -> RGB颜色映射表\n")
            f.write(f"# 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("#" + "=" * 78 + "\n\n")
            for line in sorted(_color_list):
                f.write(line + "\n")
        return True
    except Exception as e:
        print(f"❌ 保存颜色映射失败: {e}")
        return False

def log_save(filepath):
    global _log_lines, _log_models_success, _log_models_failed, _log_models_missing
    
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
# 颜色
# ============================================================
CLASS_COLORS = {
    'LevelMesh':(0.7,0.7,0.7),
}
DEFAULT_COLOR = (0.5, 0.5, 0.5)

def get_class_color(cls_name):
    if cls_name in CLASS_COLORS:
        return CLASS_COLORS[cls_name]
    return get_color_from_classname(cls_name)

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
_global_mesh_index = None

_VARIANT_RE = re.compile(r'_(StripAnim|CompOcc|ZipPos|ZipUvs|StripNorm|StripUv13|NoOcc|NoCollision|CopyFrameDelay).*$')

def _strip_variant(name):
    return _VARIANT_RE.sub('', name)

def _build_global_mesh_index():
    global _global_mesh_index
    if _global_mesh_index is not None:
        return
    _global_mesh_index = {}
    assets_dir = os.environ.get('SKY_ASSETS_DIR', '')
    if not assets_dir:
        for p in sys.path + [os.getcwd()]:
            candidate = os.path.join(p, '..', '..', '..', '..')
            candidate = os.path.normpath(candidate)
            if os.path.isdir(os.path.join(candidate, 'meshes')):
                assets_dir = candidate
                break
    if not assets_dir:
        return
    for pkg in os.listdir(assets_dir):
        mdir = os.path.join(assets_dir, pkg, 'Data', 'Meshes', 'Bin')
        if not os.path.isdir(mdir):
            continue
        for f in os.listdir(mdir):
            if f.endswith('.mesh'):
                name = f[:-5]
                full_path = os.path.join(mdir, f)
                if name not in _global_mesh_index:
                    _global_mesh_index[name] = full_path
                base = _strip_variant(name)
                if base != name and base not in _global_mesh_index:
                    _global_mesh_index[base] = full_path
    log_write(f"[OK] global mesh index: {len(_global_mesh_index)} entries")


def find_mesh_file(mesh_folder, resource_name):
    if os.path.isdir(mesh_folder):
        exact_path = os.path.join(mesh_folder, f"{resource_name}.mesh")
        if os.path.exists(exact_path):
            return exact_path
        try:
            for f in os.listdir(mesh_folder):
                if f.endswith('.mesh') and resource_name in f:
                    return os.path.join(mesh_folder, f)
        except:
            pass
    if _global_mesh_index and resource_name in _global_mesh_index:
        return _global_mesh_index[resource_name]
    return None

from backends import MATERIAL_COLORS, MATERIAL_COLOR_DEFAULT

def _blend_terrain_color(materials, ao_brightness):
    r, g, b = 0.0, 0.0, 0.0
    total_w = 0
    for mid, mw in materials:
        if mw <= 0:
            continue
        mc = MATERIAL_COLORS.get(mid, MATERIAL_COLOR_DEFAULT)
        r += mc[0] * mw
        g += mc[1] * mw
        b += mc[2] * mw
        total_w += mw
    if total_w > 0:
        r /= total_w
        g /= total_w
        b /= total_w
    else:
        r, g, b = MATERIAL_COLOR_DEFAULT
    ao = max(ao_brightness / 255.0, 0.3)
    return (r * ao, g * ao, b * ao)


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
    
    all_verts=[]; all_faces=[]; all_colors=[]; v_offset=0
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
                all_colors_needed = []
                vert_indices = {}
                new_idx = 0

                for patch in terrain_patches:
                    vs = patch['vert_start']
                    ve = patch['vert_end']
                    for vi in range(vs, ve):
                        if vi not in vert_indices:
                            vert_indices[vi] = new_idx
                            pos = verts[vi].get('pos', (0, 0, 0))
                            vc = verts[vi].get('v_color', (255, 255, 255, 255))
                            mats = verts[vi].get('materials', [])
                            ao = max(vc[0], vc[1], vc[2])
                            color = _blend_terrain_color(mats, ao)
                            all_verts_needed.append((-pos[0], pos[1], -pos[2]))
                            all_colors_needed.append(color)
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
                all_colors.extend(all_colors_needed)
                v_offset += len(all_verts_needed)

            elif chunk.get('verts') and chunk.get('indices'):
                verts = chunk.get('verts', [])
                indices = chunk.get('indices', [])
                if not verts or not indices: continue
                base_v = len(all_verts)
                for v in verts:
                    pos=v.get('pos',(0,0,0))
                    vc = v.get('v_color', (255, 255, 255, 255))
                    mats = v.get('materials', [])
                    ao = max(vc[0], vc[1], vc[2])
                    color = _blend_terrain_color(mats, ao)
                    all_verts.append((-pos[0], pos[1], -pos[2]))
                    all_colors.append(color)
                for i in range(0,len(indices),3):
                    if i+2<len(indices): all_faces.append((indices[i]+base_v,indices[i+2]+base_v,indices[i+1]+base_v))
                v_offset+=len(verts)

    log_entry['terrain_patch_count'] = patch_count
    log_entry['terrain_vertices'] = len(all_verts)
    log_entry['terrain_faces'] = len(all_faces)
    log_entry['terrain_decode_end'] = datetime.now().isoformat()

    return all_verts, all_faces, all_colors

# ============================================================
# .mesh 模型解析
# ============================================================
_sky_mesh_mod = None
try:
    _sky_mesh_path = os.path.join(SCRIPT_DIR, 'sky_mesh_to_obj.py')
    if not os.path.exists(_sky_mesh_path):
        _sky_mesh_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       '..', '..', '..', 'sky_mesh_to_obj.py')
        _sky_mesh_path = os.path.normpath(_sky_mesh_path)
    if not os.path.exists(_sky_mesh_path):
        _sky_mesh_path = r"F:\编程文件\编程计划\Sky逆向\sky_mesh_to_obj.py"
    if os.path.exists(_sky_mesh_path):
        _spec2 = importlib.util.spec_from_file_location("sky_mesh_to_obj", _sky_mesh_path)
        _sky_mesh_mod = importlib.util.module_from_spec(_spec2)
        _spec2.loader.exec_module(_sky_mesh_mod)
        log_write("[OK] sky_mesh_to_obj.py (ZipPos修复版)")
except Exception as e:
    log_write(f"[WARN] sky_mesh_to_obj.py 导入失败: {e}")


def parse_mesh_file(mesh_path, log_entry=None):
    try:
        with open(mesh_path, 'rb') as f:
            data = f.read()
    except Exception as e:
        if log_entry is not None:
            log_entry['error'] = f"读取失败: {e}"
        return [], []

    if len(data) < 4:
        if log_entry is not None:
            log_entry['error'] = "文件太小"
        return [], []

    hdr_ver = struct.unpack_from("<I", data, 0)[0]

    # v0x1F/v0x20 优先用修好的 sky_mesh_to_obj（正确处理 ZipPos）
    if hdr_ver in (0x1F, 0x20) and _sky_mesh_mod:
        try:
            payload, bones, _ = _sky_mesh_mod.parse_container(data)
            verts, uvs, faces = _sky_mesh_mod.parse_mesh_payload(
                payload, bones, os.path.basename(mesh_path))
            if verts and faces:
                if log_entry is not None:
                    log_entry['vertices'] = len(verts)
                    log_entry['faces'] = len(faces)
                    log_entry['success'] = True
                    log_entry['parser'] = 'sky_mesh_to_obj'
                return list(verts), list(faces)
        except Exception as e:
            if log_entry is not None:
                log_entry['sky_mesh_error'] = str(e)

    # 回退到原有 meshtoobj.py handler
    if not HAS_MESH:
        return [], []

    header = data[:4]
    version = HEADER_VERSION_MAP.get(header)
    if version is None:
        if log_entry is not None:
            log_entry['error'] = f"未知头 {header.hex()}"
        return [], []

    handler = _mesh_handlers.get(header)
    if handler is None:
        if log_entry is not None:
            log_entry['error'] = f"无处理器"
        return [], []

    try:
        filename = os.path.basename(mesh_path)

        if header == b'\x17\x00\x00\x00':
            result = handler(data, mesh_path, filename, version, False, True)
        else:
            result = handler(data, mesh_path, filename, version, True)

        if result and len(result) >= 3:
            verts_raw = result[0]
            faces_raw = result[2]
            if verts_raw and faces_raw:
                verts = [(v[0], v[1], v[2]) for v in verts_raw]
                faces = [(f[0], f[1], f[2]) for f in faces_raw]
                if log_entry is not None:
                    log_entry['vertices'] = len(verts)
                    log_entry['faces'] = len(faces)
                    log_entry['success'] = True
                    log_entry['parser'] = 'meshtoobj'
                return verts, faces
    except Exception as e:
        if log_entry is not None:
            log_entry['error'] = str(e)

    return [], []

# ============================================================
# 调用bintojson.py 生成 JSON
# ============================================================
def convert_bin_to_json(bin_path, output_dir, log_entry):
    converter = os.path.join(SCRIPT_DIR, 'bintojson.py')
    if not os.path.exists(converter):
        log_entry['error'] = "未找到 bintojson.py"
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
# 主导出
# ============================================================
def export_map(map_folder, mesh_folder, export_markers=True, enabled_classes=None, output_dir=None):
    _build_global_mesh_index()
    start_time = time.time()
    map_name = os.path.basename(map_folder.rstrip('/\\'))

    # 创建输出目录
    if output_dir:
        work_dir = os.path.join(output_dir, f"{map_name}_export")
    else:
        work_dir = os.path.join(map_folder, f"{map_name}_export")
    os.makedirs(work_dir, exist_ok=True)
    
    # 初始化日志
    log_path = os.path.join(work_dir, f"{map_name}_export.log")
    color_path = os.path.join(work_dir, f"{map_name}_colors.txt")
    log_init()
    log_write(f"地图名称: {map_name}")
    log_write(f"地图文件夹: {map_folder}")
    log_write(f"Mesh 文件夹: {mesh_folder}")
    log_write(f"输出目录: {work_dir}")
    log_write(f"导出标记小球: {'是' if export_markers else '否'}")
    if export_markers and enabled_classes:
        log_write(f"标记类名数量: {len(enabled_classes)}")
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
    
    # === 3. 提取标记 ===
    markers = []
    if export_markers:
        log_write(f"   🔍 提取标记节点...")
        all_markers = find_all_markers(json_data)
        log_write(f"   找到 {len(all_markers)} 个标记节点")
        
        if enabled_classes:
            enabled_set = set(enabled_classes)
            markers = [m for m in all_markers if m['class'] in enabled_set]
            log_write(f"   已过滤: {len(markers)} 个标记点 ({len(enabled_classes)} 个类名)")
        else:
            markers = all_markers
            log_write(f"   标记点: {len(markers)} 个 (全部)")
    
    # === 4. 地形 .meshes ===
    terrain_verts, terrain_faces, terrain_colors = [], [], []
    terrain_log = {}

    if meshes_file and os.path.exists(meshes_file):
        log_write(f"\n📖 [.meshes] {os.path.basename(meshes_file)}")
        terrain_verts, terrain_faces, terrain_colors = parse_meshes_to_obj_data(meshes_file, terrain_log)
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
                    log_model_success(res, len(verts), len(faces), os.path.basename(mesh_file))
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
        total_instances = 0
        export_log['models'] = {'error': 'mesh 解析不可用或没有模型数据'}
    
    # === 6. 写入 OBJ ===
    log_write(f"\n📝 导出 OBJ...")
    
    # 收集所有需要写入 MTL 的材质（标记类名 + 地形 + 模型）
    marker_classes = set(m['class'] for m in markers) if markers else set()
    
    with open(mtl_path, 'w', encoding='utf-8') as mf:
        mf.write("# Sky Map Materials (Auto-generated colors)\n")
        mf.write("# Colors are generated from class name hash\n\n")
        mf.write("newmtl terrain\nKd 0.45 0.42 0.38\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n\n")
        mf.write("newmtl model\nKd 0.75 0.73 0.68\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n\n")
        
        # 为每个标记类名生成材质
        for cls_name in sorted(marker_classes):
            color = get_class_color(cls_name)
            # 材质名使用类名，但需要处理特殊字符
            safe_name = cls_name.replace(' ', '_').replace('(', '_').replace(')', '_').replace('>', '_').replace('<', '_')
            mf.write(f"newmtl {safe_name}\nKd {color[0]:.4f} {color[1]:.4f} {color[2]:.4f}\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n\n")
    
    global_v = 1
    
    with open(obj_path, 'w', encoding='utf-8') as f:
        f.write(f"# Sky Map: {map_name}\n")
        f.write(f"# Exported by map_exporter v18\n")
        f.write(f"# Export markers: {export_markers}\n")
        f.write(f"mtllib {map_name}.mtl\n\n")
        
        # 地形（带顶点颜色）
        if terrain_verts:
            f.write(f"o Terrain\nusemtl terrain\n")
            has_colors = len(terrain_colors) == len(terrain_verts)
            for i, v in enumerate(terrain_verts):
                if has_colors:
                    c = terrain_colors[i]
                    f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f} {c[0]:.4f} {c[1]:.4f} {c[2]:.4f}\n")
                else:
                    f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            for tri in terrain_faces:
                f.write(f"f {tri[0]+global_v} {tri[1]+global_v} {tri[2]+global_v}\n")
            global_v += len(terrain_verts)
            f.write("\n")
        
        # 模型实例
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
        
        # 标记小球（按类名分组）
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
    
    # 保存颜色映射文件
    save_color_map(color_path)
    
    elapsed = time.time() - start_time
    export_log['end_time'] = datetime.now().isoformat()
    export_log['elapsed_seconds'] = round(elapsed, 2)
    export_log['final_status'] = 'success'
    export_log['output_obj'] = obj_path
    export_log['output_mtl'] = mtl_path
    export_log['total_vertices'] = global_v - 1
    export_log['markers_count'] = len(markers)
    export_log['color_count'] = len(_color_map)
    
    # 保存日志 JSON
    json_log_path = os.path.join(work_dir, f"{map_name}_export.json")
    with open(json_log_path, 'w', encoding='utf-8') as f:
        json.dump(export_log, f, ensure_ascii=False, indent=2)
    
    # 保存日志 TXT
    log_write(f"\n✅ 完成!")
    log_write(f"   地形: {len(terrain_verts):,} 顶点, {len(terrain_faces):,} 三角形")
    log_write(f"   模型: {len(mesh_models)} 种, {total_instances} 实例")
    log_write(f"   标记: {len(markers)} {'(已导出)' if export_markers else '(已禁用)'}")
    log_write(f"   颜色映射: {len(_color_map)} 种颜色")
    log_write(f"   OBJ: {obj_path}")
    log_write(f"   耗时: {elapsed:.1f} 秒")
    log_write(f"\n📄 文本日志: {log_path}")
    log_write(f"📋 JSON日志: {json_log_path}")
    log_write(f"🎨 颜色映射: {color_path}")
    
    log_save(log_path)
    return work_dir


def main():
    print("=" * 55)
    print("   ☁️ 地图可视化导出 v18 (自动生成颜色)")
    print("=" * 55)
    print()
    print("说明：")
    print("  - 标记类名会自动从 JSON 中提取")
    print("  - 每个类名自动生成颜色（基于哈希值）")
    print("  - 可自由选择要导出的类名")
    print("  - 颜色映射表会保存到 .txt 文件中")
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
    
    enabled_classes = None
    if export_markers:
        # 先快速读取 JSON 获取类名列表
        bin_file = os.path.join(path, 'Objects.level.bin')
        if not os.path.exists(bin_file):
            bfs = [f for f in os.listdir(path) if f.endswith('.bin') and not f.endswith('.meshes')]
            if bfs:
                bin_file = os.path.join(path, bfs[0])
        
        if bin_file and os.path.exists(bin_file):
            # 临时读取 JSON 获取类名
            temp_json = bin_file + '.json'
            if not os.path.exists(temp_json):
                # 临时转换
                converter = os.path.join(SCRIPT_DIR, 'bintojson.py')
                if os.path.exists(converter):
                    subprocess.run([sys.executable, converter, bin_file], capture_output=True, cwd=path)
            
            if os.path.exists(temp_json):
                with open(temp_json, 'r', encoding='utf-8') as f:
                    temp_data = json.load(f)
                markers = find_all_markers(temp_data)
                if markers:
                    enabled_classes = select_marker_categories(markers)
                else:
                    print("未找到任何标记节点")
                    enabled_classes = []
            else:
                print("⚠️ 无法读取 JSON 获取类名，将导出所有标记")
                enabled_classes = None
        else:
            print("⚠️ 未找到 .bin 文件")
            enabled_classes = None
    
    export_map(path, mesh_dir, export_markers, enabled_classes)
    input("\n按回车退出...")


if __name__ == '__main__':
    main()