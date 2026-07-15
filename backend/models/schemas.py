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
    """A faithfully-imported character sheet — every value comes from the
    player's own sheet, not from dice rolled by the app."""
    name: str
    char_class: str
    str_score: int = Field(ge=3, le=18)
    dex_score: int = Field(ge=3, le=18)
    con_score: int = Field(ge=3, le=18)
    int_score: int = Field(ge=3, le=18)
    wis_score: int = Field(ge=3, le=18)
    cha_score: int = Field(ge=3, le=18)
    hp_max: int = Field(ge=1)
    ac: int = 9
    gold: float = 0.0
    race: Optional[str] = None
    inventory: list[str] = []
    spells: list[str] = []


class PlayActionRequest(BaseModel):
    action: str


class RollRequest(BaseModel):
    notation: str
    reason: str = ""
    reported_result: Optional[int] = None


class GMSayRequest(BaseModel):
    message: str


class UpdateHPRequest(BaseModel):
    target_user: str
    delta: int


class PhysicalDiceModeRequest(BaseModel):
    enabled: bool


class StartCampaignRequest(BaseModel):
    name: str = "The Campaign"
    module: str = "a classic B/X dungeon"


class RestRequest(BaseModel):
    rest_type: str = "long"  # 'short' | 'long'


class UpdateInventoryRequest(BaseModel):
    inventory: list[str]


class UpdateSpellsRequest(BaseModel):
    spells: list[str]
