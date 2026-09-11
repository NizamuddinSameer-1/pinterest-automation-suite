# ==============================================================================
# 🚀 PINTEREST REALISM ENGINE - FREE CLOUD GPU AI UPSCALER (GOOGLE COLAB)
# ==============================================================================

import io
import os
import re
import sys
import time
import threading
import subprocess
import torch
import torchvision.transforms.functional as TF
from PIL import Image
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response
import uvicorn
from spandrel import ModelLoader

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"⚡ Loading model on: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")

model_loader = ModelLoader()
upscale_model = model_loader.load_from_file("RealESRGAN_x4plus.pth")
upscale_model = upscale_model.to(device).eval()
if device.type == "cuda":
    upscale_model = upscale_model.half()

print("✅ Real-ESRGAN Model loaded into GPU VRAM successfully!")

app = FastAPI(title="Pinterest Realism Engine AI Upscaler")

@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "Pinterest Realism Engine AI Upscaler",
        "model": MODEL_FILE,
        "max_output_px": MAX_OUTPUT_PX,
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        "half_precision": device.type == "cuda"
    }

@app.post("/upscale")
async def upscale_endpoint(file: UploadFile = File(...)):
    raw_bytes = await file.read()
    input_image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")

    tensor = TF.to_tensor(input_image).unsqueeze(0).to(device)
    if device.type == "cuda":
        tensor = tensor.half()

    with torch.no_grad():
        output_tensor = upscale_model(tensor)
        output_tensor = output_tensor.clamp(0, 1)

    output_image = TF.to_pil_image(output_tensor.squeeze(0).float().cpu())

    # Cap the 4x output before it crosses the tunnel.
    #
    # Real-ESRGAN is a 4x model: a 1080px input becomes 4320px, which encodes to
    # roughly 21 MB at q98/4:4:4 and is then immediately downscaled back to
    # ~1080px on the client and discarded. Downscaling here, on the GPU, keeps
    # the detail that actually survives while cutting the transfer ~20x.
    if max(output_image.size) > MAX_OUTPUT_PX:
        scale = MAX_OUTPUT_PX / max(output_image.size)
        output_image = output_image.resize(
            (max(1, round(output_image.width * scale)),
             max(1, round(output_image.height * scale))),
            Image.Resampling.LANCZOS,
        )

    output_buf = io.BytesIO()
    # q92 4:2:0 — the client downscales further anyway, so higher quality here
    # is pure transfer cost. optimize=True was costing CPU on the GPU box for a
    # negligible size win.
    output_image.save(output_buf, format="JPEG", quality=92, subsampling=2)
    return Response(
        content=output_buf.getvalue(),
        media_type="image/jpeg",
        headers={"X-Output-Size": f"{output_image.width}x{output_image.height}"},
    )

def start_api():
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")

if __name__ == "__main__":
    threading.Thread(target=start_api, daemon=True).start()
    time.sleep(2)
    
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
        print("🎉 AI UPSCALER IS 100% ONLINE AND READY ON FREE COLAB GPU!")
        print(f"👉 Public Cloudflare URL: {tunnel_url}")
        print("\n👉 To connect your local Pinterest app, put this into your .env:")
        print(f"   COLAB_UPSCALER_URL={tunnel_url}")
        print("="*70 + "\n")
    
    while True:
        time.sleep(60)
