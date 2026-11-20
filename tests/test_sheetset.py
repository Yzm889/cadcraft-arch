"""图纸集 / 图纸目录 / 批量出图验收（v1.0.33）。

覆盖：登记校验（图号重复、图幅占用、图幅不存在、空集）、目录表生成与回读、
两张图幅批量出 PNG 且产物存在，以及"图幅/比例"从图框读而不是手填。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    CadError,
    Session,
    block_geometry,
    create_opening,
    create_sheet,
    create_sheet_index,
    create_sheet_set,
    create_wall,
    export_sheet_set,
    read_sheet_index,
    read_sheet_set,
    set_drawing_scale,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_sheetset.dxf"
    path.unlink(missing_ok=True)
    s = Session(path)
    s.new_metric()
    set_drawing_scale(s, 100, rescale=False)

    # 一张平面落在 S001（A3），一张大样落在 S002（A4）
    create_wall(s, "W001", (0.0, 0.0), (6000.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W002", (6000.0, 0.0), (6000.0, 4000.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W003", (6000.0, 4000.0), (0.0, 4000.0), thick=240.0, kind="EXTERNAL")
    create_wall(s, "W004", (0.0, 4000.0), (0.0, 0.0), thick=240.0, kind="EXTERNAL")
    create_opening(s, "D001", "W001", "DOOR", width=900.0, pos=2000.0, height=2100.0)

    a3 = create_sheet(s, "S001", size="A3", scale=100, at=(-5000.0, -5000.0),
                      project="学校样例", drawing="一层平面图", number="建施-01")
    a4 = create_sheet(s, "S002", size="A4", scale=100, at=(40000.0, 0.0),
                      project="学校样例", drawing="门窗大样", number="建施-02")
    assert a3["size"] == "A3" and a4["size"] == "A4", (a3, a4)

    st = create_sheet_set(s, "SS1", [
        {"no": "建施-01", "name": "一层平面图", "sheet": "S001"},
        {"no": "建施-02", "name": "门窗大样", "sheet": "S002", "note": "详见建施-01"},
    ])
    assert st["count"] == 2, st
    back = read_sheet_set(s, "SS1")
    assert [x["no"] for x in back["items"]] == ["建施-01", "建施-02"], back
    assert [x["size"] for x in back["items"]] == ["A3", "A4"], back
    assert all(x["scale"] == 100.0 for x in back["items"]), back

    idx = create_sheet_index(s, "SS1", "ML1", (-5000.0, 15000.0))
    assert idx["count"] == 2, idx
    g = block_geometry(path, "AA_TABLE_ML1")
    texts = [x["text"] for x in g if x["type"] == "TEXT"]
    for want in ("图纸目录", "图号", "图名", "图幅", "比例", "建施-01", "一层平面图", "A3", "A4", "1:100"):
        assert want in texts, (want, texts)
    assert "详见建施-01" in texts, texts
    rows = read_sheet_index(s, "ML1")
    assert rows[0]["no"] == "建施-01" and rows[0]["size"] == "A3", rows
    assert rows[1]["scale"] == "1:100", rows

    # 批量出图：两张图幅各一个文件
    outdir = OUT / "test_sheetset_out"
    for f in outdir.glob("*"):
        f.unlink()
    res = export_sheet_set(s, "SS1", outdir, fmt="png")
    assert res["count"] == 2, res
    for f in res["files"]:
        p = Path(f["path"])
        assert p.exists() and p.stat().st_size > 2048, f
    names = sorted(Path(f["path"]).name for f in res["files"])
    assert names == ["建施-01_一层平面图.png", "建施-02_门窗大样.png"], names

    # 登记校验：图号重复 / 图幅被占用 / 图幅不存在 / 空集 / 集合编号重复
    cases = [
        ("图号重复", [{"no": "建施-01", "name": "x", "sheet": "S001"},
                     {"no": "建施-01", "name": "y", "sheet": "S002"}]),
        ("图幅", [{"no": "建施-03", "name": "x", "sheet": "S001"},
                  {"no": "建施-04", "name": "y", "sheet": "S001"}]),
        ("找不到图幅", [{"no": "建施-03", "name": "x", "sheet": "S999"}]),
    ]
    for i, (want, items) in enumerate(cases):
        try:
            create_sheet_set(s, "BAD%d" % i, items)
        except CadError as e:
            assert want in str(e), (want, e)
        else:
            raise AssertionError("应拒绝：%s" % want)
    try:
        create_sheet_set(s, "SSX", [])
    except CadError as e:
        assert "不能为空" in str(e), e
    else:
        raise AssertionError("空图纸集应被拒绝")
    try:
        create_sheet_set(s, "SS1", [{"no": "建施-09", "name": "x", "sheet": "S001"}])
    except CadError as e:
        assert "已存在" in str(e), e
    else:
        raise AssertionError("重复图纸集应被拒绝")

    # CLI 回读口径
    ro = subprocess.run([sys.executable, str(ROOT / "tools" / "aa_cmd.py"),
                         "sheet-set", str(path), "SS1", "--show=SS1"],
                        capture_output=True, text=True, encoding="utf-8")
    assert ro.returncode == 0, ro.stdout + ro.stderr
    cli = json.loads(ro.stdout.strip().splitlines()[-1])
    assert cli["ok"] and cli["count"] == 2, cli
    assert cli["items"][1]["name"] == "门窗大样", cli

    print("图纸集: 2 张（A3 建施-01 / A4 建施-02），目录 2 行，批量出图 2 个 PNG")
    print("PASS test_sheetset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
