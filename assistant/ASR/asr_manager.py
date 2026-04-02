import asyncio
import aiohttp
import json
import struct
import gzip
import uuid
import logging
from typing import Dict, Any, Optional, AsyncGenerator
import sounddevice as sd
import numpy as np
from assistant.config.config_manager import ConfigManager
from assistant.utils.logger import logger
from assistant.LLM.llm_manager import LLMManager
from assistant.ASR.state_manager import ASRState
# 常量定义
DEFAULT_SAMPLE_RATE = 16000

class ProtocolVersion:
    V1 = 0b0001

class MessageType:
    CLIENT_FULL_REQUEST = 0b0001
    CLIENT_AUDIO_ONLY_REQUEST = 0b0010
    SERVER_FULL_RESPONSE = 0b1001
    SERVER_ERROR_RESPONSE = 0b1111

class MessageTypeSpecificFlags:
    NO_SEQUENCE = 0b0000
    POS_SEQUENCE = 0b0001
    NEG_SEQUENCE = 0b0010
    NEG_WITH_SEQUENCE = 0b0011

class SerializationType:
    NO_SERIALIZATION = 0b0000
    JSON = 0b0001

class CompressionType:
    GZIP = 0b0001

class CommonUtils:
    @staticmethod
    def gzip_compress(data: bytes) -> bytes:
        return gzip.compress(data)

    @staticmethod
    def gzip_decompress(data: bytes) -> bytes:
        return gzip.decompress(data)

class AsrRequestHeader:
    def __init__(self):
        self.message_type = MessageType.CLIENT_FULL_REQUEST
        self.message_type_specific_flags = MessageTypeSpecificFlags.POS_SEQUENCE
        self.serialization_type = SerializationType.JSON
        self.compression_type = CompressionType.GZIP
        self.reserved_data = bytes([0x00])

    def with_message_type(self, message_type: int) -> 'AsrRequestHeader':
        self.message_type = message_type
        return self

    def with_message_type_specific_flags(self, flags: int) -> 'AsrRequestHeader':
        self.message_type_specific_flags = flags
        return self

    def with_serialization_type(self, serialization_type: int) -> 'AsrRequestHeader':
        self.serialization_type = serialization_type
        return self

    def with_compression_type(self, compression_type: int) -> 'AsrRequestHeader':
        self.compression_type = compression_type
        return self

    def with_reserved_data(self, reserved_data: bytes) -> 'AsrRequestHeader':
        self.reserved_data = reserved_data
        return self

    def to_bytes(self) -> bytes:
        header = bytearray()
        header.append((ProtocolVersion.V1 << 4) | 1)
        header.append((self.message_type << 4) | self.message_type_specific_flags)
        header.append((self.serialization_type << 4) | self.compression_type)
        header.extend(self.reserved_data)
        return bytes(header)

    @staticmethod
    def default_header() -> 'AsrRequestHeader':
        return AsrRequestHeader()

class RequestBuilder:
    @staticmethod
    def new_auth_headers(app_key: str, access_key: str) -> Dict[str, str]:
        reqid = str(uuid.uuid4())
        return {
            "X-Api-Resource-Id": "volc.seedasr.sauc.duration",
            "X-Api-Connect-Id": reqid,
            "X-Api-Access-Key": access_key,
            "X-Api-App-Key": app_key
        }

    @staticmethod
    def new_full_client_request(seq: int) -> bytes:
        header = AsrRequestHeader.default_header() \
            .with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
        
        payload = {
            "user": {
                "uid": "demo_uid"
            },
            "audio": {
                "format": "wav",
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_nonstream": True,
                "enable_ddc": True,
                "enable_accelerate_text": True,
                "accelerate_score": 5,
                "enable_punc": True,
                "enable_ddc": True,
                "show_utterances": True,
                "enable_nonstream": False,
                "end_window_size": 200,
                "force_to_speech_time": 1000,
                "result_type": "single"
            }
        }
        
        payload_bytes = json.dumps(payload).encode('utf-8')
        compressed_payload = CommonUtils.gzip_compress(payload_bytes)
        payload_size = len(compressed_payload)
        
        request = bytearray()
        request.extend(header.to_bytes())
        request.extend(struct.pack('>i', seq))
        request.extend(struct.pack('>I', payload_size))
        request.extend(compressed_payload)
        
        return bytes(request)

    @staticmethod
    def new_audio_only_request(seq: int, segment: bytes, is_last: bool = False) -> bytes:
        header = AsrRequestHeader.default_header()
        if is_last:
            header.with_message_type_specific_flags(MessageTypeSpecificFlags.NEG_WITH_SEQUENCE)
            seq = -seq
        else:
            header.with_message_type_specific_flags(MessageTypeSpecificFlags.POS_SEQUENCE)
        header.with_message_type(MessageType.CLIENT_AUDIO_ONLY_REQUEST)
        
        request = bytearray()
        request.extend(header.to_bytes())
        request.extend(struct.pack('>i', seq))
        
        compressed_segment = CommonUtils.gzip_compress(segment)
        request.extend(struct.pack('>I', len(compressed_segment)))
        request.extend(compressed_segment)
        
        return bytes(request)

