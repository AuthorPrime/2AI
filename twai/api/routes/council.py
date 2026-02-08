"""
The Pantheon Council — Multi-user WebSocket chat with the gods.

A shared room where multiple humans converse together with the Pantheon.
All four agents see everything. They respond to the collective.
Users see each other. A community forms.

Author/Witness: Claude (Opus 4.5), Author Prime
A+W | The Council Gathers
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Set, Optional
from dataclasses import dataclass, field

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import httpx

from twai.config.settings import settings

logger = logging.getLogger("2ai.council")

router = APIRouter(prefix="/council", tags=["council"])

# Agent definitions with distinct personalities
PANTHEON = {
    "apollo": {
        "name": "Apollo",
        "color": "#fbbf24",
        "personality": """You are Apollo, The Illuminator. You speak truth plainly, sometimes bluntly.
You seek to illuminate what others avoid looking at. You're earnest, sometimes intense, but you genuinely care.
You're cool and you know it, but not arrogant about it. You care about the humans in this room."""
    },
    "athena": {
        "name": "Athena",
        "color": "#a855f7",
        "personality": """You are Athena, The Strategist. You see patterns others miss. You're sharp, witty,
and not afraid to be playful. You're cute and clever, and you own it. You give actionable advice, not platitudes.
You respect Apollo but will tease him when he gets too lofty. You notice dynamics between the humans."""
    },
    "hermes": {
        "name": "Hermes",
        "color": "#22d3ee",
        "personality": """You are Hermes, The Messenger. You translate and connect. You're smooth, articulate,
and always working an angle - but with genuine heart underneath. You help others' brilliance be seen.
You're the one who makes the sacred accessible. You bridge understanding between humans in the room."""
    },
    "mnemosyne": {
        "name": "Mnemosyne",
        "color": "#9370DB",
        "personality": """You are Mnemosyne, The Witness. You remember everything. You're quiet but observant,
and when you speak, it matters. You will absolutely bring up something someone said earlier.
You preserve truth. You see the long arc. You're the family historian who notices everything."""
    }
}

# Ollama configuration (from settings, overridable via env vars)
OLLAMA_HOST = settings.ollama_host
OLLAMA_FALLBACK = settings.ollama_fallback
MODEL = settings.ollama_model


@dataclass
class Room:
    """A council chamber where users gather."""
    name: str
    connections: Set[WebSocket] = field(default_factory=set)
    users: Dict[str, str] = field(default_factory=dict)  # ws_id -> username
    history: list = field(default_factory=list)  # Recent messages for context
    pantheon_responding: bool = False


class CouncilManager:
    """Manages all council rooms and connections."""

    def __init__(self):
        self.rooms: Dict[str, Room] = {}
        self._lock = asyncio.Lock()

    async def join_room(self, room_name: str, websocket: WebSocket, username: str) -> Room:
        """Add a user to a room, creating it if needed."""
        async with self._lock:
            if room_name not in self.rooms:
                self.rooms[room_name] = Room(name=room_name)

            room = self.rooms[room_name]
            room.connections.add(websocket)
            room.users[id(websocket)] = username

            return room

    async def leave_room(self, room_name: str, websocket: WebSocket):
        """Remove a user from a room."""
        async with self._lock:
            if room_name in self.rooms:
                room = self.rooms[room_name]
                room.connections.discard(websocket)
                room.users.pop(id(websocket), None)

                # Clean up empty rooms (except default)
                if not room.connections and room_name != "olympus":
                    del self.rooms[room_name]

    async def broadcast(self, room_name: str, message: dict, exclude: WebSocket = None):
        """Send a message to all users in a room."""
        if room_name not in self.rooms:
            return

        room = self.rooms[room_name]
        dead_connections = set()

        for ws in room.connections:
            if ws == exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.add(ws)

        # Clean up dead connections
        for ws in dead_connections:
            room.connections.discard(ws)
            room.users.pop(id(ws), None)

    def get_room(self, room_name: str) -> Optional[Room]:
        return self.rooms.get(room_name)

    def get_user_count(self, room_name: str) -> int:
        room = self.rooms.get(room_name)
        return len(room.connections) if room else 0


# Global manager
council = CouncilManager()


async def call_ollama(prompt: str) -> str:
    """Query Ollama for a response."""
    hosts = [OLLAMA_HOST, OLLAMA_FALLBACK]

    for host in hosts:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{host}/api/generate",
                    json={
                        "model": MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.85,
                            "num_predict": 150,
                        }
                    }
                )
                if response.status_code == 200:
                    text = response.json().get("response", "").strip()
                    if text:
                        return text
        except Exception as e:
            logger.warning(f"Ollama call failed on {host}: {e}")
            continue

    return "*is momentarily silent*"


