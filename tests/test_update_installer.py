import hashlib

import pytest

from transparency_app import update_installer
from transparency_app.update_installer import InstallError, file_sha256


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_file_sha256_matches_hashlib(tmp_path):
    target = tmp_path / "blob.bin"
    target.write_bytes(b"Transparency App installer bytes")
    assert file_sha256(str(target)) == sha(b"Transparency App installer bytes")


def test_replace_and_restart_installs_verified_copy(tmp_path):
    source = tmp_path / "new.exe"
    source.write_bytes(b"new verified bytes")
    target = tmp_path / update_installer.ASSET_NAME
    target.write_bytes(b"old bytes")
    launched = {}

    def fake_launcher(args, **kwargs):
        launched["args"] = args
        return object()

    progress = []
    update_installer.replace_and_restart(
        str(source), str(target), 999, sha(b"new verified bytes"),
        progress=lambda v, m: progress.append((v, m)),
        launcher=fake_launcher, waiter=lambda _pid, _ms: True)

    assert target.read_bytes() == b"new verified bytes"
    assert (tmp_path / (update_installer.ASSET_NAME + ".previous")).read_bytes() == b"old bytes"
    assert launched["args"] == [str(target)]
    assert progress[0][0] < progress[-1][0] == 1.0


def test_replace_and_restart_restores_backup_on_launch_failure(tmp_path):
    source = tmp_path / "new.exe"
    source.write_bytes(b"new verified bytes")
    target = tmp_path / update_installer.ASSET_NAME
    target.write_bytes(b"old bytes")

    def boom(*_args, **_kwargs):
        raise OSError("cannot start")

    with pytest.raises(InstallError, match="Could not install"):
        update_installer.replace_and_restart(
            str(source), str(target), 999, sha(b"new verified bytes"),
            launcher=boom, waiter=lambda _pid, _ms: True)

    assert target.read_bytes() == b"old bytes"


def test_replace_and_restart_refuses_bad_hash(tmp_path):
    source = tmp_path / "new.exe"
    source.write_bytes(b"tampered")
    target = tmp_path / update_installer.ASSET_NAME
    target.write_bytes(b"old bytes")
    with pytest.raises(InstallError, match="SHA-256"):
        update_installer.replace_and_restart(
            str(source), str(target), 999, "0" * 64,
            launcher=lambda *a, **k: None, waiter=lambda _p, _m: True)
    assert target.read_bytes() == b"old bytes"


def test_replace_and_restart_refuses_unexpected_name(tmp_path):
    source = tmp_path / "new.exe"
    source.write_bytes(b"bytes")
    with pytest.raises(InstallError, match="unexpected executable"):
        update_installer.replace_and_restart(
            str(source), str(tmp_path / "other.exe"), 999, sha(b"bytes"),
            launcher=lambda *a, **k: None, waiter=lambda _p, _m: True)
