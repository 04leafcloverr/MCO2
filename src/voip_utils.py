import struct
import wave
import time
import random
import uuid
from typing import Dict, Tuple, List, Optional

# Optional live-audio dependencies.
# These are only needed if you use microphone / speaker features.
try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    import numpy as np
except ImportError:
    np = None


# ============================================================
# LOGGING
# ============================================================

def log_event(tag: str, message: str) -> None:
    print(f"[{tag}] {message}")


# ============================================================
# GENERAL HELPERS
# ============================================================

def generate_tag() -> str:
    return str(random.randint(100000, 999999))


def generate_call_id() -> str:
    return str(uuid.uuid4())


def generate_ssrc() -> int:
    return random.randint(100000, 99999999)


def current_ntp_time() -> Tuple[int, int]:
    """
    Returns current time as NTP timestamp (seconds, fractional seconds).
    NTP epoch starts on 1900-01-01.
    """
    ntp_epoch_offset = 2208988800
    now = time.time() + ntp_epoch_offset
    seconds = int(now)
    fraction = int((now - seconds) * (1 << 32))
    return seconds, fraction


# ============================================================
# CODEC HELPERS
# ============================================================

CODEC_MAP = {
    0: "PCMU",
    8: "PCMA",
    96: "L16",
    97: "PCM",
}


def get_codec_name(payload_type: int) -> str:
    return CODEC_MAP.get(payload_type, f"UNKNOWN_PT_{payload_type}")


def get_payload_type(codec_name: str) -> int:
    codec_name = codec_name.upper().strip()
    reverse_map = {name: pt for pt, name in CODEC_MAP.items()}
    return reverse_map.get(codec_name, 0)


# ============================================================
# SIP / SDP HELPERS
# ============================================================

def build_sdp(
    ip: str,
    rtp_port: int,
    codec_payload_type: int = 0,
    session_name: str = "VoIP Call"
) -> str:
    sdp = (
        "v=0\r\n"
        f"o=user 12345 12345 IN IP4 {ip}\r\n"
        f"s={session_name}\r\n"
        "t=0 0\r\n"
        f"c=IN IP4 {ip}\r\n"
        f"m=audio {rtp_port} RTP/AVP {codec_payload_type}\r\n"
    )
    return sdp


def build_invite(
    receiver_ip: str,
    caller_ip: str,
    caller_port: int,
    receiver_name: str,
    caller_name: str,
    call_id: str,
    cseq: int,
    from_tag: str,
    rtp_port: int,
    codec_payload_type: int = 0
) -> str:
    sdp = build_sdp(caller_ip, rtp_port, codec_payload_type)
    content_length = len(sdp.encode())

    msg = (
        f"INVITE sip:{receiver_ip} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {caller_ip}:{caller_port}\r\n"
        f"To: {receiver_name} <sip:{receiver_ip}>\r\n"
        f"From: {caller_name} <sip:{caller_ip}>;tag={from_tag}\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: {cseq} INVITE\r\n"
        "Content-Type: application/sdp\r\n"
        f"Content-Length: {content_length}\r\n"
        "\r\n"
        f"{sdp}"
    )
    return msg


def build_200_ok(
    via_line: str,
    to_line: str,
    from_line: str,
    call_id_line: str,
    cseq_line: str,
    receiver_ip: str,
    rtp_port: int,
    codec_payload_type: int = 0,
    session_name: str = "VoIP Call"
) -> str:
    sdp = build_sdp(receiver_ip, rtp_port, codec_payload_type, session_name=session_name)
    content_length = len(sdp.encode())

    if "tag=" not in to_line:
        to_line = to_line + f";tag={generate_tag()}"

    msg = (
        "SIP/2.0 200 OK\r\n"
        f"{via_line}\r\n"
        f"{to_line}\r\n"
        f"{from_line}\r\n"
        f"{call_id_line}\r\n"
        f"{cseq_line}\r\n"
        "Content-Type: application/sdp\r\n"
        f"Content-Length: {content_length}\r\n"
        "\r\n"
        f"{sdp}"
    )
    return msg


