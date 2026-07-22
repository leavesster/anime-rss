import re
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_qbittorrent_contract_images_are_versioned_and_digest_pinned() -> None:
    script = (_root() / "scripts" / "acceptance-qbittorrent.sh").read_text(encoding="utf-8")
    images = re.findall(r'"(lscr\.io/linuxserver/qbittorrent:[^|]+)\|v[^\"]+"', script)

    assert len(images) == 2
    assert all(re.fullmatch(r".+:version-[^@]+@sha256:[0-9a-f]{64}", image) for image in images)


def test_container_base_images_are_multi_arch_digest_pinned() -> None:
    dockerfile = (_root() / "Dockerfile").read_text(encoding="utf-8")
    base_images = re.findall(r"^FROM ([^ ]+)", dockerfile, flags=re.MULTILINE)

    assert len(base_images) == 2
    assert all(re.fullmatch(r".+@sha256:[0-9a-f]{64}", image) for image in base_images)


def test_image_publication_is_gated_by_both_architectures_and_security_scan() -> None:
    workflow = (_root() / ".github" / "workflows" / "image.yml").read_text(encoding="utf-8")

    for required in (
        "value: linux/amd64",
        "value: linux/arm64",
        "make image-smoke",
        "aquasecurity/trivy-action@",
        "severity: HIGH,CRITICAL",
        "needs: smoke",
        "cosign sign --yes",
    ):
        assert required in workflow


def test_dependabot_covers_every_locked_delivery_ecosystem() -> None:
    configuration = (_root() / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    for ecosystem in ("pip", "npm", "docker", "github-actions"):
        assert f"package-ecosystem: {ecosystem}" in configuration
