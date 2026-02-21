from django import template

register = template.Library()

@register.filter
def get_item(d, key):
    return d.get(key, 0) if isinstance(d, dict) else 0
