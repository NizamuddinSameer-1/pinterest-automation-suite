# 🚀 Pinterest Realism Engine — Free Google Colab GPU AI Upscaler

Run **Real-ESRGAN Neural Super-Resolution** on Google's free **NVIDIA Tesla T4 GPU (16 GB VRAM)**. 
**Zero RAM and Zero GPU** will be used on your local laptop!

---

### 3 Quick Steps to Use:

1. Go to [Google Colab](https://colab.research.google.com/) and click **Upload Notebook**.
2. Upload `google_colab_upscaler.ipynb` (or copy-paste code from `colab_server.py`).
3. Make sure GPU is selected:
   - Click **Runtime** > **Change runtime type**
   - Select **T4 GPU** > Click **Save**.
4. Click the **Play / Run** button.
5. In about 30 seconds, it will print a link like:
   ```
   🎉 AI UPSCALER READY ON FREE COLAB GPU!
   👉 Copy this URL: https://random-words.trycloudflare.com
   ```
6. Open your local `.env` file and paste it:
   ```env
   COLAB_UPSCALER_URL=https://random-words.trycloudflare.com
   ```

---

### What happens if Colab is closed or offline?
Nothing breaks! Your system will automatically detect that Colab is offline and seamlessly fallback to the built-in **Local Lanczos 1080p + 98% 4:4:4 Studio Engine** (which runs in < 0.2s with almost zero RAM on your laptop).
