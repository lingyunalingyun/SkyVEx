# [Upstream] sky_mesh_to_obj — .mesh parser v2 (v31/v32)
# Based on: kfhammond/SkyModelViewer + tudou178/fmt_mesh.py
# License: MIT (see NOTICE)
"""
Sky mesh → OBJ 转换器
支持 ZipPos (10-bit量化顶点) + ZipUvs (16-bit量化UV) + StripNorm
"""
import struct
import os
import sys

try:
    import lz4.block
except ImportError:
    lz4 = None


def decompress_lz4(src, uncomp_size):
    if lz4:
        return lz4.block.decompress(src, uncompressed_size=uncomp_size)
    # fallback: pure python LZ4
    i = 0
    out = bytearray()
    src_len = len(src)
    def read_len(base):
        nonlocal i
        ln = base
        if ln == 15:
            while True:
                s = src[i]; i += 1; ln += s
                if s != 255: break
        return ln
    while i < src_len:
        token = src[i]; i += 1
        lit_len = read_len(token >> 4)
        out += src[i:i+lit_len]; i += lit_len
        if i >= src_len: break
        offset = src[i] | (src[i+1] << 8); i += 2
        match_len = read_len(token & 0x0F) + 4
        start = len(out) - offset
        for _ in range(match_len):
            out.append(out[start]); start += 1
    return bytes(out)


def parse_container(file_bytes):
    """解析外层容器，返回 (payload, bones, header_version)"""
    hdr_ver = struct.unpack_from("<I", file_bytes, 0)[0]

    if hdr_ver == 0x20:  # version 32
        animated = file_bytes[0x48]
        marker_count = struct.unpack_from("<H", file_bytes, 0x4A)[0]
        payload_off = 0x4E + marker_count * 112
        is_comp = struct.unpack_from("<I", file_bytes, payload_off)[0]
        comp_size = struct.unpack_from("<I", file_bytes, payload_off + 4)[0]
        uncomp_size = struct.unpack_from("<I", file_bytes, payload_off + 8)[0]
        r = payload_off + 12
        comp = file_bytes[r:r+comp_size]
        r += comp_size
        if is_comp:
            payload = decompress_lz4(comp, uncomp_size)
        else:
            payload = comp

        bones = []
        if animated == 1:
            binf = struct.unpack_from("<20I", file_bytes, r); r += 80
            b_byte = file_bytes[r]; r += 1
            tail_i = struct.unpack_from("<I", file_bytes, r)[0]; r += 4
            bone_count = int(binf[17])
            for _ in range(bone_count):
                name_raw = file_bytes[r:r+64]; r += 64
                name = name_raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore")
                mat = struct.unpack_from("<16f", file_bytes, r); r += 64
                parent = struct.unpack_from("<I", file_bytes, r)[0]; r += 4
                bones.append((name, parent - 1, mat))

        return payload, bones, 0x20

    elif hdr_ver == 0x1F:  # version 31
        hdr = struct.unpack_from("<18IH", file_bytes, 0)  # 74 bytes
        extra = struct.unpack_from("<3I", file_bytes, 74)  # 12 bytes
        h = hdr[17:] + extra
        animated = int(h[1])
        comp_size = int(h[3])
        uncomp_size = int(h[4])
        r = 86  # 74 + 12
        comp = file_bytes[r:r+comp_size]
        r += comp_size
        payload = decompress_lz4(comp, uncomp_size)

        bones = []
        if animated == 1:
            binf = struct.unpack_from("<20I", file_bytes, r); r += 80
            b_byte = file_bytes[r]; r += 1
            tail_i = struct.unpack_from("<I", file_bytes, r)[0]; r += 4
            bone_count = int(binf[17])
            for _ in range(bone_count):
                name_raw = file_bytes[r:r+64]; r += 64
                name = name_raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore")
                mat = struct.unpack_from("<16f", file_bytes, r); r += 64
                parent = struct.unpack_from("<I", file_bytes, r)[0]; r += 4
                bones.append((name, parent - 1, mat))

        return payload, bones, 0x1F

    else:
        raise ValueError(f"Unsupported header version: 0x{hdr_ver:X}")


