import json
import random
import asyncio
import threading
import os
from tqdm import tqdm
from fastapi.responses import StreamingResponse
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from app.utils import ChatDB, Infrastructure, ContactImagePromptCompiler, ImageType
from app.jobs import JobQueue, MetaJob, ImageJob
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from jose import jwt
from datetime import datetime, timedelta, timezone

from app.common import Logger, ChatRequest, Utils, GetMessagesRequest, GetAttachmentsRequest, ImageRequest
logger = Logger(__name__).get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.dev_mode = os.getenv("DEV_MODE", "prod")
    logger.info(f"running DEV_MODE={app.state.dev_mode}")

    app.state.infrastructure = Infrastructure()
    db_path = "/hub/db/chat.db"
    app.state.db = ChatDB(db_path)    
    app.state.job_queue = JobQueue()

    logger.info("hub initialized")

    yield

    app.state.job_queue.stop()

    logger.info("hub shut down")


app = FastAPI(lifespan=lifespan)
security = HTTPBearer()

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
    token = credentials.credentials    
    return decode_token(token)

@app.get("/users")
def get_users():
    users = app.state.db.get_users()
    return {"users": users}

class UserCreate(BaseModel):
    user_name: str
    user_passwd: str

@app.post("/users")
def create_user(user: UserCreate):
    user_id = app.state.db.create_user(user.user_name, hash_password(user.user_passwd))
    return {"user_id": user_id}

class LoginRequest(BaseModel):
    user_name: str
    user_passwd: str

@app.post("/login")
def login(data: LoginRequest):
    user = app.state.db.get_user(data.user_name)

    if not user:
        raise HTTPException(status_code=401)

    if data.user_passwd and not verify_password(data.user_passwd, user["password"]):
        raise HTTPException(status_code=401)

    token = create_access_token(user["username"])

    return {"access_token": token}

########### system handling
@app.get("/")
def default():
    return {"status": "ok"}

@app.get("/health")
def health():
    status = app.state.infrastructure.get_status()
    for server in status.servers:
        if not server.ok:
            return {"status": "error", "message": f"{server.url} {server.error}"}

    return {"status": "ok"}

