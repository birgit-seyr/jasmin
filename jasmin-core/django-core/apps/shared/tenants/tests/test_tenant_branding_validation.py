"""Branding uploads and feature-flag groups on the tenant row.

``logo`` / ``bio_logo`` are served from the tenant's own origin with a
Content-Type derived from the stored file EXTENSION. Django's ImageField only
proves "decodes as an image under an image-ish extension" — a list that
includes formats no browser renders — and bounds neither bytes nor pixels. Both
fields therefore accept only a decodable PNG/JPEG/WEBP/GIF and store a
re-encode of it under a generated name, so neither the uploader's bytes nor
their file name reach storage.

``navigation`` / ``ai`` are free JSON the client reads as flag groups, so a
string or list there survives every "is anything configured?" test and only
fails deep inside the UI. A group the request does not change is left alone:
the configuration page echoes the whole tenant row back on every save.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from apps.commissioning.tests.factories import JasminUserFactory

LOGO_INVALID_CODE = "tenant.logo_invalid"
FLAGS_INVALID_CODE = "tenant.feature_flags_invalid"


def _image_bytes(image_format: str, size: tuple[int, int] = (8, 6)) -> bytes:
    buffer = BytesIO()
    mode = {"JPEG": "RGB", "GIF": "P", "BMP": "RGB"}.get(image_format, "RGBA")
    Image.new(mode, size, "green").save(buffer, format=image_format)
    return buffer.getvalue()


def _detail_url(tenant) -> str:
    return f"/api/tenants/tenants/{tenant.id}/"


@pytest.fixture()
def admin_client(tenant, tenant_host) -> APIClient:
    """Writes on the tenant row are gated by ``write_permission = IsAdmin``."""
    client = APIClient(HTTP_HOST=tenant_host)
    client.force_authenticate(user=JasminUserFactory(roles=["admin"]))
    return client


@pytest.fixture(autouse=True)
def _isolated_media_root(settings, tmp_path):
    """Keep uploaded test files out of the repo's media directory."""
    settings.MEDIA_ROOT = tmp_path


@pytest.mark.django_db
class TestBrandingPictureUploads:
    @pytest.mark.parametrize("field", ["logo", "bio_logo"])
    def test_the_stored_file_is_a_re_encode_under_a_generated_name(
        self, admin_client, tenant, field
    ):
        """What lands in storage is this backend's own PNG, not the uploaded
        bytes under the uploader's file name."""
        upload = SimpleUploadedFile(
            "brand.png", _image_bytes("PNG"), content_type="image/png"
        )

        response = admin_client.patch(
            _detail_url(tenant), {field: upload}, format="multipart"
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        tenant.refresh_from_db()
        stored_name = getattr(tenant, field).name
        assert stored_name.endswith(".png"), stored_name
        assert "brand" not in stored_name, stored_name

    @pytest.mark.parametrize("field", ["logo", "bio_logo"])
    def test_a_format_outside_the_allowlist_is_refused(
        self, admin_client, tenant, field
    ):
        """BMP decodes as an image — Django's own ImageField accepts it — but
        it is not one of the formats served back to a browser."""
        upload = SimpleUploadedFile(
            "logo.bmp", _image_bytes("BMP"), content_type="image/bmp"
        )

        response = admin_client.patch(
            _detail_url(tenant), {field: upload}, format="multipart"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert response.data["code"] == LOGO_INVALID_CODE
        assert response.data["field"] == field
        tenant.refresh_from_db()
        assert not getattr(tenant, field)

    @pytest.mark.parametrize("field", ["logo", "bio_logo"])
    def test_clearing_the_field_still_works(self, admin_client, tenant, field):
        """``null`` is the clear-the-picture path, not an upload to validate."""
        upload = SimpleUploadedFile(
            "brand.png", _image_bytes("PNG"), content_type="image/png"
        )
        admin_client.patch(_detail_url(tenant), {field: upload}, format="multipart")
        tenant.refresh_from_db()
        assert getattr(tenant, field)

        response = admin_client.patch(_detail_url(tenant), {field: None}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.data
        tenant.refresh_from_db()
        assert not getattr(tenant, field)


@pytest.mark.django_db
class TestFeatureFlagGroups:
    @pytest.mark.parametrize("field", ["navigation", "ai"])
    @pytest.mark.parametrize(
        "value",
        ["show_members", ["show_members"], 5],
        ids=["string", "list", "number"],
    )
    def test_a_non_object_group_is_refused(self, admin_client, tenant, field, value):
        response = admin_client.patch(
            _detail_url(tenant), {field: value}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert response.data["code"] == FLAGS_INVALID_CODE
        assert response.data["field"] == field
        tenant.refresh_from_db()
        assert getattr(tenant, field) != value

    @pytest.mark.parametrize("field", ["navigation", "ai"])
    def test_a_non_boolean_flag_value_is_refused(self, admin_client, tenant, field):
        response = admin_client.patch(
            _detail_url(tenant), {field: {"show_members": "yes"}}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.data
        assert response.data["code"] == FLAGS_INVALID_CODE
        tenant.refresh_from_db()
        assert getattr(tenant, field) != {"show_members": "yes"}

    @pytest.mark.parametrize("field", ["navigation", "ai"])
    def test_boolean_flags_are_accepted_and_unknown_names_survive(
        self, admin_client, tenant, field
    ):
        """The group grows with the UI, so a flag name this backend has never
        heard of is still stored."""
        flags = {"show_members": True, "a_flag_added_later": False}

        response = admin_client.patch(
            _detail_url(tenant), {field: flags}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        tenant.refresh_from_db()
        assert getattr(tenant, field) == flags

    @pytest.mark.parametrize("field", ["navigation", "ai"])
    def test_an_unchanged_group_is_accepted_verbatim(self, admin_client, tenant, field):
        """Compatibility guard: the configuration page re-sends the stored
        group with every unrelated edit, so a stored oddity must not lock the
        tenant out of editing anything else."""
        setattr(tenant, field, {"show_members": "yes"})
        tenant.save(update_fields=[field])

        response = admin_client.patch(
            _detail_url(tenant),
            {field: {"show_members": "yes"}, "app_short_name": "Acme"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        tenant.refresh_from_db()
        assert tenant.app_short_name == "Acme"