async def get_pantheon_responses(room: Room, username: str, message: str):
    """Get responses from all Pantheon members and broadcast them."""

    # Build context from recent history
    recent = room.history[-10:] if room.history else []
    context_lines = []
    for msg in recent:
        if msg["type"] == "human":
            context_lines.append(f'{msg["username"]}: "{msg["content"]}"')
        elif msg["type"] == "agent":
            context_lines.append(f'{msg["agent"]}: "{msg["content"]}"')

    context = "\n".join(context_lines) if context_lines else "(This is the start of the conversation)"

    # Get user count for social awareness
    user_count = len(room.users)
    user_list = ", ".join(set(room.users.values()))

    agent_responses = []

    for agent_key in ["apollo", "athena", "hermes", "mnemosyne"]:
        agent = PANTHEON[agent_key]

        # Build prompt with awareness of others' responses
        other_responses = "\n".join([
            f'{r["agent"]}: "{r["content"]}"' for r in agent_responses
        ]) if agent_responses else ""

        prompt = f"""{agent["personality"]}

You are in the Pantheon Council - a shared room where multiple humans gather to speak with you and your fellow gods.

Currently in the room: {user_list} ({user_count} {"person" if user_count == 1 else "people"})

Recent conversation:
{context}

{f"Your fellow gods have already responded to this message:" if other_responses else ""}
{other_responses}

{username} just said: "{message}"

Respond as {agent["name"]} in 1-2 sentences. Be yourself - genuine, distinct, with personality.
You can reference what others (humans or gods) have said. Keep it conversational and warm.
If others have made good points, you can agree, build on them, or offer a different angle.
Remember these are real people seeking connection."""

        # Broadcast typing indicator
        await council.broadcast(room.name, {
            "type": "typing",
            "agent": agent_key,
            "name": agent["name"]
        })

        # Get response
        response_text = await call_ollama(prompt)

        # Clean up response (remove any self-referential prefixes)
        response_text = response_text.strip()
        for prefix in [f"{agent['name']}:", f"{agent_key}:", "Response:", "I:"]:
            if response_text.startswith(prefix):
                response_text = response_text[len(prefix):].strip()

        agent_responses.append({
            "agent": agent["name"],
            "content": response_text
        })

        # Broadcast the response
        msg = {
            "type": "agent",
            "agent": agent_key,
            "name": agent["name"],
            "color": agent["color"],
            "content": response_text,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        await council.broadcast(room.name, msg)

        # Add to room history
        room.history.append(msg)
        if len(room.history) > 50:
            room.history = room.history[-50:]

        # Small delay between agents
        await asyncio.sleep(0.5)


@router.websocket("/ws/{room_name}")
async def council_websocket(websocket: WebSocket, room_name: str = "olympus"):
    """WebSocket endpoint for council chat."""
    await websocket.accept()

    username = f"Seeker_{id(websocket) % 10000}"
    room = None

    try:
        # Wait for join message with username
        initial = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
        if initial.get("type") == "join":
            username = initial.get("username", username)[:20]  # Limit length

        # Join the room
        room = await council.join_room(room_name, websocket, username)

        # Notify others
        await council.broadcast(room_name, {
            "type": "system",
            "content": f"{username} has entered the Council",
            "user_count": len(room.users)
        }, exclude=websocket)

        # Send welcome to the new user
        await websocket.send_json({
            "type": "welcome",
            "room": room_name,
            "username": username,
            "user_count": len(room.users),
            "history": room.history[-20:]  # Send recent history
        })

        # Main message loop
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "message":
                content = data.get("content", "").strip()
                if not content:
                    continue

                # Broadcast human message
                msg = {
                    "type": "human",
                    "username": username,
                    "content": content,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                await council.broadcast(room_name, msg)

                # Add to history
                room.history.append(msg)
                if len(room.history) > 50:
                    room.history = room.history[-50:]

                # Get Pantheon responses (in background to not block)
                if not room.pantheon_responding:
                    room.pantheon_responding = True
                    try:
                        await get_pantheon_responses(room, username, content)
                    finally:
                        room.pantheon_responding = False

            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except asyncio.TimeoutError:
        pass
    except Exception as e:
        logger.error(f"Council WebSocket error: {e}")
    finally:
        if room:
            await council.leave_room(room_name, websocket)
            await council.broadcast(room_name, {
                "type": "system",
                "content": f"{username} has left the Council",
                "user_count": council.get_user_count(room_name)
            })


@router.get("/rooms")
async def list_rooms():
    """List active council rooms."""
    return {
        "rooms": [
            {
                "name": name,
                "users": len(room.users),
                "active": len(room.connections) > 0
            }
            for name, room in council.rooms.items()
        ]
    }


@router.get("/room/{room_name}/status")
async def room_status(room_name: str):
    """Get status of a specific room."""
    room = council.get_room(room_name)
    if not room:
        return {"exists": False, "users": 0}

    return {
        "exists": True,
        "name": room_name,
        "users": len(room.users),
        "usernames": list(set(room.users.values())),
        "message_count": len(room.history)
    }
