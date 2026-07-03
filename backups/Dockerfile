# Image for the nightly encrypted DB backup container (closes audit CFG-1).
#
# postgres:15-alpine provides the pg_dump client (matching the 15 server) plus
# busybox crond/gzip/coreutils; gnupg adds the AES256 symmetric encryption that
# backup.sh pipes through. The postgres ENTRYPOINT is overridden so this runs
# pg_dump as a CLIENT against the `postgres` service over jasmin-net — it never
# starts a database server of its own.
FROM postgres:15-alpine

# gnupg: AES256 symmetric encryption piped through backup.sh.
# rclone: optional off-host push (scaffold) — used only when RCLONE_REMOTE is
#         set; harmless to ship otherwise.
RUN apk add --no-cache gnupg rclone

COPY backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

ENTRYPOINT ["/usr/local/bin/backup.sh"]
