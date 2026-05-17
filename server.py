"""
AI Product Design Canvas — Backend
FastAPI bridge to ComfyUI (auto-launched)
Zero VRAM — ComfyUI owns the GPU
"""

import asyncio
import base64
import io
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI, File, UploadFile, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Config ──
COMFYUI_DIR = os.environ.get(
    "COMFYUI_DIR",
    r"C:\ComfyUI\ComfyUI_windows_portable\ComfyUI"
)
COMFYUI_HOST = "127.0.0.1"
COMFYUI_PORT = 8188
COMFYUI_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"
WORKFLOWS_DIR = Path(__file__).parent / "workflows"
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
WORKFLOWS_DIR.mkdir(exist_ok=True)

app = FastAPI()
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

comfyui_process = None
progress_clients: list[WebSocket] = []


# ── ComfyUI Process Management ──

def launch_comfyui():
    """Auto-launch ComfyUI as a subprocess."""
    global comfyui_process

    comfyui_path = Path(COMFYUI_DIR)
    main_py = comfyui_path / "main.py"

    if not main_py.exists():
        print(f"WARNING: ComfyUI not found at {COMFYUI_DIR}")
        print("Set COMFYUI_DIR env var or start ComfyUI manually on port 8188")
        return False

    # Check if already running
    if is_comfyui_running():
        print(f"ComfyUI already running at {COMFYUI_URL}")
        return True

    print(f"Launching ComfyUI from {COMFYUI_DIR}...")

    # Find python in ComfyUI's venv or use system python
    venv_python = comfyui_path / "venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = comfyui_path.parent / "python_embeded" / "python.exe"
    if not venv_python.exists():
        venv_python = sys.executable

    comfyui_process = subprocess.Popen(
        [str(venv_python), str(main_py), "--listen", COMFYUI_HOST, "--port", str(COMFYUI_PORT)],
        cwd=str(comfyui_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # Wait for it to be ready
    print("Waiting for ComfyUI to start...")
    for i in range(60):  # 60 seconds timeout
        time.sleep(1)
        if is_comfyui_running():
            print(f"ComfyUI ready at {COMFYUI_URL}")
            return True
        if comfyui_process.poll() is not None:
            print("ComfyUI process exited unexpectedly")
            return False

    print("ComfyUI startup timed out")
    return False


def is_comfyui_running():
    import urllib.request
    try:
        urllib.request.urlopen(f"{COMFYUI_URL}/system_stats", timeout=2)
        return True
    except Exception:
        return False


# ── ComfyUI API Client ──

async def upload_image_to_comfyui(image_bytes, filename):
    """Upload an image to ComfyUI's input directory."""
    data = aiohttp.FormData()
    data.add_field('image', image_bytes, filename=filename, content_type='image/png')
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{COMFYUI_URL}/upload/image", data=data) as r:
            if r.status == 200:
                result = await r.json()
                return result.get("name", filename)
            else:
                text = await r.text()
                print(f"Upload failed ({r.status}): {text}")
                return None


async def queue_workflow(workflow, client_id):
    """Send a workflow to ComfyUI's /prompt endpoint."""
    payload = {"prompt": workflow, "client_id": client_id}
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{COMFYUI_URL}/prompt", json=payload) as r:
            if r.status == 200:
                result = await r.json()
                return result.get("prompt_id")
            else:
                text = await r.text()
                print(f"Queue failed ({r.status}): {text}")
                return None


async def poll_result(prompt_id, timeout=120):
    """Poll /history until the result is ready."""
    deadline = time.time() + timeout
    async with aiohttp.ClientSession() as session:
        while time.time() < deadline:
            async with session.get(f"{COMFYUI_URL}/history/{prompt_id}") as r:
                if r.status == 200:
                    data = await r.json()
                    if prompt_id in data:
                        return data[prompt_id]
            await asyncio.sleep(0.5)
    return None


async def download_output_image(file_info):
    """Download a generated image from ComfyUI."""
    params = {
        "filename": file_info["filename"],
        "subfolder": file_info.get("subfolder", ""),
        "type": file_info.get("type", "output"),
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{COMFYUI_URL}/view", params=params) as r:
            if r.status == 200:
                return await r.read()
    return None


def find_output_images(history):
    """Extract output image info from ComfyUI history."""
    outputs = history.get("outputs", {})
    images = []
    for node_output in outputs.values():
        for items in node_output.values():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "filename" in item:
                        if item["filename"].endswith((".png", ".jpg", ".jpeg")):
                            images.append(item)
    return images


def load_workflow(name):
    """Load a workflow JSON from the workflows directory."""
    path = WORKFLOWS_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def get_default_workflow():
    """Build a simple SDXL img2img workflow programmatically (API format)."""
    return {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": "CANVAS_IMAGE"}
        },
        "2": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "CHECKPOINT_NAME"}
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "POSITIVE_PROMPT",
                "clip": ["2", 1]
            }
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "NEGATIVE_PROMPT",
                "clip": ["2", 1]
            }
        },
        "5": {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": ["1", 0],
                "vae": ["2", 2]
            }
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
                "seed": 0,
                "steps": 25,
                "cfg": 7.5,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 0.55
            }
        },
        "7": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["6", 0],
                "vae": ["2", 2]
            }
        },
        "8": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["7", 0],
                "filename_prefix": "design_canvas"
            }
        }
    }


