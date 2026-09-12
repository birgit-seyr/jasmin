"""Web-app install: launcher-icon validation, the manifest, and the icon route.

Three things are load-bearing and each has a test here:

1. ``validate_app_icon`` is the ONLY gate on shape — DRF's auto-mapped
   ``ImageField`` proves "decodes as an image" and nothing else.
2. The manifest is per-tenant. One built bundle serves every subdomain, so if
   this ever went static, every tenant's install would be branded identically.
3. The icon is served WITHOUT credentials. Every other media URL on this
   platform carries an expiring ``?st=`` token; an installed home screen would
   show a broken icon a day later if this route ever went back through that
   gate, so the anonymous-fetch assertion is the regression guard.
"""

from __future__ import annotations

import json
from io import BytesIO

import pytest
from django.core.files.base import ContentFile
from django.db import connection
from django.test import override_settings
from PIL import Image
from rest_framework.test import APIClient

from apps.shared.tenants.errors import NoTenantContext, TenantAppIconInvalid
from apps.shared.tenants.serializers import TenantSerializer
from apps.shared.tenants.views import FALLBACK_APP_ICON_PATH, _tenant_from_schema

MANIFEST_URL = "/api/tenants/manifest.webmanifest"
APP_ICON_URL = "/api/tenants/app-icon.png"
TENANT_HOST = "tenants-pytest.localhost"


def _image_bytes(width: int, height: int, image_format: str = "PNG") -> bytes:
    buffer = BytesIO()
    mode = "RGBA" if image_format == "PNG" else "RGB"
    Image.new(mode, (width, height), "green").save(buffer, format=image_format)
    return buffer.getvalue()


def _upload(width: int, height: int, image_format: str = "PNG") -> ContentFile:
    payload = _image_bytes(width, height, image_format)
    suffix = "png" if image_format == "PNG" else image_format.lower()
    return ContentFile(payload, name=f"icon.{suffix}")


def _validate(upload):
    """Run the field validator in isolation — no DB write, no storage."""
    return TenantSerializer().validate_app_icon(upload)


@pytest.fixture()
def anon_client():
    """Unauthenticated client on the tenant host.

    The launcher fetching a manifest or icon has no session, so every test
    that exercises those routes must use this and never ``api_client``.
    """
    return APIClient(HTTP_HOST=TENANT_HOST)


@pytest.fixture()
def tenant_with_icon(tenant):
    tenant.app_icon.save("icon.png", ContentFile(_image_bytes(512, 512)), save=True)
    yield tenant
    tenant.app_icon.delete(save=True)


