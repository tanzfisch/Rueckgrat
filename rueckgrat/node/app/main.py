import os
from tqdm import tqdm
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from pathlib import Path
import uuid
from pydantic import BaseModel
from app.utils import ModelRegistry, LLamaCppInterface, ComfyUIInterface

from app.common import Logger, ChatRequestLlama, ChatResponse, ImageRequest, ImageResponse
logger = Logger(__name__).get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):

    host = "host.docker.internal"
    llamacpp_port = "8080" # TODO make configurable
    app.state.llamacpp = LLamaCppInterface(host, llamacpp_port)

    comfyui_port = "8188" # TODO make configurable
    client_id = str(uuid.uuid4())
    app.state.comfyui = ComfyUIInterface(host, comfyui_port, client_id)

    logger.info("Infrastructure initialized")

    yield
    
    logger.info("Infrastructure shut down")

app = FastAPI(lifespan=lifespan)   

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequestLlama):
    logger.debug("got ChatRequest")
    return app.state.llamacpp.chat(request)

@app.post("/image", response_model=ImageResponse)
def chat(request: ImageRequest):
    logger.debug("got ImageRequest")
    return app.state.comfyui.image(request)

@app.get("/download/{file_path:path}")
async def download_file(file_path: str):
    base_path = Path("/node").resolve()
    path = (base_path / file_path).resolve()

    if not str(path).startswith(str(base_path)):
        return {"error": "Invalid path"}

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
    registry = ModelRegistry("/node/models")
    sources = registry.get_urls(request.model_name)
    return GetModelURLResponse(
        model_urls=sources
    )

