from pathlib import Path

from anime_rss.config import Settings
from anime_rss.main import create_app
from fastapi.testclient import TestClient


def test_built_web_app_is_served_without_shadowing_api(tmp_path: Path) -> None:
    web_dist = tmp_path / "web"
    assets = web_dist / "assets"
    assets.mkdir(parents=True)
    (web_dist / "index.html").write_text("<main>Anime RSS UI</main>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ready')", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", web_dist_dir=web_dist)

    with TestClient(create_app(settings)) as client:
        assert client.get("/").text == "<main>Anime RSS UI</main>"
        assert client.get("/feeds/example").text == "<main>Anime RSS UI</main>"
        assert client.get("/assets/app.js").text == "console.log('ready')"
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/api/v1/health/ready").json() == {"status": "ready"}
