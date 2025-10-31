--- Schema Creation:
CREATE SCHEMA rewards AUTHORIZATION troc_pgdata;

-- DROP TABLE IF EXISTS rewards.reward_categories;
CREATE TABLE rewards.reward_categories (
	reward_category varchar(255) NOT NULL,
	CONSTRAINT pk_reward_categories_pkey PRIMARY KEY (reward_category)
);

INSERT INTO rewards.reward_categories (reward_category) VALUES
    ('Test Category'),
    ('T-ROC Core Values'),
    ('Sales Targets'),
    ('Effective Communication'),
    ('Empathy'),
    ('Problem-Solving'),
    ('Salesmanship'),
    ('Teamwork'),
    ('Promotion Know-How'),
    ('Conflict Resolution');
INSERT INTO rewards.reward_categories (reward_category) VALUES
    ('Self-Motivation'),
    ('Great Hair-do'),
    ('Recognition');


-- DROP TABLE IF EXISTS rewards.reward_groups;
CREATE TABLE rewards.reward_groups (
	reward_group varchar(255) NOT NULL,
	CONSTRAINT pk_reward_groups_pkey PRIMARY KEY (reward_group)
);

INSERT INTO rewards.reward_groups (reward_group) VALUES
    ('Test Badges'),
    ('Core Badges'),
    ('TROC Badges');


-- DROP TABLE IF EXISTS rewards.reward_types;
CREATE TABLE rewards.reward_types (
	reward_type varchar NOT NULL,
	description varchar(255) NOT NULL,
	CONSTRAINT pk_award_types_pkey PRIMARY KEY (reward_type)
);

INSERT INTO rewards.reward_types (reward_type,description) VALUES
    ('Test Badge','This is a test badge'),
    ('User Badge','An User can assign this Badge'),
    ('Automated Badge','This Badge is assigned by automatic rules'),
    ('Recognition Badge','Appreciation or Recognition based on some merits/virtues');

-- DROP TABLE IF EXISTS rewards.reward_permissions;
CREATE TABLE rewards.reward_permissions (
	permission_id bigserial NOT NULL,
	group_id int8 NOT NULL,
	reward_id int8 NOT NULL,
	permission_type varchar(50) NOT NULL,
	inserted_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT pk_group_permissions_pkey PRIMARY KEY (permission_id),
	CONSTRAINT fk_group_permissions_group FOREIGN KEY (group_id) REFERENCES auth."groups"(group_id) ON DELETE CASCADE ON UPDATE CASCADE,
	CONSTRAINT fk_group_permissions_reward FOREIGN KEY (reward_id) REFERENCES rewards.rewards(reward_id) ON DELETE CASCADE ON UPDATE CASCADE
);

--- Functions:
-- DROP FUNCTION rewards.add_karma_after_award();
CREATE OR REPLACE FUNCTION rewards.add_karma_after_award()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    reward_points INT;
BEGIN
    -- Ensure receiver_user must be not NULL
    IF NEW.receiver_user IS NULL THEN
       RETURN NEW;
    END IF;

    -- Get the points from the rewards table, default to 10 if not found
    SELECT COALESCE(points, 10) INTO reward_points FROM rewards.rewards WHERE reward_id = NEW.reward_id;

    -- if reward is null, then is a system reward
    IF reward_points IS NULL THEN
        reward_points = NEW.points;
    END IF;

    -- Insert points for the receiver
    INSERT INTO rewards.points (user_id, points)
    VALUES (NEW.receiver_user, reward_points);

    -- Insert 1 point for the giver for giving a badge
    -- Check if giver_user is not NULL to avoid inserting points for system actions
    IF NEW.giver_user IS NOT NULL THEN
        INSERT INTO rewards.points (user_id, points)
        VALUES (NEW.giver_user, 1);
    END IF;

    RETURN NEW;
END;
$function$
;

-- DROP FUNCTION rewards.check_user_points_for_comment();

