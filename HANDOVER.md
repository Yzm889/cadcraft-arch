# cadcraft-arch 交接文档

> 交接日期：2026-11-24
> 项目：`cadcraft-arch`（MIT）—— 面向 CADCraft 的自研建筑智能绘图插件
> 当前分支：`main`；远端：`git@github.com:Yzm889/cadcraft-arch.git`
> 当前状态：交接时本地领先 `origin/main` 12 个提交，本文档提交后为 13；2026-11-24 债务处理后再 +2，共 15；**未 push**；无 tag
> 适用对象：接手开发的新同事 / 新 AI 代理 / 换 CAD 平台后的迁移负责人

---

## 0. 先看这三句

1. **这是自研项目，不是天正二次开发**：只实现建筑绘图通用行为，不读取/复刻天正私有对象、ARX/BRX、菜单或模板。
2. **当前生产入口是 CLI + MCP，不是 GUI**：`tools/aa_cmd.py` 55+ 子命令，`tools/aa_mcp.py` 62 个 MCP 工具；图形界面只有本地确认面板。
3. **M-VERT（电梯/坡道/阳台）与 M-DIM（尺寸标注补齐）都已完成**：下一步建议按 `ROADMAP.md` 做 M-OPEN 高级门窗，先写测试再写实现。

---

## 1. 当前版本与完成度

| 项 | 值 |
|---|---|
| README 版本 | **v1.0.61**（M-DIM 尺寸标注补齐） |
| MCP `SERVER_INFO` 版本 | **1.0.61**（与 README 一致；`tests/test_mcp.py` 与 `tools/check_version.py` 守住） |
| 测试文件 | **59 个**（`tests/test_*.py`） |
| MCP 工具 | **62 个** = 59 原子 + 3 事务编排（batch/checkpoint/restore） |
| 标准图层 | **22 个**（新增电梯层 `AA-ELEVATOR`） |
| CADCraft | 0.20.1（`cadcraft-cli`） |
| Python | 3.11.9，仅标准库（无第三方依赖） |
| 最近提交 | `git log --oneline -8`（2026-11-24：交接债务处理 2 笔 + M-DIM 实现/文档） |
| 交付图 | `deliverables/幼儿园教学楼/00–05`（受保护，当前 `git status` 干净） |

已完成的大块：
- 单栋幼儿园教学楼 00–05 全套建施（平面/总平面/立面/剖面/详图/图框/附表/质量门禁）
- M-VERT-1 电梯、M-VERT-2 坡道、M-VERT-3 平面阳台
- 新建墙自动合角修复 + `audit.corner_gap`
- 集成样板：电梯+坡道+阳台+门窗+房间+尺寸+图框+PNG 同图协同

---

## 2. 项目定位与硬边界

### 2.1 做什么

在 CADCraft（Rust 2D CAD）之上，用 Python 驱动 LISP 子集生成建筑平面/立面/剖面/详图，并用块+属性保存构件数据；每一步都回读校验，失败零残留。

### 2.2 不做什么（硬边界）

- 不读取、反编译、复刻天正（T30）私有对象、XData、菜单、图标、模板、LISP/ARX。
- 不生成 AutoCAD ARX/BRX/C++ TRX 代码。
- 不把天正的 `EVTR` 层名、`$DORLIB2D$...` 门库块、精确坐标作为实现依赖；这些只作为行为证据。
- 不改 `deliverables/幼儿园教学楼/00–05`，除非所有权人明确批准并接受哈希变化。
- 不在未授权时 push；远端虽存在，但本地提交尚未推送。

### 2.3 许可

MIT，见 `LICENSE`。

---

## 3. 环境与运行

### 3.1 依赖

- Python 3.11+（当前 3.11.9）
- CADCraft 0.20.1，`cadcraft-cli.exe` 默认路径：
  `C:\Users\19891\AppData\Local\Programs\ArtCraft\CADCraft\cadcraft-cli.exe`
- 可用环境变量 `CADCRAFT_CLI` 覆盖 CLI 路径
- 无 pip 依赖；PNG 预览的 Pillow 可选，缺少时导出仍可用但补线宽像素断言会跳过

### 3.2 快速自检

