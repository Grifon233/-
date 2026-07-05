from pathlib import Path

from backend.media_storage import (
    get_upload_dir,
    normalize_media_reference,
    public_upload_url,
)


def test_upload_dir_is_stable_for_relative_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "persistent-uploads"))

    upload_dir = get_upload_dir()

    assert upload_dir == (tmp_path / "persistent-uploads").resolve()
    assert upload_dir.is_dir()


def test_default_upload_dir_is_inside_project(monkeypatch):
    monkeypatch.delenv("UPLOAD_DIR", raising=False)

    upload_dir = get_upload_dir()

    assert upload_dir.name == "uploads"
    assert upload_dir.parent == Path(__file__).resolve().parents[1]


def test_legacy_local_upload_url_uses_current_site():
    assert normalize_media_reference(
        "http://127.0.0.1:8000/api/uploads/avatar_12.jpg"
    ) == "/api/uploads/avatar_12.jpg"
    assert normalize_media_reference(
        "http://localhost:8000/uploads/menu_12.png?version=2"
    ) == "/api/uploads/menu_12.png?version=2"


def test_external_media_url_is_not_rewritten():
    value = "https://cdn.example.com/profiles/avatar.jpg"
    assert normalize_media_reference(value) == value
    assert public_upload_url("avatar.jpg") == "/api/uploads/avatar.jpg"
