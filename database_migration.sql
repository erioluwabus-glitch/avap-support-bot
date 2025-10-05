-- =============================================
-- COMPLETE AVAP SUPPORT BOT DATABASE SETUP
-- =============================================
-- This script creates a fresh, complete database setup
-- Run this after deleting all existing queries
-- WARNING: This will create tables but preserve existing data if tables exist

-- Drop existing tables if they exist (CAUTION: This deletes data!)
-- Uncomment the lines below if you want to start completely fresh:
/*
DROP TABLE IF EXISTS tips CASCADE;
DROP TABLE IF EXISTS faqs CASCADE;
DROP TABLE IF EXISTS questions CASCADE;
DROP TABLE IF EXISTS wins CASCADE;
DROP TABLE IF EXISTS assignments CASCADE;
DROP TABLE IF EXISTS match_requests CASCADE;
DROP TABLE IF EXISTS verified_users CASCADE;
DROP TABLE IF EXISTS pending_verifications CASCADE;
*/

-- =============================================
-- TABLE CREATION
-- =============================================

-- 1. Pending verifications table
CREATE TABLE IF NOT EXISTS pending_verifications (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'Pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Verified users table
CREATE TABLE IF NOT EXISTS verified_users (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    telegram_id BIGINT UNIQUE,
    status TEXT DEFAULT 'verified',
    badge TEXT DEFAULT 'New Student',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Assignments table
CREATE TABLE IF NOT EXISTS assignments (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    username TEXT NOT NULL,
    telegram_id BIGINT NOT NULL,
    module TEXT NOT NULL,
    submission_type TEXT NOT NULL,
    file_id TEXT,
    file_name TEXT,
    grade INTEGER,
    comments TEXT,
    status TEXT DEFAULT 'submitted',
    submitted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    graded_at TIMESTAMP WITH TIME ZONE
);

-- 4. Wins table
CREATE TABLE IF NOT EXISTS wins (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    username TEXT NOT NULL,
    telegram_id BIGINT NOT NULL,
    win_type TEXT NOT NULL,
    file_id TEXT,
    file_name TEXT,
    shared_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 5. Questions table
CREATE TABLE IF NOT EXISTS questions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    username TEXT NOT NULL,
    telegram_id BIGINT NOT NULL,
    question_text TEXT NOT NULL,
    file_id TEXT,
    file_name TEXT,
    answer TEXT,
    status TEXT DEFAULT 'pending',
    asked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    answered_at TIMESTAMP WITH TIME ZONE
);

-- 6. FAQs table for AI matching
CREATE TABLE IF NOT EXISTS faqs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 7. Tips table for daily tips
CREATE TABLE IF NOT EXISTS tips (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tip_text TEXT NOT NULL,
    day_of_week INTEGER NOT NULL, -- 0=Sunday, 1=Monday, etc.
    is_manual BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 8. Match requests table
CREATE TABLE IF NOT EXISTS match_requests (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    username TEXT,
    match_id TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Now add missing columns to existing tables (only if they don't exist)
-- Note: Since we used CREATE TABLE IF NOT EXISTS, most columns should already be there
-- But we'll add any missing ones for backward compatibility

DO $$
BEGIN
    -- Check if status column exists in pending_verifications
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'pending_verifications'
        AND column_name = 'status'
    ) THEN
        ALTER TABLE pending_verifications ADD COLUMN status TEXT DEFAULT 'Pending';
        RAISE NOTICE 'Added status column to pending_verifications table';
    END IF;

    -- Check if username column exists in verified_users
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'verified_users'
        AND column_name = 'username'
    ) THEN
        ALTER TABLE verified_users ADD COLUMN username TEXT;
        RAISE NOTICE 'Added username column to verified_users table';
    END IF;

    -- Check if comment column exists in assignments (note: we already have comments column in schema)
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'assignments'
        AND column_name = 'comment'
    ) THEN
        ALTER TABLE assignments ADD COLUMN comment TEXT;
        RAISE NOTICE 'Added comment column to assignments table';
    END IF;

    -- Check if tip_type column exists in tips (note: we already have is_manual in schema)
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'tips'
        AND column_name = 'tip_type'
    ) THEN
        ALTER TABLE tips ADD COLUMN tip_type TEXT DEFAULT 'auto';
        RAISE NOTICE 'Added tip_type column to tips table';
    END IF;
END $$;

-- Create FAQs table if it doesn't exist
DO $$
BEGIN
    -- Check if the faqs table exists
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = 'faqs'
    ) THEN
        -- Create the FAQs table
        CREATE TABLE faqs (
            id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        -- Insert sample FAQs
        INSERT INTO faqs (question, answer, category) VALUES
        ('How do I submit an assignment?', 'Use the "Submit Assignment" button in the bot menu, select your module, choose the type (text/audio/video), and send your work.', 'submission'),
        ('What modules are available?', 'There are 12 modules in the AVAP course. You can submit assignments for any module from 1-12.', 'course'),
        ('How do I check my progress?', 'Use the "Check Status" button to see your assignments, wins, and progress toward the Top Student badge.', 'progress'),
        ('How do I share a win?', 'Use the "Share Win" button to motivate other students with your success story.', 'community'),
        ('How do I ask a question?', 'Use the "Ask Question" button to get help from the support team.', 'support');

        -- Enable Row Level Security
        ALTER TABLE faqs ENABLE ROW LEVEL SECURITY;

        -- Create policy
        CREATE POLICY "Allow all operations" ON faqs FOR ALL USING (true);

        RAISE NOTICE 'Created faqs table with sample data';
    ELSE
        RAISE NOTICE 'faqs table already exists';
    END IF;
END $$;

-- Insert sample FAQs if table is empty
INSERT INTO faqs (question, answer, category)
SELECT
    'How do I submit an assignment?',
    'Use the "Submit Assignment" button in the bot menu, select your module, choose the type (text/audio/video), and send your work.',
    'submission'
WHERE NOT EXISTS (SELECT 1 FROM faqs WHERE question = 'How do I submit an assignment?');

INSERT INTO faqs (question, answer, category)
SELECT
    'What modules are available?',
    'There are 12 modules in the AVAP course. You can submit assignments for any module from 1-12.',
    'course'
WHERE NOT EXISTS (SELECT 1 FROM faqs WHERE question = 'What modules are available?');

INSERT INTO faqs (question, answer, category)
SELECT
    'How do I check my progress?',
    'Use the "Check Status" button to see your assignments, wins, and progress toward the Top Student badge.',
    'progress'
WHERE NOT EXISTS (SELECT 1 FROM faqs WHERE question = 'How do I check my progress?');

INSERT INTO faqs (question, answer, category)
SELECT
    'How do I share a win?',
    'Use the "Share Win" button to motivate other students with your success story.',
    'community'
WHERE NOT EXISTS (SELECT 1 FROM faqs WHERE question = 'How do I share a win?');

INSERT INTO faqs (question, answer, category)
SELECT
    'How do I ask a question?',
    'Use the "Ask Question" button to get help from the support team.',
    'support'
WHERE NOT EXISTS (SELECT 1 FROM faqs WHERE question = 'How do I ask a question?');

-- Insert sample tips for each day (only if tips table is empty)
INSERT INTO tips (tip_text, day_of_week, is_manual)
SELECT 'Success is not final, failure is not fatal: it is the courage to continue that counts. - Winston Churchill', 0, FALSE
WHERE NOT EXISTS (SELECT 1 FROM tips WHERE day_of_week = 0);

INSERT INTO tips (tip_text, day_of_week, is_manual)
SELECT 'The only way to do great work is to love what you do. - Steve Jobs', 1, FALSE
WHERE NOT EXISTS (SELECT 1 FROM tips WHERE day_of_week = 1);

INSERT INTO tips (tip_text, day_of_week, is_manual)
SELECT 'Believe you can and you''re halfway there. - Theodore Roosevelt', 2, FALSE
WHERE NOT EXISTS (SELECT 1 FROM tips WHERE day_of_week = 2);

INSERT INTO tips (tip_text, day_of_week, is_manual)
SELECT 'The future belongs to those who believe in the beauty of their dreams. - Eleanor Roosevelt', 3, FALSE
WHERE NOT EXISTS (SELECT 1 FROM tips WHERE day_of_week = 3);

INSERT INTO tips (tip_text, day_of_week, is_manual)
SELECT 'It is during our darkest moments that we must focus to see the light. - Aristotle', 4, FALSE
WHERE NOT EXISTS (SELECT 1 FROM tips WHERE day_of_week = 4);

INSERT INTO tips (tip_text, day_of_week, is_manual)
SELECT 'The way to get started is to quit talking and begin doing. - Walt Disney', 5, FALSE
WHERE NOT EXISTS (SELECT 1 FROM tips WHERE day_of_week = 5);

INSERT INTO tips (tip_text, day_of_week, is_manual)
SELECT 'Don''t be pushed around by the fears in your mind. Be led by the dreams in your heart. - Roy T. Bennett', 6, FALSE
WHERE NOT EXISTS (SELECT 1 FROM tips WHERE day_of_week = 6);

-- Create indexes for better performance (only if they don't exist)
CREATE INDEX IF NOT EXISTS idx_verified_users_telegram_id ON verified_users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_verified_users_email ON verified_users(email);
CREATE INDEX IF NOT EXISTS idx_assignments_username ON assignments(username);
CREATE INDEX IF NOT EXISTS idx_assignments_status ON assignments(status);
CREATE INDEX IF NOT EXISTS idx_match_requests_status ON match_requests(status);
CREATE INDEX IF NOT EXISTS idx_tips_day_of_week ON tips(day_of_week);

-- Enable Row Level Security (RLS) if not already enabled
ALTER TABLE IF EXISTS pending_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS verified_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS match_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS wins ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS faqs ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS tips ENABLE ROW LEVEL SECURITY;

-- Create policies (allow all for now - adjust based on your security needs)
DROP POLICY IF EXISTS "Allow all operations" ON pending_verifications;
CREATE POLICY "Allow all operations" ON pending_verifications FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all operations" ON verified_users;
CREATE POLICY "Allow all operations" ON verified_users FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all operations" ON match_requests;
CREATE POLICY "Allow all operations" ON match_requests FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all operations" ON assignments;
CREATE POLICY "Allow all operations" ON assignments FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all operations" ON wins;
CREATE POLICY "Allow all operations" ON wins FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all operations" ON questions;
CREATE POLICY "Allow all operations" ON questions FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all operations" ON faqs;
CREATE POLICY "Allow all operations" ON faqs FOR ALL USING (true);

DROP POLICY IF EXISTS "Allow all operations" ON tips;
CREATE POLICY "Allow all operations" ON tips FOR ALL USING (true);

-- =============================================
-- VERIFICATION QUERIES
-- =============================================

-- Check that all tables were created successfully
SELECT
    schemaname,
    tablename,
    tableowner
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('pending_verifications', 'verified_users', 'assignments', 'wins', 'questions', 'faqs', 'tips', 'match_requests')
ORDER BY tablename;

-- Verify key columns exist
SELECT '✅ pending_verifications has status column' as check_result
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'pending_verifications' AND column_name = 'status'
);

SELECT '✅ verified_users has username column' as check_result
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'verified_users' AND column_name = 'username'
);

SELECT '✅ assignments has comment column' as check_result
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'assignments' AND column_name = 'comment'
);

-- Count records in key tables
SELECT 'FAQs inserted:' as info, COUNT(*) as count FROM faqs;
SELECT 'Tips inserted:' as info, COUNT(*) as count FROM tips;
