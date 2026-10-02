FROM python:3.12.14-slim-trixie
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 app && install -d -o app -g app -m 700 /app/data /app/data/jobs_v6 /app/data/exports_v6 /app/backups
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["python3", "-c", "import os, urllib.request; host=os.environ['LOTTERY_ALLOWED_HOSTS'].split(',')[0].strip(); request=urllib.request.Request('http://127.0.0.1:8000/api/v1/auth/csrf/', headers={'Host': host}); urllib.request.urlopen(request, timeout=3).read()"]
CMD ["gunicorn", "webapp.wsgi:application", "--bind", "0.0.0.0:8000", "--worker-class", "gthread", "--workers", "2", "--threads", "4", "--timeout", "120", "--graceful-timeout", "30", "--access-logfile", "-", "--error-logfile", "-"]
