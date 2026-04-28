import os
import json
import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                name VARCHAR UNIQUE NOT NULL,
                gender VARCHAR NOT NULL,
                gender_probability FLOAT NOT NULL,
                age INT NOT NULL,
                age_group VARCHAR NOT NULL,
                country_id VARCHAR(2) NOT NULL,
                country_name VARCHAR NOT NULL,
                country_probability FLOAT NOT NULL,
                created_at TIMESTAMP NOT NULL
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                github_id VARCHAR UNIQUE NOT NULL,
                username VARCHAR NOT NULL,
                email VARCHAR,
                avatar_url VARCHAR,
                role VARCHAR NOT NULL DEFAULT 'analyst',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                last_login_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL
            )
        """)


async def seed_db():
    """Insert seed profiles. Skips existing records (idempotent)."""
    seed_path = os.path.join(os.path.dirname(__file__), "seed_profiles.json")
    if not os.path.exists(seed_path):
        print("seed_profiles.json not found, skipping seed.")
        return

    with open(seed_path) as f:
        profiles = json.load(f)["profiles"]

    import uuid6
    from datetime import datetime, timezone

    pool = await get_pool()
    async with pool.acquire() as conn:
        inserted = 0
        for p in profiles:
            result = await conn.execute("""
                INSERT INTO profiles
                    (id, name, gender, gender_probability, age, age_group,
                     country_id, country_name, country_probability, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (name) DO NOTHING
            """,
                str(uuid6.uuid7()),
                p["name"].lower(),
                p["gender"],
                p["gender_probability"],
                p["age"],
                p["age_group"],
                p["country_id"],
                p["country_name"],
                p["country_probability"],
                datetime.now(timezone.utc).replace(tzinfo=None),
            )
            if result == "INSERT 0 1":
                inserted += 1

    print(f"Seed complete: {inserted} inserted, {len(profiles) - inserted} skipped.")
