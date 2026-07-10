"""Capability-URL protection for ``/media/``.

nginx no longer serves ``/media/`` directly (it used to — anyone holding
a URL could fetch tenant documents). Instead:

1. ``SignedTenantFileSystemStorage.url()`` appends a signed,
   time-limited token (``?st=...``) to every media URL the API hands
   out. One override point — no serializer changes anywhere.
2. ``protected_media_view`` validates the token and hands the actual
   file transfer back to nginx via ``X-Accel-Redirect`` (internal
   location ``/_protected_media/``). Under ``DEBUG`` it streams the
   file itself so plain ``runserver`` works.

Why capability URLs instead of session auth: media is fetched by the
browser itself (``<img src>``, ``window.open``) — those requests carry
neither the Bearer access token (memory-only) nor the refresh cookie
(path-scoped to ``/api/auth/``). The signed URL is the only credential
that survives that hop. Possession of a fresh URL grants access for
``MEDIA_URL_SIGNATURE_MAX_AGE`` (default 24 h); the frontend refetches
API payloads on every mount (global ``staleTime: 0``), so live pages
always hold fresh links.

The token is BUCKETED (``_bucket_seconds``, default 1 h) rather than
per-sign, so the emitted URL string is stable within the bucket window —
otherwise ``staleTime: 0`` re-signing rotated the ``?st=`` on every
refetch, changing the cache key and forcing a re-download of every image /
PDF on each mount. With a stable URL the browser's ``private, max-age``
cache on ``/_protected_media/`` actually applies.
"""

from __future__ import annotations

import posixpath
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from django.conf import settings
from django.core import signing
from django.db import connection
from django.http import (
    FileResponse,
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseForbidden,
    HttpResponseNotFound,
)
from django_tenants.files.storage import TenantFileSystemStorage

_SALT = "protected-media"

# nginx-internal location that aliases the media root. Must match the
# ``location /_protected_media/ { internal; alias /app/media/; }``
# blocks in nginx/nginx.conf.template.
INTERNAL_MEDIA_LOCATION = "/_protected_media/"


def _signature_max_age() -> int:
    return getattr(settings, "MEDIA_URL_SIGNATURE_MAX_AGE", 60 * 60 * 24)


def _bucket_seconds() -> int:
    """Time-bucket size for the media token (default 1 h).

    The token embeds a *bucket number* instead of an exact timestamp, so every
    ``.url()`` call within the same bucket window emits the IDENTICAL token
    string. That keeps the media URL (and thus the browser/CDN cache key)
    stable across the frontend's aggressive API refetches (``staleTime: 0`` +
    refetch-on-focus), so a repeat-viewed image / PDF is served from cache
    instead of re-downloaded on every mount. A per-call ``TimestampSigner``
    token (the old scheme) rotated on every sign and defeated that entirely."""
    return getattr(settings, "MEDIA_URL_SIGNATURE_BUCKET", 60 * 60)


def _current_bucket() -> int:
    return int(time.time()) // _bucket_seconds()


