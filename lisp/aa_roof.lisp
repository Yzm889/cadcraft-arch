;;; ============================================================
;;; 屋顶平面  (aa_roof.lisp)   依赖 aa_core.lisp
;;; kind = 0 平屋顶（檐沟 + 雨水口 + 找坡箭头）
;;;        1 双坡（正脊 + 两侧檐口找坡箭头）
;;;        2 四坡（正脊 + 四条 45° 斜脊 + 找坡箭头）
;;;        3 单坡（一侧檐沟 + 单向找坡箭头）
;;; 本地原点 = 屋面投影（建筑轮廓）左下角，+X 沿长度、+Y 沿进深
;;; oh = 檐口外挑，gut = 檐沟宽，ridgex = 1 屋脊沿 X / 0 沿 Y
;;; 未做：天沟、女儿墙压顶、上人孔、屋面分格、坡度文字
;;; ============================================================

;; 闭合矩形（一条多段线）
(defun aa:rectpl (x1 y1 x2 y2 lay)
  (aa:mkpline (list (aa:pt x1 y1) (aa:pt x2 y1)
                    (aa:pt x2 y2) (aa:pt x1 y2)
                    (aa:pt x1 y1)) lay))

;; 实心三角箭头（屋顶专用，避免依赖 aa_stair.lisp）
(defun aa:rhd (tx ty bx by hw lay / )
  (entmake (list (cons 0 "SOLID") (cons 8 lay)
                 (cons 10 (list tx ty 0.0))
                 (cons 11 (list (- bx hw) by 0.0))
                 (cons 12 (list (+ bx hw) by 0.0))
                 (cons 13 (list (+ bx hw) by 0.0))))
  (aa:record (aa:hlast)))

;; 找坡箭头：从 (x1,y1) 画到 (x2,y2)，箭头尖在终点（指向下坡/檐沟）
(defun aa:slopearrow (x1 y1 x2 y2 hw lay / len ux uy bx by)
  (setq len (sqrt (+ (* (- x2 x1) (- x2 x1)) (* (- y2 y1) (- y2 y1)))))
  (if (< len 1.0)
      nil
      (progn
        (setq ux (/ (- x2 x1) len) uy (/ (- y2 y1) len))
        (setq bx (- x2 (* 3.0 hw ux)) by (- y2 (* 3.0 hw uy)))
        (aa:mkline (aa:pt x1 y1) (aa:pt bx by) lay)
        (aa:rhd x2 y2 bx by hw lay))))

;; 单个雨水口：方形篦子（边宽 ds），四条线拼方框
(defun aa:drain (cx cy ds lay / h)
  (setq h (/ ds 2.0))
  (aa:rectpl (- cx h) (- cy h) (+ cx h) (+ cy h) lay)
  (aa:mkline (aa:pt (- cx h) cy) (aa:pt (+ cx h) cy) lay))

