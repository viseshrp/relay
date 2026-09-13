"""Relay URL configuration, populated by the HTTP implementation step."""

from django.urls import URLPattern, URLResolver

urlpatterns: list[URLPattern | URLResolver] = []
