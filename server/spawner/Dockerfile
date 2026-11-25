FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app.py metrics.py admin_ui.py /app/
RUN mkdir -p /data

EXPOSE 8787

CMD ["python3", "/app/app.py"]
