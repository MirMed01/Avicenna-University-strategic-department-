"""«Паутинка» здоровья: координаты для SVG по результатам проверки (шкала 0–100 %)."""

import math

SIZE, CX, CY, R = 440, 220, 200, 140


def _pt(i, n, v):
    a = -math.pi / 2 + i * 2 * math.pi / n
    return CX + R * v / 100 * math.cos(a), CY + R * v / 100 * math.sin(a)


def radar(results):
    rows = [r for r in results if r.value is not None]
    if len(rows) < 3:
        return None  # из двух точек «паутинку» не построить — показываем только таблицу
    n = len(rows)
    clamp = lambda v: max(0, min(100, float(v)))
    axes = []
    for i, r in enumerate(rows):
        x, y = _pt(i, n, 100)
        lx, ly = _pt(i, n, 116)
        vx, vy = _pt(i, n, clamp(r.value))
        anchor = "middle" if abs(lx - CX) < 5 else ("start" if lx > CX else "end")
        # Координаты — готовыми строками с точкой: шаблон в русской локали поставил бы запятую и сломал SVG.
        f = lambda v: "%.1f" % v
        axes.append({"x": f(x), "y": f(y), "lx": f(lx), "ly": f(ly + 4), "anchor": anchor, "label": r.title.split(" ", 1)[0],
                     "vx": f(vx), "vy": f(vy), "status": r.status, "title": r.title, "value": r.value})
    rings = [" ".join("%.1f,%.1f" % _pt(i, n, v) for i in range(n)) for v in (25, 50, 75, 100)]
    value_poly = " ".join(f'{a["vx"]},{a["vy"]}' for a in axes)
    thr = [r.expected_threshold for r in rows]
    thr_poly = None
    if all(t is not None for t in thr):
        thr_poly = " ".join("%.1f,%.1f" % _pt(i, n, clamp(t)) for i, t in enumerate(thr))
    return {"size": SIZE, "cx": CX, "cy": CY, "axes": axes, "rings": rings, "value_poly": value_poly, "thr_poly": thr_poly}
