# cadcraft-arch

**面向 CADCraft 的自研建筑智能绘图插件**（MIT 协议）。

让 AI 直接驱动 CADCraft 画建筑平面图：轴网、墙体、门窗、房间，全部由 AI 按指令生成，并且**每一步都经回读校验，不谎报成功**。

## 现状（v0.9，已实测跑通）

| 功能 | 命令 | 状态 | 验收 |
|---|---|---|---|
| 新建公制图纸 | `new` | 完成 | — |
| 轴网（等距） | `axis` | 完成 | 4 纵 + 3 横、14 个图元、10 项属性、DWG 往返 |
| **轴网自动** | `axis-auto` | 完成 | 由墙反推轴线：竖墙 x 聚类、横墙 y 聚类（`--tol` 50mm 合同轴）、竖轴编 1/2/3、横轴编 A/B/C、轴线端外伸 2400、斜墙跳过并记 `AA_SKIP`；回读校验线数/圈数/文字/线型（全 CENTER） |
| 墙体 | `wall` | 完成 | 水平/斜墙长度与角度、厚度属性、包围盒；相交处墙线裁剪 + **转角合角** |
| 门窗 | `opening` | 完成 | 依附墙、越界拒绝、重叠拒绝、宽度校验；**洞口在墙身真实开洞**（侧线断开） |
| 房间 | `room` | 完成 | 闭合墙环校验、内偏移净面积（3360×4560 实测）；只落名称文字，不画与墙面重合的轮廓 |
| 房间自动搜环 | `room --auto` | 完成 | 从全部墙自动枚举闭合房间（半边面遍历，线性复杂度）；T 接/十字交叉自动打断只在搜索时生效、**不改图纸**；自动编号 `R001…`、重跑幂等、不闭合缺口不虚报 |
| 房间改名 | `set-room` | 完成 | 按已存轮廓整体重建（块内名称文字真的重画）；面积/轮廓不变、同名幂等不写盘、未知房间拒绝且字节不变、失败自动回滚 |
| 房间汇总 | `rooms` | 完成 | 按编号列出净面积/周长/围合墙，导出 CSV（BOM，Excel 双击不乱码）或插入图上表格（中文标题+表头+合计行，4 列） |
| 墙体相交切断 | `split` | 完成 | 十字交叉 2→4 段、编号与逻辑根保留、门窗迁移、幂等、跨切点拒绝且零残留 |
| 墙体合并 | `merge` | 完成 | 切断可逆：4→2 段、原编号恢复、门位回 2700、幂等、非共线/墙厚不一致拒绝且零残留 |
| 改墙参数 | `set-wall` | 完成 | 改墙厚/类型/材质/轴号后整体重建：墙线、洞口边线、邻墙裁剪全部同步；拒绝零残留、幂等 |
| 改门窗参数 | `set-opening` | 完成 | 改位置/宽度/类型/窗框厚/编号后重建符号并重排所属墙缺口；越界/重叠拒绝且文件字节不变 |
| 门窗表 | `openings` | 完成 | 同编号合并计数，列洞口宽高/樘数/所在墙；CSV 与图上表格（6 列，编号窄、所在墙宽）|
| 尺寸标注 | `dim` | 完成 | 外墙墙段长度标外层、洞口宽标内层，落在 `AA-DIM` 层；内墙自动跳过，重跑幂等、回读测量值 |
| 图框 + 标题栏 | `sheet` / `set-sheet` | 完成 | GB/T 14689 图幅（A0–A4）、装订边 25、其余边 A0/A1=10 其余 5；标题栏 180×56 九格（GB/T 10609.1）；不给位置按全图外廓（墙/房间/轴号/尺寸/表格）自动居中排图，装不下直接报错；重复编号拒绝、改标题栏后块唯一且属性同步 |
| 出图 | `export` | 完成 | 按扩展名导出 png/svg/pdf；`--sheet` 自动按图幅取窗口，PNG/PDF 均实测有产物（含 5% 余量、不裁切） |
| 图层标准 | `layers` | 完成 | 9 个标准层开图即建：轴线红 CENTER 0.15、墙白 0.35、门窗青 0.18、标注绿 0.15、图框 0.70；层被改坏后下次绘制自动纠回，回读 DXF 层表（62/6/370）校验，不符即报错；`--fix` 可批量矫正老图 |
| MCP 工具服务 | `aa_mcp.py` | 完成 | stdio JSON-RPC 的 MCP 服务器，20 个工具与 CLI 一一对应；返回回读校验结果，失败 `isError=true` 且零残留 |

