import sounddevice as sd
import numpy as np
from typing import Dict, List, Optional
import uuid

class AudioManager:
    def __init__(self):
        self.streams: Dict[str, Dict] = {}
    
    def list_devices(self) -> List[Dict]:
        """
        列出可用音频设备
        
        Returns:
            List[Dict]: 设备列表
        """
        devices = []
        for i, device in enumerate(sd.query_devices()):
            devices.append({
                'id': i,
                'name': device['name'],
                'channels_in': device['max_input_channels'],
                'channels_out': device['max_output_channels']
            })
        return devices
    
    def create_stream(self, session_id: str, device_id: Optional[int] = None) -> str:
        """
        为会话ID创建音频流
        
        Args:
            session_id: 会话ID
            device_id: 设备ID，None表示使用默认设备
            
        Returns:
            str: 流ID
        """
        stream_id = str(uuid.uuid4())
        self.streams[session_id] = {
            'stream_id': stream_id,
            'device_id': device_id,
            'stream': None,
            'status': 'created'
        }
        return stream_id
    
    def start_stream(self, session_id: str) -> None:
        """
        启动会话ID音频流
        
        Args:
            session_id: 会话ID
        """
        if session_id not in self.streams:
            raise ValueError(f"Stream for session {session_id} not found")
        
        stream_info = self.streams[session_id]
        if stream_info['status'] == 'running':
            return
        
        # 配置音频流参数
        device = stream_info['device_id']
        SAMPLE_RATE = 16000
        CHANNELS = 1
        DTYPE = 'int16'
        BLOCKSIZE = int(SAMPLE_RATE * 0.03)  # 30ms
        
        # 创建音频流
        def callback(indata, frames, time, status):
            if status:
                print(status)
        
        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=BLOCKSIZE,
            device=device,
            callback=callback
        )
        
        stream.start()
        stream_info['stream'] = stream
        stream_info['status'] = 'running'
    
    def stop_stream(self, session_id: str) -> None:
        """
        停止会话ID音频流
        
        Args:
            session_id: 会话ID
        """
        if session_id in self.streams:
            stream_info = self.streams[session_id]
            if stream_info['stream']:
                try:
                    stream_info['stream'].stop()
                    stream_info['stream'].close()
                except Exception:
                    pass
            stream_info['status'] = 'stopped'
    
    def get_active_streams(self) -> List[Dict]:
        """
        获取活跃音频流列表
        
        Returns:
            List[Dict]: 活跃流列表
        """
        active_streams = []
        for session_id, stream_info in self.streams.items():
            if stream_info['status'] == 'running':
                active_streams.append({
                    'session_id': session_id,
                    'stream_id': stream_info['stream_id'],
                    'device_id': stream_info['device_id']
                })
        return active_streams
