"""Upload image validation stays strict after WeasyPrint has turned on Pillow's
process-wide truncated-image tolerance, and consent-PDF rendering holds the lock
that keeps the two apart."""

from __future__ import annotations

import struct
import zlib
from io import BytesIO
from unittest import mock

import pytest
from django.core.files.base import ContentFile
from PIL import Image, ImageFile

from apps.commissioning.errors import PictureInvalid
from apps.commissioning.services import consent_pdf
from apps.shared import image_upload
from apps.shared.tenants.errors import TenantAppIconInvalid
from apps.shared.tenants.serializers import TenantSerializer


def _png(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), "green").save(buffer, format="PNG")
    return buffer.getvalue()


def _corrupt_pixel_data(png: bytes) -> bytes:
    """Garble the compressed IDAT data but recompute its CRC, so ``verify()``
    accepts the file and only decoding the pixels fails."""
    data = bytearray(png)
    position = 8
    while position < len(data):
        (length,) = struct.unpack(">I", data[position : position + 4])
        chunk_type = bytes(data[position + 4 : position + 8])
        data_start = position + 8
        crc_position = data_start + length
        if chunk_type == b"IDAT":
            data[data_start + 2 : crc_position] = bytes(
                byte ^ 0xFF for byte in data[data_start + 2 : crc_position]
            )
            crc = zlib.crc32(b"IDAT" + bytes(data[data_start:crc_position]))
            data[crc_position : crc_position + 4] = struct.pack(">I", crc)
            return bytes(data)
        position = crc_position + 4
    raise AssertionError("no IDAT chunk in the generated PNG")


@pytest.fixture
def truncated_loading_on(monkeypatch):
    """The state of a worker process that has already imported WeasyPrint."""
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)


class TestStrictImageDecoding:
    def test_picture_with_corrupt_pixel_data_is_rejected(self, truncated_loading_on):
        upload = ContentFile(_corrupt_pixel_data(_png(64, 64)), name="x.png")

        with pytest.raises(PictureInvalid):
            image_upload.normalize_uploaded_picture(upload, error_cls=PictureInvalid)

        assert ImageFile.LOAD_TRUNCATED_IMAGES is True

    def test_app_icon_with_corrupt_pixel_data_is_rejected(self, truncated_loading_on):
        upload = ContentFile(_corrupt_pixel_data(_png(512, 512)), name="icon.png")

        with pytest.raises(TenantAppIconInvalid):
            TenantSerializer().validate_app_icon(upload)

        assert ImageFile.LOAD_TRUNCATED_IMAGES is True

    def test_valid_picture_is_still_accepted(self, truncated_loading_on):
        upload = ContentFile(_png(16, 16), name="ok.png")

        result = image_upload.normalize_uploaded_picture(
            upload, error_cls=PictureInvalid
        )

        assert result.name.endswith(".png")

    def test_consent_pdf_render_holds_the_decoding_lock(self):
        seen = {}

        def fake_render(document):
            seen["locked"] = image_upload.PILLOW_TRUNCATED_IMAGES_LOCK.locked()
            return ContentFile(b"%PDF-")

        with mock.patch.object(
            consent_pdf, "_render_consent_pdf", side_effect=fake_render
        ):
            consent_pdf.render_consent_pdf(object())

        assert seen["locked"] is True
        assert image_upload.PILLOW_TRUNCATED_IMAGES_LOCK.locked() is False
