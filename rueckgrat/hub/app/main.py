import json
import random
import sys

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.security import HTTPBearer

from pydantic import BaseModel
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from app.utils import ChatDB, Infrastructure, PromptCompiler
from pathlib import Path
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from jose import jwt
from datetime import datetime, timedelta, timezone
import copy


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.infrastructure = Infrastructure()
    db_path = "/data/chat.db"
    app.state.db = ChatDB(db_path)

    print("Backend initialized")

    yield

    print("Backend shut down")

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

########### chat handling
class ChatRequest(BaseModel):
    contact_id: int
    conversation_id: int
    role: str
    name: str
    content: str
    temperature: float

class ChatResponse(BaseModel):
    role: str
    content: str

def crate_system_prompt(contact, user_name):
    data = copy.deepcopy(contact)
    data.pop("profile")
    data["profile"] = json.loads(contact["profile"])

    compiler = PromptCompiler(data, user_name)
    result = compiler.build()

    return result

########### system handling
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
    return {"contacts": contacts}

class ContactRequest(BaseModel):
    contact_id: int

@app.get("/contact")
def get_contact(request: ContactRequest, username: str = Depends(get_current_user)):
    contact = app.state.db.get_contact_by_id(request.contact_id)
    return {"contact": contact}    

@app.post("/contact")
def create_contact(username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    contact_name = f"new_contact_{random.randint(0,10000)}"
    contact_id = app.state.db.create_empty_contact(user_id, contact_name)
    return {"contact_id": contact_id}

class UpdateContactRequest(BaseModel):
    contact_id: int
    contact_data: dict

@app.post("/update_contact")
def create_contact(request: UpdateContactRequest, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    app.state.db.update_contact(user_id, request.contact_id, request.contact_data)
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
def get_conversations(conversations: ConversationsRequest, username: str = Depends(get_current_user)):
    user_id = app.state.db.get_user_id(username)
    conversations = app.state.db.get_conversations(user_id, conversations.contact_id)
    return {"conversations": conversations}

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
class GetMessagesRequest(BaseModel):
    conversation_id: int

@app.get("/messages")
def get_messages(request: GetMessagesRequest, username: str = Depends(get_current_user)):
    messages = app.state.db.get_messages_by_conversation(request.conversation_id, 100)
    return {"messages": messages}

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

########### websocket handling 
def cleanup_reply(reply: str, name: str):
    prefix = f"{name}: "
    if reply.startswith(prefix):
        return reply.removeprefix(prefix)
    
    return reply

def handle_chat_request(request: ChatRequest):
    contact = app.state.db.get_contact_by_id(request.contact_id)
    system_prompt = crate_system_prompt(contact, request.name)
    payload = [{"role": "system", "content": system_prompt}]

    app.state.db.add_message(request.conversation_id, request.role, request.content, request.name)
    messages = app.state.db.get_messages_by_conversation(request.conversation_id, 30)
    for message in messages:
        content = message['content']
        payload.append({"role": message["role"], "content": content})

    size_in_bytes = sys.getsizeof(messages)
    print(f"request from {request.name} of size: {size_in_bytes / 1000}k")

    response = app.state.infrastructure.chat(payload, request.temperature)
    if response.status_code == 200:
        data = response.json()
        reply = cleanup_reply(data.get("content", ""), contact["name"])
        app.state.db.add_message(request.conversation_id, "assistant", reply, contact["name"])

        return ChatResponse(
            role="assistant",
            content=reply
        )
    
    else:
        data = response.json()
        error = data.get("error", "")
        return ChatResponse(
            role="error",
            content=error
        )   

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            text = await websocket.receive_text()
            data = json.loads(text)

            #TODO check if this is a tool request

            if "chat" in data:
                response = handle_chat_request(ChatRequest(**data["chat"]))
                response = {"chat": response.model_dump()}
                await websocket.send_text(json.dumps(response))
            else:
                response = json({"status" : "unknown request"})
                await websocket.send_text(json.dumps(response))

    except WebSocketDisconnect:
        print("Client disconnected")

    except Exception as e:
        print(f"Error: websocket endpoint {repr(e)}")
        await websocket.close(code=1011)