def inject_params(workflow, params):
    """Inject parameters into a workflow template."""
    for node_id, node in workflow.items():
        inputs = node.get("inputs", {})
        ct = node.get("class_type", "")

        # Inject canvas image
        if ct == "LoadImage":
            if inputs.get("image") == "CANVAS_IMAGE":
                inputs["image"] = params.get("image_filename", "canvas.png")

        # Inject checkpoint
        if ct == "CheckpointLoaderSimple":
            if inputs.get("ckpt_name") == "CHECKPOINT_NAME":
                inputs["ckpt_name"] = params.get("checkpoint", "sd_xl_base_1.0.safetensors")

        # Inject prompts
        if ct == "CLIPTextEncode":
            if inputs.get("text") == "POSITIVE_PROMPT":
                inputs["text"] = params.get("prompt", "")
            elif inputs.get("text") == "NEGATIVE_PROMPT":
                inputs["text"] = params.get("negative_prompt", "")

        # Inject sampler params
        if ct == "KSampler":
            inputs["seed"] = params.get("seed", random.randint(0, 2**32 - 1))
            inputs["steps"] = params.get("steps", 25)
            inputs["cfg"] = params.get("guidance_scale", 7.5)
            inputs["denoise"] = params.get("strength", 0.55)

    return workflow


# ── API Endpoints ──

class GenerateRequest(BaseModel):
    image: str          # base64 PNG — composite (3D + drawings)
    prompt: str
    strength: float = 0.55
    steps: int = 25
    guidance_scale: float = 7.5
    negative_prompt: str = "blurry, low quality, distorted, ugly, text, watermark"
    seed: int = -1
    workflow: str = "default"  # workflow name or "default"
    checkpoint: str = ""       # empty = auto-detect


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(Path(__file__).parent / "app.html")


@app.get("/status")
async def status():
    running = is_comfyui_running()
    # List available workflows
    workflows = ["default"]
    for f in WORKFLOWS_DIR.glob("*.json"):
        workflows.append(f.stem)
    # List available checkpoints from ComfyUI
    checkpoints = []
    if running:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{COMFYUI_URL}/object_info/CheckpointLoaderSimple") as r:
                    if r.status == 200:
                        data = await r.json()
                        ckpts = data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
                        checkpoints = ckpts if isinstance(ckpts, list) else []
        except Exception:
            pass

    return {
        "ready": running,
        "comfyui_running": running,
        "workflows": workflows,
        "checkpoints": checkpoints,
    }


@app.post("/upload_obj")
async def upload_obj(file: UploadFile = File(...)):
    filename = file.filename or "model.obj"
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._-")
    dest = UPLOAD_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return {"url": f"/uploads/{safe_name}", "filename": safe_name}


@app.post("/upload_files")
async def upload_files(files: list[UploadFile] = File(...)):
    results = []
    for file in files:
        filename = file.filename or "file"
        safe_name = "".join(c for c in filename if c.isalnum() or c in "._-")
        dest = UPLOAD_DIR / safe_name
        content = await file.read()
        dest.write_bytes(content)
        results.append({"url": f"/uploads/{safe_name}", "filename": safe_name})
    return results


