## Nomination award system

Key Features
🏆 Complete Nomination Lifecycle

* Nomination Phase: Users nominate colleagues (or themselves if enabled)
* Voting Phase: People vote on nominees
* Winner Selection: Automatic winner determination and reward assignment

⚙️ Flexible Configuration

* Configurable duration for each phase
* Eligibility criteria (job codes, departments, tenure requirements)
* Voting limits and nomination limits per user
* Self-nomination controls

🔄 Automatic Management

* Scheduled phase transitions
* Winner selection based on vote counts
* Integration with existing reward templates and notifications

How It Works

* Create Campaign: Set up a nomination campaign for a specific reward
* Nomination Phase: Users submit nominations with reasons
* Voting Phase: Eligible users vote on their favorite nominations
* Winner Selection: System selects winner and awards the reward automatically


```json
{
    "reward_id": 9001,
    "reward": "Employee of the Month",
    "reward_type": "Nomination Badge",
    "nomination_config": {
        "nomination_duration_days": 7,
        "voting_duration_days": 5,
        "allow_self_nomination": false,
        "max_nominations_per_user": 2,
        "max_votes_per_user": 1,
        "eligible_nominators": {
            "job_codes": ["MSLASSOC", "AREAMGR"],
            "min_tenure_days": 90
        }
    }
}
```
