"""Начальные данные: структура ТГМУ, показатели Стратегии 2030, каркасы WFME, ESG, ISO.

Команду можно запускать повторно: уже существующие записи не дублируются и не перезаписываются
(правки, сделанные в программе, сохраняются).
"""

import json
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from norms.models import Framework, FrameworkVersion, Indicator, NormNode
from org.models import OrgUnit

DATA = settings.BASE_DIR / "data"


def _load(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


class Command(BaseCommand):
    help = "Загрузить начальные данные (структура ТГМУ, Стратегия 2030, каркасы стандартов)"

    @transaction.atomic
    def handle(self, *args, **opts):
        self.structure()
        self.strategy()
        self.skeletons()

    def _unit(self, kind, name, parent, order=0):
        unit, created = OrgUnit.objects.get_or_create(kind=kind, name=name, parent=parent, defaults={"order": order})
        return unit, created

    def structure(self):
        s = _load("tsmu_structure.json")
        uni, _ = self._unit(OrgUnit.Kind.UNIVERSITY, s["university"], None)
        made = 0
        for i, fac in enumerate(s["faculties"]):
            f, c = self._unit(OrgUnit.Kind.FACULTY, fac["name"], uni, i)
            made += c
            for j, dep in enumerate(fac["departments"]):
                made += self._unit(OrgUnit.Kind.DEPARTMENT, dep, f, j)[1]
        for k, name in enumerate(s["centers"]):
            made += self._unit(OrgUnit.Kind.CENTER, name, uni, 100 + k)[1]
        self.stdout.write(f"Структура: добавлено {made} подразделений.")

    def strategy(self):
        s = _load("strategy2030_kpi.json")
        fw, _ = Framework.objects.get_or_create(
            code="tsmu-strategy-2030",
            defaults={"title": "Стратегия развития ТГМУ до 2030 г.",
                      "description": f"Утверждена: {s['approved']}. Порог 2027 г. принят как «средний» уровень, порог 2030 г. — как «высокий»; "
                                     "«слабый» не задан. Базовых значений в документе нет."})
        v, created = FrameworkVersion.objects.get_or_create(
            framework=fw, version="2025-12-25", defaults={"source_url": s["source"]})
        if not created:
            self.stdout.write("Стратегия 2030: уже загружена, пропуск.")
            return
        for i, p in enumerate(s["priorities"]):
            node = NormNode.objects.create(version=v, kind=NormNode.Kind.AREA, code=p["code"], title=p["title"], order=i)
            for j, ind in enumerate(p["indicators"]):
                numeric = isinstance(ind["target_2027"], (int, float))
                Indicator.objects.create(
                    node=node, code=ind["code"], title=ind["title"], unit=ind["unit"], order=j,
                    threshold_medium=Decimal(str(ind["target_2027"])) if numeric else None,
                    threshold_high=Decimal(str(ind["target_2030"])) if numeric else None,
                    note="" if numeric else f"Цель 2027: {ind['target_2027']}; цель 2030: {ind['target_2030']}. Порогов в числах нет — оценивается экспертом.",
                )
        self.stdout.write("Стратегия 2030: загружено 16 показателей.")

    def skeletons(self):
        for f in _load("frameworks_skeleton.json")["frameworks"]:
            fw, _ = Framework.objects.get_or_create(code=f["code"], defaults={"title": f["title"], "description": f["description"]})
            v, created = FrameworkVersion.objects.get_or_create(
                framework=fw, version=f["version"], defaults={"source_url": f["source_url"]})
            if not created:
                continue
            for i, (code, title) in enumerate(f["areas"]):
                NormNode.objects.create(version=v, kind=NormNode.Kind.AREA, code=code, title=title, order=i)
            self.stdout.write(f"{fw.title}: каркас из {len(f['areas'])} областей.")
