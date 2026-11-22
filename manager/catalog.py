"""Define the supported repositories and runtime roles for a Cabek installation.

Depends on Manager-owned deployment recipes. The pricing frontend and legacy
Streamlit application are deliberately outside the managed ecosystem.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Component:
    key: str
    repository: str
    name: str


COMPONENTS = (
    Component("manager", "insadamt/Cabek-AI-Manager", "Cabek AI Manager"),
    Component("backend", "insadamt/Cabek-AI-Backend", "Cabek AI API"),
    Component("frontend", "insadamt/Cabek-AI-Frontend", "Cabek AI interface"),
    Component("autoestimate", "insadamt/Cabek-Autoestimate-Backend", "AutoEstimate pricing"),
    Component("cameras", "insadamt/Cabek-AI-Cam", "Tiandy cameras"),
    Component("lighting", "insadamt/Cabek-Capture-Lights", "ESP32 lighting"),
    Component("ocr", "insadamt/Cabek-EConstat-OCR", "E-Constat OCR"),
)


def enabled_components(config=None):
    return list(COMPONENTS)
