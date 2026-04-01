import socket

SIP_IP = "0.0.0.0"
SIP_PORT = 5060
RTP_PORT = 5006
MAX_BYTES = 4096

receiver_ip = input("Enter receiver IP: ") #user input
receiver_name = input("Enter receiver name: ") #user input

unique_tag = "1234" #create a function that makes the tag
session_name = "VoIP Call" #depends if audio file is being sent or if we're able to successfully do live audio

via_line = ""
to_line = ""
from_line = ""
call_id_line = ""
cseq_line = ""


#SIP UDP socket
SIP_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
SIP_sock.bind((SIP_IP, SIP_PORT))

#receive INVITE
print("Waiting for INVITE...")
invite_message, sip_addr = SIP_sock.recvfrom(MAX_BYTES)

#convert message to string
decoded_invite = invite_message.decode()

#fro debugging
print("Received INVITE mssg:\n", decoded_invite)

#same values as from invite
lines = decoded_invite.split("\n")
for line in lines:
    if line.startswith("Via:"): 
        via_line = line
    if line.startswith("To:"):
        to_line = line
        if "tag=" not in to_line:
            to_line = to_line + f";tag={unique_tag}"
    if line.startswith("From:"): 
        from_line = line
    if line.startswith("Call-ID:"): 
        call_id_line = line
    if line.startswith("CSeq:"):
        cseq_line = line
    
#build 200 OK response
response = "SIP/2.0 200 OK\n" \
f"{via_line}\n" \
f"{to_line}\n" \
f"{from_line}\n" \
f"{call_id_line}\n" \
f"{cseq_line}\n" \
f"Content-Type: application/sdp\n\n" \
"v=0\n" \
f"o={receiver_name} 12345 12345 IN IP4 {receiver_ip}\n" \
f"s={session_name}\n" \
"t=0 0\n" \
f"c=IN IP4 {receiver_ip}\n" \
f"m=audio {RTP_PORT} RTP/AVP 0\n"

#for debugging
print("200 OK to be sent: ", response)

#encode 200 OK
encoded_response = response.encode()

#send encoded 200 OK
SIP_sock.sendto(encoded_response, sip_addr)

try:
    SIP_sock.settimeout(20)
    #wait for ack
    ack_message, sip_addr = SIP_sock.recvfrom(MAX_BYTES)
except socket.timeout:
    print("ACK not received (timeout)")
    exit()

decoded_ack = ack_message.decode()

#for debugging
print("Received ACK:\n", decoded_ack)

if decoded_ack.startswith("ACK"):
    media_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    media_sock.bind((SIP_IP, RTP_PORT))

    print(f"Waiting for RTP on port {RTP_PORT}")

    for i in range(5):
        payload_message, rtp_addr = media_sock.recvfrom(MAX_BYTES)
        decoded_payload = payload_message.decode()

        print(f"Received RTP packet {i+1}: {decoded_payload}")

    #for debugging
    #print("Received RTP payload:\n", decoded_payload)
    print("Received from\n", rtp_addr)

    media_sock.close()
    SIP_sock.close()
else:
    print("Invalid ACK")
    SIP_sock.close()
    exit()