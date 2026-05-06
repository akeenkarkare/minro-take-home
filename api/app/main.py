from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="minro enrichment", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
