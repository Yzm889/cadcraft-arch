;;; ============================================================
;;; cadcraft-arch 图面符号库  (aa_symbol.lisp)
;;; 只依赖 aa_core.lisp 的 entmake 封装：
;;;   · 图名标注：图名（5mm@1:100）+ 右侧比例（3.5mm）+ 图名下粗线 + 比例下细线
;;;   · 指北针：圆（直径 24mm@1:100）+ 指针（尾部宽 3mm，GB/T 50001 习惯）
;;; 单位均为图元单位（mm），1:100 出图时 1mm = 10 图元单位；这里是 1:100 的取值。
;;; ============================================================

(setq aa:*lay-name* "AA-NAME")
(setq aa:*lay-sheet* "AA-SHEET")

;; 字高（图元单位，1:100）
(setq aa:*title-h* 500.0)       ; 图名 5mm
(setq aa:*title-scale-h* 350.0) ; 比例 3.5mm
(setq aa:*name-h* 350.0)        ; 指北针 N 3.5mm
(setq aa:*title-base* 250.0)    ; 图名线离字底 2.5mm
(setq aa:*title-gap* 400.0)     ; 图名与比例的水平间距 4mm

;; 文字宽度粗估：按 0.9 字高/字计（中文接近 1.0、数字接近 0.6，取折中）。
;; 不用 ascii —— 该函数不在已实测通过的 LISP 子集里。
(defun aa:text-w (str hgt /)
  (* 0.9 hgt (float (strlen str))))

;; (aa:title x y "一层平面图" "1:100")
(defun aa:title (x y nm sc / h hs w gap base)
  (setq h aa:*title-h*
        hs aa:*title-scale-h*
        w (aa:text-w nm h)
        gap aa:*title-gap*
        base (- y aa:*title-base*))
  (aa:mktext (aa:pt x y) nm aa:*lay-name* h)
  ;; 图名下：粗线（图框线层 0.70）
  (aa:mkline (aa:pt x base) (aa:pt (+ x w) base) aa:*lay-sheet*)
  (if (> (strlen sc) 0)
      (progn
        (aa:mktext (aa:pt (+ x w gap) y) sc aa:*lay-name* hs)
        ;; 比例下：细线（图名层 0.25）
        (aa:mkline (aa:pt (+ x w gap) base)
                   (aa:pt (+ x w gap (aa:text-w sc hs)) base)
                   aa:*lay-name*)))
  (aa:hs))

;; (aa:elev x y val h th)
;; 标高符号（GB/T 50001 习惯）：等腰直角三角，尖端指向标注面
;;   (x,y) 尖端；h 三角高（3mm@比例）；th 数字字高（2.5mm@比例）
(defun aa:elev (x y val h th / p1 p2 p3 xt)
  (aa:begin)
  (setq p1 (list x y 0.0)
        p2 (list (- x h) (+ y h) 0.0)
        p3 (list (+ x h) (+ y h) 0.0))
  (aa:mkline p1 p2 aa:*lay-sheet*)
  (aa:mkline p2 p3 aa:*lay-sheet*)
  (aa:mkline p3 p1 aa:*lay-sheet*)
  ;; 底边向右引出短基线，数字写在基线上方
  (aa:mkline p3 (list (+ x h (* 1.6 h)) (+ y h) 0.0) aa:*lay-name*)
  (aa:mktext (list (+ x h (* 0.35 h)) (+ y h (* 0.55 th)) 0.0)
             val aa:*lay-name* th)
  (aa:hs))

;; (aa:idx x y d n1 n2 th)
;; 索引符号：直径 d 的圆 + 水平直径线；上半写详图编号，下半写图号
(defun aa:idx (x y d n1 n2 th / r w1 w2)
  (aa:begin)
  (setq r (/ (float d) 2.0)
        w1 (aa:text-w n1 th)
        w2 (aa:text-w n2 th))
  (aa:mkcircle (aa:pt x y) r aa:*lay-name*)
  (aa:mkline (aa:pt (- x r) y) (aa:pt (+ x r) y) aa:*lay-name*)
  (aa:mktext (aa:pt (- x (/ w1 2.0)) (+ y (* 0.18 th)))
             n1 aa:*lay-name* th)
  (aa:mktext (aa:pt (- x (/ w2 2.0)) (- y (* 1.05 th)))
             n2 aa:*lay-name* th)
  (aa:hs))

