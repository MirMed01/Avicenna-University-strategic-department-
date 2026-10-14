from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def num(value):
    """60.00 → 60, 2.50 → 2.5, None → «—»."""
    if value is None or value == "":
        return "—"
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"
    return value
