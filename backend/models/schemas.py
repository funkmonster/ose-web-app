"""
Pydantic models — request/response schemas for the API.
"""

from pydantic import BaseModel, Field
from typing import Optional


class LoginRequest(BaseModel):
    passphrase: str


class LoginResponse(BaseModel):
    name: str
    color: str
    role: str


class CreateCharacterRequest(BaseModel):
    name: str
    char_class: str
    str_score: int = Field(ge=3, le=18)
    dex_score: int = Field(ge=3, le=18)
    con_score: int = Field(ge=3, le=18)
    int_score: int = Field(ge=3, le=18)
    wis_score: int = Field(ge=3, le=18)
    cha_score: int = Field(ge=3, le=18)
    ac: int = 9
    gold: float = 0.0


class PlayActionRequest(BaseModel):
    action: str


class RollRequest(BaseModel):
    notation: str
    reason: str = ""


class GMSayRequest(BaseModel):
    message: str


class UpdateHPRequest(BaseModel):
    target_user: str
    delta: int


class StartCampaignRequest(BaseModel):
    name: str = "The Campaign"
    module: str = "a classic B/X dungeon"


class RestRequest(BaseModel):
    rest_type: str = "long"  # 'short' | 'long'


class UpdateInventoryRequest(BaseModel):
    inventory: list[str]


class UpdateSpellsRequest(BaseModel):
    spells: list[str]
