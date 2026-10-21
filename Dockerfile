FROM python:3.12-slim

# ---- create non‑root user ----
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /app -s /usr/sbin/nologin appuser

# ---- set workdir ----
WORKDIR /app

# ---- copy only build‑time files ----
COPY pyproject.toml README.md ./
COPY app/ ./app/
COPY migrations/ ./migrations/
COPY legacy_sim/ ./legacy_sim/
COPY scripts/ ./scripts/

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

# ---- image metadata ----
LABEL org.opencontainers.image.source="https://github.com/ajay206/revenuelens"
LABEL org.opencontainers.image.description="RevenueLens – AI‑powered revenue assurance for telecom billing"

# ---- entrypoint ----
CMD ["sh", "-c", "python -m app.migrate && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
