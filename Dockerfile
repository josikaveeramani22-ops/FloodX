FROM python:3.12-slim

WORKDIR /app

# Dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application: pages, server, ESP32 sketch, bundled demo dataset
COPY *.html ./
COPY fastapi_server.py ./
COPY esp32_floodx.ino ./
COPY data ./data

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=25s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:'+__import__('os').environ['PORT']+'/health')"

CMD ["uvicorn", "fastapi_server:app", "--host", "0.0.0.0", "--port", "8000"]