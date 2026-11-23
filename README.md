# cadcraft-arch

**面向 CADCraft 的自研建筑智能绘图插件**（MIT 协议）。

让 AI 直接驱动 CADCraft 画建筑平面图：轴网、墙体、门窗、房间，全部由 AI 按指令生成，并且**每一步都经回读校验，不谎报成功**。

## 现状（v1.0.59，门窗/楼梯图例补齐）

| 功能 | 命令 | 状态 | 验收 |
|---|---|---|---|
| 新建公制图纸 | `new` | 完成 | 建图即建 22 个标准层；`--scale 100` 可开图就定出图比例 |
| **总平面** | `site` | 完成（M2，v1.0.55） | 用地红线闭合多段线（红 Continuous）+ 建筑轮廓 + 道路双线 + 出入口箭头/名称 + 简化指北针 + 红线顶点坐标（m）+ 总宽/总深尺寸；`AA_SITE_<id>` 存 `AA_PTS/AA_AREA/AA_DATA`，`read_site` 可回读；红线/道路只作示意，不替代实测；CLI `--show` 与 MCP `aa_site` 均已接通 |
| 轴网（等距） | `axis` | 完成 | 4 纵 + 3 横、14 个图元、10 项属性、DWG 往返；`--xspaces/--yspaces` 可传逐段间距序列，非等距同样支持 |
| **轴网（非等距）** | `axis --xspaces/--yspaces` | 完成（v1.0.52） | 间距参数可为标量或序列；序列长度必须等于轴数减一，按顺序写 `AA_XSPACES/AA_YSPACES`，同时回读 `AA_XPOS/AA_YPOS`；轴号/轴线/文字位置全部按实际累计间距生成，不按平均值摊平 |
| **轴网自动** | `axis-auto` | 完成 | 由墙反推轴线：竖墙 x 聚类、横墙 y 聚类（`--tol` 50mm 合同轴）、竖轴编 1/2/3、横轴编 A/B/C、轴线端外伸 2400、斜墙跳过并记 `AA_SKIP`；回读校验线数/圈数/文字/线型（全 CENTER）；**生成时顺手把每堵墙的 AX1/AX2 回填**（横墙端点→1/2/3，竖墙端点→A/B/C，斜墙留空） |
| 墙轴号回填 | `axis-bind` | 完成 | 对已有图按轴网回填墙的 AX1/AX2，只改属性不改几何（`--only-empty` 不覆盖手填值、`--tol` 可调） |
| 墙体 | `wall` | 完成 | 水平/斜墙长度与角度、厚度属性、包围盒；相交处墙线裁剪 + **转角合角**；`--snap-axis` 可把端点吸附到最近轴（**先轴后墙**），吸附量在结果里如实返回；`--floor` 写层号 `AA_FLOOR`（门窗表按它归"所在层"，缺省 1） |
| 门窗 | `opening` | 完成（v1.0.59 图例补齐） | 依附墙、越界拒绝、重叠拒绝、宽度校验；**洞口在墙身真实开洞**（侧线断开）。平面图例按 GB/T 50104：**窗**四线（贴墙面 ±t/2 + 内退窗框厚 ±(t/2−frame)）；**平开门**门扇线 + 90° 开启弧，`--leaves` 单/双扇（`0` 自动：≥1200 双扇），`--hinge ±1` 铰点端、`--swing ±1/0` 开向（`0` 按室内外自动——外门朝室外即疏散方向）；**门连窗**门扇带弧 + 固定窗四线 + 中梃，`--doorpart` 指定门扇宽。`AA_HINGE/AA_SWING/AA_LEAVES/AA_DOORPART` 可回读 |
| 台阶 / 散水 | `step` / `apron` | 完成 | 台阶：贴墙线不画、按踏步数×踏步宽出踏步线 + 两侧边线（2 步×300 演示）；散水：外沿线 + 两端收头（600 宽）；同在 `AA-STEP`（白 7、0.18）；`AA_TYPE=STEP/APRON` 可回读 |
| 剖面 | `profile` | 完成（B6-4） | 按楼层生成剖面：地坪线、**剖切面穿过的两端外墙都画成墙厚窄带**（半剖时 `--side LEFT/RIGHT` 只画一端）、每层楼板（板顶粗 / 板底细）、屋面板、女儿墙（两端窄矩形 + 压顶）、双坡屋面板 + 脊；剖到的门窗断墙 + 窗框双线 + 玻璃/门上亮子 + 窗台挑出；门窗可直接由 `read_cut_openings` 沿剖切线从平面反取；被剖到的室内隔墙按 120 墙厚画窄带、隔墙上被剖到的门窗可断墙（`--inwall x,厚[,层号,洞高,窗台高[,WINDOW|DOOR]]`）、楼板下可挂梁（`--beam 层号,x0,x1,梁高`）、楼梯断面（`--stair x0,x1,起层,踏步数`：踏步一平一竖 + 梯段板斜线）；各层楼面与屋面注标高；左侧默认注三道竖向尺寸 + 底部两道横向尺寸（净宽/总宽，落 `AA-DIM`，`--no-dims` 可关） |
| **立面** | `elevation` | 完成（B6-3） | 按楼层数据 + 门窗生成立面：地坪线（两端出头）、两侧轮廓、楼面线、直立门窗洞（天正立面做法：窗框双线 + 亮子 + 中梃分扇 + 窗台线）、平屋顶女儿墙 + 压顶 / 双坡山墙三角 / 双坡正对檐口（檐口 + 屋脊）/ 无屋顶；每层右侧注标高（±0.000 / 3.600）；`--from-wall=W001` 可直接从平面读这道墙的门窗（北面墙加 `--flip`）；`--eave=200` 檐口板厚（檐口线下加板底线 + 两端封口）、`--axis "0,1"` 立面轴号（顶部 8mm 圆 + 圈内 3mm 字，圈下短引线接轮廓顶）；门扇固定 2100，洞高 >2200 才画门上亮子线；左侧默认注三道竖向尺寸（细部/层高/总高，落 `AA-DIM`，`--no-dims` 可关）；同层洞口重叠、洞超宽、门超层高都拒绝 |
| **屋面细部** | `roof-detail` | 完成（M2，v1.0.56） | 在已有屋顶净区追加分格线（`nx×ny` 或间距）、内天沟（N/S/E/W 带 + 雨水口）、找坡箭头与 `i=x%` 注字；块 `AA_ROOFD_<id>` 存 `AA_GRID/AA_INNER_GUTTER/AA_SLOPE` 等，`read_roof_detail` 可回读规格与图元数量；CLI `--show` 与 MCP `aa_roof_detail` 已接通 |
| 屋顶 | `roof` | 完成（B6-2） | 平屋顶（檐口 + 檐沟 + 四角雨水口 + 南北找坡，可选女儿墙 `--parapet` 画压顶外沿 + 内皮、`--hatch "x,y,size"` 上人孔方框 + 对角 + 注字）/ 双坡（正脊贯到檐口）/ 四坡（正脊 + 四条 45° 斜脊）/ 单坡（低端檐沟）；檐口外挑计入平面面积，找坡箭头尖指下坡；类型/尺寸/檐沟过宽/重名都拒绝 |
| 楼层表 | `floors` | 完成（B6-1） | 各层层号/楼层标高/层高/平面图号/层名，画成 `AA_TABLE_<编号>` 表（`AA_TYPE=FLOOR_TABLE`）；标高省略时按层高自下而上累加（±0.000 / 3.600 / 7.200），层高≤0、标高低于下层顶、编号重复都拒绝；`read_floors` 可回读成结构化数据，是立面/剖面的数据源 |
| **门窗表** | `opening-table` | 完成（B7-1） | 从图上 `AA_OPENING` 自动统计，不手抄：编号+类别+洞口宽高+窗台高归并，樘数=图上真实数量，所在层取洞口所在墙的 `AA_FLOOR`（连续写 `1-3`、不连续写 `1,2`）；7 列（序号/编号/类别/洞口尺寸/窗台高/樘数/所在层），`AA_TYPE=OPENING_TABLE`，`read_opening_table` 可回读；`--note` 表下附注，`--no-scale` 标题不带比例；空图/重名拒绝。依赖 `wall --floor` 写层号，墙体重建（开洞/split/merge/set-wall）不丢层号 |
| **图纸集** | `sheet-set` | 完成（B7-2） | 登记"图号→图名→图幅→备注"，**图幅与比例从图框读**不手填；图号重复/图幅被占用/图幅不存在/空集/集编号重复都拒绝；`AA_TYPE=SHEETSET`，`read_sheet_set` 回读，是图纸目录与批量出图的数据源 |
| **自动排附表** | `place` | 完成（v1.0.58） | 把门窗表 / 房间面积表 / 指北针自动放进图面空位，不用手填坐标：先量内框、图签与已有图元外包，再按「图签上方横带 → 图形右侧竖带 → 全内框」优先级找空矩形（积分图，O(1) 单次查询）；留缝按图纸 mm 给，放不下时逐级收紧到 1.5mm；两张表**大表先落位、小表跟着同一落位区**，不会拆到图纸两头；`--replace` 先清同名附表再重排，可重复执行不堆表；`--sheet auto` 自动识别唯一图幅；返回 `placed / skipped / occupancy_before / occupancy_after`。CLI 与 MCP `aa_place` 均已接通 |
| **图纸目录** | `sheet-index` | 完成（B7-2） | 按图纸集自动生成 6 列（序号/图号/图名/图幅/比例/备注），行高 5mm、字高 3mm；`AA_TYPE=SHEET_INDEX` 可回读；表下可附注 |
| **批量出图** | `export-set` | 完成（B7-2） | 按图纸集逐张出 PNG/SVG/PDF，一张图幅一个文件，命名`图号_图名.扩展名`；每张出完校验产物 >2KB，缺一张整体报错并列已完成清单；PNG 仍按图层线宽补粗、按 ACI 上色 |
| **楼层复制** | `copy-floor` | 完成（B7-3） | 按 `AA_FLOOR` 把源层墙 + 门窗 + 房间整层复制到目标层，编号统一加前缀（`2W001`/`2M001`/`2R001`），房间面积必须与源层一致；可选 `offset` 平移便于同图核对；层相同/无墙/目标层已有墙/编号冲突/偏移非法都拒绝；楼梯柱台阶暂不带（无层号） |
| **详图符号** | `detail-mark` | 完成（B7-4） | 直径 14mm 圆 + 水平直径线，上半详图编号、下半图纸号（同图 `—`）；`AA_KIND=DETAIL_MARK`，`AA_DETAIL/AA_SHEETNO/AA_DIAM` 可回读 |

