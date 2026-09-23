"""
Search module for MSRIT AI.
Performs semantic vector search across notes_chunks using pgvector and all-MiniLM-L6-v2.
"""
from typing import Optional, List, Dict, Any
import sys
from sentence_transformers import SentenceTransformer
from db.connection import get_connection

# Load embedding model once at module level for optimal performance
model = SentenceTransformer("all-MiniLM-L6-v2")


def search_notes(
    query: str,
    stream: Optional[str] = None,
    cycle: Optional[str] = None,
    subject: Optional[str] = None,
    top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    Search notes_chunks using pgvector cosine distance operator (<=>).
    Pre-filters by stream, cycle, and subject using ILIKE if provided.
    Returns a list of dicts with content, similarity, and metadata.
    """
    if not query or not query.strip():
        return []

    try:
        # Encode query to 384-dimensional vector
        query_embedding = model.encode(query.strip(), normalize_embeddings=True).tolist()
        emb_str = f"[{','.join(str(x) for x in query_embedding)}]"

        where_clauses = []
        filter_params = []

        if stream and stream.strip():
            s_val = stream.strip()
            where_clauses.append("(stream ILIKE %s OR stream ILIKE %s)")
            filter_params.extend([s_val, f"%{s_val}%"])

        if cycle and cycle.strip():
            c_val = cycle.strip()
            where_clauses.append("(cycle ILIKE %s OR cycle ILIKE %s)")
            filter_params.extend([c_val, f"%{c_val}%"])

        if subject and subject.strip():
            sub_val = subject.strip()
            where_clauses.append("(subject ILIKE %s OR file_path ILIKE %s)")
            filter_params.extend([sub_val, f"%{sub_val}%"])

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        sql = f"""
            SELECT 
                content,
                (embedding <=> %s::vector) AS distance,
                stream,
                cycle,
                subject,
                doc_type,
                source_url,
                file_path
            FROM notes_chunks
            {where_sql}
            ORDER BY distance ASC
            LIMIT %s;
        """

        conn = get_connection()
        cur = conn.cursor()
        query_args = [emb_str] + filter_params + [top_k]
        cur.execute(sql, query_args)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        results = []
        for row in rows:
            content, distance, st, cy, sub, doc_type, source_url, file_path = row
            dist_val = float(distance) if distance is not None else 1.0
            similarity = max(0.0, 1.0 - dist_val)
            results.append({
                "content": content,
                "similarity": round(similarity, 4),
                "stream": st or "",
                "cycle": cy or "",
                "subject": sub or "",
                "doc_type": doc_type or "",
                "source_url": source_url or "",
                "file_path": file_path or ""
            })
        return results

    except Exception as e:
        print(f"Error in search_notes: {e}", file=sys.stderr)
        return []
