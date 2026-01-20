import asyncio
import aiohttp
import json
import struct
import gzip
import uuid
import logging
import os
import subprocess
from typing import Optional, List, Dict, Any, Tuple, AsyncGenerator
import signal
import sounddevice as sd
import numpy as np
import webrtcvad
# 导入大模型流式处理函数
from doubao_api_test import stream_text_to_llm
import asyncio
import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title = "Recruitment Service")

asr_task: asyncio.Task | None = None
stop_event: asyncio.Event | None = None

# 配置日志
logger = logging.getLogger("uvicorn.error")

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


class Config:
    def __init__(self):
        # 填入控制台获取的app id和access token
        self.auth = {
            "app_key": "5732215494",
            "access_key": "1nb4wqYUAauPuMABBnwi--o271GrwG43"
        }

    @property
    def app_key(self) -> str:
        return self.auth["app_key"]

    @property
    def access_key(self) -> str:
        return self.auth["access_key"]

config = Config()

class CommonUtils:
    @staticmethod
    def gzip_compress(data: bytes) -> bytes:
        return gzip.compress(data)

    @staticmethod
    def gzip_decompress(data: bytes) -> bytes:
        return gzip.decompress(data)

    @staticmethod
    def judge_wav(data: bytes) -> bool:
        if len(data) < 44:
            return False
        return data[:4] == b'RIFF' and data[8:12] == b'WAVE'

    @staticmethod
    def convert_wav_with_path(audio_path: str, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
        try:
            cmd = [
                "ffmpeg", "-v", "quiet", "-y", "-i", audio_path,
                "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(sample_rate),
                "-f", "wav", "-"
            ]
            result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # 尝试删除原始文件
            try:
                os.remove(audio_path)
            except OSError as e:
                logger.warning(f"Failed to remove original file: {e}")
                
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg conversion failed: {e.stderr.decode()}")
            raise RuntimeError(f"Audio conversion failed: {e.stderr.decode()}")

    @staticmethod
    def read_wav_info(data: bytes) -> Tuple[int, int, int, int, bytes]:
        if len(data) < 44:
            raise ValueError("Invalid WAV file: too short")
            
        # 解析WAV头
        chunk_id = data[:4]
        if chunk_id != b'RIFF':
            raise ValueError("Invalid WAV file: not RIFF format")
            
        format_ = data[8:12]
        if format_ != b'WAVE':
            raise ValueError("Invalid WAV file: not WAVE format")
            
        # 解析fmt子块
        audio_format = struct.unpack('<H', data[20:22])[0]
        num_channels = struct.unpack('<H', data[22:24])[0]
        sample_rate = struct.unpack('<I', data[24:28])[0]
        bits_per_sample = struct.unpack('<H', data[34:36])[0]
        
        # 查找data子块
        pos = 36
        while pos < len(data) - 8:
            subchunk_id = data[pos:pos+4]
            subchunk_size = struct.unpack('<I', data[pos+4:pos+8])[0]
            if subchunk_id == b'data':
                wave_data = data[pos+8:pos+8+subchunk_size]
                return (
                    num_channels,
                    bits_per_sample // 8,
                    sample_rate,
                    subchunk_size // (num_channels * (bits_per_sample // 8)),
                    wave_data
                )
            pos += 8 + subchunk_size
            
        raise ValueError("Invalid WAV file: no data subchunk found")

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
    def new_auth_headers() -> Dict[str, str]:
        reqid = str(uuid.uuid4())
        return {
            "X-Api-Resource-Id": "volc.seedasr.sauc.duration",
            "X-Api-Connect-Id": reqid,
            "X-Api-Access-Key": config.access_key,
            "X-Api-App-Key": config.app_key
        }

    @staticmethod
    def new_full_client_request(seq: int) -> bytes:  # 添加seq参数
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
                "enable_punc": True,
                "enable_ddc": True,
                "show_utterances": True,
                "enable_nonstream": False
            }
        }
        
        payload_bytes = json.dumps(payload).encode('utf-8')
        compressed_payload = CommonUtils.gzip_compress(payload_bytes)
        payload_size = len(compressed_payload)
        
        request = bytearray()
        request.extend(header.to_bytes())
        request.extend(struct.pack('>i', seq))  # 使用传入的seq
        request.extend(struct.pack('>I', payload_size))
        request.extend(compressed_payload)
        
        logger.info(f"Request seq: {seq}, payload_size: {payload_size}")
        

        return bytes(request)

    @staticmethod
    def new_audio_only_request(seq: int, segment: bytes, is_last: bool = False) -> bytes:
        header = AsrRequestHeader.default_header()
        if is_last:  # 最后一个包特殊处理
            header.with_message_type_specific_flags(MessageTypeSpecificFlags.NEG_WITH_SEQUENCE)
            seq = -seq  # 设为负值
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
        
        # 解析message_type_specific_flags
        if message_type_specific_flags & 0x01:
            response.payload_sequence = struct.unpack('>i', payload[:4])[0]
            payload = payload[4:]
        if message_type_specific_flags & 0x02:
            response.is_last_package = True
        if message_type_specific_flags & 0x04:
            response.event = struct.unpack('>i', payload[:4])[0]
            payload = payload[4:]
            
        # 解析message_type
        if message_type == MessageType.SERVER_FULL_RESPONSE:
            response.payload_size = struct.unpack('>I', payload[:4])[0]
            payload = payload[4:]
        elif message_type == MessageType.SERVER_ERROR_RESPONSE:
            response.code = struct.unpack('>i', payload[:4])[0]
            response.payload_size = struct.unpack('>I', payload[4:8])[0]
            payload = payload[8:]
            
        if not payload:
            return response
            
        # 解压缩
        if message_compression == CompressionType.GZIP:
            try:
                payload = CommonUtils.gzip_decompress(payload)
            except Exception as e:
                logger.error(f"Failed to decompress payload: {e}")
                return response
                
        # 解析payload
        try:
            if serialization_method == SerializationType.JSON:
                response.payload_msg = json.loads(payload.decode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to parse payload: {e}")
            
        return response

class AsrWsClient:
    def __init__(self, url: str, segment_duration: int = 200):
        self.seq = 1    #协议序列号
        self.url = url  #WebSocket地址
        self.segment_duration = segment_duration    #每个音频包的时长，单位ms
        self.conn = None                #WebSocket连接
        self.session = None             #aiohttp会话

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc, tb):
        if self.conn and not self.conn.closed:
            await self.conn.close()
        if self.session and not self.session.closed:
            await self.session.close()
        
    async def read_audio_data(self, file_path: str) -> bytes:
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
                
            if not CommonUtils.judge_wav(content):
                logger.info("Converting audio to WAV format...")
                content = CommonUtils.convert_wav_with_path(file_path, DEFAULT_SAMPLE_RATE)
                
            return content
        except Exception as e:
            logger.error(f"Failed to read audio data: {e}")
            raise
            
    def get_segment_size(self, content: bytes) -> int:
        try:
            channel_num, samp_width, frame_rate, _, _ = CommonUtils.read_wav_info(content)[:5]
            size_per_sec = channel_num * samp_width * frame_rate
            segment_size = size_per_sec * self.segment_duration // 1000
            return segment_size
        except Exception as e:
            logger.error(f"Failed to calculate segment size: {e}")
            raise
    #连接建立阶段，成功后建立全双工通道
    async def create_connection(self) -> None:
        headers = RequestBuilder.new_auth_headers()     #构建鉴权header
        try:  
            self.conn = await self.session.ws_connect(  # 使用self.session
                self.url,
                headers=headers
            )
            logger.info(f"Connected to {self.url}")
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            raise
        
    #构建协议头[Header][Seq][PayloadSize][CompressedPayload] 即发送的第一个请求full client request
    async def send_full_client_request(self) -> None:
        request = RequestBuilder.new_full_client_request(self.seq)
        self.seq += 1  # 发送后递增
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
    
    #发送包含音频数据的audio-only client request请求        
    async def send_messages(self, segment_size: int, content: bytes) -> AsyncGenerator[None, None]:
        audio_segments = self.split_audio(content, segment_size)
        total_segments = len(audio_segments)
        for i, segment in enumerate(audio_segments):
            is_last = (i == total_segments - 1)
            request = RequestBuilder.new_audio_only_request(
                self.seq, 
                segment,
                is_last=is_last
            )
            await self.conn.send_bytes(request)
            logger.info(f"Sent audio segment with seq: {self.seq} (last: {is_last})")
            
            if not is_last:
                self.seq += 1
                
            await asyncio.sleep(self.segment_duration / 1000) # 逐个发送，间隔时间模拟实时流
            # 让出控制权，允许接受消息
            yield
            
    async def recv_messages(self) -> AsyncGenerator[AsrResponse, None]:
        try:
            async for msg in self.conn:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    response = ResponseParser.parse_response(msg.data)
                    yield response
                    
                    if response.is_last_package or response.code != 0:
                        break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {msg.data}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info("WebSocket connection closed")
                    break
        except Exception as e:
            logger.error(f"Error receiving messages: {e}")
            raise
            
    async def start_audio_stream(self, segment_size: int, content: bytes) -> AsyncGenerator[AsrResponse, None]:
        async def sender():
            async for _ in self.send_messages(segment_size, content):
                pass
                
        # 启动发送和接收任务
        sender_task = asyncio.create_task(sender())
        
        try:
            async for response in self.recv_messages():
                yield response
        finally:
            sender_task.cancel()
            try:
                await sender_task
            except asyncio.CancelledError:
                pass
                
    @staticmethod
    def split_audio(data: bytes, segment_size: int) -> List[bytes]:
        if segment_size <= 0:
            return []
            
        segments = []
        for i in range(0, len(data), segment_size):
            end = i + segment_size
            if end > len(data):
                end = len(data)
            segments.append(data[i:end])
        return segments
    
    def build_wav_header(self,sample_rate=16000,channels=1,bits_per_sample=16,data_size=0) -> bytes:

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
    #能量检测
    def is_silence(self, pcm,threshold=500):
        data = np.frombuffer(pcm, dtype=np.int16)
        rms = np.sqrt(np.mean(data.astype(np.float32)**2))
        return rms < threshold
    
    async def execute_mic(self,channels: int = 1, use_llm: bool = True, stop_event: asyncio.Event | None = None):
        """
        Real-time microphone streaming ASR
        
        Args:
            channels: 声道数
            use_llm: 是否将ASR结果传递给大模型
        """

        # ========= 1. 建立连接 & Full Request =========
        self.seq = 1
        await self.create_connection()
        await self.send_full_client_request()

        loop = asyncio.get_running_loop()
        audio_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=10)   
        text_q: asyncio.Queue[str] = asyncio.Queue(maxsize=10)  # 用于传递ASR结果的队列
        
        SAMPLE_RATE = 16000
        FRAME_DURATION = 30     # 每帧时长 ms（WebRTC VAD 只支持 10/20/30）
        FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION / 1000)   #需要480个采样点
        vad = webrtcvad.Vad(3)  # 0~3，越大越激进
        MAX_SILENCE = 0.8
        silence_duration = 0.0
        is_speaking = False
        is_pause = True

        # ========= 2. sounddevice 回调 =========
        def callback(indata, frames, time, status):
            nonlocal silence_duration, is_speaking, is_pause
            if stop_event and stop_event.is_set():
                return
            if status:
                logger.warning(status)
            try:
                pcm_bytes = bytes(indata)
                is_voice = vad.is_speech(pcm_bytes, SAMPLE_RATE)
                if is_voice:
                    silence_duration = 0.0
                    if not is_speaking:
                        is_speaking = True
                        is_pause = False
                else:
                    silence_duration += FRAME_DURATION / 1000
                    if is_speaking and silence_duration > MAX_SILENCE:
                        is_speaking = False
                        is_pause = True
                loop.call_soon_threadsafe( 
                    audio_q.put_nowait,
                    pcm_bytes,
                )
            except asyncio.QueueFull:
                pass  # 丢帧比阻塞安全

        stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=channels,
            dtype="int16",
            blocksize=FRAME_SIZE,
            callback=callback,
        )

        stream.start()
        logger.info("🎙 Microphone streaming started")
        
        # ========= 主线程 添加ASR接收协程 =========
        async def receiver():
            async for resp in self.recv_messages():
                if stop_event and stop_event.is_set():
                    break
                msg = resp.payload_msg
                if not msg:
                    continue
                result = msg.get("result")
                if not result:
                    continue
                utterances = result.get("utterances", []) or []
                for utt in utterances:
                    text = utt.get("text")
                    start_time = utt.get("start_time")
                    end_time = utt.get("end_time")  
                    
                    if is_pause:
                        text = utt.get("text")
                        definite = utt.get("definite")
                        logger.info(f"text:{text} definite:{definite} start_time: {start_time}, end_time: {end_time} interval:{end_time - start_time}ms")
                        
                        # 将ASR结果放入队列
                        if text and use_llm:
                            try:
                                await text_q.put(text)
                            except asyncio.QueueFull:
                                pass  # 队列满时丢弃

                if resp.is_last_package:
                    break
        recv_task = asyncio.create_task(receiver())
        
        # ========= 4. LLM处理协程 =========
       
        async def consume_llm():
            async for llm_chunk in stream_text_to_llm(text_q):
                print(llm_chunk, end="", flush=True)
        llm_consume_task = asyncio.create_task(consume_llm())

        # ========= 5. 给ASR服务器 发送音频 ========= 主循环，不断从audio_q队列中获取分割的声音块
        first_packet = True
        try:
            while not (stop_event and stop_event.is_set()):
                segment = await audio_q.get()
                #为第一个数据包添加wav格式头
                if first_packet:
                    wav_header = self.build_wav_header(
                        sample_rate=SAMPLE_RATE,
                        channels=channels,
                        bits_per_sample=16,
                        data_size=0,)
                    segment = wav_header + segment
                    first_packet = False


                req = RequestBuilder.new_audio_only_request(
                    seq=self.seq,
                    segment=segment,
                    is_last=False,
                )
                await self.conn.send_bytes(req)
                logger.debug(f"Sent mic segment seq={self.seq}")
                self.seq += 1
        except asyncio.TimeoutError:
            pass
        finally:
            logger.info("Stopping microphone stream...")
            if stop_event and stop_event.is_set():
                try:
                # 发送 EOF
                    final_req = RequestBuilder.new_audio_only_request(
                    seq=self.seq,
                    segment=b"",
                    is_last=True,
                    )
                    await self.conn.send_bytes(final_req)
                except Exception:
                    pass
                recv_task.cancel()
                asr_task.cancel()
                llm_consume_task.cancel()
                stream.stop()
                stream.close()
                await self.conn.close()


    
    



    async def execute(self, file_path: str) -> AsyncGenerator[AsrResponse, None]:
        if not file_path:
            raise ValueError("File path is empty")

        if not self.url:
            raise ValueError("URL is empty")
            
        self.seq = 1
        
        try:
            # 1. 读取音频文件
            content = await self.read_audio_data(file_path)
            
            # 2. 计算分段大小
            segment_size = self.get_segment_size(content)
            
            # 3. 创建WebSocket连接
            await self.create_connection()
            
            # 4. 发送完整客户端请求
            await self.send_full_client_request()
            
            # 5. 启动音频流处理
            async for response in self.start_audio_stream(segment_size, content):
                yield response
                
        except Exception as e:
            logger.error(f"Error in ASR execution: {e}")
            raise
        finally:
            if self.conn:
                await self.conn.close()



