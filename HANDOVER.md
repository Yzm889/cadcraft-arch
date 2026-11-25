# cadcraft-arch 交接文档

> 交接日期：2026-11-25（按 v1.0.64 状态修订；2026-11-25 增补自动合角句柄补丁与 M-OPEN 转角窗；首版为同日早间的 v1.0.60 交接）
> 项目：`cadcraft-arch`（MIT）—— 面向 CADCraft 的自研建筑智能绘图插件
> 当前分支：`main`；远端：`git@github.com:Yzm889/cadcraft-arch.git`
> 当前状态：v1.0.64 本地已提交 `55d2c45`；tags `v1.0.62`、`v1.0.63` 已推送，`v1.0.64` 待推送；工作区除本轮改动外已还原测试样例；62 个测试文件；新增转角窗与相邻 combo/mcp 用例已过，全量回归受本机内存限制未跑完（见 §1.4）。
> 适用对象：接手开发的新同事 / 新 AI 代理 / 换 CAD 平台后的迁移负责人

---

## 0. 先看这三句

1. **这是自研项目，不是天正二次开发**：只实现建筑绘图通用行为，不读取/复刻天正私有对象、ARX/BRX、菜单或模板。
2. **当前生产入口是 CLI + MCP，不是 GUI**：`tools/aa_cmd.py` 60+ 子命令，`tools/aa_mcp.py` 62 个 MCP 工具；图形界面只有本地确认面板。
3. **工作节奏已经定型**：先写 `tests/test_*.py`（红）→ 实现 `aa_lib` + `lisp` + CLI + MCP（绿）→ 全量回归 → commit → push → 打 tag。2026-11-24 一天里按这个节奏落了四笔（见 §1.5）。

---

## 1. 当前版本与完成度

| 项 | 值 |
|---|---|
| README 版本 | **v1.0.64**（M-OPEN 转角窗 + 组合门窗/带形窗 + rescale 房间重建修复 + M-DIM + M-VERT） |
| MCP `SERVER_INFO` 版本 | **1.0.64**（与 README 一致；`tests/test_mcp.py` 与 `tools/check_version.py` 双闸，漂移直接红） |
| 测试文件 | **62 个**（`tests/test_*.py`），全量约 12 分钟 |
| MCP 工具 | **63 个** = 60 原子 + 3 事务编排（batch/checkpoint/restore） |
| 标准图层 | **22 个**（含电梯层 `AA-ELEVATOR`） |
| CADCraft | 0.20.1（`cadcraft-cli`） |
| Python | 3.11.9，仅标准库（无第三方依赖；Pillow 可选） |
| tags | `v1.0.62`、`v1.0.63`（已推送）；`v1.0.64` 待推送 |
| 最近提交 | `55d2c45` feat: M-OPEN corner window (v1.0.64)；上一笔文档 `ed0ac3e` |
| 交付图 | `deliverables/幼儿园教学楼/00–05`（受保护，`git status -- deliverables` 为空） |

### 1.1 已完成的大块

- 单栋幼儿园教学楼 00–05 全套建施（平面/总平面/立面/剖面/详图/图框/附表/质量门禁）
- M-VERT：电梯、坡道、平面阳台（v1.0.60）
- M-DIM 尺寸标注补齐：门窗定位链 / 墙厚 / 墙角坐标（v1.0.61）
- rescale 房间重建修复：带 T 接内墙的图改比例不再失败（v1.0.62）
- M-OPEN 组合门窗 / 带形窗（v1.0.63）；转角窗（v1.0.64）
- 集成样板：电梯+坡道+阳台+门窗+房间+尺寸+图框+PNG 同图协同

### 1.2 本轮变更记录（2026-11-24，四笔提交）

| 提交 | 内容 |
|---|---|
| `b902223` | chore: 交接债务 #1/#3/#4/#5/#11——SERVER_INFO 对齐 1.0.60、缺口盘点文档入库、`.gitignore` 忽略测试产物、删仓库内 49 个 `scratch_*`、轻量 CI |
| `a476ef2` | feat: M-DIM 尺寸标注补齐（v1.0.61，见 §10.1） |
| `8e2377c` | fix: rescale 房间重建改走搜环子段边界（v1.0.62，见 §10.2） |
| `6566560` | feat: M-OPEN 组合门窗/带形窗（v1.0.63，见 §10.3） |

