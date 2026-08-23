import re
import urllib.parse

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

HASHTAG_PATTERN = re.compile(r"(#\w+)")


@register.filter(name="linkify_hashtags")
def linkify_hashtags(text):
    escaped = escape(text)

    def repl(match):
        tag = match.group(1)
        encoded_tag = urllib.parse.quote(tag)
        return (
            f'<a href="/photos/search/?q={encoded_tag}"'
            f' style="color: var(--primary); text-decoration: none;">{tag}</a>'
        )

    result = HASHTAG_PATTERN.sub(repl, escaped)
    return mark_safe(result)