class TestAppIconValidation:
    def test_accepts_square_png_and_normalizes_to_512(self):
        result = _validate(_upload(1024, 1024))

        assert result.name == "app_icon.png"
        rendered = Image.open(BytesIO(result.read()))
        assert rendered.size == (512, 512)
        # PNG regardless of input format, so the manifest's hardcoded
        # ``type: image/png`` stays truthful.
        assert rendered.format == "PNG"

    def test_accepts_jpeg_and_re_encodes_it_as_png(self):
        result = _validate(_upload(512, 512, image_format="JPEG"))

        rendered = Image.open(BytesIO(result.read()))
        assert rendered.format == "PNG"
        assert rendered.size == (512, 512)

    def test_accepts_exactly_the_minimum_size(self):
        assert _validate(_upload(512, 512)) is not None

    def test_rejects_a_decompression_bomb_that_slips_under_the_byte_cap(self):
        """The byte cap does NOT bound pixels — this is the guard that does.

        Flat-colour PNG compresses ~3500:1, so a 12000x12000 single-colour
        image is tens of kilobytes: square, over the 512px minimum, under the
        2 MB cap, and structurally valid. Decoding it allocates roughly a
        gigabyte in a worker shared by every tenant, and Pillow does not stop
        it — 144 MP sits in the warning-only band below the 2x threshold that
        raises DecompressionBombError.

        The upload must be rejected from the HEADER, before any decode.
        """
        bomb = _upload(12000, 12000)
        assert bomb.size < 2 * 1024 * 1024, "fixture must stay under the byte cap"

        with pytest.raises(TenantAppIconInvalid) as excinfo:
            _validate(bomb)

        assert excinfo.value.code == "tenant.app_icon_invalid"
        assert "12000x12000" in str(excinfo.value)

    def test_rejects_non_square(self):
        with pytest.raises(TenantAppIconInvalid) as excinfo:
            _validate(_upload(1024, 768))

        assert excinfo.value.code == "tenant.app_icon_invalid"
        assert "1024x768" in str(excinfo.value)

    def test_rejects_below_minimum_size(self):
        with pytest.raises(TenantAppIconInvalid) as excinfo:
            _validate(_upload(256, 256))

        assert excinfo.value.code == "tenant.app_icon_invalid"

    def test_rejects_oversized_payload(self):
        upload = ContentFile(b"x" * (2 * 1024 * 1024 + 1), name="huge.png")

        with pytest.raises(TenantAppIconInvalid) as excinfo:
            _validate(upload)

        assert excinfo.value.code == "tenant.app_icon_invalid"

    def test_rejects_non_image_bytes(self):
        upload = ContentFile(b"this is not an image", name="icon.png")

        with pytest.raises(TenantAppIconInvalid) as excinfo:
            _validate(upload)

        assert excinfo.value.code == "tenant.app_icon_invalid"

    @pytest.mark.parametrize("empty", [None, ""])
    def test_clearing_the_field_passes_through(self, empty):
        """``PATCH {"app_icon": null}`` is how the upload widget clears it."""
        assert _validate(empty) == empty


@pytest.mark.django_db
class TestManifest:
    def test_serves_the_tenants_own_name_unauthenticated(self, tenant, anon_client):
        response = anon_client.get(MANIFEST_URL)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/manifest+json"
        manifest = json.loads(response.content)
        assert manifest["name"] == tenant.name
        assert manifest["display"] == "standalone"
        assert manifest["start_url"] == "/"
        assert manifest["scope"] == "/"
        # ``id`` pins install identity — changing it later reads as a different
        # app to an already-installed client, so it is asserted explicitly.
        assert manifest["id"] == "/"

    def test_falls_back_to_the_platform_icon_when_none_uploaded(
        self, tenant, anon_client
    ):
        response = anon_client.get(MANIFEST_URL)

        icons = json.loads(response.content)["icons"]
        # Never an empty list: that would make the app non-installable.
        assert len(icons) == 1
        assert icons[0]["src"] == FALLBACK_APP_ICON_PATH
        assert icons[0]["sizes"] == "512x512"
        assert icons[0]["purpose"] == "any"

    def test_points_at_the_tenant_icon_with_a_cache_buster(
        self, tenant_with_icon, anon_client
    ):
        icons = json.loads(anon_client.get(MANIFEST_URL).content)["icons"]

        assert icons[0]["src"].startswith(f"{APP_ICON_URL}?v=")
        assert icons[0]["type"] == "image/png"

    def test_short_name_falls_back_to_a_truncated_name(self, tenant, anon_client):
        tenant.name = "A Very Long Community Farm Name"
        tenant.app_short_name = ""
        tenant.save(update_fields=["name", "app_short_name"])

        manifest = json.loads(anon_client.get(MANIFEST_URL).content)

        assert manifest["short_name"] == "A Very Long "
        assert len(manifest["short_name"]) <= 12

    def test_short_name_is_used_when_set(self, tenant, anon_client):
        tenant.app_short_name = "Gemüsehof"
        tenant.save(update_fields=["app_short_name"])

        manifest = json.loads(anon_client.get(MANIFEST_URL).content)

        assert manifest["short_name"] == "Gemüsehof"

    def test_is_browser_cacheable_but_never_shared_cacheable(self, tenant, anon_client):
        """``ApiNoStoreCacheControlMiddleware`` allowlists this path, so the
        view's own header must survive — and must stay ``private``, since a
        shared CDN keying without Host would cross-serve tenant branding."""
        cache_control = anon_client.get(MANIFEST_URL)["Cache-Control"]

        assert "max-age" in cache_control
        assert "private" in cache_control
        assert "public" not in cache_control

    def test_icon_stamp_changes_when_the_icon_is_replaced(
        self, tenant_with_icon, anon_client
    ):
        """Without a changing stamp, replacing an icon would leave every
        client on the old one for the icon route's full max-age."""
        first = json.loads(anon_client.get(MANIFEST_URL).content)["icons"][0]["src"]

        tenant_with_icon.app_icon.save(
            "icon.png", ContentFile(_image_bytes(512, 512)), save=True
        )
        second = json.loads(anon_client.get(MANIFEST_URL).content)["icons"][0]["src"]

        assert "?v=" in first and "?v=" in second
        assert first != second

    def test_refuses_to_render_without_a_tenant_context(self, tenant):
        """The platform host never reaches this view (``public_urls`` doesn't
        include this urlconf), but the guard is what makes that safe."""
        connection.set_schema_to_public()
        try:
            with pytest.raises(NoTenantContext):
                _tenant_from_schema()
        finally:
            connection.set_tenant(tenant)


