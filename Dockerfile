# Gunakan base image Python 3.10 versi slim agar ukurannya lebih ringan
FROM python:3.10-slim

# Set zona waktu jika diperlukan dan kurangi logs yang tidak perlu dari Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on

# Set working directory di dalam container
WORKDIR /app

# Copy requirement pertama untuk memanfaatkan docker cache
COPY requirements.txt .

# Install dependencies yang dibutuhkan
RUN pip install --no-cache-dir -r requirements.txt

# Copy semua source code aplikasi ke dalam container
COPY . .

# Buat direktori data dan logs yang dibutuhkan oleh bot agar tidak error jika tidak ada
RUN mkdir -p data logs

# Jalankan bot
CMD ["python", "main.py"]