def build_ack(
    receiver_ip: str,
    caller_ip: str,
    caller_port: int,
    to_line: str,
    from_line: str,
    call_id: str,
    cseq: int
) -> str:
    msg = (
        f"ACK sip:{receiver_ip} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {caller_ip}:{caller_port}\r\n"
        f"{to_line}\r\n"
        f"{from_line}\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: {cseq} ACK\r\n"
        "Content-Length: 0\r\n"
        "\r\n"
    )
    return msg


def build_bye(
    receiver_ip: str,
    caller_ip: str,
    caller_port: int,
    to_line: str,
    from_line: str,
    call_id: str,
    cseq: int,
    total_rtp_packets: int
) -> str:
    msg = (
        f"BYE sip:{receiver_ip} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {caller_ip}:{caller_port}\r\n"
        f"{to_line}\r\n"
        f"{from_line}\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: {cseq} BYE\r\n"
        f"Total-RTP-Packets: {total_rtp_packets}\r\n"
        "Content-Length: 0\r\n"
        "\r\n"
    )
    return msg


def build_bye_ok(
    via_line: str,
    to_line: str,
    from_line: str,
    call_id_line: str,
    cseq_line: str
) -> str:
    msg = (
        "SIP/2.0 200 OK\r\n"
        f"{via_line}\r\n"
        f"{to_line}\r\n"
        f"{from_line}\r\n"
        f"{call_id_line}\r\n"
        f"{cseq_line}\r\n"
        "Content-Length: 0\r\n"
        "\r\n"
    )
    return msg


def build_sip_error_response(
    status_code: int,
    reason_phrase: str,
    via_line: str,
    to_line: str,
    from_line: str,
    call_id_line: str,
    cseq_line: str,
    body: str = ""
) -> str:
    content_length = len(body.encode()) if body else 0

    msg = (
        f"SIP/2.0 {status_code} {reason_phrase}\r\n"
        f"{via_line}\r\n"
        f"{to_line}\r\n"
        f"{from_line}\r\n"
        f"{call_id_line}\r\n"
        f"{cseq_line}\r\n"
        f"Content-Length: {content_length}\r\n"
        "\r\n"
    )

    if body:
        msg += body

    return msg


def parse_sip_message(message: str) -> Tuple[str, Dict[str, str], str]:
    parts = message.split("\r\n\r\n", 1)
    header_block = parts[0]
    body = parts[1] if len(parts) > 1 else ""

    lines = header_block.split("\r\n")
    start_line = lines[0]
    headers = {}

    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()

    return start_line, headers, body


def parse_sdp(sdp: str) -> Dict[str, Optional[object]]:
    result = {
        "ip": None,
        "port": None,
        "codec": None
    }

    for line in sdp.splitlines():
        line = line.strip()
        if line.startswith("c="):
            parts = line.split()
            if len(parts) >= 3:
                result["ip"] = parts[2]
        elif line.startswith("m=audio"):
            parts = line.split()
            if len(parts) >= 4:
                result["port"] = int(parts[1])
                result["codec"] = parts[3]

    return result


def get_sip_status_info(start_line: str) -> Tuple[Optional[int], str]:
    """
    Example input: 'SIP/2.0 404 Not Found'
    Returns: (404, 'Not Found')
    """
    if not start_line.startswith("SIP/2.0"):
        return None, ""

    parts = start_line.split(" ", 2)
    if len(parts) < 3:
        return None, ""

    try:
        return int(parts[1]), parts[2]
    except ValueError:
        return None, ""


# ============================================================
# RTP HELPERS
# ============================================================

def build_rtp_packet(
    payload: bytes,
    seq_num: int,
    timestamp: int,
    ssrc: int,
    payload_type: int = 0,
    marker: int = 0
) -> bytes:
    version = 2
    padding = 0
    extension = 0
    cc = 0

    first_byte = (version << 6) | (padding << 5) | (extension << 4) | cc
    second_byte = ((marker & 0x01) << 7) | (payload_type & 0x7F)

    header = struct.pack("!BBHII", first_byte, second_byte, seq_num, timestamp, ssrc)
    return header + payload


