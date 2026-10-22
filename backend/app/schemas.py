from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Credentials(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)


class SignupRequest(Credentials):
    nickname: str = Field(min_length=2, max_length=24)

    @field_validator("nickname")
    @classmethod
    def nickname_not_blank(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("nickname must be 2-24 characters")
        return value


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: int
    email: str
    nickname: str
    created_at: datetime

    model_config = {"from_attributes": True}


def normalize_league_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("league name must not be blank")
    if len(value) > 100:
        raise ValueError("league name must be at most 100 characters")
    return value


class LeagueCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_normalized(cls, value: str) -> str:
        return normalize_league_name(value)


class LeagueUpdate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_normalized(cls, value: str) -> str:
        return normalize_league_name(value)


class LeagueOut(BaseModel):
    id: int
    name: str
    invite_code: str
    owner_id: int
    member_count: int


class JoinRequest(BaseModel):
    invite_code: str


class LeagueMemberOut(BaseModel):
    user_id: int
    nickname: str
    is_owner: bool


class TransferOwnership(BaseModel):
    new_owner_id: int = Field(ge=1)


class PredictionCreate(BaseModel):
    question: str
    game_url: str | None = None

    @field_validator("question")
    @classmethod
    def question_normalized(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        if len(value) > 500:
            raise ValueError("question must be at most 500 characters")
        return value


class PredictionOut(BaseModel):
    id: int
    question: str
    status: str
    creator_id: int
    created_at: datetime
    yes_count: int
    no_count: int
    yes_stake: int
    no_stake: int
    resolved_outcome: str | None = None


class PickCreate(BaseModel):
    side: Literal["yes", "no"]
    stake: int = Field(default=0, ge=0, le=1000000)


class PickOut(BaseModel):
    id: int
    user_id: int
    nickname: str
    side: str
    stake: int
    created_at: datetime
    was_correct: bool | None = None


class PredictionDetail(PredictionOut):
    picks: list[PickOut]
    picks_visible: bool


class ResolveRequest(BaseModel):
    outcome: Literal["yes", "no"]


class LeaderboardEntry(BaseModel):
    user_id: int
    nickname: str
    points: int
    correct: int
    total: int
    accuracy: float
