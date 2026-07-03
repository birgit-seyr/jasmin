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
"""

from __future__ import annotations

import posixpath
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


def sign_media_path(path: str) -> str:
    """Token for ``path`` — the unquoted URL path below ``MEDIA_URL``
    (i.e. ``<schema>/<storage name>``)."""
    return signing.dumps(path, salt=_SALT, compress=True)


def media_token_is_valid(path: str, token: str) -> bool:
    try:
        return signing.loads(token, salt=_SALT, max_age=_signature_max_age()) == path
    except signing.BadSignature:
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
