from contextlib import asynccontextmanager

from fastmcp import FastMCP

from garage61.client import (
    Garage61Client,
    get_cached_cars,
    get_cached_tracks,
    load_static_data,
)


@asynccontextmanager
async def lifespan(_server: FastMCP):
    client = None
    try:
        client = Garage61Client.from_env()
        await load_static_data(client)
        yield
    finally:
        if client:
            await client.close()


mcp = FastMCP("garage61-race-engineer", lifespan=lifespan)


@mcp.tool()
def list_tracks() -> dict:
    """Returns available tracks so the agent can resolve a track name to a track_id."""
    return {
        "tracks": [
            {"track_id": t.track_id, "name": t.name} for t in get_cached_tracks()
        ]
    }


@mcp.tool()
def list_cars() -> dict:
    """Returns available cars so the agent can resolve a car name to a car_id."""
    return {"cars": [{"car_id": c.car_id, "name": c.name} for c in get_cached_cars()]}


if __name__ == "__main__":
    mcp.run()