实测环境：CADCraft 0.20.1（`cadcraft-cli`），Windows。测试全部通过：

```bash
python tests/run_all.py     # ALL PASS (18 tests)
python tools/demo.py        # 生成 samples/demo_floorplan.dxf + .png
python tools/mcp_demo.py    # 纯 MCP 客户端身份画一张图，生成 samples/mcp_demo.dxf + .png
```

验收图：

- `samples/verify_join.dxf/.png` —— 四墙闭环 6000×4000 + 门 + 窗，一次验收"四角闭合 + 门窗真开口"。
- `samples/demo_opening.dxf/.png` —— 单墙 6000×240 上开一门一窗，看洞口两侧墙线的断开区间。
- `samples/test_corner_ring.dxf` —— 四角合角的断言基线（每个角外侧线都到 ±120 外墙面）。
- `samples/test_modify.dxf/.png`（导出为 `demo_modify.png`）—— 同一堵墙从 240 改 360 厚、门从 900@2000 挪到 1200@3000 之后的样子。
- `samples/demo_auto_room.dxf/.png` —— 6000×4000 外墙 + 240 隔墙，`room --auto` 自动搜出两间 2760×3760（各 10377600 mm²）并落 `R001` / `R002`。
- `samples/mcp_demo.dxf/.png` —— 纯 MCP 客户端身份从零画的成品（轴网 A/B/C + 1/2、5 堵墙、2 门 1 窗、自动 2 间房），验证 Agent 直连链路。
- `samples/zoom_layers.png` —— 图层配色实测：轴号/轴线红（轴线点划线）、墙白、门窗青、尺寸绿、房间名白；局部放大看得到点划线的"点"。`samples/demo_sheet.png` 是同一套颜色出在 A3 图框里。

## 它和天正侧插件的区别

本插件**不依赖任何私有对象**。所有构件都是 CADCraft 原生「块参照 + 不可见属性」，几何算法全部使用公开标准（线段求交、向量几何、鞋带公式）。不读取、不复刻任何第三方插件的私有实体结构。

## 用法

```bash
# 1. 新建图纸
python tools/aa_cmd.py new out.dxf

# 2a. 轴网（等距）：3 道纵轴 @3600，2 道横轴 @4800
python tools/aa_cmd.py axis out.dxf AX001 --xcount 3 --xspace 3600 --ycount 2 --yspace 4800

# 2b. 轴网（自动）：墙都画完后按墙反推轴线，编号自动排（tol 合同轴，ext 端外伸）
python tools/aa_cmd.py axis-auto out.dxf AX001 --tol 50 --ext 2400

# 3. 墙：起点 -> 终点，墙厚 240
python tools/aa_cmd.py wall out.dxf W001 --p1 0,0 --p2 6000,0 --thick 240 --kind EXTERNAL

# 4. 门：依附 W001，洞口中心距墙起点 1000，宽 1000
python tools/aa_cmd.py opening out.dxf D001 --wall W001 --kind DOOR --width 1000 --pos 1000

# 5. 房间：按环形顺序给墙编号，自动算净面积
python tools/aa_cmd.py room out.dxf R001 --walls W001,W007,W005,W006 --name 客厅

# 5b. 房间：不给墙环，直接自动搜所有闭合房间
python tools/aa_cmd.py room out.dxf --auto              # 编号 R001、R002…，名称缺省用编号
python tools/aa_cmd.py room out.dxf --auto --prefix RM --min-area 1000000

# 6. 墙体相交自动切断（十字/T 形交叉），并重裁墙线
python tools/aa_cmd.py split out.dxf

# 7. 合并共线相接的墙段（切断的逆操作）
python tools/aa_cmd.py merge out.dxf                 # 按 AA_ROOT 自动聚合
python tools/aa_cmd.py merge out.dxf --walls W001,W003   # 显式指定

# 8. 改参数后重绘（墙线、洞口边线、邻墙裁剪一起重建）
python tools/aa_cmd.py set-wall out.dxf W001 --thick 300 --kind EXTERNAL
python tools/aa_cmd.py set-opening out.dxf D001 --pos 1500 --width 900

# 9. 尺寸标注（外墙墙段 + 洞口宽）
python tools/aa_cmd.py dim out.dxf

# 10. 出图：A3@1:100 图框 + 标题栏（不给 --at 就按图形外廓自动居中排图）
python tools/aa_cmd.py sheet out.dxf S001 --size A3 --scale 100 \
    --project "某工程" --drawing "一层平面图" --no "建-01" --date 2026-11-20 --design 严

# 11. 改标题栏内容（图幅/位置/比例不变，重画并同步属性）
python tools/aa_cmd.py set-sheet out.dxf S001 --drawing "二层平面图" --no "建-02"

# 12. 出图导出：按图幅范围裁切，扩展名决定 png/svg/pdf
python tools/aa_cmd.py export out.dxf --out out.pdf --sheet S001

# 13. 回读全部构件
python tools/aa_cmd.py show out.dxf
```

