import asyncio
import httpx
from fastapi import HTTPException


async def fetch_genderize(name: str, client: httpx.AsyncClient) -> dict:
    resp = await client.get(f"https://api.genderize.io?name={name}")
    data = resp.json()
    if not data.get("gender") or not data.get("count"):
        raise HTTPException(status_code=502, detail="Genderize returned an invalid response")
    return data


async def fetch_agify(name: str, client: httpx.AsyncClient) -> dict:
    resp = await client.get(f"https://api.agify.io?name={name}")
    data = resp.json()
    if data.get("age") is None:
        raise HTTPException(status_code=502, detail="Agify returned an invalid response")
    return data


async def fetch_nationalize(name: str, client: httpx.AsyncClient) -> dict:
    resp = await client.get(f"https://api.nationalize.io?name={name}")
    data = resp.json()
    if not data.get("country"):
        raise HTTPException(status_code=502, detail="Nationalize returned an invalid response")
    return data


async def fetch_all(name: str) -> tuple[dict, dict, dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        results = await asyncio.gather(
            fetch_genderize(name, client),
            fetch_agify(name, client),
            fetch_nationalize(name, client),
        )
    return results[0], results[1], results[2]
