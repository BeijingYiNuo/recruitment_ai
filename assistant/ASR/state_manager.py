import asyncio
import time

class ASRState:
    def __init__(self):
        self.is_silence = False
        self.last_voice_time = time.time()

        self.silence_event = asyncio.Event()
        self.speech_event = asyncio.Event()
        self.segment_event = asyncio.Event()
        
        # 流式输出内容
        self.streaming_content = ""

    def add_streaming_content(self, content):
        """
        添加流式输出内容
        """
        self.streaming_content += content
