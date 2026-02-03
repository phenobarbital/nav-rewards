-- ============================================================================
-- NAV-REWARDS: FEEDBACK SYSTEM DATABASE SCHEMA
-- ============================================================================
-- Description: Database schema for the Feedback System
-- Points: 5 pts to giver, 10 pts to receiver
-- Targets: badges (users_rewards), kudos (users_kudos), nominations
-- ============================================================================

-- ============================================================================
-- FEEDBACK TYPES TABLE
-- ============================================================================
-- Predefined feedback categories (similar to kudos_tags)

CREATE TABLE IF NOT EXISTS rewards.feedback_types (
    feedback_type_id SERIAL PRIMARY KEY,
    type_name VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    description TEXT,
    emoji VARCHAR(10),
    category VARCHAR(50),
    usage_count INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Create index for active feedback types
CREATE INDEX IF NOT EXISTS idx_feedback_types_active 
    ON rewards.feedback_types(is_active) WHERE is_active = TRUE;

-- Insert initial feedback types
INSERT INTO rewards.feedback_types (type_name, display_name, description, emoji, category) VALUES
    ('appreciation', 'Appreciation', 'Grateful for this recognition', '🙏', 'gratitude'),
    ('impact', 'Great Impact', 'This had significant positive impact', '💥', 'performance'),
    ('inspiring', 'Inspiring', 'This inspired me or others', '✨', 'motivation'),
    ('well_deserved', 'Well Deserved', 'Completely earned this recognition', '🏆', 'validation'),
    ('teamwork', 'Team Player', 'Exemplifies great teamwork', '🤝', 'collaboration'),
    ('growth', 'Shows Growth', 'Demonstrates personal/professional growth', '📈', 'development'),
    ('leadership', 'Leadership', 'Shows excellent leadership qualities', '👑', 'leadership'),
    ('innovation', 'Innovative', 'Creative and innovative approach', '💡', 'innovation'),
    ('dedication', 'Dedication', 'Shows remarkable dedication', '💪', 'commitment'),
    ('excellence', 'Excellence', 'Exemplifies excellence in work', '⭐', 'quality')
ON CONFLICT (type_name) DO NOTHING;

-- ============================================================================
-- USER FEEDBACK TABLE
-- ============================================================================
-- Main feedback storage with polymorphic target support

CREATE TABLE IF NOT EXISTS rewards.user_feedback (
    feedback_id BIGSERIAL PRIMARY KEY,
    
    -- Polymorphic target reference
    target_type VARCHAR(20) NOT NULL,  -- 'badge', 'kudos', 'nomination'
    target_id BIGINT NOT NULL,         -- award_id, kudos_id, nomination_id
    
    -- User relationships
    giver_user_id BIGINT NOT NULL,
    giver_email VARCHAR(255),
    giver_name VARCHAR(255),
    receiver_user_id BIGINT NOT NULL,
    receiver_email VARCHAR(255),
    receiver_name VARCHAR(255),
    
    -- Feedback content
    feedback_type_id INT REFERENCES rewards.feedback_types(feedback_type_id),
    rating SMALLINT CHECK (rating IS NULL OR (rating BETWEEN 1 AND 5)),
    message TEXT,
    
    -- Points awarded (denormalized for performance/audit)
    points_given INT DEFAULT 5 NOT NULL,
    points_received INT DEFAULT 10 NOT NULL,
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    
    -- Constraints
    CONSTRAINT chk_feedback_no_self CHECK (giver_user_id <> receiver_user_id),
    CONSTRAINT chk_feedback_target_type CHECK (target_type IN ('badge', 'kudos', 'nomination')),
    CONSTRAINT chk_feedback_points_given CHECK (points_given >= 0),
    CONSTRAINT chk_feedback_points_received CHECK (points_received >= 0),
    
    -- Unique constraint: one feedback per user per target
    CONSTRAINT unq_feedback_per_target UNIQUE (target_type, target_id, giver_user_id),
    
    -- Foreign keys
    CONSTRAINT fk_feedback_giver_user 
        FOREIGN KEY (giver_user_id) 
        REFERENCES auth.users(user_id) 
        ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_feedback_receiver_user 
        FOREIGN KEY (receiver_user_id) 
        REFERENCES auth.users(user_id) 
        ON DELETE RESTRICT ON UPDATE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_user_feedback_giver 
    ON rewards.user_feedback(giver_user_id);
CREATE INDEX IF NOT EXISTS idx_user_feedback_receiver 
    ON rewards.user_feedback(receiver_user_id);
CREATE INDEX IF NOT EXISTS idx_user_feedback_target 
    ON rewards.user_feedback(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_user_feedback_type 
    ON rewards.user_feedback(feedback_type_id);
CREATE INDEX IF NOT EXISTS idx_user_feedback_created 
    ON rewards.user_feedback(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_feedback_active 
    ON rewards.user_feedback(is_active) WHERE is_active = TRUE;

-- ============================================================================
-- FEEDBACK COOLDOWN TABLE
-- ============================================================================
-- Optional: Track cooldowns to prevent feedback spam

CREATE TABLE IF NOT EXISTS rewards.feedback_cooldowns (
    cooldown_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES auth.users(user_id),
    target_type VARCHAR(20) NOT NULL,
    last_feedback_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    feedback_count_today INT DEFAULT 1,
    
    CONSTRAINT unq_cooldown_user_target UNIQUE (user_id, target_type)
);

CREATE INDEX IF NOT EXISTS idx_feedback_cooldowns_user 
    ON rewards.feedback_cooldowns(user_id);

-- ============================================================================
-- TRIGGER: Award Points on Feedback
-- ============================================================================
-- Automatically award points when feedback is created

CREATE OR REPLACE FUNCTION rewards.award_feedback_points()
RETURNS TRIGGER AS $$
BEGIN
    -- Award points to giver (5 points)
    INSERT INTO rewards.rewards_points (user_id, points, karma, awarded_at)
    VALUES (NEW.giver_user_id, NEW.points_given, 1, CURRENT_TIMESTAMP);
    
    -- Award points to receiver (10 points)
    INSERT INTO rewards.rewards_points (user_id, points, karma, awarded_at)
    VALUES (NEW.receiver_user_id, NEW.points_received, 2, CURRENT_TIMESTAMP);
    
    -- Update feedback type usage count
    IF NEW.feedback_type_id IS NOT NULL THEN
        UPDATE rewards.feedback_types 
        SET usage_count = usage_count + 1 
        WHERE feedback_type_id = NEW.feedback_type_id;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_award_feedback_points ON rewards.user_feedback;
CREATE TRIGGER trg_award_feedback_points
    AFTER INSERT ON rewards.user_feedback
    FOR EACH ROW
    EXECUTE FUNCTION rewards.award_feedback_points();

-- ============================================================================
-- TRIGGER: Update Cooldown Tracking
-- ============================================================================

CREATE OR REPLACE FUNCTION rewards.update_feedback_cooldown()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO rewards.feedback_cooldowns (user_id, target_type, last_feedback_at, feedback_count_today)
    VALUES (NEW.giver_user_id, NEW.target_type, CURRENT_TIMESTAMP, 1)
    ON CONFLICT (user_id, target_type) 
    DO UPDATE SET 
        last_feedback_at = CURRENT_TIMESTAMP,
        feedback_count_today = CASE 
            WHEN DATE(rewards.feedback_cooldowns.last_feedback_at) = CURRENT_DATE 
            THEN rewards.feedback_cooldowns.feedback_count_today + 1
            ELSE 1
        END;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_feedback_cooldown ON rewards.user_feedback;
CREATE TRIGGER trg_update_feedback_cooldown
    AFTER INSERT ON rewards.user_feedback
    FOR EACH ROW
    EXECUTE FUNCTION rewards.update_feedback_cooldown();

-- ============================================================================
-- VIEWS
-- ============================================================================

-- View: Feedback with full details
CREATE OR REPLACE VIEW rewards.vw_user_feedback AS
SELECT 
    f.feedback_id,
    f.target_type,
    f.target_id,
    f.giver_user_id,
    f.giver_email,
    f.giver_name,
    gu.display_name AS giver_display_name,
    f.receiver_user_id,
    f.receiver_email,
    f.receiver_name,
    ru.display_name AS receiver_display_name,
    f.feedback_type_id,
    ft.type_name,
    ft.display_name AS feedback_type_display,
    ft.emoji AS feedback_emoji,
    f.rating,
    f.message,
    f.points_given,
    f.points_received,
    f.created_at,
    f.is_active
FROM rewards.user_feedback f
LEFT JOIN auth.users gu ON f.giver_user_id = gu.user_id
LEFT JOIN auth.users ru ON f.receiver_user_id = ru.user_id
LEFT JOIN rewards.feedback_types ft ON f.feedback_type_id = ft.feedback_type_id
WHERE f.is_active = TRUE;

-- View: Trending feedback types (last 30 days)
CREATE OR REPLACE VIEW rewards.vw_trending_feedback_types AS
SELECT 
    ft.feedback_type_id,
    ft.type_name,
    ft.display_name,
    ft.emoji,
    ft.category,
    COUNT(f.feedback_id) AS recent_usage,
    ft.usage_count AS total_usage
FROM rewards.feedback_types ft
LEFT JOIN rewards.user_feedback f 
    ON ft.feedback_type_id = f.feedback_type_id 
    AND f.created_at >= CURRENT_TIMESTAMP - INTERVAL '30 days'
    AND f.is_active = TRUE
WHERE ft.is_active = TRUE
GROUP BY ft.feedback_type_id, ft.type_name, ft.display_name, ft.emoji, ft.category, ft.usage_count
ORDER BY recent_usage DESC, total_usage DESC;

-- View: User feedback statistics
CREATE OR REPLACE VIEW rewards.vw_user_feedback_stats AS
SELECT 
    u.user_id,
    u.email,
    u.display_name,
    COALESCE(given.feedback_given, 0) AS feedback_given,
    COALESCE(given.points_earned_giving, 0) AS points_earned_giving,
    COALESCE(received.feedback_received, 0) AS feedback_received,
    COALESCE(received.points_earned_receiving, 0) AS points_earned_receiving,
    COALESCE(received.avg_rating, 0) AS avg_rating_received
FROM auth.users u
LEFT JOIN (
    SELECT 
        giver_user_id,
        COUNT(*) AS feedback_given,
        SUM(points_given) AS points_earned_giving
    FROM rewards.user_feedback
    WHERE is_active = TRUE
    GROUP BY giver_user_id
) given ON u.user_id = given.giver_user_id
LEFT JOIN (
    SELECT 
        receiver_user_id,
        COUNT(*) AS feedback_received,
        SUM(points_received) AS points_earned_receiving,
        AVG(rating) FILTER (WHERE rating IS NOT NULL) AS avg_rating
    FROM rewards.user_feedback
    WHERE is_active = TRUE
    GROUP BY receiver_user_id
) received ON u.user_id = received.receiver_user_id
WHERE given.feedback_given > 0 OR received.feedback_received > 0;

-- View: Feedback summary by target
CREATE OR REPLACE VIEW rewards.vw_feedback_by_target AS
SELECT 
    target_type,
    target_id,
    COUNT(*) AS feedback_count,
    AVG(rating) FILTER (WHERE rating IS NOT NULL) AS avg_rating,
    array_agg(DISTINCT ft.type_name) AS feedback_types,
    MIN(f.created_at) AS first_feedback,
    MAX(f.created_at) AS last_feedback
FROM rewards.user_feedback f
LEFT JOIN rewards.feedback_types ft ON f.feedback_type_id = ft.feedback_type_id
WHERE f.is_active = TRUE
GROUP BY target_type, target_id;

-- ============================================================================
-- GRANTS (adjust as needed for your user)
-- ============================================================================
-- GRANT ALL ON rewards.feedback_types TO your_app_user;
-- GRANT ALL ON rewards.user_feedback TO your_app_user;
-- GRANT ALL ON rewards.feedback_cooldowns TO your_app_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA rewards TO your_app_user;
