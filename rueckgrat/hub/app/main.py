import json
import random
import sys
import re

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

import logging
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.DEBUG)

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

class UpdateConversationRequest(BaseModel):
    conversation_id: int
    brief: str
    context: str

@app.get("/update_conversation")
def update_conversation(request: UpdateConversationRequest, username: str = Depends(get_current_user)):
    if app.state.db.update_conversation(request.conversation_id, request.brief, request.context):
        return {"status": "ok"}
    else:
        return {"status": "operation failed"}

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

def update_context(context, messages: list):
    messages_block = "\n".join([
        f'- "{m["content"]}" (role: {m["role"]})'
        for m in messages
    ])

    query = f"""
    You maintain a SHORT running context for a conversation.

    NEW MESSAGES:
    {messages_block}

    CURRENT CONTEXT:
    {{
        "location": "{context['location']}",
        "user": "{context['user']}",
        "assistant": "{context['assistant']}",
        "topic": "{context['topic']}"
    }}

    INSTRUCTIONS:
    - Process messages in order (top = oldest, bottom = newest)
    - Update information if possible and overwrite if necessary
    - Ammend if information is important
    - Keep ALL fields SHORT (max 40 words each)
    - Keep only the MOST IMPORTANT and RECENT info
    - DROP anything irrelevant or outdated
    - "topic" = 1 short phrase
    - "user"/"assistant" = intent or role summary, also body position or movement, NOT dialogue
    - "location" = only if explicitly mentioned

    OUTPUT:
    Return ONLY valid JSON in the same format.
    """
    payload = [{"role": "user", 
                "content": query}]
    response = app.state.infrastructure.chat(payload, 0.0, True)

    if response.status_code == 200:
        data = response.json()
        try:
            content = data.get("content", "")
            match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if not match:
                return context
            
            reply = json.loads(match.group(1))

            new_context = {
                "location": reply["location"],
                "user": reply["user"],
                "assistant": reply["assistant"],
                "topic": reply["topic"]
            }            
        except Exception as e:
            logger.error(f"failed to update context: {e}")
            return context   

        return new_context

    else:
        data = response.json()
        error = data.get("error", "")        
        logger.error(f"failed to update context with: {error}")
        return context

def update_conversation(conversation_id: int):
    logger.debug(f"update_conversation {conversation_id}")

    # TODO update brief and title
    conversation = app.state.db.get_conversation(conversation_id)
    context = conversation["context"]
    
    messages = app.state.db.get_messages_by_conversation(conversation_id, 4)
    context = update_context(context, messages)

    conversation["title"] = context["topic"]

    logger.debug(f"updated context {context}")

    app.state.db.update_conversation(conversation_id, conversation["title"], conversation["brief"], json.dumps(context))

def create_mood_image_prompt(contact, conversation):
    context = conversation["context"]

    profile = contact["profile"]
    image_parameters = profile["image_parameters"]

    person_a = f"Person A: {image_parameters}, {context['assistant']}"
    person_b = f"Person B: {context['user']}" # TODO add description of user
    person_b = ""
    location = context["location"]

    query = f"""
    Create a detailed, vivid image prompt for an AI image generator based on:

    Location: {location}
    {person_a}
    {person_b}

    Flesh out the description richly with visual details, lighting, mood, composition, style, and specifics so it works well for image generators. Make it cohesive and immersive.
    Output a single, ready-to-use image prompt.
    Output only the generated prompt and nothing else.
    """
    payload = [{"role": "user", 
                "content": query}]
    response = app.state.infrastructure.chat(payload, 0.5)

    if response.status_code == 200:
        data = response.json()
        try:
            content = data.get("content", "")
            return content
        except Exception as e:
            logger.error(f"failed to update context: {e}")

        return ""

    else:
        data = response.json()
        error = data.get("error", "")        
        logger.error(f"failed to generate image prompt: {error}")
        return ""

def handle_chat_request(request: ChatRequest):
    logger.debug(f"handle_chat_request {request}")
    app.state.db.add_message(request.conversation_id, request.role, request.content, request.name)
    
    update_conversation(request.conversation_id)

    conversation = app.state.db.get_conversation(request.conversation_id)
    contact = app.state.db.get_contact_by_id(request.contact_id)

    #image = create_mood_image_prompt(contact, conversation)
    #logger.debug(f"image prompt: {image}")

    compiler = PromptCompiler(contact, conversation, request.name)
    system_prompt = compiler.build_system_prompt()    

    #logger.debug(f"\nsystem_prompt {system_prompt}")

    payload = [{"role": "system", "content": system_prompt}]
    
    messages = app.state.db.get_messages_by_conversation(request.conversation_id, 20)
    for message in messages:
        content = message['content']
        payload.append({"role": message["role"], "content": content})

    size_in_bytes = sys.getsizeof(messages)
    estimated_tokens = size_in_bytes / 4 * 1.25
    logger.debug(f"request from {request.name} estimated token size: {estimated_tokens / 1000}k")

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
        logger.info("Client disconnected")

    except Exception as e:
        logger.error(f"websocket endpoint failure {repr(e)}")
        await websocket.close(code=1011)