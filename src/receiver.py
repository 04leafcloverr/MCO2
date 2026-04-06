import socket
import threading
import time

from voip_utils import (
    build_200_ok,
    build_bye_ok,
    build_sip_error_response,
    parse_sip_message,
    parse_sdp,
    parse_rtp_packet,
    parse_rtcp_packet,
    save_wav_file,
    build_rtp_packet,
    build_rtcp_sender_report,
    generate_ssrc,
    log_event,
    should_reject_invite,
    get_default_audio_params,
    open_output_stream,
    play_audio_chunk,
    close_audio_stream,
    open_input_stream,
    read_mic_chunk,
)

# ------------------------------------------------------------
# NETWORK CONFIGURATION
# ------------------------------------------------------------
SIP_IP = "0.0.0.0"
SIP_PORT = 5060
RTP_IP = "0.0.0.0"
RTP_PORT = 5006
RTCP_PORT = RTP_PORT + 1
MAX_BYTES = 4096


# ------------------------------------------------------------
# DETECT LOCAL IP
# ------------------------------------------------------------
def detect_local_ip(target_ip: str = "8.8.8.8") -> str:
    # Get local LAN IP address
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


# ------------------------------------------------------------
# CHOOSE RECEIVER IP FOR SDP
# ------------------------------------------------------------
def choose_receiver_ip_for_sdp() -> str:
    # Choose IP to advertise in SDP
    choice = input("Enter receiver IP to advertise [default: auto-detect]: ").strip()
    if choice:
        return choice
    return detect_local_ip()


# ------------------------------------------------------------
# SEND RTCP REPORT
# ------------------------------------------------------------
def send_rtcp_report(rtcp_sock, dest_ip, dest_port, ssrc, packet_count, octet_count, timestamp):
    # Send RTCP sender report
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


# ------------------------------------------------------------
# RECEIVE RTCP REPORTS
# ------------------------------------------------------------
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


# ------------------------------------------------------------
# STREAM MICROPHONE AUDIO OVER RTP
# ------------------------------------------------------------
def stream_mic_audio(media_sock, rtcp_sock, dest_ip, dest_port, stop_event, payload_type=97):
    # Send live microphone audio to caller
    input_stream = None

    audio_params = get_default_audio_params()
    chunk_frames = 640

    seq_num = 1
    timestamp = 0
    ssrc = generate_ssrc()

    packet_count = 0
    octet_count = 0
    rtcp_interval_packets = 10

    log_event("AUDIO", f"Receiver microphone input params: {audio_params}")
    log_event("RTP SEND", "Receiver microphone RTP streaming started")

    try:
        # Open microphone input stream
        input_stream = open_input_stream(audio_params, blocksize=chunk_frames)
        first_packet = True

        while not stop_event.is_set():
            # Read one mic chunk
            chunk = read_mic_chunk(input_stream, chunk_frames)

            # Build RTP packet
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

            # Send RTCP periodically
            if packet_count % rtcp_interval_packets == 0:
                send_rtcp_report(
                    rtcp_sock, dest_ip, dest_port, ssrc,
                    packet_count, octet_count, timestamp
                )

            seq_num += 1
            timestamp += chunk_frames

        log_event("RTP SEND", "Receiver microphone streaming finished")
        send_rtcp_report(rtcp_sock, dest_ip, dest_port, ssrc, packet_count, octet_count, timestamp)

    except Exception as e:
        log_event("ERROR", f"Error during receiver microphone RTP streaming: {e}")

    finally:
        close_audio_stream(input_stream)


