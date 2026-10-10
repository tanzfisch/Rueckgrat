import requests
import re
import json

from app.common import get_logger, ChatRequestLlama, ChatResponse
logger = get_logger()

class LLamaCppInterface:
    def __init__(self, host: str, port: int):
        self.url = f"http://{host}:{port}/v1/chat/completions"

        logger.info(f"startup llama interface")
        logger.info(f"llama.cpp url: {self.url}")

    def extract_think_and_response(self, content):
        match = re.search(r'<think>(.*?)</think>', content, re.DOTALL)
        think = match.group(1).strip() if match else ''
        response = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        return think, response

    def _split(self, content: str, reasoning: str):
        # reasoning_content (native reasoning) plus inline <think> tags as fallback
        think, resp = self.extract_think_and_response(content or "")
        think = "\n".join(x for x in ((reasoning or "").strip(), think) if x)
        return think, resp

    def _normalize_messages(self, messages: list) -> list:
        system, rest = [], []
        for m in messages:
            if m.get("role") in ("system", "developer"):
                system.append(m["content"])
            else:
                rest.append(m)
        return ([{"role": "system", "content": "\n\n".join(system)}] if system else []) + rest

    def _build_payload(self, request: ChatRequestLlama) -> dict:
        # sampling settings (top_k, top_p, min_p, repeat_penalty, ...) come from the
        # server's extra_args so they can be configured per model in registry.json
        return {
            "messages": self._normalize_messages(request.messages),
            "temperature": request.temperature,
            "seed": request.seed,
            "max_tokens": request.max_new_tokens,
            "stream": request.stream
        }

    def _check_finish_reason(self, finish_reason):
        if finish_reason == "length":
            logger.warning("llama.cpp stopped because max_tokens was reached; response may be truncated")

    def chat(self, request: ChatRequestLlama, callback=None) -> ChatResponse:
        payload = self._build_payload(request)
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
                full_reasoning = ""
                with requests.post(self.url, json=payload, headers=headers, stream=True, timeout=240) as http_response:
                    http_response.raise_for_status()
                    for line in http_response.iter_lines():
                        if not line:
                            continue
                        line = line.decode('utf-8')
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        data = json.loads(data_str)
                        choices = data.get("choices")
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})

                        reasoning = delta.get("reasoning_content")
                        if reasoning:
                            full_reasoning += reasoning

                        content = delta.get("content")
                        if content:
                            full_content += content
                            callback(json.dumps({
                                "conversation_id": request.conversation_id,
                                "delta": content
                            }))

                        finish_reason = choices[0].get("finish_reason")
                        if finish_reason:
                            self._check_finish_reason(finish_reason)
                            break

                think, resp = self._split(full_content, full_reasoning)
                callback(json.dumps({
                    "conversation_id": request.conversation_id,
                    "response": resp,
                    "thinking": think
                }))
                return ChatResponse(role="assistant", content=resp, think=think)

            else:
                http_response = requests.post(
                    self.url,
                    json=payload,
                    headers=headers,
                    timeout=240
                )
                http_response.raise_for_status()

                choice = http_response.json()["choices"][0]
                self._check_finish_reason(choice.get("finish_reason"))
                message = choice["message"]
                think, resp = self._split(message.get("content"), message.get("reasoning_content"))
                return ChatResponse(role="assistant", content=resp, think=think)

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            return ChatResponse(role="error", content=f"Request failed: {str(e)}")
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"Invalid response: {str(e)}")
            return ChatResponse(role="error", content=f"Invalid response: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return ChatResponse(role="error", content=f"Unexpected error: {str(e)}")
