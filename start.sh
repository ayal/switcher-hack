#!/bin/bash

# Start server 1
# server_command1 > server1_output.log 2> server1_error.log &
# PID1=$!

# start server.py
python server.py > server.log 2> server.error.log & PID1=$!


# start tunnl to server, do it in a screen
ssh -R 80:localhost:3001 tunnl.icu > tunnl.log 2> tunnl.error.log & PID2=$!

# start auto.py
python3 auto.py > auto.log 2> auto.error.log & PID3=$!


echo "Servers started with PIDs: $PID1, $PID2, $PID3"
echo "Check the log files for outputs and errors."

# Optionally, you can add a trap to handle termination signals and clean up
trap "echo 'Stopping servers...'; kill $PID1 $PID2 $PID3; exit" SIGINT SIGTERM

# Keep the script running to maintain the background processes
wait
