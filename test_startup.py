import asyncio
from app.main import lifespan
from fastapi import FastAPI

async def test():
    async with lifespan(FastAPI()):
        pass

if __name__ == "__main__":
    asyncio.run(test())
