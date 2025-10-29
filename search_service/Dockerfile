FROM python:3.10-slim

WORKDIR /app

# Copy and install dependencies first to leverage Docker cache
COPY requirements.txt ./requirements.txt
# Upgrade pip to avoid hash mismatches against the protobuf wheel.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose the search API port
EXPOSE 8000

# Start the FastAPI application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
