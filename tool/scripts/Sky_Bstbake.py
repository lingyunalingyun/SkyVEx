# [Upstream] SkyBstbake — terrain/meshes parser
# Source: https://github.com/ThatSkyOldServer/SkyBstbake
# Authors: checion (雨人) & Heriel (落秋)
# License: MIT (see NOTICE)
# Modified by lingyunalingyun: 修复 meshoptimizer 参数顺序

import os
import sys
import struct
import argparse
import ctypes
import ctypes.util

try:
    import lz4.block
except ImportError:
    print("[!] 缺少 lz4 库，正在尝试自动安装...")
    os.system(f"{sys.executable} -m pip install lz4")
    import lz4.block

SEGMENT_NAMES = ['Mesh.bin', 'Terrain.bin', 'Cloud.bin', 'Skirt.bin', 'Occluder.bin']
SEGMENT_NAMES_V2 = ['Mesh.bin', 'Terrain.bin', 'Cloud.bin', 'Skirt.bin', 'Occluder.bin', 'METR.bin']
SEGMENT_NAMES_V3 = ['GEO0.bin', 'Mesh.bin', 'Cloud.bin', 'Skirt.bin', 'Occluder.bin', 'METR.bin']

# ==========================================
# Meshoptimizer Python 模块 (Android 原生支持)
# ==========================================
HAS_MESHOPTIMIZER = False
try:
    import meshoptimizer
    HAS_MESHOPTIMIZER = True
    print("[OK] meshoptimizer Python 模块已加载 (Android 原生)")
except ImportError:
    print("[WARN] meshoptimizer 模块未找到，将使用 ctypes 回退")

# ==========================================
# Meshopt 动态库加载 (ctypes 回退)
# ==========================================
_meshopt_lib = None

def _load_meshopt_lib():
    global _meshopt_lib
    if _meshopt_lib is not None:
        return _meshopt_lib
    
    # 获取当前脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    candidates = [
        os.path.join(script_dir, '_meshopt', 'meshopt2.dll'),
        os.path.join(script_dir, 'meshopt2.dll'),
    ]
    found = ctypes.util.find_library('meshopt')
    if found:
        candidates.insert(0, found)
    for name in candidates:
        try:
            if os.path.exists(name):
                _meshopt_lib = ctypes.CDLL(name)
                _meshopt_lib.meshopt_decodeVertexBuffer.restype = ctypes.c_int
                _meshopt_lib.meshopt_decodeVertexBuffer.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint64, ctypes.c_size_t,
                    ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t
                ]
                _meshopt_lib.meshopt_decodeIndexBuffer.restype = ctypes.c_int
                _meshopt_lib.meshopt_decodeIndexBuffer.argtypes = [
                    ctypes.c_void_p, ctypes.c_uint64, ctypes.c_size_t,
                    ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t
                ]
                print(f"  [meshopt] 已加载动态库: {name}")
                return _meshopt_lib
        except OSError:
            continue
    print("  [meshopt] 未找到 meshopt 动态库，meshopt 解压功能不可用")
    _meshopt_lib = False
    return None

# ==========================================
# 基础读取工具
# ==========================================
def read_u8(data, off): return data[off], off + 1
def read_u16(data, off): return struct.unpack_from('<H', data, off)[0], off + 2
def read_u32(data, off): return struct.unpack_from('<I', data, off)[0], off + 4
def read_i32(data, off): return struct.unpack_from('<i', data, off)[0], off + 4
def read_f32(data, off): return struct.unpack_from('<f', data, off)[0], off + 4
def read_bool(data, off): return bool(data[off]), off + 1
def read_vec3(data, off):
    x, y, z = struct.unpack_from('<3f', data, off)
    return (x, y, z), off + 12
def read_string(data, off):
    length, off = read_u32(data, off)
    s = data[off:off + length].decode('utf-8', errors='replace')
    return s, off + length


# ==========================================
# Meshopt 解码器 (优先使用 Python 模块，修复参数顺序)
# ==========================================

def try_decompress_meshopt_vertex(compressed_data, vertex_count, stride):
    """解码顶点缓冲 - 优先使用 meshoptimizer 模块"""
    # 1. 优先使用 Python 模块 (Android/Linux)
    if HAS_MESHOPTIMIZER:
        try:
            # 修正参数顺序：decode_vertex_buffer(count, stride, data)
            result = meshoptimizer.decode_vertex_buffer(vertex_count, stride, compressed_data)
            if result is not None:
                return bytes(result)
        except Exception as e:
            print(f"    [meshoptimizer] 顶点解码失败: {e}")
    
    # 2. 回退到 ctypes (Windows)
    lib = _load_meshopt_lib()
    if not lib:
        print("    [!!] meshopt2.dll 未加载，无法解码顶点缓冲")
        return None
    out_buf = (ctypes.c_uint8 * (vertex_count * stride))()
    in_arr = (ctypes.c_uint8 * len(compressed_data))(*compressed_data)
    ret = lib.meshopt_decodeVertexBuffer(out_buf, vertex_count, stride, in_arr, len(compressed_data))
    if ret == 0:
        return bytes(out_buf)
    return None


def try_decompress_meshopt_index(compressed_data, index_count, index_size=2):
    """解码索引缓冲 - 优先使用 meshoptimizer 模块"""
    # 1. 优先使用 Python 模块 (Android/Linux)
    if HAS_MESHOPTIMIZER:
        try:
            # 修正参数顺序：decode_index_buffer(count, stride, data)
            result = meshoptimizer.decode_index_buffer(index_count, index_size, compressed_data)
            if result is not None:
                return bytes(result)
        except Exception as e:
            print(f"    [meshoptimizer] 索引解码失败: {e}")
    
    # 2. 回退到 ctypes (Windows)
    lib = _load_meshopt_lib()
    if not lib:
        print("    [!!] meshopt2.dll 未加载，无法解码索引缓冲")
        return None
    out_buf = (ctypes.c_uint8 * (index_count * index_size))()
    in_arr = (ctypes.c_uint8 * len(compressed_data))(*compressed_data)
    ret = lib.meshopt_decodeIndexBuffer(out_buf, index_count, index_size, in_arr, len(compressed_data))
    if ret == 0:
        return bytes(out_buf)
    return None


# ==========================================
# METR 段解析
# ==========================================
def parse_metr(data, offset, length):
    """解析 METR (Metrics) 段，固定 64 字节。返回 dict 或 None。"""
    if length < 64:
        print(f"  [METR] 段长度 {length} < 64，跳过")
        return None
    off = offset
    version = struct.unpack_from('<I', data, off)[0]; off += 4
    total_size = struct.unpack_from('<I', data, off)[0]; off += 4
    print(f"  [METR] version={version}, totalSize={total_size}")
    if version != 1 or total_size != 64:
        print(f"  [METR] 校验失败 (期望 version=1, size=64)，清零处理")
        return {'version': 0, 'size': 0, 'raw': b'\x00' * 56}
    raw_metrics = data[off:off + 56]
    return {'version': version, 'size': total_size, 'raw': raw_metrics}


