"""Define the supported repositories and runtime roles for a Cabek installation.

Depends on repository-owned Dockerfiles. The pricing frontend and legacy
Streamlit application are deliberately outside the managed ecosystem.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Component:
    key: str
    repository: str
    name: str
    optional: bool = False


COMPONENTS = (
    Component("manager", "insadamt/Cabek-AI-Manager", "Cabek AI Manager"),
    Component("backend", "insadamt/Cabek-AI-Backend", "Cabek AI API"),
    Component("frontend", "insadamt/Cabek-AI-Frontend", "Cabek AI interface"),
    Component("autoestimate", "insadamt/Cabek-Autoestimate-Backend", "AutoEstimate pricing"),
    Component("cameras", "insadamt/Cabek-AI-Cam", "Tiandy cameras", True),
    Component("lighting", "insadamt/Cabek-Capture-Lights", "ESP32 lighting", True),
    Component("ocr", "insadamt/Cabek-EConstat-OCR", "E-Constat OCR", True),
)


def enabled_components(config):
    keys = {"manager", "backend", "frontend", "autoestimate"}
    if config.ocr_enabled:
        keys.add("ocr")
    if config.profile == "station":
        keys.add("cameras")
    if config.lighting_enabled:
        keys.add("lighting")
    return [component for component in COMPONENTS if component.key in keys]
