# 天正命令入口证据（最小引用集）

> 仅列出本报告缺口表实际引用的命令，用于证明"天正入口存在"。
> 来源：`C:\Tangent\TArchT30V2\help\CmdMapToHelp.txt`（T30 安装自带命令→帮助映射，共 462 条 / 22 模块）。
> 本文件不是天正命令表的拷贝，只保留缺口论证所需条目；不包含任何天正源码、LISP/ARX、私有实体、XData、图标或菜单资源。

| 模块 | 命令 | 中文名 | 本报告用途 |
|---|---|---|---|
| 7-门窗 | `TBanWin` | 带形窗 | 缺口 1 |
| 7-门窗 | `TCornerWin` | 转角窗 | 缺口 1 |
| 7-门窗 | `TGroupOpening` | 组合门窗 | 缺口 1 |
| 7-门窗 | `TPolyHole` | 异形洞 | 缺口 1 |
| 7-门窗 | `TValidOp` | 门窗检查 | 缺口 6 |
| 7-门窗 | `TStatOp` | 门窗表 | 缺口 6 |
| 7-门窗 | `TPrjOP` | 门窗总表 | 缺口 6 |
| 7-门窗 | `TWDRegul` | 门窗归整 | 缺口 6 |
| 7-门窗 | `TFillOpening` | 门窗填墙 | 缺口 6 |
| 7-门窗 | `TMirWinIO` / `TMirWinLR` | 内外翻转 / 左右翻转 | 缺口 6 |
| 7-门窗 | `TStaticHole` | 留洞表 | 缺口 6 |
| 7-门窗 | `TSetWinLab` | 编号设置 | 缺口 6 |
| 8-房间 | `TSpOutline` | 房间轮廓 | 缺口 5 |
| 8-房间 | `TModifySpaceEdge` | 修改边界 | 缺口 5 |
| 8-房间 | `TApartArea` | 套内面积 | 缺口 5 |
| 8-房间 | `TShareArea` | 公摊面积 | 缺口 5 |
| 8-房间 | `TCountArea` | 面积统计 | 缺口 5 |
| 8-房间 | `TTextToSpace` | 字转房间 | 缺口 5 |
| 9-屋顶 | `TSlopeRoof` | 任意坡顶 | 缺口 4 |
| 9-屋顶 | `TDualSlopeRoof` | 人字坡顶 | 缺口 4 |
| 9-屋顶 | `TCuspRoof` | 攒尖屋顶 | 缺口 4 |
| 9-屋顶 | `TRectRoof` | 矩形屋顶 | 缺口 4 |
| 9-屋顶 | `TDormer` | 加老虎窗 | 缺口 4 |
| 9-屋顶 | `TStrm` | 加雨水管 | 缺口 4 |
| 9-屋顶 | `TRoflna` | 搜屋顶线 | 缺口 4 |
| 10-楼梯与其他 | `TElevator` | 电梯 | 缺口 2 |
| 10-楼梯与其他 | `TAscent` | 坡道 | 缺口 2 |
| 10-楼梯与其他 | `TBalcony` | 阳台 | 缺口 2 |
| 10-楼梯与其他 | `tdrawautostair` | 自动扶梯 | 缺口 2 |
| 10-楼梯与其他 | `TLStair` / `TRStair` | 直线梯段 / 双跑楼梯 | 对照 |
| 11-立面 | `TEWinLib` / `TEWPara` | 立面门窗 / 门窗参数 | 缺口 7 |
| 11-立面 | `Id_Elwct` | 立面窗套 | 缺口 7 |
| 11-立面 | `tlmroof` | 立面屋顶 | 缺口 7 |
| 11-立面 | `TEStrm` | 雨水管线 | 缺口 7 |
| 11-立面 | `TObjElev` | 构件立面 | 缺口 7 |
| 12-剖面 | `Id_Sfloor1` | 预制楼板 | 缺口 8 |
| 12-剖面 | `Id_Sroof` | 剖面檐口 | 缺口 8 |
| 12-剖面 | `MCGL` | 门窗过梁 | 缺口 8 |
| 12-剖面 | `TSectStair` | 参数楼梯 | 缺口 8 |
| 12-剖面 | `Id_Rltplib` | 参数栏杆 | 缺口 8 |
| 12-剖面 | `ID_FillSect` | 剖面填充 | 缺口 8 |
| 12-剖面 | `Id_Sltoplc1` | 居中加粗 | 缺口 8 |
| 13-文字表格 | `TMText` | 多行文字 | 缺口 9 |
| 13-文字表格 | `TCurveText` | 曲线文字 | 缺口 9 |
| 13-文字表格 | `TWordLib` | 专业词库 | 缺口 9 |
| 13-文字表格 | `TTxtCount` | 文字统计 | 缺口 9 |
| 13-文字表格 | `TTextAddFrame` | 文字加框 | 缺口 9 |
| 13-文字表格 | `TNewSheet` | 新建表格 | 缺口 9 |
| 13-文字表格 | `Sheet2Excel` | 转出 Excel | 缺口 9 |
| 14-尺寸标注 | `TDimWall` | 墙厚标注 | 缺口 3 |
| 14-尺寸标注 | `TDim3` | 门窗标注 | 缺口 3 |
| 14-尺寸标注 | `TCaveSize` | 洞口尺寸 | 缺口 3 |
| 14-尺寸标注 | `TDimRad` / `TDimDia` | 半径 / 直径标注 | 缺口 3 |
| 14-尺寸标注 | `TQuickDim` | 自由标注 | 对照 |
| 15-符号标注 | `TCoord` | 坐标标注 | 缺口 3 |
| 15-符号标注 | `TCheckCoord` | 坐标检查 | 缺口 3 |
| 15-符号标注 | `TCoordSheet` | 生坐标表 | 缺口 3 |
| 15-符号标注 | `TMElev` | 标高标注 | 对照 |
| 15-符号标注 | `TSection` | 剖切符号 | 对照 |
| 15-符号标注 | `TDrawingName` | 图名标注 | 对照 |
| 4-轴网 | `TSingleAxis` | 单轴绘制 | 缺口 10 |
| 4-轴网 | `TInsAxis` / `TDelAxis` | 添加 / 删除轴线 | 缺口 10 |
| 4-轴网 | `TClipAxis` / `TMergeAxis` | 轴线剪裁 / 轴网合并 | 缺口 10 |
| 4-轴网 | `TAxisDote` | 轴改线型 | 缺口 10 |
| 4-轴网 | `TMultAxisDim` | 轴网标注 | 缺口 10 |
| 4-轴网 | `TMutiLabel` | 一轴多号 | 缺口 10 |
| 6-墙体 | `tkatana` / `TDivWall` | 墙体切割 / 等分加墙 | 缺口 11 |
| 6-墙体 | `TSWall` / `TPartwall` | 单线变墙 / 墙体分段 | 缺口 11 |
| 6-墙体 | `TConvertCurtain` / `TFillet` / `TFixWall` | 幕墙转换 / 倒墙角 / 修墙角 | 缺口 11 |
| 6-墙体 | `TAdjWallBase` / `TOffset` | 基线对齐 / 净距偏移 | 缺口 11 |
