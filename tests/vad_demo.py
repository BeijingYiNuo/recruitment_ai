import webrtcvad
import sounddevice as sd
import numpy as np
import time

SAMPLE_RATE = 16000     #采样率
FRAME_DURATION = 30     # 每帧时长 ms
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION / 1000)   #每帧样本数

vad = webrtcvad.Vad(3)  # 0~3，越大越激进

silence_duration = 0
MAX_SILENCE = 0.8  # 判断“说话结束的最大静默时长”
is_speaking = False



def audio_callback(indata, frames, time_info, status):
    global silence_duration, is_speaking

    audio = (indata[:, 0] * 32768).astype(np.int16).tobytes()
    is_voice = vad.is_speech(audio, SAMPLE_RATE)    #对当前帧判断是否为语音

    if is_voice:
        silence_duration = 0
        if not is_speaking:
            is_speaking = True
            print("🎙️ Voice START")
    else:
        silence_duration += FRAME_DURATION / 1000
        if is_speaking and silence_duration > MAX_SILENCE:
            is_speaking = False
            print("🛑 Voice END")


print("🎧 Listening with WebRTC VAD...")

with sd.InputStream(
    samplerate=SAMPLE_RATE,
    channels=1,
    blocksize=FRAME_SIZE,
    dtype="float32",
    callback=audio_callback
):
    while True:
        time.sleep(0.1)
