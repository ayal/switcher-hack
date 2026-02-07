import socket

source_ip_address = "10.100.102.17"


ip_address = "<DEVICE_IP>"
port = 10000

s = None
try:
    print(f"Connecting to {ip_address}:{port}...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # s.bind((source_ip_address, 0))
    s.connect((ip_address, port))
    print("Connection successful!")
except Exception as e:
    print(f"Connection failed: {e}")
finally:
    if s:
        s.close()
