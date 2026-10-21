FROM python:3.12-slim

WORKDIR /app

# Install build dependencies minimally
RUN python -m pip install --upgrade pip setuptools

# Install the package (includes migrations)
COPY . /app
RUN pip install .

# Run migrations before starting the server
CMD ["sh", "-c", "python -m app.migrate && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
