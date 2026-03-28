import websocket
import json
import urllib.request
import os
from PIL import Image
import io
from app.utils import ImageRequest, ImageResponse
import random
import string
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

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
    def __init__(self, host: str, port: str, client_id: str, output_dir: str):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.output_dir = output_dir

        self.url_ws = f"ws://{host}:{port}/ws?clientId={client_id}"
        self.url_prompt = f"http://{host}:{port}/prompt"

        logger.debug(f"ws: {self.url_ws}")
        logger.debug(f"prompt: {self.url_prompt}")

    def image(self, request: ImageRequest) -> ImageResponse:
        output_file = Path(self.output_dir) / f"image_{''.join(random.choices(string.digits, k=10))}.png"
        logging.info(output_file)

        self.generate_image(
            request.positive_prompt,
            request.negative_prompt,
            output_file,
            request.seed,
            request.width,
            request.height,
            request.steps,
            request.cfg,
            request.model
        )

        return ImageResponse(
            output_url=output_file
        )

    def generate_image(self, positive_prompt: str, negative_prompt: str, output_file: str, seed: int, width: int, height: int, steps: int, cfg: float, model: str):
        directory, filename = os.path.split(output_file)

        prompt = json.loads(base_text_to_image)
        prompt["3"]["inputs"]["seed"] = seed
        prompt["3"]["inputs"]["steps"] = steps
        prompt["3"]["inputs"]["cfg"] = cfg
        prompt["6"]["inputs"]["text"] = positive_prompt
        prompt["7"]["inputs"]["text"] = negative_prompt
        prompt["5"]["inputs"]["width"] = width
        prompt["5"]["inputs"]["height"] = height

        prompt["4"]["inputs"]["ckpt_name"] = model        

        ws = websocket.WebSocket()
        ws.connect(self.url_ws)        
        images = self._get_images(ws, prompt)
        ws.close()

        if not images:
            logger.error("no images generated")
            return

        for node_id in images:
            for image_data in images[node_id]:
                image = Image.open(io.BytesIO(image_data))
                image.save(output_file)

    def _queue_prompt(self, prompt):
        payload = {"prompt": prompt, "client_id": self.client_id}
        data = json.dumps(payload).encode('utf-8')
        logger.debug(data)
        req =  urllib.request.Request(self.url_prompt, data=data)

        try:
            return json.loads(urllib.request.urlopen(req).read())
        except Exception as e:
            logging.error(f"failed to queue prompt {repr(e)}")
            return None

    def _get_images(self, ws, prompt):
        queued_prompt = self._queue_prompt(prompt)
        if not queued_prompt:
            return None

        prompt_id = queued_prompt
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