#!/usr/bin/env python3
"""
MemMachine Client Demo

This script demonstrates how to use the MemMachineClient to interact with
the MemMachine API for adding memories, searching, and managing sessions.
"""

import asyncio
import sys
import os

# Add the src directory to the path so we can import memmachine
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from memmachine.client.main import MemMachineClient, AsyncMemMachineClient


def sync_demo():
    """Demonstrate synchronous MemMachine client usage."""
    print("=== Synchronous MemMachine Client Demo ===")
    
    # Initialize the client
    client = MemMachineClient(
        host="http://localhost:8000",  # Default MemMachine server URL
        group_id="demo_group",
        agent_id="demo_agent", 
        user_id="demo_user",
        session_id="demo_session"
    )
    
    try:
        # Check server health
        print("1. Checking server health...")
        health = client.health_check()
        print(f"   Server status: {health.get('status')}")
        print(f"   Service: {health.get('service')}")
        print(f"   Version: {health.get('version')}")
        
        # Add a memory
        print("\n2. Adding a memory...")
        memory_result = client.add_memory(
            producer="demo_user",
            produced_for="demo_agent",
            episode_content="I love playing tennis on weekends",
            episode_type="text",
            metadata={"sport": "tennis", "frequency": "weekly"}
        )
        print(f"   Memory added successfully: {memory_result}")
        
        # Search for memories
        print("\n3. Searching for memories...")
        search_result = client.search_memory(
            query="tennis",
            limit=5
        )
        print(f"   Search results: {search_result}")
        
        # Get sessions for agent
        print("\n4. Getting sessions for agent...")
        sessions = client.get_sessions("demo_agent")
        print(f"   Sessions: {sessions}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Close the client
        client.close()


async def async_demo():
    """Demonstrate asynchronous MemMachine client usage."""
    print("\n=== Asynchronous MemMachine Client Demo ===")
    
    # Initialize the async client
    async with AsyncMemMachineClient(
        host="http://localhost:8000",
        group_id="demo_group",
        agent_id="demo_agent",
        user_id="demo_user", 
        session_id="demo_session"
    ) as client:
        try:
            # Check server health
            print("1. Checking server health...")
            health = await client.health_check()
            print(f"   Server status: {health.get('status')}")
            print(f"   Service: {health.get('service')}")
            print(f"   Version: {health.get('version')}")
            
            # Add multiple memories concurrently
            print("\n2. Adding multiple memories concurrently...")
            tasks = []
            for i in range(3):
                task = client.add_memory(
                    producer=f"demo_user_{i}",
                    produced_for="demo_agent",
                    episode_content=f"Memory content {i}: I enjoy activity {i}",
                    episode_type="text",
                    metadata={"index": i, "type": "demo"}
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks)
            print(f"   Added {len(results)} memories successfully")
            
            # Search for memories
            print("\n3. Searching for memories...")
            search_result = await client.search_memory(
                query="activity",
                limit=10
            )
            print(f"   Search results: {search_result}")
            
            # Get sessions for agent
            print("\n4. Getting sessions for agent...")
            sessions = await client.get_sessions("demo_agent")
            print(f"   Sessions: {sessions}")
            
        except Exception as e:
            print(f"Error: {e}")


def main():
    """Main function to run both sync and async demos."""
    print("MemMachine Client Demo")
    print("=" * 50)
    print("Make sure the MemMachine server is running on http://localhost:8000")
    print("You can start it with: python -m memmachine.server.app")
    print()
    
    # Run synchronous demo
    sync_demo()
    
    # Run asynchronous demo
    asyncio.run(async_demo())
    
    print("\nDemo completed!")


if __name__ == "__main__":
    main()
