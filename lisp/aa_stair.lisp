;;; ============================================================
;;; 楼梯  (aa_stair.lisp)   依赖 aa_core.lisp / aa_symbol.lisp
;;; 直跑：踏步线 + 两侧梯段边线 + 贯穿箭头 + 起点"上"字
;;; 双跑 U 形（对齐天正"双跑楼梯"对话框的做法）：
;;;   level = 0 中层：两跑全画 + 折断线 + "上""下"
;;;   level = 1 首层：只画上行第一跑，左低右高的 45° 折断线
;;;   level = 2 顶层：两跑全画，只标"下"
;;;   sgn = 1 上楼在左 / -1 上楼在右（整体左右镜像）
;;; 本地原点 = 起步踏步前缘中点，+Y 为上行方向
;;; 未做：踏步取齐（齐平台/居中/齐楼板/自由）、疏散半径
;;; ============================================================

;; 实心三角箭头（SOLID）：尖点 p，底边中心 b，半宽 hw
(defun aa:arrowhead (p b hw lay / tip bl br)
  (setq tip p
        bl (list (- (car b) hw) (cadr b) 0.0)
        br (list (+ (car b) hw) (cadr b) 0.0))
  (entmake (list (cons 0 "SOLID") (cons 8 lay)
                 (cons 10 tip) (cons 11 bl) (cons 12 br) (cons 13 br)))
  (aa:record (aa:hlast)))

;; 折断线（天正的剖断符号）：斜线 + 中部"Z"形小折
(defun aa:breakline (x1 y1 x2 y2 lay h / dx dy xm ym xa ya xb yb)
  (setq dx (- x2 x1) dy (- y2 y1) xm (/ (+ x1 x2) 2.0) ym (/ (+ y1 y2) 2.0))
  (setq xa (- xm (* 0.18 dx)) ya (- ym (* 0.18 dy))
        xb (+ xm (* 0.34 dx)) yb (+ ym (* 0.34 dy)))
  (aa:mkline (aa:pt x1 y1) (aa:pt xa ya) lay)
  (aa:mkline (aa:pt xa ya) (aa:pt (+ xa (* 0.10 dx)) (+ ya h)) lay)
  (aa:mkline (aa:pt (+ xa (* 0.10 dx)) (+ ya h)) (aa:pt xb yb) lay)
  (aa:mkline (aa:pt xb yb) (aa:pt x2 y2) lay))

;; 直跑：(aa:stair-straight w steps tread lh (+ trot 1.5707963))
(defun aa:stair-straight (w steps tread lh trot / hw run k y mid)
  (aa:begin)
  (setq hw (/ (float w) 2.0)
        run (* (float steps) (float tread))
        k 1)
  (aa:mkline (aa:pt (- hw) 0.0) (aa:pt (- hw) run) aa:*lay-stair*)
  (aa:mkline (aa:pt hw 0.0) (aa:pt hw run) aa:*lay-stair*)
  (while (<= k steps)
    (setq y (* k (float tread)))
    (aa:mkline (aa:pt (- hw) y) (aa:pt hw y) aa:*lay-stair*)
    (setq k (+ k 1)))
  (setq mid (* 0.55 run))
  (aa:mkline (aa:pt 0.0 (* -0.12 run)) (aa:pt 0.0 run) aa:*lay-stairarrow*)
  (aa:arrowhead (aa:pt 0.0 mid) (aa:pt 0.0 (- mid 320.0)) 80.0 aa:*lay-stairarrow*)
  (aa:mktext-r (aa:pt (- (* 0.9 lh)) (* -1.05 lh)) "上" aa:*lay-stairtext* lh (+ trot 1.5707963))
  (aa:hs))

