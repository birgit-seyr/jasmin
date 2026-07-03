================================================================================
JASMIN WAITING-LIST PLANNING DOC
================================================================================
Last updated: 2026-06-05
Status:       Audit done, no code shipped yet. Phase A is small + safe; Phases
              B and C require product decisions before any line of code.

This file is the planning sibling to docs/code/email-overview.md. It
captures what's already on disk for the waiting-list feature, what's dead
code, the open product questions, and a phased plan so we can resume
without reauditing.

--------------------------------------------------------------------------------
0. TL;DR
--------------------------------------------------------------------------------
- The data model is ~60% built and untouched since the initial migration.
- ``WaitingListMixin`` on Member + Subscription, six-state enum, helper
  methods (``add_to_waiting_list`` / ``notify_spot_available`` /
  ``confirm_spot`` / ``decline_spot`` / ``mark_as_expired``) all exist.
- ZERO of those methods have non-test callers. ``notify_spot_available``
  is the load-bearing "P1-6" entry in the email overview.
- ``WaitingListAbos.tsx`` is a real, working filtered table.
- ``WaitingListMembers.tsx`` is a stub ("coming soon").
- No automation today: when a Member exits or a Subscription is cancelled,
  nothing notices and offers the seat to the queue head. Manual office.

--------------------------------------------------------------------------------
1. What exists on disk
--------------------------------------------------------------------------------

Backend (apps/commissioning/):

  models/mixin.py — WaitingListMixin
    Fields:
      on_waiting_list           BooleanField, default False
                                — denormalised flag, fast filter
      waiting_list_status       CharField w/ choices (see enum below)
      waiting_list_position     PositiveIntegerField, null/blank,
                                editable=False — defined but never written
      notification_sent_at      DateTimeField, null/blank
      notification_expires_at   DateTimeField, null/blank (default 7d from
                                notification_sent_at when set by
                                ``notify_spot_available``)
      response_received_at      DateTimeField, null/blank — when the
                                applicant confirmed or declined

    Status enum (WaitingListStatus):
      NOT_ON_LIST       default; not queued
      PENDING           on the list, waiting for a spot to open
      SPOT_AVAILABLE    office offered a spot; awaiting their answer
      CONFIRMED         accepted; on_waiting_list flipped to False
      DECLINED          refused; on_waiting_list flipped to False
      EXPIRED           didn't respond before notification_expires_at;
                        on_waiting_list flipped to False

    Methods (all wired, none called from prod code):
      add_to_waiting_list()
        Sets status -> PENDING, on_waiting_list -> True. Idempotent.
      notify_spot_available(expiry_days=7)
        Sets status -> SPOT_AVAILABLE, stamps notification_sent_at +
        notification_expires_at. THIS is the P1-6 / P2-9 entry that
        stamps the timestamp WITHOUT sending an email — no template
        wired yet.
      confirm_spot()
        Sets status -> CONFIRMED, on_waiting_list -> False, stamps
        response_received_at.
      decline_spot()
        Sets status -> DECLINED, on_waiting_list -> False, stamps
        response_received_at.
      mark_as_expired()
        Sets status -> EXPIRED, on_waiting_list -> False.

      Property is_awaiting_confirmation: status == SPOT_AVAILABLE
      Property has_expired_notification: now() > notification_expires_at
                                         AND status == SPOT_AVAILABLE

  Member and Subscription both inherit WaitingListMixin
  (commissioning/models/members.py).

Viewsets/views (apps/commissioning/viewsets/):

  SubscriptionViewSet filters by ``?on_waiting_list=true``. That's the
  ONLY production code path that reads any waiting-list field
  (members_viewsets.py around line 297 + 340).

  No add_to_waiting_list / notify_spot_available actions exposed.
  No reject-flow integration.

Frontend (jasmin-core/react-core/src/):

  pages/abos/WaitingListAbos.tsx
    Functional. Editable table of Subscriptions with
    ``on_waiting_list=True``, columns for member / share-type-
    variation / quantity / delivery-station. Reuses
    AdminConfirmationModalAbos — confirm/reject only, no
    waiting-list-specific actions.

  pages/members/WaitingListMembers.tsx
    Stub. "Coming soon".

  api/generated/models/waitingListStatusEnum.ts
    Generated from OpenAPI. Full type support already exists frontend-
    side — no orval regen needed for Phase A.

i18n:
  members.waiting_list = "Warteliste"
  abos.waiting_list   = "Warteliste"
  explainers.waiting_list — empty string