### 1.3 2026-11-25 增补（自动合角句柄）

| 提交 | 内容 |
|---|---|
| `f52f3b4` | fix: refresh wall geom handles after auto corner |

- `create_wall(normalize=True)` 自动合角会重建当前墙块，旧图元句柄失效；现在重建后用 `block_geometry` 重新解析并回填 `geom_handles`。
- `block_geometry` 的每个图元多返回 `handle` 字段；不改变原有几何字段，兼容旧调用。
- `tests/test_wall_auto_corner.py` 增加断言：当前墙返回的 `geom_handles` 必须等于重建后块内句柄。
- README 的测试数从 56 修正为 **61**（当时实际 `tests/test_*.py` 数量；v1.0.64 已变为 62）。
- 验证：`test_wall_auto_corner`、`test_corner`、`test_axis_auto`、`test_elevator`、`test_wall`、`test_opening`、`test_dim`、`test_audit`、`test_quality_audit`、`test_mcp`、`test_balcony`、`test_ramp`、`test_floor_clone` 均通过；集成样板回读 `audit.count=0 / errors=0 / warning_count=0 / corner_gap=0`。
- **全量回归 61/61 PASS**：2026-11-25 重启后，先跑完 31 个；剩余 30 个按“不同 `test_*.dxf`”分 10 组、每组 3 项并行，30/30 PASS；合计 61/61。并行只用于不同样例文件的测试，不重复跑同一全量批次。

### 1.4 2026-11-25 增补（M-OPEN 转角窗，v1.0.64）

- 新增库函数 `create_corner_window`：两堵垂直外墙共用端点，两侧各一樘纯窗 COMBO 洞口，共享编号，写 `AA_CORNER`；角点落 `AA_CORNER_<id>` 四线转角柱。
- CLI `corner-opening`、MCP `aa_corner_opening` 同参入口；任一侧失败整图字节回滚。
- 新增 `tests/test_open_corner.py`（正常/七类拒绝/回滚/CLI/MCP）；新增 `docs/spec-M-OPEN-转角窗.md`。
- 已知边界：门窗表按两侧边窗分别计数、立面/剖面未做整体展开、转角柱未做 L 形包角。详见 spec §5。
- 回归：`test_open_corner`、`test_open_combo`、`test_mcp` 通过；全量 `tests/run_all.py` 在 `test_dim_locate` 处因本机 `cadcraft-cli` 内存分配失败中断（`3221226505`），不是断言失败；`test_dim_locate` 单独重跑仍在 `create_opening` 处同因中断。待内存恢复后按 2–3 项一组分批补跑 62 个。


---

## 2. 项目定位与硬边界

### 2.1 做什么

在 CADCraft（Rust 2D CAD）之上，用 Python 驱动 LISP 子集生成建筑平面/立面/剖面/详图，并用块+属性保存构件数据；每一步都回读校验，失败零残留。

### 2.2 不做什么（硬边界）

- 不读取、反编译、复刻天正（T30）私有对象、XData、菜单、图标、模板、LISP/ARX。
- 不生成 AutoCAD ARX/BRX/C++ TRX 代码。
- 不把天正的 `EVTR` 层名、`$DORLIB2D$...` 门库块、精确坐标作为实现依赖；这些只作为行为证据。
- 不改 `deliverables/幼儿园教学楼/00–05`，除非所有权人明确批准并接受哈希变化。
- **push 与打 tag 需所有权人授权**；2026-11-24 起所有权人已明确"完成即 push + 打 tag"的节奏，沿用即可，但换远端/强推等非常规操作仍要先问。

### 2.3 许可

MIT，见 `LICENSE`。

---

## 3. 环境与运行

### 3.1 依赖

- Python 3.11+（当前 3.11.9）
- CADCraft 0.20.1，`cadcraft-cli.exe` 默认路径：
  `C:\Users\19891\AppData\Local\Programs\ArtCraft\CADCraft\cadcraft-cli.exe`
- 可用环境变量 `CADCRAFT_CLI` 覆盖 CLI 路径（CI 上就是靠指向不存在路径来跑"无 CLI 三件套"的）
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

### 3.3 CI

`.github/workflows/ci.yml`（轻量）：compileall + MCP selftest + 版本一致性三步，push 即生效。
56+ 个真实测试依赖本机 `cadcraft-cli.exe`，**托管 runner 上跑不了**，全量回归始终在本地逐文件跑（见 §8.2）。

