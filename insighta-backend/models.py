from pydantic import BaseModel
from typing import Optional


# ── Profile Models ──────────────────────────────────────────────────────────

class ProfileRequest(BaseModel):
    name: str


class ProfileFull(BaseModel):
    id: str
    name: str
    gender: str
    gender_probability: float
    age: int
    age_group: str
    country_id: str
    country_name: str
    country_probability: float
    created_at: str


class ProfileSummary(BaseModel):
    id: str
    name: str
    gender: str
    gender_probability: float
    age: int
    age_group: str
    country_id: str
    country_name: str
    country_probability: float
    created_at: str


# ── Auth Models ──────────────────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    status: str
    access_token: str
    refresh_token: str


class UserOut(BaseModel):
    id: str
    github_id: str
    username: str
    email: Optional[str]
    avatar_url: Optional[str]
    role: str
    is_active: bool
    last_login_at: Optional[str]
    created_at: str
