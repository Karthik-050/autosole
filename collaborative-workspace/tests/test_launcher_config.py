import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import run
from backend.config import Settings


class TestLauncherConfiguration(unittest.TestCase):
    def test_auto_reload_watches_backend_source_only(self):
        uvicorn = Mock()
        with patch.dict(sys.modules, {"uvicorn": uvicorn}):
            run.start_server(reload=True)

        args, options = uvicorn.run.call_args
        self.assertEqual(args, ("backend.main:app",))
        self.assertEqual(options["reload_dirs"], [str(run.WORKSPACE_DIR / "backend")])

    def test_disabled_reload_does_not_set_reload_directories(self):
        uvicorn = Mock()
        with patch.dict(sys.modules, {"uvicorn": uvicorn}):
            run.start_server(reload=False)

        options = uvicorn.run.call_args.kwargs
        self.assertFalse(options["reload"])
        self.assertNotIn("reload_dirs", options)

    def test_environment_defaults_and_cli_overrides(self):
        with patch.dict(os.environ, {"HOST": "0.0.0.0", "PORT": "8123"}, clear=False):
            args = run.build_parser().parse_args([])
            self.assertEqual(args.host, "0.0.0.0")
            self.assertEqual(args.port, 8123)

            overridden = run.build_parser().parse_args(["--host", "127.0.0.1", "--port", "9000"])
            self.assertEqual(overridden.host, "127.0.0.1")
            self.assertEqual(overridden.port, 9000)

    def test_workspace_settings_read_environment(self):
        with patch.dict(
            os.environ,
            {"JENKINS_URL": "http://jenkins.example:8080", "DEPLOY_PORT": "5123"},
            clear=False,
        ):
            settings = Settings()
            self.assertEqual(settings.jenkins_url, "http://jenkins.example:8080")
            self.assertEqual(settings.default_deploy_port, 5123)


if __name__ == "__main__":
    unittest.main()