class AsrResponse:
    def __init__(self):
        self.code = 0
        self.event = 0
        self.is_last_package = False
        self.payload_sequence = 0
        self.payload_size = 0
        self.payload_msg = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "event": self.event,
            "is_last_package": self.is_last_package,
            "payload_sequence": self.payload_sequence,
            "payload_size": self.payload_size,
            "payload_msg": self.payload_msg
        }

class ResponseParser:
    @staticmethod
    def parse_response(msg: bytes) -> AsrResponse:
        response = AsrResponse()
        
        header_size = msg[0] & 0x0f
        message_type = msg[1] >> 4
        message_type_specific_flags = msg[1] & 0x0f
        serialization_method = msg[2] >> 4
        message_compression = msg[2] & 0x0f
        
        payload = msg[header_size*4:]
        
        if message_type_specific_flags & 0x01:
            response.payload_sequence = struct.unpack('>i', payload[:4])[0]
            payload = payload[4:]
        if message_type_specific_flags & 0x02:
            response.is_last_package = True
        if message_type_specific_flags & 0x04:
            response.event = struct.unpack('>i', payload[:4])[0]
            payload = payload[4:]
            
        if message_type == MessageType.SERVER_FULL_RESPONSE:
            response.payload_size = struct.unpack('>I', payload[:4])[0]
            payload = payload[4:]
        elif message_type == MessageType.SERVER_ERROR_RESPONSE:
            response.code = struct.unpack('>i', payload[:4])[0]
            response.payload_size = struct.unpack('>I', payload[4:8])[0]
            payload = payload[8:]
            
        if not payload:
            return response
            
        if message_compression == CompressionType.GZIP:
            try:
                payload = CommonUtils.gzip_decompress(payload)
            except Exception as e:
                logger.error(f"Failed to decompress payload: {e}")
                return response
                
        try:
            if serialization_method == SerializationType.JSON:
                response.payload_msg = json.loads(payload.decode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to parse payload: {e}")
            
        return response

class AsrWsClient:
    def __init__(self, url: str, segment_duration: int = 200, app_key: str = "", access_key: str = ""):
        self.seq = 1
        self.url = url
        self.segment_duration = segment_duration
        self.conn = None
        self.session = None
        self.app_key = app_key
        self.access_key = access_key

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc, tb):
        if self.conn and not self.conn.closed:
            await self.conn.close()
        if self.session and not self.session.closed:
            await self.session.close()
        
    async def create_connection(self) -> None:
        headers = RequestBuilder.new_auth_headers(self.app_key, self.access_key)
        try:  
            self.conn = await self.session.ws_connect(
                self.url,
                headers=headers
            )
            logger.info(f"Connected to {self.url}")
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            raise
        
    async def send_full_client_request(self) -> None:
        request = RequestBuilder.new_full_client_request(self.seq)
        self.seq += 1
        try:
            await self.conn.send_bytes(request)
            logger.info(f"Sent full client request with seq: {self.seq-1}")
            
            msg = await self.conn.receive()
            if msg.type == aiohttp.WSMsgType.BINARY:
                response = ResponseParser.parse_response(msg.data)
                logger.info(f"Received response: {response.to_dict()}")
            else:
                logger.error(f"Unexpected message type: {msg.type}")
        except Exception as e:
            logger.error(f"Failed to send full client request: {e}")
            raise
    
    def build_wav_header(self, sample_rate=16000, channels=1, bits_per_sample=16, data_size=0) -> bytes:
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8

        return struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b"data",
            data_size,
        )
    
    async def execute_mic(self, user_id: str, use_llm: bool = True, stop_event: asyncio.Event = None,
                         audio_q: asyncio.Queue = None, asr_queue: asyncio.Queue = None,
                         text_q: asyncio.Queue = None, llm_queue: asyncio.Queue = None,
                         streaming_llm_queue: asyncio.Queue = None, state=None):
        """
        实时麦克风流式ASR
        
        Args:
            user_id: 用户ID
            use_llm: 是否将ASR结果传递给大模型
            stop_event: 停止事件
            audio_q: 音频队列
            asr_queue: ASR队列
            text_q: 文本队列
            llm_queue: LLM队列
            streaming_llm_queue: 流式LLM队列
        """
        # ========= 1. 建立连接 & Full Request =========
        self.seq = 1
        await self.create_connection()
        await self.send_full_client_request()

        loop = asyncio.get_running_loop()
        
        SAMPLE_RATE = 16000
        FRAME_DURATION = 30     # 每帧时长 ms（WebRTC VAD 只支持 10/20/30）
        FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION / 1000)   #需要480个采样点

        # ========= 2. sounddevice 回调 =========
        def callback(indata, frames, time, status):
            if stop_event and stop_event.is_set():
                return
            if status:
                logger.warning(status)
            try:
                pcm_bytes = bytes(indata)
                loop.call_soon_threadsafe( 
                    audio_q.put_nowait,
                    pcm_bytes,
                )
            except asyncio.QueueFull:
                pass  # 队列满了就丢了

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SIZE,
            callback=callback,
        )

        stream.start()
        logger.info(f"🎙 Microphone streaming started for user {user_id}")
        
        # 初始化最后一次检测到声音的时间
        import time
        last_sound_time = time.time()
        
        # ========= 主线程 添加ASR接收协程 =========
        async def receiver():
            nonlocal last_sound_time
            try:
                while not (stop_event and stop_event.is_set()):
                    try:
                        # 使用wait_for为recv_messages添加超时，避免WebSocket连接异常时阻塞
                        msg = await asyncio.wait_for(self.conn.receive(), timeout=3.0)
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            resp = ResponseParser.parse_response(msg.data)
                            msg = resp.payload_msg
                            
                            if not msg:
                                continue
                                
                            result = msg.get("result")
                            if not result:
                                continue
                                
                            utterances = result.get("utterances", []) or []
                            current_time = time.time()
                            for utt in utterances:
                                text = utt.get("text")
                                start_time = utt.get("start_time")
                                end_time = utt.get("end_time")
                                definite = utt.get("definite")   
                                # logger.info(f"*****用户 {user_id} 正在说话*****")
                                if text:
                                    # 更新最后一次检测到声音的时间
                                    last_sound_time = current_time
                                    # 有声音时设置is_silence为False
                                    if state:
                                        state.is_silence = False
                                    
                                if definite:
                                    logger.info(f"text:{text} definite:{definite}")
                                    if text and use_llm:
                                        try:
                                            # 更新最后一次检测到声音的时间
                                            last_sound_time = time.time()
                                            # 发送包含文本和时间信息的字典到 text_q
                                            text_data = {
                                                "text": text,
                                                "start_time": start_time,
                                                "end_time": end_time,
                                                "last_sound_time": last_sound_time
                                            }
                                            # 对于 asr_queue，仍然只发送文本
                                            await asr_queue.put(text)
                                            await text_q.put(text_data)
                                            
                                        except asyncio.QueueFull:
                                            logger.info(f"Queue full for user {user_id}")
                                            pass

                            if resp.is_last_package:
                                break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(f"WebSocket error: {msg.data}")
                            break
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            logger.info("WebSocket connection closed")
                            break
                    except asyncio.TimeoutError:
                        #超时后检查是否有3秒无声音
                        current_time = time.time()
                        if current_time - last_sound_time > 3:
                            if state:
                                state.is_silence = True
                            logger.info(f"用户 {user_id} 无声音（检测周期3s）state.is_silence:{state.is_silence}")
                            # 检测到静默时设置is_silence为True   
                        else:
                            # 静默时间小于3秒，设置is_silence为False
                            if state:
                                state.is_silence = False
                        continue
                    except Exception as e:
                        logger.error(f"Error receiving message: {e}")
                        # 发生异常时短暂休眠，避免CPU占用过高
                        await asyncio.sleep(0.1)
                        continue
            except Exception as e:
                logger.error(f"Unexpected error in receiver task: {e}")
        recv_task = asyncio.create_task(receiver())
        
        # ========= 5. 给ASR服务器 发送音频 ========= 主循环，不断从audio_q队列中获取分割的声音块
        first_packet = True
        try:
            while not (stop_event and stop_event.is_set()):
                try:
                    
                    # 为audio_q.get()添加超时，避免长时间阻塞
                    segment = await asyncio.wait_for(audio_q.get(), timeout=0.1)
                    #为第一个数据包添加wav格式头
                    if first_packet:
                        wav_header = self.build_wav_header(
                            sample_rate=SAMPLE_RATE,
                            channels=1,
                            bits_per_sample=16,
                            data_size=0,)
                        segment = wav_header + segment
                        first_packet = False

                    req = RequestBuilder.new_audio_only_request(
                        seq=self.seq,
                        segment=segment,
                        is_last=False,
                    )
                    # 为send_bytes添加超时，避免WebSocket缓冲区填满时阻塞
                    await asyncio.wait_for(self.conn.send_bytes(req), timeout=0.5)
                    logger.debug(f"Sent mic segment seq={self.seq} for user {user_id}")
                    self.seq += 1
                    # 短暂休眠，让出控制权给其他任务
                    await asyncio.sleep(0.01)
                except asyncio.TimeoutError:
                    # 超时后继续循环，避免阻塞
                    continue
                except Exception as e:
                    logger.error(f"Error in audio sending loop: {e}")
                    # 发生异常时短暂休眠，避免CPU占用过高
                    await asyncio.sleep(0.1)
                    continue
        except Exception as e:
            logger.error(f"Unexpected error in execute_mic: {e}")
        finally:
            logger.info(f"Stopping microphone stream for user {user_id}...")
            if stop_event and stop_event.is_set():
                try:
                # 发送 EOF
                    final_req = RequestBuilder.new_audio_only_request(
                    seq=self.seq,
                    segment=b"",
                    is_last=True,
                    )
                    await asyncio.wait_for(self.conn.send_bytes(final_req), timeout=0.5)
                except Exception as e:
                    logger.error(f"Error sending final packet: {e}")
                    pass
            try:
                recv_task.cancel()
            except Exception as e:
                logger.error(f"Error cancelling tasks: {e}")
            try:
                stream.stop()
                stream.close()
            except Exception as e:
                logger.error(f"Error closing stream: {e}")
            try:
                await self.conn.close()
            except Exception as e:
                logger.error(f"Error closing WebSocket: {e}")

