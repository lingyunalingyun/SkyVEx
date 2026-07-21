#!/usr/bin/env python3
# SkyVEx — pure Python .mesh parser (all versions)
# Copyright (c) 2026 lingyunalingyun
# License: MIT (see LICENSE)
#
# Parses Sky: Children of the Light .mesh model files.
# Supports versions 0x17–0x20 with a unified code path.
# Zero native dependencies — LZ4 decompression has a pure Python fallback.

import struct
import os


def _lz4_decompress(src, uncompressed_size):
    try:
        import lz4.block
        return lz4.block.decompress(src, uncompressed_size=uncompressed_size)
    except Exception:
        pass

    i = 0
    out = bytearray()
    src_len = len(src)

    def _read_len(base):
        nonlocal i
        ln = base
        if ln == 15:
            while True:
                if i >= src_len:
                    raise ValueError("LZ4: truncated length")
                s = src[i]; i += 1
                ln += s
                if s != 255:
                    break
        return ln

    while i < src_len:
        token = src[i]; i += 1
        lit_len = _read_len(token >> 4)
        if i + lit_len > src_len:
            raise ValueError("LZ4: literal out of range")
        out += src[i:i + lit_len]
        i += lit_len
        if i >= src_len:
            break
        if i + 2 > src_len:
            raise ValueError("LZ4: missing match offset")
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0:
            raise ValueError("LZ4: invalid offset=0")
        match_len = _read_len(token & 0x0F) + 4
        start = len(out) - offset
        if start < 0:
            raise ValueError("LZ4: offset beyond buffer")
        for _ in range(match_len):
            out.append(out[start]); start += 1

    if len(out) != uncompressed_size:
        raise ValueError(f"LZ4: size mismatch: got {len(out)} expected {uncompressed_size}")
    return bytes(out)


def _read_f32(data, off):
    return struct.unpack_from('<f', data, off)[0]

def _read_u32(data, off):
    return struct.unpack_from('<I', data, off)[0]

def _read_i32(data, off):
    return struct.unpack_from('<i', data, off)[0]

def _read_u16(data, off):
    return struct.unpack_from('<H', data, off)[0]

def _read_half(data, off):
    return struct.unpack_from('<e', data, off)[0]


def parse_mesh(filepath):
    """Parse a .mesh file.

    Returns dict with keys:
        vertices: [(x, y, z), ...]
        uvs: [(u, v), ...]
        faces: [(a, b, c), ...]
        bone_weights: [[(bone_idx, weight), ...], ...] or []
        skeleton: [{"name", "parent_index", "inv_bind_matrix"}, ...] or None
        version: int
        animated: bool
    """
    with open(filepath, 'rb') as f:
        raw = f.read()

    if len(raw) < 0x58:
        raise ValueError(f"File too small ({len(raw)} bytes)")

    version = _read_i32(raw, 0x00)

    if version < 0x1E:
        return _parse_uncompressed(raw, version, filepath)
    else:
        return _parse_compressed(raw, version, filepath)