########### contact handling
@app.get("/contacts")
def get_contacts(username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    contacts = app.state.db.get_contacts(user_id)

    for contact in contacts:
        images = app.state.db.get_contact_images(contact["id"])
        contact["images"] = images

    return {"contacts": contacts}

class ContactRequest(BaseModel):
    contact_id: int

@app.get("/contact")
def get_contact(request: ContactRequest, username: str = Depends(get_current_user)):
    contact = app.state.db.get_contact_by_id(request.contact_id)

    images = app.state.db.get_contact_images(contact["id"])
    contact["images"] = images

    return {"contact": contact}    

@app.post("/contact")
def create_contact(username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    contact_name = f"new_contact_{random.randint(0,100000)}"
    contact_id = app.state.db.create_contact(user_id, contact_name)
    return {"contact_id": contact_id}

class UpdateContactRequest(BaseModel):
    contact_id: int
    contact_data: dict

@app.post("/update_contact")
def update_contact(request: UpdateContactRequest, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    app.state.db.update_contact(user_id, request.contact_id, request.contact_data)
    contact_data = app.state.db.get_contact_by_id(request.contact_id)
    image_parameters = contact_data["profile"]["image_parameters"]

    compiler = ContactImagePromptCompiler(contact_data, None, ImageType.UpperBody, False, "natural smile, looking at camera")
    positive_prompt, negative_prompt = compiler.build()

    # generate profile image
    image_request = ImageRequest(
        positive_prompt = positive_prompt,
        negative_prompt = negative_prompt,
        seed = image_parameters.get("seed", 1337),
        width = 600,
        height = 600,
        steps = image_parameters.get("steps", 40.0),
        cfg = image_parameters.get("cfg", 8.0),
        model = image_parameters.get("model", "default"),
        output = ""
    )
    
    image_gen_hash = Utils.hash_image_request(image_request)
    output_file = f"{image_gen_hash}.png"
    app.state.db.add_contact_image(request.contact_id, output_file, "profile")
    image_request.output = output_file

    job = ImageJob(image_request, app.state.infrastructure)
    app.state.job_queue.add(job)

    return {"status": "ok"}

class DeleteContactRequest(BaseModel):
    contact_id: int

@app.post("/delete_contact")
def delete_conversation(request: DeleteContactRequest, username: str = Depends(get_current_user)):
    if app.state.db.delete_contact(request.contact_id):
        return {"status": "ok"}
    else:
        return {"status": "failed to delete contact"}

########### conversations handling
class ConversationsRequest(BaseModel):
    contact_id: int

@app.get("/conversations")
def get_conversations(request: ConversationsRequest, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    conversations = app.state.db.get_conversations(user_id, request.contact_id)
    return {"conversations": conversations}

class ConversationRequest(BaseModel):
    conversation_id: int

@app.get("/get_conversation")
def get_conversation(request: ConversationRequest, username: str = Depends(get_current_user)):
    conversation = app.state.db.get_conversation(request.conversation_id)
    return {"conversation": conversation}

class CreateConversationRequest(BaseModel):
    contact_id: int

@app.post("/conversations")
def create_conversation(request: CreateConversationRequest, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    conversation_id = app.state.db.create_conversation(user_id, request.contact_id)
    return {"conversation_id": conversation_id}

class DeleteConversationRequest(BaseModel):
    conversation_id: int

@app.post("/delete_conversation")
def delete_conversation(request: DeleteConversationRequest, username: str = Depends(get_current_user)):
    if app.state.db.delete_conversation(request.conversation_id):
        return {"status": "ok"}
    else:
        return {"status": "failed to delete conversation"}

########### messages handling
@app.get("/messages")
def get_messages(request: GetMessagesRequest, username: str = Depends(get_current_user)):
    messages = app.state.db.get_messages_by_conversation(request.conversation_id, request.max_messages)
    return {"messages": messages}

@app.get("/attachments")
def get_messages(request: GetAttachmentsRequest, username: str = Depends(get_current_user)):
    attachments = app.state.db.get_attachments_for_message(request.message_id)
    return {"attachments": attachments}

########### model handling
class GetModelURLRequest(BaseModel):
    model_name: str

class GetModelURLResponse(BaseModel):
    model_urls: list[str]

@app.get("/model", response_model=GetModelURLResponse)
def get_model_url(request: GetModelURLRequest, username: str = Depends(get_current_user)):
    sources = app.state.infrastructure.get_model_url(request.model_name)
    return GetModelURLResponse(
        model_urls=sources
    )

########### downloads
@app.get("/download/{file_path:path}")
async def download_file(file_path: str):
    base_path = Path("/hub").resolve()
    path = (base_path / file_path).resolve()

    if not str(path).startswith(str(base_path)):
        logger.error(f"invalid path {path}")
        return {"error": "Invalid path"}

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

########### websocket handling 
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    loop = asyncio.get_running_loop()
    done_queue = asyncio.Queue()
    closed = asyncio.Event()

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

    async def receiver():
        try:
            while not closed.is_set():
                text = await websocket.receive_text()
                data = json.loads(text)                

                if "chat" in data:
                    chat_request = ChatRequest(**data["chat"])
                    job = MetaJob(chat_request, app.state.db, app.state.infrastructure)
                    app.state.job_queue.add(job)
                else:
                    await websocket.send_text(
                        json.dumps({"status": "unknown request"})
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
                job = await done_queue.get()

                if closed.is_set():
                    break

                try:
                    if job.has_response():
                        await websocket.send_text(json.dumps(job.result()))
                except RuntimeError:
                    # happens if socket already closed underneath
                    break

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