;;; ============================================================
;;; 轴网  (aa_axis.lisp)   依赖 aa_core.lisp
;;; 块定义：AA_AXGRID_<ID>
;;; 几何：纵/横轴线（点划线）+ 轴号圆圈 + 圈内轴号
;;; 轴号按 GB/T 50104：细实线圆，直径 8mm（1:100 出图 => 800 单位），圆与轴线端相切，
;;; 编号写在圈内、字高 3mm（=> 300 单位）
;;; ============================================================

;; 序号 -> 字母轴号（1 -> A）
(defun aa:letter (i / alpha)
  (setq alpha "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
  (if (and (> i 0) (<= i 26))
      (substr alpha i 1)
      (strcat "A" (itoa i))))

;; 把轴号列表拼成 "A;B;C"
(defun aa:joinc (lst / s)
  (setq s "")
  (foreach x lst
    (if (= s "") (setq s x) (setq s (strcat s ";" x))))
  s)

;; (aa:axistag cx cy str)
;;   在 (cx,cy) 画轴号圆圈 + 圈内居中文字
(defun aa:axistag (cx cy str / w tx ty)
  (setq w (* 0.62 aa:*axis-h* (float (strlen str)))   ; 字宽粗估：0.62 * 字高 * 字数
        tx (- cx (/ w 2.0))
        ty (- cy (/ aa:*axis-h* 2.0)))
  (aa:mkcircle (aa:pt cx cy) aa:*axis-r* aa:*lay-axistext*)
  (aa:mktext (aa:pt tx ty) str aa:*lay-axistext* aa:*axis-h*))

;; (aa:axis id xcount xspace ycount yspace xstart ystart ext)
;;   xcount/xspace  = 纵向轴线（沿 X 排列）的数量与间距
;;   ycount/yspace  = 横向轴线（沿 Y 排列）的数量与间距
;;   ext            = 轴线两端伸出墙外皮的尺寸
;; 返回 "VER#HOR"（几何句柄由驱动层用快照差分取，LISP 不依赖 entlast）
(defun aa:axis (id xcount xspace ycount yspace xstart ystart ext
                / i j x y top right cx cy vlab hlab vl hl)
  (aa:begin)
  (setq xstart (float xstart) ystart (float ystart)
        xspace (float xspace) yspace (float yspace) ext (float ext)
        top (+ ystart (* (- ycount 1) yspace))
        right (+ xstart (* (- xcount 1) xspace))
        vl nil hl nil)

  ;; 纵向轴线（竖线）+ 顶端数字轴号 1、2、3（GB/T 50001：竖向轴线编数字）
  (setq i 0)
  (while (< i xcount)
    (setq x (+ xstart (* i xspace)))
    (aa:mkline-lt (aa:pt x (- ystart ext))
               (aa:pt x (+ top ext))
               aa:*lay-axis* "CENTER")
    (setq cy (+ top ext aa:*axis-r*))              ; 圆与轴线端相切
    (aa:axistag x cy (itoa (1+ i)))
    (setq vl (cons (itoa (1+ i)) vl))
    (setq i (1+ i)))

  ;; 横向轴线（横线）+ 左端字母轴号 A、B、C（横向轴线编字母）
  (setq j 0)
  (while (< j ycount)
    (setq y (+ ystart (* j yspace)))
    (aa:mkline-lt (aa:pt (- xstart ext) y)
               (aa:pt (+ right ext) y)
               aa:*lay-axis* "CENTER")
    (setq cx (- xstart ext aa:*axis-r*))
    (aa:axistag cx y (aa:letter (1+ j)))
    (setq hl (cons (aa:letter (1+ j)) hl))
    (setq j (1+ j)))

  (strcat (aa:joinc (reverse vl)) "#" (aa:joinc (reverse hl))))
