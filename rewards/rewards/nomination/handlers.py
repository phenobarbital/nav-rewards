from typing import Any
from aiohttp import web
from datetime import datetime, timedelta
from navigator_session import get_session
from navigator_auth.libs.json import json_encoder
from datamodel.exceptions import ValidationError
from asyncdb.exceptions import DriverError
from navigator.views import BaseHandler
from ...context import EvalContext
from ...env import Environment
from .models import (
    NominationCampaign,
    Nomination,
    NominationVote,
    NominationComment,
    CampaignStatus
)


class NominationAwardHandler(BaseHandler):
    """handler for nomination awards with pre-candidate support."""

    model = NominationCampaign

    async def create_campaign(self, request: web.Request) -> web.Response:
        """Create a new nomination campaign."""
        try:
            session, user = await self._get_user_session(request)
            data = await request.json()

            # Validate required fields
            required_fields = ['campaign_name', 'reward_id']
            for field in required_fields:
                if field not in data:
                    return self.json_response(
                        {'error': f'Missing required field: {field}'},
                        status=400
                    )

            # Get the reward engine to access nomination rewards
            reward_engine = request.app['reward_engine']
            nomination_reward = await reward_engine.get_reward(
                data['reward_id']
            )

            if not nomination_reward or nomination_reward.type != 'nomination':
                return self.json_response(
                    {'error': 'Invalid nomination reward'},
                    status=400
                )

            # Create environment context
            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            # Create evaluation context
            ctx = EvalContext(
                request=request,
                user=user,
                session=session
            )

            # Create the campaign
            campaign = await nomination_reward.create_campaign(
                ctx=ctx,
                env=env,
                campaign_name=data['campaign_name'],
                description=data.get('description', ''),
                start_date=datetime.fromisoformat(
                    data['start_date']
                ) if 'start_date' in data else None
            )

            return self.json_response(campaign.to_dict(), status=201)

        except ValidationError as err:
            return self.json_response(
                {'error': 'Validation error', 'details': err.payload},
                status=400
            )
        except Exception as err:
            return self.json_response(
                {'error': str(err)},
                status=500
            )

    async def start_nomination_phase(
        self,
        request: web.Request
    ) -> web.Response:
        """Start the nomination phase for a campaign."""
        try:
            campaign_id = int(request.match_info['campaign_id'])
            reward_engine = request.app['reward_engine']

            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            # Get campaign and associated nomination reward
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                nomination_reward = await reward_engine.get_reward(
                    campaign.reward_id
                )
                if not nomination_reward:
                    return self.json_response(
                        {'error': 'Associated reward not found'},
                        status=404
                    )

                success = await nomination_reward.start_nomination_phase(
                    campaign_id,
                    env
                )

                if success:
                    return self.json_response(
                        {'message': 'Nomination phase started'}
                    )
                else:
                    return self.json_response(
                        {'error': 'Failed to start nomination phase'},
                        status=400
                    )

        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def start_voting_phase(
        self,
        request: web.Request
    ) -> web.Response:
        """Start the voting phase for a campaign."""
        try:
            campaign_id = int(request.match_info['campaign_id'])
            reward_engine = request.app['reward_engine']

            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            # Get campaign and associated nomination reward
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                nomination_reward = await reward_engine.get_reward(
                    campaign.reward_id
                )
                success = await nomination_reward.start_voting_phase(
                    campaign_id,
                    env
                )

                if success:
                    return self.json_response(
                        {'message': 'Voting phase started'}
                    )
                else:
                    return self.json_response(
                        {'error': 'Failed to start voting phase'},
                        status=400
                    )

        except Exception as err:
            return self.json_response(
                {'error': str(err)},
                status=500
            )

    async def close_campaign(self, request: web.Request) -> web.Response:
        """Close campaign and select winner."""
        try:
            campaign_id = int(request.match_info['campaign_id'])
            reward_engine = request.app['reward_engine']

            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            # Get campaign and associated nomination reward
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                _nomination = await reward_engine.get_reward(
                    campaign.reward_id
                )
                winner = await _nomination.close_campaign_and_select_winner(
                    campaign_id, env
                )

                if winner:
                    return self.json_response({
                        'message': 'Campaign closed successfully',
                        'winner': winner.to_dict()
                    })
                else:
                    return self.json_response({
                        'message': 'Campaign closed with no winner'
                    })

        except Exception as err:
            return self.json_response(
                {'error': str(err)},
                status=500
            )

    async def get_campaign_status(self, request: web.Request) -> web.Response:
        """Get detailed campaign status including nominations and votes."""
        try:
            campaign_id = int(request.match_info['campaign_id'])
            reward_engine = request.app['reward_engine']

            async with await reward_engine.connection.acquire() as conn:
                # Get campaign
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                # Get nominations with vote counts
                nominations_query = """
                    SELECT n.*,
                    u1.display_name as nominee_display_name,
                    u2.display_name as nominator_display_name
                    FROM rewards.nominations n
                    LEFT JOIN auth.users u1 ON n.nominee_user_id = u1.user_id
                    LEFT JOIN auth.users u2 ON n.nominator_user_id = u2.user_id
                    WHERE n.campaign_id = $1 AND n.is_active = true
                    ORDER BY n.vote_count DESC, n.nominated_at ASC
                """
                nominations = await conn.fetch_all(
                    nominations_query,
                    campaign_id
                )

                # Get vote statistics
                vote_stats_query = """
                    SELECT
                        COUNT(DISTINCT voter_user_id) as unique_voters,
                        COUNT(*) as total_votes
                    FROM rewards.nomination_votes
                    WHERE campaign_id = $1
                """
                vote_stats = await conn.fetch_one(
                    vote_stats_query,
                    campaign_id
                )

                response_data = {
                    'campaign': campaign.to_dict(),
                    'nominations': [dict(nom) for nom in nominations],
                    'vote_statistics': dict(vote_stats) if vote_stats else {},
                    'phase_info': self._get_phase_info(campaign)
                }

                return self.json_response(response_data)

        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    def _get_phase_info(self, campaign: NominationCampaign) -> dict:
        """Get information about current phase and timing."""
        now = datetime.now()

        if campaign.status == CampaignStatus.DRAFT:
            return {
                'current_phase': 'draft',
                'can_start': now >= campaign.nomination_start,
                'time_until_start': (
                    campaign.nomination_start - now).total_seconds() if now < campaign.nomination_start else 0  # noqa
            }
        elif campaign.status == CampaignStatus.NOMINATION_PHASE:
            return {
                'current_phase': 'nomination',
                'time_remaining': (campaign.nomination_end - now).total_seconds() if now < campaign.nomination_end else 0,  # noqa
                'can_transition_to_voting': now >= campaign.nomination_end
            }
        elif campaign.status == CampaignStatus.VOTING_PHASE:
            return {
                'current_phase': 'voting',
                'time_remaining': (campaign.voting_end - now).total_seconds() if now < campaign.voting_end else 0,  # noqa
                'can_close': now >= campaign.voting_end
            }
        else:
            return {
                'current_phase': campaign.status.value,
                'is_closed': True
            }

    async def create_campaign_with_candidates(
        self,
        request: web.Request
    ) -> web.Response:
        """Create a campaign with pre-defined candidates."""
        try:
            session, user = await self._get_user_session(request)
            data = await request.json()

            # Validate required fields
            required_fields = ['campaign_name', 'reward_id']
            for field in required_fields:
                if field not in data:
                    return self.json_response(
                        {'error': f'Missing required field: {field}'},
                        status=400
                    )

            # Get the reward engine
            reward_engine = request.app['reward_engine']
            nomination_award = await reward_engine.get_reward(
                data['reward_id']
            )

            if not nomination_award or nomination_award.type != 'nomination':
                return self.json_response(
                    {'error': 'Invalid nomination award'},
                    status=400
                )

            # Create environment context
            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            # Create evaluation context
            ctx = EvalContext(
                request=request,
                user=user,
                session=session
            )

            # Parse candidates list
            candidates = data.get('candidates', [])
            start_date = None
            if 'start_date' in data:
                start_date = datetime.fromisoformat(data['start_date'])

            # Create the campaign with candidates
            campaign = await nomination_award.create_campaign_with_candidates(
                ctx=ctx,
                env=env,
                campaign_name=data['campaign_name'],
                description=data.get('description', ''),
                candidates=candidates,
                start_date=start_date
            )

            return self.json_response(
                campaign.to_dict(),
                status=201
            )

        except ValidationError as err:
            return self.json_response(
                {'error': 'Validation error', 'details': err.payload},
                status=400
            )
        except Exception as err:
            return self.json_response(
                {'error': str(err)},
                status=500
            )

    async def add_candidate_to_campaign(
        self,
        request: web.Request
    ) -> web.Response:
        """Add a single candidate to an existing campaign."""
        try:
            session, user = await self._get_user_session(request)
            campaign_id = int(request.match_info['campaign_id'])
            data = await request.json()

            # Validate required fields
            required_fields = ['candidate_user_id', 'reason']
            for field in required_fields:
                if field not in data:
                    return self.json_response(
                        {'error': f'Missing required field: {field}'},
                        status=400
                    )

            reward_engine = request.app['reward_engine']
            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            ctx = EvalContext(
                request=request,
                user=user,
                session=session
            )

            # Get campaign and associated nomination award
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                nomination_award = await reward_engine.get_reward(
                    campaign.reward_id
                )

                nomination = await nomination_award.add_single_candidate(
                    ctx=ctx,
                    env=env,
                    campaign_id=campaign_id,
                    candidate_user_id=data['candidate_user_id'],
                    reason=data['reason'],
                    supporting_evidence=data.get('supporting_evidence', ''),
                    nominator_user_id=data.get('nominator_user_id')
                )

                if nomination:
                    return self.json_response(nomination.to_dict(), status=201)
                else:
                    return self.json_response(
                        {'error': 'Failed to add candidate'},
                        status=400
                    )

        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def start_voting_direct(self, request: web.Request) -> web.Response:
        """Start voting phase directly (skip nomination phase)."""
        try:
            campaign_id = int(request.match_info['campaign_id'])
            reward_engine = request.app['reward_engine']

            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            # Get campaign and associated nomination award
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                nomination_award = await reward_engine.get_reward(
                    campaign.reward_id
                )
                success = await nomination_award.start_voting_phase_direct(
                    campaign_id,
                    env
                )

                if success:
                    return self.json_response(
                        {'message': 'Voting phase started'}
                    )
                else:
                    return self.json_response(
                        {'error': 'Failed to start voting phase'},
                        status=400
                    )

        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def get_vote_statistics(
        self,
        request: web.Request
    ) -> web.Response:
        """Get detailed vote statistics for a campaign."""
        try:
            campaign_id = int(request.match_info['campaign_id'])

            # Parse query parameters
            include_voter_details = request.query.get(
                'include_voters', 'false'
            ).lower() == 'true'

            reward_engine = request.app['reward_engine']
            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            # Get campaign and associated nomination award
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                _nomination = await reward_engine.get_reward(
                    campaign.reward_id
                )

                statistics = await _nomination.get_campaign_vote_statistics(
                    campaign_id=campaign_id,
                    env=env,
                    include_voter_details=include_voter_details
                )

                return self.json_response(statistics)

        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def get_real_time_vote_counts(
        self,
        request: web.Request
    ) -> web.Response:
        """Get real-time vote counts for quick updates."""
        try:
            campaign_id = int(request.match_info['campaign_id'])

            reward_engine = request.app['reward_engine']
            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            # Get campaign and associated nomination award
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                nomination_award = await reward_engine.get_reward(
                    campaign.reward_id
                )

                vote_counts = await nomination_award.get_real_time_vote_counts(
                    campaign_id=campaign_id,
                    env=env
                )

                # Add metadata
                response_data = {
                    'campaign_id': campaign_id,
                    'last_updated': env.timestamp.isoformat(),
                    'vote_counts': vote_counts,
                    'total_candidates': len(vote_counts)
                }

                return self.json_response(response_data)

        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def get_candidate_leaderboard(
        self,
        request: web.Request
    ) -> web.Response:
        """Get simplified leaderboard for display purposes."""
        try:
            campaign_id = int(request.match_info['campaign_id'])

            # Parse query parameters
            limit = int(request.query.get('limit', 10))
            include_details = request.query.get(
                'include_details', 'false'
            ).lower() == 'true'

            reward_engine = request.app['reward_engine']

            async with await reward_engine.connection.acquire() as conn:
                if include_details:
                    query = """
                        SELECT
                            n.nomination_id,
                            n.nominee_user_id,
                            n.nominee_name,
                            n.reason,
                            n.vote_count,
                            n.nominated_at,
                            u.display_name,
                            u.department,
                            u.job_code,
                            RANK() OVER (
                                ORDER BY n.vote_count DESC,
                                n.nominated_at ASC
                            ) as rank
                        FROM rewards.nominations n
                        LEFT JOIN auth.vw_users u ON n.nominee_user_id = u.user_id
                        WHERE n.campaign_id = $1 AND n.is_active = true
                        ORDER BY n.vote_count DESC, n.nominated_at ASC
                        LIMIT $2
                    """  # noqa
                else:
                    query = """
                        SELECT
                            n.nomination_id,
                            n.nominee_user_id,
                            n.nominee_name,
                            n.vote_count,
                            RANK() OVER (
                                ORDER BY n.vote_count DESC,
                                n.nominated_at ASC
                            ) as rank
                        FROM rewards.nominations n
                        WHERE n.campaign_id = $1 AND n.is_active = true
                        ORDER BY n.vote_count DESC, n.nominated_at ASC
                        LIMIT $2
                    """

                results = await conn.fetch_all(query, campaign_id, limit)

                leaderboard = []
                for result in results:
                    entry = {
                        'rank': result['rank'],
                        'nomination_id': result['nomination_id'],
                        'nominee_user_id': result['nominee_user_id'],
                        'nominee_name': result['nominee_name'],
                        'vote_count': result['vote_count']
                    }

                    if include_details:
                        entry |= {
                            'reason': result['reason'],
                            'display_name': result['display_name'],
                            'department': result['department'],
                            'job_code': result['job_code'],
                            'nominated_at': result['nominated_at'].isoformat() if result['nominated_at'] else None  # noqa
                        }

                    leaderboard.append(entry)

                return self.json_response({
                    'campaign_id': campaign_id,
                    'leaderboard': leaderboard,
                    'total_shown': len(leaderboard)
                })

        except Exception as err:
            return self.json_response(
                {'error': str(err)},
                status=500
            )

    async def get_user_voting_status(
        self,
        request: web.Request
    ) -> web.Response:
        """Get current user's voting status for a campaign."""
        try:
            session, user = await self._get_user_session(request)
            campaign_id = int(request.match_info['campaign_id'])

            reward_engine = request.app['reward_engine']

            async with await reward_engine.connection.acquire() as conn:
                # Get campaign info
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )

                # Get user's votes in this campaign
                user_votes_query = """
                    SELECT
                        nv.nomination_id,
                        nv.voted_at,
                        nv.vote_comment,
                        n.nominee_name
                    FROM rewards.nomination_votes nv
                    JOIN rewards.nominations n ON nv.nomination_id = n.nomination_id
                    WHERE nv.campaign_id = $1 AND nv.voter_user_id = $2
                    ORDER BY nv.voted_at DESC
                """  # noqa
                user_votes = await conn.fetch_all(
                    user_votes_query,
                    campaign_id,
                    user.user_id
                )

                # Calculate remaining votes
                votes_used = len(user_votes)
                votes_remaining = max(
                    0, campaign.max_votes_per_user - votes_used
                )

                # Check if user can still vote
                can_vote = (
                    campaign.status == CampaignStatus.VOTING_PHASE and
                    votes_remaining > 0 and
                    datetime.now() < campaign.voting_end
                )

                response_data = {
                    'campaign_id': campaign_id,
                    'user_id': user.user_id,
                    'voting_status': {
                        'can_vote': can_vote,
                        'votes_used': votes_used,
                        'votes_remaining': votes_remaining,
                        'max_votes_allowed': campaign.max_votes_per_user
                    },
                    'user_votes': [
                        {
                            'nomination_id': vote['nomination_id'],
                            'nominee_name': vote['nominee_name'],
                            'voted_at': vote['voted_at'].isoformat() if vote['voted_at'] else None,  # noqa
                            'comment': vote['vote_comment']
                        }
                        for vote in user_votes
                    ],
                    'campaign_phase': campaign.status.value,
                    'voting_end_time': campaign.voting_end.isoformat() if campaign.voting_end else None  # noqa
                }

                return self.json_response(response_data)

        except Exception as err:
            return self.json_response(
                {'error': str(err)},
                status=500
            )

    async def get_campaign_summary(self, request: web.Request) -> web.Response:
        """Get a comprehensive campaign summary including all key metrics."""
        try:
            campaign_id = int(request.match_info['campaign_id'])

            reward_engine = request.app['reward_engine']
            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            async with await env.connection.acquire() as conn:
                # Get campaign
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=campaign_id
                )
                _award = await reward_engine.get_reward(
                    campaign.reward_id
                )

                # Get comprehensive statistics
                statistics = await _award.get_campaign_vote_statistics(
                    campaign_id=campaign_id,
                    env=env,
                    include_voter_details=False
                )

                # Get real-time vote counts
                vote_counts = await _award.get_real_time_vote_counts(
                    campaign_id=campaign_id,
                    env=env
                )

                # Calculate time remaining
                now = datetime.now()
                time_remaining = None
                if campaign.status == CampaignStatus.VOTING_PHASE and campaign.voting_end:  # noqa
                    time_remaining = max(
                        0,
                        (campaign.voting_end - now).total_seconds()
                    )
                in_voting = campaign.status == CampaignStatus.VOTING_PHASE
                is_closed = campaign.status == CampaignStatus.CLOSED
                winner_email = campaign.winner_email if campaign.winner_user_id else None  # noqa
                summary = {
                    'campaign': statistics['campaign_info'],
                    'overall_statistics': statistics['voting_statistics'],
                    'vote_distribution': statistics['vote_distribution'],
                    'current_standings': vote_counts[:5],  # Top 5
                    'phase_info': {
                        'current_phase': campaign.status.value,
                        'time_remaining_seconds': time_remaining,
                        'is_active': in_voting,
                        'is_closed': is_closed
                    },
                    'winner_info': {
                        'has_winner': bool(campaign.winner_user_id),
                        'winner_email': winner_email
                    }
                }

                return self.json_response(summary)

        except Exception as err:
            return self.json_response(
                {'error': str(err)},
                status=500
            )

    async def _get_user_session(self, request: web.Request):
        """Get user session information."""
        session = await get_session(request, new=False)
        user = session.decode('user')
        return session, user


