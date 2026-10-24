"""Mail bodies: plain text as HTML that keeps its layout, and a reply's text above the quote.

Graph's reply and forward actions, and the drafts their ``create*`` forms make, take the
new text in one of two places, and neither keeps a formatted reply intact (checked
against an Exchange Online mailbox):

- ``comment`` is plain text, and Graph joins its lines with spaces: two paragraphs, a
  line break and a list arrive as one run-on paragraph. On a plain-text original it
  also turns the draft into HTML.
- ``message.body`` keeps its markup but replaces the whole body, so the quoted original
  is gone.

So the draft is created with neither. Graph quotes the original into it, as HTML for
an HTML original and as plain text for a plain-text one, and the new text goes in by
one PATCH, above the quote, in the draft's own format.
"""

from __future__ import annotations

import re
from html import escape
from typing import Any

# The opening tag of a draft's HTML body, whatever its case and attributes.
_BODY_OPEN_TAG = re.compile(r"<body\b[^>]*>", re.IGNORECASE)
# A list item: "- " or "* " at the start of a line, after any indentation.
_BULLET = re.compile(r"^\s*[-*]\s+(\S.*)$")
# A blank line, which may hold spaces or tabs.
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def text_to_html(text: str) -> str:
    """Plain text as HTML that reads the way the text does.

    A blank line separates paragraphs (``<p>``), a single line break stays one
    (``<br>``), and lines starting ``- `` or ``* `` become a list (``<ul><li>``).
    Everything is HTML-escaped, so ``<b>`` in plain text is shown, not applied.
    Nothing else is interpreted.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts: list[str] = []
    for block in _BLANK_LINE.split(text):
        run: list[str] = []
        in_list = False
        for line in block.split("\n"):
            if not line.strip():
                continue
            bullet = _BULLET.match(line)
            if run and (bullet is not None) != in_list:
                parts.append(_render(run, in_list))
                run = []
            in_list = bullet is not None
            run.append(escape(bullet.group(1).rstrip() if bullet else line.rstrip()))
        if run:
            parts.append(_render(run, in_list))
    return "".join(parts)


def _render(lines: list[str], as_list: bool) -> str:
    if as_list:
        return "<ul>" + "".join(f"<li>{line}</li>" for line in lines) + "</ul>"
    return "<p>" + "<br>".join(lines) + "</p>"


def above_quote(draft_body: Any, body: str, is_html: bool) -> Any:
    """The body for a reply or forward draft: ``body`` above the original Graph quoted.

    - An HTML draft: ``body`` goes right after its ``<body ...>`` tag, plain text
      converted by :func:`text_to_html` first. That is where Outlook puts a reply, above
      the ``<hr>`` and header block that open the quote, and the original's markup stays
      as Graph wrote it.
    - A plain-text draft, which Graph makes for a plain-text original: plain text stays
      plain text, above the quote, with the draft's line endings. HTML turns the draft
      into HTML, its quote escaped, line breaks kept.
    """
    from msgraph.generated.models.body_type import BodyType
    from msgraph.generated.models.item_body import ItemBody

    content = getattr(draft_body, "content", None) or ""
    result = ItemBody()
    result.content_type = BodyType.Html
    if getattr(draft_body, "content_type", None) == BodyType.Text:
        if is_html:
            quoted = escape(content).replace("\r\n", "\n").replace("\n", "<br>")
            result.content = f"{body}<br>{quoted}" if quoted else body
            return result
        newline = "\r\n" if "\r\n" in content else "\n"
        text = body.replace("\r\n", "\n").rstrip("\n").replace("\n", newline)
        # Graph's plain-text quote opens with a line break; one blank line either way.
        gap = newline if content.startswith(("\r\n", "\n")) else newline * 2
        result.content = text + gap + content if content else text
        result.content_type = BodyType.Text
        return result
    html = body if is_html else text_to_html(body)
    match = _BODY_OPEN_TAG.search(content)
    if match is None:
        result.content = html + content
    else:
        result.content = content[: match.end()] + html + content[match.end() :]
    return result
