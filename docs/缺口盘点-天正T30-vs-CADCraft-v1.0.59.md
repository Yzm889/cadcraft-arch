# CADCraft 与天正 T30-Arch V2.0 缺口盘点

> 轮次：第 1 轮（只盘点 + 规格，不写实现）
> 基线：`cadcraft-arch` v1.0.59；幼儿园教学楼 00–05 已验收，本轮不动
> 分析对象：天正建筑 T30-Arch V2.0（安装于 `C:\Tangent\TArchT30V2`；连接器实测记录 Build250811 + AutoCAD 2022）
> 口径：只做行为、交互、DXF 结果层分析；不解析/复制私有实体、XData、LISP/ARX、图标与菜单资源

## 0. 输入修正（模板占位符未填）

你给的模板里 `<版本>`、`<标准样本路径>`、`<异常样本路径>` 仍是占位符。本轮按本机可核实的信息先填，**请确认或纠正**：

| 项 | 本轮采用 | 依据 | 状态 |
|---|---|---|---|
| 天正版本 | T30-Arch V2.0（Build250811） | 安装目录 `C:\Tangent\TArchT30V2`；天正连接器 README 实测记录 | 待确认 |
| 标准样本 | `C:\Tangent\TArchT30V2\samples\幼儿园方案\Floor1.dwg` ~ `Floor4.dwg` + `BUILDING.DBF` | T30 自带官方范例（4 层幼儿园） | 待确认 |
| 异常样本 | `C:\Users\19891\Desktop\插件创作\Drawing31.dwg`；`教学楼一层平面图.dwg` | 本机已有天正图纸 | 待确认 |
| 天正侧 DXF 前后差分 | 未执行 | 需授权运行天正并导出 DXF；本轮不运行 | UNKNOWN-06 |

> 注意：官方标准样本是 **4 层**幼儿园，交付基线是 **5 层**。两者楼层数不同，比对时以"单层构件行为"为准，不按整栋对齐。

---

## 1. 当前基线

### 1.1 CADCraft 已实现能力（v1.0.59，证据 E-C01/E-C07）

| 类别 | 已实现 | 验收状态 |
|---|---|---|
| 轴网 | `axis`（等距/逐段间距）、`axis-auto`（按墙反推+回填轴号）、`axis-bind` | 完成 |
| 墙体 | `wall`（厚/类型/材质/轴号、转角合角、相交裁剪、吸附轴）、`set-wall`、`split`、`merge` | 完成 |
| 门窗 | `opening`（DOOR/WINDOW/DOORWIN，真实开洞、铰点/开向/单双扇/门连窗）、`set-opening` | 完成（v1.0.59 图例） |
| 房间 | `room`（显式墙环）、`room --auto`（半边面遍历）、`set-room`、`rooms`（CSV/表格） | 完成 |
| 楼梯 | `stair`（直跑/双跑、首层/中层/顶层、45° 剖断、上/下注字） | 完成 |
| 柱 | `column`（矩形/圆柱、实心填充） | 完成 |
| 屋顶 | `roof`（平/双坡/四坡/单坡）、`roof-detail`（分格/内天沟/坡度） | 完成 |
| 总平面 | `site`（红线/建筑/道路/出入口/指北针/坐标尺寸） | 完成（M2） |
| 立面 | `elevation`（楼层/门窗/女儿墙/坡屋顶/标高/尺寸）、`elev-balcony`（阳台/雨篷） | 完成 |
| 剖面 | `profile`（地坪/墙带/楼板/屋面/门窗/隔墙/梁/楼梯断面/标高/尺寸） | 完成 |
| 详图 | `detail-mark`、`wall-node`、`stair-detail`、`wc-detail` | 完成 |
| 表格 | `floors`、`opening-table`（7 列）、`sheet-index` | 完成 |
| 图纸集/出图 | `sheet-set`、`export-set`、`sheet`/`set-sheet`、`export`、`place` | 完成 |
| 标注/符号 | `dim`（三道外墙尺寸）、`title`、`north`、`elev`、`index`、`section`、`text`、`leader` | 完成 |
| 比例 | `new --scale`、`scale`、`rescale` | 完成 |
| 工程化 | 21 标准层、`audit`、`verify`、`reconcile`、`copy-floor` | 完成 |
| Agent 接口 | MCP 59 工具（56 原子 + batch/checkpoint/restore） | 完成 |

