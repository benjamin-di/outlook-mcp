"""One instance may optionally refuse a different sign-in; every record here is synthetic."""

from unittest.mock import MagicMock

import pytest
from azure.identity import AuthenticationRecord
from pydantic import ValidationError

from outlook_mcp import auth as auth_module
from outlook_mcp.auth import AuthManager
from outlook_mcp.config import Config
from outlook_mcp.errors import OutlookMCPError


def record(username):
    return AuthenticationRecord(
        tenant_id="consumers",
        client_id="test-id",
        authority="https://login.microsoftonline.com/consumers",
        home_account_id="home-1",
        username=username,
    )


@pytest.mark.parametrize("username", ["other@example.com", ""])
def test_wrong_saved_user_is_refused_before_any_credential(tmp_path, monkeypatch, username):
    path = tmp_path / "auth_record.json"
    path.write_text(record(username).serialize())
    original = path.read_bytes()
    monkeypatch.setattr(auth_module, "_auth_record_path", lambda: path)
    manager = AuthManager(Config(client_id="test-id", expected_username="owner@example.com"))
    make = MagicMock()
    monkeypatch.setattr(manager, "_make_credential", make)

    assert manager.try_cached_token() is False
    assert not manager.is_authenticated()
    make.assert_not_called()
    assert manager.startup_error.code == "account_mismatch"
    with pytest.raises(OutlookMCPError, match="expected_username"):
        manager.get_credential()
    assert path.read_bytes() == original


@pytest.mark.parametrize("expected", [None, "OWNER@Example.COM"])
def test_unset_or_case_insensitive_match_keeps_cached_refresh(monkeypatch, expected):
    saved = record("owner@example.com")
    monkeypatch.setattr(auth_module, "_load_auth_record", lambda: saved)
    manager = AuthManager(Config(client_id="test-id", expected_username=expected))
    make = MagicMock()
    monkeypatch.setattr(manager, "_make_credential", make)

    assert manager.try_cached_token() is True
    make.assert_called_once_with(auth_record=saved, silent=True)
    make.return_value.get_token.assert_called_once_with(auth_module.GRAPH_DEFAULT_SCOPE)


@pytest.mark.parametrize("username", ["other@example.com", None])
def test_wrong_new_user_does_not_replace_an_existing_record(tmp_path, monkeypatch, username):
    path = tmp_path / "auth_record.json"
    path.write_text(record("owner@example.com").serialize())
    original = path.read_bytes()
    monkeypatch.setattr(auth_module, "_auth_record_path", lambda: path)
    manager = AuthManager(Config(client_id="test-id", expected_username="owner@example.com"))
    credential = MagicMock()
    credential._auth_record = record(username) if username is not None else None
    monkeypatch.setattr(manager, "_make_credential", MagicMock(return_value=credential))

    with pytest.raises(OutlookMCPError, match="expected_username"):
        manager.login_interactive()
    assert not manager.is_authenticated()
    assert path.read_bytes() == original


@pytest.mark.parametrize("expected", [None, "OWNER@Example.COM"])
def test_matching_new_sign_in_is_saved_and_used(tmp_path, monkeypatch, expected):
    path = tmp_path / "auth_record.json"
    monkeypatch.setattr(auth_module, "_auth_record_path", lambda: path)
    manager = AuthManager(Config(client_id="test-id", expected_username=expected))
    credential = MagicMock()
    credential._auth_record = record("owner@example.com")
    monkeypatch.setattr(manager, "_make_credential", MagicMock(return_value=credential))

    manager.login_interactive()
    assert manager.get_credential() is credential
    assert auth_module._load_auth_record().username == "owner@example.com"


@pytest.mark.parametrize("value", ["", "  ", "owner\n@example.com", "owner\x00@example.com"])
def test_expected_username_refuses_blank_or_control_characters(value):
    with pytest.raises(ValidationError, match="expected_username"):
        Config(expected_username=value)


@pytest.mark.parametrize("key", ["expectedUsername", "expected-user-name", "expected_usernmae"])
def test_a_misspelt_identity_guard_is_not_ignored(key):
    with pytest.raises(ValidationError, match="expected_username"):
        Config(**{key: "owner@example.com"})
