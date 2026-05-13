"""Cosign-based signing and verification for .zil archives."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_COSIGN_NOT_FOUND_MSG = (
    "cosign is not installed or not in PATH.\n"
    "Install it from: https://docs.sigstore.dev/cosign/system_config/installation/\n"
    "  macOS:   brew install cosign\n"
    "  Linux:   https://github.com/sigstore/cosign/releases\n"
    "  Docker:  gcr.io/projectsigstore/cosign"
)


@dataclass
class SignResult:
    """Result of signing an archive."""

    signed: bool
    signature_path: Path | None = None
    certificate_path: Path | None = None
    signature_type: str = ""
    signer_identity: str = ""
    error: str = ""


@dataclass
class VerifyResult:
    """Result of verifying a signed archive."""

    verified: bool
    signer_identity: str = ""
    error: str = ""


def _find_cosign() -> Path | None:
    """Locate the cosign binary."""
    path = shutil.which("cosign")
    return Path(path) if path else None


def sign_archive(
    archive_path: Path,
    *,
    key_path: Path | None = None,
) -> SignResult:
    """Sign a .zil archive using cosign.

    Args:
        archive_path: Path to the .zil archive to sign.
        key_path: Optional path to a cosign private key. If None, uses
            keyless (OIDC/Sigstore) signing.

    Returns:
        SignResult with paths to the .sig and .cert files.
    """
    cosign = _find_cosign()
    if cosign is None:
        return SignResult(signed=False, error=_COSIGN_NOT_FOUND_MSG)

    sig_path = archive_path.with_suffix(archive_path.suffix + ".sig")
    cert_path = archive_path.with_suffix(archive_path.suffix + ".cert")

    if key_path:
        # Key-based signing
        cmd = [
            str(cosign),
            "sign-blob",
            "--key", str(key_path),
            "--output-signature", str(sig_path),
            "--tlog-upload=false",
            str(archive_path),
        ]
        signature_type = "cosign-key"
    else:
        # Keyless (OIDC) signing via Sigstore
        cmd = [
            str(cosign),
            "sign-blob",
            "--yes",
            "--output-signature", str(sig_path),
            "--output-certificate", str(cert_path),
            str(archive_path),
        ]
        signature_type = "cosign-keyless"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return SignResult(signed=False, error="cosign timed out after 120 seconds")
    except OSError as e:
        return SignResult(signed=False, error=f"Failed to run cosign: {e}")

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        return SignResult(signed=False, error=f"cosign failed: {error_msg}")

    # Extract signer identity from certificate if available
    signer_identity = ""
    if cert_path.exists():
        signer_identity = _extract_signer_from_cert(cert_path)

    return SignResult(
        signed=True,
        signature_path=sig_path if sig_path.exists() else None,
        certificate_path=cert_path if cert_path.exists() else None,
        signature_type=signature_type,
        signer_identity=signer_identity,
    )


def verify_archive(
    archive_path: Path,
    *,
    key_path: Path | None = None,
) -> VerifyResult:
    """Verify a signed .zil archive using cosign.

    Looks for .sig and .cert files alongside the archive.

    Args:
        archive_path: Path to the .zil archive.
        key_path: Optional path to the cosign public key.

    Returns:
        VerifyResult indicating whether verification passed.
    """
    cosign = _find_cosign()
    if cosign is None:
        return VerifyResult(verified=False, error=_COSIGN_NOT_FOUND_MSG)

    sig_path = archive_path.with_suffix(archive_path.suffix + ".sig")
    cert_path = archive_path.with_suffix(archive_path.suffix + ".cert")

    if not sig_path.exists():
        return VerifyResult(verified=False, error="No signature file found (.sig)")

    if key_path:
        # Key-based verification
        cmd = [
            str(cosign),
            "verify-blob",
            "--key", str(key_path),
            "--signature", str(sig_path),
            str(archive_path),
        ]
    else:
        # Keyless verification (requires certificate)
        if not cert_path.exists():
            return VerifyResult(
                verified=False,
                error="No certificate file found (.cert). Use --key for key-based verification.",
            )
        cmd = [
            str(cosign),
            "verify-blob",
            "--certificate", str(cert_path),
            "--certificate-identity-regexp", ".*",
            "--certificate-oidc-issuer-regexp", ".*",
            "--signature", str(sig_path),
            str(archive_path),
        ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return VerifyResult(verified=False, error="cosign verify timed out")
    except OSError as e:
        return VerifyResult(verified=False, error=f"Failed to run cosign: {e}")

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        return VerifyResult(verified=False, error=f"Verification failed: {error_msg}")

    signer_identity = ""
    if cert_path.exists():
        signer_identity = _extract_signer_from_cert(cert_path)

    return VerifyResult(verified=True, signer_identity=signer_identity)


def _extract_signer_from_cert(cert_path: Path) -> str:
    """Try to extract the signer identity from a Sigstore certificate."""
    try:
        # Use openssl to extract the SAN from the cert
        result = subprocess.run(
            ["openssl", "x509", "-in", str(cert_path), "-noout", "-ext", "subjectAltName"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            # Parse out the email from SAN
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("email:"):
                    return line.replace("email:", "").strip()
                if line.startswith("URI:"):
                    return line.replace("URI:", "").strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""
