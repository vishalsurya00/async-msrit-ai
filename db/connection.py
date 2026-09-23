import os
import sys
from pathlib import Path
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Load .env manually to avoid unnecessary dependencies
def load_env():
    env_path = Path(__file__).resolve().parent.parent / '.env'
    if env_path.exists():
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())

load_env()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:msritdev@localhost:5432/msrit_ai")

def get_connection():
    """Returns a fresh psycopg2 connection using the configured DATABASE_URL."""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    print(f"Connecting to database: {DATABASE_URL}")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # Check pgvector extension
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector';")
        has_vector = cur.fetchone()
        
        schema_path = Path(__file__).resolve().parent / "schema.sql"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        cur.execute(schema_sql)
        print("Schema successfully applied!")

        # Verify tables created
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public';
        """)
        tables = [row[0] for row in cur.fetchall()]
        print(f"Tables verified: {tables}")
        
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Database setup error: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    success = init_db()
    if not success:
        sys.exit(1)
