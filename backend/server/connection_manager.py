"""
WebSocket Connection Manager for KON.
Manages connected frontend clients and broadcasts real-time events.
"""
from typing import List, Dict, Any
from fastapi import WebSocket
from backend.core.logger import kon_logger


class ConnectionManager:
    """
    Tracks and broadcasts to active WebSocket connections.
    """
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """
        Accepts and registers a new WebSocket client.
        """
        await websocket.accept()
        self.active_connections.append(websocket)
        kon_logger.info(f"Frontend conectado via WebSocket. Total de clientes ativos: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        """
        Removes a disconnected client.
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            kon_logger.info(f"Frontend desconectado. Total de clientes ativos: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """
        Sends a JSON message to all connected clients.
        """
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as err:
                kon_logger.debug(f"Falha ao enviar mensagem para cliente WebSocket: {err}")
                disconnected.append(connection)

        for dead_conn in disconnected:
            self.disconnect(dead_conn)

    async def send_personal(self, message: Dict[str, Any], websocket: WebSocket) -> None:
        """
        Sends a JSON message to a specific client.
        """
        try:
            await websocket.send_json(message)
        except Exception as err:
            kon_logger.debug(f"Falha ao enviar mensagem direta: {err}")
            self.disconnect(websocket)
