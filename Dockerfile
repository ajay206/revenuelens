FROM python:3.12-slim

# Create a non‑root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /usr/sbin/nologin appuser

WORKDIR /app

# Install system dependencies (if any) and Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Switch to non‑root user
USER appuser

# Run migrations, seeding and start the API
CMD ["sh", "-c", "python -m app.migrate && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
