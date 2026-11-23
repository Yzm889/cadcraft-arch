;;; ============================================================
;;; 电梯  (aa_elevator.lisp)   依赖 aa_core.lisp
;;; 本地原点 = 井道净空中心；门在 +Y，对重在 -Y；
;;; 插入时按 door_side 旋转（N=0 / E=-90 / S=180 / W=90）。
;;; 图元：轿厢 4 线 + 对角线 2 线 + 对重 4 线 = 10 条 LINE；
;;; 不画文字（电梯编号由门洞块 AA_OPENING_<id>-D 携带）。
;;; ============================================================

;; (aa:elevator car_w car_d cw_w cw_d car_offset shaft_d cw_gap)
(defun aa:elevator (car_w car_d cw_w cw_d car_offset shaft_d cw_gap /
                    hw hd y0 y1 cwx cwy)
  (aa:begin)
  (setq hw (/ (float car_w) 2.0)
        hd (/ (float car_d) 2.0)
        y0 (- (float car_offset) hd)
        y1 (+ (float car_offset) hd))
  ;; 轿厢矩形
  (aa:mkline (aa:pt (- hw) y0) (aa:pt hw y0) aa:*lay-elevator*)
  (aa:mkline (aa:pt hw y0) (aa:pt hw y1) aa:*lay-elevator*)
  (aa:mkline (aa:pt hw y1) (aa:pt (- hw) y1) aa:*lay-elevator*)
  (aa:mkline (aa:pt (- hw) y1) (aa:pt (- hw) y0) aa:*lay-elevator*)
  ;; 轿厢对角线（X）
  (aa:mkline (aa:pt (- hw) y0) (aa:pt hw y1) aa:*lay-elevator*)
  (aa:mkline (aa:pt hw y0) (aa:pt (- hw) y1) aa:*lay-elevator*)
  ;; 对重矩形（-Y 侧）
  (setq cwx (/ (float cw_w) 2.0)
        cwy (- (/ (float shaft_d) 2.0) (float cw_gap)))
  (aa:mkline (aa:pt (- cwx) cwy) (aa:pt cwx cwy) aa:*lay-elevator*)
  (aa:mkline (aa:pt cwx cwy) (aa:pt cwx (+ cwy (float cw_d))) aa:*lay-elevator*)
  (aa:mkline (aa:pt cwx (+ cwy (float cw_d)))
             (aa:pt (- cwx) (+ cwy (float cw_d))) aa:*lay-elevator*)
  (aa:mkline (aa:pt (- cwx) (+ cwy (float cw_d)))
             (aa:pt (- cwx) cwy) aa:*lay-elevator*)
  (aa:hs))
