import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.controllers.chat_controller import router as chat_router
from app.controllers.fintech_controller import router as fintech_router
from app.controllers.whatsapp_controller import router as whatsapp_router
from app.models.database import init_db

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    yield


init_db()

app = FastAPI(
    title="Fintech Omnichannel Assistant API",
    description=(
        "Omnichannel Financial Services Orchestrator integrating Meta WhatsApp Cloud API, "
        "Llama 3.1, Semantic RAG, Llama Stack Conversation Memory, Two-Layer Safety "
        "(Prompt Guard + Llama Guard), and SQLAlchemy Relational Core (CU-01..CU-04)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(fintech_router)
app.include_router(whatsapp_router)

if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    return FileResponse(os.path.join(WEB_DIR, "index.html"))
