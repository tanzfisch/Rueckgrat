from silero_vad import load_silero_vad
import json
import random
import asyncio
import threading
import os
import io
import wave
import hashlib
from tqdm import tqdm
from pathlib import Path
import numpy as np
import torch

from fastapi.responses import StreamingResponse, Response
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from fastapi.security import HTTPBearer
from fastapi.concurrency import run_in_threadpool

from pydantic import BaseModel
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from app.utils import ChatDB, Infrastructure, ImageType, ImageStore
from app.tools import ToolRegistry
from app.jobs import JobQueue, MetaJob, AssistantImageJob, ContactGeneratorJob
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from jose import jwt
from datetime import datetime, timedelta, timezone

from app.common import get_logger, set_log_level, ChatRequest, GetMessagesRequest, MessageQueue, GetModelURLResponse, HubTTSRequest
logger = get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("connecting infrastructure")
    app.state.infrastructure = Infrastructure()
    await app.state.infrastructure.connect_nodes()

    logger.info("loading db")
    db_path = "/hub/db/chat.db"
    app.state.db = ChatDB(db_path)
    app.state.image_store = ImageStore(app.state.db, app.state.infrastructure)
    app.state.job_queue = JobQueue()

    logger.info("loading tool registry")
    app.state.tool_registry = ToolRegistry(
        infrastructure=app.state.infrastructure,
        db=app.state.db,
        job_queue=app.state.job_queue
    )

    logger.info("loading vad")
    app.state.vad = load_silero_vad(onnx=True)
    torch.set_num_threads(1)

    logger.info("hub initialized")

    yield

    app.state.job_queue.stop()

    logger.info("hub shut down")


app = FastAPI(lifespan=lifespan)
security = HTTPBearer(auto_error=False)

########### user handling
SECRET_KEY = "change_this_later"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

ph = PasswordHasher()

def decode_token(token: str):
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )
        return payload["sub"]

    except Exception:        
        raise HTTPException(status_code=401, detail="Invalid token")

def hash_password(password: str) -> str:
    return ph.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        ph.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        return False

def create_access_token(username: str):
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": username,
        "exp": expire
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials=Depends(security)):
    if credentials is None:
        return None 

    try:
        token = credentials.credentials
        return decode_token(token)
    except Exception:
        return None

async def get_current_user_ws(websocket: WebSocket):
    auth_header = websocket.headers.get("authorization")
    
    if not auth_header:
        await websocket.close(code=4001, reason="Missing token")
        raise Exception("No auth")  # or return None if you prefer
    
    try:
        scheme, token = auth_header.split()
        if scheme.lower() != "bearer":
            raise ValueError
        return decode_token(token)
    except Exception:
        await websocket.close(code=4001, reason="Invalid token")
        raise

@app.get("/users")
def get_users():
    # invite mode: the hub is public, never hand out who has an account.
    # Clients log in with a typed name instead (chat login_page)
    if SIGNUP_MODE == "invite":
        raise HTTPException(status_code=403, detail="user list disabled in invite mode")
    users = app.state.db.get_users()
    return {"users": users}

