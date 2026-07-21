# [Upstream] meshtoobj — .mesh model parser (legacy, v23–v30)
# Source: https://github.com/ThatSkyOldServer/SkyBstbake
# Authors: checion (雨人) & Heriel (落秋)
# License: MIT (see NOTICE)

import struct
import os
import sys
import re
import ctypes
import io
from dataclasses import dataclass
from typing import List, Optional, Tuple

try:
    import lz4.block
    LZ4_AVAILABLE = True
except ImportError:
    LZ4_AVAILABLE = False
    try:
        from ctypes import CDLL
        lz4 = CDLL('liblz4.so.1')
        LZ4_SO_AVAILABLE = True
    except:
        LZ4_SO_AVAILABLE = False

VERTEX_STRIDE = 16
UV_STRIDE = 16
INDEX_STRIDE_32 = 4
INDEX_STRIDE_16 = 2

HEADER_VERSION_MAP = {
    b'\x17\x00\x00\x00': 23,
    b'\x18\x00\x00\x00': 24,
    b'\x19\x00\x00\x00': 25,
    b'\x1a\x00\x00\x00': 26,
    b'\x1b\x00\x00\x00': 27,
    b'\x1c\x00\x00\x00': 28,
    b'\x1d\x00\x00\x00': 29,
    b'\x1e\x00\x00\x00': 30,
    b'\x1f\x00\x00\x00': 31,
    b'\x20\x00\x00\x00': 32,
}

class Reader:
    __slots__ = ("data", "ofs", "size")

    def __init__(self, data: bytes):
        self.data = data
        self.ofs = 0
        self.size = len(data)

    def tell(self) -> int:
        return self.ofs

    def seek(self, pos: int, whence: int = 0):
        if whence == 0:
            self.ofs = pos
        elif whence == 1:
            self.ofs += pos
        elif whence == 2:
            self.ofs = self.size + pos
        else:
            raise ValueError("Invalid whence")
        if self.ofs < 0 or self.ofs > self.size:
            raise ValueError(f"Seek out of range: {self.ofs}/{self.size}")

    def read_bytes(self, n: int) -> bytes:
        if self.ofs + n > self.size:
            raise ValueError(f"Read out of range: {self.ofs}+{n} > {self.size}")
        b = self.data[self.ofs:self.ofs+n]
        self.ofs += n
        return b

    def read_u8(self) -> int:
        return self._unpack_from("<B", 1)[0]

    def read_u16(self) -> int:
        return self._unpack_from("<H", 2)[0]

    def read_u32(self) -> int:
        return self._unpack_from("<I", 4)[0]

    def read_fmt(self, fmt: str):
        sz = struct.calcsize(fmt)
        return self._unpack_from(fmt, sz)

    def _unpack_from(self, fmt: str, sz: int):
        if self.ofs + sz > self.size:
            raise ValueError(f"Unpack out of range: {self.ofs}+{sz} > {self.size}")
        out = struct.unpack_from(fmt, self.data, self.ofs)
        self.ofs += sz
        return out

def lz4_block_decompress(src: bytes, uncompressed_size: Optional[int] = None) -> bytes:
    try:
        import lz4.block
        if uncompressed_size is None:
            return lz4.block.decompress(src)
        return lz4.block.decompress(src, uncompressed_size=uncompressed_size)
    except Exception:
        pass

    i = 0
    out = bytearray()
    src_len = len(src)

    def read_len(base: int) -> int:
        nonlocal i
        ln = base
        if ln == 15:
            while True:
                if i >= src_len:
                    raise ValueError("LZ4: truncated length")
                s = src[i]
                i += 1
                ln += s
                if s != 255:
                    break
        return ln

    while i < src_len:
        token = src[i]
        i += 1

        lit_len = read_len(token >> 4)
        if i + lit_len > src_len:
            raise ValueError("LZ4: literal length out of range")
        out += src[i:i+lit_len]
        i += lit_len

        if i >= src_len:
            break

        if i + 2 > src_len:
            raise ValueError("LZ4: missing match offset")
        offset = src[i] | (src[i+1] << 8)
        i += 2
        if offset == 0:
            raise ValueError("LZ4: invalid offset=0")

        match_len = read_len(token & 0x0F) + 4

        start = len(out) - offset
        if start < 0:
            raise ValueError("LZ4: offset beyond output buffer")

        for _ in range(match_len):
            out.append(out[start])
            start += 1

        if uncompressed_size is not None and len(out) > uncompressed_size:
            raise ValueError("LZ4: output exceeds expected uncompressed size")

    if uncompressed_size is not None and len(out) != uncompressed_size:
        raise ValueError(f"LZ4: size mismatch: got {len(out)} expected {uncompressed_size}")

    return bytes(out)

def decompress_lz4_python(src, uncompressed_size):
    return lz4.block.decompress(src, uncompressed_size=uncompressed_size)

def decompress_lz4_ctypes(src, uncompressed_size):
    dest = ctypes.create_string_buffer(uncompressed_size)
    ret = lz4.LZ4_decompress_safe(src, dest, len(src), uncompressed_size)
    if ret <= 0:
        raise IOError('LZ4解压失败')
    return dest.raw

def hex_string_to_bytes(hex_str):
    hex_str = re.sub(r'\s+', '', hex_str)
    if not hex_str:
        return b''
    try:
        return bytes.fromhex(hex_str)
    except ValueError as e:
        print(f"16进制字符串格式错误: {e}")
        return b''

def find_first_01(data, start_offset=0):
    for i in range(start_offset, len(data)):
        if data[i] == 0x01:
            return i
    return None

def find_all_occurrences(data, value_bytes):
    positions = []
    pos = 0
    while True:
        pos = data.find(value_bytes, pos)
        if pos == -1:
            break
        positions.append(pos)
        pos += 1
    return positions

def create_output_folder(filepath, base_name, version):
    base_dir = os.path.dirname(os.path.abspath(filepath))
    obj_dir = os.path.join(base_dir, "obj")
    os.makedirs(obj_dir, exist_ok=True)
    folder_name = f"{base_name}_{version}"
    out_folder = os.path.join(obj_dir, folder_name)
    idx = 1
    original_out = out_folder
    while os.path.exists(out_folder):
        out_folder = f"{original_out}_{idx}"
        idx += 1
    os.makedirs(out_folder)
    return out_folder

