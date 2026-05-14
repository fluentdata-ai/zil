"""Cosign-based signing and verification for .zil archives.

Cosign 3.x uses the --bundle flag which produces a single JSON file
containing the signature, certificate chain, and transparency log entry.
This replaces the deprecated --output-signature / --output-certificate flags.
"""

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
)


@dataclass
class SignResult:
    """Result of signing an archive."""

    signed: bool
    bundle_path: Path | None = None
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
        SignResult with path to the .bundle file.
    """
    cosign = _find_cosign()
    if cosign is None:
        return SignResult(signed=False, error=_COSIGN_NOT_FOUND_MSG)

    bundle_path = archive_path.with_suffix(archive_path.suffix + ".bundle")

    if key_path:
        # Key-based signing
        cmd = [
            str(cosign),
            "sign-blob",
            "--key", str(key_path),
            "--bundle", str(bundle_path),
            "--tlog-upload=false",
            "--yes",
            str(archive_path),
        ]
        signature_type = "cosign-key"
    else:
        # Keyless (OIDC) signing via Sigstore
        cmd = [
            str(cosign),
            "sign-blob",
            "--yes",
            "--bundle", str(bundle_path),
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

    if not bundle_path.exists():
        return SignResult(signed=False, error="cosign did not produce a bundle file")

    # Extract signer identity from bundle certificate
    signer_identity = _extract_signer_from_bundle(bundle_path)

    return SignResult(
        signed=True,
        bundle_path=bundle_path,
        signature_type=signature_type,
        signer_identity=signer_identity,
    )


def verify_archive(
    archive_path: Path,
    *,
    key_path: Path | None = None,
) -> VerifyResult:
    """Verify a signed .zil archive using cosign.

    Looks for a .bundle file alongside the archive.

    Args:
        archive_path: Path to the .zil archive.
        key_path: Optional path to the cosign public key.

    Returns:
        VerifyResult indicating whether verification passed.
    """
    cosign = _find_cosign()
    if cosign is None:
        return VerifyResult(verified=False, error=_COSIGN_NOT_FOUND_MSG)

    bundle_path = archive_path.with_suffix(archive_path.suffix + ".bundle")

    if not bundle_path.exists():
        return VerifyResult(
            verified=False,
            error="No bundle file found (.bundle). Sign the archive first with: zil pack --sign",
        )

    if key_path:
        # Key-based verification
        cmd = [
            str(cosign),
            "verify-blob",
            "--key", str(key_path),
            "--bundle", str(bundle_path),
            "--new-bundle-format",
            str(archive_path),
        ]
    else:
        # Keyless verification via bundle (includes cert + tlog entry)
        cmd = [
            str(cosign),
            "verify-blob",
            "--bundle", str(bundle_path),
            "--new-bundle-format",
            "--certificate-identity-regexp", ".*",
            "--certificate-oidc-issuer-regexp", ".*",
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

    signer_identity = _extract_signer_from_bundle(bundle_path)

    return VerifyResult(verified=True, signer_identity=signer_identity)


def _extract_signer_from_bundle(bundle_path: Path) -> str:
    """Try to extract the signer identity from a Sigstore bundle."""
    try:
        bundle = json.loads(bundle_path.read_text())

        # Sigstore bundle format: verificationMaterial.x509CertificateChain.certificates[0].rawBytes
        certs = (
            bundle.get("verificationMaterial", {})
            .get("x509CertificateChain", {})
            .get("certificates", [])
        )
        if not certs:
            return ""

        # Decode the leaf certificate and extract SAN via openssl
        cert_b64 = certs[0].get("rawBytes", "")
        if not cert_b64:
            return ""

        pem = (
            "-----BEGIN CERTIFICATE-----\n"
            + cert_b64
            + "\n-----END CERTIFICATE-----\n"
        )
        result = subprocess.run(
            ["openssl", "x509", "-noout", "-ext", "subjectAltName"],
            input=pem,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("email:"):
                    return line.replace("email:", "").strip()
                if line.startswith("URI:"):
                    return line.replace("URI:", "").strip()
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        pass
    return ""