@app.get("/users/me")
def get_user_data(username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    user_data = app.state.db.get_user_data(user_id)
    return {"user_data": user_data}  

class UpdateUserDataRequest(BaseModel):
    user_id: int
    user_data: dict

@app.patch("/users/me")
def update_contact(request: UpdateUserDataRequest, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    if user_id != request.user_id:
        return {"status": "wrong user"}

    if app.state.db.update_user_data(
        user_id = request.user_id,
        user_data = request.user_data
    ):
        return {"status": "ok"}
    else:
        return {"status": "failed"}

# "open": anyone can create an account (default, fine for local use)
# "invite": signup needs a valid invite token, use this when the hub is reachable from the internet
SIGNUP_MODE = os.environ.get("SIGNUP_MODE", "open").lower()
if SIGNUP_MODE not in ("open", "invite"):
    raise RuntimeError(f"invalid SIGNUP_MODE {SIGNUP_MODE}, expected open or invite")

INVITE_ERRORS = {
    "unknown": "this invite code is not valid",
    "expired": "this invite has expired",
    "exhausted": "this invite has already been used",
    "email mismatch": "this invite belongs to a different email address",
}

class UserCreate(BaseModel):
    user_name: str
    user_passwd: str
    invite_token: str | None = None
    email: str | None = None

@app.post("/users")
def create_user(user: UserCreate):
    if SIGNUP_MODE == "open":
        user_id = app.state.db.create_user(user.user_name, hash_password(user.user_passwd))
        return {"user_id": user_id}

    if not user.invite_token:
        raise HTTPException(status_code=403, detail="invite required")

    user_id, reason = app.state.db.create_user_with_invite(
        user.user_name, hash_password(user.user_passwd), user.invite_token, user.email
    )
    if reason == "username exists":
        raise HTTPException(status_code=409, detail="username already exists")
    if reason:
        logger.warning(f"signup rejected for {user.user_name}: invite {reason}")
        raise HTTPException(status_code=403, detail=INVITE_ERRORS.get(reason, "invite not accepted"))

    return {"user_id": user_id}

@app.get("/signup-mode")
def get_signup_mode():
    return {"mode": SIGNUP_MODE}

class LoginRequest(BaseModel):
    user_name: str
    user_passwd: str

@app.post("/login")
def login(data: LoginRequest):
    user = app.state.db.get_user(data.user_name)

    if not user:
        raise HTTPException(status_code=401)

    if not verify_password(data.user_passwd or "", user["password"]):
        raise HTTPException(status_code=401)

    token = create_access_token(user["username"])

    return {
        "access_token": token,
        "user_id": user["id"],
        "nsfw_allowed": bool(user["nsfw_allowed"])
    }

########### system handling
@app.get("/health")
def health():
    # hub is up; missing nodes make the system degraded, not broken
    status = app.state.infrastructure.get_status()
    missing = [f"{node.url} {node.error}" for node in status.nodes if not node.ok]
    if missing:
        return {"status": "degraded", "message": ", ".join(missing)}

    return {"status": "ok"}

@app.put("/log-level/{level}")
def _set_log_level(level: str):
    name = level.upper()
    try:
        set_log_level(name)
        app.state.infrastructure.set_log_level(name)
    except ValueError:
        logger.error("failed to set log level %s", level)
        raise HTTPException(status_code=400, detail=f"invalid log level: {level}")
    return {"log_level": name}

########### contact handling
@app.get("/contacts")
def get_contacts(username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    contacts = app.state.db.get_contacts(user_id)

    for contact in contacts:
        images = app.state.db.get_contact_images(contact["id"])
        contact["images"] = images

    return {"contacts": contacts}

@app.get("/contact/{contact_id}")
def get_contact(contact_id: int, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    if not app.state.db.owns_contact(user_id, contact_id):
        raise HTTPException(status_code=404, detail="contact not found")
    contact = app.state.db.get_contact_by_id(contact_id)
    images = app.state.db.get_contact_images(contact_id)
    contact["images"] = images

    return {"contact": contact}

@app.post("/contacts")
def create_contact(username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    contact_name = f"new_contact_{random.randint(0,100000)}"
    contact_id = app.state.db.create_contact(user_id, contact_name)
    return {"contact_id": contact_id}

class UpdateContactRequest(BaseModel):
    contact_data: dict

@app.patch("/contacts/{contact_id}")
def update_contact(contact_id: int, request: UpdateContactRequest, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    if not app.state.db.owns_contact(user_id, contact_id):
        raise HTTPException(status_code=404, detail="contact not found")
    app.state.db.update_contact(user_id, contact_id, request.contact_data)
    
    job = AssistantImageJob(
        user_id = user_id,
        contact_id = contact_id,
        db = app.state.db, 
        infrastructure = app.state.infrastructure, 
        image_type = ImageType.UpperBody,
        store_image_as = "profile",
        width = 720,
        height = 720,                
    )        
    app.state.job_queue.add(job)

    return {"status": "ok"}

@app.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    if not app.state.db.owns_contact(user_id, contact_id):
        raise HTTPException(status_code=404, detail="contact not found")
    image_keys = app.state.db.get_contact_image_keys(contact_id)
    if app.state.db.delete_contact(contact_id):
        released_images = app.state.image_store.release(image_keys, drop_conversation_images=False)
        return {"status": "ok", "released_images": released_images}
    else:
        return {"status": "failed to delete contact"}

########### conversations handling
@app.get("/contacts/{contact_id}/conversations")
def get_conversations(contact_id: int, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    conversations = app.state.db.get_conversations(user_id, contact_id)
    return {"conversations": conversations}

@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    if not app.state.db.owns_conversation(user_id, conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    conversation = app.state.db.get_conversation(conversation_id)
    return {"conversation": conversation}

class CreateConversationRequest(BaseModel):
    contact_id: int

@app.post("/conversations")
def create_conversation(request: CreateConversationRequest, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    if not app.state.db.owns_contact(user_id, request.contact_id):
        raise HTTPException(status_code=404, detail="contact not found")
    conversation_id = app.state.db.create_conversation(user_id, request.contact_id)
    return {"conversation_id": conversation_id}

@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    if not app.state.db.owns_conversation(user_id, conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    image_keys = app.state.db.get_conversation_image_keys(conversation_id)
    if app.state.db.delete_conversation(conversation_id):
        released_images = app.state.image_store.release(image_keys)
        return {"status": "ok", "released_images": released_images}
    else:
        return {"status": "failed to delete conversation"}

@app.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: int, request: GetMessagesRequest, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    if not app.state.db.owns_conversation(user_id, conversation_id):
        raise HTTPException(status_code=404, detail="conversation not found")
    messages = app.state.db.get_messages_by_conversation(conversation_id, request.max_messages)
    return {"messages": messages}

@app.get("/messages/{message_id}/attachments")
def get_messages(message_id: int, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    if not app.state.db.owns_message(user_id, message_id):
        raise HTTPException(status_code=404, detail="message not found")
    attachments = app.state.db.get_attachments_for_message(message_id)
    return {"attachments": attachments}

########### text to speech
@app.post("/tts")
def text_to_speech(request: HubTTSRequest, username: str = Depends(get_current_user)):
    wav = app.state.infrastructure.tts(request.text, request.voice)
    if wav is None:
        raise HTTPException(status_code=503, detail="text to speech not available")
    return Response(content=wav, media_type="audio/wav")

########### voice handling
MAX_VOICE_UPLOAD_BYTES = 20 * 1024 * 1024

# predefined voices from characters/voices in the repo, mounted read only (see compose.yml)
PREDEFINED_VOICES_DIR = Path("/hub/predefined_voices")

def store_voice(user_id: int, data: bytes, predefined_id: str = "") -> str:
    """
    validates wav bytes and saves them as /hub/voices/<uuid>.wav, returns the uuid.
    predefined_id is the voices.json id for a predefined voice, "" for an upload.
    raises HTTPException if the data is not usable
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            frames, sample_rate = w.getnframes(), w.getframerate()
            if w.getnchannels() < 1 or frames <= 0 or sample_rate <= 0:
                raise ValueError("no audio")
            duration = frames / sample_rate
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"not a valid wav file: {e}")

    # same file from the same origin again for this user -> reuse the stored voice
    content_hash = hashlib.sha256(data).hexdigest()
    existing_id = app.state.db.find_voice_by_hash(user_id, content_hash, predefined_id)
    if existing_id and (ChatDB.VOICES_DIR / f"{existing_id}.wav").exists():
        logger.debug(f"reusing voice {existing_id} for user {user_id} (same content hash)")
        return existing_id

    voice_id = app.state.db.add_voice(user_id, sample_rate, duration, content_hash=content_hash, predefined_id=predefined_id)
    if voice_id is None:
        raise HTTPException(status_code=500, detail="failed to store voice")

    path = ChatDB.VOICES_DIR / f"{voice_id}.wav"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except Exception as e:
        logger.error(f"failed writing voice file {path}: {e}")
        app.state.db.remove_voice(voice_id)
        raise HTTPException(status_code=500, detail="failed to store voice")

    logger.debug(f"stored voice {voice_id} for user {user_id} ({duration:.1f}s, {sample_rate} Hz)")
    return voice_id

def load_predefined_voices() -> list:
    """entries of voices.json, empty list if the folder is not mounted"""
    path = PREDEFINED_VOICES_DIR / "voices.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"no predefined voices ({path}): {e}")
        return []

@app.post("/voices")
async def upload_voice(request: Request, username: str = Depends(get_current_user)):
    """
    raw wav bytes in the request body (content-type audio/wav), no multipart.
    saves the file as /hub/voices/<uuid>.wav and returns the uuid. the voice is not linked to a contact yet
    """
    user_id = app.state.db.get_user_id(username)
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(data) > MAX_VOICE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="voice file too large")

    voice_id = store_voice(user_id, data)
    return {"status": "ok", "voice_id": voice_id}

def find_stored_predefined_voice(user_id: int, entry: dict) -> str:
    """uuid of the user's stored copy of a predefined voice, "" if not stored yet. uploads never match"""
    try:
        content_hash = hashlib.sha256((PREDEFINED_VOICES_DIR / entry["file"]).read_bytes()).hexdigest()
    except Exception:
        content_hash = ""
    return app.state.db.find_predefined_voice(user_id, entry["id"], content_hash) or ""

@app.get("/voices/predefined")
def get_predefined_voices(username: str = Depends(get_current_user)):
    # only what the client needs to show a selection, the id is the key.
    # voice_id lets the client map a contact's stored voice back to the predefined entry it came from
    user_id = app.state.db.get_user_id(username)
    voices = [
        {
            "id": v["id"], "name": v["name"], "description": v.get("description", ""), "gender": v.get("gender", ""), "language": v.get("language", ""),
            "voice_id": find_stored_predefined_voice(user_id, v),
        }
        for v in load_predefined_voices()
    ]
    return {"voices": voices}

@app.post("/voices/predefined/{predefined_id}")
def use_predefined_voice(predefined_id: str, username: str = Depends(get_current_user)):
    """
    copies a predefined voice into the user's voices, so it works like an uploaded one.
    returns the uuid of the stored voice, the same predefined voice always maps to the same uuid per user
    """
    user_id = app.state.db.get_user_id(username)
    entry = next((v for v in load_predefined_voices() if v["id"] == predefined_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="voice not found")

    path = PREDEFINED_VOICES_DIR / entry["file"]
    try:
        data = path.read_bytes()
    except Exception as e:
        logger.error(f"failed reading predefined voice {path}: {e}")
        raise HTTPException(status_code=500, detail="failed to read voice")

    voice_id = store_voice(user_id, data, predefined_id)
    return {"status": "ok", "voice_id": voice_id}

@app.delete("/voices/{voice_id}")
def delete_voice(voice_id: str, username: str = Depends(get_current_user)):
    # only the owner can remove a voice, an unknown or foreign id looks the same to the client
    user_id = app.state.db.get_user_id(username)
    if not app.state.db.remove_voice(voice_id, user_id):
        raise HTTPException(status_code=404, detail="voice not found")
    app.state.infrastructure.drop_voice(voice_id)
    return {"status": "ok", "voice_id": voice_id}

########### image generation info
@app.get("/images/{file_key}/generation")
def get_image_generation(file_key: str, username: str = Depends(get_current_user)):
    """everything that went into one image (prompts, seed, model, size, steps, cfg)"""
    user_id = app.state.db.get_user_id(username)
    if not app.state.db.owns_image(user_id, file_key):
        raise HTTPException(status_code=404, detail="no generation info for this image")
    generation = app.state.db.get_image_generation(file_key)
    if generation is None:
        raise HTTPException(status_code=404, detail="no generation info for this image")
    return {"file_key": file_key, "generation": generation}

########### model handling
@app.get("/models/{model_name}/url", response_model=GetModelURLResponse)
def get_model_url(model_name: str, username: str = Depends(get_current_user)):
    sources = app.state.infrastructure.get_model_url(model_name)
    return GetModelURLResponse(
        model_urls=sources
    )

########### downloads
@app.get("/downloads/{file_path:path}")
async def download_file(file_path: str):
    base_path = Path("/hub").resolve()
    path = (base_path / file_path).resolve()

    if not str(path).startswith(str(base_path)):
        logger.error(f"invalid path {path}")
        return {"error": "Invalid path"}

    if not os.path.exists(path) and path.parent == base_path / "images":
        await run_in_threadpool(app.state.image_store.ensure, path.name)

    if not os.path.exists(path):
        logger.error(f"file not found {path}")
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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, username: str = Depends(get_current_user_ws)):
    await websocket.accept()

    loop = asyncio.get_running_loop()
    done_queue = asyncio.Queue()
    closed = asyncio.Event()
    logger.debug(f"username: {username}")
    user_id = app.state.db.get_user_id(username)

    async def safe_close(code: int = 1000):
        if not closed.is_set():
            closed.set()
            try:
                await websocket.close(code=code)
            except RuntimeError:
                # already closed at ASGI level
                pass

    def pump_done_jobs():
        while True:
            job = app.state.job_queue.get_done()
            if closed.is_set():
                break
            loop.call_soon_threadsafe(done_queue.put_nowait, job)

    threading.Thread(target=pump_done_jobs, daemon=True).start()

    # recieve from client
    async def receiver():
        try:
            while not closed.is_set():
                text = await websocket.receive_text()
                data = json.loads(text)

                if "chat" in data:
                    chat_request = ChatRequest(**data["chat"])

                    if chat_request.content == "ping":
                        MessageQueue().send_data({ 
                            "chat": {
                                "conversation_id": chat_request.conversation_id,
                                "role": "assistant",
                                "content": "pong",
                                "tool_calls": [] 
                            }
                        })
                    else:
                        job = MetaJob(user_id, chat_request, app.state.db, app.state.infrastructure, app.state.tool_registry)
                        app.state.job_queue.add(job)
                elif "generate" in data:
                    generate = data["generate"]
                    if "generate_profile" in generate:
                        job = ContactGeneratorJob(generate["generate_profile"], user_id, app.state.db, app.state.infrastructure)
                        app.state.job_queue.add(job)
                    else:
                        logger.error(f"unknown generation request")
                        await websocket.send_text(
                            json.dumps({"status": "unknown generation request"})
                        )
                else:                    
                    logger.error(f"unknown request {data}")
                    await websocket.send_text(
                        json.dumps({"error": "unknown request"})
                    )

        except WebSocketDisconnect:
            print("Client disconnected (receiver)")
            await safe_close()

        except Exception as e:
            logger.error(f"receiver failure {repr(e)}")
            await safe_close(code=1011)

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
                    await asyncio.sleep(0.01)  # or use a proper event/queue

        except WebSocketDisconnect:
            print("Client disconnected (sender)")
            await safe_close()

        except Exception as e:
            logger.error(f"sender failure {repr(e)}")
            await safe_close(code=1011)

    # send back to client
    async def finish_job():
        while not closed.is_set():
            job = await done_queue.get()

            if closed.is_set():
                break

            if job.has_response():
                MessageQueue().send_data(job.result())

    receiver_task = asyncio.create_task(receiver())
    finish_job_task = asyncio.create_task(finish_job())
    sender_task = asyncio.create_task(sender())

    done, pending = await asyncio.wait(
        [receiver_task, sender_task, finish_job_task],
        return_when=asyncio.FIRST_EXCEPTION
    )

    await safe_close()

    for task in pending:
        task.cancel()

    await asyncio.gather(*pending, return_exceptions=True)        

SPEECH = 0.5
SILENCE_MS = 2000
PARTIAL_MS = 1000

def pcm16_to_float(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.int16).astype(np.float32) / 32768.0

@app.websocket("/ws/audio")
async def audio_endpoint(websocket: WebSocket, username: str = Depends(get_current_user_ws)):
    await websocket.accept()
    user_id = app.state.db.get_user_id(username)
    utterance = []
    voiced = False
    silence = 0
    spoken_ms = 0
    busy = False
    buf = bytearray()
    meta = {"sample_rate": 16000, "channels": 1, "encoding": "pcm_s16le"}
    frame = 512

    async def transcribe(wav, kind: str):
        nonlocal busy
        if kind == "partial" and busy:
            return
        busy = True
        try:
            pcm16 = (np.clip(wav, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            text = await asyncio.to_thread(app.state.infrastructure.stt, pcm16, kind)
            if text:
                await websocket.send_json({"type": kind, "text": text})
        finally:
            busy = False

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            if "text" in msg and msg["text"]:
                data = json.loads(msg["text"])
                if data.get("type") == "audio.start":
                    meta.update({k: data[k] for k in ("sample_rate", "channels", "encoding") if k in data})
                    await websocket.send_json({"type": "audio.ready"})
                elif data.get("type") == "audio.stop":
                    break
                continue

            chunk = msg.get("bytes")
            if not chunk:
                continue
            buf.extend(chunk)
            audio = pcm16_to_float(bytes(buf))

            while len(audio) >= frame:
                piece = audio[:frame]
                audio = audio[frame:]
                buf = bytearray(audio.astype(np.int16).tobytes())
                prob = app.state.vad(torch.from_numpy(piece), 16000).item()
                if prob >= SPEECH:
                    voiced = True
                    silence = 0
                    utterance.append(piece)
                    spoken_ms += frame / 16
                    if spoken_ms >= PARTIAL_MS:
                        spoken_ms = 0
                        wav = np.concatenate(utterance)
                        await transcribe(wav, "partial")
                elif voiced:
                    silence += frame / 16
                    utterance.append(piece)
                    if silence >= SILENCE_MS:
                        wav = np.concatenate(utterance)
                        await transcribe(wav, "final")
                        utterance = []
                        voiced = False
                        silence = 0
                        spoken_ms = 0

    except WebSocketDisconnect:
        pass