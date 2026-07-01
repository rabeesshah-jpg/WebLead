"""Tests for qualification DRF permissions and exception helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory

from apps.qualification.api.exceptions import (
    FORBIDDEN_ERROR,
    INTERNAL_SERVER_ERROR,
    INVALID_REQUEST_ERROR,
    QUALIFICATION_SERVICE_REQUEST_FAILED_ERROR,
    QUALIFICATION_SERVICE_UNAVAILABLE_ERROR,
    SERVICE_REQUEST_FAILED_ERROR,
    SERVICE_UNAVAILABLE_ERROR,
    error_response,
    qualification_exception_handler,
)
from apps.qualification.api.permissions import InternalWebhookSecretPermission


@patch("apps.qualification.api.permissions.is_internal_qualification_authorized")
def test_internal_webhook_secret_permission_delegates_to_auth_helper(mock_is_authorized):
    mock_is_authorized.return_value = True
    permission = InternalWebhookSecretPermission()
    request = MagicMock()

    assert permission.has_permission(request, None) is True
    mock_is_authorized.assert_called_once_with(request)


@patch("apps.qualification.api.permissions.is_internal_qualification_authorized", return_value=True)
def test_valid_secret_header_permits_access(mock_is_authorized):
    permission = InternalWebhookSecretPermission()
    assert permission.has_permission(MagicMock(), None) is True


@patch("apps.qualification.api.permissions.is_internal_qualification_authorized", return_value=False)
def test_missing_or_invalid_secret_header_is_denied(mock_is_authorized):
    permission = InternalWebhookSecretPermission()
    assert permission.has_permission(MagicMock(), None) is False
    assert permission.message == "Forbidden."


def test_error_response_forbidden_returns_contract_403():
    response = error_response(FORBIDDEN_ERROR, 403)

    assert response.status_code == 403
    assert response.data == {"error": "Forbidden."}


def test_error_response_internal_server_error_returns_contract_500():
    response = error_response(INTERNAL_SERVER_ERROR, 500)

    assert response.status_code == 500
    assert response.data == {"error": "Internal server error."}


def test_error_response_invalid_request_returns_contract_400():
    response = error_response(INVALID_REQUEST_ERROR, 400)

    assert response.status_code == 400
    assert response.data == {"error": "Invalid request."}


def test_error_response_service_request_failed_returns_contract_502():
    response = error_response(SERVICE_REQUEST_FAILED_ERROR, 502)

    assert response.status_code == 502
    assert response.data == {"error": "Qualification service request failed."}


def test_error_response_service_unavailable_returns_contract_503():
    response = error_response(SERVICE_UNAVAILABLE_ERROR, 503)

    assert response.status_code == 503
    assert response.data == {"error": "Qualification service is unavailable."}


def test_qualification_exception_handler_maps_permission_denied_to_forbidden_contract():
    request = APIRequestFactory().get("/api/internal/qualification/extract/")
    exc = PermissionDenied("Forbidden.")

    response = qualification_exception_handler(exc, {"request": request, "view": None})

    assert response is not None
    assert response.status_code == 403
    assert response.data == {"error": FORBIDDEN_ERROR}


def test_service_error_aliases_match_standardized_constants():
    assert QUALIFICATION_SERVICE_REQUEST_FAILED_ERROR == SERVICE_REQUEST_FAILED_ERROR
    assert QUALIFICATION_SERVICE_UNAVAILABLE_ERROR == SERVICE_UNAVAILABLE_ERROR
