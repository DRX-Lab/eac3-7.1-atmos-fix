#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sys
from typing import Optional, BinaryIO, Tuple, Dict, List

# Fixed default chanmap (no CLI option)
DEFAULT_CHANMAP = 0x1A00

fsizetable = [
    64,64,80,80,96,96,112,112,128,128,160,160,192,192,224,224,256,256,320,320,384,384,448,448,512,512,640,640,768,768,896,896,
    1024,1024,1152,1152,1280,1280,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    69,70,87,88,104,105,121,122,139,140,174,175,208,209,243,244,278,279,348,349,417,418,487,488,557,558,696,697,835,836,975,976,
    1114,1115,1253,1254,1393,1394,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    96,96,120,120,144,144,168,168,192,192,240,240,288,288,336,336,384,384,480,480,576,576,672,672,768,768,960,960,1152,1152,1344,1344,
    1536,1536,1728,1728,1920,1920,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
]

# CRC
CRC16_POLY = 0x8005
_crc_table = [0] * 256

def crc_init() -> None:
    for n in range(256):
        c = (n << 8) & 0xFFFF
        for _ in range(8):
            if c & 0x8000:
                c = ((c << 1) & 0xFFFF) ^ CRC16_POLY
            else:
                c = (c << 1) & 0xFFFF
        _crc_table[n] = c

def crc16(data: bytes, crc: int = 0) -> int:
    crc &= 0xFFFF
    for b in data:
        crc = (_crc_table[((b ^ (crc >> 8)) & 0xFF)] ^ ((crc << 8) & 0xFFFF)) & 0xFFFF
    return crc

def eac3_rewrite_crc2_like_c(frame: bytearray, frlen: int) -> None:
    if frlen < 6:
        return
    c = crc16(bytes(frame[2:frlen - 2]), 0)
    frame[frlen - 2] = (c >> 8) & 0xFF
    frame[frlen - 1] = c & 0xFF

# Bits
def getbit(buf: bytes, bitoffset: int) -> int:
    idx = bitoffset // 8
    if idx >= len(buf):
        return 0
    mask = 0x80 >> (bitoffset % 8)
    return 1 if (buf[idx] & mask) else 0

def setbit(buf: bytearray, bit: int, bitoffset: int) -> None:
    idx = bitoffset // 8
    if idx >= len(buf):
        return
    mask = 0x80 >> (bitoffset % 8)
    if bit:
        buf[idx] |= mask
    else:
        buf[idx] &= (~mask) & 0xFF

def getbits(buf: bytes, bitoffset: int, nbits: int) -> int:
    v = 0
    for i in range(nbits):
        v = (v << 1) | getbit(buf, bitoffset + i)
    return v

def setbits(buf: bytearray, bitoffset: int, nbits: int, value: int) -> None:
    for i in range(nbits):
        bit = 1 if (value & (1 << (nbits - 1 - i))) else 0
        setbit(buf, bit, bitoffset + i)

# IO
class PatchError(Exception):
    pass

def read_exact(f: BinaryIO, n: int) -> bytes:
    b = f.read(n)
    return b if b is not None else b""

def read_frame(fin: BinaryIO) -> Tuple[Optional[bytearray], int, bool, str]:
    head = read_exact(fin, 6)
    if len(head) == 0:
        return None, 0, True, ""
    if len(head) < 6:
        raise PatchError("Unexpected EOF (short header)")

    fr = bytearray(head)
    if fr[0] != 0x0B or fr[1] != 0x77:
        raise PatchError("Bad syncword (expected 0x0B 0x77)")

    bsid = fr[5] >> 3
    if bsid < 10:
        frmsizecod = fr[4]
        frame_len = fsizetable[frmsizecod] * 2
        if frame_len == 0:
            raise PatchError("Invalid AC-3 frmsizecod")
        kind = "ac3"
    else:
        frame_len = (256 * (fr[2] & 7) + fr[3]) * 2 + 2
        if frame_len < 10:
            raise PatchError("Invalid E-AC-3 frmsiz")
        kind = "eac3"

    tail = read_exact(fin, frame_len - 6)
    if len(tail) != frame_len - 6:
        raise PatchError("Unexpected EOF (truncated frame)")
    fr.extend(tail)
    return fr, frame_len, False, kind

