"""WebSocket connection manager for real-time workflow status streaming to dashboard clients."""

import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

from src.core.logger import get_logger

logger = get_logger(__name__)


class WorkflowWebSocketManager:
    """Manages active WebSocket subscriber connections grouped by workflow job ID."""

    def __init__(self) -> None:
        # Maps job_id -> set of active WebSockets
        self._active_connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, job_id: str) -> None:
        """Accepts and registers a client connection subscribed to a specific job."""
        await websocket.accept()
        self._active_connections[job_id].add(websocket)
        logger.info(
            "WebSocket client connected",
            extra={"job_id": job_id, "active_subscribers": len(self._active_connections[job_id])},
        )

    def disconnect(self, websocket: WebSocket, job_id: str) -> None:
        """Removes a disconnected client from the job's subscription pool."""
        self._active_connections[job_id].discard(websocket)
        if not self._active_connections[job_id]:
            self._active_connections.pop(job_id, None)
        logger.info("WebSocket client disconnected", extra={"job_id": job_id})

    async def broadcast(self, job_id: str, message: dict[str, Any]) -> None:
        """Broadcasts a JSON status event to all connected clients listening to job_id."""
        subscribers = list(self._active_connections.get(job_id, set()))
        if not subscribers:
            return

        payload_str = json.dumps(message)
        dead_sockets: list[WebSocket] = []

        for ws in subscribers:
            try:
                await ws.send_text(payload_str)
            except Exception as exc:
                logger.warning(
                    "Failed to deliver WebSocket message to subscriber; dropping connection",
                    extra={"job_id": job_id, "error": str(exc)},
                )
                dead_sockets.append(ws)

        for dead_ws in dead_sockets:
            self.disconnect(dead_ws, job_id)


# Global singleton instance
ws_manager = WorkflowWebSocketManager()
