import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_data_path


@dataclass
class Config:
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("RESUME_MAKER_DATA_DIR", user_data_path("ResumeMaker", appauthor=False))
        )
    )
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    port: int = 8765
    frontend: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[2] / "frontend" / "dist"
    )

    def prepare(self) -> None:
        self.data_dir = self.data_dir.resolve()
        for name in ("snapshots", "workspaces", "templates", "exports", "backups"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