;; 双跑：(aa:stair-dogleg w steps tread well landing lh trot level sgn)
(defun aa:stair-dogleg (w steps tread well landing lh trot level sgn /
                        wtot dep run p k y hl xlL xlR xrL xrR xl xr cut t1)
  (aa:begin)
  (setq wtot (+ (* 2.0 w) well)
        run (* (float steps) (float tread))
        p (float landing)
        dep (+ (* 2.0 p) run)
        hl (/ wtot 2.0)
        xlL (- hl)
        xlR (+ (- hl) (float w))
        xrL (- hl (float w))
        xrR hl
        xl (/ (+ xlL xlR) 2.0)
        xr (/ (+ xrL xrR) 2.0)
        t1 (float tread))

  (if (= level 1)
      ;; ---- 首层：只画上行第一跑，左低右高的 45° 折断线切掉上部 ----
      (progn
        (setq cut (* 0.42 run))
        (aa:mkline (aa:pt (* sgn xlL) 0.0) (aa:pt (* sgn xlL) cut) aa:*lay-stair*)
        (aa:mkline (aa:pt (* sgn xlR) 0.0) (aa:pt (* sgn xlR) run) aa:*lay-stair*)
        (aa:breakline (* sgn (- xlL (* 0.40 t1))) (- cut (* 0.40 t1))
                      (* sgn (+ xlR (* 0.40 t1))) (+ run (* 0.40 t1))
                      aa:*lay-stairbreak* (* 0.55 lh))
        (setq k 1)
        (while (<= k steps)
          (setq y (* k t1))
          (if (< y cut)
              (aa:mkline (aa:pt (* sgn xlL) y) (aa:pt (* sgn xlR) y) aa:*lay-stair*))
          (setq k (+ k 1)))
        (aa:mkline (aa:pt (* sgn xl) (* -0.12 run)) (aa:pt (* sgn xl) run) aa:*lay-stairarrow*)
        (aa:arrowhead (aa:pt (* sgn xl) (* 0.55 run))
                      (aa:pt (* sgn xl) (- (* 0.55 run) 320.0)) 80.0 aa:*lay-stairarrow*)
        (aa:mktext-r (aa:pt (* sgn (- xl (* 0.9 lh))) (* -1.05 lh)) "上" aa:*lay-stairtext* lh (+ trot 1.5707963)))
    (if (= level 2)
        ;; ---- 顶层：两跑全画，只有"下" ----
        (progn
          (aa:mkline (aa:pt (* sgn xlL) 0.0) (aa:pt (* sgn xlL) dep) aa:*lay-stair*)
          (aa:mkline (aa:pt (* sgn xrR) 0.0) (aa:pt (* sgn xrR) dep) aa:*lay-stair*)
          (aa:mkline (aa:pt (* sgn xlL) 0.0) (aa:pt (* sgn xrR) 0.0) aa:*lay-stair*)
          (aa:mkline (aa:pt (* sgn xlL) dep) (aa:pt (* sgn xrR) dep) aa:*lay-stair*)
          (aa:mkline (aa:pt (* sgn xlL) p) (aa:pt (* sgn xrR) p) aa:*lay-stair*)
          (aa:mkline (aa:pt (* sgn xlL) (+ p run)) (aa:pt (* sgn xrR) (+ p run)) aa:*lay-stair*)
          (aa:mkline (aa:pt (* sgn xlR) p) (aa:pt (* sgn xlR) (+ p run)) aa:*lay-stair*)
          (aa:mkline (aa:pt (* sgn xrL) p) (aa:pt (* sgn xrL) (+ p run)) aa:*lay-stair*)
          (setq k 1)
          (while (<= k steps)
            (setq y (+ p (* k t1)))
            (aa:mkline (aa:pt (* sgn xlL) y) (aa:pt (* sgn xlR) y) aa:*lay-stair*)
            (aa:mkline (aa:pt (* sgn xrL) y) (aa:pt (* sgn xrR) y) aa:*lay-stair*)
            (setq k (+ k 1)))
          ;; 天正式"绕一圈"箭头：左跑上去 → 横穿上平台 → 右跑下来，第二跑带向下箭头
          (aa:mkline (aa:pt (* sgn xl) (* -0.12 run)) (aa:pt (* sgn xl) (- dep (* 0.25 p))) aa:*lay-stairarrow*)
          (aa:mkline (aa:pt (* sgn xl) (- dep (* 0.25 p))) (aa:pt (* sgn xr) (- dep (* 0.25 p))) aa:*lay-stairarrow*)
          (aa:mkline (aa:pt (* sgn xr) (- dep (* 0.25 p))) (aa:pt (* sgn xr) (* -0.12 run)) aa:*lay-stairarrow*)
          (aa:arrowhead (aa:pt (* sgn xr) (+ p (* 0.30 run)))
                        (aa:pt (* sgn xr) (+ p (* 0.30 run) 320.0)) 80.0 aa:*lay-stairarrow*)
          (aa:mktext-r (aa:pt (* sgn (- xr (* 0.9 lh))) (* -1.05 lh)) "下" aa:*lay-stairtext* lh (+ trot 1.5707963)))
      ;; ---- 中层（默认）：两跑全画 + 折断线 + 上/下 ----
      (progn
        (aa:mkline (aa:pt (* sgn xlL) 0.0) (aa:pt (* sgn xlL) dep) aa:*lay-stair*)
        (aa:mkline (aa:pt (* sgn xrR) 0.0) (aa:pt (* sgn xrR) dep) aa:*lay-stair*)
        (aa:mkline (aa:pt (* sgn xlL) 0.0) (aa:pt (* sgn xrR) 0.0) aa:*lay-stair*)
        (aa:mkline (aa:pt (* sgn xlL) dep) (aa:pt (* sgn xrR) dep) aa:*lay-stair*)
        (aa:mkline (aa:pt (* sgn xlL) p) (aa:pt (* sgn xrR) p) aa:*lay-stair*)
        (aa:mkline (aa:pt (* sgn xlL) (+ p run)) (aa:pt (* sgn xrR) (+ p run)) aa:*lay-stair*)
        (aa:mkline (aa:pt (* sgn xlR) p) (aa:pt (* sgn xlR) (+ p run)) aa:*lay-stair*)
        (aa:mkline (aa:pt (* sgn xrL) p) (aa:pt (* sgn xrL) (+ p run)) aa:*lay-stair*)
        (setq k 1)
        (while (<= k steps)
          (setq y (+ p (* k t1)))
          (aa:mkline (aa:pt (* sgn xlL) y) (aa:pt (* sgn xlR) y) aa:*lay-stair*)
          (aa:mkline (aa:pt (* sgn xrL) y) (aa:pt (* sgn xrR) y) aa:*lay-stair*)
          (setq k (+ k 1)))
        ;; 折断线横切上行跑中部，两端伸出梯段边线
        (aa:breakline (* sgn (- xlL (* 0.40 t1))) (+ p (* 0.32 run) (* -0.40 t1))
                      (* sgn (+ xlR (* 0.10 t1))) (+ p (* 0.32 run) w (* 0.35 t1))
                      aa:*lay-stairbreak* (* 0.55 lh))
        ;; 天正式"绕一圈"箭头：左跑上去 → 横穿上平台 → 右跑下来
        (aa:mkline (aa:pt (* sgn xl) (* -0.12 run)) (aa:pt (* sgn xl) (- dep (* 0.25 p))) aa:*lay-stairarrow*)
        (aa:mkline (aa:pt (* sgn xl) (- dep (* 0.25 p))) (aa:pt (* sgn xr) (- dep (* 0.25 p))) aa:*lay-stairarrow*)
        (aa:mkline (aa:pt (* sgn xr) (- dep (* 0.25 p))) (aa:pt (* sgn xr) (* -0.12 run)) aa:*lay-stairarrow*)
        (aa:arrowhead (aa:pt (* sgn xl) (+ p (* 0.55 run)))
                      (aa:pt (* sgn xl) (- (+ p (* 0.55 run)) 320.0)) 80.0 aa:*lay-stairarrow*)
        (aa:arrowhead (aa:pt (* sgn xr) (+ p (* 0.45 run)))
                      (aa:pt (* sgn xr) (- (+ p (* 0.45 run)) 320.0)) 80.0 aa:*lay-stairarrow*)
        (aa:mktext-r (aa:pt (* sgn (- xl (* 0.9 lh))) (* -1.05 lh)) "上" aa:*lay-stairtext* lh (+ trot 1.5707963))
        (aa:mktext-r (aa:pt (* sgn (- xr (* 0.9 lh))) (* -1.05 lh)) "下" aa:*lay-stairtext* lh (+ trot 1.5707963)))))
  (aa:hs))
