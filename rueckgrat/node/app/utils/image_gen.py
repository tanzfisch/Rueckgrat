import torch
import gc
import os
from pathlib import Path
from threading import Lock
from diffusers import FluxPipeline, FluxTransformer2DModel, StableDiffusionXLPipeline
from app.utils import ModelRegistry

from app.common import get_logger, ImageRequest, ImageResponse
logger = get_logger()

# default sdxl configs from stabilityai/stable-diffusion-xl-base-1.0, no weights
SDXL_BASE_CONFIG_DIR = Path("/node/models/image_gen/stable-diffusion-xl-base-1.0-config")

class ImageGen:
    def __init__(self):
        self.device = self._pick_device()
        self.model = None
        self.pipe = None
        self.compel = None
        # one lock per image file (key = request.output, the hash file name the existence check uses):
        # requests for the same image serialize and the second one reuses the file of the first
        self.file_locks: dict[str, Lock] = {}
        self.file_locks_guard = Lock()
        # the gpu pipeline is shared (one loaded model, _load/_unload swap it), so the render itself
        # still runs one at a time
        self.pipeline_lock = Lock()
        # face reference (FaceID PlusV2), created and loaded on the first request with a reference_image_key.
        # faceid_attached: adapter + LoRA are in the current pipe (they go with it on _unload)
        self.faceid = None
        self.faceid_attached = False

        logger.info(f"startup image_gen interface")

        self.output_dir = Path("/node/images")
        os.makedirs(self.output_dir, exist_ok=True)

    def _file_lock(self, file_key: str) -> Lock:
        with self.file_locks_guard:
            return self.file_locks.setdefault(file_key, Lock())

    def image(self, request: ImageRequest) -> ImageResponse:
        registry = ModelRegistry()
        model_path = registry.get_safetensors(request.model)

        output_file = self.output_dir / request.output

        # check, generate and save all inside the per file lock: a second request for the same file (e.g. the
        # hub timed out and asks again) waits here for the first one and then reuses its file
        with self._file_lock(request.output):
            if request.output and output_file.exists():
                logger.debug(f"image {output_file} already exists, not generating it again")
                return ImageResponse(output=str(request.output))

            with self.pipeline_lock:
                image = self._generate(
                    prompt = request.positive_prompt,
                    model = model_path,
                    negative_prompt = request.negative_prompt,
                    steps = request.steps,
                    guidance = request.cfg, # TODO
                    width = request.width,
                    height = request.height,
                    seed = request.seed,
                    model_name = request.model,
                    reference_image_key = request.reference_image_key,
                    reference_image_b64 = request.reference_image_b64,
                )

            # write to a temp file and rename, so nobody ever sees a half written png
            logger.debug(f"save image to {output_file}")
            tmp_file = output_file.with_name(output_file.name + ".tmp")
            image.save(tmp_file, format="PNG")
            os.replace(tmp_file, output_file)

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
        self.faceid_attached = False

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
        if is_flux:
            pipe = cls.from_single_file(str(model), torch_dtype=dtype)
        else:
            # use the model's own pipeline configs next to the safetensors (see registry.json),
            # models without their own (e.g. lustify) fall back to the default sdxl base configs
            config_dir = Path(model).parent
            if not (config_dir / "model_index.json").exists():
                config_dir = SDXL_BASE_CONFIG_DIR
            logger.debug(f"sdxl pipeline config from {config_dir}")
            pipe = cls.from_single_file(str(model), torch_dtype=dtype, config=str(config_dir), local_files_only=True)
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
                # default True silently drops everything after 77 CLIP tokens (the character's appearance
                # and clothing sit there). False splits long prompts into 77 token chunks instead
                truncate_long_prompts=False,
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
        model_name: str = "",
        reference_image_key: str = "",
        reference_image_b64: str = "",
        **kwargs,
    ):
        
        pipe = self._load(model)

        is_flux = "flux" in str(model)

        # face reference: only sdxl, only with a usable face. otherwise the plain path below, as without one
        face = None
        if reference_image_key and not is_flux:
            face = self._face_reference(reference_image_key, reference_image_b64)
            if face is not None and not self._attach_faceid(pipe):
                face = None
        if face is None and self.faceid_attached:
            self._detach_faceid(pipe)
        
        if seed is not None:
            kwargs["generator"] = torch.Generator(device=self.device).manual_seed(seed)

        kwargs.setdefault("num_inference_steps", steps or (20 if is_flux else 30))
        kwargs.setdefault("guidance_scale", guidance or 3.5)

        if face is not None:
            max_cfg, max_steps = self._faceid_caps(model_name)
            kwargs["num_inference_steps"] = min(int(kwargs["num_inference_steps"]), max_steps)
            kwargs["guidance_scale"] = min(float(kwargs["guidance_scale"]), max_cfg)
            kwargs["ip_adapter_image_embeds"] = self.faceid.pipeline_embeds(
                face, pipe, do_cfg=kwargs["guidance_scale"] > 1, device=self.device, dtype=pipe.unet.dtype)
            logger.debug(f"face reference {reference_image_key}: steps={kwargs['num_inference_steps']} cfg={kwargs['guidance_scale']}")

        if width:
            kwargs["width"] = width

        if height:
            kwargs["height"] = height

        if self.compel is not None:
            embeds, pooled = self.compel(prompt)
            kwargs["pooled_prompt_embeds"] = pooled
            if negative_prompt:
                neg_embeds, neg_pooled = self.compel(negative_prompt)
                embeds, neg_embeds = self._pad_to_same_length(embeds, neg_embeds)
                kwargs["negative_prompt_embeds"] = neg_embeds
                kwargs["negative_pooled_prompt_embeds"] = neg_pooled
            kwargs["prompt_embeds"] = embeds
            logger.debug(f"generate image (compel) {prompt}\nusing model {self.model}")
            return pipe(**kwargs).images[0]

        if not is_flux and negative_prompt:
            kwargs["negative_prompt"] = negative_prompt

        logger.debug(f"generate image {prompt}\nusing model {self.model}")

        return pipe(prompt, **kwargs).images[0]

    def _face_reference(self, reference_image_key: str, reference_image_b64: str):
        """face embeddings for reference_image_key or None (no face, not installable, broken image ...)"""
        try:
            if self.faceid is None:
                from app.utils.faceid import FaceReference
                self.faceid = FaceReference()
            return self.faceid.embeds(reference_image_key, reference_image_b64)
        except Exception as e:
            logger.error(f"face reference {reference_image_key} failed, generating without it: {e!r}")
            return None

    def _attach_faceid(self, pipe) -> bool:
        if self.faceid_attached:
            return True
        # load_ip_adapter can't take over SlicedAttnProcessor, _detach_faceid turns slicing on again
        if hasattr(pipe, "disable_attention_slicing"):
            pipe.disable_attention_slicing()
        try:
            self.faceid_attached = self.faceid.attach(pipe)
        except Exception as e:
            logger.error(f"failed to load the face reference adapter: {e!r}")
            self.faceid_attached = True     # half loaded, let detach clean up whatever got in
        if not self.faceid_attached or not self._faceid_ready(pipe):
            self._detach_faceid(pipe)
            return False
        return True

    @staticmethod
    def _faceid_ready(pipe) -> bool:
        layers = getattr(getattr(pipe.unet, "encoder_hid_proj", None), "image_projection_layers", None)
        return bool(layers) and hasattr(layers[0], "clip_embeds")

    def _detach_faceid(self, pipe):
        """back to the pipe as _load() left it: no adapter, no LoRA, attention slicing as before"""
        for step in (pipe.unload_ip_adapter, pipe.unload_lora_weights):
            try:
                step()
            except Exception as e:
                logger.warning(f"removing the face reference adapter: {step.__name__} failed: {e!r}")
        if self.device == "cuda" and hasattr(pipe, "enable_attention_slicing"):
            pipe.enable_attention_slicing()
        self.faceid_attached = False

    def _faceid_caps(self, model_name: str) -> tuple[float, int]:
        """cfg/steps caps while a face reference is used, registry "faceid" of the image model"""
        from app.utils.faceid import DEFAULT_MAX_CFG, DEFAULT_MAX_STEPS
        caps = (ModelRegistry().get_model(model_name) or {}).get("faceid") or {}
        return float(caps.get("max_cfg", DEFAULT_MAX_CFG)), int(caps.get("max_steps", DEFAULT_MAX_STEPS))

    def _pad_to_same_length(self, embeds, neg_embeds):
        """
        without truncation both prompts can have a different number of 77 token chunks, the pipeline needs the
        positive and negative embeddings to have the same length. pads the shorter one with empty chunks
        (the embedding of an empty prompt). compel's own pad helper breaks with two text encoders
        """
        diff = embeds.shape[1] - neg_embeds.shape[1]
        if diff == 0:
            return embeds, neg_embeds
        empty_chunk, _ = self.compel("")                      # shape (1, 77, dim)
        chunks = abs(diff) // empty_chunk.shape[1]            # diff is always a multiple of 77
        padding = empty_chunk.repeat(1, chunks, 1).to(embeds.dtype)
        if diff > 0:
            neg_embeds = torch.cat([neg_embeds, padding], dim=1)
        else:
            embeds = torch.cat([embeds, padding], dim=1)
        return embeds, neg_embeds

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