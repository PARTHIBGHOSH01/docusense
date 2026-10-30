import base64

from app import main


def test_basic_auth_requires_exact_configured_credentials(monkeypatch):
    monkeypatch.setattr(main, "APP_USERNAME", "parth")
    monkeypatch.setattr(main, "APP_PASSWORD", "a long demo password")
    valid = base64.b64encode(b"parth:a long demo password").decode("ascii")
    wrong_password = base64.b64encode(b"parth:wrong").decode("ascii")

    assert main._valid_basic_credentials(f"Basic {valid}")
    assert not main._valid_basic_credentials(None)
    assert not main._valid_basic_credentials("Bearer token")
    assert not main._valid_basic_credentials("Basic not-valid-base64!")
    assert not main._valid_basic_credentials(f"Basic {wrong_password}")
