pids=$(pgrep -f 'auto.py')
if [ -n "$pids" ]; then
  echo "Process(es) for 'auto.py' found with PID: $pids"
else
  echo "No process found for 'auto.py'"
fi

pids=$(pgrep -f 'server.py')
if [ -n "$pids" ]; then
  echo "Process(es) for 'server.py' found with PID: $pids"
else
  echo "No process found for 'server.py'"
fi

pids=$(pgrep -f 'cloudflared')
if [ -n "$pids" ]; then
  echo "Process(es) for 'cloudflared' found with PID: $pids"
else
  echo "No process found for 'cloudflared'"
fi
