"""门窗编号 / 窗框厚 / 门窗表 验收测试。

验收链：画墙 -> 开门窗（编号自动生成）-> 改窗框厚 -> 门窗表 CSV -> 图上表格回读。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    Session, block_geometry, create_opening, create_wall,
    openings_report, opening_no, set_opening,
)

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def flat_y(path: Path, block: str) -> list[float]:
    lines = [g for g in block_geometry(path, block) if g["type"] == "LINE"]
    return sorted({round(g["pts"][0][1], 1) for g in lines
                   if abs(g["pts"][0][1] - g["pts"][1][1]) < 1e-6})


def main() -> int:
    path = OUT / "test_openings.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()

    # 编号规则：类型 + 洞口宽高（分米两位）
    assert opening_no("DOOR", 900.0, 2100.0) == "M0921"
    assert opening_no("WINDOW", 1500.0, 1500.0) == "C1515"
    assert opening_no("DOORWIN", 1200.0, 2400.0) == "MC1224"
    print("编号规则 ok")

    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W002", (0.0, -2000.0), (6000.0, -2000.0), thick=370.0)

    d = create_opening(s, "D001", "W001", "DOOR", width=900.0, pos=1500.0)
    assert d["no"] == "M0921", d
    c1 = create_opening(s, "C001", "W001", "WINDOW", width=1500.0, pos=4000.0)
    c2 = create_opening(s, "C002", "W002", "WINDOW", width=1500.0, pos=4000.0)
    assert c1["no"] == c2["no"] == "C1515", (c1, c2)
    print("编号落盘 ok:", d["no"], c1["no"], c2["no"])

    # 1) 编号文字真的画在图上（块内 TEXT）
    texts = [g["text"] for g in block_geometry(path, "AA_OPENING_D001")
             if g["type"] == "TEXT"]
    assert texts == ["M0921"], texts

    # 2) 窗框厚默认 60：240 墙 ±60、370 墙 ±125
    assert flat_y(path, "AA_OPENING_C001") == [-120.0, -60.0, 60.0, 120.0]
    assert flat_y(path, "AA_OPENING_C002") == [-185.0, -125.0, 125.0, 185.0]

    # 3) 改窗框厚后重绘：240 墙 frame=40 => ±80；编号保持不变
    res = set_opening(s, "C001", frame=40.0)
    assert abs(res["frame"] - 40.0) < 1e-9, res
    assert flat_y(path, "AA_OPENING_C001") == [-120.0, -80.0, 80.0, 120.0]
    assert s.attributes("AA_OPENING_C001")["AA_NO"] == "C1515"

    # 4) 改编号：文字与属性同步
    set_opening(s, "D001", no="M-1")
    attrs = s.attributes("AA_OPENING_D001")
    assert attrs["AA_NO"] == "M-1", attrs
    assert [g["text"] for g in block_geometry(path, "AA_OPENING_D001")
            if g["type"] == "TEXT"] == ["M-1"]

    # 5) 门窗表：同编号合并计数（C1515 两樘，跨两道墙）
    csv = OUT / "test_openings.csv"
    rep = openings_report(s, csv)
    rows = {r["编号"]: r for r in rep["rows"]}
    print("门窗表:", rep["rows"])
    assert rep["marks"] == 2 and rep["openings"] == 3, rep       # M-1 改名后并入同编号
    assert rows["C1515"]["樘数"] == 2, rows
    assert rows["C1515"]["所在墙"] == "W001;W002", rows["C1515"]
    assert rows["C1515"]["宽(mm)"] == "1500" and rows["C1515"]["高(mm)"] == "1500"
    assert rows["M-1"]["类型"] == "门" and rows["M-1"]["樘数"] == 1
    text = csv.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0] == "编号,类型,宽(mm),高(mm),樘数,所在墙", text
    assert text.splitlines()[-1].startswith("合计,2 种"), text
    assert "\ufeff\ufeff" not in text, "BOM 只能写一份"

    # 6) 图上门窗表：改为几何绘制后，回读 AA-TABLE 层里的文字与线框
    rep2 = openings_report(s, table_at=(0.0, -3200.0))
    tab = rep2.get("table", {})
    assert tab.get("by") == "geometry" and tab.get("cols") == 6, rep2
    marks = [e for e in s.entities().get("entities", [])
             if e.get("layer") == "AA-TABLE"]
    texts = [e for e in marks if str(e.get("type", "")).lower() in ("text", "mtext")]
    assert len(texts) >= tab["rows"] + tab["cols"] - 1, len(texts)
    flat = " ".join(str(t["geometry"].get("text", t["geometry"].get("value", "")))
                    for t in texts)
    assert "门窗表" in flat and "樘数" in flat, flat
    assert "C1515" in flat and "M-1" in flat, flat
    print("图上门窗表 ok: %d 行 %d 列" % (tab["rows"], tab["cols"]))

    print("PASS test_openings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
