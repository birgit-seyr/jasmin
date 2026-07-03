from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import RequiresStepUp
from core.serializers import ErrorResponseSerializer

from ..errors import BackupFailed, BackupScriptMissing, BackupTimedOut
from ..permissions import IsSuperAdmin
from ..serializers import BackupFileSerializer
from .authentication import SuperAdminJWTAuthentication

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))
# The dump script is installed at this path in the dedicated ``backup``
# container (see backups/Dockerfile). NOTE: this endpoint runs inside the
# ``backend`` container, which does NOT ship the script — so unless the script
# (and pg_dump/gpg) are mounted in, the ``.exists()`` guard below fails cleanly
# with ``BackupScriptMissing`` rather than silently doing nothing. Scheduled
# backups do not depend on this endpoint; the ``backup`` container's cron is
# the real writer. Override the path via ``BACKUP_SCRIPT`` if you mount it.
BACKUP_SCRIPT = Path(os.environ.get("BACKUP_SCRIPT", "/usr/local/bin/backup.sh"))


@extend_schema(
    tags=["super-admin"],
    summary="List database backups",
    responses={
        200: inline_serializer(
            name="BackupListResponse",
            fields={
                "backups": BackupFileSerializer(many=True),
            },
        ),
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
    },
)
@api_view(["GET"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin])
def super_admin_list_backups_view(request: Request) -> Response:
    """List all available database backups."""
    backups = []

    if BACKUP_DIR.exists():
        for f in sorted(BACKUP_DIR.glob("*.sql.gz.gpg"), reverse=True):
            stat = f.stat()
            backups.append(
                {
                    "filename": f.name,
                    "size_bytes": stat.st_size,
                    "size_human": _human_size(stat.st_size),
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                }
            )

    return Response({"backups": backups})


@extend_schema(
    tags=["super-admin"],
    summary="Trigger a database backup now",
    responses={
        200: inline_serializer(
            name="BackupTriggerResponse",
            fields={
                "message": drf_serializers.CharField(),
                "filename": drf_serializers.CharField(),
            },
        ),
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
        500: ErrorResponseSerializer,
        504: ErrorResponseSerializer,
    },
)
@api_view(["POST"])
@authentication_classes([SuperAdminJWTAuthentication])
@permission_classes([IsSuperAdmin, RequiresStepUp])
def super_admin_trigger_backup_view(request: Request) -> Response:
    """Trigger an immediate database backup.

    Gated by step-up auth because a fresh backup file on disk is a
    full DB dump — a stolen session shouldn't be able to materialise
    one without a fresh password re-confirmation.
    """
    if not BACKUP_SCRIPT.exists():
        raise BackupScriptMissing(
            "Backup script not found. Is the backup container configured?"
        )

    try:
        result = subprocess.run(
            [str(BACKUP_SCRIPT), "now"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            raise BackupFailed(f"Backup failed: {result.stderr}")

        # Find the newest backup file
        newest = max(BACKUP_DIR.glob("*.sql.gz.gpg"), key=lambda f: f.stat().st_mtime)

        return Response(
            {
                "message": "Backup created successfully",
                "filename": newest.name,
            }
        )
    except subprocess.TimeoutExpired:
        raise BackupTimedOut("Backup timed out") from None


def _human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
