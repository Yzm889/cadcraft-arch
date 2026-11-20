"""图层配置验收测试：用户用自己的图层标准时，几何必须落在用户指定的图层上。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import aa_lib  # noqa: E402
from aa_lib import Session, create_axis_grid, create_opening, create_wall  # noqa: E402

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)

CUSTOM = {
    "axis": "AXIS",
    "axistext": "AXIS-TXT",
    "wall": "WALL",
    "opening": "OPEN",
    "room": "ROOM-TXT",
}


def block_layers(path: Path) -> dict[str, set[str]]:
    """解析 DXF，返回 {块名: {几何所在图层}}。"""
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    pairs = [(lines[i].strip(), lines[i + 1].strip()) for i in range(0, len(lines) - 1, 2)]
    out: dict[str, set[str]] = {}
    in_block = False
    block = None
    entity = None
    for code, val in pairs:
        if code == "0":
            entity = val
            if val == "BLOCK":
                in_block, block = True, None
            elif val == "ENDBLK":
                in_block = False
        elif code == "2" and entity == "BLOCK":
            block = val
        elif code == "8" and in_block and block:
            out.setdefault(block, set()).add(val)
    return out


def main() -> int:
    cfg = OUT / "_layers_custom.json"
    cfg.write_text(json.dumps(CUSTOM, ensure_ascii=False), encoding="utf-8")
    try:
        got = aa_lib.load_layer_config(cfg)
        assert got["layers"]["wall"] == "WALL" and got["layers"]["axis"] == "AXIS", got
        print("图层配置:", got)

        path = OUT / "test_layers.dxf"
        if path.exists():
            path.unlink()
        s = Session(path)
        s.new_metric()
        create_axis_grid(s, "AX001", 2, 3600.0, 1, 4000.0, 0.0, 0.0, 800.0)
        create_wall(s, "W001", (0.0, 0.0), (3600.0, 0.0), thick=240.0, kind="EXTERNAL")
        create_opening(s, "D001", "W001", "DOOR", width=900.0, pos=1200.0)

        names = {l["name"] for l in s.info()["layers"]}
        for lay in ("AXIS", "AXIS-TXT", "WALL", "OPEN"):
            assert lay in names, (lay, sorted(names))
        assert "AA-WALL" not in names, sorted(names)

        layers = block_layers(path)
        print("块图层:", {k: sorted(v) for k, v in layers.items()})
        # 墙块几何不得留 AA- 前缀层（中心线已删，只剩两条墙面线）
        assert "WALL" in layers["AA_WALL_W001"], layers["AA_WALL_W001"]
        assert "AA-WALL" not in layers["AA_WALL_W001"], layers["AA_WALL_W001"]
        assert "AXIS" in layers["AA_AXGRID_AX001"], layers["AA_AXGRID_AX001"]
        assert "OPEN" in layers["AA_OPENING_D001"], layers["AA_OPENING_D001"]
    finally:
        cfg.unlink(missing_ok=True)
        # 恢复默认层名，避免影响后续用例
        aa_lib.load_layer_config(Path("__none__.json"))

    print("PASS test_layers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