def parse_geo0(geo_data, result, segments):
    """解析 GEO0 段 (v57+ 地形数据)。

      GEO0 格式:
        24B header: 6×u32 (index_bytes, vert_count, a_cnt, b_cnt, c_cnt, vb_comp_size)
        meshopt VB (stride=36): 全局顶点缓冲 (所有地形 patch 共享)
        index buffer: **uint8 字节三元组** (每三角形3字节)
        Array A (a_cnt×56B): 地形 patch 描述符
        Array B (b_cnt×56B): Cloud patch 描述符
        Array C (c_cnt×8B): 元数据( 包含 mat_id 等)

      56B patch:
        u32@0  ib_byte_off  — IB 字节偏移 (指向字节三元组)
        u32@4  vert_start   — 全局 VB 起始顶点索引
        u32@8  patch_id     — 全局 patch 编号
        u32@12 (guid hi16 + ib_byte_len lo16)
                              低16位 = IB 字节长度 (每 patch 固定 756 = 252 tri × 3)
        u8@14  vert_count   — 本 patch 顶点数 (≤187, 适合 uint8 索引)
        u8@15  flags
        f32×6  AABB         — 局部包围盒
        u8×16  未知/填充

        - 读取 IB 为 unsigned __int8* byte triplets: [i0,i1,i2] [i3,i4,i5] ...
        - 每 3 字节 = 1 个三角形, 索引为 patch 本地顶点 (0..vert_count-1)
        - 全局 VB 索引 = vert_start + 本地索引
    """
    if not geo_data or len(geo_data) < 24:
        return

    start_off = 0
    index_bytes, vert_count, array_a_count, array_b_count, array_c_count, vb_comp_size = \
        struct.unpack_from('<6I', geo_data, 0)
    off = 24
    vb_comp_data = geo_data[off:off + vb_comp_size]; off += vb_comp_size
    index_data = geo_data[off:off + index_bytes]; off += index_bytes
    array_ab_raw = geo_data[off:off + 56 * (array_a_count + array_b_count)]
    off += 56 * (array_a_count + array_b_count)
    array_c_raw = geo_data[off:off + 8 * array_c_count]
    off += 8 * array_c_count

    print(f"  [GEO0] verts={vert_count}, index_bytes={index_bytes}, "
          f"tris={index_bytes//3}, "
          f"arrays={array_a_count}/{array_b_count}/{array_c_count}, vb_size={vb_comp_size}")
    if off != len(geo_data):
        print(f"    [!] GEO0 size mismatch: parsed={off}, actual={len(geo_data)}")


    verts = []
    vb_raw = try_decompress_meshopt_vertex(vb_comp_data, vert_count, 36)
    if vb_raw:
        for vi in range(vert_count):
            vo = vi * 36
            x, y, z = struct.unpack_from('<3f', vb_raw, vo)
            nx_b, ny_b, nz_b, _ = struct.unpack_from('<4B', vb_raw, vo + 12)
            nx, ny, nz = (nx_b / 255.0) * 2 - 1, (ny_b / 255.0) * 2 - 1, (nz_b / 255.0) * 2 - 1
            mat_ids = struct.unpack_from('<4B', vb_raw, vo + 16)
            mat_weights = struct.unpack_from('<4B', vb_raw, vo + 20)
            v_color = struct.unpack_from('<4B', vb_raw, vo + 24)
            verts.append({
                'pos': (x, y, z), 'normal': (nx, ny, nz),
                'materials': list(zip(mat_ids, mat_weights)),
                'v_color': v_color
            })
        print(f"      meshopt VB OK ({len(verts)} verts)")
    else:
        print("      meshopt VB FAILED")

    tri_count = index_bytes // 3
    # print(f"      IB OK ({len(index_data)} bytes = {tri_count} triangles @ 3 bytes/tri)")

    patches = []
    for i in range(array_a_count + array_b_count):
        entry = array_ab_raw[i * 56:(i + 1) * 56]
        ib_byte_off = struct.unpack_from('<I', entry, 0)[0]    # IB 字节偏移 (全局)
        vert_start = struct.unpack_from('<I', entry, 4)[0]     # 起始顶点索引 (全局 VB)
        u32_08 = struct.unpack_from('<I', entry, 8)[0]         # patch_id / flags
        u32_0c = struct.unpack_from('<I', entry, 12)[0]        # GUID (低16位=IB字节大小)
        ib_byte_len = struct.unpack_from('<H', entry, 12)[0]   # IB 字节大小 (u16@12)
        vert_count = entry[14]                                  # 顶点数 (u8@14)
        u8_0f = entry[15]                                      # 标志位 (2=A类, 其他?)
        ax, ay, az = struct.unpack_from('<3f', entry, 16)
        bx, by, bz = struct.unpack_from('<3f', entry, 28)
        leftover = entry[40:56]  # 16B 未处理

        patches.append({
            'array': 'A' if i < array_a_count else 'B',
            'index': i,
            'patch_id': u32_08,
            'guid': u32_0c,
            'ib_byte_off': ib_byte_off,
            'ib_byte_len': ib_byte_len,
            'vert_start': vert_start,
            'vert_count': vert_count,
            'vert_end': vert_start + vert_count,
            'aabb_min': (ax, ay, az),
            'aabb_max': (bx, by, bz),
            'u8_0f': u8_0f,
            'remainder': leftover,
        })
        prev_v1 = vert_start + vert_count

    if patches:
        a_cnt_actual = array_a_count
        b_cnt_actual = array_b_count
        total_vc = sum(p['vert_count'] for p in patches)
        total_ib = sum(p['ib_byte_len'] for p in patches)
        # print(f"      Patches: {a_cnt_actual}A + {b_cnt_actual}B = {len(patches)}, "
        #       f"total_vc={total_vc}, total_ib={total_ib}, "
        #       f"v_range=[0,{patches[-1]['vert_end']})")


    c_entries = []
    for i in range(array_c_count):
        raw = array_c_raw[i * 8:(i + 1) * 8]
        c_entries.append({
            'index': i,
            'raw': raw,
            'u32': struct.unpack_from('<I', raw, 0)[0],
            'u16': struct.unpack_from('<4H', raw, 0),
            'u8': struct.unpack_from('<8B', raw, 0),
        })

    result['terrain'].append({
        'linked_id': 0,
        'verts': verts,
        'ib_raw': index_data,         
        'tri_count': tri_count,      
        'patches': patches,
        'patch_count': len(patches),
        'c_entries': c_entries,
    })
    segments['GEO0.bin'] = geo_data[start_off:len(geo_data)]


