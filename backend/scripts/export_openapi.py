import json
from pathlib import Path

from anime_rss.main import create_app


def main() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    output = repository_root / "web" / "src" / "generated" / "api" / "openapi.json"
    output.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