def save_results(out_folder, base_name, raw_vertices, raw_uv, raw_indices,
                 vertex_buffer, uv_buffer, triangles,
                 extra_info=None, is_special=False, extra_gap=0,
                 decompressed_raw=None):
    v_bin = os.path.join(out_folder, f"{base_name}_vertices.bin")
    with open(v_bin, 'wb') as f:
        f.write(raw_vertices)
    uv_bin = os.path.join(out_folder, f"{base_name}_uvs.bin")
    with open(uv_bin, 'wb') as f:
        f.write(raw_uv)
    idx_bin = os.path.join(out_folder, f"{base_name}_indices.bin")
    with open(idx_bin, 'wb') as f:
        f.write(raw_indices)
    if decompressed_raw is not None:
        dec_bin = os.path.join(out_folder, f"{base_name}_decompressed.bin")
        with open(dec_bin, 'wb') as f:
            f.write(decompressed_raw)

    txt_path = os.path.join(out_folder, f"{base_name}.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(f"源文件: {extra_info.get('filepath', '')}\n")
        f.write(f"文件大小: {extra_info.get('file_size', 0)} 字节\n")
        if 'decompressed_size' in extra_info:
            f.write(f"解压后大小: {extra_info['decompressed_size']} 字节\n")
        f.write(f"顶点数: {extra_info.get('vertex_count', 0)}\n")
        f.write(f"实际顶点数: {len(vertex_buffer)}\n")
        f.write(f"顶点数据范围: {extra_info.get('vertex_range', '')}\n")
        f.write(f"顶点与UV间隔: {extra_info.get('gap', 0)} 字节\n")
        f.write(f"UV数据范围: {extra_info.get('uv_range', '')}\n")
        if is_special:
            f.write(f"特殊文件额外间隙: {extra_gap} 字节\n")
        f.write(f"索引个数: {extra_info.get('index_count', 0)}\n")
        f.write(f"索引数据范围: {extra_info.get('index_range', '')}\n")
        f.write(f"实际三角形数: {len(triangles)}\n\n")
        if 'bones' in extra_info and extra_info['bones']:
            f.write("骨骼信息:\n")
            for b in extra_info['bones']:
                f.write(f"  {b}\n")
            f.write("\n")
        f.write("顶点列表:\n")
        for i, v in enumerate(vertex_buffer):
            f.write(f"v{i}: {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        f.write("\nUV列表:\n")
        for i, uv in enumerate(uv_buffer):
            f.write(f"uv{i}: {uv[0]:.6f} {uv[1]:.6f}\n")
        f.write("\n三角形列表:\n")
        for i, tri in enumerate(triangles):
            f.write(f"f{i}: {tri[0]} {tri[1]} {tri[2]}\n")
    print(f"报告保存: {txt_path}")

    obj_path = os.path.join(out_folder, f"{base_name}.obj")
    with open(obj_path, 'w') as f:
        f.write(f"# OBJ from {extra_info.get('filename', base_name)}\n")
        for v in vertex_buffer:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for uv in uv_buffer:
            f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
        for tri in triangles:
            f.write(f"f {tri[0]+1}/{tri[0]+1} {tri[1]+1}/{tri[1]+1} {tri[2]+1}/{tri[2]+1}\n")
    print(f"OBJ保存: {obj_path}")

    try:
        import bpy
        mesh = bpy.data.meshes.new(base_name)
        edges = []
        faces = triangles
        mesh.from_pydata(vertex_buffer, edges, faces)
        mesh.update()
        if uv_buffer:
            uvl = mesh.uv_layers.new()
            uv_data = []
            for loop in mesh.loops:
                uv = uv_buffer[loop.vertex_index]
                uv_data.extend(uv)
            uvl.data.foreach_set('uv', uv_data)
        obj = bpy.data.objects.new(base_name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        print(f"已在Blender中创建物体: {base_name}")
    except:
        pass

    print(f"输出文件夹: {out_folder}")

def process_header_17(data, filepath, filename, version, is_batch, return_data_only=False):
    name_no_ext = os.path.splitext(filename)[0]
    file_size = len(data)

    if not return_data_only and "StripAnim" not in filename:
        fn_lower = filename.lower()
        cond_anim = "anim" in fn_lower
        cond_anc = "anc" in fn_lower and not fn_lower.startswith("anc")
        cond_clothes = "衣服" in filename
        if (cond_anim or cond_anc) and not cond_clothes:
            if is_batch:
                print(f"文件名包含特殊关键词，在批量模式中跳过: {filename}")
                return None
            else:
                print(f"文件名包含特殊关键词，转为手动输入模式...")
                manual_process()
                return None

    if not return_data_only and "StripAnim" in filename:
        print("检测到 StripAnim 文件，使用特殊解析逻辑（固定偏移）")
        vertex_info_pos = 0x4061
        index_info_pos = 0x4065
        vertex_start = 0x408D

        if vertex_info_pos + 4 > file_size:
            print("顶点数量信息超出文件范围")
            return None
        vertex_count_from_info = struct.unpack('<I', data[vertex_info_pos:vertex_info_pos+4])[0]
        vertex_bytes = vertex_count_from_info * 16
        print(f"顶点数据字节数: {vertex_bytes} (由{vertex_count_from_info}*16得来)")

        if vertex_start + vertex_bytes > file_size:
            print("顶点数据超出文件范围")
            return None
        raw_vertices = data[vertex_start:vertex_start+vertex_bytes]

        vertex_buffer = []
        for i in range(0, vertex_bytes, VERTEX_STRIDE):
            chunk = raw_vertices[i:i+VERTEX_STRIDE]
            if len(chunk) < 12:
                continue
            try:
                x, y, z = struct.unpack('<fff', chunk[:12])
                vertex_buffer.append((x, y, z))
            except:
                continue
        actual_vertex_count = len(vertex_buffer)
        if actual_vertex_count != vertex_count_from_info:
            print(f"警告: 实际顶点数 {actual_vertex_count} 与声明的 {vertex_count_from_info} 不符")
        vertex_count = actual_vertex_count
        print(f"成功解析 {vertex_count} 个顶点")

        gap = vertex_bytes // 4
        print(f"顶点与UV之间的间隔字节数: {gap}")
        normal_start = vertex_start + vertex_bytes
        raw_normals = data[normal_start:normal_start+gap]

        uv_start = normal_start + gap
        uv_end = uv_start + vertex_bytes
        if uv_end > file_size:
            uv_end = file_size
        raw_uv = data[uv_start:uv_end]

        uv_buffer = []
        for i in range(0, len(raw_uv), UV_STRIDE):
            chunk = raw_uv[i:i+UV_STRIDE]
            if len(chunk) >= 8:
                try:
                    u, v = struct.unpack('<ff', chunk[:8])
                    uv_buffer.append((u, v))
                except:
                    uv_buffer.append((0.0, 0.0))
        if len(uv_buffer) < vertex_count:
            uv_buffer.extend([(0.0,0.0)] * (vertex_count - len(uv_buffer)))
        elif len(uv_buffer) > vertex_count:
            uv_buffer = uv_buffer[:vertex_count]
        print(f"UV数量: {len(uv_buffer)}")

        extra_gap = vertex_count_from_info * 8
        print(f"StripAnim: UV与索引之间的额外间隙字节数: {extra_gap}")

        if index_info_pos + 4 > file_size:
            print("索引数量信息超出文件范围")
            return None
        index_count = struct.unpack('<I', data[index_info_pos:index_info_pos+4])[0]
        index_bytes = index_count * INDEX_STRIDE_32
        print(f"索引个数: {index_count} (字节数: {index_bytes})")

        index_start = uv_end + extra_gap
        index_end = index_start + index_bytes
        if index_end > file_size:
            index_end = file_size

        if index_start >= file_size or index_count == 0:
            raw_indices = b''
            index_values = []
            triangles = []
        else:
            raw_indices = data[index_start:index_end]
            index_values = []
            for i in range(0, len(raw_indices), INDEX_STRIDE_32):
                if i+4 <= len(raw_indices):
                    try:
                        idx = struct.unpack('<I', raw_indices[i:i+4])[0]
                        index_values.append(idx)
                    except:
                        continue
            triangles = []
            for i in range(0, len(index_values), 3):
                if i+3 <= len(index_values):
                    triangles.append(tuple(index_values[i:i+3]))
        print(f"三角形数量: {len(triangles)}")

        extra_info = {
            'filepath': filepath,
            'filename': filename,
            'file_size': file_size,
            'vertex_count': vertex_count,
            'vertex_start': vertex_start,
            'vertex_bytes': vertex_bytes,
            'normal_start': normal_start,
            'normal_bytes': gap,
            'uv_start': uv_start,
            'uv_bytes': vertex_bytes,
            'index_start': index_start,
            'index_bytes': index_bytes,
            'gap': gap,
            'index_count': index_count,
        }
        if return_data_only:
            return (vertex_buffer, uv_buffer, triangles, raw_vertices, raw_uv, raw_indices, extra_info, raw_normals, False, None)
        else:
            out_folder = create_output_folder(filepath, name_no_ext, version)
            save_results(out_folder, name_no_ext, raw_vertices, raw_uv, raw_indices,
                         vertex_buffer, uv_buffer, triangles,
                         extra_info=extra_info, is_special=True, extra_gap=extra_gap)
            return out_folder

    pos_first_01 = find_first_01(data)
    if pos_first_01 is None:
        print("未找到0x01字节")
        return None
    print(f"第一个0x01位置: 0x{pos_first_01:02x}")

    vertex_info_pos = pos_first_01 + 45
    if vertex_info_pos + 4 > file_size:
        print("顶点数量信息超出文件范围")
        return None
    vertex_count_from_info = struct.unpack('<I', data[vertex_info_pos:vertex_info_pos+4])[0]
    vertex_bytes = vertex_count_from_info * 16
    print(f"顶点数据字节数: {vertex_bytes} (由{vertex_count_from_info}*16得来)")

    VERTEX_START = 0x9d
    if VERTEX_START + vertex_bytes > file_size:
        print("顶点数据超出文件范围")
        return None
    raw_vertices = data[VERTEX_START:VERTEX_START+vertex_bytes]

    vertex_buffer = []
    for i in range(0, vertex_bytes, VERTEX_STRIDE):
        chunk = raw_vertices[i:i+VERTEX_STRIDE]
        if len(chunk) < 12:
            continue
        try:
            x, y, z = struct.unpack('<fff', chunk[:12])
            vertex_buffer.append((x, y, z))
        except:
            continue
    actual_vertex_count = len(vertex_buffer)
    if actual_vertex_count != vertex_count_from_info:
        print(f"警告: 实际顶点数 {actual_vertex_count} 与声明的 {vertex_count_from_info} 不符")
    vertex_count = actual_vertex_count
    print(f"成功解析 {vertex_count} 个顶点")

    gap = vertex_bytes // 4
    print(f"顶点与UV之间的间隔字节数: {gap}")
    normal_start = VERTEX_START + vertex_bytes
    raw_normals = data[normal_start:normal_start+gap]

    uv_start = normal_start + gap
    uv_end = uv_start + vertex_bytes
    if uv_end > file_size:
        uv_end = file_size
    raw_uv = data[uv_start:uv_end]

    uv_buffer = []
    for i in range(0, len(raw_uv), UV_STRIDE):
        chunk = raw_uv[i:i+UV_STRIDE]
        if len(chunk) >= 8:
            try:
                u, v = struct.unpack('<ff', chunk[:8])
                uv_buffer.append((u, v))
            except:
                uv_buffer.append((0.0, 0.0))
    if len(uv_buffer) < vertex_count:
        uv_buffer.extend([(0.0,0.0)] * (vertex_count - len(uv_buffer)))
    elif len(uv_buffer) > vertex_count:
        uv_buffer = uv_buffer[:vertex_count]
    print(f"UV数量: {len(uv_buffer)}")

    INDEX_INFO_POS = 0x75
    if INDEX_INFO_POS + 4 > file_size:
        print("索引数量信息超出文件范围 (0x75)")
        return None
    index_count = struct.unpack('<I', data[INDEX_INFO_POS:INDEX_INFO_POS+4])[0]
    index_bytes = index_count * INDEX_STRIDE_32
    print(f"索引个数: {index_count} (字节数: {index_bytes})")

    index_start = uv_end
    index_end = index_start + index_bytes
    if index_end > file_size:
        print(f"警告: 索引数据超出文件，实际可用至文件末尾")
        index_end = file_size

    raw_indices = data[index_start:index_end]
    index_values = []
    for i in range(0, len(raw_indices), INDEX_STRIDE_32):
        if i+4 <= len(raw_indices):
            try:
                idx = struct.unpack('<I', raw_indices[i:i+4])[0]
                index_values.append(idx)
            except:
                continue
    triangles = []
    for i in range(0, len(index_values), 3):
        if i+3 <= len(index_values):
            triangles.append(tuple(index_values[i:i+3]))
    print(f"三角形数量: {len(triangles)}")

    extra_info = {
        'filepath': filepath,
        'filename': filename,
        'file_size': file_size,
        'vertex_count': vertex_count,
        'vertex_start': VERTEX_START,
        'vertex_bytes': vertex_bytes,
        'normal_start': normal_start,
        'normal_bytes': gap,
        'uv_start': uv_start,
        'uv_bytes': vertex_bytes,
        'index_start': index_start,
        'index_bytes': index_bytes,
        'vertex_info_pos': vertex_info_pos,
        'index_info_pos': INDEX_INFO_POS,
        'gap': gap,
        'index_count': index_count,
    }
    if return_data_only:
        return (vertex_buffer, uv_buffer, triangles, raw_vertices, raw_uv, raw_indices, extra_info, raw_normals, False, None)
    else:
        out_folder = create_output_folder(filepath, name_no_ext, version)
        save_results(out_folder, name_no_ext, raw_vertices, raw_uv, raw_indices,
                     vertex_buffer, uv_buffer, triangles, extra_info=extra_info)
        return out_folder

def process_header_1A(data, filepath, filename, version, return_data_only=False):
    name_no_ext = os.path.splitext(filename)[0]
    file_size = len(data)

    VERTEX_COUNT_OFFSET = 0x66
    INDEX_COUNT_OFFSET = 0x6A
    VERTEX_START = 0x92

    if VERTEX_COUNT_OFFSET + 4 > file_size:
        print("顶点数偏移超出文件范围")
        return None
    vertex_count_orig = struct.unpack('<I', data[VERTEX_COUNT_OFFSET:VERTEX_COUNT_OFFSET+4])[0]
    vertex_bytes = vertex_count_orig * VERTEX_STRIDE
    print(f"顶点数(原始): {vertex_count_orig} (字节数: {vertex_bytes})")

    if INDEX_COUNT_OFFSET + 4 > file_size:
        print("索引数偏移超出文件范围")
        return None
    index_count = struct.unpack('<I', data[INDEX_COUNT_OFFSET:INDEX_COUNT_OFFSET+4])[0]
    index_bytes = index_count * INDEX_STRIDE_32
    print(f"索引数: {index_count} (字节数: {index_bytes})")

    if VERTEX_START + vertex_bytes > file_size:
        print("顶点数据超出文件范围")
        return None
    raw_vertices = data[VERTEX_START:VERTEX_START+vertex_bytes]

    vertex_buffer = []
    for i in range(0, vertex_bytes, VERTEX_STRIDE):
        chunk = raw_vertices[i:i+VERTEX_STRIDE]
        if len(chunk) < 12:
            continue
        try:
            x, y, z = struct.unpack('<fff', chunk[:12])
            vertex_buffer.append((x, y, z))
        except:
            continue
    actual_vertex_count = len(vertex_buffer)
    if actual_vertex_count != vertex_count_orig:
        print(f"警告: 实际顶点数 {actual_vertex_count} 与声明的 {vertex_count_orig} 不符")
    print(f"成功解析 {actual_vertex_count} 个顶点")

    gap = vertex_bytes // 4
    print(f"顶点与UV之间的间隔字节数: {gap}")
    normal_start = VERTEX_START + vertex_bytes
    raw_normals = data[normal_start:normal_start+gap]

    uv_start = normal_start + gap
    uv_end = uv_start + vertex_bytes
    if uv_end > file_size:
        uv_end = file_size
    raw_uv = data[uv_start:uv_end]

    uv_buffer = []
    for i in range(0, len(raw_uv), UV_STRIDE):
        chunk = raw_uv[i:i+UV_STRIDE]
        if len(chunk) >= 8:
            try:
                u, v = struct.unpack('<ff', chunk[:8])
                uv_buffer.append((u, v))
            except:
                uv_buffer.append((0.0, 0.0))
    if len(uv_buffer) < actual_vertex_count:
        uv_buffer.extend([(0.0,0.0)] * (actual_vertex_count - len(uv_buffer)))
    elif len(uv_buffer) > actual_vertex_count:
        uv_buffer = uv_buffer[:actual_vertex_count]
    print(f"UV数量: {len(uv_buffer)}")

    has_anim = re.search(r'anim', filename, re.IGNORECASE)
    has_anc = re.search(r'anc', filename, re.IGNORECASE)
    has_ancestor = re.search(r'ancestor', filename, re.IGNORECASE)
    is_special = (has_anim or has_anc) and not has_ancestor
    if is_special:
        print("检测到包含 anim 或 anc（且不包含 ancestor）的文件，将使用额外间隙调整索引位置")
        extra_gap = vertex_count_orig * 8
        print(f"特殊文件: UV与索引之间的额外间隙字节数: {extra_gap}")
        index_start = uv_end + extra_gap
    else:
        extra_gap = 0
        index_start = uv_end

    index_end = index_start + index_bytes
    if index_end > file_size:
        print(f"警告: 索引数据超出文件，实际可用至文件末尾")
        index_end = file_size

    if index_start >= file_size or index_count == 0:
        print("无有效索引数据")
        raw_indices = b''
        index_values = []
        triangles = []
    else:
        raw_indices = data[index_start:index_end]
        index_values = []
        for i in range(0, len(raw_indices), INDEX_STRIDE_32):
            if i+4 <= len(raw_indices):
                try:
                    idx = struct.unpack('<I', raw_indices[i:i+4])[0]
                    index_values.append(idx)
                except:
                    continue
        triangles = []
        for i in range(0, len(index_values), 3):
            if i+3 <= len(index_values):
                triangles.append(tuple(index_values[i:i+3]))
    print(f"三角形数量: {len(triangles)}")

    extra_info = {
        'filepath': filepath,
        'filename': filename,
        'file_size': file_size,
        'vertex_count': vertex_count_orig,
        'vertex_start': VERTEX_START,
        'vertex_bytes': vertex_bytes,
        'normal_start': normal_start,
        'normal_bytes': gap,
        'uv_start': uv_start,
        'uv_bytes': vertex_bytes,
        'index_start': index_start,
        'index_bytes': index_bytes,
        'gap': gap,
        'index_count': index_count,
        'is_special': is_special,
        'extra_gap': extra_gap,
    }
    if return_data_only:
        return (vertex_buffer, uv_buffer, triangles, raw_vertices, raw_uv, raw_indices, extra_info, raw_normals, False, None)
    else:
        out_folder = create_output_folder(filepath, name_no_ext, version)
        save_results(out_folder, name_no_ext, raw_vertices, raw_uv, raw_indices,
                     vertex_buffer, uv_buffer, triangles,
                     extra_info=extra_info, is_special=is_special, extra_gap=extra_gap)
        return out_folder

def process_header_1C(data, filepath, filename, version, return_data_only=False):
    name_no_ext = os.path.splitext(filename)[0]
    file_size = len(data)

    try:
        if 0x44 + 4 > file_size or 0x4E + 4 > file_size or 0x52 + 4 > file_size:
            print("压缩信息偏移超出文件范围")
            return None
        num_lods = struct.unpack('<I', data[0x44:0x48])[0]
        compressed_size = struct.unpack('<I', data[0x4E:0x52])[0]
        uncompressed_size = struct.unpack('<I', data[0x52:0x56])[0]
    except Exception as e:
        print(f"读取压缩信息失败: {e}")
        return None

    print('LOD数量:', num_lods)
    print('压缩大小:', compressed_size)
    print('未压缩大小:', uncompressed_size)

    if compressed_size <= 0 or uncompressed_size <= 0 or 0x56 + compressed_size > file_size:
        print("错误：无效的压缩/未压缩大小")
        return None

    src = data[0x56:0x56+compressed_size]
    if len(src) != compressed_size:
        print("错误：未能读取完整的压缩数据")
        return None

    dest_raw = None
    if LZ4_AVAILABLE:
        try:
            dest_raw = decompress_lz4_python(src, uncompressed_size)
            print("使用Python lz4库解压成功")
        except Exception as e:
            print(f"Python lz4解压失败: {e}")
            return None
    elif LZ4_SO_AVAILABLE:
        try:
            dest_raw = decompress_lz4_ctypes(src, uncompressed_size)
            print("使用系统liblz4解压成功")
        except Exception as e:
            print(f"系统liblz4解压失败: {e}")
            return None
    else:
        print("错误：没有可用的LZ4解压方法，请安装lz4库 (pip install lz4)")
        return None

    if dest_raw is None:
        print("解压失败")
        return None

    decompressed_size = len(dest_raw)
    print(f"解压后大小: {decompressed_size} 字节 (预期 {uncompressed_size})")

    has_anim = re.search(r'anim', filename, re.IGNORECASE)
    has_anc = re.search(r'anc', filename, re.IGNORECASE)
    has_ancestor = re.search(r'Ancestor', filename, re.IGNORECASE)
    is_special = (has_anim or has_anc) and not has_ancestor
    if is_special:
        print("检测到包含 anim 或 anc（且不包含 ancestor）的文件，将使用额外间隙调整索引位置")

    VERTEX_COUNT_OFFSET = 0x34
    INDEX_COUNT_OFFSET = 0x38
    VERTEX_START = 0x60

    if VERTEX_COUNT_OFFSET + 4 > decompressed_size:
        print("顶点数偏移超出解压后数据范围")
        return None
    vertex_count = struct.unpack('<I', dest_raw[VERTEX_COUNT_OFFSET:VERTEX_COUNT_OFFSET+4])[0]
    vertex_bytes = vertex_count * VERTEX_STRIDE
    print(f"顶点数: {vertex_count} (字节数: {vertex_bytes})")

    if INDEX_COUNT_OFFSET + 4 > decompressed_size:
        print("索引数偏移超出解压后数据范围")
        return None
    index_count = struct.unpack('<I', dest_raw[INDEX_COUNT_OFFSET:INDEX_COUNT_OFFSET+4])[0]
    index_bytes = index_count * INDEX_STRIDE_32
    print(f"索引数: {index_count} (字节数: {index_bytes})")

    if VERTEX_START + vertex_bytes > decompressed_size:
        print("顶点数据超出解压后数据范围")
        return None
    raw_vertices = dest_raw[VERTEX_START:VERTEX_START+vertex_bytes]

    vertex_buffer = []
    for i in range(0, vertex_bytes, VERTEX_STRIDE):
        chunk = raw_vertices[i:i+VERTEX_STRIDE]
        if len(chunk) < 12:
            continue
        try:
            x, y, z = struct.unpack('<fff', chunk[:12])
            vertex_buffer.append((x, y, z))
        except:
            continue
    actual_vertex_count = len(vertex_buffer)
    if actual_vertex_count != vertex_count:
        print(f"警告: 实际顶点数 {actual_vertex_count} 与声明的 {vertex_count} 不符")
    print(f"成功解析 {actual_vertex_count} 个顶点")

    gap = vertex_bytes // 4
    print(f"顶点与UV之间的间隔字节数: {gap}")
    normal_start = VERTEX_START + vertex_bytes
    raw_normals = dest_raw[normal_start:normal_start+gap]

    uv_start = normal_start + gap
    uv_end = uv_start + vertex_bytes
    if uv_end > decompressed_size:
        print(f"UV数据超出范围，实际可用至文件末尾")
        uv_end = decompressed_size
    raw_uv = dest_raw[uv_start:uv_end]

    uv_buffer = []
    for i in range(0, len(raw_uv), UV_STRIDE):
        chunk = raw_uv[i:i+UV_STRIDE]
        if len(chunk) >= 8:
            try:
                u, v = struct.unpack('<ff', chunk[:8])
                uv_buffer.append((u, v))
            except:
                uv_buffer.append((0.0, 0.0))
    if len(uv_buffer) < actual_vertex_count:
        uv_buffer.extend([(0.0,0.0)] * (actual_vertex_count - len(uv_buffer)))
    elif len(uv_buffer) > actual_vertex_count:
        uv_buffer = uv_buffer[:actual_vertex_count]
    print(f"UV数量: {len(uv_buffer)}")

    if is_special:
        extra_gap = vertex_count * 8
        print(f"特殊文件: UV与索引之间的额外间隙字节数: {extra_gap}")
        index_start = uv_end + extra_gap
    else:
        extra_gap = 0
        index_start = uv_end

    index_end = index_start + index_bytes
    if index_end > decompressed_size:
        print(f"警告: 索引数据超出文件，实际可用至文件末尾")
        index_end = decompressed_size

    if index_start >= decompressed_size or index_count == 0:
        print("无有效索引数据")
        raw_indices = b''
        index_values = []
        triangles = []
    else:
        raw_indices = dest_raw[index_start:index_end]
        index_values = []
        for i in range(0, len(raw_indices), INDEX_STRIDE_32):
            if i+4 <= len(raw_indices):
                try:
                    idx = struct.unpack('<I', raw_indices[i:i+4])[0]
                    index_values.append(idx)
                except:
                    continue
        triangles = []
        for i in range(0, len(index_values), 3):
            if i+3 <= len(index_values):
                triangles.append(tuple(index_values[i:i+3]))
    print(f"三角形数量: {len(triangles)}")

    extra_info = {
        'filepath': filepath,
        'filename': filename,
        'file_size': file_size,
        'decompressed_size': decompressed_size,
        'vertex_count': vertex_count,
        'vertex_start': VERTEX_START,
        'vertex_bytes': vertex_bytes,
        'normal_start': normal_start,
        'normal_bytes': gap,
        'uv_start': uv_start,
        'uv_bytes': vertex_bytes,
        'index_start': index_start,
        'index_bytes': index_bytes,
        'gap': gap,
        'index_count': index_count,
        'is_special': is_special,
        'extra_gap': extra_gap,
        'compressed_info': (compressed_size, uncompressed_size, 0x56, src)
    }
    if return_data_only:
        return (vertex_buffer, uv_buffer, triangles, raw_vertices, raw_uv, raw_indices, extra_info, raw_normals, True, dest_raw)
    else:
        out_folder = create_output_folder(filepath, name_no_ext, version)
        save_results(out_folder, name_no_ext, raw_vertices, raw_uv, raw_indices,
                     vertex_buffer, uv_buffer, triangles,
                     extra_info=extra_info, is_special=is_special, extra_gap=extra_gap,
                     decompressed_raw=dest_raw)
        return out_folder

def process_header_1E(data, filepath, filename, version, return_data_only=False):
    name_no_ext = os.path.splitext(filename)[0]
    file_size = len(data)

    try:
        if 0x44 + 4 > file_size or 0x4E + 4 > file_size or 0x52 + 4 > file_size:
            print("压缩信息偏移超出文件范围")
            return None
        num_lods = struct.unpack('<I', data[0x44:0x48])[0]
        compressed_size = struct.unpack('<I', data[0x4E:0x52])[0]
        uncompressed_size = struct.unpack('<I', data[0x52:0x56])[0]
    except Exception as e:
        print(f"读取压缩信息失败: {e}")
        return None

    print('LOD数量:', num_lods)
    print('压缩大小:', compressed_size)
    print('未压缩大小:', uncompressed_size)

    if compressed_size <= 0 or uncompressed_size <= 0 or 0x56 + compressed_size > file_size:
        print("错误：无效的压缩/未压缩大小")
        return None

    src = data[0x56:0x56+compressed_size]
    if len(src) != compressed_size:
        print("错误：未能读取完整的压缩数据")
        return None

    dest_raw = None
    if LZ4_AVAILABLE:
        try:
            dest_raw = decompress_lz4_python(src, uncompressed_size)
            print("使用Python lz4库解压成功")
        except Exception as e:
            print(f"Python lz4解压失败: {e}")
            return None
    elif LZ4_SO_AVAILABLE:
        try:
            dest_raw = decompress_lz4_ctypes(src, uncompressed_size)
            print("使用系统liblz4解压成功")
        except Exception as e:
            print(f"系统liblz4解压失败: {e}")
            return None
    else:
        print("错误：没有可用的LZ4解压方法，请安装lz4库 (pip install lz4)")
        return None

    if dest_raw is None:
        print("解压失败")
        return None

    decompressed_size = len(dest_raw)
    print(f"解压后大小: {decompressed_size} 字节 (预期 {uncompressed_size})")

    if decompressed_size < 0x84:
        print("解压后数据太小，无法读取计数")
        return None

    shared_vertex_count = struct.unpack('<I', dest_raw[0x74:0x78])[0]
    total_vertex_count = struct.unpack('<I', dest_raw[0x78:0x7C])[0]
    point_count = struct.unpack('<I', dest_raw[0x80:0x84])[0]
    uv_count = shared_vertex_count

    print(f"shared_vertex_count: {shared_vertex_count}")
    print(f"total_vertex_count: {total_vertex_count}")
    print(f"point_count: {point_count}")
    print(f"uv_count: {uv_count}")

    vertex_start = 0xB3
    vertex_bytes = shared_vertex_count * VERTEX_STRIDE
    if vertex_start + vertex_bytes > decompressed_size:
        print("顶点数据超出范围")
        return None
    raw_vertices = dest_raw[vertex_start:vertex_start+vertex_bytes]

    vertex_buffer = []
    for i in range(0, vertex_bytes, VERTEX_STRIDE):
        chunk = raw_vertices[i:i+VERTEX_STRIDE]
        if len(chunk) < 12:
            continue
        try:
            x, y, z = struct.unpack('<fff', chunk[:12])
            vertex_buffer.append((x, y, z))
        except:
            continue
    actual_vertex_count = len(vertex_buffer)
    if actual_vertex_count != shared_vertex_count:
        print(f"警告: 实际顶点数 {actual_vertex_count} 与声明的 {shared_vertex_count} 不符")
    print(f"成功解析 {actual_vertex_count} 个顶点")

    fn_lower = filename.lower()
    is_special = ('anim' in fn_lower) or ('anc' in fn_lower and 'ancestor' not in fn_lower)

    if is_special:
        gap = vertex_bytes // 4
        normal_start = vertex_start + vertex_bytes
        raw_normals = dest_raw[normal_start:normal_start+gap]
        uv_start = normal_start + gap
        uv_size = vertex_bytes
        extra_gap = shared_vertex_count * 8
        index_start = uv_start + uv_size + extra_gap
        print(f"特殊文件: UV 起始偏移 = 0x{uv_start:x}, UV 大小 = {uv_size}, 额外间隙 = {extra_gap}")
    else:
        uv_header_size = uv_count * 4 - 4
        normal_start = vertex_start + vertex_bytes
        raw_normals = dest_raw[normal_start:normal_start+uv_header_size]
        uv_start = normal_start + uv_header_size
        uv_size = uv_count * UV_STRIDE
        index_start = uv_start + uv_size + 4
        extra_gap = 0
        print(f"普通文件: UV 起始偏移 = 0x{uv_start:x}, UV 大小 = {uv_size}")
        gap = uv_header_size

    face_count = total_vertex_count // 3
    index_bytes = face_count * 6
    index_end = index_start + index_bytes
    if index_end > decompressed_size:
        print(f"警告: 索引数据超出文件，实际可用至文件末尾")
        index_end = decompressed_size

    if uv_start + uv_size > decompressed_size:
        print("UV 数据超出范围")
        uv_end = decompressed_size
    else:
        uv_end = uv_start + uv_size
    raw_uv = dest_raw[uv_start:uv_end]

    uv_buffer = []
    uv_data_len = len(raw_uv)
    pos = 0
    while pos + UV_STRIDE <= uv_data_len:
        chunk = raw_uv[pos:pos+UV_STRIDE]
        try:
            u, v = struct.unpack('<ee', chunk[4:8])
            uv_buffer.append((float(u), float(v)))
        except:
            uv_buffer.append((0.0, 0.0))
        pos += UV_STRIDE
    if len(uv_buffer) < actual_vertex_count:
        uv_buffer.extend([(0.0,0.0)] * (actual_vertex_count - len(uv_buffer)))
    elif len(uv_buffer) > actual_vertex_count:
        uv_buffer = uv_buffer[:actual_vertex_count]
    print(f"UV数量: {len(uv_buffer)}")

    if index_start >= decompressed_size or face_count == 0:
        raw_indices = b''
        index_values = []
        triangles = []
    else:
        raw_indices = dest_raw[index_start:index_end]
        index_values = []
        for i in range(0, len(raw_indices), 2):
            if i+2 <= len(raw_indices):
                try:
                    idx = struct.unpack('<H', raw_indices[i:i+2])[0]
                    index_values.append(idx)
                except:
                    continue
        triangles = []
        for i in range(0, len(index_values), 3):
            if i+3 <= len(index_values):
                triangles.append(tuple(index_values[i:i+3]))
    print(f"三角形数量: {len(triangles)}")

    extra_info = {
        'filepath': filepath,
        'filename': filename,
        'file_size': file_size,
        'decompressed_size': decompressed_size,
        'vertex_count': shared_vertex_count,
        'vertex_start': vertex_start,
        'vertex_bytes': vertex_bytes,
        'normal_start': normal_start,
        'normal_bytes': gap,
        'uv_start': uv_start,
        'uv_bytes': uv_size,
        'index_start': index_start,
        'index_bytes': index_bytes,
        'gap': gap,
        'index_count': face_count * 3,
        'is_special': is_special,
        'extra_gap': extra_gap,
        'compressed_info': (compressed_size, uncompressed_size, 0x56, src)
    }
    if return_data_only:
        return (vertex_buffer, uv_buffer, triangles, raw_vertices, raw_uv, raw_indices, extra_info, raw_normals, True, dest_raw)
    else:
        out_folder = create_output_folder(filepath, name_no_ext, version)
        save_results(out_folder, name_no_ext, raw_vertices, raw_uv, raw_indices,
                     vertex_buffer, uv_buffer, triangles,
                     extra_info=extra_info, is_special=is_special, extra_gap=extra_gap,
                     decompressed_raw=dest_raw)
        return out_folder

@dataclass
class BoneInfo:
    name: str
    parent: int
    matrix: list

@dataclass
class MeshData20:
    verts: List[Tuple[float, float, float]]
    faces: List[Tuple[int, int, int]]
    uv_layers: List[List[Tuple[float, float]]]
    weights: Optional[List[Tuple[List[int], List[float]]]]

def parse_container_and_bones_20(file_bytes: bytes) -> Tuple[bytes, List[BoneInfo], bool]:
    bones: List[BoneInfo] = []
    is_zippos = False

    if file_bytes[:4] != b"\x20\x00\x00\x00":
        return file_bytes, bones, is_zippos

    r = Reader(file_bytes)

    hdr = r.read_fmt("<18IH")
    h = hdr[17:] + r.read_fmt("<4I")
    comp_size = int(h[4])
    uncomp_size = int(h[5])

    comp = r.read_bytes(comp_size)
    payload = lz4_block_decompress(comp, uncomp_size)

    if int(h[1]) == 1:
        binf_20 = r.read_fmt("<20I")
        b = r.read_u8()
        tail_i = r.read_u32()
        binf = binf_20 + (b, tail_i)
        bone_count = int(binf[17])

        for x in range(bone_count):
            name_raw = r.read_bytes(64)
            name = name_raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore")
            if not name:
                name = f"bone_{x}"
            mat_bytes = r.read_bytes(64)
            vals = struct.unpack("<16f", mat_bytes)
            parent = int(r.read_u32()) - 1
            bones.append(BoneInfo(name=name, parent=parent, matrix=vals))

    return payload, bones, is_zippos

def parse_standard_mesh_20(payload: bytes, bones: List[BoneInfo]) -> Tuple[MeshData20, bytes, bytes, bytes, bytes]:
    r = Reader(payload)

    r.seek(116)
    vnum = r.read_u32()
    r.seek(120)
    inum = r.read_u32()
    r.seek(128)
    _unum = r.read_u32()

    vertex_buffer_start = 179
    r.seek(vertex_buffer_start)
    vbuf = r.read_bytes(vnum * 16)

    normals_raw = r.read_bytes(vnum * 4)

    uvbuf = r.read_bytes(vnum * 16)

    wbuf = None
    if bones:
        wbuf = r.read_bytes(vnum * 8)

    ibuf = r.read_bytes(inum * 2)

    verts = []
    for i in range(vnum):
        x, y, z = struct.unpack_from("<3f", vbuf, i * 16)
        verts.append((x, y, z))

    idx = struct.unpack("<" + "H" * inum, ibuf)
    tri_count = inum // 3
    faces = []
    for t in range(tri_count):
        a = idx[t * 3 + 0]
        b = idx[t * 3 + 1]
        c = idx[t * 3 + 2]
        faces.append((a, b, c))

    uv_layers = [[], [], [], []]
    for i in range(vnum):
        uvs = struct.unpack_from("<8e", uvbuf, i * 16)
        pairs = [(uvs[0], uvs[1]), (uvs[2], uvs[3]), (uvs[4], uvs[5]), (uvs[6], uvs[7])]
        for l in range(4):
            uv_layers[l].append(pairs[l])

    weights = None
    if wbuf is not None:
        bone_map = [i - 1 for i in range(len(bones) + 1)]
        bone_map[0] = 0
        weights = []
        for i in range(vnum):
            base = i * 8
            idxs = list(wbuf[base:base+4])
            ws = list(wbuf[base+4:base+8])
            bone_ids = []
            bone_ws = []
            for j in range(4):
                fi = idxs[j]
                fw = ws[j] / 255.0
                if fw <= 0.0:
                    continue
                if fi >= len(bone_map):
                    continue
                bi = bone_map[fi]
                if bi < 0 or bi >= len(bones):
                    continue
                bone_ids.append(bi)
                bone_ws.append(fw)
            s = sum(bone_ws)
            if s > 0:
                bone_ws = [w / s for w in bone_ws]
            weights.append((bone_ids, bone_ws))

    mesh_data = MeshData20(
        verts=verts,
        faces=faces,
        uv_layers=uv_layers,
        weights=weights,
    )
    return mesh_data, vbuf, normals_raw, uvbuf, ibuf

def process_header_20(data, filepath, filename, version, return_data_only=False):
    name_no_ext = os.path.splitext(filename)[0]
    file_size = len(data)

    is_zippos = "ZipPos" in filename

    try:
        payload, bones, _ = parse_container_and_bones_20(data)
    except Exception as e:
        print(f"解析 20 头容器失败: {e}")
        return None

    decompressed_size = len(payload)
    print(f"解压后大小: {decompressed_size} 字节")

    try:
        if is_zippos:
            mesh_data, raw_vertices, raw_normals, raw_uv, raw_indices = parse_standard_mesh_20(payload, bones)
        else:
            mesh_data, raw_vertices, raw_normals, raw_uv, raw_indices = parse_standard_mesh_20(payload, bones)
    except Exception as e:
        print(f"解析 20 头网格数据失败: {e}")
        return None

    vertex_buffer = mesh_data.verts
    uv_buffer = mesh_data.uv_layers[0]
    triangles = mesh_data.faces

    actual_vertex_count = len(vertex_buffer)
    vnum = actual_vertex_count

    vertex_start = 0xB3
    vertex_bytes = vnum * 16
    normal_start = vertex_start + vertex_bytes
    normal_bytes = vnum * 4
    uv_start = normal_start + normal_bytes
    uv_bytes = vnum * 16
    weight_bytes = vnum * 8 if bones else 0
    index_start = uv_start + uv_bytes + weight_bytes
    index_bytes = len(raw_indices)

    extra_info = {
        'filepath': filepath,
        'filename': filename,
        'file_size': file_size,
        'decompressed_size': decompressed_size,
        'vertex_count': vnum,
        'vertex_start': vertex_start,
        'vertex_bytes': vertex_bytes,
        'normal_start': normal_start,
        'normal_bytes': normal_bytes,
        'uv_start': uv_start,
        'uv_bytes': uv_bytes,
        'index_start': index_start,
        'index_bytes': index_bytes,
        'gap': normal_bytes,
        'index_count': len(raw_indices) // 2,
        'bones': [f"{b.name} parent {b.parent}" for b in bones],
        'has_bones': len(bones) > 0,
        'is_zippos': is_zippos,
    }

    if return_data_only:
        return (vertex_buffer, uv_buffer, triangles,
                raw_vertices, raw_uv, raw_indices,
                extra_info, raw_normals, True, payload)
    else:
        out_folder = create_output_folder(filepath, name_no_ext, version)
        save_results(out_folder, name_no_ext, raw_vertices, raw_uv, raw_indices,
                     vertex_buffer, uv_buffer, triangles,
                     extra_info=extra_info, is_special=False, extra_gap=0,
                     decompressed_raw=payload)
        return out_folder

def parse_container_and_bones_1F(file_bytes: bytes) -> Tuple[bytes, List[BoneInfo], bool]:
    bones: List[BoneInfo] = []
    is_zippos = False

    if file_bytes[:4] != b"\x1F\x00\x00\x00":
        return file_bytes, bones, is_zippos

    r = Reader(file_bytes)

    hdr = r.read_fmt("<18IH")
    h = hdr[17:] + r.read_fmt("<3I")
    comp_size = int(h[3])
    uncomp_size = int(h[4])

    comp = r.read_bytes(comp_size)
    payload = lz4_block_decompress(comp, uncomp_size)

    if int(h[1]) == 1:
        binf_20 = r.read_fmt("<20I")
        b = r.read_u8()
        tail_i = r.read_u32()
        binf = binf_20 + (b, tail_i)
        bone_count = int(binf[17])

        for x in range(bone_count):
            name_raw = r.read_bytes(64)
            name = name_raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore")
            if not name:
                name = f"bone_{x}"
            mat_bytes = r.read_bytes(64)
            vals = struct.unpack("<16f", mat_bytes)
            parent = int(r.read_u32()) - 1
            bones.append(BoneInfo(name=name, parent=parent, matrix=vals))

    return payload, bones, is_zippos

def parse_standard_mesh_1F(payload: bytes, bones: List[BoneInfo]) -> Tuple[MeshData20, bytes, bytes, bytes, bytes]:
    r = Reader(payload)

    r.seek(116)
    vnum = r.read_u32()
    r.seek(120)
    inum = r.read_u32()
    r.seek(128)
    _unum = r.read_u32()

    vertex_buffer_start = 179
    r.seek(vertex_buffer_start)
    vbuf = r.read_bytes(vnum * 16)

    normals_raw = r.read_bytes(vnum * 4)

    uvbuf = r.read_bytes(vnum * 16)

    wbuf = None
    if bones:
        wbuf = r.read_bytes(vnum * 8)

    ibuf = r.read_bytes(inum * 2)

    verts = []
    for i in range(vnum):
        x, y, z = struct.unpack_from("<3f", vbuf, i * 16)
        verts.append((x, y, z))

    idx = struct.unpack("<" + "H" * inum, ibuf)
    tri_count = inum // 3
    faces = []
    for t in range(tri_count):
        a = idx[t * 3 + 0]
        b = idx[t * 3 + 1]
        c = idx[t * 3 + 2]
        faces.append((a, b, c))

    uv_layers = [[], [], [], []]
    for i in range(vnum):
        uvs = struct.unpack_from("<8e", uvbuf, i * 16)
        pairs = [(uvs[0], uvs[1]), (uvs[2], uvs[3]), (uvs[4], uvs[5]), (uvs[6], uvs[7])]
        for l in range(4):
            uv_layers[l].append(pairs[l])

    weights = None
    if wbuf is not None:
        bone_map = [i - 1 for i in range(len(bones) + 1)]
        bone_map[0] = 0
        weights = []
        for i in range(vnum):
            base = i * 8
            idxs = list(wbuf[base:base+4])
            ws = list(wbuf[base+4:base+8])
            bone_ids = []
            bone_ws = []
            for j in range(4):
                fi = idxs[j]
                fw = ws[j] / 255.0
                if fw <= 0.0:
                    continue
                if fi >= len(bone_map):
                    continue
                bi = bone_map[fi]
                if bi < 0 or bi >= len(bones):
                    continue
                bone_ids.append(bi)
                bone_ws.append(fw)
            s = sum(bone_ws)
            if s > 0:
                bone_ws = [w / s for w in bone_ws]
            weights.append((bone_ids, bone_ws))

    mesh_data = MeshData20(
        verts=verts,
        faces=faces,
        uv_layers=uv_layers,
        weights=weights,
    )
    return mesh_data, vbuf, normals_raw, uvbuf, ibuf

def parse_zippos_mesh_1F(payload: bytes, bones: List[BoneInfo]) -> Tuple[MeshData20, bytes, bytes, bytes, bytes]:
    r = Reader(payload)

    r.seek(116)
    vnum = r.read_u32()
    r.seek(120)
    inum = r.read_u32()
    r.seek(128)
    _unum = r.read_u32()

    r.seek(179)
    if bones:
        r.seek(vnum * 8, 1)
    ibuf = r.read_bytes(inum * 2)

    comp_vbuf = payload[-(vnum * 4):]
    verts = []
    for i in range(vnum):
        x, y, z, w = struct.unpack_from("<BBBB", comp_vbuf, i * 4)
        verts.append((float(y), float(z), float(w)))

    idx = struct.unpack("<" + "H" * inum, ibuf)
    tri_count = inum // 3
    faces = []
    for t in range(tri_count):
        a = idx[t * 3 + 0]
        b = idx[t * 3 + 1]
        c = idx[t * 3 + 2]
        faces.append((a, b, c))

    uv_layers = [[(0.0,0.0)] * vnum for _ in range(4)]
    mesh_data = MeshData20(
        verts=verts,
        faces=faces,
        uv_layers=uv_layers,
        weights=None,
    )
    raw_vertices = comp_vbuf
    raw_normals = b'\x00' * (vnum * 4)
    raw_uv = b'\x00' * (vnum * 16)
    raw_indices = ibuf
    return mesh_data, raw_vertices, raw_normals, raw_uv, raw_indices

def process_header_1F(data, filepath, filename, version, return_data_only=False):
    name_no_ext = os.path.splitext(filename)[0]
    file_size = len(data)

    is_zippos = "ZipPos" in filename

    try:
        payload, bones, _ = parse_container_and_bones_1F(data)
    except Exception as e:
        print(f"解析 1F 头容器失败: {e}")
        return None

    decompressed_size = len(payload)
    print(f"解压后大小: {decompressed_size} 字节")

    try:
        if is_zippos:
            mesh_data, raw_vertices, raw_normals, raw_uv, raw_indices = parse_zippos_mesh_1F(payload, bones)
        else:
            mesh_data, raw_vertices, raw_normals, raw_uv, raw_indices = parse_standard_mesh_1F(payload, bones)
    except Exception as e:
        print(f"解析 1F 头网格数据失败: {e}")
        return None

    vertex_buffer = mesh_data.verts
    uv_buffer = mesh_data.uv_layers[0]
    triangles = mesh_data.faces

    actual_vertex_count = len(vertex_buffer)
    vnum = actual_vertex_count

    vertex_start = 0xB3
    vertex_bytes = vnum * 16
    normal_start = vertex_start + vertex_bytes
    normal_bytes = vnum * 4
    uv_start = normal_start + normal_bytes
    uv_bytes = vnum * 16
    weight_bytes = vnum * 8 if bones else 0
    index_start = uv_start + uv_bytes + weight_bytes
    index_bytes = len(raw_indices)

    extra_info = {
        'filepath': filepath,
        'filename': filename,
        'file_size': file_size,
        'decompressed_size': decompressed_size,
        'vertex_count': vnum,
        'vertex_start': vertex_start,
        'vertex_bytes': vertex_bytes,
        'normal_start': normal_start,
        'normal_bytes': normal_bytes,
        'uv_start': uv_start,
        'uv_bytes': uv_bytes,
        'index_start': index_start,
        'index_bytes': index_bytes,
        'gap': normal_bytes,
        'index_count': len(raw_indices) // 2,
        'bones': [f"{b.name} parent {b.parent}" for b in bones],
        'has_bones': len(bones) > 0,
        'is_zippos': is_zippos,
    }

    if return_data_only:
        return (vertex_buffer, uv_buffer, triangles,
                raw_vertices, raw_uv, raw_indices,
                extra_info, raw_normals, True, payload)
    else:
        out_folder = create_output_folder(filepath, name_no_ext, version)
        save_results(out_folder, name_no_ext, raw_vertices, raw_uv, raw_indices,
                     vertex_buffer, uv_buffer, triangles,
                     extra_info=extra_info, is_special=is_zippos, extra_gap=0,
                     decompressed_raw=payload)
        return out_folder

def process_single_file(filepath, is_batch=False):
    if not filepath.lower().endswith('.mesh'):
        print(f"跳过非.mesh文件: {filepath}")
        return None

    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except Exception as e:
        print(f"无法读取文件 {filepath}: {e}")
        return None

    if len(data) < 4:
        print(f"文件太小: {filepath}")
        return None

    header = data[:4]
    filename = os.path.basename(filepath)

    print(f"\n处理文件: {filename}, 大小: {len(data)} 字节, 头部: {header.hex()}")

    version = HEADER_VERSION_MAP.get(header)
    if version is None:
        print(f"未知的文件头: {header.hex()}, 跳过")
        return None

    print(f"版本号: {version}")

    if header == b'\x17\x00\x00\x00':
        return process_header_17(data, filepath, filename, version, is_batch, return_data_only=False)
    elif header == b'\x1a\x00\x00\x00':
        return process_header_1A(data, filepath, filename, version, return_data_only=False)
    elif header == b'\x1c\x00\x00\x00':
        return process_header_1C(data, filepath, filename, version, return_data_only=False)
    elif header == b'\x1e\x00\x00\x00':
        return process_header_1E(data, filepath, filename, version, return_data_only=False)
    elif header == b'\x1f\x00\x00\x00':
        return process_header_1F(data, filepath, filename, version, return_data_only=False)
    elif header == b'\x20\x00\x00\x00':
        return process_header_20(data, filepath, filename, version, return_data_only=False)
    else:
        print(f"未实现该头部的处理逻辑: {header.hex()}")
        return None

def auto_process():
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    else:
        try:
            filename = input("请输入mesh文件路径: ").strip()
        except:
            print("未提供文件路径")
            return
    if not os.path.exists(filename):
        print(f"文件不存在: {filename}")
        return
    process_single_file(filename, is_batch=False)

def process_directory():
    dir_path = input("请输入目录路径: ").strip()
    if not os.path.isdir(dir_path):
        print("无效目录")
        return

    mesh_files = []
    for root, dirs, files in os.walk(dir_path):
        for file in files:
            if file.lower().endswith('.mesh'):
                full_path = os.path.join(root, file)
                mesh_files.append(full_path)

    if not mesh_files:
        print("目录中没有 .mesh 文件")
        return

    print(f"找到 {len(mesh_files)} 个 .mesh 文件，开始处理...")
    for i, filepath in enumerate(mesh_files, 1):
        print(f"\n[{i}/{len(mesh_files)}] 处理文件: {filepath}")
        process_single_file(filepath, is_batch=True)

    print("所有文件处理完成")

def manual_process():
    print("\n=== 手动处理模式 ===")
    vertex_hex = ""
    print("请输入顶点数据(16进制，按Enter换行，输入空行结束):")
    while True:
        line = input().strip()
        if line == "":
            break
        vertex_hex += line

    vertex_data = hex_string_to_bytes(vertex_hex)
    if vertex_data is None or len(vertex_data) == 0:
        print("顶点数据无效或为空")
        return

    vertex_buffer = []
    pos = 0
    vertex_count = 0
    while pos + 16 <= len(vertex_data):
        chunk = vertex_data[pos:pos+16]
        try:
            x, y, z = struct.unpack('<fff', chunk[:12])
            vertex_buffer.append((x, y, z))
            vertex_count += 1
            pos += 16
        except:
            print(f"解析顶点数据时出错，位置: 0x{pos:02x}")
            pos += 1
    print(f"解析到 {vertex_count} 个顶点")

    uv_hex = ""
    print("\n请输入UV数据(16进制，按Enter换行，输入空行结束):")
    while True:
        line = input().strip()
        if line == "":
            break
        uv_hex += line

    uv_buffer = []
    uv_data = b''
    if uv_hex:
        uv_data = hex_string_to_bytes(uv_hex)
        if uv_data is not None and len(uv_data) > 0:
            pos = 0
            uv_count = 0
            while pos + 16 <= len(uv_data):
                chunk = uv_data[pos:pos+16]
                try:
                    u, v = struct.unpack('<ff', chunk[:8])
                    uv_buffer.append((u, v))
                    uv_count += 1
                    pos += 16
                except:
                    print(f"解析UV数据时出错，位置: 0x{pos:02x}")
                    pos += 1
            print(f"解析到 {uv_count} 个UV坐标")

    index_hex = ""
    print("\n请输入索引数据(16进制，按Enter换行，输入空行结束):")
    while True:
        line = input().strip()
        if line == "":
            break
        index_hex += line

    index_buffer = []
    index_data = b''
    if index_hex:
        index_data = hex_string_to_bytes(index_hex)
        if index_data is not None and len(index_data) > 0:
            pos = 0
            index_temp = []
            triangle_count = 0
            while pos + 4 <= len(index_data):
                chunk = index_data[pos:pos+4]
                try:
                    index_value = struct.unpack('<I', chunk)[0]
                    index_temp.append(index_value)
                    pos += 4
                    if len(index_temp) >= 3:
                        v1, v2, v3 = index_temp[0], index_temp[1], index_temp[2]
                        index_buffer.append((v1, v2, v3))
                        index_temp = []
                        triangle_count += 1
                except:
                    print(f"解析索引数据时出错，位置: 0x{pos:02x}")
                    pos += 1
            print(f"解析到 {triangle_count} 个三角形")

    if len(uv_buffer) < len(vertex_buffer):
        uv_buffer.extend([(0.0,0.0)] * (len(vertex_buffer) - len(uv_buffer)))
    elif len(uv_buffer) > len(vertex_buffer):
        uv_buffer = uv_buffer[:len(vertex_buffer)]

    base_dir = os.getcwd()
    folder_idx = 1
    while True:
        out_folder = os.path.join(base_dir, f"manual_output_{folder_idx}")
        if not os.path.exists(out_folder):
            os.makedirs(out_folder)
            break
        folder_idx += 1
    print(f"\n创建输出文件夹: {out_folder}")

    v_bin = os.path.join(out_folder, "manual_vertices.bin")
    with open(v_bin, 'wb') as f:
        f.write(vertex_data)
    if uv_data:
        uv_bin = os.path.join(out_folder, "manual_uvs.bin")
        with open(uv_bin, 'wb') as f:
            f.write(uv_data)
    if index_data:
        idx_bin = os.path.join(out_folder, "manual_indices.bin")
        with open(idx_bin, 'wb') as f:
            f.write(index_data)

    txt_path = os.path.join(out_folder, "manual_mesh.txt")
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write("=== 手动处理结果 ===\n\n")
        f.write(f"顶点数量: {vertex_count}\n")
        for i, v in enumerate(vertex_buffer):
            f.write(f"v{i}: {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        f.write("\nUV数量: {}\n".format(len(uv_buffer)))
        for i, uv in enumerate(uv_buffer):
            f.write(f"uv{i}: {uv[0]:.6f} {uv[1]:.6f}\n")
        f.write("\n三角形数量: {}\n".format(len(index_buffer)))
        for i, tri in enumerate(index_buffer):
            f.write(f"f{i}: {tri[0]} {tri[1]} {tri[2]}\n")
    print(f"报告保存: {txt_path}")

    obj_path = os.path.join(out_folder, "manual_mesh.obj")
    with open(obj_path, 'w') as f:
        f.write("# Manual mesh\n")
        for v in vertex_buffer:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for uv in uv_buffer:
            f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
        for tri in index_buffer:
            if len(uv_buffer) >= len(vertex_buffer):
                f.write(f"f {tri[0]+1}/{tri[0]+1} {tri[1]+1}/{tri[1]+1} {tri[2]+1}/{tri[2]+1}\n")
            else:
                f.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")
    print(f"OBJ保存: {obj_path}")

    try:
        import bpy
        mesh = bpy.data.meshes.new('manual_mesh')
        edges = []
        faces = index_buffer
        mesh.from_pydata(vertex_buffer, edges, faces)
        mesh.update()
        if uv_buffer:
            uvl = mesh.uv_layers.new()
            uv_data = []
            for loop in mesh.loops:
                uv = uv_buffer[loop.vertex_index]
                uv_data.extend(uv)
            uvl.data.foreach_set('uv', uv_data)
        obj = bpy.data.objects.new('manual_object', mesh)
        bpy.context.scene.collection.objects.link(obj)
        print("网格已成功导入Blender")
    except:
        pass

def main():
    print("=== 通用 Mesh 解析工具 (支持头 17/1A/1C/1E/1F/20) ===")
    print("1. 处理目录下所有文件（含子目录）")
    print("2. 处理单个文件")
    print("3. 手动输入内容")
    print("====================================================")

    while True:
        try:
            choice = input("请选择 (1/2/3): ").strip()
            if choice == "1":
                process_directory()
                break
            elif choice == "2":
                auto_process()
                break
            elif choice == "3":
                manual_process()
                break
            else:
                print("无效选择，请输入1、2或3")
        except KeyboardInterrupt:
            print("\n程序已终止")
            break
        except Exception as e:
            print(f"发生错误: {e}")
            break

    input("\n按Enter键退出...")

if __name__ == "__main__":
    main()