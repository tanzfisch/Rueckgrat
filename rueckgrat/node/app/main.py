import json
import re
import os
import asyncio

from tqdm import tqdm
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, Response
from contextlib import asynccontextmanager
from pathlib import Path

TTS_VOICES_DIR = Path("/node/voices")  # same folder as VOICES_DIR in utils/tts.py
import os
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from app.utils import ModelRegistry, LLamaCppInterface, CleanupWorker

from app.common import (
    get_logger, set_log_level, ChatRequestLlama, ChatResponse, ImageRequest, ImageResponse, 
    ModelInfo, GetModelsResponse, InstallModelResponse, InstallModelRequest, 
    GetModelURLResponse, GetModelResponse, RegisteredModel, GetRegisteredModelsResponse,
    MessageQueue, NodeTTSRequest
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
        app.state.llamacpp = LLamaCppInterface(host, os.getenv("LLAMA_SERVER_PORT"))
    else:
        app.state.llamacpp = None

    if os.getenv("USE_IMAGE_GEN") == "true":
        from app.utils.image_gen import ImageGen
        app.state.image_gen = ImageGen()  
    else:
        app.state.image_gen = None

    if os.getenv("USE_TTS") == "true":
        from app.utils.tts import TextToSpeech
        app.state.tts = TextToSpeech()
        logger.debug(f"pre loading text to speech")
        app.state.tts.preload()
    else:
        app.state.tts = None

    if os.getenv("USE_STT") == "true":
        from app.utils.stt import SpeechToText
        app.state.stt = SpeechToText()
        logger.debug(f"pre loading speech to text")
        app.state.stt.preload()
    else:
        app.state.stt = None

    if os.getenv("USE_EMBEDDING") == "true":
        from app.utils.embedding import TextEmbedder
        app.state.embedder = TextEmbedder()
        try:
            app.state.embedder.preload()
        except Exception as e:
            logger.error(f"embedding model not loaded: {e}")
    else:
        app.state.embedder = None

    if os.getenv("USE_DECISION") == "true":
        from app.utils.decision import DecisionModel
        app.state.decision = DecisionModel()
        try:
            app.state.decision.preload()
        except Exception as e:
            logger.error(f"decision model not loaded: {e}")
    else:
        app.state.decision = None

    # keep image cache clean
    app.state.cleanup_worker = CleanupWorker(folder="/node/images")
    app.state.cleanup_worker.start()

    logger.info("\n"
    "          ╭───────────────────────────╮\n"
    "          │     🚀   Rückgrat   🚀    │\n"
    "          │                           │\n"
    "          │      Node initialized     │\n"
    "          ╰───────────────────────────╯")

    yield

    app.state.cleanup_worker.stop()
    
    logger.info("node shut down")

app = FastAPI(lifespan=lifespan)   

@app.get("/health")
def health():
    return {"status": "ok"}

@app.put("/log-level/{level}")
def _set_log_level(level: str):
    name = level.upper()
    try:
        set_log_level(name)
    except ValueError:
        logger.error("failed to set log level %s", level)
        raise HTTPException(status_code=400, detail=f"invalid log level: {level}")
    return {"log_level": name}

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

@app.post("/tts")
def tts(request: NodeTTSRequest):
    if not app.state.tts:
        raise HTTPException(status_code=503, detail="Node has no tts module loaded")
    from app.utils.tts import TTS_MODEL
    try:
        # the tts class installs its own model through the registry if it is missing
        app.state.tts.install()
    except Exception as e:
        logger.error(f"Model installation failed for {TTS_MODEL}: {e}")
        raise HTTPException(status_code=503, detail=f"tts model {TTS_MODEL} not installed")
    try:
        wav = app.state.tts.speak(request.text, request.voice, request.exaggeration, request.cfg_weight, request.language)
    except Exception as e:
        logger.error(f"tts failed: {e!r}")
        raise HTTPException(status_code=500, detail="tts failed")
    return Response(content=wav, media_type="audio/wav")

@app.post("/stt")
async def stt(request: Request, kind: str = "final", language: str = ""):
    """body: raw 16 kHz mono pcm_s16le audio. kind: final (accurate model) or partial (fast model).
    language: whisper language code, "" = detect it"""
    if not app.state.stt:
        raise HTTPException(status_code=503, detail="Node has no stt module loaded")
    from app.utils.stt import STT_MODELS
    if kind not in STT_MODELS:
        raise HTTPException(status_code=400, detail=f"unknown kind {kind}")
    model_name = STT_MODELS[kind]
    try:
        # the stt class installs its own models through the registry if they are missing
        install_path = await asyncio.to_thread(app.state.stt.install, kind)
    except Exception as e:
        logger.error(f"Model installation failed for {model_name}: {e}")
        raise HTTPException(status_code=503, detail=f"stt model {model_name} not installed")

    pcm16 = await request.body()
    try:
        text = await asyncio.to_thread(app.state.stt.transcribe, pcm16, kind, install_path, language)
    except Exception as e:
        logger.error(f"stt failed: {e!r}")
        raise HTTPException(status_code=500, detail="stt failed")
    return {"text": text}

MAX_EMBED_TEXTS = 64
MAX_EMBED_CHARS = 2000

class EmbedRequest(BaseModel):
    texts: List[str]
    query: bool = False    # True: search queries, False: passages that are stored

@app.post("/embed")
async def embed(request: EmbedRequest):
    """text embeddings, one vector per text in order: {"vectors": [[floats], ...]}"""
    if not app.state.embedder:
        raise HTTPException(status_code=503, detail="Node has no embedding module loaded")
    if not request.texts or len(request.texts) > MAX_EMBED_TEXTS or any(len(t) > MAX_EMBED_CHARS for t in request.texts):
        raise HTTPException(status_code=400, detail=f"1 to {MAX_EMBED_TEXTS} texts of max {MAX_EMBED_CHARS} characters")
    try:
        vectors = await asyncio.to_thread(app.state.embedder.embed, request.texts, request.query)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"embedding failed: {e!r}")
        raise HTTPException(status_code=500, detail="embedding failed")
    return {"vectors": vectors}

