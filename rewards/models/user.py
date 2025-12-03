"""User model for Rewards application."""
from typing import Optional, Callable
from datetime import datetime, timedelta, date
from enum import Enum
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, field_validator
from navigator_auth.models import User as AuthUser
from asyncdb.drivers.base import BasePool, InitDriver


class UserType(Enum):
    """Enumeration for User Types."""
    USER = 1  # , 'user'
    CUSTOMER = 2  # , 'customer'
    STAFF = 3  # , 'staff'
    MANAGER = 4  # , 'manager'
    ADMIN = 5  # , 'admin'
    ROOT = 10  # , 'superuser'


class User(BaseModel):
    """Basic User notation - Pydantic version."""

    user_id: Optional[int] = Field(
        default=None,
        description="Primary key, auto-generated"
    )
    userid: UUID = Field(
        default_factory=uuid4,
        description="Unique user identifier"
    )
    first_name: Optional[str] = Field(
        default=None,
        max_length=254,
        description="First Name"
    )
    last_name: Optional[str] = Field(
        default=None,
        max_length=254,
        description="Last Name"
    )
    display_name: Optional[str] = None
    email: Optional[str] = Field(
        default=None,
        max_length=254,
        description="User's Email"
    )
    alt_email: Optional[str] = Field(
        default=None,
        max_length=254,
        description="Alternate Email"
    )
    username: str = Field(..., description="Username (required)")
    user_role: Optional[UserType] = None
    is_superuser: bool = False
    is_staff: bool = True
    title: Optional[str] = Field(default=None, max_length=120)
    avatar: Optional[str] = None
    is_active: bool = True
    is_new: bool = True
    timezone: str = Field(default="UTC", max_length=75)
    attributes: Optional[dict] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    last_login: datetime = Field(default_factory=datetime.now)

    # Additional fields for the methods
    birthday: Optional[str] = Field(
        default=None,
        description="Birthday in format YYYY-MM-DD"
    )
    start_date: Optional[date] = Field(
        default=None,
        description="Employment start date"
    )

    model_config = {
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "use_enum_values": True,
    }

    @field_validator('email', 'alt_email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        """Basic email validation"""
        if v and '@' not in v:
            raise ValueError('must be a valid email address')
        return v

    def birth_date(self) -> Optional[date]:
        """Calculate birth date for the current year."""
        if self.birthday:
            _, month, day = self.birthday.split('-')  # pylint: disable=E1101
            # Get the current year
            current_year = datetime.now().year
            # Create a new date string with the current year
            new_date_str = f"{current_year}-{month}-{day}"
            # Convert the new date string to a datetime object
            return datetime.strptime(new_date_str, "%Y-%m-%d").date()
        return None

    def employment_duration(self) -> tuple[Optional[int], Optional[int], Optional[int]]:
        """Calculate years, months, and days since employment start."""
        if not self.start_date:
            return None, None, None

        # Get today's date
        today = datetime.now()
        # employment:
        employment = self.start_date

        # Calculate the difference in years, months, days
        years = today.year - employment.year  # pylint: disable=E1101
        months = today.month - employment.month  # pylint: disable=E1101
        days = today.day - employment.day  # pylint: disable=E1101

        # Adjust for cases where the current month is before the start month
        if months < 0:
            years -= 1
            months += 12

        # Adjust for cases where the current day
        # is before the start day in the month
        if days < 0:
            # Subtract one month and calculate days based on the previous month
            months -= 1
            if months < 0:
                years -= 1
                months += 12
            # Calculate the last day of the previous month
            last_day_of_prev_month = (
                today.replace(day=1) - timedelta(days=1)
            ).day
            days += last_day_of_prev_month

        # Adjust months and years again if necessary
        if months < 0:
            years -= 1
            months += 12

        return years, months, days


async def get_user(pool: Callable, user_id: int) -> Optional[User]:
    """Fetch user by user_id."""
    if isinstance(pool, BasePool):
        async with await pool.acquire() as conn:
            AuthUser.Meta.connection = conn
            user = await AuthUser.get(user_id=user_id)
            if user:
                return User(
                    **user.to_dict()
                )
    # Handle InitDriver case:
    AuthUser.Meta.connection = pool
    user = await AuthUser.get(user_id=user_id)
    return User(**user.to_dict()) if user else None

async def get_user_by_username(pool: Callable, username: str) -> Optional[User]:
    """Fetch user by username."""
    async with await pool.acquire() as conn:
        AuthUser.Meta.connection = conn
        user = await AuthUser.get(username=username)
        if user:
            return User(
                **user.to_dict()
            )
    return None

async def all_users(pool: Callable) -> list[User]:
    """Fetch all users."""
    users_list = []
    async with await pool.acquire() as conn:
        AuthUser.Meta.connection = conn
        users = await AuthUser.all()
        users_list.extend(User(**user.to_dict()) for user in users)
    return users_list

async def filter_users(pool: Callable, **filters) -> list[User]:
    """Fetch users by filters."""
    users_list = []
    if not filters:
        filters = {
            "is_active": True
        }
    async with await pool.acquire() as conn:
        AuthUser.Meta.connection = conn
        users = await AuthUser.filter(**filters)
        users_list.extend(User(**user.to_dict()) for user in users)
    return users_list

# Attach methods to User model
User.get_user = get_user
User.get_user_by_username = get_user_by_username
User.all_users = all_users
User.filter_users = filter_users
