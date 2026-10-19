"""Recover the map from a platform replay (match zip or replay.repl26a).

    python scripts/extract_map.py <match.zip | replay.repl26a> <out.map26a>

The map file is embedded verbatim at byte 14 of replay.repl26a. It ends 4 bytes
before the first "?? ?? 00 00 04 01" that follows; this rule recovers all 10 local
maps byte-for-byte. If several candidates exist, validate with:
    cambc run inspect inspect --map <out.map26a> --rounds 1   (engine error 7 = bad cut)
"""
import sys
import zipfile

src, out = sys.argv[1], sys.argv[2]
data = zipfile.ZipFile(src).read("replay.repl26a") if src.endswith(".zip") else open(src, "rb").read()
assert data[14:20] == b"w62pam", "no embedded map at byte 14"
cands = [e for e in range(214, len(data) - 8) if data[e + 2:e + 4] == b"\x00\x00" and data[e + 4:e + 6] == b"\x04\x01"]
if not cands:
    sys.exit("no end marker found")
open(out, "wb").write(data[14:cands[0]])
print("wrote %s (%d bytes, %d candidate cuts)" % (out, cands[0] - 14, len(cands)))
