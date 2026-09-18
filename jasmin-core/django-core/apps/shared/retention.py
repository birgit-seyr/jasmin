"""How long the platform keeps each kind of record.

The windows are independent of each other. Two that happen to be equal
today are a coincidence, not a shared policy, so changing one does not
imply changing the others — the one deliberate coupling is stated where
it applies.
"""

# GenG §31 / HGB §257 / AO §147 — ten years from the legal exit date is
# the statutory floor. We treat that floor as both the soonest a member
# CAN be anonymised and the SLA: once 10 years elapse, the platform
# erases unless an explicit retention block still applies (open
# CoopShare, open invoice, etc. — those are picked up by
# ``GDPRService.check_retention_blocks``).
EX_MEMBER_RETENTION_YEARS = 10

# Abandoned share-import batches, i.e. the FAILED / PREVIEW_READY rows an
# upload-and-preview cycle leaves behind. APPLIED rows are never swept:
# they are the audit trail of which membership changes actually happened.
IMPORT_BATCH_RETENTION_DAYS = 90

# ``EmailLog`` and terminal ``BackgroundJob`` rows share one window on
# purpose. A bulk send leaves a BackgroundJob whose ``result`` JSON holds
# the same per-recipient names and outcomes as the EmailLog rows it sent,
# so letting the jobs outlive the log would keep that data past its
# window. 90 days is long enough to answer "did this member get the
# invoice?", short enough not to bloat either per-tenant table.
NOTIFICATION_LOG_RETENTION_DAYS = 90
