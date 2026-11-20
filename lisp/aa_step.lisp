;;; ============================================================
;;; 台阶 / 散水  (aa_step.lisp)   依赖 aa_core.lisp
;;; 台阶：贴墙线不画（与墙线重合），从第一步起画踏步线，
;;;       两侧画边线，最后一步的外沿即外轮廓线。
;;; 散水：沿墙外侧的等宽带状，画外沿线 + 两端收头线（宽度可配）。
;;; 块定义：AA_STEP_<ID> / AA_APRON_<ID>
;;; 本地原点 = 贴墙线中点，+Y 为外挑方向
;;; ============================================================

;; (aa:step w steps tread)  w=台阶宽（沿墙向），steps=踏步数，tread=踏步宽
(defun aa:step (w steps tread / hw d k y)
  (aa:begin)
  (setq hw (/ (float w) 2.0)
        d (* (float steps) (float tread))
        k 1)
  ;; 两侧边线：从贴墙线（y=0）到外沿
  (aa:mkline (aa:pt (- hw) 0.0) (aa:pt (- hw) d) aa:*lay-step*)
  (aa:mkline (aa:pt hw 0.0) (aa:pt hw d) aa:*lay-step*)
  ;; 踏步线：第一步线在 y=tread，最后一步线即外沿 y=d
  (while (<= k steps)
    (setq y (* k (float tread)))
    (aa:mkline (aa:pt (- hw) y) (aa:pt hw y) aa:*lay-step*)
    (setq k (+ k 1)))
  (aa:hs))

;; (aa:apron len width)  len=沿墙长（贴墙中线到两端各一半），width=外挑宽
(defun aa:apron (len width / hl)
  (aa:begin)
  (setq hl (/ (float len) 2.0))
  ;; 外沿线
  (aa:mkline (aa:pt (- hl) width) (aa:pt hl width) aa:*lay-step*)
  ;; 两端收头（从墙面到外沿，斜 45° 的简化：直接垂直收头）
  (aa:mkline (aa:pt (- hl) 0.0) (aa:pt (- hl) width) aa:*lay-step*)
  (aa:mkline (aa:pt hl 0.0) (aa:pt hl width) aa:*lay-step*)
  (aa:hs))
