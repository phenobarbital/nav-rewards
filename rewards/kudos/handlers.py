from datamodel import BaseModel
from navigator.views import ModelView, FormModel
from .models import (
    UserKudos,
    KudosTag,
)

class UserKudosHandler(ModelView):
    model: BaseModel = UserKudos
    pk: str = 'kudos_id'
    name: str = "User Kudos Recognition"

class KudosTagHandler(ModelView):
    model: BaseModel = KudosTag
    pk: str = 'tag_id'
    name: str = "Kudos Tags"

def normalize_tags(tags: list) -> list:
    """Normalize tags to ensure consistency"""
    normalized = []
    for tag in tags:
        if isinstance(tag, str):
            if tag := tag.strip():
                # Ensure hashtag prefix
                if not tag.startswith('#'):
                    tag = f"#{tag}"
                # Convert to lowercase for consistency (optional)
                # tag = tag.lower()
                normalized.append(tag)
    return normalized


def extract_tag_names(tags: list) -> list:
    """Extract tag names without hashtag for database operations"""
    return [tag.lstrip('#').lower() for tag in tags if tag.strip()]


async def update_tag_usage_counts(connection, tags: list):
    """Update usage counts for tags in the database"""
    try:
        tag_names = extract_tag_names(tags)

        if not tag_names:
            return

        # Update existing tags
        update_query = """
        UPDATE rewards.kudos_tags
        SET usage_count = usage_count + 1
        WHERE tag_name = ANY($1)
        """
        await connection.execute(update_query, tag_names)

        # Log the update
        print(f"Updated usage counts for tags: {tag_names}")

    except Exception as e:
        print(f"Error updating tag usage counts: {e}")


async def get_trending_tags(connection, limit: int = 10):
    """Get trending tags from the database"""
    try:
        query = """
        SELECT tag_name, display_name, emoji, recent_usage, total_usage
        FROM rewards.vw_trending_tags
        LIMIT $1
        """
        results = await connection.fetch_all(query, limit)
        return [dict(row) for row in results]
    except Exception as e:
        print(f"Error getting trending tags: {e}")
        return []


async def get_user_kudos_stats(connection, user_id: int):
    """Get kudos statistics for a specific user"""
    try:
        query = """
        SELECT * FROM rewards.vw_user_kudos_stats
        WHERE user_id = $1
        """
        result = await connection.fetch_one(query, user_id)
        return dict(result) if result else None
    except Exception as e:
        print(f"Error getting user kudos stats: {e}")
        return None
