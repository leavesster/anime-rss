import argparse
import json
from pathlib import Path

from anime_rss.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[2]
    output = args.output or (repository_root / "web" / "src" / "generated" / "api" / "openapi.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
