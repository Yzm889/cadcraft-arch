;;; ============================================================
;;; 墙体求交  (aa_intersect.lisp)   依赖 aa_core.lisp
;;; 输入：墙段表，形如 (list (list "W001" p1 p2) ...)
;;; 输出：交点串 "id1|id2|t1|t2|x|y;id1|id2|..."
;;;       t1/t2 为交点在两段上的参数（0..1），只保留落在两段内部的情况
;;; ============================================================

(defun aa:xsec (segs / i j n a b r pt t1 t2 out id1 id2 s)
  (setq n (length segs) i 0 out nil)
  (while (< i n)
    (setq j (1+ i))
    (while (< j n)
      (setq a (nth i segs)
            b (nth j segs)
            r (aa:segint (nth 1 a) (nth 2 a) (nth 1 b) (nth 2 b)))
      (if r
          (progn
            (setq pt (car r) t1 (nth 1 r) t2 (nth 2 r)
                  id1 (nth 0 a) id2 (nth 0 b))
            ;; 只要有一方是"内部相交"就记录；端点相接（T 形首尾）不记录
            (if (or (and (> t1 1e-6) (< t1 (- 1.0 1e-6)))
                    (and (> t2 1e-6) (< t2 (- 1.0 1e-6))))
                (setq out (cons (strcat id1 "|" id2 "|"
                                       (rtos t1 2 10) "|" (rtos t2 2 10) "|"
                                       (rtos (car pt) 2 4) "|" (rtos (nth 1 pt) 2 4))
                                out)))
            nil)
          nil)
      (setq j (1+ j)))
    (setq i (1+ i)))
  (setq s "")
  (foreach rec (reverse out)
    (if (= s "") (setq s rec) (setq s (strcat s ";" rec))))
  s)
