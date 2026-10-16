"""Классический анализ экзаменационного теста: трудность, различающая способность, варианты ответа, надёжность.

Формулы — общепринятые (руководства AMEE по анализу тестов): трудность p — доля верных ответов;
различающая способность — исправленная точечно-бисериальная корреляция задания с суммой остальных заданий
и разность долей верных в верхних и нижних 27 %; надёжность — KR-20 (для заданий «верно/неверно» совпадает
с альфой Кронбаха); стандартная ошибка измерения — SD × √(1 − α). Пороги — в «Настройках».
Личности студентов не нужны и не сохраняются: первый столбец файла только пропускается.
"""

import math

KEY_WORDS = {"ключ", "key", "калид", "ответ", "answer"}
MAX_ROWS, MAX_COLS = 3000, 400


class AnalysisError(ValueError):
    pass


def read_limited(ws):
    """Строки листа по одной, не больше MAX_ROWS и MAX_COLS: поддельный файл не займёт всю память (аудит 16.10.2026)."""
    rows = []
    for row in ws.iter_rows(values_only=True, max_col=MAX_COLS + 2):
        row = list(row)
        while row and row[-1] in (None, ""):  # пустые ячейки справа (лист дополняет ими строку)
            row.pop()
        if len(row) > MAX_COLS + 1 or len(rows) > MAX_ROWS + 2:  # первый столбец — номер студента; заголовок и ключ — запас
            raise AnalysisError("Слишком большой файл: не больше 3000 студентов и 400 заданий.")
        rows.append(row)
    return rows


def _norm(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip().upper()


def parse_rows(rows):
    """rows — список строк таблицы (первая — заголовки). Возвращает (названия заданий, матрица 0/1, выборы, ключ)."""
    rows = [list(r) for r in rows if r is not None and any(c not in (None, "") for c in r)]
    if len(rows) < 3:
        raise AnalysisError("В файле нужны строка заголовков и хотя бы два студента.")
    if len(rows) > MAX_ROWS or len(rows[0]) > MAX_COLS:
        raise AnalysisError("Слишком большой файл: не больше 3000 студентов и 400 заданий.")
    header = rows[0]
    labels = [_norm(h) or str(i) for i, h in enumerate(header[1:], start=1)]
    while labels and not _norm(header[len(labels)]):  # пустые столбцы справа
        labels.pop()
    k = len(labels)
    if k < 2:
        raise AnalysisError("Нужно хотя бы два задания (столбцы после первого).")
    body = rows[1:]
    key = None
    if _norm(body[0][0]).lower() in KEY_WORDS:
        key = [_norm(c) for c in (body[0][1:k + 1] + [None] * k)[:k]]
        if any(not c for c in key):
            raise AnalysisError("В строке ключа заполнены не все задания.")
        body = body[1:]
    matrix, choices = [], []
    for r in body:
        cells = [_norm(c) for c in (r[1:k + 1] + [None] * k)[:k]]
        if key:
            matrix.append([1 if c == key[j] else 0 for j, c in enumerate(cells)])
            choices.append(cells)
        else:
            row = []
            for c in cells:
                if c in ("", "0"):
                    row.append(0)
                elif c == "1":
                    row.append(1)
                else:
                    raise AnalysisError("Без строки «Ключ» в ячейках должны быть только 1 (верно) и 0 (неверно).")
            matrix.append(row)
    if len(matrix) < 2:
        raise AnalysisError("Нужно хотя бы два студента.")
    return labels, matrix, (choices if key else None), key


def _corr(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def analyse(labels, matrix, choices=None, key=None):
    n, k = len(matrix), len(labels)
    totals = [sum(r) for r in matrix]
    mean = sum(totals) / n
    var = sum((t - mean) ** 2 for t in totals) / n
    sd = math.sqrt(var)
    order = sorted(range(n), key=lambda i: totals[i])
    g = max(1, round(0.27 * n))
    lower, upper = order[:g], order[-g:]
    items, pq = [], 0.0
    # Набор вариантов — все встречавшиеся в файле (A–E и т. п.): вариант, который не выбрал никто, тоже «не работает».
    all_opts = sorted({c for row in choices for c in row if c} | set(key)) if choices is not None else []
    for j in range(k):
        col = [r[j] for r in matrix]
        p = sum(col) / n
        pq += p * (1 - p)
        rest = [t - c for t, c in zip(totals, col)]
        item = {"label": labels[j], "p": round(p, 3), "r": None, "d": None, "options": None}
        r = _corr(col, rest)
        item["r"] = None if r is None else round(r, 3)
        item["d"] = round(sum(col[i] for i in upper) / g - sum(col[i] for i in lower) / g, 3)
        if choices is not None:
            counts = dict.fromkeys(all_opts, 0)
            for row in choices:
                counts[row[j] or "—"] = counts.get(row[j] or "—", 0) + 1
            item["key"] = key[j]
            item["options"] = sorted(([opt, round(100 * c / n, 1)] for opt, c in counts.items()), key=lambda x: x[0])
        items.append(item)
    alpha = None if (k < 2 or var == 0) else (k / (k - 1)) * (1 - pq / var)
    sem = None if alpha is None else sd * math.sqrt(max(0.0, 1 - alpha))
    return {"n": n, "k": k, "mean": round(mean, 2), "mean_pct": round(100 * mean / k, 1), "sd": round(sd, 2),
            "alpha": None if alpha is None else round(alpha, 3), "sem": None if sem is None else round(sem, 2),
            "has_key": choices is not None, "items": items}


def flags(item, s):
    """Замечания к заданию по порогам из «Настроек» (s — словарь exam_*)."""
    out = []
    p, r = item["p"], item["r"]
    if p < float(s["exam_p_min"]):
        out.append("hard")
    if p > float(s["exam_p_max"]):
        out.append("easy")
    if r is None:
        out.append("no_variance")
    elif r < 0:
        out.append("negative")
    elif r < float(s["exam_disc_min"]):
        out.append("weak")
    if item.get("options"):
        dead = [o for o, share in item["options"] if o not in (item["key"], "—") and share < s["exam_distractor_min"]]
        if dead:
            item["dead"] = dead
            out.append("distractor")
    return out
