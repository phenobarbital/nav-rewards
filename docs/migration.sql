--- Step 1: Drop Conflicting Constraint
ALTER TABLE rewards.users_rewards
DROP CONSTRAINT IF EXISTS unq_rewards_user_reward_system;


ALTER TABLE rewards.rewards
ADD COLUMN cooldown_minutes int DEFAULT 1;
COMMENT ON COLUMN rewards.rewards.cooldown_minutes IS
'Minimum minutes between receiving this reward (spam prevention)';
