"""台阶 / 散水验收（v1.0.0，B2 第 6 项）。

要点：
  · 台阶：steps 条踏步线（含外沿）+ 两侧边线，不画贴墙线；落在 AA-STEP
  · 总进深 = steps*tread，宽/踏步数/单步高可回读
  · 散水：外沿线 + 两端收头线（3 条线）
  · 重名 / 非正尺寸 / 踏步数非整数拒绝
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from aa_lib import (  # noqa: E402
    LAYERS,
    CadError,
    Session,
    block_geometry,
    create_apron,
    create_step,
    layer_of_block,
)

OUT = ROOT / "samples"


def main() -> int:
    path = OUT / "test_step.dxf"
    if path.exists():
        path.unlink()
    s = Session(path)
    s.new_metric()

    # 1. 台阶 ST1：宽 1500、3 步、踏步 300 → 5 条线（3 踏步 + 2 侧边）
    st1 = create_step(s, "ST1", (1000.0, -120.0), 1500.0, 3, 300.0, 270.0)
    assert abs(st1["depth"] - 900.0) < 1e-6, st1
    g1 = block_geometry(path, "AA_STEP_ST1")
    lines1 = [x for x in g1 if x["type"] == "LINE"]
    assert len(lines1) == 5, [x["type"] for x in g1]
    ys = sorted({round(p[1], 3) for x in lines1 for p in x["pts"]})
    assert ys == [0.0, 300.0, 600.0, 900.0], ys
    attrs = s.attributes("AA_STEP_ST1")
    assert attrs["AA_TYPE"] == "STEP", attrs
    assert attrs["AA_STEPS"] == "3", attrs
    assert abs(float(attrs["AA_DEPTH"]) - 900.0) < 1e-6, attrs
    assert abs(float(attrs["AA_H"]) - 450.0) < 1e-6, attrs
    assert layer_of_block(path, "AA_STEP_ST1") - {"0"} == {LAYERS["step"]}

    # 2. 散水 SW1：长 6000、挑 800 → 3 条线（外沿 + 两端收头）
    sw1 = create_apron(s, "SW1", (3000.0, -120.0), 6000.0, 800.0, 270.0)
    g2 = block_geometry(path, "AA_APRON_SW1")
    assert len([x for x in g2 if x["type"] == "LINE"]) == 3, [x["type"] for x in g2]
    attrs2 = s.attributes("AA_APRON_SW1")
    assert attrs2["AA_TYPE"] == "APRON", attrs2
    assert abs(float(attrs2["AA_W"]) - 800.0) < 1e-6, attrs2
    assert abs(float(attrs2["AA_LEN"]) - 6000.0) < 1e-6, attrs2

    # 3. 拒绝：重名、非正尺寸、非整数踏步
    for kwargs, msg in (
        (dict(step_id="ST1", at=(0.0, 0.0), width=1200.0), "重名"),
        (dict(step_id="ST9", at=(0.0, 0.0), width=0.0), "宽"),
        (dict(step_id="ST9", at=(0.0, 0.0), width=1200.0, steps=2.5), "踏步数"),
    ):
        try:
            create_step(s, **kwargs)
        except CadError as e:
            assert "已存在" in str(e) or "正实数" in str(e) or "整数" in str(e), (msg, e)
        else:
            raise AssertionError("应被拒绝：%s" % msg)

    try:
        create_step(s, "ST8", (0.0, 0.0), 1200.0, 2, -300.0)
    except CadError as e:
        assert "正实数" in str(e), e
    else:
        raise AssertionError("应被拒绝：负踏步宽")

    print("台阶: %s 步 × %s = %s mm, 散水挑 %s mm" %
          (st1["steps"], st1["tread"], st1["depth"], sw1["width"]))
    print("PASS test_step")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
