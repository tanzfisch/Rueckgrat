from pydantic import BaseModel
from typing import List, Optional

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
    think: str = ""
    attachments: list[str] = []

class ChatRequestLlama(BaseModel):
    messages: list[dict]
    temperature: float
    seed: int
    max_new_tokens: int
    context_size: int

class ImageRequest(BaseModel):
    positive_prompt: str
    negative_prompt: str = "low quality, artifacts, missing limbs, bad hands"
    seed: int = 1337
    width: int = 256
    height: int = 256
    steps: int = 10
    cfg: float = 7.5
    model: str
    output: str

class ImageResponse(BaseModel):
    output: str

class GetMessagesRequest(BaseModel):
    max_messages: int = 100

class ModelInfo(BaseModel):
    name: str
    type: str
    installed: bool
    size_gb: Optional[float] = None
    description: Optional[str] = None

class GetModelsResponse(BaseModel):
    models: List[ModelInfo]

class InstallModelRequest(BaseModel):
    name: str
    source: Optional[str] = None
    force: bool = False

class InstallModelResponse(BaseModel):
    name: str
    size_gb: Optional[float] = None