;; (aa:section x1 y1 x2 y2 vx vy no seg d th)
;; 剖切符号（GB/T 50001）：剖切位置线只画两端两段粗线（seg 6~10mm，不与图面线条相接），
;; 两端各一条垂直的投射方向线（d 4~6mm），编号 no-no 写在两条方向线端部。
;; 编号按投射方向对齐：左右投射时数字在端部外侧，上下投射时数字在端部上方/下方居中。
(defun aa:section (x1 y1 x2 y2 vx vy no seg d th / dx dy len ux uy gap txt w
                   ax1 ay1 bx1 by1 ax2 ay2 bx2 by2 tx1 ty1 tx2 ty2)
  (aa:begin)
  (setq dx (- x2 x1)
        dy (- y2 y1)
        len (sqrt (+ (* dx dx) (* dy dy)))
        ux (/ dx len)
        uy (/ dy len)
        gap (* 0.6 th)
        txt (strcat no "-" no)
        w (aa:text-w txt th))
  ;; 位置线：起点处向终点方向一段，终点处向起点方向一段
  (setq ax1 x1 ay1 y1
        bx1 (+ x1 (* ux seg)) by1 (+ y1 (* uy seg))
        ax2 x2 ay2 y2
        bx2 (- x2 (* ux seg)) by2 (- y2 (* uy seg)))
  (aa:mkline (aa:pt ax1 ay1) (aa:pt bx1 by1) aa:*lay-sheet*)
  (aa:mkline (aa:pt ax2 ay2) (aa:pt bx2 by2) aa:*lay-sheet*)
  ;; 投射方向线：两端各自垂直位置线
  (aa:mkline (aa:pt ax1 ay1) (aa:pt (+ ax1 (* vx d)) (+ ay1 (* vy d))) aa:*lay-sheet*)
  (aa:mkline (aa:pt ax2 ay2) (aa:pt (+ ax2 (* vx d)) (+ ay2 (* vy d))) aa:*lay-sheet*)
  ;; 编号：横向投射时贴端部外侧；纵向投射时在端部之间居中
  (setq tx1 (+ ax1 (* vx (+ d gap)))
        ty1 (+ ay1 (* vy (+ d gap)))
        tx2 (+ ax2 (* vx (+ d gap)))
        ty2 (+ ay2 (* vy (+ d gap))))
  (cond ((< vx 0.0)
         (setq tx1 (- tx1 w) ty1 (- ty1 (/ th 2.0))
               tx2 (- tx2 w) ty2 (- ty2 (/ th 2.0))))
        ((> vx 0.0)
         (setq ty1 (- ty1 (/ th 2.0)) ty2 (- ty2 (/ th 2.0))))
        (T
         (setq tx1 (- tx1 (/ w 2.0)) tx2 (- tx2 (/ w 2.0)))
         (if (< vy 0.0)
             (setq ty1 (- ty1 th) ty2 (- ty2 th)))))
  (aa:mktext (aa:pt tx1 ty1) txt aa:*lay-name* th)
  (aa:mktext (aa:pt tx2 ty2) txt aa:*lay-name* th)
  (aa:hs))

;; (aa:north x y size)  size = 圆直径（1:100 取 2400 => 24mm）
(defun aa:north (x y size / r w apex l r2 txt)
  (setq r (/ (float size) 2.0)
        w (/ r 8.0)                      ; 尾部半宽 = 直径/16（总宽 3mm@24mm 圆）
        apex (+ y r 0.0)
        l (- y (* r 0.90))
        r2 (- y (* r 0.55)))
  (aa:mkcircle (aa:pt x y) r aa:*lay-name*)
  ;; 指针：等腰三角形（尖端在圆周上方，尾部宽 3mm，尾部在圆心下方）
  ;; 用三条 LINE 而不是多段线：预览补线宽阶段对 LWPOLYLINE 只按首末点重画。
  (aa:mkline (aa:pt x apex) (aa:pt (- x w) l) aa:*lay-name*)
  (aa:mkline (aa:pt x apex) (aa:pt (+ x w) l) aa:*lay-name*)
  (aa:mkline (aa:pt (- x w) l) (aa:pt (+ x w) l) aa:*lay-name*)
  ;; 指北文字
  (aa:mktext (aa:pt (- x (* 0.31 aa:*name-h*)) (+ y r 250.0))
             "N" aa:*lay-name* aa:*name-h*)
  (aa:hs))
