"""Расчёт по ответам. Консервативно: нет данных — значит «посчитать нельзя», а не ноль."""

from decimal import Decimal, InvalidOperation

from .models import Derived, Item

HUNDRED = Decimal(100)


def parse(item, raw):
    """Строка из формы → значение ответа (или None, если не отвечено)."""
    raw = (raw or "").strip()
    if raw == "":
        return None
    if item.type == Item.Type.YES_NO:
        return raw == "yes"
    if item.type == Item.Type.SCALE:
        v = int(raw)
        if not 1 <= v <= 5:
            raise ValueError("Шкала 1–5")
        return v
    if item.type == Item.Type.NUMBER:
        try:
            v = Decimal(raw.replace(",", "."))
        except InvalidOperation:
            raise ValueError("Нужно число")
        if v < 0:
            raise ValueError("Число не может быть отрицательным")
        return v
    return raw


def _scope(derived, items):
    if derived.section_id:
        return [i for i in items if i.section_id == derived.section_id]
    return items


def compute(derived, items, answers):
    """Возвращает (значение или None, пояснение)."""
    if derived.method == Derived.Method.RATIO:
        num, den = answers.get(derived.numerator_id), answers.get(derived.denominator_id)
        if num is None or den is None:
            return None, "не заполнены числитель или знаменатель"
        if den == 0:
            return None, "знаменатель равен нулю"
        note = f"{num} из {den}"
        if num > den:
            # Бывает законно (нагрузка выполнена с превышением), но для долей людей — ошибка ввода.
            note += " — больше 100 %, проверьте данные"
        return (num / den * HUNDRED).quantize(Decimal("0.1")), note

    scoped = _scope(derived, items)
    if derived.method == Derived.Method.PERCENT_YES:
        yn = [i for i in scoped if i.type == Item.Type.YES_NO]
        answered = [i for i in yn if answers.get(i.pk) is not None]
        if not yn:
            return None, "нет пунктов «да / нет»"
        if len(answered) < len(yn):
            return None, f"отвечено {len(answered)} из {len(yn)} пунктов"
        yes = sum(1 for i in answered if answers[i.pk])
        return (Decimal(yes) / len(yn) * HUNDRED).quantize(Decimal("0.1")), f"«да» в {yes} из {len(yn)}"

    # SCORE: да = полный вес, шкала 1–5 = доля веса (1 → 0, 5 → весь вес).
    scored = [i for i in scoped if i.type in (Item.Type.YES_NO, Item.Type.SCALE)]
    if not scored:
        return None, "нет пунктов с баллами"
    missing = [i for i in scored if answers.get(i.pk) is None]
    if missing:
        return None, f"не оценено {len(missing)} из {len(scored)} пунктов"
    total = sum(i.weight for i in scored)
    got = Decimal(0)
    for i in scored:
        a = answers[i.pk]
        got += i.weight if (i.type == Item.Type.YES_NO and a) else (i.weight * (a - 1) / 4 if i.type == Item.Type.SCALE else 0)
    if total == 0:
        return None, "сумма весов равна нулю"
    return (got / total * HUNDRED).quantize(Decimal("0.1")), f"{got.quantize(Decimal('0.01')).normalize():f} из {total.normalize():f} баллов"