每条命令输出一行 JSON。校验不通过时输出 `{"ok": false, "error": "..."}` 并以非零码退出，**不留下任何半成品实体**。

## 门窗开洞规则（`opening`）

- 洞口区间 = `[pos - 宽/2, pos + 宽/2]`，在所属墙中心线上截取，向两侧半墙厚展开。
- **墙身真实开洞**：洞口区间内墙的两条侧线断开，只在洞口端部留一道垂直于墙的垛线；墙中心线不落图（只作语义线）。
- 开洞由墙块承担，门窗符号是另一个独立块：门画门扇+开启弧（合页在墙面，门扇从墙面起画，不穿墙身）；窗画**四线窗**——贴墙面两条（窗框外沿，±t/2）＋ 内侧两条（墙面内退窗框厚 `AA_FRAME`，默认 60，即 ±(t/2-60)），两端各一道垛线，符合 GB/T 50104 门窗图例的"四条平行细实线"。改洞口会重建所属墙块，不用双写几何。
- 拒绝条件（图纸零改动）：墙不存在、宽度 ≤ 0、洞口越出墙段、同墙洞口重叠。
- 墙被 `split` 切开或 `merge` 并回后，洞口缺口自动跟随重算，不会丢洞。

## 图层

每个构件按用途分图层落图，互不混线：

| 用途 | 默认层名 | 颜色 | 线型 | 线宽 | 内容 |
|---|---|---|---|---|---|
| 轴线 | `AA-AXIS` | 红 1 | `CENTER` 点划线 | 0.15 | 轴线直线（**单独一层，与墙体完全分离**） |
| 轴号 | `AA-AXISTEXT` | 红 1 | 实线 | 0.15 | A/B/C、1/2/3 |
| 墙体 | `AA-WALL` | 白 7 | 实线 | **0.35（粗线 b）** | 两侧墙面线 |
| 门窗 | `AA-OPENING` | 青 4 | 实线 | 0.18 | 洞口边线、门扇线、弧、窗平行线 |
| 房间 | `AA-ROOM` | 白 7 | 实线 | 0.18 | 房间名称文字 |
| 尺寸 | `AA-DIM` | 绿 3 | 实线 | 0.15 | 两道尺寸线、箭头、数字 |
| 图框 | `AA-SHEET` | 白 7 | 实线 | **0.70（图框粗线）** | 图幅外框、内框 |
| 标题栏 | `AA-TITLE` | 白 7 | 实线 | 0.25 | 标题栏九格与文字 |
| 表格 | `AA-TABLE` | 白 7 | 实线 | 0.18 | 房间表、门窗表 |

**层是自动建的，不用你手调**：`new` 一开图就把上表 9 层按颜色/线型/线宽建好；任何后续命令画之前都会再校验一遍，缺层补建、颜色线型线宽被改坏就**自动改回来**，改不回来直接报错（不静默放过）。`layers out.dxf --fix` 可对老图纸一次性补规格。取色截至 GB/T 50001 线宽组 b=0.35/0.5/0.7 与天正默认配色（轴线红、标注绿、门窗青）。

**图层名由你定**：把 `aa_layers.example.json` 复制成项目根的 `aa_layers.json`，值可以是层名字符串，也可以是对象覆盖颜色/线型/线宽：

```json
{
  "axis":  {"name": "AXIS", "color": "红", "linetype": "CENTER", "lineweight": 0.25},
  "wall":  "WALL"
}
```

也可用环境变量 `AA_LAYERS_FILE` 指向别处的配置。键固定为 `axis / axistext / wall / opening / room / dim / sheet / title / table`。块内几何也落在你指定的层上（`tests/test_layers.py`、`tests/test_layer_style.py` 断言了这一点）。

## 图面规则（避免"看起来像没做完"）

