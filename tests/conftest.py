import pytest


@pytest.fixture(autouse=True)
def secrets_for_tests(monkeypatch):
    """Fixed fake secrets, so no test depends on (or can leak) the real .env."""
    monkeypatch.setenv("JWT_SECRET", "x" * 48)
    monkeypatch.setenv("PASSWORD_PEPPER", "p" * 48)
    monkeypatch.setenv("MONGO_PASSWORD", "m" * 48)  # the client is only built, never connected, in tests that do not override the store
