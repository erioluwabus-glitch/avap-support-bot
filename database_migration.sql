-- Database Migration Script
-- Add missing 'status' column to pending_verifications table

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

-- Verify the column was added
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'pending_verifications' 
ORDER BY ordinal_position;
