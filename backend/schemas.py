from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    request_id: str
    data: T


class ErrorDetail(BaseModel):
    code: str
    message: str
    stage: str


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorDetail


class HealthData(BaseModel):
    status: str = Field(examples=["ok"])


class UploadData(BaseModel):
    audio_id: str = Field(examples=["aud_7f3a9c12e4b8"])


class AsrRequest(BaseModel):
    audio_id: str = Field(examples=["aud_7f3a9c12e4b8"])


class AsrData(BaseModel):
    text: str


class ExtractRequest(BaseModel):
    text: str = Field(min_length=1, examples=["我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店"])
    city: str = Field(default="杭州", min_length=1, examples=["杭州"])


class ExtractModelOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    city_a: str | None
    address_a: str | None
    city_b: str | None
    address_b: str | None
    category: str | None
    party_count: int | None
    incomplete_reason: str | None


class ExtractData(BaseModel):
    city_a: str
    address_a: str
    city_b: str
    address_b: str
    category: str


class SearchRequest(BaseModel):
    city_a: str = Field(min_length=1, examples=["杭州"])
    address_a: str = Field(min_length=1, examples=["杭州东站"])
    city_b: str = Field(min_length=1, examples=["杭州"])
    address_b: str = Field(min_length=1, examples=["西湖龙翔桥地铁站"])
    category: str = Field(min_length=1, examples=["咖啡店"])


class Midpoint(BaseModel):
    longitude: float
    latitude: float


class PoiItem(BaseModel):
    name: str
    address: str
    distance_to_midpoint_m: float


class SearchData(BaseModel):
    search_id: str
    midpoint: Midpoint
    pois: list[PoiItem]


class FinalizeRequest(BaseModel):
    search_id: str = Field(examples=["srch_9d2b4e7c1a5f"])


class FinalizeData(BaseModel):
    reply_text: str
    audio_url: str | None
    warning: str | None
