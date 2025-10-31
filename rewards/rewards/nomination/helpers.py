from datetime import datetime
from .models import CampaignStatus

class NominationUIHelper:
    """Helper class for generating nomination UI data."""

    @staticmethod
    def get_campaign_ui_data(campaign, nominations=None, user_votes=None):
        """Generate UI-friendly campaign data."""
        now = datetime.now()

        ui_data = {
            'campaign': campaign.to_dict(),
            'current_phase': campaign.status.value,
            'is_active': campaign.status in [CampaignStatus.NOMINATION_PHASE, CampaignStatus.VOTING_PHASE],  # noqa
            'is_closed': campaign.status == CampaignStatus.CLOSED,
            'time_remaining': None,
            'can_nominate': False,
            'can_vote': False,
            'nominations': [],
            'user_nominations': 0,
            'user_votes': 0
        }

        # Calculate time remaining and permissions
        if campaign.status == CampaignStatus.NOMINATION_PHASE:
            ui_data['time_remaining'] = max(
                0, (campaign.nomination_end - now).total_seconds()
            )
            ui_data['can_nominate'] = now < campaign.nomination_end

        elif campaign.status == CampaignStatus.VOTING_PHASE:
            ui_data['time_remaining'] = max(
                0, (campaign.voting_end - now).total_seconds()
            )
            ui_data['can_vote'] = now < campaign.voting_end

        # Add nomination data
        if nominations:
            ui_data['nominations'] = [
                {
                    **nom,
                    'can_vote_for': ui_data['can_vote'] and user_votes.get(
                        nom['nomination_id'], 0
                    ) == 0
                }
                for nom in nominations
            ]

        return ui_data

    @staticmethod
    def get_user_eligibility(user, campaign):
        """Check user eligibility for various actions."""
        # This would implement the same eligibility checks
        # as the NominationAward class
        return {
            'can_nominate': True,  # Implement actual check
            'can_be_nominated': True,  # Implement actual check
            'can_vote': True,  # Implement actual check
            'remaining_nominations': campaign.max_nominations_per_user,
            'remaining_votes': campaign.max_votes_per_user
        }
