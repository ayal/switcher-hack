pids=$(pgrep -f 'auto.py')
if [ -n "$pids" ]; then
  echo "Found and killing process(es) with PID: $pids"
  echo "$pids" | xargs kill -9
else
  echo "No process found for auto.py"
fi

pids=$(pgrep -f 'server.py')
if [ -n "$pids" ]; then
  echo "Found and killing process(es) with PID: $pids"
  echo "$pids" | xargs kill -9
else
  echo "No process found for server.py"
fi

pids=$(pgrep -f 'cloudflared')
if [ -n "$pids" ]; then
  echo "Found and killing process(es) with PID: $pids"
  echo "$pids" | xargs kill -9
else
  echo "No process found for cloudflared"
fi
