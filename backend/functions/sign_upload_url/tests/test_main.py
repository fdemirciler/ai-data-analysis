import os
import json
import importlib
from unittest.mock import MagicMock, patch

import pytest
from flask import Request
from werkzeug.datastructures import Headers

# Import the module to be tested
import main

@pytest.fixture(autouse=True)
def setup_and_reload_main(monkeypatch):
    """Set environment variables and reload the main module before each test."""
    monkeypatch.setenv("FILES_BUCKET", "test-bucket")
    monkeypatch.setenv("GCP_PROJECT", "test-project")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:5173,https://ai-data-analyser.web.app")
    monkeypatch.setenv("RUNTIME_SERVICE_ACCOUNT", "test-sa@example.com")
    importlib.reload(main)

@pytest.fixture
def mock_request():
    """Creates a mock Flask request object."""
    def _mock_request(
        method="POST",
        headers=None,
        args=None,
        json_data=None,
    ):
        req = MagicMock(spec=Request)
        req.method = method
        req.headers = Headers(headers or {})
        req.args = args or {}
        req.get_json.return_value = json_data or {}
        return req
    return _mock_request

@patch("main.storage.Client")
@patch("main.firestore.Client")
@patch("main.fb_auth.verify_id_token")
@patch("main._impersonated_signing_credentials")
def test_sign_upload_url_happy_path(
    mock_creds, mock_verify_id_token, mock_firestore_client, mock_storage_client, mock_request
):
    """
    Tests the happy path for the sign_upload_url function.
    """
    # Arrange: Set up mocks
    mock_verify_id_token.return_value = {"uid": "test-uid"}
    mock_creds.return_value = "mock-credentials"

    mock_blob = MagicMock()
    mock_blob.generate_signed_url.return_value = "https://signed.url/for/upload"
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_storage_client.return_value.bucket.return_value = mock_bucket

    mock_fs_doc = MagicMock()
    mock_firestore_client.return_value.document.return_value = mock_fs_doc

    # Arrange: Create a valid request
    req = mock_request(
        headers={
            "Origin": "http://localhost:5173",
            "Authorization": "Bearer valid-token",
            "X-Session-Id": "test-session-id",
        },
        args={
            "filename": "my_data.csv",
            "size": "1048576",  # 1 MB
            "type": "text/csv",
        },
    )

    # Act: Call the function
    response_body, status_code, headers = main.sign_upload_url(req)

    # Assert: Check the response
    assert status_code == 200
    assert headers["Content-Type"] == "application/json"
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"

    response_data = json.loads(response_body)
    assert response_data["url"] == "https://signed.url/for/upload"
    assert "datasetId" in response_data
    assert response_data["storagePath"].startswith("users/test-uid/sessions/test-session-id/datasets/")
    assert response_data["storagePath"].endswith("/raw/input.csv")

    # Assert: Check that external services were called correctly
    mock_verify_id_token.assert_called_once_with("valid-token")
    mock_storage_client.return_value.bucket.assert_called_once_with("test-bucket")
    mock_bucket.blob.assert_called_once()
    mock_blob.generate_signed_url.assert_called_once()
    mock_firestore_client.return_value.document.assert_called_once()
    mock_fs_doc.set.assert_called_once()

    # Check that the Firestore document has the correct status
    firestore_call_args = mock_fs_doc.set.call_args[0][0]
    assert firestore_call_args["status"] == "awaiting_upload"
    assert firestore_call_args["rawUri"].startswith("gs://test-bucket/users/test-uid/")


def test_sign_upload_url_invalid_origin(mock_request):
    """
    Tests that a request with an invalid origin is rejected.
    """
    # Arrange
    req = mock_request(headers={"Origin": "https://invalid.origin"})

    # Act
    response_body, status_code, _ = main.sign_upload_url(req)

    # Assert
    assert status_code == 403
    response_data = json.loads(response_body)
    assert response_data["error"] == "origin not allowed"


@patch("main.fb_auth.verify_id_token")
def test_sign_upload_url_missing_token(mock_verify_id_token, mock_request):
    """
    Tests that a request without an auth token is rejected.
    """
    # Arrange
    req = mock_request(
        headers={
            "Origin": "http://localhost:5173",
            "X-Session-Id": "test-session-id",
        },
        args={"filename": "a.csv", "size": "100", "type": "text/csv"},
    )

    # Act
    response_body, status_code, _ = main.sign_upload_url(req)

    # Assert
    assert status_code == 401
    response_data = json.loads(response_body)
    assert response_data["error"] == "missing Authorization Bearer token"
    mock_verify_id_token.assert_not_called()


@patch("main.fb_auth.verify_id_token")
def test_sign_upload_url_invalid_token(mock_verify_id_token, mock_request):
    """
    Tests that a request with an invalid auth token is rejected.
    """
    # Arrange
    mock_verify_id_token.side_effect = Exception("Invalid token")
    req = mock_request(
        headers={
            "Origin": "http://localhost:5173",
            "Authorization": "Bearer invalid-token",
            "X-Session-Id": "test-session-id",
        },
        args={"filename": "a.csv", "size": "100", "type": "text/csv"},
    )

    # Act
    response_body, status_code, _ = main.sign_upload_url(req)

    # Assert
    assert status_code == 401
    response_data = json.loads(response_body)
    assert response_data["error"] == "invalid token"


