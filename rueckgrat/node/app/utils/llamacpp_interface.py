from app.utils import ChatRequest, ChatResponse
import requests

import logging
logger = logging.getLogger(__name__)

class LLamaCppInterface:
    def __init__(self, host, port):
        self.url = f"http://{host}:{port}/v1/chat/completions"

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = {
            "messages": request.messages,
            "temperature": request.temperature,
            "top_p": 0.95,
            "top_k": 40,
            "min_p": 0.05,
            "repetition_penalty": 1.2,
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
            "typical_p": 1.0,
            "tfs_z": 1.0,

            "mirostat": 0,
            "mirostat_tau": 5.0,
            "mirostat_eta": 0.1,

            "max_tokens": 5000,
            "stop": [
                "<|start_header_id|>",
                "<|end_header_id|>",
                "<|im_end|>",
                "assistant:",
                ". assistant",
                "\" assistant",
                "user:",
                ". user",
                "\" user",
                "\nuser",
                "\nassistant"
            ],

            "n_ctx": 8192,
            "rope_freq_base": 10000,
            "rope_freq_scale": 1.0,

            "n_batch": 512,
            "n_threads": 8,

            "num_experts_per_token": 2,
            "stream": False
        }

        headers = {
            "Content-Type": "application/json"
        }   

        try:
            response = requests.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=30
            )

            response.raise_for_status()    

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                return ChatResponse(
                    role="assistant",
                    content=content
                )

            return ChatResponse(
                role="error",
                content=f"Error: llama.cpp failed to respond ({response.status_code} {response.reason})"
            )

        except requests.exceptions.RequestException as e:
            return ChatResponse(
                role="error",
                content=f"Error: llama.cpp failed to respond - {e}"
            )