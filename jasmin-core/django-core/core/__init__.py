"""Pure-Python infrastructure shared across apps.

`core` is intentionally NOT a Django app: it has no models, no AppConfig, and
no dependency on any `apps.*` module. Apps depend on `core`; `core` never
depends on apps. This keeps individual apps (e.g. `commissioning`) portable
— if you ever extract one, you bundle `core/` with it or vendor the small
pieces it actually uses.
"""
