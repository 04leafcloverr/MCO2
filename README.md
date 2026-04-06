## Project Structure

```
project-folder/
│
├── caller.py              # SIP caller + RTP sender
├── receiver.py            # SIP receiver + RTP listener
├── voip_utils.py          # Helper functions (SIP, RTP, RTCP, audio)
├── sample.wav             # Sample audio file for testing
├── received_output.wav    # Output file (generated after receiving)
├── README.md
```



## Requirements

Make sure the following are installed:

- Python 3.x  
- Required libraries:

```
pip install sounddevice numpy
```

Note: Microphone and live playback features require `sounddevice` and `numpy`.



## How to Run the Program

### Step 1: Start the Receiver

```
python receiver.py
```

Enter:
- Receiver IP (usually `127.0.0.1`)
- Receiver name (any name, e.g., "Receiver")

Optional:
- Enable live playback (`y` or `n`)



### Step 2: Start the Caller

```
python caller.py
```

Enter:
- Receiver name  
- Receiver IP (`127.0.0.1` for same computer testing)  
- Caller name  
- Audio mode:
  - `wav` → send audio file  
  - `mic` → use microphone  

Optional:
- WAV filename (default: `sample.wav`)  
- Codec (default provided)



### Step 3: Observe the Call Flow

You should see:

- SIP signaling:
  - INVITE → 200 OK → ACK  
- RTP streaming logs  
- RTCP reports  
- BYE → 200 OK  



## Test Cases and Sample Outputs

### Test Case 1: WAV File Streaming

Input:
- Mode: `wav`
- File: `sample.wav`

Expected Output:
- RTP packets sent continuously  
- Receiver logs incoming RTP packets  
- Audio saved as `received_output.wav`  
- Audio plays correctly (if playback enabled)



### Test Case 2: Microphone Streaming

Input:
- Mode: `mic`

Expected Output:
- Live audio captured from microphone  
- RTP packets sent in real-time  
- Receiver plays audio (if enabled)  
- Press ENTER to stop transmission  



### Test Case 3: SIP Handshake Verification

Expected Logs:
- Sending INVITE  
- 200 OK received  
- Sending ACK  
- Call established  



### Test Case 4: Call Termination

Expected Logs:
- Sending BYE  
- Received 200 OK for BYE  
- Sockets closed successfully  



### Test Case 5: RTCP Monitoring

Expected Logs:
- Periodic RTCP Sender Reports  
- Display of:
  - Packet count  
  - Octet count  
  - RTP timestamp  



## Assumptions

- Both clients run on the same machine or local network  
- No NAT traversal is required  
- No SIP proxy or registrar is used  
- Communication is direct (peer-to-peer)  



## Limitations

- One-way audio streaming (Caller → Receiver)  
- No packet loss recovery (UDP-based)  
- Basic codec handling only  
- No encryption or authentication  



## Notes for Demonstration

- Use `127.0.0.1` for both clients if testing on one device  
- Ensure ports `5060`, `5004`, and `5006` are not blocked  
- Use a clear `.wav` file for best results  
- Microphone mode may require adjusting system audio permissions  



## References

- RFC 3261 – SIP: Session Initiation Protocol  
- RFC 4566 – SDP: Session Description Protocol  
- RFC 3550 – RTP: Real-Time Transport Protocol  
- RFC 3551 – RTP Profile for Audio  