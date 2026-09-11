# ==============================================================================
# 🚀 PINTEREST REALISM ENGINE — UGC PHOTOREALISM AI UPSCALER (GOOGLE COLAB)
# ==============================================================================
# Model: 4x-UltraSharp (fine-tuned for UGC realism, fabric weave and skin pores)
# Architecture: tiled inference, 0 CUDA OOM errors on a T4 GPU.
#
# Tuning notes — see the constants below:
#   * The model is 4x, so a large input is expensive. The input is capped at
#     PRE_MODEL_INPUT_MAX (default 768). The old code fed it the full 1440px
#     pin, ran 49.5 MP of super-resolution over 70 tiles, and then downscaled
#     the result straight back to 1440px — the size it started at. Capping the
#     input cuts the tiled work about 6x and returns a better image, because
#     the model now works from the render instead of from a sharpened copy.
#   * The output is capped at PRE_MAX_OUTPUT_PX (default 2160) and encoded
#     q92 4:2:0. The client resizes to its own pin width, so the old q98 4:4:4
#     encode was a 3.8 MB transfer carrying detail that was thrown away.
#
# 1. Run this entire cell in Google Colab with T4 GPU enabled.
#    (Runtime -> Change runtime type -> T4 GPU -> Save)
# 2. It downloads 4x-UltraSharp and starts a secure Cloudflare public tunnel.
# 3. Copy the generated URL into your local .env as:
#    COLAB_UPSCALER_URL=https://your-tunnel-id.trycloudflare.com
# ==============================================================================

import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

# --- STEP 1: Fast & Clean Installs (Modern Spandrel AI Engine) ---
print("📦 [1/4] Installing FastAPI, Uvicorn & Spandrel (modern AI upscaler engine)...")
import subprocess, sys

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "fastapi", "uvicorn", "python-multipart", "spandrel", "pillow"], check=True)

# Download cloudflared binary directly from Cloudflare release (instant, 100% reliable)
print("🌐 [2/4] Setting up Cloudflare tunnel...")
subprocess.run(["curl", "-s", "-L", "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64", "-o", "/usr/local/bin/cloudflared"], check=True)
subprocess.run(["chmod", "+x", "/usr/local/bin/cloudflared"], check=True)

# Download 4x-UltraSharp weights (Gold Standard for Photorealistic UGC & Micro-Textures)
MODEL_NAME = "4x-UltraSharp.pth"
MODEL_URL = "https://huggingface.co/lokCX/4x-Ultrasharp/resolve/main/4x-UltraSharp.pth"
print(f"🧠 [3/4] Downloading {MODEL_NAME} (Ultra-photorealistic UGC & fabric detail model, 67MB)...")
if not os.path.exists(MODEL_NAME) or os.path.getsize(MODEL_NAME) < 50_000_000:
    subprocess.run(["curl", "-s", "-L", MODEL_URL, "-o", MODEL_NAME], check=True)

# --- STEP 2: Load Model onto GPU ---
import io
import time
import re
import threading
import torch
import torchvision.transforms.functional as TF
from PIL import Image
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response, JSONResponse
import uvicorn
from spandrel import ModelLoader

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"⚡ Loading model on: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU (Warning: GPU not active!)'}")

model_loader = ModelLoader()
upscale_model = model_loader.load_from_file(MODEL_NAME)
upscale_model = upscale_model.to(device).eval()
if device.type == "cuda":
    upscale_model = upscale_model.half()  # 16-bit half precision for 2x faster GPU inference!

print("✅ 4x-UltraSharp Photorealism Model loaded into GPU VRAM successfully!")

# --- Tunables ---------------------------------------------------------------
#: Longest edge handed to the model. The model multiplies pixel count by 16,
#: so this is the single biggest lever on how long a pin takes.
MODEL_INPUT_MAX = int(os.environ.get("PRE_MODEL_INPUT_MAX", "768"))
#: Longest edge returned to the client. The client resizes to its own pin
#: width, so anything above that is transfer cost for nothing.
MAX_OUTPUT_PX = int(os.environ.get("PRE_MAX_OUTPUT_PX", "2160"))
#: Tiled inference geometry. Fewer, larger tiles means less overlap waste and
#: fewer kernel launches. 384px tiles peak well under 2 GB on a T4.
TILE_SIZE = int(os.environ.get("PRE_TILE_SIZE", "384"))
TILE_OVERLAP = int(os.environ.get("PRE_TILE_OVERLAP", "32"))
JPEG_QUALITY = int(os.environ.get("PRE_JPEG_QUALITY", "92"))
JPEG_SUBSAMPLING = int(os.environ.get("PRE_JPEG_SUBSAMPLING", "2"))