class NominationHandler(BaseHandler):
    """Handler for nominations."""

    model = Nomination

    async def submit_nomination(self, request: web.Request) -> web.Response:
        """Submit a nomination."""
        try:
            session, user = await self._get_user_session(request)
            data = await request.json()

            # Validate required fields
            required_fields = ['campaign_id', 'nominee_user_id', 'reason']
            for field in required_fields:
                if field not in data:
                    return self.json_response(
                        {'error': f'Missing required field: {field}'},
                        status=400
                    )

            reward_engine = request.app['reward_engine']
            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            ctx = EvalContext(
                request=request,
                user=user,
                session=session
            )

            # Get campaign and associated nomination reward
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=data['campaign_id']
                )

                nomination_reward = await reward_engine.get_reward(
                    campaign.reward_id
                )

                nomination = await nomination_reward.submit_nomination(
                    ctx=ctx,
                    env=env,
                    campaign_id=data['campaign_id'],
                    nominee_user_id=data['nominee_user_id'],
                    reason=data['reason'],
                    supporting_evidence=data.get('supporting_evidence', '')
                )

                if nomination:
                    return self.json_response(nomination.to_dict(), status=201)
                else:
                    return self.json_response(
                        {'error': 'Failed to submit nomination'},
                        status=400
                    )

        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def get_campaign_nominations(
        self,
        request: web.Request
    ) -> web.Response:
        """Get all nominations for a campaign."""
        try:
            campaign_id = int(request.match_info['campaign_id'])
            reward_engine = request.app['reward_engine']

            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT n.*,
                    u1.display_name as nominee_display_name,
                    u2.display_name as nominator_display_name
                    FROM rewards.nominations n
                    LEFT JOIN auth.users u1 ON n.nominee_user_id = u1.user_id
                    LEFT JOIN auth.users u2 ON n.nominator_user_id = u2.user_id
                    WHERE n.campaign_id = $1 AND n.is_active = true
                    ORDER BY n.vote_count DESC, n.nominated_at ASC
                """
                nominations = await conn.fetch_all(query, campaign_id)

                return self.json_response(
                    [dict(nom) for nom in nominations]
                )

        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def _get_user_session(self, request: web.Request):
        """Get user session information."""
        session = await get_session(request, new=False)
        user = session.decode('user')
        return session, user


class NominationVoteHandler(BaseHandler):
    """Handler for nomination votes."""

    model = NominationVote

    async def submit_vote(
        self,
        request: web.Request
    ) -> web.Response:
        """Submit a vote for a nomination."""
        try:
            session, user = await self._get_user_session(request)
            data = await request.json()

            # Validate required fields
            required_fields = ['campaign_id', 'nomination_id']
            for field in required_fields:
                if field not in data:
                    return self.json_response(
                        {'error': f'Missing required field: {field}'},
                        status=400
                    )

            reward_engine = request.app['reward_engine']
            env = Environment(
                connection=reward_engine.connection,
                cache=reward_engine.get_cache()
            )

            ctx = EvalContext(
                request=request,
                user=user,
                session=session
            )

            # Get campaign and associated nomination reward
            async with await env.connection.acquire() as conn:
                NominationCampaign.Meta.connection = conn
                campaign = await NominationCampaign.get(
                    campaign_id=data['campaign_id']
                )

                nomination_reward = await reward_engine.get_reward(
                    campaign.reward_id
                )

                vote = await nomination_reward.submit_vote(
                    ctx=ctx,
                    env=env,
                    campaign_id=data['campaign_id'],
                    nomination_id=data['nomination_id'],
                    vote_comment=data.get('vote_comment', '')
                )

                if vote:
                    return self.json_response(
                        vote.to_dict(),
                        status=201
                    )
                else:
                    return self.json_response(
                        {'error': 'Failed to submit vote'},
                        status=400
                    )

        except Exception as err:
            return self.json_response(
                {'error': str(err)},
                status=500
            )

    async def get_nomination_votes(self, request: web.Request) -> web.Response:
        """Get all votes for a nomination."""
        try:
            nomination_id = int(request.match_info['nomination_id'])
            reward_engine = request.app['reward_engine']

            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT nv.*, u.display_name as voter_display_name
                    FROM rewards.nomination_votes nv
                    LEFT JOIN auth.users u ON nv.voter_user_id = u.user_id
                    WHERE nv.nomination_id = $1
                    ORDER BY nv.voted_at DESC
                """
                votes = await conn.fetch_all(query, nomination_id)

                return self.json_response([dict(vote) for vote in votes])

        except Exception as err:
            return self.json_response({'error': str(err)}, status=500)

    async def _get_user_session(self, request: web.Request):
        """Get user session information."""
        session = await get_session(request, new=False)
        user = session.decode('user')
        return session, user


