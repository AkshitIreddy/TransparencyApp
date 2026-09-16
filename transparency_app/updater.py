"""Secure, dependency-free updates from the project's GitHub Releases.

The running one-file executable cannot replace itself on Windows. We download
and hash the next executable first, then start a tiny detached PowerShell
helper which waits for this process to exit, swaps the file, and relaunches it.
"""

from dataclasses import dataclass
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.request

from . import __version__
from .update_installer import file_sha256

LATEST_RELEASE_API = (
    "https://api.github.com/repos/AkshitIreddy/TransparencyApp/releases/latest"
)
ASSET_NAME = "TransparencyApp.exe"
MAX_UPDATE_BYTES = 100 * 1024 * 1024
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256 = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    asset_url: str
    asset_size: int
    sha256: str
    release_url: str


def _version_tuple(value):
    match = _SEMVER.fullmatch(str(value).strip())
    return tuple(map(int, match.groups())) if match else None


def _request(url, timeout=20):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"TransparencyApp/{__version__}",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


def check_for_update(current_version=__version__, opener=_request):
    """Return the latest newer release, or None when already current."""
    try:
        with opener(LATEST_RELEASE_API) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise UpdateError(f"Could not check GitHub Releases: {exc}") from exc

    tag = str(payload.get("tag_name", ""))
    latest = _version_tuple(tag)
    current = _version_tuple(current_version)
    if latest is None or current is None:
        raise UpdateError("The release has an unsupported version number.")
    if latest <= current:
        return None

    asset = next(
        (item for item in payload.get("assets", [])
         if item.get("name") == ASSET_NAME),
        None,
    )
    if asset is None:
        raise UpdateError(f"Release {tag} has no {ASSET_NAME} asset.")

    url = str(asset.get("browser_download_url", ""))
    if not url.startswith("https://github.com/"):
        raise UpdateError("The update download URL is not trusted.")
    try:
        size = int(asset.get("size", 0))
    except (TypeError, ValueError):
        size = 0
    if size <= 0 or size > MAX_UPDATE_BYTES:
        raise UpdateError("The update has an invalid download size.")
    digest = _SHA256.fullmatch(str(asset.get("digest", "")))
    if digest is None:
        raise UpdateError("GitHub did not provide a SHA-256 digest for the update.")

    return ReleaseInfo(
        version=".".join(map(str, latest)),
        tag=tag,
        asset_url=url,
        asset_size=size,
        sha256=digest.group(1).lower(),
        release_url=str(payload.get("html_url", "")),
    )


def download_update(release, destination, progress=None, opener=_request):
    """Download and verify an update, atomically producing *destination*."""
    destination = os.path.abspath(destination)
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    partial = destination + ".part"
    hasher = hashlib.sha256()
    received = 0
    try:
        with opener(release.asset_url, timeout=60) as response, \
                open(partial, "wb") as output:
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                received += len(chunk)
                if received > release.asset_size or received > MAX_UPDATE_BYTES:
                    raise UpdateError("The update download is larger than expected.")
                output.write(chunk)
                hasher.update(chunk)
                if progress:
                    progress(received, release.asset_size)
        if received != release.asset_size:
            raise UpdateError("The update download is incomplete.")
        if hasher.hexdigest().lower() != release.sha256:
            raise UpdateError("The update failed SHA-256 verification.")
        os.replace(partial, destination)
        return destination
    except UpdateError:
        try:
            os.remove(partial)
        except OSError:
            pass
        raise
    except Exception as exc:
        try:
            os.remove(partial)
        except OSError:
            pass
        raise UpdateError(f"Could not download the update: {exc}") from exc


def staged_update_path(version):
    directory = os.path.join(tempfile.gettempdir(), "TransparencyAppUpdates")
    return os.path.join(directory, f"TransparencyApp-v{version}.exe")


def launch_installer(staged_path, target_path, expected_sha256, process_id=None,
                     version=None):
    """Start the verified executable's branded installer mode."""
    staged_path = os.path.abspath(staged_path)
    target_path = os.path.abspath(target_path)
    if not os.path.isfile(staged_path):
        raise UpdateError("The verified update file is missing.")
    if os.path.basename(target_path).lower() != ASSET_NAME.lower():
        raise UpdateError("Refusing to replace an unexpected executable name.")
    expected_sha256 = str(expected_sha256).lower()
    if file_sha256(staged_path) != expected_sha256:
        raise UpdateError("The update no longer matches its verified SHA-256.")
    try:
        creation_flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
        args = [staged_path, "--install-update", "--target", target_path,
                "--wait-pid", str(process_id or os.getpid()),
                "--expected-sha256", expected_sha256]
        if version:
            args += ["--version", str(version)]
        return subprocess.Popen(
            args,
            cwd=os.path.dirname(target_path),
            close_fds=True,
            creationflags=creation_flags,
        )
    except Exception as exc:
        raise UpdateError(f"Could not start the update installer: {exc}") from exc