--------------------------------------------------------------------------------
2. What's dead code (call sites confirmed by grep, non-test)
--------------------------------------------------------------------------------

  notify_spot_available()    no callers
  add_to_waiting_list()      no callers
  confirm_spot()             no callers
  decline_spot()             no callers
  mark_as_expired()          no callers
  waiting_list_position      never written

Also missing:
  - No "Put on waiting list" button in either AdminConfirmationModal.
  - No automation hook from ``cancel_member_with_coop_shares`` or
    ``SubscriptionService.cancel_subscription`` to spot-detection.
  - No ``commissioning.waiting_list_*`` email templates (the slug
    ``members.waiting_list_spot_available`` is reserved in the email
    overview as P2-9 but not registered).

--------------------------------------------------------------------------------
3. Open product questions (DECIDE BEFORE Phase B)
--------------------------------------------------------------------------------

These three are blockers for any automation work. None of them have a
definitive answer in the existing code. Phase A doesn't need them — Phase
B / C do.

  Q1. What IS a "spot"?
      - A subscription slot per share-type-variation
        (e.g. "the veggie-box waiting list is full but fruit is open")?
      - A total membership count enforced at the coop level?
      - A delivery-station capacity (Tuesday box is full, Thursday is
        open)?
      Today there is NO capacity model anywhere. Without one,
      ``notify_spot_available`` has no trigger to react to.

  Q2. Who picks the next person?
      - FIFO on ``created_at`` is simplest.
      - The ``waiting_list_position`` field exists (PositiveInteger,
        editable=False) but is never written — pick a writer if we
        want explicit positions.
      - Manual office assignment is the safest first version.

  Q3. What does the applicant receive?
      - Should "you were put on the waiting list" send an email
        immediately, or is the office happy telling them out-of-band?
      - Should ``notify_spot_available`` send a "your spot is ready"
        email automatically, with a confirm/decline link, or only
        stamp the status and let the office follow up by phone?
      - If we want emails, two new slugs:
          commissioning.waiting_list_added
          commissioning.waiting_list_spot_available
        Templates would carry expiry deadline, accept link, decline
        link.

--------------------------------------------------------------------------------
4. Phased plan
--------------------------------------------------------------------------------

============================ PHASE A — manual flow ============================
Ship without answering any of Q1-Q3. Office user explicitly clicks "put on
waiting list" inside the existing AdminConfirmationModal — that's the only
trigger. No email, no automation, no detection. 1-2 hours of work.

Backend:
  MembersViewSet
    + ``@action(detail=True, methods=["post"]) def add_to_waiting_list``
      Calls ``member.add_to_waiting_list()``. Returns the refreshed
      MemberSerializer payload.

  SubscriptionViewSet
    + Same, calling ``subscription.add_to_waiting_list()``.

  Serializer lockdown:
    Add ``on_waiting_list`` + ``waiting_list_status`` +
    ``waiting_list_position`` + ``notification_sent_at`` +
    ``notification_expires_at`` + ``response_received_at`` to the
    ``read_only_fields`` tuples on MemberSerializer +
    SubscriptionSerializer. They're set by the action endpoints; PATCH
    must not bypass.

