
import uvicorn
import json
import random
import asyncio
import threading
import os
from tqdm import tqdm
from pathlib import Path
import time

from fastapi.responses import StreamingResponse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.security import HTTPBearer

from pydantic import BaseModel
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from app.utils import ChatDB, Infrastructure, ImageType
from app.tools import ToolRegistry
from app.jobs import JobQueue, MetaJob, AssistantImageJob, ContactGeneratorJob
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from jose import jwt
from datetime import datetime, timedelta, timezone

from app.common import get_logger, ChatRequest, GetMessagesRequest, MessageQueue
logger = get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    random.seed(time.time())
        
    app.state.infrastructure = Infrastructure()
    await app.state.infrastructure.connect_nodes()

    db_path = "/hub/db/chat.db"
    app.state.db = ChatDB(db_path)
    app.state.job_queue = JobQueue()

    app.state.tool_registry = ToolRegistry(
        infrastructure=app.state.infrastructure,
        db=app.state.db,
        job_queue=app.state.job_queue
    )

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

    return {
        "access_token": token,
        "user_id": user["id"]
    }

########### system handling
@app.get("/health")
def health():
    status = app.state.infrastructure.get_status()
    for node in status.nodes:
        if not node.ok:
            return {"status": "error", "message": f"{node.url} {node.error}"}

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

@app.get("/contact/{contact_id}")
def get_contact(contact_id: int, username: str = Depends(get_current_user)):
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
def delete_conversation(contact_id: int, username: str = Depends(get_current_user)):
    if app.state.db.delete_contact(contact_id):
        return {"status": "ok"}
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
    conversation = app.state.db.get_conversation(conversation_id)
    return {"conversation": conversation}

class CreateConversationRequest(BaseModel):
    contact_id: int

@app.post("/conversations")
def create_conversation(request: CreateConversationRequest, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    conversation_id = app.state.db.create_conversation(user_id, request.contact_id)
    return {"conversation_id": conversation_id}

@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, username: str = Depends(get_current_user)):
    if app.state.db.delete_conversation(conversation_id):
        return {"status": "ok"}
    else:
        return {"status": "failed to delete conversation"}

@app.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: int, request: GetMessagesRequest, username: str = Depends(get_current_user)):
    messages = app.state.db.get_messages_by_conversation(conversation_id, request.max_messages)
    return {"messages": messages}

@app.get("/messages/{message_id}/attachments")
def get_messages(message_id: int, username: str = Depends(get_current_user)):
    attachments = app.state.db.get_attachments_for_message(message_id)
    return {"attachments": attachments}

########### model handling
class GetModelURLResponse(BaseModel):
    model_urls: list[str]

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
