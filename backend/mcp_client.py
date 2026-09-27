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

BASE_DIR = Path(__file__).resolve().parent.parent
SERVER_SCRIPT = BASE_DIR / "mcp_server" / "server.py"


def get_python_executable() -> str:
    """Return project virtual environment Python if available, else current sys.executable."""
    win_venv = BASE_DIR / "venv" / "Scripts" / "python.exe"
    if win_venv.exists():
        return str(win_venv)
    posix_venv = BASE_DIR / "venv" / "bin" / "python"
    if posix_venv.exists():
        return str(posix_venv)
    return sys.executable


class PersistentMCPClient:
    """
    Maintains a single persistent session with the local MCP server over stdio.
    Avoids reconnecting and re-spawning python subprocesses on every tool call.
    """
    def __init__(self):
        self._session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def start(self) -> ClientSession:
        async with self._get_lock():
            if self._session is not None:
                return self._session

            self._exit_stack = AsyncExitStack()
            python_cmd = get_python_executable()
            server_params = StdioServerParameters(
                command=python_cmd,
                args=[str(SERVER_SCRIPT)],
                env=dict(os.environ)
            )

            read, write = await self._exit_stack.enter_async_context(stdio_client(server_params))
            session = await self._exit_stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._session = session
            return self._session

    async def close(self) -> None:
        async with self._get_lock():
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


LIST_RETURNING_TOOLS = {
    "lookup_club",
    "search_academic_documents",
    "search_notes",
    "list_subjects",
    "get_recommended_clubs",
}


def _parse_tool_result(result_content: List[Any], tool_name: Optional[str] = None) -> Any:
    """Convert MCP TextContent items back into Python primitives (lists, dicts, or strings)."""
    is_list_tool = tool_name in LIST_RETURNING_TOOLS if tool_name else False

    if not result_content:
        return [] if is_list_tool else None

    parsed_items = []
    for item in result_content:
        text = getattr(item, "text", str(item))
        try:
            val = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            val = text
        parsed_items.append(val)

    if is_list_tool:
        # If the single item parsed is already a list, return it; otherwise return parsed_items as a list
        if len(parsed_items) == 1 and isinstance(parsed_items[0], list):
            return parsed_items[0]
        return parsed_items

    # For single-object tools
    if len(parsed_items) == 1:
        return parsed_items[0]
    return parsed_items


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

        return _parse_tool_result(call_res.content, tool_name=tool_name)

    except Exception as e:
        print(f"Error calling MCP tool '{tool_name}': {e}", file=sys.stderr)
        try:
            client = get_mcp_client()
            await client.close()
        except Exception:
            pass
        return {"error": f"MCP communication error: {str(e)}"}


async def list_tools() -> List[str]:
    """
    List names of all registered tools on the MCP server.
    """
    try:
        client = get_mcp_client()
        session = await client.get_session()
        res = await session.list_tools()
        return [tool.name for tool in res.tools]
    except Exception as e:
        print(f"Error listing MCP tools: {e}", file=sys.stderr)
        return []