@pytest.mark.django_db
class TestAppIconRoute:
    def test_404s_when_no_icon_uploaded(self, tenant, anon_client):
        assert anon_client.get(APP_ICON_URL).status_code == 404

    def test_serves_without_any_credentials(self, tenant_with_icon, anon_client):
        """The regression guard for the whole design.

        If someone routes this back through ``protected_media_view``, this
        turns 403 — and every already-installed home screen silently breaks
        24h later when the signature expires.
        """
        response = anon_client.get(APP_ICON_URL)

        assert response.status_code == 200
        assert "st=" not in response.get("X-Accel-Redirect", "")

    def test_delegates_the_file_read_to_nginx_in_production_mode(
        self, tenant_with_icon, anon_client
    ):
        response = anon_client.get(APP_ICON_URL)

        redirect = response["X-Accel-Redirect"]
        assert redirect.startswith("/_protected_media/")
        # The tenant-relative layout puts the schema first; asserting it here
        # keeps the internal path honest if the storage layout ever changes.
        assert connection.schema_name in redirect
        assert "app_icons/" in redirect

    @override_settings(DEBUG=True)
    def test_streams_the_file_directly_in_debug(self, tenant_with_icon, anon_client):
        response = anon_client.get(APP_ICON_URL)

        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"
        assert b"".join(response.streaming_content).startswith(b"\x89PNG")

    def test_is_browser_cacheable_but_never_shared_cacheable(
        self, tenant_with_icon, anon_client
    ):
        cache_control = anon_client.get(APP_ICON_URL)["Cache-Control"]

        assert "max-age" in cache_control
        assert "private" in cache_control
        assert "public" not in cache_control


@pytest.mark.django_db
class TestAppIconVersionExposure:
    """Every tenant payload the frontend can hold must carry the stamp.

    ``TenantContext`` swaps the anonymous payload for the authenticated one
    after login (and for a narrowed one for non-staff roles). If any of the
    three drops the field, the apple-touch-icon silently reverts to the
    platform fallback for that role and cannot recover without a reload.
    """

    @pytest.mark.parametrize(
        "serializer_name",
        ["CurrentTenantSerializer", "TenantSerializer", "TenantNonStaffReadSerializer"],
    )
    def test_all_three_tenant_serializers_expose_the_stamp(
        self, tenant_with_icon, serializer_name
    ):
        from apps.shared.tenants import serializers as tenant_serializers

        serializer_class = getattr(tenant_serializers, serializer_name)
        data = serializer_class(tenant_with_icon).data

        assert "app_icon_version" in data, serializer_name
        assert data["app_icon_version"], "stamp must be non-empty when an icon is set"

    def test_stamp_is_empty_without_an_icon(self, tenant):
        from apps.shared.tenants.serializers import CurrentTenantSerializer

        assert CurrentTenantSerializer(tenant).data["app_icon_version"] == ""
