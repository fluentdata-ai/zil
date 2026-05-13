"""Tests for cosign signing and verification (v0.1.11)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from zil.packaging.signing import (
    SignResult,
    VerifyResult,
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

        # Create the expected output files
        sig_path = archive.with_suffix(".zil.sig")
        cert_path = archive.with_suffix(".zil.cert")

        def side_effect(*args, **kwargs):
            sig_path.write_text("signature-data")
            cert_path.write_text("cert-data")
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            return mock_result

        mock_run.side_effect = side_effect

        result = sign_archive(archive)
        assert result.signed is True
        assert result.signature_type == "cosign-keyless"
        assert result.signature_path == sig_path

        # Verify cosign was called with --yes (keyless) — first call is cosign
        call_args = mock_run.call_args_list[0][0][0]
        assert "sign-blob" in call_args
        assert "--yes" in call_args

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_key_based_signing_success(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        key_file = tmp_path / "cosign.key"
        key_file.write_text("private-key")

        sig_path = archive.with_suffix(".zil.sig")

        def side_effect(*args, **kwargs):
            sig_path.write_text("signature-data")
            mock_result = MagicMock()
            mock_result.returncode = 0
            return mock_result

        mock_run.side_effect = side_effect

        result = sign_archive(archive, key_path=key_file)
        assert result.signed is True
        assert result.signature_type == "cosign-key"

        # Verify cosign was called with --key — first call is cosign
        call_args = mock_run.call_args_list[0][0][0]
        assert "--key" in call_args

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

    def test_no_signature_file(self, tmp_path):
        """Verify fails when .sig file doesn't exist."""
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        # Don't mock _find_cosign — just patch which to return something
        with patch("shutil.which", return_value="/usr/local/bin/cosign"):
            result = verify_archive(archive)
        assert result.verified is False
        assert "No signature file" in result.error

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    def test_no_cert_for_keyless(self, mock_which, tmp_path):
        """Keyless verify fails when .cert doesn't exist."""
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        sig_path = archive.with_suffix(".zil.sig")
        sig_path.write_text("sig-data")
        # No .cert file

        result = verify_archive(archive)
        assert result.verified is False
        assert "No certificate file" in result.error

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_keyless_verification_success(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        sig_path = archive.with_suffix(".zil.sig")
        sig_path.write_text("sig-data")
        cert_path = archive.with_suffix(".zil.cert")
        cert_path.write_text("cert-data")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        result = verify_archive(archive)
        assert result.verified is True

        # Verify cosign called with --certificate — first call is verify-blob
        call_args = mock_run.call_args_list[0][0][0]
        assert "verify-blob" in call_args
        assert "--certificate" in call_args

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_key_based_verification_success(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        sig_path = archive.with_suffix(".zil.sig")
        sig_path.write_text("sig-data")
        key_file = tmp_path / "cosign.pub"
        key_file.write_text("public-key")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        result = verify_archive(archive, key_path=key_file)
        assert result.verified is True

        # First call is cosign verify-blob
        call_args = mock_run.call_args_list[0][0][0]
        assert "--key" in call_args

    @patch("shutil.which", return_value="/usr/local/bin/cosign")
    @patch("subprocess.run")
    def test_verification_failure(self, mock_run, mock_which, tmp_path):
        archive = tmp_path / "test-0.1.0.zil"
        archive.write_bytes(b"fake archive")
        sig_path = archive.with_suffix(".zil.sig")
        sig_path.write_text("sig-data")
        cert_path = archive.with_suffix(".zil.cert")
        cert_path.write_text("cert-data")

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
