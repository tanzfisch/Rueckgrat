from pydantic import BaseModel, Field, model_serializer
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

class ChatRequestLlama(BaseModel):
    messages: list[dict]
    temperature: float
    seed: int
    max_new_tokens: int
    context_size: int
    stream: bool = False
    conversation_id: int = -1
    stream_id: str | None = None

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
    # face reference (FaceID): file key of the contact's current profile image on the hub, "" = none.
    # only dumped/hashed when set, so requests without a reference keep their old dump and hash
    reference_image_key: str = ""
    # the image bytes of reference_image_key (base64), attached by the hub right before it posts the request
    # to the node. never part of model_dump(), so never hashed or stored with the generation
    reference_image_b64: str = Field(default="", exclude=True)

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

class HubTTSRequest(BaseModel):
    text: str
    voice: str = ""