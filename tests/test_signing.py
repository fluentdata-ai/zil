"""Tests for cosign signing and verification (v0.1.11).

Cosign 3.x uses --bundle for signing/verification. The bundle is a single
JSON file containing the signature, certificate chain, and tlog entry.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from zil.packaging.signing import (
    _find_cosign,
    sign_archive,
    verify_archive,
)

# ---------------------------------------------------------------------------
# _find_cosign
# ---------------------------------------------------------------------------


class TestFindCosign:
    """Tests for cosign binary detection."""

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    def test_found(self, mock_which):
        result = _find_cosign()
        assert result == Path("/usr/local/bin/cosign")

    @patch("shutil.which", return_value=None)
    def test_not_found(self, mock_which):
        result = _find_cosign()
        assert result is None


def _fake_bundle() -> str:
    """Return a minimal Sigstore bundle JSON string."""
    return json.dumps({
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": {
            "x509CertificateChain": {
                "certificates": [{"rawBytes": "ZmFrZS1jZXJ0LWRhdGE="}]
            }
        },
        "messageSignature": {"signature": "ZmFrZS1zaWc="},
    })


# ---------------------------------------------------------------------------
# sign_archive
# ---------------------------------------------------------------------------


class TestSignArchive:
    """Tests for signing .zil archives."""

    @patch("shutil.which", return_value=None)
    def test_cosign_not_installed(self, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        result = sign_archive(archive)
        assert result.signed is False
        assert "not installed" in result.error

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_keyless_signing_success(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")

        bundle_path = archive.with_suffix(".zil.bundle")

        def side_effect(*args, **kwargs):
            bundle_path.write_text(_fake_bundle())
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            return mock_result

        mock_run.side_effect = side_effect

        result = sign_archive(archive)
        assert result.signed is True
        assert result.signature_type == "cosign-keyless"
        assert result.bundle_path == bundle_path

        # Verify cosign was called with --bundle and --yes (keyless)
        call_args = mock_run.call_args_list[0][0][0]
        assert "sign-blob" in call_args
        assert "--yes" in call_args
        assert "--bundle" in call_args

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_key_based_signing_success(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        key_file = tmp_path / "cosign.key"
        key_file.write_text("private-key")

        bundle_path = archive.with_suffix(".zil.bundle")

        def side_effect(*args, **kwargs):
            bundle_path.write_text(_fake_bundle())
            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        mock_run.side_effect = side_effect

        result = sign_archive(archive, key_path=key_file)
        assert result.signed is True
        assert result.signature_type == "cosign-key"

        # Verify cosign was called with --key and --bundle
        call_args = mock_run.call_args_list[0][0][0]
        assert "--key" in call_args
        assert "--bundle" in call_args

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_signing_failure(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: OIDC token expired"
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        result = sign_archive(archive)
        assert result.signed is False
        assert "OIDC token expired" in result.error

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_signing_timeout(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="cosign", timeout=120)

        result = sign_archive(archive)
        assert result.signed is False
        assert "timed out" in result.error

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_signing_no_bundle_produced(self, mock_run, mock_which, tmp_path):
        """Fails if cosign returns 0 but no bundle file was created."""
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        result = sign_archive(archive)
        assert result.signed is False
        assert "bundle" in result.error.lower()


# ---------------------------------------------------------------------------
# verify_archive
# ---------------------------------------------------------------------------


class TestVerifyArchive:
    """Tests for verifying .zil archive signatures."""

    @patch("shutil.which", return_value=None)
    def test_cosign_not_installed(self, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        result = verify_archive(archive)
        assert result.verified is False
        assert "not installed" in result.error

    def test_no_bundle_file(self, tmp_path):
        """Verify fails when .bundle file doesn't exist."""
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        with patch("shutil.which", return_value="/usr/local/bin/cosign"):
            result = verify_archive(archive)
        assert result.verified is False
        assert "No bundle file" in result.error

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_keyless_verification_success(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        bundle_path = archive.with_suffix(".zil.bundle")
        bundle_path.write_text(_fake_bundle())

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        result = verify_archive(archive)
        assert result.verified is True

        # Verify cosign called with --bundle and --new-bundle-format
        call_args = mock_run.call_args_list[0][0][0]
        assert "verify-blob" in call_args
        assert "--bundle" in call_args
        assert "--new-bundle-format" in call_args

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_key_based_verification_success(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        bundle_path = archive.with_suffix(".zil.bundle")
        bundle_path.write_text(_fake_bundle())
        key_file = tmp_path / "cosign.pub"
        key_file.write_text("public-key")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = verify_archive(archive, key_path=key_file)
        assert result.verified is True

        # First call is cosign verify-blob with --key
        call_args = mock_run.call_args_list[0][0][0]
        assert "--key" in call_args
        assert "--bundle" in call_args

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_verification_failure(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        bundle_path = archive.with_suffix(".zil.bundle")
        bundle_path.write_text(_fake_bundle())

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: invalid signature"
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        result = verify_archive(archive)
        assert result.verified is False
        assert "invalid signature" in result.error


# ---------------------------------------------------------------------------
# CLI integration — pack --sign
# ---------------------------------------------------------------------------


class TestPackSignCLI:
    """Test pack --sign CLI option wiring."""

    def test_pack_help_shows_sign_option(self):
        """Verify --sign and --key options are registered."""
        from click.testing import CliRunner

        from zil.commands.pack import pack

        runner = CliRunner()
        result = runner.invoke(pack, ["--help"])
        assert "--sign" in result.output
        assert "--key" in result.output

    def test_inspect_help_shows_verify_option(self):
        """Verify --verify and --key options are registered."""
        from click.testing import CliRunner

        from zil.commands.inspect import inspect

        runner = CliRunner()
        result = runner.invoke(inspect, ["--help"])
        assert "--verify" in result.output
        assert "--key" in result.output
