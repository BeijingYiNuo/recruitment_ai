import asyncio
import time
from dataclasses import dataclass

@dataclass
class ASRState:
    def __init__(self):
        self.is_silence = False
        self.last_voice_time = time.time()
        self.lock = asyncio.Lock()