```powershell
cd C:\Users\19891\Desktop\CADcraf\cadcraft-arch
python tools\aa_cmd.py new samples\smoke.dxf
python tools\aa_cmd.py wall samples\smoke.dxf W001 --p1 0,0 --p2 6000,0 --thick 240
python tools\aa_cmd.py show samples\smoke.dxf
python tools\aa_mcp.py --selftest     # 看工具表与数量
python tools\check_version.py        # README 现状版本 == MCP SERVER_INFO（CI 也跑）
python tools\build_integration.py     # 重生成集成样板 + audit + PNG
```

### 3.3 MCP 接入

客户端配置抄 `mcp.example.json`，以子进程方式启动：

```bash
python tools/aa_mcp.py --serve
```

工具返回的是**回读校验后的结构化结果**，不是“命令已发送”；失败返回 `isError=true` 且图纸零残留。

### 3.4 GUI / 面板

`tools/panel_server.py` 是本地 `127.0.0.1` 的确认面板，只用于“AI 画完、人确认”，不是绘图工具栏。主入口仍是 CLI/MCP。

---

## 4. 目录与关键文件

```text
cadcraft-arch/
├─ tools/
│  ├─ aa_lib.py          # 核心：Session、几何算法、全部 create_*、audit/reconcile/verify
│  ├─ aa_cmd.py          # CLI 入口（60+ 子命令）
│  ├─ aa_mcp.py          # MCP stdio 服务器（62 工具）
│  ├─ build_integration.py # 集成样板生成器（可复现）
│  ├─ panel_server.py    # 本地确认面板
│  └─ demo_*.py          # 各功能演示脚本
├─ lisp/
│  ├─ aa_core.lisp       # 基础绘图/句柄/图层变量
│  ├─ aa_wall.lisp       # 墙体块内几何
│  ├─ aa_opening.lisp    # 门窗图例
│  ├─ aa_elevator.lisp   # 电梯 10 LINE
│  ├─ aa_ramp.lisp       # 坡道 6/8 LINE + 箭头 + 注字
│  └─ aa_balcony.lisp    # 阳台 6 LINE
├─ tests/                # 59 个逐文件验收（先测试后实现的产物）
├─ docs/
│  ├─ spec-M-VERT-电梯坡道阳台.md   # M-VERT 规格（§13 C1 定稿）
│  ├─ T30-M-VERT-1-电梯实测记录.md  # T30 行为证据
│  ├─ 构件数据存储规格.md           # 块/属性/数据模型总规格
│  └─ 缺口盘点-天正T30-vs-CADCraft-v1.0.59.md  # 未跟踪，见 §9
├─ deliverables/幼儿园教学楼/       # 00–05 受保护交付图 + 生成/克隆脚本
├─ samples/integration_mvert/       # 集成样板（DXF/PNG/回读 JSON）
├─ README.md             # 功能/用法/平台约束（最重要的上手材料）
└─ ROADMAP.md            # M1/M2/M3 与 B1–B8 路线
```

`scratch_*` 是本地实验文件，`.gitignore` 已忽略，可安全删除。

---

## 5. 架构与数据模型（接手必读）

### 5.1 构件存储

- 每个构件一个块：`AA_<TYPE>_<ID>`，例如 `AA_WALL_W001`、`AA_ELEVATOR_EL001`、`AA_RAMP_RP001`、`AA_BALCONY_BA001`、`AA_OPENING_D001`、`AA_ROOM_R001`。
- 属性用 AutoCAD 风格 `ATTDEF`/`ATTRIB`，tag 以 `AA_` 开头，如 `AA_TYPE`、`AA_ID`、`AA_W`、`AA_D`、`AA_CW_SIDE`。
- 平面数据**不依赖 XData**：CADCraft 没有 `regapp/entmakex/setxdata/getxdata`。
- 标准层 22 个，集中定义在 `tools/aa_lib.py` 的 `DEFAULT_LAYERS`/`DEFAULT_LAYER_STYLES`，可被 `aa_layers.json` 覆盖。

### 5.2 生成/校验范式

典型 `create_*` 流程：

1. 全量校验（参数、墙/洞口/编号冲突）
2. 整图字节快照（或 `_drawing_bytes`）
3. LISP 生成块内几何
4. 快照差分取新句柄（`entlast` 不可靠）
5. `define_attributes` 定义属性
6. `insert_block` 建块+插入+设层（一次 CLI 事务）
7. `expect_attributes` 回读校验
8. 失败 `_restore_drawing_bytes` 原子回滚，零残留

