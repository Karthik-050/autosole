import tempfile
from pathlib import Path

from automation.project_detect import ProjectDetector

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    assert ProjectDetector(root).detect() == "unknown"

    (root / "requirements.txt").write_text("fastapi\n")
    assert ProjectDetector(root).detect() == "python"

    (root / "requirements.txt").unlink()
    (root / "package.json").write_text("{}\n")
    assert ProjectDetector(root).detect() == "node"

    (root / "package.json").unlink()
    (root / "pom.xml").write_text("<project/>\n")
    assert ProjectDetector(root).detect() == "java"

print("project_detect: all checks passed")
