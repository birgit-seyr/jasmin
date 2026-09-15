"""Picture uploads on ShareTypeVariation and DeliveryStation must be images.

Media is served from the tenant origin with a Content-Type derived from the
stored file EXTENSION, so an ``.html`` / ``.svg`` "picture" (or a PNG renamed
``x.html``) would run script there when its signed link is opened. Both write
paths therefore accept only a decodable PNG/JPEG/WEBP/GIF, and store a
re-encode under a generated name whose extension matches the detected format.
"""

from __future__ import annotations

import os
from io import BytesIO

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status

from apps.commissioning.errors import PictureInvalid
from apps.commissioning.models import DeliveryStation
from apps.commissioning.models.choices import ShareTypeVariationSizeOptions
from apps.commissioning.tests.factories import (
    DeliveryStationFactory,
    ShareTypeFactory,
    ShareTypeVariationFactory,
)
from apps.shared import image_upload

HTML_PAYLOAD = b"<!doctype html><html><body><script>alert(1)</script></body></html>"
SVG_PAYLOAD = (
    b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
    b'<rect width="10" height="10"/></svg>'
)
INVALID_CODE = "commissioning.picture_invalid"


def _image_bytes(image_format: str, size: tuple[int, int] = (8, 6)) -> bytes:
    buffer = BytesIO()
    mode = {"JPEG": "RGB", "GIF": "P"}.get(image_format, "RGBA")
    Image.new(mode, size, "green").save(buffer, format=image_format)
    return buffer.getvalue()


def _upload(name: str, payload: bytes, content_type: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, payload, content_type=content_type)


@pytest.fixture(autouse=True)
def _isolated_media_root(settings, tmp_path):
    """Keep uploaded test files out of the repo's media directory."""
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture(params=["share_type_variation", "delivery_station"])
def picture_target(request, tenant):
    """``(instance, detail_url, upload_dir)`` for each model with a picture."""
    if request.param == "share_type_variation":
        instance = ShareTypeVariationFactory()
        upload_dir = "pictures_share_type_variation/"
    else:
        instance = DeliveryStationFactory()
        upload_dir = "pictures_delivery_station/"
    url = reverse(f"{request.param}-detail", kwargs={"pk": instance.pk})
    return instance, url, upload_dir