### 3.4 MCP 接入

客户端配置抄 `mcp.example.json`，以子进程方式启动：

```bash
python tools/aa_mcp.py --serve
```

工具返回的是**回读校验后的结构化结果**，不是"命令已发送"；失败返回 `isError=true` 且图纸零残留。

### 3.5 GUI / 面板

`tools/panel_server.py` 是本地 `127.0.0.1` 的确认面板，只用于"AI 画完、人确认"，不是绘图工具栏。主入口仍是 CLI/MCP。

---

## 4. 目录与关键文件

```text
cadcraft-arch/
├─ .github/workflows/ci.yml  # 轻量 CI（compileall + selftest + 版本一致性）
├─ tools/
│  ├─ aa_lib.py          # 核心：Session、几何算法、全部 create_*、audit/reconcile/verify
│  ├─ aa_cmd.py          # CLI 入口（60+ 子命令）
│  ├─ aa_mcp.py          # MCP stdio 服务器（62 工具）
│  ├─ check_version.py   # README 现状版本 == SERVER_INFO（CI 与 test_mcp 共用）
│  ├─ build_integration.py # 集成样板生成器（可复现）
│  ├─ panel_server.py    # 本地确认面板
│  └─ demo_*.py          # 各功能演示脚本
├─ lisp/
│  ├─ aa_core.lisp       # 基础绘图/句柄/图层变量
│  ├─ aa_wall.lisp       # 墙体块内几何
│  ├─ aa_opening.lisp    # 门窗图例（含 aa:opening-label，组合门窗共用）
│  ├─ aa_elevator.lisp   # 电梯 10 LINE
│  ├─ aa_ramp.lisp       # 坡道 6/8 LINE + 箭头 + 注字
│  └─ aa_balcony.lisp    # 阳台 6 LINE
├─ tests/                # 62 个逐文件验收（先测试后实现的产物）
├─ docs/
│  ├─ spec-M-VERT-电梯坡道阳台.md   # M-VERT 规格（§13 C1 定稿）
│  ├─ T30-M-VERT-1-电梯实测记录.md  # T30 行为证据
│  ├─ 构件数据存储规格.md           # 块/属性/数据模型总规格
│  └─ 缺口盘点-天正T30-vs-CADCraft-v1.0.59.md  # 已入库（2026-11-24）
├─ deliverables/幼儿园教学楼/       # 00–05 受保护交付图 + 生成/克隆脚本
├─ samples/integration_mvert/       # 集成样板（DXF/PNG/回读 JSON）
├─ README.md             # 功能/用法/平台约束（最重要的上手材料）
└─ ROADMAP.md            # M1/M2/M3 与 B1–B8 路线
```

注意：工作区根目录（仓库外）还有两个仓库开发用的辅助脚本 `probe_apply_blocks.py`（分块精确替换，见 §8.4）与 `probe_fix_crlf.py`（行尾规整），它们**不属于仓库**，但改这个仓库的文件时用得上。

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

### 5.3 墙体合角（务必理解）

- `create_wall(..., normalize=True)` 默认画完立即 `normalize_around(session, wall_id)`，重建当前墙 + 相交/相接邻墙。
- 批量建墙传 `normalize=False`，最后调用 `normalize_all_walls(session)` 一次算全图 sides 后统一 `_apply_layout`。
- `_apply_layout` 内部重建必须 `normalize=False, bind_axis=False`，否则递归/轴号回填冲突。
- `audit.corner_gap` 统计"块侧线跨度与 `wall_sides` 期望不一致"的墙块数；0 表示按当前算法已合角。
- 回归：`tests/test_wall_auto_corner.py`、`tests/test_corner.py`、`tests/test_axis_auto.py`。
- **数值噪声**：合角重建后墙端点带 1e-5 级漂移，反推的法向带 1e-9 级噪声——凡"按方向判正负/计数"的逻辑都要先求和再用粗阈值（0.5），别拿 1e-9 当门槛（坐标标注踩过）。

### 5.4 三个检查器的分工

