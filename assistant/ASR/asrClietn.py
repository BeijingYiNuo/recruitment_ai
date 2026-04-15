from __future__ import annotations
import websockets
import uuid
import typing
import bitstruct
from pydantic import BaseModel
import asyncio

MESSAGE_TPYE_STR: typing.TypeAlias = typing.Literal[
    "full client request",
    "audio only request",
    "full server response",
    "error message from server",
]
MessageTypeStr: dict[int, MESSAGE_TPYE_STR] = {
    0b0001: "full client request",
    0b0010: "audio only request",
    0b1001: "full server response",
    0b1111: "error message from server",
}
MessageTypeCode: dict[MESSAGE_TPYE_STR, int] = {v: k for k, v in MessageTypeStr.items()}
MESSAGE_TPYE_SPECIFIC_FLAGS_STR: typing.TypeAlias = typing.Literal[
    "not sequence number",
    "positive sequence number",
    "not sequence number (last or negative package)",
    "negative sequence number",
]
MessageTypeSpecificFlagsStr: dict[int, MESSAGE_TPYE_SPECIFIC_FLAGS_STR] = {
    0b0000: "not sequence number",
    0b0001: "positive sequence number",
    0b0010: "not sequence number (last or negative package)",
    0b0011: "negative sequence number",
}
MessageTypeSpecificFlagsCode: dict[MESSAGE_TPYE_SPECIFIC_FLAGS_STR, int] = {
    v: k for k, v in MessageTypeSpecificFlagsStr.items()
}
MESSAGE_SERIALIZATION_METHOD_STR: typing.TypeAlias = typing.Literal["none", "json"]
MessageSerializationMethodStr: dict[int, MESSAGE_SERIALIZATION_METHOD_STR] = {
    0b0000: "none",
    0b0001: "json",
}
MessageSerializationMethodCode: dict[MESSAGE_SERIALIZATION_METHOD_STR, int] = {
    v: k for k, v in MessageSerializationMethodStr.items()
}
MESSAGE_COMPRESSION_STR: typing.TypeAlias = typing.Literal["none", "gzip"]
MessageCompressionStr: dict[int, MESSAGE_COMPRESSION_STR] = {
    0b0000: "none",
    0b0001: "gzip",
}
MessageCompressionCode: dict[MESSAGE_COMPRESSION_STR, int] = {
    v: k for k, v in MessageCompressionStr.items()
}


class Header(BaseModel):
    protocol_version: int = 0b0001
    header: int = 0b0001
    message_type: MESSAGE_TPYE_STR
    message_type_specific_flags: MESSAGE_TPYE_SPECIFIC_FLAGS_STR = "not sequence number"
    message_serialization_method: MESSAGE_SERIALIZATION_METHOD_STR = "json"
    message_compression: MESSAGE_COMPRESSION_STR = "none"

    def to_bytes(self) -> bytes:
        return bitstruct.pack(
            ">" + ("u4" * 8),
            self.protocol_version,
            self.header,
            MessageTypeCode[self.message_type],
            MessageTypeSpecificFlagsCode[self.message_type_specific_flags],
            MessageSerializationMethodCode[self.message_serialization_method],
            MessageCompressionCode[self.message_compression],
            0,
            0,
        )

    def from_bytes(data: bytes) -> "Header":
        (
            protocol_version,
            header,
            message_type_code,
            message_type_specific_flags_code,
            serialization_code,
            compression_code,
            _,
            _,
        ) = bitstruct.unpack(">" + ("u4" * 8), data)
        return __class__(
            protocol_version=protocol_version,
            header=header,
            message_type=MessageTypeStr[message_type_code],
            message_type_specific_flags=MessageTypeSpecificFlagsStr[
                message_type_specific_flags_code
            ],
            message_serialization_method=MessageSerializationMethodStr[
                serialization_code
            ],
            message_compression=MessageCompressionStr[compression_code],
        )


class UserConfig(BaseModel):
    uid: str | None = None
    did: str | None = None
    platform: str | None = None
    sdk_version: str | None = None
    app_version: str | None = None


class AudioConfig(BaseModel):
    language: str | None = None
    format: typing.Literal["pcm", "wav", "ogg", "mp3"]
    codec: typing.Literal["raw", "opus"] | None = None
    rate: typing.Literal[16000] = 16000
    bits: typing.Literal[16] = 16
    channel: typing.Literal[1, 2] = 1


class CorpusConfig(BaseModel):
    boosting_table_name: str | None = None
    boosting_table_id: str | None = None
    correct_table_name: str | None = None
    correct_table_id: str | None = None
    context: str | None = None


class RequestConfig(BaseModel):
    model_name: typing.Literal["bigmodel"]
    enable_nonstream: bool | None = None
    enable_itn: bool = True
    enable_speaker_info: bool = False
    ssd_version: str | None = None
    enable_punc: bool = True
    enable_ddc: bool = False
    output_zh_variant: typing.Literal["traiditional", "tw", "hk"] | None = None
    show_utterances: bool | None = None
    show_speech_rate: bool = False
    show_volume: bool = False
    enable_lid: bool = False
    enable_emotion_detection: bool = False
    enable_gender_detection: bool = False
    result_type: typing.Literal["full", "single"] = "full"
    enable_accelerate_text: bool = False
    accelerate_score: int = 0
    vad_segment_duration: int = 3000
    end_window_size: int = 800
    force_to_speech_time: int | None = None
    sensitive_words_filter: str | None = None
    enable_poi_fc: bool | None = None
    enable_music_fc: bool | None = None
    corpus: CorpusConfig | None = None


class FullClientRequestPayload(BaseModel):
    user: UserConfig = None
    audio: AudioConfig
    request: RequestConfig


