import torch
import gc
import os
from pathlib import Path
from diffusers import FluxPipeline, FluxTransformer2DModel, StableDiffusionXLPipeline
from app.utils import ModelRegistry

from app.common import get_logger, ImageRequest, ImageResponse
logger = get_logger()

class ImageGen:
    def __init__(self):
        self.device = self._pick_device()
        self.model = None
        self.pipe = None
        self.compel = None

        logger.info(f"startup image_gen interface")

        self.output_dir = Path("/node/images")
        os.makedirs(self.output_dir, exist_ok=True)

    def image(self, request: ImageRequest) -> ImageResponse:
        registry = ModelRegistry()
        model_path = registry.get_safetensors(request.model)

        image = self._generate(
            prompt = request.positive_prompt,
            model = model_path,
            negative_prompt = request.negative_prompt,
            steps = request.steps,
            guidance = request.cfg, # TODO
            width = request.width,
            height = request.height,
            seed = request.seed
        )

        output_file = self.output_dir / request.output
        logger.debug(f"save image to {output_file}")
        image.save(output_file)

        return ImageResponse(output=str(request.output))

    def _dtype(self):
        if self.device == "cpu":
            return torch.float32
        if getattr(torch.version, "hip", None):
            return torch.bfloat16
        return torch.float16  # NVIDIA
    
    def _unload(self):
        if self.pipe is None and self.compel is None:
            return

        logger.info(f"unloading model {self.model} ...")
        
        if self.pipe is not None:
            try:
                self.pipe.to("cpu")
            except Exception:
                pass
            del self.pipe

        if self.compel is not None:
            del self.compel

        self.pipe = None
        self.compel = None
        self.model = None

        gc.collect()
        if self.device == "cuda":
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

    def _load(self, model: Path):
        if self.model == model and self.pipe is not None:
            return self.pipe

        self._unload()

        is_flux = "flux" in str(model).lower()
        if is_flux:
            logger.error("flux is currently not supported")

        self.model = model
        dtype = self._dtype()
        logger.info(f"loading model {model} dtype={dtype} device={self.device} ...")

        cls = FluxPipeline if is_flux else StableDiffusionXLPipeline
        pipe = cls.from_single_file(str(model), torch_dtype=dtype)
        pipe.to(self.device)

        if self.device == "cuda":
            if hasattr(pipe, "vae"):
                pipe.vae.enable_slicing()
                pipe.vae.enable_tiling()
            if hasattr(pipe, "enable_attention_slicing"):
                pipe.enable_attention_slicing()

        self.compel = None
        if not is_flux:
            from compel import Compel, ReturnedEmbeddingsType
            self.compel = Compel(
                tokenizer=[pipe.tokenizer, pipe.tokenizer_2],
                text_encoder=[pipe.text_encoder, pipe.text_encoder_2],
                returned_embeddings_type=ReturnedEmbeddingsType.PENULTIMATE_HIDDEN_STATES_NON_NORMALIZED,
                requires_pooled=[False, True],
            )

        self.pipe = pipe
        return pipe

    def _generate(
        self,
        prompt: str,
        model: Path = "",
        negative_prompt: str = "",
        steps: int | None = None,
        guidance: float | None = None,
        width: int | None = None,
        height: int | None = None,
        seed: int | None = None,
        **kwargs,
    ):
        
        pipe = self._load(model)

        is_flux = "flux" in str(model)
        
        if seed is not None:
            kwargs["generator"] = torch.Generator(device=self.device).manual_seed(seed)

        kwargs.setdefault("num_inference_steps", steps or (20 if is_flux else 30))
        kwargs.setdefault("guidance_scale", guidance or 3.5)

        if width:
            kwargs["width"] = width

        if height:
            kwargs["height"] = height

        if self.compel is not None:
            embeds, pooled = self.compel(prompt)
            kwargs["prompt_embeds"] = embeds
            kwargs["pooled_prompt_embeds"] = pooled
            if negative_prompt:
                neg_embeds, neg_pooled = self.compel(negative_prompt)
                kwargs["negative_prompt_embeds"] = neg_embeds
                kwargs["negative_pooled_prompt_embeds"] = neg_pooled
            logger.debug(f"generate image (compel) {prompt}")
            return pipe(**kwargs).images[0]

        if not is_flux and negative_prompt:
            kwargs["negative_prompt"] = negative_prompt

        logger.debug(f"generate image {prompt}")

        return pipe(prompt, **kwargs).images[0]

    def _pick_device(self) -> str:
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            if getattr(torch.version, "hip", None):
                logger.info(f"device cuda (ROCm/HIP {torch.version.hip}) {name}")
            else:
                logger.info(f"device cuda (CUDA {torch.version.cuda}) {name}")
            return "cuda"

        if hasattr(torch, "xpu") and torch.xpu.is_available():
            logger.info("device xpu")
            return "xpu"

        logger.warning("no GPU backend available, using cpu")
        return "cpu"