#!/usr/bin/env python3
# SkyVEx — pluggable backend registry
# Copyright (c) 2026 lingyunalingyun
# License: MIT (see LICENSE)

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

_meshes_backends = {}
_mesh_backends = {}


class MeshesBackend:
    """Base class for .meshes (terrain/level geometry) backends."""
    name = ""
    description = ""
    dependencies = []
    source_files = []
    info = ""

    def is_available(self):
        raise NotImplementedError

    def get_capabilities(self):
        return set()

    def parse_to_obj_data(self, meshes_file):
        """Parse .meshes → (verts, faces). verts=[(x,y,z),...], faces=[(i,j,k),...]"""
        raise NotImplementedError

    def parse_to_json(self, meshes_file):
        """Parse .meshes → dict (JSON-serializable)."""
        raise NotImplementedError

    def convert_to_obj_file(self, meshes_file, output_path, full=False):
        """Convert .meshes → .obj file on disk."""
        raise NotImplementedError

    def get_info(self, meshes_file):
        """Return info string about a .meshes file."""
        raise NotImplementedError


class MeshBackend:
    """Base class for .mesh (individual model) backends."""
    name = ""
    description = ""
    dependencies = []
    source_files = []
    info = ""

    def is_available(self):
        raise NotImplementedError

    def parse_mesh_file(self, mesh_path):
        """Parse .mesh → (verts, uvs, faces)."""
        raise NotImplementedError


# ── Registry ──────────────────────────────────────────────

def register_meshes_backend(backend):
    _meshes_backends[backend.name] = backend

def register_mesh_backend(backend):
    _mesh_backends[backend.name] = backend

def get_meshes_backends():
    return dict(_meshes_backends)

def get_mesh_backends():
    return dict(_mesh_backends)

def get_available_meshes_backends():
    return {k: v for k, v in _meshes_backends.items() if v.is_available()}

def get_available_mesh_backends():
    return {k: v for k, v in _mesh_backends.items() if v.is_available()}


# ── Built-in backend: BstBake (Sky_Bstbake.py + lz4) ─────

class BstBakeMeshesBackend(MeshesBackend):
    name = "bstbake"
    description = "Sky_Bstbake.py + lz4 (原生依赖)"
    dependencies = ["lz4", "Sky_Bstbake.py"]
    source_files = ["Sky_Bstbake.py"]
    info = (
        "解析 .meshes 文件中的 LOD0 段 (BstBaked 地形数据)。\n\n"
        "原理: .meshes 文件包含多个数据段，LOD0 段存储的是\n"
        "LZ4 压缩的烘焙地形网格，包括地形面片(terrain)、\n"
        "裙边(skirts)和遮挡体(occluder)三类几何体。\n"
        "解压后由 Sky_Bstbake.py 拆分各 patch 的顶点和索引。\n\n"
        "依赖: 需要 pip install lz4 (原生 C 扩展)。\n\n"
        "与 meshes2obj_json 互补: 两者解析的是同一文件的\n"
        "不同数据段 (LOD0 vs GEO0)，输出的顶点数和面数不同。"
    )

    def __init__(self):
        self._parse_and_split = None
        self._has_lz4 = False
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            import lz4.block
            self._has_lz4 = True
        except ImportError:
            return
        try:
            if SCRIPT_DIR not in sys.path:
                sys.path.insert(0, SCRIPT_DIR)
            from Sky_Bstbake import parse_and_split
            self._parse_and_split = parse_and_split
        except ImportError:
            pass

    def is_available(self):
        self._load()
        return self._has_lz4 and self._parse_and_split is not None

    def get_capabilities(self):
        return {"meshes_to_obj_data"}

    def parse_to_obj_data(self, meshes_file):
        self._load()
        if not self.is_available():
            return [], []
        import struct
        import lz4.block

        try:
            with open(meshes_file, 'rb') as f:
                data = f.read()
        except Exception:
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
            result, _ = self._parse_and_split(decompressed, file_version, metr_data, geo_data)
        except Exception:
            return [], []

        all_verts = []
        all_faces = []

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
                        all_verts.append((-pos[0], pos[1], -pos[2]))
                    for i in range(0, len(indices), 3):
                        if i + 2 < len(indices):
                            all_faces.append((indices[i] + base_v, indices[i+2] + base_v, indices[i+1] + base_v))

        return all_verts, all_faces


# ── Built-in backend: meshes2obj_json (pure Python) ───────

