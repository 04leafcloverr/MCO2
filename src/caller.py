import socket
import time

from voip_utils import (
    generate_tag,
    generate_call_id,
    generate_ssrc,
    build_invite,
    build_ack,
    build_bye,
    parse_sip_message,
    parse_sdp,
    get_sip_status_info,
    get_codec_name,
    get_payload_type,
    read_wav_chunks,
    estimate_chunk_duration_ms,
    get_timestamp_step,
    build_rtp_packet,
    build_rtcp_sender_report,
    log_event,
    is_live_mode,
    is_file_mode,
    get_default_audio_params,
    open_input_stream,
    read_mic_chunk,
    close_audio_stream,
    mic_chunk_duration_ms
)

SIP_PORT = 5060
RTP_PORT = 5004
RTCP_PORT = RTP_PORT + 1
MAX_BYTES = 4096


def send_rtcp_report(rtcp_sock, dest_ip, dest_port, ssrc, packet_count, octet_count, timestamp):
    try:
        rtcp_packet = build_rtcp_sender_report(
            ssrc=ssrc,
            packet_count=packet_count,
            octet_count=octet_count,
            rtp_timestamp=timestamp
        )
        rtcp_sock.sendto(rtcp_packet, (dest_ip, dest_port + 1))
        log_event(
            "RTCP SEND",
            f"Sender Report sent | Packets={packet_count} Octets={octet_count} RTP_TS={timestamp}"
        )
    except Exception as e:
        log_event("ERROR", f"Failed to send RTCP Sender Report: {e}")


def stream_wav_audio(media_sock, rtcp_sock, dest_ip, dest_port, audio_filename, payload_type):
    try:
        audio_chunks, audio_params = read_wav_chunks(audio_filename, chunk_size=160)
    except FileNotFoundError:
        log_event("ERROR", f"Audio file not found: {audio_filename}")
        return 0, 0, 0
    except Exception as e:
        log_event("ERROR", f"Failed to read WAV file: {e}")
        return 0, 0, 0

    log_event("AUDIO", f"Loaded WAV file: {audio_filename}")
    log_event("AUDIO", f"Total chunks: {len(audio_chunks)}")
    log_event("AUDIO", f"Params: {audio_params}")

    seq_num = 1
    timestamp = 0
    ssrc = generate_ssrc()

    packet_count = 0
    octet_count = 0
    rtcp_interval_packets = 10

    log_event("RTP SEND", "Starting RTP stream in WAV mode")

    try:
        for i, chunk in enumerate(audio_chunks):
            rtp_packet = build_rtp_packet(
                payload=chunk,
                seq_num=seq_num,
                timestamp=timestamp,
                ssrc=ssrc,
                payload_type=payload_type,
                marker=1 if i == 0 else 0
            )

            media_sock.sendto(rtp_packet, (dest_ip, dest_port))
            packet_count += 1
            octet_count += len(chunk)

            log_event(
                "RTP SEND",
                f"Packet={packet_count} Seq={seq_num} Timestamp={timestamp} "
                f"Bytes={len(chunk)} Codec={get_codec_name(payload_type)}"
            )

            if packet_count % rtcp_interval_packets == 0:
                send_rtcp_report(
                    rtcp_sock, dest_ip, dest_port, ssrc,
                    packet_count, octet_count, timestamp
                )

            seq_num += 1
            timestamp += get_timestamp_step(chunk, audio_params)

            sleep_ms = estimate_chunk_duration_ms(chunk, audio_params)
            time.sleep(sleep_ms / 1000.0)

        log_event("RTP SEND", "WAV streaming finished")
        send_rtcp_report(rtcp_sock, dest_ip, dest_port, ssrc, packet_count, octet_count, timestamp)

    except Exception as e:
        log_event("ERROR", f"Error during WAV RTP streaming: {e}")

    return packet_count, octet_count, timestamp


