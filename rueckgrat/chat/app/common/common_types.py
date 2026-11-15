from pydantic import BaseModel, Field, model_serializer
from typing import List, Optional

class ChatRequest(BaseModel):
    contact_id: int
    conversation_id: int
    role: str
    name: str
    content: str
    temperature: float
    poll_answer: Optional[dict] = None   # {"message_id", "chosen": [options]}: the content answers that message's poll

class ChatResponse(BaseModel):
    role: str
    content: str
    think: str = ""
    finish_reason: str = ""     # llama.cpp's: "stop", "length" (max_tokens reached, cut off); "" when unknown
    prompt_tokens: int = 0      # the llm's token counts of the call, 0 when unknown
    completion_tokens: int = 0

class ChatRequestLlama(BaseModel):
    messages: list[dict]
    temperature: float
    seed: int
    max_new_tokens: int
    context_size: int
    stream: bool = False
    conversation_id: int = -1
    stream_id: str | None = None
    timeout: float | None = None     # seconds the node waits for llama.cpp, None = its default (240)
    json_schema: dict | None = None  # the reply must be json matching this schema (llama.cpp grammar), None = free text

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
    reference_image_key: str = ""                               # face reference (FaceID): file key of the current profile image on the hub (contact or user)
    reference_image_b64: str = Field(default="", exclude=True)  # the image bytes of reference_image_key (base64)

    @model_serializer(mode="wrap")
    def _drop_empty_reference(self, handler):
        data = handler(self)
        if isinstance(data, dict) and not self.reference_image_key:
            data.pop("reference_image_key", None)
        return data

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

class GetModelURLResponse(BaseModel):
    model_urls: list[str]

class GetModelResponse(BaseModel):
    name: str
    type: Optional[str] = None
    description: str = ""
    comment: str = ""
    compatibility: Optional[dict | list | str] = None
    install_path: str = ""
    files: list[dict] = []
    installed: bool = False
    size_bytes: int = 0

class RegisteredModel(BaseModel):
    name: str
    type: Optional[str] = None

class GetRegisteredModelsResponse(BaseModel):
    models: list[RegisteredModel]    

class NodeTTSRequest(BaseModel):
    text: str
    voice: str = ""
    exaggeration: float = 0.5
    cfg_weight: float = 0.5
    language: str = ""  # multilingual model only, "" or unsupported = detected from the text

class HubTTSRequest(BaseModel):
    text: str
    voice: str = ""