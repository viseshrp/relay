"""Database causes remain diagnosable without changing public envelopes."""

from __future__ import annotations

import logging

from django.db import OperationalError
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory
import pytest

from relay.errors import PersistenceError, log_persistence_failure, persistence_cause
from relay.web.views import api_errors


def suppressed_failure() -> None:
    try:
        message = "private database diagnostic"
        raise OperationalError(message)  # noqa: TRY301 -- reproduce the adapter boundary
    except OperationalError:
        public_message = "Relay could not read the run."
        raise PersistenceError(public_message) from None


def test_http_logs_suppressed_database_cause_without_exposing_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @api_errors
    def failing(request: HttpRequest) -> HttpResponse:
        del request
        suppressed_failure()
        return HttpResponse()  # pragma: no cover

    response = failing(RequestFactory().get("/api/runs/example"))
    assert response.status_code == 503
    assert b"private database diagnostic" not in response.content
    assert any(
        record.exc_info and isinstance(record.exc_info[1], OperationalError)
        for record in caplog.records
    )


def test_nested_suppressed_cause_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    try:
        suppressed_failure()
    except PersistenceError as error:
        wrapper = RuntimeError("worker boundary")
        wrapper.__cause__ = error
        log_persistence_failure(logging.getLogger(__name__), wrapper, worker_id="test")
        assert isinstance(persistence_cause(wrapper), OperationalError)
    assert caplog.records[-1].worker_id == "test"
    assert caplog.records[-1].exc_info


def test_cause_walk_handles_cycles_and_non_database_errors() -> None:
    error = RuntimeError("cycle")
    error.__context__ = error
    assert persistence_cause(error) is None
    assert persistence_cause(PersistenceError("no cause")) is None
