import json
import os
import sys
from pathlib import Path
import pymupdf
import psycopg2
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Base project directory
BASE_DIR = Path(__file__).resolve().parent.parent

def load_env():
    env_path = BASE_DIR / '.env'
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())

load_env()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:msritdev@localhost:5432/msrit_ai")

def clean_text(text: str) -> str:
    """Remove null bytes that PostgreSQL rejects."""
    if not text:
        return ""
    return text.replace("\x00", "").replace("\u0000", "")

def ingest_data():
    metadata_path = BASE_DIR / "data" / "structured" / "first_year_metadata.json"
    if not metadata_path.exists():
        print(f"Error: Metadata file missing at {metadata_path}", file=sys.stderr)
        return

    with open(metadata_path, "r", encoding="utf-8") as f:
        meta_data = json.load(f)

    if isinstance(meta_data, list):
        raw_docs = meta_data
    elif isinstance(meta_data, dict):
        raw_docs = meta_data.get("documents") or meta_data.get("files") or []
    else:
        raw_docs = []

    docs_to_index = [
        d for d in raw_docs
        if not d.get("exclude_from_index", False) and not d.get("needs_ocr", False)
    ]
    print(f"Total documents to ingest: {len(docs_to_index)}")

    print("Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=70,
        separators=["\n\n", "\n", ". ", " ", ""]
    )

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("TRUNCATE TABLE notes_chunks;")
    conn.commit()

    total_chunks = 0

    for idx, doc in enumerate(docs_to_index, 1):
        rel_path = doc.get("file_path") or doc.get("path") or doc.get("local_path")
        if not rel_path:
            file_name = doc.get("file_name") or doc.get("name")
            if file_name:
                matches = list((BASE_DIR / "data" / "raw").glob(f"**/{file_name}"))
                if matches:
                    rel_path = str(matches[0].relative_to(BASE_DIR))
        
        if not rel_path:
            print(f"[{idx}/{len(docs_to_index)}] Skipping entry without valid file path: {doc.get('file_name', 'Unknown')}")
            continue

        full_path = BASE_DIR / rel_path
        if not full_path.exists():
            print(f"[{idx}/{len(docs_to_index)}] File not found: {rel_path}")
            continue

        text_content = ""
        try:
            pdf_doc = pymupdf.open(full_path)
            for page in pdf_doc:
                raw_page_text = page.get_text()
                text_content += clean_text(raw_page_text) + "\n"
            pdf_doc.close()
        except Exception as e:
            print(f"[{idx}/{len(docs_to_index)}] Error reading {Path(rel_path).name}: {e}")
            continue

        text_content = clean_text(text_content).strip()
        if not text_content:
            continue

        raw_chunks = text_splitter.split_text(text_content)
        chunks = [clean_text(c) for c in raw_chunks if clean_text(c).strip()]
        if not chunks:
            continue

        embeddings = model.encode(chunks, show_progress_bar=False, normalize_embeddings=True)

        streams_val = doc.get("streams") or doc.get("stream") or ""
        if isinstance(streams_val, list):
            streams_str = clean_text(", ".join(streams_val))
        else:
            streams_str = clean_text(str(streams_val))

        records = []
        for c_idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            records.append((
                clean_text(str(rel_path)),
                c_idx,
                chunk,
                emb.tolist(),
                streams_str,
                clean_text(str(doc.get("cycle", ""))),
                clean_text(str(doc.get("subject", ""))),
                clean_text(str(doc.get("doc_type", "notes"))),
                doc.get("unit"),
                clean_text(str(doc.get("source_url", "")))
            ))

        insert_sql = """
            INSERT INTO notes_chunks (
                file_path, chunk_index, content, embedding, 
                stream, cycle, subject, doc_type, unit, source_url
            ) VALUES %s
        """
        execute_values(cur, insert_sql, records, template="(%s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s)")
        conn.commit()

        total_chunks += len(chunks)
        print(f"[{idx}/{len(docs_to_index)}] {Path(rel_path).name}: {len(chunks)} chunks inserted.")

    cur.close()
    conn.close()
    print(f"\nIngestion complete! Total chunks indexed in PostgreSQL: {total_chunks}")

if __name__ == "__main__":
    ingest_data()