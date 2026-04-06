import socket
import time
import threading

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
    parse_rtp_packet,
    parse_rtcp_packet,
    save_wav_file,
    log_event,
    is_live_mode,
    is_file_mode,
    get_default_audio_params,
    open_input_stream,
    read_mic_chunk,
    close_audio_stream,
    open_output_stream,
    play_audio_chunk,
)


SIP_BIND_IP = "0.0.0.0"
SIP_PORT = 5060
CALLER_SIP_PORT = 5062

RTP_BIND_IP = "0.0.0.0"
RTP_PORT = 5004
RTCP_PORT = RTP_PORT + 1

MAX_BYTES = 4096


def detect_local_ip(target_ip: str = "8.8.8.8") -> str:
    """
    Best-effort LAN IP detection.
    Works even without sending actual data.
    """
    test_sock = None
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        test_sock.connect((target_ip, 80))
        return test_sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        if test_sock:
            test_sock.close()


def choose_advertised_ip(receiver_ip: str) -> str:
    """
    If receiver is localhost, advertise localhost.
    Otherwise advertise the machine's LAN IP.
    """
    localhost_values = {"127.0.0.1", "localhost"}

    if receiver_ip.strip().lower() in localhost_values:
        return "127.0.0.1"

    return detect_local_ip(receiver_ip)


def send_rtcp_report(rtcp_sock, dest_ip, dest_port, ssrc, packet_count, octet_count, timestamp):
    try:
        rtcp_packet = build_rtcp_sender_report(
            ssrc=ssrc,
            packet_count=packet_count,
            octet_count=octet_count,
            rtp_timestamp=timestamp
        )
        rtcp_sock.sendto(rtcp_packet, (dest_ip, dest_port + 1))

        if packet_count % 50 == 0 and packet_count > 0:
            log_event(
                "RTCP SEND",
                f"Sender Report sent | Packets={packet_count} Octets={octet_count} RTP_TS={timestamp}"
            )
    except Exception as e:
        log_event("ERROR", f"Failed to send RTCP Sender Report: {e}")


def receive_rtcp(rtcp_sock, stop_event):
    rtcp_sock.settimeout(1.0)
    rtcp_counter = 0

    while not stop_event.is_set():
        try:
            packet, addr = rtcp_sock.recvfrom(MAX_BYTES)
            rtcp_info = parse_rtcp_packet(packet)
            rtcp_counter += 1

            if rtcp_counter % 10 == 0:
                log_event(
                    "RTCP RECV",
                    f"From={addr} SSRC={rtcp_info['ssrc']} "
                    f"Packets={rtcp_info['packet_count']} "
                    f"Octets={rtcp_info['octet_count']} "
                    f"RTP_TS={rtcp_info['rtp_timestamp']}"
                )
        except socket.timeout:
            continue
        except Exception as e:
            log_event("RTCP ERROR", str(e))


def receive_rtp_audio(media_sock, stop_event, live_playback=True, save_filename="caller_received_output.wav"):
    received_audio_chunks = []
    received_audio_params = get_default_audio_params()
    output_stream = None
    packet_counter = 0

    try:
        if live_playback:
            try:
                output_stream = open_output_stream(received_audio_params, blocksize=640)
                log_event("AUDIO", "Caller speaker output stream opened")
            except Exception as e:
                log_event("ERROR", f"Failed to open speaker output stream: {e}")
                live_playback = False

        media_sock.settimeout(1.0)
        log_event("RTP RECV", "Caller RTP receive thread started")

        while not stop_event.is_set():
            try:
                packet, rtp_addr = media_sock.recvfrom(MAX_BYTES)
                rtp_info = parse_rtp_packet(packet)

                packet_counter += 1
                payload = rtp_info["payload"]
                received_audio_chunks.append(payload)

                if packet_counter % 50 == 0:
                    log_event(
                        "RTP RECV",
                        f"Packet={packet_counter} From={rtp_addr} "
                        f"Seq={rtp_info['sequence_number']} "
                        f"Timestamp={rtp_info['timestamp']} "
                        f"Bytes={len(payload)} "
                        f"Codec={rtp_info['codec_name']}"
                    )

                if live_playback and output_stream is not None:
                    try:
                        play_audio_chunk(output_stream, payload)
                    except Exception as e:
                        log_event("AUDIO ERROR", f"Failed to play audio chunk: {e}")

            except socket.timeout:
                continue
            except Exception as e:
                log_event("RTP ERROR", str(e))

    finally:
        close_audio_stream(output_stream)

        if received_audio_chunks:
            try:
                save_wav_file(save_filename, received_audio_chunks, received_audio_params)
                log_event("AUDIO", f"Caller received audio saved to: {save_filename}")
                log_event("AUDIO", f"Caller total received chunks: {len(received_audio_chunks)}")
            except Exception as e:
                log_event("ERROR", f"Failed to save caller received audio: {e}")
        else:
            log_event("AUDIO", "Caller received no RTP audio to save")

        log_event("RTP RECV", "Caller RTP receive thread finished")


def stream_wav_audio(media_sock, rtcp_sock, dest_ip, dest_port, audio_filename, payload_type):
    try:
        audio_chunks, audio_params = read_wav_chunks(audio_filename, chunk_size=640)
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

            if packet_count % 50 == 0:
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


