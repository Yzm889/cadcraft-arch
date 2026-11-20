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

;; 文字宽度粗估：按 0.9 字高/字计（中文接近 1.0、数字接近 0.6，取折中）。
;; 不用 ascii —— 该函数不在已实测通过的 LISP 子集里。
(defun aa:text-w (str hgt /)
  (* 0.9 hgt (float (strlen str))))

;; (aa:title x y "一层平面图" "1:100")
(defun aa:title (x y nm sc / h hs w gap base)
  (setq h aa:*title-h*
        hs aa:*title-scale-h*
        w (aa:text-w nm h)
        gap 400.0
        base (- y 150.0))
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