@patch("main.fb_auth.verify_id_token")
def test_sign_upload_url_missing_session_id(mock_verify_id_token, mock_request):
    """
    Tests that a request without a session ID is rejected.
    """
    # Arrange
    mock_verify_id_token.return_value = {"uid": "test-uid"}
    req = mock_request(
        headers={
            "Origin": "http://localhost:5173",
            "Authorization": "Bearer valid-token",
        },
        args={"filename": "a.csv", "size": "100", "type": "text/csv"},
    )

    # Act
    response_body, status_code, _ = main.sign_upload_url(req)

    # Assert
    assert status_code == 400
    response_data = json.loads(response_body)
    assert response_data["error"] == "Missing X-Session-Id header"


@patch("main.fb_auth.verify_id_token")
@pytest.mark.parametrize("args", [
    {"size": "100", "type": "text/csv"},
    {"filename": "a.csv", "size": "100"},
    {"filename": "a.csv", "type": "text/csv"},
])
def test_sign_upload_url_missing_args(mock_verify_id_token, mock_request, args):
    """
    Tests that requests with missing file metadata are rejected.
    """
    # Arrange
    mock_verify_id_token.return_value = {"uid": "test-uid"}
    req = mock_request(
        headers={
            "Origin": "http://localhost:5173",
            "Authorization": "Bearer valid-token",
            "X-Session-Id": "test-session-id",
        },
        args=args,
    )

    # Act
    response_body, status_code, _ = main.sign_upload_url(req)

    # Assert
    assert status_code == 400


@patch("main.fb_auth.verify_id_token")
def test_sign_upload_url_file_too_large(mock_verify_id_token, mock_request):
    """
    Tests that a request for a file that is too large is rejected.
    """
    # Arrange
    mock_verify_id_token.return_value = {"uid": "test-uid"}
    req = mock_request(
        headers={
            "Origin": "http://localhost:5173",
            "Authorization": "Bearer valid-token",
            "X-Session-Id": "test-session-id",
        },
        args={
            "filename": "large.csv",
            "size": str(20 * 1024 * 1024 + 1),
            "type": "text/csv",
        },
    )

    # Act
    response_body, status_code, _ = main.sign_upload_url(req)

    # Assert
    assert status_code == 400
    response_data = json.loads(response_body)
    assert "too large" in response_data["error"]


@patch("main.fb_auth.verify_id_token")
def test_sign_upload_url_unsupported_type(mock_verify_id_token, mock_request):
    """
    Tests that a request for an unsupported file type is rejected.
    """
    # Arrange
    mock_verify_id_token.return_value = {"uid": "test-uid"}
    req = mock_request(
        headers={
            "Origin": "http://localhost:5173",
            "Authorization": "Bearer valid-token",
            "X-Session-Id": "test-session-id",
        },
        args={
            "filename": "data.txt",
            "size": "1024",
            "type": "text/plain",
        },
    )

    # Act
    response_body, status_code, _ = main.sign_upload_url(req)

    # Assert
    assert status_code == 400
    response_data = json.loads(response_body)
    assert response_data["error"] == "unsupported file type"

@patch("main.storage.Client")
@patch("main.fb_auth.verify_id_token")
def test_sign_upload_url_storage_error(mock_verify_id_token, mock_storage_client, mock_request):
    """
    Tests that an internal server error is returned if Cloud Storage fails.
    """
    # Arrange
    mock_verify_id_token.return_value = {"uid": "test-uid"}
    mock_storage_client.side_effect = Exception("Storage is down")
    req = mock_request(
        headers={
            "Origin": "http://localhost:5173",
            "Authorization": "Bearer valid-token",
            "X-Session-Id": "test-session-id",
        },
        args={
            "filename": "my_data.csv",
            "size": "1048576",
            "type": "text/csv",
        },
    )

    # Act
    response_body, status_code, _ = main.sign_upload_url(req)

    # Assert
    assert status_code == 500
    response_data = json.loads(response_body)
    assert response_data["error"] == "internal error"


def test_sign_upload_url_cors_preflight(mock_request):
    """
    Tests the CORS preflight OPTIONS request.
    """
    # Arrange
    req = mock_request(
        method="OPTIONS",
        headers={"Origin": "http://localhost:5173"},
    )

    # Act
    response_body, status_code, headers = main.sign_upload_url(req)

    # Assert
    assert status_code == 204
    assert response_body == ""
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "GET" in headers["Access-Control-Allow-Methods"]
    assert "POST" in headers["Access-Control-Allow-Methods"]
    assert "OPTIONS" in headers["Access-Control-Allow-Methods"]
    assert "Content-Type" in headers["Access-Control-Allow-Headers"]
    assert "Authorization" in headers["Access-Control-Allow-Headers"]
    assert "X-Session-Id" in headers["Access-Control-Allow-Headers"]


def test_sign_upload_url_cors_preflight_invalid_origin(mock_request):
    """
    Tests that a CORS preflight from an invalid origin is rejected.
    """
    # Arrange
    req = mock_request(
        method="OPTIONS",
        headers={"Origin": "https://invalid.origin"},
    )

    # Act
    response_body, status_code, _ = main.sign_upload_url(req)

    # Assert
    assert status_code == 403
    assert "Origin not allowed" in response_body