def _parse_uncompressed(raw, version, filepath):
    """Parse uncompressed .mesh files (v0x17–0x1C).

    These versions store vertex/UV/index data at fixed offsets
    without LZ4 compression.
    """
    file_size = len(raw)

    if version <= 0x19:
        vertex_count_off = None
        index_count_off = 0x75
        vertex_start = 0x9D

        pos_01 = None
        for i in range(min(file_size, 256)):
            if raw[i] == 0x01:
                pos_01 = i
                break

        if pos_01 is not None:
            vc_off = pos_01 + 45
            if vc_off + 4 <= file_size:
                vertex_count_off = vc_off

        if vertex_count_off is None or vertex_count_off + 4 > file_size:
            raise ValueError("Cannot locate vertex count")
        if index_count_off + 4 > file_size:
            raise ValueError("Cannot locate index count")

        shared_verts = _read_u32(raw, vertex_count_off)
        total_verts = _read_u32(raw, index_count_off)
        is_idx32 = True
    else:
        vertex_count_off = 0x66
        index_count_off = 0x6A
        vertex_start = 0x92

        if vertex_count_off + 4 > file_size or index_count_off + 4 > file_size:
            raise ValueError("File too small for header offsets")

        shared_verts = _read_u32(raw, vertex_count_off)
        total_verts = _read_u32(raw, index_count_off)
        is_idx32 = True

    vertex_bytes = shared_verts * 16
    if vertex_start + vertex_bytes > file_size:
        raise ValueError("Vertex data out of range")

    vertices = []
    for i in range(shared_verts):
        off = vertex_start + i * 16
        x = _read_f32(raw, off)
        y = _read_f32(raw, off + 4)
        z = _read_f32(raw, off + 8)
        vertices.append((x, y, z))

    normal_bytes = shared_verts * 4
    normal_start = vertex_start + vertex_bytes

    uv_start = normal_start + normal_bytes
    uv_bytes = shared_verts * 16

    uvs = []
    uv_end = min(uv_start + uv_bytes, file_size)
    for i in range(shared_verts):
        off = uv_start + i * 16
        if off + 8 <= uv_end:
            u = _read_f32(raw, off)
            v = _read_f32(raw, off + 4)
            uvs.append((u, v))
        else:
            uvs.append((0.0, 0.0))

    idx_unit = 4 if is_idx32 else 2
    face_count = total_verts // 3 if not is_idx32 else total_verts // 3
    index_start = uv_start + uv_bytes

    if is_idx32:
        index_byte_count = total_verts * 4
    else:
        index_byte_count = total_verts * 2

    index_end = min(index_start + index_byte_count, file_size)

    faces = []
    p = index_start
    while p + idx_unit * 3 <= index_end:
        if is_idx32:
            a = _read_u32(raw, p)
            b = _read_u32(raw, p + 4)
            c = _read_u32(raw, p + 8)
            p += 12
        else:
            a = _read_u16(raw, p)
            b = _read_u16(raw, p + 2)
            c = _read_u16(raw, p + 4)
            p += 6
        faces.append((a, b, c))

    return {
        'vertices': vertices,
        'uvs': uvs,
        'faces': faces,
        'bone_weights': [],
        'skeleton': None,
        'version': version,
        'animated': False,
    }


