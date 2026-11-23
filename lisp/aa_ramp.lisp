;;; ============================================================
;;; 坡道  (aa_ramp.lisp)   依赖 aa_core.lisp
;;; 本地原点 = p1；+X 从 p1 指向 p2；宽度沿 ±Y。
;;; 图元：两侧边线 2 + 两端端线 2 + 中心线 1 = 5 LINE；
;;;       扶手 2（rail=1）；
;;;       箭头杆 1 + 实心箭头 1 SOLID；
;;;       注字 1 TEXT。
;;; 故 rail=1：8 LINE + 1 SOLID + 1 TEXT；rail=0：6 LINE + 1 SOLID + 1 TEXT。
;;; 不新增图层：边线/端线/中心线/扶手 AA-STEP，箭头 AA-STAIR-ARROW，注字 AA-STAIR-TEXT。
;;; ============================================================

;; 实心箭头：tip 为尖端，base 为底边中心，hw 为底边半宽
(defun aa:ramp-arrow (tip base hw lay / bl br)
  (setq bl (list (- (car base) hw) (cadr base) 0.0)
        br (list (+ (car base) hw) (cadr base) 0.0))
  (entmake (list (cons 0 "SOLID") (cons 8 lay)
                 (cons 10 tip) (cons 11 bl) (cons 12 br) (cons 13 br)))
  (aa:record (aa:hlast)))

;; (aa:ramp len w rail lh label arrow)
;; arrow=1 上坡（+X），arrow=-1 下坡（-X）；rail=1 画扶手
(defun aa:ramp (len w rail lh label arrow / L hw rail-y x1 x2 tipx basex)
  (aa:begin)
  (setq L (float len)
        hw (/ (float w) 2.0)
        rail-y (- hw 50.0)
        x1 (* 0.15 L)
        x2 (* 0.85 L))
  ;; 两侧边线
  (aa:mkline (aa:pt 0.0 (- hw)) (aa:pt L (- hw)) aa:*lay-step*)
  (aa:mkline (aa:pt 0.0 hw) (aa:pt L hw) aa:*lay-step*)
  ;; 两端端线
  (aa:mkline (aa:pt 0.0 (- hw)) (aa:pt 0.0 hw) aa:*lay-step*)
  (aa:mkline (aa:pt L (- hw)) (aa:pt L hw) aa:*lay-step*)
  ;; 中心线（箭头基座，保证 6/8 线口径）
  (aa:mkline (aa:pt 0.0 0.0) (aa:pt L 0.0) aa:*lay-step*)
  ;; 扶手线
  (if (> rail 0)
      (progn
        (aa:mkline (aa:pt 0.0 (- rail-y)) (aa:pt L (- rail-y)) aa:*lay-step*)
        (aa:mkline (aa:pt 0.0 rail-y) (aa:pt L rail-y) aa:*lay-step*)))
  ;; 箭头杆 + 实心箭头（上坡尖端在 +X，下坡尖端在起点侧）
  (aa:mkline (aa:pt x1 0.0) (aa:pt x2 0.0) aa:*lay-stairarrow*)
  (if (> arrow 0)
      (setq tipx x2 basex (- tipx 320.0))
      (setq tipx x1 basex (+ tipx 320.0)))
  (aa:ramp-arrow (aa:pt tipx 0.0) (aa:pt basex 0.0) 80.0 aa:*lay-stairarrow*)
  ;; 注字：默认 i=1:n；空串不注字
  (if (> (strlen label) 0)
      (aa:mktext-r (aa:pt (* 0.5 L) (+ hw (* 1.2 (float lh))))
                   label aa:*lay-stairtext* lh 0.0))
  (aa:hs))
