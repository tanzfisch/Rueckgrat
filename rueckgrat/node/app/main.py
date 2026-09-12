import json
import os
import asyncio

from tqdm import tqdm
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from pathlib import Path
import os
from pydantic import BaseModel
from typing import List, Optional
from app.utils import ModelRegistry, LLamaCppInterface, CleanupWorker

from app.common import (
    get_logger, ChatRequestLlama, ChatResponse, ImageRequest, ImageResponse, 
    ModelInfo, GetModelsResponse, InstallModelResponse, InstallModelRequest, MessageQueue
)
logger = get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.dev_mode = os.getenv("DEV_MODE", "")
    if app.state.dev_mode == "":
        app.state.dev_mode = "prod"
    logger.info(f"running DEV_MODE={app.state.dev_mode}")

    if os.getenv("USE_LLAMA") == "true":
        host = "host.docker.internal"
        app.state.llamacpp = LLamaCppInterface(host, "8080")
    else:
        app.state.llamacpp = None

    if os.getenv("USE_IMAGE_GEN") == "true":
        from app.utils.image_gen import ImageGen
        app.state.image_gen = ImageGen()  
    else:
        app.state.image_gen = None

    # keep image cache clean
    app.state.cleanup_worker = CleanupWorker(folder="/node/images")
    app.state.cleanup_worker.start()

    logger.info("node initialized")

    yield

    app.state.cleanup_worker.stop()
    
    logger.info("node shut down")

app = FastAPI(lifespan=lifespan)   

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequestLlama):
    return app.state.llamacpp.chat(request)

@app.post("/image", response_model=ImageResponse)
def image(request: ImageRequest):
    if not app.state.image_gen:
        logger.error(f"Node has not image_gen module loaded")
        return ImageResponse(output="")
    
    registry = ModelRegistry()
    if not registry.has_model(request.model):
        logger.error(f"model {request.model} not found in registry")
        return ImageResponse(output="")

    if not registry.is_installed(request.model):
        try:
            _install_model(name=request.model)
        except Exception as e:
            logger.error(f"Model installation failed for {request.model}: {e}")
            return ImageResponse(output="")
    
    response = app.state.image_gen.image(request)
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
    
    models_list: List[ModelInfo] = []
    
    for model_name in registry.get_models(type_filter):
        installed = registry.is_installed(model_name)
        size_gb = registry.get_size(model_name)
        description = registry.get_description(model_name)
        
        models_list.append(ModelInfo(
            name=model_name,
            type=type_filter,
            installed=installed,
            size_gb=size_gb,
            description=description
        ))
    
    return GetModelsResponse(
        models=models_list
    )

def _install_model(name: str, alternative_server: str=None, force_install: bool=False):
    registry = ModelRegistry()
    
    if not registry.has_model(name):
        logger.error(f"model {name} not found in registry")
        raise HTTPException(
            status_code=404, 
            detail=f"Model '{name}' not registered"
        )
    
    installed_cfg = registry.install_model(name, alternative_server, force_install)
    
    if not installed_cfg:
        logger.error(f"Failed to install model {name}")
        raise HTTPException(
            status_code=500, 
            detail="Failed to install model '{name}'"
        )

@app.post("/models/install", response_model=InstallModelResponse)
def install_model(request: InstallModelRequest):
    try:
        _install_model(request.name, request.source, request.force)
        return InstallModelResponse(
           name=request.name,
           size_gb=0 # TODO
        )
         
    except Exception as e:
        logger.error(f"Model installation failed for {request.name}: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Installation failed: {str(e)}"
        )

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    closed = asyncio.Event()

    async def safe_close(code: int = 1000):
        if not closed.is_set():
            closed.set()
            try:
                await websocket.close(code=code)
            except RuntimeError:
                # already closed at ASGI level
                pass

    # recieve from client
    async def receiver():
        try:
            while not closed.is_set():
                text = await websocket.receive_text()
                data = json.loads(text)

                if "chat" in data:
                    chat_request = ChatRequestLlama(**data["chat"])
                    app.state.llamacpp.chat(chat_request, lambda message: MessageQueue().send_data(message))
                
                else:                    
                    logger.error(f"unknown request")
                    MessageQueue().send_data({"error": "unknown request", "data": data})

        except WebSocketDisconnect:
            print("Client disconnected (receiver)")
            await safe_close()

        except Exception as e:
            logger.error(f"receiver failure {repr(e)}")
            await safe_close(code=1011)

    # send to client
    async def sender():
        try:
            while not closed.is_set():
                message = MessageQueue().pop_message()
                if message:
                    try:
                        await websocket.send_text(json.dumps(message))
                    except RuntimeError:
                        break
                else:
                    await asyncio.sleep(0.01)

        except WebSocketDisconnect:
            print("Client disconnected (sender)")
            await safe_close()

        except Exception as e:
            logger.error(f"sender failure {repr(e)}")
            await safe_close(code=1011)

    receiver_task = asyncio.create_task(receiver())
    sender_task = asyncio.create_task(sender())

    done, pending = await asyncio.wait(
        [receiver_task, sender_task],
        return_when=asyncio.FIRST_EXCEPTION
    )

    await safe_close()

    for task in pending:
        task.cancel()

    await asyncio.gather(*pending, return_exceptions=True)
