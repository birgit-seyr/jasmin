"""Tests for the safe Mustache-style email template renderer.

Tenants paste arbitrary text into the template editor, so this renderer
MUST stay strict — XSS escaping for ``{{ var }}``, raw output for
``{{{ var }}}``, no other syntax accepted, no Django template tags
honoured. A regression here would let any tenant admin run code or
inject scripts into outgoing emails.
"""

from __future__ import annotations

import pytest

from apps.notifications.template_renderer import (
    RAW_KEYS,
    extract_placeholders,
    find_undeclared_placeholders,
    find_unsafe_placeholders,
    render,
    render_subject,
)


class TestRenderEscaped:
    def test_basic_substitution(self):
        assert render("Hi {{name}}", {"name": "Bia"}) == "Hi Bia"

    def test_escapes_html(self):
        out = render("Hi {{name}}", {"name": "<script>alert(1)</script>"})
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_escapes_quotes(self):
        out = render("attr={{v}}", {"v": '"x"'})
        assert "&quot;" in out

    def test_dotted_path_dict(self):
        ctx = {"user": {"first_name": "Bia"}}
        assert render("Hello {{user.first_name}}", ctx) == "Hello Bia"

    def test_dotted_path_attribute(self):
        class U:
            email = "b@example.com"

        out = render("{{user.email}}", {"user": U()})
        assert out == "b@example.com"

    def test_missing_key_renders_empty(self):
        assert render("X={{missing}}Y", {}) == "X=Y"

    def test_missing_dotted_path_renders_empty(self):
        # ``user`` exists but ``last_name`` does not.
        assert render("[{{user.last_name}}]", {"user": {}}) == "[]"

    def test_none_value_renders_empty(self):
        assert render("X={{v}}Y", {"v": None}) == "X=Y"


class TestRenderRaw:
    def test_raw_key_does_not_escape(self):
        # A RAW_KEYS entry carries trusted, server-built markup → emitted as-is.
        out = render("{{{invoices_table}}}", {"invoices_table": "<b>hi</b>"})
        assert out == "<b>hi</b>"

    def test_triple_brace_on_non_raw_key_is_escaped(self):
        # INJ-2: {{{ }}} around a NON-RAW_KEYS field (e.g. a tenant-controlled
        # value) is HTML-escaped — the triple-brace syntax can't be turned into
        # an XSS vector in the email body by a tenant admin.
        out = render("{{{html}}}", {"html": "<b>hi</b>"})
        assert out == "&lt;b&gt;hi&lt;/b&gt;"

    def test_raw_key_and_escaped_in_same_template(self):
        out = render(
            "{{{invoices_table}}}-{{b}}",
            {"invoices_table": "<x>", "b": "<y>"},
        )
        assert out == "<x>-&lt;y&gt;"


class TestRenderRefusesUnsafeSyntax:
    def test_django_tag_passes_through_untouched(self):
        # Critical: a tenant typing {% ... %} must NOT trigger Django.
        tpl = "{% load static %}{% include 'evil.html' %}{{x}}"
        out = render(tpl, {"x": "ok"})
        # The Django tags survive verbatim; only the Mustache var is
        # substituted. They will be sent as plain text in the email body.
        assert "{% load static %}" in out
        assert "{% include 'evil.html' %}" in out
        assert out.endswith("ok")

    def test_no_filter_pipeline(self):
        # ``{{ x|upper }}`` is Django syntax — our regex requires only
        # word chars + dots, so this becomes a no-op (unmatched) lookup.
        out = render("{{x|upper}}", {"x": "small"})
        # ``x|upper`` doesn't match the strict regex, so the literal
        # passes through.
        assert "{{x|upper}}" in out

    def test_unbalanced_braces_pass_through(self):
        out = render("{{x", {"x": "y"})
        assert out == "{{x"

    def test_empty_template(self):
        assert render("", {"any": 1}) == ""


class TestRenderSubject:
    def test_strips_newlines(self):
        out = render_subject("Hello\n{{name}}\r!", {"name": "Bia"})
        assert "\n" not in out and "\r" not in out
        assert out.strip().startswith("Hello")
        assert "Bia" in out


class _FakeModel:
    """Stand-in for a Django model instance: a plain data attribute plus a
    method (so ``.save.__globals__`` would reach module globals → settings)."""

    iban = "DE89 3704 0044 0532 0130 00"

    def save(self, *args, **kwargs):
        pass