class NominationCommentHandler(BaseHandler):
    """Handler for nomination comments."""

    model = NominationComment

    async def add_comment(
        self,
        request: web.Request
    ) -> web.Response:
        """Add a comment to a nomination."""
        try:
            _, user = await self._get_user_session(request)
            data = await request.json()

            if 'comment' not in data:
                return self.json_response(
                    {'error': 'Missing required field: comment'},
                    status=400
                )

            nomination_id = int(request.match_info['nomination_id'])
            reward_engine = request.app['reward_engine']

            async with await reward_engine.connection.acquire() as conn:
                NominationComment.Meta.connection = conn

                comment_data = {
                    'nomination_id': nomination_id,
                    'user_id': user.user_id,
                    'user_email': user.email,
                    'comment': data['comment']
                }

                comment = NominationComment(**comment_data)
                result = await comment.insert()

                return self.json_response(
                    result.to_dict(),
                    status=201
                )

        except Exception as err:
            return self.json_response(
                {'error': str(err)},
                status=500
            )

    async def get_nomination_comments(
        self,
        request: web.Request
    ) -> web.Response:
        """Get all comments for a nomination."""
        try:
            nomination_id = int(
                request.match_info['nomination_id']
            )
            reward_engine = request.app['reward_engine']

            async with await reward_engine.connection.acquire() as conn:
                query = """
                    SELECT nc.*, u.display_name as user_display_name
                    FROM rewards.nomination_comments nc
                    LEFT JOIN auth.users u ON nc.user_id = u.user_id
                    WHERE nc.nomination_id = $1 AND nc.is_enabled = true
                    ORDER BY nc.commented_at ASC
                """
                comments = await conn.fetch_all(
                    query,
                    nomination_id
                )

                return self.json_response(
                    [dict(comment) for comment in comments]
                )

        except Exception as err:
            return self.json_response(
                {'error': str(err)},
                status=500
            )

    async def _get_user_session(self, request: web.Request):
        """Get user session information."""
        session = await get_session(request, new=False)
        user = session.decode('user')
        return session, user