def _max_buckets() -> int:
    # How many buckets a token stays valid: the max-age window in buckets.
    return max(1, _signature_max_age() // _bucket_seconds())


def sign_media_path(path: str, *, bucket: int | None = None) -> str:
    """Deterministic capability token for ``path`` — the unquoted URL path below
    ``MEDIA_URL`` (i.e. ``<schema>/<storage name>``).

    Uses a plain (non-timestamp) ``Signer`` over ``{path, bucket}`` so the token
    is STABLE for the whole bucket window (see ``_bucket_seconds``). The bucket
    bounds the token's lifetime on the verify side. ``bucket`` is injectable for
    tests only."""
    if bucket is None:
        bucket = _current_bucket()
    return signing.Signer(salt=_SALT).sign_object(
        {"p": path, "b": bucket}, compress=True
    )


def media_token_is_valid(path: str, token: str) -> bool:
    """True iff ``token`` is a valid, unexpired capability for ``path``.

    Accepts the current bucketed scheme, and — for backward compatibility during
    a deploy — falls back to the legacy per-sign ``TimestampSigner`` scheme so
    ``?st=`` URLs already in flight in live browsers don't 403. The legacy branch
    self-obsoletes: an old token older than ``MEDIA_URL_SIGNATURE_MAX_AGE`` (24 h)
    can't validate anyway, so it is safe to delete once any deploy carrying this
    code has been live longer than that window."""
    try:
        # ``unsign_object`` auto-detects the compression prefix — do NOT pass
        # ``compress`` (that kwarg is forwarded to ``unsign`` and errors).
        data = signing.Signer(salt=_SALT).unsign_object(token)
    except (signing.BadSignature, ValueError):
        # Not a valid new-scheme token (bad/forged signature, or an old
        # TimestampSigner token whose base64 payload won't decode under the
        # plain Signer → ValueError/binascii.Error) → try the legacy scheme.
        # Fail-closed: legacy also rejects garbage/forged tokens.
        return _legacy_token_is_valid(path, token)
    return (
        isinstance(data, dict)
        and data.get("p") == path
        and isinstance(data.get("b"), int)
        # ``-1`` tolerates a token minted a hair before a bucket rollover; the
        # upper bound is the max-age window expressed in buckets.
        and -1 <= _current_bucket() - data["b"] <= _max_buckets()
    )


def _legacy_token_is_valid(path: str, token: str) -> bool:
    """Legacy per-sign ``TimestampSigner`` token check (pre-bucketing).

    TRANSITIONAL — safe to remove once every deploy has been live longer than
    ``MEDIA_URL_SIGNATURE_MAX_AGE`` (no such token can still be valid)."""
    try:
        return signing.loads(token, salt=_SALT, max_age=_signature_max_age()) == path
    except (signing.BadSignature, ValueError):
        # Fail-closed: a new-scheme token fed here (or any garbage) can raise
        # more than BadSignature (e.g. ValueError extracting a non-existent
        # timestamp) — all mean "not a valid legacy token".
        return False


class SignedTenantFileSystemStorage(TenantFileSystemStorage):
    """``TenantFileSystemStorage`` whose ``.url()`` carries the
    capability token. Wired in as the default storage backend in
    ``settings.STORAGES`` so every ``FileField.url`` the API returns —
    invoice / delivery-note PDFs, e-invoice XML, tenant logos — is
    signed without touching any serializer."""

    def url(self, name: str | None) -> str:
        unsigned = super().url(name)
        if not unsigned.startswith(settings.MEDIA_URL):
            return unsigned
        # ``super().url()`` percent-encodes the name; the view receives
        # the DECODED path from the URL resolver — sign the decoded form
        # so both sides compare the same string.
        path = unquote(urlsplit(unsigned).path[len(settings.MEDIA_URL) :])
        return f"{unsigned}?st={sign_media_path(path)}"


def protected_media_view(request: HttpRequest, path: str) -> HttpResponseBase:
    """Serve one media file iff the request carries a valid token."""
    # Reject traversal before even looking at the token. ``path`` comes
    # percent-decoded from the URL resolver. ``normpath`` leaves a
    # leading ``..`` in place, so check the components explicitly rather
    # than relying on ``normalized != path``. Null bytes / control chars
    # are rejected outright — they have no legitimate place in a media
    # name and dodge component checks (``"..\x00"`` != ``".."``).
    # (Belt-and-suspenders: the signature below is the real gate — a
    # caller can't mint a valid token for a traversal path — but failing
    # closed here keeps a malformed path from ever reaching nginx.)
    if (
        path.startswith("/")
        or "\\" in path
        or ".." in path.split("/")
        or posixpath.normpath(path) != path
        or any(ord(ch) < 0x20 or ch == "\x7f" for ch in path)
    ):
        return HttpResponseForbidden("Invalid media path.")

    token = request.GET.get("st", "")
    if not token or not media_token_is_valid(path, token):
        return HttpResponseForbidden("Invalid or expired media link.")

    # Tenant binding: the path's first segment is the schema the file
    # lives under (``MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"``). A valid
    # token for tenant B's file must not be served to a request that
    # resolved to tenant A. The signing key is global (SECRET_KEY), so
    # the token alone doesn't encode the tenant — enforce it here.
    # Tenant logos etc. are fetched on that tenant's own subdomain, so
    # this never blocks legitimate traffic.
    path_schema = path.split("/", 1)[0]
    if path_schema != connection.schema_name:
        return HttpResponseForbidden("Media path does not match this tenant.")

    if settings.DEBUG:
        file_path = Path(settings.MEDIA_ROOT) / path
        if not file_path.is_file():
            return HttpResponseNotFound("No such media file.")
        return FileResponse(file_path.open("rb"))

    response = HttpResponse()
    # Drop Django's default ``text/html`` so nginx derives the type
    # from the file extension (mime.types) at the internal location.
    del response.headers["Content-Type"]
    response.headers["X-Accel-Redirect"] = quote(INTERNAL_MEDIA_LOCATION + path)
    return response