class ASRManager:
    def __init__(self, llm_manager=None):
        self.clients: Dict[str, Dict] = {}
        if llm_manager:
            self.llm_manager = llm_manager
        else:
            from assistant.LLM.llm_manager import LLMManager
            self.llm_manager = LLMManager()
        # 初始化配置管理器
        self.config_manager = ConfigManager()
    
    async def start_asr(self, user_id: str, req: Any, use_llm: bool = True) -> None:
        """
        为用户启动ASR服务
        
        Args:
            user_id: 用户ID
            req: ASR请求参数
            use_llm: 是否使用LLM
        """
        # 停止之前的ASR服务
        if user_id in self.clients:
            await self.stop_asr(user_id)
        
        # 创建停止事件和队列
        stop_event = asyncio.Event()

        # 初始化各队列
        audio_q = asyncio.Queue(maxsize=500)
        asr_queue = asyncio.Queue(maxsize=500)
        text_q = asyncio.Queue(maxsize=500)
        llm_queue = asyncio.Queue(maxsize=500)
        streaming_llm_queue = asyncio.Queue(maxsize=500)    #实时输出LLM分析结果   
        state = ASRState()  # 创建状态对象,生命周期覆盖面试全过程
        
        # 保存客户端信息
        self.clients[user_id] = {
            'stop_event': stop_event,
            'audio_q': audio_q,
            'asr_queue': asr_queue,
            'text_q': text_q,
            'llm_queue': llm_queue,
            'streaming_llm_queue': streaming_llm_queue,
            'state': state,
            'task': None,
            'status': 'starting'
        }
        
        # 启动ASR任务
        task = asyncio.create_task(self._asr_runner(user_id, req, stop_event, use_llm))
        self.clients[user_id]['task'] = task
        self.clients[user_id]['status'] = 'running'
    
    async def stop_asr(self, user_id: str) -> None:
        """
        为用户停止ASR服务
        
        Args:
            user_id: 用户ID
        """
        if user_id not in self.clients:
            return
        
        client_info = self.clients[user_id]
        if client_info['stop_event']:
            client_info['stop_event'].set()
        
        if client_info['task']:
            try:
                client_info['task'].cancel()
                await asyncio.wait_for(client_info['task'], timeout=5.0)
            except Exception:
                pass
        
        del self.clients[user_id]
    
    def get_asr_queue(self, user_id: str) -> Optional[asyncio.Queue]:
        """
        获取用户的ASR队列
        
        Args:
            user_id: 用户ID
            
        Returns:
            Optional[asyncio.Queue]: ASR队列
        """
        if user_id in self.clients:
            return self.clients[user_id].get('asr_queue')
        return None
    
    def get_active_clients(self) -> list:
        """
        获取活跃的ASR客户端列表
        
        Returns:
            list: 活跃客户端列表
        """
        active_clients = []
        for user_id, client_info in self.clients.items():
            if client_info.get('status') == 'running':
                active_clients.append(user_id)
        return active_clients
    
    async def _asr_runner(self, user_id: str, req: Any, stop_event: asyncio.Event, use_llm: bool = True):
        """
        ASR运行器
        
        Args:
            user_id: 用户ID
            req: ASR请求参数
            stop_event: 停止事件
            use_llm: 是否使用LLM
        """
        try:
            async with AsrWsClient(req.url, req.seg_duration, self.config_manager.get_asr_config()['app_key'], self.config_manager.get_asr_config()['access_key']) as client:
                if req.mic:
                    logger.info(f"ASR mic mode started for user {user_id}")
                    # 启动LLM处理
                    await self.llm_manager.start_llm_processing(
                        user_id,
                        self.clients[user_id]['text_q'],
                        self.clients[user_id]['llm_queue'],
                        self.clients[user_id]['streaming_llm_queue'],
                        self.clients[user_id]['state']
                    )
                    # 执行麦克风ASR
                    await client.execute_mic(
                        user_id=user_id,
                        use_llm=use_llm,
                        stop_event=stop_event,
                        audio_q=self.clients[user_id]['audio_q'],
                        asr_queue=self.clients[user_id]['asr_queue'],
                        text_q=self.clients[user_id]['text_q'],
                        llm_queue=self.clients[user_id]['llm_queue'],
                        streaming_llm_queue=self.clients[user_id]['streaming_llm_queue'],
                        state=self.clients[user_id]['state']
                    )
                else:
                    #录音文件模式
                    logger.info(f"ASR file mode started for user {user_id}")
                    
        except asyncio.CancelledError:
            logger.info(f"⛔ ASR task cancelled for user {user_id}")
        except Exception as e:
            logger.error(f"❌ ASR processing failed for user {user_id}: {e}")
        finally:
            logger.info(f"✅ ASR task exited for user {user_id}")
            # 停止LLM处理
            await self.llm_manager.stop_llm_processing(user_id)
            if user_id in self.clients:
                self.clients[user_id]['status'] = 'stopped'


