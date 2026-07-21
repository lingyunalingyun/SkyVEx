#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
meshes2obj_json.py - That Sky Level .meshes 全方位转换器 (纯 Python, 适配 Termux)

支持以下转换方向:
    .meshes -> .obj (可逆)   网格 -> OBJ (含全部信息, 建模软件可读, 可直接转回)
    .meshes -> .obj (标准)   网格 -> OBJ (仅几何, touch_object)
    .obj    -> .meshes       OBJ -> 网格 (自动检测: 可逆OBJ精确还原 / 标准OBJ邻接分块)
    .meshes -> .json         网格 -> JSON (全部数据, 可视化)
    .json   -> .meshes       JSON -> 网格 (从 JSON 重建二进制)

用法:
    # 交互式菜单 (推荐, 无参数启动)
    python3 meshes2obj_json.py

    # 命令行
    python3 meshes2obj_json.py -i input.meshes -o output.obj --full   # meshes -> 可逆 obj
    python3 meshes2obj_json.py -i input.meshes -o output.obj          # meshes -> 标准 obj
    python3 meshes2obj_json.py -i input.obj -o output.meshes          # obj -> meshes
    python3 meshes2obj_json.py -i input.meshes -o output.json         # meshes -> json
    python3 meshes2obj_json.py -i input.json -o output.meshes         # json -> meshes
    python3 meshes2obj_json.py -i input.meshes --info                 # 仅打印文件信息

转换方向根据输入/输出文件扩展名自动判断, 也可用 --mode 显式指定:
    m2o  = meshes->obj (标准)    m2of = meshes->obj (可逆)
    o2m  = obj->meshes           m2j  = meshes->json    j2m = json->meshes

可逆 OBJ 格式: 标准 OBJ 几何 (v/vn/f) + # @ 注释嵌入完整 meshes 元数据。
建模软件 (Blender/Maya 等) 可正常读取几何; 转换器读取元数据可字节级无损还原。