- 墙块里**只画两侧墙面线**，不画中心线——中心线只是语义线，画出来会在门洞处留下一条穿洞的直线。
- **不画房间轮廓线**：房间轮廓与墙面完全重合，画出来会被误读成墙线，还会横穿门窗洞口。房间只落名称文字，面积/周长/墙环都记在属性里。
- **相交裁剪**：侧线落在邻墙实心矩形内的部分被挖掉，交叉处不再互相穿插。
- **转角合角**：转角处外侧墙线延伸到邻墙外墙面，角部闭合，不留半墙厚见方的小缺口。
- **轴线是点划线**：轴线用专用 `aa:mkline-lt` 直接带 `CENTER` 线型组码（实测 `entmake` 认组 6），轴号不动；新建图档先 `linetype {"load":"*"}` 载入内置线型库，否则线型表里没有 `CENTER` 可渲染。这样轴线穿门洞时不会被误认成墙线。
- **轴号是圆圈**（GB/T 50104）：细实线圆，直径 8mm（1:100 出图 => 800 单位），圆与轴线端**相切**，编号写在圈内居中、字高 3mm（=> 300 单位）。轴号落在 `AA-AXISTEXT` 层。
- **窗框厚是构造尺寸，可逐樘改**：默认 60（240 墙即 ±60，370 墙为 ±125），`--frame` 可覆盖（40 => 内侧 ±80），**不随墙厚等比缩放**。
- **门窗编号可放室内或室外**：编号按尺寸自动生成（`M0921` / `C1215` / 门连窗 `MC…`，类型 + 宽高各两位分米），`--no` 可覆盖；`--label-side in|out|auto` 决定编号落在室内侧还是室外侧（默认 `in`，`auto` 沿用旧的"-Y 侧"行为），离墙面 250、沿墙居中、字高 180，墙块转 180° 时补 180° 旋转避免倒字。房间建好（或后建）会自动重画到正确一侧——室内外要靠房间轮廓才判得出来。
- **尺寸两道、只标外墙**：洞口宽在内层（离墙面 900）、墙段长度在外层（离墙面 2000），字高 250 / 箭头 150；内墙两侧都是房间，标注会压在房间名和门扇上，所以自动跳过（`--all-walls` 可强制全标）。轴号圈在墙外 2400 起，不与尺寸线叠。
- 画完一堵墙会立即规整"它 + 它碰到的邻墙"（`normalize_around`），保证新墙与旧墙的裁剪/合角一致。

## 房间自动搜环规则（`room --auto`）

- **半边面遍历**（half-edge face traversal）：把墙中线建成平面图，每条半边只属于一条面的边界，沿"顶点处逆时针紧前一格"走一圈就是一个面。有界面（逆时针、面积为正）即房间，外轮廓与退化面丢掉；复杂度线性，不枚举回路。
- **T 接/十字交叉自动打断，但不改图纸**：隔墙端点落在长墙中段、或两墙非共线相交时，只在搜索时把长墙切成子段，成环后把连续的同墙子段并回一个墙号。所以**不用先跑 `split`**，图纸也不会被改动。
- 房间边界允许落在某堵墙的中段——净面积按每条边界边的实际半墙厚内偏移求交得到。
- 自动编号 `R%03d`（避开已占用号），`AA_NAME` 缺省用编号；`--prefix`、`--min-area` 可调。
- **幂等**：以"墙编号集合"判重，同一墙环已有房间就跳过（输出里的 `skipped`），重复执行不会生成重复房间。
- 不闭合的缺口、房间内不接墙的悬挂墙都不会虚报房间。

## 房间改名规则（`set-room`）

- 房间名称是块里的那句 TEXT，属性改不动文字，所以改名走**整体重建**：读 `AA_PTS` → 校验 → 备份 `.bak` → 删旧块 → 按原轮廓/面积/墙环以新名称重建 → 回读断言名称已变且面积未变（1e-2）→ 删备份。
- 同名直接返回 `changed:0`，不写盘（幂等）；未知房间报出"现有房间：…"清单，图纸字节不变。
- `--name ""` 表示清空名称。
- 旧版图纸没有 `AA_PTS` 会明确拒绝，提示用 `room` / `room --auto` 重建。

## 房间汇总规则（`rooms`）

