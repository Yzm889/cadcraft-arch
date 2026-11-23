;;; ============================================================
;;; 楼梯  (aa_stair.lisp)   依赖 aa_core.lisp / aa_symbol.lisp
;;; 直跑：踏步线 + 两侧梯段边线 + 贯穿箭头 + 起步"上"字
;;; 双跑 U 形（对齐天正"双跑楼梯"的做法）：
;;;   level = 0 中层：两跑全画 + 第一跑 45° 折断线 + "上""下"
;;;   level = 1 首层：只画上行第一跑，踏步按 45° 折断线裁剪
;;;   level = 2 顶层：两跑全画，只画沿第二跑的"下"箭头
;;;   sgn = 1 上楼在左 / -1 上楼在右（整体左右镜像）
;;; 本地原点 = 楼梯间起步边（楼面一跑踏步前缘）中点，+Y 为上行方向，
;;; 总进深 dep = run + landing（两跑并排，平台在尽端）。
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

;; 梯井（天正做法）：一条封闭的"跑道"形线，两端带小圆角
;; (aa:well xc ytop ybot hw lay)
(defun aa:well (xc ytop ybot hw lay / c pts)
  (setq c (* 0.55 hw))
  (setq pts (list
    (list (- xc hw) (+ ybot c) 0.0)
    (list (+ (- xc hw) c) ybot 0.0)
    (list (- (+ xc hw) c) ybot 0.0)
    (list (+ xc hw) (+ ybot c) 0.0)
    (list (+ xc hw) (- ytop c) 0.0)
    (list (- (+ xc hw) c) ytop 0.0)
    (list (+ (- xc hw) c) ytop 0.0)
    (list (- xc hw) (- ytop c) 0.0)
    (list (- xc hw) (+ ybot c) 0.0)))
  (aa:mkpline pts lay))

;; (aa:stair-label x y s lh trot lay) —— "上"/"下"标注
;; 把字的**可见左下角**对齐到 (x, y)：trot = 180° 时块内文字反向生长，
;; 插入点要先右移、上移一个字高，否则字会跑到梯段外面压住边线。
(defun aa:stair-label (x y s lh trot lay)
  (if (> (abs (float trot)) 1.0)
      (aa:mktext-r (aa:pt (+ (float x) (float lh)) (+ (float y) (float lh)))
                   s lay lh trot)
      (aa:mktext-r (aa:pt x y) s lay lh trot)))

;; 直跑：(aa:stair-straight w steps tread lh trot)
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
  (aa:mkline (aa:pt 0.0 (* -0.45 lh)) (aa:pt 0.0 run) aa:*lay-stairarrow*)
  (aa:arrowhead (aa:pt 0.0 mid) (aa:pt 0.0 (- mid 320.0)) 80.0 aa:*lay-stairarrow*)
  (aa:stair-label (* 0.7 lh) (* 0.10 (float tread)) "上" lh trot aa:*lay-stairtext*)
  (aa:hs))