def stream_mic_audio(media_sock, rtcp_sock, dest_ip, dest_port, payload_type, stop_event):
    input_stream = None

    audio_params = get_default_audio_params()
    chunk_frames = 640

    seq_num = 1
    timestamp = 0
    ssrc = generate_ssrc()

    packet_count = 0
    octet_count = 0
    rtcp_interval_packets = 10

    log_event("AUDIO", f"Using microphone input with params: {audio_params}")
    log_event("RTP SEND", "Starting RTP stream in microphone mode")

    try:
        input_stream = open_input_stream(audio_params, blocksize=chunk_frames)
        first_packet = True

        log_event("RTP SEND", "Microphone RTP streaming in progress...")

        while not stop_event.is_set():
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

            if packet_count % rtcp_interval_packets == 0:
                send_rtcp_report(
                    rtcp_sock, dest_ip, dest_port, ssrc,
                    packet_count, octet_count, timestamp
                )

            seq_num += 1
            timestamp += chunk_frames

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

    auto_ip = choose_advertised_ip(receiver_ip)
    caller_ip_input = input(f"Enter caller IP to advertise [default: {auto_ip}]: ").strip()
    caller_ip = caller_ip_input if caller_ip_input else auto_ip
    caller_port = CALLER_SIP_PORT

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

    default_codec = "PCM" if is_live_mode(mode) else "PCMU"
    codec_input = input(f"Enter codec name (default: {default_codec}): ").strip()
    if not codec_input:
        codec_input = default_codec

    payload_type = get_payload_type(codec_input)

    if is_live_mode(mode) and codec_input.upper() == "PCMU":
        log_event(
            "AUDIO WARN",
            "Microphone mode works better with PCM because the captured mic data is raw PCM."
        )

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

    rtp_receive_thread = None
    rtcp_receive_thread = None
    stop_event = threading.Event()

    try:
        sip_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sip_sock.bind((SIP_BIND_IP, caller_port))
        sip_sock.settimeout(10)

        log_event("SYSTEM", f"Caller SIP listening on {SIP_BIND_IP}:{caller_port}")
        log_event("SYSTEM", f"Caller advertises IP: {caller_ip}")
        log_event("SYSTEM", f"Audio mode selected: {mode}")
        log_event("SYSTEM", f"Codec selected: {codec_input} (PT={payload_type})")

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
        time.sleep(0.5)

        media_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rtcp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        media_sock.bind((RTP_BIND_IP, RTP_PORT))
        rtcp_sock.bind((RTP_BIND_IP, RTCP_PORT))

        log_event("RTP RECV", f"Caller RTP listening on {RTP_BIND_IP}:{RTP_PORT}")
        log_event("RTCP RECV", f"Caller RTCP listening on {RTP_BIND_IP}:{RTCP_PORT}")

        rtp_receive_thread = threading.Thread(
            target=receive_rtp_audio,
            args=(media_sock, stop_event, True, "caller_received_output.wav"),
            daemon=True
        )
        rtp_receive_thread.start()

        rtcp_receive_thread = threading.Thread(
            target=receive_rtcp,
            args=(rtcp_sock, stop_event),
            daemon=True
        )
        rtcp_receive_thread.start()

        if is_file_mode(mode):
            total_packets_sent, _, _ = stream_wav_audio(
                media_sock=media_sock,
                rtcp_sock=rtcp_sock,
                dest_ip=dest_ip,
                dest_port=dest_port,
                audio_filename=audio_filename,
                payload_type=payload_type
            )
            log_event("SYSTEM", "Finished sending WAV audio. Waiting briefly for incoming media...")
            time.sleep(3)

        else:
            def wait_for_stop():
                input()
                stop_event.set()

            print("\n[INFO] Two-way microphone mode started.")
            print("[INFO] Both sides can speak and hear audio in real time.")
            print("[INFO] Press ENTER on caller to end the call.\n")

            threading.Thread(target=wait_for_stop, daemon=True).start()

            total_packets_sent, _, _ = stream_mic_audio(
                media_sock=media_sock,
                rtcp_sock=rtcp_sock,
                dest_ip=dest_ip,
                dest_port=dest_port,
                payload_type=payload_type,
                stop_event=stop_event
            )

        stop_event.set()
        time.sleep(0.5)

        cseq += 1
        bye_msg = build_bye(
            receiver_ip=receiver_ip,
            caller_ip=caller_ip,
            caller_port=caller_port,
            to_line=to_line,
            from_line=from_line,
            call_id=call_id,
            cseq=cseq,
            total_rtp_packets=total_packets_sent
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

        if rtp_receive_thread and rtp_receive_thread.is_alive():
            rtp_receive_thread.join(timeout=2)

        if rtcp_receive_thread and rtcp_receive_thread.is_alive():
            rtcp_receive_thread.join(timeout=2)

    finally:
        stop_event.set()

        if media_sock:
            media_sock.close()
        if rtcp_sock:
            rtcp_sock.close()
        if sip_sock:
            sip_sock.close()

        log_event("SYSTEM", "Caller sockets closed. Caller finished.")


if __name__ == "__main__":
    main()