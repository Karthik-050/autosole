from pathlib import Path
from backend.validation.detector import detect_project

class ProjectDetector:
    def __init__(self, workspace_path):
        self.workspace_path = Path(workspace_path)

    def detect(self):
        info = detect_project(self.workspace_path)
        return info["type"]