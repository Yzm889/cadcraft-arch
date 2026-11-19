"""直接解析 DXF 文本，列出块定义内部的 LINE/LWPOLYLINE 几何。

用于核对墙块内两条侧线是否真的在交界处被裁短。
"""
from pathlib import Path

ROOT = Path(r"C:\Users\19891\Desktop\CADcraf\cadcraft-arch\samples")


def records(path: Path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for i in range(0, len(lines) - 1, 2):
        code = lines[i].strip()
        val = lines[i + 1].strip()
        try:
            yield int(code), val
        except ValueError:
            continue


def read_blocks(path: Path):
    blocks = {}
    section = None
    cur = None      # 当前块：{"name":..., "ents":[...]}
    ent = None
    last = None     # 上一个组码，用来判断 10/20 是否连续
    for code, val in records(path):
        if code == 0:
            if val == "SECTION":
                section = None
                cur = ent = None
                last = code
                continue
            if val == "ENDSEC":
                section = None
                cur = ent = None
                last = code
                continue
            if section == "BLOCKS":
                if val == "BLOCK":
                    cur = {"name": None, "ents": []}
                    ent = None
                elif val == "ENDBLK":
                    if cur and cur["name"]:
                        blocks[cur["name"]] = cur["ents"]
                    cur = ent = None
                elif cur is not None:
                    ent = {"type": val, "sx": None, "sy": None, "ex": None, "ey": None,
                           "pts": []}
                    cur["ents"].append(ent)
            last = code
            continue
        if code == 2:
            if section is None:
                section = val
            elif cur is not None and cur["name"] is None:
                cur["name"] = val
            last = code
            continue
        if section != "BLOCKS" or cur is None:
            last = code
            continue
        if ent is not None:
            if code == 10:
                if ent["type"] == "LWPOLYLINE":
                    ent["pts"].append([float(val), None])
                else:
                    ent["sx"] = float(val)
            elif code == 20:
                if ent["type"] == "LWPOLYLINE" and ent["pts"] and ent["pts"][-1][1] is None:
                    ent["pts"][-1][1] = float(val)
                elif ent["sx"] is not None and ent["sy"] is None:
                    ent["sy"] = float(val)
            elif code == 11:
                ent["ex"] = float(val)
            elif code == 21:
                ent["ey"] = float(val)
        last = code
    return blocks


def show(name, blocks):
    print("=" * 66)
    print(name)
    for bname in sorted(blocks):
        if not bname.startswith("AA_"):
            continue
        print(" 块", bname)
        for e in blocks[bname]:
            if e["type"] == "LINE":
                print("     LINE %s,%s -> %s,%s" % (e["sx"], e["sy"], e["ex"], e["ey"]))
            elif e["type"] == "LWPOLYLINE":
                print("     LWPOLYLINE", e["pts"])


for f in ("test_merge.dxf", "test_split.dxf"):
    show(f, read_blocks(ROOT / f))
