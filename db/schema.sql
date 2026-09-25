-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Table for document chunks and vector embeddings
CREATE TABLE IF NOT EXISTS notes_chunks (
    id SERIAL PRIMARY KEY,
    file_path TEXT NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(384),
    stream TEXT,
    cycle TEXT,
    subject TEXT,
    doc_type TEXT,
    unit INT,
    source_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast cosine similarity vector search
CREATE INDEX IF NOT EXISTS notes_chunks_embedding_idx 
ON notes_chunks USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Static campus knowledge tables
CREATE TABLE IF NOT EXISTS branches (
    code VARCHAR(10) PRIMARY KEY,
    name TEXT NOT NULL,
    stream TEXT NOT NULL,
    hod_name TEXT,
    location TEXT
);

CREATE TABLE IF NOT EXISTS clubs (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    lead_name TEXT,
    description TEXT
);

-- Persistent student profile memory
CREATE TABLE IF NOT EXISTS student_profile (
    student_id VARCHAR(50) PRIMARY KEY,
    name TEXT,
    college TEXT,
    degree TEXT,
    branch TEXT,
    semester INT,
    year INT,
    stream TEXT,
    cycle TEXT,
    cgpa NUMERIC(4,2),
    preferences JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Audited tool execution log (MCP compliance)
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    tool_name VARCHAR(100) NOT NULL,
    student_id VARCHAR(50),
    parameters JSONB,
    result_summary TEXT,
    success BOOLEAN DEFAULT TRUE
);
