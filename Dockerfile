FROM python:3.11-slim

# Install ffmpeg for audio/video merging
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot.py .

CMD ["python", "-u", "bot.py"]
