"""Sign a release for the in-app updater (plan 17).

    uv run python scripts/release_sign.py keygen
    uv run python scripts/release_sign.py sign dist/WvWAnalyzer-Setup-X.Y.Z.exe

`keygen` writes a passphrase-protected Ed25519 private key (default
~/.wvw-analyzer/release-signing.key, never inside the repo) and prints the public key to add to
`TRUSTED_KEYS` in backend/wvw_analyzer/updater.py.

`sign` writes dist/latest.json and dist/latest.json.sig next to the installer. Attach all three
to the GitHub release:

    gh release create vX.Y.Z dist/WvWAnalyzer-Setup-X.Y.Z.exe dist/latest.json \
        dist/latest.json.sig --notes-file notes.md

The passphrase is asked for on the terminal; WVW_SIGNING_PASSPHRASE can supply it instead.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import os
import sys
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from wvw_analyzer import __version__, updater

DEFAULT_KEY = Path.home() / ".wvw-analyzer" / "release-signing.key"
ENV_PASSPHRASE = "WVW_SIGNING_PASSPHRASE"


def _passphrase(confirm: bool) -> bytes:
    env = os.environ.get(ENV_PASSPHRASE)
    if env:
        return env.encode()
    first = getpass.getpass("Signing key passphrase: ")
    if confirm and getpass.getpass("Again: ") != first:
        sys.exit("The passphrases differ.")
    if len(first) < 8:
        sys.exit("Use a passphrase of at least 8 characters.")
    return first.encode()


def public_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw,
                                        serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def keygen(path: Path) -> str:
    if path.exists():
        sys.exit(f"{path} already exists; not overwriting a signing key.")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.BestAvailableEncryption(_passphrase(confirm=True)))
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    return public_b64(key)


def load_key(path: Path) -> Ed25519PrivateKey:
    if not path.is_file():
        sys.exit(f"No signing key at {path} (run `keygen` first, or pass --key).")
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), _passphrase(confirm=False))
    except ValueError:
        sys.exit("Wrong passphrase or not a key file.")
    if not isinstance(key, Ed25519PrivateKey):
        sys.exit("Not an Ed25519 key.")
    return key


def sign(installer: Path, key: Ed25519PrivateKey, version: str = __version__,
         trusted: list[str] | None = None) -> tuple[Path, Path]:
    """Write latest.json and latest.json.sig next to the installer; returns their paths."""
    if installer.name != updater.installer_name(version):
        sys.exit(f"Expected {updater.installer_name(version)} (the app version is {version}).")
    if public_b64(key) not in (updater.TRUSTED_KEYS if trusted is None else trusted):
        sys.exit("This key is not in updater.TRUSTED_KEYS: the app would refuse the release.")
    manifest = updater.build_manifest(version, installer, date.today().isoformat())
    sig = base64.b64encode(key.sign(manifest)).decode()
    updater.verify_signature(manifest, sig, [public_b64(key)])  # check before publishing
    out = installer.parent / updater.MANIFEST_NAME
    sig_out = installer.parent / updater.SIG_NAME
    out.write_bytes(manifest)
    sig_out.write_text(sig + "\n", encoding="ascii")
    return out, sig_out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--key", type=Path, default=DEFAULT_KEY, help="private key file")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen", help="create the signing key")
    s = sub.add_parser("sign", help="sign an installer")
    s.add_argument("installer", type=Path)
    args = p.parse_args()
    if args.cmd == "keygen":
        pub = keygen(args.key)
        print(f"Key written to {args.key}. Back it up; keep it out of the repo.")
        print("Add this to TRUSTED_KEYS in backend/wvw_analyzer/updater.py:")
        print(f'    "{pub}",')
    else:
        manifest, sig = sign(args.installer, load_key(args.key))
        print(f"Wrote {manifest} and {sig}")


if __name__ == "__main__":
    main()
