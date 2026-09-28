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
    get_principal_info as _get_principal_info,
    get_chief_proctor_info as _get_chief_proctor_info,
    lookup_office as _lookup_office,
    get_branch_count as _get_branch_count,
    get_club_count as _get_club_count,
)
from backend.documents import (
    search_academic_documents as _search_academic_documents,
    get_academic_document as _get_academic_document,
    sanitize_document_metadata as _sanitize_document_metadata,
)
from backend.knowledge import (
    get_academic_context as _get_academic_context,
    get_recommended_clubs as _get_recommended_clubs,
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
    if not student_id or not str(student_id).strip():
        return None
    return _get_student_profile(student_id=str(student_id).strip())


@mcp.tool()
@audited("update_student_profile")
def update_student_profile(
    student_id: str,
    name: Optional[str] = None,
    college: Optional[str] = None,
    degree: Optional[str] = None,
    branch: Optional[str] = None,
    semester: Optional[int] = None,
    year: Optional[int] = None,
    stream: Optional[str] = None,
    cycle: Optional[str] = None,
    cgpa: Optional[float] = None,
    preferences: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create or update a student's profile (name, college, degree, branch, semester, year, stream, cycle, cgpa, preferences) in persistent database memory.
    """
    if not student_id or not str(student_id).strip():
        return {"error": "student_id is required"}
    return _update_student_profile(
        student_id=str(student_id).strip(),
        name=name,
        college=college,
        degree=degree,
        branch=branch,
        semester=semester,
        year=year,
        stream=stream,
        cycle=cycle,
        cgpa=cgpa,
        preferences=preferences
    )


@mcp.tool()
@audited("lookup_department")
def lookup_department(query: str) -> Optional[Dict[str, Any]]:
    """
    Look up official MSRIT engineering department details such as department code, name, HOD, and location.
    """
    if not query or not str(query).strip():
        return None
    return _lookup_branch(query=str(query).strip())


@mcp.tool()
@audited("lookup_branch")
def lookup_branch(query: str) -> Optional[Dict[str, Any]]:
    """
    Look up official MSRIT engineering department/branch details such as branch code, department name, HOD, and location.
    Backwards-compatible alias for lookup_department.
    """
    return lookup_department(query=query)


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


@mcp.tool()
@audited("search_academic_documents")
def search_academic_documents(
    query: Optional[str] = None,
    subject: Optional[str] = None,
    unit: Optional[int] = None,
    semester: Optional[int] = None,
    branch: Optional[str] = None,
    document_type: Optional[str] = None,
    year: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Search verified MSRIT academic documents, notes, question papers, and syllabus files by subject, unit, semester, document type, or year.
    """
    docs = _search_academic_documents(
        query=query,
        subject=subject,
        unit=unit,
        semester=semester,
        branch=branch,
        document_type=document_type,
        year=year,
        limit=limit
    )
    return [_sanitize_document_metadata(d) for d in docs]


@mcp.tool()
@audited("get_academic_document")
def get_academic_document(document_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve exact verified metadata and local file path for an academic document by its unique ID.
    """
    if not document_id or not str(document_id).strip():
        return None
    doc = _get_academic_document(document_id=str(document_id).strip())
    if not doc:
        return None
    return _sanitize_document_metadata(doc)


@mcp.tool()
@audited("get_academic_context")
def get_academic_context(
    student_id: Optional[str] = None,
    branch: Optional[str] = None,
    cycle: Optional[str] = None
) -> Dict[str, Any]:
    """
    Resolve multi-hop academic curriculum relationships connecting student, branch, curricular stream, cycle, enrolled subjects, and document counts.
    """
    return _get_academic_context(student_id=student_id, branch=branch, cycle=cycle)


@mcp.tool()
@audited("get_recommended_clubs")
def get_recommended_clubs(
    branch: Optional[str] = None,
    category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Search and recommend student clubs based on branch eligibility (branch_scope) and category.
    """
    return _get_recommended_clubs(branch=branch, category=category)


@mcp.tool()
@audited("lookup_principal")
def lookup_principal() -> Optional[Dict[str, Any]]:
    """
    Retrieve verified institutional details about the Principal of MSRIT.
    """
    return _get_principal_info()


@mcp.tool()
@audited("lookup_proctor")
def lookup_proctor() -> Optional[Dict[str, Any]]:
    """
    Retrieve verified institutional details about the Chief Proctor of MSRIT.
    """
    return _get_chief_proctor_info()


@mcp.tool()
@audited("lookup_campus_office")
def lookup_campus_office(query: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve verified office locations and campus administrative facilities.
    """
    return _lookup_office(query=query)


@mcp.tool()
@audited("get_entity_counts")
def get_entity_counts(entity_type: str = "branches") -> Dict[str, Any]:
    """
    Get authoritative counts and listings of branches, departments, or clubs.
    """
    if "club" in entity_type.lower():
        return {"entity_type": "clubs", "count": _get_club_count()}
    return {"entity_type": "branches", "count": _get_branch_count()}


if __name__ == "__main__":
    mcp.run(transport="stdio")


