import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import database
from .webhooks import router as webhooks_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="Never Miss a Job -- Week 1 Backend", lifespan=lifespan)
app.include_router(webhooks_router)


@app.get("/")
async def root():
    return {"status": "ok", "service": "never-miss-a-job-backend", "week": 1}


@app.get("/health")
async def health():
    return {"status": "ok"}