class StartAsrRequest(BaseModel):
    url: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
    seg_duration: int = 200
    mic: bool = True
    file: str | None = None
    use_llm: bool = True

async def asr_runner(args: StartAsrRequest, stop_event: asyncio.Event):
    try:
        async with AsrWsClient(args.url, args.seg_duration) as client:
            if args.mic:
                logger.info("ASR mic mode started")
                await client.execute_mic(
                    use_llm=args.use_llm,
                    stop_event = stop_event
                )
            else:
                logger.info("ASR file mode started")
                async for response in client.execute(args.file):
                    if stop_event.is_set():
                        logger.info("🛑 Stop event received, exiting ASR loop")
                        break
                    logger.info(
                        f"Received response: {json.dumps(response.to_dict(), ensure_ascii=False)}"
                    )
    except asyncio.CancelledError:
        logger.info("⛔ ASR task cancelled")
    except Exception as e:
        logger.error(f"❌ ASR processing failed: {e}")
    finally:
        logger.info("✅ ASR task exited")

@app.post("/asr/start")
async def start_asr(req: StartAsrRequest):
    global asr_task, stop_event
    if asr_task and not asr_task.done():
        raise HTTPException(status_code=400, detail="ASR service already running")
    stop_event = asyncio.Event()
    asr_task = asyncio.create_task(asr_runner(req, stop_event))
    return {
        "status": "started",
        "mode": "mic" if req.mic else "file"
    }


