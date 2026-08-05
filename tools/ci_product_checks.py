"""CI checks for product manifests and distribution boundaries.

The repository currently publishes one compatibility wheel.  Product
manifests make the intended future split explicit and these checks ensure
that each product can already be built without absorbing its siblings.

Usage::

    python tools/ci_product_checks.py manifests
    python tools/ci_product_checks.py wheels
    python tools/ci_product_checks.py clean
    python tools/ci_product_checks.py all
"""

from __future__ import annotations

import glob
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PRODUCTS = {
    "cds-text-sync": ROOT / "products/cds-text-sync/product.toml",
    "cds-static-analyzer": ROOT / "products/cds-static-analyzer/pyproject.toml",
    "cds-cli": ROOT / "products/cds-cli/pyproject.toml",
    "visu-lint": ROOT / "products/visu-lint/pyproject.toml",
    "codesys-host": ROOT / "products/codesys-host/deployment.toml",
}


def _load(path: Path) -> dict:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _test_paths(name: str, path: Path) -> list[str]:
    data = _load(path)
    section = data.get("tool", {}).get("cds_product") or data.get("product", {})
    paths = section.get("test_paths", [])
    if not paths:
        raise SystemExit(f"{name}: no test ownership declared in {path}")
    return paths


def check_manifests() -> None:
    for name, manifest in PRODUCTS.items():
        if not manifest.is_file():
            raise SystemExit(f"{name}: missing manifest {manifest}")
        for pattern in _test_paths(name, manifest):
            matches = list((manifest.parent / pattern).parent.glob(Path(pattern).name))
            if not matches:
                raise SystemExit(f"{name}: test ownership pattern matches nothing: {pattern}")
    print(f"product manifests OK: {len(PRODUCTS)} products have build/runtime and test ownership")


def _build(path: Path, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(path), "-w", str(output), "--no-deps", "--no-cache-dir", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode:
        raise SystemExit(f"wheel build failed for {path}: {proc.stderr[-1000:]}")
    wheels = glob.glob(str(output / "*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected one wheel for {path}, found {wheels}")
    return Path(wheels[0])


def _names(wheel: Path) -> list[str]:
    with zipfile.ZipFile(wheel) as archive:
        return archive.namelist()


def check_wheels() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        expected = {
            "cds-static-analyzer": "cds_static_analyzer/",
            "cds-cli": "cds_cli/",
            "visu-lint": "visu_lint/",
        }
        for name, prefix in expected.items():
            wheel = _build(PRODUCTS[name].parent, tmp_path / name)
            names = _names(wheel)
            if not any(item.startswith(prefix) for item in names):
                raise SystemExit(f"{name}: wheel does not contain {prefix}")
            sibling_prefixes = [value for key, value in expected.items() if key != name]
            leaked = [item for item in names if any(item.startswith(sibling) for sibling in sibling_prefixes)]
            if leaked:
                raise SystemExit(f"{name}: sibling runtime leaked into wheel: {leaked}")

        root_wheel = _build(ROOT, tmp_path / "root")
        names = _names(root_wheel)
        forbidden = [item for item in names if item.startswith(("products/", "tests/")) or item in {"spec.md"}]
        if forbidden:
            raise SystemExit(f"root compatibility wheel contains repository artifacts: {forbidden}")
        if any("codesys-host" in item or item.endswith("Project_build.py") for item in names):
            raise SystemExit("root compatibility wheel contains CODESYS host runtime files")
        print("product wheels OK: isolated product wheels and clean root compatibility wheel")


def check_clean_tree() -> None:
    proc = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    if proc.returncode:
        raise SystemExit(f"git status failed: {proc.stderr.strip()}")
    if proc.stdout.strip():
        raise SystemExit("clean-tree packaging check failed; commit or remove working-tree changes")
    print("clean-tree packaging check OK")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "all"
    if command in {"manifests", "all"}:
        check_manifests()
    if command in {"wheels", "all"}:
        check_wheels()
    if command in {"clean", "all"}:
        check_clean_tree()
    if command not in {"manifests", "wheels", "clean", "all"}:
        raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
