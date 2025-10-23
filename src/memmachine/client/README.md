# MemMachine Client

This directory contains the MemMachine client library for interacting with the MemMachine API.

## Overview

The MemMachine client provides both synchronous and asynchronous interfaces for:
- Adding memory episodes
- Searching memories
- Managing agent sessions
- Health checking

## Classes

### MemMachineClient

Synchronous client for interacting with the MemMachine API.

```python
from memmachine.client.main import MemMachineClient

client = MemMachineClient(
    host="http://localhost:8000",
    group_id="my_group",
    agent_id="my_agent",
    user_id="my_user",
    session_id="my_session"
)

# Add a memory
result = client.add_memory(
    producer="user123",
    produced_for="agent456", 
    episode_content="I love playing tennis",
    episode_type="text",
    metadata={"sport": "tennis"}
)

# Search memories
search_result = client.search_memory(
    query="tennis",
    limit=10
)

# Get sessions
sessions = client.get_sessions("agent456")

# Check health
health = client.health_check()

client.close()
```

### AsyncMemMachineClient

Asynchronous client for non-blocking operations.

```python
import asyncio
from memmachine.client.main import AsyncMemMachineClient

async def main():
    async with AsyncMemMachineClient(
        host="http://localhost:8000",
        group_id="my_group",
        agent_id="my_agent",
        user_id="my_user",
        session_id="my_session"
    ) as client:
        # Add a memory
        result = await client.add_memory(
            producer="user123",
            produced_for="agent456",
            episode_content="I love playing tennis", 
            episode_type="text",
            metadata={"sport": "tennis"}
        )
        
        # Search memories
        search_result = await client.search_memory(
            query="tennis",
            limit=10
        )
        
        # Get sessions
        sessions = await client.get_sessions("agent456")
        
        # Check health
        health = await client.health_check()

asyncio.run(main())
```

## API Methods

### add_memory(producer, produced_for, episode_content, episode_type="text", metadata=None)

Add a new memory episode to MemMachine.

**Parameters:**
- `producer` (str): The ID of the entity that produced this memory
- `produced_for` (str): The ID of the entity this memory is produced for
- `episode_content` (str or List[float]): The content of the memory (text string or embedding vector)
- `episode_type` (str): The type of episode content ("text" or "embedding")
- `metadata` (dict, optional): Optional metadata dictionary

**Returns:** Dictionary containing the API response

### search_memory(query, filter=None, limit=None)

Search for memories in MemMachine.

**Parameters:**
- `query` (str): The search query string
- `filter` (dict, optional): Optional filter dictionary for narrowing search results
- `limit` (int, optional): Optional limit on the number of results to return

**Returns:** Dictionary containing the search results

### get_sessions(agent_id)

Get all sessions for a specific agent.

**Parameters:**
- `agent_id` (str): The ID of the agent to get sessions for

**Returns:** Dictionary containing the sessions data

### health_check()

Check the health status of the MemMachine server.

**Returns:** Dictionary containing the health status information

## Error Handling

The client includes comprehensive error handling with the `@api_error_handler` decorator. All methods will raise `ValueError` with descriptive messages if:

- The server is not reachable
- The server returns an error status
- Invalid parameters are provided
- The server is not healthy

## Session Context

The client uses headers to provide session context to the MemMachine server:

- `group-id`: Group identifier
- `session-id`: Session identifier  
- `agent-id`: Agent identifier
- `user-id`: User identifier

These headers are automatically included in all API requests when the corresponding parameters are provided during client initialization.

## Examples

See `examples/memmachine_client_demo.py` for a complete working example that demonstrates both synchronous and asynchronous usage patterns.