def _parse_compressed(raw, version, filepath):
    """Parse LZ4-compressed .mesh files (v0x1E–0x20).

    These versions wrap vertex data in an LZ4-compressed payload,
    support quantized positions/UVs, bone weights, and embedded skeletons.
    """
    file_size = len(raw)
    animated = raw[0x48] != 0
    payload_off = 0x4E if version >= 0x20 else 0x4A

    if payload_off + 12 > file_size:
        raise ValueError("File too small for compression header")

    is_compressed = _read_i32(raw, payload_off)
    compressed_size = _read_i32(raw, payload_off + 4)
    uncompressed_size = _read_i32(raw, payload_off + 8)

    if compressed_size <= 0 or uncompressed_size <= 0:
        raise ValueError("Invalid compression sizes")
    if payload_off + 12 + compressed_size > file_size:
        raise ValueError("Compressed data out of range")

    src = raw[payload_off + 12: payload_off + 12 + compressed_size]
    skeleton_raw = raw[payload_off + 12 + compressed_size:]

    if is_compressed:
        dest = _lz4_decompress(src, uncompressed_size)
    else:
        dest = src

    p = 4

    aabb_a = (_read_f32(dest, p), _read_f32(dest, p+4), _read_f32(dest, p+8)); p += 12
    aabb_b = (_read_f32(dest, p), _read_f32(dest, p+4), _read_f32(dest, p+8)); p += 12
    aabb_a2 = (_read_f32(dest, p), _read_f32(dest, p+4), _read_f32(dest, p+8)); p += 12
    aabb_b2 = (_read_f32(dest, p), _read_f32(dest, p+4), _read_f32(dest, p+8)); p += 12

    quant_min = [_read_f32(dest, p + i*4) for i in range(8)]; p += 32
    quant_max = [_read_f32(dest, p + i*4) for i in range(8)]; p += 32

    shared_verts = _read_u32(dest, p); p += 4
    total_verts = _read_u32(dest, p); p += 4
    is_idx32 = _read_u32(dest, p) != 0; p += 4
    num_points = _read_u32(dest, p); p += 4
    prop11 = _read_u32(dest, p); p += 4
    prop12 = _read_u32(dest, p); p += 4
    prop13 = _read_u32(dest, p); p += 4
    prop14 = _read_u32(dest, p); p += 4

    load_norms = dest[p] != 0; p += 1
    load_info2 = dest[p] != 0; p += 1
    p += 1

    skip_pos = _read_u32(dest, p); p += 4
    skip_uvs = _read_u32(dest, p); p += 4
    flag3 = _read_u32(dest, p); p += 4
    p += 0x10

    face_count = total_verts // 3
    idx_unit = 4 if is_idx32 else 2

    # ── Vertices ──
    vertices = []
    if skip_pos == 0:
        for i in range(shared_verts):
            off = p + i * 16
            x = _read_f32(dest, off)
            y = _read_f32(dest, off + 4)
            z = _read_f32(dest, off + 8)
            vertices.append((x, y, z))
        p += shared_verts * 16

    # ── Normals (skip) ──
    if load_norms:
        p += shared_verts * 4

    # ── UVs ──
    uvs = []
    if skip_uvs == 0:
        for i in range(shared_verts):
            off = p + i * 16
            u = float(_read_half(dest, off))
            v = float(_read_half(dest, off + 2))
            uvs.append((u, v))
        p += shared_verts * 16

    # ── Bone weights ──
    bone_weights = []
    if animated:
        for i in range(shared_verts):
            off = p + i * 8
            weights = []
            for j in range(4):
                bi = dest[off + j]
                wi = dest[off + 4 + j]
                if bi > 0 and wi > 0:
                    weights.append((bi - 1, wi / 255.0))
            bone_weights.append(weights)
        p += shared_verts * 8

    # ── Indices ──
    faces = []
    for i in range(face_count):
        if is_idx32:
            a = _read_i32(dest, p); p += 4
            b = _read_i32(dest, p); p += 4
            c = _read_i32(dest, p); p += 4
        else:
            a = _read_u16(dest, p); p += 2
            b = _read_u16(dest, p); p += 2
            c = _read_u16(dest, p); p += 2
        faces.append((a, b, c))

    # ── Skip optional sections ──
    if load_info2:
        p += total_verts * idx_unit
    if num_points > 0:
        p += shared_verts * idx_unit
    if prop11 > 0:
        p += shared_verts * idx_unit
    if prop12 > 0:
        p += prop12 * idx_unit
    if prop13 > 0:
        p += prop13 * 4
    if prop14 > 0:
        p += prop14 * (8 if is_idx32 else 4)

    p += face_count * 4

    # ── Quantized positions ──
    if skip_pos > 0:
        ax, ay, az = aabb_a2
        sx = aabb_b2[0] - ax
        sy = aabb_b2[1] - ay
        sz = aabb_b2[2] - az

        for i in range(shared_verts):
            packed = _read_u32(dest, p + i * 4)
            qz = packed & 0x3FF
            qy = (packed >> 10) & 0x3FF
            qx = (packed >> 20) & 0x3FF
            x = ax + (qx / 1023.0) * sx
            y = ay + (qy / 1023.0) * sy
            z = az + (qz / 1023.0) * sz
            vertices.append((x, y, z))
        p += shared_verts * 4
        p += shared_verts

    # ── Quantized UVs ──
    if skip_uvs > 0:
        uv_min_u = quant_min[0]
        uv_min_v = quant_min[1]
        uv_size_u = quant_max[0] - uv_min_u
        uv_size_v = quant_max[1] - uv_min_v

        for i in range(shared_verts):
            off = p + i * 4
            u_hi = dest[off]
            v_hi = dest[off + 1]
            u_lo = dest[off + 2]
            v_lo = dest[off + 3]
            u_norm = ((u_hi << 8) | u_lo) / 65535.0
            v_norm = ((v_hi << 8) | v_lo) / 65535.0
            u = uv_min_u + u_norm * uv_size_u
            v = uv_min_v + v_norm * uv_size_v
            uvs.append((u, v))
        p += shared_verts * 4

    # ── Embedded skeleton ──
    skeleton = None
    if animated and len(skeleton_raw) >= 85:
        skeleton = _try_parse_skeleton(skeleton_raw)

    return {
        'vertices': vertices,
        'uvs': uvs,
        'faces': faces,
        'bone_weights': bone_weights,
        'skeleton': skeleton,
        'version': version,
        'animated': animated,
    }


def _try_parse_skeleton(raw):
    try:
        return _parse_skeleton(raw)
    except Exception:
        return None


def _parse_skeleton(raw):
    p = 0
    p += 4  # skip first u32
    p += 64
    num_bones = _read_u32(raw, p); p += 4
    p += 4 * 3  # skip 3 u32s
    p += 1

    if num_bones > 1000 or p + num_bones * (64 + 64 + 4) > len(raw):
        return None

    bones = []
    for i in range(num_bones):
        name_bytes = raw[p:p + 64]
        nul = name_bytes.find(0)
        name = name_bytes[:nul if nul >= 0 else 64].decode('ascii', 'replace')
        p += 64

        mat = [_read_f32(raw, p + j * 4) for j in range(16)]
        p += 64

        parent_1based = _read_u32(raw, p); p += 4
        parent_idx = int(parent_1based) - 1 if parent_1based > 0 else -1

        bones.append({
            'name': name,
            'parent_index': parent_idx,
            'inv_bind_matrix': mat,
        })

    return bones
