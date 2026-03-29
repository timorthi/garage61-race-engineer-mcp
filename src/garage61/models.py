"""Pydantic v2 models for Garage61 API inputs and outputs."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Track(BaseModel):
    track_id: int
    name: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Track:
        return cls(
            track_id=int(data["id"]),
            name=str(data["name"]),
        )


class Car(BaseModel):
    car_id: int
    name: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Car:
        return cls(
            car_id=int(data["id"]),
            name=str(data["name"]),
        )


class LapSummary(BaseModel):
    """Lap metadata returned by the /laps search endpoint."""

    lap_id: str
    lap_time_ms: int
    driver_name: str
    driver_irating: Optional[int] = None
    session_type: int
    air_temp_c: Optional[float] = None
    track_temp_c: Optional[float] = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> LapSummary:
        """Construct from a /laps response item.

        NOTE: Field names (e.g. "lapTime", "iRating", "airTemp") are ASSUMED
        based on camelCase REST conventions. Verify against a real API response.
        """
        conditions: dict[str, Any] = data.get("conditions") or {}
        driver: dict[str, Any] = data.get("driver") or {}
        return cls(
            lap_id=str(data["id"]),
            lap_time_ms=int(data["lapTime"]),
            driver_name=str(driver.get("name", "")),
            driver_irating=driver.get("iRating"),
            session_type=int(data.get("sessionType", 0)),
            air_temp_c=conditions.get("airTemp"),
            track_temp_c=conditions.get("trackTemp"),
        )


class LapDetail(BaseModel):
    """Full single-lap metadata returned by GET /laps/{id}."""

    lap_id: str
    lap_time_ms: int
    driver_name: str
    driver_irating: Optional[int] = None
    session_type: int
    track_id: int
    car_id: int
    air_temp_c: Optional[float] = None
    track_temp_c: Optional[float] = None
    has_telemetry: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> LapDetail:
        """Construct from a /laps/{id} response.

        NOTE: Field names (e.g. "lapTime", "trackId", "carId", "hasTelemetry")
        are ASSUMED based on camelCase REST conventions. Verify against a real
        API response.
        """
        conditions: dict[str, Any] = data.get("conditions") or {}
        driver: dict[str, Any] = data.get("driver") or {}
        return cls(
            lap_id=str(data["id"]),
            lap_time_ms=int(data["lapTime"]),
            driver_name=str(driver.get("name", "")),
            driver_irating=driver.get("iRating"),
            session_type=int(data.get("sessionType", 0)),
            track_id=int(data["trackId"]),
            car_id=int(data["carId"]),
            air_temp_c=conditions.get("airTemp"),
            track_temp_c=conditions.get("trackTemp"),
            has_telemetry=bool(data.get("hasTelemetry", False)),
        )


class FindLapsParams(BaseModel):
    """Typed wrapper for the /laps query parameters used by search_similar_conditions."""

    track_id: int
    car_id: int
    min_air_temp: Optional[float] = None
    max_air_temp: Optional[float] = None
    min_track_temp: Optional[float] = None
    max_track_temp: Optional[float] = None
    session_types: list[int] = Field(default_factory=lambda: [1, 2, 3])
    see_telemetry: bool = True


class Garage61Error(BaseModel):
    """Structured error payload returned to the MCP tool layer."""

    error: str
    message: str
    recoverable: bool
