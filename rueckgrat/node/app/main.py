import os
from tqdm import tqdm
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from pathlib import Path
import uuid
from pydantic import BaseModel
from typing import List, Optional
from app.utils import ModelRegistry, LLamaCppInterface, ComfyUIInterface, CleanupWorker

from app.common import (
    get_logger, ChatRequestLlama, ChatResponse, ImageRequest, ImageResponse, 
    ModelInfo, GetModelsResponse, InstallModelResponse, InstallModelRequest
)
logger = get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.dev_mode = os.getenv("DEV_MODE", "")
    if app.state.dev_mode == "":
        app.state.dev_mode = "prod"
    logger.info(f"running DEV_MODE={app.state.dev_mode}")

    host = "host.docker.internal"
    app.state.llamacpp = LLamaCppInterface(host, "8080")

    client_id = str(uuid.uuid4())
    app.state.comfyui = ComfyUIInterface(host, "8188", client_id)

    # keep image cache clean
    app.state.cleanup_worker = CleanupWorker(folder="/node/images")
    app.state.cleanup_worker.start()

    logger.info("Infrastructure initialized")

    yield

    app.state.cleanup_worker.stop()
    
    logger.info("Infrastructure shut down")

app = FastAPI(lifespan=lifespan)   

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequestLlama):
    return app.state.llamacpp.chat(request)

@app.post("/image", response_model=ImageResponse)
def image(request: ImageRequest):
    response = app.state.comfyui.image(request)
    if not response:
        logger.error("failed to generate image with comfyui")
    return response

@app.get("/downloads/{file_path:path}")
async def download_file(file_path: str):
    base_path = Path("/node").resolve()
    path = (base_path / file_path).resolve()

    if not str(path).startswith(str(base_path)):
        raise HTTPException(status_code=400, detail="Invalid path")

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")

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

class GetModelURLResponse(BaseModel):
    model_urls: list[str]

@app.get("/models/{model_name}/url")
def get_model_url(model_name: str):
    registry = ModelRegistry()
    sources = registry.get_urls(model_name)
    return GetModelURLResponse(
        model_urls=sources
    )

@app.get("/models", response_model=GetModelsResponse)
def get_models(type_filter: Optional[str] = None, verbose: bool = False):
    registry = ModelRegistry()
    data = registry.get_registry()
    
    models_list: List[ModelInfo] = []
    
    for key, model_cfg in data.items():
        if type_filter and type_filter != model_cfg.get("type"):
            continue
            
        installed = registry.check_model_files(model_cfg)
        
        size_gb = None
        if verbose and installed:
            size_gb = registry.get_model_size(model_cfg)
        
        models_list.append(ModelInfo(
            name=key,
            type=model_cfg.get("type", "unknown"),
            installed=installed,
            size_gb=size_gb,
            description=model_cfg.get("description")  # assuming this field exists
        ))
    
    return GetModelsResponse(
        models=models_list
    )

@app.post("/models/install", response_model=InstallModelResponse)
def install_model(request: InstallModelRequest):
    registry = ModelRegistry()
    
    model_cfg = registry.get_model_cfg(request.name)
    if not model_cfg:
        logger.error(f"model {request.name} not found in registry")
        raise HTTPException(
            status_code=404, 
            detail=f"Model '{request.name}' not registered"
        )
    
    try:
        installed_cfg = registry.install_model(
            request.name,
            request.source,
            request.force
        )
        
        if not installed_cfg:
            logger.error(f"Failed to install model {request.name}")
            raise HTTPException(
                status_code=500, 
                detail="Failed to install model"
            )
        
        size_gb = registry.get_model_size(installed_cfg) if installed_cfg else None
        
        return InstallModelResponse(
            name=request.name,
            size_gb=size_gb
        )
        
    except Exception as e:
        logger.error(f"Model installation failed for {request.name}: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Installation failed: {str(e)}"
        )