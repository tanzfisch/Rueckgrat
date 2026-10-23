"""
face reference for sdxl image generation: IP-Adapter FaceID PlusV2 (h94/IP-Adapter-FaceID).

the hub sends the contact's current profile image (ImageRequest.reference_image_key + reference_image_b64). from it
we take the largest face: the insightface (buffalo_l) identity embedding plus the CLIP ViT-H hidden states of
the aligned face crop (PlusV2 "clip_embeds", shortcut on). both are cached by reference_image_key, in memory (LRU)
and on disk. the key is the hub's content hash of the image, so a new profile image is a new key and an old
entry is never stale, it only ages out (see CACHE_MAX_AGE_SECONDS).

everything here is loaded lazily on the first request with a reference, a node that never gets one loads and
downloads nothing of it. insightface runs on the cpu (onnxruntime-gpu is cuda only, the node also runs on
rocm), the image encoder too and only while new embeddings are computed.

note: the insightface models are licensed for non-commercial research use only.
"""
import base64
import gc
import io
import os
import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from app.utils.registry import ModelRegistry, MODEL_BASE_DIR
from app.common import get_logger
logger = get_logger()

FACEID_MODEL = "faceid-plusv2-sdxl"     # registry.json entry: adapter, lora, image encoder, buffalo_l
ADAPTER_FILE = "ip-adapter-faceid-plusv2_sdxl.bin"
LORA_FILE = "ip-adapter-faceid-plusv2_sdxl_lora.safetensors"
LORA_NAME = "faceid"

ADAPTER_SCALE = 0.9
LORA_SCALE = 0.7
# cfg/steps caps while a face reference is used (registry "faceid" of the image model overrides them).
# only ever lower the requested values, the adapter burns faces at high cfg
DEFAULT_MAX_CFG = 6.0
DEFAULT_MAX_STEPS = 30

CACHE_DIR = MODEL_BASE_DIR / "faceid_cache"
CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60   # unused entries (deleted contacts, old profile images) go after 30 days
CACHE_CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60
MEMORY_CACHE_SIZE = 16

# hub file keys are "<sha256>.png", anything else is not used as a file name
KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}\.png")


