"""Bootstrap a SuperAdmin account from the CLI.

Django's built-in ``createsuperuser`` targets ``AUTH_USER_MODEL`` —
``accounts.JasminUser`` — which lives in tenant schemas. SuperAdmins are
a separate model in the public schema (``apps.shared.super_admin.SuperAdmin``)
and have no built-in management command, so this one provides the equivalent.

Usage::

    # Interactive (prompts for password twice, no echo)
    poetry run python manage.py createsuperadmin --email=admin@example.com

    # Scripted (do NOT use in shell history; prefer the interactive form)
    poetry run python manage.py createsuperadmin \\
        --email=admin@example.com \\
        --password='supersecret' \\
        --first-name=Bia --last-name=Seyr

    # Explicit reset: pass --update-if-exists to refresh password / names
    # on an existing account (and re-activate it) instead of erroring.
    poetry run python manage.py createsuperadmin \\
        --email=admin@example.com --update-if-exists

    # Container boot (docker_entrypoint.sh): create the first SuperAdmin only
    # while none exists; never touches an existing account.
    poetry run python manage.py createsuperadmin --bootstrap \\
        --email=admin@example.com --password='supersecret'
"""

from __future__ import annotations

import getpass
import re
import sys
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from apps.shared.super_admin.models import SuperAdmin

_MIN_PASSWORD_LENGTH = 10


class Command(BaseCommand):
    help = "Create (or update) a public-schema SuperAdmin account."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--email", default="", help="SuperAdmin email (USERNAME_FIELD)."
        )
        parser.add_argument(
            "--password",
            default=None,
            help=(
                "Plaintext password. If omitted, you'll be prompted "
                "interactively (no echo). Prefer the interactive form so "
                "the password doesn't end up in your shell history."
            ),
        )
        parser.add_argument("--first-name", default="", help="Optional display name.")
        parser.add_argument("--last-name", default="", help="Optional display name.")
        parser.add_argument(
            "--update-if-exists",
            action="store_true",
            help=(
                "If an account with this email already exists, refresh "
                "its password / first / last name instead of erroring. "
                "Useful after a dev-DB reset."
            ),
        )
        parser.add_argument(
            "--bootstrap",
            action="store_true",
            help=(
                "Create the SuperAdmin only while no SuperAdmin exists at all, "
                "and leave every existing account untouched — so a password "
                "rotated in the UI or an account deactivated during an incident "
                "survives the next container start. Missing --email/--password "
                "with no SuperAdmin yet prints a hint instead of failing."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["bootstrap"]:
            if options["update_if_exists"]:
                raise CommandError(
                    "--bootstrap never updates an existing SuperAdmin; "
                    "drop --update-if-exists."
                )
            if self._bootstrap_is_done(options):
                return

        email = options["email"].strip().lower()
        if not email:
            raise CommandError("--email is required.")
        first_name = options["first_name"]
        last_name = options["last_name"]
        update_if_exists = options["update_if_exists"]

        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError(f"Invalid email '{email}': {exc.messages[0]}") from exc

        password = options["password"] or self._prompt_password()
        self._validate_password(password)

        existing = SuperAdmin.objects.filter(email=email).first()
        if existing is None:
            super_admin = SuperAdmin.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            self.stdout.write(
                self.style.SUCCESS(f"Created SuperAdmin {super_admin.email}")
            )
            return

        if not update_if_exists:
            raise CommandError(
                f"A SuperAdmin with email '{email}' already exists. "
                f"Pass --update-if-exists to refresh password / names."
            )

        existing.set_password(password)
        existing.first_name = first_name or existing.first_name
        existing.last_name = last_name or existing.last_name
        existing.is_active = True
        existing.save()
        self.stdout.write(
            self.style.SUCCESS(f"Updated existing SuperAdmin {existing.email}")
        )

    def _bootstrap_is_done(self, options: dict[str, Any]) -> bool:
        """True when the boot-time bootstrap has nothing to create.

        The check is "any SuperAdmin at all", not "this email": an operator who
        retired the bootstrap account in favour of another must not see it come
        back on the next start.
        """
        if SuperAdmin.objects.exists():
            self.stdout.write(
                "A SuperAdmin already exists; leaving every account untouched."
            )
            return True
        if not options["email"].strip() or not options["password"]:
            self.stderr.write(
                "No SuperAdmin exists yet and DJANGO_SUPERUSER_EMAIL / "
                "DJANGO_SUPERUSER_PASSWORD are not both set, so none was "
                "created. Set both in .env and restart the backend, or run "
                "'docker compose exec backend python manage.py createsuperadmin "
                "--email <email>' (it asks for the password)."
            )
            return True
        return False

    @staticmethod
    def _prompt_password() -> str:
        if not sys.stdin.isatty():
            raise CommandError(
                "No --password given and stdin is not a TTY. "
                "Pass --password explicitly when running non-interactively."
            )
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Password (again): ")
        if first != second:
            raise CommandError("Passwords did not match.")
        return first

    @staticmethod
    def _validate_password(password: str) -> None:
        if not password:
            raise CommandError("Password is required.")
        if len(password) < _MIN_PASSWORD_LENGTH:
            raise CommandError(
                f"Password must be at least {_MIN_PASSWORD_LENGTH} characters."
            )
        if re.fullmatch(r"\d+", password):
            raise CommandError("Password cannot be entirely numeric.")
