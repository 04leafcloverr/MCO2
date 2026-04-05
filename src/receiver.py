import socket
import threading

from voip_utils import (
    build_200_ok,
    build_bye_ok,
    build_sip_error_response,
    parse_sip_message,
    parse_sdp,
    parse_rtp_packet,
    parse_rtcp_packet,
    save_wav_file,
    log_event,
    should_reject_invite,
    get_codec_name,
    get_default_audio_params,
    open_output_stream,
    play_audio_chunk,
    close_audio_stream
)

SIP_IP = "0.0.0.0"
SIP_PORT = 5060
RTP_PORT = 5006
RTCP_PORT = RTP_PORT + 1
MAX_BYTES = 4096


def receive_rtcp(rtcp_sock, stop_event):
    rtcp_sock.settimeout(1.0)

    while not stop_event.is_set():
        try:
            packet, addr = rtcp_sock.recvfrom(MAX_BYTES)
            rtcp_info = parse_rtcp_packet(packet)

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


def main():
    receiver_ip = input("Enter receiver IP: ").strip()
    receiver_name = input("Enter receiver name: ").strip()

    playback_choice = input("Enable live speaker playback? (y/n) [default: n]: ").strip().lower()
    live_playback = playback_choice == "y"

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

    stop_rtcp_event = threading.Event()
    rtcp_thread = None

    try:
        # ------------------------------------------------------------
        # SIP SOCKET
        # ------------------------------------------------------------
        sip_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sip_sock.bind((SIP_IP, SIP_PORT))
        log_event("SYSTEM", f"Receiver listening for SIP on {SIP_IP}:{SIP_PORT}")
        log_event("SYSTEM", f"Live playback enabled: {live_playback}")

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

        # Extract SIP header lines
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
        # OPTIONAL INVITE VALIDATION / REJECTION
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
        # PARSE REMOTE SDP
        # ------------------------------------------------------------
        remote_sdp = parse_sdp(body)
        remote_ip = remote_sdp["ip"]
        remote_port = remote_sdp["port"]
        remote_codec = remote_sdp["codec"]

        log_event("SDP", f"Remote media IP: {remote_ip}")
        log_event("SDP", f"Remote media port: {remote_port}")
        log_event("SDP", f"Remote codec/PT: {remote_codec}")

        # ------------------------------------------------------------
        # SEND 200 OK
        # ------------------------------------------------------------
        codec_payload_type = int(remote_codec) if remote_codec is not None else 0

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
        # MEDIA SOCKETS
        # ------------------------------------------------------------
        media_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        media_sock.bind((SIP_IP, RTP_PORT))
        media_sock.settimeout(2)

        rtcp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rtcp_sock.bind((SIP_IP, RTCP_PORT))

        log_event("RTP RECV", f"Listening on port {RTP_PORT}")
        log_event("RTCP RECV", f"Listening on port {RTCP_PORT}")

        # ------------------------------------------------------------
        # OPTIONAL LIVE PLAYBACK SETUP
        # ------------------------------------------------------------
        if live_playback:
            try:
                output_stream = open_output_stream(received_audio_params, blocksize=160)
                log_event("AUDIO", "Live speaker output stream opened")
            except Exception as e:
                log_event("ERROR", f"Failed to open speaker output stream: {e}")
                live_playback = False

        # ------------------------------------------------------------
        # START RTCP THREAD
        # ------------------------------------------------------------
        rtcp_thread = threading.Thread(
            target=receive_rtcp,
            args=(rtcp_sock, stop_rtcp_event),
            daemon=True
        )
        rtcp_thread.start()

        # ------------------------------------------------------------
        # RECEIVE RTP UNTIL BYE ARRIVES
        # ------------------------------------------------------------
        bye_received = False
        packet_counter = 0

        while not bye_received:
            try:
                packet, rtp_addr = media_sock.recvfrom(MAX_BYTES)
                rtp_info = parse_rtp_packet(packet)

                packet_counter += 1
                payload = rtp_info["payload"]
                received_audio_chunks.append(payload)

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
                pass
            except Exception as e:
                log_event("RTP ERROR", str(e))

            # --------------------------------------------------------
            # CHECK FOR SIP BYE
            # --------------------------------------------------------
            try:
                sip_sock.settimeout(0.2)
                sip_message, sip_addr = sip_sock.recvfrom(MAX_BYTES)
                decoded_sip = sip_message.decode(errors="ignore")

                sip_start_line, sip_headers, _ = parse_sip_message(decoded_sip)

                if sip_start_line.startswith("BYE"):
                    log_event("SIP", "BYE received")
                    print(decoded_sip)

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

            except socket.timeout:
                pass
            except Exception as e:
                log_event("SIP ERROR", str(e))

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
        stop_rtcp_event.set()

        if rtcp_thread and rtcp_thread.is_alive():
            rtcp_thread.join(timeout=1)

        close_audio_stream(output_stream)

        if media_sock:
            media_sock.close()
        if rtcp_sock:
            rtcp_sock.close()
        if sip_sock:
            sip_sock.close()

        log_event("SYSTEM", "Receiver sockets closed. Receiver finished.")


if __name__ == "__main__":
    main()