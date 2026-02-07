from scapy.all import *

# Define IP and TCP details
src_ip = "10.100.102.45"
dst_ip = "<DEVICE_IP>"
src_port = 49443  # Source port
dst_port = 10000  # Destination port
src_mac = "f8:4d:89:85:ce:8a"
dst_mac = "<DEVICE_MAC>"

# Step 1: Send SYN packet
eth = Ether(src=src_mac, dst=dst_mac)
ip = IP(src=src_ip, dst=dst_ip)
syn = TCP(sport=src_port, dport=dst_port, flags='S', seq=1000)
syn_ack_packet = sr1(ip/syn)

# Check if we received a SYN-ACK
if syn_ack_packet and TCP in syn_ack_packet and syn_ack_packet[TCP].flags == 'SA':
    print(f"Received SYN-ACK from {dst_ip}")

    # Step 2: Send ACK packet to complete the handshake
    ack = TCP(sport=src_port, dport=dst_port, flags='A', seq=syn_ack_packet.ack, ack=syn_ack_packet.seq + 1)
    send(ip/ack)
    print(f"Sent ACK, TCP handshake complete with {dst_ip}")

    # Step 3: Send data (optional)
    data = "GET / HTTP/1.1\r\nHost: {}\r\n\r\n".format(dst_ip)
    psh = TCP(sport=src_port, dport=dst_port, flags='PA', seq=syn_ack_packet.ack, ack=syn_ack_packet.seq + 1)
    send(eth/ip/psh/data)

    # Step 4: Receive server's response (optional)
    response = sr1(ip/psh)
    print(f"Received response: {response[TCP].payload}")
else:
    print(f"No SYN-ACK received from {dst_ip}, handshake failed.")
