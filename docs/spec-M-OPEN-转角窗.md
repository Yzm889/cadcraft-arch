# M-OPEN 转角窗规格（v1.0.64）

状态：可执行；库 / CLI / MCP 已落地，验收 `tests/test_open_corner.py`。
适用：两堵外墙在建筑外角相交，窗从角点连续包过去，平面图上不再留一段实墙角。

## 1. 产品口径

转角窗 = 两樘联动边窗 + 一个转角柱。

- 两堵墙必须**共用端点**（同一坐标，容差 1 mm）且**互相垂直**（方向点积 ≤ 1e-3）。
- 每侧窗从共用角点沿墙向室内方向延伸 `len_a / len_b`；不允许离开角点另起一段。
- 两侧只能由 WINDOW 面板组成：缺省为一整樘窗；给面板序列时即为带形转角窗，面板合计必须等于该侧窗长。
- 两侧共用同一个门窗编号 `no`，缺省取转角窗 `id`；两侧洞口都写 `AA_CORNER=<id>`，供后续筛选和表头归并。
- 转角柱是 `AA_CORNER_<id>` 块：墙中心线交点处一个边长 `post` 的正方形，4 条 `AA-OPEN` 线；
  不新增图层，不画填充，不替代墙体材料。
- 插入失败（含第二侧越界/重叠、柱块生成失败）整图按字节回滚，原图零残留。

## 2. 参数

```
create_corner_window(session, id, wall_a, wall_b, len_a, len_b,
                     height=1500, sill=900, frame=60, post=300,
                     no="", panels_a=None, panels_b=None,
                     label_side="in", label_h=2.5, floor=1)
```

CLI：

```
python tools/aa_cmd.py corner-opening <path> <id> \
  --wall-a W001 --wall-b W002 --len-a 1800 --len-b 1500 \
  [--height 1500] [--sill 900] [--frame 60] [--post 300] \
  [--no CW01] [--panels-a "W900;W900"] [--panels-b "W750;W750"] \
  [--label-side in] [--label-h 2.5] [--floor 1]
```

MCP：`aa_corner_opening`，字段与 CLI 同名（下划线风格）。

## 3. 几何与数据

- 两侧洞口仍是标准 `AA_OPENING_<id>-A` / `-B`，`kind=COMBO`，走既有 `aa:win4` 四线窗图例；
  `AA_WALLID / AA_POS / AA_WIDTH / AA_PANELS / AA_NO` 全部沿用。
- `AA_POS` 按“从共用角点起算的中心距离”换算：角点在墙起点时 `pos=len/2`，在终点时 `pos=墙长-len/2`。
- 转角柱属性：
  `AA_TYPE=CORNER_WINDOW`、`AA_ID`、`AA_WALL1/2`、`AA_OPENING_A/B`、`AA_W1/2`、`AA_POST`、
  `AA_NO`、`AA_FLOOR`、`AA_ATX/ATY`。
- 两侧洞口图元数和普通单扇窗一致；转角柱固定 4 LINE，无 TEXT。

## 4. 拒绝条件

| 条件 | 结果 |
|---|---|
| 同一堵墙 / 墙不存在 | `CadError`，不写入 |
| 两墙不共端点、共两个端点（重合） | 拒绝 |
| 两墙不垂直 | 拒绝 |
| 单侧窗长 `< 600`、超过墙长 | 拒绝 |
| 柱宽不在 `100–600`，或大于单侧窗长 | 拒绝 |
| 任一侧面板含 DOOR，或合计不等于窗长 | 拒绝 |
| 与同墙已有洞口重叠 | 由 `create_opening` 拒绝，包装层整图回滚 |
| 转角柱/任一边窗块已存在 | 拒绝，不覆盖 |

## 5. 已知边界

1. 门窗表当前按两侧洞口分别计数：同一 `no` 会出现两行/两樘，尚未合并成“一樘转角窗”。
   若后续要合并，应在 `openings_report` 按 `AA_CORNER` 分组，并明确面积/宽度取哪一侧。
2. 立面/剖面按两道墙分别读洞口，转角处会出现两个相邻洞口；尚未做“整体转角洞口”展开。
3. 转角柱目前是轴对齐正方形，未按墙厚做 L 形包角；材料/保温收口留给后续构造节点。
4. 只做两墙直角；斜角、三墙阳角、弧墙不在本版范围。

## 6. 验收

`tests/test_open_corner.py` 覆盖：

- 正常 1800/1500：块存在、4 线柱、`pos` 从角点起算、`AA_CORNER`/`AA_PANELS` 回读；
- 不共角 / 不垂直 / 超墙长 / 含门面板 / 柱过宽 / 重复编号 / 同墙重叠七类拒绝；
- 第二侧重叠时，第一侧已插入也整图字节回滚，`AA_CORNER`、`-A`、`-B` 均不存在；
- CLI `corner-opening` 与 MCP `aa_corner_opening` 同参可复现。
