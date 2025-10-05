-- =============================================
-- DATABASE VERIFICATION SCRIPT
-- =============================================
-- Run this to verify your database setup is complete

-- 1. Check all required tables exist
SELECT
    schemaname,
    tablename,
    tableowner
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('pending_verifications', 'verified_users', 'assignments', 'wins', 'questions', 'faqs', 'tips', 'match_requests')
ORDER BY tablename;

-- 2. Verify key columns exist in each table
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

SELECT '✅ tips has tip_type column' as check_result
WHERE EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'tips' AND column_name = 'tip_type'
);

-- 3. Check data counts
SELECT '📊 pending_verifications' as table_name, COUNT(*) as record_count FROM pending_verifications;
SELECT '📊 verified_users' as table_name, COUNT(*) as record_count FROM verified_users;
SELECT '📊 assignments' as table_name, COUNT(*) as record_count FROM assignments;
SELECT '📊 wins' as table_name, COUNT(*) as record_count FROM wins;
SELECT '📊 questions' as table_name, COUNT(*) as record_count FROM questions;
SELECT '📊 faqs' as table_name, COUNT(*) as record_count FROM faqs;
SELECT '📊 tips' as table_name, COUNT(*) as record_count FROM tips;
SELECT '📊 match_requests' as table_name, COUNT(*) as record_count FROM match_requests;

-- 4. Verify sample data was inserted
SELECT '📝 Sample FAQs inserted' as info, COUNT(*) as count FROM faqs WHERE question LIKE 'How do I%';
SELECT '📝 Daily tips inserted' as info, COUNT(*) as count FROM tips WHERE tip_text LIKE '%-%';

-- 5. Check security policies are in place
SELECT
    schemaname,
    tablename,
    policyname,
    permissive,
    roles,
    cmd,
    qual
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;
