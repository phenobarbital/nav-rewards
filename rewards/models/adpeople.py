"""Active Directory People Model for Rewards Application."""
from typing import Optional
from uuid import UUID
from datetime import datetime
from datamodel import BaseModel, Field
from asyncdb.models import Model
from ..conf import (
    PEOPLE_LIST,
    PEOPLE_SCHEMA,
    EMPLOYEES_TABLE_NAME
)


class ADPeople(Model):
    """Active Directory Users."""
    people_id: UUID = Field(
        required=False,
        primary_key=True,
        db_default="auto",
        repr=False
    )
    user_id: int = Field(required=True)
    userid: UUID = Field(required=False)
    username: str = Field(required=False)
    display_name: str = Field(required=False)
    given_name: str = Field(required=False)
    last_name: str = Field(required=False)
    phones: Optional[list] = Field(required=False)
    mobile: str = Field(required=False)
    job_title: str = Field(required=False)
    email: str = Field(required=False)
    alt_email: str = Field(required=False)
    office_location: str = Field(required=False)
    preferred_language: str = Field(required=False)
    associate_id: str = Field(required=False)
    associate_oid: str = Field(required=False)
    job_code_title: str = Field(required=False)
    position_id: str = Field(required=False)
    reports_to: Optional[int] = Field(required=False)
    created_at: datetime = Field(
        required=False,
        default=datetime.now(),
        repr=False
    )

    class Meta:
        name = PEOPLE_LIST
        schema = PEOPLE_SCHEMA
        strict = True


class Employee(BaseModel):
    """Employee Information from AD People View."""
    associate_id: str = Field(required=True)
    position_id: str = Field(required=True)
    file_number: str = Field(required=True)
    operator_name: str = Field(required=True)
    first_name: str = Field(required=False)
    last_name: str = Field(required=False)
    display_name: str = Field(required=False)
    corporate_email: str = Field(required=True)
    job_code: str = Field(required=False)
    job_code_title: str = Field(required=False)
    region_code: str = Field(required=False)
    department: str = Field(required=False)
    department_code: str = Field(required=False)
    location_code: str = Field(required=False)
    work_location: str = Field(required=False)
    reports_to_associate_oid: str = Field(required=False)
    reports_to_associate_id: str = Field(required=False)
    reports_to_position_id: str = Field(required=False)

    def email(self):
        """Return corporate email."""
        return self.corporate_email

    class Meta:
        name = EMPLOYEES_TABLE_NAME
        schema = PEOPLE_SCHEMA
        strict = True
