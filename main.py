import argparse
import sys
import os
from colorama import Fore, Style, init

# ---------------------------------------------------------
# Colorama init
# ---------------------------------------------------------
init(autoreset=True)

def fname(path):
    return os.path.basename(path)

def info(msg):
    print(f"{Fore.CYAN}[INFO]{Style.RESET_ALL} {msg}")

def ok(msg):
    print(f"{Fore.GREEN}[OK]{Style.RESET_ALL} {msg}")

def warn(msg):
    print(f"{Fore.YELLOW}[WARN]{Style.RESET_ALL} {msg}")

def err(msg):
    print(f"{Fore.RED}[ERR]{Style.RESET_ALL} {msg}")

# ---------------------------------------------------------
# CRC16
# ---------------------------------------------------------
CRC16_POLY = 0x8005
crc_table = [0] * 256

def ac3_crc_init():
    for n in range(256):
        c = n << 8
        for _ in range(8):
            if c & 0x8000:
                c = ((c << 1) & 0xFFFF) ^ CRC16_POLY
            else:
                c = (c << 1) & 0xFFFF
        crc_table[n] = c

def ac3_crc(data, crc=0):
    for b in data:
        crc = (
            crc_table[(b ^ (crc >> 8)) & 0xFF]
            ^ ((crc << 8) & 0xFFFF)
        ) & 0xFFFF
    return crc

# ---------------------------------------------------------
# Bit helpers (SAFE)
# ---------------------------------------------------------
def getbit(data, bitoffset):
    byte = bitoffset // 8
    if byte >= len(data):
        return 0
    return 1 if (data[byte] & (0x80 >> (bitoffset % 8))) else 0

def setbit(data, bit, bitoffset):
    byte = bitoffset // 8
    if byte >= len(data):
        return
    if bit:
        data[byte] |= 0x80 >> (bitoffset % 8)
    else:
        data[byte] &= ~(0x80 >> (bitoffset % 8))

def setbyte(data, byteval, bitoffset):
    byte = bitoffset // 8
    if byte + 1 >= len(data):
        return

    offs = bitoffset % 8
    if offs == 0:
        data[byte] = byteval
        return

    data[byte] &= 0xFF << (8 - offs)
    data[byte] |= byteval >> offs
    data[byte + 1] &= 0xFF >> offs
    data[byte + 1] |= (byteval << (8 - offs)) & 0xFF

# ---------------------------------------------------------
# Progress (compact)
# ---------------------------------------------------------
def print_progress(frames):
    sys.stdout.write(
        f"\r{Fore.CYAN}[INFO]{Style.RESET_ALL} Frames: {Style.BRIGHT}{frames}{Style.RESET_ALL}"
    )
    sys.stdout.flush()

# ---------------------------------------------------------
# E-AC3 patcher
# ---------------------------------------------------------
def patch_eac3_file(filename):
    with open(filename, "rb") as f:
        data = bytearray(f.read())

    total_len = len(data)
    i = 0

    # Find first syncword
    while i + 1 < total_len and not (data[i] == 0x0B and data[i + 1] == 0x77):
        i += 1

    if i >= total_len:
        raise RuntimeError("No E-AC3 syncword found")

    if i > 0:
        warn(f"Trimmed {i} bytes")
        data = data[i:]
        total_len = len(data)
        i = 0

    patched = 0

    while i + 4 < total_len:
        if not (data[i] == 0x0B and data[i + 1] == 0x77):
            j = data.find(b"\x0B\x77", i + 1, min(i + 4096, total_len))
            if j == -1:
                break
            i = j
            continue

        frmsiz = ((data[i + 2] & 0x07) << 8) | data[i + 3]
        frame_len = 2 * frmsiz + 2
        frame_end = i + frame_len

        if frame_end > total_len:
            warn("Truncated frame")
            break

        bit_base = i * 8

        # Independent E-AC3 + fixed chanmap
        if not getbit(data, bit_base + 61):
            setbit(data, 1, bit_base + 61)

        # EXACT chanmap
        setbyte(data, 0b01101000, bit_base + 62)
        setbyte(data, 0x00, bit_base + 70)

        # CRC
        crc = ac3_crc(data[i + 2:frame_end - 2])
        data[frame_end - 2] = (crc >> 8) & 0xFF
        data[frame_end - 1] = crc & 0xFF

        patched += 1
        print_progress(patched)

        i = frame_end

    sys.stdout.write("\n")

    base, _ = os.path.splitext(filename)
    out_file = base + ".patched.eac3"

    with open(out_file, "wb") as f:
        f.write(data)

    return out_file, patched

# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
def main(input_file):
    ac3_crc_init()

    ok(f"Input  : {fname(input_file)}")

    try:
        out, frames = patch_eac3_file(input_file)
    except Exception as e:
        err(str(e))
        sys.exit(1)

    ok(f"Frames : {frames}")
    ok(f"Output : {fname(out)}")

# ---------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="E-AC3 7.1 channel layout correction"
    )
    parser.add_argument("-i", "--input", required=True, help="Input .eac3 file")
    args = parser.parse_args()
    main(args.input)