;; 双跑：(aa:stair-dogleg w steps tread well landing lh trot level sgn)
(defun aa:stair-dogleg (w steps tread well landing lh trot level sgn /
                        wtot dep run p k y hl xlL xlR xrL xrR xl xr
                        t1 s e cutL cutR xa yT lw)
  (aa:begin)
  (setq wtot (+ (* 2.0 w) well)
        run (* (float steps) (float tread))
        p (float landing)
        dep (+ p run)
        hl (/ wtot 2.0)
        xlL (- hl)
        xlR (+ (- hl) (float w))
        xrL (- hl (float w))
        xrR hl
        xl (/ (+ xlL xlR) 2.0)
        xr (/ (+ xrL xrR) 2.0)
        t1 (float tread)
        s (float sgn)
        e (* 0.40 (float tread))
        ;; 折断线左下端高度：默认切在 30% 处；两端各留一级，保证 45° 斜线落在跑内
        cutL (* 0.30 run))
  (if (> cutL (- run t1)) (setq cutL (- run t1)))
  (if (< cutL t1) (setq cutL t1))
  (setq cutR (+ cutL (float w)))
  (if (> cutR run) (setq cutR run))

  (if (= level 1)
      ;; ---------- 首层：只画上行第一跑，踏步按 45° 折断线裁剪 ----------
      ;; 折断线左低右高（45°），左端在 cutL、右端在 cutR = cutL + w；
      ;; 线的左边是"被切掉的上部"，踏步到线为止，箭头也止在线上。
      (progn
        (aa:mkline (aa:pt (* s xlL) 0.0) (aa:pt (* s xlL) cutL) aa:*lay-stair*)
        (aa:mkline (aa:pt (* s xlR) 0.0) (aa:pt (* s xlR) cutR) aa:*lay-stair*)
        (setq k 1)
        (while (<= k steps)
          (setq y (* k t1))
          (if (<= y cutR)
              (progn
                (setq xa xlL)
                (if (> y cutL) (setq xa (+ xlL (- y cutL))))
                (if (> (- xlR xa) (* 0.20 t1))
                    (aa:mkline (aa:pt (* s xa) y) (aa:pt (* s xlR) y)
                               aa:*lay-stair*))))
          (setq k (+ k 1)))
        (aa:breakline (* s (- xlL e)) (- cutL e)
                      (* s (+ xlR e)) (+ cutR e)
                      aa:*lay-stairbreak* (* 0.55 lh))
        ;; 上行箭头：从楼面外侧起，止在折断线前（不越出被切掉的区域）
        (setq yT (+ cutL (* 0.5 (float w))))
        (aa:mkline (aa:pt (* s xl) (* -0.45 lh)) (aa:pt (* s xl) yT)
                   aa:*lay-stairarrow*)
        (aa:arrowhead (aa:pt (* s xl) yT) (aa:pt (* s xl) (- yT 320.0))
                      80.0 aa:*lay-stairarrow*)
        (aa:stair-label (+ (* s xl) (* 0.7 lh)) (* 0.10 t1)
                        "上" lh trot aa:*lay-stairtext*))
    (progn
      ;; ---------- 中层 / 顶层共用的两跑图：外轮廓 + 平台分界 + 梯井 + 踏步 ----------
      (aa:mkline (aa:pt (* s xlL) 0.0) (aa:pt (* s xlL) dep) aa:*lay-stair*)
      (aa:mkline (aa:pt (* s xrR) 0.0) (aa:pt (* s xrR) dep) aa:*lay-stair*)
      (aa:mkline (aa:pt (* s xlL) 0.0) (aa:pt (* s xrR) 0.0) aa:*lay-stair*)
      (aa:mkline (aa:pt (* s xlL) dep) (aa:pt (* s xrR) dep) aa:*lay-stair*)
      (aa:mkline (aa:pt (* s xlL) run) (aa:pt (* s xrR) run) aa:*lay-stair*)
      ;; 梯井只到平台内边（平台是整块板，井不穿过去）
      (aa:well 0.0 run 0.0 (/ (float well) 2.0) aa:*lay-stair*)
      (setq k 1)
      (while (<= k steps)
        (setq y (* k t1))
        (aa:mkline (aa:pt (* s xlL) y) (aa:pt (* s xlR) y) aa:*lay-stair*)
        (aa:mkline (aa:pt (* s xrL) y) (aa:pt (* s xrR) y) aa:*lay-stair*)
        (setq k (+ k 1)))
      (setq yT (- dep (* 0.30 p)))
      (if (= level 2)
          ;; ---------- 顶层：只有"下"，沿第二跑从平台指向楼面 ----------
          (progn
            (aa:mkline (aa:pt (* s xr) yT) (aa:pt (* s xr) (* 0.30 lh))
                       aa:*lay-stairarrow*)
            (aa:arrowhead (aa:pt (* s xr) (* 0.30 lh))
                          (aa:pt (* s xr) (+ (* 0.30 lh) 320.0))
                          80.0 aa:*lay-stairarrow*)
            (aa:stair-label (+ (* s xr) (* 0.7 lh)) (* 0.10 t1)
                            "下" lh trot aa:*lay-stairtext*))
        ;; ---------- 中层：折断线横切上行跑 + "绕一圈"箭头（上→平台→下） ----------
        (progn
          (aa:breakline (* s (- xlL e)) (- cutL e)
                        (* s (+ xlR e)) (+ cutR e)
                        aa:*lay-stairbreak* (* 0.55 lh))
          (aa:mkline (aa:pt (* s xl) (* -0.45 lh)) (aa:pt (* s xl) yT)
                     aa:*lay-stairarrow*)
          (aa:mkline (aa:pt (* s xl) yT) (aa:pt (* s xr) yT) aa:*lay-stairarrow*)
          (aa:mkline (aa:pt (* s xr) yT) (aa:pt (* s xr) (* 0.30 lh))
                     aa:*lay-stairarrow*)
          (aa:arrowhead (aa:pt (* s xl) (* 0.55 run))
                        (aa:pt (* s xl) (- (* 0.55 run) 320.0))
                        80.0 aa:*lay-stairarrow*)
          (aa:arrowhead (aa:pt (* s xr) (* 0.30 lh))
                        (aa:pt (* s xr) (+ (* 0.30 lh) 320.0))
                        80.0 aa:*lay-stairarrow*)
          (aa:stair-label (+ (* s xl) (* 0.7 lh)) (* 0.10 t1)
                          "上" lh trot aa:*lay-stairtext*)
          (aa:stair-label (+ (* s xr) (* 0.7 lh)) (* 0.10 t1)
                          "下" lh trot aa:*lay-stairtext*)))))
  (aa:hs))
