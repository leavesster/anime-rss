import os
from pathlib import Path

from starlette.staticfiles import StaticFiles


class SpaStaticFiles(StaticFiles):
    """Serve real assets normally and send extensionless routes to the SPA."""

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        full_path, stat_result = super().lookup_path(path)
        if stat_result is not None or Path(path).suffix:
            return full_path, stat_result
        return super().lookup_path("index.html")
