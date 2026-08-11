import requests
import re
import json

from app.common import get_logger, ChatRequestLlama, ChatResponse
logger = get_logger()

class LLamaCppInterface:
    def __init__(self, host: str, port: int):
        self.url = f"http://{host}:{port}/v1/chat/completions"

        logger.debug(f"llama.cpp url: {self.url}")

    def extract_think_and_response(self, content):
        match = re.search(r'<think>(.*?)</think>', content, re.DOTALL)
        think = match.group(1).strip() if match else ''
        response = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        return think, response

    def chat(self, request: ChatRequestLlama, callback=None) -> ChatResponse:
        payload = {
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

            "max_new_tokens": request.max_new_tokens,
            "max_tokens": request.context_size,

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

            "n_ctx": request.context_size,
            "rope_freq_base": 10000,
            "rope_freq_scale": 1.0,

            "n_batch": 512,

            "num_experts_per_token": 2,
            "stream": request.stream
        }

        headers = {
            "Content-Type": "application/json"
        }   
        try:
            if request.stream:
                logger.info("using stream")
                if not callback:
                    logger.error("need callback to run as stream")
                    return ChatResponse(role="error", content="No callback")

                full_content = ""
                with requests.post(self.url, json=payload, headers=headers, stream=True, timeout=240) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line:
                            line = line.decode('utf-8')
                            if line.startswith("data: "):
                                data = json.loads(line[6:])
                                if data.get("choices"):
                                    delta = data["choices"][0]["delta"].get("content", "")
                                    if delta:
                                        full_content += delta
                                        response = {
                                            "conversation_id": request.conversation_id,
                                            "delta": delta
                                        }
                                        callback(json.dumps(response))
                                    if data.get("choices", [{}])[0].get("finish_reason"):
                                        break
               
                think, resp = self.extract_think_and_response(full_content)
                response = {
                    "conversation_id": request.conversation_id,               
                    "response": resp,
                    "thinking": think
                }
                callback(json.dumps(response))
                return ChatResponse(role="assistant", content=resp, think=think)
            
            else:
                response = requests.post(
                    self.url,
                    json=payload,
                    headers=headers,
                    timeout=240
                )

                response.raise_for_status()

                if response.status_code == 200:
                    content = response.json()["choices"][0]["message"]["content"]
                    think, response = self.extract_think_and_response(content)
                    return ChatResponse(role = "assistant", content = response, think = think)

                return ChatResponse(role="error", content=f"llama.cpp error: {response.status_code} {response.reason}")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            return ChatResponse(role="error", content=f"Request failed: {str(e)}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"Invalid response: {str(e)}")
            return ChatResponse(role="error", content=f"Invalid response: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return ChatResponse(role="error", content=f"Unexpected error: {str(e)}")