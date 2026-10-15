"""Начальные данные: структура ТГМУ, показатели Стратегии 2030, каркасы WFME, ESG, ISO.

Команду можно запускать повторно: уже существующие записи не дублируются и не перезаписываются
(правки, сделанные в программе, сохраняются).
"""

import json
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from instruments.models import Derived, Instrument, InstrumentVersion, Item, Section
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
        self.instruments()
        self.problems()
        self.iaar()
        self.processes()

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

    def instruments(self):
        data = _load("instruments.json")
        f = data["framework"]
        fw, _ = Framework.objects.get_or_create(code=f["code"], defaults={"title": f["title"], "description": f["description"]})
        v, _ = FrameworkVersion.objects.get_or_create(framework=fw, version=f["version"])
        # По разделам: новые разделы добавляются и в уже работающую базу, существующие не трогаются.
        for i, area in enumerate(f["areas"]):
            node, new_node = NormNode.objects.get_or_create(version=v, code=area["code"], defaults={
                "kind": NormNode.Kind.AREA, "title": area["title"], "order": i})
            if new_node:
                for j, (code, title, unit) in enumerate(area["indicators"]):
                    Indicator.objects.create(node=node, code=code, title=title, unit=unit, order=j,
                                             note="Порог не задан — установите его.")
        indicators = {i.code: i for i in Indicator.objects.filter(node__version=v)}
        made = 0
        for d in data["instruments"]:
            self._fill_tajik(d)
            inst, new = Instrument.objects.get_or_create(code=d["code"], defaults={
                k: d[k] for k in ("title", "kind", "respondent", "description", "source_title", "source_url")})
            if not new:
                continue
            made += 1
            ver = InstrumentVersion.objects.create(instrument=inst, number=1)
            items, sections = {}, {}
            for si, sec in enumerate(d["sections"]):
                s = sections[sec["title"]] = Section.objects.create(version=ver, title=sec["title"], order=si)
                for ii, (code, text, typ, help_, ind) in enumerate(sec["items"]):
                    items[code] = Item.objects.create(section=s, code=code, text=text, type=typ, help=help_, order=ii,
                                                      required=typ != "text", indicator=indicators.get(ind))
            for di, row in enumerate(d["derived"]):
                code, title, method, num, den, ind = row[:6]
                # Седьмое поле (необязательное) — раздел, по которому считать (подшкала анкеты).
                Derived.objects.create(version=ver, code=code, title=title, method=method, order=di,
                                       numerator=items.get(num), denominator=items.get(den), indicator=indicators.get(ind),
                                       section=sections.get(row[6]) if len(row) > 6 else None)
            ver.publish()
            self._fill_tajik(d)
        self.stdout.write(f"Инструменты: добавлено {made}.")

    def _fill_tajik(self, d):
        """Таджикский вариант вопросов: заполняется только там, где поле ещё пустое (правки в программе не затираются)."""
        tg = d.get("tg")
        if not tg:
            return
        for title, title_tg in tg.get("sections", {}).items():
            Section.objects.filter(version__instrument__code=d["code"], title=title, title_tg="").update(title_tg=title_tg)
        for code, text_tg in tg.get("items", {}).items():
            Item.objects.filter(section__version__instrument__code=d["code"], code=code, text_tg="").update(text_tg=text_tg)

    def problems(self):
        from capa.models import Problem, ProblemGroup

        data = _load("problems.json")
        groups = {}
        for i, (code, title) in enumerate(data["groups"]):
            groups[code], _ = ProblemGroup.objects.get_or_create(code=code, defaults={"title": title, "order": i})
        made = 0
        for p in data["problems"]:
            obj, new = Problem.objects.get_or_create(code=p["code"], defaults={
                "title": p["title"], "description": p["description"], "typical_actions": "\n".join(p["actions"]),
                "group": groups.get(p["group"]), "causes": p["causes"]})
            if not new and obj.group_id is None and p["group"]:
                # Старые проблемы получают группу один раз; правки Центра не затираются.
                Problem.objects.filter(pk=obj.pk, group__isnull=True, causes="").update(group=groups[p["group"]], causes=p["causes"])
            if new:
                made += 1
                for fw, code in p["indicators"]:
                    obj.indicators.add(*Indicator.objects.filter(node__version__framework__code=fw, code=code))
        self.stdout.write(f"Справочник проблем качества: добавлено {made}.")

    def iaar(self):
        """Стандарт IAAR для программной аккредитации и три подготовки ТГМУ (срок — окончание действующей аккредитации)."""
        from datetime import date

        from accreditation.models import Cycle

        d = _load("iaar_programme_2025.json")
        doc = d["document"]
        fw, _ = Framework.objects.get_or_create(code="iaar-bmifo", defaults={
            "title": "IAAR: международная аккредитация программ медицинского и фармацевтического образования",
            "description": f"{doc['title']}. Издание {doc['edition']}, {doc['year']}; {doc['approved']}. "
                           "Критерии даны кратким изложением — точные формулировки сверять с PDF."})
        v, created = FrameworkVersion.objects.get_or_create(framework=fw, version=f"{doc['year']}, изд. {doc['edition']}",
                                                            defaults={"source_url": doc["url_ru"]})
        if created:
            order = 0
            for s in d["standards"]:
                std = NormNode.objects.create(version=v, kind=NormNode.Kind.AREA, code=s["code"], title=s["title"], order=int(s["code"]))
                for sub in s["substandards"]:
                    sn = NormNode.objects.create(version=v, parent=std, kind=NormNode.Kind.STANDARD, code=sub["code"], title=sub["title"], order=order)
                    for code, summary in sub["criteria"]:
                        order += 1
                        NormNode.objects.create(version=v, parent=sn, kind=NormNode.Kind.CRITERION, code=code,
                                                title=summary, order=order)
            self.stdout.write(f"IAAR: {NormNode.objects.filter(version=v, kind='criterion').count()} критериев.")
        if Cycle.objects.exists():
            return
        faculties = {f.name: f for f in OrgUnit.objects.filter(kind=OrgUnit.Kind.FACULTY)}
        for code, name, fac in (("1-790101", "Лечебное дело", "Медицинский факультет"),
                                ("1-790102", "Педиатрия", "Педиатрический факультет"),
                                ("1-790108", "Фармация", "Фармацевтический факультет")):
            c = Cycle.objects.create(title=f"{name}: повторная аккредитация IAAR", version=v, programme=f"{code} {name}",
                                     org_unit=faculties.get(fac), deadline=date(2027, 4, 21))
            c.ensure_assessments()
        self.stdout.write("Подготовка к аккредитации: 3 программы (срок — 21.04.2027, уточните дату визита).")

    def processes(self):
        """Типовой реестр процессов. Добавляются только новые процессы; паспорта, правленные Центром, не трогаются.
        Исключение — однократно: процесс, у которого ещё нет ни одного инструмента оценки, получает инструменты
        и недостающие показатели из данных (так обновляется база, созданная до появления инструментов у процессов)."""
        from instruments.models import Instrument
        from processes.models import Process

        made = 0
        for i, d in enumerate(_load("processes.json")["processes"]):
            level = d.get("level", "university")
            obj, new = Process.objects.get_or_create(code=d["code"], defaults={
                "title": d["title"], "group": d["group"], "owner_position": d["owner_position"], "purpose": d["purpose"],
                "inputs": d["inputs"], "outputs": d["outputs"], "customers": d["customers"], "order": i, "level": level,
                "is_key": level == "university", "parent": Process.objects.filter(code=d.get("parent")).first()})
            instruments = Instrument.objects.filter(code__in=d.get("instruments", []))
            if not new:
                if not obj.instruments.exists() and instruments:
                    obj.instruments.add(*instruments)
                    for fw, code in d["indicators"]:
                        obj.indicators.add(*Indicator.objects.filter(node__version__framework__code=fw, code=code))
                continue
            made += 1
            obj.instruments.add(*instruments)
            for fw, code in d["nodes"]:
                node = NormNode.objects.filter(version__framework__code=fw, code=code, parent__isnull=True).order_by(
                    "-version__effective_from", "-id").first()
                if node:
                    obj.norm_nodes.add(node)
            for fw, code in d["indicators"]:
                obj.indicators.add(*Indicator.objects.filter(node__version__framework__code=fw, code=code))
        self.stdout.write(f"Реестр процессов: добавлено {made}.")
