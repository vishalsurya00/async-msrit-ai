-- Step 5: Lightweight Knowledge / Relationship Layer Schema
-- Connects Student, Branch, Curricular Stream, Cycle, Subject, Academic Documents, and Clubs.
-- Authoritative source of truth: PostgreSQL.
-- Safe to run repeatedly (idempotent).

-- 1. Canonical Subjects Table
CREATE TABLE IF NOT EXISTS subjects (
    code VARCHAR(20) PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    semester INTEGER DEFAULT 1,
    default_cycle TEXT,
    description TEXT
);

-- 2. Curricular Stream & Branch Relationship Table
CREATE TABLE IF NOT EXISTS stream_branches (
    stream_name TEXT NOT NULL,
    branch_code VARCHAR(20) NOT NULL REFERENCES branches(code) ON DELETE CASCADE,
    PRIMARY KEY (stream_name, branch_code)
);

-- 3. Curricular Stream, Cycle & Subject Relationship Table
CREATE TABLE IF NOT EXISTS stream_subjects (
    stream_name TEXT NOT NULL,
    cycle TEXT NOT NULL,
    subject_code VARCHAR(20) NOT NULL REFERENCES subjects(code) ON DELETE CASCADE,
    PRIMARY KEY (stream_name, cycle, subject_code)
);

-- 4. Add branch_scope to clubs for branch-aware club recommendations
ALTER TABLE clubs ADD COLUMN IF NOT EXISTS branch_scope TEXT DEFAULT 'All branches';

-- Helpful performance indexes for relationship traversals
CREATE INDEX IF NOT EXISTS idx_stream_branches_branch ON stream_branches(branch_code);
CREATE INDEX IF NOT EXISTS idx_stream_subjects_lookup ON stream_subjects(stream_name, cycle);
CREATE INDEX IF NOT EXISTS idx_academic_docs_subj_unit ON academic_documents(subject, unit);
