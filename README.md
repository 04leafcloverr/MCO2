# Real-Time Audio Streaming over IP (VoIP Simulation)
NSCOM01 – MCO2 (Term 2, AY 2025–2026)

---

## Group Members
- Besa, April Denise B.
- Martinez, Gabrielle P.

---

## Project Overview

This project implements a simplified VoIP (Voice over IP) system using:

- SIP (Session Initiation Protocol) for call setup and teardown  
- SDP (Session Description Protocol) for media negotiation  
- RTP (Real-time Transport Protocol) for audio streaming  
- RTCP (RTP Control Protocol) for transmission statistics  

The system simulates a real-time call between two clients:
- Caller (Client 1) sends audio  
- Receiver (Client 2) receives and plays or stores audio  

---

## Features Implemented

### Core Requirements

#### SIP Signaling (UDP)
- Sends INVITE  
- Receives 200 OK  
- Sends ACK  
- Includes required SIP headers (Via, To, From, Call-ID, CSeq)  
- Sends BYE to terminate session  
- Receives 200 OK for BYE  

---

#### SDP Negotiation
- Embeds SDP in INVITE  
- Parses SDP from 200 OK  
- Extracts:
  - IP address  
  - RTP port  
  - Codec  

---

#### RTP Audio Streaming
- Builds RTP packets with:
  - Sequence number  
  - Timestamp  
  - SSRC  
- Streams audio from a WAV file  
- Sends packets in real-time intervals  

---

#### RTP Receiving and Playback
- Receives RTP packets  
- Extracts payload  
- Stores received audio  
- Saves output as a WAV file  
- Optional live playback through speakers  

---

#### RTCP Support
- Sends RTCP Sender Reports  
- Receives and parses RTCP packets  
- Displays:
  - Packet count  
  - Octet count  
  - RTP timestamps  

---

#### Basic Error Handling
- Handles timeouts  
- Handles invalid SIP messages  
- Prevents crashes on unexpected packets  

---

## Bonus Features

- Microphone input streaming  
- Live audio playback on receiver  
- Dual audio modes (file and microphone)  

---

## Project Structure
