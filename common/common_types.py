from pydantic import BaseModel

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
    attachments: list[str] = []

class ChatRequestLlama(BaseModel):
    messages: list[dict]
    temperature: float
    low_accuracy: bool
    seed: int

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
    conversation_id: int
    max_messages: int = 100

class GetAttachmentsRequest(BaseModel):
    message_id: int    