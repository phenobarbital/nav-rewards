-- ============================================================================
-- NAV-Rewards: Enhanced Collections (Collectives) System
-- ============================================================================
-- Extends the existing collectives infrastructure with:
--   1. Enhanced collectives table with completion types and temporality
--   2. Collection bonus rewards (auto-awarded on completion)
--   3. User progress tracking
--   4. Collection tiers and seasonal support
--   5. Notification triggers
-- ============================================================================

-- ============================================================================
-- STEP 1: ALTER EXISTING TABLES (backward-compatible additions)
-- ============================================================================

-- Add new columns to existing collectives table
ALTER TABLE rewards.collectives
    ADD COLUMN IF NOT EXISTS completion_type VARCHAR(20) DEFAULT 'all'
        CHECK (completion_type IN ('all', 'n_of_m', 'any_n')),
    ADD COLUMN IF NOT EXISTS required_count INT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS bonus_reward_id BIGINT REFERENCES rewards.rewards(reward_id),
    ADD COLUMN IF NOT EXISTS bonus_points INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS is_seasonal BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS start_date TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS end_date TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS tier VARCHAR(50) DEFAULT 'bronze'
        CHECK (tier IN ('bronze', 'silver', 'gold', 'platinum', 'diamond')),
    ADD COLUMN IF NOT EXISTS sort_order INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS programs VARCHAR[] DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS message TEXT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS teams_webhook TEXT DEFAULT NULL;

-- Comments for documentation
COMMENT ON COLUMN rewards.collectives.completion_type IS
    'all = every badge required, n_of_m = specific count from set, any_n = any N badges';
COMMENT ON COLUMN rewards.collectives.required_count IS
    'Number of badges required when completion_type is n_of_m or any_n';
COMMENT ON COLUMN rewards.collectives.bonus_reward_id IS
    'Optional: auto-award this badge when collection is completed';
COMMENT ON COLUMN rewards.collectives.bonus_points IS
    'Extra points awarded on collection completion (on top of individual badge points)';

-- ============================================================================
-- STEP 2: COLLECTION PROGRESS TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS rewards.collectives_progress (
    progress_id BIGSERIAL PRIMARY KEY,
    collective_id INT NOT NULL REFERENCES rewards.collectives(collective_id)
        ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES auth.users(user_id)
        ON DELETE CASCADE,

    -- Progress tracking
    badges_earned INT DEFAULT 0 NOT NULL,
    badges_required INT NOT NULL,
    progress_pct DECIMAL(5,2) DEFAULT 0.00 NOT NULL
        CHECK (progress_pct BETWEEN 0 AND 100),
    is_complete BOOLEAN DEFAULT FALSE NOT NULL,
    completed_at TIMESTAMPTZ DEFAULT NULL,

    -- Earned badge details (denormalized for fast reads)
    earned_reward_ids BIGINT[] DEFAULT '{}',

    -- Audit
    first_badge_at TIMESTAMPTZ DEFAULT NULL,
    last_badge_at TIMESTAMPTZ DEFAULT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,

    -- Constraints
    CONSTRAINT unq_collective_user_progress UNIQUE (collective_id, user_id),
    CONSTRAINT chk_progress_badges CHECK (badges_earned >= 0),
    CONSTRAINT chk_progress_required CHECK (badges_required > 0)
);

CREATE INDEX IF NOT EXISTS idx_collectives_progress_user
    ON rewards.collectives_progress(user_id);
CREATE INDEX IF NOT EXISTS idx_collectives_progress_complete
    ON rewards.collectives_progress(is_complete) WHERE is_complete = FALSE;
CREATE INDEX IF NOT EXISTS idx_collectives_progress_collective
    ON rewards.collectives_progress(collective_id, is_complete);

-- ============================================================================
-- STEP 3: COLLECTION COMPLETION LOG (audit trail)
-- ============================================================================

