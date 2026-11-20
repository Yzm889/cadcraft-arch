;;; ============================================================
;;; 楼梯  (aa_stair.lisp)   依赖 aa_core.lisp / aa_symbol.lisp
;;; 直跑：踏步线 + 两侧梯段边线 + 实心箭头 + 起步"上"字
;;; 双跑 U 形（对齐天正"双跑楼梯"对话框的做法）：
;;;   level = 0 中层：两跑全画 + 剖断线 + "上""下"
;;;   level = 1 首层：只画上行第一跑，顶部 45° 剖断
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

;; (aa:stair-straight w steps tread lh trot)
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
  (aa:mkline (aa:pt 0.0 0.0) (aa:pt 0.0 mid) aa:*lay-stairarrow*)
  (aa:arrowhead (aa:pt 0.0 (+ mid 300.0)) (aa:pt 0.0 mid) 70.0 aa:*lay-stairarrow*)
  (aa:mktext-r (aa:pt 220.0 (- (/ (float tread) 2.0) (* 0.35 (float lh))))
               "上" aa:*lay-stairtext* lh trot)
  (aa:hs))

;; (aa:stair-dogleg w steps tread well landing lh trot level sgn)
(defun aa:stair-dogleg (w steps tread well landing lh trot level sgn /
                        wtot dep run p k y hl xlL xlR xrL xrR xl xr cut)
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
        xr (/ (+ xrL xrR) 2.0))

  (if (= level 1)
      ;; ---- 首层：只画上行第一跑，顶端 45° 剖断（不画上部平台与第二跑） ----
      (progn
        (setq cut run)
        (aa:mkline (aa:pt (* sgn xlL) 0.0) (aa:pt (* sgn xlL) cut) aa:*lay-stair*)
        (aa:mkline (aa:pt (* sgn xlR) 0.0) (aa:pt (* sgn xlR) (- cut (/ (float w) 2.0))) aa:*lay-stair*)
        (aa:mkline (aa:pt (* sgn xlR) (- cut (/ (float w) 2.0))) (aa:pt (* sgn xlL) cut) aa:*lay-stairbreak*)
        (setq k 1)
        (while (<= k steps)
          (setq y (* k (float tread)))
          (if (< y (- cut (/ (float w) 2.0)))
              (aa:mkline (aa:pt (* sgn xlL) y) (aa:pt (* sgn xlR) y) aa:*lay-stair*))
          (setq k (+ k 1)))
        (aa:mktext-r (aa:pt (* sgn (+ xl 220.0)) (- (/ (float tread) 2.0) (* 0.35 (float lh))))
                     "上" aa:*lay-stairtext* lh trot))
    (if (= level 2)
        ;; ---- 顶层：两跑全画，只标"下" ----
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
            (setq y (+ p (* k (float tread))))
            (aa:mkline (aa:pt (* sgn xlL) y) (aa:pt (* sgn xlR) y) aa:*lay-stair*)
            (aa:mkline (aa:pt (* sgn xrL) y) (aa:pt (* sgn xrR) y) aa:*lay-stair*)
            (setq k (+ k 1)))
          (aa:mkline (aa:pt (* sgn xr) (+ p run)) (aa:pt (* sgn xr) (- (+ p run) (* 0.45 run))) aa:*lay-stairarrow*)
          (aa:arrowhead (aa:pt (* sgn xr) (- (- (+ p run) (* 0.45 run)) 300.0))
                        (aa:pt (* sgn xr) (- (+ p run) (* 0.45 run))) 70.0 aa:*lay-stairarrow*)
          (aa:mktext-r (aa:pt (* sgn (- xr 220.0)) (- (/ (float tread) 2.0) (* 0.35 (float lh))))
                       "下" aa:*lay-stairtext* lh trot))
      ;; ---- 中层（默认）：两跑全画 + 剖断线 + 上/下 ----
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
          (setq y (+ p (* k (float tread))))
          (aa:mkline (aa:pt (* sgn xlL) y) (aa:pt (* sgn xlR) y) aa:*lay-stair*)
          (aa:mkline (aa:pt (* sgn xrL) y) (aa:pt (* sgn xrR) y) aa:*lay-stair*)
          (setq k (+ k 1)))
        (aa:mkline (aa:pt (* sgn xl) p) (aa:pt (* sgn xl) (+ p (* 0.45 run))) aa:*lay-stairarrow*)
        (aa:arrowhead (aa:pt (* sgn xl) (+ (+ p (* 0.45 run)) 300.0))
                      (aa:pt (* sgn xl) (+ p (* 0.45 run))) 70.0 aa:*lay-stairarrow*)
        (aa:mkline (aa:pt (* sgn xr) (+ p run)) (aa:pt (* sgn xr) (- (+ p run) (* 0.45 run))) aa:*lay-stairarrow*)
        (aa:arrowhead (aa:pt (* sgn xr) (- (- (+ p run) (* 0.45 run)) 300.0))
                      (aa:pt (* sgn xr) (- (+ p run) (* 0.45 run))) 70.0 aa:*lay-stairarrow*)
        (aa:mkline (aa:pt (* sgn xrL) (+ p (* 0.30 run)))
                   (aa:pt (* sgn xrR) (+ p (* 0.30 run) (float w))) aa:*lay-stairbreak*)
        (aa:mktext-r (aa:pt (* sgn (+ xl 220.0)) (- (/ (float tread) 2.0) (* 0.35 (float lh))))
                     "上" aa:*lay-stairtext* lh trot)
        (aa:mktext-r (aa:pt (* sgn (- xr 220.0)) (- (/ (float tread) 2.0) (* 0.35 (float lh))))
                     "下" aa:*lay-stairtext* lh trot))))
  (aa:hs))
