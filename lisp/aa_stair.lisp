;;; ============================================================
;;; 楼梯  (aa_stair.lisp)   依赖 aa_core.lisp
;;; 直跑：踏步线 + 两侧梯段边线 + 上行箭头（实心三角头）
;;; 双跑（U 形）：外轮廓 + 上下平台分界线 + 中间梯井 + 两跑踏步线
;;;              左跑上行、右跑下行，箭头方向相反
;;; 块定义：AA_STAIR_<ID>；本地原点 = 起步踏步前缘中点，+Y 为上行方向
;;; 剖断线暂不画（README / 规格里注明）
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
(defun aa:stair-straight (w steps tread lh trot / hw run k y mid tw)
  (aa:begin)
  (setq hw (/ (float w) 2.0)
        run (* (float steps) (float tread))
        k 1)
  ;; 两侧梯段边线
  (aa:mkline (aa:pt (- hw) 0.0) (aa:pt (- hw) run) aa:*lay-stair*)
  (aa:mkline (aa:pt hw 0.0) (aa:pt hw run) aa:*lay-stair*)
  ;; 踏步线（最后一条即上端边线）
  (while (<= k steps)
    (setq y (* k (float tread)))
    (aa:mkline (aa:pt (- hw) y) (aa:pt hw y) aa:*lay-stair*)
    (setq k (+ k 1)))
  ;; 上行箭头（沿中心线，到梯段中部）
  (setq mid (* 0.55 run))
  (aa:mkline (aa:pt 0.0 0.0) (aa:pt 0.0 mid) aa:*lay-stair*)
  (aa:arrowhead (aa:pt 0.0 (+ mid 300.0)) (aa:pt 0.0 mid) 70.0 aa:*lay-stair*)
  ;; 起步处"上"字（水平写，块转 180° 时由 trot 抵消倒字）
  (aa:mktext-r (aa:pt 220.0 (- (/ (float tread) 2.0) (* 0.35 (float lh))))
               "上" aa:*lay-stair* lh trot)
  (aa:hs))

;; (aa:stair-dogleg w steps tread well landing)
;;   w=单跑梯段宽  well=梯井宽  landing=平台深
(defun aa:stair-dogleg (w steps tread well landing lh trot / wtot dep run p k y xl xr hl xlL xlR xrL xrR tw)
  (aa:begin)
  (setq wtot (+ (* 2.0 w) well)
        run (* (float steps) (float tread))
        p (float landing)
        dep (+ (* 2.0 p) run)
        hl (/ wtot 2.0)
        xlL (- hl)
        xlR (+ (- hl) (float w))     ;; 左跑右边界
        xrL (- hl (float w))         ;; 右跑左边界
        xrR hl
        xl (/ (+ xlL xlR) 2.0)       ;; 左跑中心
        xr (/ (+ xrL xrR) 2.0)       ;; 右跑中心
        k 1)
  ;; 外轮廓（贴墙的两侧 + 两端）
  (aa:mkline (aa:pt xlL 0.0) (aa:pt xlL dep) aa:*lay-stair*)
  (aa:mkline (aa:pt xrR 0.0) (aa:pt xrR dep) aa:*lay-stair*)
  (aa:mkline (aa:pt xlL 0.0) (aa:pt xrR 0.0) aa:*lay-stair*)
  (aa:mkline (aa:pt xlL dep) (aa:pt xrR dep) aa:*lay-stair*)
  ;; 上下平台分界线
  (aa:mkline (aa:pt xlL p) (aa:pt xrR p) aa:*lay-stair*)
  (aa:mkline (aa:pt xlL (+ p run)) (aa:pt xrR (+ p run)) aa:*lay-stair*)
  ;; 梯井两侧边线（只在中段）
  (aa:mkline (aa:pt (- (/ (float well) 2.0)) p) (aa:pt (- (/ (float well) 2.0)) (+ p run)) aa:*lay-stair*)
  (aa:mkline (aa:pt (/ (float well) 2.0) p) (aa:pt (/ (float well) 2.0) (+ p run)) aa:*lay-stair*)
  ;; 两跑踏步线（同一组 y，方向相反）
  (while (<= k steps)
    (setq y (+ p (* k (float tread))))
    (aa:mkline (aa:pt xlL y) (aa:pt xlR y) aa:*lay-stair*)
    (aa:mkline (aa:pt xrL y) (aa:pt xrR y) aa:*lay-stair*)
    (setq k (+ k 1)))
  ;; 左跑上行箭头（+Y）
  (aa:mkline (aa:pt xl p) (aa:pt xl (+ p (* 0.45 run))) aa:*lay-stair*)
  (aa:arrowhead (aa:pt xl (+ (+ p (* 0.45 run)) 300.0)) (aa:pt xl (+ p (* 0.45 run)))
                70.0 aa:*lay-stair*)
  ;; 右跑下行箭头（-Y）
  (aa:mkline (aa:pt xr (+ p run)) (aa:pt xr (- (+ p run) (* 0.45 run))) aa:*lay-stair*)
  (aa:arrowhead (aa:pt xr (- (- (+ p run) (* 0.45 run)) 300.0))
                (aa:pt xr (- (+ p run) (* 0.45 run))) 70.0 aa:*lay-stair*)
  ;; 起步处"上"字（左跑平台上方一点）
  (aa:mktext-r (aa:pt (+ xl 220.0) (- (+ p (/ (float tread) 2.0)) (* 0.35 (float lh))))
               "上" aa:*lay-stair* lh trot)
  (aa:hs))
