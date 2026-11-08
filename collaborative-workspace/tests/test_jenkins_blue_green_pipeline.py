import unittest

from backend.jenkins.manager import generate_repository_pipeline


class TestJenkinsBlueGreenPipeline(unittest.TestCase):
    def test_pipeline_checks_out_builds_health_checks_then_switches_proxy(self):
        script = generate_repository_pipeline(
            project_id="c4b8a6e4-8ae3-4e75-9dc4-project",
            repository_url="https://github.com/example/service.git",
            branch="main",
            project_type="python",
            entrypoint="app.py",
            container_port=5000,
        )

        self.assertIn("disableConcurrentBuilds()", script)
        self.assertIn("https://github.com/example/service.git", script)
        self.assertIn("*/${env.SOURCE_BRANCH}", script)
        self.assertIn("docker build -t", script)
        self.assertIn("Candidate failed its HTTP health check", script)
        self.assertIn("nginx -s reload", script)
        self.assertIn("server_name ${PROJECT_SLUG}.localhost", script)
        self.assertLess(script.index("Candidate failed its HTTP health check"), script.index("server_name ${PROJECT_SLUG}.localhost"))
        self.assertLess(script.rindex("nginx -s reload"), script.index("docker stop --time 120"))
        self.assertNotIn("@@", script)

    def test_private_checkout_uses_configured_jenkins_credential_id(self):
        script = generate_repository_pipeline(
            project_id="repo-1",
            repository_url="https://github.com/example/private.git",
            branch="release/1.0",
            project_type="node",
            container_port=3000,
            credentials_id="project-k-github",
        )

        self.assertIn("GITHUB_CREDENTIALS_ID = 'project-k-github'", script)
        self.assertIn("remote.credentialsId = env.GITHUB_CREDENTIALS_ID", script)


if __name__ == "__main__":
    unittest.main()
