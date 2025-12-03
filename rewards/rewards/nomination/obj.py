"""Nomination-based Reward Object."""
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from ..base import RewardObject
from ..workflow import WorkflowReward
from ...models import (
    RewardView,
    UserReward,
    User,
    get_user,
    filter_users,
)
from ...context import EvalContext
from ...env import Environment
from .models import (
    NominationCampaign,
    Nomination,
    NominationVote,
    CampaignStatus
)


class NominationAward(WorkflowReward):
    """
    Nomination-based Award system.

    Supports two modes:
    1. Open Nominations: Users nominate candidates, then vote
        Manages the complete nomination lifecycle:
        1. Nomination Phase - Users nominate candidates
        2. Voting Phase - Users vote on nominations
        3. Winner Selection - Determine winner and award reward
    2. Pre-defined Candidates: Admin provides candidates, users only vote
    """
    type: str = 'nomination'

    def __init__(
        self,
        reward: RewardView,
        rules: Optional[list] = None,
        conditions: Optional[dict] = None,
        nomination_config: Optional[dict] = None,
        **kwargs
    ) -> None:
        # Set up workflow states for nomination process
        workflow_steps = [
            {"step": "Nomination Phase"},
            {"step": "Voting Phase"},
            {"step": "Winner Selection"}
        ]

        super().__init__(
            reward,
            rules,
            conditions,
            workflow=workflow_steps,
            auto_evaluation=False,  # Manual phase transitions
            **kwargs
        )

        # Nomination-specific configuration
        self.nomination_config = nomination_config or {}
        self._setup_nomination_config()

    def _setup_nomination_config(self):
        """Setup nomination configuration with defaults."""
        config = self.nomination_config

        # Campaign type: 'open' or 'pre_candidates'
        self.campaign_type = config.get('campaign_type', 'open')

        # Duration settings
        self.nomination_duration_days = config.get(
            'nomination_duration_days',
            7
        )
        self.voting_duration_days = config.get('voting_duration_days', 5)

        # Participation settings
        # Allow self-nomination or not
        # This can be overridden by campaign config
        self.allow_self_nomination = config.get('allow_self_nomination', False)
        self.max_nominations_per_user = config.get(
            'max_nominations_per_user',
            1
        )
        self.max_votes_per_user = config.get('max_votes_per_user', 1)
        self.min_nominations_to_proceed = config.get(
            'min_nominations_to_proceed',
            1
        )
        # Pre-candidates settings
        self.allow_additional_nominations = config.get(
            'allow_additional_nominations',
            False
        )
        self.require_candidate_approval = config.get(
            'require_candidate_approval',
            False
        )

        # Eligibility criteria
        self.eligible_nominators = config.get('eligible_nominators', {})
        self.eligible_nominees = config.get('eligible_nominees', {})
        self.eligible_voters = config.get('eligible_voters', {})

    async def create_campaign(
        self,
        ctx: EvalContext,
        env: Environment,
        campaign_name: str,
        description: str = "",
        start_date: datetime = None
    ) -> NominationCampaign:
        """Create a new nomination campaign."""
        if start_date is None:
            start_date = env.timestamp + timedelta(hours=1)

        nomination_end = start_date + timedelta(
            days=self.nomination_duration_days
        )
        voting_start = nomination_end + timedelta(hours=1)
        voting_end = voting_start + timedelta(days=self.voting_duration_days)

        campaign_data = {
            'campaign_name': campaign_name,
            'description': description,
            'reward_id': self._reward.reward_id,
            'nomination_start': start_date,
            'nomination_end': nomination_end,
            'voting_start': voting_start,
            'voting_end': voting_end,
            'allow_self_nomination': self.allow_self_nomination,
            'max_nominations_per_user': self.max_nominations_per_user,
            'max_votes_per_user': self.max_votes_per_user,
            'min_nominations_to_proceed': self.min_nominations_to_proceed,
            'eligible_nominators': self.eligible_nominators,
            'eligible_nominees': self.eligible_nominees,
            'eligible_voters': self.eligible_voters,
            'created_by': ctx.user.user_id,
            'status': CampaignStatus.DRAFT
        }

        async with await env.connection.acquire() as conn:
            NominationCampaign.Meta.connection = conn
            campaign = NominationCampaign(**campaign_data)
            return await campaign.insert()

    async def create_campaign_with_candidates(
        self,
        ctx: EvalContext,
        env: Environment,
        campaign_name: str,
        description: str = "",
        candidates: List[Dict[str, Any]] = None,
        start_date: datetime = None
    ) -> NominationCampaign:
        """
        Create a campaign with pre-defined candidates.

        Args:
            candidates: List of dicts with keys:
                user_id,
                reason,
                nominator_info
        """
        if start_date is None:
            start_date = env.timestamp + timedelta(hours=1)

        # For pre-candidate campaigns, skip nomination phase
        voting_start = start_date
        voting_end = voting_start + timedelta(days=self.voting_duration_days)

        campaign_data = {
            'campaign_name': campaign_name,
            'description': description,
            'reward_id': self._reward.reward_id,
            'nomination_start': start_date,  # Not used for pre-candidates
            'nomination_end': start_date,    # Not used for pre-candidates
            'voting_start': voting_start,
            'voting_end': voting_end,
            'allow_self_nomination': self.allow_self_nomination,
            'max_nominations_per_user': self.max_nominations_per_user,
            'max_votes_per_user': self.max_votes_per_user,
            'min_nominations_to_proceed': 0,  # Not needed for pre-candidates
            'eligible_nominators': self.eligible_nominators,
            'eligible_nominees': self.eligible_nominees,
            'eligible_voters': self.eligible_voters,
            'created_by': ctx.user.user_id,
            'status': CampaignStatus.DRAFT,

            # Additional metadata for pre-candidates
            'campaign_metadata': {
                'campaign_type': 'pre_candidates',
                'total_pre_candidates': len(candidates) if candidates else 0,
                'allow_additional_nominations': self.allow_additional_nominations  # noqa
            }
        }

        async with await env.connection.acquire() as conn:
            NominationCampaign.Meta.connection = conn
            campaign = NominationCampaign(**campaign_data)
            created_campaign = await campaign.insert()

            # Add pre-defined candidates if provided
            if candidates:
                await self._add_pre_candidates(
                    conn, created_campaign.campaign_id, candidates, ctx, env
                )

            return created_campaign

    async def start_nomination_phase(
        self,
        campaign_id: int,
        env: Environment
    ) -> bool:
        """Start the nomination phase of a campaign."""
        try:
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                if campaign.status != CampaignStatus.DRAFT:
                    raise ValueError(
                        "Campaign must be in DRAFT status to start"
                    )

                campaign.status = CampaignStatus.NOMINATION_PHASE
                campaign.updated_at = env.timestamp
                await campaign.save()

                self.logger.info(
                    f"Started nomination phase for campaign {campaign_id}"
                )
                return True

        except Exception as err:
            self.logger.error(f"Error starting nomination phase: {err}")
            return False

    async def submit_nomination(
        self,
        ctx: EvalContext,
        env: Environment,
        campaign_id: int,
        nominee_user_id: int,
        reason: str,
        supporting_evidence: str = ""
    ) -> Optional[Nomination]:
        """Submit a nomination for a campaign."""
        try:
            # Get nominee information
            nominee = await get_user(env.connection, nominee_user_id)
            async with await env.connection.acquire() as conn:
                # Validate campaign and phase
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                if campaign.status != CampaignStatus.NOMINATION_PHASE:
                    raise ValueError("Campaign is not in nomination phase")

                if env.timestamp > campaign.nomination_end:
                    raise ValueError("Nomination phase has ended")

                # Check eligibility
                if not await self._check_nominator_eligibility(ctx, campaign):
                    raise ValueError("User not eligible to nominate")

                # Check if user can nominate this person
                if not campaign.allow_self_nomination and nominee_user_id == ctx.user.user_id:  # noqa
                    raise ValueError("Self-nomination not allowed")

                # Check nomination limit
                existing_nominations = await self._count_user_nominations(
                    conn, campaign_id, ctx.user.user_id
                )
                if existing_nominations >= campaign.max_nominations_per_user:
                    raise ValueError("Maximum nominations per user exceeded")

                # Create nomination
                Nomination.Meta.connection = conn
                nomination_data = {
                    'campaign_id': campaign_id,
                    'nominee_user_id': nominee_user_id,
                    'nominee_email': nominee.email,
                    'nominee_name': nominee.display_name,
                    'nominator_user_id': ctx.user.user_id,
                    'nominator_email': ctx.user.email,
                    'nominator_name': ctx.user.display_name,
                    'reason': reason,
                    'supporting_evidence': supporting_evidence
                }

                nomination = Nomination(**nomination_data)
                result = await nomination.insert()

                # Update campaign nomination count
                await self._update_campaign_stats(conn, campaign_id)

                self.logger.info(
                    f"User {ctx.user.email} nominated {nominee.email} "
                    f"for campaign {campaign_id}"
                )

                return result

        except Exception as err:
            self.logger.error(f"Error submitting nomination: {err}")
            return None

    async def start_voting_phase(
        self,
        campaign_id: int,
        env: Environment
    ) -> bool:
        """Transition campaign to voting phase."""
        try:
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                if campaign.status != CampaignStatus.NOMINATION_PHASE:
                    raise ValueError("Campaign must be in nomination phase")

                # Check if minimum nominations met
                if campaign.total_nominations < campaign.min_nominations_to_proceed:  # noqa
                    raise ValueError(
                        f"Minimum {campaign.min_nominations_to_proceed} "
                        f"nominations required, only {campaign.total_nominations} received"  # noqa
                    )

                campaign.status = CampaignStatus.VOTING_PHASE
                campaign.updated_at = env.timestamp
                await campaign.save()

                self.logger.info(
                    f"Started voting phase for campaign {campaign_id}"
                )
                return True

        except Exception as err:
            self.logger.error(f"Error starting voting phase: {err}")
            return False

    async def submit_vote(
        self,
        ctx: EvalContext,
        env: Environment,
        campaign_id: int,
        nomination_id: int,
        vote_comment: str = ""
    ) -> Optional[NominationVote]:
        """Submit a vote for a nomination."""
        try:
            async with await env.connection.acquire() as conn:
                # Validate campaign and phase
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                if campaign.status != CampaignStatus.VOTING_PHASE:
                    raise ValueError("Campaign is not in voting phase")

                if env.timestamp > campaign.voting_end:
                    raise ValueError("Voting phase has ended")

                # Check voter eligibility
                if not await self._check_voter_eligibility(ctx, campaign):
                    raise ValueError("User not eligible to vote")

                # Check if user already voted
                existing_votes = await self._count_user_votes(
                    conn, campaign_id, ctx.user.user_id
                )
                if existing_votes >= campaign.max_votes_per_user:
                    raise ValueError("Maximum votes per user exceeded")

                # Validate nomination exists and is active
                Nomination.Meta.connection = conn
                nomination = await Nomination.get(nomination_id=nomination_id)

                if nomination.campaign_id != campaign_id:
                    raise ValueError(
                        "Nomination does not belong to this campaign"
                    )

                if not nomination.is_active:
                    raise ValueError("Nomination is not active")

                # Create vote
                NominationVote.Meta.connection = conn
                vote_data = {
                    'nomination_id': nomination_id,
                    'campaign_id': campaign_id,
                    'voter_user_id': ctx.user.user_id,
                    'voter_email': ctx.user.email,
                    'voter_name': ctx.user.display_name,
                    'vote_comment': vote_comment
                }

                vote = NominationVote(**vote_data)
                result = await vote.insert()

                # Update nomination vote count
                await self._update_nomination_vote_count(conn, nomination_id)
                await self._update_campaign_stats(conn, campaign_id)

                self.logger.info(
                    f"User {ctx.user.email} voted for nomination {nomination_id} "  # noqa
                    f"in campaign {campaign_id}"
                )

                return result

        except Exception as err:
            self.logger.error(f"Error submitting vote: {err}")
            return None

    async def close_campaign_and_select_winner(
        self,
        campaign_id: int,
        env: Environment
    ) -> Optional[Nomination]:
        """Close voting and select the winner."""
        try:
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                if campaign.status != CampaignStatus.VOTING_PHASE:
                    raise ValueError("Campaign must be in voting phase")

                # Find winner (nomination with most votes)
                winner = await self._select_winner(conn, campaign_id)
                campaign.status = CampaignStatus.CLOSED
                campaign.updated_at = env.timestamp
                if winner:
                    # Update campaign with winner
                    campaign.winner_user_id = winner.nominee_user_id
                    campaign.winner_email = winner.nominee_email
                    await campaign.save()

                    # Mark winning nomination
                    Nomination.Meta.connection = conn
                    winner.is_winner = True
                    await winner.save()

                    # Award the reward to the winner
                    await self._award_winner(winner, env, conn)

                    self.logger.info(
                        f"Campaign {campaign_id} closed. "
                        f"Winner: {winner.nominee_email}"
                    )

                    return winner
                else:
                    # No clear winner
                    await campaign.save()

                    self.logger.info(
                        f"Campaign {campaign_id} closed with no winner"
                    )
                    return None

        except Exception as err:
            self.logger.error(f"Error closing campaign: {err}")
            return None

    async def _check_nominator_eligibility(
        self,
        ctx: EvalContext,
        campaign: NominationCampaign
    ) -> bool:
        """Check if user is eligible to nominate."""
        return await self._check_eligibility(ctx, campaign.eligible_nominators)

    async def _check_voter_eligibility(
        self,
        ctx: EvalContext,
        campaign: NominationCampaign
    ) -> bool:
        """Check if user is eligible to vote."""
        return await self._check_eligibility(ctx, campaign.eligible_voters)

    async def _check_eligibility(
        self,
        ctx: EvalContext,
        criteria: dict
    ) -> bool:
        """Check user eligibility against criteria."""
        if not criteria:
            return True  # No restrictions

        user = ctx.user
        session = ctx.session

        # Check job codes
        if 'job_codes' in criteria:
            user_job_code = getattr(user, 'job_code', None)
            if user_job_code not in criteria['job_codes']:
                return False

        # Check groups
        if 'groups' in criteria:
            user_groups = session.get('groups', [])
            if all(group not in criteria['groups'] for group in user_groups):
                return False

        # Check departments
        if 'departments' in criteria:
            user_dept = getattr(user, 'department_code', None)
            if user_dept not in criteria['departments']:
                return False

        return True

    async def _count_user_nominations(
        self,
        conn,
        campaign_id: int,
        user_id: int
    ) -> int:
        """Count nominations submitted by user for campaign."""
        query = """
            SELECT COUNT(*) FROM rewards.nominations
            WHERE campaign_id = $1 AND nominator_user_id = $2
            AND is_active = true
        """
        return await conn.fetchval(query, campaign_id, user_id) or 0

    async def _count_user_votes(
        self,
        conn,
        campaign_id: int,
        user_id: int
    ) -> int:
        """Count votes submitted by user for campaign."""
        query = """
            SELECT COUNT(*) FROM rewards.nomination_votes
            WHERE campaign_id = $1 AND voter_user_id = $2
        """
        return await conn.fetchval(query, campaign_id, user_id) or 0

    async def _update_nomination_vote_count(self, conn, nomination_id: int):
        """Update vote count for a nomination."""
        query = """
            UPDATE rewards.nominations
            SET vote_count = (
                SELECT COUNT(*) FROM rewards.nomination_votes
                WHERE nomination_id = $1
            )
            WHERE nomination_id = $1
        """
        await conn.execute(query, nomination_id)

    async def _update_campaign_stats(self, conn, campaign_id: int):
        """Update campaign statistics."""
        query = """
            UPDATE rewards.nomination_campaigns
            SET
                total_nominations = (
                    SELECT COUNT(*) FROM rewards.nominations
                    WHERE campaign_id = $1 AND is_active = true
                ),
                total_votes = (
                    SELECT COUNT(*) FROM rewards.nomination_votes
                    WHERE campaign_id = $1
                )
            WHERE campaign_id = $1
        """
        await conn.execute(query, campaign_id)

    async def _select_winner(
        self,
        conn,
        campaign_id: int
    ) -> Optional[Nomination]:
        """Select winner based on votes."""
        query = """
            SELECT nomination_id, nominee_user_id, nominee_email,
            vote_count, reason
            FROM rewards.nominations
            WHERE campaign_id = $1 AND is_active = true
            ORDER BY vote_count DESC, nominated_at ASC
            LIMIT 1
        """
        result = await conn.fetch_one(query, campaign_id)

        if result and result['vote_count'] > 0:
            Nomination.Meta.connection = conn
            return await Nomination.get(
                nomination_id=result['nomination_id']
            )

        return None

    async def _award_winner(
        self,
        winner: Nomination,
        env: Environment,
        conn
    ):
        """Award the reward to the winner."""
        try:
            # Create user context for winner
            winner_user = await get_user(env.connection, winner.nominee_user_id)
            # Create evaluation context for winner
            ctx = self._get_context_user(winner_user)

            # Generate award message
            message = await self._reward_message(
                ctx,
                env,
                winner_user,
                nomination=winner
            )

            # Create reward record
            email = winner.nominee_email
            args = {
                "reward_id": self._reward.reward_id,
                "reward": self._reward.reward,
                "receiver_user": winner.nominee_user_id,
                "receiver_email": email,
                "receiver_id": winner.nominee_user_id,
                "receiver_employee": getattr(
                    winner_user,
                    'associate_id',
                    email
                ),
                "points": self._reward.points,
                "awarded_at": env.timestamp,
                "message": message
            }

            UserReward.Meta.connection = conn
            reward = UserReward(**args)
            await reward.insert()

            self.logger.info(
                f"Awarded {self._reward.reward} to {winner.nominee_email} "
                f"for nomination campaign"
            )

        except Exception as err:
            self.logger.error(f"Error awarding winner: {err}")
            raise

    def _get_context_user(self, user) -> EvalContext:
        """Create evaluation context for user."""
        email = user.email
        session = {
            "username": email,
            "id": email,
            "user_id": user.user_id,
            "name": user.display_name,
            "first_name": getattr(user, 'first_name', ''),
            "last_name": getattr(user, 'last_name', ''),
            "display_name": user.display_name,
            "email": user.email,
            "associate_id": getattr(user, 'associate_id', email),
            "session": {
                "groups": getattr(user, 'groups', []),
                "programs": getattr(user, 'programs', []),
            }
        }

        return EvalContext(
            request=None,
            user=user,
            session=session
        )

    async def get_real_time_vote_counts(
        self,
        campaign_id: int,
        env: Environment
    ) -> List[Dict[str, Any]]:
        """Get real-time vote counts for quick updates."""
        try:
            async with await env.connection.acquire() as conn:
                query = """
                    SELECT
                        n.nomination_id,
                        n.nominee_user_id,
                        n.nominee_name,
                        n.vote_count,
                        RANK() OVER (
                            ORDER BY n.vote_count DESC,
                            n.nominated_at ASC
                        ) as current_rank
                    FROM rewards.nominations n
                    WHERE n.campaign_id = $1 AND n.is_active = true
                    ORDER BY n.vote_count DESC, n.nominated_at ASC
                """
                results = await conn.fetch_all(query, campaign_id)

                return [
                    {
                        'nomination_id': result['nomination_id'],
                        'nominee_user_id': result['nominee_user_id'],
                        'nominee_name': result['nominee_name'],
                        'vote_count': result['vote_count'],
                        'current_rank': result['current_rank']
                    }
                    for result in results
                ]

        except Exception as err:
            self.logger.error(f"Error getting real-time vote counts: {err}")
            return []

    async def _count_eligible_voters(
        self,
        conn,
        campaign: NominationCampaign
    ) -> int:
        """Count total eligible voters for the campaign."""
        try:
            # If no voter restrictions, count all active users
            if not campaign.eligible_voters:
                query = """
                SELECT COUNT(*) FROM auth.users WHERE is_active = true
                """
                return await conn.fetchval(query) or 0

            # Build query based on eligibility criteria
            where_conditions = ["u.is_active = true"]
            params = []
            param_count = 0

            criteria = campaign.eligible_voters

            if 'job_codes' in criteria:
                param_count += 1
                where_conditions.append(
                    f"u.job_code = ANY(${param_count})"
                )
                params.append(criteria['job_codes'])

            if 'departments' in criteria:
                param_count += 1
                where_conditions.append(
                    f"u.department_code = ANY(${param_count})"
                )
                params.append(criteria['departments'])

            # if 'groups' in criteria:
            #     # This would need to be adjusted based on
            #  your user-group relationship
            #     pass

            where_clause = " AND ".join(where_conditions)
            query = f"SELECT COUNT(*) FROM auth.vw_users u WHERE {where_clause}"  # noqa

            return await conn.fetchval(query, *params) or 0

        except Exception as err:
            self.logger.error(f"Error counting eligible voters: {err}")
            return 0

    async def get_campaign_vote_statistics(
        self,
        campaign_id: int,
        env: Environment,
        include_voter_details: bool = False
    ) -> Dict[str, Any]:
        """
        Get detailed vote statistics for a campaign.

        Returns vote counts for each candidate and overall statistics.
        """
        try:
            async with await env.connection.acquire() as conn:
                # Get campaign info
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                # Get candidate vote counts
                candidates_query = """
                    SELECT
                        n.nomination_id,
                        n.nominee_user_id,
                        n.nominee_email,
                        n.nominee_name,
                        n.reason,
                        n.supporting_evidence,
                        n.vote_count,
                        n.nominated_at,
                        n.is_pre_candidate,
                        u.display_name as nominee_display_name,
                        u.department_code,
                        u.job_code
                    FROM rewards.nominations n
                    LEFT JOIN auth.vw_users u ON n.nominee_user_id = u.user_id
                    WHERE n.campaign_id = $1 AND n.is_active = true
                    ORDER BY n.vote_count DESC, n.nominated_at ASC
                """
                candidates = await conn.fetch_all(
                    candidates_query,
                    campaign_id
                )

                # Get overall voting statistics
                voting_stats_query = """
                    SELECT
                        COUNT(DISTINCT nv.voter_user_id) as unique_voters,
                        COUNT(nv.vote_id) as total_votes,
                        COUNT(DISTINCT nv.nomination_id) as nominations_with_votes,
                        MAX(nv.voted_at) as last_vote_time,
                        MIN(nv.voted_at) as first_vote_time
                    FROM rewards.nomination_votes nv
                    WHERE nv.campaign_id = $1
                """  # noqa
                voting_stats = await conn.fetch_one(
                    voting_stats_query,
                    campaign_id
                )

                # Get vote distribution
                vote_query = """
                    SELECT
                        n.vote_count,
                        COUNT(*) as candidates_with_this_count
                    FROM rewards.nominations n
                    WHERE n.campaign_id = $1 AND n.is_active = true
                    GROUP BY n.vote_count
                    ORDER BY n.vote_count DESC
                """
                vote_distribution = await conn.fetch_all(
                    vote_query,
                    campaign_id
                )

                # Prepare candidate details
                candidate_details = []
                for candidate in candidates:
                    candidate_info = {
                        'nomination_id': candidate['nomination_id'],
                        'candidate': {
                            'user_id': candidate['nominee_user_id'],
                            'email': candidate['nominee_email'],
                            'name': candidate['nominee_name'],
                            'display_name': candidate['nominee_display_name'],
                            'department': candidate['department_code'],
                            'job_code': candidate['job_code']
                        },
                        'nomination_details': {
                            'reason': candidate['reason'],
                            'supporting_evidence': candidate['supporting_evidence'],  # noqa
                            'nominated_at': candidate['nominated_at'].isoformat() if candidate['nominated_at'] else None,  # noqa
                            'is_pre_candidate': candidate['is_pre_candidate']
                        },
                        'vote_statistics': {
                            'vote_count': candidate['vote_count'],
                            'rank': len([c for c in candidates if c['vote_count'] > candidate['vote_count']]) + 1  # noqa
                        }
                    }

                    # Add voter details if requested
                    if include_voter_details:
                        voter_details = """
                            SELECT
                                nv.voter_user_id,
                                nv.voter_email,
                                nv.voter_name,
                                nv.voted_at,
                                nv.vote_comment,
                                u.department_code as voter_department,
                                u.job_code as voter_job_code
                            FROM rewards.nomination_votes nv
                            LEFT JOIN auth.vw_users u ON nv.voter_user_id = u.user_id
                            WHERE nv.nomination_id = $1
                            ORDER BY nv.voted_at DESC
                        """  # noqa
                        voters = await conn.fetch_all(
                            voter_details,
                            candidate['nomination_id']
                        )
                        candidate_info['voters'] = [
                            dict(voter) for voter in voters
                        ]

                    candidate_details.append(candidate_info)

                # Calculate voting progress
                eligible_voters_count = await self._count_eligible_voters(
                    conn,
                    campaign
                )
                voting_participation_rate = (
                    (
                        voting_stats['unique_voters'] / eligible_voters_count * 100  # noqa
                    )
                    if eligible_voters_count > 0 and voting_stats['unique_voters']  # noqa
                    else 0
                )

                # Prepare response
                return {
                    'campaign_info': {
                        'campaign_id': campaign.campaign_id,
                        'campaign_name': campaign.campaign_name,
                        'description': campaign.description,
                        'status': campaign.status.value,
                        'voting_start': campaign.voting_start.isoformat() if campaign.voting_start else None,  # noqa
                        'voting_end': campaign.voting_end.isoformat() if campaign.voting_end else None,  # noqa
                        'max_votes_per_user': campaign.max_votes_per_user
                    },
                    'voting_statistics': {
                        'total_candidates': len(candidates),
                        'unique_voters': voting_stats['unique_voters'] or 0,
                        'total_votes': voting_stats['total_votes'] or 0,
                        'nominations_with_votes': voting_stats['nominations_with_votes'] or 0,  # noqa
                        'eligible_voters_count': eligible_voters_count,
                        'participation_rate_percent': round(voting_participation_rate, 2),  # noqa
                        'first_vote_time': voting_stats['first_vote_time'].isoformat() if voting_stats['first_vote_time'] else None,  # noqa
                        'last_vote_time': voting_stats['last_vote_time'].isoformat() if voting_stats['last_vote_time'] else None,  # noqa
                        'average_votes_per_candidate': round(
                            (voting_stats['total_votes'] / len(candidates)) if len(candidates) > 0 and voting_stats['total_votes'] else 0,  # noqa
                            2
                        )
                    },
                    'vote_distribution': [
                        dict(dist) for dist in vote_distribution
                    ],
                    'candidates': candidate_details,
                    'current_leader': candidate_details[0] if candidate_details else None  # noqa
                }

        except Exception as err:
            self.logger.error(
                f"Error getting vote statistics: {err}"
            )
            return {}

    async def _add_pre_candidates(
        self,
        conn,
        campaign_id: int,
        candidates: List[Dict[str, Any]],
        ctx: EvalContext,
        env: Environment
    ):
        """Add pre-defined candidates to the campaign."""
        try:
            Nomination.Meta.connection = conn

            for candidate_data in candidates:
                # Get candidate user information
                candidate_user = await get_user(
                    conn,
                    user_id=candidate_data['user_id']
                )

                # Determine nominator
                # (could be admin, system, or specific user)
                nominator_user_id = candidate_data.get(
                    'nominator_user_id', ctx.user.user_id
                )
                nominator_email = candidate_data.get(
                    'nominator_email', ctx.user.email
                )
                nominator_name = candidate_data.get(
                    'nominator_name', ctx.user.display_name
                )

                # Create nomination record
                nomination_data = {
                    'campaign_id': campaign_id,
                    'nominee_user_id': candidate_user.user_id,
                    'nominee_email': candidate_user.email,
                    'nominee_name': candidate_user.display_name,
                    'nominator_user_id': nominator_user_id,
                    'nominator_email': nominator_email,
                    'nominator_name': nominator_name,
                    'reason': candidate_data.get(
                        'reason', 'Pre-selected candidate'
                    ),
                    'supporting_evidence': candidate_data.get(
                        'supporting_evidence', ''
                    ),
                    'is_pre_candidate': True  # Mark as pre-defined
                }

                nomination = Nomination(**nomination_data)
                await nomination.insert()

                self.logger.info(
                    f"Added pre-candidate {candidate_user.email} to campaign {campaign_id}"  # noqa
                )

            # Update campaign stats
            await self._update_campaign_stats(
                conn, campaign_id
            )

        except Exception as err:
            self.logger.error(f"Error adding pre-candidates: {err}")
            raise

    async def add_single_candidate(
        self,
        ctx: EvalContext,
        env: Environment,
        campaign_id: int,
        candidate_user_id: int,
        reason: str,
        supporting_evidence: str = "",
        nominator_user_id: int = None
    ) -> Optional[Nomination]:
        """Add a single candidate to an existing campaign."""
        try:
            async with await env.connection.acquire() as conn:
                # Validate campaign
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                if campaign.status not in [
                    CampaignStatus.DRAFT,
                    CampaignStatus.NOMINATION_PHASE
                ]:
                    raise ValueError(
                        "Cannot add candidates to this campaign in current phase"  # noqa
                    )

                # Check if candidate already exists
                _query = """
                    SELECT COUNT(*) FROM rewards.nominations
                    WHERE campaign_id = $1 AND nominee_user_id = $2 AND is_active = true
                """  # noqa
                existing_count = await conn.fetchval(
                    _query, campaign_id, candidate_user_id
                )
                if existing_count > 0:
                    raise ValueError(
                        "Candidate already nominated in this campaign"
                    )

                # Get candidate information
                candidate_user = await get_user(
                    pool=conn,
                    user_id=candidate_user_id
                )

                # Use provided nominator or default to current user
                nominator_id = nominator_user_id or ctx.user.user_id

                # Create nomination
                Nomination.Meta.connection = conn
                nomination_data = {
                    'campaign_id': campaign_id,
                    'nominee_user_id': candidate_user.user_id,
                    'nominee_email': candidate_user.email,
                    'nominee_name': candidate_user.display_name,
                    'nominator_user_id': nominator_id,
                    'nominator_email': ctx.user.email,
                    'nominator_name': ctx.user.display_name,
                    'reason': reason,
                    'supporting_evidence': supporting_evidence,
                    'is_pre_candidate': True
                }

                nomination = Nomination(**nomination_data)
                result = await nomination.insert()

                # Update campaign stats
                await self._update_campaign_stats(conn, campaign_id)

                self.logger.info(
                    f"Added candidate {candidate_user.email} to campaign {campaign_id}"  # noqa
                )

                return result

        except Exception as err:
            self.logger.error(f"Error adding single candidate: {err}")
            return None

    async def start_voting_phase_direct(
        self,
        campaign_id: int,
        env: Environment
    ) -> bool:
        """Start voting phase directly (skip nomination phase)."""
        try:
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                if campaign.status != CampaignStatus.DRAFT:
                    raise ValueError("Campaign must be in draft status")

                # Check if we have candidates
                candidate_count_query = """
                    SELECT COUNT(*) FROM rewards.nominations
                    WHERE campaign_id = $1 AND is_active = true
                """
                candidate_count = await conn.fetchval(
                    candidate_count_query, campaign_id
                )

                if candidate_count == 0:
                    raise ValueError("Cannot start voting without candidates")

                # Transition directly to voting
                campaign.status = CampaignStatus.VOTING_PHASE
                campaign.updated_at = env.timestamp
                await campaign.save()

                self.logger.info(
                    f"Started voting phase for campaign {campaign_id} with {candidate_count} candidates"  # noqa
                )
                return True

        except Exception as err:
            self.logger.error(
                f"Error starting voting phase: {err}"
            )
            return False