class FaceReference:
    def __init__(self):
        self.lock = threading.Lock()
        self.memory: "OrderedDict[str, dict | None]" = OrderedDict()   # None = image has no usable face
        self.model_dir: Path | None = None
        self.face_app = None
        self._last_cleanup = 0.0

    # ---------------------------------------------------------------- install

    def install(self) -> Path | None:
        """installs the registry entry (same mechanism as the image models), returns its directory"""
        if self.model_dir is not None:
            return self.model_dir
        registry = ModelRegistry()
        if not registry.is_installed(FACEID_MODEL):
            logger.info(f"installing {FACEID_MODEL} for face references ...")
            if not registry.install_model(FACEID_MODEL):
                logger.error(f"failed to install {FACEID_MODEL}, generating without face reference")
                return None
        self.model_dir = MODEL_BASE_DIR / registry.get_install_path(FACEID_MODEL)
        return self.model_dir

    # ---------------------------------------------------------------- pipeline

    def attach(self, pipe) -> bool:
        """loads the FaceID PlusV2 adapter and its LoRA into an sdxl pipeline. the caller disabled attention
        slicing before (load_ip_adapter can't rebuild SlicedAttnProcessor) and restores it in detach()"""
        model_dir = self.install()
        if model_dir is None:
            return False
        logger.info(f"loading {FACEID_MODEL} into the image pipeline ...")
        pipe.load_ip_adapter(
            str(model_dir),
            subfolder=None,
            weight_name=ADAPTER_FILE,
            image_encoder_folder=None,      # we encode the face crop ourselves, on the cpu
            local_files_only=True,
        )
        pipe.load_lora_weights(str(model_dir), weight_name=LORA_FILE, adapter_name=LORA_NAME, local_files_only=True)
        pipe.set_ip_adapter_scale(ADAPTER_SCALE)
        pipe.set_adapters([LORA_NAME], adapter_weights=[LORA_SCALE])
        return True

    @staticmethod
    def detach(pipe) -> None:
        """removes adapter and LoRA again, the unet gets its plain attention processors and layers back"""
        logger.info(f"removing {FACEID_MODEL} from the image pipeline")
        pipe.unload_ip_adapter()
        pipe.unload_lora_weights()

    @staticmethod
    def pipeline_embeds(entry: dict, pipe, do_cfg: bool, device, dtype) -> list:
        """the ip_adapter_image_embeds argument for the pipeline call. also sets the PlusV2 clip_embeds and
        shortcut on the projection layer (diffusers reads them from there, not from the call)"""
        id_embeds = entry["id"].to(device=device, dtype=dtype)[None]           # (1, 1, 512)
        clip_embeds = entry["clip"].to(device=device, dtype=dtype)[None]       # (1, 1, 257, 1280)
        if do_cfg:
            # [negative, positive], the pipeline chunks it in two
            id_embeds = torch.cat([torch.zeros_like(id_embeds), id_embeds])
            clip_embeds = torch.cat([entry["uncond_clip"].to(device=device, dtype=dtype)[None], clip_embeds])

        projection = pipe.unet.encoder_hid_proj.image_projection_layers[0]
        projection.clip_embeds = clip_embeds
        projection.shortcut = True          # PlusV2
        projection.shortcut_scale = 1.0
        return [id_embeds]

    # ---------------------------------------------------------------- embeddings

    def embeds(self, reference_image_key: str, image_b64: str) -> dict | None:
        """face embeddings of the reference image, None if there is no usable face (or it fails).
        cached by reference_image_key, the bytes are only needed when the key is not cached yet"""
        if not reference_image_key or not KEY_PATTERN.fullmatch(reference_image_key):
            logger.warning(f"invalid face reference key {reference_image_key!r}, generating without face reference")
            return None

        with self.lock:
            self._cleanup_disk()

            if reference_image_key in self.memory:
                self.memory.move_to_end(reference_image_key)
                return self.memory[reference_image_key]

            found, entry = self._load_disk(reference_image_key)
            if not found:
                if not image_b64:
                    logger.warning(f"face reference {reference_image_key} is not cached and came without image bytes")
                    return None
                try:
                    entry = self._compute(reference_image_key, image_b64)
                except Exception as e:
                    logger.error(f"failed to compute face embeddings of {reference_image_key}: {e!r}")
                    return None
                self._save_disk(reference_image_key, entry)

            self.memory[reference_image_key] = entry
            while len(self.memory) > MEMORY_CACHE_SIZE:
                self.memory.popitem(last=False)
            return entry

    def _compute(self, reference_image_key: str, image_b64: str) -> dict | None:
        model_dir = self.install()
        if model_dir is None:
            raise RuntimeError(f"{FACEID_MODEL} not installed")

        image = Image.open(io.BytesIO(base64.b64decode(image_b64, validate=True))).convert("RGB")
        bgr = np.ascontiguousarray(np.array(image)[:, :, ::-1])     # insightface works on opencv bgr images

        faces = self._face_analysis(model_dir).get(bgr)
        if not faces:
            logger.info(f"no face found in reference image {reference_image_key}, generating without face reference")
            return None
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))

        from insightface.utils import face_align
        id_embeds = torch.from_numpy(np.asarray(face.normed_embedding, dtype=np.float32)).unsqueeze(0)   # (1, 512)
        crop = face_align.norm_crop(bgr, landmark=face.kps, image_size=224)
        crop = Image.fromarray(np.ascontiguousarray(crop[:, :, ::-1]))                                  # back to rgb

        # the image encoder (CLIP ViT-H, ~2.5 GB fp32) only lives while we encode, the result is cached
        from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection
        encoder = CLIPVisionModelWithProjection.from_pretrained(str(model_dir / "image_encoder"), torch_dtype=torch.float32)
        encoder.eval()
        try:
            pixel_values = CLIPImageProcessor()(images=crop, return_tensors="pt").pixel_values
            with torch.no_grad():
                # same as diffusers encode_image() with output_hidden_states (what FaceID Plus is trained on)
                clip_embeds = encoder(pixel_values, output_hidden_states=True).hidden_states[-2]
                uncond_clip = encoder(torch.zeros_like(pixel_values), output_hidden_states=True).hidden_states[-2]
        finally:
            del encoder
            gc.collect()

        logger.debug(f"face embeddings of {reference_image_key}: {len(faces)} face(s), using the largest")
        return {
            "id": id_embeds,                        # (1, 512) float32
            "clip": clip_embeds.to(torch.float16),  # (1, 257, 1280)
            "uncond_clip": uncond_clip.to(torch.float16),
        }

    def _face_analysis(self, model_dir: Path):
        if self.face_app is None:
            from insightface.app import FaceAnalysis
            # root/models/buffalo_l is installed by the registry entry, insightface doesn't download anything then
            self.face_app = FaceAnalysis(
                name="buffalo_l",
                root=str(model_dir / "insightface"),
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection", "recognition"],
            )
            self.face_app.prepare(ctx_id=-1, det_size=(640, 640))
        return self.face_app

    # ---------------------------------------------------------------- disk cache

    @staticmethod
    def _cache_file(reference_image_key: str) -> Path:
        return CACHE_DIR / f"{reference_image_key}.pt"

    def _load_disk(self, reference_image_key: str) -> tuple[bool, dict | None]:
        path = self._cache_file(reference_image_key)
        if not path.is_file():
            return False, None
        try:
            data = torch.load(path, map_location="cpu", weights_only=True)
            os.utime(path)      # in use, keep it away from the age cleanup
            return True, (data["entry"] if data.get("face") else None)
        except Exception as e:
            logger.warning(f"broken face cache file {path} ({e!r}), computing it again")
            path.unlink(missing_ok=True)
            return False, None

    def _save_disk(self, reference_image_key: str, entry: dict | None) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path = self._cache_file(reference_image_key)
            tmp = path.with_name(path.name + ".tmp")
            torch.save({"face": entry is not None, "entry": entry}, tmp)
            os.replace(tmp, path)
        except Exception as e:
            logger.warning(f"failed to cache face embeddings of {reference_image_key}: {e!r}")

    def _cleanup_disk(self) -> None:
        """drops cache files nobody used for CACHE_MAX_AGE_SECONDS. runs at most every
        CACHE_CLEANUP_INTERVAL_SECONDS, from the request that comes along"""
        now = time.time()
        if now - self._last_cleanup < CACHE_CLEANUP_INTERVAL_SECONDS:
            return
        self._last_cleanup = now
        if not CACHE_DIR.is_dir():
            return
        for path in CACHE_DIR.iterdir():
            try:
                if path.is_file() and now - path.stat().st_mtime > CACHE_MAX_AGE_SECONDS:
                    path.unlink()
                    self.memory.pop(path.name.removesuffix(".tmp").removesuffix(".pt"), None)
            except OSError as e:
                logger.warning(f"failed to clean face cache file {path}: {e!r}")