def stream_mic_audio(media_sock, rtcp_sock, dest_ip, dest_port, payload_type):
    input_stream = None

    audio_params = get_default_audio_params()
    chunk_frames = 160

    seq_num = 1
    timestamp = 0
    ssrc = generate_ssrc()

    packet_count = 0
    octet_count = 0
    rtcp_interval_packets = 10

    duration_ms = mic_chunk_duration_ms(chunk_frames, audio_params)
    duration_sec = duration_ms / 1000.0

    log_event("AUDIO", f"Using microphone input with params: {audio_params}")
    log_event("RTP SEND", "Starting RTP stream in microphone mode")
    log_event("AUDIO", "Recording duration: 10 seconds")

    try:
        input_stream = open_input_stream(audio_params, blocksize=chunk_frames)

        start_time = time.time()
        max_duration_seconds = 10

        first_packet = True

        while time.time() - start_time < max_duration_seconds:
            chunk = read_mic_chunk(input_stream, chunk_frames)

            rtp_packet = build_rtp_packet(
                payload=chunk,
                seq_num=seq_num,
                timestamp=timestamp,
                ssrc=ssrc,
                payload_type=payload_type,
                marker=1 if first_packet else 0
            )
            first_packet = False

            media_sock.sendto(rtp_packet, (dest_ip, dest_port))
            packet_count += 1
            octet_count += len(chunk)

            log_event(
                "RTP SEND",
                f"Packet={packet_count} Seq={seq_num} Timestamp={timestamp} "
                f"Bytes={len(chunk)} Codec={get_codec_name(payload_type)} Source=MIC"
            )

            if packet_count % rtcp_interval_packets == 0:
                send_rtcp_report(
                    rtcp_sock, dest_ip, dest_port, ssrc,
                    packet_count, octet_count, timestamp
                )

            seq_num += 1
            timestamp += chunk_frames

            time.sleep(duration_sec)

        log_event("RTP SEND", "Microphone streaming finished")
        send_rtcp_report(rtcp_sock, dest_ip, dest_port, ssrc, packet_count, octet_count, timestamp)

    except Exception as e:
        log_event("ERROR", f"Error during microphone RTP streaming: {e}")

    finally:
        close_audio_stream(input_stream)

    return packet_count, octet_count, timestamp


