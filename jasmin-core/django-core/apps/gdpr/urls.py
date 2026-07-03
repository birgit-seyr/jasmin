from django.urls import path

from . import views

urlpatterns = [
    path("my-data/", views.gdpr_my_data_view, name="gdpr-my-data"),
    path(
        "my-deletion-status/",
        views.gdpr_my_deletion_status_view,
        name="gdpr-my-deletion-status",
    ),
    # Two-step deletion flow. The request endpoint creates a PENDING
    # request + sends the confirmation email; the confirm endpoint is
    # the link the user clicks; the admin endpoints gate the deletion
    # when the tenant / persona requires office approval.
    path(
        "request-deletion/",
        views.gdpr_request_deletion_view,
        name="gdpr-request-deletion",
    ),
    path(
        "confirm-deletion/<str:token>/",
        views.gdpr_confirm_deletion_view,
        name="gdpr-confirm-deletion",
    ),
    path(
        "admin/pending-deletions/",
        views.gdpr_admin_pending_deletions_view,
        name="gdpr-admin-pending-deletions",
    ),
    path(
        "admin/decided-deletions/",
        views.gdpr_admin_decided_deletions_view,
        name="gdpr-admin-decided-deletions",
    ),
    path(
        "admin/approve-deletion/<str:request_id>/",
        views.gdpr_admin_approve_deletion_view,
        name="gdpr-admin-approve-deletion",
    ),
    path(
        "admin/reject-deletion/<str:request_id>/",
        views.gdpr_admin_reject_deletion_view,
        name="gdpr-admin-reject-deletion",
    ),
    path("deletion-log/", views.gdpr_deletion_log_view, name="gdpr-deletion-log"),
    # Art. 30 Record of Processing Activities (VVT) — structured
    # export. See ``apps/gdpr/vvt.py`` for the code-level facts
    # that back it.
    path(
        "processing-activities/",
        views.gdpr_processing_activities_view,
        name="gdpr-processing-activities",
    ),
]