### 5.3 墙体合角（最近修复，务必理解）

- `create_wall(..., normalize=True)` 默认画完立即 `normalize_around(session, wall_id)`，重建当前墙 + 相交/相接邻墙。
- 批量建墙传 `normalize=False`，最后调用 `normalize_all_walls(session)` 一次算全图 sides 后统一 `_apply_layout`。
- `_apply_layout` 内部重建必须 `normalize=False, bind_axis=False`，否则递归/轴号回填冲突。
- `audit.corner_gap` 统计“块侧线跨度与 `wall_sides` 期望不一致”的墙块数；0 表示按当前算法已合角。
- 回归：`tests/test_wall_auto_corner.py`、`tests/test_corner.py`、`tests/test_axis_auto.py`。

### 5.4 三个检查器的分工

| 命令 | 作用 |
|---|---|
| `audit` | 图面几何：墙端点、文字重叠、越图幅、图签重叠、图幅利用率、实现术语、`corner_gap` |
| `reconcile` | 构件自身/跨构件一致性（墙-洞-房间等），可 `--fix` |
| `verify` | 图与表一致性：轴号、门窗表、楼层表、尺寸链 |

---

## 6. M-VERT 当前实现（电梯/坡道/阳台）

### 6.1 电梯 `elevator` / `aa_elevator`

- 图层：**`AA-ELEVATOR`**（黄 2 / 实线 / 0.18）。
  - 注意：`AA-ELEV` 是**立面**层（白 7 / 0.35），不是电梯层，别混。
- 块 `AA_ELEVATOR_<ID>`：**10 LINE + 0 TEXT** = 轿厢 4 + 对角线 2 + 对重 4。
- 默认：井道 2200×2200、轿厢 1600×1400、门 1100、门高 2100；对重 `0.8×轿厢宽`、`0.13×轿厢深`。
- `gap` 是**最小允许净距**（默认 100），实际门侧净距由几何推导（默认 284），不可断言“实际=gap”。
- `AA_GAP/AA_CW_SIDE/AA_CW_W/AA_CW_D` 可回读；门洞编号 `<ID>-D`（如 `EL001-D`）。
- C1 只允许对重与门**相对**（N↔S、E↔W）；相邻侧拒绝。
- 单次插入，同 ID 拒绝，失败整图回滚。
- T30 实测只确认了**南向门**；N/E/W 是自研旋转行为，不能写成“已与天正确认”。

### 6.2 坡道 `ramp` / `aa_ramp`

- 默认 `RP001 / width 1500 / slope 12 / rail true / arrow up / label i=1:12`。
- 图元：`rail=true` **8 LINE + 1 SOLID + 1 TEXT**；`rail=false` **6 LINE + 1 SOLID + 1 TEXT**。
  - 6/8 口径含一条中心线（箭头基座），不要按“2 边+2 端+2 扶手+1 箭头=7”去改。
- 图层：`AA-STEP`（边/端/中心/扶手）、`AA-STAIR-ARROW`（箭头）、`AA-STAIR-TEXT`（注字）。
- 坡度 8–20；8–11 返回 warning 不拒绝；<8 或 >20 拒绝。
- 单次插入，同 ID 拒绝，失败回滚。

### 6.3 阳台 `balcony` / `aa_balcony`

- 默认 `BA001 / width 3000 / depth 1200 / rail 100 / label 空`。
- 图元：**6 LINE**（外沿 1 + 侧边 2 + 栏板内线 1 + 两侧回线 2），有注字时 +1 TEXT。
- 图层：线 `AA-STEP`，注字 `AA-STAIR-TEXT`。
- 校验：墙存在、区间在墙段内、不压洞口、width≥600、depth 600–2400、rail 50–300；内墙只 warning。
- 不修改墙块/洞口；单次插入，失败回滚。
- 外侧判断：用墙两侧探点是否落在房间内；无房间时默认墙左法向，真实图建议先建房间。

### 6.4 集成样板

```bash
python tools/build_integration.py
```

产物：
- `samples/integration_mvert/integration_plan.dxf`
- `samples/integration_mvert/integration_plan.png`
- `samples/integration_mvert/integration_readback.json`

