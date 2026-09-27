import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from db.connection import get_connection

def apply_migration():
    conn = get_connection()
    cur = conn.cursor()
    with open('db/step8_conversations.sql', 'r', encoding='utf-8') as f:
        sql = f.read()
    cur.execute(sql)
    conn.commit()
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_name IN ('conversation_sessions', 'conversation_messages');
    """)
    tables = cur.fetchall()
    print('Verified tables:', tables)
    cur.close()
    conn.close()

if __name__ == '__main__':
    apply_migration()
