#!/usr/bin/env python3
import sys, os, hashlib, subprocess

VOICES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",
    "yunyang": "zh-CN-YunyangNeural",
    "yunxi": "zh-CN-YunxiNeural",
    "xiaoyi": "zh-CN-XiaoyiNeural",
    "liaoning": "zh-CN-liaoning-XiaobeiNeural",
    "shaanxi": "zh-CN-shaanxi-XiaoniNeural",
}
CACHE_DIR = "/opt/xiaonai/data/voice_cache"

def speak(text, voice="xiaoxiao"):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_key = hashlib.md5((text + "|" + voice).encode()).hexdigest()
    cache_path = os.path.join(CACHE_DIR, cache_key + ".mp3")
    if os.path.exists(cache_path):
        return cache_path
    voice_name = VOICES.get(voice, VOICES["xiaoxiao"])
    tmp = cache_path + ".tmp"
    r = subprocess.run(["edge-tts", "--voice", voice_name, "--text", text, "--write-media", tmp], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return "[Error] " + r.stderr[:200]
    os.rename(tmp, cache_path)
    return cache_path

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: say_voice.py <text> [voice]")
        sys.exit(1)
    text = sys.argv[1]
    voice = sys.argv[2] if len(sys.argv) > 2 else "xiaoxiao"
    path = speak(text, voice)
    if path.startswith("[Error]"):
        print(path)
    else:
        kb = os.path.getsize(path) / 1024
        print("VOICE_READY: " + path + " (" + str(round(kb,1)) + "KB)")