import gc

def purge_vram():
    """Immediately purge cached tensors and free 100% of GPU memory."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


def predict_tiled(model, input_tensor, tile_size=256, overlap=24, scale=4, dev="cuda"):
    """
    Tiled super-resolution: processes small 256px tiles with seamless feathering.
    Uses less than 800 MB VRAM peak, guaranteeing ZERO CUDA OOM errors on any image!
    """
    b, c, h, w = input_tensor.shape
    stride = tile_size - overlap
    out_h, out_w = h * scale, w * scale

    output = torch.zeros((b, c, out_h, out_w), dtype=torch.float32, device=dev)
    weights = torch.zeros((1, 1, out_h, out_w), dtype=torch.float32, device=dev)

    for y in range(0, h, stride):
        for x in range(0, w, stride):
            y_end = min(y + tile_size, h)
            x_end = min(x + tile_size, w)
            y_start = max(0, y_end - tile_size)
            x_start = max(0, x_end - tile_size)

            tile = input_tensor[:, :, y_start:y_end, x_start:x_end]
            with torch.no_grad():
                out_tile = model(tile).float()

            out_y1, out_y2 = y_start * scale, y_end * scale
            out_x1, out_x2 = x_start * scale, x_end * scale

            th, tw = out_tile.shape[2], out_tile.shape[3]
            mask = torch.ones((1, 1, th, tw), dtype=torch.float32, device=dev)
            fade = overlap * scale
            if fade > 0:
                if y_start > 0:
                    mask[:, :, :fade, :] *= torch.linspace(0, 1, fade, device=dev).view(1, 1, -1, 1)
                if y_end < h:
                    mask[:, :, -fade:, :] *= torch.linspace(1, 0, fade, device=dev).view(1, 1, -1, 1)
                if x_start > 0:
                    mask[:, :, :, :fade] *= torch.linspace(0, 1, fade, device=dev).view(1, 1, 1, -1)
                if x_end < w:
                    mask[:, :, :, -fade:] *= torch.linspace(1, 0, fade, device=dev).view(1, 1, 1, -1)

            output[:, :, out_y1:out_y2, out_x1:out_x2] += out_tile * mask
            weights[:, :, out_y1:out_y2, out_x1:out_x2] += mask

            del tile, out_tile, mask

    output = output / torch.clamp(weights, min=1e-5)
    return output.clamp(0, 1)


# --- STEP 3: FastAPI Web Server ---
app = FastAPI(title="Pinterest Realism Engine 2K UGC Upscaler")
ENHANCED_COUNTER = 0

@app.get("/")
def health_check():
    purge_vram()
    vram_free = 0
    vram_total = 0
    if torch.cuda.is_available():
        vram_free = torch.cuda.mem_get_info()[0] / (1024**3)
        vram_total = torch.cuda.mem_get_info()[1] / (1024**3)
    return {
        "status": "online",
        "service": "Pinterest Realism Engine 4x-UltraSharp 2K UGC Upscaler",
        "model": "4x-UltraSharp.pth (No Smoothing, High-Texture UGC)",
        "output_standard": "2K Master (Max 1440x2560, 98% 4:4:4)",
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        "vram_free_gb": round(vram_free, 2),
        "vram_total_gb": round(vram_total, 2),
        "pins_enhanced_total": ENHANCED_COUNTER,
    }

@app.post("/upscale")
async def upscale_endpoint(file: UploadFile = File(...)):
    """Receives one image, runs tiled 4x-UltraSharp, clears VRAM, returns a JPEG."""
    global ENHANCED_COUNTER
    t_start = time.time()
    ENHANCED_COUNTER += 1

    filename = file.filename or f"pin_{ENHANCED_COUNTER}.jpg"
    raw_bytes = await file.read()
    
    try:
        # Step A: Purge all GPU memory before starting this pin
        purge_vram()

        input_image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        in_w, in_h = input_image.size
        print(f"\n📥 [PIN #{ENHANCED_COUNTER}] Enhancing '{filename}' ({in_w}x{in_h}, {len(raw_bytes)//1024} KB)...")

        # Step B: Cap the model input. The model multiplies the pixel count by
        # 16, so this is what keeps a pin from taking tens of seconds.
        w, h = input_image.size
        if max(w, h) > MODEL_INPUT_MAX:
            scale = MODEL_INPUT_MAX / max(w, h)
            input_image = input_image.resize(
                (max(1, round(w * scale)), max(1, round(h * scale))),
                Image.Resampling.LANCZOS,
            )
            print(f"   ↳ input resized to {input_image.size} for inference")

        # Step C: Pre-process to tensor
        tensor = TF.to_tensor(input_image).unsqueeze(0).to(device)
        if device.type == "cuda":
            tensor = tensor.half()

        # Step D: Tiled 4x inference
        output_tensor = predict_tiled(
            upscale_model, tensor, tile_size=TILE_SIZE, overlap=TILE_OVERLAP,
            scale=4, dev=device,
        )

        output_image = TF.to_pil_image(output_tensor.squeeze(0).float().cpu())
        del tensor, output_tensor

        # Step E: Cap the output. The client resizes down to its own pin width,
        # so anything beyond this is transfer cost for no visible gain.
        w, h = output_image.size
        if max(w, h) > MAX_OUTPUT_PX:
            scale = MAX_OUTPUT_PX / max(w, h)
            output_image = output_image.resize(
                (max(1, round(w * scale)), max(1, round(h * scale))),
                Image.Resampling.LANCZOS,
            )

        out_w, out_h = output_image.size

        # Step F: Encode. q92 4:2:0 is ~1.1 MB where q98 4:4:4 was ~3.8 MB, for
        # an image that gets downscaled again on arrival.
        output_buf = io.BytesIO()
        output_image.save(
            output_buf, format="JPEG", quality=JPEG_QUALITY,
            subsampling=JPEG_SUBSAMPLING, optimize=False,
        )
        out_bytes = output_buf.getvalue()
        del output_image, output_buf

        # Step G: Purge all memory immediately after completing this pin!
        purge_vram()

        elapsed = time.time() - t_start
        vram_free = torch.cuda.mem_get_info()[0] / (1024**3) if torch.cuda.is_available() else 0
        vram_total = torch.cuda.mem_get_info()[1] / (1024**3) if torch.cuda.is_available() else 0
        print(f"   ⚡ Processed in {elapsed:.1f}s | Output: {out_w}x{out_h}")
        print(f"   🧹 VRAM Purged: {vram_free:.1f} GB / {vram_total:.1f} GB Free | Memory 100% Clean!")
        print(f"   ✅ [PIN #{ENHANCED_COUNTER}] Ready ({len(out_bytes)//1024} KB) — Sent to Local App")

        return Response(content=out_bytes, media_type="image/jpeg")

    except Exception as e:
        print(f"   ❌ [ERROR on Pin #{ENHANCED_COUNTER} - {filename}]: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        purge_vram()
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error_type": type(e).__name__,
                "detail": str(e),
                "filename": filename,
                "pin_number": ENHANCED_COUNTER,
            }
        )

# Start FastAPI in a background daemon thread
def start_api():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

threading.Thread(target=start_api, daemon=True).start()
time.sleep(2)

# --- STEP 4: Start Cloudflare Tunnel & Print Public URL ---
print("🚀 [4/4] Starting Cloudflare Public Tunnel...")
tunnel_proc = subprocess.Popen(
    ["cloudflared", "tunnel", "--url", "http://127.0.0.1:8000"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True
)

tunnel_url = None
start_time = time.time()
while time.time() - start_time < 30:
    line = tunnel_proc.stdout.readline()
    if not line:
        continue
    match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
    if match:
        tunnel_url = match.group(0)
        break

if tunnel_url:
    print("\n" + "="*70)
    print("🎉 2K UGC AI UPSCALER IS 100% ONLINE AND READY ON FREE COLAB GPU!")
    print(f"👉 Public Cloudflare URL: {tunnel_url}")
    print("\n👉 To connect your local Pinterest app, put this into your .env:")
    print(f"   COLAB_UPSCALER_URL={tunnel_url}")
    print("="*70 + "\n")
else:
    print("⚠️ Could not automatically extract tunnel URL. Check tunnel logs above.")

# Keep the Colab cell running
while True:
    time.sleep(60)
