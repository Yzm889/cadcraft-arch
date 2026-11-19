"""轴网功能验收测试。

验收链：新建图纸 -> 生成轴网 -> 回读属性/几何 -> DWG 往返后再回读。
任何一步不符就失败（不谎报成功）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import Session, block_geometry, create_axis_grid  # noqa: E402

OUT = ROOT / "samples"
OUT.mkdir(exist_ok=True)


def bbox_of(session: Session) -> list[list[float]]:
    return session.info()["extents"]


def main() -> int:
    path = OUT / "test_axis.dxf"
    if path.exists():
        path.unlink()

    s = Session(path)
    s.new_metric()

    res = create_axis_grid(
        s, "AX001",
        xcount=4, xspace=4000.0,
        ycount=3, yspace=5000.0,
        xstart=0.0, ystart=0.0, ext=1000.0,
    )
    print("axis ok:", json.dumps(res, ensure_ascii=False))

    # 1) 几何图元数量：7 条轴线 + 7 个轴号圆圈 + 7 个圈内轴号 = 21
    assert len(res["geom_handles"]) == 21, res["geom_handles"]
    assert res["ver"] == "A;B;C;D", res["ver"]
    assert res["hor"] == "1;2;3", res["hor"]

    # 2) 图元类型统计（模型空间只剩块参照，几何在块定义内）
    counts = s.info()["counts"]
    assert counts.get("Block Reference") == 1, counts

    # 2b) 轴线用点划线（CENTER）：块内 7 条 LINE 全部带线型，轴号 TEXT 不受影响
    geom = block_geometry(path, "AA_AXGRID_AX001")
    lines = [g for g in geom if g["type"] == "LINE"]
    assert len(lines) == 7, len(lines)
    assert all(g["lt"] == "CENTER" for g in lines), [g["lt"] for g in lines]
    print("axis linetype ok:", [g["lt"] for g in lines])

    # 2c) 轴号圆圈（GB/T 50104：细实线圆，直径 8mm @1:100 => 半径 400）
    circles = [g for g in geom if g["type"] == "CIRCLE"]
    assert len(circles) == 7, circles
    assert all(abs(g["r"] - 400.0) < 1e-9 for g in circles), [g["r"] for g in circles]
    texts = [g for g in geom if g["type"] == "TEXT"]
    assert len(texts) == 7, texts
    assert sorted(g["text"] for g in texts) == ["1", "2", "3", "A", "B", "C", "D"], \
        [g["text"] for g in texts]
    # 轴号文字落在圈内（距圆心不超过半径）
    for c in circles:
        cx, cy = c["pts"][0]
        assert any(abs(t["pts"][0][0] - cx) < 400 and abs(t["pts"][0][1] - cy) < 400
                   for t in texts), (cx, cy)
    print("axis circles ok:", [(round(c["pts"][0][0], 1), round(c["pts"][0][1], 1)) for c in circles])

    # 3) 属性逐项核对
    attrs = s.attributes("AA_AXGRID_AX001")
    for k, v in {
        "AA_TYPE": "AXGRID", "AA_ID": "AX001",
        "AA_XCOUNT": "4", "AA_YCOUNT": "3",
        "AA_XSPACE": "4000.0000", "AA_YSPACE": "5000.0000",
        "AA_VER": "A;B;C;D", "AA_HOR": "1;2;3",
    }.items():
        assert attrs.get(k) == v, (k, attrs.get(k), v)
    print("attributes ok:", attrs)

    # 4) 外形包围盒：轴线覆盖 0..12000 / 0..10000，轴号圆圈各再外扩
    #    左：-ext-2r = -1000-800 = -1800；上：+ext+2r = 11800（圆与轴线端相切）
    ext = bbox_of(s)
    x0, y0 = ext[0]
    x1, y1 = ext[1]
    assert abs(x0 - (-1800.0)) < 50, ext
    assert abs(x1 - 13000.0) < 60, ext                      # 最右轴线伸出端
    assert abs(y0 - (-1000.0)) < 50, ext                    # 最下轴线伸出端
    assert abs(y1 - 11800.0) < 60, ext                      # 顶部轴号圆圈
    print("extents ok:", ext)

    # 5) DWG 往返：存 DWG -> 转回 DXF -> 属性仍一致
    dwg = OUT / "test_axis.dwg"
    s.run([], save=False)  # noop，仅确认会话可用
    import subprocess
    subprocess.run([s.cli, "convert", str(path), str(dwg)], check=True,
                   capture_output=True, text=True, encoding="utf-8")
    back = OUT / "test_axis_roundtrip.dxf"
    subprocess.run([s.cli, "convert", str(dwg), str(back)], check=True,
                   capture_output=True, text=True, encoding="utf-8")
    s2 = Session(back)
    assert s2.block_exists("AA_AXGRID_AX001")
    s2.expect_attributes("AA_AXGRID_AX001", {"AA_ID": "AX001", "AA_VER": "A;B;C;D"})
    print("dwg roundtrip ok")

    print("PASS test_axis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