| **墙身节点** | `wall-node` | 完成（B7-4） | 1:20 的窗台节点 SILL（墙身/楼板/窗台板/窗框 + 墙厚与窗台高）与女儿墙节点 PARAPET（墙身/屋面板/压顶 + 墙厚与女儿墙高）；几何放大 5 倍、注字不放大；压顶厚/挑出记属性；AA_WN_<id> 可回读 |
| **楼梯间大样** | `stair-detail` | 完成（B7-4） | 从图上已有楼梯读参数（梯段宽/踏步数/踏步宽/梯井/平台深）放大重画，**上行方向朝上**；直跑画梯段 + 踏步线 + 箭头，注梯段宽与"步数×踏步宽=总长"；双跑再加梯井/平台带/两跑踏步，注平台深共 3 道；尺寸写真实 mm、几何放大 5 倍，`AA_SD_<id>` 可回读 |
| **卫生间大样** | `wc-detail` | 完成（B7-4） | 1:20 放大：墙带 + 坐便（400×700）/台盆（450×600）/地漏（100×100）+ 排水坡箭头 `i=%`；注开间/进深/坐便中心距三道尺寸；净宽/净深/墙厚/坡度/地漏位置可调，落 `AA_WC_<id>` 可回读 |
| **立面阳台/雨篷** | `elev-balcony` | 完成（B7-4） | 立面上画阳台挑板 + 栏板（两侧竖线 + 压顶）或雨篷挑板 + 两端牛腿；注宽与栏板高（雨篷只注宽），挑出宽记属性；`AA_EB_<id>` 可回读 |
| **基础大放脚** | `foundation` | 完成（B7-4） | 按标准 6-6 砖砌大放脚条基：240 墙 / 500 基底 / 600 垫层；墙头折断线、240 墙厚尺寸；50 砖覆盖 + 250 地圈梁（6Φ12、Φ6@250 示意）+ 防潮层 -0.300 + 45° 砖砌体剖面线 + 圈梁/垫层点骨料；±0.000/-0.300/-2.000、竖向分道与 50/500/50 分道尺寸；墙厚/级数/台阶/埋深/垫层/圈梁/外伸/墙头/3:7 灰土分层/配筋根数均可改，`AA_FD_<id>` 可回读 |
| **注字 / 引注** | `text` / `leader` | 完成（B7 收尾） | 注字给左下角锚点、内容、图面字高与旋转角，落 `AA_TXT_<id>`；引注画斜线箭头 + 文字下横段，落 `AA_LD_<id>`；两者均可 `--show` 回读，重号/空内容/非法字高拒绝 |
| 楼梯 | `stair` | 直跑/双跑完成（v1.0.59 图例补齐） | 直跑：踏步线 + 两侧边线 + 实心箭头 + 起步"上"字；双跑 U 形：外轮廓 + 平台分界 + 梯井 + 两跑踏步，进深 = 梯段长 + 平台深；**层类型 首层/中层/顶层**、**上楼位置 左/右**（整体镜像）。首层只画上行第一跑，踏步按 **45° 剖断线裁剪**（线左侧被切掉的部分不画，左右边线各自止于斜线），箭头止在剖断处；中层两跑全画 + 45° 剖断线横切上行跑 + "上/下"；顶层两跑全画、只沿第二跑标"下"、无剖断线。梯井只贯通梯段（0→梯段长），不穿平台；"上/下"写在起步踏步格内。落 `AA-STAIR`；`AA_STEPS_TOTAL`/`AA_DEPTH`/`AA_WELL`/`AA_LEVEL`/`AA_UPSIDE` 可回读；剪刀梯、弧梯、踏步取齐未做 |
| 柱 | `column` | 完成 | 矩形柱：实心 SOLID + 外框（可转角）；圆柱：圆 + 24 扇形填充；落在 `AA-COLUMN`（灰 8、0.35）；尺寸为真实尺寸、不随出图比例变；`AA_W/AA_H/AA_ANGLE/AA_AREA/AA_MATERIAL` 可回读 |
| 房间 | `room` | 完成 | 闭合墙环校验（墙方向/选择顺序不一致也能串环）、内偏移净面积（3360×4560 实测）；落两行字：房间名 2.5mm + 面积 2.0mm（天正默认注面积，`--no-area` 只注名称）；不画与墙面重合的轮廓 |
| 房间自动搜环 | `room --auto` | 完成 | 从全部墙自动枚举闭合房间（半边面遍历，线性复杂度）；T 接/十字交叉自动打断只在搜索时生效、**不改图纸**；自动编号 `R001…`、重跑幂等、不闭合缺口不虚报 |
| 房间改名 | `set-room` | 完成 | 按已存轮廓整体重建（块内名称文字真的重画）；面积/轮廓不变、同名幂等不写盘、未知房间拒绝且字节不变、失败自动回滚 |
| 房间汇总 | `rooms` | 完成 | 按编号列出净面积/周长/围合墙，导出 CSV（BOM，Excel 双击不乱码）或插入图上表格（中文标题+表头+合计行，4 列） |
| 墙体相交切断 | `split` | 完成 | 十字交叉 2→4 段、编号与逻辑根保留、门窗迁移、幂等、跨切点拒绝且零残留 |
| 墙体合并 | `merge` | 完成 | 切断可逆：4→2 段、原编号恢复、门位回 2700、幂等、非共线/墙厚不一致拒绝且零残留 |
| 改墙参数 | `set-wall` | 完成 | 改墙厚/类型/材质/轴号后整体重建：墙线、洞口边线、邻墙裁剪全部同步；拒绝零残留、幂等 |
| 改门窗参数 | `set-opening` | 完成 | 改位置/宽度/类型/窗框厚/编号后重建符号并重排所属墙缺口；越界/重叠拒绝且文件字节不变 |
| 门窗表 | `openings` | 完成 | 同编号合并计数，列洞口宽高/樘数/所在墙；CSV 与图上表格（6 列，编号窄、所在墙宽）|
| 尺寸标注（三道） | `dim` | 完成 | 洞口宽内层（9mm）、墙段/轴线中层（16mm）、总尺寸外层（22mm），轴号圈从 24mm 起不压线；总尺寸按同一条外墙线归组，矩形平面四边各一条；内墙跳过，重跑幂等、逐条回读测量值 |
| 图框 + 标题栏 | `sheet` / `set-sheet` | 完成 | GB/T 14689 图幅（A0–A4）、装订边 25、其余边 A0/A1=10 其余 5；标题栏 180×56 九格（GB/T 10609.1）；不给位置按全图外廓（墙/房间/轴号/尺寸/表格）自动居中排图；`--size AUTO` 按外廓挑最小能装下的图幅，指定图幅装不下时自动升一级并在结果里回传 `promoted`；重复编号拒绝、改标题栏后块唯一且属性同步 |
| 出图 | `export` | 完成 | 按扩展名导出 png/svg/pdf；`--sheet` 自动按图幅取窗口，PNG/PDF 均实测有产物（含 5% 余量、不裁切）；**PNG 按图层线宽自动补粗、并按图层 ACI 上色**（红轴/青门窗/绿尺寸/黄楼梯/绿箭头，预览即天正式的彩色图）（墙 0.35 / 图框 0.70 在预览里就是粗线，按 1:100 换像素，实测补粗后亮点数 3844→65316） |
| 图层标准 | `layers` | 完成 | 22 个标准层开图即建：轴线红 CENTER 0.15、墙白 0.35、门窗青 0.18、标注绿 0.15、图框 0.70、图名 0.25；层被改坏后下次绘制自动纠回，回读 DXF 层表（62/6/370）校验，不符即报错；`--fix` 可批量矫正老图 |
| 图名标注 | `title` | 完成 | 图名（5mm@1:100）+ 右侧比例（3.5mm）+ 图名下粗线（图框层 0.70）+ 比例下细线；落在 `AA-NAME`，属性存 `AA_TEXT`/`AA_SCALE` |
| 指北针 | `north` | 完成 | 细线圆（直径 24mm@出图比例）+ 等腰三角指针（尾部宽 3mm），落在 `AA-NAME`，`AA_R` 可回读 |
| 标高 | `elev` | 完成 | 等腰直角三角（高 3mm@比例）+ 向右短基线，数值 2.5mm 写在**基线之上**；`±0.000 / 3.600 / -0.450` 三位小数米制；`AA_SYM_E001` 块，`AA_VALUE`/`AA_H` 可回读 |
| 索引 | `index` | 完成 | 直径 10mm 圆 + 水平直径线，上半详图编号、下半图号（同图写 `—`）；`AA_DETAIL`/`AA_SHEETNO` 可回读 |
| 剖切 | `section` | 完成 | 位置线只画两端两段 6mm 粗线（不与图面线条相接），两端各 5mm 投射方向线，`1-1` 编号两端都写、按投射方向对齐；`direction` 收 down/up/left/right |
| **图面自检** | `audit` | 完成 | 只报不改：墙端点没接上、门窗超出墙段、房间文字重叠、**门窗编号压房间名/楼梯/编号**、尺寸压轴号圈、图形超出图幅内框；返回 `issues/count/by_kind/errors`，`--strict` 有 error 级问题时返回 1 |
| **编号自动避让** | 自动（`build_kindergarten` / 标准层复制） | 完成（v1.0.53） | 房间文字落图后检查门窗编号与房间名/楼梯/其他编号文字框；互压时按 leader→in→out 换侧，仍无解则保留并由 `audit` 报 `opening_text_overlap` |
| **全图复核** | `verify` | 完成（M1 图面复核清单，v1.0.49） | 只读跨表核对：轴号重复/轴数/墙轴号引用、门窗表樘数与图上洞口（兼容旧版 6 列门窗表）、楼层表标高/层高及立面/剖面楼层行、尺寸测量值与三道尺寸链合计；缺表/缺轴网按未做跳过，返回 `issues/count/by_kind/errors/warnings/stats` |
| **构件一致性检查** | `reconcile` | 完成（B8-1，v1.0.48 自动收尾） | 只查数据是否自洽：墙长/墙厚为 0、门窗宿主墙缺失或越出墙段/同墙重叠、房间存储面积与轮廓鞋带面积不符；`--fix` 只做无歧义修复：删零长空墙、删零宽洞口、唯一可匹配的悬空门窗重挂、放得下的越界洞口夹回墙内、重建房间面积；墙厚 0、重叠、多候选、洞口比墙长等只给 `suggestion`；整图先备份 `<stem>.reconcile.bak.dxf`，任一动作失败整图回滚；房间仍受门窗/墙体遗留错误保护（`fix_skipped`） |
| **图档出图比例** | `new --scale` / `scale` | 完成 | 先定比例再画（天正口径）：比例写进图档标记 `AA_CFG_SCALE`（只有一条不可见属性、不画几何），之后画的轴号/房间名/门窗编号/尺寸/图名/表格直接按该比例取 mm 规格；重开图档仍有效；中途 `scale --set 50` 默认把已有注记整批重画，`--no-rescale` 只改标记 |
| 标注比例联动 | `rescale` | 完成 | 换出图比例时按 mm 规格整批重画：轴号圈 8mm / 轴号字 3mm / 房间名 2.5mm / 门窗编号 1.8mm / 图名 5mm / 指北针 24mm，尺寸标注删掉按新字高箭头重画；实测 1:100→1:50 轴号字 300→150、圈半径 400→200；房间表/门窗表也按 2.5mm 字高重画。属于"已画完再改比例"的补救路径，正常流程优先用 `scale` |
| MCP 工具服务 | `aa_mcp.py` | 完成 | stdio JSON-RPC 的 MCP 服务器，56 个原子工具与 CLI 一一对应（含 `aa_site` / `aa_roof_detail` / `aa_place`），另有 3 个事务编排工具（batch / checkpoint / restore）只在 MCP 暴露，共 59 个；返回回读校验结果，失败 `isError=true` 且零残留 |

