import requests

from app.common import Logger, ChatRequestLlama, ChatResponse
logger = Logger(__name__).get_logger()

class LLamaCppInterface:
    def __init__(self, host, port):
        self.url = f"http://{host}:{port}/v1/chat/completions"

        logger.debug(f"llama.cpp url: {self.url}")

    def chat(self, request: ChatRequestLlama) -> ChatResponse:
        payload_low_accuracy = {
            "messages": request.messages,
            "temperature": request.temperature,
            "top_p": 0.8,
            "top_k": 20,
            "min_p": 0.0,
            "do_sample": True,
            "repetition_penalty": 1.05,
            "no_repeat_ngram_size": 2,
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
            "typical_p": 1.0,
            "tfs_z": 1.0,

            # Disable complexity
            "mirostat": 0,

            # BIG speed gain here
            "max_new_tokens": 100,
            "max_tokens": 5000,

            "stop": [
                "<|start_header_id|>",
                "<|end_header_id|>",
                "<|im_end|>",
                "<|im_start|>",
                "assistant:",
                ". assistant",
                "\" assistant",
                "user:",
                ". user",
                "\" user",
                "\nuser",
                "\nassistant"
            ],

            "n_ctx": 2048,
            "rope_freq_base": 10000,
            "rope_freq_scale": 1.0,
            "n_batch": 128,

            "num_experts_per_token": 1,
            "stream": False
        }

        payload_high_accuracy = {
            "messages": request.messages,
            "temperature": request.temperature,
            "top_p": 0.9,
            "top_k": 50,
            "min_p": 0.1,
            "do_sample": True,
            "repetition_penalty": 1.15,
            "no_repeat_ngram_size": 4,
            "presence_penalty": 0.0,
            "frequency_penalty": 0.1,
            "typical_p": 0.9,
            "tfs_z": 1.0,

            # More stable decoding
            "mirostat": 0,

            "max_new_tokens": 300,
            "max_tokens": 5000,

            "stop": [
                "<|start_header_id|>",
                "<|end_header_id|>",
                "<|im_end|>",
                "<|im_start|>",
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

            "num_experts_per_token": 2,
            "stream": False
        }

        if request.low_accuracy:
            payload = payload_low_accuracy
        else:
            payload = payload_high_accuracy

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