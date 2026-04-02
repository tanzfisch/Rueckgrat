from requests.models import Response
import json
from pathlib import Path
import requests
from typing import Optional
from dataclasses import dataclass

INFRASTRUCTURE_CONFIG_PATH = Path("/hub/config/infrastructure.json")

def make_error_response(message: str, status_code: int = 500, content_type: str = "application/json") -> Response:
    response = Response()
    response.status_code = status_code

    # Support JSON-style error payloads
    if content_type == "application/json":
        response._content = json.dumps({
            "error": message
        }).encode("utf-8")
    else:
        response._content = message.encode("utf-8")

    response.headers["Content-Type"] = content_type
    return response

@dataclass
class ServerResult:
    url: str
    ok: bool
    error: Optional[str] = None

@dataclass
class StatusResult:
    def __init__(self, servers: list[ServerResult] = None):
        self.servers = servers if servers else []

    servers : list[ServerResult]

class Infrastructure:
    def __init__(self):
        if not INFRASTRUCTURE_CONFIG_PATH.exists():
            print(f"Error: no infrastructure config found at {INFRASTRUCTURE_CONFIG_PATH}")
            return

        with open(INFRASTRUCTURE_CONFIG_PATH, "r") as f:
            data = json.load(f)

        self.servers = data["servers"]

        self.chat_server = None

        for server in self.servers:
            if "services" in server:
                services = server["services"]
                for service in services:
                    if service["type"] == "llm":
                        self.chat_server = server
                        break
            if self.chat_server:
                break

        if not self.chat_server:
            print("Error: couldn't find chat server in config")

    def get_status(self) -> StatusResult:
        result = StatusResult()

        for server in self.servers:             
            url = f"http://{server['host']}:{server['port']}/health"

            try:
                response = requests.get(url, timeout=3)

                ok = response.status_code == 200 \
                and response.json() == {"status": "ok"} \
                and response.headers.get("content-type", "").startswith("application/json")

                if ok:
                    result.servers.append(ServerResult(url, ok))
                else:
                    result.servers.append(ServerResult(url, ok, error=response["status"]))
                                
            except Exception as e:
                result.servers.append(ServerResult(url, False, error=repr(e)))

        return result
            
    def chat(self, messages, temperature: float, low_accuracy: bool = False) -> Response:
        url = f"http://{self.chat_server['host']}:{self.chat_server['port']}/chat"
        
        payload={
            "messages": messages,
            "temperature": temperature,
            "low_accuracy": low_accuracy
        }

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=20,
            )
            return response
        
        except Exception as e:
            print(f"Error: failed to get a chat response {repr(e)}")

        return None

    def get_model_url(self, model_name) -> Response:
        url = f"http://{self.chat_server['host']}:{self.chat_server['port']}/model"
        
        try:
            response = requests.get(
                url,
                json={"model_name": model_name},
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                return data.get("model_urls", [])

            print(f"Error: failed to get_model_url response {response.status_code} {response.reason}")
            return []

        except Exception as e:
            print(f"Error: failed to get_model_url response {repr(e)}")

        return []