def parse_rtp_packet(packet: bytes) -> Dict[str, object]:
    if len(packet) < 12:
        raise ValueError("Packet too short to be valid RTP.")

    first_byte, second_byte, seq_num, timestamp, ssrc = struct.unpack("!BBHII", packet[:12])

    version = first_byte >> 6
    padding = (first_byte >> 5) & 0x01
    extension = (first_byte >> 4) & 0x01
    cc = first_byte & 0x0F
    marker = second_byte >> 7
    payload_type = second_byte & 0x7F

    header_length = 12 + (cc * 4)
    payload = packet[header_length:]

    return {
        "version": version,
        "padding": padding,
        "extension": extension,
        "cc": cc,
        "marker": marker,
        "payload_type": payload_type,
        "codec_name": get_codec_name(payload_type),
        "sequence_number": seq_num,
        "timestamp": timestamp,
        "ssrc": ssrc,
        "payload": payload
    }


# ============================================================
# RTCP HELPERS
# ============================================================

def build_rtcp_sender_report(
    ssrc: int,
    packet_count: int,
    octet_count: int,
    rtp_timestamp: int
) -> bytes:
    version = 2
    padding = 0
    rc = 0
    first_byte = (version << 6) | (padding << 5) | rc
    packet_type = 200

    ntp_sec, ntp_frac = current_ntp_time()
    length = 6

    return struct.pack(
        "!BBHIIIIII",
        first_byte,
        packet_type,
        length,
        ssrc,
        ntp_sec,
        ntp_frac,
        rtp_timestamp,
        packet_count,
        octet_count
    )


def parse_rtcp_packet(packet: bytes) -> Dict[str, int]:
    if len(packet) < 28:
        raise ValueError("Packet too short to be valid RTCP SR.")

    first_byte, packet_type, length = struct.unpack("!BBH", packet[:4])
    version = first_byte >> 6

    if packet_type != 200:
        raise ValueError("Only RTCP Sender Report (PT=200) is supported here.")

    ssrc, ntp_sec, ntp_frac, rtp_timestamp, packet_count, octet_count = struct.unpack(
        "!IIIIII", packet[4:28]
    )

    return {
        "version": version,
        "packet_type": packet_type,
        "length": length,
        "ssrc": ssrc,
        "ntp_seconds": ntp_sec,
        "ntp_fraction": ntp_frac,
        "rtp_timestamp": rtp_timestamp,
        "packet_count": packet_count,
        "octet_count": octet_count
    }


# ============================================================
# WAV AUDIO HELPERS
# ============================================================

