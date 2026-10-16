"""Меню программы: разделы по группам, с учётом прав. Одно место — для боковой панели, меню телефона и нижних вкладок."""

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from accounts.models import Role
from accounts.permissions import VERIFIERS, VIEW_ALL, can_manage, has_role

TABS = ("home", "inspections:index", "capa:index", "processes:index")  # нижние вкладки на телефоне (+ «Меню»)
SHORT = {"capa:index": _("Планы")}  # короткие подписи для нижних вкладок


def nav(request):
    u = request.user
    if not u.is_authenticated:
        return {}
    view_all, verifier, manager = has_role(u, *VIEW_ALL), has_role(u, *VERIFIERS), can_manage(u)
    groups = [
        (_("Главное"), [("home", _("Главная"), "home", True),
                        ("dashboard:index", _("Панель"), "chart", view_all or verifier)]),
        (_("Работа Центра"), [("inspections:index", _("Проверки"), "check", True),
                              ("capa:index", _("Планы исправления"), "wrench", True),
                              ("exams:index", _("Анализ тестов"), "test", True),
                              ("feedback:index", _("Опросы студентов"), "chat", True)]),
        (_("Система качества"), [("processes:index", _("Процессы"), "flow", True),
                                 ("norms:index", _("Нормы"), "book", True),
                                 ("instruments:index", _("Инструменты"), "list", True),
                                 ("accreditation:index", _("Аккредитация"), "award", True),
                                 ("management:index", _("Руководство"), "people", view_all)]),
        (_("Люди и структура"), [("org:tree", _("Структура"), "tree", True),
                                 ("portfolio:my", _("Моё портфолио"), "person", True),
                                 ("portfolio:queue", _("Проверка портфолио"), "badge", verifier),
                                 ("accounts:users", _("Пользователи"), "people", manager)]),
        (_("Администрирование"), [("journal", _("Журнал"), "clock", manager),
                                  ("settings", _("Настройки"), "gear", manager)]),
    ]
    path = request.path
    built, best = [], ("", None)
    for title, items in groups:
        row = []
        for name, label, icon, allowed in items:
            if not allowed:
                continue
            url = reverse(name)
            item = {"name": name, "url": url, "label": label, "short": SHORT.get(name, label), "icon": icon, "active": False}
            # Активен самый длинный совпавший адрес; главная — только точное совпадение.
            if (url == "/" and path == "/") or (url != "/" and path.startswith(url) and len(url) > len(best[0])):
                best = (url, item)
            row.append(item)
        if row:
            built.append({"title": title, "items": row})
    if best[1]:
        best[1]["active"] = True
    flat = {i["name"]: i for g in built for i in g["items"]}
    return {"nav_groups": built, "nav_tabs": [flat[n] for n in TABS if n in flat],
            "nav_more_active": bool(best[1]) and best[1]["name"] not in TABS}
