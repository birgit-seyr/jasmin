"""Safe Mustache-style renderer for tenant-edited email templates.

Why not Django's template engine?
    Tenant admins can paste arbitrary text into a rich-text editor. Django
    tags (``{% load %}``, ``{% include %}``, custom filters) would let
    them read files from disk, exfiltrate data, or run arbitrary Python
    via badly-written tags. We need a strict allow-list.

Supported syntax (intentionally tiny):
    {{ var }}        -> HTML-escaped lookup of ``var`` in context.
    {{ user.email }} -> dotted path lookup (dict keys, attributes).
    {{{ var }}}      -> raw (unescaped) ONLY when ``var`` is a ``RAW_KEYS`` entry
                        (trusted, server-built markup); any other key is
                        HTML-escaped just like ``{{ var }}`` (INJ-2), so a tenant
                        admin can't smuggle markup through the triple-brace form.

That's the whole grammar. No conditionals, no loops, no filters. If a
tenant needs branching they can edit two templates (e.g. one per locale)
and pick one in code. The variables registry per slug tells the editor
which placeholders are available.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape
from typing import Any

# Match {{{ raw }}} first (greedy on braces), then {{ escaped }}.
_RAW_RE = re.compile(r"\{\{\{\s*([\w.]+)\s*\}\}\}")
_ESCAPED_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

# EML-1: keys whose value is TRUSTED, server-built markup (assembled in Python
# with every cell already HTML-escaped — e.g. the pre-flattened invoice-reminder
# table/text). Such keys are emitted UNescaped even via ``{{ key }}`` so the same
# template string renders raw under BOTH Django (the value is mark_safe'd) and
# this renderer. They are NEVER tenant input, so this is no riskier than the
# ``{{{ raw }}}`` syntax already supported below. ``find_undeclared_placeholders``
# also treats these as always-allowed (they are declared on the one spec that
# builds them, but the renderer trusts them regardless).
RAW_KEYS: frozenset[str] = frozenset(
    {
        "invoices_table",
        "invoices_text",
        # Daily-renewal office digest: the failed-subscription rows are
        # pre-flattened + escaped in Python (see the daily task), same pattern
        # as the invoice-reminder table — no Django ``{% for %}`` (the Mustache
        # override renderer can't reproduce it).
        "renewal_failures_html",
        "renewal_failures_text",
    }
)


def _resolve(path: str, context: Mapping[str, Any]) -> str:
    """Walk a dotted path through dicts / objects. Missing -> ''.

    SECURITY: these templates are tenant-admin-editable, so ``_resolve`` is a
    sandbox boundary. Without the guards below it is an attribute-walk escape
    hatch — e.g. ``x.save.__globals__.settings.SECRET_KEY`` /
    ``FIELD_ENCRYPTION_KEY`` reads the cluster-wide keys that sign every
    tenant's JWTs and decrypt every tenant's PII, and ``x.__class__`` /
    ``x._meta`` pivot into internals. Two rules close that:

      * Reject any "private" segment — one starting with ``_`` (covers every
        dunder: ``__globals__``, ``__class__``, ``__dict__``, ``_meta``,
        ``_state`` …).
      * Never traverse into or render a callable — a bound method's
        ``__globals__`` is the usual pivot to ``settings``. If a segment
        resolves to something callable, stop and render empty.

    Only plain data attributes / Mapping keys resolve to a value.
    """
    parts = path.split(".")
    current: Any = context
    for part in parts:
        if part.startswith("_"):
            return ""
        if current is None:
            return ""
        if isinstance(current, Mapping):
            current = current.get(part, "")
        else:
            current = getattr(current, part, "")
        if callable(current):
            return ""
    if current is None:
        return ""
    return str(current)


def extract_placeholders(template: str) -> list[str]:
    """Return every ``{{ path }}`` / ``{{{ path }}}`` placeholder path in
    *template*, in document order, duplicates preserved. The single source of
    truth for "which placeholders does this template reference" — both
    validators below build on it so the extraction grammar can never drift
    from what :func:`render` actually substitutes."""
    if not template:
        return []
    return [
        match.group(1)
        for match in (*_RAW_RE.finditer(template), *_ESCAPED_RE.finditer(template))
    ]


def find_unsafe_placeholders(template: str) -> list[str]:
    """Return the placeholder paths in *template* that :func:`_resolve` would
    refuse on security grounds — any with a ``_``-prefixed (private/dunder)
    segment. Lets the write path reject a malicious tenant template up front
    instead of silently rendering it empty later.
    """
    return [
        path
        for path in extract_placeholders(template)
        if any(segment.startswith("_") for segment in path.split("."))
    ]


def find_undeclared_placeholders(
    template: str,
    declared: frozenset[str] | set[str],
    *,
    raw_keys: frozenset[str] = RAW_KEYS,
) -> list[str]:
    """Return placeholder paths in *template* that are neither declared for the
    template's slug nor a trusted raw key.

    ``declared`` is the set of ``EmailVariable.name`` values from the slug's
    registry spec (e.g. ``{"tenant_name", "member.first_name",
    "invoice.total", "tenant.bank_details"}``).

    A placeholder is ACCEPTED when, by full dotted path:

      * the exact path is declared (``member.first_name`` declared →
        ``{{ member.first_name }}`` ok), OR
      * the path's ROOT segment is declared as a dotted object — i.e. some
        declared name shares that root and is itself dotted, so the object is
        a known nested structure and any leaf under it is allowed
        (``invoice.total`` declared → root ``invoice`` known → ``{{
        invoice.due_date }}`` ok, ``{{ invoice.foo }}`` also ok since the
        spec opts the whole object in), OR
      * the path is a trusted raw key (``invoices_table``).

    A FLAT declared name (no dot, e.g. ``tenant_name``) only matches that
    exact flat path — it does NOT open a ``tenant_name.x`` namespace. Note
    ``tenant_name`` (flat) and ``tenant.bank_details`` (root ``tenant``)
    legitimately coexist; only the latter opens the ``tenant`` object.

    Returned in document order, duplicates removed (first occurrence kept).
    """
    # Roots that a declared *dotted* path opens up as a nested object.
    object_roots = {name.split(".", 1)[0] for name in declared if "." in name}
    undeclared: list[str] = []
    seen: set[str] = set()
    for path in extract_placeholders(template):
        if path in seen:
            continue
        if path in declared or path in raw_keys:
            continue
        root = path.split(".", 1)[0]
        if "." in path and root in object_roots:
            continue
        seen.add(path)
        undeclared.append(path)
    return undeclared


def render(
    template: str,
    context: Mapping[str, Any],
    *,
    raw_keys: frozenset[str] = RAW_KEYS,
) -> str:
    """Render ``template`` with the given context. ``raw_keys`` names context
    keys emitted unescaped even via ``{{ key }}`` (trusted server-built markup)."""
    if not template:
        return ""

    # Raw substitutions first (so {{{x}}} doesn't get eaten as {{x}} + }).
    def raw_sub(match: re.Match[str]) -> str:
        key = match.group(1)
        value = _resolve(key, context)
        # INJ-2: emit unescaped HTML only for trusted server-built markup
        # (``raw_keys``). A tenant admin wrapping a user-controlled field in
        # ``{{{ }}}`` gets it HTML-escaped instead — the safe default — so the
        # triple-brace syntax can't be turned into an XSS vector in the body.
        return value if key in raw_keys else escape(value, quote=True)

    out = _RAW_RE.sub(raw_sub, template)

    def escaped_sub(match: re.Match[str]) -> str:
        key = match.group(1)
        value = _resolve(key, context)
        # Trusted, pre-escaped server markup is emitted as-is; all other
        # substitutions stay HTML-escaped (the safe default).
        return value if key in raw_keys else escape(value, quote=True)

    return _ESCAPED_RE.sub(escaped_sub, out)


def render_subject(template: str, context: Mapping[str, Any]) -> str:
    """Render a subject line. Same rules, but newlines are stripped."""
    return render(template, context).replace("\n", " ").replace("\r", " ").strip()
