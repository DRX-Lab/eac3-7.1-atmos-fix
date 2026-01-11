![eac3-7.1-atmos-fix Banner](https://github.com/DRX-Lab/eac3-7.1-atmos-fix/blob/main/ico/eac3-7.1-atmos-fix%20banner.png)
# 

Bitstream-level patcher for **E-AC-3 JOC (Dolby Atmos) 7.1** streams.  
Fixes the **channel map (chanmap)** in dependent E-AC-3 frames and rewrites **CRC** to keep the stream valid.  
**Dialnorm is never modified.** AC-3 frames (if present) are copied as-is.

## What it does
- Detects the chanmap bit position by sampling **dependent** E-AC-3 frames (`strmtype=1`)
- Forces a fixed chanmap value (`0x1A00`) on dependent frames only
- Forces `compr` to `0xFF` on all E-AC-3 frames
- Recalculates CRC after patching

## Scope / Limitations
- **Only intended for E-AC-3 JOC (Atmos) 7.1** bitstreams
- No re-encoding; this is a low-level frame patcher
- Always validate the output in your workflow before production use

## Example

```bash
python main.py -i "test.eac3" -o "test.fixed.eac3"
``` 