MAX_DECIDE_QUESTIONS = 64
MAX_DECIDE_CHARS = 4000

class DecideRequest(BaseModel):
    state: str                              # the text the questions are about
    questions: Dict[str, Dict[str, Any]]    # laya questions by id: {"type": "choice"|"score"|"noul", "instructions": ..., "criteria": ...}

@app.post("/decide")
async def decide(request: DecideRequest):
    """laya typed decisions, all questions in one forward pass: {"answers": {id: {"type": "noul", "noul": P(true), ...}}}"""
    if not app.state.decision:
        raise HTTPException(status_code=503, detail="Node has no decision module loaded")
    if not request.state or len(request.state) > MAX_DECIDE_CHARS or not request.questions or len(request.questions) > MAX_DECIDE_QUESTIONS:
        raise HTTPException(status_code=400, detail=f"a state of max {MAX_DECIDE_CHARS} characters and 1 to {MAX_DECIDE_QUESTIONS} questions")
    try:
        answers = await asyncio.to_thread(app.state.decision.decide, request.state, request.questions)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))    # laya refuses malformed questions with ValueError
    except Exception as e:
        logger.error(f"decision failed: {e!r}")
        raise HTTPException(status_code=500, detail="decision failed")
    return {"answers": answers}

VOICE_ID_PATTERN = r"[\w.-]+"
MAX_VOICE_BYTES = 20 * 1024 * 1024

@app.head("/voices/{voice_id}")
def has_voice(voice_id: str):
    """lets the hub check whether a voice wav is already in the local cache"""
    if not re.fullmatch(VOICE_ID_PATTERN, voice_id) or not (TTS_VOICES_DIR / f"{voice_id}.wav").exists():
        raise HTTPException(status_code=404, detail="voice not found")
    return Response(status_code=200)

