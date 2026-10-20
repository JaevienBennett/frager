from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    email: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LeagueCreate(BaseModel):
    name: str


class LeagueOut(BaseModel):
    id: int
    name: str
    invite_code: str
    owner_id: int
    member_count: int


class JoinRequest(BaseModel):
    invite_code: str


class PredictionCreate(BaseModel):
    question: str


class PredictionOut(BaseModel):
    id: int
    question: str
    status: str
    creator_id: int
    created_at: datetime
    yes_count: int
    no_count: int


class PickCreate(BaseModel):
    side: Literal["yes", "no"]
    stake: int = Field(default=0, ge=0)


class PickOut(BaseModel):
    id: int
    user_id: int
    side: str
    stake: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PredictionDetail(PredictionOut):
    picks: list[PickOut]
