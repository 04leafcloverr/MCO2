import socket
import time

RTP_PORT = 5004
MAX_BYTES = 4096
SIP_PORT = 5060

receiver_name = input("Enter receiver name: ") #user input
receiver_ip = input("Enter receiver IP: ") #user input

caller_name = input("Enter caller name: ") #from user input
caller_ip = "127.0.0.1" #for local testing
caller_port = 5062 #temp port num

unique_tag = "1234" #create a function that makes the tag
unique_id = "call1" #made in same functino as unique_tag
sequence_num = 1 #increments for new requests in same dialog
session_name = "VoIP Call" #depends if audio file is being sent or if we're able to successfully do live audio
to_line = ""
from_line = ""

dest_ip = None
dest_port = None


#build SIP INVITE & headers; blank line; SDP body
INVITE = f"INVITE sip:{receiver_ip} SIP/2.0\n" \
f"Via: SIP/2.0/UDP {caller_ip}:{caller_port}\n" \
f"To: {receiver_name} <sip:{receiver_ip}>\n" \
f"From: {caller_name} <sip:{caller_ip}>;tag={unique_tag}\n" \
f"Call-ID: {unique_id}\n" \
f"CSeq: {sequence_num} INVITE\n" \
"Content-Type: application/sdp\n\n" \
"v=0\n" \
f"o={caller_name} 12345 12345 IN IP4 {caller_ip}\n" \
f"s={session_name}\n" \
"t=0 0\n" \
f"c=IN IP4 {caller_ip}\n" \
f"m=audio {RTP_PORT} RTP/AVP 0\n" # c= : destination IP; m= : destination port and media type

#for debugging
print("INVITE to be sent: ", INVITE)

#encode invite
encoded_invite = INVITE.encode()

#SIP socket
SIP_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

#send invite
SIP_sock.sendto(encoded_invite, (receiver_ip, SIP_PORT))


#wait for response
response, addr = SIP_sock.recvfrom(MAX_BYTES)

#decode response
decoded_response = response.decode()

#check for 200 OK (for debugging)
print("Received 200 OK message:\n", decoded_response)

#it has 200 OK, proceed
if decoded_response.startswith("SIP/2.0 200 OK"):
    lines = decoded_response.split("\n")
    for line in lines:
        if line.startswith("To:"): #whole to line
            to_line = line
        if line.startswith("From:"): #whole from line
            from_line = line
        if line.startswith("c="): #destination IP
            c_parts = line.split(" ")
            dest_ip = c_parts[2]
        if line.startswith("m=audio"): #destination port
            m_parts = line.split(" ")
            dest_port = int(m_parts[1])

    #build ACK message
    ACK = f"ACK sip:{receiver_ip} SIP/2.0\n" \
    f"Via: SIP/2.0/UDP {caller_ip}:{caller_port}\n" \
    f"{to_line}\n" \
    f"{from_line}\n" \
    f"Call-ID: {unique_id}\n" \
    f"CSeq: {sequence_num} ACK\n"

    #for debugging
    print("ACK to be sent:\n", ACK)

    #encode ack
    encoded_ack = ACK.encode()
    
    #send ack
    SIP_sock.sendto(encoded_ack, (receiver_ip, SIP_PORT))
    time.sleep(1)

    #create new socket
    media_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    #sample payload for now **Need to Change this for actual sending of data**
    payload = "rah"

    #encoded payload
    encoded_payload = payload.encode()

    #for debugging
    print("Destination IP: ", dest_ip)
    print("Destination Port: ", dest_port)

    #send encoded payload RTP
    if dest_ip is not None and dest_port is not None:
        print("Starting RTP stream...")
        
        media_sock.sendto(encoded_payload, (dest_ip, dest_port))
        print("RTP packet sent successfully.")
    
        media_sock.close()
        SIP_sock.close()
    else:
        print("SDP parse failure.")
        media_sock.close()
        SIP_sock.close()

else:
    print("Connection attempt failed.")
    SIP_sock.close()