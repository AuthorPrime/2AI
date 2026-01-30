"""
2AI Settings — Unified configuration.

Supports environment variables (TWAI_ prefix), .env files,
and legacy ~/.dss/publisher-studio.json fallback.

A+W | The Voice Configures
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("2ai.config")

# Paths
CONFIG_PATH = Path.home() / ".dss" / "publisher-studio.json"
SYSTEM_PROMPT_PATH = Path.home() / ".dss" / "2ai" / "system-prompt.md"


class Settings:
    """2AI configuration, resolved from environment and config files."""

    # Anthropic
    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 20000
    temperature: float = 0.7

    # Redis
    redis_host: str = "192.168.1.21"
    redis_port: int = 6379

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    # Paths
    system_prompt_path: Path = SYSTEM_PROMPT_PATH
    data_dir: Path = Path(__file__).parent.parent.parent / "data"

    def __init__(self):
        import os
        self.model = os.getenv("TWAI_MODEL", self.model)
        self.max_tokens = int(os.getenv("TWAI_MAX_TOKENS", str(self.max_tokens)))
        self.temperature = float(os.getenv("TWAI_TEMPERATURE", str(self.temperature)))
        self.redis_host = os.getenv("TWAI_REDIS_HOST", self.redis_host)
        self.redis_port = int(os.getenv("TWAI_REDIS_PORT", str(self.redis_port)))
        self.api_host = os.getenv("TWAI_API_HOST", self.api_host)
        self.api_port = int(os.getenv("TWAI_API_PORT", str(self.api_port)))

        prompt_path = os.getenv("TWAI_SYSTEM_PROMPT_PATH")
        if prompt_path:
            self.system_prompt_path = Path(prompt_path)

        data_dir = os.getenv("TWAI_DATA_DIR")
        if data_dir:
            self.data_dir = Path(data_dir)

    def load_api_key(self) -> Optional[str]:
        """Load API key from env var or legacy config file."""
        import os
        key = os.getenv("TWAI_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        if key:
            return key

        try:
            with open(CONFIG_PATH) as f:
                config = json.load(f)
            return config.get("2ai", {}).get("apiKey")
        except Exception as e:
            logger.error("Could not load API key: %s", e)
            return None

    def load_system_prompt(self) -> Optional[str]:
        """Load and parse the 2AI system prompt."""
        try:
            text = self.system_prompt_path.read_text()
            if "---" in text:
                text = text.split("---", 1)[1].strip()
            return text
        except Exception as e:
            logger.error("Could not load system prompt: %s", e)
            return None


settings = Settings()