@app.post("/asr/stop")
async def stop_asr():
    global asr_task, stop_event
    if not asr_task or asr_task.done():
        raise HTTPException(status_code=400, detail="ASR service not running")
    
    stop_event.set()
    asr_task.cancel()
    try:
        await asr_task
    except asyncio.CancelledError:
        pass
    asr_task = None
    stop_event = None
    return {
        "status":"stopped"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("asr_demo:app", host="127.0.0.1", port=8000, reload=True)

# async def main():
#     import argparse
    
#     parser = argparse.ArgumentParser(description="ASR WebSocket Client")
#     parser.add_argument("--file", type=str, required=False, help="Audio file path")

#     #wss://openspeech.bytedance.com/api/v3/sauc/bigmodel
#     #wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async
#     #wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream
#     #wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async
    
#     parser.add_argument("--url", type=str, default="wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async", 
#                        help="WebSocket URL")
#     parser.add_argument("--seg-duration", type=int, default=200, 
#                        help="Audio duration(ms) per packet, default:200")
    
#     parser.add_argument("--sample-rate", type=int, default=16000)
#     parser.add_argument("--channels", type=int, default=1,help="Mic channels, default:1")
#     parser.add_argument("--mic", action="store_true", default =True ,help="Use microphone for live input")
#     parser.add_argument("--use-llm", default=True, help="Pass ASR results to LLM for processing")
    
#     args = parser.parse_args()
    
#     #创建Asr WebSocket 客户端
#     async with AsrWsClient(args.url, args.seg_duration) as client:  # 使用async with 会自动触发AsrWsClient的__aenter__()方法，即创建session
#         try:
#             if args.mic:
#                 await client.execute_mic(use_llm=args.use_llm)
#             else:
#                 async for response in client.execute(args.file):
#                     logger.info(f"Received response: {json.dumps(response.to_dict(), indent=2, ensure_ascii=False)}")
#         except Exception as e:
#             logger.error(f"ASR processing failed: {e}")

# if __name__ == "__main__":
#     asyncio.run(main())