"""
Garage61 API client.

# ============================================================================
# WARNING: TELEMETRY_COLUMNS MUST BE VERIFIED AGAINST A REAL API RESPONSE
# The column names listed in TELEMETRY_COLUMNS below are ASSUMED based on
# iRacing SDK conventions. They have NOT been confirmed against an actual
# GET /laps/{id}/csv response from the Garage61 API.
# Once a real response is available, update TELEMETRY_COLUMNS and re-run the
# test suite. See docs/PROJECT_SPECS.md §13 "Confirm CSV column names".
# ============================================================================
"""

from __future__ import annotations

import json
import logging
from io import StringIO

from typing import Any

import httpx
import pandas as pd
from pydantic_settings import BaseSettings, SettingsConfigDict

from garage61.models import Car, FindLapsParams, LapDetail, LapSummary, Track
from garage61.exceptions import (
    APIError,
    LapNotFoundError,
    TelemetryParseError,
    TelemetryUnavailableError,
)
from garage61.constants import (
    BASE_URL,
    STATIC_DIR,
    TELEMETRY_CACHE_MAX,
)

from utils.lru_cache import LRUCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Assumed telemetry CSV column names.
# NOTE: These MUST be verified against a real GET /laps/{id}/csv response.
# Update this list and re-run tests once confirmed. See module docstring.
# ---------------------------------------------------------------------------
TELEMETRY_COLUMNS: list[str] = [
    "LapDistPct",         # Lap distance as 0.0–1.0 fraction
    "Speed",              # Speed in m/s
    "Throttle",           # Throttle position 0.0–1.0
    "Brake",              # Brake pressure 0.0–1.0
    "Gear",               # Current gear (integer)
    "SteeringWheelAngle", # Steering angle in radians
    "PositionType",       # Position type: 3 = on track
]



# Module-level static reference data, populated once by load_static_data().
_TRACKS: list[Track] = []
_CARS: list[Car] = []


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class _Settings(BaseSettings):
    garage61_api_key: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")



# ---------------------------------------------------------------------------
# Static data loader
# ---------------------------------------------------------------------------

