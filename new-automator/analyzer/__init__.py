"""Automator Stack and Project Analyzer Package."""

from .detector import DetectionResult, detect_project, inspect_existing_dockerfile

__all__ = ["DetectionResult", "detect_project", "inspect_existing_dockerfile"]