class TestRenderSandboxEscape:
    """Tenant-edited templates must not walk object internals to exfiltrate
    the cluster SECRET_KEY / FIELD_ENCRYPTION_KEY (which sign every tenant's
    JWTs and decrypt every tenant's PII) or pivot via dunders. ``_resolve``
    rejects ``_``-prefixed (dunder/private) segments and refuses to traverse
    or render callables."""

    def test_globals_secret_key_escape_renders_empty(self):
        # The exact exploit shape from the audit.
        out = render(
            "[{{x.save.__globals__.settings.SECRET_KEY}}]", {"x": _FakeModel()}
        )
        assert out == "[]"

    def test_raw_form_of_escape_also_empty(self):
        out = render("[{{{x.save.__globals__}}}]", {"x": _FakeModel()})
        assert out == "[]"

    def test_dunder_class_renders_empty(self):
        assert render("[{{x.__class__}}]", {"x": _FakeModel()}) == "[]"

    def test_private_segment_blocked_even_if_present_in_context(self):
        # A ``_``-prefixed key is refused regardless of whether it exists.
        assert render("[{{_secret}}]", {"_secret": "nope"}) == "[]"

    def test_private_attribute_segment_blocked(self):
        assert render("[{{x._meta}}]", {"x": _FakeModel()}) == "[]"

    def test_bare_callable_renders_empty(self):
        assert render("[{{x.save}}]", {"x": _FakeModel()}) == "[]"

    def test_plain_attribute_still_resolves(self):
        # The renderer blocks the ESCAPE, not field reads — plain data
        # attributes still resolve. (Call-site context flattening is the
        # complementary defence for field-level exposure.)
        assert render("{{x.iban}}", {"x": _FakeModel()}) == _FakeModel.iban


class TestFindUnsafePlaceholders:
    def test_flags_private_and_dunder_paths(self):
        tpl = "{{ ok }} {{ x.__class__ }} {{{ y.save.__globals__ }}} {{ _p }}"
        flagged = set(find_unsafe_placeholders(tpl))
        assert {"x.__class__", "y.save.__globals__", "_p"} <= flagged
        assert "ok" not in flagged

    def test_safe_template_has_none(self):
        tpl = "Hi {{ user.first_name }} — {{ tenant_name }} ({{{ link }}})"
        assert find_unsafe_placeholders(tpl) == []


class TestExtractPlaceholders:
    def test_extracts_escaped_and_raw(self):
        # Raw matches come first, then escaped (mirrors the renderer's
        # substitution order and find_unsafe_placeholders). A {{{ raw }}}
        # placeholder also matches the escaped regex on its inner {{ }}, so it
        # legitimately appears twice — the dedup happens in the consumers.
        tpl = "Hi {{ a }} and {{{ b }}} and {{ c.d }}"
        result = extract_placeholders(tpl)
        assert set(result) == {"a", "b", "c.d"}
        # Raw ("b") is yielded before the escaped batch.
        assert result[0] == "b"

    def test_empty_template(self):
        assert extract_placeholders("") == []


class TestFindUndeclaredPlaceholders:
    """EML-10: a tenant override may only reference variables declared for its
    slug (plus trusted raw keys). Anything else would render silently empty, so
    the write path rejects it."""

    def test_exact_declared_path_accepted(self):
        declared = frozenset({"tenant_name", "user.first_name"})
        tpl = "Hi {{ user.first_name }} — {{ tenant_name }}"
        assert find_undeclared_placeholders(tpl, declared) == []

    def test_undeclared_path_flagged(self):
        declared = frozenset({"tenant_name", "user.first_name"})
        tpl = "Hi {{ user.first_name }} — {{ foo.bar }}"
        assert find_undeclared_placeholders(tpl, declared) == ["foo.bar"]

    def test_declared_object_root_opens_nested_leaves(self):
        # ``invoice.total`` declared opts the whole ``invoice`` object in, so a
        # sibling leaf the spec didn't enumerate is still accepted.
        declared = frozenset({"invoice.total"})
        tpl = "{{ invoice.total }} due {{ invoice.due_date }}"
        assert find_undeclared_placeholders(tpl, declared) == []

    def test_flat_declared_name_does_not_open_namespace(self):
        # ``tenant_name`` is flat — it must NOT permit ``tenant_name.x``. And
        # ``tenant.bank_details`` (root ``tenant``) coexists, opening ``tenant``.
        declared = frozenset({"tenant_name", "tenant.bank_details"})
        tpl = "{{ tenant_name }} {{ tenant.iban }} {{ tenant_name.evil }}"
        assert find_undeclared_placeholders(tpl, declared) == ["tenant_name.evil"]

    def test_raw_keys_always_allowed(self):
        declared = frozenset({"tenant_name"})
        tpl = "{{ invoices_table }}{{ invoices_text }}"
        assert find_undeclared_placeholders(tpl, declared) == []
        # And the default raw_keys arg is RAW_KEYS.
        assert "invoices_table" in RAW_KEYS

    def test_duplicates_deduped_first_occurrence(self):
        declared = frozenset({"tenant_name"})
        tpl = "{{ a }} {{ a }} {{ b }}"
        assert find_undeclared_placeholders(tpl, declared) == ["a", "b"]

    def test_empty_template(self):
        assert find_undeclared_placeholders("", frozenset({"x"})) == []


