;;; ============================================================
;;; cadcraft-arch 核心库  (aa_core.lisp)
;;; 目标环境：CADCraft 0.20.1
;;; 只使用已在该版本实测通过的 LISP 子集：
;;;   entmake / entget / entmod / entdel / entlast / entnext
;;;   ssget / ssname / sslength / tblsearch
;;;   defun / setq / while / repeat / foreach / mapcar / if / cond
;;;   strcat / substr / strlen / rtos / itoa / atoi / float / append
;;; 注意：CADCraft 无 XData，构件数据一律走"块定义 + 内嵌属性"
;;; ============================================================

;; ---------- 全局配置 ----------

(setq aa:*tol* 0.001)
(setq aa:*made* nil)
(setq aa:*text-h* 200.0)
(setq aa:*label-gap* 400.0)

;; 制图取值（GB/T 50104 / 常见建筑制图习惯）
;; 轴号圆圈：直径 8mm，1:100 出图 => 800 图元单位
(setq aa:*axis-r* 400.0)
;; 轴号字高：3mm @1:100 => 300
(setq aa:*axis-h* 300.0)
;; 窗框厚：固定构造尺寸（默认 60），可逐樘覆盖
(setq aa:*win-frame* 60.0)
;; 门窗编号字高：1.8mm @1:100 => 180
(setq aa:*label-h* 180.0)
;; 房间名字高：2.5mm @1:100 => 250（换比例时由驱动层 setq 覆盖）
(setq aa:*room-h* 250.0)

(setq aa:*lay-axis* "AA-AXIS")
(setq aa:*lay-axistext* "AA-AXISTEXT")
(setq aa:*lay-wall* "AA-WALL")
(setq aa:*lay-opening* "AA-OPENING")
(setq aa:*lay-room* "AA-ROOM")
(setq aa:*lay-column* "AA-COLUMN")
(setq aa:*lay-step* "AA-STEP")
(setq aa:*lay-stair* "AA-STAIR")(setq aa:*lay-stairarrow* "AA-STAIR-ARROW")(setq aa:*lay-stairtext* "AA-STAIR-TEXT")(setq aa:*lay-stairbreak* "AA-STAIR-BREAK")
(setq aa:*lay-roof* "AA-ROOF")
(setq aa:*lay-roofarrow* "AA-ROOF-ARROW")
(setq aa:*lay-elevator* "AA-ELEVATOR")

;; ---------- 点与向量 ----------

(defun aa:pt (x y) (list (float x) (float y) 0.0))
(defun aa:px (p) (car p))
(defun aa:py (p) (cadr p))

(defun aa:dist (a b / dx dy)
  (setq dx (- (aa:px a) (aa:px b))
        dy (- (aa:py a) (aa:py b)))
  (sqrt (+ (* dx dx) (* dy dy))))

(defun aa:eqpt (a b) (< (aa:dist a b) aa:*tol*))

(defun aa:ang (a b / dx dy)
  (setq dx (- (aa:px b) (aa:px a))
        dy (- (aa:py b) (aa:py a)))
  (if (and (< (abs dx) 1e-12) (< (abs dy) 1e-12))
      0.0
      (atan dy dx)))

(defun aa:dir (a b / dx dy len)
  (setq dx (- (aa:px b) (aa:px a))
        dy (- (aa:py b) (aa:py a))
        len (sqrt (+ (* dx dx) (* dy dy))))
  (if (< len 1e-12)
      (list 1.0 0.0)
      (list (/ dx len) (/ dy len))))

(defun aa:normal (a b / d)
  (setq d (aa:dir a b))
  (list (- (cadr d)) (car d)))

(defun aa:offseg (p1 p2 nx ny d)
  (list (list (+ (aa:px p1) (* nx d)) (+ (aa:py p1) (* ny d)) 0.0)
        (list (+ (aa:px p2) (* nx d)) (+ (aa:py p2) (* ny d)) 0.0)))

;; ---------- 线段求交（公开的向量几何算法） ----------

(defun aa:cross (ax ay bx by) (- (* ax by) (* ay bx)))

(defun aa:segint (p1 p2 p3 p4 / rx ry sx sy den par1 par2)
  (setq rx (- (aa:px p2) (aa:px p1))
        ry (- (aa:py p2) (aa:py p1))
        sx (- (aa:px p4) (aa:px p3))
        sy (- (aa:py p4) (aa:py p3)))
  (setq den (aa:cross rx ry sx sy))
  (if (< (abs den) 1e-12)
      nil
      (progn
        (setq par1 (/ (aa:cross (- (aa:px p3) (aa:px p1))
                                (- (aa:py p3) (aa:py p1))
                                sx sy)
                      den)
              par2 (/ (aa:cross (- (aa:px p3) (aa:px p1))
                                (- (aa:py p3) (aa:py p1))
                                rx ry)
                      den))
        (if (and (>= par1 0.0) (<= par1 1.0) (>= par2 0.0) (<= par2 1.0))
            (list (list (+ (aa:px p1) (* par1 rx))
                        (+ (aa:py p1) (* par1 ry))
                        0.0)
                  par1 par2)
            nil))))

