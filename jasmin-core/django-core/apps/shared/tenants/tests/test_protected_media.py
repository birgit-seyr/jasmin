"""Signed-URL protection for ``/media/`` (``core/protected_media.py``).

nginx proxies every ``/media/`` request to Django; the view only lets a
request through when it carries a valid, unexpired ``?st=`` capability
token. The storage backend mints those tokens in ``.url()``, so the two
halves are tested together here: what the storage signs, the view must
accept — and nothing else.
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlsplit

import pytest
import time_machine
from django.test import RequestFactory, override_settings

from core.protected_media import (
    SignedTenantFileSystemStorage,
    media_token_is_valid,
    protected_media_view,
    sign_media_path,
)

pytestmark = pytest.mark.django_db


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

    @override_settings(DEBUG=True)
    def test_debug_streams_the_file_directly(self, tenant, tmp_path, settings):
        settings.MEDIA_ROOT = tmp_path
        (tmp_path / "test_tenants").mkdir()
        file_path = tmp_path / "test_tenants" / "note.pdf"
        file_path.write_bytes(b"%PDF-1.7 test")

        path = "test_tenants/note.pdf"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == b"%PDF-1.7 test"

    @override_settings(DEBUG=True)
    def test_debug_missing_file_is_404(self, tenant, tmp_path, settings):
        settings.MEDIA_ROOT = tmp_path
        path = "test_tenants/gone.pdf"
        response = self._get(path, token=sign_media_path(path))
        assert response.status_code == 404
