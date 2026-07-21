#!/usr/bin/env python3
# [Original] bintojson — TGCL .bin → .json parser
# Copyright (c) 2026 lingyunalingyun
# License: MIT (see LICENSE)
# Format research: Miau (https://github.com/Miau0x1/Sky-.bin-reader)

import sys
import os
import struct
import json

def _read_cstring(f):
    buf = bytearray()
    while True:
        ch = f.read(1)
        if not ch or ch == b'\x00':
            break
        buf.extend(ch)
    return buf.decode('utf-8', errors='replace')


def parse_bin(path):
    with open(path, 'rb') as f:
        magic, version, class_count, prop_count, node_count, obj_ptr_count, \
            class_off, prop_off, name_off, node_off, file_size = \
            struct.unpack('<4sIIIIIIIIII', f.read(44))

        if magic != b'TGCL':
            raise ValueError(f"not a TGCL file: {magic}")

        f.seek(class_off)
        classes = []
        for _ in range(class_count):
            name_offset, prop_start, prop_cnt = struct.unpack('<III', f.read(12))
            classes.append((name_offset, prop_start, prop_cnt))

        f.seek(prop_off)
        props = []
        for _ in range(prop_count):
            ptype, pname_off, psize, arr_idx = struct.unpack('<IIII', f.read(16))
            props.append((ptype, pname_off, psize, arr_idx))

        def read_name(offset):
            f.seek(name_off + offset)
            return _read_cstring(f)

        class_defs = []
        for name_offset, prop_start, prop_cnt in classes:
            cname = read_name(name_offset)
            cprops = []
            for i in range(prop_start, prop_start + prop_cnt):
                if i < len(props):
                    ptype, pname_off, psize, arr_idx = props[i]
                    pname = read_name(pname_off)
                    cprops.append((pname, ptype, psize, arr_idx))
            class_defs.append((cname, cprops))

        def read_value(ptype, psize, arr_idx):
            if ptype == 0:
                return read_raw_value(psize)
            elif ptype == 1:
                return _read_cstring(f)
            elif ptype == 2:
                return struct.unpack('<I', f.read(4))[0]
            elif ptype == 3:
                count = min(struct.unpack('<I', f.read(4))[0], 100000)
                if arr_idx != 0xFFFFFFFF and arr_idx < len(class_defs):
                    return [read_class_data(arr_idx) for _ in range(count)]
                else:
                    return [struct.unpack('<I', f.read(4))[0] for _ in range(count)]
            else:
                return f.read(max(psize, 4)).hex()

        def read_raw_value(size):
            if size == 1:
                return struct.unpack('<B', f.read(1))[0]
            elif size == 2:
                return struct.unpack('<H', f.read(2))[0]
            elif size == 4:
                raw = f.read(4)
                return struct.unpack('<f', raw)[0]
            elif size == 8:
                return struct.unpack('<d', f.read(8))[0]
            elif size == 10:
                val = struct.unpack('<d', f.read(8))[0]
                f.read(2)
                return val
            elif size == 16:
                vals = struct.unpack('<4f', f.read(16))
                return {'_raw_floats': [str(v) for v in vals]}
            elif size == 64:
                vals = struct.unpack('<16f', f.read(64))
                return {'_raw_floats': [str(v) for v in vals]}
            else:
                return f.read(size).hex()

        def read_class_data(class_idx):
            if class_idx >= len(class_defs):
                return {}
            cname, cprops = class_defs[class_idx]
            data = {}
            for pname, ptype, psize, arr_idx in cprops:
                try:
                    data[pname] = read_value(ptype, psize, arr_idx)
                except Exception:
                    break
            return {cname: data}

        f.seek(node_off)
        nodes = {}
        for _ in range(node_count):
            class_idx = struct.unpack('<I', f.read(4))[0]
            node_name = _read_cstring(f)
            node_data = read_class_data(class_idx)
            nodes[node_name] = node_data

    return {'version': version, 'BSTNodes': nodes}


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.bin> [file2.bin ...]")
        sys.exit(1)

    for path in sys.argv[1:]:
        if not os.path.isfile(path):
            print(f"file not found: {path}")
            continue
        try:
            result = parse_bin(path)
            out_path = path + '.json'
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=1, ensure_ascii=False,
                          default=str)
            print(f"{os.path.basename(path)} -> {os.path.basename(out_path)}")
        except Exception as e:
            print(f"error parsing {path}: {e}")


if __name__ == '__main__':
    main()
