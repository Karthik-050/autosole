import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from backend.workspace.manager import WorkspaceManager


class TestZipImportSecurity(unittest.TestCase):
    def test_zip_import_rejects_parent_traversal(self):
        manager = WorkspaceManager()
        with tempfile.TemporaryDirectory(dir=manager.base_dir) as temp_dir:
            temp_path = Path(temp_dir)
            archive_path = temp_path / "unsafe.zip"
            escaped_path = manager.base_dir / "escaped-by-zip-import.txt"
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("../escaped-by-zip-import.txt", "should not be written")

            with self.assertRaises(ValueError):
                manager.import_from_zip(archive_path)

            self.assertFalse(escaped_path.exists())

            # Backslashes are path separators on Windows and must be checked too.
            with ZipFile(archive_path, "w") as archive:
                archive.writestr(r"..\escaped-by-zip-import.txt", "should not be written")

            with self.assertRaises(ValueError):
                manager.import_from_zip(archive_path)

            self.assertFalse(escaped_path.exists())


if __name__ == "__main__":
    unittest.main()
