import json
import random
from app.common import Logger, Utils
logger = Logger(__name__).get_logger()

class GenericImagePromptCompiler:
    def __init__(self, prompt: str, infrastructure, temperature):
        self.prompt = prompt
        self.infrastructure = infrastructure
        self. temperature = temperature
    
    def _build_prompt(self) -> str:
        try:
            prompt = f"""
Create a concise, self-contained image generation prompt (positive and negative) based on the given input.

Input: {self.prompt}

Use the following json format for the output and nothing else

{{
  "positive_prompt": "",
  "negative_prompt": ""
}}

- positive_prompt: be specific but also add detail when helpfull. add quality and lighting information
- negative_prompt: exclude what not to expect in the image
- do not add ``` to mark the reply as code
            """
            payload = [{"role": "system", "content": prompt}]

            new_prompt = self.infrastructure.chat(payload, self.temperature, random.randint(0,100000))
            logger.debug(new_prompt)

            loaded = json.loads(new_prompt)
            logger.debug(loaded)

            return loaded
        except Exception as e:
            logger.error(f"failed to generate new prompt {repr(e)}")

        return None

    def build(self) -> str:
        try:
            prompt = self._build_prompt()

            positive_prompt = prompt["positive_prompt"]
            negative_prompt = prompt["negative_prompt"]

            return positive_prompt, negative_prompt
        except Exception as e:
            logger.error(f"failed to build image prompt {repr(e)}")