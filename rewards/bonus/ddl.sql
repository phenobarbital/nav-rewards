-- ============================================================================
-- NAV-Rewards: Prize Marketplace & Redemption System
-- ============================================================================
-- This DDL creates the infrastructure for:
--   1. Prize Catalog (Marketplace) - Catalog of redeemable prizes
--   2. Prize Awards - Prizes awarded to users (optionally with badges)
--   3. Prize Redemptions - Redemption tracking with full audit trail
--   4. Mystery Box Events - Random prize distribution system
-- ============================================================================

-- ============================================================================
-- PRIZE CATALOG TABLES
-- ============================================================================

-- Prize Categories (physical, digital, experience, etc.)
CREATE TABLE IF NOT EXISTS rewards.prize_categories (
    category_id SERIAL PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    icon VARCHAR(500),
    display_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Initial prize categories
INSERT INTO rewards.prize_categories (category_name, description, display_order) VALUES
    ('Gift Cards', 'Digital and physical gift cards', 1),
    ('Merchandise', 'Company branded merchandise and swag', 2),
    ('Experiences', 'Experiences like extra PTO, lunch with executives, etc.', 3),
    ('Digital Rewards', 'Digital content, subscriptions, etc.', 4),
    ('Mystery Box', 'Random surprise prizes', 5),
    ('Charitable', 'Donations to charities on behalf of employee', 6)
ON CONFLICT (category_name) DO NOTHING;

-- Prize Tiers (determines rarity/value)
CREATE TABLE IF NOT EXISTS rewards.prize_tiers (
    tier_id SERIAL PRIMARY KEY,
    tier_name VARCHAR(50) NOT NULL UNIQUE,
    tier_level INT NOT NULL UNIQUE,  -- 1=common, 5=legendary
    description TEXT,
    color_code VARCHAR(7),  -- Hex color for UI
    drop_rate DECIMAL(5,4) DEFAULT 0.2000,  -- Probability for mystery boxes
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Initial prize tiers
INSERT INTO rewards.prize_tiers (tier_name, tier_level, description, color_code, drop_rate) VALUES
    ('Common', 1, 'Frequently available prizes', '#9E9E9E', 0.4000),
    ('Uncommon', 2, 'Less common, slightly better value', '#4CAF50', 0.3000),
    ('Rare', 3, 'Rare and valuable prizes', '#2196F3', 0.1800),
    ('Epic', 4, 'Very rare, high-value prizes', '#9C27B0', 0.0900),
    ('Legendary', 5, 'Extremely rare, premium prizes', '#FF9800', 0.0300)
ON CONFLICT (tier_name) DO NOTHING;

-- Prize Catalog (Main marketplace table)
CREATE TABLE IF NOT EXISTS rewards.prize_catalog (
    prize_id BIGSERIAL PRIMARY KEY,

    -- Basic Info
    prize_name VARCHAR(255) NOT NULL,
    description TEXT,
    short_description VARCHAR(500),

    -- Categorization
    category_id INT REFERENCES rewards.prize_categories(category_id),
    tier_id INT REFERENCES rewards.prize_tiers(tier_id),

    -- Value & Cost
    points_cost INT DEFAULT 0,  -- Points required to redeem (if purchasable)
    monetary_value DECIMAL(10,2),  -- Actual monetary value

    -- Inventory
    total_quantity INT,  -- NULL = unlimited
    available_quantity INT,  -- Current stock
    reserved_quantity INT DEFAULT 0,  -- Reserved but not yet redeemed

    -- Imagery
    image_url VARCHAR(500),
    thumbnail_url VARCHAR(500),

    -- Availability Rules
    availability_rule JSONB DEFAULT '{}'::JSONB,
    -- Example: {"start_date": "2025-01-01", "end_date": "2025-12-31", "dow": [1,2,3,4,5]}

    -- Eligibility Rules
    eligibility_rules JSONB DEFAULT '{}'::JSONB,
    -- Example: {"min_points": 1000, "groups": ["sales", "marketing"], "job_codes": ["MGR"]}

    -- Redemption Rules
    max_per_user INT,  -- Maximum times a user can receive this prize
    cooldown_days INT DEFAULT 0,  -- Days between same user receiving this prize
    requires_approval BOOLEAN DEFAULT FALSE,  -- Needs manager approval

    -- Mystery Box specific
    is_mystery_eligible BOOLEAN DEFAULT TRUE,  -- Can appear in mystery boxes
    mystery_weight INT DEFAULT 100,  -- Weight for random selection (higher = more likely within tier)

    -- Optional Badge Link
    linked_reward_id BIGINT REFERENCES rewards.rewards(reward_id),

    -- Fulfillment
    fulfillment_type VARCHAR(50) DEFAULT 'automatic',  -- automatic, manual, external
    fulfillment_instructions TEXT,
    external_vendor VARCHAR(255),
    vendor_sku VARCHAR(100),

    -- Metadata
    tags TEXT[],
    attributes JSONB DEFAULT '{}'::JSONB,

    -- Status & Audit
    is_active BOOLEAN DEFAULT TRUE,
    is_featured BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    updated_by VARCHAR(255),
    deleted_at TIMESTAMPTZ,
    deleted_by VARCHAR(255),

    -- Constraints
    CONSTRAINT chk_prize_points_positive CHECK (points_cost >= 0),
    CONSTRAINT chk_prize_quantity_valid CHECK (
        available_quantity IS NULL OR
        (available_quantity >= 0 AND (total_quantity IS NULL OR available_quantity <= total_quantity))
    )
);

-- Indexes for prize_catalog
CREATE INDEX IF NOT EXISTS idx_prize_catalog_category ON rewards.prize_catalog(category_id);
CREATE INDEX IF NOT EXISTS idx_prize_catalog_tier ON rewards.prize_catalog(tier_id);
CREATE INDEX IF NOT EXISTS idx_prize_catalog_active ON rewards.prize_catalog(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_prize_catalog_mystery ON rewards.prize_catalog(is_mystery_eligible, tier_id) WHERE is_mystery_eligible = TRUE;
CREATE INDEX IF NOT EXISTS idx_prize_catalog_featured ON rewards.prize_catalog(is_featured) WHERE is_featured = TRUE;

-- ============================================================================
-- PRIZE AWARDS TABLE (Prizes given to users)
-- ============================================================================

-- Award Status Enum
DO $$ BEGIN
    CREATE TYPE rewards.award_status AS ENUM (
        'pending',      -- Awarded but not yet available for redemption
        'available',    -- Ready to be redeemed
        'reserved',     -- User initiated redemption, pending fulfillment
        'redeemed',     -- Successfully redeemed
        'expired',      -- Award expired before redemption
        'cancelled',    -- Award was cancelled/revoked
        'failed'        -- Redemption failed
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- Award Source Enum
DO $$ BEGIN
    CREATE TYPE rewards.award_source AS ENUM (
        'badge',           -- Awarded with a badge
        'mystery_box',     -- Won from mystery box event
        'purchase',        -- Purchased with points
        'manual',          -- Manually awarded by admin
        'campaign',        -- Part of a promotional campaign
        'milestone',       -- Reached a milestone
        'referral',        -- Referral reward
        'lottery'          -- Won in a lottery
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS rewards.prize_awards (
    award_id BIGSERIAL PRIMARY KEY,

    -- Prize Reference
    prize_id BIGINT NOT NULL REFERENCES rewards.prize_catalog(prize_id),

    -- Recipient
    user_id BIGINT NOT NULL REFERENCES auth.users(user_id),
    user_email VARCHAR(255) NOT NULL,
    user_employee_id VARCHAR(100),

    -- Source & Attribution
    source rewards.award_source NOT NULL DEFAULT 'manual',
    source_reference_id BIGINT,  -- ID of badge, mystery_box_event, etc.
    source_reference_type VARCHAR(50),  -- 'badge', 'mystery_box_event', etc.

    -- Linked Badge (optional)
    linked_award_id BIGINT REFERENCES rewards.users_rewards(award_id),

    -- Award Details
    awarded_by_user_id BIGINT REFERENCES auth.users(user_id),
    awarded_by_email VARCHAR(255),
    awarded_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    award_message TEXT,

    -- Status & Lifecycle
    status rewards.award_status DEFAULT 'available' NOT NULL,
    status_changed_at TIMESTAMPTZ DEFAULT NOW(),
    status_changed_by VARCHAR(255),

    -- Expiration
    expires_at TIMESTAMPTZ,  -- NULL = never expires

    -- Value at time of award (snapshot)
    points_value INT DEFAULT 0,
    monetary_value DECIMAL(10,2),

    -- Metadata
    metadata JSONB DEFAULT '{}'::JSONB,
    -- Example: {"mystery_box_id": 123, "tier_rolled": "rare", "campaign_name": "Holiday 2025"}

    -- Audit Trail
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unq_prize_award_tracking UNIQUE (prize_id, user_id, awarded_at, source)
);

-- Indexes for prize_awards
CREATE INDEX IF NOT EXISTS idx_prize_awards_user ON rewards.prize_awards(user_id);
CREATE INDEX IF NOT EXISTS idx_prize_awards_prize ON rewards.prize_awards(prize_id);
CREATE INDEX IF NOT EXISTS idx_prize_awards_status ON rewards.prize_awards(status);
CREATE INDEX IF NOT EXISTS idx_prize_awards_source ON rewards.prize_awards(source);
CREATE INDEX IF NOT EXISTS idx_prize_awards_expires ON rewards.prize_awards(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_prize_awards_user_status ON rewards.prize_awards(user_id, status);

-- ============================================================================
-- PRIZE REDEMPTIONS TABLE (Redemption tracking with full audit)
-- ============================================================================

-- Redemption Status Enum
DO $$ BEGIN
    CREATE TYPE rewards.redemption_status AS ENUM (
        'initiated',       -- User started redemption
        'pending_approval', -- Waiting for manager/admin approval
        'approved',        -- Approved, pending fulfillment
        'processing',      -- Being processed/fulfilled
        'shipped',         -- Physical item shipped
        'completed',       -- Successfully completed
        'rejected',        -- Approval rejected
        'cancelled',       -- User cancelled
        'failed'           -- Fulfillment failed
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS rewards.prize_redemptions (
    redemption_id BIGSERIAL PRIMARY KEY,

    -- References
    award_id BIGINT NOT NULL REFERENCES rewards.prize_awards(award_id),
    prize_id BIGINT NOT NULL REFERENCES rewards.prize_catalog(prize_id),
    user_id BIGINT NOT NULL REFERENCES auth.users(user_id),

    -- Redemption Details
    redemption_code VARCHAR(100) UNIQUE,  -- Unique code for this redemption

    -- Status Tracking
    status rewards.redemption_status DEFAULT 'initiated' NOT NULL,

    -- Timestamps (full lifecycle tracking)
    initiated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    approved_at TIMESTAMPTZ,
    approved_by BIGINT REFERENCES auth.users(user_id),
    processing_started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    cancelled_by BIGINT REFERENCES auth.users(user_id),
    cancelled_reason TEXT,

    -- Fulfillment Details
    fulfillment_method VARCHAR(50),  -- email, physical_shipping, in_person, api
    fulfillment_details JSONB DEFAULT '{}'::JSONB,
    -- Example: {"tracking_number": "1Z999AA10123456784", "carrier": "UPS"}
    -- Example: {"gift_card_code": "XXXX-XXXX-XXXX", "pin": "1234"}
    -- Example: {"download_url": "https://...", "expires": "2025-12-31"}

    -- Shipping (if applicable)
    shipping_address JSONB,
    -- Example: {"street": "123 Main", "city": "NYC", "state": "NY", "zip": "10001"}
    tracking_number VARCHAR(100),
    shipped_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,

    -- User Feedback
    user_rating INT CHECK (user_rating BETWEEN 1 AND 5),
    user_feedback TEXT,
    feedback_at TIMESTAMPTZ,

    -- Metrics (calculated durations)
    time_to_approve_seconds BIGINT,
    time_to_complete_seconds BIGINT,
    total_processing_seconds BIGINT,

    -- Notes & Communication
    admin_notes TEXT,
    notification_sent_at TIMESTAMPTZ,
    reminder_sent_at TIMESTAMPTZ,

    -- Metadata
    metadata JSONB DEFAULT '{}'::JSONB,

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Prevent duplicate redemptions for same award
    CONSTRAINT unq_award_redemption UNIQUE (award_id)
);

-- Indexes for prize_redemptions
CREATE INDEX IF NOT EXISTS idx_prize_redemptions_user ON rewards.prize_redemptions(user_id);
CREATE INDEX IF NOT EXISTS idx_prize_redemptions_prize ON rewards.prize_redemptions(prize_id);
CREATE INDEX IF NOT EXISTS idx_prize_redemptions_status ON rewards.prize_redemptions(status);
CREATE INDEX IF NOT EXISTS idx_prize_redemptions_initiated ON rewards.prize_redemptions(initiated_at);
CREATE INDEX IF NOT EXISTS idx_prize_redemptions_pending ON rewards.prize_redemptions(status)
    WHERE status IN ('initiated', 'pending_approval', 'processing');

-- ============================================================================
-- REDEMPTION STATUS HISTORY (Full audit trail)
-- ============================================================================

CREATE TABLE IF NOT EXISTS rewards.redemption_status_history (
    history_id BIGSERIAL PRIMARY KEY,
    redemption_id BIGINT NOT NULL REFERENCES rewards.prize_redemptions(redemption_id),

    previous_status rewards.redemption_status,
    new_status rewards.redemption_status NOT NULL,

    changed_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    changed_by_user_id BIGINT REFERENCES auth.users(user_id),
    changed_by_email VARCHAR(255),
    change_reason TEXT,

    metadata JSONB DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS idx_redemption_history_redemption ON rewards.redemption_status_history(redemption_id);
CREATE INDEX IF NOT EXISTS idx_redemption_history_changed_at ON rewards.redemption_status_history(changed_at);

-- ============================================================================
-- MYSTERY BOX EVENTS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS rewards.mystery_box_events (
    event_id BIGSERIAL PRIMARY KEY,

    -- Event Configuration
    event_name VARCHAR(255) NOT NULL,
    description TEXT,

    -- Scheduling
    scheduled_at TIMESTAMPTZ NOT NULL,
    executed_at TIMESTAMPTZ,

    -- Eligibility
    eligible_user_count INT,
    eligible_users JSONB,  -- Criteria: {"groups": [], "job_codes": [], "min_tenure_days": 30}

    -- Results
    winners_count INT DEFAULT 0,
    prizes_awarded JSONB DEFAULT '[]'::JSONB,
    -- Array of: {"user_id": 123, "prize_id": 456, "tier": "rare", "award_id": 789}

    -- Status
    status VARCHAR(50) DEFAULT 'scheduled',  -- scheduled, running, completed, failed, cancelled
    error_message TEXT,

    -- Linked Computed Badge (optional)
    linked_reward_id BIGINT REFERENCES rewards.rewards(reward_id),

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_mystery_box_events_scheduled ON rewards.mystery_box_events(scheduled_at);
CREATE INDEX IF NOT EXISTS idx_mystery_box_events_status ON rewards.mystery_box_events(status);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- View: User's Prize Wallet (all their prizes with status)
CREATE OR REPLACE VIEW rewards.vw_user_prize_wallet AS
SELECT
    pa.award_id,
    pa.user_id,
    pa.user_email,
    pc.prize_id,
    pc.prize_name,
    pc.short_description,
    pc.image_url,
    pc.thumbnail_url,
    pt.tier_name,
    pt.color_code AS tier_color,
    pcat.category_name,
    pa.source,
    pa.status,
    pa.awarded_at,
    pa.expires_at,
    pa.monetary_value,
    pa.points_value,
    pr.redemption_id,
    pr.status AS redemption_status,
    pr.initiated_at AS redemption_initiated_at,
    pr.completed_at AS redemption_completed_at,
    pr.redemption_code,
    -- Computed fields
    CASE
        WHEN pa.expires_at IS NOT NULL AND pa.expires_at < NOW() THEN TRUE
        ELSE FALSE
    END AS is_expired,
    CASE
        WHEN pa.status = 'available' AND (pa.expires_at IS NULL OR pa.expires_at > NOW()) THEN TRUE
        ELSE FALSE
    END AS can_redeem,
    -- Days until expiration
    CASE
        WHEN pa.expires_at IS NOT NULL THEN
            EXTRACT(DAY FROM (pa.expires_at - NOW()))::INT
        ELSE NULL
    END AS days_until_expiry
FROM rewards.prize_awards pa
JOIN rewards.prize_catalog pc ON pa.prize_id = pc.prize_id
LEFT JOIN rewards.prize_tiers pt ON pc.tier_id = pt.tier_id
LEFT JOIN rewards.prize_categories pcat ON pc.category_id = pcat.category_id
LEFT JOIN rewards.prize_redemptions pr ON pa.award_id = pr.award_id
WHERE pa.status != 'cancelled';

-- View: Prize Catalog with Stock Info
CREATE OR REPLACE VIEW rewards.vw_prize_catalog AS
SELECT
    pc.*,
    pt.tier_name,
    pt.tier_level,
    pt.color_code AS tier_color,
    pt.drop_rate,
    pcat.category_name,
    r.reward AS linked_badge_name,
    r.icon AS linked_badge_icon,
    -- Stock status
    CASE
        WHEN pc.total_quantity IS NULL THEN 'unlimited'
        WHEN pc.available_quantity <= 0 THEN 'out_of_stock'
        WHEN pc.available_quantity <= (pc.total_quantity * 0.1) THEN 'low_stock'
        ELSE 'in_stock'
    END AS stock_status,
    -- Effective availability
    COALESCE(pc.available_quantity, 999999) - COALESCE(pc.reserved_quantity, 0) AS effective_quantity
FROM rewards.prize_catalog pc
LEFT JOIN rewards.prize_tiers pt ON pc.tier_id = pt.tier_id
LEFT JOIN rewards.prize_categories pcat ON pc.category_id = pcat.category_id
LEFT JOIN rewards.rewards r ON pc.linked_reward_id = r.reward_id
WHERE pc.deleted_at IS NULL;

-- View: Redemption Metrics
CREATE OR REPLACE VIEW rewards.vw_redemption_metrics AS
SELECT
    pr.redemption_id,
    pr.award_id,
    pr.prize_id,
    pr.user_id,
    pc.prize_name,
    pr.status,
    pr.initiated_at,
    pr.completed_at,
    pa.awarded_at,
    -- Time from award to redemption initiation
    EXTRACT(EPOCH FROM (pr.initiated_at - pa.awarded_at))::BIGINT AS seconds_to_initiate,
    -- Time from initiation to completion
    CASE
        WHEN pr.completed_at IS NOT NULL THEN
            EXTRACT(EPOCH FROM (pr.completed_at - pr.initiated_at))::BIGINT
        ELSE NULL
    END AS seconds_to_complete,
    -- Total lifecycle time
    CASE
        WHEN pr.completed_at IS NOT NULL THEN
            EXTRACT(EPOCH FROM (pr.completed_at - pa.awarded_at))::BIGINT
        ELSE NULL
    END AS total_lifecycle_seconds,
    -- Human readable durations
    pr.completed_at - pa.awarded_at AS total_duration,
    pr.completed_at - pr.initiated_at AS processing_duration,
    pr.initiated_at - pa.awarded_at AS sitting_duration
FROM rewards.prize_redemptions pr
JOIN rewards.prize_awards pa ON pr.award_id = pa.award_id
JOIN rewards.prize_catalog pc ON pr.prize_id = pc.prize_id;

-- View: Mystery Box Statistics
CREATE OR REPLACE VIEW rewards.vw_mystery_box_stats AS
SELECT
    DATE_TRUNC('day', mbe.executed_at) AS event_date,
    COUNT(*) AS events_count,
    SUM(mbe.winners_count) AS total_winners,
    AVG(mbe.winners_count) AS avg_winners_per_event,
    SUM(JSONB_ARRAY_LENGTH(mbe.prizes_awarded)) AS total_prizes_awarded
FROM rewards.mystery_box_events mbe
WHERE mbe.status = 'completed'
GROUP BY DATE_TRUNC('day', mbe.executed_at)
ORDER BY event_date DESC;

-- ============================================================================
-- FUNCTIONS & TRIGGERS
-- ============================================================================

-- Function: Generate unique redemption code
CREATE OR REPLACE FUNCTION rewards.generate_redemption_code()
RETURNS VARCHAR(100) AS $$
DECLARE
    chars TEXT := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    result TEXT := '';
    i INT;
BEGIN
    -- Format: RDM-XXXXX-XXXXX
    result := 'RDM-';
    FOR i IN 1..5 LOOP
        result := result || SUBSTR(chars, FLOOR(RANDOM() * LENGTH(chars) + 1)::INT, 1);
    END LOOP;
    result := result || '-';
    FOR i IN 1..5 LOOP
        result := result || SUBSTR(chars, FLOOR(RANDOM() * LENGTH(chars) + 1)::INT, 1);
    END LOOP;
    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- Function: Update prize stock on award
CREATE OR REPLACE FUNCTION rewards.update_prize_stock_on_award()
RETURNS TRIGGER AS $$
BEGIN
    -- Only update if prize has limited quantity
    IF (SELECT total_quantity FROM rewards.prize_catalog WHERE prize_id = NEW.prize_id) IS NOT NULL THEN
        UPDATE rewards.prize_catalog
        SET
            available_quantity = available_quantity - 1,
            updated_at = NOW()
        WHERE prize_id = NEW.prize_id
          AND available_quantity > 0;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'Prize % is out of stock', NEW.prize_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Update stock on award
CREATE TRIGGER trg_update_stock_on_award
    BEFORE INSERT ON rewards.prize_awards
    FOR EACH ROW
    EXECUTE FUNCTION rewards.update_prize_stock_on_award();

-- Function: Prevent duplicate redemption
CREATE OR REPLACE FUNCTION rewards.prevent_duplicate_redemption()
RETURNS TRIGGER AS $$
BEGIN
    -- Check if this award has already been redeemed
    IF EXISTS (
        SELECT 1 FROM rewards.prize_awards
        WHERE award_id = NEW.award_id
        AND status IN ('redeemed', 'reserved')
    ) THEN
        RAISE EXCEPTION 'Award % has already been redeemed or is being processed', NEW.award_id;
    END IF;

    -- Update award status to reserved
    UPDATE rewards.prize_awards
    SET
        status = 'reserved',
        status_changed_at = NOW(),
        updated_at = NOW()
    WHERE award_id = NEW.award_id;

    -- Generate redemption code if not provided
    IF NEW.redemption_code IS NULL THEN
        NEW.redemption_code := rewards.generate_redemption_code();
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Prevent duplicate redemption
CREATE TRIGGER trg_prevent_duplicate_redemption
    BEFORE INSERT ON rewards.prize_redemptions
    FOR EACH ROW
    EXECUTE FUNCTION rewards.prevent_duplicate_redemption();

-- Function: Track redemption status changes
CREATE OR REPLACE FUNCTION rewards.track_redemption_status_change()
RETURNS TRIGGER AS $$
BEGIN
    -- Only track if status actually changed
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        INSERT INTO rewards.redemption_status_history (
            redemption_id,
            previous_status,
            new_status,
            changed_at,
            changed_by_email
        ) VALUES (
            NEW.redemption_id,
            OLD.status,
            NEW.status,
            NOW(),
            NEW.metadata->>'changed_by'
        );

        -- Update timing metrics
        IF NEW.status = 'approved' AND OLD.status != 'approved' THEN
            NEW.approved_at := NOW();
            NEW.time_to_approve_seconds := EXTRACT(EPOCH FROM (NOW() - NEW.initiated_at))::BIGINT;
        END IF;

        IF NEW.status = 'completed' AND OLD.status != 'completed' THEN
            NEW.completed_at := NOW();
            NEW.time_to_complete_seconds := EXTRACT(EPOCH FROM (NOW() - NEW.initiated_at))::BIGINT;
            NEW.total_processing_seconds := EXTRACT(EPOCH FROM (NOW() - NEW.created_at))::BIGINT;

            -- Update award status to redeemed
            UPDATE rewards.prize_awards
            SET
                status = 'redeemed',
                status_changed_at = NOW(),
                updated_at = NOW()
            WHERE award_id = NEW.award_id;
        END IF;

        IF NEW.status IN ('cancelled', 'rejected', 'failed') THEN
            NEW.cancelled_at := NOW();

            -- Restore award to available (if not expired)
            UPDATE rewards.prize_awards
            SET
                status = CASE
                    WHEN expires_at IS NOT NULL AND expires_at < NOW() THEN 'expired'::rewards.award_status
                    ELSE 'available'::rewards.award_status
                END,
                status_changed_at = NOW(),
                updated_at = NOW()
            WHERE award_id = NEW.award_id;
        END IF;
    END IF;

    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Track status changes
CREATE TRIGGER trg_track_redemption_status
    BEFORE UPDATE ON rewards.prize_redemptions
    FOR EACH ROW
    EXECUTE FUNCTION rewards.track_redemption_status_change();

-- Function: Expire old awards
CREATE OR REPLACE FUNCTION rewards.expire_old_awards()
RETURNS INTEGER AS $$
DECLARE
    expired_count INTEGER;
BEGIN
    WITH expired AS (
        UPDATE rewards.prize_awards
        SET
            status = 'expired',
            status_changed_at = NOW(),
            updated_at = NOW()
        WHERE status = 'available'
          AND expires_at IS NOT NULL
          AND expires_at < NOW()
        RETURNING award_id
    )
    SELECT COUNT(*) INTO expired_count FROM expired;

    RETURN expired_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- SAMPLE DATA FOR TESTING
-- ============================================================================

-- Insert sample prizes
INSERT INTO rewards.prize_catalog (
    prize_name, description, short_description, category_id, tier_id,
    points_cost, monetary_value, total_quantity, available_quantity,
    is_mystery_eligible, mystery_weight, fulfillment_type
) VALUES
    -- Common Tier
    ('$10 Amazon Gift Card', 'A $10 digital Amazon gift card', '$10 Amazon eGift', 1, 1,
     100, 10.00, NULL, NULL, TRUE, 100, 'automatic'),
    ('Company T-Shirt', 'Premium company branded t-shirt', 'Branded T-Shirt', 2, 1,
     150, 15.00, 100, 100, TRUE, 80, 'manual'),
    ('Coffee Mug', 'Insulated company branded coffee mug', 'Branded Mug', 2, 1,
     80, 12.00, 50, 50, TRUE, 90, 'manual'),

    -- Uncommon Tier
    ('$25 Restaurant Gift Card', 'Gift card to local restaurant partner', '$25 Restaurant', 1, 2,
     250, 25.00, NULL, NULL, TRUE, 100, 'automatic'),
    ('Wireless Mouse', 'High-quality wireless mouse', 'Wireless Mouse', 2, 2,
     300, 35.00, 30, 30, TRUE, 70, 'manual'),

    -- Rare Tier
    ('$50 Spa Gift Card', 'Relaxing spa experience gift card', '$50 Spa Certificate', 1, 3,
     500, 50.00, NULL, NULL, TRUE, 100, 'automatic'),
    ('Noise-Canceling Earbuds', 'Premium wireless earbuds', 'Premium Earbuds', 2, 3,
     800, 80.00, 20, 20, TRUE, 60, 'manual'),
    ('Extra PTO Day', 'One additional paid day off', 'Extra PTO Day', 3, 3,
     1000, 200.00, 10, 10, TRUE, 40, 'manual'),

    -- Epic Tier
    ('$100 Travel Voucher', 'Voucher for airline or hotel booking', '$100 Travel', 3, 4,
     1500, 100.00, NULL, NULL, TRUE, 100, 'automatic'),
    ('Premium Backpack', 'High-end laptop backpack', 'Premium Backpack', 2, 4,
     1200, 120.00, 15, 15, TRUE, 50, 'manual'),

    -- Legendary Tier
    ('$500 Experience Package', 'VIP experience of your choice', '$500 Experience', 3, 5,
     5000, 500.00, 5, 5, TRUE, 100, 'manual'),
    ('Latest Tablet', 'Current generation tablet device', 'Premium Tablet', 4, 5,
     8000, 600.00, 3, 3, TRUE, 30, 'manual'),
    ('Lunch with CEO', 'Exclusive lunch meeting with company CEO', 'CEO Lunch', 3, 5,
     NULL, 300.00, 2, 2, TRUE, 20, 'manual')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- GRANT PERMISSIONS (adjust user/role as needed)
-- ============================================================================

-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA rewards TO your_app_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA rewards TO your_app_user;

COMMENT ON TABLE rewards.prize_catalog IS 'Catalog of all available prizes in the marketplace';
COMMENT ON TABLE rewards.prize_awards IS 'Prizes awarded to users - tracks from award to redemption';
COMMENT ON TABLE rewards.prize_redemptions IS 'Redemption records with full audit trail and metrics';
COMMENT ON TABLE rewards.mystery_box_events IS 'Mystery box event executions and results';
