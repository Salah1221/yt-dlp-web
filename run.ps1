# Start the local yt-dlp web page.
# The server listens on the loopback address only.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