移植自 https://github.com/that-sky-project/that-sky-level
仅依赖 Python 标准库, meshopt 编解码用纯 Python 重写, 无需任何原生模块。
"""

import sys
import os
import math
import struct
import json
import argparse
import time


# ============================================================
#  小端二进制流读取器
# ============================================================
class BinaryStream:
    __slots__ = ("data", "pos")

    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def remaining(self):
        return len(self.data) - self.pos

    def read(self, n):
        s = self.data[self.pos:self.pos + n]
        if len(s) != n:
            raise EOFError("读取超出文件末尾")
        self.pos += n
        return s

    def u8(self):
        b = self.data[self.pos]; self.pos += 1
        return b

    def u16(self):
        v = struct.unpack_from("<H", self.data, self.pos)[0]; self.pos += 2
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.data, self.pos)[0]; self.pos += 4
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.data, self.pos)[0]; self.pos += 4
        return v

    def f32(self):
        v = struct.unpack_from("<f", self.data, self.pos)[0]; self.pos += 4
        return v

    def vec3(self):
        x, y, z = struct.unpack_from("<fff", self.data, self.pos)
        self.pos += 12
        return (x, y, z)

    def bytes(self, n):
        return self.read(n)


# ============================================================
#  小端二进制流写入器
# ============================================================
class WritableStream:
    __slots__ = ("buf",)

    def __init__(self):
        self.buf = bytearray()

    def u8(self, v):
        self.buf.append(v & 0xFF)

    def u16(self, v):
        self.buf.extend(struct.pack("<H", v & 0xFFFF))

    def u32(self, v):
        self.buf.extend(struct.pack("<I", v & 0xFFFFFFFF))

    def i32(self, v):
        self.buf.extend(struct.pack("<i", v))

    def f32(self, v):
        self.buf.extend(struct.pack("<f", v))

    def vec3(self, v):
        self.buf.extend(struct.pack("<fff", v[0], v[1], v[2]))

    def bytes(self, data):
        self.buf.extend(data)

    def data(self):
        return bytes(self.buf)

    def __len__(self):
        return len(self.buf)


# ============================================================
#  meshopt 顶点缓冲解码器 (纯 Python, 移植自 meshoptimizer v1.1)
# ============================================================
K_VERTEX_HEADER = 0xA0
K_VERTEX_BLOCK_SIZE_BYTES = 8192
K_VERTEX_BLOCK_MAX_SIZE = 256
K_BYTE_GROUP_SIZE = 16

_REVERSE_BITS8 = [int(format(i, "08b")[::-1], 2) for i in range(256)]


def _get_vertex_block_size(vertex_size):
    result = (K_VERTEX_BLOCK_SIZE_BYTES // vertex_size) & ~(K_BYTE_GROUP_SIZE - 1)
    return result if result < K_VERTEX_BLOCK_MAX_SIZE else K_VERTEX_BLOCK_MAX_SIZE


def _decode_bytes_group(data, pos, out, out_off, bits):
    if bits == 0:
        for i in range(16):
            out[out_off + i] = 0
        return pos
    if bits == 8:
        out[out_off:out_off + 16] = data[pos:pos + 16]
        return pos + 16

    sentinel = (1 << bits) - 1
    byte_size = 8 // bits
    fixed_count = 16 // byte_size
    var_pos = pos + fixed_count
    idx = out_off

    for fb in range(fixed_count):
        byte = data[pos + fb]
        if bits == 1:
            byte = _REVERSE_BITS8[byte]
        for _ in range(byte_size):
            enc = byte >> (8 - bits)
            byte = (byte << bits) & 0xFF
            if enc == sentinel:
                out[idx] = data[var_pos]
                var_pos += 1
            else:
                out[idx] = enc
            idx += 1
    return var_pos


def _decode_bytes(data, pos, buffer_size, bits_table):
    num_groups = buffer_size // 16
    header_size = (num_groups + 3) // 4
    header = data[pos:pos + header_size]
    pos += header_size
    out = bytearray(buffer_size)
    for g in range(num_groups):
        bitsk = (header[g // 4] >> ((g % 4) * 2)) & 3
        pos = _decode_bytes_group(data, pos, out, g * 16, bits_table[bitsk])
    return out, pos


def _decode_deltas_u8(planes, result, base, vertex_count, vertex_size, last_vertex, k):
    for kb in range(4):
        plane = planes[kb]
        p = last_vertex[k + kb]
        off = base + kb
        for i in range(vertex_count):
            v = plane[i]
            v = (((255 if (v & 1) else 0)) ^ (v >> 1)) + p & 0xFF
            result[off] = v
            p = v
            off += vertex_size


def _decode_deltas_u16(planes, result, base, vertex_count, vertex_size, last_vertex, k):
    for kb in (0, 2):
        p = last_vertex[k + kb] | (last_vertex[k + kb + 1] << 8)
        off = base + kb
        p0 = planes[kb]
        p1 = planes[kb + 1]
        for i in range(vertex_count):
            v = p0[i] | (p1[i] << 8)
            v = (((0xFFFF if (v & 1) else 0)) ^ (v >> 1)) + p & 0xFFFF
            result[off] = v & 0xFF
            result[off + 1] = (v >> 8) & 0xFF
            p = v
            off += vertex_size


def _decode_deltas_u32_xor(planes, result, base, vertex_count, vertex_size, last_vertex, k, rot):
    p = (last_vertex[k] | (last_vertex[k + 1] << 8) |
         (last_vertex[k + 2] << 16) | (last_vertex[k + 3] << 24))
    off = base
    p0, p1, p2, p3 = planes[0], planes[1], planes[2], planes[3]
    if rot == 0:
        for i in range(vertex_count):
            v = (p0[i] | (p1[i] << 8) | (p2[i] << 16) | (p3[i] << 24)) ^ p
            result[off] = v & 0xFF
            result[off + 1] = (v >> 8) & 0xFF
            result[off + 2] = (v >> 16) & 0xFF
            result[off + 3] = (v >> 24) & 0xFF
            p = v
            off += vertex_size
    else:
        rshift = 32 - rot
        for i in range(vertex_count):
            v = p0[i] | (p1[i] << 8) | (p2[i] << 16) | (p3[i] << 24)
            v = (((v << rot) | (v >> rshift)) & 0xFFFFFFFF) ^ p
            result[off] = v & 0xFF
            result[off + 1] = (v >> 8) & 0xFF
            result[off + 2] = (v >> 16) & 0xFF
            result[off + 3] = (v >> 24) & 0xFF
            p = v
            off += vertex_size


def _decode_vertex_block(data, pos, result, vertex_offset, vertex_count,
                         vertex_size, last_vertex, channels, version):
    vertex_count_aligned = (vertex_count + 15) & ~15
    control_size = 0 if version == 0 else vertex_size // 4
    control = data[pos:pos + control_size]
    pos += control_size

    planes = [None, None, None, None]
    for k in range(0, vertex_size, 4):
        ctrl_byte = 0 if version == 0 else control[k // 4]
        for j in range(4):
            ctrl = (ctrl_byte >> (j * 2)) & 3
            if ctrl == 3:
                planes[j] = bytearray(data[pos:pos + vertex_count])
                pos += vertex_count
            elif ctrl == 2:
                planes[j] = bytearray(vertex_count)
            else:
                if version == 0:
                    bits_table = (0, 2, 4, 8)
                else:
                    bits_table = (0, 1, 2, 4) if ctrl == 0 else (1, 2, 4, 8)
                planes[j], pos = _decode_bytes(data, pos, vertex_count_aligned, bits_table)

        channel = 0 if version == 0 else channels[k // 4]
        ctype = channel & 3
        base = vertex_offset * vertex_size + k
        if ctype == 0:
            _decode_deltas_u8(planes, result, base, vertex_count, vertex_size, last_vertex, k)
        elif ctype == 1:
            _decode_deltas_u16(planes, result, base, vertex_count, vertex_size, last_vertex, k)
        else:
            rot = (32 - (channel >> 4)) & 31
            _decode_deltas_u32_xor(planes, result, base, vertex_count, vertex_size, last_vertex, k, rot)

    last_start = vertex_offset * vertex_size + (vertex_count - 1) * vertex_size
    last_vertex[:vertex_size] = result[last_start:last_start + vertex_size]
    return pos


def meshopt_decode_vertex_buffer(vertex_count, vertex_size, data):
    """解码 meshopt 顶点缓冲, 返回 (bytearray, version)。"""
    if vertex_size % 4 != 0:
        raise ValueError("vertex size 必须是 4 的倍数")

    data_end = len(data)
    if data_end < 1:
        raise ValueError("meshopt 数据为空")

    header = data[0]
    if (header & 0xF0) != K_VERTEX_HEADER:
        raise ValueError("meshopt 顶点头不匹配: 0x%02X" % header)
    version = header & 0x0F
    if version > 1:
        raise ValueError("不支持的 meshopt 顶点版本: %d" % version)

    tail_size = vertex_size + (0 if version == 0 else vertex_size // 4)
    tail_size_min = 32 if version == 0 else 24
    tail_size_pad = max(tail_size, tail_size_min)

    if data_end < 1 + tail_size_pad:
        raise ValueError("meshopt 数据过短")

    tail_start = data_end - tail_size
    last_vertex = bytearray(256)
    last_vertex[:vertex_size] = data[tail_start:tail_start + vertex_size]
    if version != 0:
        channels = data[tail_start + vertex_size:tail_start + vertex_size + vertex_size // 4]
    else:
        channels = None

    vertex_block_size = _get_vertex_block_size(vertex_size)
    result = bytearray(vertex_count * vertex_size)
    pos = 1
    vertex_offset = 0
    while vertex_offset < vertex_count:
        block_size = min(vertex_block_size, vertex_count - vertex_offset)
        pos = _decode_vertex_block(data, pos, result, vertex_offset, block_size,
                                   vertex_size, last_vertex, channels, version)
        vertex_offset += block_size
    return result, version


# ============================================================
#  meshopt 顶点缓冲编码器 (纯 Python)
#  支持 version 0 (游戏兼容, bit-packed: bits=0 零组 / bits=8 字面量)
#  和 version 1 (ctrl=3 literal, channels=0)
# ============================================================
def _zigzag8_encode(d):
    """无符号 delta (0-255) -> zigzag 编码字节。"""
    if d < 128:
        return (d << 1) & 0xFF
    else:
        return ((d << 1) ^ 0xFF) & 0xFF


def meshopt_encode_vertex_buffer(vertex_count, vertex_size, vertex_data, version=0):
    """
    编码 meshopt 顶点缓冲。
    version=0: 游戏兼容格式 (bit-packed, bits=0/8)
    version=1: ctrl=3 literal, channels=0
    vertex_data: bytes-like, 长度 = vertex_count * vertex_size。
    """
    if vertex_size % 4 != 0:
        raise ValueError("vertex size 必须是 4 的倍数")
    if len(vertex_data) < vertex_count * vertex_size:
        raise ValueError("vertex_data 过短")

    if version == 0:
        return _encode_v0(vertex_count, vertex_size, vertex_data)
    else:
        return _encode_v1(vertex_count, vertex_size, vertex_data)


def _encode_v0(vertex_count, vertex_size, vertex_data):
    """
    Version 0 编码 (游戏兼容)。
    - 无控制字节, 所有通道均为 channel 0 (u8 zigzag delta)
    - 每 16 字节组用 bit-packed 编码, 自动选择最优 bits: 0/2/4/8
    - bits_table = (0, 2, 4, 8): selector 0→0, 1→2, 2→4, 3→8
    - tail: 仅 first_vertex (vertex_size 字节, 无 channels)
    """
    out = bytearray()
    out.append(K_VERTEX_HEADER | 0)  # 0xA0

    if vertex_count == 0:
        tail = bytearray(vertex_data[:vertex_size]) if len(vertex_data) >= vertex_size else bytearray(vertex_size)
        out.extend(tail)
        return bytes(out)

    vertex_block_size = _get_vertex_block_size(vertex_size)
    tail = bytearray(vertex_data[:vertex_size])
    last_vertex = bytearray(vertex_data[:vertex_size])

    vertex_offset = 0
    while vertex_offset < vertex_count:
        block_size = min(vertex_block_size, vertex_count - vertex_offset)
        vertex_count_aligned = (block_size + 15) & ~15
        num_groups = vertex_count_aligned // 16
        header_size = (num_groups + 3) // 4

        for k in range(0, vertex_size, 4):
            for kb in range(4):
                # zigzag delta for this channel
                deltas = bytearray(block_size)
                p = last_vertex[k + kb]
                for i in range(block_size):
                    v = vertex_data[(vertex_offset + i) * vertex_size + k + kb]
                    d = (v - p) & 0xFF
                    deltas[i] = _zigzag8_encode(d)
                    p = v
                last_vertex[k + kb] = vertex_data[(vertex_offset + block_size - 1) * vertex_size + k + kb]

                header = bytearray(header_size)
                data = bytearray()

                for g in range(num_groups):
                    start = g * 16
                    end = min(start + 16, block_size)
                    # pad group to 16 with zeros
                    vals = [deltas[start + i] if start + i < block_size else 0 for i in range(16)]
                    sel, enc = _encode_group_v0(vals)
                    header[g // 4] |= (sel << ((g % 4) * 2))
                    data.extend(enc)

                out.extend(header)
                out.extend(data)

        vertex_offset += block_size

    out.extend(tail)
    return bytes(out)


def _encode_group_v0(vals):
    """Encode a 16-value group for v0. Returns (selector, encoded_bytes).
    bits_table = (0, 2, 4, 8): sel 0→bits=0, sel 1→bits=2, sel 2→bits=4, sel 3→bits=8
    """
    # bits=0: all zero
    if all(v == 0 for v in vals):
        return 0, b''

    # Compute sizes for each option
    # bits=2: sentinel=3, 4 fixed bytes + 1 var byte per value>=3
    var2 = sum(1 for v in vals if v >= 3)
    size2 = 4 + var2

    # bits=4: sentinel=15, 8 fixed bytes + 1 var byte per value>=15
    var4 = sum(1 for v in vals if v >= 15)
    size4 = 8 + var4

    # bits=8: 16 literal bytes
    size8 = 16

    # Pick smallest
    if size2 <= size4 and size2 <= size8:
        return 1, _pack_bits(vals, 2)
    if size4 <= size8:
        return 2, _pack_bits(vals, 4)
    return 3, bytes(vals)


def _pack_bits(vals, bits):
    """Pack 16 values into bit-packed format (MSB-first, sentinel for overflow).
    Returns fixed_bytes + variable_bytes.
    """
    sentinel = (1 << bits) - 1
    byte_size = 8 // bits       # values per fixed byte
    fixed_count = 16 // byte_size
    fixed = bytearray(fixed_count)
    variable = bytearray()

    for i in range(16):
        v = vals[i]
        byte_idx = i // byte_size
        pos_in_byte = i % byte_size
        shift = 8 - bits * (pos_in_byte + 1)
        if v >= sentinel:
            fixed[byte_idx] |= (sentinel << shift)
            variable.append(v)
        else:
            fixed[byte_idx] |= (v << shift)

    return bytes(fixed) + bytes(variable)


def _encode_v1(vertex_count, vertex_size, vertex_data):
    """Version 1 编码: ctrl=3 literal, channels=0 (备用)。"""
    if vertex_count == 0:
        tail = bytearray(vertex_data[:vertex_size]) + bytearray(vertex_size // 4)
        return bytes([K_VERTEX_HEADER | 1]) + bytes(tail)

    out = bytearray()
    out.append(K_VERTEX_HEADER | 1)  # 0xA1

    vertex_block_size = _get_vertex_block_size(vertex_size)
    control_size = vertex_size // 4
    tail = bytearray(vertex_data[:vertex_size]) + bytearray(control_size)
    last_vertex = bytearray(vertex_data[:vertex_size])

    vertex_offset = 0
    while vertex_offset < vertex_count:
        block_size = min(vertex_block_size, vertex_count - vertex_offset)
        out.extend(b'\xff' * control_size)

        for k in range(0, vertex_size, 4):
            for kb in range(4):
                p = last_vertex[k + kb]
                for i in range(block_size):
                    v = vertex_data[(vertex_offset + i) * vertex_size + k + kb]
                    d = (v - p) & 0xFF
                    out.append(_zigzag8_encode(d))
                    p = v
                last_vertex[k + kb] = vertex_data[(vertex_offset + block_size - 1) * vertex_size + k + kb]

        vertex_offset += block_size

    out.extend(tail)
    return bytes(out)


# ============================================================
#  范数编解码辅助
# ============================================================
def _snorm(b):
    """R8G8B8A8_SNORM 单通道: 有符号字节 -> [-1, 1]"""
    s = b - 256 if b >= 128 else b
    v = s / 127.0
    return v if v >= -1.0 else -1.0


def _unorm(b):
    """R8G8B8A8_UNORM 单通道: 无符号字节 -> [0, 1]"""
    return b / 255.0


def _snorm_encode_byte(v):
    """[-1, 1] -> signed byte.
    Matches JS: round(clamp(v,-1,1)*127), clamp to [-128,127].
    -1.0 -> round(-127) = -127 -> byte 129 (matches original game data).
    """
    v = max(-1.0, min(1.0, v))
    x = round(v * 127)
    x = max(-128, min(127, x))
    return x & 0xFF


def _unorm_encode_byte(v):
    """[0, 1] -> 无符号字节 (匹配 JS: (255*clamp(v,0,1))|0, 截断)"""
    v = max(0.0, min(1.0, v))
    return int(255 * v) & 0xFF


# ============================================================
#  kMaterial 枚举表
# ============================================================
K_MATERIAL = {
    "None": 0, "Transparent": 2, "Void": 3, "Particle": 4,
    "WoodSlippery": 5, "VoidMinor": 6, "WoodPlank": 7,
    "Cliff": 16, "Soil": 17, "CliffLight": 18, "WallDamaged": 19,
    "Wall": 20, "Gold": 21, "Glacier": 22, "TileCeiling": 23,
    "TileFloor": 24, "TileWall": 25, "WallBrick": 26, "SoilWet": 27,
    "CliffWet": 28, "Bone": 29, "Wood": 30, "Ceramics": 31,
    "Sand": 32, "SandWet": 33, "SandLight": 34, "Snow": 35,
    "SandDeep": 36, "Mud": 37,
    "Grass": 48, "GrassWet": 49, "GrassLight": 50, "GrassMoss": 51,
    "Cloth": 52, "Cloud": 80,
}

K_MATERIAL_REVERSE = {v: k for k, v in K_MATERIAL.items()}


def _material_name_to_id(name):
    """材质名 -> ID, 匹配 JS TriangleMeshMaterial.getId()。"""
    if not name or not name.startswith("kMaterial_"):
        return 0
    return K_MATERIAL.get(name[10:], 0)


def _material_from_filename(filepath):
    """从文件名提取材质名。
    匹配顺序: 精确匹配 > 后缀分隔 > 包含匹配。
    例: 'output_Cliff.obj' -> 'Cliff', 'Cliff.obj' -> 'Cliff', 'my_Grass_test.obj' -> 'Grass'
    """
    name = os.path.splitext(os.path.basename(filepath))[0]
    # 精确匹配
    if name in K_MATERIAL:
        return name
    # 分隔符匹配 (从后往前找, 优先后缀)
    for sep in ('_', '-', ' '):
        parts = name.split(sep)
        for part in reversed(parts):
            if part in K_MATERIAL:
                return part
    # 包含匹配
    for mat_name in sorted(K_MATERIAL.keys(), key=len, reverse=True):
        if mat_name in name:
            return mat_name
    return "None"


def _is_reversible_obj(filepath):
    """检测 OBJ 文件是否为可逆格式 (含 @MESHES_META 元数据块)。

    从文件末尾向前分块搜索, 确保即使元数据块很大也能找到 META_BEGIN 标记。
    """
    marker = META_BEGIN
    marker_len = len(marker)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            # 小文件: 直接全读
            f.seek(0, 2)
            size = f.tell()
            if size <= 65536:
                f.seek(0)
                return marker in f.read()

            # 大文件: 从末尾向前分块搜索
            # META_BEGIN 在元数据块开头, 元数据块在文件末尾
            # 每个顶点的 @vraw 行约 80 字节, 大量顶点时元数据块可能很大
            chunk_size = 65536  # 每次读 64KB
            overlap = marker_len + 10  # 重叠区, 防止标记跨块

            pos = size
            while pos > 0:
                read_start = max(0, pos - chunk_size)
                read_len = pos - read_start
                f.seek(read_start)
                block = f.read(read_len)
                if marker in block:
                    return True
                if read_start == 0:
                    break
                pos = read_start + overlap  # 重叠, 防止标记跨块
            return False
    except Exception:
        return False


# ============================================================
#  .meshes 结构
# ============================================================
VERTEX_SIZE = 36  # pos(12) + normal(4) + material(8) + input2/3/4(4*3)

MAGIC_LVL0 = 0x304C564C  # "LVL0"
SUPPORTED_VERSIONS = (0x3C, 0x3D)

FLT_MAX = struct.unpack("<f", b'\xff\xff\x7f\x7f')[0]

LOD0_FIXED_BYTES = bytes.fromhex("1B000100C0010000000000000000000000")


class LevelGeoVertex:
    """36 字节顶点, 同时存储原始字节和解码值。"""
    __slots__ = ("raw", "pos", "normal", "normal_w",
                 "material", "weights", "in2", "in3", "in4")

    @classmethod
    def unpack_all(cls, raw_buffer, count):
        """从解压后的原始字节 (count*36) 解析全部顶点。"""
        verts = [None] * count
        off = 0
        for i in range(count):
            v = cls()
            v.raw = bytes(raw_buffer[off:off + VERTEX_SIZE])
            v.pos = struct.unpack_from("<fff", v.raw, 0)
            n = struct.unpack_from("<I", v.raw, 12)[0]
            v.normal = (_snorm(n & 0xFF), _snorm((n >> 8) & 0xFF), _snorm((n >> 16) & 0xFF))
            v.normal_w = _snorm((n >> 24) & 0xFF)
            v.material = tuple(v.raw[16:20])
            v.weights = tuple(b / 255.0 for b in v.raw[20:24])
            v.in2 = tuple(b / 255.0 for b in v.raw[24:28])
            v.in3 = tuple(b / 255.0 for b in v.raw[28:32])
            v.in4 = tuple(b / 255.0 for b in v.raw[32:36])
            verts[i] = v
            off += VERTEX_SIZE
        return verts

    @classmethod
    def from_raw(cls, raw_bytes):
        """从 36 字节原始数据创建。"""
        v = cls()
        v.raw = bytes(raw_bytes)
        v.pos = struct.unpack_from("<fff", v.raw, 0)
        n = struct.unpack_from("<I", v.raw, 12)[0]
        v.normal = (_snorm(n & 0xFF), _snorm((n >> 8) & 0xFF), _snorm((n >> 16) & 0xFF))
        v.normal_w = _snorm((n >> 24) & 0xFF)
        v.material = tuple(v.raw[16:20])
        v.weights = tuple(b / 255.0 for b in v.raw[20:24])
        v.in2 = tuple(b / 255.0 for b in v.raw[24:28])
        v.in3 = tuple(b / 255.0 for b in v.raw[28:32])
        v.in4 = tuple(b / 255.0 for b in v.raw[32:36])
        return v

    @classmethod
    def from_values(cls, pos, normal, material_ids, material_weights, in2, in3, in4):
        """从解码值创建 (用于 obj->meshes)。"""
        raw = bytearray(VERTEX_SIZE)
        struct.pack_into("<fff", raw, 0, pos[0], pos[1], pos[2])
        nx = _snorm_encode_byte(normal[0])
        ny = _snorm_encode_byte(normal[1])
        nz = _snorm_encode_byte(normal[2])
        nw = _snorm_encode_byte(normal[3]) if len(normal) > 3 else 0
        struct.pack_into("<I", raw, 12, nx | (ny << 8) | (nz << 16) | (nw << 24))
        for i in range(4):
            raw[16 + i] = material_ids[i] if i < len(material_ids) else 0
        for i in range(4):
            raw[20 + i] = _unorm_encode_byte(material_weights[i]) if i < len(material_weights) else 0
        for i in range(4):
            raw[24 + i] = _unorm_encode_byte(in2[i]) if i < len(in2) else 0
            raw[28 + i] = _unorm_encode_byte(in3[i]) if i < len(in3) else 0
            raw[32 + i] = _unorm_encode_byte(in4[i]) if i < len(in4) else 0
        return cls.from_raw(raw)


class LevelGeoChunk:
    __slots__ = ("idx_start", "vtx_start", "subchunk_start",
                 "idx_count", "vtx_count", "subchunk_count",
                 "min", "max", "pad")

    @classmethod
    def from_stream(cls, s):
        c = cls()
        c.idx_start = s.u32()
        c.vtx_start = s.u32()
        c.subchunk_start = s.u32()
        c.idx_count = s.u16()
        c.vtx_count = s.u8()
        c.subchunk_count = s.u8()
        c.min = s.vec3()
        c.max = s.vec3()
        c.pad = (s.u32(), s.u32(), s.u32(), s.u32())
        return c

    def to_stream(self, s):
        s.u32(self.idx_start)
        s.u32(self.vtx_start)
        s.u32(self.subchunk_start)
        s.u16(self.idx_count)
        s.u8(self.vtx_count)
        s.u8(self.subchunk_count)
        s.vec3(self.min)
        s.vec3(self.max)
        for p in (self.pad if self.pad else (0, 0, 0, 0)):
            s.u32(p)


class LevelGeoSubchunk:
    __slots__ = ("material_id", "triangle_count", "vtx_count",
                 "triangle_start", "triangle_end", "vtx_start", "vtx_end")

    @classmethod
    def from_stream(cls, s):
        sc = cls()
        sc.material_id = s.u8()
        sc.triangle_count = s.u8()
        sc.vtx_count = s.u8()
        sc.triangle_start = s.u8()
        sc.triangle_end = s.u8()
        sc.vtx_start = s.u8()
        sc.vtx_end = s.u8()
        s.u8()  # padding
        return sc

    def to_stream(self, s):
        # u8 溢出检查: subchunk 所有字段都是 u8 (0-255)
        # 超过 255 会导致游戏读取错误数据, 渲染丢顶点
        for name, val in [
            ("material_id", self.material_id),
            ("triangle_count", self.triangle_count),
            ("vtx_count", self.vtx_count),
            ("triangle_start", self.triangle_start),
            ("triangle_end", self.triangle_end),
            ("vtx_start", self.vtx_start),
            ("vtx_end", self.vtx_end),
        ]:
            if val < 0 or val > 255:
                print("警告: subchunk.%s = %d 超出 u8 范围 (0-255), 已截断" % (name, val))
                val = max(0, min(255, val))
                setattr(self, name, val)
        s.u8(self.material_id)
        s.u8(self.triangle_count)
        s.u8(self.vtx_count)
        s.u8(self.triangle_start)
        s.u8(self.triangle_end)
        s.u8(self.vtx_start)
        s.u8(self.vtx_end)
        s.u8(0)  # padding


class LevelGeo:
    __slots__ = ("index_count", "vertex_count", "chunk_count",
                 "cloud_chunk_count", "subchunk_count",
                 "vertices", "local_indices", "chunks", "subchunks",
                 "meshopt_version")

    @classmethod
    def from_buffer(cls, buf):
        s = BinaryStream(buf)
        geo = cls()
        geo.index_count = s.u32()
        geo.vertex_count = s.u32()
        geo.chunk_count = s.u32()
        geo.cloud_chunk_count = s.u32()
        geo.subchunk_count = s.u32()

        if geo.vertex_count > 0:
            compressed_size = s.u32()
            compressed = s.bytes(compressed_size)
            raw, mv = meshopt_decode_vertex_buffer(geo.vertex_count, VERTEX_SIZE, compressed)
            geo.meshopt_version = mv
            geo.vertices = LevelGeoVertex.unpack_all(raw, geo.vertex_count)
        else:
            geo.meshopt_version = 0
            geo.vertices = []

        geo.local_indices = list(s.bytes(geo.index_count)) if geo.index_count > 0 else []

        total_chunks = geo.chunk_count + geo.cloud_chunk_count
        geo.chunks = [LevelGeoChunk.from_stream(s) for _ in range(total_chunks)]

        geo.subchunks = [LevelGeoSubchunk.from_stream(s) for _ in range(geo.subchunk_count)]
        return geo

    def to_buffer(self):
        s = WritableStream()
        s.u32(self.index_count)
        s.u32(self.vertex_count)
        s.u32(self.chunk_count)
        s.u32(self.cloud_chunk_count)
        s.u32(self.subchunk_count)

        # 顶点缓冲 (meshopt 压缩)
        if self.vertex_count > 0 and self.vertices:
            raw = bytearray()
            for v in self.vertices:
                raw.extend(v.raw)
            compressed = meshopt_encode_vertex_buffer(
                self.vertex_count, VERTEX_SIZE, bytes(raw),
                getattr(self, 'meshopt_version', 0))
            s.u32(len(compressed))
            s.bytes(compressed)

        # 索引
        for idx in self.local_indices:
            s.u8(idx)

        # 分块
        for chunk in self.chunks:
            chunk.to_stream(s)

        # 材质子区间
        for sc in self.subchunks:
            sc.to_stream(s)

        return s.data()


class TocSegment:
    __slots__ = ("type", "offset", "length")

    def __init__(self, type_, offset, length):
        self.type = type_
        self.offset = offset
        self.length = length


def _parse_toc(buf):
    s = BinaryStream(buf)
    count = s.u32()
    toc = {}
    for _ in range(count):
        type_raw = s.bytes(4)
        type_name = type_raw.rstrip(b"\x00").decode("ascii", "replace")
        offset = s.u32()
        length = s.u32()
        toc[type_name] = TocSegment(type_name, offset, length)
    return toc


def _write_toc(segments):
    """segments: list of (type_name, offset, length). 返回 100 字节 TOC。"""
    s = WritableStream()
    s.u32(len(segments))
    seg_data = bytearray(0x60)  # 96 bytes, zero-padded
    for i, (name, offset, length) in enumerate(segments):
        name_bytes = name.encode("ascii")[:4].ljust(4, b'\x00')
        off = i * 12
        seg_data[off:off + 4] = name_bytes
        struct.pack_into("<I", seg_data, off + 4, offset)
        struct.pack_into("<I", seg_data, off + 8, length)
    s.bytes(seg_data)
    return s.data()


class LevelMeshes:
    __slots__ = ("version", "max_pos", "min_pos", "toc", "desc", "desc_raw", "lod_raw", "geo")

    @classmethod
    def from_file_buffer(cls, buffer):
        s = BinaryStream(buffer)
        magic = s.u32()
        if magic != MAGIC_LVL0:
            raise ValueError("不是合法的 .meshes 文件 (魔数: 0x%08X)" % magic)
        version = s.u32()
        if version not in SUPPORTED_VERSIONS:
            raise ValueError("不支持的版本: 0x%X" % version)

        m = cls()
        m.version = version

        toc_buf = s.bytes(0x64)
        m.toc = _parse_toc(toc_buf)

        s.u32()  # padding
        m.max_pos = s.vec3()
        m.min_pos = s.vec3()

        # DESC 段
        seg = m.toc.get("DESC")
        if seg:
            m.desc_raw = buffer[seg.offset:seg.offset + seg.length]
            m.desc = _parse_desc(m.desc_raw)
        else:
            m.desc_raw = None
            m.desc = None

        # LOD0 段
        seg = m.toc.get("LOD0")
        if seg:
            m.lod_raw = buffer[seg.offset:seg.offset + seg.length]
        else:
            m.lod_raw = None

        # GEO0 段
        seg = m.toc.get("GEO0")
        if seg:
            m.geo = LevelGeo.from_buffer(buffer[seg.offset:seg.offset + seg.length])
        else:
            m.geo = None
        return m

    def to_file_buffer(self):
        """序列化为 .meshes 二进制。"""
        header_len = 4 + 4 + 100 + 4 + 12 + 12  # 136

        # 构建内容流 (DESC + LOD0 + GEO0)
        content = WritableStream()
        segments = []
        cursor = 0

        # DESC
        if self.desc_raw is not None:
            content.bytes(self.desc_raw)
            segments.append(("DESC", cursor + header_len, len(self.desc_raw)))
            cursor = len(content)

        # LOD0
        lod_data = self.lod_raw if self.lod_raw is not None else LOD0_FIXED_BYTES
        content.bytes(lod_data)
        segments.append(("LOD0", cursor + header_len, len(lod_data)))
        cursor = len(content)

        # GEO0
        if self.geo is not None:
            geo_data = self.geo.to_buffer()
            content.bytes(geo_data)
            segments.append(("GEO0", cursor + header_len, len(geo_data)))
            cursor = len(content)

        # 构建完整文件
        out = WritableStream()
        out.u32(MAGIC_LVL0)
        out.u32(self.version if self.version in SUPPORTED_VERSIONS else 0x3C)
        out.bytes(_write_toc(segments))
        out.u32(0)  # padding
        # 原项目 that-sky-level 始终写 FLT_MAX, 游戏不依赖此值做渲染
        out.vec3((FLT_MAX, FLT_MAX, FLT_MAX))
        out.vec3((-FLT_MAX, -FLT_MAX, -FLT_MAX))
        out.bytes(content.data())
        return out.data()


# ============================================================
#  NBT 读取 (小端/Bedrock 风格, 用于 DESC 元数据)
# ============================================================
def _parse_desc(buf):
    try:
        root, _ = _nbt_read_payload(buf, buf[0], 1 + _nbt_skip_name(buf, 1))
        return root if isinstance(root, dict) else {}
    except Exception:
        return {}


def _nbt_skip_name(buf, pos):
    nlen = struct.unpack_from("<H", buf, pos)[0]
    return 2 + nlen


def _nbt_read_name(buf, pos):
    nlen = struct.unpack_from("<H", buf, pos)[0]
    pos += 2
    name = buf[pos:pos + nlen].decode("utf-8", "replace")
    return name, pos + nlen


def _nbt_read_payload(buf, tag_type, pos):
    if tag_type == 1:
        return buf[pos] - 256 if buf[pos] >= 128 else buf[pos], pos + 1
    if tag_type == 2:
        return struct.unpack_from("<h", buf, pos)[0], pos + 2
    if tag_type == 3:
        return struct.unpack_from("<i", buf, pos)[0], pos + 4
    if tag_type == 4:
        return struct.unpack_from("<q", buf, pos)[0], pos + 8
    if tag_type == 7:
        n = struct.unpack_from("<i", buf, pos)[0]; pos += 4
        return buf[pos:pos + n], pos + n
    if tag_type == 8:
        n = struct.unpack_from("<H", buf, pos)[0]; pos += 2
        return buf[pos:pos + n].decode("utf-8", "replace"), pos + n
    if tag_type == 9:
        et = buf[pos]; pos += 1
        n = struct.unpack_from("<i", buf, pos)[0]; pos += 4
        out = []
        for _ in range(n):
            v, pos = _nbt_read_payload(buf, et, pos)
            out.append(v)
        return out, pos
    if tag_type == 10:
        d = {}
        while True:
            ct = buf[pos]; pos += 1
            if ct == 0:
                break
            name, pos = _nbt_read_name(buf, pos)
            v, pos = _nbt_read_payload(buf, ct, pos)
            d[name] = v
        return d, pos
    if tag_type == 11:
        n = struct.unpack_from("<i", buf, pos)[0]; pos += 4
        return list(struct.unpack_from("<%di" % n, buf, pos)), pos + 4 * n
    raise ValueError("不支持的 NBT 标签类型: %d" % tag_type)


# ============================================================
#  NBT 写入 (小端/Bedrock 风格, 用于 DESC 元数据)
# ============================================================
def _nbt_write_desc(desc):
    """将 desc 字典序列化为 NBT 二进制 (匹配 JS LevelDesc.toStream 顺序)。"""
    out = bytearray()
    # 根 compound
    out.append(10)  # TAG_Compound
    out.extend(struct.pack("<H", 0))  # 根名长度 = 0

    # timeStamp (TAG_Int)
    _nbt_write_tag_header(out, "timeStamp", 3)
    out.extend(struct.pack("<i", desc.get("timeStamp", 0)))

    # fileName (TAG_String)
    _nbt_write_tag_header(out, "fileName", 8)
    _nbt_write_string_payload(out, desc.get("fileName", ""))

    # editor (TAG_String)
    _nbt_write_tag_header(out, "editor", 8)
    _nbt_write_string_payload(out, desc.get("editor", ""))

    # editorVersion (TAG_List of TAG_Int)
    _nbt_write_tag_header(out, "editorVersion", 9)
    ev = desc.get("editorVersion", [1, 0, 0])
    out.append(3)  # element type = TAG_Int
    out.extend(struct.pack("<i", len(ev)))
    for v in ev:
        out.extend(struct.pack("<i", v))

    # engineVersion (TAG_List of TAG_Int)
    _nbt_write_tag_header(out, "engineVersion", 9)
    gv = desc.get("engineVersion", [0, 32, 2])
    out.append(3)
    out.extend(struct.pack("<i", len(gv)))
    for v in gv:
        out.extend(struct.pack("<i", v))

    out.append(0)  # TAG_End
    return bytes(out)


def _nbt_write_tag_header(out, name, tag_type):
    out.append(tag_type)
    name_bytes = name.encode("utf-8")
    out.extend(struct.pack("<H", len(name_bytes)))
    out.extend(name_bytes)


def _nbt_write_string_payload(out, value):
    value_bytes = value.encode("utf-8")
    out.extend(struct.pack("<H", len(value_bytes)))
    out.extend(value_bytes)


# ============================================================
#  OBJ 生成 (touchObject)
# ============================================================
def _fmt(f):
    """对齐 JS Number.toString()。"""
    if f != f:
        return "0"
    if f == float("inf"):
        return "Infinity"
    if f == float("-inf"):
        return "-Infinity"
    if f == 0:
        return "0"
    neg = f < 0
    af = -f if neg else f
    s = _js_num_str(af)
    return ("-" + s) if neg else s


def _js_num_str(af):
    r = repr(af)
    if "e" in r:
        mant, exps = r.split("e")
        exp = int(exps)
        if "." in mant:
            intp, frac = mant.split(".")
        else:
            intp, frac = mant, ""
        digs = (intp + frac).rstrip("0") or "0"
        k = exp + len(intp) - 1
    else:
        if "." in r:
            intp, frac = r.split(".")
        else:
            intp, frac = r, ""
        if intp != "0" and intp != "":
            digs = (intp + frac).rstrip("0") or "0"
            k = len(intp) - 1
        else:
            idx = 0
            while idx < len(frac) and frac[idx] == "0":
                idx += 1
            if idx == len(frac):
                return "0"
            digs = frac[idx:].rstrip("0") or "0"
            k = -(idx + 1)

    n = k + 1
    if -6 < n <= 21:
        point = k + 1
        if point <= 0:
            return "0." + "0" * (-point) + digs
        if point >= len(digs):
            return digs + "0" * (point - len(digs))
        return digs[:point] + "." + digs[point:]
    else:
        exp = k
        mant = digs[0] + ("." + digs[1:] if len(digs) > 1 else "")
        return mant + "e" + (("+" if exp >= 0 else "-") + str(abs(exp)))


def touch_object(meshes, merge=False):
    """根据 LevelGeo 生成 OBJ 文本。"""
    geo = meshes.geo
    out = []
    ap = out.append

    for v in geo.vertices:
        ap("v %s %s %s\n" % (_fmt(v.pos[0]), _fmt(v.pos[1]), _fmt(v.pos[2])))
    ap("\n")

    for v in geo.vertices:
        n = v.normal
        ap("vn %s %s %s\n" % (_fmt(n[0]), _fmt(n[1]), _fmt(n[2])))
    ap("\n")

    li = geo.local_indices
    chunks = geo.chunks
    if merge:
        ap("o Chunks\n")

    for i in range(geo.chunk_count):
        if not merge:
            ap("o Chunk_%d\n" % i)
        chunk = chunks[i]
        idx_start = chunk.idx_start
        vtx_start = chunk.vtx_start
        idx_count = chunk.idx_count
        j = 0
        while j < idx_count:
            a = vtx_start + li[idx_start + j] + 1
            b = vtx_start + li[idx_start + j + 1] + 1
            c = vtx_start + li[idx_start + j + 2] + 1
            ap("f %d//%d %d//%d %d//%d\n" % (a, a, b, b, c, c))
            j += 3

    return "".join(out)


# ============================================================
#  可逆 OBJ: 标准 OBJ 几何 + 嵌入完整 meshes 元数据
#  建模软件可正常读取 v/vn/f; 转换器读取 # @ 注释完整还原 .meshes
# ============================================================
META_BEGIN = "# @MESHES_META_BEGIN"
META_END = "# @MESHES_META_END"


def _write_obj_meta(out_list, meshes, geo):
    """将完整 meshes 元数据写入 # @ 注释块, 追加到 out_list。"""
    ap = out_list.append
    ap(META_BEGIN + "\n")

    # ---- 版本和包围盒 ----
    ap("# @version 0x%X\n" % meshes.version)
    if geo:
        ap("# @meshopt_version %d\n" % getattr(geo, 'meshopt_version', 0))
    ap("# @bounds_max %s %s %s\n" % (
        _fmt(meshes.max_pos[0]), _fmt(meshes.max_pos[1]), _fmt(meshes.max_pos[2])))
    ap("# @bounds_min %s %s %s\n" % (
        _fmt(meshes.min_pos[0]), _fmt(meshes.min_pos[1]), _fmt(meshes.min_pos[2])))

    # ---- DESC / LOD0 原始字节 (hex, 保证精确还原) ----
    if meshes.desc_raw is not None:
        ap("# @desc_raw %s\n" % meshes.desc_raw.hex())
    if meshes.lod_raw is not None:
        ap("# @lod0_raw %s\n" % meshes.lod_raw.hex())

    if not geo:
        ap(META_END + "\n")
        return

    # ---- 计数 ----
    ap("# @counts %d %d %d %d %d\n" % (
        geo.vertex_count, geo.index_count,
        geo.chunk_count, geo.cloud_chunk_count, geo.subchunk_count))

    # ---- 顶点原始字节 (36 字节/顶点, hex, 保证字节级无损) ----
    for i, v in enumerate(geo.vertices):
        ap("# @vraw %d %s\n" % (i, v.raw.hex()))

    # ---- 分块 (含地形块 + 云块) ----
    for i, c in enumerate(geo.chunks):
        pad = c.pad if c.pad else (0, 0, 0, 0)
        ap("# @chunk %d %d %d %d %d %d %d %s %s %s %s %s %s %d %d %d %d\n" % (
            i, c.idx_start, c.idx_count, c.vtx_start, c.vtx_count,
            c.subchunk_start, c.subchunk_count,
            _fmt(c.min[0]), _fmt(c.min[1]), _fmt(c.min[2]),
            _fmt(c.max[0]), _fmt(c.max[1]), _fmt(c.max[2]),
            pad[0], pad[1], pad[2], pad[3]))

    # ---- 材质子区间 ----
    for i, sc in enumerate(geo.subchunks):
        ap("# @subchunk %d %d %d %d %d %d %d %d\n" % (
            i, sc.material_id, sc.triangle_count, sc.vtx_count,
            sc.triangle_start, sc.triangle_end, sc.vtx_start, sc.vtx_end))

    # ---- 索引 (分组输出, 每行最多 256 个) ----
    li = geo.local_indices
    for i in range(0, len(li), 256):
        group = li[i:i + 256]
        ap("# @indices %s\n" % " ".join(str(x) for x in group))

    ap(META_END + "\n")


