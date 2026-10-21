#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import getpass
from importlib import import_module

import asyncpg

auth = import_module("01_HCM.auth")
settings = import_module("01_HCM.settings").settings


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create or reset a HomeControl ADMIN user.")
    parser.add_argument("username")
    parser.add_argument("--database-url", default=settings.database_url)
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("passwords do not match")
    if len(password) < 10:
        raise SystemExit("password must be at least 10 characters")

    conn = await asyncpg.connect(args.database_url)
    try:
        await conn.execute(
            """
            INSERT INTO users(username, role, password_hash, enabled)
            VALUES($1,'ADMIN',$2,true)
            ON CONFLICT(username)
            DO UPDATE SET role='ADMIN', password_hash=EXCLUDED.password_hash, enabled=true
            """,
            args.username,
            auth.hash_password(password),
        )
    finally:
        await conn.close()
    print(f"ADMIN user ready: {args.username}")


if __name__ == "__main__":
    asyncio.run(main())
