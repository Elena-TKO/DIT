"""Настройки приложения из переменных окружения."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(BASE_DIR / "runtime"))))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", ""))
    token_ttl_hours: int = field(default_factory=lambda: int(_env("TOKEN_TTL_HOURS", "72")))
    detector: str = field(default_factory=lambda: _env("DETECTOR", "ultralytics"))
    model_weights: str = field(default_factory=lambda: _env("MODEL_WEIGHTS", "yolov8s-worldv2.pt"))
    onnx_classes: str = field(default_factory=lambda: _env("ONNX_CLASSES", ""))
    detect_conf: float = field(default_factory=lambda: float(_env("DETECT_CONF", "0.25")))
    detect_imgsz: int = field(default_factory=lambda: int(_env("DETECT_IMGSZ", "1280")))
    device: str | None = field(default_factory=lambda: os.environ.get("DEVICE") or None)
    mock_annotations_dir: str | None = field(default_factory=lambda: os.environ.get("MOCK_ANNOTATIONS_DIR"))
    # Разрешить камеры на localhost: нужно для тестов и демостенда, в продакшене оставить 0
    detect_tiles: int = field(default_factory=lambda: int(_env("DETECT_TILES", "1")))
    allow_local_cameras: bool = field(default_factory=lambda: _env("ALLOW_LOCAL_CAMERAS", "0") == "1")
    cors_origins: list[str] = field(default_factory=lambda: [o.strip() for o in _env(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:8080").split(",") if o.strip()])
    camera_poll_seconds: int = field(default_factory=lambda: int(_env("CAMERA_POLL_SECONDS", "5")))
    max_upload_mb: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_MB", "25")))
    enable_poller: bool = field(default_factory=lambda: _env("ENABLE_CAMERA_POLLER", "1") == "1")

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "photos").mkdir(exist_ok=True)
        (self.data_dir / "emulator").mkdir(exist_ok=True)
        if not self.secret_key:
            # Ключ сохраняется, чтобы токены переживали перезапуск
            key_file = self.data_dir / ".secret_key"
            if not key_file.exists():
                key_file.write_text(secrets.token_hex(32))
            self.secret_key = key_file.read_text().strip()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "stroykontrol.sqlite3"

    @property
    def photos_dir(self) -> Path:
        return self.data_dir / "photos"

    @property
    def emulator_dir(self) -> Path:
        return self.data_dir / "emulator"