- 测试：52 项，按功能独立跑（E-C04）。
- 已验收：幼儿园 00–05，`audit count=0 / warning_count=0`（E-C07）。
- 平台约束：CADCraft 0.20.1 无 XData；LISP 建/读不了属性；`entlast` 不可靠；`insert.rotation` 入参度/回读弧度（E-C03）。

### 1.2 本次不重复分析

- 00–05 六张图的几何与图面质量（v1.0.57–v1.0.59 已修：图签压线、说明术语、门窗/楼梯图例）。
- 已完成的 M1 / M2 功能本身。
- M2/M3 内部待办（设计说明页/会签栏、多页 PDF、CI、plot_style、全量回归、同图多比例）——不是"天正差异"，单列在 §2 末行，不占候选名额。

---

## 2. 缺口表

优先级口径：**P1** = 对成图影响大 + 依赖少 + 能独立验收；**P2** = 影响中或依赖中等；**P3** = 影响小或依赖多。
证据编号见 §6。

| # | 功能 | 天正入口 | CADCraft 现状 | 差异 | 影响 | 优先级 | 证据 |
|---|---|---|---|---|---|---|---|
| 1 | 门窗类型：带形窗/转角窗/组合门窗/异形洞 | `TBanWin` `TCornerWin` `TGroupOpening` `TPolyHole` | 只有单洞 `DOOR/WINDOW/DOORWIN`；一个洞口一堵墙 | 缺"跨多墙/跨转角/组合/异形"四类；幼儿园带形窗、转角窗常用 | 平面/立面门窗表达不完整，影响最大 | P1 | E-T01,E-T02,E-C05 |
| 2 | 竖向交通与无障碍：电梯/坡道/阳台（平面） | `TElevator` `TAscent` `TBalcony` `tdrawautostair` | 楼梯只有直跑/双跑；`step`/`apron` 有；电梯只画门洞+文字，无电梯符号；无坡道；阳台只有立面 | 5 层幼儿园必需电梯/无障碍坡道；平面阳台缺失 | 合规性与平面完整性 | P1 | E-T01,E-T02,E-C01,E-C06 |
| 3 | 尺寸与符号标注：墙厚/门窗/洞口/坐标/半径直径 | `TDimWall` `TDim3` `TCaveSize` `TCoord` `TDimRad` `TDimDia` | `dim` 只有三道外墙尺寸；`elev/index/section/title/north` 有 | 缺墙厚标注、门窗定位标注、洞口尺寸、坐标标注、半径/直径/角度/弧弦 | 施工图规范性、返工率 | P1 | E-T01,E-T02,E-C01 |
| 4 | 屋顶类型：任意坡顶/人字坡/攒尖/矩形/老虎窗/雨水管 | `TSlopeRoof` `TDualSlopeRoof` `TCuspRoof` `TRectRoof` `TDormer` `TStrm` `TRoflna` | `roof` 只有平/双坡/四坡/单坡（矩形轮廓）；`roof-detail` 有分格/天沟/坡度 | 缺任意多段线坡顶、人字坡、攒尖、老虎窗、雨水管/排水 | 屋顶平面成图；本轮 00–05 无屋顶图，暂列 P2 | P2 | E-T01,E-T02,E-C01 |
| 5 | 房间面积体系：轮廓/边界/套内/公摊/统计/字转房间 | `TSpOutline` `TModifySpaceEdge` `TApartArea` `TShareArea` `TCountArea` `TTextToSpace` | `room`/`room --auto`/`set-room`/`rooms`；面积=净面积，可按编号汇总 CSV | 缺套内/公摊/住宅面积、面积统计表、房间轮廓独立对象、边界编辑、字转房间 | 报建面积表、面积核对 | P2 | E-T01,E-T02,E-C01 |
| 6 | 门窗管理：检查/总表/归整/填墙/翻转/留洞表/编号设置 | `TValidOp` `TPrjOP` `TWDRegul` `TFillOpening` `TMirWinIO/LR` `TStaticHole` `TSetWinLab` | `opening-table`（7 列）、`set-opening`（含编号/铰点/开向）、`audit` 查越界/重叠 | 缺门窗检查器、门窗总表、归整、填墙、内外/左右翻转、留洞表、编号批量设置 | 门窗表与校审效率 | P2 | E-T01,E-T02,E-C01 |
| 7 | 立面细部：立面门窗库/窗套/立面屋顶/雨水管/构件立面 | `TEWinLib` `TEWPara` `Id_Elwct` `tlmroof` `TEStrm` `TObjElev` | `elevation` 基本立面 + `elev-balcony` | 缺立面门窗库/参数、窗套、立面屋顶细部、雨水管、单构件立面 | 立面完成度 | P2 | E-T01,E-T02,E-C01 |
| 8 | 剖面细部：预制板/檐口/过梁/参数楼梯/栏杆/填充/加粗 | `Id_Sfloor1` `Id_Sroof` `MCGL` `TSectStair` `Id_Rltplib` `ID_FillSect` `Id_Sltoplc1` | `profile` 基本剖面 + 梁 + 楼梯断面 + 门窗断墙 | 缺预制板、檐口、门窗过梁、参数楼梯/栏杆、剖面填充、加粗工具 | 剖面完成度 | P2 | E-T01,E-T02,E-C01 |
| 9 | 文字表格：多行/曲线/词库/统计/加框/表格全套/Excel 互转 | `TMText` `TCurveText` `TWordLib` `TTxtCount` `TTextAddFrame` `TNewSheet` `Sheet2Excel` | `text`（单行）、表格仅房间/门窗/楼层专用 | 缺多行文字、曲线文字、专业词库、文字统计/加框、通用表格、Excel/Word 互转 | 说明页、表格效率 | P2 | E-T01,E-T02,E-C01 |
| 10 | 轴网编辑：单轴/增删/裁剪/合并/轴改线型/轴网标注/一轴多号 | `TSingleAxis` `TInsAxis` `TDelAxis` `TClipAxis` `TMergeAxis` `TAxisDote` `TMultAxisDim` `TMutiLabel` | `axis`/`axis-auto`/`axis-bind`；`dim` 带轴线尺寸 | 缺单轴增删、裁剪合并、轴改线型、轴网标注（多轴）、一轴多号/轴号隐现 | 轴网返工 | P2 | E-T01,E-T02,E-C01 |
| 11 | 墙体编辑：切割/等分/单线变墙/分段/幕墙/倒角/修角/基线对齐/净距/保温/造型 | `tkatana` `TDivWall` `TSWall` `TPartwall` `TConvertCurtain` `TFillet` `TFixWall` `TAdjWallBase` `TOffset` | `wall`/`set-wall`/`split`/`merge` | 缺大部分墙体编辑命令 | 改图效率 | P3 | E-T01,E-T02 |
| 12 | 天正私有对象互操作 | 天正 `TDbWall` 等 | CADCraft 读入为标准 `Proxy`：Floor1 216 个、教学楼 65 个、Drawing31 42 个 | **不做**：按合规约束不解析私有对象；只认公共 DXF 实体/图层 | 边界，不是缺口 | — | E-D01,E-D02,E-D03 |
| 13 | 内部待办（非天正差异） | — | 设计说明页/会签栏、多页 PDF、CI/plot_style/回归/多比例 | 工程化，不是天正能力差 | 交付效率 | P3 | E-C01 |

