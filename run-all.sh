nohup python auto.py &
nohup python server.py &
nohup cloudflared tunnel run --url localhost:3001 my-tunnel &
