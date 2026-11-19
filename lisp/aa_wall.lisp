;;; ============================================================
;;; 墙体  (aa_wall.lisp)   依赖 aa_core.lisp
;;; 块定义：AA_WALL_<ID>
;;; 块内几何（局部坐标：起点 (0,0)，沿 +X）：
;;;   中心线 LWPOLYLINE  (0,0)->(L,0)
;;;   两侧墙线 LINE      —— 可由驱动层裁剪后传入 sides，避免墙线互相穿插
;;; 块参照插入点 = 墙起点，旋转 = 墙方向角，缩放恒为 1
;;; ============================================================

;; (aa:wall p1 p2 thick sides)
;;   sides = (list (list x1 y1 x2 y2) ...)，局部坐标的墙线段；nil 则画未裁剪的双侧线
;; 只画两侧墙面线，不画中心线（中心线是语义线，画出来会横穿门窗洞口）
;; 返回 "长度#方向角(弧度)"
(defun aa:wall (p1 p2 thick sides / len half s x1 y1 x2 y2)
  (aa:begin)
  (setq len (aa:dist p1 p2)
        half (/ (float thick) 2.0))
  (if sides
      (foreach s sides
        (setq x1 (nth 0 s) y1 (nth 1 s) x2 (nth 2 s) y2 (nth 3 s))
        (aa:mkline (aa:pt x1 y1) (aa:pt x2 y2) aa:*lay-wall*))
      (progn
        (aa:mkline (aa:pt 0.0 half) (aa:pt len half) aa:*lay-wall*)
        (aa:mkline (aa:pt 0.0 (- half)) (aa:pt len (- half)) aa:*lay-wall*)))
  (strcat (rtos len 2 4) "#" (rtos (aa:ang p1 p2) 2 10)))

;; 单侧墙线（无厚度显示，用于隔墙等场景）
(defun aa:wall-single (p1 p2 / len)
  (aa:begin)
  (setq len (aa:dist p1 p2))
  (aa:mkline (aa:pt 0.0 0.0) (aa:pt len 0.0) aa:*lay-wall*)
  (strcat (rtos len 2 4) "#" (rtos (aa:ang p1 p2) 2 10)))
