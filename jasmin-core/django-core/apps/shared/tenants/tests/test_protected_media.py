"""Signed-URL protection for ``/media/`` (``core/protected_media.py``).

nginx proxies every ``/media/`` request to Django; the view only lets a
request through when it carries a valid, unexpired ``?st=`` capability
token. The storage backend mints those tokens in ``.url()``, so the two
halves are tested together here: what the storage signs, the view must
accept — and nothing else.

Only PDFs and pictures may render in the browser; every other file goes out
as an attachment, and the gateway adds a CSP sandbox to it. The view and the
nginx configs each keep that list, so the last class holds them together.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import pytest
import time_machine
from django.core import signing
from django.test import RequestFactory, override_settings

from core.protected_media import (
    _SALT,
    SignedTenantFileSystemStorage,
    media_token_is_valid,
    protected_media_view,
    sign_media_path,
)

pytestmark = pytest.mark.django_db

# This file lives at apps/shared/tenants/tests/<file>, so django-core is four
# up and the repo root two above that.
DJANGO_CORE = Path(__file__).resolve().parents[4]
NGINX_DIR = DJANGO_CORE.parent.parent / "nginx"

INLINE_MEDIA = [
    "invoicesresellers/RE-2026-001.pdf",
    "consents/privacy-v3.PDF",
    "logos/logo.png",
    "share_pictures/carrots.jpg",
    "avatars/me.JPEG",
    "share_pictures/beans.gif",
    "share_pictures/kale.webp",
    "share_pictures/tomato.xml.png",
]
ATTACHMENT_MEDIA = [
    "invoicesresellers/RE-2026-001.xml",
    "billing_runs/billing_run_12.xml",
    "share_imports/2026/10/shares.csv",
    "logos/logo.svg",
    "share_pictures/page.html",
    "share_pictures/page.xhtml",
    "invoicesresellers/RE-2026-001.pdf.xml",
    "share_imports/README",
]


class TestMediaToken:
    def test_round_trip(self):
        path = "test_tenants/logos/logo.png"
        assert media_token_is_valid(path, sign_media_path(path))

    def test_token_is_bound_to_the_exact_path(self):
        token = sign_media_path("test_tenants/docs/invoice-1.pdf")
        assert not media_token_is_valid("test_tenants/docs/invoice-2.pdf", token)

    def test_tampered_token_rejected(self):
        path = "test_tenants/docs/invoice-1.pdf"
        token = sign_media_path(path)
        assert not media_token_is_valid(path, token[:-2])

    def test_token_expires(self):
        path = "test_tenants/docs/invoice-1.pdf"
        with time_machine.travel("2026-06-01 12:00:00"):
            token = sign_media_path(path)
            assert media_token_is_valid(path, token)
        # Default max age is 24h — two days later the link is dead.
        with time_machine.travel("2026-06-03 12:00:00"):
            assert not media_token_is_valid(path, token)

    def test_token_is_stable_within_a_bucket(self):
        # The caching win: two signs in the same time bucket → IDENTICAL token,
        # so the media URL (and its cache key) doesn't rotate on every refetch.
        path = "test_tenants/logos/logo.png"
        with time_machine.travel("2026-06-01 12:00:00", tick=False):
            assert sign_media_path(path) == sign_media_path(path)

    def test_token_rotates_across_buckets_but_stays_valid(self):
        path = "test_tenants/logos/logo.png"
        with time_machine.travel("2026-06-01 12:00:00", tick=False):
            early = sign_media_path(path)
        with time_machine.travel("2026-06-01 14:00:00", tick=False):
            later = sign_media_path(path)
            # Different bucket → different token string...
            assert early != later
            # ...but the earlier one is still valid (well within the 24h window).
            assert media_token_is_valid(path, early)

    def test_legacy_timestampsigner_token_is_accepted(self):
        # Backward compat during a deploy: a token minted by the OLD per-sign
        # scheme (signing.dumps) that's still in flight in a live browser must
        # keep validating so the ?st= URL doesn't 403 mid-deploy.
        path = "test_tenants/docs/invoice-1.pdf"
        legacy = signing.dumps(path, salt=_SALT, compress=True)
        assert media_token_is_valid(path, legacy)

    def test_legacy_token_still_expires_and_is_path_bound(self):
        path = "test_tenants/docs/invoice-1.pdf"
        with time_machine.travel("2026-06-01 12:00:00"):
            legacy = signing.dumps(path, salt=_SALT, compress=True)
            assert media_token_is_valid(path, legacy)
            # Path binding holds for the legacy branch too.
            assert not media_token_is_valid("test_tenants/docs/other.pdf", legacy)
        with time_machine.travel("2026-06-03 12:00:00"):
            assert not media_token_is_valid(path, legacy)


class TestSignedStorageUrl:
    def test_url_carries_a_token_the_view_accepts(self, tenant):
        storage = SignedTenantFileSystemStorage()
        url = storage.url("docs/Ünïcode invoice.pdf")

        split = urlsplit(url)
        assert split.path.startswith("/media/")
        token = parse_qs(split.query)["st"][0]
        # The view receives the percent-DECODED path from the URL
        # resolver — that's the form the token must validate against.
        decoded_path = unquote(split.path[len("/media/") :])
        assert media_token_is_valid(decoded_path, token)


class TestProtectedMediaView:
    def _get(self, path: str, token: str | None = None):
        params = {"st": token} if token is not None else {}
        request = RequestFactory().get("/media/" + path, params)
        return protected_media_view(request, path=path)

    def test_missing_token_is_403(self):
        assert self._get("test_tenants/docs/invoice-1.pdf").status_code == 403

    def test_garbage_token_is_403(self):
        response = self._get("test_tenants/docs/invoice-1.pdf", token="garbage")
        assert response.status_code == 403

    def test_path_traversal_is_403_even_with_valid_token(self):
        path = "../config/settings.py"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 403

    def test_control_char_in_path_is_403(self):
        # A null byte dodges the ``".." in split`` component check; the
        # control-char guard must catch it. (The signature would reject
        # it anyway — defense in depth.)
        path = "test_tenants/..\x00/secret.pdf"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 403

    def test_cross_tenant_token_is_403(self, tenant):
        # ``tenant`` fixture → connection schema is ``test_tenants``.
        # A perfectly-signed token for ANOTHER tenant's file must not be
        # served on this tenant's request.
        path = "other_tenant/docs/invoice-1.pdf"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 403

    @override_settings(DEBUG=False)
    def test_valid_token_hands_off_to_nginx(self, tenant):
        path = "test_tenants/docs/invoice-1.pdf"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 200
        assert (
            response.headers["X-Accel-Redirect"]
            == "/_protected_media/test_tenants/docs/invoice-1.pdf"
        )
        # Django's default text/html must be dropped so nginx derives
        # the type from the file extension at the internal location.
        assert "Content-Type" not in response.headers

    @override_settings(DEBUG=False)
    @pytest.mark.parametrize("name", INLINE_MEDIA)
    def test_pdfs_and_pictures_are_left_to_render_inline(self, tenant, name):
        path = f"test_tenants/{name}"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 200
        assert "Content-Disposition" not in response.headers

    @override_settings(DEBUG=False)
    @pytest.mark.parametrize("name", ATTACHMENT_MEDIA)
    def test_other_files_are_handed_off_as_attachments(self, tenant, name):
        # Opened in a tab, an XHTML-namespaced XML or an SVG would run script
        # on the tenant origin. nginx carries the header across the redirect;
        # without a filename, the name an ``<a download>`` link asks for wins.
        path = f"test_tenants/{name}"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 200
        assert response.headers["X-Accel-Redirect"] == quote(
            "/_protected_media/" + path
        )
        assert response.headers["Content-Disposition"] == "attachment"

    def test_debug_streams_the_file_directly(self, tenant, tmp_path, settings):
        settings.DEBUG = True
        settings.MEDIA_ROOT = tmp_path
        (tmp_path / "test_tenants").mkdir()
        file_path = tmp_path / "test_tenants" / "note.pdf"
        file_path.write_bytes(b"%PDF-1.7 test")

        path = "test_tenants/note.pdf"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == b"%PDF-1.7 test"
        assert response.headers["Content-Disposition"].startswith("inline")

    def test_debug_streams_other_files_as_attachments(self, tenant, tmp_path, settings):
        settings.DEBUG = True
        settings.MEDIA_ROOT = tmp_path
        (tmp_path / "test_tenants").mkdir()
        file_path = tmp_path / "test_tenants" / "RE-2026-001.xml"
        file_path.write_bytes(b"<Invoice/>")

        path = "test_tenants/RE-2026-001.xml"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == b"<Invoice/>"
        # Replaces FileResponse's own ``inline; filename="..."``.
        assert response.headers["Content-Disposition"] == "attachment"
        response.close()

    def test_debug_missing_file_is_404(self, tenant, tmp_path, settings):
        settings.DEBUG = True
        settings.MEDIA_ROOT = tmp_path
        path = "test_tenants/gone.pdf"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 404


_COMMENT = re.compile(r"#.*$", re.MULTILINE)
_MAP_ENTRY = re.compile(r'^\s*(\S+)\s+("[^"]*"|\S+)\s*;\s*$', re.MULTILINE)


def _nginx_config(name: str) -> str:
    """``nginx/<name>`` without its comments."""
    path = NGINX_DIR / name
    if not path.is_file():
        pytest.skip(f"nginx/{name} is not in this checkout")
    return _COMMENT.sub("", path.read_text(encoding="utf-8"))


def _block_bodies(config: str, opener: str) -> list[str]:
    """The bodies of every ``<opener> { ... }`` block; none of these nest."""
    return re.findall(opener + r"\s*\{([^{}]*)\}", config)


def _directives(body: str) -> set[str]:
    return {" ".join(part.split()) + ";" for part in body.split(";") if part.strip()}


def _map(config: str, source: str, name: str) -> dict[str, str]:
    bodies = _block_bodies(config, rf"\bmap\s+{re.escape(source)}\s+{re.escape(name)}")
    assert len(bodies) == 1, f"expected one `map {source} {name}` block"
    return {key: value.strip('"') for key, value in _MAP_ENTRY.findall(bodies[0])}


def _map_value(entries: dict[str, str], value: str) -> str:
    """What nginx resolves ``value`` to: the first matching regex, else the default."""
    for key, result in entries.items():
        if key.startswith("~*"):
            matched = re.search(key[2:], value, re.IGNORECASE)
        elif key.startswith("~"):
            matched = re.search(key[1:], value)
        else:
            continue
        if matched:
            return result
    return entries["default"]


class TestGatewayMediaHeaders:
    """nginx's half: nginx/nginx.conf.template in production, nginx.conf.local
    in dev. nginx does not carry a CSP header across the X-Accel-Redirect, so
    the sandbox exists only in these configs."""

    PROTECTED_MEDIA_DIRECTIVES = {
        "add_header Content-Security-Policy $protected_media_csp always;",
        "add_header Content-Disposition $protected_media_disposition;",
        'add_header Cache-Control "private, max-age=2592000";',
        'add_header X-Content-Type-Options "nosniff";',
        # A location with an add_header of its own inherits none from the server.
        "include /etc/nginx/security_headers.conf;",
    }

    def test_every_protected_media_location_sends_the_headers(self):
        locations = _block_bodies(
            _nginx_config("nginx.conf.template"), r"location\s+/_protected_media/"
        )
        assert len(locations) == 2, "expected the tenant and the super-admin block"
        for body in locations:
            assert self.PROTECTED_MEDIA_DIRECTIVES <= _directives(body)

    def test_the_gateway_disposition_only_stands_in_for_the_backend(self):
        # Django sends the disposition itself, and a second header line would
        # make the response invalid.
        entries = _map(
            _nginx_config("nginx.conf.template"),
            "$upstream_http_content_disposition",
            "$protected_media_disposition",
        )
        assert entries == {'""': "$protected_media_attachment", "default": ""}

    def test_the_dev_gateway_sandboxes_media(self):
        locations = _block_bodies(
            _nginx_config("nginx.conf.local"), r"location\s+/media/"
        )
        assert len(locations) == 1
        assert (
            "add_header Content-Security-Policy $protected_media_csp always;"
            in _directives(locations[0])
        )

    @override_settings(DEBUG=False)
    @pytest.mark.parametrize("name", INLINE_MEDIA + ATTACHMENT_MEDIA)
    def test_the_gateways_and_the_view_agree_on_what_renders_inline(self, tenant, name):
        template = _nginx_config("nginx.conf.template")
        csp = _map(template, "$uri", "$protected_media_csp")
        attachment = _map(template, "$uri", "$protected_media_attachment")
        dev_csp = _map(
            _nginx_config("nginx.conf.local"), "$uri", "$protected_media_csp"
        )

        path = f"test_tenants/{name}"
        request = RequestFactory().get("/media/" + path, {"st": sign_media_path(path)})
        response = protected_media_view(request, path=path)
        inline = "Content-Disposition" not in response.headers

        sandbox = "" if inline else "sandbox; default-src 'none'"
        assert _map_value(csp, f"/_protected_media/{path}") == sandbox
        assert _map_value(dev_csp, f"/media/{path}") == sandbox
        assert _map_value(attachment, f"/_protected_media/{path}") == (
            "" if inline else "attachment"
        )