CREATE OR REPLACE FUNCTION rewards.check_user_points_for_comment()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    user_points INT;
BEGIN
    -- Check the points of the user
    SELECT points INTO user_points FROM rewards.points WHERE user_id = NEW.user_id;

    -- If the points are zero or less, raise an exception and prevent the insert
    IF user_points IS NULL OR user_points <= 0 THEN
        RAISE EXCEPTION 'The user has insufficient points to add a comment.';
    END IF;

    -- If the points are sufficient, allow the insert
    RETURN NEW;
END;
$function$
;

-- DROP FUNCTION rewards.check_giver_points();
CREATE OR REPLACE FUNCTION rewards.check_giver_points()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    giver_points INT;
BEGIN
    -- Check the points of the giver_user
    SELECT points INTO giver_points FROM rewards.points WHERE user_id = NEW.giver_user;

    -- If the points are zero or less, raise an exception and prevent the insert
    --- IF giver_points IS NULL OR giver_points < 0 THEN
    IF giver_points < 0 THEN
        RAISE EXCEPTION 'The giver_user has insufficient points to assign a badge.';
    END IF;

    -- If the points are sufficient, allow the insert
    RETURN NEW;
END;
$function$
;



-- DROP TABLE IF EXISTS rewards.rewards;
CREATE TABLE rewards.rewards (
	reward_id bigserial NOT NULL,
	reward varchar(255) NOT NULL,
	description varchar NULL,
	points int4 DEFAULT 10 NOT NULL,
	multiple bool DEFAULT false NOT NULL,
	reward_type varchar NULL,
	reward_group varchar NULL,
	reward_category varchar NULL,
	programs _varchar NULL,
	icon varchar NULL,
	"attributes" jsonb NULL,
	availability_rule jsonb DEFAULT '{}'::jsonb NOT NULL,
	rules jsonb DEFAULT '{}'::jsonb NOT NULL,
	conditions jsonb DEFAULT '{}'::jsonb NULL,
	effective_date timestamptz DEFAULT now() NOT NULL,
	inserted_at timestamptz DEFAULT now() NOT NULL,
    inserted_by varchar(255) NULL,
    updated_at timestamptz DEFAULT now() NOT NULL,
    updated_by varchar(255) NULL,
	deleted_at timestamptz NULL,
    deleted_by varchar(255) NULL,
    is_enabled bool DEFAULT true NOT NULL,
    completion_callbacks jsonb DEFAULT '[]'::jsonb NOT NULL,
    step_callbacks jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT chk_rewards_points_positive CHECK (points >= 0),
	CONSTRAINT pk_rewards_rewards_pkey PRIMARY KEY (reward_id),
	CONSTRAINT fk_auth_users_rewards_category FOREIGN KEY (reward_category) REFERENCES rewards.reward_categories(reward_category) ON DELETE RESTRICT ON UPDATE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_auth_users_rewards_groups FOREIGN KEY (reward_group) REFERENCES rewards.reward_groups(reward_group) ON DELETE RESTRICT ON UPDATE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_auth_users_rewards_type FOREIGN KEY (reward_type) REFERENCES rewards.reward_types(reward_type) ON DELETE RESTRICT ON UPDATE CASCADE DEFERRABLE INITIALLY DEFERRED
);

INSERT INTO rewards.rewards (reward,description,points,multiple,reward_type,reward_group,reward_category,programs,icon,"attributes",availability_rule,rules,conditions,effective_date,inserted_at) VALUES
    ('Special Automated Badge','A special badge awarded automatically on specific days and times',10,false,'Automated Badge','Test Badges','Test Category','{walmart,mso}','path/to/icon.png','{}','{"dow": [3, 5], "end_time": "17:00:00", "start_time": "09:00:00"}','{}','{}','2024-02-13 19:33:10.025635+01','2024-02-13 19:33:10.025635+01'),
    ('Assignable Badge','A special badge awarded only on specific days and times',10,false,'User Badge','Test Badges','Test Category',NULL,'path/to/icon.png','{}','{"dow": [0, 1, 2, 3, 4], "end_time": "23:20:00", "start_time": "10:00:00"}','{}','{}','2024-02-13 19:33:10.025635+01','2024-02-13 19:33:10.025635+01');

