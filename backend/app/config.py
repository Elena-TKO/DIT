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
    detect_tiles: int = field(default_factory=lambda: int(_env("DETECT_TILES", "1")))
    cors_origins: list[str] = field(default_factory=lambda: [o.strip() for o in _env(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:8080").split(",") if o.strip()])
    max_upload_mb: int = field(default_factory=lambda: int(_env("MAX_UPLOAD_MB", "25")))
    # Карта строек: auto — Яндекс (если есть ключ), затем Nominatim, затем встроенный справочник; off — только справочник
    geocoder: str = field(default_factory=lambda: _env("GEOCODER", "auto"))
    yandex_geocoder_key: str = field(default_factory=lambda: _env("YANDEX_GEOCODER_KEY", ""))
    nominatim_url: str = field(default_factory=lambda: _env("NOMINATIM_URL", "https://nominatim.openstreetmap.org"))
    geocoder_timeout: float = field(default_factory=lambda: float(_env("GEOCODER_TIMEOUT", "4")))
    # Помощник (бета): задержка между фрагментами ответа при потоковой выдаче, секунды
    assistant_stream_delay: float = field(default_factory=lambda: float(_env("ASSISTANT_STREAM_DELAY", "0.025")))

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "photos").mkdir(exist_ok=True)
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