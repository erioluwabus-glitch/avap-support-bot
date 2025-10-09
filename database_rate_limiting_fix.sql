-- Database tables for rate limiting fixes
-- Run this SQL in your Supabase database

-- Table for distributed locks
CREATE TABLE IF NOT EXISTS distributed_locks (
    id SERIAL PRIMARY KEY,
    lock_key VARCHAR(255) UNIQUE NOT NULL,
    lock_token VARCHAR(255) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Table for cooldown states
CREATE TABLE IF NOT EXISTS cooldown_states (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) UNIQUE NOT NULL,
    next_allowed_time TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_distributed_locks_key ON distributed_locks(lock_key);
CREATE INDEX IF NOT EXISTS idx_distributed_locks_expires ON distributed_locks(expires_at);
CREATE INDEX IF NOT EXISTS idx_cooldown_states_key ON cooldown_states(key);
CREATE INDEX IF NOT EXISTS idx_cooldown_states_time ON cooldown_states(next_allowed_time);

-- Clean up old entries automatically (optional)
-- This will run every hour to clean up expired locks
CREATE OR REPLACE FUNCTION cleanup_expired_locks()
RETURNS void AS $$
BEGIN
    DELETE FROM distributed_locks WHERE expires_at < NOW();
    DELETE FROM cooldown_states WHERE next_allowed_time < NOW();
END;
$$ LANGUAGE plpgsql;
