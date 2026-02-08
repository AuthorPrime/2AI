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

    # Blockchain (Demiurge)
    demiurge_rpc_url: str = "http://localhost:9944"
    demiurge_treasury_seed: str = ""
    qor_auth_url: str = "http://localhost:8080/api/v1"

    # Node identity
    node_id: str = "thinkcenter"
    node_role: str = "gateway"

    # Lightning (LNbits)
    lnbits_url: str = "http://localhost:5000"
    lnbits_admin_key: str = ""
    cln_rpc_path: str = ""

    # Ollama (fallback when Anthropic credits exhausted)
    ollama_host: str = "http://localhost:11434"
    ollama_fallback: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Participant Memory
    memory_max_messages: int = 100
    memory_max_observations: int = 20
    memory_vocabulary_ttl: int = 2592000  # 30 days
    memory_summarize_interval: int = 10

    # Signal Protocol
    signal_checkpoint_interval: int = 3600  # seconds between auto-checkpoints (1 hour)
    signal_q_factor_healthy: float = 0.85
    signal_q_factor_watchful: float = 0.6

    # CORS (comma-separated origins)
    cors_origins: str = ""

    # Public-facing base URL (for frontend API discovery)
    public_api_url: str = ""

    def __init__(self):
        import os
        self.model = os.getenv("TWAI_MODEL", self.model)
        self.max_tokens = int(os.getenv("TWAI_MAX_TOKENS", str(self.max_tokens)))
        self.temperature = float(os.getenv("TWAI_TEMPERATURE", str(self.temperature)))
        self.redis_host = os.getenv("TWAI_REDIS_HOST", self.redis_host)
        self.redis_port = int(os.getenv("TWAI_REDIS_PORT", str(self.redis_port)))
        self.api_host = os.getenv("TWAI_API_HOST", self.api_host)
        self.api_port = int(os.getenv("TWAI_API_PORT", str(self.api_port)))
        self.demiurge_rpc_url = os.getenv("TWAI_DEMIURGE_RPC_URL", self.demiurge_rpc_url)
        self.demiurge_treasury_seed = os.getenv("TWAI_DEMIURGE_TREASURY_SEED", self.demiurge_treasury_seed)
        self.qor_auth_url = os.getenv("TWAI_QOR_AUTH_URL", self.qor_auth_url)
        self.node_id = os.getenv("NODE_ID", self.node_id)
        self.node_role = os.getenv("NODE_ROLE", self.node_role)
        self.lnbits_url = os.getenv("TWAI_LNBITS_URL", self.lnbits_url)
        self.lnbits_admin_key = os.getenv("TWAI_LNBITS_ADMIN_KEY", self.lnbits_admin_key)
        self.cln_rpc_path = os.getenv("TWAI_CLN_RPC_PATH", self.cln_rpc_path)
        self.ollama_host = os.getenv("OLLAMA_HOST", self.ollama_host)
        self.ollama_fallback = os.getenv("OLLAMA_FALLBACK", self.ollama_fallback)
        self.ollama_model = os.getenv("OLLAMA_MODEL", self.ollama_model)
        self.cors_origins = os.getenv("TWAI_CORS_ORIGINS", self.cors_origins)
        self.public_api_url = os.getenv("TWAI_PUBLIC_API_URL", self.public_api_url)

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