def parse_and_split(data, version, metr_data=None, geo_data=None):
    # LOD 数据解析工具
    off = 0
    result = {'meshes': [], 'terrain': [], 'skirts': [], 'occluder': [], 'cloud': None}
    segments = {}

    if version >= 57:
        parse_geo0(geo_data, result, segments)

    # ========================================================
    # Mesh (地图网格烘焙数据)
    # ========================================================
    start_off = off
    mesh_count, off = read_u32(data, off)
    if version >= 55:
        print(f"  [Mesh] mesh_count={mesh_count}")

    for i in range(mesh_count):
        name, off = read_string(data, off)
        bst_guid, off = read_u32(data, off)
        sub_count, off = read_u32(data, off)
        compress_flag, off = read_bool(data, off)

        mesh_obj = {'name': name, 'bst_guid': bst_guid, 'submeshes': []}
        # if version >= 55:
        #     try:
        #         print(f"    mesh[{i}] name={name!r}, guid={bst_guid}, subs={sub_count}, compressed={compress_flag}")
        #     except UnicodeEncodeError:
        #         print(f"    mesh[{i}] name=<binary>, guid={bst_guid}, subs={sub_count}, compressed={compress_flag}")

        for j in range(sub_count):
            uv_count, off = read_u32(data, off)
            face_count, off = read_u32(data, off)

            color_size = 12 if compress_flag else 12 * uv_count
            off += color_size
            idx_count = face_count // 2
            indices = list(struct.unpack_from(f'<{idx_count}H', data, off))
            off += face_count

            mesh_obj['submeshes'].append({'verts': [], 'indices': indices})
        result['meshes'].append(mesh_obj)
    segments['Mesh.bin'] = data[start_off:off]

    # ========================================================
    # Terrain / Cloud / Skirt 
    # ========================================================
    if version >= 57:
        # ===== v57+ Terrain 已移至 GEO0, Cloud → Skirt (meshopt) =====

        # -----------------------------------------------------------
        # 2A. Cloud 体积云稀疏块数据
        # -----------------------------------------------------------
        start_off = off
        has_cloud, off = read_u32(data, off)
        print(f"  [Cloud] has_cloud={has_cloud} (0x{has_cloud:08X})")
        if has_cloud:
            ox, oy, oz = struct.unpack_from('<3i', data, off); off += 12
            gw, gh, gd = struct.unpack_from('<3i', data, off); off += 12
            print(f"    origin=({ox},{oy},{oz}), grid=({gw},{gh},{gd})")

            if version >= 60:
                # v60+: 无 bitmask, 4 个 compressed data chunk
                active_block_count, off = read_u32(data, off)
                off += 6 * active_block_count  # 3 × uint16 (x,y,z block coord)
                print(f"    active_blocks={active_block_count}")
            else:
                mask_size = 2 * abs(gw) * abs(gh) * abs(gd)
                print(f"    mask_size={mask_size}")
                if mask_size > len(data) - off or mask_size < 0:
                    print(f"    [!] mask_size 异常，回退")
                    off = start_off
                else:
                    off += mask_size
                    active_block_count, off = read_u32(data, off)
                    off += 6 * active_block_count
                    print(f"    active_blocks={active_block_count}")
            
            if off > start_off + 4:
                # 压缩数据: v57 有 3 个 chunk, v60 有 4 个 chunk
                if version >= 60:
                    dist_comp_size, off = read_u32(data, off)
                    amb01_comp_size, off = read_u32(data, off)
                    amb2_comp_size, off = read_u32(data, off)
                    extra_comp_size, off = read_u32(data, off)
                    off += dist_comp_size + amb01_comp_size + amb2_comp_size + extra_comp_size
                    print(f"    comp_sizes: dist={dist_comp_size}, amb01={amb01_comp_size}, amb2={amb2_comp_size}, extra={extra_comp_size}")

                else:
                    dist_comp_size, off = read_u32(data, off)
                    amb01_comp_size, off = read_u32(data, off)
                    amb2_comp_size, off = read_u32(data, off)
                    off += dist_comp_size
                    off += amb01_comp_size
                    off += amb2_comp_size
                    print(f"    comp_sizes: dist={dist_comp_size}, amb01={amb01_comp_size}, amb2={amb2_comp_size}")
                
                voxel_scale, off = read_f32(data, off)
                bpp_dist_amb01, off = read_u32(data, off)
                bpp_amb2, off = read_u32(data, off)
                print(f"    voxel_scale={voxel_scale}, bpp={bpp_dist_amb01}/{bpp_amb2}")

            result['cloud'] = {}
        segments['Cloud.bin'] = data[start_off:off]

        # -----------------------------------------------------------
        # Skirt (v57: meshopt 压缩, stride=36, 无 UV/切线)
        # 格式: 每裙边 { vc(u32), vb_comp_size(u32), vb_data, ic(u32), ib_comp_size(u32), ib_data }
        # -----------------------------------------------------------
        start_off = off
        skirt_count, off = read_u32(data, off)
        print(f"  [Skirt] skirt_count={skirt_count}")
        for i in range(skirt_count):
            # 顶点数量 & 压缩顶点缓冲
            vert_count, off = read_u32(data, off)
            vb_comp_size, off = read_u32(data, off)
            vb_comp_data = data[off:off + vb_comp_size]; off += vb_comp_size
            # 索引数量 & 压缩索引缓冲
            index_count, off = read_u32(data, off)
            ib_comp_size, off = read_u32(data, off)
            ib_comp_data = data[off:off + ib_comp_size]; off += ib_comp_size

            # print(f"    skirt[{i}] verts={vert_count}, idx={index_count}, "
            #       f"vb={vb_comp_size}B, ib={ib_comp_size}B")

            verts = []
            indices = []
            vb_raw = try_decompress_meshopt_vertex(vb_comp_data, vert_count, 36)
            ib_raw = try_decompress_meshopt_index(ib_comp_data, index_count, 2)
            if vb_raw and ib_raw:
                for vi in range(vert_count):
                    vo = vi * 36
                    # 1. 世界坐标 (Position) - 12 bytes
                    x, y, z = struct.unpack_from('<3f', vb_raw, vo)
                    # 2. 压缩法线 (Packed Normal) - 4 bytes
                    nx_b, ny_b, nz_b, _ = struct.unpack_from('<4B', vb_raw, vo + 12)
                    nx, ny, nz = (nx_b/255.0)*2-1, (ny_b/255.0)*2-1, (nz_b/255.0)*2-1
                    # 3. 材质 ID (Blend Indices) - 4 bytes
                    mat_ids = struct.unpack_from('<4B', vb_raw, vo + 16)
                    # 4. 材质权重 (Blend Weights) - 4 bytes
                    mat_weights = struct.unpack_from('<4B', vb_raw, vo + 20)
                    # 5. 顶点颜色与 AO (Vertex Color & AO) - 4 bytes
                    v_color = struct.unpack_from('<4B', vb_raw, vo + 24)
                    # 6. 全局光照数据 (Baked GI / HDR Light) - 4 bytes
                    gi_light = struct.unpack_from('<4B', vb_raw, vo + 28)
                    # 7. 全局元数据 (Global Metadata) - 4 bytes
                    meta_id = struct.unpack_from('<I', vb_raw, vo + 32)[0]

                    verts.append({
                        'pos': (x, y, z),
                        'normal': (nx, ny, nz),
                        'materials': list(zip(mat_ids, mat_weights)),
                        'v_color': v_color
                    })
                indices = list(struct.unpack_from(f'<{index_count}H', ib_raw, 0))
            #     print(f"      meshopt OK ({len(verts)} verts, {len(indices)} idx)")
            # else:
            #     print(f"      meshopt FAILED (vb={vb_raw is not None}, ib={ib_raw is not None})")

            result['skirts'].append({'verts': verts, 'indices': indices})
        segments['Skirt.bin'] = data[start_off:off]

    else:
        # ===== Terrain → Cloud → Skirt =====

        # -----------------------------------------------------------
        # Terrain
        # -----------------------------------------------------------
        start_off = off
        blob_count, off = read_u32(data, off)
        if version >= 55:
            print(f"  [Terrain] blob_count={blob_count}")
        for i in range(blob_count):
            linked_id, off = read_u32(data, off)
            terrain_flags, off = read_u8(data, off)
            is_active = bool(terrain_flags & 1)               # 取第 0 位: 地形块是否被激活渲染
            has_tessellation = bool((terrain_flags >> 1) & 1)  # 取第 1 位: 是否启用了硬件细分曲面

            # Local AABB
            aabb_min, off = read_vec3(data, off)
            aabb_max, off = read_vec3(data, off)

            vert_count, off = read_u32(data, off)
            index_count, off = read_u32(data, off)
            if version >= 55:
                print(f"    blob[{i}] linked={linked_id}, verts={vert_count}, idx={index_count}, "
                      f"active={is_active}, tess={has_tessellation}")

            verts = []
            for _ in range(vert_count):
                # 1. 世界坐标 (Position) - 12 bytes
                x, y, z = struct.unpack_from('<3f', data, off)

                # 2. 压缩法线 (Packed Normal) - 4 bytes
                # 将 0~255 映射回 -1.0 ~ 1.0 的 3D 方向向量
                nx_b, ny_b, nz_b, _ = struct.unpack_from('<4B', data, off + 12)
                nx, ny, nz = (nx_b/255.0)*2-1, (ny_b/255.0)*2-1, (nz_b/255.0)*2-1

                # 3. 材质 ID (Blend Indices) - 4 bytes
                # 指向关卡材质调色板 (Palette) 的索引，支持 4 层地表材质混合
                mat_ids = struct.unpack_from('<4B', data, off + 16)

                # 4. 材质权重 (Blend Weights) - 4 bytes
                # 取值 0~255，表示对应材质 ID 的混合浓度
                mat_weights = struct.unpack_from('<4B', data, off + 20)

                # 5. 顶点颜色与环境光遮蔽 (Vertex Color & AO) - 4 bytes
                # RGB 改变地形底色，Alpha 通道控制顶点亮度(AO)，0为纯黑
                v_color = struct.unpack_from('<4B', data, off + 24)

                # 6. 烘焙全局光照 (Baked GI / HDR Light) - 4 bytes
                # 用于 HDR 环境光渲染，随意修改 Alpha 会导致引擎后处理出现 NaN 使得全屏黑屏
                gi_light = struct.unpack_from('<4B', data, off + 28)

                # 7. 全局元数据 (Global Metadata) - 4 bytes
                # 每个地图固定相同的值。地形 UV 通过世界坐标(XY)在 Shader 实时投影计算
                meta_id = struct.unpack_from('<I', data, off + 32)[0]

                verts.append({
                    'pos': (x, y, z),
                    'normal': (nx, ny, nz),
                    'materials': list(zip(mat_ids, mat_weights)),
                    'v_color': v_color
                })
                off += 36  # 每顶点 36 字节

            # -----------------------------------------------------
            # Octree
            # -----------------------------------------------------
            raw_size, off = read_u32(data, off)
            off += raw_size  # 预留给外部独立 Collision / Octree 的原始数据块

            # -----------------------------------------------------
            # [均匀网格剔除头部] (Uniform Grid Culling Header)
            # 用于将大地形切分成小方块，进行视锥体剔除优化
            # -----------------------------------------------------
            grid_aabb_min, off = read_vec3(data, off)
            grid_aabb_max, off = read_vec3(data, off)
            grid_cell_size, off = read_f32(data, off)   # 每个虚拟网格单元的物理边长 (如 10.0米)
            grid_count_x, off = read_u32(data, off)      # 网格在三维空间中的划分总数量
            grid_count_y, off = read_u32(data, off)
            grid_count_z, off = read_u32(data, off)
            patch_count, off = read_u32(data, off)        # 实际包含几何数据的非空网格(Patch)数量

            # -----------------------------------------------------
            # [网格区块数据] (Culling Patches)
            # -----------------------------------------------------
            patches = []
            for _ in range(patch_count):
                # 前 4 字节: 当前 3D 网格区块需要渲染的三角形索引数量 (Index Count)
                p_idx_count = struct.unpack_from('<I', data, off)[0]
                # 后 4 字节: 该网格在划分空间中的 3D 坐标 (X, Y, Z) + 1字节标志位
                p_cell_x, p_cell_y, p_cell_z, p_flags = struct.unpack_from('<4B', data, off + 4)
                patches.append({'idx_count': p_idx_count, 'cell_coord': (p_cell_x, p_cell_y, p_cell_z)})
                off += 8

            # -----------------------------------------------------
            # [硬件细分曲面] (Tessellation)
            # 根据相机距离动态增加地形三角形精度的数据
            # -----------------------------------------------------
            tess_tri_edge_count, off = read_u32(data, off)
            tess_edge_list_count, off = read_u32(data, off)
            tess_index_count, off = read_u32(data, off)
            off += 4 * tess_edge_list_count   # Edge List: 每条边 ID (uint32)
            off += 2 * tess_index_count       # 细分顶点索引 (uint16)
            off += 4 * tess_tri_edge_count    # 细分三角边 (uint32)

            # -----------------------------------------------------
            # [基础网格索引] (Index Buffer)
            # 核心数据：告诉 GPU 如何将顶点连成三角形。数据长度必须是 3 的倍数。
            # 引擎同时利用此数据构建物理碰撞(Collision BVH Tree)。
            # -----------------------------------------------------
            indices = list(struct.unpack_from(f'<{index_count}H', data, off))
            off += 2 * index_count

            result['terrain'].append({'linked_id': linked_id, 'verts': verts, 'indices': indices})
        segments['Terrain.bin'] = data[start_off:off]

        # ========================================================
        # 3. Cloud 体积云稀疏块数据
        # v56-: mask 1字节/像素, proxy 网格
        # v56+:   mask 2字节/像素, proxy 网格使用meshopt压缩
        # ========================================================
        start_off = off
        has_cloud, off = read_u32(data, off)
        if version >= 55:
            print(f"  [Cloud] has_cloud={has_cloud} (0x{has_cloud:08X})")
        if has_cloud:
            # 1. 稀疏网格世界坐标偏移 (Origin XYZ)
            ox, oy, oz = struct.unpack_from('<3i', data, off); off += 12

            # 2. 宏观稀疏网格的三维维度 (Grid Dimensions)
            gw, gh, gd = struct.unpack_from('<3i', data, off); off += 12

            if version >= 55:
                mask_size = 2 * abs(gw) * abs(gh) * abs(gd)
            else:
                # mask 占位图大小 = gw*gh*gd (1 字节/像素)
                mask_size = abs(gw) * abs(gh) * abs(gd)

            if version >= 55:
                print(f"    origin=({ox},{oy},{oz}), grid=({gw},{gh},{gd})")
                print(f"    mask_size={mask_size}, buf_remaining={len(data)-off}")

            if mask_size > len(data) - off or mask_size < 0:
                if version >= 55:
                    print(f"    [!] mask_size 异常，回退并保留原始数据")
                off = start_off
            else:
                off += mask_size

                # 活跃云块列表 (Active Cloud Bins)
                active_block_count, off = read_u32(data, off)
                off += 6 * active_block_count  # 3 * uint16

                # Dist (距离场), Amb01 (环境光0/1), Amb2 (环境光2)
                dist_comp_size, off = read_u32(data, off)
                amb01_comp_size, off = read_u32(data, off)
                amb2_comp_size, off = read_u32(data, off)

                # lz4 compressed data
                off += dist_comp_size
                off += amb01_comp_size
                off += amb2_comp_size

                if version >= 55:
                    print(f"    active_blocks={active_block_count}")
                    print(f"    comp_sizes: dist={dist_comp_size}, amb01={amb01_comp_size}, amb2={amb2_comp_size}")

                if version < 55:
                    voxel_scale, off = read_f32(data, off)    # 体素物理缩放比例 (通常为 1.0)
                    # 3D 纹理的 Bytes Per Pixel (BPP)
                    bpp_dist_amb01, off = read_u32(data, off) # DistGrid 和 Amb01Grid 的单像素字节数 (通常为 4)
                    bpp_amb2, off = read_u32(data, off)       # Amb2Grid 的单像素字节数 (通常为 2)
                    # 代理包围网格 (Cloud Proxy Mesh)
                    proxy_vert_count, off = read_u32(data, off)
                    proxy_idx_count, off = read_u32(data, off)
                    proxy_verts = []
                    for _ in range(proxy_vert_count):
                        x, y, z = struct.unpack_from('<3f', data, off)
                        off += 12
                        off += 4  # 跳过额外 4 字节 (颜色/标志) 纯懒得写了
                        proxy_verts.append((x, y, z))
                    proxy_indices = list(struct.unpack_from(f'<{proxy_idx_count}H', data, off))
                    off += 2 * proxy_idx_count
                    result['cloud'] = {
                        'proxy_verts': proxy_verts,
                        'proxy_indices': proxy_indices
                    }
                    if version >= 54:
                        off += 1
                else:
                    voxel_scale, off = read_f32(data, off)
                    bpp_dist_amb01, off = read_u32(data, off)
                    bpp_amb2, off = read_u32(data, off)
                    cloud_field_A, off = read_u32(data, off)
                    cloud_field_B, off = read_u32(data, off)  # vertex 
                    cloud_field_C, off = read_u32(data, off)  # index 
                    cloud_skip_D, off = read_u32(data, off)   # metadata size
                    cloud_skip_E, off = read_u32(data, off)   # compressed VB size
                    cloud_skip_F, off = read_u32(data, off)   # compressed IB size

                    # skip_D = metadata (AABB, flags), skip_E = meshopt VB, skip_F = meshopt IB
                    skip_D_data = data[off:off + cloud_skip_D]; off += cloud_skip_D
                    skip_E_data = data[off:off + cloud_skip_E]; off += cloud_skip_E
                    skip_F_data = data[off:off + cloud_skip_F]; off += cloud_skip_F
                    cloud_flag = data[off]; off += 1  # bool flag

                    # 解压 cloud proxy mesh (stride=20: pos(12) + normal(4) + color(4))
                    proxy_verts = []
                    proxy_indices = []
                    if cloud_field_B > 0 and cloud_field_C > 0 and skip_E_data and skip_F_data:
                        vb_raw = try_decompress_meshopt_vertex(skip_E_data, cloud_field_B, 20)
                        ib_raw = try_decompress_meshopt_index(skip_F_data, cloud_field_C, 2)
                        if vb_raw and ib_raw:
                            for vi in range(cloud_field_B):
                                vo = vi * 20
                                x, y, z = struct.unpack_from('<3f', vb_raw, vo)
                                proxy_verts.append((x, y, z))
                            proxy_indices = list(struct.unpack_from(f'<{cloud_field_C}H', ib_raw, 0))
                            print(f"    [cloud proxy] {cloud_field_B} verts, {cloud_field_C} idx (meshopt OK)")
                        else:
                            print(f"    [cloud proxy] meshopt FAILED (vb={vb_raw is not None}, ib={ib_raw is not None})")

                    result['cloud'] = {
                        'proxy_verts': proxy_verts,
                        'proxy_indices': proxy_indices
                    }

        segments['Cloud.bin'] = data[start_off:off]

        # ========================================================
        # Skirt
        # ========================================================
        start_off = off
        skirt_count, off = read_u32(data, off)
        if version >= 55:
            print(f"  [Skirt] skirt_count={skirt_count}")
        for i in range(skirt_count):
            if version >= 55:
                #   vertex_count (uint32)
                #   compressed_vertex_size (uint32) → skip compressed_vertex_size bytes
                #   index_count (uint32)
                #   compressed_index_size (uint32) → skip compressed_index_size bytes
                # 之后在 line 1197-1205 用 meshopt 解压
                vc, off = read_u32(data, off)
                vb_comp_size, off = read_u32(data, off)
                vb_comp_data = data[off:off + vb_comp_size]; off += vb_comp_size

                ic, off = read_u32(data, off)
                ib_comp_size, off = read_u32(data, off)
                ib_comp_data = data[off:off + ib_comp_size]; off += ib_comp_size

                # meshopt 解压 pos+normal+mat+color+gi+uv+tangent
                stride = 40  # 0x28
                vb_raw = try_decompress_meshopt_vertex(vb_comp_data, vc, stride)
                ib_raw = try_decompress_meshopt_index(ib_comp_data, ic, 2)

                if vb_raw and ib_raw:
                    verts = []
                    for vi in range(vc):
                        vo = vi * stride
                        # 1. 世界坐标 (Position) - 12 bytes
                        x, y, z = struct.unpack_from('<3f', vb_raw, vo)
                        # 2. 压缩法线 (Packed Normal) - 4 bytes
                        nx_b, ny_b, nz_b, _ = struct.unpack_from('<4B', vb_raw, vo + 12)
                        nx, ny, nz = (nx_b/255.0)*2-1, (ny_b/255.0)*2-1, (nz_b/255.0)*2-1
                        # 3. 材质 ID (Blend Indices) - 4 bytes
                        mat_ids = struct.unpack_from('<4B', vb_raw, vo + 16)
                        # 4. 材质权重 (Blend Weights) - 4 bytes
                        mat_weights = struct.unpack_from('<4B', vb_raw, vo + 20)
                        # 5. 顶点颜色与 AO (Vertex Color & AO) - 4 bytes
                        v_color = struct.unpack_from('<4B', vb_raw, vo + 24)
                        # 6. 烘焙全局光照 (Baked GI / HDR Light) - 4 bytes
                        gi_light = struct.unpack_from('<4B', vb_raw, vo + 28)
                        # 7. 显式 UV 坐标 (4 bytes) - 16位 half-float
                        u, vv = struct.unpack_from('<2e', vb_raw, vo + 32)
                        # 8. 切线向量 (Tangent) - 4 bytes, Skirt 独有
                        tx_b, ty_b, tz_b, tw_b = struct.unpack_from('<4B', vb_raw, vo + 36)
                        tx, ty, tz = (tx_b/255.0)*2-1, (ty_b/255.0)*2-1, (tz_b/255.0)*2-1
                        verts.append({
                            'pos': (x, y, z), 'normal': (nx, ny, nz),
                            'materials': list(zip(mat_ids, mat_weights)),
                            'v_color': v_color
                        })
                    indices = list(struct.unpack_from(f'<{ic}H', ib_raw, 0))
                #     print(f"    skirt[{i}] verts={vc}, idx={ic} (meshopt OK)")
                # else:
                #     verts, indices = [], []
                #     print(f"    skirt[{i}] verts={vc}, idx={ic} (meshopt FAILED, 保留原始数据)")
            else:
                vc, off = read_u32(data, off)
                verts = []
                for _ in range(vc):
                    # 1. 坐标 (12)
                    x, y, z = struct.unpack_from('<3f', data, off)
                    # 2. 法线 (4)
                    nx_b, ny_b, nz_b, _ = struct.unpack_from('<4B', data, off + 12)
                    nx, ny, nz = (nx_b/255.0)*2-1, (ny_b/255.0)*2-1, (nz_b/255.0)*2-1
                    # 3. 材质 ID (4)
                    mat_ids = struct.unpack_from('<4B', data, off + 16)
                    # 4. 材质权重 (4)
                    mat_weights = struct.unpack_from('<4B', data, off + 20)
                    # 5. 顶点色与 AO (4)
                    v_color = struct.unpack_from('<4B', data, off + 24)
                    # 6. 环境光 GI (4)
                    gi_light = struct.unpack_from('<4B', data, off + 28)
                    # 7. 显式 UV 坐标 (4) - 解析为 16位 half-float
                    u, v = struct.unpack_from('<2e', data, off + 32)
                    # 8. 切线向量 (4) - Skirt 独有的新增数据
                    tx_b, ty_b, tz_b, tw_b = struct.unpack_from('<4B', data, off + 36)
                    tx, ty, tz = (tx_b/255.0)*2-1, (ty_b/255.0)*2-1, (tz_b/255.0)*2-1

                    verts.append({
                        'pos': (x, y, z),
                        'normal': (nx, ny, nz),
                        'materials': list(zip(mat_ids, mat_weights)),
                        'v_color': v_color
                    })
                    off += 40

                ic, off = read_u32(data, off)
                indices = list(struct.unpack_from(f'<{ic}H', data, off))
                off += 2 * ic

            result['skirts'].append({'verts': verts, 'indices': indices})
        segments['Skirt.bin'] = data[start_off:off]

    # ========================================================
    # Occluder (遮挡剔除体积网格)
    # ========================================================
    start_off = off
    occluder_count, off = read_u32(data, off)
    if version >= 55:
        print(f"  [Occluder] count={occluder_count}")
    if occluder_count > 0:
        vc, off = read_u32(data, off)
        ic, off = read_u32(data, off)

        verts = []
        for _ in range(vc):
            # 1. 顶点坐标 (12 bytes)
            x, y, z = struct.unpack_from('<3f', data, off)
            # 2. 压缩法线 (4 bytes) - 用于 CPU 剔除背面的 Occluder 面片
            nx_b, ny_b, nz_b, _ = struct.unpack_from('<4B', data, off + 12)
            nx, ny, nz = (nx_b/255.0)*2-1, (ny_b/255.0)*2-1, (nz_b/255.0)*2-1
            verts.append({'pos': (x, y, z), 'normal': (nx, ny, nz)})
            off += 16  # Occluder 顶点精确为 16 字节对齐

        indices = list(struct.unpack_from(f'<{ic}H', data, off))
        off += 2 * ic
        result['occluder'].append({'verts': verts, 'indices': indices})
    segments['Occluder.bin'] = data[start_off:off]

    # ==========================================================
    # METR 段 用于索引各个数据段与大小并使引擎分配内存，目前不做解析
    # ==========================================================
    if metr_data:
        segments['METR.bin'] = metr_data

    return result, segments