@app.put("/voices/{voice_id}")
async def store_voice(voice_id: str, request: Request):
    """the hub pushes a voice wav here (raw body). the node never calls the hub"""
    if not re.fullmatch(VOICE_ID_PATTERN, voice_id):
        raise HTTPException(status_code=400, detail="invalid voice id")
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty voice file")
    if len(data) > MAX_VOICE_BYTES:
        raise HTTPException(status_code=413, detail="voice file too large")
    TTS_VOICES_DIR.mkdir(parents=True, exist_ok=True)
    path = TTS_VOICES_DIR / f"{voice_id}.wav"
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)  # atomic, a half written file is never used by tts
    logger.debug(f"cached voice {voice_id} ({len(data)} bytes)")
    return {"status": "ok", "voice_id": voice_id}

@app.delete("/voices/{voice_id}")
def drop_voice(voice_id: str):
    """the hub removes a cached voice after it was deleted on the hub"""
    if re.fullmatch(VOICE_ID_PATTERN, voice_id):
        (TTS_VOICES_DIR / f"{voice_id}.wav").unlink(missing_ok=True)
    return {"status": "ok", "voice_id": voice_id}

@app.get("/downloads/{file_path:path}")
async def download_file(file_path: str):
    base_path = Path("/node").resolve()
    path = (base_path / file_path).resolve()

    # only what the hub fetches: generated images and model files. /node also holds the config
    # (infrastructure.json with the tunnel token) and the code, and this endpoint has no auth
    allowed = [base_path / "images", base_path / "models"]
    if not any(path.is_relative_to(folder) and path != folder for folder in allowed):
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

# fixed paths before /models/{model_name}: fastapi matches routes in declaration order
@app.get("/models/registered", response_model=GetRegisteredModelsResponse)
def get_registered_models():
    registry = ModelRegistry()
    models = []
    for model_name in registry.get_models():
        model = registry.get_model(model_name) or {}
        models.append(RegisteredModel(name=model_name, type=model.get("type")))
    return GetRegisteredModelsResponse(models=models)

@app.get("/models/{model_name}", response_model=GetModelResponse)
def get_model(model_name: str):
    registry = ModelRegistry()
    model = registry.get_model(model_name)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not registered")
    installed = bool(registry.is_installed(model_name))
    return GetModelResponse(
        name=model_name,
        type=model.get("type"),
        description=model.get("description") or "",
        comment=model.get("comment") or "",
        compatibility=model.get("compatibility"),
        install_path=model.get("install_path") or "",
        files=model.get("files") or [],
        installed=installed,
        size_bytes=registry.get_size(model_name) if installed else 0,
    )

@app.get("/models/{model_name}/url")
def get_model_url(model_name: str):
    registry = ModelRegistry()
    if not registry.has_model(model_name):
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' not registered")
    sources = registry.get_urls(model_name) or []
    return GetModelURLResponse(
        model_urls=sources
    )

@app.get("/models", response_model=GetModelsResponse)
def get_models(type_filter: Optional[str] = None, verbose: bool = False):
    registry = ModelRegistry()
    
    models_list: List[ModelInfo] = []
    
    for model_name in registry.get_models(type_filter):
        installed = registry.is_installed(model_name)
        size_gb = registry.get_size(model_name) / 1024**3     # get_size is in bytes
        description = registry.get_description(model_name)
        
        models_list.append(ModelInfo(
            name=model_name,
            type=(registry.get_model(model_name) or {}).get("type") or "",
            installed=bool(installed),
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
            detail=f"Failed to install model '{name}'"
        )

@app.post("/models/install", response_model=InstallModelResponse)
def install_model(request: InstallModelRequest):
    try:
        _install_model(request.name, request.source, request.force)
        return InstallModelResponse(
           name=request.name,
           size_gb=0 # TODO
        )
         
    except HTTPException:
        raise   # already has the right status (404 unknown model, 500 install failed)
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
    chats = set()  # running chat threads, referenced so they aren't garbage collected

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
                    # in a thread, so this keeps reading (cancels, a second chat for llama-server's other slot).
                    # MessageQueue is locked, safe to fill from the thread
                    chat_request = ChatRequestLlama(**data["chat"])
                    chat = asyncio.create_task(asyncio.to_thread(app.state.llamacpp.chat, chat_request, lambda message: MessageQueue().send_data(message)))
                    chats.add(chat)
                    chat.add_done_callback(chats.discard)

                elif "cancel" in data:
                    app.state.llamacpp.cancel(data["cancel"])
                
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