当前结果：9 墙 / 3 洞口 / 1 房间 / 10 尺寸 / 3 表 / A4 图框；
`audit.count=0, errors=0, warning_count=0, corner_gap=0`，图幅利用率 35.2%。

---

## 7. 天正 T30 实测结论（证据，不是实现依赖）

详见 `docs/T30-M-VERT-1-电梯实测记录.md`；T30 版本 V2.0 Build250811 / AutoCAD 2022。

关键行为：
- 电梯命令 `TElevator`；入口 T30 面板“楼梯其他 → 电梯”。
- 对话框默认：客梯/1000kg/中分/轿厢 1600×1400/门 1100；无井道宽深输入，由两点推导。
- 提示序列：角点 → 对角点 → 开门墙线 → 平衡块侧 → 其他开门墙线<无> → 回到角点循环。
- 必须已有闭合井道墙，且角点/门墙点取**墙内表面**；命令不新建墙。
- 实测结果：+10 LINE（轿厢 4 + X 2 + 对重 4）、+1 TDbOpening（1100×2100）、+1 门库块、+1 图层 `EVTR`；无“电梯”文字；成功后循环插入。
- **只测南向门**；北/东/西、重复井道、编号冲突等仍 UNKNOWN。
- T30 的 `EVTR`、`$DORLIB2D$...`、精确坐标只作证据；CADCraft 实现用 `AA-ELEVATOR` + `AA_ELEVATOR_<ID>` + `create_opening`。

---

## 8. 测试与回归

### 8.1 测试规模

59 个文件，覆盖：轴网/墙/门窗/房间/标注/尺寸标注补齐（M-DIM）/楼梯/电梯/坡道/阳台/屋顶/总平面/详图/图框/质量门禁/MCP/事务回滚。

### 8.2 推荐跑法

```powershell
# 单文件最稳
python tests\test_elevator.py
python tests\test_wall_auto_corner.py
python tests\test_ramp.py
python tests\test_balcony.py

# 全量（逐文件，不要直接依赖 run_all 的批量删除）
Get-ChildItem tests\test_*.py | ForEach-Object { python $_.FullName; if ($LASTEXITCODE -ne 0) { "FAIL $($_.Name)" } }
```

- `tests/run_all.py` 在宿主拦截批量删除时会有**假失败**，以逐文件 exit code 为准。
- 测试会改写 `samples/test_*.dxf` 等已跟踪样例；提交前按老流程还原（`git show HEAD:file > file`，中文/含空格路径用 Python 字节写回），否则会产生大量样例噪声。
- 测试生成的 `samples/test_*.dxf` 已由 `.gitignore` 忽略（连同 `samples/_zoom_*.png`），不会误提交；已跟踪的样例被改写后仍需还原。
- 受保护交付图 00–05 的 SHA-256 见 `deliverables/幼儿园教学楼/验收报告.md`；当前工作区 `git status -- deliverables` 为空。

### 8.3 新增功能约定

1. 先写 `tests/test_<feature>.py`（期望红）。
2. 再实现 `tools/aa_lib.py` + `lisp/aa_*.lisp` + CLI + MCP。
3. `py_compile` → 单测 → 全量回归。
4. 检查无 `.bak` / `.restore.tmp`；00–05 不动。
5. 修复与 sample 分开提交；不 push。

---

## 9. 已知问题、债务与风险

