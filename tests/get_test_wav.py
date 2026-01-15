import sounddevice as sd
import numpy as np
import wave

samplerate = 16000
duration = 5

print("🎙️ 录音中...")
audio = sd.rec(int(duration * samplerate),
               samplerate=samplerate,
               channels=1,
               dtype='int16')
sd.wait()

with wave.open("test.wav", "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)   # int16 = 2 bytes
    wf.setframerate(samplerate)
    wf.writeframes(audio.tobytes())

print("✅ 保存成功 test.wav")
