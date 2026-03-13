import os
from tqdm import tqdm
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path

from pydantic import BaseModel
from app.utils import ModelRegistry, ChatRequest, ChatResponse, LLamaCppInterface


@asynccontextmanager
async def lifespan(app: FastAPI):
    # todo figure out which chat service is running
    host = "localhost" # TODO configureables
    port = "8080" # TODO configureables
    app.state.llamacpp_interface = LLamaCppInterface(host, port)
    print("Infrastructure initialized")

    yield
    
    print("Infrastructure shut down")

app = FastAPI(lifespan=lifespan)   

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    return app.state.llamacpp_interface.chat(request)

@app.get("/download/{file_path:path}")
async def download_file(file_path: str):
    path = Path(f"models/{file_path}")
    if not os.path.exists(path):
        return {"error": "File not found"}

    file_size = os.path.getsize(path)
    filename = path.name

    def iterfile():
        with open(path, "rb") as f:
            with tqdm(total=file_size, unit="B", unit_scale=True, desc=filename) as pbar:
                while chunk := f.read(1024 * 64):  # 64KB chunks
                    yield chunk
                    pbar.update(len(chunk))

    return StreamingResponse(
        iterfile(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

class GetModelURLRequest(BaseModel):
    model_name: str

class GetModelURLResponse(BaseModel):
    model_urls: list[str]

@app.get("/model")
def get_model_url(request: GetModelURLRequest):
    registry = ModelRegistry(Path.cwd() / "models")
    sources = registry.get_urls(request.model_name)
    print(f"infrastructure get_model_url {sources}")
    return GetModelURLResponse(
        model_urls=sources
    )

