"""User model for Rewards application."""
from typing import Optional, Callable
from datetime import datetime, timedelta, date
from enum import Enum
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, field_validator
from asyncdb.models import Column, Model
from asyncdb.drivers.base import BasePool
from ..conf import (
    REWARDS_USER_TABLE,
    REWARDS_USER_SCHEMA,
    REWARDS_IDENTITY_TABLE,
    REWARDS_IDENTITY_SCHEMA,
)


class UserType(Enum):
    """Enumeration for User Types."""
    USER = 1  # , 'user'
    CUSTOMER = 2  # , 'customer'
    STAFF = 3  # , 'staff'
    MANAGER = 4  # , 'manager'
    ADMIN = 5  # , 'admin'
    ROOT = 10  # , 'superuser'


class UserModel(Model):
    """Database model for retrieving users inside Rewards."""

    user_id: int = Column(
        required=False,
        primary_key=True,
        db_default="auto"
    )
    first_name: str = Column(required=False)
    last_name: str = Column(required=False)
    display_name: str = Column(required=False)
    email: str = Column(required=False, max=254)
    alt_email: str = Column(required=False, max=254)
    password: str = Column(required=False, max=128)
    last_login: datetime = Column(required=False)
    username: str = Column(required=False)
    is_superuser: bool = Column(required=True, default=False)
    is_active: bool = Column(required=True, default=True)
    is_new: bool = Column(required=True, default=True)
    is_staff: bool = Column(required=False, default=True)
    title: str = Column(required=False, max=90)
    avatar: str = Column(required=False, max=512)
    associate_id: str = Column(required=False)
    associate_oid: str = Column(required=False)
    department_code: str = Column(required=False)
    job_code: str = Column(required=False)
    position_id: str = Column(required=False)
    group_id: list = Column(required=False)
    groups: list = Column(required=False)
    program_id: list = Column(required=False)
    programs: list = Column(required=False)
    start_date: datetime = Column(required=False)
    birthday: str = Column(required=False)
    worker_type: str = Column(required=False)
    created_at: datetime = Column(required=False)
    reports_to_associate_oid: str = Column(required=False)
    manager_id: str = Column(required=False)

    class Meta:
        driver = "pg"
        name = REWARDS_USER_TABLE
        schema = REWARDS_USER_SCHEMA
        description = 'View Model for getting Users.'
        strict = True
        frozen = False
        connection = None


class UserIdentityModel(Model):
    """Database model for user identities inside Rewards."""

    identity_id: UUID = Column(
        required=False,
        primary_key=True,
        db_default="auto",
        repr=False
    )
    display_name: str = Column(required=False)
    title: str = Column(required=False)
    nickname: str = Column(required=False)
    email: str = Column(required=False)
    phone: str = Column(required=False)
    short_bio: str = Column(required=False)
    avatar: str = Column(required=False)
    user_id: UserModel = Column(required=False, repr=False)
    auth_provider: str = Column(required=False)
    auth_data: Optional[dict] = Column(required=False, repr=False)
    attributes: Optional[dict] = Column(required=False, repr=False)
    created_at: datetime = Column(
        required=False,
        default=datetime.now(),
        repr=False
    )

    class Meta:
        driver = "pg"
        name = REWARDS_IDENTITY_TABLE
        description = 'Manage User Identities.'
        schema = REWARDS_IDENTITY_SCHEMA
        strict = True
        connection = None


class User(BaseModel):
    """Basic User notation - Pydantic version."""

    user_id: Optional[int] = Field(
        default=None,
        description="Primary key, auto-generated"
    )
    userid: Optional[UUID] = Field(
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
    created_at: Optional[datetime] = Field(default_factory=datetime.now)
    last_login: Optional[datetime] = Field(default_factory=datetime.now)
    groups: Optional[list[str]] = Field(default_factory=list)
    programs: Optional[list[str]] = Field(default_factory=list)
    worker_type: Optional[str] = Field(
        default=None,
        description="Type of worker (e.g., Full-time, Part-time, Contractor)"
    )
    job_code: Optional[str] = Field(
        default=None,
        description="Job code or position identifier"
    )
    department_code: Optional[str] = Field(
        default=None,
        description="Department code or identifier"
    )
    associate_oid: Optional[str] = Field(
        default=None,
        description="Unique OID for the associate"
    )

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

    @field_validator('userid', mode='before')
    @classmethod
    def set_default_userid(cls, v):
        if v is None:
            return uuid4()
        return v

    @field_validator('created_at', 'last_login', mode='before')
    @classmethod
    def set_default_datetime(cls, v):
        if v is None:
            return datetime.now()
        return v

    @field_validator('email', 'alt_email', mode='before')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        """Basic email validation"""
        if v == 'None':
            return None
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
            UserModel.Meta.connection = conn
            user = await UserModel.get(user_id=user_id)
            return User(**user.to_dict()) if user else None

    # Handle InitDriver case:
    UserModel.Meta.connection = pool
    user = await UserModel.get(user_id=user_id)
    return User(**user.to_dict()) if user else None


async def get_user_by_username(pool: Callable, username: str) -> Optional[User]:
    """Fetch user by username."""
    if isinstance(pool, BasePool):
        async with await pool.acquire() as conn:
            UserModel.Meta.connection = conn
            user = await UserModel.get(username=username)
            return User(**user.to_dict()) if user else None

    UserModel.Meta.connection = pool
    user = await UserModel.get(username=username)
    return User(**user.to_dict()) if user else None


async def all_users(pool: Callable) -> list[User]:
    """Fetch all users."""
    users_list = []
    if isinstance(pool, BasePool):
        async with await pool.acquire() as conn:
            UserModel.Meta.connection = conn
            users = await UserModel.all()
            users_list.extend(User(**user.to_dict()) for user in users)
        return users_list

    UserModel.Meta.connection = pool
    users = await UserModel.all()
    users_list.extend(User(**user.to_dict()) for user in users)
    return users_list


async def filter_users(pool: Callable, **filters) -> list[User]:
    """Fetch users by filters."""
    users_list = []
    if not filters:
        filters = {
            "is_active": True
        }

    if isinstance(pool, BasePool):
        async with await pool.acquire() as conn:
            UserModel.Meta.connection = conn
            users = await UserModel.filter(**filters)
            users_list.extend(User(**user.to_dict()) for user in users)
        return users_list

    UserModel.Meta.connection = pool
    users = await UserModel.filter(**filters)
    users_list.extend(User(**user.to_dict()) for user in users)
    return users_list


# Attach methods to User model
User.get_user = get_user
User.get_user_by_username = get_user_by_username
User.all_users = all_users
User.filter_users = filter_users
