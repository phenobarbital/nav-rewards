--- Step 1: Drop Conflicting Constraint
ALTER TABLE rewards.users_rewards
DROP CONSTRAINT IF EXISTS unq_rewards_user_reward_system;


ALTER TABLE rewards.rewards
ADD COLUMN cooldown_minutes int DEFAULT 1;
COMMENT ON COLUMN rewards.rewards.cooldown_minutes IS
'Minimum minutes between receiving this reward (spam prevention)';

-- Timeframe between receiving the same reward
ALTER TABLE rewards.rewards
ADD COLUMN timeframe varchar DEFAULT 'daily';
COMMENT ON COLUMN rewards.rewards.timeframe IS
'Timeframe between receiving the same reward (e.g., daily, weekly)';

ALTER TABLE rewards.rewards
ADD COLUMN auto_enroll boolean DEFAULT FALSE;
COMMENT ON COLUMN rewards.rewards.auto_enroll IS
'If True, users will be automatically enrolled in this reward';

-- rewards.vw_rewards View
CREATE OR REPLACE VIEW rewards.vw_rewards
AS SELECT
    r.reward_id,
    r.reward,
    r.description,
    r.points,
    r.multiple,
    r.reward_type,
    r.reward_group,
    r.reward_category,
    r.programs,
    r.icon,
    r.emoji,
    r.attributes,
    r.availability_rule,
    r.rules,
    r.message,
    r.conditions,
    s.groups AS assigner,
    w.groups AS awardee,
    r.timeframe,
    r.cooldown_minutes,
    r.effective_date,
    r.auto_enroll,
    --- callbacks
    r.completion_callbacks,
    r.step_callbacks,
    r.awarded_callbacks
   FROM rewards.rewards r
     LEFT JOIN ( SELECT array_agg(g.group_name) AS groups,
            rp.reward_id
           FROM rewards.reward_permissions rp
             JOIN auth.groups g USING (group_id)
          WHERE rp.permission_type::text = 'assigner'::text
          GROUP BY rp.reward_id) s ON s.reward_id = r.reward_id
     LEFT JOIN ( SELECT array_agg(g.group_name) AS groups,
            rp.reward_id
           FROM rewards.reward_permissions rp
             JOIN auth.groups g USING (group_id)
          WHERE rp.permission_type::text = 'awardee'::text
          GROUP BY rp.reward_id) w ON w.reward_id = r.reward_id
  WHERE r.is_enabled = TRUE AND r.deleted_at IS NULL AND r.effective_date <= CURRENT_TIMESTAMP;