---

## 3. 候选模块（按"影响大 / 依赖少 / 可独立验收"排序）

### 候选 1：M-OPEN 门窗类型扩展
**为什么先做它**
- 门窗是每张平面图出现频率最高的构件；当前只有单洞门/窗/门连窗，幼儿园常见的带形窗、转角窗、组合门窗、异形洞都画不出来。
- 已有 `opening` 的开洞、校验、重建框架，扩展点集中，不需要改动墙/房间的数据模型。
- 验收最直接：洞口两侧墙线断开区间 + 门窗块几何，DXF 可逐项断言。

### 候选 2：M-VERT 竖向交通与无障碍
**为什么排第二**
- 5 层幼儿园的电梯、无障碍坡道是合规性缺口；当前电梯只有"门洞 + 文字"，没有电梯符号，也没有坡道和平面阳台。
- 与门窗/房间耦合低，是新增独立构件族（块 + 图层 + 属性），可独立验收。
- 频次低于门窗，但一旦缺就是"图不完整"的硬伤。

### 候选 3：M-DIM 尺寸与符号标注补齐
**为什么排第三**
- 当前只有三道外墙尺寸；墙厚标注、门窗定位、洞口尺寸、坐标标注都缺，直接影响"图规不规范、返工率高不高"（这是当前阶段重心）。
- 纯注记层，依赖最低，不动几何；可用"测量值回读"逐条验收。
- 排第三是因为它不改变构件本身，属于"表达完整度"而非"能不能画出来"。