(defun aa:roof (w d oh gut kind ridgex h /
                ox1 oy1 ox2 oy2 gx1 gy1 gx2 gy2 ow od cx cy m hw)
  (setq ox1 (- 0.0 oh) oy1 (- 0.0 oh)
        ox2 (+ w oh) oy2 (+ d oh))
  (setq gx1 (+ ox1 gut) gy1 (+ oy1 gut)
        gx2 (- ox2 gut) gy2 (- oy2 gut))
  (setq ow (- ox2 ox1)
        od (- oy2 oy1)
        cx (/ (+ ox1 ox2) 2.0)
        cy (/ (+ oy1 oy2) 2.0))
  (setq hw (* 0.7 h))

  ;; 檐口外轮廓（所有类型都画）
  (aa:rectpl ox1 oy1 ox2 oy2 aa:*lay-roof*)

  (if (= kind 0)
      ;; ---- 平屋顶：檐沟 + 四角雨水口 + 南北找坡 ----
      (progn
        (aa:rectpl gx1 gy1 gx2 gy2 aa:*lay-roof*)
        (aa:drain gx1 gy1 300.0 aa:*lay-roof*)
        (aa:drain gx2 gy1 300.0 aa:*lay-roof*)
        (aa:drain gx1 gy2 300.0 aa:*lay-roof*)
        (aa:drain gx2 gy2 300.0 aa:*lay-roof*)
        (aa:slopearrow cx cy cx gy1 hw aa:*lay-roofarrow*)
        (aa:slopearrow cx cy cx gy2 hw aa:*lay-roofarrow*))
      (if (= kind 1)
          ;; ---- 双坡：正脊（贯到檐口） + 两坡找坡箭头 ----
          (progn
            (if (= ridgex 1)
                (progn
                  (aa:mkline (aa:pt ox1 cy) (aa:pt ox2 cy) aa:*lay-roof*)
                  (aa:slopearrow cx (- cy (* 0.12 od)) cx oy1 hw aa:*lay-roofarrow*)
                  (aa:slopearrow cx (+ cy (* 0.12 od)) cx oy2 hw aa:*lay-roofarrow*))
                (progn
                  (aa:mkline (aa:pt cx oy1) (aa:pt cx oy2) aa:*lay-roof*)
                  (aa:slopearrow (- cx (* 0.12 ow)) cy ox1 cy hw aa:*lay-roofarrow*)
                  (aa:slopearrow (+ cx (* 0.12 ow)) cy ox2 cy hw aa:*lay-roofarrow*))))
          (if (= kind 2)
              ;; ---- 四坡：正脊 + 四条 45° 斜脊（都落在檐口外轮廓上） ----
              (progn
                (setq m (/ (if (< ow od) ow od) 2.0))
                (if (>= ow od)
                    (progn
                      (aa:mkline (aa:pt (+ ox1 m) cy) (aa:pt (- ox2 m) cy) aa:*lay-roof*)
                      (aa:mkline (aa:pt ox1 oy1) (aa:pt (+ ox1 m) cy) aa:*lay-roof*)
                      (aa:mkline (aa:pt ox1 oy2) (aa:pt (+ ox1 m) cy) aa:*lay-roof*)
                      (aa:mkline (aa:pt ox2 oy1) (aa:pt (- ox2 m) cy) aa:*lay-roof*)
                      (aa:mkline (aa:pt ox2 oy2) (aa:pt (- ox2 m) cy) aa:*lay-roof*)
                      (aa:slopearrow cx (- cy (* 0.12 od)) cx oy1 hw aa:*lay-roofarrow*)
                      (aa:slopearrow cx (+ cy (* 0.12 od)) cx oy2 hw aa:*lay-roofarrow*))
                    (progn
                      (aa:mkline (aa:pt cx (+ oy1 m)) (aa:pt cx (- oy2 m)) aa:*lay-roof*)
                      (aa:mkline (aa:pt ox1 oy1) (aa:pt cx (+ oy1 m)) aa:*lay-roof*)
                      (aa:mkline (aa:pt ox2 oy1) (aa:pt cx (+ oy1 m)) aa:*lay-roof*)
                      (aa:mkline (aa:pt ox1 oy2) (aa:pt cx (- oy2 m)) aa:*lay-roof*)
                      (aa:mkline (aa:pt ox2 oy2) (aa:pt cx (- oy2 m)) aa:*lay-roof*)
                      (aa:slopearrow (- cx (* 0.12 ow)) cy ox1 cy hw aa:*lay-roofarrow*)
                      (aa:slopearrow (+ cx (* 0.12 ow)) cy ox2 cy hw aa:*lay-roofarrow*))))
              ;; ---- 单坡：低端檐沟 + 单向找坡 ----
              (progn
                (aa:rectpl ox1 oy1 ox2 (+ oy1 gut) aa:*lay-roof*)
                (aa:slopearrow cx (+ oy1 (* 0.85 od)) cx gy1 hw aa:*lay-roofarrow*))))))