;; ---------- 多边形度量（鞋带公式 / 公开标准） ----------

(defun aa:polyarea (pts / n i s a b)
  (setq n (length pts))
  (if (< n 3)
      0.0
      (progn
        (setq i 0 s 0.0)
        (while (< i n)
          (setq a (nth i pts)
                b (nth (rem (1+ i) n) pts)
                s (+ s (- (* (aa:px a) (aa:py b)) (* (aa:px b) (aa:py a)))))
          (setq i (1+ i)))
        (/ (abs s) 2.0))))

(defun aa:polyperim (pts / n i s a b)
  (setq n (length pts))
  (if (< n 2)
      0.0
      (progn
        (setq i 0 s 0.0)
        (while (< i n)
          (setq a (nth i pts)
                b (nth (rem (1+ i) n) pts)
                s (+ s (aa:dist a b)))
          (setq i (1+ i)))
        s)))

;; ---------- 实体构造 ----------

(defun aa:handle (e) (cdr (assoc 5 (entget e))))
(defun aa:hlast () (aa:handle (entlast)))
(defun aa:record (h) (setq aa:*made* (cons h aa:*made*)) h)

(defun aa:mkline (p1 p2 lay / h)
  (entmake (list (cons 0 "LINE") (cons 8 lay) (cons 10 p1) (cons 11 p2)))
  (setq h (aa:hlast))
  (aa:record h))

;; 带线型的线（实测 entmake 认组 6）；轴线用这个，墙线/门窗线仍走 aa:mkline
(defun aa:mkline-lt (p1 p2 lay lt / h)
  (entmake (list (cons 0 "LINE") (cons 8 lay) (cons 6 lt) (cons 10 p1) (cons 11 p2)))
  (setq h (aa:hlast))
  (aa:record h))

(defun aa:mktext (pt str lay hgt / h)
  (entmake (list (cons 0 "TEXT") (cons 8 lay) (cons 10 pt)
                 (cons 40 (float hgt)) (cons 1 str)))
  (setq h (aa:hlast))
  (aa:record h))

;; 带旋转角的文字：块参照若转了 180°，块内文字会倒着看，
;; 用 180° 抵消（组 50 是弧度）
(defun aa:mktext-r (pt str lay hgt ang / h)
  (entmake (list (cons 0 "TEXT") (cons 8 lay) (cons 10 pt)
                 (cons 40 (float hgt)) (cons 50 (float ang)) (cons 1 str)))
  (setq h (aa:hlast))
  (aa:record h))

(defun aa:mkpline (pts lay / code p h)
  (setq code (list (cons 0 "LWPOLYLINE") (cons 8 lay)
                   (cons 90 (length pts)) (cons 70 0)))
  (foreach p pts
    (setq code (append code (list (cons 10 (list (aa:px p) (aa:py p)))))))
  (entmake code)
  (setq h (aa:hlast))
  (aa:record h))

(defun aa:mkarc (cen rad a1 a2 lay / h)
  (entmake (list (cons 0 "ARC") (cons 8 lay) (cons 10 cen)
                 (cons 40 (float rad)) (cons 50 a1) (cons 51 a2)))
  (setq h (aa:hlast))
  (aa:record h))

(defun aa:mkcircle (cen rad lay / h)
  (entmake (list (cons 0 "CIRCLE") (cons 8 lay) (cons 10 cen)
                 (cons 40 (float rad))))
  (setq h (aa:hlast))
  (aa:record h))

;; ---------- 句柄收集 ----------

(defun aa:hs (/ s)
  (setq s "")
  (foreach h (reverse aa:*made*)
    (if (= s "")
        (setq s h)
        (setq s (strcat s "|" h))))
  s)

(defun aa:begin () (setq aa:*made* nil))

;; ---------- 编号工具 ----------

(defun aa:pad3 (n / s)
  (setq s (itoa n))
  (if (< n 10)
      (strcat "00" s)
      (if (< n 100)
          (strcat "0" s)
          s)))

(defun aa:ids (prefix / s i out nm)
  (setq s (ssget "X" (list (cons 0 "INSERT") (cons 2 (strcat prefix "*")))))
  (setq out nil)
  (if s
      (progn
        (setq i 0)
        (while (< i (sslength s))
          (setq nm (cdr (assoc 2 (entget (ssname s i))))
                nm (substr nm (1+ (strlen prefix)))
                out (cons nm out))
          (setq i (1+ i))))
      nil)
  (reverse out))

(defun aa:nextid (prefix / ids best num tail)
  (setq ids (aa:ids prefix)
        best 0)
  (foreach x ids
    (setq tail (if (> (strlen x) 3) (substr x (1+ (- (strlen x) 3)) 3) x)
          num (atoi tail))
    (if (> num best) (setq best num)))
  (strcat prefix (aa:pad3 (1+ best))))

(defun aa:exists (prefix id)
  (if (member id (aa:ids prefix)) "1" "0"))