- 一行一个房间：编号 / 名称 / 净面积(mm²) / 净面积(m²) / 周长(mm) / 围合墙，末行合计（`合计,N 间,总面积,总面积m²`）。
- CSV 用 `utf-8-sig`（BOM 只写一份，Excel 双击不乱码）；`--csv` 给路径即导出。
- `--table x,y` 会在图上插一张**真表格**（`table` 命令，不是 `eattext`）：4 列「编号/名称/净面积(m²)/周长(mm)」+ 中文标题 + 合计行。
- 表格尺寸是硬约束实测出来的：先 `tablestyle` 建 `AA-TABLE`（`textHeight:180`、`margin:50`、切为当前样式），否则默认字高极小、整张表在图里只是一条短线；行高 340。
- **分列宽度按出图习惯**：`table` 的 `colWidth` 只收标量（传数组报 `colWidth must be positive`），所以先用 1 列（编号宽 1000）建表，再 `table.insertcol {width}` 依次加 3 列（名称 2000、面积 1800、周长 1800），`table.set` 逐格填字，最后 `table.merge` 合并标题行 + `table.cellstyle` 套 `Title` / `Header` 样式让标题、表头居中。

## 墙体相交规则（`split`）

- 交点落在某段墙**内部**时切断；端点相接（T 形衔接、转角）不切。
- 切断后首段沿用原编号，其余分段取新编号，全部带 `AA_ROOT` 记录逻辑墙号，便于按"一道墙"聚合。
- 门窗不允许跨越切点：先校验再动图；跨越时整次操作拒绝。
- 洞口跟随所在分段迁移（重建参照，偏移量按新墙起点换算）。
- 动图前自动备份 `.bak`，中途任何异常整体回滚。
- 操作幂等：已切过的图纸再跑一次，分段数不变。

切墙同时会重算墙两侧线：落在其它墙体实心范围内的墙线被裁掉，所以转角/交叉处不会出现"墙线互相穿过去"的脏线。

## 墙体合并规则（`merge`）

- 默认按 `AA_ROOT` 分组：组内能排成**共线且首尾相接**的链，就合回一整段（即撤销一次切断）；不成链的组保持原样，不报错。
- 也可 `--walls` 显式指定要合并的几堵墙（人工并段），新墙沿用链首编号。
- 合并后沿用原编号、`AA_ROOT` 归位为自身编号，门窗按投影换算回新墙起点。
- 拒绝条件（图纸零改动）：指定的墙不共线/不相接、链上墙厚不一致、洞口合并后会越界。

## 构件数据模型

CADCraft 0.20.1 没有 XData，因此每个构件是一个**独立块参照**，块定义名为 `AA_<类型>_<编号>`，属性全部不可见，只做数据载体：

| 类型 | 块名 | 关键属性 |
|---|---|---|
| 轴网（等距） | `AA_AXGRID_AX001` | `AA_TYPE` `AA_ID` `AA_XCOUNT` `AA_YCOUNT` `AA_XSPACE` `AA_YSPACE` `AA_XSTART` `AA_YSTART` `AA_VER` `AA_HOR` |
| **轴网（自动）** | `AA_AXGRID_AX001` | 同上 + `AA_MODE=AUTO` `AA_XPOS` `AA_YPOS` `AA_SKIP`（`;` 分隔的实际轴位/被跳过斜墙） |
| 墙 | `AA_WALL_W001` | `AA_TYPE` `AA_ID` `AA_THICK` `AA_KIND` `AA_MAT` `AA_AX1` `AA_AX2` `AA_LEN` `AA_ROOT` |
| 门窗 | `AA_OPENING_D001` | `AA_TYPE` `AA_ID` `AA_KIND` `AA_WIDTH` `AA_HEIGHT` `AA_SILL` `AA_WALLID` `AA_POS` `AA_FRAME` `AA_NO` |
| 房间 | `AA_ROOM_R001` | `AA_TYPE` `AA_ID` `AA_NAME` `AA_AREA` `AA_PERIMETER` `AA_WALLS` `AA_PTS` |

`AA_PTS` 是房间净空轮廓点串（`"x,y;x,y;..."`，2 位小数），也是房间改名的依据：改名字不改属性也能变，因为名称是块内那句 TEXT，属性改不动文字。

墙体块内几何（局部坐标：起点为原点，沿 +X）：中心线 LWPOLYLINE + 两侧墙线；块参照插在墙起点、按墙方向旋转，缩放恒为 1。门窗块用与所属墙相同的插入点与旋转角，所以必然贴墙。

完整规则见 [docs/构件数据存储规格.md](docs/构件数据存储规格.md)。

