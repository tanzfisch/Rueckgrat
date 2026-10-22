import random
from .job_queue import Job
from .image_job import ImageJob, ImageRequest
from ..utils.generic_image_prompt_compiler import GenericImagePromptCompiler
from typing import Dict, Any

from app.common import get_logger, Utils
logger = get_logger()

MODEL = "DreamShaperXL_Turbo_V2-SFW"    # the sfw default of the other image jobs


class GenerateImageJob(Job):
    """image generation tool: one image from a free text prompt. no contact, no conversation.
    the png stays in /hub/images, the client fetches it from /downloads/images/<filename> like chat images.
    the job is remembered for its user in the generated_images table (GET /generated-images): a pending row when the job is
    created (the hub got the request, even if it waits in the queue), done + file name or failed when it ends, also when the
    client is gone by then. result() goes to the client as {"generated_image": {request_id, prompt, filename, image_path or error}}"""
    def __init__(self, user_id: int, prompt: str, db, infrastructure, request_id: str = ""):
        super().__init__()
        self.user_id = user_id
        self.db = db
        self.infrastructure = infrastructure
        self.prompt = prompt
        self.request_id = request_id
        self.image = {}
        self.row_id = db.add_generated_image_pending(user_id, prompt, request_id)

    def build_request(self) -> ImageRequest:
        seed = random.randint(0, 2**31 - 1)     # a new image every time, also for the same prompt
        # same llm rewrite as the chat's generate_image tool (quality, lighting, english), the raw prompt if it fails
        prompts = GenericImagePromptCompiler(self.prompt, self.infrastructure, 0.7, seed).build()
        if not prompts or not prompts[0]:
            prompts = (self.prompt, ImageRequest.model_fields["negative_prompt"].default)
        positive_prompt, negative_prompt = prompts
        request = ImageRequest(
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            width=1024,
            height=1024,
            steps=40,
            cfg=11.0,
            model=MODEL,
            output="",
        )
        request.output = f"{Utils.hash_image_request(request)}.png"
        return request

    def execute(self) -> None:
        try:
            # run inline, not as a sub job: a sub job would send its own {"image": ...} to the client
            # with the db, the generation parameters are stored too, so a lost file can be generated again (ImageStore)
            image_job = ImageJob(self.build_request(), self.infrastructure, self.db)
            image_job.execute()
            self.image = image_job.result().get("image") or {}
        except Exception as e:
            logger.error(f"failed to generate image {repr(e)}")
        if self.image:
            self.db.complete_generated_image(self.row_id, self.image["filename"])
        else:
            self.db.fail_generated_image(self.row_id)

    def result(self) -> Dict[str, Any]:
        generated = {"request_id": self.request_id, "prompt": self.prompt}
        if self.image:
            generated.update(filename=self.image["filename"], image_path=self.image["image_path"])
        else:
            generated["error"] = "image generation failed"
        return {"generated_image": generated}

    def has_response(self) -> bool:
        return True
