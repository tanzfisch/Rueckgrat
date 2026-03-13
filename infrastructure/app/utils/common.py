from pydantic import BaseModel

class ChatRequest(BaseModel):
    messages: list[dict]

class ChatResponse(BaseModel):
    role: str
    content: str