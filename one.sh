#!/bin/bash

# start server.py
python server.py 2>&1 | while IFS= read -r line; do echo "$(date) $line"; done >> ./logs/server.log &
PID1=$!


# start auto.py
python3 auto.py 2>&1 | while IFS= read -r line; do echo "$(date) $line"; done >> ./logs/auto.log &
PID3=$!


echo "Servers started with PIDs: $PID1, $PID3"
echo "Check the log files for outputs and errors."

# Optionally, you can add a trap to handle termination signals and clean up
trap "echo 'Stopping servers...'; kill $PID1 $PID3; exit" SIGINT SIGTERM

# Keep the script running to maintain the background processes
wait
