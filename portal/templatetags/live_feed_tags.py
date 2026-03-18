from django import template

register = template.Library()


@register.filter
def get_key(dictionary, key):
    if isinstance(dictionary, dict):
        return dictionary.get(key, '')
    return ''
