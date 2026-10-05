"""ASGI entry point served by Uvicorn."""

from __future__ import annotations

import os

from django.core.asgi import ASGIHandler, get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "relay.web.settings")

application: ASGIHandler = get_asgi_application()
