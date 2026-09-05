import re
import urllib.parse

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

HASHTAG_PATTERN = re.compile(r"(#\w+)")
MENTION_PATTERN = re.compile(r"(@[\w\.]+)")


@register.filter(name="linkify_hashtags")
def linkify_hashtags(text):
    escaped = escape(text)

    def hashtag_repl(match):
        tag = match.group(1)
        encoded_tag = urllib.parse.quote(tag)
        return (
            f'<a href="/photos/search/?q={encoded_tag}"'
            f' style="color: var(--primary); text-decoration: none;">{tag}</a>'
        )

    def mention_repl(match):
        mention = match.group(1)
        username = mention[1:]  # strip the @
        return (
            f'<a href="/users/{username}/"'
            f' style="color: var(--primary); text-decoration: none; '
            f'font-weight: 500;">{mention}</a>'
        )

    result = HASHTAG_PATTERN.sub(hashtag_repl, escaped)
    result = MENTION_PATTERN.sub(mention_repl, result)
    return mark_safe(result)
