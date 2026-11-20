;;; ============================================================
;;; 房间  (aa_room.lisp)   依赖 aa_core.lisp
;;; 块定义：AA_ROOM_<ID>
;;; 几何：房间名称 TEXT（不再画轮廓线：轮廓与墙内表面完全重合，
;;;       画出来会被误读成"墙线"，而且会横穿门窗洞口）
;;; 轮廓点由驱动层按"墙中心线内偏移半墙厚"算好后传入，仅用于面积/名称定位
;;; ============================================================

(defun aa:centroid (pts / n i sx sy p)
  (setq n (length pts) i 0 sx 0.0 sy 0.0)
  (while (< i n)
    (setq p (nth i pts)
          sx (+ sx (aa:px p))
          sy (+ sy (aa:py p))
          i (1+ i)))
  (list (/ sx n) (/ sy n) 0.0))

;; (aa:room pts name)
;; 返回 "area#perimeter"
(defun aa:room (pts name / area per c)
  (aa:begin)
  (setq area (aa:polyarea pts)
        per (aa:polyperim pts)
        c (aa:centroid pts))
  (if (> (strlen name) 0)
    (aa:mktext c name aa:*lay-room* aa:*room-h*))
  (strcat (rtos area 2 2) "#" (rtos per 2 2)))
