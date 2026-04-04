# CTP Seed Dockerfile
# NOTE: The CTP DLL (thostmduserapi_se.dll) is Windows-only.
# On Windows: run ctp_seed.py directly (pip install -r requirements.txt)
# This Dockerfile is for reference / Linux environments with Linux CTP API.
# For our setup, run ctp_seed.py on Windows host, this container is optional.

FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# CTP DLL for Linux (if available)
# COPY thostmduserapi_se.so /usr/local/lib/
# COPY thostmduserapi.py /app/

COPY ctp_seed.py .

CMD ["python", "-u", "ctp_seed.py"]