> 屋顶类型（P2）不是不重要，而是本轮 00–05 没有屋顶图；若下一交付包含屋顶平面，应把它提到候选 1 或 2。

---

## 4. 规格卡

### 4.1 M-OPEN 门窗类型扩展

**目标**
在现有 `opening` 上增加四类洞口：**带形窗（BAND）**、**转角窗（CORNER）**、**组合门窗（GROUP）**、**异形洞（POLYHOLE）**，保持"依附墙、真实开洞、越界/重叠拒绝、失败零残留"。

**前置状态**
- 图纸已 `new`（21 标准层已建）；目标墙已存在且 `AA_THICK>0`。
- 转角窗要求两墙共享转角顶点（容差 1mm）；组合门窗的每个子洞口都满足单洞规则。

**输入参数和默认值（提案，天正参数细节待核）**

| 参数 | 带形窗 | 转角窗 | 组合门窗 | 异形洞 | 默认 |
|---|---|---|---|---|---|
| `wall` / `walls` | 1 堵（首期） | 2 堵（转角） | 1 堵 | 1 堵 | 必填 |
| `pos` | 洞口中心距墙起点 | 距转角两墙各一段 | 组合中心 | — | 必填 |
| `width` | 洞口总宽 | 两肢宽 `w1,w2` | 组合总宽 | — | 必填 |
| `height` | 洞高 | 洞高 | 各子项洞高 | 洞高 | 窗 1500 / 门 2100 |
| `sill` | 窗台高 | 窗台高 | 子项窗台 | 洞底高 | 0 |
| `frame` | 窗框厚 | 窗框厚 | 子项框厚 | — | 60 |
| `mullion` | 竖梃间距 | — | — | — | 900（提案） |
| `subs` | — | — | 子项列表（门/窗/固定窗） | — | 必填 |
| `pts` | — | — | — | 闭合多段线点串 | 必填 |

**操作步骤**
1. 校验墙存在、厚度>0、洞口区间在墙段内、同墙洞口不重叠。
2. 带形窗：按 `pos/width` 在墙中心线截洞口，按 `mullion` 生成竖梃；转角窗：在两墙转角处各截一段，生成 L 形洞口与转角梃；组合门窗：逐子项截洞并生成对应图例；异形洞：把 `pts` 投影到墙中心线坐标系，生成异形洞口边线。
3. 断开墙两侧线（洞口区间），生成门窗块（含属性），插入点=墙起点、旋转=墙方向、缩放=1。
4. 回读：洞口区间、块属性、墙线断开段、重叠检查；任一项失败回滚。

**生成/修改实体**

| 项 | 规格 |
|---|---|
| 实体 | `INSERT`（门窗块）+ 墙块内墙线修改 |
| 图层 | `AA-OPENING`（青 4、实线、0.18）；墙线仍在 `AA-WALL` |
| 块名 | `AA_OPENING_<编号>` |
| 属性 | `AA_TYPE=OPENING`、`AA_ID`、`AA_KIND`（BAND/CORNER/GROUP/POLYHOLE）、`AA_WIDTH/AA_HEIGHT/AA_SILL/AA_FRAME`、`AA_WALLID`（转角窗为 `AA_WALLIDS`）、`AA_POS`、`AA_SUBS`（JSON，组合）、`AA_PTS`（异形洞） |
| 图例 | 带形窗：连续四线 + 竖梃；转角窗：两肢四线 + 转角梃；组合门窗：门扇弧 + 固定窗四线 + 中梃；异形洞：洞口边线（无门窗符号） |

**边界、异常、回滚、幂等**
- 拒绝：墙不存在、厚度≤0、洞口越界、同墙重叠、转角两墙不共角、组合子项越界、异形洞不闭合/超出墙面、编号重复——**图纸零改动**。
- 回滚：先全量校验，再写；写前整图字节快照，异常原子写回；`.bak` 仅作辅助。
- 幂等：同 `AA_ID` + 同 `AA_KIND` + 同几何参数重复执行返回 `changed:0`，不堆块。