| # | 问题 | 影响/建议 |
|---|---|---|
| 1 | ~~README v1.0.60，但 `aa_mcp.py` `SERVER_INFO` 仍 1.0.59~~ **已处理（2026-11-24）** | `SERVER_INFO` 已升 1.0.60；`tests/test_mcp.py` 与 `tools/check_version.py` 断言 README 现状版本 == SERVER_INFO，再漂移直接红 |
| 2 | 本地 `main` 领先 `origin/main` **15 个提交**（含 2026-11-24 的 2 笔），未 push | 所有权人已确认暂不 push；换机器/换软件前再决定 |
| 3 | `docs/缺口盘点-...md` | **已单独提交（2026-11-24）**，不再未跟踪 |
| 4 | `samples/` 下历史未跟踪测试图/截图 | **已处理（2026-11-24）**：`.gitignore` 忽略 `samples/test_*.dxf`、`samples/_zoom_*.png`；要保留新样例需 `git add -f` |
| 5 | `scratch_*` 本地实验文件 | **已处理（2026-11-24）**：仓库内 49 个已删；工作区根目录 `CADcraf\` 下的 `probe_*`/`spike*`/`scratch_*` 在仓库外，未动 |
| 6 | T30 只实测南向电梯门 | 北/东/西/重复井道/编号冲突仍 UNKNOWN，不要写成已验证 |
| 7 | `audit.corner_gap` 是“墙块侧线 vs wall_sides 期望”的不一致墙块数 | 能抓未合角，但不等于逐角几何测量；目检/测试仍需配合 |
| 8 | 默认 `create_wall(normalize=True)` 增加单墙开销 | 批量必须 `normalize=False` + `normalize_all_walls`；`_apply_layout` 内禁止递归 |
| 9 | `_apply_layout` 连续重建偶发块定义残留 | 已有 purge 兜底；若再遇 `块定义已存在`，先查 purge 流程 |
| 10 | 00–05 是在自动合角修复前生成的 | 按约定**不重生成**；若将来重生成，哈希会变，需所有权人批准 |
| 11 | 无 package/tag、无远程 push；CI 只有轻量版 | **已加 `.github/workflows/ci.yml`（2026-11-24）**：compileall + MCP selftest + 版本一致性；56 个测试依赖本机 CLI，不在云端跑；push 后才生效 |
| 12 | ~~M-DIM 未开始~~ **已完成（2026-11-24，v1.0.61）** | `dim --locate / --thickness / --coords`（MCP `aa_dim` 同名布尔参数）；选项记在 `AA_CFG_DIM`，`rescale` 按原选项重画。下一功能：M-OPEN 高级门窗 |
| 13 | **既有缺陷（M-DIM 开发中发现，未修）**：带 T 接内墙的图上 `rescale` 会失败 | `rescale_annotations` 用整墙版 `create_room` 重建房间，拼不上含 T 接内墙的环：`拒绝写入：墙环断裂，墙 W005 的端点与上一个终点不重合`。改动前（HEAD b902223）同样复现，与 M-DIM 无关；修法是改用 `create_room_edges` 按子段重建。M-DIM 的三个测试因此都另起一张没有内墙的图验 rescale |
| 14 | 中间轴线的轴号圈会压住总尺寸文字（`audit` 报 `dim_over_axis`） | 轴线外伸 1600 + 圈半径 400 = 2000，正好落在 22mm 总尺寸线（2200）的文字上；与 M-DIM 开关无关（关掉同样报，M-DIM 开发中实测）。规避：轴网 `ext` 给到 ≥ 2400，或用 `dim --opening-off/--wall-off` 把尺寸线调开 |

---

## 10. 下一步路线

### 10.1 M-DIM 尺寸标注补齐（已完成，v1.0.61）

全部是 `annotate()` 的可选参数，默认行为不变（`test_dim.py` 的 10 条断言原样通过）：

| 项 | 用法 | 口径 |
|---|---|---|
| 门窗定位 | `dim --locate` / `locate:true` | 第一道尺寸线补成完整链 墙端→洞口边→…→墙端，合计 = 墙长；洞口宽沿用原洞口尺寸不重复画 |
| 墙厚 | `dim --thickness` / `thickness:true` | 每道墙在墙端外延处一道；墙端是 T 接/共线延续/落点进房间则换端，都不行跳过并报 `thickness_skipped` |
| 坐标 | `dim --coords` / `coords:true` | 外廓各墙角（墙中心线交点）两行 `X=`（北，图面 y）/`Y=`（东，图面 x），单位 m |
| 洞口尺寸 | （已含在上面） | 即第一道链里的洞口宽，不另注“宽×高” |

`verify` 把墙厚尺寸识别出来不进尺寸链分组（`stats.thickness_dims`）。原始设想清单（按对施工图规范性收益排序）：


1. 墙厚标注 —— `thickness`
2. 门窗定位（沿墙定位尺寸）—— `locate`
3. 洞口尺寸 —— 第一道链里的洞口宽（`annotate` 原有）
4. 坐标标注 —— `coords`

要求：先写 `tests/test_dim_*`，再实现 CLI/MCP；沿用 `AA-DIM` 图层、`annotate` 现有两道尺寸体系；不得破坏 `test_dim.py` 现有 10 条标注断言。

### 10.2 之后

- M-OPEN 高级门窗（带形窗/转角窗/组合门窗）
- 设计说明页 / 会签栏 / 多页 PDF
- 最后才考虑 GUI、构件库、三维

详见 `ROADMAP.md`。

---

## 11. 如果“换软件”指换 CAD 平台

当前实现与 CADCraft 的耦合点主要在：
1. `Session._exec` 调 `cadcraft-cli`；
2. LISP 子集由 CADCraft 解释器执行；
3. 块/属性读写用 CADCraft 的 `block/insert/attdef/entities` 命令；
4. 导出用 CADCraft 的 `run --export`。

可迁移资产（平台无关）：
- `docs/spec-M-VERT-电梯坡道阳台.md`、`docs/构件数据存储规格.md`
- 几何算法（墙合角、洞口裁剪、楼梯/坡道/阳台图元、尺寸排布）
- 块+属性数据模型（任何支持块/属性的 CAD 都能承载）
- 测试用例与验收口径
- 天正行为证据（只作行为参考）

需要重写的适配层：
- `Session._exec` / `find_cli` / 导出
- LISP 小函数 → 目标平台 API（AutoCAD .NET/ARX、BricsCAD、中望、浩辰等）
- 图层/线型/图框/字高按目标平台重接

如果换的是 **AI 编程环境** 而不是 CAD：仓库自包含，Python 3.11 + CADCraft CLI 即可；把本文件、README、spec、T30 记录一起带走即可。

---

## 12. 交接检查清单

- [ ] 读 `README.md`（功能/用法/平台约束）
- [ ] 读 `docs/spec-M-VERT-电梯坡道阳台.md` §13（C1 定稿）
- [ ] 读 `docs/构件数据存储规格.md`（块/属性/数据模型）
- [ ] 读 `docs/T30-M-VERT-1-电梯实测记录.md`（哪些是实测、哪些是自研）
- [ ] 跑 `python tests/test_wall_auto_corner.py` 和 `python tools/build_integration.py`
- [ ] 确认集成样板 `audit.count=0 / errors=0 / warning_count=0 / corner_gap=0`
- [ ] 确认 `git status --short -- deliverables` 为空
- [ ] 确认无 `.bak` / `.restore.tmp`
- [ ] 决定是否 push 本地 12 个提交（默认不 push）
- [x] 若要继续开发：M-DIM 已完成，下一个功能按 ROADMAP 做 M-OPEN 高级门窗

---

## 13. 关键命令速查

```powershell
# 新建 + 墙 + 门窗 + 房间
python tools\aa_cmd.py new out.dxf
python tools\aa_cmd.py wall out.dxf W001 --p1 0,0 --p2 6000,0 --thick 240 --kind EXTERNAL
python tools\aa_cmd.py opening out.dxf D001 --wall W001 --kind DOOR --width 1000 --pos 1000
python tools\aa_cmd.py room out.dxf R001 --walls W001,W002,W003,W004 --name 门厅

