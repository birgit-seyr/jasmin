"""The Sentry/GlitchTip hooks scrub email/IP/IBAN substrings from breadcrumbs,
the event's log entry and its exception values, and request bodies are never
attached, so app-authored PII doesn't accumulate in the monitoring store
(beyond the reach of the Art. 17 erasure pipeline)."""

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


class TestScrubIban:
    def test_scrubs_compact_iban(self):
        assert scrub_pii("iban=DE89370400440532013000 ok") == "iban=<iban> ok"

    def test_scrubs_spaced_iban(self):
        assert scrub_pii("iban DE89 3704 0044 0532 0130 00.") == "iban <iban>."

    def test_leaves_a_record_id_alone(self):
        assert scrub_pii("member=AB12cdEFgh34") == "member=AB12cdEFgh34"


class TestBeforeSendFormattedParamsAndExceptions:
    def test_scrubs_formatted_message(self):
        event = {
            "logentry": {
                "message": "tenant.create_failed ip=%s user=%s iban=%s",
                "formatted": (
                    "tenant.create_failed ip=203.0.113.42 user=eve@example.com "
                    "iban=DE89370400440532013000"
                ),
            }
        }
        out = before_send(event, None)
        assert out["logentry"]["formatted"] == (
            "tenant.create_failed ip=<ip> user=<email> iban=<iban>"
        )

    def test_scrubs_every_string_param(self):
        event = {
            "logentry": {
                "message": "%s %s %s %s",
                "params": [
                    "203.0.113.42",
                    "eve@example.com",
                    "DE89370400440532013000",
                    7,
                ],
            }
        }
        out = before_send(event, None)
        assert out["logentry"]["params"] == ["<ip>", "<email>", "<iban>", 7]

    def test_scrubs_named_params(self):
        event = {"logentry": {"params": {"who": "eve@example.com", "n": 3}}}
        out = before_send(event, None)
        assert out["logentry"]["params"] == {"who": "<email>", "n": 3}

    def test_scrubs_exception_values(self):
        event = {
            "exception": {
                "values": [
                    {"type": "ValueError", "value": "bad iban DE89370400440532013000"},
                    {"type": "KeyError", "value": "eve@example.com from 10.0.0.1"},
                ]
            }
        }
        out = before_send(event, None)
        values = out["exception"]["values"]
        assert values[0]["value"] == "bad iban <iban>"
        assert values[1]["value"] == "<email> from <ip>"
        assert values[0]["type"] == "ValueError"

    def test_survives_unexpected_shapes(self):
        odd_events = [
            {"logentry": "not a dict"},
            {"logentry": {"params": "a string", "formatted": None}},
            {"logentry": {"params": None}},
            {"exception": "not a dict"},
            {"exception": {"values": None}},
            {"exception": {"values": ["not a dict", {"value": None}, {}]}},
            {"exception": [{"value": "eve@example.com"}]},
            {"breadcrumbs": "not a list"},
        ]
        for event in odd_events:
            assert before_send(event, None) is event


class TestInitSentry:
    def test_never_attaches_request_bodies(self, monkeypatch):
        from core import sentry_setup

        captured: dict = {}
        monkeypatch.setattr(
            sentry_setup.sentry_sdk, "init", lambda **kwargs: captured.update(kwargs)
        )
        sentry_setup.init_sentry("https://key@example.invalid/1", debug=False)

        assert captured["max_request_body_size"] == "never"
        assert captured["send_default_pii"] is False
        assert captured["before_send"] is before_send
        assert captured["before_breadcrumb"] is before_breadcrumb
        assert captured["environment"] == "production"
