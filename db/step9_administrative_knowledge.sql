-- Step 9: Administrative and Institutional Knowledge Schema
-- Authoritative persistent storage for Principal, Chief Proctor, Campus Offices, and Buildings.

CREATE TABLE IF NOT EXISTS institutional_entities (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    role TEXT,
    additional_role TEXT,
    office_location TEXT,
    building TEXT,
    floor TEXT,
    email TEXT,
    education TEXT,
    joined TEXT,
    description TEXT,
    source_url TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_inst_entities_type ON institutional_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_inst_entities_building ON institutional_entities(building);

-- Seed verified persistent institutional data

-- 1. Principal
INSERT INTO institutional_entities (
    entity_type, entity_key, name, role, office_location, building, floor, email, education, joined, description, source_url
) VALUES (
    'principal',
    'principal',
    'Dr. B. Sathish Babu',
    'Professor and Principal, M.S. Ramaiah Institute of Technology (MSRIT)',
    'Ground Floor, Apex Block',
    'Apex Block',
    'Ground Floor',
    'principal@msrit.edu',
    'Ph.D. from the Indian Institute of Science (IISc), Bangalore',
    'June 2026',
    'Professor and Principal, M.S. Ramaiah Institute of Technology (MSRIT)',
    'https://www.msrit.edu/gb/principal.html'
) ON CONFLICT (entity_key) DO UPDATE SET
    name = EXCLUDED.name,
    role = EXCLUDED.role,
    office_location = EXCLUDED.office_location,
    building = EXCLUDED.building,
    floor = EXCLUDED.floor,
    email = EXCLUDED.email,
    education = EXCLUDED.education,
    joined = EXCLUDED.joined,
    description = EXCLUDED.description,
    source_url = EXCLUDED.source_url;

-- 2. Chief Proctor
INSERT INTO institutional_entities (
    entity_type, entity_key, name, role, additional_role, office_location, building, floor, description, source_url
) VALUES (
    'proctor',
    'chief_proctor',
    'Dr. Monica R. Mundada',
    'Chief Proctor, M.S. Ramaiah Institute of Technology',
    'Professor, Department of Computer Science and Engineering',
    '1st Floor, Apex Block',
    'Apex Block',
    '1st Floor',
    'Oversees student academic and administrative progress through the Proctorial System.',
    'https://www.msrit.edu/support/proctorial-system.html'
) ON CONFLICT (entity_key) DO UPDATE SET
    name = EXCLUDED.name,
    role = EXCLUDED.role,
    additional_role = EXCLUDED.additional_role,
    office_location = EXCLUDED.office_location,
    building = EXCLUDED.building,
    floor = EXCLUDED.floor,
    description = EXCLUDED.description,
    source_url = EXCLUDED.source_url;

-- 3. Apex Block Offices
INSERT INTO institutional_entities (entity_type, entity_key, name, role, office_location, building, floor, source_url)
VALUES 
    ('office', 'office_principal', 'Principal''s Office', 'Office of the Principal', 'Ground Floor, Apex Block', 'Apex Block', 'Ground Floor', 'https://www.msrit.edu/gb/principal.html'),
    ('office', 'office_account', 'Account Section', 'Financial and Accounts Office', 'Ground Floor, Apex Block', 'Apex Block', 'Ground Floor', 'https://www.msrit.edu/gb/principal.html'),
    ('office', 'office_scholarship', 'Scholarship Section', 'Student Scholarship Office', 'Ground Floor, Apex Block', 'Apex Block', 'Ground Floor', 'https://www.msrit.edu/gb/principal.html'),
    ('office', 'office_registrar', 'Registrar Office', 'Office of the Registrar', 'Ground Floor, Apex Block', 'Apex Block', 'Ground Floor', 'https://www.msrit.edu/gb/principal.html'),
    ('office', 'office_proctor', 'Chief Proctor''s Office', 'Office of the Chief Proctor', '1st Floor, Apex Block', 'Apex Block', '1st Floor', 'https://www.msrit.edu/support/proctorial-system.html')
ON CONFLICT (entity_key) DO UPDATE SET
    name = EXCLUDED.name,
    role = EXCLUDED.role,
    office_location = EXCLUDED.office_location,
    building = EXCLUDED.building,
    floor = EXCLUDED.floor,
    source_url = EXCLUDED.source_url;

-- 4. Apex Block Building
INSERT INTO institutional_entities (entity_type, entity_key, name, role, office_location, building, floor, description, source_url, metadata)
VALUES (
    'building',
    'building_apex',
    'Apex Block',
    'Administrative and Academic Block',
    'Apex Block',
    'Apex Block',
    'Ground Floor',
    'Administrative facility housing executive offices and academic departments.',
    'https://www.msrit.edu/gb/principal.html',
    '{
        "ground_floor": ["Principal''s Office", "Account Section", "Scholarship Section", "Registrar Office"],
        "first_floor": ["Chief Proctor''s Office"]
    }'::jsonb
) ON CONFLICT (entity_key) DO UPDATE SET
    metadata = EXCLUDED.metadata;

-- Fix typo in ECE location if present
UPDATE branches 
SET location = 'DES Block, 2nd Floor' 
WHERE code = 'ECE' AND (location ILIKE '%2th%' OR location ILIKE '%2nd%');
