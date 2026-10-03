"""Single-owner onboarding and JSON-friendly session authentication."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Concatenate, NoReturn, ParamSpec

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.http import HttpRequest, JsonResponse
from django.http.response import HttpResponseBase
from django.middleware.csrf import get_token

from relay.errors import ConfigError, PermissionFlowError, PersistenceError

from .models import Installation

P = ParamSpec("P")


def _reject_existing_owner() -> NoReturn:
    message = "Relay owner onboarding has already completed."
    raise PermissionFlowError(message)


def _request_user(request: HttpRequest) -> User | AnonymousUser:
    value = getattr(request, "user", None)
    return value if isinstance(value, (User, AnonymousUser)) else AnonymousUser()


def auth_state(request: HttpRequest) -> dict[str, object]:
    """Return onboarding/session state and ensure the CSRF cookie is available."""
    get_token(request)
    try:
        installation = Installation.objects.filter(pk=1).first()
        owner_created = bool(installation and installation.owner_created)
    except DatabaseError:
        message = "Relay could not read installation authentication state."
        raise PersistenceError(message) from None
    user = _request_user(request)
    authenticated = bool(user.is_authenticated)
    return {
        "owner_created": owner_created,
        "authenticated": authenticated,
        "username": user.get_username() if authenticated else None,
    }


def create_owner(request: HttpRequest, username: str, password: str) -> User:
    """Create the installation's only owner and authenticate its first session."""
    normalized = username.strip()
    if not normalized or len(normalized) > 150:
        message = "Username must contain 1 through 150 characters."
        raise ConfigError(message)
    candidate = User(username=normalized, is_staff=True, is_superuser=True)
    try:
        validate_password(password, user=candidate)
    except ValidationError:
        message = "The password does not satisfy Relay's local password policy."
        raise ConfigError(message, next_action="Choose a stronger password.") from None
    try:
        with transaction.atomic():
            installation, _created = Installation.objects.select_for_update().get_or_create(pk=1)
            if installation.owner_created or User.objects.exists():
                _reject_existing_owner()
            candidate.set_password(password)
            candidate.save(force_insert=True)
            installation.owner_created = True
            installation.save(update_fields=("owner_created", "updated_at"))
    except PermissionFlowError:
        raise
    except (DatabaseError, IntegrityError):
        message = "Relay could not create the local owner account."
        raise PersistenceError(message) from None
    else:
        login(request, candidate)
        return candidate


def login_owner(request: HttpRequest, username: str, password: str) -> User | None:
    """Authenticate only the single local superuser created by onboarding."""
    user = authenticate(request, username=username, password=password)
    if not isinstance(user, User) or not user.is_superuser:
        return None
    login(request, user)
    return user


def logout_owner(request: HttpRequest) -> None:
    """End the current browser session without changing owner credentials."""
    logout(request)


def owner_required(
    view: Callable[Concatenate[HttpRequest, P], HttpResponseBase],
) -> Callable[Concatenate[HttpRequest, P], HttpResponseBase]:
    """Return the stable JSON envelope instead of redirecting unauthenticated APIs."""

    @wraps(view)
    def wrapped(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> HttpResponseBase:
        if not _request_user(request).is_authenticated:
            return JsonResponse(
                {
                    "code": "authentication_required",
                    "message": "Sign in to the local Relay owner account.",
                    "context": {},
                },
                status=401,
            )
        return view(request, *args, **kwargs)

    return wrapped


def owner_username(request: HttpRequest) -> str:
    """Return the authenticated local owner's stable session name."""
    return _request_user(request).get_username()


__all__ = [
    "auth_state",
    "create_owner",
    "login_owner",
    "logout_owner",
    "owner_required",
    "owner_username",
]