@app.post("/upload_workflow")
async def upload_workflow(file: UploadFile = File(...)):
    """Upload a custom ComfyUI workflow JSON."""
    filename = file.filename or "custom.json"
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._-")
    if not safe_name.endswith(".json"):
        safe_name += ".json"
    dest = WORKFLOWS_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)
    return {"name": safe_name.replace(".json", ""), "filename": safe_name}


@app.websocket("/ws/progress")
async def ws_progress(ws: WebSocket):
    await ws.accept()
    progress_clients.append(ws)
    try:
        # Connect to ComfyUI's WebSocket for progress
        client_id = f"design_canvas_{id(ws)}"
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"ws://{COMFYUI_HOST}:{COMFYUI_PORT}/ws?clientId={client_id}") as comfy_ws:
                # Forward ComfyUI progress to our client
                async for msg in comfy_ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("type") == "progress":
                            prog = data.get("data", {})
                            step = prog.get("value", 0)
                            total = prog.get("max", 1)
                            await ws.send_text(json.dumps({"step": step, "total": total}))
                        elif data.get("type") == "executing" and data.get("data", {}).get("node") is None:
                            # Generation complete
                            await ws.send_text(json.dumps({"step": total, "total": total, "done": True}))
    except Exception:
        pass
    finally:
        if ws in progress_clients:
            progress_clients.remove(ws)


@app.post("/generate")
async def generate(req: GenerateRequest):
    if not is_comfyui_running():
        return JSONResponse({"error": "ComfyUI is not running"}, status_code=503)

    # 1. Decode and upload canvas image to ComfyUI
    img_bytes = base64.b64decode(req.image)
    img_filename = f"canvas_{int(time.time())}.png"
    uploaded_name = await upload_image_to_comfyui(img_bytes, img_filename)
    if not uploaded_name:
        return JSONResponse({"error": "Failed to upload image to ComfyUI"}, status_code=500)

    # 2. Load workflow
    if req.workflow == "default":
        workflow = get_default_workflow()
    else:
        workflow = load_workflow(req.workflow)
        if not workflow:
            workflow = get_default_workflow()

    # 3. Auto-detect checkpoint if not specified
    checkpoint = req.checkpoint
    if not checkpoint:
        # Try to find an SDXL checkpoint
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{COMFYUI_URL}/object_info/CheckpointLoaderSimple") as r:
                    if r.status == 200:
                        data = await r.json()
                        ckpts = data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
                        if ckpts:
                            # Prefer SDXL checkpoints
                            for c in ckpts:
                                if 'xl' in c.lower() or 'sdxl' in c.lower():
                                    checkpoint = c
                                    break
                            if not checkpoint:
                                checkpoint = ckpts[0]  # fallback to first available
        except Exception:
            checkpoint = "sd_xl_base_1.0.safetensors"

    # 4. Inject parameters
    seed = req.seed if req.seed >= 0 else random.randint(0, 2**32 - 1)
    params = {
        "image_filename": uploaded_name,
        "checkpoint": checkpoint,
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt,
        "seed": seed,
        "steps": req.steps,
        "guidance_scale": req.guidance_scale,
        "strength": req.strength,
    }
    workflow = inject_params(workflow, params)

    # 5. Queue workflow
    client_id = f"design_canvas_{int(time.time())}"
    prompt_id = await queue_workflow(workflow, client_id)
    if not prompt_id:
        return JSONResponse({"error": "Failed to queue workflow"}, status_code=500)

    # 6. Poll for result
    history = await poll_result(prompt_id, timeout=180)
    if not history:
        return JSONResponse({"error": "Generation timed out"}, status_code=504)

    # 7. Download output image
    output_images = find_output_images(history)
    if not output_images:
        return JSONResponse({"error": "No output images found"}, status_code=500)

    image_data = await download_output_image(output_images[0])
    if not image_data:
        return JSONResponse({"error": "Failed to download result"}, status_code=500)

    result_b64 = base64.b64encode(image_data).decode("utf-8")

    return {
        "image": result_b64,
        "seed": seed,
        "checkpoint": checkpoint,
        "workflow": req.workflow,
    }


if __name__ == "__main__":
    # Auto-launch ComfyUI
    launch_comfyui()

    print(f"\nDesign Canvas server starting on http://127.0.0.1:5000")
    print(f"ComfyUI backend at {COMFYUI_URL}\n")

    uvicorn.run(app, host="127.0.0.1", port=5000)
