FROM python:3.11-slim

WORKDIR /app

COPY requirements-ha.txt .
RUN pip install --no-cache-dir -r requirements-ha.txt

COPY ha_seed.py .

EXPOSE 9101

CMD ["python", "-u", "ha_seed.py"]
