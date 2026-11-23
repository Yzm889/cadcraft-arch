;;; ============================================================
;;; 门窗  (aa_opening.lisp)   依赖 aa_core.lisp
;;; 块定义：AA_OPENING_<ID>
;;; 本地坐标与所属墙一致：原点=墙起点，+X=沿墙方向，+Y=墙法向
;;; 因此块参照用"墙起点 + 墙旋转角"插入，门窗必然贴墙
;;;
;;; 三种平面图例（GB/T 50104）：
;;;   WINDOW  窗：洞口内四条平行细实线（贴墙面两条 + 内退窗框厚两条）
;;;   DOOR    平开门：门扇线（垂直墙面）+ 90° 开启弧；宽洞口按双扇画
;;;   DOORWIN 门连窗：一端门扇带开启弧，另一端固定窗四线，中间加中梃
;;; ============================================================

;; (aa:win-frame thick frame) -> 窗框厚
;; 制图惯例：窗框厚是构造尺寸（默认 60，可逐樘给定），不随墙厚等比缩放；
;; 太薄的墙兜底为"半墙厚减 10"，避免内线贴到墙中线。
(defun aa:win-frame (thick frame / half f)
  (setq half (/ (float thick) 2.0)
        f (float frame))
  (if (> f (- half 10.0)) (- half 10.0) f))

;; (aa:win4 x1 x2 half inner lay) —— 窗的四条平行线
;;   ±half  贴墙面（墙块在洞口处已断开，这里把墙面轮廓补回来）
;;   ±inner 内退一个窗框厚的窗框内沿
(defun aa:win4 (x1 x2 half inner lay)
  (aa:mkline (aa:pt x1 half) (aa:pt x2 half) lay)
  (aa:mkline (aa:pt x1 (- half)) (aa:pt x2 (- half)) lay)
  (aa:mkline (aa:pt x1 inner) (aa:pt x2 inner) lay)
  (aa:mkline (aa:pt x1 (- inner)) (aa:pt x2 (- inner)) lay))

;; (aa:door-leaf hx face wd jamb sgn lay) —— 单扇门
;;   hx   铰点沿墙坐标（洞口某一端）
;;   face 门扇所贴墙面 ±half
;;   wd   门扇宽（= 弧半径）
;;   jamb +1 铰点在洞口左端 / -1 右端；sgn +1 向本地 +Y 开 / -1 向 -Y 开
;; 画两条东西：门扇线（从铰点垂直墙面伸出 wd）+ 90° 开启弧（从闭合位到开启位）。
;; 弧的角度按"铰点端 + 开向"四种组合取：
;;   (+1,+1) 闭合沿 +X → 弧 0°→90°      (+1,-1) 闭合沿 +X → 弧 270°→360°
;;   (-1,+1) 闭合沿 -X → 弧 90°→180°    (-1,-1) 闭合沿 -X → 弧 180°→270°
(defun aa:door-leaf (hx face wd jamb sgn lay / a1 a2)
  (aa:mkline (aa:pt hx face) (aa:pt hx (+ (float face) (* (float sgn) (float wd)))) lay)
  (cond
    ((and (= jamb 1) (= sgn 1)) (setq a1 0.0 a2 1.5707963267948966))
    ((and (= jamb 1) (= sgn -1)) (setq a1 4.71238898038469 a2 6.283185307179586))
    ((and (= jamb -1) (= sgn 1)) (setq a1 1.5707963267948966 a2 3.141592653589793))
    (t (setq a1 3.141592653589793 a2 4.71238898038469)))
  (aa:mkarc (aa:pt hx face) (abs (float wd)) a1 a2 lay))

