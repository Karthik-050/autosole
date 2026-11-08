"""Automator Zero-Downtime Deployment and Preview Routing Module.

Provides candidate container lifecycle management, health verification,
dynamic traffic switching, rollback, and reverse-proxy routing.
"""

from .manager import (
    CandidateContainer,
    DeploymentManager,
    DeploymentResult,
    find_available_port,
)
from .proxy import proxy_preview_request

__all__ = [
    "CandidateContainer",
    "DeploymentManager",
    "DeploymentResult",
    "find_available_port",
    "proxy_preview_request",
]
