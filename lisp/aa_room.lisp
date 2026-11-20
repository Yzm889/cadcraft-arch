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

;; 字高（图元单位，1:100 的取值由驱动层按比例改写）
(setq aa:*room-h* 250.0)        ; 房间名 2.5mm
(setq aa:*room-area-h* 200.0)   ; 面积 2.0mm
(setq aa:*room-show-area* 1)    ; 1 = 名称下方注面积（天正默认）

;; (aa:room pts name)
;; 返回 "area#perimeter"
(defun aa:room (pts name / area per c area_txt)
  (aa:begin)
  (setq area (aa:polyarea pts)
        per (aa:polyperim pts)
        c (aa:centroid pts)
        area_txt (strcat (rtos (/ area 1000000.0) 2 2) "㎡"))
  (if (> (strlen name) 0)
    (aa:mktext (list (aa:px c) (+ (aa:py c) (* 0.75 aa:*room-h*)) 0.0)
               name aa:*lay-room* aa:*room-h*))
  (if (= aa:*room-show-area* 1)
    (aa:mktext (list (aa:px c) (- (aa:py c) (* 1.1 aa:*room-area-h*)) 0.0)
               area_txt aa:*lay-room* aa:*room-area-h*))
  (strcat (rtos area 2 2) "#" (rtos per 2 2)))
