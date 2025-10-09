-- Final database fix for all missing tables
-- Run this SQL in your Supabase database

-- Create cooldown_states table
CREATE TABLE IF NOT EXISTS public.cooldown_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE NOT NULL,
    next_allowed_time TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create distributed_locks table
CREATE TABLE IF NOT EXISTS public.distributed_locks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lock_key TEXT UNIQUE NOT NULL,
    lock_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_cooldown_states_key ON public.cooldown_states(key);
CREATE INDEX IF NOT EXISTS idx_cooldown_states_time ON public.cooldown_states(next_allowed_time);
CREATE INDEX IF NOT EXISTS idx_distributed_locks_key ON public.distributed_locks(lock_key);
CREATE INDEX IF NOT EXISTS idx_distributed_locks_expires ON public.distributed_locks(expires_at);

-- Reload schema cache
NOTIFY pgrst, 'reload schema';