# EAC3 header positions
def eac3_parse_positions(fr: bytes) -> Dict[str, int]:
    off = 16
    strmtype = getbits(fr, off, 2); off += 2
    off += 3
    off += 11
    off += 2
    off += 2
    off += 3
    off += 1
    off += 5
    dialnorm_pos = off
    off += 5  # dialnorm bits exist but we will NEVER touch them
    compre_pos = off
    compre = getbits(fr, off, 1); off += 1
    compr_pos = off  # starts here if compre==1
    if compre == 1:
        off += 8
    return {
        "strmtype": strmtype,
        "dialnorm_pos": dialnorm_pos,  # kept for completeness; unused
        "compre_pos": compre_pos,
        "compr_pos": compr_pos,
        "scan_start": off,
    }

def find_chanmap_bitpos(samples: List[bytes], extra_bits: int = 2048) -> Optional[int]:
    pos_hist: Dict[int, Dict[int, int]] = {}
    for fr in samples:
        if (fr[5] >> 3) < 10:
            continue
        info = eac3_parse_positions(fr)
        if info["strmtype"] != 1:
            continue
        start = info["scan_start"]
        end = min(len(fr) * 8 - 17, start + extra_bits)
        for p in range(start, end):
            if getbit(fr, p) != 1:
                continue
            v = getbits(fr, p + 1, 16)
            if v in (0x0000, 0xFFFF):
                continue
            d = pos_hist.setdefault(p + 1, {})
            d[v] = d.get(v, 0) + 1

    if not pos_hist:
        return None

    best_pos = None
    best_score = -1.0
    for pos, hist in pos_hist.items():
        total = sum(hist.values())
        top = max(hist.values())
        stability = top / total if total else 0.0
        score = total * (stability ** 2)
        if score > best_score:
            best_score = score
            best_pos = pos

    return best_pos

# Progress
def print_progress(current: int, total: int, width: int = 42) -> None:
    if total <= 0:
        return
    frac = current / total
    frac = 0.0 if frac < 0 else (1.0 if frac > 1 else frac)
    filled = int(round(frac * width))
    bar = "■" * filled + " " * (width - filled)
    sys.stdout.write(f"\r[{bar}] {frac*100:6.2f}%")
    sys.stdout.flush()

def patch_file(in_path: str, out_path: str) -> None:
    # Detect chanmap position from dependent E-AC-3 (strmtype=1) frames
    samples: List[bytes] = []
    with open(in_path, "rb") as fin:
        while len(samples) < 8:
            fr, _, eof, kind = read_frame(fin)
            if eof:
                break
            assert fr is not None
            if kind == "eac3":
                info = eac3_parse_positions(fr)
                if info["strmtype"] == 1:
                    samples.append(bytes(fr))

    chanmap_pos = find_chanmap_bitpos(samples)
    if chanmap_pos is None:
        raise PatchError("Could not detect the chanmap location in dependent E-AC-3 frames.")

    in_size = os.path.getsize(in_path)

    total_frames = 0
    ac3_count = 0
    eac3_count = 0
    patched_eac3 = 0

    first_printed = False

    with open(in_path, "rb") as fin, open(out_path, "wb") as fout:
        while True:
            fr, frlen, eof, kind = read_frame(fin)
            if eof:
                break
            assert fr is not None

            if not first_printed:
                print(f"Parsing first frame: SIZE {frlen} bytes")
                first_printed = True

            total_frames += 1

            if kind == "ac3":
                ac3_count += 1
                fout.write(fr)
            else:
                eac3_count += 1
                info = eac3_parse_positions(fr)

                changed = False

                #compr ALWAYS FF for all E-AC-3 (strmtype 0 and 1)
                setbits(fr, info["compre_pos"], 1, 1)
                setbits(fr, info["compr_pos"], 8, 0xFF)
                changed = True

                #chanmap ONLY if strmtype=1 (dependent)
                if info["strmtype"] == 1:
                    setbits(fr, chanmap_pos, 16, DEFAULT_CHANMAP)
                    changed = True

                if changed:
                    eac3_rewrite_crc2_like_c(fr, frlen)
                    patched_eac3 += 1

                fout.write(fr)

            print_progress(fin.tell(), in_size)

    print_progress(in_size, in_size)
    print()

    print(f"Detected chanmap bit position: {chanmap_pos}")
    print(f"Frames: total={total_frames} ac3={ac3_count} eac3={eac3_count} patched_eac3={patched_eac3}")

def main() -> int:
    crc_init()

    ap = argparse.ArgumentParser(description="E-AC-3 7.1 Atmos channel map fix")
    ap.add_argument("-i", "--input", required=True, help="Input .eac3")
    ap.add_argument("-o", "--output", required=True, help="Output .eac3")
    args = ap.parse_args()

    if args.input == args.output:
        print("ERROR: input and output cannot be the same")
        return 1

    try:
        patch_file(args.input, args.output)
        return 0
    except Exception as e:
        print("ERROR:", str(e))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