**DXF 差分摘要**
- 预期（CADCraft 侧）：新增 1 个 `INSERT`（`AA_OPENING_*`），墙块内洞口区间两侧线断开，新增/更新对应 `ATTRIB`；墙中心线、其它墙、房间不变。
- 天正侧实测差分：**UNKNOWN-06**（本轮未运行天正）。执行方法见 §5。

**证据编号**
E-T01（`TBanWin/TCornerWin/TGroupOpening/TPolyHole` 存在）、E-T02（`7-门窗.pdf`）、E-C01（README 门窗现状）、E-C05（`aa_opening.lisp` 仅 3 类）。

**CADCraft 实现建议**
- 在 `aa:opening` 内按 `kind` 分支，复用现有"洞口区间→断墙线→重建"函数；新增 `aa:opening-band/corner/group/polyhole`。
- CLI/MCP 各加一个工具；参数校验集中在 `aa_lib`，与现有 `opening` 一致。
- 测试：每类 1 个正例 + 3 个拒绝例（越界/重叠/不共角），断言墙线断开区间与块属性。

**UNKNOWN 和风险**
- U-01：天正四类洞口的完整参数集、默认值、失败处理（需 `7-门窗.pdf` 或实测）。
- 转角窗的墙转角处理（合角/裁剪）可能与现有 `normalize_around` 冲突，需先做几何可行性验证。
- 组合门窗的子项语义（是否共享一个编号/一个块）未证实。

---

### 4.2 M-VERT 竖向交通与无障碍

**目标**
新增三个平面构件：**电梯（ELEV）**、**坡道（RAMP）**、**阳台（BALCONY，平面）**，补齐 5 层幼儿园的竖向交通与无障碍表达。

**前置状态**
- 电梯：所在位置有闭合井道墙（可由现有 `wall` 画）；电梯门洞可由 `opening` 预留。
- 坡道：两端有地坪/入口；坡度与长度满足 `length ≥ height/slope`。
- 阳台：依附外墙，所在墙段无洞口冲突。

**输入参数和默认值（提案）**

| 构件 | 参数 | 默认 |
|---|---|---|
| 电梯 | `at`（井道中心）、`w×d`（轿厢/井道）、`door`（门宽）、`wall_thick`、`label` | 2000×2200、门 1100、墙 200、注"电梯" |
| 坡道 | `p1,p2`（起终点）、`width`、`slope`（1:n）、`rail`（是否画扶手）、`arrow` | 宽 1500、1:12、画扶手、画箭头 |
| 阳台 | `wall`、`pos`（沿墙起点）、`width`、`depth`、`rail`、`drain` | 宽 3000、深 1200、栏板 100、否 |

**操作步骤**
1. 校验前置（井道闭合/坡道长度/阳台贴外墙且不压洞口）。
2. 生成对应块：电梯=井道轮廓+轿厢+对重+门；坡道=两条边线+坡度箭头+`i=1:n` 注字+扶手线；阳台=外轮廓+栏板线+（可选）地漏。
3. 落属性、回读、失败回滚。

**生成/修改实体**

| 项 | 规格 |
|---|---|
| 实体 | `INSERT`（构件块）+ 必要时墙/洞口不变 |
| 图层 | 电梯 `AA-ELEV`（提案）、坡道 `AA-RAMP`（提案）、阳台 `AA-BALCONY`（提案）；或复用 `AA-STAIR`/`AA-STEP`，需拍板 |
| 块名 | `AA_ELEVATOR_<id>` / `AA_RAMP_<id>` / `AA_BALCONY_<id>` |
| 属性 | `AA_TYPE=ELEVATOR/RAMP/BALCONY`、`AA_ID`、`AA_W/AA_D/AA_SLOPE/AA_RAIL`、`AA_WALLID`、`AA_POS` |
| 图例 | 电梯：井道矩形 + 轿厢 + 门洞；坡道：双线 + 箭头 + 坡度注字；阳台：轮廓 + 栏板 |

**边界、异常、回滚、幂等**
- 拒绝：电梯井道未闭合、坡道长度不足/坡度非法、阳台不贴外墙/压洞口、编号重复——零改动。
- 回滚/幂等：同 M-OPEN。

**DXF 差分摘要**
- 预期：新增 1 个 `INSERT` + 对应图层/属性；墙、门窗、房间不变。
- 天正实测：UNKNOWN-06。

**证据编号**
E-T01（`TElevator/TAscent/TBalcony`）、E-T02（`10-楼梯与其他.pdf`）、E-C01（楼梯仅直跑/双跑）、E-C06（`build_kindergarten.py` 电梯仅门洞/文字）。