| 命令 | 作用 |
|---|---|
| `audit` | 图面几何：墙端点、文字重叠、越图幅、图签重叠、图幅利用率、实现术语、`corner_gap` |
| `reconcile` | 构件自身/跨构件一致性（墙-洞-房间等），可 `--fix` |
| `verify` | 图与表一致性：轴号、门窗表、楼层表、尺寸链（墙厚尺寸不进链分组，计入 `stats.thickness_dims`） |

### 5.5 本轮新增的三个机制（2026-11-24）

- **`AA_CFG_DIM`**：`annotate(locate/thickness/coords)` 的选项全集记在这个标记块里（做法同 `AA_CFG_SCALE`），`rescale_annotations` 重画尺寸时按它原样恢复——改出图比例不会丢补出来的标注。
- **`AA_PANELS`**：组合门窗的面板序列（如 `D900;W1500;D900`）存在洞口块属性里，`opening_data` 回读为 `panels` 列表；六处内部重建（rescale/split/merge/reconcile --fix/copy-floor/set-opening）全部透传。
- **rescale 房间环重建**：重画房间按墙编号集合从 `find_room_rings` 匹配**子段边界**走 `create_room_edges`；搜不到环退回整墙版 `create_room`。房间边界可能落在墙中段（T 接内墙），整墙版拼不出这种环。

---

## 6. M-VERT 当前实现（电梯/坡道/阳台）

### 6.1 电梯 `elevator` / `aa_elevator`

- 图层：**`AA-ELEVATOR`**（黄 2 / 实线 / 0.18）。
  - 注意：`AA-ELEV` 是**立面**层（白 7 / 0.35），不是电梯层，别混。
- 块 `AA_ELEVATOR_<ID>`：**10 LINE + 0 TEXT** = 轿厢 4 + 对角线 2 + 对重 4。
- 默认：井道 2200×2200、轿厢 1600×1400、门 1100、门高 2100；对重 `0.8×轿厢宽`、`0.13×轿厢深`。
- `gap` 是**最小允许净距**（默认 100），实际门侧净距由几何推导（默认 284），不可断言"实际=gap"。
- `AA_GAP/AA_CW_SIDE/AA_CW_W/AA_CW_D` 可回读；门洞编号 `<ID>-D`（如 `EL001-D`）。
- C1 只允许对重与门**相对**（N↔S、E↔W）；相邻侧拒绝。
- 单次插入，同 ID 拒绝，失败整图回滚。
- T30 实测只确认了**南向门**；N/E/W 是自研旋转行为，不能写成"已与天正确认"。

### 6.2 坡道 `ramp` / `aa_ramp`

- 默认 `RP001 / width 1500 / slope 12 / rail true / arrow up / label i=1:12`。
- 图元：`rail=true` **8 LINE + 1 SOLID + 1 TEXT**；`rail=false` **6 LINE + 1 SOLID + 1 TEXT**。
  - 6/8 口径含一条中心线（箭头基座），不要按"2 边+2 端+2 扶手+1 箭头=7"去改。
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

产物：`samples/integration_mvert/` 下的 DXF / PNG / 回读 JSON。
当前结果：9 墙 / 3 洞口 / 1 房间 / 10 尺寸 / 3 表 / A4 图框；
`audit.count=0, errors=0, warning_count=0, corner_gap=0`，图幅利用率 35.2%。

---

## 7. 天正 T30 实测结论（证据，不是实现依赖）

详见 `docs/T30-M-VERT-1-电梯实测记录.md`；T30 版本 V2.0 Build250811 / AutoCAD 2022。

关键行为：
- 电梯命令 `TElevator`；入口 T30 面板"楼梯其他 → 电梯"。
- 对话框默认：客梯/1000kg/中分/轿厢 1600×1400/门 1100；无井道宽深输入，由两点推导。
- 提示序列：角点 → 对角点 → 开门墙线 → 平衡块侧 → 其他开门墙线<无> → 回到角点循环。
- 必须已有闭合井道墙，且角点/门墙点取**墙内表面**；命令不新建墙。
- 实测结果：+10 LINE（轿厢 4 + X 2 + 对重 4）、+1 TDbOpening（1100×2100）、+1 门库块、+1 图层 `EVTR`；无"电梯"文字；成功后循环插入。
- **只测南向门**；北/东/西、重复井道、编号冲突等仍 UNKNOWN。
- T30 的 `EVTR`、`$DORLIB2D$...`、精确坐标只作证据；CADCraft 实现用 `AA-ELEVATOR` + `AA_ELEVATOR_<ID>` + `create_opening`。

