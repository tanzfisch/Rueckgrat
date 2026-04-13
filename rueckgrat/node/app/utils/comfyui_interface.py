import websocket
import json
import urllib.request
import os
from PIL import Image
import io
from pathlib import Path
import threading

from app.common import Logger, ImageRequest, ImageResponse
logger = Logger(__name__).get_logger()

INFRASTRUCTURE_CONFIG_PATH = Path("node/config/infrastructure.json")

base_text_to_image = """
{
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "cfg": 7.75,
            "denoise": 1.0,
            "latent_image": ["5",0],
            "model": ["4",0],
            "negative": ["7",0],
            "positive": ["6",0],
            "sampler_name": "dpmpp_3m_sde",
            "scheduler": "sgm_uniform",
            "seed": 8566257,
            "steps": 40
        }
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {
            "ckpt_name": "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors"
        }
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "batch_size": 1,
            "height": 1280,
            "width": 720
        }
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "clip": ["4",1],
            "text": "masterpiece, best quality, highly detailed, beautiful girl, sharp focus, cinematic lighting"
        }
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "clip": ["4",1],
            "text": "cropped, no legs, no arms, 4 nipples, no head, low quality, artifacts, artifacts in eyes, bad anatomy, multiple images"            
        }
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["3",0],
            "vae": ["4",2]
        }
    },
    "save_image_websocket_node": {
        "class_type": "SaveImageWebsocket",
        "inputs": {
            "images": ["8",0]
        }
    }
}
"""

class ComfyUIInterface:
    def __init__(self, host: str, port: str, client_id: str):
        self.lock = threading.Lock()
        self.host = host
        self.port = port
        self.client_id = client_id

        self.url_ws = f"ws://{host}:{port}/ws?clientId={client_id}"
        self.url_prompt = f"http://{host}:{port}/prompt"

        logger.debug(f"ComfyUI url ws: {self.url_ws}")
        logger.debug(f"ComfyUI url prompt: {self.url_prompt}")

        self.default_model = "DreamShaperXL_Turbo_V2-SFW.safetensors"

        self.output_dir = Path("/node/images")
        os.makedirs(self.output_dir, exist_ok=True)

    def image(self, request: ImageRequest) -> ImageResponse:
        output_file = self.output_dir / request.output
        model = request.model if not request.model or request.model != "default" else self.default_model        

        if self.generate_image(
                request.positive_prompt,
                request.negative_prompt,
                output_file,
                request.seed,
                request.width,
                request.height,
                request.steps,
                request.cfg,
                model):
            return ImageResponse(output=str(request.output))
        else:
            return None
        
    def generate_image(self, positive_prompt: str, negative_prompt: str, output_file: str, seed: int, width: int, height: int, steps: int, cfg: float, model: str):
        with self.lock:
            try:
                prompt = json.loads(base_text_to_image)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON: {e}")

            try:
                prompt["3"]["inputs"]["seed"] = seed
                prompt["3"]["inputs"]["steps"] = steps
                prompt["3"]["inputs"]["cfg"] = cfg
                prompt["6"]["inputs"]["text"] = positive_prompt
                prompt["7"]["inputs"]["text"] = negative_prompt
                prompt["5"]["inputs"]["width"] = width
                prompt["5"]["inputs"]["height"] = height
                prompt["4"]["inputs"]["ckpt_name"] = model        
            except Exception as e:
                logger.error(f"faild to update prompt: {e}")

            try:
                ws = websocket.WebSocket()
                ws.connect(self.url_ws)
                images = self._get_images(ws, prompt)
            except websocket.WebSocketException as e:
                logger.error(f"WebSocket: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected: {e}")
                return False
            finally:
                try:
                    ws.close()
                except Exception:
                    pass
                    return False

            if not images:
                logger.error("failed to generate images")
                return False

            for node_id in images:
                for image_data in images[node_id]:
                    image = Image.open(io.BytesIO(image_data))
                    image.save(output_file)
                    logger.info(f"saved generated image: {output_file}")

            return True

    def _queue_prompt(self, prompt):
        logger.debug(f"queue prompt: {prompt}")
        payload = {"prompt": prompt, "client_id": self.client_id}
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(self.url_prompt, data=data, headers={'Content-Type': 'application/json'})
        logger.debug(f"req {req}")

        try:
            with urllib.request.urlopen(req) as response:
                try:
                    resp_data = response.read()
                    return json.loads(resp_data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to read response: {repr(e)} | Response: {resp_data}")
                    return None

        except urllib.error.HTTPError as e:
            # Handles HTTP errors like 404, 500, etc.
            logger.error(f"HTTP error while queuing prompt: {e.code} {e.reason} | {e.read().decode('utf-8')}")
        except urllib.error.URLError as e:
            # Handles connection errors, DNS failures, refused connections, etc.
            logger.error(f"URL error while queuing prompt: {repr(e)}")
        except Exception as e:
            # Catch-all for any other unexpected errors
            logger.error(f"Unexpected error while queuing prompt: {repr(e)}")

        return None

    def _get_images(self, ws, prompt):
        prompt_id = self._queue_prompt(prompt)['prompt_id']
        output_images = {}
        current_node = ""
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message['type'] == 'executing':
                    data = message['data']
                    if data['prompt_id'] == prompt_id:
                        if data['node'] is None:
                            break #Execution is done
                        else:
                            current_node = data['node']
            else:
                if current_node == 'save_image_websocket_node':
                    images_output = output_images.get(current_node, [])
                    images_output.append(out[8:])
                    output_images[current_node] = images_output

        return output_images
