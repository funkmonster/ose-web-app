"""
Tests for config.py

Config.load_users() caches to a class attribute (_users_cache), so every
test that touches it must reset that cache and point USERS_FILE at its
own temp file — otherwise tests leak state into each other via the shared
class object.
"""

import pytest
import yaml

from config import Config


@pytest.fixture(autouse=True)
def reset_users_cache():
    """Ensure no test observes another test's cached users.yaml."""
    Config._users_cache = None
    yield
    Config._users_cache = None


@pytest.fixture
def users_file(tmp_path, monkeypatch):
    def _make(users):
        path = tmp_path / "users.yaml"
        path.write_text(yaml.dump({"users": users}))
        monkeypatch.setattr(Config, "USERS_FILE", str(path))
        return path
    return _make


SAMPLE_USERS = [
    {"name": "Sean", "passphrase": "keep-on-the-borderlands", "role": "gm", "color": "#ff0000"},
    {"name": "Wren", "passphrase": "wren-secret", "role": "player", "color": "#00ff00"},
]


def test_load_users_reads_and_caches(users_file):
    path = users_file(SAMPLE_USERS)
    users = Config.load_users()
    assert len(users) == 2
    assert Config._users_cache is users

    # Mutate the file on disk — cached result should NOT change
    path.write_text(yaml.dump({"users": []}))
    assert len(Config.load_users()) == 2


def test_load_users_missing_users_key_defaults_to_empty_list(tmp_path, monkeypatch):
    path = tmp_path / "users.yaml"
    path.write_text(yaml.dump({}))
    monkeypatch.setattr(Config, "USERS_FILE", str(path))
    assert Config.load_users() == []


def test_authenticate_returns_user_without_passphrase(users_file):
    users_file(SAMPLE_USERS)
    user = Config.authenticate("keep-on-the-borderlands")
    assert user == {"name": "Sean", "role": "gm", "color": "#ff0000"}
    assert "passphrase" not in user


def test_authenticate_wrong_passphrase_returns_none(users_file):
    users_file(SAMPLE_USERS)
    assert Config.authenticate("not-a-real-passphrase") is None


def test_authenticate_empty_passphrase_returns_none(users_file):
    users_file(SAMPLE_USERS)
    assert Config.authenticate("") is None


def test_authenticate_is_case_sensitive(users_file):
    users_file(SAMPLE_USERS)
    assert Config.authenticate("Keep-On-The-Borderlands") is None


def test_get_user_by_name(users_file):
    users_file(SAMPLE_USERS)
    user = Config.get_user("Wren")
    assert user == {"name": "Wren", "role": "player", "color": "#00ff00"}


def test_get_user_unknown_name_returns_none(users_file):
    users_file(SAMPLE_USERS)
    assert Config.get_user("Nobody") is None
