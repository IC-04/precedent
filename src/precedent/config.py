"""Cloud configuration shared by every Gemini model initialization."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VertexSettings:
    project: str
    location: str = "global"

    @classmethod
    def from_env(cls) -> VertexSettings:
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        if not project or project == "your-project-id":
            raise ValueError(
                "Set GOOGLE_CLOUD_PROJECT to your billed Google Cloud project ID "
                "in .env or the environment. Gemini uses Vertex AI with ADC."
            )
        # All currently configured Gemini models support the global endpoint.
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip()
        if not location:
            raise ValueError(
                "GOOGLE_CLOUD_LOCATION must not be empty; use global or a supported region."
            )
        return cls(project=project, location=location)
