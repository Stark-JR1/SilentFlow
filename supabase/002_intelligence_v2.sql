-- Intelligence v2: User Profile + Alert Engine
-- This migration adds tables for user behavior profiling and intelligent alerts

-- User Behavior Profile table
-- Stores consolidated user financial behavior metrics
CREATE TABLE IF NOT EXISTS user_behavior_profile (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    avg_monthly_income DECIMAL(15,2) DEFAULT 0,
    avg_monthly_expense DECIMAL(15,2) DEFAULT 0,
    avg_monthly_savings DECIMAL(15,2) DEFAULT 0,
    avg_transaction_value DECIMAL(15,2) DEFAULT 0,
    recurring_transactions_count INTEGER DEFAULT 0,
    active_months_count INTEGER DEFAULT 0,
    top_category_id UUID REFERENCES categories(id),
    top_category_share DECIMAL(5,2) DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- User Category Behavior table
-- Stores detailed category usage patterns per user
CREATE TABLE IF NOT EXISTS user_category_behavior (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    category_id UUID NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    total_transactions INTEGER DEFAULT 0,
    total_amount DECIMAL(15,2) DEFAULT 0,
    avg_transaction_value DECIMAL(15,2) DEFAULT 0,
    monthly_avg DECIMAL(15,2) DEFAULT 0,
    usage_percentage DECIMAL(5,2) DEFAULT 0,
    last_transaction_date DATE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, category_id)
);

-- Intelligence Alerts table
-- Stores generated intelligent alerts for users
CREATE TABLE IF NOT EXISTS intelligence_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL, -- category_spike, unusual_transaction, low_savings_rate, high_card_usage
    severity VARCHAR(20) NOT NULL DEFAULT 'info', -- info, warning, critical
    title VARCHAR(200) NOT NULL,
    message TEXT NOT NULL,
    reference_date DATE,
    reference_month DATE, -- normalized month start (YYYY-MM-01)
    amount DECIMAL(15,2),
    is_read BOOLEAN DEFAULT FALSE,
    is_dismissed BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '30 days')
);

ALTER TABLE intelligence_alerts
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

ALTER TABLE intelligence_alerts
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE DEFAULT (NOW() + INTERVAL '30 days');

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'intelligence_alerts'
          AND column_name = 'reference_month'
          AND data_type <> 'date'
    ) THEN
        ALTER TABLE intelligence_alerts
            ALTER COLUMN reference_month TYPE DATE
            USING CASE
                WHEN reference_month IS NULL OR btrim(reference_month::text) = '' THEN NULL
                WHEN reference_month::text ~ '^\d{4}-\d{2}$' THEN to_date(reference_month::text || '-01', 'YYYY-MM-DD')
                ELSE reference_month::text::date
            END;
    END IF;
END;
$$;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_user_behavior_profile_user_id ON user_behavior_profile(user_id);
CREATE INDEX IF NOT EXISTS idx_user_category_behavior_user_id ON user_category_behavior(user_id);
CREATE INDEX IF NOT EXISTS idx_user_category_behavior_category_id ON user_category_behavior(category_id);
CREATE INDEX IF NOT EXISTS idx_intelligence_alerts_user_id ON intelligence_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_intelligence_alerts_type ON intelligence_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_intelligence_alerts_severity ON intelligence_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_intelligence_alerts_created_at ON intelligence_alerts(created_at);
CREATE INDEX IF NOT EXISTS idx_intelligence_alerts_expires_at ON intelligence_alerts(expires_at);

-- Row Level Security (RLS) policies
ALTER TABLE user_behavior_profile ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_category_behavior ENABLE ROW LEVEL SECURITY;
ALTER TABLE intelligence_alerts ENABLE ROW LEVEL SECURITY;

-- RLS policies for user_behavior_profile
CREATE POLICY "Users can view their own behavior profile" ON user_behavior_profile
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own behavior profile" ON user_behavior_profile
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own behavior profile" ON user_behavior_profile
    FOR UPDATE USING (auth.uid() = user_id);

-- RLS policies for user_category_behavior
CREATE POLICY "Users can view their own category behavior" ON user_category_behavior
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own category behavior" ON user_category_behavior
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own category behavior" ON user_category_behavior
    FOR UPDATE USING (auth.uid() = user_id);

-- RLS policies for intelligence_alerts
CREATE POLICY "Users can view their own alerts" ON intelligence_alerts
    FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own alerts" ON intelligence_alerts
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update their own alerts" ON intelligence_alerts
    FOR UPDATE USING (auth.uid() = user_id);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
CREATE TRIGGER update_user_behavior_profile_updated_at
    BEFORE UPDATE ON user_behavior_profile
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_category_behavior_updated_at
    BEFORE UPDATE ON user_category_behavior
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_intelligence_alerts_updated_at ON intelligence_alerts;
CREATE TRIGGER update_intelligence_alerts_updated_at
    BEFORE UPDATE ON intelligence_alerts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Function to automatically clean up expired alerts
CREATE OR REPLACE FUNCTION cleanup_expired_alerts()
RETURNS void AS $$
BEGIN
    DELETE FROM intelligence_alerts
    WHERE expires_at < NOW() AND is_dismissed = TRUE;
END;
$$ LANGUAGE plpgsql;

-- Create a scheduled job to run cleanup (this would be done via pg_cron in production)
-- For now, we'll just create the function that can be called manually or via cron
