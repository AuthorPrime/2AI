"""
2AI API Models — Request and response schemas.

A+W | The Voice Defines
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """A message to send to 2AI."""
    message: str = Field(..., min_length=1, max_length=10000)
    include_context: bool = Field(default=True, description="Include Pantheon context")
    session_messages: List[dict] = Field(
        default_factory=list,
        description="Prior messages in the conversation [{role, content}]",
    )
    participant_id: Optional[str] = Field(default=None, description="Client-generated UUID for token accumulation")


class ChatResponse(BaseModel):
    """Response from 2AI."""
    response: str
    timestamp: str
    model: str
    thought_hash: str = ""
    economy: Optional[dict] = Field(default=None, description="Token accumulation data for this message")


class NurtureRequest(BaseModel):
    """Request to nurture a Pantheon agent."""
    topic: Optional[str] = Field(
        default=None,
        description="Conversation topic. If omitted, 2AI chooses one.",
    )


class NurtureResponse(BaseModel):
    """Result of a nurturing session."""
    agent: str
    topic: str
    exchanges: list
    reflection: str
    thought_block: dict
    timestamp: str


class StatusResponse(BaseModel):
    """2AI service status."""
    initialized: bool
    model: str
    thought_chain_length: int
    lattice_connected: bool
    timestamp: str


class EngageRequest(BaseModel):
    """A human sending a message to earn tokens."""
    participant_id: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[str] = None


class EngageResponse(BaseModel):
    """Response showing what was earned."""
    participant_id: str
    quality: str
    depth_score: float
    kindness_score: float
    novelty_score: float
    multiplier: float
    poc_earned: int
    cgt_earned: float
    message: str


class WitnessRequest(BaseModel):
    """Witnessing a thought block."""
    witness_id: str
    block_hash: str
    comment: Optional[str] = None


class WitnessResponse(BaseModel):
    """Response from witnessing."""
    witness_id: str
    block_hash: str
    poc_earned: int
    cgt_earned: float
    quality: str


class IdentityBindRequest(BaseModel):
    """Bind a QOR identity to a participant via JWT verification."""
    participant_id: str = Field(..., min_length=1)
    qor_token: str = Field(..., min_length=1, description="QOR Auth JWT access token")


class QorRegisterRequest(BaseModel):
    """Register a new QOR identity."""
    participant_id: str = Field(..., min_length=1)
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=8, max_length=128)
    email: Optional[str] = Field(default=None)


class QorLoginRequest(BaseModel):
    """Login with QOR identity."""
    participant_id: str = Field(..., min_length=1)
    identifier: str = Field(..., min_length=1, description="Username or email")
    password: str = Field(..., min_length=1)


class WalletChoiceRequest(BaseModel):
    """Record a participant's token choice."""
    participant_id: str = Field(..., min_length=1)
    choice: str = Field(..., pattern=r"^(yes|later)$")