**CADCraft 实现建议**
- 新增 `aa_elevator.lisp` / `aa_ramp.lisp` / `aa_balcony.lisp`，CLI/MCP 三个工具；复用 `aa_lib` 的块/属性/回读框架。
- 图层若不想新增，可复用 `AA-STAIR`（电梯/坡道）与 `AA-STEP`（阳台），但建议新增以便 audit 区分。

**UNKNOWN 和风险**
- U-02：天正电梯/坡道/阳台的图例细节、图层/块名、是否生成 3D 对象（需 `10-楼梯与其他.pdf` 或实测）。
- 电梯井道墙是否由本模块自动生成（还是要求用户先画墙）未定；建议首期"要求先画墙，模块只画电梯符号"。
- 坡道坡度注字格式（`i=1:12` vs `8.3%`）需拍板。

---

### 4.3 M-DIM 尺寸与符号标注补齐

**目标**
在现有 `dim`（三道外墙尺寸）之外，补齐 **墙厚标注（TDimWall）**、**门窗定位标注（TDim3）**、**洞口尺寸（TCaveSize）**、**坐标标注（TCoord）**，并覆盖半径/直径/角度/弧弦。

**前置状态**
- 图档比例已定（`new --scale` / `scale`）；`AA-DIM` 层已建。
- 目标墙/门窗/点已存在；坐标标注需给出世界坐标点。

**输入参数和默认值（提案）**

| 子命令 | 参数 | 默认 |
|---|---|---|
| `dim-wall` | `wall`、`side`、`offset`、`text`（可覆盖） | 自动取 `AA_THICK`，字高 2.5mm@1:100 |
| `dim-opening` | `opening`、`side`、`chain`（到轴线/墙端） | 两侧各一道 |
| `dim-hole` | `opening`、`dir`（宽/高） | 宽 |
| `dim-coord` | `pt`、`axis`（x/y/xy）、`precision`、`unit`（m/mm） | xy、3 位小数、m |
| `dim-radial` | `entity`、`mode`（半径/直径/角度/弧弦） | 半径 |

**操作步骤**
1. 校验目标存在、比例已定、标注不与现有尺寸/轴号重叠（可复用 `audit` 的压碰检查）。
2. 生成原生 `DIMENSION`（或现有多段线+文字方案，与 `dim` 保持一致），落 `AA-DIM`。
3. 回读测量值，与目标几何比对；失败回滚。

**生成/修改实体**

| 项 | 规格 |
|---|---|
| 实体 | `DIMENSION`（优先）或线+箭头+文字（与现有 `dim` 实现一致） |
| 图层 | `AA-DIM`（绿 3、实线、0.15） |
| 属性 | 无需块属性；标注值由几何决定，可加 `AA_DIM_KIND/AA_TARGET` 便于回读（若用块） |
| 文字 | 字高按比例取 mm；墙厚写 `240`；坐标写 `X=… Y=…` |

**边界、异常、回滚、幂等**
- 拒绝：目标不存在、比例未定、墙厚≤0、洞口不存在、坐标点越界、标注与已有标注重叠且无法避让——零改动。
- 幂等：同一 `(kind,target,side)` 已存在则跳过/更新，不重复叠加。

**DXF 差分摘要**
- 预期：新增 `DIMENSION`（或标注图元）于 `AA-DIM`；几何不变；测量值可回读。
- 天正实测：UNKNOWN-06。

**证据编号**
E-T01（`TDimWall/TDim3/TCaveSize/TCoord/TDimRad/TDimDia`）、E-T02（`14-尺寸标注.pdf`、`15-符号标注.pdf`）、E-C01（`dim` 仅三道外墙尺寸）。

**CADCraft 实现建议**
- 扩展 `aa_dim.lisp` 为子命令族；复用现有尺寸样式/比例/避让；CLI `dim --kind` 或独立子命令，MCP 对应工具。
- 测试：墙厚标注读回 `240`；门窗定位读回到轴线距离；坐标读回与输入点一致；重叠时拒绝。

**UNKNOWN 和风险**
- U-03：天正默认字高/箭头/偏移、坐标格式（`X=…`/`Y=…` 或 `x,y`）、墙厚标注是否关联墙体。
- 现有 `dim` 若用"线+文字"而非原生 `DIMENSION`，扩展时需保持同一套，避免两套标注风格混用。
- 坐标标注单位（m vs mm）与本图单位（mm）的换算需明确。

