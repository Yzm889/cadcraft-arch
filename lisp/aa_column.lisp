;;; ============================================================
;;; 柱  (aa_column.lisp)   依赖 aa_core.lisp
;;; 矩形柱：实心 SOLID 填充 + 外框（天正柱子在平面上就是"实心块"）
;;; 圆柱：圆 + 内接多边形三角扇形填充（CADCraft 的 SOLID 是四点实心，
;;;       用退化四边形（第四点=第三点）拼成扇形）
;;; 块定义：AA_COLUMN_<ID>，本地原点 = 柱中心，+X 为柱宽方向
;;; ============================================================

;; (aa:column-rect w h ang)  以 (0,0) 为中心、绕中心转 ang 弧度
(defun aa:column-rect (w h ang / hw hh ca sa ux uy vx vy c1 c2 c3 c4)
  (aa:begin)
  (setq hw (/ (float w) 2.0)
        hh (/ (float h) 2.0)
        ca (cos ang)
        sa (sin ang)
        ux (* hw ca) uy (* hw sa)
        vx (* hh sa) vy (* hh ca)
        c1 (list (+ (- ux) vx) (- (- uy) vy) 0.0)
        c2 (list (+ ux vx) (- uy vy) 0.0)
        c3 (list (- ux vx) (+ uy vy) 0.0)
        c4 (list (- (- ux) vx) (+ (- uy) vy) 0.0))
  ;; 实心填充（10/11 一条边，12/13 对边，Z 序两两相对）
  (entmake (list (cons 0 "SOLID") (cons 8 aa:*lay-column*)
                 (cons 10 c1) (cons 11 c2) (cons 12 c4) (cons 13 c3)))
  (aa:record (aa:hlast))
  ;; 外框（与填充同层，保证线宽与墙一致）
  (aa:mkpline (list c1 c2 c3 c4) aa:*lay-column*)
  (aa:hs))

;; (aa:column-circle d)  以 (0,0) 为中心、直径 d
(defun aa:column-circle (d / r n i a da p q ctr)
  (aa:begin)
  (setq r (/ (float d) 2.0)
        n 24
        da (/ 6.283185307179586 n)
        ctr (list 0.0 0.0 0.0)
        i 0)
  ;; 扇形三角填充
  (while (< i n)
    (setq a (* i da)
          p (list (* r (cos a)) (* r (sin a)) 0.0)
          a (+ a da)
          q (list (* r (cos a)) (* r (sin a)) 0.0))
    (entmake (list (cons 0 "SOLID") (cons 8 aa:*lay-column*)
                   (cons 10 ctr) (cons 11 p) (cons 12 q) (cons 13 q)))
    (aa:record (aa:hlast))
    (setq i (+ i 1)))
  (aa:mkcircle (aa:pt 0.0 0.0) r aa:*lay-column*)
  (aa:hs))