def parse_mesh_payload(payload, bones, filename=""):
    """解析 decompressed payload，返回 (verts, uvs, faces)"""
    d = payload

    aabb_a2 = struct.unpack_from("<3f", d, 0x1C)
    aabb_b2 = struct.unpack_from("<3f", d, 0x28)
    quant_min = struct.unpack_from("<8f", d, 0x34)
    quant_max = struct.unpack_from("<8f", d, 0x54)

    vnum = struct.unpack_from("<I", d, 0x74)[0]
    inum = struct.unpack_from("<I", d, 0x78)[0]
    is_idx32 = struct.unpack_from("<I", d, 0x7C)[0]
    load_norms = d[0x94]
    skip_mesh_pos = struct.unpack_from("<I", d, 0x97)[0]
    skip_uvs = struct.unpack_from("<I", d, 0x9B)[0]
    flag3 = struct.unpack_from("<I", d, 0x9F)[0]

    animated = bool(bones)

    verts = []
    uvs = []

    # === 前向: 读取内联数据和索引 ===
    p = 0xB3

    if skip_mesh_pos == 0:
        inline_vbuf = d[p:p + vnum * 16]
        p += vnum * 16
        for i in range(vnum):
            x, y, z = struct.unpack_from("<3f", inline_vbuf, i * 16)
            verts.append((x, y, z))

    if load_norms != 0:
        p += vnum * 4

    if skip_uvs == 0:
        inline_uvbuf = d[p:p + vnum * 16]
        p += vnum * 16
        for i in range(vnum):
            u, v = struct.unpack_from("<2e", inline_uvbuf, i * 16)
            uvs.append((u, v))

    if animated:
        p += vnum * 8

    idx_unit = 4 if is_idx32 else 2
    ibuf = d[p:p + inum * idx_unit]

    # === 倒推: 从末尾定位压缩数据 ===
    end = len(d)

    if flag3 > 0:
        end -= vnum * 4

    uvs_start = end
    if skip_uvs > 0:
        uvs_start = end - vnum * 4
        end = uvs_start

    extra_start = end
    pos_start = end
    if skip_mesh_pos > 0:
        extra_start = end - vnum
        pos_start = extra_start - vnum * 4

    # === 解码压缩顶点 (ZipPos) ===
    if skip_mesh_pos > 0:
        ax, ay, az = aabb_a2
        sx = aabb_b2[0] - ax
        sy = aabb_b2[1] - ay
        sz = aabb_b2[2] - az

        for i in range(vnum):
            packed = struct.unpack_from("<I", d, pos_start + i * 4)[0]
            qz = packed & 0x3FF
            qy = (packed >> 10) & 0x3FF
            qx = (packed >> 20) & 0x3FF
            x = ax + (qx / 1023.0) * sx
            y = ay + (qy / 1023.0) * sy
            z = az + (qz / 1023.0) * sz
            verts.append((x, y, z))

    # === 解码压缩UV (ZipUvs) ===
    if skip_uvs > 0:
        umin, vmin = quant_min[0], quant_min[1]
        usz = quant_max[0] - umin
        vsz = quant_max[1] - vmin

        for i in range(vnum):
            off = uvs_start + i * 4
            u_hi = d[off]
            v_hi = d[off + 1]
            u_lo = d[off + 2]
            v_lo = d[off + 3]
            un = ((u_hi << 8) | u_lo) / 65535.0
            vn = ((v_hi << 8) | v_lo) / 65535.0
            u = umin + un * usz
            v = vmin + vn * vsz
            uvs.append((u, v))

    # === 解析索引 ===
    face_count = inum // 3
    faces = []
    if is_idx32:
        for t in range(face_count):
            a, b, c = struct.unpack_from("<3I", ibuf, t * 12)
            faces.append((a, c, b))
    else:
        for t in range(face_count):
            a, b, c = struct.unpack_from("<3H", ibuf, t * 6)
            faces.append((a, c, b))

    return verts, uvs, faces


def write_obj(filepath, verts, uvs, faces):
    with open(filepath, 'w') as f:
        f.write(f"# Sky mesh - {len(verts)} verts, {len(faces)} faces\n")
        for v in verts:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        if uvs:
            for uv in uvs:
                f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
        for face in faces:
            a, b, c = face[0] + 1, face[1] + 1, face[2] + 1
            if uvs:
                f.write(f"f {a}/{a} {b}/{b} {c}/{c}\n")
            else:
                f.write(f"f {a} {b} {c}\n")


def convert_mesh(mesh_path, output_path=None):
    """转换单个 .mesh 文件到 .obj"""
    with open(mesh_path, 'rb') as f:
        data = f.read()

    try:
        payload, bones, hdr_ver = parse_container(data)
    except Exception as e:
        return False, f"container parse: {e}"

    try:
        verts, uvs, faces = parse_mesh_payload(payload, bones, os.path.basename(mesh_path))
    except Exception as e:
        return False, f"mesh parse: {e}"

    if not verts or not faces:
        return False, "no geometry"

    if output_path is None:
        output_path = os.path.splitext(mesh_path)[0] + ".obj"

    write_obj(output_path, verts, uvs, faces)
    return True, f"{len(verts)} verts, {len(faces)} faces"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sky_mesh_to_obj.py <mesh_file> [output.obj]")
        sys.exit(1)

    mesh_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None

    ok, msg = convert_mesh(mesh_path, out_path)
    if ok:
        print(f"OK: {msg}")
    else:
        print(f"FAIL: {msg}")
        sys.exit(1)