class Utterance(BaseModel):
    text: str | None = None
    start_time: int | None = None
    end_time: int | None = None
    definite: bool | None = None


class Result(BaseModel):
    text: str | None = None
    utterances: list[Utterance] | None = None


class FullServerResponsePayload(BaseModel):
    result: Result | None = None

    def from_payload(payload: bytes) -> FullServerResponsePayload:
        return __class__.model_validate_json(payload)


ErrorMessageCodeMsg: dict[int, str] = {
    2000_0000: "success",
    4500_0001: "request param invalid",
    4500_0002: "empty audio",
    4500_0081: "timeout waiting packet",
    4500_0151: "wrong audio type",
    5500_0031: "server busy",
}


class ErrorMessageFromServerPayload(BaseModel):
    error_message_code: int
    error_message_code_msg: str
    error_message_size: int
    error_message: str

    def from_payload(payload: bytes) -> ErrorMessageFromServerPayload:
        error_message_code = int.from_bytes(payload[:4], "big")
        error_message_code_msg = ErrorMessageCodeMsg.get(
            error_message_code, "internal server error"
        )
        error_message_size = int.from_bytes(payload[4:8], "big")
        error_message = payload[8:].decode("utf-8")
        return __class__(
            error_message_code=error_message_code,
            error_message_code_msg=error_message_code_msg,
            error_message_size=error_message_size,
            error_message=error_message,
        )


class ArkAsrClient:
    websocket_client: websockets.ClientConnection = None
    uri: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
    # uri: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    x_api_connect_id: str
    x_api_resource_id: str = "volc.seedasr.sauc.duration"
    x_api_access_key = "d3OKET8P5LJz690Tl1UY4Lm5F7taSf73"
    x_api_app_key = "5739877651"
    auto_refresh_seconds: float
    refresh_seconds_counter: float = 0

    def __init__(self, x_api_connect_id: str = None, auto_refresh_seconds: float = 10):
        self.auto_refresh_seconds = auto_refresh_seconds
        if x_api_connect_id is None:
            x_api_connect_id = str(uuid.uuid4())
        self.x_api_connect_id = x_api_connect_id

    def build_full_client_request(self, payload: FullClientRequestPayload) -> bytes:
        b_header = Header(message_type="full client request").to_bytes()
        b_payload = payload.model_dump_json(ensure_ascii=False).encode("utf-8")
        b_payload_size = len(b_payload).to_bytes(4, byteorder="big", signed=False)
        return b_header + b_payload_size + b_payload

    def build_audio_only_request(
        self, payload: bytes, last_packet: bool = False
    ) -> bytes:
        """
        pcm, 16000Hz, 1 channel, 16bit
        """
        header = Header(message_type="audio only request")
        if last_packet:
            header.message_type_specific_flags = (
                "not sequence number (last or negative package)"
            )
        b_header = header.to_bytes()
        b_payload = payload
        b_payload_size = len(b_payload).to_bytes(4, byteorder="big", signed=False)
        return b_header + b_payload_size + b_payload

    async def parse_response(
        self, data: bytes
    ) -> tuple[Header, FullServerResponsePayload | ErrorMessageFromServerPayload]:
        header: Header = Header.from_bytes(data[:4])
        need_recon = False
        offset = 0
        if (
            header.message_type_specific_flags == "negative sequence number"
            or header.message_type_specific_flags == "positive sequence number"
        ):
            offset = 4
        if (
            header.message_type_specific_flags
            == "not sequence number (last or negative package)"
            or header.message_type_specific_flags == "negative sequence number"
        ):
            need_recon = True
        if header.message_type == "full server response":
            response = FullServerResponsePayload.from_payload(data[8 + offset :])
        # elif header.message_type == "error message from server":
        else:
            response = ErrorMessageFromServerPayload.from_payload(data[4 + offset :])
            if response.error_message_code_msg != "success":
                need_recon = True
        if need_recon:
            await self.init()
        return header, response

    async def init(self) -> ArkAsrClient:
        self.websocket_client = await websockets.connect(
            self.uri,
            additional_headers={
                "X-Api-App-Key": self.x_api_app_key,
                "X-Api-Access-Key": self.x_api_access_key,
                "X-Api-Resource-Id": self.x_api_resource_id,
                "X-Api-Connect-Id": self.x_api_connect_id,
            },
        ).__aenter__()
        await self.websocket_client.send(
            self.build_full_client_request(
                FullClientRequestPayload(
                    audio=AudioConfig(format="pcm"),
                    request=RequestConfig(model_name="bigmodel"),
                )
            )
        )
        # await self.recv()
        return self

    async def send(self, pcm_data: bytes) -> None:
        data_sec_length = len(pcm_data) / 16000 / 2  # 16000Hz,2byte
        self.refresh_seconds_counter += data_sec_length
        refresh = False
        if self.refresh_seconds_counter > self.auto_refresh_seconds:
            refresh = True
            self.refresh_seconds_counter = 0
        try:
            await self.websocket_client.send(
                self.build_audio_only_request(pcm_data, refresh)
            )
        except Exception as e:
            print(e)

    async def recv(
        self,
    ) -> tuple[Header, FullServerResponsePayload | ErrorMessageFromServerPayload]:
        return await self.parse_response(await self.websocket_client.recv())

    async def loop(
        self,
        callback_cor: typing.Callable[
            [Header, FullServerResponsePayload | ErrorMessageFromServerPayload],
            typing.Coroutine[typing.Any, None, None],
        ],
    ):

        while True:
            try:
                h, r = await self.recv()
                await callback_cor(h, r)
            except websockets.exceptions.ConnectionClosed as e:
                await asyncio.sleep(1)
                print(e)
            except Exception as e:
                raise


async def main():
    aac = ArkAsrClient()
    await aac.init()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())