def read_wav_chunks(filename: str, chunk_size: int = 160) -> Tuple[List[bytes], Dict[str, int]]:
    chunks = []

    with wave.open(filename, "rb") as wf:
        params = {
            "nchannels": wf.getnchannels(),
            "sampwidth": wf.getsampwidth(),
            "framerate": wf.getframerate(),
            "nframes": wf.getnframes()
        }

        while True:
            frames_to_read = max(1, chunk_size // max(1, params["sampwidth"] * params["nchannels"]))
            data = wf.readframes(frames_to_read)
            if not data:
                break
            chunks.append(data)

    return chunks, params


def save_wav_file(filename: str, audio_chunks: List[bytes], params: Dict[str, int]) -> None:
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(params["nchannels"])
        wf.setsampwidth(params["sampwidth"])
        wf.setframerate(params["framerate"])
        wf.writeframes(b"".join(audio_chunks))


def estimate_chunk_duration_ms(chunk: bytes, params: Dict[str, int]) -> float:
    bytes_per_frame = params["nchannels"] * params["sampwidth"]
    if bytes_per_frame == 0 or params["framerate"] == 0:
        return 20.0

    frames_in_chunk = len(chunk) / bytes_per_frame
    duration_sec = frames_in_chunk / params["framerate"]
    return duration_sec * 1000.0


def get_timestamp_step(chunk: bytes, params: Dict[str, int]) -> int:
    bytes_per_frame = params["nchannels"] * params["sampwidth"]
    if bytes_per_frame == 0:
        return 160

    frames_in_chunk = len(chunk) // bytes_per_frame
    return max(1, frames_in_chunk)


# ============================================================
# LIVE AUDIO HELPERS (MIC / SPEAKER)
# ============================================================

def check_live_audio_support() -> None:
    if sd is None or np is None:
        raise RuntimeError(
            "Live microphone/speaker support requires 'sounddevice' and 'numpy'. "
            "Install them with: pip install sounddevice numpy"
        )


def get_default_audio_params() -> Dict[str, int]:
    """
    Safe default demo audio format.
    Mono, 16-bit, upgraded to 16000 Hz from 8000 Hz for a clearer audio.
    """
    return {
        "nchannels": 1,
        "sampwidth": 2,   # 16-bit PCM
        "framerate": 16000 # clearer voice
    }


def open_input_stream(params: Optional[Dict[str, int]] = None, blocksize: int = 160):
    """
    Opens a microphone input stream.
    Returns a sounddevice.RawInputStream.
    """
    check_live_audio_support()

    if params is None:
        params = get_default_audio_params()

    dtype = "int16" if params["sampwidth"] == 2 else "int8"

    stream = sd.RawInputStream(
        samplerate=params["framerate"],
        channels=params["nchannels"],
        dtype=dtype,
        blocksize=blocksize
    )
    stream.start()
    return stream


def open_output_stream(params: Optional[Dict[str, int]] = None, blocksize: int = 160):
    """
    Opens a speaker output stream.
    Returns a sounddevice.RawOutputStream.
    """
    check_live_audio_support()

    if params is None:
        params = get_default_audio_params()

    dtype = "int16" if params["sampwidth"] == 2 else "int8"

    stream = sd.RawOutputStream(
        samplerate=params["framerate"],
        channels=params["nchannels"],
        dtype=dtype,
        blocksize=blocksize
    )
    stream.start()
    return stream


def read_mic_chunk(input_stream, chunk_size: int = 160) -> bytes:
    """
    Reads one chunk from the microphone stream and returns raw PCM bytes.
    """
    data, overflowed = input_stream.read(chunk_size)
    if overflowed:
        log_event("AUDIO WARN", "Microphone input overflow detected")
    return bytes(data)


def play_audio_chunk(output_stream, chunk: bytes) -> None:
    """
    Plays one raw PCM chunk to the speaker stream.
    """
    output_stream.write(chunk)


def close_audio_stream(stream) -> None:
    if stream is not None:
        try:
            stream.stop()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass


def mic_chunk_duration_ms(chunk_size_frames: int, params: Optional[Dict[str, int]] = None) -> float:
    if params is None:
        params = get_default_audio_params()

    if params["framerate"] == 0:
        return 20.0

    duration_sec = chunk_size_frames / params["framerate"]
    return duration_sec * 1000.0


# ============================================================
# SIMPLE AUDIO MODE HELPERS
# ============================================================

def is_live_mode(mode: str) -> bool:
    return mode.strip().lower() in {"mic", "microphone", "live"}


def is_file_mode(mode: str) -> bool:
    return mode.strip().lower() in {"wav", "file", "audiofile"}


# ============================================================
# SIMPLE SIP DECISION HELPERS
# ============================================================

def should_reject_invite(receiver_name: str, receiver_ip: str) -> Tuple[bool, int, str]:
    """
    Placeholder policy hook for receiver-side validation.
    You can expand this later.

    Returns:
        (reject?, status_code, reason_phrase)
    """
    if not receiver_name:
        return True, 400, "Bad Request"

    if not receiver_ip:
        return True, 400, "Bad Request"

    return False, 200, "OK"