实测环境：CADCraft 0.20.1（`cadcraft-cli`），Windows。测试全部通过：

```bash
python tests/run_all.py     # 51 tests；逐项跑最稳（批量删除被宿主拦截时会有假失败）
python tests/test_site.py   # 总平面单项验收（库 / CLI / MCP / 拒绝用例）
python tests/test_roof_detail.py  # 屋面分格/天沟/坡度注字单项验收
python tests/test_quality_audit.py  # 图面质量门禁（图签压线/幅面利用率/施工说明术语）
python tools/demo.py        # 生成 samples/demo_floorplan.dxf + .png
python tools/demo_building.py  # 生成 samples/demo_building.dxf + .png（全套图 A2）
python tools/mcp_demo.py    # 纯 MCP 客户端身份画一张图，生成 samples/mcp_demo.dxf + .png
```

验收图：

- `samples/verify_join.dxf/.png` —— 四墙闭环 6000×4000 + 门 + 窗，一次验收"四角闭合 + 门窗真开口"。
- `samples/demo_opening.dxf/.png` —— 单墙 6000×240 上开一门一窗，看洞口两侧墙线的断开区间。
- `samples/test_corner_ring.dxf` —— 四角合角的断言基线（每个角外侧线都到 ±120 外墙面）。
- `samples/test_modify.dxf/.png`（导出为 `demo_modify.png`）—— 同一堵墙从 240 改 360 厚、门从 900@2000 挪到 1200@3000 之后的样子。
- `samples/demo_auto_room.dxf/.png` —— 6000×4000 外墙 + 240 隔墙，`room --auto` 自动搜出两间 2760×3760（各 10377600 mm²）并落 `R001` / `R002`。
- `samples/mcp_demo.dxf/.png` —— 纯 MCP 客户端身份从零画的成品（轴网 A/B/C + 1/2、5 堵墙、2 门 1 窗、自动 2 间房），验证 Agent 直连链路。
- `samples/demo_building.dxf/.png` —— 一栋小楼的全套图拼在一张 A2 上（平面 + 屋顶 + 楼层表 + 门窗表 + 立面 + 剖面，1:100 同一比例），用来验图面自洽：轴网对得上、楼层表标高与立/剖面标高一致、图名与比例对得上。由 `tools/demo_building.py` 生成。`samples/demo_building_roof.png` / `_plan.png` / `_elev_top.png`（轴号 + 檐口板厚）/ `_elev_low.png`（首层门窗）/ `_sect.png` / `_sectwin.png` / `_opening_table.png`（门窗表放大）是局部放大。
- `samples/demo_sheetset.dxf` + `samples/demo_sheetset_out/` —— 一栋小楼的**五张图幅套图**（建施-00 图纸目录 A4、建施-01 一层平面 A3、建施-02 屋顶 A3、建施-03 立面 A3、建施-04 剖面 A3），每张图幅只框自己那张图，按图纸集批量出 PNG（`图号_图名.png`）。演示"多图幅 + 图纸目录 + 批量出图"这条链路；注意我们是模型空间排图，不是布局/视口。由 `tools/demo_sheetset.py` 生成。
- `samples/demo_floor_copy.dxf` + `samples/demo_floor_copy_1f.png` / `demo_floor_copy_2f.png` —— **标准层复制**：一层 7200×4500 教室（一门一窗一房间）整层复制成二层（y 平移 9000、编号加 `2`），两张图上下对照，门窗编号/房间面积完全一致。演示"画一层 → 整层复制"。由 `tools/demo_floor_copy.py` 生成。
- `samples/demo_detail.dxf` + `samples/demo_detail_plan.png` / `demo_detail_big.png` —— **详图**：一层平面的 M0921/C1515 各带一个索引符号（1、2），旁边两张 1:20 大样（洞口/框/中梃/双扇/窗台板 + 宽高尺寸 + 图名比例），各配详图符号（14mm 圆）。演示"平面索引 → 门窗大样"。由 `tools/demo_detail.py` 生成。
- `samples/demo_wall_node.dxf` + `demo_wall_node.png` —— **墙身节点**：1:20 窗台节点（墙身止于窗台、楼板、窗台板、窗框+玻璃、墙厚与窗台高）与女儿墙节点（墙身、屋面板、压顶、墙厚与女儿墙高）并排，各配详图符号。由 `tools/demo_wall_node.py` 生成。
- `samples/demo_stair_detail.dxf` + `demo_stair_detail_plan.png` / `demo_stair_detail_big.png` —— **楼梯间大样**：平面双跑楼梯（10×280、梯段宽 1200、梯井 120、平台 1200）带索引符号，下方 1:20 大样（梯段/踏步/梯井/平台带/箭头 + 梯段宽、`10×280=2800`、平台深三道尺寸 + 图名比例）。由 `tools/demo_stair_detail.py` 生成。
- `samples/demo_wc_detail.dxf` + `demo_wc_detail.png` —— **卫生间大样**：2400×1800 净空 + 120 墙带，坐便靠上墙、台盆靠左墙、地漏右下角，排水坡箭头 `i=1%`，注开间/进深/坐便中心距，右上详图符号 3。由 `tools/demo_wc_detail.py` 生成。
- `samples/demo_elev_balcony.dxf` + `demo_elev_balcony.png` —— **立面阳台/雨篷**：两层立面（3600×2）+ 二层阳台（挑板 100、栏板 1000）+ 一层门头雨篷（1600×120，门洞 1600×2100）。由 `tools/demo_elev_balcony.py` 生成。
- `samples/demo_foundation.dxf` + `demo_foundation.png` —— **基础大放脚**：标准 6-6 节点：240 墙、两级 130×65 放脚、基底 500、垫层 600、埋深 2000、地圈梁 250。由 `tools/demo_foundation.py` 生成。
- `samples/demo_dim_annot.dxf` + `demo_dim_annot.png` —— **三道尺寸 + 注字/引注**：6000×4800 平面，洞口/轴线/总尺寸三道不压轴号，配"外墙 240 厚"注字与"窗台 1500"引注。由 `tools/demo_dim_annot.py` 生成。
- `samples/demo_roof_detail.dxf` + `samples/demo_roof_detail.png` —— **屋面细部**：平屋顶上加 4×3 分格、南北内天沟（各带 2 个雨水口）、错开的找坡箭头与 `i=2%` 注字；`audit` 0 问题。由 `tools/demo_roof_detail.py` 生成。
- `samples/demo_site.dxf` + `samples/demo_site.png` —— **总平面示意**：60×40 m 闭合红线、3 处建筑轮廓、2 条道路双线、2 个出入口箭头与名称、指北针、红线顶点坐标（m）与总宽/总深尺寸；`audit` 0 问题。由 `tools/demo_site.py` 生成。
- `samples/zoom_layers.png` —— 图层配色实测：轴号/轴线红（轴线点划线）、墙白、门窗青、尺寸绿、房间名白；局部放大看得到点划线的"点"。`samples/demo_sheet.png` 是同一套颜色出在 A3 图框里。

