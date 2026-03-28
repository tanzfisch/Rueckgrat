from pydantic import BaseModel

class ChatRequest(BaseModel):
    messages: list[dict]
    temperature: float

class ChatResponse(BaseModel):
    role: str
    content: str

class ImageRequest(BaseModel):
    positive_prompt: str
    negative_prompt: str = "low quality, artifacts, missing limbs, bad hands"
    seed: int = 1337
    width: int = 256
    height: int = 256
    steps: int = 10
    cfg: float = 7.5
    model: str

class ImageResponse(BaseModel):
    output_url: str