def meshes_to_obj_full(meshes):
    """生成可逆 OBJ: 标准 OBJ 几何 + 嵌入完整 meshes 元数据。

    - 建模软件 (Blender/Maya 等) 可正常读取 v/vn/f 几何数据
    - 转换器读取 # @ 注释块可完整还原 .meshes (字节级无损)
    - 等价于 meshes→json 的信息量, 但以 OBJ 格式呈现
    """
    geo = meshes.geo
    out = []
    ap = out.append

    # ---- 文件头 ----
    ap("# ============================================================\n")
    ap("# That Sky Level Meshes OBJ (可逆格式)\n")
    ap("# 版本: 0x%X\n" % meshes.version)
    ap("# 此文件包含标准 OBJ 几何 + 嵌入的 .meshes 元数据\n")
    ap("# 建模软件可正常读取 v/vn/f; 转换器读取 # @ 注释完整还原\n")
    ap("# ============================================================\n\n")

    if not geo or geo.vertex_count == 0:
        ap("# (无几何数据)\n")
        _write_obj_meta(out, meshes, geo)
        return "".join(out)

    # ---- 顶点位置 ----
    for v in geo.vertices:
        ap("v %s %s %s\n" % (_fmt(v.pos[0]), _fmt(v.pos[1]), _fmt(v.pos[2])))
    ap("\n")

    # ---- 顶点法线 ----
    for v in geo.vertices:
        n = v.normal
        ap("vn %s %s %s\n" % (_fmt(n[0]), _fmt(n[1]), _fmt(n[2])))
    ap("\n")

    # ---- 面 (按 chunk + subchunk 材质分组输出) ----
    li = geo.local_indices
    chunks = geo.chunks

    for ci in range(geo.chunk_count):
        chunk = chunks[ci]
        ap("o Chunk_%d\n" % ci)
        idx_start = chunk.idx_start
        vtx_start = chunk.vtx_start
        idx_count = chunk.idx_count

        if chunk.subchunk_count > 0:
            # 按 subchunk 材质区间输出面
            for si in range(chunk.subchunk_count):
                sc = geo.subchunks[chunk.subchunk_start + si]
                mat_name = K_MATERIAL_REVERSE.get(sc.material_id, "Unknown_%d" % sc.material_id)
                ap("usemtl %s\n" % mat_name)
                for tri in range(sc.triangle_start, sc.triangle_start + sc.triangle_count):
                    j = tri * 3
                    if j + 2 >= idx_count:
                        break
                    a = vtx_start + li[idx_start + j] + 1
                    b = vtx_start + li[idx_start + j + 1] + 1
                    c = vtx_start + li[idx_start + j + 2] + 1
                    ap("f %d//%d %d//%d %d//%d\n" % (a, a, b, b, c, c))
        else:
            # 无 subchunk, 直接输出所有面
            j = 0
            while j < idx_count:
                a = vtx_start + li[idx_start + j] + 1
                b = vtx_start + li[idx_start + j + 1] + 1
                c = vtx_start + li[idx_start + j + 2] + 1
                ap("f %d//%d %d//%d %d//%d\n" % (a, a, b, b, c, c))
                j += 3
        ap("\n")

    # ---- 元数据块 (用于精确还原) ----
    _write_obj_meta(out, meshes, geo)

    return "".join(out)


