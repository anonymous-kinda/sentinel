"""deploy/tools.lock: third-party binaries and trust material, pinned by sha256.

    name  version  arch  sha256  url  member

`arch` is x86_64, aarch64 or noarch (trust roots, signature bundles). `member`
is the path inside a .tar.gz, or `-` for a file served as-is. A download is
hashed before anything is written; a mismatch raises and leaves no file
behind (SR-3, SR-11). A file already on disk is reused only if it still
hashes to what was written after that verified download.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import pathlib
import re
import tarfile
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable

from sentinel.obs import get_logger

log = get_logger(__name__)

NOARCH = "noarch"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COLUMNS = ("name", "version", "arch", "sha256", "url", "member")


class LockError(Exception):
    """A pin is malformed or missing, or its file cannot be fetched or does not match it."""


class DownloadError(LockError):
    """A pinned file could not be downloaded: no network, a DNS or HTTP error,
    a timeout. It names the tool and the URL; nothing is written."""


@dataclasses.dataclass(frozen=True)
class ToolPin:
    name: str
    version: str
    arch: str
    sha256: str
    url: str
    member: str

    @property
    def is_data(self) -> bool:
        """Trust material (JSON) is written without the execute bit."""
        return self.name.endswith(".json")


def parse(text: str) -> list[ToolPin]:
    pins = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != len(_COLUMNS):
            raise LockError(f"tools.lock line {number}: expected {len(_COLUMNS)} columns, got {len(fields)}")
        row = dict(zip(_COLUMNS, fields, strict=True))
        if not _SHA256.fullmatch(row["sha256"]):
            raise LockError(f"tools.lock line {number}: sha256 must be 64 lowercase hex characters")
        pins.append(ToolPin(**row))
    return pins


def read_lock(path: pathlib.Path) -> list[ToolPin]:
    return parse(path.read_text())


def select(pins: Iterable[ToolPin], arch: str, names: Iterable[str] = ()) -> list[ToolPin]:
    """Pins for one architecture (plus noarch), optionally narrowed to names.

    Every requested name must have a pin: asking for a tool the lock does not
    cover is an error, not a silent partial fetch.
    """
    wanted = list(names)
    chosen = [p for p in pins if p.arch in (arch, NOARCH) and (not wanted or p.name in wanted)]
    missing = sorted(set(wanted) - {p.name for p in chosen})
    if missing:
        raise LockError(f"no pin for arch {arch}: {', '.join(missing)}")
    return chosen


Opener = Callable[..., io.BufferedIOBase]


def fetch(pin: ToolPin, dest_dir: pathlib.Path, opener: Opener = urllib.request.urlopen) -> pathlib.Path:
    """Download, verify and install one pinned file into dest_dir."""
    dest = dest_dir / pin.name
    stamp = dest_dir / f".{pin.name}.sha256"
    if dest.exists() and stamp.exists() and stamp.read_text().strip() == _stamp(pin, dest.read_bytes()):
        return dest
    blob = _download(pin, opener)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != pin.sha256:
        log.error("Pinned download digest mismatch", tool=pin.name, arch=pin.arch, got=digest, pinned=pin.sha256)
        raise LockError(f"SHA-256 mismatch for {pin.name} {pin.arch}: got {digest}, pinned {pin.sha256}")
    payload = blob if pin.member == "-" else _extract(blob, pin.member)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(payload)
    dest.chmod(0o644 if pin.is_data else 0o755)
    stamp.write_text(_stamp(pin, payload) + "\n")
    log.info("Pinned tool installed", tool=pin.name, version=pin.version, arch=pin.arch, sha256=pin.sha256)
    return dest


def _download(pin: ToolPin, opener: Opener) -> bytes:
    try:
        with opener(pin.url, timeout=120) as response:
            return response.read()
    except OSError as error:  # URLError, HTTPError, timeouts and resets are all OSError
        reason = _reason(error)
        log.error("Pinned tool download failed", tool=pin.name, arch=pin.arch, url=pin.url, error=reason)
        raise DownloadError(f"cannot download {pin.name} {pin.version} ({pin.arch}) from {pin.url}: {reason}") from error


def _reason(error: OSError) -> str:
    """The status of an HTTP error, the socket error a URLError wraps, or the error itself."""
    if isinstance(error, urllib.error.HTTPError):
        return f"HTTP {error.code} {error.reason}"
    if isinstance(error, urllib.error.URLError):
        return str(error.reason)
    return str(error)


def _stamp(pin: ToolPin, installed: bytes) -> str:
    """The pin a file was verified against, and the digest of the file as
    written: a member extracted from an archive has no pin of its own."""
    return f"{pin.sha256} {hashlib.sha256(installed).hexdigest()}"


def _extract(blob: bytes, member: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        handle = tar.extractfile(member)
        if handle is None:
            raise LockError(f"{member} is not a regular file in the archive")
        return handle.read()
