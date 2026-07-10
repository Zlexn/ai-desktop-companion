from pathlib import Path

import httpx

payload = {
    "text": "今天晚上我想先休息十分钟，然后再继续整理桌面。",
    "voice_id": "default-zh-female",
    "speed": 1.0,
}
with httpx.Client(trust_env=False, timeout=120) as client:
    response = client.post("http://127.0.0.1:18003/api/audio/speech", json=payload)
print("status", response.status_code)
print("content-type", response.headers.get("content-type"))
print("provider", response.headers.get("x-tts-provider"))
print("model", response.headers.get("x-tts-model"))
print("duration", response.headers.get("x-audio-duration-ms"))
print("sample-rate", response.headers.get("x-audio-sample-rate"))
if response.status_code == 200:
    path = Path("data/cosyvoice-backend-smoke.wav")
    path.write_bytes(response.content)
    print("bytes", path.stat().st_size)
else:
    print(response.text[:500])
