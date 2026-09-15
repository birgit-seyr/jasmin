"""Validate and re-encode a user-uploaded raster picture before it is stored.

Media is served from the tenant origin with a Content-Type that nginx derives
from the stored FILE EXTENSION (and ``nosniff``, no attachment disposition).
Storing an upload under its client-chosen name therefore lets the uploader pick
the served type: an ``.html`` or ``.svg`` "picture" — or a real PNG renamed to
``x.html`` — would run script on the tenant origin when its signed link is
opened. So a picture is only accepted when Pillow decodes it as one of a small
set of browser-renderable raster formats, and what gets stored is a fresh
re-encode in that detected format under a generated name whose extension
matches it. The client's file name and bytes never reach storage.

The error class is injected by the caller so each app keeps raising its own
``JasminError`` (with its own stable code) from its own ``errors.py``.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from typing import Any

from django.core.files.base import ContentFile
from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

from core.errors import JasminError

# Cap on the uploaded bytes. Generous enough for a full-resolution phone photo.
PICTURE_MAX_BYTES = 20 * 1024 * 1024
# Cap on decoded pixels, checked from the header BEFORE any decode. The byte cap
# does not bound this: a flat-colour PNG compresses by orders of magnitude, so a
# few KB can declare a canvas that decodes to gigabytes in a worker shared by
# every tenant. 40 MP (~120 MB decoded as RGB) covers ordinary camera photos.
PICTURE_MAX_PIXELS = 40_000_000
# Pillow format name -> extension the re-encoded file is stored under. Only
# formats a browser renders natively. Never SVG (active content; Pillow cannot
# decode it anyway). Restricting ``Image.open`` to these also keeps Pillow's
# riskier plugins (EPS via Ghostscript, etc.) from ever being tried.
PICTURE_FORMAT_EXTENSIONS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif"}

# Everything Pillow raises for a file that is not (or not entirely) a decodable
# image: unknown format, truncated data, bad chunk checksums (``SyntaxError``),
# broken EXIF, or a canvas past Pillow's own bomb threshold.
_DECODE_ERRORS = (
    UnidentifiedImageError,
    OSError,
    ValueError,
    SyntaxError,
    EOFError,
    Image.DecompressionBombError,
)


# Pillow's LOAD_TRUNCATED_IMAGES switch is process-wide, and importing WeasyPrint
# turns it on so its renders tolerate truncated images. With it on, Pillow fills
# corrupt pixel data instead of raising, which upload validation must not accept.
# Upload decoding and consent-PDF rendering both hold this lock, so a gunicorn
# gthread worker never flips the switch while a render runs in its other thread.
PILLOW_TRUNCATED_IMAGES_LOCK = threading.Lock()


@contextmanager
def strict_image_decoding() -> Iterator[None]:
    """Decode with Pillow's truncated-image tolerance off, then restore it."""
    with PILLOW_TRUNCATED_IMAGES_LOCK:
        previous = ImageFile.LOAD_TRUNCATED_IMAGES
        ImageFile.LOAD_TRUNCATED_IMAGES = False
        try:
            yield
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = previous


def normalize_uploaded_picture(
    value: Any,
    *,
    error_cls: type[JasminError],
    field: str = "picture",
) -> Any:
    """Return a re-encoded ``ContentFile`` for a valid picture upload.

    ``None`` / ``""`` (the clear-the-field paths — a JSON ``null`` PATCH or an
    empty multipart value) pass through untouched. Anything else must be a PNG,
    JPEG, WEBP or GIF within the byte and pixel caps, or ``error_cls`` is raised.

    Only the first frame of an animated GIF/WEBP is kept. EXIF orientation is
    applied to the pixels before re-encoding, because the re-encode drops the
    EXIF block (which also strips e.g. GPS metadata from phone photos).
    """
    if not value:
        return value

    formats = list(PICTURE_FORMAT_EXTENSIONS)
    allowed = "PNG, JPEG, WEBP or GIF"

    if value.size > PICTURE_MAX_BYTES:
        raise error_cls(
            f"The picture exceeds the {PICTURE_MAX_BYTES // (1024 * 1024)} MB limit.",
            field=field,
        )

    try:
        # ``verify()`` is the cheap structural check but leaves the image object
        # unusable, so the real work below needs a second ``open()``.
        value.seek(0)
        probe = Image.open(value, formats=formats)
        image_format = (probe.format or "").upper()
        probe.verify()
    except _DECODE_ERRORS:
        raise error_cls(
            f"The picture must be a {allowed} image.", field=field
        ) from None

    # A JPEG whose multi-picture header lists more than one image (common from
    # phones and cameras: embedded previews, gain-map secondaries) comes out of
    # Pillow's JPEG factory as "MPO". It is still a plain ``.jpg`` to the user
    # and the browser, so treat it as JPEG: reopening with ``formats=["JPEG"]``
    # reaches the same factory, and only the primary image is re-encoded.
    if image_format == "MPO":
        image_format = "JPEG"

    if image_format not in PICTURE_FORMAT_EXTENSIONS:
        raise error_cls(f"The picture must be a {allowed} image.", field=field)

    try:
        value.seek(0)
        with strict_image_decoding():
            image = Image.open(value, formats=[image_format])
            width, height = image.size
            # Header-only read so far — this MUST stay above the decode below.
            if width * height > PICTURE_MAX_PIXELS:
                raise error_cls(
                    f"The picture must be at most "
                    f"{PICTURE_MAX_PIXELS // 1_000_000} megapixels — "
                    f"this one is {width}x{height}.",
                    field=field,
                )
            icc_profile = image.info.get("icc_profile")
            rendered = ImageOps.exif_transpose(image)
            source_mode = rendered.mode
            save_kwargs: dict[str, Any] = {}
            if image_format == "JPEG":
                if rendered.mode not in ("RGB", "L"):
                    rendered = rendered.convert("RGB")
                save_kwargs["quality"] = 90
            elif image_format == "WEBP":
                if rendered.mode not in ("RGB", "RGBA"):
                    rendered = rendered.convert("RGBA")
                save_kwargs["quality"] = 90
            # A profile describes the ORIGINAL colour space (e.g. CMYK). Once the
            # pixels were converted it no longer matches them, and attaching it would
            # make viewers mis-render or ignore the colours, so drop it.
            if icc_profile and image_format != "GIF" and rendered.mode == source_mode:
                save_kwargs["icc_profile"] = icc_profile
            buffer = BytesIO()
            rendered.save(buffer, format=image_format, **save_kwargs)
    except _DECODE_ERRORS:
        raise error_cls(
            f"The picture must be a {allowed} image.", field=field
        ) from None
    finally:
        # The upload handler may still read the original after a failure.
        value.seek(0)

    extension = PICTURE_FORMAT_EXTENSIONS[image_format]
    return ContentFile(buffer.getvalue(), name=f"{uuid.uuid4().hex}.{extension}")
