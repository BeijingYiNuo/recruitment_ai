import asyncio
import aiohttp
import json
import struct
import gzip
import uuid
from typing import Dict, Any, Optional
import time
from assistant.utils.logger import logger

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
        
    

    async def send_final_packet(self):
        final_req = RequestBuilder.new_audio_only_request(
                    seq=self.seq,
                    segment=b"",
                    is_last=True,
                    )
        await asyncio.wait_for(self.conn.send_bytes(final_req), timeout=0.5)
        
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

    async def create_asr_connection(self) -> None:
        try:
            self.session = aiohttp.ClientSession()
            await self.create_connection()
            await self.send_full_client_request()
            logger.info(f"ASR connection created")
        except Exception as e:
            logger.error(f"Failed to create ASR connection: {e}")
            raise
    
    async def send_audio2asr(self, audio_data: bytes):
        
        try:
            req = RequestBuilder.new_audio_only_request(
                seq=self.seq,
                segment=audio_data,
                is_last=False,
            )
            # 为send_bytes添加超时，避免WebSocket缓冲区填满时阻塞
            await asyncio.wait_for(self.conn.send_bytes(req), timeout=0.1)
            # logger.info(f"Sent mic segment seq={self.seq}")
            self.seq += 1
            
        except Exception as e:
            logger.error(f"Failed to send audio only request: {e}")
            raise
    def debug_audio(self,chunk):
        if len(chunk) % 2 != 0:
            logger.error("❌ 不是 int16（字节数不对齐）")
            return
        
        audio = np.frombuffer(chunk, dtype=np.int16)
        
        logger.info(f"""
        [音频检测]
        len={len(chunk)}
        samples={len(audio)}
        min={audio.min()}
        max={audio.max()}
        mean={audio.mean()}
        """)

    async def receive_asr_response(self,  
                               asr_queue: asyncio.Queue = None, text_q: asyncio.Queue = None, 
                               state: Any = None, session_id: str = None) -> str:
        """
        接收ASR服务端返回的识别结果（单次接收）
        
        Args:
            use_llm: 是否使用LLM
            asr_queue: ASR队列
            text_q: 文本队列
            state: ASR状态对象
            session_id: 会话ID
            
        Returns:
            str: 识别的文本，如果没有则返回None
        """
        try:
            # 使用wait_for为recv_messages添加超时，避免WebSocket连接异常时阻塞
            msg_b = await asyncio.wait_for(self.conn.receive(), timeout=3)
            
            # logger.info(f"Received message********: {msg_b.type}")
            if msg_b.type == aiohttp.WSMsgType.BINARY:
                resp = ResponseParser.parse_response(msg_b.data)
                msg = resp.payload_msg
                if not msg:
                    return None
                result = msg.get("result")
                if not result:
                    return None
                utterances = result.get("utterances", []) or []
                current_time = time.time()  # 确保current_time在所有使用场景下都已定义
                last_text = None
                for utt in utterances:
                    text = utt.get("text")
                    start_time = utt.get("start_time")
                    end_time = utt.get("end_time")
                    definite = utt.get("definite")   
                    try:
                        if text:
                            last_text = text  # 保存最后一个有效的文本
                            # 有声音时设置is_silence为False
                            if state:
                                async with state.lock:
                                    state.is_silence = False
                                    state.last_voice_time = current_time
                            await asr_queue.put(text)
                            if definite:
                                # logger.info(f"text:{text} definite:{definite}")
                                text_data = {
                                    "text": text,
                                    "start_time": start_time,
                                    "end_time": end_time,
                                    "last_sound_time": current_time
                                }
                                await text_q.put(text_data)            
                    except asyncio.QueueFull:
                        logger.info(f"Queue full for session {session_id}")
                        pass
                # 返回最后一个有效的文本，而不是在第一个循环就返回
                return last_text

                if resp.is_last_package:
                    return None
            elif msg_b.type == aiohttp.WSMsgType.ERROR:
                logger.error(f"WebSocket error: {msg_b.data}")
                return None
            elif msg_b.type == aiohttp.WSMsgType.CLOSED:
                logger.info("WebSocket connection closed")
                return None
        except asyncio.TimeoutError:
            # 超时检查静默状态
            if state:
                current_time = time.time()
                if current_time - state.last_voice_time > 3:
                    async with state.lock:
                        state.is_silence = True
                    logger.info(f"会话 {session_id} 无声音（检测周期3s）state.is_silence:{state.is_silence}")
                else:
                    async with state.lock:
                        state.is_silence = False
            return None
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            return None
        
        return None
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
    
    async def send_end_message(self):
        """
        发送结束消息给ASR服务器
        """
        try:
            # 检查WebSocket连接状态
            if not self.conn or self.conn.closed:
                logger.info("WebSocket connection already closed, skipping end message")
                return
            
            # 发送 EOF
            final_req = RequestBuilder.new_audio_only_request(
                seq=self.seq,
                segment=b"",
                is_last=True,
            )
            await asyncio.wait_for(self.conn.send_bytes(final_req), timeout=0.5)
            logger.info(f"Sent end message to ASR server with seq: {self.seq}")
        except asyncio.CancelledError:
            logger.info("Send end message cancelled")
        except Exception as e:
            # 忽略连接关闭错误
            if "Cannot write to closing transport" in str(e) or "WebSocket connection closed" in str(e):
                logger.info("WebSocket connection closed, skipping end message")
            else:
                logger.error(f"Error sending final packet: {e}")
            pass

    