-- DROP TABLE IF EXISTS rewards.points;
CREATE TABLE rewards.points (
	point_id bigserial NOT NULL,
	user_id int8 NOT NULL,
	points int4 DEFAULT 0 NOT NULL,
	awarded_at timestamptz DEFAULT CURRENT_TIMESTAMP NOT NULL,
	CONSTRAINT pk_rewards_users_karma_points_pkey PRIMARY KEY (point_id),
	CONSTRAINT unq_rewards_users_karma UNIQUE (user_id, awarded_at),
	CONSTRAINT fk_auth_users_karma FOREIGN KEY (user_id) REFERENCES auth.users(user_id) ON DELETE RESTRICT ON UPDATE CASCADE DEFERRABLE INITIALLY DEFERRED
);


-- rewards.users_rewards definition
-- DROP TABLE IF EXISTS rewards.users_rewards;

CREATE TABLE rewards.users_rewards (
	award_id bigserial NOT NULL,
	reward_id int8 NULL,
	reward varchar NULL,
	giver_user int8 NULL,
	giver_email varchar NULL,
	giver_employee varchar NULL,
	message varchar NULL,
	receiver_user int8 NOT NULL,
	receiver_email varchar NULL,
	receiver_employee varchar NULL,
	receiver_id varchar NULL,
	original_email varchar NULL,
	points int8 NULL,
	awarded_at timestamptz DEFAULT CURRENT_TIMESTAMP NOT NULL,
	revoked bool DEFAULT false NOT NULL,
	revoked_at timestamptz NULL,
	revoked_by int8 NULL,
	deleted_at timestamptz NULL,
	CONSTRAINT chk_no_self_assign CHECK ((giver_user <> receiver_user)),
	CONSTRAINT pk_rewards_users_rewards_pkey PRIMARY KEY (award_id),
	CONSTRAINT unq_rewards_user_reward_awardet_at UNIQUE (receiver_email, reward_id, awarded_at),
	CONSTRAINT unq_rewards_user_reward_system UNIQUE (giver_email, receiver_email, reward_id),
	CONSTRAINT fk_auth_users_rewards_giver_user FOREIGN KEY (giver_user) REFERENCES auth.users(user_id) ON DELETE RESTRICT ON UPDATE CASCADE DEFERRABLE INITIALLY DEFERRED,
	CONSTRAINT fk_auth_users_rewards_receiver_user FOREIGN KEY (receiver_user) REFERENCES auth.users(user_id) ON DELETE RESTRICT ON UPDATE CASCADE DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX idx_users_rewards_giver_receiver ON rewards.users_rewards USING btree (giver_user, receiver_user);
CREATE INDEX idx_users_rewards_giver_user ON rewards.users_rewards USING btree (giver_user);
CREATE INDEX idx_users_rewards_receiver_user ON rewards.users_rewards USING btree (receiver_user);
CREATE INDEX idx_users_rewards_revoked ON rewards.users_rewards USING btree (revoked);
CREATE INDEX idx_users_rewards_reward_id ON rewards.users_rewards USING btree (reward_id);

-- Table Triggers

create trigger trg_add_karma_after_award after
insert
    on
    rewards.users_rewards for each row execute function rewards.add_karma_after_award();
create trigger trigger_check_giver_points before
insert
    on
    rewards.users_rewards for each row execute function rewards.check_giver_points();

--- View Definition:
CREATE OR REPLACE VIEW rewards.vw_rewards
AS SELECT r.reward_id,
    r.reward,
    r.description,
    r.points,
    r.multiple,
    r.reward_type,
    r.reward_group,
    r.reward_category,
    r.programs,
    r.icon,
    r.attributes,
    r.availability_rule,
    r.rules,
    r.conditions,
    s.groups AS assigner,
    w.groups AS awardee,
    r.completion_callbacks,
    r.step_callbacks,
    r.effective_date
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
  WHERE r.deleted_at IS NULL AND r.effective_date <= CURRENT_TIMESTAMP;
