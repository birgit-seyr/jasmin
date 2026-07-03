#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    # Local CLI convenience: settings.py defaults DEBUG to False (fail-safe for
    # prod), so default it on here for a bare ``manage.py runserver`` / ``shell``
    # run without exported env. The prod container always sets DEBUG explicitly
    # (compose), so this never fires there; the serving path (gunicorn via
    # config.wsgi) is unaffected.
    os.environ.setdefault('DEBUG', 'True')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