## MCP 工具（Agent 直连）

Agent 不必拼命令行：`tools/aa_mcp.py` 是一个标准 **stdio MCP 服务器**（newline-delimited JSON-RPC 2.0，无第三方依赖），工具与 CLI 一一对应。

| 工具 | 作用 |
|---|---|
| `aa_new` / `aa_show` | 新建公制图纸 / 回读全部构件 |
| `aa_axis` | 轴网（纵轴 + 横轴 + 轴号） |
| `aa_axis_auto` | **轴网自动**：按现有墙段反推轴线位置并自动编号 |
| `aa_layers` | 查看/校正标准图层的颜色、线型、线宽（`fix=true` 自动纠正） |
| `aa_wall` | 画墙，画完自动规整邻墙裁剪与合角 |
| `aa_opening` | 墙体真实开洞 + 门窗符号 + 自动编号（`frame` 窗框厚、`no` 编号可覆盖）|
| `aa_room` / `aa_room_auto` | 显式墙环建房间 / 自动搜环建房间 |
| `aa_split` / `aa_merge` | 墙体相交切断 / 共线合并（互为逆操作） |
| `aa_set_wall` / `aa_set_opening` | 改参数后整体重建（失败回滚、幂等） |
| `aa_set_room` / `aa_rooms` | 房间改名（重画名称文字）/ 汇总出 CSV 与图上表格 |
| `aa_openings` | 门窗表：同编号合并计数，CSV 或图上 6 列表格 |
| `aa_dim` | 尺寸标注：外墙墙段 + 洞口宽，两道尺寸线，幂等 |

客户端配置直接抄 `mcp.example.json`。启动方式：

```bash
python tools/aa_mcp.py --serve      # 客户端以子进程拉起，走 stdin/stdout
python tools/aa_mcp.py --selftest   # 只看工具表，确认版本与工具数
```

工具返回的永远是**回读校验后的结构化结果**（`geom_handles`、`area`、`normalized` 等），不是"命令已发送"。校验失败时 MCP 层返回 `isError: true` 且 `content` 里带 `{"ok": false, "error": "..."}`，图纸零残留——这一点由 `tests/test_mcp.py` 断言（含真子进程 stdio 握手）。

## 目录

```
cadcraft-arch/
├── docs/     规格（业务规则 + 实现补遗）
├── lisp/     几何引擎：aa_core / aa_axis / aa_wall / aa_opening / aa_room
├── tools/    CLI 驱动：aa_lib.py（会话与校验）、aa_cmd.py（命令行）、aa_mcp.py（MCP 服务）、demo.py
├── tests/    按功能验收：axis / wall / opening / room / room_auto / room_modify / openings / dim / label / mcp / corner / layers / split / merge / modify
└── samples/  验收输出（dxf/png）
```

## 实测踩到的平台约束（重要）

这些是写代码时绕不开的坑，已写进 docs 的实现补遗，避免后续重蹈：

1. **LISP 建不了属性**：`entmake` 对 `ATTRIB` / `SEQEND` 返回 nil，块参照的属性必须由原生 `insert {attribs}` 落盘。
2. **LISP 读不了属性**：`ssget` 过滤 `ATTRIB` 返回 nil，`entnext` 不穿透属性子实体；回读必须用原生 `entities` / `eattext`。
3. **`entlast` 不可靠**：同一段 LISP 里连续 `entmake`，`entlast` 始终返回同一个实体。句柄改用"操作前后快照差分"取得。
4. **`insert.rotation` 入参是度、回读是弧度**，两者不可混用。
5. **XData 不可用**：`regapp` / `entmakex` / `setxdata` / `getxdata` 全部无函数定义。

## 下一步（v0.5 规划）

- 门窗洞口标注（`dim` 系列命令已探明可无头调用）与轴号自动挂接墙体 `AA_AX1/AX2`
- 表格样式增强：分列不同宽度（引擎 `colWidth` 仅收标量，待试 `table.cellstyle` / `table.insertcol{width}` 绕过）

## 合规声明

本项目为独立自研，仅实现建筑绘图领域的通用业务行为。所有数据模型、几何算法均为自行设计，采用公开标准算法；不读取、分析、复刻、引用任何第三方 CAD 插件的内部代码、私有实体结构或私有存储格式；不生成 AutoCAD ARX / BRX / C++ TRX 代码。

## 许可

MIT，见 [LICENSE](LICENSE)。
