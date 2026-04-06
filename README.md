# Real-Time Audio Streaming over IP (VoIP Simulation)
NSCOM01 – MCO2 (Term 2, AY 2025–2026)



## Group Members
- Besa, April Denise B.
- Martinez, Gabrielle P.



## Project Overview

This project implements a simplified VoIP (Voice over IP) system using:

- SIP (Session Initiation Protocol) for call setup and teardown
- SDP (Session Description Protocol) for media negotiation
- RTP (Real-time Transport Protocol) for audio streaming
- RTCP (RTP Control Protocol) for transmission statistics

The system supports both WAV file streaming and live microphone streaming. It can be tested on a single machine using localhost or across two machines on the same local network. The updated version also supports two-way live microphone communication, allowing both the caller and receiver to speak and hear each other in real time.



## Project Structure

    project-folder/
    │
    ├── caller.py              # SIP caller + RTP sender/receiver
    ├── receiver.py            # SIP receiver + RTP sender/receiver
    ├── voip_utils.py          # Helper functions (SIP, RTP, RTCP, audio)
    ├── sample.wav             # Sample audio file for testing
    ├── received_output.wav    # Output file generated after receiving audio
    └── README.md



## Requirements

Make sure the following are installed:

- Python 3.x
- Required libraries:

    pip install sounddevice numpy

Note: Microphone and live playback features require `sounddevice` and `numpy`.



## Features

- SIP-based call setup using INVITE, 200 OK, ACK, and BYE
- SDP-based media negotiation
- RTP audio streaming
- RTCP sender reports for basic transmission statistics
- WAV file audio streaming
- Live microphone audio streaming
- Two-way live microphone communication
- Audio playback through speaker during reception
- Saving received audio into WAV output files
- Works on one machine or two machines within the same LAN



## How to Run the Program

### Step 1: Start the Receiver

Run:

    python receiver.py

You will be asked to enter:

- Receiver IP to advertise
  - Use `127.0.0.1` for same-machine testing
  - Use the receiver's LAN IP for two-machine testing
- Receiver name

Optional settings:
- Enable live speaker playback (`y` or `n`)
- Enable two-way microphone send from receiver (`y` or `n`)

### Step 2: Start the Caller

Run:

    python caller.py

You will be asked to enter:

- Receiver name
- Receiver IP
  - Use `127.0.0.1` for same-machine testing
  - Use the receiver's LAN IP for two-machine testing
- Caller name
- Caller IP to advertise
  - Press Enter to use the detected default IP
- Audio source
  - `wav` to send a WAV file
  - `mic` to use live microphone input

If `wav` mode is selected:
- Enter WAV filename (default: `sample.wav`)

You will also be asked for:
- Codec name
  - Default is `PCMU` for WAV mode
  - Default is `PCM` for microphone mode

### Step 3: During the Call

You should observe the following sequence:

- SIP signaling:
  - INVITE
  - 200 OK
  - ACK
- RTP audio transmission
- RTCP report exchange
- BYE
- 200 OK for BYE

For microphone mode:
- Both sides can speak and hear audio in real time if two-way microphone sending is enabled
- Press **ENTER on the caller side** to end the live microphone session



## Test Cases and Expected Behavior

### Test Case 1: SIP Handshake Verification

Setup:
- Start `receiver.py`
- Start `caller.py`

Expected behavior:
- Caller sends INVITE
- Receiver sends 200 OK
- Caller sends ACK
- Receiver logs that the call is established

Expected output logs:
- "Sending INVITE"
- "INVITE received"
- "Sending 200 OK"
- "200 OK received successfully"
- "Sending ACK"
- "ACK received"
- "Call established"

### Test Case 2: WAV File Streaming on One Machine

Setup:
- Start receiver and caller on the same computer
- Use `127.0.0.1` as the receiver IP
- On the receiver, advertise `127.0.0.1`
- On the caller, select `wav` mode
- Use `sample.wav`

Expected behavior:
- Caller sends RTP packets containing WAV audio
- Receiver receives the audio correctly
- Receiver can play the audio if playback is enabled
- Receiver saves the output as `received_output.wav`
- Caller may also save returned audio as `caller_received_output.wav` if media is received back