Frontend:
  hooks/modals/useWaitingListModalMembers.ts
    Mirrors useRejectMemberModal — open / close / loading / submit.
    Submit POSTs ``/api/commissioning/members/{id}/add_to_waiting_list/``.

  hooks/modals/useWaitingListModalAbos.ts
    Same shape against ``/api/commissioning/abos/{id}/add_to_waiting_list/``.

  components/modals/AdminConfirmationModalMembers.tsx
  components/modals/AdminConfirmationModalAbos.tsx
    Third footer button: "Auf Warteliste setzen" / "Put on waiting list".
    Sits between Cancel and Reject. Shown only when the row is pending
    (not confirmed, not rejected, not already on the list).

  components/ui/ButtonLibrary.tsx
    + ``adminWaiting`` StatusButton variant (ClockCircleOutlined on a
    warning background, e.g. #fff7e6 / #d48806).

  hooks/modals/useModalAdminConfirmationMembers.ts
  hooks/modals/useModalAdminConfirmationAbos.ts
    Extend ``getAdminStatus`` to return ``adminWaiting`` when
    ``record.on_waiting_list === true`` and the row is not already
    confirmed or rejected. Priority sits between rejected and pending
    so the table sort surfaces unanswered queue entries near the top.

  pages/members/WaitingListMembers.tsx
    Replace the stub by cloning WaitingListAbos.tsx — filtered Member
    list (``?on_waiting_list=true``), editable table, same modal
    wiring.

i18n (members.json + common.json):
  members.put_on_waiting_list      "Auf Warteliste setzen"
  members.waiting_list_status      "Warteliste-Status"
  members.put_on_waiting_list_success / _error notifications

Tests:
  + ``MembersViewSet.add_to_waiting_list`` happy path + idempotency.
  + Frontend modal renders the new button only for pending rows.

============================== PHASE B — detection =============================
DEPENDS ON Q1 (define what a "spot" is). Estimated 1-2 days once Q1 is
answered.

If Q1 = "subscription slot per share-type-variation":
  - Add a ``capacity`` field somewhere (likely on ShareTypeVariation —
    a soft cap per season).
  - On subscription cancellation / expiry, call a new
    ``waiting_list_service.try_promote_next(share_type_variation)``
    that loads queued members ordered by ``created_at`` (or
    ``waiting_list_position`` once we write it) and calls
    ``notify_spot_available`` on the first one whose preferred
    variation matches.

If Q1 = "total coop membership count":
  - Cleaner — a single TenantSettings.max_active_members. Any
    transition that decrements the active-member count fires the
    promotion sweep.

If Q1 = "delivery-station capacity":
  - Trickier. Capacity would live on DeliveryStation. The waiting
    list would also need a "preferred delivery_station" field on
    Member / Subscription.

Whichever shape, the integration points are:
  - ``cancel_member_with_coop_shares`` (apps/commissioning/services/
    member_cancellation.py:40) — call promote-next after the cascade.
  - ``SubscriptionService.cancel_subscription`` — same.
  - Optional periodic sweep in ``apps/commissioning/tasks.py`` to
    auto-expire SPOT_AVAILABLE rows past their ``notification_expires
    _at``.

============================ PHASE C — accept/decline ===========================
DEPENDS ON Q3 (send emails or stay manual). Estimated 1 day.

If we want emails:
  - Two new registry slugs (matching the email_overview P2-9 spec):
      commissioning.waiting_list_added
        Sent on ``add_to_waiting_list``. Confirms position / queue.
      commissioning.waiting_list_spot_available
        Sent on ``notify_spot_available``. Contains accept + decline
        links with single-use tokens (HMAC-signed like the GDPR
        deletion-confirm link).
  - New public endpoints (no auth, token in URL):
      POST /api/waiting-list/{token}/accept/  -> confirm_spot()
      POST /api/waiting-list/{token}/decline/ -> decline_spot()
  - Frontend public landing pages for those two URLs.

If we stay manual:
  - The office calls the applicant by phone, then opens the modal +
    clicks "Confirm spot" / "Decline spot" / "Mark expired" buttons.
  - Three more modal actions, no email, no token endpoints.

--------------------------------------------------------------------------------
5. Field-readiness checklist (already on disk, just needs wiring)
--------------------------------------------------------------------------------

  [x] WaitingListMixin model fields
  [x] WaitingListStatus enum
  [x] Mixin methods (add / notify / confirm / decline / expire)
  [x] Subscription on_waiting_list filter in viewset
  [x] WaitingListAbos.tsx page
  [x] waitingListStatusEnum.ts (orval generated, frontend usable)
  [x] sidebar links to both /waiting-list pages
  [ ] WaitingListMembers.tsx (currently stub)
  [ ] add_to_waiting_list DRF actions
  [ ] AdminConfirmationModal "Put on waiting list" button
  [ ] adminWaiting StatusButton variant
  [ ] notify_spot_available trigger from cancellation flows
  [ ] commissioning.waiting_list_* email registry entries
  [ ] capacity model (Q1 blocker)
  [ ] queue priority writer (Q2 — likely just FIFO via created_at)
  [ ] accept / decline token endpoints (Q3 dependent)

--------------------------------------------------------------------------------
6. Cross-references
--------------------------------------------------------------------------------

  docs/code/email-overview.md
    P1-6: notify_spot_available stamps without sending — the "UI lies"
          warning belongs here. Currently DEFERRED.
    P2-9: members.waiting_list_spot_available — reserved slug for the
          Phase C email.

  CLAUDE.md
    The apps/commissioning isolation note still holds — waiting-list
    code lives entirely inside commissioning; safe even if/when
    commissioning is extracted into its own service.