class PurePythonMeshesBackend(MeshesBackend):
    name = "meshes2obj_json"
    description = "meshes2obj_json.py (纯 Python, 零依赖)"
    dependencies = []
    source_files = ["meshes2obj_json.py"]
    info = (
        "解析 .meshes 文件中的 GEO0 段 (meshopt 编码几何数据)。\n\n"
        "原理: GEO0 段使用 meshoptimizer 库的顶点编码格式，\n"
        "本模块内置纯 Python 的 meshopt 顶点解码器，无需任何\n"
        "原生 DLL 或 pip 包。支持 7 种操作:\n"
        "  • meshes → OBJ (数据/文件)\n"
        "  • meshes → JSON\n"
        "  • meshes 信息查看\n"
        "  • OBJ → meshes (反向写入)\n"
        "  • 按材质拆分\n"
        "  • 多 OBJ 合并写入\n\n"
        "来源: that-sky-project/that-sky-level-meshes (LGPL 2.1)\n\n"
        "与 bstbake 互补: 解析 GEO0 段而非 LOD0 段，\n"
        "两者输出的顶点数和面数不同。"
    )

    def __init__(self):
        self._mod = None
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            if SCRIPT_DIR not in sys.path:
                sys.path.insert(0, SCRIPT_DIR)
            import importlib.util
            mod_path = os.path.join(SCRIPT_DIR, "meshes2obj_json.py")
            if os.path.exists(mod_path):
                spec = importlib.util.spec_from_file_location("meshes2obj_json", mod_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self._mod = mod
        except Exception:
            pass

    def is_available(self):
        self._load()
        return self._mod is not None

    def get_capabilities(self):
        caps = {"meshes_to_obj_data", "meshes_to_obj_file", "meshes_to_json", "meshes_info"}
        if self._mod and hasattr(self._mod, 'obj_to_meshes'):
            caps.add("obj_to_meshes")
        if self._mod and hasattr(self._mod, 'touch_object_multi'):
            caps.add("meshes_material_split")
        if self._mod and hasattr(self._mod, 'multi_obj_to_meshes'):
            caps.add("multi_obj_to_meshes")
        return caps

    def parse_to_obj_data(self, meshes_file):
        self._load()
        if not self._mod:
            return [], []
        try:
            with open(meshes_file, 'rb') as f:
                buf = f.read()
            meshes = self._mod.LevelMeshes.from_file_buffer(buf)
            geo = meshes.geo
            if not geo or geo.vertex_count == 0:
                return [], []

            all_verts = []
            all_faces = []
            li = geo.local_indices

            for v in geo.vertices:
                all_verts.append((-v.pos[0], v.pos[1], -v.pos[2]))

            for ci in range(geo.chunk_count):
                chunk = geo.chunks[ci]
                idx_start = chunk.idx_start
                vtx_start = chunk.vtx_start
                idx_count = chunk.idx_count
                j = 0
                while j < idx_count:
                    a = vtx_start + li[idx_start + j]
                    b = vtx_start + li[idx_start + j + 1]
                    c = vtx_start + li[idx_start + j + 2]
                    all_faces.append((a, b, c))
                    j += 3

            return all_verts, all_faces
        except Exception:
            return [], []

    def parse_to_json(self, meshes_file):
        self._load()
        if not self._mod:
            return None
        try:
            with open(meshes_file, 'rb') as f:
                buf = f.read()
            meshes = self._mod.LevelMeshes.from_file_buffer(buf)
            return self._mod.meshes_to_json(meshes)
        except Exception:
            return None

    def convert_to_obj_file(self, meshes_file, output_path, full=False):
        self._load()
        if not self._mod:
            return False
        try:
            with open(meshes_file, 'rb') as f:
                buf = f.read()
            meshes = self._mod.LevelMeshes.from_file_buffer(buf)
            if full:
                obj_text = self._mod.meshes_to_obj_full(meshes)
            else:
                obj_text = self._mod.touch_object(meshes)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(obj_text)
            return True
        except Exception:
            return False

    def get_info(self, meshes_file):
        self._load()
        if not self._mod:
            return None
        try:
            with open(meshes_file, 'rb') as f:
                buf = f.read()
            meshes = self._mod.LevelMeshes.from_file_buffer(buf)
            import io
            old = sys.stdout
            sys.stdout = cap = io.StringIO()
            try:
                self._mod.print_info(meshes)
            finally:
                sys.stdout = old
            return cap.getvalue()
        except Exception:
            return None


# ── Built-in backend: meshtoobj.py (.mesh files) ─────────

class MeshtoobjBackend(MeshBackend):
    name = "meshtoobj"
    description = "meshtoobj.py + meshopt2.dll (原生依赖)"
    dependencies = ["meshtoobj.py", "meshopt2.dll"]
    source_files = ["meshtoobj.py", "meshopt2.dll"]
    info = (
        "解析 .mesh 模型文件 (v0x17–0x20 全版本)。\n\n"
        "原理: 按版本号分发到 6 个独立处理函数，每个函数\n"
        "读取该版本特定的头部偏移和数据布局。压缩版本\n"
        "(v0x1E+) 使用 meshopt2.dll 进行顶点解码。\n\n"
        "依赖: 需要 meshopt2.dll (meshoptimizer 原生库)。\n\n"
        "来源: 上游 sky_mesh_to_obj 工具链。"
    )

    def __init__(self):
        self._handlers = {}
        self._version_map = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            if SCRIPT_DIR not in sys.path:
                sys.path.insert(0, SCRIPT_DIR)
            from meshtoobj import (
                process_header_17, process_header_1A, process_header_1C,
                process_header_1E, process_header_1F, process_header_20,
                HEADER_VERSION_MAP,
            )
            self._version_map = HEADER_VERSION_MAP
            self._handlers = {
                b'\x17\x00\x00\x00': process_header_17,
                b'\x1a\x00\x00\x00': process_header_1A,
                b'\x1c\x00\x00\x00': process_header_1C,
                b'\x1e\x00\x00\x00': process_header_1E,
                b'\x1f\x00\x00\x00': process_header_1F,
                b'\x20\x00\x00\x00': process_header_20,
            }
        except ImportError:
            pass

    def is_available(self):
        self._load()
        return bool(self._handlers)

    def parse_mesh_file(self, mesh_path):
        self._load()
        if not self._handlers:
            return [], [], []
        try:
            with open(mesh_path, 'rb') as f:
                data = f.read()
        except Exception:
            return [], [], []

        if len(data) < 4:
            return [], [], []

        header = data[:4]
        version = self._version_map.get(header)
        if version is None:
            return [], [], []

        handler = self._handlers.get(header)
        if handler is None:
            return [], [], []

        try:
            filename = os.path.basename(mesh_path)
            if header == b'\x17\x00\x00\x00':
                result = handler(data, mesh_path, filename, version, False, True)
            else:
                result = handler(data, mesh_path, filename, version, True)

            if result and len(result) >= 3:
                verts = [(v[0], v[1], v[2]) for v in result[0]]
                uvs = [(uv[0], uv[1]) for uv in result[1]] if result[1] else []
                faces = [(f[0], f[1], f[2]) for f in result[2]]
                return verts, uvs, faces
        except Exception:
            pass

        return [], [], []


# ── Built-in backend: mesh_parser.py (.mesh, pure Python) ─

class PurePythonMeshBackend(MeshBackend):
    name = "mesh_parser"
    description = "mesh_parser.py (纯 Python, 零原生依赖)"
    dependencies = []
    source_files = ["mesh_parser.py"]
    info = (
        "纯 Python 解析 .mesh 模型文件 (v0x17–0x20 全版本)。\n\n"
        "原理: 统一为两条代码路径处理所有版本:\n"
        "  • 未压缩 (v0x17–0x1C): 固定偏移读取顶点/UV/索引\n"
        "  • LZ4 压缩 (v0x1E–0x20): 内置纯 Python LZ4 解压，\n"
        "    支持 10-10-10 bit 量化位置、16-bit 量化 UV、\n"
        "    骨骼权重和嵌入式骨架解析\n\n"
        "零依赖: 不需要任何原生 DLL 或 pip 包，\n"
        "LZ4 解压有纯 Python 回退实现。\n\n"
        "经 30 个随机文件验证，输出与 meshtoobj + meshopt2.dll\n"
        "完全一致。"
    )

    def __init__(self):
        self._mod = None
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            if SCRIPT_DIR not in sys.path:
                sys.path.insert(0, SCRIPT_DIR)
            import importlib.util
            mod_path = os.path.join(SCRIPT_DIR, "mesh_parser.py")
            if os.path.exists(mod_path):
                spec = importlib.util.spec_from_file_location("mesh_parser", mod_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self._mod = mod
        except Exception:
            pass

    def is_available(self):
        self._load()
        return self._mod is not None

    def parse_mesh_file(self, mesh_path):
        self._load()
        if not self._mod:
            return [], [], []
        try:
            result = self._mod.parse_mesh(mesh_path)
            verts = result['vertices']
            uvs = result['uvs']
            faces = result['faces']
            return verts, uvs, faces
        except Exception:
            return [], [], []


# ── Auto-discovery ────────────────────────────────────────

def discover_and_register():
    """Discover and register all built-in backends."""
    register_meshes_backend(BstBakeMeshesBackend())
    register_meshes_backend(PurePythonMeshesBackend())
    register_mesh_backend(PurePythonMeshBackend())
    register_mesh_backend(MeshtoobjBackend())


discover_and_register()
