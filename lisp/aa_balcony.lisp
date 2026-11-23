;;; ============================================================
;;; 阳台（平面）(aa_balcony.lisp)   依赖 aa_core.lisp
;;; 块本地原点 = 墙外表面中点；+X 沿墙，+Y 向外。
;;; 图元：外沿线 1 + 两侧边线 2 + 栏板内线 1 + 两侧栏板回线 2 = 6 LINE；
;;; 可选注字 1 TEXT。
;;; 不新增图层：线全部 AA-STEP，注字 AA-STAIR-TEXT。
;;; ============================================================

;; (aa:balcony w d rail lh label)
(defun aa:balcony (w d rail lh label / hw dd rr x)
  (aa:begin)
  (setq hw (/ (float w) 2.0)
        dd (float d)
        rr (float rail))
  ;; 外沿线
  (aa:mkline (aa:pt (- hw) dd) (aa:pt hw dd) aa:*lay-step*)
  ;; 两侧边线
  (aa:mkline (aa:pt (- hw) 0.0) (aa:pt (- hw) dd) aa:*lay-step*)
  (aa:mkline (aa:pt hw 0.0) (aa:pt hw dd) aa:*lay-step*)
  ;; 栏板内线
  (aa:mkline (aa:pt (+ (- hw) rr) (- dd rr))
             (aa:pt (- hw rr) (- dd rr)) aa:*lay-step*)
  ;; 两侧栏板回线（从侧边到栏板内线）
  (aa:mkline (aa:pt (- hw) (- dd rr))
             (aa:pt (+ (- hw) rr) (- dd rr)) aa:*lay-step*)
  (aa:mkline (aa:pt hw (- dd rr))
             (aa:pt (- hw rr) (- dd rr)) aa:*lay-step*)
  ;; 可选注字
  (if (> (strlen label) 0)
      (aa:mktext-r (aa:pt 0.0 (/ dd 2.0)) label aa:*lay-stairtext* lh 0.0))
  (aa:hs))
