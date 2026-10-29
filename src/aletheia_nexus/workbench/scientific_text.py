"""Plain presentation of scholarly formatting, without rewriting source metadata."""

from __future__ import annotations

import re
from html import unescape

# This is deliberately not a general HTML stripper. In a title, < and > can be
# mathematical operators. Only known, balanced formatting tags are removed;
# their scientific text is always retained, with no inferred Unicode chemistry.
_FORMAT_TAG = re.compile(
    r"<(?P<closing>/)?(?P<name>(?:[a-z][\w.-]*:)?"
    r"(?:sup|sub|i|b|em|strong|u|span|font|small|big|italic|bold|"
    r"monospace|sc|underline|overline|styled-content|named-content|br|wbr))"
    r"(?:\s+[^<>]{0,512})?\s*/?>",
    re.IGNORECASE,
)


def scientific_filename_text(value: str) -> str:
    """Decode entities and flatten paired scholarly markup for a filename.

    Unmatched/unknown tags and mathematical angle brackets remain literal here.
    The existing portable filename sanitizer still handles filesystem characters
    after rendering. Original titles, human translations and source bytes must
    never be overwritten with this presentation value.
    """
    text = unescape(value)
    matches = list(_FORMAT_TAG.finditer(text))
    stacks, replacements = {}, {}
    for index, match in enumerate(matches):
        name = match["name"].casefold()
        local_name = name.rsplit(":", 1)[-1]
        closing = bool(match["closing"])
        if local_name in {"br", "wbr"}:
            replacements[index] = " "
        elif match[0].endswith("/>"):
            # An empty inline formatting element contributes no scientific text.
            if not closing:
                replacements[index] = ""
        elif closing:
            pending = stacks.get(name)
            if pending:
                replacements[pending.pop()] = replacements[index] = ""
        else:
            stacks.setdefault(name, []).append(index)
    if not replacements:
        return text
    parts, start = [], 0
    for index, match in enumerate(matches):
        if index not in replacements:
            continue
        parts.extend((text[start : match.start()], replacements[index]))
        start = match.end()
    parts.append(text[start:])
    return "".join(parts)