;; (aa:opening pos width thick kind frame label lrot side leader
;;             hinge swing doorpart leaves)
;;   pos      = 洞口中心到墙起点的距离
;;   width    = 洞口宽度
;;   thick    = 所属墙厚
;;   kind     = "DOOR" / "WINDOW" / "DOORWIN"
;;   frame    = 窗框厚（平开门忽略）
;;   label    = 门窗编号文字（空串则不写）
;;   lrot     = 编号文字的附加旋转（弧度，墙块转 180° 时传 3.14159 抵消倒字）
;;   side     = 编号所在侧：-1 = 本地 -Y 侧，+1 = 本地 +Y 侧（驱动层按室内/室外换算）
;;   leader   = 1 时编号外移并加一条引线指向洞口端部（天正"引线编号"）
;;   hinge    = ±1 铰点在洞口左端 / 右端（门、门连窗用）
;;   swing    = ±1 向本地 +Y / -Y 开
;;   doorpart = 门连窗里门扇宽度（<=0 时取洞口一半）
;;   leaves   = 1 单扇 / 2 双扇（门连窗与窗忽略）
;; 返回 "pos#width"
(defun aa:opening (pos width thick kind frame label lrot side leader
                   hinge swing doorpart leaves
                   / x1 x2 half inner lw lh ly lx dp dx)
  (aa:begin)
  (setq pos (float pos)
        width (float width)
        thick (float thick)
        x1 (- pos (/ width 2.0))
        x2 (+ pos (/ width 2.0))
        half (/ thick 2.0)
        inner (- half (aa:win-frame thick frame)))

  ;; 洞口两侧竖线（垂直于墙）——门、窗、门连窗都要
  (aa:mkline (aa:pt x1 (- half)) (aa:pt x1 half) aa:*lay-opening*)
  (aa:mkline (aa:pt x2 (- half)) (aa:pt x2 half) aa:*lay-opening*)

  (cond
    ;; ---- 窗：四条平行细实线 ----
    ((= kind "WINDOW")
     (aa:win4 x1 x2 half inner aa:*lay-opening*))

    ;; ---- 门连窗：门扇在一端（带开启弧），剩下的是固定窗，中间加中梃 ----
    ((= kind "DOORWIN")
     (setq dp (if (> (float doorpart) 0.0) (float doorpart) (/ width 2.0)))
     ;; 门扇宽夹在 20%~80% 洞口宽之间，保证门窗两部分都画得出来
     (if (< dp (* 0.2 width)) (setq dp (* 0.2 width)))
     (if (> dp (* 0.8 width)) (setq dp (* 0.8 width)))
     (if (= hinge 1) (setq dx (+ x1 dp)) (setq dx (- x2 dp)))
     (aa:door-leaf (if (= hinge 1) x1 x2) (* (float swing) half)
                   dp hinge swing aa:*lay-opening*)
     (if (= hinge 1)
         (aa:win4 dx x2 half inner aa:*lay-opening*)
         (aa:win4 x1 dx half inner aa:*lay-opening*))
     ;; 中梃：门与窗的分界，一条贴洞口的竖线
     (aa:mkline (aa:pt dx (- half)) (aa:pt dx half) aa:*lay-opening*))

    ;; ---- 平开门：双扇各占半宽，两个铰点分别落在洞口两端 ----
    ((= leaves 2)
     (aa:door-leaf (if (= hinge 1) x1 x2) (* (float swing) half)
                   (/ width 2.0) hinge swing aa:*lay-opening*)
     (aa:door-leaf (if (= hinge 1) x2 x1) (* (float swing) half)
                   (/ width 2.0) (- hinge) swing aa:*lay-opening*))

    ;; ---- 平开门：单扇 ----
    (t
     (aa:door-leaf (if (= hinge 1) x1 x2) (* (float swing) half)
                   width hinge swing aa:*lay-opening*)))

  ;; 门窗编号：默认写在洞口靠室内一侧墙面外 250，沿墙方向居中，字高 180
  ;; （side = -1 / +1 决定落在本地 -Y / +Y 侧，室内外由驱动层换算）。
  ;; 放在洞内会压住窗的四条线/门的门扇线，所以走墙外。
  ;; 文字转了 180° 时，插入点要沿侧向反向偏一个字高，可见框才仍贴墙居中。
  ;; leader=1：编号再外移 8mm，并从洞口右端墙中点拉一条 45° 引线到编号端部。
  (if (= label "")
      nil
      (progn
        (setq lw (* 0.62 aa:*label-h* (float (strlen label)))
              lh aa:*label-h*)
        (if (= leader 1)
            (progn
              (setq lx (+ x2 700.0)
                    ly (* (float side) (+ half 700.0)))
              (aa:mkline (aa:pt x2 (* (float side) half)) (aa:pt lx ly)
                         aa:*lay-opening*)
              (if (> (abs lrot) 1.0)
                  (if (> side 0.0)
                      (aa:mktext-r (aa:pt (+ lx lw 180.0) (+ ly lh 80.0)) label
                                   aa:*lay-opening* lh lrot)
                      (aa:mktext-r (aa:pt (+ lx lw 180.0) (- ly 80.0)) label
                                   aa:*lay-opening* lh lrot))
                  (if (> side 0.0)
                      (aa:mktext-r (aa:pt (+ lx 180.0) (+ ly 80.0)) label
                                   aa:*lay-opening* lh lrot)
                      (aa:mktext-r (aa:pt (+ lx 180.0) (- ly (+ lh 80.0))) label
                                   aa:*lay-opening* lh lrot))))
            (progn
              (setq ly (* (float side) (+ half 250.0)))
              (if (> (abs lrot) 1.0)
                  (aa:mktext-r (aa:pt (+ pos (/ lw 2.0)) (- ly (* (float side) lh)))
                               label aa:*lay-opening* lh lrot)
                  (aa:mktext-r (aa:pt (- pos (/ lw 2.0)) ly)
                               label aa:*lay-opening* lh lrot))))))

  (strcat (rtos pos 2 4) "#" (rtos width 2 4)))
