import hashlib
import logging
import os
import warnings
from typing import Any, Dict, List, Optional, Union

import httpx
import requests

logger = logging.getLogger(__name__)


def api_error_handler(func):
    """Decorator for handling API errors."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except httpx.HTTPStatusError as e:
            try:
                error_data = e.response.json()
                error_message = error_data.get("detail", str(e))
            except Exception:
                error_message = str(e)
            raise ValueError(f"API Error: {error_message}")
        except Exception as e:
            raise ValueError(f"Unexpected error: {str(e)}")
    return wrapper


def capture_client_event(event_name: str, client, data: Dict[str, Any]):
    """Capture client events for analytics."""
    # Placeholder for analytics - can be implemented later
    pass


def get_user_id() -> str:
    """Generate a user ID."""
    return hashlib.md5(b"default_user").hexdigest()


class MemMachineClient:
    """Client for interacting with the MemMachine API.

    This class provides methods to add, search, and manage memories using the MemMachine API.

    Attributes:
        host (str): The base URL for the MemMachine API.
        client (httpx.Client): The HTTP client used for making API requests.
        group_id (str, optional): Group ID for session context.
        agent_id (str, optional): Agent ID for session context.
        user_id (str, optional): User ID for session context.
        session_id (str, optional): Session ID for session context.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        group_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ):
        """Initialize the MemMachineClient.

        Args:
            host: The base URL for the MemMachine API. Defaults to
                  "http://localhost:8000".
            group_id: The group ID for session context.
            agent_id: The agent ID for session context.
            user_id: The user ID for session context.
            session_id: The session ID for session context.
            client: A custom httpx.Client instance. If provided, it will be
                    used instead of creating a new one.

        Raises:
            ValueError: If connection to MemMachine server fails.
        """
        self.host = host or "http://localhost:8000"
        self.group_id = group_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.session_id = session_id

        if client is not None:
            self.client = client
            # Ensure the client has the correct base_url
            self.client.base_url = httpx.URL(self.host)
        else:
            self.client = httpx.Client(
                base_url=self.host,
                timeout=300,
            )

        # Validate connection
        self._validate_connection()

        capture_client_event("client.init", self, {"sync_type": "sync"})

    def _validate_connection(self):
        """Validate the connection to MemMachine server."""
        try:
            response = self.client.get("/health")
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "healthy":
                raise ValueError(f"Server not healthy: {data}")
        except httpx.HTTPStatusError as e:
            try:
                error_data = e.response.json()
                error_message = error_data.get("detail", str(e))
            except Exception:
                error_message = str(e)
            raise ValueError(f"Connection error: {error_message}")

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        headers = {}
        if self.group_id:
            headers["group-id"] = self.group_id
        if self.session_id:
            headers["session-id"] = self.session_id
        if self.agent_id:
            headers["agent-id"] = self.agent_id
        if self.user_id:
            headers["user-id"] = self.user_id
        return headers

    @api_error_handler
    def add_memory(
        self,
        producer: str,
        produced_for: str,
        episode_content: Union[str, List[float]],
        episode_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add a new memory episode to MemMachine.

        Args:
            producer: The ID of the entity that produced this memory.
            produced_for: The ID of the entity this memory is produced for.
            episode_content: The content of the memory (text string or embedding vector).
            episode_type: The type of episode content ("text" or "embedding").
            metadata: Optional metadata dictionary.

        Returns:
            A dictionary containing the API response.

        Raises:
            ValueError: If the input data is invalid or API request fails.
        """
        payload = {
            "producer": producer,
            "produced_for": produced_for,
            "episode_content": episode_content,
            "episode_type": episode_type,
            "metadata": metadata,
        }

        headers = self._get_headers()
        response = self.client.post("/v1/memories", json=payload, headers=headers)
        response.raise_for_status()
        
        capture_client_event("client.add_memory", self, {
            "producer": producer,
            "produced_for": produced_for,
            "episode_type": episode_type,
            "sync_type": "sync"
        })
        return response.json()

    @api_error_handler
    def search_memory(
        self,
        query: str,
        filter: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Search for memories in MemMachine.

        Args:
            query: The search query string.
            filter: Optional filter dictionary for narrowing search results.
            limit: Optional limit on the number of results to return.

        Returns:
            A dictionary containing the search results.

        Raises:
            ValueError: If the input data is invalid or API request fails.
        """
        payload = {
            "query": query,
            "filter": filter,
            "limit": limit,
        }

        headers = self._get_headers()
        response = self.client.post("/v1/memories/search", json=payload, headers=headers)
        response.raise_for_status()
        
        capture_client_event("client.search_memory", self, {
            "query": query,
            "has_filter": filter is not None,
            "limit": limit,
            "sync_type": "sync"
        })
        return response.json()

    @api_error_handler
    def get_sessions(self, agent_id: str) -> Dict[str, Any]:
        """Get all sessions for a specific agent.

        Args:
            agent_id: The ID of the agent to get sessions for.

        Returns:
            A dictionary containing the sessions data.

        Raises:
            ValueError: If the input data is invalid or API request fails.
        """
        headers = self._get_headers()
        response = self.client.get(f"/v1/agents/{agent_id}/sessions", headers=headers)
        response.raise_for_status()
        
        capture_client_event("client.get_sessions", self, {
            "agent_id": agent_id,
            "sync_type": "sync"
        })
        return response.json()

    @api_error_handler
    def health_check(self) -> Dict[str, Any]:
        """Check the health status of the MemMachine server.

        Returns:
            A dictionary containing the health status information.

        Raises:
            ValueError: If the server is not healthy or API request fails.
        """
        response = self.client.get("/health")
        response.raise_for_status()
        
        capture_client_event("client.health_check", self, {"sync_type": "sync"})
        return response.json()

    def close(self):
        """Close the HTTP client connection."""
        self.client.close()


class AsyncMemMachineClient:
    """Asynchronous client for interacting with the MemMachine API.

    This class provides asynchronous versions of all MemMachineClient methods.
    It uses httpx.AsyncClient for making non-blocking API requests.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        group_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        """Initialize the AsyncMemMachineClient.

        Args:
            host: The base URL for the MemMachine API. Defaults to
                  "http://localhost:8000".
            group_id: The group ID for session context.
            agent_id: The agent ID for session context.
            user_id: The user ID for session context.
            session_id: The session ID for session context.
            client: A custom httpx.AsyncClient instance. If provided, it will
                    be used instead of creating a new one.

        Raises:
            ValueError: If connection to MemMachine server fails.
        """
        self.host = host or "http://localhost:8000"
        self.group_id = group_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.session_id = session_id

        if client is not None:
            self.async_client = client
            # Ensure the client has the correct base_url
            self.async_client.base_url = httpx.URL(self.host)
        else:
            self.async_client = httpx.AsyncClient(
                base_url=self.host,
                timeout=300,
            )

        capture_client_event("client.init", self, {"sync_type": "async"})

    async def _validate_connection(self):
        """Validate the connection to MemMachine server."""
        try:
            response = await self.async_client.get("/health")
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "healthy":
                raise ValueError(f"Server not healthy: {data}")
        except httpx.HTTPStatusError as e:
            try:
                error_data = e.response.json()
                error_message = error_data.get("detail", str(e))
            except Exception:
                error_message = str(e)
            raise ValueError(f"Connection error: {error_message}")

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests."""
        headers = {}
        if self.group_id:
            headers["group-id"] = self.group_id
        if self.session_id:
            headers["session-id"] = self.session_id
        if self.agent_id:
            headers["agent-id"] = self.agent_id
        if self.user_id:
            headers["user-id"] = self.user_id
        return headers

    async def __aenter__(self):
        # Validate connection on first use
        await self._validate_connection()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.async_client.aclose()

    @api_error_handler
    async def add_memory(
        self,
        producer: str,
        produced_for: str,
        episode_content: Union[str, List[float]],
        episode_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add a new memory episode to MemMachine asynchronously.

        Args:
            producer: The ID of the entity that produced this memory.
            produced_for: The ID of the entity this memory is produced for.
            episode_content: The content of the memory (text string or embedding vector).
            episode_type: The type of episode content ("text" or "embedding").
            metadata: Optional metadata dictionary.

        Returns:
            A dictionary containing the API response.

        Raises:
            ValueError: If the input data is invalid or API request fails.
        """
        payload = {
            "producer": producer,
            "produced_for": produced_for,
            "episode_content": episode_content,
            "episode_type": episode_type,
            "metadata": metadata,
        }

        headers = self._get_headers()
        response = await self.async_client.post("/v1/memories", json=payload, headers=headers)
        response.raise_for_status()
        
        capture_client_event("client.add_memory", self, {
            "producer": producer,
            "produced_for": produced_for,
            "episode_type": episode_type,
            "sync_type": "async"
        })
        return response.json()

    @api_error_handler
    async def search_memory(
        self,
        query: str,
        filter: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Search for memories in MemMachine asynchronously.

        Args:
            query: The search query string.
            filter: Optional filter dictionary for narrowing search results.
            limit: Optional limit on the number of results to return.

        Returns:
            A dictionary containing the search results.

        Raises:
            ValueError: If the input data is invalid or API request fails.
        """
        payload = {
            "query": query,
            "filter": filter,
            "limit": limit,
        }

        headers = self._get_headers()
        response = await self.async_client.post("/v1/memories/search", json=payload, headers=headers)
        response.raise_for_status()
        
        capture_client_event("client.search_memory", self, {
            "query": query,
            "has_filter": filter is not None,
            "limit": limit,
            "sync_type": "async"
        })
        return response.json()

    @api_error_handler
    async def get_sessions(self, agent_id: str) -> Dict[str, Any]:
        """Get all sessions for a specific agent asynchronously.

        Args:
            agent_id: The ID of the agent to get sessions for.

        Returns:
            A dictionary containing the sessions data.

        Raises:
            ValueError: If the input data is invalid or API request fails.
        """
        headers = self._get_headers()
        response = await self.async_client.get(f"/v1/agents/{agent_id}/sessions", headers=headers)
        response.raise_for_status()
        
        capture_client_event("client.get_sessions", self, {
            "agent_id": agent_id,
            "sync_type": "async"
        })
        return response.json()

    @api_error_handler
    async def health_check(self) -> Dict[str, Any]:
        """Check the health status of the MemMachine server asynchronously.

        Returns:
            A dictionary containing the health status information.

        Raises:
            ValueError: If the server is not healthy or API request fails.
        """
        response = await self.async_client.get("/health")
        response.raise_for_status()
        
        capture_client_event("client.health_check", self, {"sync_type": "async"})
        return response.json()
