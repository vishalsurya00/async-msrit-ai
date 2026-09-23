"""
MCP Server module for MSRIT AI.
Exposes sovereign audited tools via FastMCP over stdio transport.
"""
from typing import Optional, List, Dict, Any
import sys
from pathlib import Path

# Ensure project root is in sys.path when executed directly or as a subprocess
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from mcp.server.fastmcp import FastMCP
from backend.search import search_notes as _search_notes
from backend.memory import (
    get_student_profile as _get_student_profile,
    update_student_profile as _update_student_profile,
)
from backend.info_lookup import (
    lookup_branch as _lookup_branch,
    lookup_club as _lookup_club,
    list_subjects as _list_subjects,
)
from backend.audit import audited

mcp = FastMCP("msrit-ai-server")


@mcp.tool()
@audited("search_notes")
def search_notes(
    query: str,
    stream: Optional[str] = None,
    cycle: Optional[str] = None,
    subject: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Search academic course notes and syllabus documents using semantic similarity with optional stream, cycle, and subject filters.
    """
    return _search_notes(query=query, stream=stream, cycle=cycle, subject=subject)


@mcp.tool()
@audited("get_student_profile")
def get_student_profile(student_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve persistent student profile details including stream, cycle, branch, semester, and preferences by student ID.
    """
    return _get_student_profile(student_id=student_id)


@mcp.tool()
@audited("update_student_profile")
def update_student_profile(
    student_id: str,
    stream: Optional[str] = None,
    cycle: Optional[str] = None,
    branch: Optional[str] = None,
    semester: Optional[int] = None
) -> Dict[str, Any]:
    """
    Create or update a student's academic profile (branch, semester, stream, cycle) in persistent database memory.
    """
    return _update_student_profile(
        student_id=student_id,
        stream=stream,
        cycle=cycle,
        branch=branch,
        semester=semester
    )


@mcp.tool()
@audited("lookup_branch")
def lookup_branch(query: str) -> Optional[Dict[str, Any]]:
    """
    Look up official MSRIT engineering department/branch details such as branch code, department name, HOD, and location.
    """
    return _lookup_branch(query=query)


@mcp.tool()
@audited("lookup_club")
def lookup_club(
    query: Optional[str] = None,
    category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Search student technical and cultural clubs, student chapters, and societies at Ramaiah Institute of Technology.
    """
    return _lookup_club(query=query, category=category)


@mcp.tool()
@audited("list_subjects")
def list_subjects(
    stream: Optional[str] = None,
    cycle: Optional[str] = None
) -> List[str]:
    """
    List all available course subjects with ingested study notes and materials, with optional stream or cycle filtering.
    """
    return _list_subjects(stream=stream, cycle=cycle)


if __name__ == "__main__":
    mcp.run(transport="stdio")
