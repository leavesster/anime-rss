import ast
from pathlib import Path


def test_modules_only_import_another_modules_public_api() -> None:
    modules_root = Path(__file__).resolve().parents[2] / "src" / "anime_rss" / "modules"
    violations: list[str] = []

    for source_path in modules_root.glob("*/*.py"):
        owner = source_path.parent.name
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            parts = node.module.split(".")
            if len(parts) < 4 or parts[:2] != ["anime_rss", "modules"]:
                continue
            imported_module = parts[2]
            imported_surface = parts[3]
            if imported_module != owner and imported_surface != "api":
                violations.append(f"{source_path.name}: {node.module}")

    assert violations == []


def test_every_module_has_a_boundary_readme() -> None:
    modules_root = Path(__file__).resolve().parents[2] / "src" / "anime_rss" / "modules"
    missing = [
        path.name
        for path in modules_root.iterdir()
        if path.is_dir() and not path.name.startswith("__") and not (path / "README.md").exists()
    ]

    assert missing == []
