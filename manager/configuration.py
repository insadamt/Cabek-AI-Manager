"""Validate site settings and generate stable installation credentials once.

Depends on Pydantic DTOs and the private Store. Unchanged secrets survive setup,
restarts, and updates; public responses contain only configured indicators.
"""
import base64
import ipaddress
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SECRET_FIELDS = {"github_token", "nvr_password"}


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str = "demo"
    app_port: int = Field(default=8180, ge=1024, le=65535)
    api_port: int = Field(default=8181, ge=1024, le=65535)
    github_token: str = ""
    nvr_host: str = ""
    nvr_user: str = "admin"
    nvr_password: str = ""
    camera_channels: list[int] = Field(default_factory=lambda: [1, 2, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14])
    lighting_enabled: bool = False
    serial_device: str = ""
    interior_enabled: bool = False
    interior_url: str = ""
    interior_switch_id: int = Field(default=0, ge=0)
    ocr_enabled: bool = True
    dataset_paths: list[str] = Field(default_factory=list)

    @field_validator("camera_channels")
    @classmethod
    def validate_channels(cls, value):
        if not value or len(value) != len(set(value)) or any(ch < 1 or ch > 256 for ch in value):
            raise ValueError("Camera channels must be unique numbers between 1 and 256.")
        return value

    @field_validator("dataset_paths")
    @classmethod
    def validate_dataset_paths(cls, value):
        for item in value:
            path = Path(item)
            if not path.is_absolute() or not path.exists() or (path.is_file() and path.suffix.lower() not in (".zip", ".json")):
                raise ValueError("Select an existing absolute JSON, ZIP, or dataset directory path.")
        return value

    @model_validator(mode="after")
    def validate_site(self):
        if self.profile not in ("demo", "station"):
            raise ValueError("Select demo or station.")
        if self.app_port == self.api_port:
            raise ValueError("Application and API ports must be different.")
        if self.profile == "station":
            if not self.nvr_host or not self.nvr_password:
                raise ValueError("Station setup requires the NVR address and password.")
            if not {4, 13, 14, 10}.issubset(self.camera_channels):
                raise ValueError("Station capture requires channels 4, 13, 14, and 10.")
            try:
                ipaddress.ip_address(self.nvr_host)
            except ValueError:
                if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for char in self.nvr_host):
                    raise ValueError("Enter an NVR IP address or hostname.") from None
        if self.lighting_enabled:
            path = Path(self.serial_device)
            if not path.is_absolute() or not str(path).startswith("/dev/") or not path.exists():
                raise ValueError("Select the connected ESP32 device under /dev/.")
        if self.interior_enabled:
            parsed = urlsplit(self.interior_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
                raise ValueError("Enter a direct Shelly HTTP address.")
        return self


class Configuration:
    def __init__(self, store):
        self.store = store

    def load(self):
        # Hardware can disappear after saving; keep setup accessible to repair its configuration.
        saved = self.store.read("configuration", {})
        saved.pop("scraper_enabled", None)
        return SiteConfig.model_construct(**saved)

    def save(self, changes):
        current = self.store.read("configuration", {})
        current.pop("scraper_enabled", None)
        for key in SECRET_FIELDS:
            if changes.get(key) in (None, "") and key in current:
                changes.pop(key, None)
        config = SiteConfig.model_validate({**current, **changes})
        self.store.write("configuration", config.model_dump())
        return config

    def public(self):
        result = self.load().model_dump()
        for key in SECRET_FIELDS:
            result[key + "_configured"] = bool(result.pop(key))
        return result

    def credentials(self):
        values = self.store.read("credentials", {})
        for key in ("db_password", "db_root_password", "camera_key", "ocr_token", "manager_key", "autoestimate_token"):
            values.setdefault(key, secrets.token_urlsafe(36))
        values.setdefault("app_key", "base64:" + base64.b64encode(secrets.token_bytes(32)).decode())
        self.store.write("credentials", values)
        return values