## 它和天正侧插件的区别

本插件**不依赖任何私有对象**。所有构件都是 CADCraft 原生「块参照 + 不可见属性」，几何算法全部使用公开标准（线段求交、向量几何、鞋带公式）。不读取、不复刻任何第三方插件的私有实体结构。

## 用法

```bash
# 1. 新建图纸（--scale 开图即定出图比例，之后画的注记都按它取 mm 规格）
python tools/aa_cmd.py new out.dxf --scale 100

# 1b. 中途定/改比例（默认把已有注记整批重画；--no-rescale 只改标记）
python tools/aa_cmd.py scale out.dxf                 # 查询当前比例
python tools/aa_cmd.py scale out.dxf --set 50

# 1c. 总平面（M2）：红线 / 建筑 / 道路 / 出入口 / 指北针 / 坐标尺寸（世界坐标 mm）
python tools/aa_cmd.py site out.dxf SITE01 --boundary "0,0;60000,0;60000,40000;0,40000" \
  --building "4000,4000,26000,17000,教学楼" --road "6000|0,25000;60000,25000" \
  --entrance "15000,0:主入口:0,-1" --north 55000,6000 --scale 500
python tools/aa_cmd.py site out.dxf --show SITE01     # 只回读，不改图

# 1d. 屋面细部（M2）：先有屋顶，再加分格/内天沟/坡度注字
python tools/aa_cmd.py roof out.dxf RF1 --at 0,0 --kind flat --w 12000 --d 8000 --parapet 240
python tools/aa_cmd.py roof-detail out.dxf RD1 --roof RF1 --grid "4,3" \
  --inner-gutter "S,N:400" --slope 2
python tools/aa_cmd.py roof-detail out.dxf --show RD1  # 只回读，不改图

# 1e. 自动排附表：门窗表 / 房间面积表 / 指北针 放进图面空位（图幅自动识别）
python tools/aa_cmd.py place out.dxf
python tools/aa_cmd.py place out.dxf --replace          # 重排：先清同名附表再放，不堆表
python tools/aa_cmd.py place out.dxf --no-rooms          # 只要门窗表 + 指北针
# 返回 placed / skipped / occupancy_before / occupancy_after，可直接看排完充实了多少

# 2a. 轴网（等距）：3 道纵轴 @3600，2 道横轴 @4800
python tools/aa_cmd.py axis out.dxf AX001 --xcount 3 --xspace 3600 --ycount 2 --yspace 4800

# 2b. 轴网（自动）：墙都画完后按墙反推轴线，编号自动排（tol 合同轴，ext 端外伸），并回填墙轴号
python tools/aa_cmd.py axis-auto out.dxf AX001 --tol 50 --ext 2400

# 2c. 已有图补轴号（只改属性不改几何；--only-empty 不覆盖手填值）
python tools/aa_cmd.py axis-bind out.dxf --tol 50

# 3. 墙：起点 -> 终点，墙厚 240（--snap-axis 先轴后墙：端点吸到最近轴，差 300mm 内）
python tools/aa_cmd.py wall out.dxf W001 --p1 110,110 --p2 5990,110 --thick 240 --snap-axis
python tools/aa_cmd.py wall out.dxf W001 --p1 0,0 --p2 6000,0 --thick 240 --kind EXTERNAL

# 4. 门：依附 W001，洞口中心距墙起点 1000，宽 1000
python tools/aa_cmd.py opening out.dxf D001 --wall W001 --kind DOOR --width 1000 --pos 1000

# 5. 房间：按环形顺序给墙编号，自动算净面积
python tools/aa_cmd.py room out.dxf R001 --walls W001,W007,W005,W006 --name 客厅   # 名称+面积两行，--no-area 只注名称

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

# 9b. 图名（图名 + 比例 + 下画线）与指北针；--scale 省略则跟图档比例
python tools/aa_cmd.py title out.dxf T001 --at 0,-6600 --name 一层平面图
python tools/aa_cmd.py title out.dxf T001 --at 0,-6600 --name 一层平面图 --scale ""
python tools/aa_cmd.py north out.dxf N001 --at 15500,4300

# 9b2. 图面符号：标高 / 索引 / 剖切（B1，v0.9.9）
python tools/aa_cmd.py elev out.dxf E001 --at 3000,1200 --value 0
python tools/aa_cmd.py index out.dxf I001 --at 9100,3800 --detail 1
python tools/aa_cmd.py section out.dxf S001 --p1 -1400,2400 --p2 12000,2400 --dir down --no 1

# 9b3. 图面自检（只报不改；--strict 有 error 级问题时退出码 1）
python tools/aa_cmd.py audit out.dxf
python tools/aa_cmd.py audit out.dxf --strict

# 9b4. 全图复核（只读）：轴号 / 门窗表 / 楼层表与立剖面 / 三道尺寸链
python tools/aa_cmd.py verify out.dxf
python tools/aa_cmd.py verify out.dxf --strict

# 9c. 已画完再改比例：所有注记按 mm 规格重画（补救路径，正常优先用第 1 步的 --scale）
python tools/aa_cmd.py rescale out.dxf --scale 50

# 10. 出图：A3@1:100 图框 + 标题栏（不给 --at 就按图形外廓自动居中排图；--size AUTO 自动选图幅）
python tools/aa_cmd.py sheet out.dxf S001 --size A3 --scale 100 \
    --project "某工程" --drawing "一层平面图" --no "建-01" --date 2026-11-20 --design 严
python tools/aa_cmd.py sheet out.dxf S002 --size AUTO --project "某工程"   # 放不下自动升一级

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
| 柱 | `AA-COLUMN` | 灰 8 | 实线 | 0.35 | 矩形柱实心填充 + 外框、圆柱扇形填充 + 圆 |
| 台阶 / 散水 | `AA-STEP` | 白 7 | 实线 | 0.18 | 踏步线、台阶边线、散水外沿与收头 |
| 楼梯 | `AA-STAIR` | 黄 2 | 实线 | 0.18 | 外轮廓、平台分界、梯井、踏步线（对齐天正：楼梯黄） |
| 楼梯箭头 | `AA-STAIR-ARROW` | 绿 3 | 实线 | 0.18 | 天正式"绕一圈"折线（一跑上→平台上横穿→二跑下）+ 两个实心箭头 |
| 楼梯文字 | `AA-STAIR-TEXT` | 白 7 | 实线 | 0.18 | "上"/"下" 水平正字，在梯段轮廓下方、箭头杆右侧（对齐天正） |
| 楼梯剖断 | `AA-STAIR-BREAK` | 白 7 | DASHED | 0.18 | 带"Z"缺口的天正折断符号，横切上行跑 |
| 屋顶 | `AA-ROOF` | 白 7 | 实线 | 0.25 | 檐口外轮廓、檐沟、正脊/斜脊、雨水口 |
| 屋顶找坡 | `AA-ROOF-ARROW` | 绿 3 | 实线 | 0.18 | 找坡箭头（尖指下坡 / 檐沟） |
| 立面轮廓 | `AA-ELEV` | 白 7 | 实线 | **0.35（粗线）** | 地坪线、两侧外轮廓、檐口/女儿墙压顶 |
| 立面细部 | `AA-ELEV-DETAIL` | 白 7 | 实线 | 0.18 | 楼层线、门窗洞、压顶内线 |
| 电梯 | `AA-ELEVATOR` | 黄 2 | 实线 | 0.18 | 轿厢、对重、电梯门洞（C1 新增；与立面 `AA-ELEV` 分开） |
| 门窗 | `AA-OPENING` | 青 4 | 实线 | 0.18 | 洞口边线、门扇线、弧、窗平行线 |
| 房间 | `AA-ROOM` | 白 7 | 实线 | 0.18 | 房间名称文字 |
| 尺寸 | `AA-DIM` | 绿 3 | 实线 | 0.15 | 两道尺寸线、箭头、数字 |
| 幅面线 | `AA-BORDER` | 白 7 | 实线 | 0.15 | 图幅外框（纸张边界，细线） |
| 图框 | `AA-FRAME` | 白 7 | 实线 | **0.70（图框粗线）** | 图框线（内框）、标题栏外框 |
| 标题栏 | `AA-TITLE` | 白 7 | 实线 | 0.25 | 标题栏分格线与文字 |
| 表格 | `AA-TABLE` | 白 7 | 实线 | 0.18 | 房间表、门窗表 |
| 图名/符号 | `AA-NAME` | 白 7 | 实线 | 0.25 | 图名文字、比例、指北针 |

**层是自动建的，不用你手调**：`new` 一开图就把上表 22 层按颜色/线型/线宽建好；任何后续命令画之前都会再校验一遍，缺层补建、颜色线型线宽被改坏就**自动改回来**，改不回来直接报错（不静默放过）。`layers out.dxf --fix` 可对老图纸一次性补规格。取色截至 GB/T 50001 线宽组 b=0.35/0.5/0.7 与天正默认配色（轴线红、标注绿、门窗青）。

**图层名由你定**：把 `aa_layers.example.json` 复制成项目根的 `aa_layers.json`，值可以是层名字符串，也可以是对象覆盖颜色/线型/线宽：

```json
{
  "axis":  {"name": "AXIS", "color": "红", "linetype": "CENTER", "lineweight": 0.25},
  "wall":  "WALL"
}
```

也可用环境变量 `AA_LAYERS_FILE` 指向别处的配置。键固定为 `axis / axistext / wall / opening / room / dim / sheet / title / table`。块内几何也落在你指定的层上（`tests/test_layers.py`、`tests/test_layer_style.py` 断言了这一点）。

## 图面规则（避免"看起来像没做完"）

- **批量生成**：块定义 + 插入 + 设层走同一次 `cadcraft-cli run`（`{last}` 链式句柄）；建墙阶段先不逐面回填轴号，整层墙齐了一次 `attedit` 批处理，避免每面墙都重读全图。

- 墙块里**只画两侧墙面线**，不画中心线——中心线只是语义线，画出来会在门洞处留下一条穿洞的直线。
- **不画房间轮廓线**：房间轮廓与墙面完全重合，画出来会被误读成墙线，还会横穿门窗洞口。房间只落名称文字，面积/周长/墙环都记在属性里。
- **相交裁剪**：侧线落在邻墙实心矩形内的部分被挖掉，交叉处不再互相穿插。
- **转角合角**：转角处外侧墙线延伸到邻墙外墙面，角部闭合，不留半墙厚见方的小缺口。
- **轴线是点划线**：轴线用专用 `aa:mkline-lt` 直接带 `CENTER` 线型组码（实测 `entmake` 认组 6），轴号不动；新建图档先 `linetype {"load":"*"}` 载入内置线型库，否则线型表里没有 `CENTER` 可渲染。这样轴线穿门洞时不会被误认成墙线。
- **轴号是圆圈**（GB/T 50104）：细实线圆，直径 8mm（1:100 出图 => 800 单位），圆与轴线端**相切**，编号写在圈内居中、字高 3mm（=> 300 单位）。轴号落在 `AA-AXISTEXT` 层。
- **窗框厚是构造尺寸，可逐樘改**：默认 60（240 墙即 ±60，370 墙为 ±125），`--frame` 可覆盖（40 => 内侧 ±80），**不随墙厚等比缩放**。
- **门窗编号可放室内或室外**：编号按尺寸自动生成（`M0921` / `C1215` / 门连窗 `MC…`，类型 + 宽高各两位分米），`--no` 可覆盖；`--label-side in|out|auto|leader` 决定编号落在室内侧还是室外侧（`leader` 再加一条 45° 引线指向洞口右端）（默认 `in`，`auto` 沿用旧的"-Y 侧"行为），离墙面 250、沿墙居中、字高 180，墙块转 180° 时补 180° 旋转避免倒字。房间建好（或后建）会自动重画到正确一侧——室内外要靠房间轮廓才判得出来。
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
- 动图前把整张图纸字节读进内存，中途任何异常用同目录临时文件原子写回；不依赖可能被 CLI 崩溃带走的 `.bak`。
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
| `aa_new` / `aa_show` | 新建公制图纸（可带 `scale` 开图即定比例）/ 回读全部构件 |
| `aa_scale` | 查询/设定图档出图比例（`set` 省略则只查；改比例默认整批重画已有注记） |
| `aa_axis` | 轴网（纵轴 + 横轴 + 轴号） |
| `aa_axis_auto` | **轴网自动**：按现有墙段反推轴线位置并自动编号，同时回填墙的 AX1/AX2 |
| `aa_axis_bind` | 按轴网回填墙的 AX1/AX2（横墙端点→1/2/3，竖墙端点→A/B/C） |
| `aa_layers` | 查看/校正标准图层的颜色、线型、线宽（`fix=true` 自动纠正） |
| `aa_title` | 图名标注：图名 + 比例 + 下画线 |
| `aa_north` | 指北针（圆 + 三角指针，直径按比例取 24mm） |
| `aa_rescale` | 换出图比例时整批重画注记（轴号/房间名/门窗编号/图名/指北针/尺寸） |
| `aa_wall` | 画墙，画完自动规整邻墙裁剪与合角；`snap_axis=true` 端点吸附到轴线 |
| `aa_opening` | 墙体真实开洞 + 门窗符号 + 自动编号（`frame` 窗框厚、`no` 编号可覆盖）|
| `aa_room` / `aa_room_auto` | 显式墙环建房间 / 自动搜环建房间 |
| `aa_split` / `aa_merge` | 墙体相交切断 / 共线合并（互为逆操作） |
| `aa_set_wall` / `aa_set_opening` | 改参数后整体重建（失败回滚、幂等） |
| `aa_set_room` / `aa_rooms` | 房间改名（重画名称文字）/ 汇总出 CSV 与图上表格 |
| `aa_openings` | 门窗表：同编号合并计数，CSV 或图上 6 列表格 |
| `aa_dim` | 尺寸标注：外墙墙段 + 洞口宽，两道尺寸线，自动排在轴号圈外，幂等 |
| `aa_sheet` | 图框 + 标题栏（`size` 可传 `AUTO` 自动选图幅） |
| `aa_set_sheet` | 改标题栏内容（图幅/位置/比例保持不变，重画后属性同步） |
| `aa_export` | 出图 png/svg/pdf（给 `sheet` 按图幅取窗口，PNG 自动补线宽） |

客户端配置直接抄 `mcp.example.json`。启动方式：

```bash
python tools/aa_mcp.py --serve      # 客户端以子进程拉起，走 stdin/stdout
python tools/aa_mcp.py --selftest   # 只看工具表，确认版本与工具数
```

工具返回的永远是**回读校验后的结构化结果**（`geom_handles`、`area`、`normalized` 等），不是"命令已发送"。校验失败时 MCP 层返回 `isError: true` 且 `content` 里带 `{"ok": false, "error": "..."}`，图纸零残留——这一点由 `tests/test_mcp.py` 断言（含真子进程 stdio 握手）。

## AI 纠错 / 确认面板

`tools/panel_server.py` 是一个只监听 `127.0.0.1` 的本地轻客户端，给"AI 画完、人确认"用，**不是天正式手动画图工具栏**：

- 只读预览（CADCraft 导出的 PNG；可缩放到 320%、开新标签看原图）
- 打开图纸：顶栏路径输入 + “浏览”弹窗（最近 8 张 + 根目录文件树，只列 `.dxf`，也可在弹窗里直接填路径）
- 多图纸页签：打开过的图纸留在顶部页签，切回时复用已读构件、预览、选中构件、缩放/对比和当前侧栏；切换前用 `/api/stat` 核对 mtime/size，外部改过就自动重读，不拿旧数据覆盖新图；关闭页签只关 UI，不改图纸
- 构件树：墙 / 门窗 / 房间，点一条看原始属性
- 预览图高亮：点构件、问题或变更差异行，预览图按统一世界坐标窗口画出金色框和编号，直接看出改的是哪根墙、哪扇窗、哪个房间；新增构件标预演落点，待删除构件标原位置
- 变更集全量高亮：默认把本次所有改动同时标在预览图上，改前红虚线、改后金框、新增绿框、删除红虚线；取消“全部改动”后只看当前选中项
- 问题清单：`reconcile` 数据一致性问题 + `audit` 图面压碰问题 + `verify` 全图跨表复核，点问题定位构件
- 只改已有构件属性：墙厚/类型/材质/轴号，门窗中心/宽/高/窗台/编号，房间名；复用 `set_wall` / `set_opening` / `set_room`，失败回滚，改前自动存快照
- AI 变更集：AI 先提交一组 `aa_set_wall` / `aa_set_opening` / `aa_set_room` 操作，面板在临时副本上预演，列出每个构件的改前/改后和新增/消除问题；接受后才整图写入，拒绝则原图不动
- 改动前后对比、快照、字节级回退
- 不提供画线、偏移、修剪、阵列等第二套绘图逻辑

AI 变更集接口（面板运行时由 Agent 调用）：

```json
POST /api/proposal
{"path":"samples/demo_building.dxf","title":"外墙加厚","ops":[
  {"tool":"aa_set_wall","args":{"id":"W001","thick":300}}
]}
```

面板收到后自动切到“变更”页，并挂出改前/改后预览；`/api/proposal/commit` 先存 `before-batch` 快照再写入，`/api/proposal/discard` 整批丢弃。

打开图纸相关：`GET /api/files?dir=...` 列出根目录内的子文件夹和 `.dxf`；`GET /api/stat?path=...` 只回图纸 `mtime/mtime_ns/bytes`，给页签缓存做失效判断；`/api/state` 成功后把当前图记住到 `.panel_cache/recent.json`，`/api/config` 与 `state` 都带回最近 8 张（不存在/越界的自动过滤）。

```bash
python tools/panel_server.py --dxf samples/demo_building.dxf
# 浏览器打开 http://127.0.0.1:8765/（默认自动打开；--no-browser 可关）
```

图纸路径默认限制在仓库内，防止面板被当成任意文件读取器；要打开桌面上其他项目：

```bash
python tools/panel_server.py --root C:\Users\19891\Desktop\CADcraf --dxf D:\项目\A栋.dxf
```

## 目录

```
cadcraft-arch/
├── docs/     规格（业务规则 + 实现补遗）
├── lisp/     几何引擎：aa_core / aa_axis / aa_wall / aa_opening / aa_room
├── panel/    本地 AI 纠错/确认面板（index.html / style.css / app.js）
├── tools/    CLI 驱动：aa_lib.py（会话与校验）、aa_cmd.py（命令行）、aa_mcp.py（MCP 服务）、panel_server.py、demo.py
├── tests/    按功能验收：axis / wall / opening / room / room_auto / room_modify / openings / dim / label / mcp / panel / corner / layers / split / merge / modify
└── samples/  验收输出（dxf/png）
```

## 图面质量门禁（v1.0.57，v1.0.58 修了三处判定缺陷）

`audit` 在原有"几何错误"之外，额外返回**不影响 `count` 的质量警告**，让"规范不规范、返工率高不高"变成可比较的数字：

```json
{
  "issues": [], "count": 0, "errors": 0,
  "warnings": [{"kind": "title_block_overlap", "message": "...", "level": "warn"}],
  "warning_count": 1,
  "quality": {"checks": 3, "occupancy": 0.336, "jargon": 0}
}
```

| 警告 | 检查口径 | 触发 |
|---|---|---|
| `title_block_overlap` | 非图幅图元是否压进图签矩形 | 红线/建筑线穿进标题栏 |
| `sheet_underfill` | 内框 24×16 网格被图元经过的比例 | 利用率 < 30% |
| `internal_jargon` | 注字里是否含 `AA_`、`鞋带`、`块参照`、`CADCraft` 等实现术语 | 施工说明混入开发语言 |

`quality.occupancy` 是连续指标，可用来比较改图前后的图面充实度。幼儿园 5 层方案图在 v1.0.57 里已把图签压线、说明术语全部修掉，00–05 六张图 `count=0 / warning_count=0`。

v1.0.58 又修掉三处**判定本身**的缺陷——指标算错比指标缺失更坏，因为它会让人以为图没问题：

1. **属性定义被当成可见图元**：`ATTDEF` 的坐标留在块定义原点附近，跟着 `INSERT` 做变换会凭空造出一堆框。一层平面图里 `ATTDEF` 有 1201 个、真实图元只有 646 个，`occupancy` 因此虚高（0.336 → 修后 0.315）。现在 `_quality_pieces` 直接排除 `ATTDEF/ATTRIB/SEQEND`。
2. **文字外包退化成零面积点**：`_piece_box` 按"插入点 ± 半径"算，文字宽度信息全丢，于是 `title_block_overlap` 干脆把 `TEXT` 整类排除在判定外——"主题：…"明明落进图签框也报不出来。现在文字按 插入点 + 估算字宽 + 字高 还原成真实占位框，压线检查把 `TEXT/MTEXT` 纳入。
3. **表格文字会顶出格子**：`draw_table` 自称"用线+文字自绘"来规避原生 table 的列宽问题，但自绘版同样不看列宽，一串墙号能把字顶到邻列甚至表格外。现在单元格文字先缩字（最紧到 70%），还超就截断加省略号，并在返回值里报 `shrunk / truncated` 计数——**表格尺寸永不变，字永不出格**。

另外顺带修了"说明标题写死第 6 行"（说明一加行就压到第一行字上）和"本层标高/主题摆进图签框"两个排版错。

## 门窗 / 楼梯图例修正（v1.0.59）

这一版不加功能，只把**已经画出来的东西改对**——门窗和楼梯的图例此前"能看但不合规"：

### 门窗（`lisp/aa_opening.lisp`）

| 修正前 | 修正后 |
|---|---|
| 铰点永远在洞口左端、门扇永远朝本地 +Y 开，全图门的开启方向一模一样 | `aa:opening` 增加 `hinge/swing` 两个参数，四种"铰点端 × 开向"组合各取对应弧角（0°→90°/90°→180°/180°→270°/270°→360°） |
| 1800 宽的门也画单扇，弧半径 = 整个洞口宽，一个门扇横扫半个房间 | `leaves=0` 时按宽度自动判定：**≥1200 双扇**（每扇 1800/2、两个铰点分别落在洞口两端、两弧在中间相接），也可显式给 1 或 2 |
| `DOORWIN`（门连窗）落进门的默认分支，被当普通平开门画，MC2424 就是 2400 的弧 | 单独一条分支：`doorpart` 宽的门扇带弧在铰点端，剩下的是固定窗四线，中间补一条中梃竖线；门扇宽夹在洞口宽的 20%~80% 之间，两头都画得出来 |
| 窗本来是对的（四线），但 `frame` 退化时内线会贴到墙中线 | 保留 `aa:win-frame` 的兜底（半墙厚减 10），四线改为 `aa:win4` 统一出 |

新增属性 `AA_HINGE / AA_SWING / AA_LEAVES / AA_DOORPART`，`opening_data` 一并回读；`set_opening` 支持改这四项；`split / merge / reconcile / copy-floor / rescale` 五处内部重建全部原样透传（**顺带修掉拆分合并会把自定义门窗编号重算掉的旧缺陷**）。`swing=0` 表示按室内外自动判——探房间轮廓定方向，外门朝室外即疏散方向，房间尚未建立时退回本地 +Y。

### 楼梯（`lisp/aa_stair.lisp`）

| 修正前 | 修正后 |
|---|---|
| 首层剖断线从"左边线的剖切高度"一路拉到"右边线的整跑长"，`dx≈1724 / dy≈2498`，是一条横跨整跑的斜线，还伸进第二跑的位置 | 剖断线严格 **45°**：左端 `cutL`、右端 `cutL + 梯段宽`，两端各外伸 0.4 踏步；`|dx| == |dy|` 由测试守住 |
| 踏步只按 `y < cut` 一刀切，斜线穿过的踏步要么整条留着要么整条没了 | 踏步按斜线**逐条裁剪**：`y ≤ cutL` 画全长，`cutL < y ≤ cutR` 从斜线交点画到右边线，超过 `cutR` 不画 |
| 左右两条边线一条止于剖切高度、一条拉满整跑，右边那条孤零零立着 | 两条边线各自止于剖断线（左 `cutL`、右 `cutR`） |
| 箭头杆从 `-0.12×梯段长` 拉到 `整跑长`，箭头尖落在剖断线以外的空白里 | 箭头杆从楼面外 0.45 字高起，止在剖断线（梯段中心处的斜线高度），箭头尖不越界 |
| 梯井画到 `-0.08×梯段长 ~ 梯段长+0.3 井宽`，下端伸到楼梯外面 | 梯井 0→梯段长，只贯通梯段，不穿平台（平台是整块板） |
| "上/下"写在 `-1.05 字高`，跑到楼梯外面贴着墙线 | 写在起步那一格踏步内（`0.10 踏步宽` 处、箭头右侧），180° 旋转时由 `aa:stair-label` 反推插入点，可见框位置一致 |
| 顶层也画"绕一圈"三段箭头，等于在只有下行梯段的楼层标了上行 | 顶层只画一条沿第二跑、从平台指向楼面的"下"箭头 |

`aa:stair-label` 把"字的可见左下角"对齐到给定点：块旋转 180° 时块内文字反向生长，插入点要先右移、上移一个字高，否则字会跑到梯段外面压住边线。

幼儿园 5 层方案图已按新图例重出 01–05，01 的 `occupancy` 0.383、`audit count=0 / warning_count=0`。


## 实测踩到的平台约束（重要）

这些是写代码时绕不开的坑，已写进 docs 的实现补遗，避免后续重蹈：

1. **LISP 建不了属性**：`entmake` 对 `ATTRIB` / `SEQEND` 返回 nil，块参照的属性必须由原生 `insert {attribs}` 落盘。
2. **LISP 读不了属性**：`ssget` 过滤 `ATTRIB` 返回 nil，`entnext` 不穿透属性子实体；回读必须用原生 `entities` / `eattext`。
3. **`entlast` 不可靠**：同一段 LISP 里连续 `entmake`，`entlast` 始终返回同一个实体。句柄改用"操作前后快照差分"取得。
4. **`insert.rotation` 入参是度、回读是弧度**，两者不可混用。
5. **XData 不可用**：`regapp` / `entmakex` / `setxdata` / `getxdata` 全部无函数定义。

## 下一步（M2 剩余 / M3）

- 设计说明页 / 会签栏（验收：图幅内可排版、文字可回读）
- 多页 PDF 合并（现在只有逐张导出）
- M3 工程化：CI 纯算法单测、`plot_style.json`、全量回归分批与汇总报告、同图多比例边界评估

## 合规声明

本项目为独立自研，仅实现建筑绘图领域的通用业务行为。所有数据模型、几何算法均为自行设计，采用公开标准算法；不读取、分析、复刻、引用任何第三方 CAD 插件的内部代码、私有实体结构或私有存储格式；不生成 AutoCAD ARX / BRX / C++ TRX 代码。

## 许可

MIT，见 [LICENSE](LICENSE)。
