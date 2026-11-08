"""Automator CI/CD Configuration and Settings Module.

Provides centralized configuration loaded from environment variables and defaults,
managing directories, ports, network settings, and timeouts.
"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import secrets
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables and defaults."""

    # Base paths
    BASE_DIR: Path = Path(__file__).resolve().parent
    PROJECTS_DIR: Optional[Path] = Field(default=None)
    BUILDS_DIR: Optional[Path] = Field(default=None)
    LOGS_DIR: Optional[Path] = Field(default=None)
    REPOS_DIR: Optional[Path] = Field(default=None)
    DB_PATH: Optional[Path] = Field(default=None)

    # Server Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # Jenkins Controller Configuration
    JENKINS_URL: str = "http://localhost:8080"
    JENKINS_USERNAME: str = ""
    JENKINS_API_TOKEN: str = ""
    JENKINS_JOB_NAME: str = "automator-deploy"
    JENKINS_CONTAINER: str = "jenkins"
    JENKINS_DOCKER_CONTAINER: str = "jenkins-docker"
    JENKINS_NETWORK: str = "jenkins"
    JENKINS_RETRY_ATTEMPTS: int = 30
    JENKINS_RETRY_INTERVAL: int = 2
    JENKINS_TIMEOUT: int = 60

    # Docker Engine Configuration
    DOCKER_HOST: Optional[str] = None
    DOCKER_REGISTRY: str = ""
    DEFAULT_CONTAINER_PORT: int = 5000
    DEFAULT_HOST_PORT: int = 5001
    # Keep the temporary Jenkins candidate port separate from the Project K
    # deployment proxy, which publishes host port 5002.
    CANDIDATE_HOST_PORT: int = 5003
    DOCKER_BUILD_TIMEOUT: int = 600
    DOCKER_DAEMON_TIMEOUT: int = 60

    # Git & GitHub Configuration
    GITHUB_WEBHOOK_SECRET: str = Field(default_factory=lambda: secrets.token_hex(32))
    GITHUB_API_TOKEN: str = ""
    COLLABORATIVE_WORKSPACE_WEBHOOK_URL: str = "http://127.0.0.1:8000/api/webhooks/github"
    GIT_TIMEOUT: int = 300
    ALLOWED_GIT_PROVIDERS: List[str] = ["github.com", "gitlab.com", "bitbucket.org"]

    # Security & General Settings
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_hex(32))
    HEALTH_CHECK_TIMEOUT: int = 120
    MAX_CONCURRENT_BUILDS: int = 3
    BUILD_RETENTION_COUNT: int = 20
    IMAGE_RETENTION_COUNT: int = 10

    model_config = {
        "env_prefix": "AUTOMATOR_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def model_post_init(self, __context: object) -> None:
        """Set default paths relative to BASE_DIR and ensure necessary directories exist."""
        if self.PROJECTS_DIR is None:
            self.PROJECTS_DIR = self.BASE_DIR / "projects"
        if self.BUILDS_DIR is None:
            self.BUILDS_DIR = self.BASE_DIR / "builds"
        if self.LOGS_DIR is None:
            self.LOGS_DIR = self.BASE_DIR / "logs"
        if self.REPOS_DIR is None:
            self.REPOS_DIR = self.BASE_DIR / "repos"
        if self.DB_PATH is None:
            self.DB_PATH = self.BASE_DIR / "automator.db"

        # Resolve paths to absolute
        self.PROJECTS_DIR = self.PROJECTS_DIR.resolve()
        self.BUILDS_DIR = self.BUILDS_DIR.resolve()
        self.LOGS_DIR = self.LOGS_DIR.resolve()
        self.REPOS_DIR = self.REPOS_DIR.resolve()
        self.DB_PATH = self.DB_PATH.resolve()

        # Ensure directories exist
        for d in [self.PROJECTS_DIR, self.BUILDS_DIR, self.LOGS_DIR, self.REPOS_DIR]:
            d.mkdir(parents=True, exist_ok=True)


@lru_cache()
def get_settings() -> Settings:
    """Get cached application settings singleton."""
    return Settings()
