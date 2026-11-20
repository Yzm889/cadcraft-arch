;;; ============================================================
;;; 门窗  (aa_opening.lisp)   依赖 aa_core.lisp
;;; 块定义：AA_OPENING_<ID>
;;; 本地坐标与所属墙一致：原点=墙起点，+X=沿墙方向，+Y=墙法向
;;; 因此块参照用"墙起点 + 墙旋转角"插入，门窗必然贴墙
;;; ============================================================

;; (aa:win-frame thick frame) -> 窗框厚
;; 制图惯例：窗框厚是构造尺寸（默认 60，可逐樘给定），不随墙厚等比缩放；
;; 太薄的墙兜底为"半墙厚减 10"，避免内线贴到墙中线。
(defun aa:win-frame (thick frame / half f)
  (setq half (/ (float thick) 2.0)
        f (float frame))
  (if (> f (- half 10.0)) (- half 10.0) f))

;; (aa:opening pos width thick kind frame label lrot side leader)
;;   pos   = 洞口中心到墙起点的距离
;;   width = 洞口宽度
;;   thick = 所属墙厚
;;   kind  = "DOOR" / "WINDOW" / "DOORWIN"
;;   frame = 窗框厚（门忽略）
;;   label = 门窗编号文字（空串则不写）
;;   lrot  = 编号文字的附加旋转（弧度，墙块转 180° 时传 3.14159 抵消倒字）
;;   side  = 编号所在侧：-1 = 本地 -Y 侧，+1 = 本地 +Y 侧（由驱动层按室内/室外换算）
;;   leader= 1 时编号外移 8mm 并加一条 45° 引线指向洞口右侧墙中点（天正"引线编号"）
;; 返回 "pos#width"
(defun aa:opening (pos width thick kind frame label lrot side leader
                   / x1 x2 half inner lw lh ly lx)
  (aa:begin)
  (setq pos (float pos)
        width (float width)
        thick (float thick)
        x1 (- pos (/ width 2.0))
        x2 (+ pos (/ width 2.0))
        half (/ thick 2.0)
        inner (- half (aa:win-frame thick frame)))

  ;; 洞口两侧竖线（垂直于墙）
  (aa:mkline (aa:pt x1 (- half)) (aa:pt x1 half) aa:*lay-opening*)
  (aa:mkline (aa:pt x2 (- half)) (aa:pt x2 half) aa:*lay-opening*)

  (if (= kind "WINDOW")
      ;; 窗：四条平行细实线（GB/T 50104 门窗图例）——
      ;; 贴墙面两条 = 窗框外沿（与墙面平齐），内侧两条 = 窗框内沿（内退 frame）
      (progn
        (aa:mkline (aa:pt x1 half) (aa:pt x2 half) aa:*lay-opening*)
        (aa:mkline (aa:pt x1 (- half)) (aa:pt x2 (- half)) aa:*lay-opening*)
        (aa:mkline (aa:pt x1 inner) (aa:pt x2 inner) aa:*lay-opening*)
        (aa:mkline (aa:pt x1 (- inner)) (aa:pt x2 (- inner)) aa:*lay-opening*))
      ;; 门：合页落在墙面（+Y 侧内表面）上，门扇从墙面起画，不穿墙身
      (progn
        (aa:mkline (aa:pt x1 half) (aa:pt x1 (+ half width)) aa:*lay-opening*)
        (aa:mkarc (aa:pt x1 half) width 0.0 1.5707963267948966 aa:*lay-opening*)))

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