---

## 8. 测试与回归

### 8.1 测试规模

62 个文件，覆盖：轴网/墙/门窗/组合门窗/转角窗（M-OPEN）/房间/标注/尺寸标注补齐（M-DIM）/rescale 房间重建/楼梯/电梯/坡道/阳台/屋顶/总平面/详图/图框/质量门禁/MCP/事务回滚。

### 8.2 推荐跑法

```powershell
# 单文件最稳（改了什么就先跑同层）
python tests\test_opening.py
python tests\test_open_combo.py
python tests\test_dim.py
python tests\test_rescale_tjunc.py

# 全量（逐文件，约 12 分钟；放后台跑，不要直接依赖 run_all 的批量删除）
Get-ChildItem tests\test_*.py | ForEach-Object { python $_.FullName; if ($LASTEXITCODE -ne 0) { "FAIL $($_.Name)" } }
```

- `tests/run_all.py` 在宿主拦截批量删除时会有**假失败**，以逐文件 exit code 为准。
- **测试会改写已跟踪样例**（`samples/test_*.dxf`、`integration_plan.png`），跑完用 `git checkout -- samples/` 还原，否则产生大量样例噪声。
- 测试新生成的 `samples/test_*.dxf` 已被 `.gitignore` 忽略（连同 `samples/_zoom_*.png`）；要保留新样例需 `git add -f`。
- 受保护交付图 00–05 的 SHA-256 见 `deliverables/幼儿园教学楼/验收报告.md`；提交前 `git status --short -- deliverables` 必须为空。

### 8.3 新增功能约定

1. 先写 `tests/test_<feature>.py`（期望红）。
2. 再实现 `tools/aa_lib.py` + `lisp/aa_*.lisp` + CLI + MCP。
3. `py_compile` → 单测 → 同层测试 → 全量回归。
4. 升版本：README「现状」标题与 `aa_mcp.py` 的 `SERVER_INFO` **同一轮**改（`check_version.py` 守着）。
5. 检查无 `.bak` / `.restore.tmp`；00–05 不动；还原样例。
6. commit → push → 打 tag（节奏已定型）。

### 8.4 改这个仓库的文件之前（工具坑，血泪）

- 仓库 `.py`/`.md` 基本是 **CRLF 行尾**：编辑工具的多行匹配块会因 LF 不匹配而失败；个别行（含 `{""}` 的 `SERVER_INFO` 行、超长表格行）会假性失配。**用工作区根目录的 `probe_apply_blocks.py` + 分块规格**（`=====OLD/=====NEW/=====END`，每块必须恰好命中一次、整体原子写入）；锚点要延伸到行尾（脚本给旧文本补换行），行中锚点要带上后续字符；两处代码尾部相同时（CLI 的 opening / set-opening 处理器）锚点要带上各自头一行。
- 规格文件一律用编辑器的写文件功能生成，**不要用 PowerShell `Set-Content`**（会被解析坏）。
- 规整行尾**绝不写** `open(p,'wb').write(f(open(p,'rb').read()))`——Python 先以写模式打开，文件在读取前就被截空（2026-11-24 踩过，README/aa_cmd/aa_mcp 被清空后靠 `git checkout` 恢复）；用 `probe_fix_crlf.py`（先读后写 + 长度校验）。
- README 的命令示例是**正斜杠** `tools/aa_cmd.py`，HANDOVER 用反斜杠——锚点照磁盘原样抄，别凭记忆。
- LISP 改动后跑 `python tools/checkparen.py lisp/<file>` 验括号平衡。

---

## 9. 遗留债务与已知问题（未处理项）

