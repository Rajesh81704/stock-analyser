"""
Unit tests for KiteClientWrapper, Login URL, and Static IP Error formatting.
"""

import pytest
from src.algodesk.data.kite_client import KiteClientWrapper, StaticIPRestrictionError


def test_login_url_generation():
    """Validates login URL generation format."""
    url = KiteClientWrapper.get_login_url(api_key="test_api_key_123")
    assert "kite.zerodha.com" in url
    assert "api_key=test_api_key_123" in url


def test_missing_api_key_raises_error():
    """Generating login url without api key raises ValueError."""
    with pytest.raises(ValueError, match="KITE_API_KEY is required"):
        KiteClientWrapper.get_login_url(api_key="")


def test_static_ip_restriction_exception():
    """Verifies that StaticIPRestrictionError contains helpful troubleshooting guidance."""
    exc = StaticIPRestrictionError("VPS Static IP Not Authorized")
    assert "VPS Static IP" in str(exc)
