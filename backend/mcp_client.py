"""
MCP Client module for MSRIT AI.
Manages a persistent stdio connection to the FastMCP server and executes audited tool calls.
"""
from typing import Optional, Dict, Any, List
import asyncio
import os
import sys
import json
from pathlib import Path
from contextlib import AsyncExitStack, asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "mcp_server" / "server.py"


class PersistentMCPClient:
    """
    Maintains a single persistent session with the local MCP server over stdio.
    Avoids reconnecting and re-spawning python subprocesses on every tool call.
    """
    def __init__(self):
        self._session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._lock = asyncio.Lock()

    async def start(self) -> ClientSession:
        async with self._lock:
            if self._session is not None:
                return self._session

            self._exit_stack = AsyncExitStack()
            server_params = StdioServerParameters(
                command=sys.executable,
                args=[str(SERVER_SCRIPT)],
                env=dict(os.environ)
            )

            read, write = await self._exit_stack.enter_async_context(stdio_client(server_params))
            session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._session = session
            return self._session

    async def close(self) -> None:
        async with self._lock:
            if self._exit_stack is not None:
                try:
                    await self._exit_stack.aclose()
                except Exception as e:
                    print(f"Warning: Error closing MCP client session: {e}", file=sys.stderr)
                finally:
                    self._exit_stack = None
                    self._session = None

    async def get_session(self) -> ClientSession:
        if self._session is None:
            await self.start()
        return self._session


# Module-level singleton
_mcp_client_instance = PersistentMCPClient()


def get_mcp_client() -> PersistentMCPClient:
    """Returns the persistent MCP client singleton."""
    return _mcp_client_instance


@asynccontextmanager
async def mcp_session():
    """
    Async context manager for managing the lifetime of the persistent MCP client.
    Can be used by FastAPI lifespan or test runners.
    """
    client = get_mcp_client()
    await client.start()
    try:
        yield client
    finally:
        await client.close()


def _parse_tool_result(result_content: List[Any]) -> Any:
    """Convert MCP TextContent items back into Python primitives (lists, dicts, or strings)."""
    if not result_content:
        return None

    if len(result_content) == 1:
        text = getattr(result_content[0], "text", str(result_content[0]))
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    items = []
    for item in result_content:
        text = getattr(item, "text", str(item))
        try:
            items.append(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            items.append(text)
    return items


async def call_tool(tool_name: str, **kwargs) -> Any:
    """
    Call an audited tool on the persistent MCP server over stdio.
    Returns the parsed result or an error dictionary if invocation fails.
    """
    try:
        client = get_mcp_client()
        session = await client.get_session()
        call_res = await session.call_tool(tool_name, arguments=kwargs)

        if call_res.isError:
            err_text = " ".join(getattr(c, "text", str(c)) for c in call_res.content)
            return {"error": f"Tool execution failed: {err_text}"}

        return _parse_tool_result(call_res.content)

    except Exception as e:
        print(f"Error calling MCP tool '{tool_name}': {e}", file=sys.stderr)
        return {"error": f"MCP communication error: {str(e)}"}