@pytest.mark.django_db
class TestPictureUploadViaUpdate:
    @pytest.mark.parametrize(
        "name, payload, content_type",
        [
            ("evil.html", HTML_PAYLOAD, "text/html"),
            ("evil.svg", SVG_PAYLOAD, "image/svg+xml"),
            # A lying extension/content type does not make markup an image.
            ("evil.png", HTML_PAYLOAD, "image/png"),
        ],
    )
    def test_rejects_non_image(
        self, api_client, picture_target, name, payload, content_type
    ):
        instance, url, _ = picture_target

        resp = api_client.patch(
            url, {"picture": _upload(name, payload, content_type)}, format="multipart"
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == INVALID_CODE
        instance.refresh_from_db()
        assert not instance.picture

    @pytest.mark.parametrize(
        "image_format, extension",
        [("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp"), ("GIF", ".gif")],
    )
    def test_accepts_raster_image_stored_with_matching_extension(
        self, api_client, picture_target, image_format, extension
    ):
        instance, url, upload_dir = picture_target
        upload = _upload(
            f"photo{extension}",
            _image_bytes(image_format),
            f"image/{image_format.lower()}",
        )

        resp = api_client.patch(url, {"picture": upload}, format="multipart")

        assert resp.status_code == status.HTTP_200_OK, resp.content
        instance.refresh_from_db()
        assert instance.picture.name.startswith(upload_dir)
        assert instance.picture.name.endswith(extension)
        with instance.picture.open("rb") as stored:
            assert Image.open(stored).format == image_format

    def test_png_uploaded_as_html_is_stored_as_png(self, api_client, picture_target):
        instance, url, _ = picture_target

        resp = api_client.patch(
            url,
            {"picture": _upload("x.html", _image_bytes("PNG"), "text/html")},
            format="multipart",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.content
        instance.refresh_from_db()
        _, extension = os.path.splitext(instance.picture.name)
        assert extension == ".png"
        assert "html" not in instance.picture.name
        with instance.picture.open("rb") as stored:
            assert Image.open(stored).format == "PNG"

    def test_multi_picture_jpeg_is_stored_as_jpg(self, api_client, picture_target):
        # Phones/cameras write JPEGs with several images in the MP header; Pillow
        # reports those as "MPO". They are ordinary .jpg photos and must upload.
        instance, url, upload_dir = picture_target
        buffer = BytesIO()
        Image.new("RGB", (8, 6), "red").save(
            buffer,
            format="MPO",
            save_all=True,
            append_images=[Image.new("RGB", (8, 6), "blue")],
        )
        buffer.seek(0)
        assert Image.open(buffer).format == "MPO"

        resp = api_client.patch(
            url,
            {"picture": _upload("phone.jpg", buffer.getvalue(), "image/jpeg")},
            format="multipart",
        )

        assert resp.status_code == status.HTTP_200_OK, resp.content
        instance.refresh_from_db()
        assert instance.picture.name.startswith(upload_dir)
        assert instance.picture.name.endswith(".jpg")
        with instance.picture.open("rb") as stored:
            stored_image = Image.open(stored)
            assert stored_image.format == "JPEG"
            assert stored_image.size == (8, 6)

    def test_rejects_upload_over_byte_cap(
        self, api_client, picture_target, monkeypatch
    ):
        # Lower the cap instead of shipping a 20 MB fixture through multipart.
        monkeypatch.setattr(image_upload, "PICTURE_MAX_BYTES", 64)
        instance, url, _ = picture_target
        payload = _image_bytes("PNG", size=(64, 64))
        assert len(payload) > 64

        resp = api_client.patch(
            url,
            {"picture": _upload("big.png", payload, "image/png")},
            format="multipart",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        body = resp.json()
        assert body["code"] == INVALID_CODE
        assert "MB limit" in body["message"]
        instance.refresh_from_db()
        assert not instance.picture

    def test_rejects_image_over_pixel_cap(self, api_client, picture_target):
        # A real decompression bomb: 42 MP of one colour is a few KB on the
        # wire, far under the byte cap, but must be refused from the header.
        instance, url, _ = picture_target
        buffer = BytesIO()
        Image.new("1", (7000, 6000)).save(buffer, format="PNG")
        assert buffer.tell() < image_upload.PICTURE_MAX_BYTES

        resp = api_client.patch(
            url,
            {"picture": _upload("bomb.png", buffer.getvalue(), "image/png")},
            format="multipart",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        body = resp.json()
        assert body["code"] == INVALID_CODE
        assert "megapixels" in body["message"]
        instance.refresh_from_db()
        assert not instance.picture

    def test_null_patch_still_clears_existing_picture(self, api_client, picture_target):
        # The frontend's delete button sends a JSON ``{"picture": null}`` PATCH.
        instance, url, _ = picture_target
        instance.picture.save("old.png", ContentFile(_image_bytes("PNG")), save=True)

        resp = api_client.patch(url, {"picture": None}, format="json")

        assert resp.status_code == status.HTTP_200_OK, resp.content
        instance.refresh_from_db()
        assert not instance.picture


@pytest.mark.django_db
class TestPictureUploadViaCreate:
    def test_delivery_station_create_rejects_html(self, api_client, tenant):
        resp = api_client.post(
            reverse("delivery_station-list"),
            {
                "short_name": "Evil station",
                "picture": _upload("evil.html", HTML_PAYLOAD, "text/html"),
            },
            format="multipart",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == INVALID_CODE

    def test_delivery_station_create_stores_png_under_png_name(
        self, api_client, tenant
    ):
        resp = api_client.post(
            reverse("delivery_station-list"),
            {
                "short_name": "Photo station",
                "picture": _upload("x.html", _image_bytes("PNG"), "text/html"),
            },
            format="multipart",
        )

        assert resp.status_code == status.HTTP_201_CREATED, resp.content
        station = DeliveryStation.objects.get(pk=resp.json()["id"])
        assert station.picture.name.startswith("pictures_delivery_station/")
        assert station.picture.name.endswith(".png")

    def test_share_type_variation_create_rejects_svg(self, api_client, tenant):
        share_type = ShareTypeFactory()

        resp = api_client.post(
            reverse("share_type_variation-list"),
            {
                "share_type": share_type.pk,
                "size": ShareTypeVariationSizeOptions.values[0],
                "valid_from": share_type.valid_from.isoformat(),
                "picture": _upload("evil.svg", SVG_PAYLOAD, "image/svg+xml"),
            },
            format="multipart",
        )

        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["code"] == INVALID_CODE


class TestNormalizeUploadedPicture:
    """The shared helper in isolation — no DB, no storage."""

    @pytest.mark.parametrize("empty", [None, ""])
    def test_empty_values_pass_through(self, empty):
        assert (
            image_upload.normalize_uploaded_picture(empty, error_cls=PictureInvalid)
            == empty
        )

    def test_truncated_image_is_rejected(self):
        payload = _image_bytes("PNG", size=(64, 64))
        truncated = ContentFile(payload[: len(payload) // 2], name="cut.png")

        with pytest.raises(PictureInvalid):
            image_upload.normalize_uploaded_picture(truncated, error_cls=PictureInvalid)

    def test_generated_name_ignores_client_name(self):
        upload = ContentFile(_image_bytes("JPEG"), name="../../evil.html")

        result = image_upload.normalize_uploaded_picture(
            upload, error_cls=PictureInvalid
        )

        assert result.name.endswith(".jpg")
        assert "/" not in result.name
        assert "evil" not in result.name

    @staticmethod
    def _normalized_image(payload: bytes, name: str) -> Image.Image:
        result = image_upload.normalize_uploaded_picture(
            ContentFile(payload, name=name), error_cls=PictureInvalid
        )
        return Image.open(BytesIO(result.read()))

    def test_converted_cmyk_jpeg_drops_its_icc_profile(self):
        # A CMYK profile on the RGB re-encode would mis-describe the pixels.
        buffer = BytesIO()
        Image.new("CMYK", (8, 6), (0, 50, 100, 0)).save(
            buffer, format="JPEG", icc_profile=b"cmyk-profile"
        )

        stored = self._normalized_image(buffer.getvalue(), "print.jpg")

        assert stored.format == "JPEG"
        assert stored.mode == "RGB"
        assert "icc_profile" not in stored.info

    def test_unconverted_image_keeps_its_icc_profile(self):
        buffer = BytesIO()
        Image.new("RGB", (8, 6), "red").save(
            buffer, format="JPEG", icc_profile=b"rgb-profile"
        )

        stored = self._normalized_image(buffer.getvalue(), "photo.jpg")

        assert stored.info.get("icc_profile") == b"rgb-profile"

    def test_exif_orientation_is_applied_and_exif_dropped(self):
        exif = Image.Exif()
        exif[0x0112] = 6  # Orientation: rotate 90 degrees clockwise to display.
        buffer = BytesIO()
        Image.new("RGB", (8, 6), "red").save(buffer, format="JPEG", exif=exif.tobytes())

        stored = self._normalized_image(buffer.getvalue(), "phone.jpg")

        assert stored.size == (6, 8)
        assert stored.getexif().get(0x0112) is None

    @pytest.mark.parametrize("image_format", ["PNG", "GIF"])
    def test_paletted_transparency_is_kept(self, image_format):
        paletted = Image.new("P", (8, 6), 0)
        paletted.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
        buffer = BytesIO()
        paletted.save(buffer, format=image_format, transparency=0)

        stored = self._normalized_image(
            buffer.getvalue(), f"icon.{image_format.lower()}"
        )

        assert stored.format == image_format
        assert stored.mode == "P"
        assert stored.info.get("transparency") == 0

    def test_16_bit_png_keeps_its_bit_depth(self):
        buffer = BytesIO()
        Image.new("I;16", (8, 6), 40000).save(buffer, format="PNG")

        stored = self._normalized_image(buffer.getvalue(), "scan.png")

        assert stored.format == "PNG"
        assert stored.mode == "I;16"
