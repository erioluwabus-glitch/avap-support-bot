-- Database Migration Script
-- Add missing 'status' column to pending_verifications table and ensure FAQs table exists

-- Check if the status column exists, if not add it
DO $$
BEGIN
    -- Check if the status column exists
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'pending_verifications'
        AND column_name = 'status'
    ) THEN
        -- Add the status column
        ALTER TABLE pending_verifications
        ADD COLUMN status TEXT DEFAULT 'Pending';

        -- Update existing records to have 'Pending' status
        UPDATE pending_verifications
        SET status = 'Pending'
        WHERE status IS NULL;

        RAISE NOTICE 'Added status column to pending_verifications table';
    ELSE
        RAISE NOTICE 'Status column already exists in pending_verifications table';
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

-- Verify the tables and columns
SELECT 'pending_verifications' as table_name, column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'pending_verifications'
ORDER BY ordinal_position;

SELECT 'faqs' as table_name, COUNT(*) as record_count
FROM faqs;
