"""GDPR-MIN-2: the Sentry/GlitchTip hooks scrub email/IP substrings from
breadcrumb + event messages so app-authored log PII doesn't accumulate in the
monitoring store (beyond the reach of the Art. 17 erasure pipeline)."""

from __future__ import annotations

from core.sentry_scrub import before_breadcrumb, before_send, scrub_pii


class TestScrubPii:
    def test_scrubs_email(self):
        assert (
            scrub_pii("2fa.verified user=alice@example.com method=totp")
            == "2fa.verified user=<email> method=totp"
        )

    def test_scrubs_ipv4(self):
        assert scrub_pii("logout.success ip=203.0.113.42") == "logout.success ip=<ip>"

    def test_scrubs_both(self):
        assert scrub_pii("u=bob@x.co ip=10.0.0.1") == "u=<email> ip=<ip>"

    def test_non_string_passthrough(self):
        assert scrub_pii(None) is None
        assert scrub_pii(42) == 42

    def test_no_pii_unchanged(self):
        assert (
            scrub_pii("password_reset.request unknown")
            == "password_reset.request unknown"
        )


class TestBeforeBreadcrumb:
    def test_scrubs_breadcrumb_message(self):
        crumb = {"message": "login user=alice@example.com from 198.51.100.7"}
        assert before_breadcrumb(crumb, None)["message"] == (
            "login user=<email> from <ip>"
        )

    def test_no_message_key_passthrough(self):
        assert before_breadcrumb({"category": "x"}, None) == {"category": "x"}


class TestBeforeSend:
    def test_scrubs_logentry_and_breadcrumbs(self):
        event = {
            "logentry": {"message": "boom for carol@example.org"},
            "breadcrumbs": {"values": [{"message": "seen dave@example.net"}]},
        }
        out = before_send(event, None)
        assert out["logentry"]["message"] == "boom for <email>"
        assert out["breadcrumbs"]["values"][0]["message"] == "seen <email>"

    def test_breadcrumbs_as_bare_list(self):
        event = {"breadcrumbs": [{"message": "from ip 172.16.0.9"}]}
        assert before_send(event, None)["breadcrumbs"][0]["message"] == "from ip <ip>"

    def test_empty_event_passthrough(self):
        assert before_send({}, None) == {}
