"""Own real station settings and stable credentials without editing application files.

Depends on Pydantic, private Store state, and optional existing dotenv files.
Legacy service switches are removed; every catalog application is mandatory.
"""
import base64
from pathlib import Path
import secrets
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SECRET_FIELDS = {"github_token", "nvr_password"}
RETIRED_FIELDS = {"profile", "lighting_enabled", "interior_enabled", "ocr_enabled", "scraper_enabled"}


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_port: int = Field(default=8180, ge=1024, le=65535)
    api_port: int = Field(default=8181, ge=1024, le=65535)
    github_token: str = ""
    nvr_host: str = ""
    nvr_user: str = "admin"
    nvr_password: str = ""
    camera_channels: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14])
    serial_device: str = "auto"
    interior_url: str = ""
    interior_switch_id: int = Field(default=0, ge=0)
    data_directory: str = ""
    dataset_paths: list[str] = Field(default_factory=list)
    native_environment: dict[str, dict[str, str]] = Field(default_factory=dict, repr=False)

    @field_validator("github_token")
    @classmethod
    def validate_token(cls, value):
        value = value.strip()
        if len(value) > 4096 or any(character.isspace() for character in value):
            raise ValueError("Enter a GitHub token without embedded whitespace.")
        return value

    @field_validator("camera_channels")
    @classmethod
    def validate_channels(cls, value):
        if len(set(value)) != len(value) or any(channel < 1 or channel > 256 for channel in value):
            raise ValueError("Camera channels must be unique numbers between 1 and 256.")
        if not {4, 13, 14, 10}.issubset(value):
            raise ValueError("Configure the station's essential channels 4, 13, 14, and 10.")
        return value

    @field_validator("serial_device")
    @classmethod
    def validate_device(cls, value):
        if value not in ("", "auto") and not value.startswith("/dev/"):
            raise ValueError("Select auto or a stable device path under /dev/.")
        return value or "auto"

    @field_validator("data_directory")
    @classmethod
    def validate_storage(cls, value):
        if value and not Path(value).is_absolute():
            raise ValueError("The data directory must be an absolute path.")
        return value

    @field_validator("dataset_paths")
    @classmethod
    def validate_datasets(cls, value):
        for item in value:
            path = Path(item)
            if not path.is_absolute() or not path.exists() or (path.is_file() and path.suffix.lower() not in (".json", ".zip")):
                raise ValueError("Select existing absolute JSON, ZIP, or dataset directory paths.")
        return value

    @model_validator(mode="after")
    def validate_station(self):
        if self.app_port == self.api_port:
            raise ValueError("Application and API ports must be different.")
        if self.nvr_host and any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:" for c in self.nvr_host):
            raise ValueError("Enter an NVR hostname or IP address.")
        if self.interior_url:
            address = urlsplit(self.interior_url)
            if address.scheme not in ("http", "https") or not address.hostname or address.username or address.password or address.query or address.fragment or address.path not in ("", "/"):
                raise ValueError("Enter a direct Shelly HTTP address.")
        return self

    def require_installation_settings(self):
        missing = [label for label, value in (("NVR address", self.nvr_host), ("NVR account", self.nvr_user),
                    ("NVR password", self.nvr_password), ("Shelly address", self.interior_url)) if not value]
        if missing:
            raise ValueError("Complete station configuration: " + ", ".join(missing))


def data_root(root, config):
    return Path(config.data_directory).resolve() if config.data_directory else Path(root) / "data"


class Configuration:
    def __init__(self, store):
        self.store = store

    def load(self):
        values = self.store.read("configuration", {})
        return SiteConfig.model_construct(**{key: value for key, value in values.items() if key not in RETIRED_FIELDS})

    def save(self, changes):
        current = self.load().model_dump()
        for key in SECRET_FIELDS:
            if changes.get(key) in (None, ""):
                changes.pop(key, None)
        config = SiteConfig.model_validate({**current, **changes})
        installed = self.store.read("installed-configuration", {})
        if installed and config.data_directory != installed.get("data_directory", ""):
            raise ValueError("Moving installed station data requires an explicit data migration.")
        self.store.write("configuration", config.model_dump())
        return config

    def public(self):
        result = self.load().model_dump()
        environments = result.pop("native_environment")
        result["imported_setting_count"] = sum(len(values) for values in environments.values())
        for key in SECRET_FIELDS:
            result[key + "_configured"] = bool(result.pop(key))
        return result

    def ensure_credentials(self):
        values = self.store.read("credentials", {})
        for key in ("db_password", "db_root_password", "camera_key", "ocr_token", "gateway_key"):
            values.setdefault(key, secrets.token_urlsafe(36))
        values.setdefault("app_key", "base64:" + base64.b64encode(secrets.token_bytes(32)).decode())
        self.store.write("credentials", values)
        return values

    def import_existing(self, directory=None):
        from dotenv import dotenv_values
        roots = [Path(directory)] if directory else [Path.home() / "Desktop/CDMA/Cabek AI", Path.cwd().parent]
        if directory and not Path(directory).is_absolute():
            raise ValueError("Select an absolute existing Cabek directory.")
        changes = {}
        native = dict(self.load().native_environment)
        names = {"NVR_IP": "nvr_host", "RTSP_USER": "nvr_user", "RTSP_PASSWORD": "nvr_password",
                 "CABEK_INTERNAL_LIGHTS_URL": "interior_url", "CABEK_LIGHTS_PORT": "serial_device"}
        for root in roots:
            for component, relative in (("cameras", "Tiandy_CABEK_API/.env"), ("backend", "cabek_ai_global/.env"), ("lighting", "cabek-esp32/.env"), ("ocr", "Cabek-EConstat-OCR/.env")):
                path = root / relative
                if not path.is_file():
                    continue
                values = dotenv_values(path)
                prefixes = {"backend": ("CABEK_", "AUTOESTIMATE_"), "cameras": ("NVR_", "RTSP_", "CAMERA_", "PREVIEW_", "API_"),
                            "lighting": ("CABEK_LIGHTS_",), "ocr": ("ECONSTAT_", "EASYOCR_")}
                native[component] = {key: value for key, value in values.items() if value is not None and key.startswith(prefixes[component])}
                for external, field in names.items():
                    if values.get(external):
                        changes[field] = values[external]
                if values.get("CAMERA_CHANNELS"):
                    changes["camera_channels"] = [int(value.strip()) for value in values["CAMERA_CHANNELS"].split(",")]
                if values.get("CABEK_INTERNAL_LIGHTS_SWITCH_ID"):
                    changes["interior_switch_id"] = int(values["CABEK_INTERNAL_LIGHTS_SWITCH_ID"])
        if not changes:
            raise ValueError("No supported station configuration was found in that directory.")
        changes["native_environment"] = native
        self.save(changes)
        return self.public()
