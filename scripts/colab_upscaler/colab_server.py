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
    
    output_buf = io.BytesIO()
    output_image.save(output_buf, format="JPEG", quality=98, subsampling=0, optimize=True)
    return Response(content=output_buf.getvalue(), media_type="image/jpeg")

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