| # | 问题 | 影响/建议 |
|---|---|---|
| 6 | T30 只实测南向电梯门 | 北/东/西/重复井道/编号冲突仍 UNKNOWN，不要写成已验证；需装 T30 的环境实测 |
| 7 | `audit.corner_gap` 是"墙块侧线 vs wall_sides 期望"的不一致墙块数 | 能抓未合角，但不等于逐角几何测量；目检/测试仍需配合 |
| 8 | 默认 `create_wall(normalize=True)` 增加单墙开销 | 批量必须 `normalize=False` + `normalize_all_walls`；`_apply_layout` 内禁止递归 |
| 9 | `_apply_layout` 连续重建偶发块定义残留 | 已有 purge 兜底；若再遇 `块定义已存在`，先查 purge 流程 |
| 10 | 00–05 是在自动合角修复前生成的 | 按约定**不重生成**；若将来重生成，哈希会变，需所有权人批准 |
| 14 | 中间轴线的轴号圈会压住总尺寸文字（`audit` 报 `dim_over_axis`） | 轴线外伸 1600 + 圈半径 400 = 2000，落在 22mm 总尺寸线（2200）的文字上，与 M-DIM 无关。**修法候选**：`annotate` 读轴网外伸量、把最外道尺寸线自动退到轴号圈外；规避：轴网 `ext` ≥ 2400，或 `dim --opening-off/--wall-off` 调开 |

已处理（2026-11-24，记录备查）：#1 版本漂移（check_version 双闸）、#3 缺口盘点入库、#4 测试产物忽略、#5 scratch 清理、#11 轻量 CI + tags、#12 M-DIM、#13 rescale 房间重建。

---

## 10. 本轮功能的口径速查

### 10.1 M-DIM 尺寸标注补齐（v1.0.61）

全部是 `annotate()` 的可选参数，默认行为不变（`test_dim.py` 的 10 条断言原样通过）：

| 项 | 用法 | 口径 |
|---|---|---|
| 门窗定位 | `dim --locate` / `locate:true` | 第一道尺寸线补成完整链 墙端→洞口边→…→墙端，合计 = 墙长；洞口宽沿用原洞口尺寸不重复画 |
| 墙厚 | `dim --thickness` / `thickness:true` | 每道墙在墙端外延处一道（尺寸线垂直于墙、离墙端 = 邻墙半厚 + 2.5mm，文字朝相邻墙那侧）；墙端是 T 接/共线延续/落点进房间则换端，都不行跳过并报 `thickness_skipped`。为什么不在墙身上跨着画：240 墙在 1:100 只有 2.4mm，字放不下会被 CAD 推进第一道尺寸文字带甚至房间（实测） |
| 坐标 | `dim --coords` / `coords:true` | 外廓各墙角（墙中心线交点）两行 `X=`（北，图面 y）/`Y=`（东，图面 x），单位 m，放在室外对角象限、最外道尺寸线外 12mm 起 |

选项记在 `AA_CFG_DIM`，`rescale` 按原选项重画；`verify` 把墙厚尺寸排除在尺寸链分组外。
回归：`tests/test_dim_locate.py`、`tests/test_dim_thickness.py`、`tests/test_dim_coords.py`。

### 10.2 rescale 房间重建修复（v1.0.62）

带 T 接内墙的图上 `rescale` 原本必报 `拒绝写入：墙环断裂`（整墙版 `create_room` 拼不上含内墙的环；集成样板这类真实图都有 T 接内墙）。修法与回归见 §5.5；`tests/test_rescale_tjunc.py`。

### 10.3 M-OPEN 组合门窗 / 带形窗（v1.0.63）

`--kind COMBO --panels "D900;W1500;D900"`：一个洞口按序拼多樘 DOOR/WINDOW 面板，面板间自动画中梃。

- 面板三种写法：紧凑串 / `[("DOOR",900),...]` / `[{"kind":"DOOR","width":900},...]`；合计必须等于洞口宽，每面板最小 300（`PANEL_MIN`）。
- 门面板铰点/开向沿用全局 `hinge/swing`，扇数按面板宽自动（≥1200 双扇）；编号按尺寸自动生成，前缀 **ZM**。
- **纯窗面板序列就是带形窗**（面板即分格、中梃即窗棂）；转角窗见 §10.4。
- 面板序列存 `AA_PANELS`；六处内部重建全部透传；立面/剖面按整体洞口画（不逐面板拆）。
- 回归：`tests/test_open_combo.py`。

### 10.4 M-OPEN 转角窗（v1.0.64）

`corner-opening <path> <id> --wall-a W001 --wall-b W002 --len-a 1800 --len-b 1500`：两堵互相垂直、共用端点的外墙，两侧各一樘纯窗，从角点向墙内延伸；共享编号，角点落 4 线转角柱。