# ------------------------------------------------------------
# MAIN RECEIVER FLOW
# ------------------------------------------------------------
def main():
    # Get receiver settings
    receiver_ip = choose_receiver_ip_for_sdp()
    receiver_name = input("Enter receiver name: ").strip()

    playback_choice = input("Enable live speaker playback? (y/n) [default: y]: ").strip().lower()
    if not playback_choice:
        playback_choice = "y"
    live_playback = playback_choice == "y"

    send_mic_choice = input("Enable two-way microphone send from receiver? (y/n) [default: y]: ").strip().lower()
    if not send_mic_choice:
        send_mic_choice = "y"
    send_mic_back = send_mic_choice == "y"

    via_line = ""
    to_line = ""
    from_line = ""
    call_id_line = ""
    cseq_line = ""

    sip_sock = None
    media_sock = None
    rtcp_sock = None
    output_stream = None

    received_audio_chunks = []
    received_audio_params = get_default_audio_params()

    stop_event = threading.Event()
    rtcp_thread = None
    sender_thread = None

    remote_ip = None
    remote_port = None
    remote_codec = None

    try:
        # Create SIP socket
        sip_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sip_sock.bind((SIP_IP, SIP_PORT))

        log_event("SYSTEM", f"Receiver SIP listening on {SIP_IP}:{SIP_PORT}")
        log_event("SYSTEM", f"Receiver advertises IP: {receiver_ip}")
        log_event("SYSTEM", f"Live playback enabled: {live_playback}")
        log_event("SYSTEM", f"Two-way microphone send enabled: {send_mic_back}")

        # ------------------------------------------------------------
        # WAIT FOR INVITE
        # ------------------------------------------------------------
        log_event("SIP", "Waiting for INVITE")
        invite_message, sip_addr = sip_sock.recvfrom(MAX_BYTES)

        decoded_invite = invite_message.decode(errors="ignore")
        log_event("SIP", "INVITE received")
        print(decoded_invite)

        start_line, headers, body = parse_sip_message(decoded_invite)

        if not start_line.startswith("INVITE"):
            log_event("ERROR", "Received message is not an INVITE")
            return

        # Extract SIP headers
        if "Via" in headers:
            via_line = f"Via: {headers['Via']}"
        if "To" in headers:
            to_line = f"To: {headers['To']}"
        if "From" in headers:
            from_line = f"From: {headers['From']}"
        if "Call-ID" in headers:
            call_id_line = f"Call-ID: {headers['Call-ID']}"
        if "CSeq" in headers:
            cseq_line = f"CSeq: {headers['CSeq']}"

        # ------------------------------------------------------------
        # CHECK IF INVITE SHOULD BE REJECTED
        # ------------------------------------------------------------
        reject, status_code, reason_phrase = should_reject_invite(receiver_name, receiver_ip)

        if reject:
            error_response = build_sip_error_response(
                status_code=status_code,
                reason_phrase=reason_phrase,
                via_line=via_line,
                to_line=to_line,
                from_line=from_line,
                call_id_line=call_id_line,
                cseq_line=cseq_line
            )
            log_event("SIP", f"Rejecting INVITE with {status_code} {reason_phrase}")
            print(error_response)
            sip_sock.sendto(error_response.encode(), sip_addr)
            return

        # ------------------------------------------------------------
        # PARSE SDP
        # ------------------------------------------------------------
        remote_sdp = parse_sdp(body)
        remote_ip = remote_sdp["ip"]
        remote_port = remote_sdp["port"]
        remote_codec = remote_sdp["codec"]

        log_event("SDP", f"Remote media IP: {remote_ip}")
        log_event("SDP", f"Remote media port: {remote_port}")
        log_event("SDP", f"Remote codec/PT: {remote_codec}")

        codec_payload_type = int(remote_codec) if remote_codec is not None else 97

        # ------------------------------------------------------------
        # SEND 200 OK
        # ------------------------------------------------------------
        response = build_200_ok(
            via_line=via_line,
            to_line=to_line,
            from_line=from_line,
            call_id_line=call_id_line,
            cseq_line=cseq_line,
            receiver_ip=receiver_ip,
            rtp_port=RTP_PORT,
            codec_payload_type=codec_payload_type,
            session_name="VoIP Call"
        )

        log_event("SIP", "Sending 200 OK")
        print(response)
        sip_sock.sendto(response.encode(), sip_addr)

        # ------------------------------------------------------------
        # WAIT FOR ACK
        # ------------------------------------------------------------
        try:
            sip_sock.settimeout(20)
            ack_message, sip_addr = sip_sock.recvfrom(MAX_BYTES)
        except socket.timeout:
            log_event("ERROR", "ACK not received (timeout)")
            return

        decoded_ack = ack_message.decode(errors="ignore")
        log_event("SIP", "ACK received")
        print(decoded_ack)

        ack_start_line, _, _ = parse_sip_message(decoded_ack)

        if not ack_start_line.startswith("ACK"):
            log_event("ERROR", "Invalid ACK")
            return

        log_event("SIP", "Call established")

        # ------------------------------------------------------------
        # CREATE RTP AND RTCP SOCKETS
        # ------------------------------------------------------------
        media_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        media_sock.bind((RTP_IP, RTP_PORT))
        media_sock.settimeout(1.0)

        rtcp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rtcp_sock.bind((RTP_IP, RTCP_PORT))

        log_event("RTP RECV", f"Receiver RTP listening on {RTP_IP}:{RTP_PORT}")
        log_event("RTCP RECV", f"Receiver RTCP listening on {RTP_IP}:{RTCP_PORT}")

        # ------------------------------------------------------------
        # OPEN SPEAKER OUTPUT
        # ------------------------------------------------------------
        if live_playback:
            try:
                output_stream = open_output_stream(received_audio_params, blocksize=640)
                log_event("AUDIO", "Live speaker output stream opened")
            except Exception as e:
                log_event("ERROR", f"Failed to open speaker output stream: {e}")
                live_playback = False

        # ------------------------------------------------------------
        # START RTCP THREAD
        # ------------------------------------------------------------
        rtcp_thread = threading.Thread(
            target=receive_rtcp,
            args=(rtcp_sock, stop_event),
            daemon=True
        )
        rtcp_thread.start()

        # ------------------------------------------------------------
        # START TWO-WAY MIC SENDING
        # ------------------------------------------------------------
        if send_mic_back and remote_ip and remote_port:
            sender_thread = threading.Thread(
                target=stream_mic_audio,
                args=(media_sock, rtcp_sock, remote_ip, remote_port, stop_event, codec_payload_type),
                daemon=True
            )
            sender_thread.start()
            log_event("SYSTEM", "Receiver two-way microphone sending started")

        bye_received = False
        expected_total_packets = None
        packet_counter = 0
        last_rtp_time = time.time()

        # ------------------------------------------------------------
        # MAIN MEDIA LOOP
        # ------------------------------------------------------------
        while True:
            try:
                packet, rtp_addr = media_sock.recvfrom(MAX_BYTES)
                rtp_info = parse_rtp_packet(packet)

                packet_counter += 1
                payload = rtp_info["payload"]
                received_audio_chunks.append(payload)
                last_rtp_time = time.time()

                # Log every 50 packets
                if packet_counter % 50 == 0:
                    log_event(
                        "RTP RECV",
                        f"Packet={packet_counter} From={rtp_addr} "
                        f"Seq={rtp_info['sequence_number']} "
                        f"Timestamp={rtp_info['timestamp']} "
                        f"Bytes={len(payload)} "
                        f"Codec={rtp_info['codec_name']}"
                    )

                # Play received audio
                if live_playback and output_stream is not None:
                    try:
                        play_audio_chunk(output_stream, payload)
                    except Exception as e:
                        log_event("AUDIO ERROR", f"Failed to play audio chunk: {e}")

            except socket.timeout:
                pass
            except Exception as e:
                log_event("RTP ERROR", str(e))

            try:
                sip_sock.settimeout(0.001)
                sip_message, sip_addr = sip_sock.recvfrom(MAX_BYTES)
                decoded_sip = sip_message.decode(errors="ignore")

                sip_start_line, sip_headers, _ = parse_sip_message(decoded_sip)

                # Check for BYE
                if sip_start_line.startswith("BYE"):
                    log_event("SIP", "BYE received")
                    print(decoded_sip)

                    if "Total-RTP-Packets" in sip_headers:
                        try:
                            expected_total_packets = int(sip_headers["Total-RTP-Packets"])
                            log_event("SIP", f"Expected total RTP packets from caller: {expected_total_packets}")
                        except ValueError:
                            expected_total_packets = None

                    current_via = f"Via: {sip_headers['Via']}" if "Via" in sip_headers else via_line
                    current_to = f"To: {sip_headers['To']}" if "To" in sip_headers else to_line
                    current_from = f"From: {sip_headers['From']}" if "From" in sip_headers else from_line
                    current_call_id = f"Call-ID: {sip_headers['Call-ID']}" if "Call-ID" in sip_headers else call_id_line
                    current_cseq = f"CSeq: {sip_headers['CSeq']}" if "CSeq" in sip_headers else cseq_line

                    bye_ok = build_bye_ok(
                        via_line=current_via,
                        to_line=current_to,
                        from_line=current_from,
                        call_id_line=current_call_id,
                        cseq_line=current_cseq
                    )

                    log_event("SIP", "Sending 200 OK for BYE")
                    print(bye_ok)
                    sip_sock.sendto(bye_ok.encode(), sip_addr)

                    bye_received = True
                    stop_event.set()

            except socket.timeout:
                pass
            except Exception as e:
                log_event("SIP ERROR", str(e))

            if bye_received and expected_total_packets is not None and packet_counter >= expected_total_packets:
                log_event("SYSTEM", "All expected RTP packets received. Closing media loop.")
                break

            if bye_received and (time.time() - last_rtp_time > 2.0):
                log_event("SYSTEM", "No more RTP packets after BYE. Closing media loop.")
                break

        if sender_thread and sender_thread.is_alive():
            sender_thread.join(timeout=2)

        # ------------------------------------------------------------
        # SAVE RECEIVED AUDIO
        # ------------------------------------------------------------
        if received_audio_chunks:
            output_filename = "received_output.wav"
            try:
                save_wav_file(output_filename, received_audio_chunks, received_audio_params)
                log_event("AUDIO", f"Received audio saved to: {output_filename}")
                log_event("AUDIO", f"Total received chunks: {len(received_audio_chunks)}")
            except Exception as e:
                log_event("ERROR", f"Failed to save received audio: {e}")
        else:
            log_event("ERROR", "No audio payload was received")

    finally:
        stop_event.set()

        if rtcp_thread and rtcp_thread.is_alive():
            rtcp_thread.join(timeout=1)

        if sender_thread and sender_thread.is_alive():
            sender_thread.join(timeout=1)

        close_audio_stream(output_stream)

        # Close all sockets
        if media_sock:
            media_sock.close()
        if rtcp_sock:
            rtcp_sock.close()
        if sip_sock:
            sip_sock.close()

        log_event("SYSTEM", "Receiver sockets closed. Receiver finished.")


if __name__ == "__main__":
    main()