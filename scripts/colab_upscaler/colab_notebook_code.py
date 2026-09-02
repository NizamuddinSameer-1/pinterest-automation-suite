# ==============================================================================
# 🚀 PINTEREST REALISM ENGINE - FREE CLOUD GPU AI UPSCALER (GOOGLE COLAB)
# ==============================================================================
# 1. Run this entire cell in Google Colab with T4 GPU enabled.
#    (Runtime -> Change runtime type -> T4 GPU -> Save)
# 2. It downloads the AI model and starts a Cloudflare public tunnel.
# 3. Copy the generated URL into your local .env as:
#    COLAB_UPSCALER_URL=https://xxxx.trycloudflare.com
# ==============================================================================

# --- STEP 1: Fast & Clean Installs (No broken basicsr, 100% stable) ---
print("📦 [1/4] Installing FastAPI, Uvicorn & Spandrel (modern AI upscaler engine)...")
import subprocess, sys

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "fastapi", "uvicorn", "python-multipart", "spandrel", "pillow"], check=True)

# Download cloudflared binary directly from Cloudflare release (instant, 100% reliable)
print("🌐 [2/4] Setting up Cloudflare tunnel...")
subprocess.run(["curl", "-s", "-L", "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64", "-o", "/usr/local/bin/cloudflared"], check=True)
subprocess.run(["chmod", "+x", "/usr/local/bin/cloudflared"], check=True)

# Download RealESRGAN_x4plus weights if not present
print("🧠 [3/4] Downloading Real-ESRGAN x4plus AI model weights (64MB)...")
import os
if not os.path.exists("RealESRGAN_x4plus.pth"):
    subprocess.run(["curl", "-s", "-L", "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth", "-o", "RealESRGAN_x4plus.pth"], check=True)

# --- STEP 2: Load Model onto GPU ---
import io
import time
import re
import threading
import torch
import torchvision.transforms.functional as TF
from PIL import Image
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import Response
import uvicorn
from spandrel import ModelLoader

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"⚡ Loading model on: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU (Warning: GPU not active!)'}")

model_loader = ModelLoader()
upscale_model = model_loader.load_from_file("RealESRGAN_x4plus.pth")
upscale_model = upscale_model.to(device).eval()
if device.type == "cuda":
    upscale_model = upscale_model.half()  # 16-bit half precision for 2x faster GPU inference!

print("✅ Real-ESRGAN Model loaded into GPU VRAM successfully!")

# --- STEP 3: FastAPI Web Server ---
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
    """Receives image bytes, runs Real-ESRGAN on GPU, returns 98% 4:4:4 master JPEG."""
    raw_bytes = await file.read()
    input_image = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    
    # Pre-process to tensor
    tensor = TF.to_tensor(input_image).unsqueeze(0).to(device)
    if device.type == "cuda":
        tensor = tensor.half()
        
    # Run AI Super-Resolution on T4 GPU
    with torch.no_grad():
        output_tensor = upscale_model(tensor)
        output_tensor = output_tensor.clamp(0, 1)
        
    # Convert back to PIL
    output_image = TF.to_pil_image(output_tensor.squeeze(0).float().cpu())
    
    # Save as ultra-sharp studio JPEG (98% quality, zero subsampling)
    output_buf = io.BytesIO()
    output_image.save(output_buf, format="JPEG", quality=98, subsampling=0, optimize=True)
    
    return Response(content=output_buf.getvalue(), media_type="image/jpeg")

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
    print("🎉 AI UPSCALER IS 100% ONLINE AND READY ON FREE COLAB GPU!")
    print(f"👉 Public Cloudflare URL: {tunnel_url}")
    print("\n👉 To connect your local Pinterest app, put this into your .env:")
    print(f"   COLAB_UPSCALER_URL={tunnel_url}")
    print("="*70 + "\n")
else:
    print("⚠️ Could not automatically extract tunnel URL. Check tunnel logs above.")

# Keep the Colab cell running
while True:
    time.sleep(60)
