"""Приём анонимного ответа и подсчёт итогов."""

from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils.translation import gettext as _

from instruments.models import Derived, Item
from instruments.scoring import parse

from .models import AccessCode, Campaign, Counter, TextAnswer

ALLOWED_TYPES = (Item.Type.YES_NO, Item.Type.SCALE, Item.Type.CHOICE, Item.Type.TEXT)


class VoteError(Exception):
    pass


def find_campaign(code):
    ac = AccessCode.objects.select_related("campaign__version").filter(code=code.strip().upper()).first()
    if ac is None:
        raise VoteError(_("Код не найден. Проверьте, что он введён без ошибок."))
    if ac.used:
        raise VoteError(_("По этому коду уже ответили. Каждый код действует один раз."))
    if not ac.campaign.accepting:
        raise VoteError(_("Приём ответов в этом опросе закрыт."))
    return ac.campaign


def validate(campaign, data):
    """Возвращает (ответы {item: значение}, ошибки {item_id: текст})."""
    answers, errors = {}, {}
    for it in campaign.version.items():
        if it.type not in ALLOWED_TYPES:
            continue
        try:
            v = parse(it, data.get(f"i{it.pk}"))
        except ValueError as e:
            errors[it.pk] = str(e)
            continue
        if v is None and it.required:
            errors[it.pk] = _("Ответьте, пожалуйста")
        elif it.type == Item.Type.CHOICE and v is not None and v not in it.option_list():
            errors[it.pk] = _("Выберите вариант из списка")
        else:
            answers[it] = v
    return answers, errors


def submit(code, answers):
    """Записать ответ. Код гасится в той же транзакции; повторно — ошибка."""
    code = code.strip().upper()
    with transaction.atomic():
        used = AccessCode.objects.filter(code=code, used=False, campaign__is_open=True).update(used=True)
        if used != 1:
            raise VoteError(_("По этому коду уже ответили или опрос закрыт."))
        campaign = Campaign.objects.select_for_update().get(codes__code=code)
        for it, v in answers.items():
            if v is None:
                continue
            if it.type == Item.Type.TEXT:
                TextAnswer.objects.create(campaign=campaign, item=it, text=v[:3000])
                continue
            value = ("yes" if v else "no") if it.type == Item.Type.YES_NO else str(v)
            Counter.objects.get_or_create(campaign=campaign, item=it, value=value)
            Counter.objects.filter(campaign=campaign, item=it, value=value).update(count=F("count") + 1)
        Campaign.objects.filter(pk=campaign.pk).update(response_count=F("response_count") + 1)


def summary(campaign):
    """Итоги по пунктам и расчётным показателям. Вызывать только если campaign.results_visible."""
    counts = {}
    for c in campaign.counters.all():
        counts.setdefault(c.item_id, {})[c.value] = c.count
    rows = []
    items = [it for it in campaign.version.items() if it.type in ALLOWED_TYPES]
    for it in items:
        d = counts.get(it.pk, {})
        n = sum(d.values())
        row = {"item": it, "n": n}
        if it.type == Item.Type.SCALE and n:
            row["mean"] = (Decimal(sum(int(k) * v for k, v in d.items())) / n).quantize(Decimal("0.01"))
            row["dist"] = [(k, d.get(str(k), 0), round(100 * d.get(str(k), 0) / n)) for k in range(1, 6)]
        elif it.type == Item.Type.YES_NO and n:
            row["yes_pct"] = round(100 * d.get("yes", 0) / n)
        elif it.type == Item.Type.CHOICE and n:
            row["dist"] = [(o, d.get(o, 0), round(100 * d.get(o, 0) / n)) for o in it.option_list()]
        elif it.type == Item.Type.TEXT:
            row["texts"] = list(campaign.texts.filter(item=it))
        rows.append(row)
    derived = [aggregate(d, items, counts) for d in campaign.version.derived.select_related("indicator__node__version__framework")]
    return rows, derived


def aggregate(d, items, counts):
    """Расчётный показатель по счётчикам: доля «да» или баллы — в среднем по всем ответам."""
    scoped = [i for i in items if not d.section_id or i.section_id == d.section_id]
    value = None
    if d.method == Derived.Method.PERCENT_YES:
        yes = sum(counts.get(i.pk, {}).get("yes", 0) for i in scoped if i.type == Item.Type.YES_NO)
        total = sum(sum(counts.get(i.pk, {}).values()) for i in scoped if i.type == Item.Type.YES_NO)
        value = (Decimal(yes) / total * 100).quantize(Decimal("0.1")) if total else None
    elif d.method == Derived.Method.SCORE:
        got = total = Decimal(0)
        for i in scoped:
            c = counts.get(i.pk, {})
            n = sum(c.values())
            if not n or i.type not in (Item.Type.SCALE, Item.Type.YES_NO):
                continue
            if i.type == Item.Type.SCALE:
                mean = Decimal(sum(int(k) * v for k, v in c.items())) / n
                got += i.weight * (mean - 1) / 4
            else:
                got += i.weight * Decimal(c.get("yes", 0)) / n
            total += i.weight
        value = (got / total * 100).quantize(Decimal("0.1")) if total else None
    return {"d": d, "value": value}
