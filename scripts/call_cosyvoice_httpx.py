from pathlib import Path

import httpx

payload = {
    "model": "Fun-CosyVoice3-0.5B-2512",
    "input": "今天晚上我想先休息十分钟，然后再继续整理桌面。",
    "voice": "default-zh-female",
    "response_format": "wav",
    "speed": 1.0,
}
with httpx.Client(trust_env=False, timeout=90) as client:
    response = client.post("http://127.0.0.1:8001/v1/audio/speech", json=payload)
print("status", response.status_code)
print("content-type", response.headers.get("content-type"))
print("duration", response.headers.get("x-audio-duration-ms"))
print("sample-rate", response.headers.get("x-audio-sample-rate"))
if response.status_code == 200:
    path = Path("data/cosyvoice-direct-api-httpx.wav")
    path.write_bytes(response.content)
    print("bytes", path.stat().st_size)
else:
    print(response.text[:500])