# M-VERT
python tools\aa_cmd.py elevator out.dxf EL001 --at 9600,1700 --door-side S --cw-side N --shaft-walls WN,WE,WS,WW
python tools\aa_cmd.py ramp out.dxf RP001 --p1 -4200,3000 --p2 -120,3000 --slope 12
python tools\aa_cmd.py balcony out.dxf BA001 --wall W001 --pos 9000 --width 3000 --depth 1200

# 检查/出图
python tools\aa_cmd.py dim out.dxf
python tools\aa_cmd.py dim out.dxf --locate --thickness --coords   # M-DIM：定位链 / 墙厚 / 墙角坐标
python tools\aa_cmd.py sheet out.dxf SH001 --size A3 --project 示例
python tools\aa_cmd.py audit out.dxf
python tools\aa_cmd.py export out.dxf out.png --sheet SH001

# 集成样板
python tools\build_integration.py

# MCP
python tools\aa_mcp.py --selftest
python tools\aa_mcp.py --serve
```

---

## 14. 所有权与联系

- 仓库所有者：`Yzm889`（GitHub），本地工作目录 `C:\Users\19891\Desktop\CADcraf\cadcraft-arch`
- 远端：`git@github.com:Yzm889/cadcraft-arch.git`
- 当前无 CI、无 tag、无 release；所有验收以本地逐文件测试与交付图哈希为准。

> 接手第一原则：**先读规格和测试，再改实现；先测试后代码；00–05 不碰；不 push。**
