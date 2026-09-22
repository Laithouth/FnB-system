# Base image chosen for compatibility with pocketsphinx's prebuilt
# manylinux wheel (no C compiler needed at build time -- verified locally:
# `pip install pocketsphinx` pulls a manylinux2014 wheel on this base).
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# PROVIDER intentionally unset here -- inherits app/config.py's own default
# (faster_whisper), which needs a container with network access to Hugging
# Face on first run. Override with -e PROVIDER=pocketsphinx for a fully
# offline deployment (no vocabulary-hint support -- see README section 2).
ENV SAMPLE_RATE=16000 \
    ALLOWED_ORIGINS=http://localhost:5173

EXPOSE 8000

# /readyz (not just process-up) gates traffic -- see app/main.py.
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/readyz').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
