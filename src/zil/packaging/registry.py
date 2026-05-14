"""OCI registry operations for .zil archives using oras-py."""

from __future__ import annotations

from pathlib import Path

import yaml


def push_archive(archive_path: Path, registry: str) -> str:
    """Push a .zil archive to an OCI registry.

    Args:
        archive_path: Path to the .zil file.
        registry: Registry URL (e.g. us-docker.pkg.dev/my-project/agents).

    Returns:
        The full reference string (registry/name:version).
    """
    try:
        import oras.client
    except ImportError as e:
        raise ImportError(
            "oras is required for registry operations. "
            "Install with: pip install 'zil-ai[registry]'"
        ) from e

    # Extract name/version from archive metadata
    import tarfile

    with tarfile.open(archive_path, "r:gz") as tar:
        manifest_file = tar.extractfile(tar.getmember("manifest.yaml"))
        if manifest_file is None:
            raise ValueError("Cannot read manifest.yaml from archive")
        manifest = yaml.safe_load(manifest_file.read())

    name = manifest["metadata"]["name"]
    version = manifest["metadata"]["version"]

    # Build the target reference
    registry = registry.rstrip("/")
    # Remove oci:// prefix if present
    if registry.startswith("oci://"):
        registry = registry[6:]
    target = f"{registry}/{name}:{version}"

    # Push using oras
    client = oras.client.OrasClient()
    client.push(
        target=target,
        files=[str(archive_path)],
        manifest_annotations={
            "org.opencontainers.image.title": name,
            "org.opencontainers.image.version": version,
            "dev.getzil.type": "agent-package",
        },
        disable_path_validation=True,
    )

    return target


def push_signature(
    bundle_path: Path,
    artifact_reference: str,
) -> str:
    """Push cosign bundle as a referrer to the OCI artifact.

    Args:
        bundle_path: Path to the .bundle file.
        artifact_reference: The OCI reference of the signed artifact.

    Returns:
        The reference string for the signature artifact.
    """
    try:
        import oras.client
    except ImportError as e:
        raise ImportError(
            "oras is required for registry operations. "
            "Install with: pip install 'zil-ai[registry]'"
        ) from e

    # Push bundle as a separate artifact tagged with -sig suffix
    sig_target = artifact_reference.replace(":", "-sig:")
    if ":" not in sig_target:
        sig_target = f"{artifact_reference}-sig"

    client = oras.client.OrasClient()
    client.push(
        target=sig_target,
        files=[str(bundle_path)],
        manifest_annotations={
            "dev.getzil.type": "agent-signature",
            "dev.getzil.signed-artifact": artifact_reference,
        },
        disable_path_validation=True,
    )

    return sig_target


def pull_archive(reference: str, output_dir: Path) -> Path:
    """Pull a .zil archive from an OCI registry.

    Args:
        reference: Full registry reference (registry/name:version).
        output_dir: Directory to write the pulled file to.

    Returns:
        Path to the pulled .zil file.
    """
    try:
        import oras.client
    except ImportError as e:
        raise ImportError(
            "oras is required for registry operations. "
            "Install with: pip install 'zil-ai[registry]'"
        ) from e

    # Remove oci:// prefix if present
    if reference.startswith("oci://"):
        reference = reference[6:]

    output_dir.mkdir(parents=True, exist_ok=True)

    client = oras.client.OrasClient()
    files = client.pull(
        target=reference,
        outdir=str(output_dir),
    )

    # Find the .zil file in the pulled artifacts
    for f in files:
        if f.endswith(".zil"):
            return Path(f)

    # If no .zil extension, return the first file
    if files:
        return Path(files[0])

    raise FileNotFoundError(
        f"No artifacts pulled from {reference}"
    )