- 库入口 `create_corner_window`；CLI `corner-opening`；MCP `aa_corner_opening`。
- 两侧洞口仍是 `AA_OPENING_<id>-A/-B`（COMBO + WINDOW 面板），写 `AA_CORNER=<id>`；`AA_POS` 从共用角点换算。
- 柱块 `AA_CORNER_<id>`：4 条 `AA-OPEN` 线，属性 `AA_WALL1/2`、`AA_OPENING_A/B`、`AA_W1/2`、`AA_POST`、`AA_NO`、`AA_FLOOR`。
- 拒绝：不共角/重合墙、不垂直、超墙长、柱宽越界、含门面板、块已存在、同墙洞口重叠；失败整图字节回滚。
- 已知边界：门窗表按两侧边窗分别计数；立面/剖面未做整体转角展开；柱未做 L 形包角。规格见 `docs/spec-M-OPEN-转角窗.md`。
- 回归：`tests/test_open_corner.py`。

---

## 11. 如果"换软件"指换 CAD 平台

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
- [ ] 读本文件 §5.5 / §8.4 / §10（本轮机制、工具坑、功能口径）
- [ ] 跑 `python tests\test_wall_auto_corner.py` 和 `python tools\build_integration.py`
- [ ] 确认集成样板 `audit.count=0 / errors=0 / warning_count=0 / corner_gap=0`
- [ ] 跑全量回归 62 个文件（约 12 分钟），确认 0 失败
- [ ] `git checkout -- samples/` 还原测试改写的样例
- [ ] 确认 `git status --short -- deliverables` 为空
- [ ] 确认无 `.bak` / `.restore.tmp`
- [ ] `python tools\check_version.py` 通过（README == SERVER_INFO）
- [ ] 下一个功能默认是 M-OPEN 转角窗的门窗表合并 / 立面整体洞口（先写测试，见 spec §5 已知边界）

---

## 13. 关键命令速查

```powershell
# 新建 + 墙 + 门窗 + 房间
python tools\aa_cmd.py new out.dxf
python tools\aa_cmd.py wall out.dxf W001 --p1 0,0 --p2 6000,0 --thick 240 --kind EXTERNAL
python tools\aa_cmd.py opening out.dxf D001 --wall W001 --kind DOOR --width 1000 --pos 1000
python tools\aa_cmd.py room out.dxf R001 --walls W001,W002,W003,W004 --name 门厅

# M-OPEN：组合门窗 / 带形窗
python tools\aa_cmd.py opening out.dxf CB01 --wall W001 --kind COMBO --width 3300 --pos 2400 --panels "D900;W1500;D900"
python tools\aa_cmd.py opening out.dxf RB01 --wall W001 --kind COMBO --width 6000 --pos 3300 --panels "W1200;W1200;W1200;W1200;W1200"

# M-VERT
python tools\aa_cmd.py elevator out.dxf EL001 --at 9600,1700 --door-side S --cw-side N --shaft-walls WN,WE,WS,WW
python tools\aa_cmd.py ramp out.dxf RP001 --p1 -4200,3000 --p2 -120,3000 --slope 12
python tools\aa_cmd.py balcony out.dxf BA001 --wall W001 --pos 9000 --width 3000 --depth 1200

# 检查/出图
python tools\aa_cmd.py dim out.dxf
python tools\aa_cmd.py dim out.dxf --locate --thickness --coords   # M-DIM：定位链 / 墙厚 / 墙角坐标
python tools\aa_cmd.py sheet out.dxf SH001 --size A3 --project 示例
python tools\aa_cmd.py audit out.dxf
python tools\aa_cmd.py verify out.dxf
python tools\aa_cmd.py export out.dxf out.png --sheet SH001

# 集成样板
python tools\build_integration.py

# MCP / 版本
python tools\aa_mcp.py --selftest
python tools\aa_mcp.py --serve
python tools\check_version.py
```

---

## 14. 所有权与联系

- 仓库所有者：`Yzm889`（GitHub），本地工作目录 `C:\Users\19891\Desktop\CADcraf\cadcraft-arch`
- 远端：`git@github.com:Yzm889/cadcraft-arch.git`；`main` 已同步（至 `6566560`）；tags `v1.0.62` / `v1.0.63`
- CI：轻量三件套（push 即跑）；全量回归始终在本地逐文件跑
- 无 release；验收以本地逐文件测试与交付图哈希为准

> 接手第一原则：**先读规格和测试，再改实现；先测试后代码；00–05 不碰；push/tag 按既定节奏，非常规操作先问。**
