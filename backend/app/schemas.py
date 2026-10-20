from datetime import datetime

from pydantic import BaseModel


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