CREATE TABLE IF NOT EXISTS rewards.collectives_completion_log (
    log_id BIGSERIAL PRIMARY KEY,
    collective_id INT NOT NULL REFERENCES rewards.collectives(collective_id),
    user_id BIGINT NOT NULL REFERENCES auth.users(user_id),

    -- Completion details
    bonus_points_awarded INT DEFAULT 0,
    bonus_reward_id BIGINT REFERENCES rewards.rewards(reward_id),
    bonus_award_id BIGINT REFERENCES rewards.users_rewards(award_id),

    -- Context
    completing_badge_id BIGINT REFERENCES rewards.rewards(reward_id),
    completing_award_id BIGINT REFERENCES rewards.users_rewards(award_id),
    badges_snapshot JSONB DEFAULT '[]'::JSONB,

    -- Audit
    completed_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    notified BOOLEAN DEFAULT FALSE,
    notified_at TIMESTAMPTZ DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_completion_log_user
    ON rewards.collectives_completion_log(user_id);
CREATE INDEX IF NOT EXISTS idx_completion_log_collective
    ON rewards.collectives_completion_log(collective_id, completed_at DESC);

-- ============================================================================
-- STEP 4: MODIFY collectives_unlocked TO ADD bonus_award_id
-- ============================================================================

ALTER TABLE rewards.collectives_unlocked
    ADD COLUMN IF NOT EXISTS bonus_points_awarded INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS bonus_award_id BIGINT
        REFERENCES rewards.users_rewards(award_id);

-- ============================================================================
-- STEP 5: TRIGGER - Auto-update progress when a badge is awarded
-- ============================================================================

CREATE OR REPLACE FUNCTION rewards.update_collection_progress()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
    rec RECORD;
    v_total_required INT;
    v_earned_count INT;
    v_earned_ids BIGINT[];
    v_progress DECIMAL(5,2);
    v_is_complete BOOLEAN;
    v_completion_type VARCHAR(20);
    v_required_count INT;
BEGIN
    -- For each collective that includes the awarded reward_id
    FOR rec IN
        SELECT c.collective_id, c.completion_type, c.required_count,
               COUNT(cr2.reward_id) AS total_badges
        FROM rewards.collectives_rewards cr
        JOIN rewards.collectives c ON c.collective_id = cr.collective_id
        JOIN rewards.collectives_rewards cr2 ON cr2.collective_id = c.collective_id
        WHERE cr.reward_id = NEW.reward_id
          AND c.is_active = TRUE
          AND (c.end_date IS NULL OR c.end_date > NOW())
        GROUP BY c.collective_id, c.completion_type, c.required_count
    LOOP
        -- Count how many badges from this collective the user has earned
        SELECT COUNT(DISTINCT cr.reward_id),
               ARRAY_AGG(DISTINCT cr.reward_id)
        INTO v_earned_count, v_earned_ids
        FROM rewards.collectives_rewards cr
        JOIN rewards.users_rewards ur ON ur.reward_id = cr.reward_id
            AND ur.receiver_user = NEW.receiver_user
            AND ur.revoked = FALSE
            AND ur.deleted_at IS NULL
        WHERE cr.collective_id = rec.collective_id;

        -- Determine required count based on completion type
        v_completion_type := rec.completion_type;
        CASE v_completion_type
            WHEN 'all' THEN
                v_total_required := rec.total_badges;
            WHEN 'n_of_m' THEN
                v_total_required := COALESCE(rec.required_count, rec.total_badges);
            WHEN 'any_n' THEN
                v_total_required := COALESCE(rec.required_count, rec.total_badges);
            ELSE
                v_total_required := rec.total_badges;
        END CASE;

        -- Calculate progress
        IF v_total_required > 0 THEN
            v_progress := LEAST(
                (v_earned_count::DECIMAL / v_total_required::DECIMAL) * 100, 100
            );
        ELSE
            v_progress := 0;
        END IF;

        v_is_complete := (v_earned_count >= v_total_required);

        -- Upsert progress record
        INSERT INTO rewards.collectives_progress (
            collective_id, user_id, badges_earned, badges_required,
            progress_pct, is_complete, earned_reward_ids,
            first_badge_at, last_badge_at, updated_at,
            completed_at
        ) VALUES (
            rec.collective_id, NEW.receiver_user, v_earned_count,
            v_total_required, v_progress, v_is_complete, v_earned_ids,
            NOW(), NOW(), NOW(),
            CASE WHEN v_is_complete THEN NOW() ELSE NULL END
        )
        ON CONFLICT (collective_id, user_id)
        DO UPDATE SET
            badges_earned = EXCLUDED.badges_earned,
            badges_required = EXCLUDED.badges_required,
            progress_pct = EXCLUDED.progress_pct,
            is_complete = EXCLUDED.is_complete,
            earned_reward_ids = EXCLUDED.earned_reward_ids,
            last_badge_at = EXCLUDED.last_badge_at,
            updated_at = NOW(),
            completed_at = CASE
                WHEN NOT rewards.collectives_progress.is_complete
                     AND EXCLUDED.is_complete
                THEN NOW()
                ELSE rewards.collectives_progress.completed_at
            END;
    END LOOP;

    RETURN NEW;
END;
$function$;

-- Attach trigger to users_rewards
DROP TRIGGER IF EXISTS trg_update_collection_progress ON rewards.users_rewards;
CREATE TRIGGER trg_update_collection_progress
    AFTER INSERT ON rewards.users_rewards
    FOR EACH ROW
    EXECUTE FUNCTION rewards.update_collection_progress();

-- ============================================================================
-- STEP 6: HELPER VIEWS
-- ============================================================================

-- View: Collection details with badge count
CREATE OR REPLACE VIEW rewards.vw_collectives AS
SELECT
    c.collective_id,
    c.collective_name,
    c.description,
    c.points,
    c.bonus_points,
    c.icon,
    c.completion_type,
    c.required_count,
    c.bonus_reward_id,
    c.is_active,
    c.is_seasonal,
    c.start_date,
    c.end_date,
    c.tier,
    c.programs,
    c.message,
    c.created_at,
    COUNT(cr.reward_id) AS total_badges,
    COALESCE(
        CASE c.completion_type
            WHEN 'all' THEN COUNT(cr.reward_id)
            ELSE COALESCE(c.required_count, COUNT(cr.reward_id))
        END, 0
    ) AS badges_to_complete,
    ARRAY_AGG(cr.reward_id ORDER BY cr.reward_id) AS badge_ids,
    ARRAY_AGG(r.reward ORDER BY cr.reward_id) AS badge_names
FROM rewards.collectives c
LEFT JOIN rewards.collectives_rewards cr USING (collective_id)
LEFT JOIN rewards.rewards r USING (reward_id)
WHERE c.is_active = TRUE
GROUP BY c.collective_id;

-- View: User progress across all collections
CREATE OR REPLACE VIEW rewards.vw_user_collection_progress AS
SELECT
    cp.user_id,
    c.collective_id,
    c.collective_name,
    c.description,
    c.icon,
    c.tier,
    c.completion_type,
    c.bonus_points,
    cp.badges_earned,
    cp.badges_required,
    cp.progress_pct,
    cp.is_complete,
    cp.completed_at,
    cp.earned_reward_ids,
    cp.first_badge_at,
    cp.last_badge_at,
    cu.unlocked_at
FROM rewards.collectives_progress cp
JOIN rewards.collectives c USING (collective_id)
LEFT JOIN rewards.collectives_unlocked cu
    ON cu.collective_id = cp.collective_id
    AND cu.user_id = cp.user_id
WHERE c.is_active = TRUE;

-- ============================================================================
-- STEP 7: INITIAL DATA - Collection Tiers Category
-- ============================================================================

INSERT INTO rewards.reward_categories (reward_category)
VALUES ('Collections')
ON CONFLICT DO NOTHING;

INSERT INTO rewards.reward_groups (reward_group)
VALUES ('Collection Rewards')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- STEP 8: SAMPLE COLLECTIONS
-- ============================================================================
-- NOTE: These reference reward_ids that must exist in your rewards table.
-- Adjust the reward_ids to match your actual badge IDs.

-- Example: "Core Values Champion" - collect all core value badges
-- INSERT INTO rewards.collectives
--     (collective_name, description, points, bonus_points, completion_type,
--      tier, icon, message)
-- VALUES
--     ('Core Values Champion',
--      'Collect all 5 core value badges to earn the Champion title!',
--      100, 500, 'all', 'gold',
--      'https://example.com/icons/champion.png',
--      'Congratulations {{user.display_name}}! You have collected all Core Value badges!');

-- Example: "Social Butterfly" - get any 3 recognition badges
-- INSERT INTO rewards.collectives
--     (collective_name, description, points, bonus_points, completion_type,
--      required_count, tier, icon)
-- VALUES
--     ('Social Butterfly',
--      'Receive any 3 different recognition badges from your peers',
--      50, 200, 'any_n', 3, 'silver',
--      'https://example.com/icons/butterfly.png');

-- Example: Seasonal "Summer Challenge" collection
-- INSERT INTO rewards.collectives
--     (collective_name, description, points, bonus_points, completion_type,
--      is_seasonal, start_date, end_date, tier, icon)
-- VALUES
--     ('Summer Challenge 2025',
--      'Complete all summer activities before the season ends!',
--      75, 1000, 'all', TRUE,
--      '2025-06-01 00:00:00', '2025-08-31 23:59:59', 'platinum',
--      'https://example.com/icons/summer.png');