# ============================================================
#  多材质 OBJ 拆分输出
# ============================================================
def touch_object_multi(meshes, output_path, use_subchunk=False):
    """
    按材质拆分输出多个 OBJ 文件。

    顶点归属: 取权重最大的材质槽作为主材质。
    面归属: 3 个顶点主材质的多数投票, 平局取权重最高者。

    use_subchunk=True 时, 使用 subchunk 的材质区间数据 (游戏原始分配)。

    output_path: 基础路径, 实际输出为 output_path_MaterialName.obj
    返回: [(material_id, material_name, file_path, vertex_count, face_count), ...]
    """
    geo = meshes.geo
    if not geo or geo.vertex_count == 0:
        print("错误: 无几何数据")
        return []

    li = geo.local_indices

    # ---- 1. 计算每个顶点的主材质 ----
    vertex_dominant = []  # (material_id, weight) per vertex
    for v in geo.vertices:
        best_mat = 0
        best_w = -1.0
        for j in range(4):
            w = v.weights[j]
            if w > best_w:
                best_w = w
                best_mat = v.material[j]
        vertex_dominant.append((best_mat, best_w))

    # ---- 2. 收集每个面及其材质 ----
    face_materials = []  # (material_id, (a, b, c)) 全局顶点索引

    for ci in range(geo.chunk_count):
        chunk = geo.chunks[ci]
        idx_start = chunk.idx_start
        vtx_start = chunk.vtx_start

        if use_subchunk:
            # 使用 subchunk 材质区间 (游戏原始分配)
            for si in range(chunk.subchunk_count):
                sc = geo.subchunks[chunk.subchunk_start + si]
                mat_id = sc.material_id
                for tri in range(sc.triangle_start,
                                 sc.triangle_start + sc.triangle_count):
                    j = tri * 3
                    if j + 2 >= chunk.idx_count:
                        break
                    a = vtx_start + li[idx_start + j]
                    b = vtx_start + li[idx_start + j + 1]
                    c = vtx_start + li[idx_start + j + 2]
                    face_materials.append((mat_id, (a, b, c)))
        else:
            # 使用顶点权重投票
            num_tris = chunk.idx_count // 3
            for t in range(num_tris):
                j = t * 3
                a = vtx_start + li[idx_start + j]
                b = vtx_start + li[idx_start + j + 1]
                c = vtx_start + li[idx_start + j + 2]

                # 多数投票
                mat_votes = {}
                mat_weights = {}
                for vi in (a, b, c):
                    mid, w = vertex_dominant[vi]
                    mat_votes[mid] = mat_votes.get(mid, 0) + 1
                    if mid not in mat_weights or w > mat_weights[mid]:
                        mat_weights[mid] = w

                # 票数最多, 平局取权重最高
                best_mat = max(mat_votes.keys(),
                               key=lambda m: (mat_votes[m], mat_weights[m]))
                face_materials.append((best_mat, (a, b, c)))

    # ---- 3. 按材质分组 ----
    material_groups = {}  # mat_id -> {"faces": [...], "vertices": set()}
    for mat_id, (a, b, c) in face_materials:
        if mat_id not in material_groups:
            material_groups[mat_id] = {"faces": [], "vertices": set()}
        material_groups[mat_id]["faces"].append((a, b, c))
        material_groups[mat_id]["vertices"].update([a, b, c])

    # ---- 4. 输出每个材质的 OBJ ----
    results = []
    base_path = output_path
    if base_path.endswith(".obj"):
        base_path = base_path[:-4]

    for mat_id in sorted(material_groups.keys()):
        group = material_groups[mat_id]
        mat_name = K_MATERIAL_REVERSE.get(mat_id, "Unknown_%d" % mat_id)

        # 顶点重映射 (全局 -> 局部)
        vtx_list = sorted(group["vertices"])
        vtx_map = {gvi: li for li, gvi in enumerate(vtx_list)}

        out_path = "%s_%s.obj" % (base_path, mat_name)
        lines = []
        ap = lines.append

        ap("# Material: %s (ID=%d)\n" % (mat_name, mat_id))
        ap("# Vertices: %d  Faces: %d\n" % (len(vtx_list), len(group["faces"])))
        ap("o %s\n" % mat_name)

        for gvi in vtx_list:
            v = geo.vertices[gvi]
            ap("v %s %s %s\n" % (_fmt(v.pos[0]), _fmt(v.pos[1]), _fmt(v.pos[2])))

        for gvi in vtx_list:
            v = geo.vertices[gvi]
            n = v.normal
            ap("vn %s %s %s\n" % (_fmt(n[0]), _fmt(n[1]), _fmt(n[2])))

        for a, b, c in group["faces"]:
            la = vtx_map[a] + 1
            lb = vtx_map[b] + 1
            lc = vtx_map[c] + 1
            ap("f %d//%d %d//%d %d//%d\n" % (la, la, lb, lb, lc, lc))

        with open(out_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        results.append((mat_id, mat_name, out_path,
                        len(vtx_list), len(group["faces"])))
        print("  %s (ID=%d): %d 顶点, %d 面 -> %s" % (
            mat_name, mat_id, len(vtx_list), len(group["faces"]), out_path))

    return results


# ============================================================
#  OBJ 解析器 (移植自 wavefront.js parseObj)
# ============================================================
class _ObjVertex:
    """OBJ 解析后的顶点 (去重后)。"""
    __slots__ = ("pos", "normal", "nearby", "faces")

    def __init__(self, pos, normal):
        self.pos = pos
        self.normal = normal
        self.nearby = set()  # 共享同一 position 的顶点索引集合
        self.faces = []      # 包含此顶点的面索引列表 (插入序)


class _ObjFace:
    """OBJ 解析后的三角面。"""
    __slots__ = ("indices", "material_id")

    def __init__(self, indices, material_id):
        self.indices = indices
        self.material_id = material_id


def parse_obj(obj_text):
    """
    解析 OBJ 文本, 返回 (vertices, faces)。
    vertices: list of _ObjVertex
    faces: list of _ObjFace (已三角化)
    """
    positions = []
    normals = []
    position_refs = []  # 每个位置的顶点索引集合

    current_mtl = ""
    vertex_map = {}  # (posIdx, normIdx) -> vertex index
    vertices = []
    faces = []

    lines = obj_text.split("\n")
    for line in lines:
        line = line.strip()
        if not line or line[0] == "#":
            continue

        parts = line.split()
        keyword = parts[0]

        if keyword == "v":
            position_refs.append(set())
            positions.append((float(parts[1]), float(parts[2]), float(parts[3])))

        elif keyword == "vn":
            normals.append((float(parts[1]), float(parts[2]), float(parts[3])))

        elif keyword == "usemtl":
            current_mtl = parts[1] if len(parts) > 1 else ""

        elif keyword == "f":
            face_indices = []
            material_id = _material_name_to_id(current_mtl)

            for j in range(1, len(parts)):
                token = parts[j]
                sub = token.split("/")
                pos_idx = int(sub[0])
                norm_idx = None

                if len(sub) >= 3 and sub[2] != "":
                    norm_idx = int(sub[2])

                if pos_idx < 0:
                    pos_idx = len(positions) + 1 + pos_idx
                if norm_idx is not None and norm_idx < 0:
                    norm_idx = len(normals) + 1 + norm_idx

                norm_key = norm_idx if norm_idx is not None else "none"
                key = (pos_idx, norm_key)

                if key not in vertex_map:
                    pos = positions[pos_idx - 1]
                    pos_ref = position_refs[pos_idx - 1]
                    if norm_idx is not None and norm_idx - 1 < len(normals) and norm_idx >= 1:
                        norm = normals[norm_idx - 1]
                    else:
                        norm = (0.0, 1.0, 0.0)

                    vtx = _ObjVertex(pos, norm)
                    vtx_idx = len(vertices)
                    vertex_map[key] = vtx_idx
                    pos_ref.add(vtx_idx)
                    vtx.nearby = pos_ref  # 共享同一个 set 引用
                    vertices.append(vtx)

                face_indices.append(vertex_map[key])

            # 扇形三角化
            for j in range(1, len(face_indices) - 1):
                faces.append(_ObjFace(
                    [face_indices[0], face_indices[j], face_indices[j + 1]],
                    material_id
                ))

    # 构建 vertex.faces
    for fi, face in enumerate(faces):
        for vi in face.indices:
            vertices[vi].faces.append(fi)

    return vertices, faces


# ============================================================
#  邻接分块算法 (移植自 adjacency.js LevelCvtAdjacency)
# ============================================================
class _CvtChunk:
    """转换中的分块。"""
    __slots__ = ("vertices", "active_subchunks", "idx_buffer", "vtx_buffer", "sub_buffer",
                 "idx_start", "vtx_start", "subchunk_start",
                 "idx_count", "vtx_count", "subchunk_count", "min", "max", "pad")

    def __init__(self):
        self.vertices = {}  # vertex_idx -> local_index
        self.active_subchunks = {}  # material_id -> subchunk dict
        self.idx_buffer = []
        self.vtx_buffer = []
        self.sub_buffer = []

    def begin_subchunk(self, sc, material_id):
        sc["material_id"] = material_id if material_id else 16  # Cliff
        sc["triangle_start"] = len(self.idx_buffer) // 3
        sc["triangle_count"] = 1
        sc["vtx_start"] = 0

    def end_subchunk(self, sc):
        sc["triangle_end"] = sc["triangle_start"] + sc["triangle_count"] - 1
        sc["vtx_count"] = len(self.vtx_buffer)
        sc["vtx_end"] = sc["vtx_start"] + sc["vtx_count"] - 1

    def done(self):
        for sc in self.active_subchunks.values():
            self.end_subchunk(sc)
            self.sub_buffer.append(sc)
        self.active_subchunks.clear()

        self.idx_count = len(self.idx_buffer)
        self.vtx_count = len(self.vtx_buffer)
        self.subchunk_count = len(self.sub_buffer)

        min_x = min_y = min_z = float("inf")
        max_x = max_y = max_z = float("-inf")
        for vi in self.vtx_buffer:
            px, py, pz = all_vertices[vi].pos
            if px < min_x: min_x = px
            if py < min_y: min_y = py
            if pz < min_z: min_z = pz
            if px > max_x: max_x = px
            if py > max_y: max_y = py
            if pz > max_z: max_z = pz
        self.min = (min_x - 0.1, min_y - 0.1, min_z - 0.1)
        self.max = (max_x + 0.1, max_y + 0.1, max_z + 0.1)
        self.pad = (0, 0, 0, 0)

    def try_assign_active_subchunk(self, face):
        if len(self.sub_buffer) + len(self.active_subchunks) > 252:
            return False

        # 多材质模式: 直接使用面的材质 (每个面来自一个 OBJ, 材质明确)
        # 单材质模式: 使用顶点材质 (兼容原始行为)
        if use_face_material and face.material_id:
            face_mats = {face.material_id}
        else:
            face_mats = set()
            for vi in face.indices:
                face_mats.add(all_vertex_materials[vi])

        # 移除不在当前面材质中的活跃子块
        to_remove = []
        for m, sc in self.active_subchunks.items():
            if m not in face_mats:
                self.end_subchunk(sc)
                self.sub_buffer.append(sc)
                to_remove.append(m)
            else:
                sc["triangle_count"] += 1
        for m in to_remove:
            del self.active_subchunks[m]

        # 为当前面的材质添加新子块
        for m in face_mats:
            if m not in self.active_subchunks:
                sc = {}
                self.begin_subchunk(sc, m)
                self.active_subchunks[m] = sc

        return True

    def try_add_face(self, face):
        if len(self.idx_buffer) + 3 > 756:
            return False

        new_vtx_count = 0
        for vi in face.indices:
            if vi not in self.vertices:
                new_vtx_count += 1

        if len(self.vtx_buffer) + new_vtx_count > 252:
            return False

        if not self.try_assign_active_subchunk(face):
            return False

        for vi in face.indices:
            if vi not in self.vertices:
                idx = len(self.vtx_buffer)
                self.vertices[vi] = idx
                self.vtx_buffer.append(vi)
            else:
                idx = self.vertices[vi]
            self.idx_buffer.append(idx)

        return True


# 全局变量 (在 obj_to_geo 中设置)
all_vertices = None
all_vertex_materials = None
use_face_material = False  # 多材质模式开关


def obj_to_geo(vertices, faces, vertex_materials_multi=None):
    """
    将 OBJ 解析后的顶点和面转换为 LevelGeo。
    使用 BFS 邻接分块算法 (移植自 adjacency.js)。

    vertex_materials_multi: 多材质权重列表, 每个元素为 [(mat_id, weight), ...]
        若提供则启用多材质模式: 面使用自身 material_id, 顶点存储多材质权重。
    """
    global all_vertices, all_vertex_materials, use_face_material
    all_vertices = vertices
    all_vertex_materials = [0] * len(vertices)
    use_face_material = vertex_materials_multi is not None

    if use_face_material:
        # 多材质模式: 取权重最大的材质作为顶点主材质 (用于分块限制检查)
        for vi, mats in enumerate(vertex_materials_multi):
            if mats:
                all_vertex_materials[vi] = mats[0][0]
    else:
        # 单材质模式: 取第一个使用它的面的材质
        for face in faces:
            for vi in face.indices:
                if all_vertex_materials[vi] == 0:
                    all_vertex_materials[vi] = face.material_id

    # BFS 分块分配
    unprocessed = dict.fromkeys(range(len(vertices)), None)  # 保持插入序
    visited_face = set()
    chunks = []

    # 初始 loop: 第一个未处理顶点
    if unprocessed:
        first_key = next(iter(unprocessed))
        loop = {first_key}
    else:
        loop = set()

    while unprocessed:
        chunk = _assign_chunk(loop, unprocessed, visited_face, vertices, faces)
        chunk.done()
        chunks.append(chunk)

    # 构建全局数组
    local_indices = []
    geo_vertices = []
    subchunks = []

    for chunk in chunks:
        chunk.idx_start = len(local_indices)
        chunk.vtx_start = len(geo_vertices)
        chunk.subchunk_start = len(subchunks)

        local_indices.extend(chunk.idx_buffer)

        for vi in chunk.vtx_buffer:
            vtx = vertices[vi]
            if use_face_material and vertex_materials_multi:
                # 多材质: 填充 4 个材质槽
                mats = vertex_materials_multi[vi]
                mat_ids = [0, 0, 0, 0]
                mat_weights = [0.0, 0.0, 0.0, 0.0]
                for j, (mid, w) in enumerate(mats[:4]):
                    mat_ids[j] = mid
                    mat_weights[j] = w
                geo_v = LevelGeoVertex.from_values(
                    pos=vtx.pos,
                    normal=(vtx.normal[0], vtx.normal[1], vtx.normal[2], 0.0),
                    material_ids=tuple(mat_ids),
                    material_weights=tuple(mat_weights),
                    in2=(0.99, 0.99, 0.99, 0.99),
                    in3=(0.5, 0.5, 0.5, 0.5),
                    in4=(0.04, 0.004, 0.004, 0.004),
                )
            else:
                # 单材质
                mat_id = all_vertex_materials[vi]
                geo_v = LevelGeoVertex.from_values(
                    pos=vtx.pos,
                    normal=(vtx.normal[0], vtx.normal[1], vtx.normal[2], 0.0),
                    material_ids=(mat_id, 0, 0, 0),
                    material_weights=(1.0, 0.0, 0.0, 0.0),
                    in2=(0.99, 0.99, 0.99, 0.99),
                    in3=(0.5, 0.5, 0.5, 0.5),
                    in4=(0.04, 0.004, 0.004, 0.004),
                )
            geo_vertices.append(geo_v)

        subchunks.extend(chunk.sub_buffer)

    geo = LevelGeo()
    geo.cloud_chunk_count = 0
    geo.meshopt_version = 0  # 游戏兼容版本
    geo.index_count = len(local_indices)
    geo.vertex_count = len(geo_vertices)
    geo.chunk_count = len(chunks)
    geo.subchunk_count = len(subchunks)
    geo.local_indices = local_indices
    geo.vertices = geo_vertices

    # 构建 LevelGeoChunk 对象
    geo.chunks = []
    for chunk in chunks:
        c = LevelGeoChunk()
        c.idx_start = chunk.idx_start
        c.vtx_start = chunk.vtx_start
        c.subchunk_start = chunk.subchunk_start
        c.idx_count = chunk.idx_count
        c.vtx_count = chunk.vtx_count
        c.subchunk_count = chunk.subchunk_count
        c.min = chunk.min
        c.max = chunk.max
        c.pad = chunk.pad
        geo.chunks.append(c)

    # 构建 LevelGeoSubchunk 对象
    geo.subchunks = []
    for sc in subchunks:
        s = LevelGeoSubchunk()
        s.material_id = sc["material_id"]
        s.triangle_count = sc["triangle_count"]
        s.vtx_count = sc["vtx_count"]
        s.triangle_start = sc["triangle_start"]
        s.triangle_end = sc["triangle_end"]
        s.vtx_start = sc["vtx_start"]
        s.vtx_end = sc["vtx_end"]
        geo.subchunks.append(s)

    return geo


def _assign_chunk(start, unprocessed, visited_face, vertices, faces):
    """BFS 分块分配 (移植自 adjacency.js assignChunk)。"""
    recursive_vtx = set(start)
    chunk = _CvtChunk()
    done = False
    next_loop_vtx = set()

    while not done:
        next_loop_vtx = set()

        for vtx_idx in recursive_vtx:
            if vtx_idx not in unprocessed:
                continue

            del unprocessed[vtx_idx]

            # selectFace: 收集附近所有顶点的面
            nearby = vertices[vtx_idx].nearby
            candidate_faces = []
            seen = set()
            for v_idx in nearby:
                for f_idx in vertices[v_idx].faces:
                    if f_idx not in seen:
                        seen.add(f_idx)
                        candidate_faces.append(f_idx)

            for f_idx in candidate_faces:
                if f_idx in visited_face:
                    continue

                face = faces[f_idx]
                if not chunk.try_add_face(face):
                    done = True
                    break

                visited_face.add(f_idx)
                # updateNextLoop: 添加面中未处理的顶点
                for vi in face.indices:
                    if vi in unprocessed:
                        next_loop_vtx.add(vi)

            if done:
                break

        if not done and not next_loop_vtx:
            if not unprocessed:
                done = True
            else:
                next_loop_vtx.add(next(iter(unprocessed)))

        recursive_vtx = next_loop_vtx

    # 将剩余的连续顶点传递给下一个分块
    if next_loop_vtx:
        start.clear()
        start.update(next_loop_vtx)

    return chunk


def obj_to_meshes_full(obj_text):
    """从可逆 OBJ 的 @MESHES_META 元数据块精确重建 LevelMeshes (字节级无损)。

    与 meshes_to_obj_full 互为逆操作, 不使用 BFS 邻接分块算法,
    直接从嵌入的元数据恢复原始结构。
    """
    if META_BEGIN not in obj_text:
        raise ValueError("OBJ 文件不包含 @MESHES_META 元数据块, 无法精确还原")

    lines = obj_text.split("\n")
    in_meta = False
    meta_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped == META_BEGIN:
            in_meta = True
            continue
        if stripped == META_END:
            break
        if in_meta and stripped.startswith("# @"):
            meta_lines.append(stripped[3:])

    if not meta_lines:
        raise ValueError("元数据块为空, 无法还原")

    # ---- 解析元数据 ----
    version = 0x3C
    meshopt_version = 0
    max_pos = (FLT_MAX, FLT_MAX, FLT_MAX)
    min_pos = (-FLT_MAX, -FLT_MAX, -FLT_MAX)
    desc_raw = None
    lod_raw = None
    counts = None
    vraw_dict = {}
    chunks_data = []
    subchunks_data = []
    indices = []

    for ml in meta_lines:
        parts = ml.split(None, 1)
        tag = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""

        if tag == "version":
            version = int(rest, 16)
        elif tag == "meshopt_version":
            meshopt_version = int(rest)
        elif tag == "bounds_max":
            v = rest.split()
            max_pos = (float(v[0]), float(v[1]), float(v[2]))
        elif tag == "bounds_min":
            v = rest.split()
            min_pos = (float(v[0]), float(v[1]), float(v[2]))
        elif tag == "desc_raw":
            desc_raw = bytes.fromhex(rest)
        elif tag == "lod0_raw":
            lod_raw = bytes.fromhex(rest)
        elif tag == "counts":
            counts = [int(x) for x in rest.split()]
        elif tag == "vraw":
            sp = rest.split(None, 1)
            idx = int(sp[0])
            vraw_dict[idx] = bytes.fromhex(sp[1]) if len(sp) > 1 else b""
        elif tag == "chunk":
            chunks_data.append(rest.split())
        elif tag == "subchunk":
            subchunks_data.append(rest.split())
        elif tag == "indices":
            indices.extend(int(x) for x in rest.split())

    # ---- 构建 LevelMeshes ----
    m = LevelMeshes()
    m.version = version
    m.max_pos = max_pos
    m.min_pos = min_pos
    m.desc_raw = desc_raw
    m.desc = _parse_desc(desc_raw) if desc_raw else None
    m.lod_raw = lod_raw if lod_raw else LOD0_FIXED_BYTES
    m.toc = None

    geo = LevelGeo()
    if counts:
        geo.vertex_count = counts[0]
        geo.index_count = counts[1]
        geo.chunk_count = counts[2]
        geo.cloud_chunk_count = counts[3]
        geo.subchunk_count = counts[4]
    else:
        geo.vertex_count = len(vraw_dict)
        geo.index_count = len(indices)
        geo.chunk_count = len(chunks_data)
        geo.cloud_chunk_count = 0
        geo.subchunk_count = len(subchunks_data)
    geo.meshopt_version = meshopt_version

    # 顶点 (从原始 36 字节重建, 字节级无损)
    geo.vertices = []
    for i in range(geo.vertex_count):
        raw = vraw_dict.get(i)
        if raw is None:
            raw = b"\x00" * VERTEX_SIZE
        geo.vertices.append(LevelGeoVertex.from_raw(raw))

    # 索引
    geo.local_indices = indices

    # 分块
    geo.chunks = []
    for vals in chunks_data:
        # @chunk <idx> <idx_start> <idx_count> <vtx_start> <vtx_count>
        #         <sub_start> <sub_count> <minx> <miny> <minz>
        #         <maxx> <maxy> <maxz> <pad0> <pad1> <pad2> <pad3>
        c = LevelGeoChunk()
        c.idx_start = int(vals[1])
        c.idx_count = int(vals[2])
        c.vtx_start = int(vals[3])
        c.vtx_count = int(vals[4])
        c.subchunk_start = int(vals[5])
        c.subchunk_count = int(vals[6])
        c.min = (float(vals[7]), float(vals[8]), float(vals[9]))
        c.max = (float(vals[10]), float(vals[11]), float(vals[12]))
        c.pad = (int(vals[13]), int(vals[14]), int(vals[15]), int(vals[16]))
        geo.chunks.append(c)

    # 子区间
    geo.subchunks = []
    for vals in subchunks_data:
        # @subchunk <idx> <mat_id> <tri_count> <vtx_count>
        #           <tri_start> <tri_end> <vtx_start> <vtx_end>
        sc = LevelGeoSubchunk()
        sc.material_id = int(vals[1])
        sc.triangle_count = int(vals[2])
        sc.vtx_count = int(vals[3])
        sc.triangle_start = int(vals[4])
        sc.triangle_end = int(vals[5])
        sc.vtx_start = int(vals[6])
        sc.vtx_end = int(vals[7])
        geo.subchunks.append(sc)

    m.geo = geo
    return m


def obj_to_meshes(obj_text):
    """OBJ 文本 -> LevelMeshes 对象。

    自动检测: 若 OBJ 包含 @MESHES_META 元数据块, 使用精确还原 (字节级无损);
    否则使用 BFS 邻接分块算法 (从零重建, 适用于普通 OBJ)。
    """
    if META_BEGIN in obj_text:
        return obj_to_meshes_full(obj_text)

    vertices, faces = parse_obj(obj_text)
    geo = obj_to_geo(vertices, faces)

    m = LevelMeshes()
    m.version = 0x3C
    m.max_pos = (FLT_MAX, FLT_MAX, FLT_MAX)
    m.min_pos = (-FLT_MAX, -FLT_MAX, -FLT_MAX)
    m.desc = {
        "timeStamp": 0,
        "fileName": "",
        "editor": "that-sky-level",
        "editorVersion": [1, 0, 0],
        "engineVersion": [0, 32, 2],
    }
    m.desc_raw = _nbt_write_desc(m.desc)
    m.lod_raw = LOD0_FIXED_BYTES
    m.geo = geo
    m.toc = None
    return m


# ============================================================
#  多 OBJ -> meshes (按材质拆分输入, 交界处权重过渡)
# ============================================================
def parse_multi_obj(obj_paths, transforms=None):
    """
    解析多个 OBJ 文件, 按位置合并顶点, 计算多材质权重。

    顶点合并: 相同坐标 (6位精度) 的顶点合并为一个, 法线取面几何自动计算。
    权重分配: 交界处顶点按各材质面数比例分配权重 (最多 4 个材质槽)。

    transforms: 可选, 与 obj_paths 一一对应的变换列表, 每项为 (offset_xyz, scale)
    返回: (vertices, faces, vertex_materials_multi)
      - vertices: list of _ObjVertex
      - faces: list of _ObjFace (material_id 来自文件名)
      - vertex_materials_multi: list of [(mat_id, weight), ...] 每顶点
    """
    pos_map = {}       # (x,y,z) rounded -> vertex index
    vertices = []
    faces = []

    # 每个位置被各材质面引用的次数
    pos_mat_counts = {}  # pos_key -> {mat_id: face_count}

    for fi, obj_path in enumerate(obj_paths):
        mat_name = _material_from_filename(obj_path)
        mat_id = K_MATERIAL.get(mat_name, 0)
        if mat_id == 0:
            print("  警告: 无法从 %s 识别材质, 跳过" % os.path.basename(obj_path))
            continue

        print("  %s -> 材质 %s (ID=%d)" % (os.path.basename(obj_path), mat_name, mat_id))

        # 该文件的坐标变换
        t_offset = (0.0, 0.0, 0.0)
        t_scale = 1.0
        if transforms and fi < len(transforms):
            t_offset, t_scale = transforms[fi]

        with open(obj_path, "r", encoding="utf-8") as f:
            obj_text = f.read()

        # 简单解析: 顶点位置 + 面
        obj_positions = []
        obj_faces = []

        for line in obj_text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts[0] == "v":
                px, py, pz = float(parts[1]), float(parts[2]), float(parts[3])
                # 应用坐标变换
                px = px * t_scale + t_offset[0]
                py = py * t_scale + t_offset[1]
                pz = pz * t_scale + t_offset[2]
                obj_positions.append((px, py, pz))
            elif parts[0] == "f":
                idxs = []
                for p in parts[1:]:
                    vi = int(p.split("/")[0])
                    idxs.append(vi - 1 if vi > 0 else len(obj_positions) + vi)
                for i in range(1, len(idxs) - 1):
                    obj_faces.append((idxs[0], idxs[i], idxs[i + 1]))

        # 合并到全局数组
        for f_tri in obj_faces:
            i0, i1, i2 = f_tri
            p0, p1, p2 = obj_positions[i0], obj_positions[i1], obj_positions[i2]

            global_idxs = []
            for pos in (p0, p1, p2):
                key = (round(pos[0], 6), round(pos[1], 6), round(pos[2], 6))
                if key not in pos_map:
                    vtx = _ObjVertex(pos, (0.0, 1.0, 0.0))
                    vtx_idx = len(vertices)
                    vertices.append(vtx)
                    pos_map[key] = vtx_idx
                    pos_mat_counts[key] = {}
                gvi = pos_map[key]
                global_idxs.append(gvi)

                # 统计该位置被当前材质引用的次数
                pos_mat_counts[key][mat_id] = pos_mat_counts[key].get(mat_id, 0) + 1

            faces.append(_ObjFace(global_idxs, mat_id))

    if not vertices:
        raise ValueError("所有 OBJ 文件均无有效几何数据")

    # ---- 计算法线 (从面几何) ----
    accum = [[0.0, 0.0, 0.0] for _ in range(len(vertices))]
    for face in faces:
        i0, i1, i2 = face.indices
        p0, p1, p2 = vertices[i0].pos, vertices[i1].pos, vertices[i2].pos
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length > 0.0001:
            nx, ny, nz = nx / length, ny / length, nz / length
        for vi in (i0, i1, i2):
            accum[vi][0] += nx
            accum[vi][1] += ny
            accum[vi][2] += nz

    for i, v in enumerate(vertices):
        nx, ny, nz = accum[i]
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length > 0.0001:
            v.normal = (nx / length, ny / length, nz / length)
        else:
            v.normal = (0.0, 1.0, 0.0)

    # ---- 构建 nearby 集合 (同位置顶点) ----
    for i, v in enumerate(vertices):
        v.nearby = {i}

    # ---- 构建 vertex.faces ----
    for fi, face in enumerate(faces):
        for vi in face.indices:
            vertices[vi].faces.append(fi)

    # ---- 计算每顶点的材质权重 ----
    vertex_materials_multi = []
    for i, v in enumerate(vertices):
        key = (round(v.pos[0], 6), round(v.pos[1], 6), round(v.pos[2], 6))
        mat_counts = pos_mat_counts.get(key, {})
        total = sum(mat_counts.values())
        if total > 0:
            # 按面数比例分配权重, 最多 4 个材质
            weights = sorted(
                [(mid, cnt / total) for mid, cnt in mat_counts.items()],
                key=lambda x: -x[1]
            )
        else:
            weights = [(0, 1.0)]
        vertex_materials_multi.append(weights)

    # 统计输出
    boundary_count = sum(1 for w in vertex_materials_multi if len(w) > 1)
    print("  合并结果: %d 顶点, %d 面, %d 交界顶点 (多材质)" % (
        len(vertices), len(faces), boundary_count))

    return vertices, faces, vertex_materials_multi


def multi_obj_to_meshes(obj_paths, transforms=None):
    """多 OBJ 文件 -> LevelMeshes 对象 (按材质名确定材质, 交界处权重过渡)。
    transforms: 可选, 与 obj_paths 一一对应的变换列表, 每项为 (offset_xyz, scale)
    """
    print("\n正在解析多 OBJ 文件...")
    vertices, faces, vertex_materials_multi = parse_multi_obj(obj_paths, transforms=transforms)

    print("\n正在执行邻接分块...")
    geo = obj_to_geo(vertices, faces, vertex_materials_multi)

    # 重新计算所有 chunk 的 min/max 包围盒, 确保视锥剔除准确
    if geo.vertices and geo.chunks:
        for c in geo.chunks:
            vs = c.vtx_start
            ve = vs + c.vtx_count
            if ve > geo.vertex_count:
                ve = geo.vertex_count
            if vs >= ve:
                continue
            xs = [geo.vertices[j].pos[0] for j in range(vs, ve)]
            ys = [geo.vertices[j].pos[1] for j in range(vs, ve)]
            zs = [geo.vertices[j].pos[2] for j in range(vs, ve)]
            c.min = (min(xs) - 0.1, min(ys) - 0.1, min(zs) - 0.1)
            c.max = (max(xs) + 0.1, max(ys) + 0.1, max(zs) + 0.1)

    m = LevelMeshes()
    m.version = 0x3C
    m.max_pos = (FLT_MAX, FLT_MAX, FLT_MAX)
    m.min_pos = (-FLT_MAX, -FLT_MAX, -FLT_MAX)
    m.desc = {
        "timeStamp": int(time.time()),
        "fileName": "",
        "editor": "that-sky-level",
        "editorVersion": [1, 0, 0],
        "engineVersion": [0, 32, 2],
    }
    m.desc_raw = _nbt_write_desc(m.desc)
    m.lod_raw = LOD0_FIXED_BYTES
    m.geo = geo
    m.toc = None
    return m


def _apply_transform(geo, offset, scale):
    """对 geo 的顶点位置和 chunk 包围盒应用偏移+缩放。
    new_pos = pos * scale + offset
    只改 pos 和 chunk min/max, 其他字段 (normal/material/weights/input2-4/索引/子区间) 不变。
    """
    if not geo or not geo.vertices:
        return geo
    ox, oy, oz = offset
    for v in geo.vertices:
        raw = bytearray(v.raw)
        px, py, pz = struct.unpack_from("<fff", raw, 0)
        struct.pack_into("<fff", raw, 0,
                         px * scale + ox,
                         py * scale + oy,
                         pz * scale + oz)
        v.raw = bytes(raw)
        v.pos = (px * scale + ox, py * scale + oy, pz * scale + oz)
    for c in geo.chunks:
        if c.min and len(c.min) == 3:
            c.min = (c.min[0] * scale + ox,
                     c.min[1] * scale + oy,
                     c.min[2] * scale + oz)
        if c.max and len(c.max) == 3:
            c.max = (c.max[0] * scale + ox,
                     c.max[1] * scale + oy,
                     c.max[2] * scale + oz)
    return geo


def multi_obj_to_meshes_mixed(standard_paths, full_paths, shadow_index=0,
                              standard_transforms=None, full_transforms=None):
    """合并标准 OBJ + 可逆 OBJ (非法OBJ) → LevelMeshes 对象。

    影子模式:
    - 选一个可逆 OBJ 作为"影子", 它提供全部元数据 (LOD0/DESC/meshopt_version/bounds)
    - 其他可逆 OBJ 只贡献几何 (顶点材质权重 + 网格), 不贡献 LOD0/DESC
    - 标准 OBJ 通过邻接分块处理, 材质来自文件名

    坐标变换:
    - 每个 OBJ 可指定 offset (x,y,z) 和 scale, 对顶点位置和 chunk bounds 应用 new_pos = pos*scale + offset
    - 只影响位置, normal/material/weights/UV/索引/子区间不变

    standard_paths: 标准 OBJ 文件路径列表 (可空)
    full_paths: 可逆 OBJ 文件路径列表 (可空)
    shadow_index: 哪个可逆 OBJ 作为影子 (0-based, 默认 0=第一个)
    standard_transforms: 标准 OBJ 的变换列表, 每项为 (offset_xyz, scale), 与 standard_paths 一一对应
    full_transforms: 可逆 OBJ 的变换列表, 每项为 (offset_xyz, scale), 与 full_paths 一一对应
    """
    if not standard_paths and not full_paths:
        raise ValueError("未提供任何 OBJ 文件")

    all_vertices = []
    all_indices = []
    all_chunks = []
    all_subchunks = []
    terrain_chunk_count = 0
    cloud_chunk_count = 0

    # 影子 OBJ 的元数据 (LOD0/DESC/meshopt_version 全部来自影子)
    shadow_lod_raw = None
    shadow_desc_raw = None
    shadow_meshopt_version = 0
    shadow_bounds_max = None
    shadow_bounds_min = None

    # ---- 1. 处理标准 OBJ ----
    if standard_paths:
        print("\n--- 处理标准 OBJ (%d 个) ---" % len(standard_paths))
        vertices, faces, vertex_materials_multi = parse_multi_obj(standard_paths, transforms=standard_transforms)
        print("\n正在执行邻接分块...")
        geo_std = obj_to_geo(vertices, faces, vertex_materials_multi)

        all_vertices.extend(geo_std.vertices)
        all_indices.extend(geo_std.local_indices)
        all_chunks.extend(geo_std.chunks)
        all_subchunks.extend(geo_std.subchunks)
        terrain_chunk_count += geo_std.chunk_count
        cloud_chunk_count += geo_std.cloud_chunk_count

        print("  标准 OBJ: %d 顶点, %d 索引, %d 分块" % (
            geo_std.vertex_count, geo_std.index_count, geo_std.chunk_count))

    # ---- 2. 处理可逆 OBJ (非法OBJ) ----
    for i, fp in enumerate(full_paths):
        print("\n--- 处理可逆 OBJ (%d/%d): %s ---" % (i + 1, len(full_paths), os.path.basename(fp)))
        with open(fp, "r", encoding="utf-8") as f:
            obj_text = f.read()

        meshes = obj_to_meshes_full(obj_text)
        geo = meshes.geo

        if not geo or geo.vertex_count == 0:
            print("  跳过: 无几何数据")
            continue

        # 应用坐标变换 (偏移+缩放)
        if full_transforms and i < len(full_transforms):
            t_offset, t_scale = full_transforms[i]
            if t_offset != (0.0, 0.0, 0.0) or t_scale != 1.0:
                _apply_transform(geo, t_offset, t_scale)
                print("  坐标变换: offset=(%.2f,%.2f,%.2f) scale=%.4f" % (
                    t_offset[0], t_offset[1], t_offset[2], t_scale))

        is_shadow = (i == shadow_index)
        if is_shadow:
            # 影子 OBJ: 提供全部元数据
            shadow_lod_raw = meshes.lod_raw
            shadow_desc_raw = meshes.desc_raw
            shadow_meshopt_version = getattr(geo, 'meshopt_version', 0)
            shadow_bounds_max = meshes.max_pos
            shadow_bounds_min = meshes.min_pos
            lod_len = len(meshes.lod_raw) if meshes.lod_raw else 0
            print("  [影子] 提供全部元数据:")
            if lod_len > len(LOD0_FIXED_BYTES):
                print("    LOD0: %d 字节 (含烘焙数据)" % lod_len)
            else:
                print("    LOD0: %d 字节 (默认)" % lod_len)
            if shadow_desc_raw:
                di = meshes.desc if meshes.desc else {}
                print("    DESC: fileName=%s, timeStamp=%d" % (
                    di.get("fileName", ""), di.get("timeStamp", 0)))
            print("    meshopt_version: %d" % shadow_meshopt_version)
        else:
            # 非影子 OBJ: 只贡献几何
            mv = getattr(geo, 'meshopt_version', 0)
            if mv != shadow_meshopt_version:
                print("  警告: meshopt_version 不一致 (影子=%d, 此OBJ=%d)" % (
                    shadow_meshopt_version, mv))

        vtx_offset = len(all_vertices)
        idx_offset = len(all_indices)
        sub_offset = len(all_subchunks)

        # 顶点直接追加 (保留完整 36 字节原始数据, 含材质权重)
        all_vertices.extend(geo.vertices)

        # 索引直接追加 (local_indices 相对于各 chunk 的 vtx_start, 无需偏移)
        all_indices.extend(geo.local_indices)

        # 分块: 调整 idx_start / vtx_start / subchunk_start
        for c in geo.chunks:
            new_c = LevelGeoChunk()
            new_c.idx_start = c.idx_start + idx_offset
            new_c.vtx_start = c.vtx_start + vtx_offset
            new_c.subchunk_start = c.subchunk_start + sub_offset
            new_c.idx_count = c.idx_count
            new_c.vtx_count = c.vtx_count
            new_c.subchunk_count = c.subchunk_count
            new_c.min = c.min
            new_c.max = c.max
            new_c.pad = c.pad if c.pad else (0, 0, 0, 0)
            all_chunks.append(new_c)

        terrain_chunk_count += geo.chunk_count
        cloud_chunk_count += geo.cloud_chunk_count

        # 子区间直接追加
        all_subchunks.extend(geo.subchunks)

        label = " [影子]" if is_shadow else ""
        print("  可逆 OBJ%s: %d 顶点, %d 索引, %d 分块" % (
            label, geo.vertex_count, geo.index_count,
            geo.chunk_count + geo.cloud_chunk_count))

    # ---- 3. 构建合并后的 geo ----
    geo = LevelGeo()
    geo.vertices = all_vertices
    geo.vertex_count = len(all_vertices)
    geo.local_indices = all_indices
    geo.index_count = len(all_indices)
    geo.chunks = all_chunks
    geo.chunk_count = terrain_chunk_count
    geo.cloud_chunk_count = cloud_chunk_count
    geo.subchunks = all_subchunks
    geo.subchunk_count = len(all_subchunks)
    geo.meshopt_version = shadow_meshopt_version

    print("\n=== 合并结果 ===")
    print("  总计: %d 顶点, %d 索引, %d 分块 (%d 地形 + %d 云), %d 子区间" % (
        geo.vertex_count, geo.index_count,
        terrain_chunk_count + cloud_chunk_count,
        terrain_chunk_count, cloud_chunk_count,
        geo.subchunk_count))
    print("  meshopt_version: %d (来自影子)" % shadow_meshopt_version)

    # ---- 3.5 重新计算所有 chunk 的 min/max 包围盒 ----
    # 从实际顶点位置计算 AABB, 确保视锥剔除准确
    # (原始 chunk min/max 可能在合并/变换后不准确)
    if geo.vertices and geo.chunks:
        for c in geo.chunks:
            vs = c.vtx_start
            ve = vs + c.vtx_count
            if ve > geo.vertex_count:
                ve = geo.vertex_count
            if vs >= ve:
                continue
            xs = [geo.vertices[j].pos[0] for j in range(vs, ve)]
            ys = [geo.vertices[j].pos[1] for j in range(vs, ve)]
            zs = [geo.vertices[j].pos[2] for j in range(vs, ve)]
            c.min = (min(xs) - 0.1, min(ys) - 0.1, min(zs) - 0.1)
            c.max = (max(xs) + 0.1, max(ys) + 0.1, max(zs) + 0.1)
        print("  chunk 包围盒: 已从顶点重新计算")

    # ---- 4. 构建 LevelMeshes ----
    m = LevelMeshes()
    m.version = 0x3C
    # bounds: 原项目始终写 FLT_MAX
    m.max_pos = (FLT_MAX, FLT_MAX, FLT_MAX)
    m.min_pos = (-FLT_MAX, -FLT_MAX, -FLT_MAX)

    # DESC: 从影子继承
    if shadow_desc_raw is not None:
        m.desc_raw = shadow_desc_raw
        m.desc = _parse_desc(shadow_desc_raw) if shadow_desc_raw else None
        print("  DESC: 从影子继承")
    else:
        m.desc = {
            "timeStamp": int(time.time()),
            "fileName": "",
            "editor": "that-sky-level",
            "editorVersion": [1, 0, 0],
            "engineVersion": [0, 32, 2],
        }
        m.desc_raw = _nbt_write_desc(m.desc)
        print("  DESC: 默认 (无可逆OBJ)")

    # LOD0: 从影子继承 (不拼接)
    if shadow_lod_raw is not None:
        m.lod_raw = shadow_lod_raw
        lod_len = len(shadow_lod_raw)
        if lod_len > len(LOD0_FIXED_BYTES):
            print("  LOD0: %d 字节 (从影子继承, 含烘焙数据)" % lod_len)
        else:
            print("  LOD0: %d 字节 (从影子继承, 默认)" % lod_len)
    else:
        m.lod_raw = LOD0_FIXED_BYTES
        print("  LOD0: 17 字节 (默认, 无可逆OBJ)")

    m.geo = geo
    m.toc = None
    return m


# ============================================================
#  meshes -> JSON export (professional English, no raw bytes)
# ============================================================
def meshes_to_json(meshes):
    """Export LevelMeshes to a clean, professional JSON dict."""
    geo = meshes.geo
    tri_count = geo.index_count // 3 if geo else 0

    data = {
        "format": "that-sky-level-meshes",
        "version": "0x%X" % meshes.version,
        "metadata": _build_desc_json(meshes),
        "bounds": {
            "max": {"x": meshes.max_pos[0], "y": meshes.max_pos[1], "z": meshes.max_pos[2]},
            "min": {"x": meshes.min_pos[0], "y": meshes.min_pos[1], "z": meshes.min_pos[2]},
        },
        "geometry": {
            "summary": {
                "vertex_count": geo.vertex_count if geo else 0,
                "triangle_count": tri_count,
                "index_count": geo.index_count if geo else 0,
                "chunk_count": geo.chunk_count if geo else 0,
                "cloud_chunk_count": geo.cloud_chunk_count if geo else 0,
                "subchunk_count": geo.subchunk_count if geo else 0,
                "meshopt_version": getattr(geo, 'meshopt_version', 0) if geo else 0,
            },
            "vertices": [],
            "triangles": [],
            "chunks": [],
            "subchunks": [],
            "indices": list(geo.local_indices) if geo else [],
        },
    }

    if not geo:
        return data

    # ---- vertices ----
    for i, v in enumerate(geo.vertices):
        materials = []
        for j in range(4):
            mid = v.material[j]
            materials.append({
                "name": K_MATERIAL_REVERSE.get(mid, "Unknown_%d" % mid),
                "id": mid,
                "weight": v.weights[j],
            })

        data["geometry"]["vertices"].append({
            "index": i,
            "position": {"x": v.pos[0], "y": v.pos[1], "z": v.pos[2]},
            "normal": {"x": v.normal[0], "y": v.normal[1], "z": v.normal[2], "w": v.normal_w},
            "materials": materials,
            "input2_ao_roughness": {"x": v.in2[0], "y": v.in2[1], "z": v.in2[2], "w": v.in2[3]},
            "input3_detail": {"x": v.in3[0], "y": v.in3[1], "z": v.in3[2], "w": v.in3[3]},
            "input4_misc": {"x": v.in4[0], "y": v.in4[1], "z": v.in4[2], "w": v.in4[3]},
        })

    # ---- triangles ----
    tri_global = 0
    for ci, chunk in enumerate(geo.chunks):
        if ci >= geo.chunk_count:
            break  # skip cloud chunks
        idx_start = chunk.idx_start
        vtx_start = chunk.vtx_start
        for j in range(0, chunk.idx_count, 3):
            a = vtx_start + geo.local_indices[idx_start + j]
            b = vtx_start + geo.local_indices[idx_start + j + 1]
            c = vtx_start + geo.local_indices[idx_start + j + 2]
            data["geometry"]["triangles"].append({
                "index": tri_global,
                "chunk": ci,
                "indices": [a, b, c],
                "positions": [
                    {"x": geo.vertices[a].pos[0], "y": geo.vertices[a].pos[1], "z": geo.vertices[a].pos[2]},
                    {"x": geo.vertices[b].pos[0], "y": geo.vertices[b].pos[1], "z": geo.vertices[b].pos[2]},
                    {"x": geo.vertices[c].pos[0], "y": geo.vertices[c].pos[1], "z": geo.vertices[c].pos[2]},
                ],
            })
            tri_global += 1

    # ---- chunks ----
    for i, c in enumerate(geo.chunks):
        is_cloud = i >= geo.chunk_count
        data["geometry"]["chunks"].append({
            "index": i,
            "type": "cloud" if is_cloud else "terrain",
            "vertex_range": {"start": c.vtx_start, "count": c.vtx_count},
            "index_range": {"start": c.idx_start, "count": c.idx_count},
            "subchunk_range": {"start": c.subchunk_start, "count": c.subchunk_count},
            "bounds": {
                "min": {"x": c.min[0], "y": c.min[1], "z": c.min[2]},
                "max": {"x": c.max[0], "y": c.max[1], "z": c.max[2]},
            },
        })

    # ---- subchunks ----
    for i, sc in enumerate(geo.subchunks):
        mname = K_MATERIAL_REVERSE.get(sc.material_id, "Unknown_%d" % sc.material_id)
        data["geometry"]["subchunks"].append({
            "index": i,
            "material": {"name": mname, "id": sc.material_id},
            "triangle_range": {"start": sc.triangle_start, "end": sc.triangle_end, "count": sc.triangle_count},
            "vertex_range": {"start": sc.vtx_start, "end": sc.vtx_end, "count": sc.vtx_count},
        })

    # ---- binary segments (required for exact reconstruction) ----
    # DESC and LOD0 are small binary blobs that cannot be losslessly
    # reconstructed from decoded values (field order, extra fields, etc.)
    if meshes.desc_raw is not None:
        data["desc_raw"] = list(meshes.desc_raw)
    if meshes.lod_raw is not None:
        data["lod0_raw"] = list(meshes.lod_raw)

    return data


def _build_desc_json(meshes):
    """Build DESC metadata JSON."""
    if meshes.desc is None:
        return None
    desc = meshes.desc
    ts = desc.get("timeStamp", 0)
    time_str = ""
    if ts:
        try:
            time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        except Exception:
            time_str = ""

    ev = desc.get("editorVersion", [])
    gv = desc.get("engineVersion", [])
    ev_str = ".".join(str(x) for x in ev) if ev else ""
    gv_str = ".".join(str(x) for x in gv) if gv else ""

    return {
        "file_name": desc.get("fileName", ""),
        "editor": desc.get("editor", ""),
        "editor_version": ev_str,
        "engine_version": gv_str,
        "timestamp": ts,
        "time": time_str,
    }


# ============================================================
#  JSON -> meshes import (reconstruct from decoded values)
# ============================================================
def _dict_to_vec3(d, default=(0.0, 0.0, 0.0)):
    """Extract (x, y, z) from a dict or list."""
    if isinstance(d, dict):
        return (d.get("x", default[0]), d.get("y", default[1]), d.get("z", default[2]))
    if isinstance(d, (list, tuple)):
        return (d[0], d[1], d[2])
    return default


def _dict_to_vec4(d, default=(0.0, 0.0, 0.0, 0.0)):
    """Extract (x, y, z, w) from a dict or list."""
    if isinstance(d, dict):
        return (d.get("x", default[0]), d.get("y", default[1]), d.get("z", default[2]), d.get("w", default[3]))
    if isinstance(d, (list, tuple)):
        return (d[0], d[1], d[2], d[3] if len(d) > 3 else 0.0)
    return default


def json_to_meshes(data):
    """Reconstruct LevelMeshes from JSON dict."""
    m = LevelMeshes()

    # version
    ver = data.get("version", 0x3C)
    if isinstance(ver, str):
        ver = int(ver, 16)
    m.version = ver

    # bounds
    bbox = data.get("bounds", data.get("header", {}))
    max_pos = bbox.get("max", bbox.get("max_pos", {}))
    min_pos = bbox.get("min", bbox.get("min_pos", {}))
    m.max_pos = _dict_to_vec3(max_pos, (FLT_MAX, FLT_MAX, FLT_MAX))
    m.min_pos = _dict_to_vec3(min_pos, (-FLT_MAX, -FLT_MAX, -FLT_MAX))

    # DESC
    desc_raw = data.get("desc_raw")
    if desc_raw is not None:
        m.desc_raw = bytes(desc_raw)
        m.desc = _parse_desc(m.desc_raw)
    else:
        desc_json = data.get("metadata", data.get("desc"))
        if desc_json is not None:
            if isinstance(desc_json, dict):
                ev_str = desc_json.get("editor_version", desc_json.get("editorVersion", ""))
                gv_str = desc_json.get("engine_version", desc_json.get("engineVersion", ""))
                ev = [int(x) for x in ev_str.split(".")] if ev_str else desc_json.get("editorVersion", [1, 0, 0])
                gv = [int(x) for x in gv_str.split(".")] if gv_str else desc_json.get("engineVersion", [0, 32, 2])
                m.desc = {
                    "timeStamp": desc_json.get("timestamp", desc_json.get("timeStamp", 0)),
                    "fileName": desc_json.get("file_name", desc_json.get("fileName", "")),
                    "editor": desc_json.get("editor", ""),
                    "editorVersion": ev,
                    "engineVersion": gv,
                }
            else:
                m.desc = desc_json
            m.desc_raw = _nbt_write_desc(m.desc)
        else:
            m.desc = None
            m.desc_raw = None

    # LOD0
    lod_raw = data.get("lod0_raw")
    if lod_raw is not None:
        m.lod_raw = bytes(lod_raw)
    else:
        m.lod_raw = LOD0_FIXED_BYTES

    # GEO0
    geo_data = data.get("geometry", data.get("geo"))
    if geo_data is not None:
        geo = LevelGeo()

        stats = geo_data.get("summary", geo_data)
        geo.vertex_count = stats.get("vertex_count", geo_data.get("vertex_count", 0))
        geo.index_count = stats.get("index_count", geo_data.get("index_count", 0))
        geo.chunk_count = stats.get("chunk_count", geo_data.get("chunk_count", 0))
        geo.cloud_chunk_count = stats.get("cloud_chunk_count", geo_data.get("cloud_chunk_count", 0))
        geo.subchunk_count = stats.get("subchunk_count", geo_data.get("subchunk_count", 0))
        geo.meshopt_version = stats.get("meshopt_version", geo_data.get("meshopt_version", 0))
        geo.local_indices = geo_data.get("indices", geo_data.get("local_indices", []))

        # vertices — reconstruct from decoded values
        vtx_list = geo_data.get("vertices", [])
        raw_vtx = data.get("_原始数据_精确往返用", {}).get("顶点原始字节")
        geo.vertices = []
        for i, vd in enumerate(vtx_list):
            # backward-compat: use raw bytes if present
            raw = vd.get("raw", vd.get("原始字节_36B"))
            if raw is not None:
                geo.vertices.append(LevelGeoVertex.from_raw(bytes(raw)))
                continue
            if raw_vtx is not None and i < len(raw_vtx):
                geo.vertices.append(LevelGeoVertex.from_raw(bytes(raw_vtx[i])))
                continue
            # reconstruct from decoded values
            pos = _dict_to_vec3(vd.get("position", vd.get("pos", {})))
            norm_d = vd.get("normal", {})
            norm = _dict_to_vec3(norm_d, (0.0, 1.0, 0.0))
            norm_w = norm_d.get("w", vd.get("normal_w", 0.0)) if isinstance(norm_d, dict) else 0.0

            mats_field = vd.get("materials", vd.get("材质"))
            if isinstance(mats_field, list) and mats_field and isinstance(mats_field[0], dict):
                mat_ids = tuple(mm.get("id", mm.get("ID", 0)) for mm in mats_field)
                mat_weights = tuple(mm.get("weight", mm.get("权重", 0)) for mm in mats_field)
            else:
                mat_ids = tuple(vd.get("material_ids", (0, 0, 0, 0)))
                mat_weights = tuple(vd.get("material_weights", (0, 0, 0, 0)))

            in2 = _dict_to_vec4(vd.get("input2_ao_roughness", vd.get("input2", {})), (0.99, 0.99, 0.99, 0.99))
            in3 = _dict_to_vec4(vd.get("input3_detail", vd.get("input3", {})), (0.5, 0.5, 0.5, 0.5))
            in4 = _dict_to_vec4(vd.get("input4_misc", vd.get("input4", {})), (0.04, 0.004, 0.004, 0.004))

            geo.vertices.append(LevelGeoVertex.from_values(
                pos=pos,
                normal=norm + (norm_w,),
                material_ids=mat_ids,
                material_weights=mat_weights,
                in2=in2,
                in3=in3,
                in4=in4,
            ))

        # chunks
        chunk_list = geo_data.get("chunks", geo_data.get("地形块列表", []))
        geo.chunks = []
        for cd in chunk_list:
            c = LevelGeoChunk()
            vr = cd.get("vertex_range", {})
            ir = cd.get("index_range", {})
            sr = cd.get("subchunk_range", {})
            c.vtx_start = vr.get("start", cd.get("vtx_start", 0))
            c.vtx_count = vr.get("count", cd.get("vtx_count", 0))
            c.idx_start = ir.get("start", cd.get("idx_start", 0))
            c.idx_count = ir.get("count", cd.get("idx_count", 0))
            c.subchunk_start = sr.get("start", cd.get("subchunk_start", 0))
            c.subchunk_count = sr.get("count", cd.get("subchunk_count", 0))
            cb = cd.get("bounds", {})
            c.min = _dict_to_vec3(cb.get("min", cd.get("min", (0, 0, 0))))
            c.max = _dict_to_vec3(cb.get("max", cd.get("max", (0, 0, 0))))
            c.pad = tuple(cd.get("pad", (0, 0, 0, 0)))
            geo.chunks.append(c)

        # subchunks
        sub_list = geo_data.get("subchunks", geo_data.get("材质子区间列表", []))
        geo.subchunks = []
        for sd in sub_list:
            s = LevelGeoSubchunk()
            mat_field = sd.get("material", {})
            s.material_id = mat_field.get("id", mat_field.get("ID", sd.get("material_id", 0))) if isinstance(mat_field, dict) else sd.get("material_id", 0)
            tr = sd.get("triangle_range", {})
            s.triangle_start = tr.get("start", sd.get("triangle_start", 0))
            s.triangle_end = tr.get("end", sd.get("triangle_end", 0))
            s.triangle_count = tr.get("count", sd.get("triangle_count", 0))
            vr = sd.get("vertex_range", {})
            s.vtx_start = vr.get("start", sd.get("vtx_start", 0))
            s.vtx_end = vr.get("end", sd.get("vtx_end", 0))
            s.vtx_count = vr.get("count", sd.get("vtx_count", 0))
            geo.subchunks.append(s)

        m.geo = geo

        # 安全检查: vertex_count 必须等于实际顶点列表长度
        # 不匹配会导致 meshopt 编码器丢顶点或读取越界
        if geo.vertex_count != len(geo.vertices):
            print("警告: vertex_count(%d) != 实际顶点数(%d), 已自动修正" % (
                geo.vertex_count, len(geo.vertices)))
            geo.vertex_count = len(geo.vertices)
    else:
        m.geo = None

    m.toc = None
    return m


# ============================================================
#  信息打印
# ============================================================
def print_info(meshes):
    print("版本: 0x%X" % meshes.version)
    print("LOD0: %s" % ("已烘焙" if meshes.lod_raw else "缺失"))
    print("全局包围盒 max: %s" % (meshes.max_pos,))
    print("全局包围盒 min: %s" % (meshes.min_pos,))
    if meshes.toc:
        print("TOC 段: %s" % ", ".join(meshes.toc.keys()))

    if meshes.desc:
        ts = meshes.desc.get("timeStamp")
        print("DESC 文件名: %s" % meshes.desc.get("fileName", "?"))
        print("DESC 编辑器: %s" % meshes.desc.get("editor", "?"))
        if ts is not None:
            try:
                print("DESC 时间戳: %d (%s)" % (ts, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))))
            except Exception:
                print("DESC 时间戳: %d" % ts)
        ev = meshes.desc.get("editorVersion")
        gv = meshes.desc.get("engineVersion")
        if ev is not None:
            print("编辑器版本: %s" % (list(ev),))
        if gv is not None:
            print("引擎版本: %s" % (list(gv),))

    if meshes.geo:
        geo = meshes.geo
        print("\n[GEO0 几何]")
        print("  顶点数: %d" % geo.vertex_count)
        print("  索引数: %d (三角形 %d)" % (geo.index_count, geo.index_count // 3))
        print("  地形块: %d  云块: %d" % (geo.chunk_count, geo.cloud_chunk_count))
        print("  材质子区间: %d" % geo.subchunk_count)


# ============================================================
#  CLI
# ============================================================
def _detect_mode(input_path, output_path, explicit_mode=None):
    """根据文件扩展名或显式参数判断转换模式。"""
    if explicit_mode:
        return explicit_mode

    in_ext = input_path.rsplit(".", 1)[-1].lower() if "." in input_path else ""
    out_ext = output_path.rsplit(".", 1)[-1].lower() if "." in output_path else ""

    if in_ext == "meshes" and out_ext == "obj":
        return "m2o"
    if in_ext == "obj" and out_ext == "meshes":
        return "o2m"
    if in_ext == "meshes" and out_ext == "json":
        return "m2j"
    if in_ext == "json" and out_ext == "meshes":
        return "j2m"
    if in_ext == "meshes" and not out_ext:
        return "m2o"  # 默认输出到 stdout

    raise ValueError("无法自动判断转换方向 (输入: .%s, 输出: .%s), 请用 --mode 指定" % (in_ext, out_ext))


# ============================================================
#  交互式 OBJ 选择菜单
# ============================================================
def _interactive_obj_selector(start_dir=None, reversible_only=False, allow_empty=False):
    """
    交互式目录浏览 + OBJ 文件选择菜单。
    用户通过序号选择多个 .obj 文件。
    返回: 选中的文件路径列表, 或 None 表示取消。

    reversible_only: True 时只显示可逆 OBJ (含 @MESHES_META),
                     False 时只显示标准 OBJ (不含 @MESHES_META)。
    """
    if start_dir:
        current_dir = os.path.abspath(start_dir)
    else:
        current_dir = os.getcwd()

    selected = []  # 已选中的文件 (绝对路径)
    selected_set = set()

    label = "可逆OBJ" if reversible_only else "标准OBJ"
    title_hint = " (仅显示可逆OBJ, 含完整meshes数据)" if reversible_only else ""

    while True:
        # ---- 收集目录内容 ----
        try:
            entries = sorted(os.listdir(current_dir))
        except OSError as e:
            print("无法读取目录: %s" % e)
            current_dir = os.path.dirname(current_dir) or "/"
            continue

        subdirs = []
        obj_files = []
        for name in entries:
            full = os.path.join(current_dir, name)
            if os.path.isdir(full):
                subdirs.append(name)
            elif name.lower().endswith(".obj"):
                is_rev = _is_reversible_obj(full)
                if reversible_only and not is_rev:
                    continue
                if not reversible_only and is_rev:
                    continue
                obj_files.append((name, is_rev))

        # ---- 显示菜单 ----
        print("\n" + "=" * 60)
        print("当前目录: %s" % current_dir)
        print("选择%s%s" % (label, title_hint))
        if selected:
            print("已选 %d 个文件:" % len(selected))
            for i, s in enumerate(selected):
                mat = _material_from_filename(s)
                print("  [%d] %s -> %s" % (i, os.path.basename(s), mat))
        print("-" * 60)

        idx = 1
        menu_items = []  # (序号, 类型, 路径/动作)

        # 上级目录
        parent = os.path.dirname(current_dir)
        if parent != current_dir:
            print("  %2d.  [上级目录] .." % idx)
            menu_items.append((idx, "up", parent))
            idx += 1

        # 子目录
        for d in subdirs:
            print("  %2d.  [文件夹] %s/" % (idx, d))
            menu_items.append((idx, "dir", os.path.join(current_dir, d)))
            idx += 1

        # OBJ 文件
        for fname, is_rev in obj_files:
            full = os.path.join(current_dir, fname)
            mat = _material_from_filename(fname)
            mark = " *" if full in selected_set else "  "
            tag = "[非法OBJ]" if is_rev else "[OBJ]"
            print("  %2d.  %s%s %s  (%s)" % (idx, tag, mark, fname, mat))
            menu_items.append((idx, "obj", full))
            idx += 1

        if not obj_files and not subdirs:
            print("  (空目录)")
        elif not obj_files:
            print("  (当前目录无%s)" % label)

        print("-" * 60)
        print("操作: 输入序号选择/取消 OBJ, 'a' 全选当前目录, 'c' 清空, 'd' 完成, 'q' 取消")
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return None

        if not choice:
            continue

        # 完成
        if choice == "d":
            if not selected and not allow_empty:
                print("还未选择任何文件! (或按 q 取消)")
                continue
            return selected

        # 取消
        if choice == "q":
            return None

        # 全选当前目录 OBJ
        if choice == "a":
            for fname, is_rev in obj_files:
                full = os.path.join(current_dir, fname)
                if full not in selected_set:
                    selected.append(full)
                    selected_set.add(full)
            print("已全选当前目录的 %d 个 %s" % (len(obj_files), label))
            continue

        # 清空
        if choice == "c":
            selected.clear()
            selected_set.clear()
            print("已清空选择")
            continue

        # 数字选择
        try:
            num = int(choice)
        except ValueError:
            print("无效输入: %s" % choice)
            continue

        matched = None
        for mi in menu_items:
            if mi[0] == num:
                matched = mi
                break

        if not matched:
            print("序号超出范围: %d" % num)
            continue

        kind = matched[1]
        path = matched[2]

        if kind == "up" or kind == "dir":
            current_dir = path
        elif kind == "obj":
            if path in selected_set:
                selected.remove(path)
                selected_set.discard(path)
                print("已取消: %s" % os.path.basename(path))
            else:
                selected.append(path)
                selected_set.add(path)
                print("已选择: %s" % os.path.basename(path))


def _prompt_path(label, must_exist=False, default=None):
    """提示输入文件路径, 返回路径或 None。"""
    hint = ""
    if default:
        hint = " (回车=%s)" % default
    try:
        p = input("%s%s: " % (label, hint)).strip().strip('"').strip("'")
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return None
    if not p:
        return default
    if must_exist and not os.path.exists(p):
        print("文件不存在: %s" % p)
        return None
    return p


def _smart_output(input_path, ext):
    """根据输入路径自动推导输出路径。"""
    base = os.path.splitext(input_path)[0]
    return base + "." + ext


def interactive_menu():
    """交互式菜单界面 — 方便选择转换方向。"""
    print("=" * 60)
    print("  That Sky Level .meshes 全方位转换器")
    print("  纯 Python / 零依赖 / 适配 Termux")
    print("=" * 60)

    while True:
        print("\n" + "-" * 60)
        print("  --- meshes ↔ OBJ ---")
        print("  1. .meshes → .obj  (可逆, 含全部信息, 可直接转回)")
        print("  2. .meshes → .obj  (标准, 仅几何)")
        print("  3. .obj → .meshes  (自动检测可逆/标准)")
        print("  4. .meshes → 多个 .obj  (按材质拆分)")
        print("  5. 多个 .obj → .meshes  (交互式, 可加入非法OBJ)")
        print("  --- meshes ↔ JSON ---")
        print("  6. .meshes → .json")
        print("  7. .json → .meshes")
        print("  --- 其他 ---")
        print("  8. 查看文件信息")
        print("  0. 退出")
        print("-" * 60)

        try:
            choice = input("请选择 [0-8]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if choice == "0":
            print("再见！")
            break

        elif choice == "1":
            # meshes -> obj (可逆)
            inp = _prompt_path("输入 .meshes", must_exist=True)
            if not inp:
                continue
            outp = _prompt_path("输出 .obj", default=_smart_output(inp, "obj"))
            if not outp:
                continue
            try:
                with open(inp, "rb") as f:
                    meshes = LevelMeshes.from_file_buffer(f.read())
                obj = meshes_to_obj_full(meshes)
                with open(outp, "w", encoding="utf-8") as f:
                    f.write(obj)
                print("\n已写出 (可逆): %s" % outp)
                print_info(meshes)
            except Exception as e:
                print("转换失败: %s" % e)
                import traceback
                traceback.print_exc()

        elif choice == "2":
            # meshes -> obj (标准)
            inp = _prompt_path("输入 .meshes", must_exist=True)
            if not inp:
                continue
            outp = _prompt_path("输出 .obj", default=_smart_output(inp, "obj"))
            if not outp:
                continue
            merge = input("合并为单个对象? (y/N): ").strip().lower() == "y"
            try:
                with open(inp, "rb") as f:
                    meshes = LevelMeshes.from_file_buffer(f.read())
                obj = touch_object(meshes, merge)
                with open(outp, "w", encoding="utf-8") as f:
                    f.write(obj)
                print("\n已写出 (标准): %s" % outp)
                print_info(meshes)
            except Exception as e:
                print("转换失败: %s" % e)

        elif choice == "3":
            # obj -> meshes
            inp = _prompt_path("输入 .obj", must_exist=True)
            if not inp:
                continue
            outp = _prompt_path("输出 .meshes", default=_smart_output(inp, "meshes"))
            if not outp:
                continue
            try:
                with open(inp, "r", encoding="utf-8") as f:
                    obj_text = f.read()
                has_meta = META_BEGIN in obj_text
                meshes = obj_to_meshes(obj_text)
                data = meshes.to_file_buffer()
                with open(outp, "wb") as f:
                    f.write(data)
                method = "精确还原 (可逆OBJ)" if has_meta else "BFS 邻接分块 (标准OBJ)"
                print("\n转换方式: %s" % method)
                print("已写出: %s" % outp)
                print_info(meshes)
            except Exception as e:
                print("转换失败: %s" % e)
                import traceback
                traceback.print_exc()

        elif choice == "4":
            # meshes -> 多个 obj (按材质拆分)
            inp = _prompt_path("输入 .meshes", must_exist=True)
            if not inp:
                continue
            outp = _prompt_path("输出基础路径 (如 output)", default=_smart_output(inp, "obj"))
            if not outp:
                continue
            use_sub = input("使用 subchunk 材质区间? (y/N): ").strip().lower() == "y"
            try:
                with open(inp, "rb") as f:
                    meshes = LevelMeshes.from_file_buffer(f.read())
                results = touch_object_multi(meshes, outp, use_sub)
                print("\n共输出 %d 个材质 OBJ:" % len(results))
                for mat_id, mat_name, path, vc, fc in results:
                    print("  %s (ID=%d): %d 顶点, %d 面" % (mat_name, mat_id, vc, fc))
            except Exception as e:
                print("转换失败: %s" % e)

        elif choice == "5":
            # 多 obj -> meshes (交互式, 可选加入非法OBJ)
            start_dir = _prompt_path("起始目录 (回车=当前目录)", default=os.getcwd())
            if not start_dir:
                continue

            # ---- 阶段1: 选择标准 OBJ (可不选, 直接跳过) ----
            print("\n" + "=" * 60)
            print("阶段 1/2: 选择标准 OBJ (可不选, 直接按 d 跳过)")
            print("=" * 60)
            standard_paths = _interactive_obj_selector(start_dir, reversible_only=False, allow_empty=True)

            if standard_paths is None:
                print("已取消")
                continue

            if not standard_paths:
                print("未选择标准 OBJ, 直接进入非法OBJ选择")

            # ---- 阶段2: 选择可逆 OBJ (非法OBJ) ----
            full_paths = []
            if not standard_paths:
                # 没选标准OBJ, 非法OBJ必须选
                print("\n" + "=" * 60)
                print("阶段 2/2: 选择非法OBJ (可逆OBJ, 含完整meshes数据)")
                print("=" * 60)
                full_start_dir = _prompt_path(
                    "非法OBJ 起始目录 (回车=同上)", default=start_dir)
                if not full_start_dir:
                    continue
                full_paths = _interactive_obj_selector(full_start_dir, reversible_only=True)
                if full_paths is None:
                    print("已取消")
                    continue
                if not full_paths:
                    print("未选择任何文件")
                    continue
            else:
                # 选了标准OBJ, 非法OBJ可选
                print("\n" + "=" * 60)
                print("阶段 2/2: 是否加入非法OBJ (可逆OBJ, 含完整meshes数据)?")
                print("=" * 60)
                try:
                    add_full = input("加入非法OBJ? (y/N): ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\n已取消")
                    continue

                if add_full == "y":
                    full_start_dir = _prompt_path(
                        "非法OBJ 起始目录 (回车=同上)", default=start_dir)
                    if not full_start_dir:
                        continue
                    print("\n" + "=" * 60)
                    print("选择非法OBJ (可逆OBJ, 仅显示含 @MESHES_META 的文件)")
                    print("=" * 60)
                    full_paths = _interactive_obj_selector(full_start_dir, reversible_only=True)

                    if full_paths is None:
                        print("已取消")
                        continue

            if not standard_paths and not full_paths:
                print("未选择任何文件")
                continue

            outp = _prompt_path("输出 .meshes", default="output.meshes")
            if not outp:
                continue
            if not outp.endswith(".meshes"):
                outp += ".meshes"

            # ---- 坐标变换 (偏移+缩放) ----
            standard_transforms = None
            full_transforms = None
            try:
                do_transform = input("\n是否设置坐标偏移/缩放? (y/N): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n已取消")
                continue
            if do_transform == "y":
                standard_transforms = []
                for p in (standard_paths or []):
                    print("\n  %s:" % os.path.basename(p))
                    try:
                        ox = float(input("    偏移 X (回车=0): ").strip() or "0")
                        oy = float(input("    偏移 Y (回车=0): ").strip() or "0")
                        oz = float(input("    偏移 Z (回车=0): ").strip() or "0")
                        sc = float(input("    缩放 (回车=1): ").strip() or "1")
                    except (ValueError, EOFError, KeyboardInterrupt):
                        print("    无效输入, 跳过变换")
                        ox, oy, oz, sc = 0.0, 0.0, 0.0, 1.0
                    standard_transforms.append(((ox, oy, oz), sc))
                    print("    -> offset=(%.2f, %.2f, %.2f) scale=%.4f" % (ox, oy, oz, sc))

                full_transforms = []
                for p in (full_paths or []):
                    print("\n  %s:" % os.path.basename(p))
                    try:
                        ox = float(input("    偏移 X (回车=0): ").strip() or "0")
                        oy = float(input("    偏移 Y (回车=0): ").strip() or "0")
                        oz = float(input("    偏移 Z (回车=0): ").strip() or "0")
                        sc = float(input("    缩放 (回车=1): ").strip() or "1")
                    except (ValueError, EOFError, KeyboardInterrupt):
                        print("    无效输入, 跳过变换")
                        ox, oy, oz, sc = 0.0, 0.0, 0.0, 1.0
                    full_transforms.append(((ox, oy, oz), sc))
                    print("    -> offset=(%.2f, %.2f, %.2f) scale=%.4f" % (ox, oy, oz, sc))

            # ---- 影子 OBJ 选择 (多个可逆OBJ时) ----
            shadow_index = 0
            if len(full_paths) > 1:
                print("\n" + "=" * 60)
                print("选择影子 OBJ (提供 LOD0/DESC/meshopt_version 等全部元数据)")
                print("其他可逆 OBJ 只贡献几何 (顶点材质权重 + 网格)")
                print("=" * 60)
                for i, fp in enumerate(full_paths):
                    try:
                        with open(fp, "r", encoding="utf-8") as f:
                            obj_text = f.read()
                        tmp_m = obj_to_meshes_full(obj_text)
                        di = tmp_m.desc if tmp_m.desc else {}
                        fn = di.get("fileName", "")
                        ts = di.get("timeStamp", 0)
                        lod_len = len(tmp_m.lod_raw) if tmp_m.lod_raw else 0
                        baking = "含烘焙数据" if lod_len > len(LOD0_FIXED_BYTES) else "默认LOD0"
                        print("  %d. %s  (fileName=%s, %s, %s)" % (
                            i, os.path.basename(fp), fn, baking,
                            "LOD0=%d字节" % lod_len))
                    except Exception:
                        print("  %d. %s  (无法读取)" % (i, os.path.basename(fp)))
                print("  (回车=默认第0个)")
                try:
                    shadow_choice = input("影子 OBJ 序号: ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n已取消")
                    continue
                if shadow_choice:
                    try:
                        shadow_index = int(shadow_choice)
                    except ValueError:
                        print("无效输入, 使用默认 0")
                        shadow_index = 0

            # ---- 确认 ----
            print("\n" + "=" * 60)
            print("已选文件:")
            if standard_paths:
                print("  [标准OBJ] %d 个:" % len(standard_paths))
                for p in standard_paths:
                    mat = _material_from_filename(p)
                    print("    %s -> %s" % (os.path.basename(p), mat))
            if full_paths:
                print("  [非法OBJ] %d 个:" % len(full_paths))
                for p in full_paths:
                    print("    %s" % os.path.basename(p))
            if full_paths and len(full_paths) > 1:
                print("  影子OBJ: 可逆OBJ #%d (%s)" % (
                    shadow_index, os.path.basename(full_paths[shadow_index])))
            print("输出: %s" % outp)
            try:
                confirm = input("\n确认转换? (回车=继续, q=取消): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n已取消")
                continue
            if confirm == "q":
                print("已取消")
                continue

            try:
                if full_paths:
                    # 混合模式: 标准 + 非法 (影子模式)
                    meshes = multi_obj_to_meshes_mixed(standard_paths, full_paths,
                                                        shadow_index=shadow_index,
                                                        standard_transforms=standard_transforms,
                                                        full_transforms=full_transforms)
                else:
                    # 纯标准模式 (兼容原有行为, 支持坐标变换)
                    meshes = multi_obj_to_meshes(standard_paths, transforms=standard_transforms)
                data = meshes.to_file_buffer()
                with open(outp, "wb") as f:
                    f.write(data)
                print("\n已写出: %s" % outp)
                print_info(meshes)
            except Exception as e:
                print("转换失败: %s" % e)
                import traceback
                traceback.print_exc()

        elif choice == "6":
            # meshes -> json
            inp = _prompt_path("输入 .meshes", must_exist=True)
            if not inp:
                continue
            outp = _prompt_path("输出 .json", default=_smart_output(inp, "json"))
            if not outp:
                continue
            try:
                with open(inp, "rb") as f:
                    meshes = LevelMeshes.from_file_buffer(f.read())
                j = meshes_to_json(meshes)
                text = json.dumps(j, indent=2, ensure_ascii=False)
                with open(outp, "w", encoding="utf-8") as f:
                    f.write(text)
                print("\n已写出: %s" % outp)
            except Exception as e:
                print("转换失败: %s" % e)

        elif choice == "7":
            # json -> meshes
            inp = _prompt_path("输入 .json", must_exist=True)
            if not inp:
                continue
            outp = _prompt_path("输出 .meshes", default=_smart_output(inp, "meshes"))
            if not outp:
                continue
            try:
                with open(inp, "r", encoding="utf-8") as f:
                    j = json.loads(f.read())
                meshes = json_to_meshes(j)
                data = meshes.to_file_buffer()
                with open(outp, "wb") as f:
                    f.write(data)
                print("\n已写出: %s" % outp)
            except Exception as e:
                print("转换失败: %s" % e)

        elif choice == "8":
            # 查看文件信息
            inp = _prompt_path("输入 .meshes", must_exist=True)
            if not inp:
                continue
            try:
                with open(inp, "rb") as f:
                    meshes = LevelMeshes.from_file_buffer(f.read())
                print_info(meshes)
            except Exception as e:
                print("解析失败: %s" % e)

        else:
            print("无效选择: %s" % choice)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="That Sky Level .meshes 全方位转换器 (纯 Python / Termux)")
    parser.add_argument("-i", "--input", help="输入文件")
    parser.add_argument("-o", "--output", help="输出文件 (省略且非 --info 时打印到 stdout)")
    parser.add_argument("-m", "--merge", action="store_true", help="meshes->obj 时合并为单个对象")
    parser.add_argument("--full", action="store_true",
                        help="meshes->obj 时生成可逆 OBJ (含全部信息, 可直接转回)")
    parser.add_argument("--info", action="store_true", help="仅打印 .meshes 文件信息")
    parser.add_argument("--split-material", action="store_true",
                        help="meshes->obj 时按材质拆分多个 OBJ (顶点取权重最大材质, 面取多数投票)")
    parser.add_argument("--use-subchunk", action="store_true",
                        help="配合 --split-material: 使用 subchunk 材质区间 (游戏原始分配) 而非顶点权重")
    parser.add_argument("--multi-obj", action="store_true",
                        help="多 OBJ -> meshes: 启动交互式菜单选择 OBJ (以文件名确定材质, 交界处权重过渡)")
    parser.add_argument("--include-full", action="store_true",
                        help="配合 --multi-obj: 额外选择可逆OBJ (非法OBJ, 含完整meshes数据) 合并")
    parser.add_argument("--shadow-index", type=int, default=0,
                        help="配合 --multi-obj: 指定哪个可逆OBJ作为影子 (提供LOD0/DESC等全部元数据, 0-based, 默认0)")
    parser.add_argument("--offset", metavar="X,Y,Z", default=None,
                        help="所有OBJ统一坐标偏移, 逗号分隔 (如 10,0,-5). 交互模式下可逐个设置")
    parser.add_argument("--scale", type=float, default=None,
                        help="所有OBJ统一缩放系数 (如 2.0). 交互模式下可逐个设置")
    parser.add_argument("--dir", metavar="PATH", help="交互式菜单的起始目录 (配合 --multi-obj)")
    parser.add_argument("--mode", choices=["m2o", "m2of", "o2m", "m2j", "j2m"],
                        help="显式指定转换方向: m2o=meshes->obj(标准), m2of=meshes->obj(可逆), "
                             "o2m=obj->meshes, m2j=meshes->json, j2m=json->meshes")
    args = parser.parse_args(argv)

    # 无参数时启动交互式菜单
    if not argv and len(sys.argv) <= 1:
        interactive_menu()
        return 0

    # --multi-obj 模式 (交互式多 OBJ -> meshes, 可选加入非法OBJ)
    if args.multi_obj:
        # ---- 阶段1: 选择标准 OBJ (可不选, 直接跳过) ----
        print("=" * 60)
        print("阶段 1/2: 选择标准 OBJ (可不选, 直接按 d 跳过)")
        print("=" * 60)

        standard_paths = _interactive_obj_selector(args.dir, reversible_only=False, allow_empty=True)
        if standard_paths is None:
            print("已取消, 退出")
            return 0

        if not standard_paths:
            print("未选择标准 OBJ, 直接进入非法OBJ选择")

        # ---- 阶段2: 选择可逆 OBJ (非法OBJ) ----
        full_paths = []
        if not standard_paths or args.include_full:
            # 没选标准OBJ时必须选非法OBJ; 选了标准OBJ时用 --include-full 控制
            print("\n" + "=" * 60)
            print("阶段 2/2: 选择非法OBJ (可逆OBJ, 含完整meshes数据)")
            print("=" * 60)

            full_paths = _interactive_obj_selector(args.dir, reversible_only=True)
            if full_paths is None:
                print("已取消, 退出")
                return 0
            if not full_paths and not standard_paths:
                print("未选择任何文件, 退出")
                return 0

        if not standard_paths and not full_paths:
            print("未选择任何文件, 退出")
            return 0

        # 输出路径
        out_path = args.output
        if not out_path:
            print("\n请输入输出 .meshes 路径 (回车=output.meshes):")
            try:
                out_path = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n已取消")
                return 0
            if not out_path:
                out_path = "output.meshes"
        if not out_path.endswith(".meshes"):
            out_path += ".meshes"

        # 坐标变换 (CLI: --offset/--scale 对所有OBJ统一应用)
        cli_offset = None
        cli_scale = None
        if args.offset:
            try:
                parts = args.offset.split(",")
                cli_offset = (float(parts[0]), float(parts[1]), float(parts[2]))
            except (ValueError, IndexError):
                print("错误: --offset 格式应为 X,Y,Z")
                return 1
        if args.scale is not None:
            cli_scale = args.scale

        # 构建变换列表
        std_transforms = None
        full_transforms = None
        if cli_offset is not None or cli_scale is not None:
            off = cli_offset if cli_offset else (0.0, 0.0, 0.0)
            sc = cli_scale if cli_scale else 1.0
            if standard_paths:
                std_transforms = [(off, sc)] * len(standard_paths)
            if full_paths:
                full_transforms = [(off, sc)] * len(full_paths)
            print("  坐标变换: offset=%s scale=%s" % (off, sc))

        # 确认
        print("\n" + "=" * 60)
        print("已选文件:")
        if standard_paths:
            print("  [标准OBJ] %d 个:" % len(standard_paths))
            for p in standard_paths:
                mat = _material_from_filename(p)
                print("    %s -> %s" % (os.path.basename(p), mat))
        if full_paths:
            print("  [非法OBJ] %d 个:" % len(full_paths))
            for p in full_paths:
                print("    %s" % os.path.basename(p))
            if len(full_paths) > 1:
                print("  影子OBJ: 可逆OBJ #%d (--shadow-index)" % args.shadow_index)
        print("输出: %s" % out_path)
        try:
            confirm = input("\n确认转换? (回车=继续, q=取消): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消")
            return 0
        if confirm == "q":
            print("已取消")
            return 0

        try:
            if full_paths:
                meshes = multi_obj_to_meshes_mixed(standard_paths, full_paths,
                                                    shadow_index=args.shadow_index,
                                                    standard_transforms=std_transforms,
                                                    full_transforms=full_transforms)
            else:
                meshes = multi_obj_to_meshes(standard_paths, transforms=std_transforms)
            data = meshes.to_file_buffer()
            with open(out_path, "wb") as f:
                f.write(data)
            print("\n已写出: %s" % out_path)
            print_info(meshes)
        except Exception as e:
            print("转换失败: %s" % e, file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
            return 1
        return 0

    # 非 multi-obj 模式必须提供 -i
    if not args.input:
        parser.error("the following arguments are required: -i/--input")

    # --info 模式
    if args.info:
        try:
            with open(args.input, "rb") as f:
                buffer = f.read()
        except OSError as e:
            print("读取文件失败: %s" % e, file=sys.stderr)
            return 1
        try:
            meshes = LevelMeshes.from_file_buffer(buffer)
        except Exception as e:
            print("解析 .meshes 失败: %s" % e, file=sys.stderr)
            return 1
        print_info(meshes)
        return 0

    # 判断转换方向
    mode = _detect_mode(args.input, args.output or "", args.mode)

    try:
        if mode in ("m2o", "m2of"):
            # meshes -> obj
            with open(args.input, "rb") as f:
                buffer = f.read()
            meshes = LevelMeshes.from_file_buffer(buffer)

            if args.split_material:
                # 按材质拆分多个 OBJ
                if not args.output:
                    print("错误: --split-material 需要指定 -o 输出路径", file=sys.stderr)
                    return 1
                print("按材质拆分输出 (use_subchunk=%s)..." % args.use_subchunk)
                results = touch_object_multi(meshes, args.output, args.use_subchunk)
                print("\n共输出 %d 个材质 OBJ:" % len(results))
                for mat_id, mat_name, path, vc, fc in results:
                    print("  %s (ID=%d): %d 顶点, %d 面" % (mat_name, mat_id, vc, fc))
                print_info(meshes)
            elif mode == "m2of" or args.full:
                # 可逆 OBJ (含全部信息)
                obj = meshes_to_obj_full(meshes)
                if args.output:
                    with open(args.output, "w", encoding="utf-8") as f:
                        f.write(obj)
                    print("已写出 (可逆): %s" % args.output)
                    print_info(meshes)
                else:
                    sys.stdout.write(obj)
            else:
                obj = touch_object(meshes, args.merge)
                if args.output:
                    with open(args.output, "w", encoding="utf-8") as f:
                        f.write(obj)
                    print("已写出: %s" % args.output)
                    print_info(meshes)
                else:
                    sys.stdout.write(obj)

        elif mode == "o2m":
            # obj -> meshes (自动检测可逆/标准)
            with open(args.input, "r", encoding="utf-8") as f:
                obj_text = f.read()
            has_meta = META_BEGIN in obj_text
            meshes = obj_to_meshes(obj_text)
            data = meshes.to_file_buffer()
            with open(args.output, "wb") as f:
                f.write(data)
            method = "精确还原 (可逆OBJ)" if has_meta else "BFS 邻接分块 (标准OBJ)"
            print("转换方式: %s" % method)
            print("已写出: %s" % args.output)
            print_info(meshes)

        elif mode == "m2j":
            # meshes -> json
            with open(args.input, "rb") as f:
                buffer = f.read()
            meshes = LevelMeshes.from_file_buffer(buffer)
            j = meshes_to_json(meshes)
            text = json.dumps(j, indent=2, ensure_ascii=False)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(text)
                print("已写出: %s" % args.output)
            else:
                sys.stdout.write(text)

        elif mode == "j2m":
            # json -> meshes
            with open(args.input, "r", encoding="utf-8") as f:
                text = f.read()
            j = json.loads(text)
            meshes = json_to_meshes(j)
            data = meshes.to_file_buffer()
            with open(args.output, "wb") as f:
                f.write(data)
            print("已写出: %s" % args.output)

    except Exception as e:
        print("转换失败: %s" % e, file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
