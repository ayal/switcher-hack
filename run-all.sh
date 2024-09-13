cd /home/ayalg/switcher-hack
nohup python -u auto.py > auto-log.log 2>&1 &
nohup python -u server.py > server-log.log 2>&1 &
nohup cloudflared tunnel run --url localhost:3001 my-tunnel > tunnel-log.log 2>&1 &
