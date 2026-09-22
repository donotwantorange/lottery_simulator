FROM python:3.12.14-slim-trixie
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 app && mkdir -p /app/data/jobs_v4 /app/backups && chown -R app:app /app
USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).read()"]
CMD ["python3", "-m", "streamlit", "run", "dashboard/app.py", "--server.headless=true", "--server.address=0.0.0.0", "--server.port=8501"]
