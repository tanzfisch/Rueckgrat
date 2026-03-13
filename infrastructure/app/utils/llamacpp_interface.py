from app.utils import ChatRequest, ChatResponse
import requests

class LLamaCppInterface:
    def __init__(self, host, port):
        self.url = f"http://{host}:{port}/v1/chat/completions"

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = {
            "messages": request.messages,
            "temperature": 0.7,
            "max_tokens": 180,
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
                content="Error: llama.cpp failed to respond"
            )

        except requests.exceptions.RequestException as e:
            return ChatResponse(
                role="error",
                content="Error: llama.cpp failed to respond"
            )