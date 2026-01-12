
import pytest
from playwright.sync_api import sync_playwright

def test_auto_login_endpoint_reachable():
    """
    Test that the /auto-login endpoint is reachable.
    Note: This returns 400 because valid credentials are not provided in the test environment.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        response = page.goto('http://127.0.0.1:6003/auto-login')
        assert response.status == 400
        # Check text content if possible
        content = page.content()
        assert "Auto Login failed" in content
        browser.close()