class TestEmailTemplateWriteValidation:
    """The IsAdmin-gated template editor must reject malicious placeholders at
    write time, not just neuter them at render — so the string never persists.
    (Validation is pure; no DB needed.)"""

    def test_update_serializer_rejects_dunder_placeholder(self):
        from apps.notifications.serializers import EmailTemplateUpdateSerializer

        ser = EmailTemplateUpdateSerializer(
            data={"body_html": "{{ x.save.__globals__.settings.SECRET_KEY }}"},
            partial=True,
        )
        assert not ser.is_valid()
        assert "body_html" in ser.errors

    def test_update_serializer_rejects_dunder_in_subject(self):
        # Subject-field coverage of the shared _SafeTemplateFieldsMixin (the
        # body_html case is covered above). Previously exercised the preview
        # request serializer, which shared the same mixin and has been removed.
        from apps.notifications.serializers import EmailTemplateUpdateSerializer

        ser = EmailTemplateUpdateSerializer(
            data={"subject": "{{ user.__class__ }}"}, partial=True
        )
        assert not ser.is_valid()
        assert "subject" in ser.errors

    def test_update_serializer_accepts_safe_placeholders(self):
        from apps.notifications.serializers import EmailTemplateUpdateSerializer

        ser = EmailTemplateUpdateSerializer(
            data={
                "subject": "{{ tenant_name }}",
                "body_html": "Hi {{ user.first_name }} — {{{ accept_url }}}",
            },
            partial=True,
        )
        assert ser.is_valid(), ser.errors


class TestEmailTemplateDeclaredVariableValidation:
    """EML-10: when the slug's spec is supplied in serializer context, the
    editor must reject any placeholder the spec doesn't declare (it would
    render empty with no warning), while accepting every declared variable and
    the trusted raw keys."""

    def _ser(self, slug, data):
        from apps.notifications.registry import get_spec
        from apps.notifications.serializers import EmailTemplateUpdateSerializer

        return EmailTemplateUpdateSerializer(
            data=data, partial=True, context={"spec": get_spec(slug)}
        )

    def test_template_using_every_declared_var_passes(self):
        # invitation declares tenant_name, user.first_name, user.email,
        # accept_url, expires_at.
        ser = self._ser(
            "accounts.invitation",
            {
                "subject": "{{ tenant_name }}",
                "body_html": (
                    "Hi {{ user.first_name }} ({{ user.email }}) — "
                    "{{{ accept_url }}} valid until {{ expires_at }}"
                ),
                "body_text": "{{ user.first_name }} {{ accept_url }}",
            },
        )
        assert ser.is_valid(), ser.errors

    def test_undeclared_placeholder_rejected_with_code_and_details(self):
        from apps.notifications.errors import UndeclaredPlaceholders

        ser = self._ser(
            "accounts.invitation",
            {"body_html": "Hi {{ user.first_name }} {{ foo.bar }}"},
        )
        with pytest.raises(UndeclaredPlaceholders) as exc_info:
            ser.is_valid(raise_exception=True)
        exc = exc_info.value
        assert exc.code == "email_template.undeclared_placeholders"
        assert exc.details["placeholders"] == ["foo.bar"]

    def test_raw_keys_allowed_under_strict_mode(self):
        # invoice_reminder declares the raw keys; even independent of that the
        # validator always permits RAW_KEYS.
        ser = self._ser(
            "commissioning.invoice_reminder",
            {
                "body_html": (
                    "{{ tenant_name }} {{ reseller.name }} "
                    "<table>{{ invoices_table }}</table> "
                    "{{ tenant.bank_details }}"
                ),
                "body_text": "{{ invoices_text }}",
            },
        )
        assert ser.is_valid(), ser.errors

    def test_member_application_templates_pass_after_completeness_pass(self):
        # Regression for the EML-10 registry-completeness gap: the shipped
        # application templates reference member.* which the registry now
        # declares. A tenant override copying the default must validate.
        ser = self._ser(
            "accounts.application_rejected",
            {
                "subject": "{{ tenant_name }}",
                "body_html": (
                    "Hi {{ member.first_name }} (#{{ member.member_number }}) "
                    "— {{ member.admin_rejection_reason }} / {{ reason }}"
                ),
            },
        )
        assert ser.is_valid(), ser.errors

    def test_without_spec_context_declared_check_is_skipped(self):
        # Standalone use (no viewset) keeps working — only the unsafe-dunder
        # check runs, not the declared-variable gate.
        from apps.notifications.serializers import EmailTemplateUpdateSerializer

        ser = EmailTemplateUpdateSerializer(
            data={"body_html": "{{ totally.undeclared }}"}, partial=True
        )
        assert ser.is_valid(), ser.errors
