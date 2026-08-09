import hashlib
import io
import json
import os

import pytest

from transparency_app import updater


class FakeResponse:
    def __init__(self, data):
        self._stream = io.BytesIO(data)

    def read(self, size=-1):
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def release_payload(version="9.2.1", content=b"new executable"):
    return {
        "tag_name": f"v{version}",
        "html_url": f"https://github.com/example/releases/tag/v{version}",
        "assets": [{
            "name": updater.ASSET_NAME,
            "browser_download_url": (
                f"https://github.com/example/releases/download/v{version}/"
                f"{updater.ASSET_NAME}"),
            "size": len(content),
            "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
        }],
    }


def test_check_for_update_returns_verified_asset_metadata():
    payload = json.dumps(release_payload()).encode()
    info = updater.check_for_update(
        "2.1.2", opener=lambda *_args, **_kwargs: FakeResponse(payload))

    assert info.version == "9.2.1"
    assert info.asset_size == len(b"new executable")
    assert len(info.sha256) == 64


def test_check_for_update_returns_none_when_current():
    payload = json.dumps(release_payload(version="2.1.2")).encode()
    assert updater.check_for_update(
        "2.1.2", opener=lambda *_args, **_kwargs: FakeResponse(payload)) is None


def test_check_rejects_release_without_digest():
    data = release_payload()
    data["assets"][0]["digest"] = None
    payload = json.dumps(data).encode()
    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.check_for_update(
            "2.1.2", opener=lambda *_args, **_kwargs: FakeResponse(payload))


def test_download_update_verifies_and_moves_complete_file(tmp_path):
    content = b"verified release bytes"
    data = release_payload(content=content)
    asset = data["assets"][0]
    info = updater.ReleaseInfo(
        version="9.2.1", tag="v9.2.1",
        asset_url=asset["browser_download_url"],
        asset_size=asset["size"], sha256=asset["digest"].split(":", 1)[1],
        release_url=data["html_url"])
    destination = tmp_path / updater.ASSET_NAME
    progress = []

    updater.download_update(
        info, str(destination), progress=lambda done, total: progress.append(
            (done, total)),
        opener=lambda *_args, **_kwargs: FakeResponse(content))

    assert destination.read_bytes() == content
    assert progress[-1] == (len(content), len(content))
    assert not os.path.exists(str(destination) + ".part")


def test_download_update_removes_partial_on_hash_mismatch(tmp_path):
    content = b"tampered bytes"
    info = updater.ReleaseInfo(
        version="9.2.1", tag="v9.2.1",
        asset_url="https://github.com/example/TransparencyApp.exe",
        asset_size=len(content), sha256="0" * 64,
        release_url="https://github.com/example/releases/tag/v9.2.1")
    destination = tmp_path / updater.ASSET_NAME

    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.download_update(
            info, str(destination),
            opener=lambda *_args, **_kwargs: FakeResponse(content))
    assert not destination.exists()
    assert not os.path.exists(str(destination) + ".part")


def test_installer_refuses_unexpected_target_name(tmp_path):
    staged = tmp_path / "staged.exe"
    staged.write_bytes(b"bytes")
    with pytest.raises(updater.UpdateError, match="unexpected executable"):
        updater.launch_installer(str(staged), str(tmp_path / "other.exe"))


def test_installer_writes_detached_rollback_helper(tmp_path, monkeypatch):
    staged = tmp_path / "staged.exe"
    staged.write_bytes(b"verified bytes")
    target = tmp_path / updater.ASSET_NAME
    target.write_bytes(b"old bytes")
    called = {}
    sentinel = object()

    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))

    def fake_popen(args, **kwargs):
        called["args"] = args
        called["kwargs"] = kwargs
        return sentinel

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    result = updater.launch_installer(
        str(staged), str(target), process_id=12345)

    assert result is sentinel
    assert "-WindowStyle" in called["args"]
    assert "Hidden" in called["args"]
    assert called["args"][called["args"].index("-AppProcessId") + 1] == "12345"
    script_path = called["args"][called["args"].index("-File") + 1]
    script = open(script_path, encoding="utf-8-sig").read()
    assert "Wait-Process" in script
    assert "$Target.previous" in script
    assert "$swapped" in script