### Test Case 3: WAV File Streaming on Two Machines

Setup:
- Start receiver on one machine
- Start caller on another machine
- Caller uses the receiver's LAN IP
- Receiver advertises its LAN IP
- Caller selects `wav` mode

Expected behavior:
- SIP signaling succeeds
- RTP audio is transmitted from caller to receiver
- Receiver plays and saves the received audio
- RTCP reports are exchanged

### Test Case 4: One-Way Microphone Streaming

Setup:
- Caller selects `mic` mode
- Receiver enables live playback
- Receiver disables two-way microphone send

Expected behavior:
- Caller microphone audio is sent to receiver in real time
- Receiver plays the audio through the speaker
- RTP packets continue until caller presses ENTER
- Receiver saves the received audio to `received_output.wav`

### Test Case 5: Two-Way Live Microphone Communication on One Machine

Setup:
- Use `127.0.0.1` for both sides
- Receiver advertises `127.0.0.1`
- Caller selects `mic`
- Receiver enables playback
- Receiver enables two-way microphone send

Expected behavior:
- Both caller and receiver can talk and hear each other
- RTP packets flow in both directions
- RTCP reports are exchanged
- Slight delay or echo may happen because both ends are on the same machine
- Press ENTER on caller to end the session

### Test Case 6: Two-Way Live Microphone Communication on Two Machines

Setup:
- Caller and receiver are on different machines on the same LAN
- Caller uses receiver's LAN IP
- Receiver advertises its LAN IP
- Caller selects `mic`
- Receiver enables playback
- Receiver enables two-way microphone send

Expected behavior:
- Caller and receiver can communicate in real time
- Audio is transmitted in both directions
- Live playback works on both sides
- RTP and RTCP logs are shown during the session
- Press ENTER on caller to terminate the call

### Test Case 7: Call Termination

Setup:
- Start a call in either `wav` or `mic` mode
- End the session normally

Expected behavior:
- Caller sends BYE
- Receiver receives BYE
- Receiver sends 200 OK for BYE
- Both sides stop media activity
- Sockets close properly

Expected output logs:
- "Sending BYE"
- "BYE received"
- "Sending 200 OK for BYE"
- "Received response to BYE"
- "Caller sockets closed. Caller finished."
- "Receiver sockets closed. Receiver finished."

### Test Case 8: RTCP Monitoring

Setup:
- Run either WAV mode or mic mode long enough for RTCP reports to be sent

Expected behavior:
- RTCP sender reports appear periodically
- Logs show:
  - packet count
  - octet count
  - RTP timestamp



## Assumptions

- Both clients are run either on the same machine or on two machines within the same local network
- No NAT traversal is required
- No SIP proxy or registrar is used
- Communication is direct and peer-to-peer
- Audio devices are available and accessible by Python
- Required libraries are correctly installed



## Limitations

- Uses UDP, so delivery is not guaranteed
- No packet loss recovery or retransmission is implemented
- No jitter buffer is implemented
- Basic codec handling only
- No encryption or authentication
- Audio quality and delay depend on device performance and system audio configuration
- Same-machine microphone tests may produce echo or feedback if speakers are used instead of headphones



## Notes for Demonstration

- Use `127.0.0.1` for both caller and receiver during single-machine testing
- For single-machine testing, make sure the receiver also advertises `127.0.0.1`
- Use LAN IP addresses for two-machine testing
- Ensure the required UDP ports are not blocked by the firewall:
  - SIP: 5060
  - Caller RTP: 5004
  - Caller RTCP: 5005
  - Receiver RTP: 5006
  - Receiver RTCP: 5007
- Use headphones during microphone mode to reduce echo and feedback
- If live microphone features do not work, check microphone permissions in the operating system
- A slight delay in live audio is normal in this simplified implementation



## References

- RFC 3261 – SIP: Session Initiation Protocol
- RFC 4566 – SDP: Session Description Protocol
- RFC 3550 – RTP: Real-Time Transport Protocol
- RFC 3551 – RTP Profile for Audio