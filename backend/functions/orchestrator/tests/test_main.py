import pytest
from unittest.mock import patch, MagicMock

# Temporarily add the parent directory to the path to allow imports
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now, import the module
import main

# Test cases for the _origin_allowed function
@pytest.mark.parametrize("origin, allowed_origins, expected", [
    ("http://localhost:5173", {"http://localhost:5173", "https://example.com"}, True),
    ("https://example.com", {"http://localhost:5173", "https://example.com"}, True),
    ("http://disallowed.com", {"http://localhost:5173", "https://example.com"}, False),
    (None, {"http://localhost:5173", "https://example.com"}, False),
    ("http://localhost:5173", {}, False),
])
def test_origin_allowed(origin, allowed_origins, expected, monkeypatch):
    """
    Tests the _origin_allowed function with various origins and allowed lists.
    """
    monkeypatch.setattr(main, "ALLOWED_ORIGINS", allowed_origins)
    assert main._origin_allowed(origin) == expected

# Test cases for the _sign_gs_uri function
@patch("main.storage.Client")
@patch("main._impersonated_signing_credentials")
def test_sign_gs_uri_valid(mock_creds, mock_storage_client):
    """
    Tests that _sign_gs_uri correctly generates a signed URL for a valid gs:// URI.
    """
    # Arrange
    mock_blob = MagicMock()
    mock_blob.generate_signed_url.return_value = "https://signed.url"
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_storage_client.return_value.bucket.return_value = mock_bucket
    mock_creds.return_value = "dummy-credentials"

    # Act
    signed_url = main._sign_gs_uri("gs://test-bucket/test-object")

    # Assert
    assert signed_url == "https://signed.url"
    mock_storage_client.return_value.bucket.assert_called_with("test-bucket")
    mock_bucket.blob.assert_called_with("test-object")
    mock_blob.generate_signed_url.assert_called_once()

@pytest.mark.parametrize("invalid_uri", [
    "not-a-gs-uri",
    "http://example.com/test.txt",
    "",
    None,
])
def test_sign_gs_uri_invalid_input(invalid_uri):
    """
    Tests that _sign_gs_uri returns the original URI if it's not a valid gs:// URI.
    """
    assert main._sign_gs_uri(invalid_uri) == invalid_uri

@patch("main.storage.Client", side_effect=Exception("GCS error"))
def test_sign_gs_uri_exception(mock_storage_client):
    """
    Tests that _sign_gs_uri returns the original URI when an exception occurs.
    """
    assert main._sign_gs_uri("gs://test-bucket/test-object") == "gs://test-bucket/test-object"