-- AVAP Support Bot Database Schema
-- Run this in your Supabase SQL editor

-- Pending verifications table
CREATE TABLE IF NOT EXISTS pending_verifications (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    phone TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'Pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Verified users table
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

-- Match requests table
CREATE TABLE IF NOT EXISTS match_requests (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    match_id TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Assignments table
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

-- Wins table
CREATE TABLE IF NOT EXISTS wins (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    username TEXT NOT NULL,
    telegram_id BIGINT NOT NULL,
    win_type TEXT NOT NULL,
    file_id TEXT,
    file_name TEXT,
    shared_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Questions table
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

-- FAQs table for AI matching
CREATE TABLE IF NOT EXISTS faqs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tips table for daily tips
CREATE TABLE IF NOT EXISTS tips (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tip_text TEXT NOT NULL,
    day_of_week INTEGER NOT NULL, -- 0=Sunday, 1=Monday, etc.
    is_manual BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert some sample FAQs
INSERT INTO faqs (question, answer, category) VALUES
('How do I submit an assignment?', 'Use the "Submit Assignment" button in the bot menu, select your module, choose the type (text/audio/video), and send your work.', 'submission'),
('What modules are available?', 'There are 12 modules in the AVAP course. You can submit assignments for any module from 1-12.', 'course'),
('How do I check my progress?', 'Use the "Check Status" button to see your assignments, wins, and progress toward the Top Student badge.', 'progress'),
('How do I share a win?', 'Use the "Share Win" button to motivate other students with your success story.', 'community'),
('How do I ask a question?', 'Use the "Ask Question" button to get help from the support team.', 'support');

-- Insert sample tips for each day
INSERT INTO tips (tip_text, day_of_week, is_manual) VALUES
('Success is not final, failure is not fatal: it is the courage to continue that counts. - Winston Churchill', 0, FALSE),
('The only way to do great work is to love what you do. - Steve Jobs', 1, FALSE),
('Believe you can and you''re halfway there. - Theodore Roosevelt', 2, FALSE),
('The future belongs to those who believe in the beauty of their dreams. - Eleanor Roosevelt', 3, FALSE),
('It is during our darkest moments that we must focus to see the light. - Aristotle', 4, FALSE),
('The way to get started is to quit talking and begin doing. - Walt Disney', 5, FALSE),
('Don''t be pushed around by the fears in your mind. Be led by the dreams in your heart. - Roy T. Bennett', 6, FALSE);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_verified_users_telegram_id ON verified_users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_verified_users_email ON verified_users(email);
CREATE INDEX IF NOT EXISTS idx_assignments_username ON assignments(username);
CREATE INDEX IF NOT EXISTS idx_assignments_status ON assignments(status);
CREATE INDEX IF NOT EXISTS idx_match_requests_status ON match_requests(status);
CREATE INDEX IF NOT EXISTS idx_tips_day_of_week ON tips(day_of_week);

-- Enable Row Level Security (RLS)
ALTER TABLE pending_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE verified_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE wins ENABLE ROW LEVEL SECURITY;
ALTER TABLE questions ENABLE ROW LEVEL SECURITY;
ALTER TABLE faqs ENABLE ROW LEVEL SECURITY;
ALTER TABLE tips ENABLE ROW LEVEL SECURITY;

-- Create policies (allow all for now - adjust based on your security needs)
CREATE POLICY "Allow all operations" ON pending_verifications FOR ALL USING (true);
CREATE POLICY "Allow all operations" ON verified_users FOR ALL USING (true);
CREATE POLICY "Allow all operations" ON match_requests FOR ALL USING (true);
CREATE POLICY "Allow all operations" ON assignments FOR ALL USING (true);
CREATE POLICY "Allow all operations" ON wins FOR ALL USING (true);
CREATE POLICY "Allow all operations" ON questions FOR ALL USING (true);
CREATE POLICY "Allow all operations" ON faqs FOR ALL USING (true);
CREATE POLICY "Allow all operations" ON tips FOR ALL USING (true);
