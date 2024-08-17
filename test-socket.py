import socket

ip_address = "<DEVICE_IP>"
port = 10000

s = None
try:
    print(f"Connecting to {ip_address}:{port}...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((ip_address, port))
    print("Connection successful!")
except Exception as e:
    print(f"Connection failed: {e}")
finally:
    if s:
        s.close()
