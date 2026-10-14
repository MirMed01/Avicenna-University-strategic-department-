"""Отчёты по кнопке: Excel (таблицы) и Word (годовой отчёт Центра). Данные — из dashboard.data."""

from io import BytesIO

from django.utils import timezone

STATUS_TEXT = {"ok": "в норме", "mild": "лёгкое отклонение", "severe": "выраженное отклонение",
               "unknown": "порог не задан", "nodata": "нет данных"}


def _num(v):
    return None if v is None else float(v)


def xlsx(ctx, strategy):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    fills = {"ok": "E2F2E8", "mild": "FBF0D9", "severe": "F8E1DF"}
    wb = Workbook()
    ws = wb.active
    ws.title = "Тепловая карта"
    heat = ctx["heat"]
    ws.append(["Кафедра"] + heat["titles"] + ["Отклонений"])
    for row in heat["rows"]:
        ws.append([row["unit"].name] + [_num(c["value"]) if c else None for c in row["line"]] + [row["bad"]])
        for j, c in enumerate(row["line"], start=2):
            if c and c["status"] in fills:
                ws.cell(ws.max_row, j).fill = PatternFill("solid", fgColor=fills[c["status"]])
    ws.append([])
    ws.append([f"Не проверялись: {len(heat['unchecked'])} кафедр"])

    st = wb.create_sheet("Стратегия 2030")
    st.append(["№", "Показатель", "Ед.", "Цель 2027", "Цель 2030", f"Значение {ctx['year']}", "Состояние", "Источник"])
    for r in strategy:
        i = r["ind"]
        st.append([i.code, i.title, i.unit, _num(i.threshold_medium), _num(i.threshold_high), _num(r["value"]),
                   STATUS_TEXT.get(r["status"], ""), r["source"]])

    pl = wb.create_sheet("Планы исправления")
    pl.append(["№", "Подразделение", "Диагноз", "План", "Статус", "Срок", "Просрочен", "Ответственный"])
    for p in ctx["plan_list"]:
        pl.append([p.ref, str(p.org_unit), str(p.problem), p.title, p.get_state_display(), p.due_date,
                   "да" if p.overdue else "", str(p.owner or "")])

    sv = wb.create_sheet("Опросы студентов")
    sv.append(["Опрос", "Кафедра", "Группа", "Ответов", "Итоги видны"])
    for c in ctx["campaigns"]:
        sv.append([c.title, str(c.org_unit), c.label, c.response_count, "да" if c.results_visible else "нет (мало ответов)"])

    for sheet in wb.worksheets:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for col in sheet.columns:
            sheet.column_dimensions[col[0].column_letter].width = min(60, max(10, *(len(str(c.value or "")) for c in col)) + 2)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def docx(ctx, strategy):
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(12)
    year = ctx["year"]
    doc.add_heading(f"Годовой отчёт Центра стратегического развития за {year} год", level=0)
    doc.add_paragraph("ТГМУ им. Абуали ибни Сино. Сформировано программой «Канон» "
                      f"{timezone.localdate():%d.%m.%Y}. Цифры — по данным, внесённым в программу; "
                      "текстовый анализ дописывается Центром.")

    doc.add_heading("1. Выполнение Стратегии развития до 2030 года", level=1)
    t = doc.add_table(rows=1, cols=6)
    t.style = "Table Grid"
    for c, h in zip(t.rows[0].cells, ["№", "Показатель", "Цель 2027", "Цель 2030", f"{year}", "Состояние"]):
        c.text = h
    for r in strategy:
        i = r["ind"]
        f = lambda v: "—" if v is None else f"{v.normalize():f}"
        cells = t.add_row().cells
        for c, v in zip(cells, [i.code, i.title, f(i.threshold_medium), f(i.threshold_high), f(r["value"]), STATUS_TEXT.get(r["status"], "")]):
            c.text = v
    filled = sum(1 for r in strategy if r["value"] is not None)
    doc.add_paragraph(f"Значения есть по {filled} из {len(strategy)} показателей. Показатели 2.2, 2.3 и 3.1 считаются "
                      "по подтверждённым портфолио преподавателей, зарегистрированных в программе.")

    doc.add_heading("2. Проверки кафедр", level=1)
    heat = ctx["heat"]
    doc.add_paragraph(f"За {year} год назначено проверок: {ctx['inspections_year']}, закрыто: {ctx['inspections_closed']}. "
                      f"Кафедр с результатами: {len(heat['rows'])}, не проверялись: {len(heat['unchecked'])}.")
    for row in heat["rows"]:
        bad = [f"{code} — {c['value'].normalize():f} %" for code, c in zip(heat["codes"], row["line"])
               if c and c["status"] in ("mild", "severe") and c["value"] is not None]
        doc.add_paragraph(f"{row['unit'].name}: " + ("отклонения — " + "; ".join(bad) if bad else "отклонений нет"), style="List Bullet")

    doc.add_heading("3. Диагнозы и планы исправления", level=1)
    ps = ctx["plans"]
    doc.add_paragraph(f"Всего планов: {ps['total']}, открыто: {ps['open']}, закрыто результативно: {ps['closed']}, "
                      f"просрочено: {len(ps['overdue'])}.")
    for name, n in ctx["problems"]:
        doc.add_paragraph(f"{name}: {n}", style="List Bullet")

    doc.add_heading("4. Обратная связь студентов", level=1)
    camps = list(ctx["campaigns"])
    doc.add_paragraph(f"Опросов: {len(camps)}, ответов: {ctx['responses']}. Итоги учитываются только там, где ответов "
                      "не меньше порога анонимности.")

    doc.add_heading("5. Выводы и предложения", level=1)
    doc.add_paragraph("________________________________________________ (заполняет Центр)")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
