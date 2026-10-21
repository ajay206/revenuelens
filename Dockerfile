FROM python:3.12-slim

# ---- create non‑root user ----
RUN groupadd -r appuser && \\
    useradd -r -g appuser -d /app -s /usr/sbin/nologin appuser

# ---- set workdir ----
WORKDIR /app

# ---- copy only build‑time files ----
COPY pyproject.toml README.md ./
COPY app/ ./app/
COPY migrations/ ./migrations/

# ---- install the package (editable not needed) ----
RUN pip install --no-cache-dir .

# ---- adjust ownership ----
RUN chown -R appuser:appuser /app

# ---- runtime user ----
USER appuser

# ---- expose port ----
EXPOSE 8000

# ---- ensure the source root is on PYTHONPATH ----
ENV PYTHONPATH=/app

# ---- entrypoint ----
CMD ["sh", "-c", "python -m app.migrate && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