# ==========================================
# OBJ 导出 (带法线，保留凹凸质感)
# ==========================================
def export_obj_filtered(result, output_dir, base_name):
    obj_path = os.path.join(output_dir, f"{base_name}.obj")
    mtl_path = os.path.join(output_dir, f"{base_name}.mtl")

    materials = {}
    def get_material(name, color=(0.8, 0.8, 0.8)):
        if name not in materials:
            materials[name] = color
        return name

    for i in range(len(result['terrain'])): get_material(f"terrain_{i}", (0.4, 0.7, 0.3))
    for i in range(len(result['skirts'])): get_material(f"skirt_{i}", (0.5, 0.4, 0.3))
    if result['occluder']: get_material("occluder", (0.2, 0.5, 0.9))
    if result.get('cloud') and result['cloud'].get('proxy_verts'): get_material("cloud_proxy", (0.9, 0.9, 1.0))

    with open(mtl_path, 'w') as mf:
        mf.write(f"# BstBaked materials\n")
        for name, (r, g, b) in materials.items():
            mf.write(f"\nnewmtl {name}\nKd {r:.4f} {g:.4f} {b:.4f}\nKa 0.1 0.1 0.1\nKs 0.0 0.0 0.0\nd 1.0\n")

    with open(obj_path, 'w') as f:
        f.write(f"# BstBaked export\nmtllib {base_name}.mtl\n\n")
        global_v_offset = 1

        # 写入顶点和法线的辅助函数
        def write_vertices_and_normals(f, verts):
            if not verts:
                return 0
            for v in verts:
                p = v.get('pos', (0, 0, 0))
                f.write(f"v {p[0]:.6f} {p[1]:.6f} {-p[2]:.6f}\n")
            for v in verts:
                n = v.get('normal', (0, 0, 1))
                f.write(f"vn {n[0]:.6f} {n[1]:.6f} {-n[2]:.6f}\n")
            return len(verts)

        def write_faces_with_normals(f, indices, base_v_offset, n_verts=None):
            tri_count = len(indices) // 3
            for t in range(tri_count):
                i0, i1, i2 = indices[t * 3], indices[t * 3 + 1], indices[t * 3 + 2]
                if n_verts is not None and (i0 >= n_verts or i1 >= n_verts or i2 >= n_verts):
                    continue
                v0 = i0 + base_v_offset + 1
                v1 = i1 + base_v_offset + 1
                v2 = i2 + base_v_offset + 1
                f.write(f"f {v0}//{v0} {v1}//{v1} {v2}//{v2}\n")

        # 保留原有的 write_vertices 和 write_faces 函数（兼容性）
        def write_vertices(f, verts):
            for v in verts:
                p = v['pos']
                f.write(f"v {p[0]:.6f} {p[1]:.6f} {-p[2]:.6f}\n")

        def write_faces(f, indices, base_offset, n_verts=None):
            tri_count = len(indices) // 3
            n = n_verts if n_verts is not None else max(indices) + 1 if indices else 0
            for t in range(tri_count):
                i0, i1, i2 = indices[t * 3], indices[t * 3 + 1], indices[t * 3 + 2]
                if n_verts is not None and (i0 >= n_verts or i1 >= n_verts or i2 >= n_verts):
                    continue
                f.write(f"f {i0 + base_offset} {i2 + base_offset} {i1 + base_offset}\n")

        def write_faces_strip(f, indices, base_offset, n_verts=None):
            tri_count = len(indices) - 2
            if tri_count <= 0:
                return
            for t in range(tri_count):
                i0, i1, i2 = indices[t], indices[t + 1], indices[t + 2]
                if n_verts is not None and (i0 >= n_verts or i1 >= n_verts or i2 >= n_verts):
                    continue
                if t & 1:
                    f.write(f"f {i2 + base_offset} {i1 + base_offset} {i0 + base_offset}\n")
                else:
                    f.write(f"f {i0 + base_offset} {i2 + base_offset} {i1 + base_offset}\n")

        def write_object(name, mat_name, verts, indices):
            nonlocal global_v_offset
            if not verts or not indices: return
            f.write(f"o {name}\nusemtl {mat_name}\n")
            write_vertices(f, verts)
            n_verts_local = len(verts)
            write_faces(f, indices, global_v_offset, n_verts_local)
            global_v_offset += n_verts_local
            f.write("\n")

        for i, t in enumerate(result['terrain']):
            patches = t.get('patches')
            ib_raw = t.get('ib_raw')
            
            if ib_raw and patches:
                all_verts = t['verts']
                c_entries = t.get('c_entries')
                
                terrain_patches = [p for p in patches if p['array'] == 'A']
                cloud_patches = [p for p in patches if p['array'] == 'B']
                
                # 使用带法线的导出方式
                base_v = global_v_offset
                n_verts = write_vertices_and_normals(f, all_verts)
                global_v_offset += n_verts
                
                total_tris = 0
                
                # --- Terrain 
                if terrain_patches:
                    group_tris = sum(p['ib_byte_len'] // 3 for p in terrain_patches)
                    total_tris += group_tris
                    vc_min = min(p['vert_count'] for p in terrain_patches)
                    vc_max = max(p['vert_count'] for p in terrain_patches)
                    f.write(f"o Terrain_{i}\n")
                    f.write(f"usemtl terrain_{i}\n")
                    f.write(f"# patches={len(terrain_patches)} tris={group_tris} vc_range=[{vc_min},{vc_max}]\n")
                    
                    for patch in terrain_patches:
                        ib_start = patch['ib_byte_off']
                        ib_end = ib_start + patch['ib_byte_len']
                        patch_bytes = ib_raw[ib_start:ib_end]
                        tri_count = len(patch_bytes) // 3
                        if tri_count == 0:
                            continue
                        vs = patch['vert_start']
                        local_indices = []
                        for ti in range(tri_count):
                            bo = ti * 3
                            i0 = patch_bytes[bo] + vs
                            i1 = patch_bytes[bo + 1] + vs
                            i2 = patch_bytes[bo + 2] + vs
                            local_indices.extend([i0, i1, i2])
                        write_faces_with_normals(f, local_indices, base_v, n_verts)
                
                # --- CloudProxy 
                if cloud_patches:
                    group_tris = sum(p['ib_byte_len'] // 3 for p in cloud_patches)
                    total_tris += group_tris
                    vc_min = min(p['vert_count'] for p in cloud_patches)
                    vc_max = max(p['vert_count'] for p in cloud_patches)
                    f.write(f"o CloudProxy_{i}\n")
                    f.write(f"usemtl cloud_proxy\n")
                    f.write(f"# patches={len(cloud_patches)} tris={group_tris} vc_range=[{vc_min},{vc_max}]\n")
                    
                    for patch in cloud_patches:
                        ib_start = patch['ib_byte_off']
                        ib_end = ib_start + patch['ib_byte_len']
                        patch_bytes = ib_raw[ib_start:ib_end]
                        tri_count = len(patch_bytes) // 3
                        if tri_count == 0:
                            continue
                        vs = patch['vert_start']
                        local_indices = []
                        for ti in range(tri_count):
                            bo = ti * 3
                            i0 = patch_bytes[bo] + vs
                            i1 = patch_bytes[bo + 1] + vs
                            i2 = patch_bytes[bo + 2] + vs
                            local_indices.extend([i0, i1, i2])
                        write_faces_with_normals(f, local_indices, base_v, n_verts)
                
                f.write(f"\n# ===== GEO0 Summary: {len(patches)} patches, {total_tris} triangles =====\n")
                
                # Array C 材质与其他信息
                if c_entries:
                    mat_groups = {}
                    for ci, ce in enumerate(c_entries):
                        raw = ce['raw']
                        mat_id = raw[0]
                        if mat_id == 0 or mat_id == 80:
                            continue
                        vtx_n = raw[1]
                        idx_n = raw[2]
                        if mat_id not in mat_groups:
                            mat_groups[mat_id] = {'vtx': 0, 'idx': 0, 'count': 0}
                        mat_groups[mat_id]['vtx'] += vtx_n
                        mat_groups[mat_id]['idx'] += idx_n
                        mat_groups[mat_id]['count'] += 1
                    
                    f.write(f"# ===== Array C Material Groups ({len(c_entries)} entries) =====\n")
                    for mid in sorted(mat_groups):
                        mg = mat_groups[mid]
                        f.write(f"#   Material[{mid:>3}]: entries={mg['count']:>3} vtx_total={mg['vtx']:>6} idx_total={mg['idx']:>6}\n")
                    f.write("\n")
            
            elif t.get('indices'):
                # 旧版本地形，使用带法线导出
                verts = t['verts']
                indices = t['indices']
                if verts and indices:
                    base_v = global_v_offset
                    n_verts = write_vertices_and_normals(f, verts)
                    global_v_offset += n_verts
                    f.write(f"o Terrain_{i}\nusemtl terrain_{i}\n")
                    write_faces_with_normals(f, indices, base_v, n_verts)
                    f.write("\n")

        # Skirt（带法线）
        for i, s in enumerate(result['skirts']):
            verts = s['verts']
            indices = s['indices']
            if verts and indices:
                base_v = global_v_offset
                n_verts = write_vertices_and_normals(f, verts)
                global_v_offset += n_verts
                f.write(f"o Skirt_{i}\nusemtl skirt_{i}\n")
                write_faces_with_normals(f, indices, base_v, n_verts)
                f.write("\n")

        # Occluder（带法线）
        for i, w in enumerate(result['occluder']):
            verts = w['verts']
            indices = w['indices']
            if verts and indices:
                base_v = global_v_offset
                n_verts = write_vertices_and_normals(f, verts)
                global_v_offset += n_verts
                f.write(f"o Occluder_{i}\nusemtl occluder\n")
                write_faces_with_normals(f, indices, base_v, n_verts)
                f.write("\n")

        # Cloud Proxy（没有法线数据，使用默认法线）
        cloud = result.get('cloud')
        if cloud and cloud.get('proxy_verts') and cloud.get('proxy_indices'):
            cv = cloud['proxy_verts']
            ci = cloud['proxy_indices']
            if cv and ci:
                f.write(f"o CloudProxy\nusemtl cloud_proxy\n")
                for p in cv:
                    f.write(f"v {p[0]:.6f} {p[1]:.6f} {-p[2]:.6f}\n")
                for p in cv:
                    f.write(f"vn 0 1 0\n")
                n_verts = len(cv)
                tri_count = len(ci) // 3
                for t in range(tri_count):
                    i0, i1, i2 = ci[t*3], ci[t*3+1], ci[t*3+2]
                    if i0 >= n_verts or i1 >= n_verts or i2 >= n_verts:
                        continue
                    f.write(f"f {i0+global_v_offset}//{i0+global_v_offset} {i1+global_v_offset}//{i1+global_v_offset} {i2+global_v_offset}//{i2+global_v_offset}\n")
                global_v_offset += n_verts
                f.write("\n")

    print(f"  [+] 成功导出模型数据至: {obj_path}")


def do_unpack(input_path, export_obj):
    """统一解包入口"""
    with open(input_path, 'rb') as f:
        data = f.read()

    if data[0:4] != b'LVL0':
        print(f"[!] {input_path} 不是有效的 LVL0 文件，跳过。")
        return

    file_version = struct.unpack_from('<I', data, 0x04)[0]
    print(f"[*] 文件版本: {file_version} ")

    # 解析 TOC
    toc_entry_count = data[0x08]
    geo0_offset, geo0_length = 0, 0
    lod0_offset, lod0_length = 0, 0
    metr_offset, metr_length = 0, 0

    if file_version >= 55:
        print(f"[*] TOC 条目数: {toc_entry_count}")
    for i in range(toc_entry_count):
        base = 0x08 + 4 + i * 12
        name = data[base:base+4].rstrip(b'\x00').decode('ascii')
        seg_offset = struct.unpack_from('<I', data, base + 4)[0]
        seg_length = struct.unpack_from('<I', data, base + 8)[0]
        if file_version >= 55:
            print(f"    [{i}] name={name!r}, offset=0x{seg_offset:X}, length={seg_length}")
        if name == 'GEO0':
            geo0_offset, geo0_length = seg_offset, seg_length
        elif name == 'LOD0':
            lod0_offset, lod0_length = seg_offset, seg_length
        elif name == 'METR':
            metr_offset, metr_length = seg_offset, seg_length

    if lod0_length == 0:
        print(f"[!] 无法在 {input_path} 中找到 LOD0 数据段。")
        return

    # METR
    metr_raw = None
    if file_version >= 55 and metr_length > 0:
        metr_info = parse_metr(data, metr_offset, metr_length)
        if metr_info:
            metr_raw = data[metr_offset:metr_offset + metr_length]

    # LOD0
    print(f"[*] 提取 LOD0 数据 (offset=0x{lod0_offset:X}, length={lod0_length})，LZ4 解压...")
    compressed = data[lod0_offset:lod0_offset + lod0_length]
    decompressed = lz4.block.decompress(compressed, uncompressed_size=0xC00000)
    print(f"[*] 解压完成，原始大小={len(decompressed):,} bytes")

    # GEO0
    geo_data = None
    if file_version >= 57 and geo0_length > 0:
        geo_data = data[geo0_offset:geo0_offset + geo0_length]
        print(f"[*] 提取 GEO0 数据 (offset=0x{geo0_offset:X}, length={geo0_length})")

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    out_dir = os.path.join(os.path.dirname(input_path), base_name)
    os.makedirs(out_dir, exist_ok=True)

    result, segments = parse_and_split(decompressed, file_version, metr_raw, geo_data)

    # 写入分段文件
    if file_version >= 57:
        seg_names = SEGMENT_NAMES_V3
    elif file_version >= 55:
        seg_names = SEGMENT_NAMES_V2
    else:
        seg_names = SEGMENT_NAMES
    for seg_name in seg_names:
        if seg_name in segments:
            with open(os.path.join(out_dir, seg_name), 'wb') as f:
                f.write(segments[seg_name])

    print(f"[+] 成功解压并拆分 {base_name}.meshes (v{file_version}) 至目录 -> {out_dir}/")

    if export_obj:
        export_obj_filtered(result, out_dir, base_name)


# ==========================================
# 重新打包的文件头参考（在0.3.18经过测试可用）
# ==========================================
def build_header(version: int, lod_offset: int, lod_length: int) -> bytes:
    out = bytearray(132)
    struct.pack_into('4s', out, 0x00, b'LVL0')
    struct.pack_into('<I', out, 0x04, version)
    out[0x08] = 1
    struct.pack_into('4s', out, 0x0C, b'LOD0')
    struct.pack_into('<I', out, 0x10, lod_offset)
    struct.pack_into('<I', out, 0x14, lod_length)
    POS_INF, NEG_INF = 0x7F7FFFFF, 0xFF7FFFFF
    for i in range(3): struct.pack_into('<I', out, 0x6C + i*4, POS_INF)
    for i in range(3): struct.pack_into('<I', out, 0x78 + i*4, NEG_INF)
    return bytes(out)



def main():
    parser = argparse.ArgumentParser(description="BstBaked Mesh 综合处理工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--unpack", type=str, help="指定需要解压的 .meshes 文件或包含它们的目录")
    parser.add_argument("-r", "--recursive", action="store_true", help="允许对目录进行批量/递归处理")
    parser.add_argument("--export-obj", action="store_true", help="在 unpack 时导出 OBJ 信息（跳过 Mesh 几何）")
    parser.add_argument("--out", type=str, help="仅对单一 repack 有效，指定输出文件路径")
    args = parser.parse_args()

    if args.unpack:
        if os.path.isfile(args.unpack):
            do_unpack(args.unpack, args.export_obj)
        elif os.path.isdir(args.unpack) and args.recursive:
            for root, _, files in os.walk(args.unpack):
                for f in files:
                    if f.endswith(".meshes"):
                        do_unpack(os.path.join(root, f), args.export_obj)
        else:
            print("[!] 指定的路径无效，或者您正在尝试解压目录但未添加 -r 参数。")

if __name__ == "__main__":
    main()