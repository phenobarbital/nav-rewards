# Rewards Platform Reference

## Recognition Building Blocks

### Reward Types, Categories, and Groups
- **RewardType** defines the badge/reward taxonomy that appears in selectors (`reward_type`) and exposes CRUD endpoints at `rewards/api/v1/reward_types`.【F:rewards/models.py†L43-L70】
- **RewardCategory** and **RewardGroup** segment incentives for reporting and eligibility filters, both backed by first-class API endpoints (`rewards/api/v1/reward_categories`, `rewards/api/v1/reward_groups`).【F:rewards/models.py†L72-L97】

### Badge / Reward Definition
Every badge is persisted as a `Reward` (or the richer `RewardView`) record with the following notable options.【F:rewards/models.py†L99-L210】【F:rewards/models.py†L530-L600】
- Descriptive metadata: display name, description, emoji, icon, default congratulatory message.
- Gamification knobs: point value, `multiple` for re-earning, timeframe, cooldown, and enablement flag.
- Targeting: required category, optional type/group, program whitelists, assigner/awardee lists, and JSON-based `conditions`/`availability_rule` payloads.
- Automation hooks: rule list, event subscriptions, callbacks, effective date, and workflow/challenge payloads.

### Recipient Records and Social Signals
Awards to individuals are stored through the `UserReward` model with giver/receiver identities, message, timestamp, and optional revoke audit fields. Likes and comments attach to the same award identifiers for lightweight feedback loops. REST endpoints live under `rewards/api/v1/users_rewards`, `rewards/api/v1/rewards_likes`, and `rewards/api/v1/rewards_comments`.【F:rewards/models.py†L307-L392】

### Quick Assign Form
`BadgeAssign` powers the administrative badge dialog (`POST /rewards/api/v1/badge_assign`). It accepts the reward id, receiver lookup, optional giver overrides, and a personalized message, mirroring `UserReward` while enforcing UI constraints for search widgets.【F:rewards/models.py†L602-L661】

## Reward Engines and Workflows

### Rule Framework
All policy classes extend `AbstractRule`, guaranteeing `fits` and async `evaluate` hooks that operate on an `EvalContext` and environment snapshot. Concrete rules (anniversary, attendance, hierarchy, seller metrics, random selection, etc.) live under `rewards/rules/` and can be mixed into any reward configuration. Computed rules expose dataset helpers for scheduled jobs. 【F:rewards/rules/abstract.py†L1-L60】【F:rewards/rules/__init__.py†L1-L21】

### Base RewardObject Lifecycle
Each reward instance is materialized as a `RewardObject`, loading rules, exposing reward metadata (emoji, multiple flag, timeframe), and orchestrating evaluation, templated messaging, and application to `UserReward` entries. It fabricates per-user contexts from directory attributes and injects dynamic rule parameters (e.g., current reward id for computed rules).【F:rewards/rewards/base.py†L1-L170】

### Computed Rewards
`ComputedReward` schedules batch eligibility using preconfigured jobs plus rule datasets. When a rule flags a candidate, the engine checks `fits`, awardee limits, and timeframe throttles before persisting the award. Responses include validation and database failure payloads for observability.【F:rewards/rewards/computed.py†L1-L98】

### Event-Driven Rewards
`EventReward` listens to AMQP deliveries, maps routing keys to configured queries (via QuerySource slugs), and converts the resulting dataset into eligible users through the same rule interface. Empty datasets short-circuit processing, keeping event-triggered badges lean.【F:rewards/rewards/event/evt.py†L1-L78】

### Challenge Rewards
`ChallengeReward` tracks multi-step progress in cache-backed user state. Each configured step is validated against incoming events, persisted with progress counters, and optionally reset for `multiple` rewards. Completion flips all steps to `completed` before allowing the award to fire.【F:rewards/rewards/challenge.py†L1-L175】

### Workflow Rewards
`WorkflowReward` wraps a state machine (`transitions.Machine`) with optional auto-enrollment. Workflows declare ordered steps, per-step conditions, and lifecycle callbacks registered through `WorkflowCallbackRegistry`, which dynamically loads async functions (`user, env, conn, **kwargs` signature) when transitions fire. Completion callbacks run on the `completed` state and can trigger downstream automation. 【F:rewards/rewards/workflow.py†L1-L156】

## Kudos Micro-Recognition
The Kudos subsystem offers lightweight recognition alongside formal badges: quick `/kudos` bot command, predefined/custom tags, trending analytics, REST endpoints (`/rewards/api/v1/user_kudos`, `/rewards/api/v1/kudos_tags`), and optional privacy controls. Database views expose trending tags and per-user stats to power dashboards and digests.【F:rewards/docs/kudos.md†L1-L134】

## Challenges, Campaigns, and Competitions
- **Challenges** leverage `ChallengeReward` for structured step completion (e.g., onboarding checklists or learning paths). Configure the `challenges` array within the reward record to list each milestone and arguments consumed by handlers.【F:rewards/rewards/challenge.py†L19-L63】
- **Workflow Campaigns** create competitions that require sequential milestones; auto-enroll whole cohorts and attach callbacks for leaderboard updates, swag fulfillment, or notifications.【F:rewards/rewards/workflow.py†L49-L135】
- **Rule-Driven Competitions** use computed or event rewards plus specialized rules (attendance streaks, seller rankings, random draws) to award weekly or quarterly winners without manual intervention.【F:rewards/rewards/computed.py†L24-L86】【F:rewards/rules/__init__.py†L1-L21】

## Example: Launching a Sales Sprint Badge
1. **Model the badge** – POST to `rewards/api/v1/rewards` with the desired metadata (name, points, emoji, category) and include a `rules` list referencing the sales performance rule plus any `conditions` (e.g., minimum deals).【F:rewards/models.py†L99-L177】【F:rewards/rules/__init__.py†L1-L21】
2. **Enable automation** – If results are batch-computed, set `reward_type` to a computed flavor, attach `job` metadata, and register the badge with the reward engine so nightly jobs call `ComputedReward.call_reward`.【F:rewards/rewards/computed.py†L1-L70】
3. **Promote micro-recognition** – Encourage peers to send `/kudos` with tags like `#closer` or `#teamwork` during the sprint; analytics views surface trending morale signals for managers.【F:rewards/docs/kudos.md†L5-L81】
4. **Celebrate completion** – When the computed job posts awards, recipients appear in `users_rewards`. Use optional workflow callbacks to notify Slack/Teams or auto-enroll winners into follow-up campaigns.【F:rewards/models.py†L307-L360】【F:rewards/rewards/workflow.py†L37-L103】