async def load_static_data(client: Garage61Client) -> None:
    """Load track and car reference data into module-level variables.

    Reads from ``static/tracks.json`` and ``static/cars.json`` if present.
    Falls back to live API calls if either file is missing, and logs a
    WARNING directing the operator to run ``scripts/seed_static.py``.
    """
    global _TRACKS, _CARS

    tracks_path = STATIC_DIR / "tracks.json"
    cars_path = STATIC_DIR / "cars.json"

    try:
        _TRACKS = [Track(**t) for t in json.loads(tracks_path.read_text())]
        logger.debug("Loaded %d tracks from %s", len(_TRACKS), tracks_path)
    except FileNotFoundError:
        logger.warning(
            "static/tracks.json not found — falling back to GET /tracks. "
            "Run scripts/seed_static.py to generate the static file and "
            "avoid this API call on every server start."
        )
        _TRACKS = await client.get_tracks()

    try:
        _CARS = [Car(**c) for c in json.loads(cars_path.read_text())]
        logger.debug("Loaded %d cars from %s", len(_CARS), cars_path)
    except FileNotFoundError:
        logger.warning(
            "static/cars.json not found — falling back to GET /cars. "
            "Run scripts/seed_static.py to generate the static file and "
            "avoid this API call on every server start."
        )
        _CARS = await client.get_cars()


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class Garage61Client:
    """Async Garage61 API client.

    Instantiate once at server startup via ``Garage61Client.from_env()``.
    All methods raise subclasses of ``Garage61ClientError`` on failure.
    """

    def __init__(self, api_key: str) -> None:
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        self._telemetry_cache = LRUCache(maxsize=TELEMETRY_CACHE_MAX)

    @classmethod
    def from_env(cls) -> Garage61Client:
        """Create a client from the ``GARAGE61_API_KEY`` environment variable."""
        settings = _Settings()
        return cls(api_key=settings.garage61_api_key)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Garage61Client:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, **params: Any) -> Any:
        """Issue a GET request and return parsed JSON.

        Keyword arguments with ``None`` values are omitted from the query
        string. List values are passed as repeated query parameters.

        Raises:
            LapNotFoundError: On 404.
            APIError: On any other non-2xx status or network error.
        """
        filtered: dict[str, Any] = {k: v for k, v in params.items() if v is not None}
        try:
            response = await self._http.get(path, params=filtered)
        except httpx.HTTPError as exc:
            raise APIError(f"HTTP error while requesting {path}: {exc}") from exc

        if response.status_code == 404:
            raise LapNotFoundError(f"Resource not found: {path}")
        if not response.is_success:
            raise APIError(
                f"Garage61 API returned {response.status_code} for {path}: "
                f"{response.text[:200]}"
            )
        return response.json()

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_tracks(self) -> list[Track]:
        """Return all available tracks from GET /tracks."""
        data = await self._get("/tracks")
        items: list[dict[str, Any]] = data if isinstance(data, list) else data.get("tracks", [])
        return [Track.from_api(t) for t in items]

    async def get_cars(self) -> list[Car]:
        """Return all available cars from GET /cars."""
        data = await self._get("/cars")
        items: list[dict[str, Any]] = data if isinstance(data, list) else data.get("cars", [])
        return [Car.from_api(c) for c in items]

    async def find_laps(self, params: FindLapsParams) -> list[LapSummary]:
        """Search for laps matching the given parameters via GET /laps."""
        data = await self._get(
            "/laps",
            tracks=[params.track_id],
            cars=[params.car_id],
            sessionTypes=params.session_types,
            seeTelemetry=params.see_telemetry,
            group="none",
            minConditionsAirTemp=params.min_air_temp,
            maxConditionsAirTemp=params.max_air_temp,
            minConditionsTrackTemp=params.min_track_temp,
            maxConditionsTrackTemp=params.max_track_temp,
        )
        items: list[dict[str, Any]] = data if isinstance(data, list) else data.get("laps", [])
        return [LapSummary.from_api(lap) for lap in items]

    async def get_lap(self, lap_id: str) -> LapDetail:
        """Fetch metadata for a single lap via GET /laps/{id}.

        Raises:
            LapNotFoundError: If the lap does not exist or is not accessible.
        """
        data = await self._get(f"/laps/{lap_id}")
        return LapDetail.from_api(data)

    async def get_lap_telemetry(self, lap_id: str, lap_length_m: float) -> pd.DataFrame:
        """Fetch, parse, and cache telemetry CSV for a lap.

        Filters rows to ``PositionType == 3`` (on track only) and adds a
        ``distance_m`` column computed as ``LapDistPct * lap_length_m``.

        Results are LRU-cached (cap: 10 laps) keyed by ``lap_id``.

        Args:
            lap_id: The Garage61 lap identifier (string).
            lap_length_m: Track lap length in metres, used to convert
                ``LapDistPct`` (0.0–1.0) to absolute distance.

        Raises:
            TelemetryUnavailableError: If the API returns 404 for the CSV.
            TelemetryParseError: If expected columns are absent in the CSV.
            APIError: For any other non-2xx response or network error.
        """
        cached = self._telemetry_cache.get(lap_id)
        if cached is not None:
            logger.debug("Telemetry cache hit for lap %s", lap_id)
            return cached

        try:
            response = await self._http.get(f"/laps/{lap_id}/csv")
        except httpx.HTTPError as exc:
            raise APIError(
                f"HTTP error fetching telemetry for lap {lap_id}: {exc}"
            ) from exc

        if response.status_code == 404:
            raise TelemetryUnavailableError(
                f"No telemetry available for lap {lap_id} (404)."
            )
        if not response.is_success:
            raise APIError(
                f"Garage61 API returned {response.status_code} for lap "
                f"{lap_id} CSV: {response.text[:200]}"
            )

        df = self._parse_telemetry_csv(response.text, lap_id, lap_length_m)
        self._telemetry_cache.put(lap_id, df)
        logger.debug(
            "Fetched and cached telemetry for lap %s (%d on-track rows)",
            lap_id,
            len(df),
        )
        return df

    @staticmethod
    def _parse_telemetry_csv(
        csv_text: str,
        lap_id: str,
        lap_length_m: float,
    ) -> pd.DataFrame:
        """Parse raw CSV text into a filtered, distance-aligned DataFrame.

        Validates that all ``TELEMETRY_COLUMNS`` are present, then:

        - Filters to rows where ``PositionType == 3`` (on track).
        - Adds ``distance_m = LapDistPct * lap_length_m``.

        Raises:
            TelemetryParseError: If any expected column is absent.
        """
        df = pd.read_csv(StringIO(csv_text))

        missing = [col for col in TELEMETRY_COLUMNS if col not in df.columns]
        if missing:
            raise TelemetryParseError(
                f"Telemetry CSV for lap {lap_id} is missing expected columns: "
                f"{missing}. Present columns: {list(df.columns)}. "
                "Update TELEMETRY_COLUMNS in client.py once confirmed against "
                "a real API response."
            )

        df = df[df["PositionType"] == 3].copy()
        df["distance_m"] = df["LapDistPct"] * lap_length_m
        return df.reset_index(drop=True)