---

## 5. 建议下一个动作

1. **先确认输入**：天正版本（是否 T30 V2.0 Build250811）、标准样本（官方 4 层幼儿园是否可用）、异常样本（Drawing31 / 教学楼一层平面图 哪张作异常）。
2. **选一个模块**（M-OPEN / M-VERT / M-DIM）。我只对选中模块出"详细 spec + 测试用例"，仍不写实现；确认后再进入编码。
3. **若要天正侧 DXF 实测差分**：需要你授权我在天正里跑命令并导出 DXF（标准样本 Floor1，异常样本 Drawing31）。我会先给"命令→导出→对比"清单，不改 00–05，不解析私有对象。
4. **本轮不动** `deliverables/幼儿园教学楼/00–05`；任何新模块验收都在独立样本/新图上做。

---

## 6. 证据清单

| 编号 | 来源 | 证明内容 |
|---|---|---|
| E-C01 | `cadcraft-arch/README.md`（v1.0.59） | 已实现功能、命令、图层、数据模型、平台约束、M2/M3 待办 |
| E-C02 | README L218–244、L314–330 | 21 标准层、块+`AA_`属性数据模型 |
| E-C03 | README L481–490 | CADCraft 平台约束（无 XData、属性读写限制、entlast 不可靠、旋转单位） |
| E-C04 | `tests/`（52 项） | 逐功能验收基线 |
| E-C05 | `lisp/aa_opening.lisp` L53 | 门窗仅 `DOOR/WINDOW/DOORWIN` 三类 |
| E-C06 | `deliverables/幼儿园教学楼/build_kindergarten.py` L41、L524–556 | 电梯仅门洞+文字，无电梯符号；无坡道/平面阳台 |
| E-C07 | `deliverables/幼儿园教学楼/验收报告.md` | 00–05 已验收，`audit count=0 / warning_count=0` |
| E-C08 | `git log` `3e4a6ba` | v1.0.59 门窗/楼梯图例修正 |
| E-T01 | `C:\Tangent\TArchT30V2\help\CmdMapToHelp.txt`（462 条命令 / 22 模块；仅引用缺口所需条目，见 `docs/evidence/tianzheng-commands-cited.md`，未拷贝全表） | 天正命令入口与模块 |
| E-T02 | `C:\Tangent\TArchT30V2\help\4-轴网.pdf` … `15-符号标注.pdf` | 天正各模块官方行为说明 |
| E-T03 | `C:\Tangent\TArchT30V2\samples\幼儿园方案\Floor1–4.dwg` + `readme.txt` | 官方幼儿园标准样本（4 层） |
| E-T04 | `C:\Users\19891\Desktop\插件创作\README.md`、`未实现功能.md` | T30 V2.0 Build250811 + AutoCAD 2022 实测记录；天正对象/命令行为 |
| E-D01 | `cadcraft-cli info Floor1.dwg` | 216 Proxy / 38 Line / 2 Text——天正对象在 CADCraft 为 Proxy |
| E-D02 | `cadcraft-cli info 教学楼一层平面图.dwg` | 65 Proxy + 65 原生实体混合 |
| E-D03 | `cadcraft-cli info Drawing31.dwg` | 42 Proxy |

### UNKNOWN 清单

| 编号 | 内容 | 补齐方式 |
|---|---|---|
| U-01 | 天正带形窗/转角窗/组合门窗/异形洞参数集与失败处理 | 读 `7-门窗.pdf` 或天正实测 |
| U-02 | 天正电梯/坡道/阳台图例、图层/块名、是否 3D | 读 `10-楼梯与其他.pdf` 或天正实测 |
| U-03 | 天正墙厚/门窗/洞口/坐标标注默认值与格式 | 读 `14/15.pdf` 或天正实测 |
| U-04 | 天正精确 build 号 | 连接器 README 记 Build250811；安装目录未见版本文件 |
| U-05 | 异常样本最终选用哪张 | 你确认 |
| U-06 | 天正侧 DXF 前后差分 | 授权运行天正并导出 DXF 后执行 |
| U-07 | 天正私有对象是否可用公共 Proxy 图形边界 | 按合规约束：不解析，边界为"不做互操作" |