def main():
    receiver_name = input("Enter receiver name: ").strip()
    receiver_ip = input("Enter receiver IP: ").strip()

    caller_name = input("Enter caller name: ").strip()
    caller_ip = "127.0.0.1"
    caller_port = 5062

    mode = input("Choose audio source (wav/mic) [default: wav]: ").strip().lower()
    if not mode:
        mode = "wav"

    if not (is_file_mode(mode) or is_live_mode(mode)):
        log_event("ERROR", "Invalid mode. Use 'wav' or 'mic'.")
        return

    audio_filename = "sample.wav"
    if is_file_mode(mode):
        chosen_file = input("Enter WAV filename (default: sample.wav): ").strip()
        if chosen_file:
            audio_filename = chosen_file

    codec_input = input("Enter codec name (default: PCMU): ").strip()
    if not codec_input:
        codec_input = "PCMU"

    payload_type = get_payload_type(codec_input)

    call_id = generate_call_id()
    from_tag = generate_tag()
    cseq = 1

    to_line = ""
    from_line = ""
    dest_ip = None
    dest_port = None

    sip_sock = None
    media_sock = None
    rtcp_sock = None

    try:
        # ------------------------------------------------------------
        # SIP SOCKET
        # ------------------------------------------------------------
        sip_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sip_sock.bind((caller_ip, caller_port))
        sip_sock.settimeout(10)

        log_event("SYSTEM", f"Caller started on {caller_ip}:{caller_port}")
        log_event("SYSTEM", f"Audio mode selected: {mode}")
        log_event("SYSTEM", f"Codec selected: {codec_input} (PT={payload_type})")

        # ------------------------------------------------------------
        # SEND INVITE
        # ------------------------------------------------------------
        invite_msg = build_invite(
            receiver_ip=receiver_ip,
            caller_ip=caller_ip,
            caller_port=caller_port,
            receiver_name=receiver_name,
            caller_name=caller_name,
            call_id=call_id,
            cseq=cseq,
            from_tag=from_tag,
            rtp_port=RTP_PORT,
            codec_payload_type=payload_type
        )

        log_event("SIP", "Sending INVITE")
        print(invite_msg)
        sip_sock.sendto(invite_msg.encode(), (receiver_ip, SIP_PORT))

        # ------------------------------------------------------------
        # WAIT FOR SIP RESPONSE
        # ------------------------------------------------------------
        try:
            response, _ = sip_sock.recvfrom(MAX_BYTES)
        except socket.timeout:
            log_event("ERROR", "No SIP response received (timeout)")
            return

        decoded_response = response.decode(errors="ignore")
        log_event("SIP", "Received SIP response")
        print(decoded_response)

        start_line, headers, body = parse_sip_message(decoded_response)

        status_code, reason_phrase = get_sip_status_info(start_line)

        if status_code != 200:
            if status_code is not None:
                log_event("SIP", f"Call rejected: {status_code} {reason_phrase}")
            else:
                log_event("ERROR", "Invalid SIP response received")
            return

        log_event("SIP", "200 OK received successfully")

        if "To" in headers:
            to_line = f"To: {headers['To']}"
        if "From" in headers:
            from_line = f"From: {headers['From']}"

        # ------------------------------------------------------------
        # PARSE SDP
        # ------------------------------------------------------------
        sdp_info = parse_sdp(body)
        dest_ip = sdp_info["ip"]
        dest_port = sdp_info["port"]
        remote_codec = sdp_info["codec"]

        log_event("SDP", f"Destination IP: {dest_ip}")
        log_event("SDP", f"Destination RTP Port: {dest_port}")
        log_event("SDP", f"Remote codec/PT: {remote_codec}")

        if dest_ip is None or dest_port is None:
            log_event("ERROR", "SDP parse failure")
            return

        # ------------------------------------------------------------
        # SEND ACK
        # ------------------------------------------------------------
        ack_msg = build_ack(
            receiver_ip=receiver_ip,
            caller_ip=caller_ip,
            caller_port=caller_port,
            to_line=to_line,
            from_line=from_line,
            call_id=call_id,
            cseq=cseq
        )

        log_event("SIP", "Sending ACK")
        print(ack_msg)
        sip_sock.sendto(ack_msg.encode(), (receiver_ip, SIP_PORT))
        time.sleep(1)

        # ------------------------------------------------------------
        # MEDIA SOCKETS
        # ------------------------------------------------------------
        media_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rtcp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        media_sock.bind((caller_ip, RTP_PORT))
        rtcp_sock.bind((caller_ip, RTCP_PORT))

        # ------------------------------------------------------------
        # STREAM AUDIO
        # ------------------------------------------------------------
        if is_file_mode(mode):
            stream_wav_audio(
                media_sock=media_sock,
                rtcp_sock=rtcp_sock,
                dest_ip=dest_ip,
                dest_port=dest_port,
                audio_filename=audio_filename,
                payload_type=payload_type
            )
        else:
            stream_mic_audio(
                media_sock=media_sock,
                rtcp_sock=rtcp_sock,
                dest_ip=dest_ip,
                dest_port=dest_port,
                payload_type=payload_type
            )

        # ------------------------------------------------------------
        # SEND BYE
        # ------------------------------------------------------------
        cseq += 1
        bye_msg = build_bye(
            receiver_ip=receiver_ip,
            caller_ip=caller_ip,
            caller_port=caller_port,
            to_line=to_line,
            from_line=from_line,
            call_id=call_id,
            cseq=cseq
        )

        log_event("SIP", "Sending BYE")
        print(bye_msg)

        try:
            sip_sock.sendto(bye_msg.encode(), (receiver_ip, SIP_PORT))
            log_event("SIP", "BYE sent")
        except Exception as e:
            log_event("ERROR", f"Failed to send BYE: {e}")

        try:
            sip_sock.settimeout(5)
            bye_response, _ = sip_sock.recvfrom(MAX_BYTES)
            log_event("SIP", "Received response to BYE")
            print(bye_response.decode(errors="ignore"))
        except socket.timeout:
            log_event("ERROR", "No response to BYE received")
        except Exception as e:
            log_event("ERROR", f"Error while waiting for BYE response: {e}")

    finally:
        if media_sock:
            media_sock.close()
        if rtcp_sock:
            rtcp_sock.close()
        if sip_sock:
            sip_sock.close()

        log_event("SYSTEM", "Caller sockets closed. Caller finished.")


if __name__ == "__main__":
    main()