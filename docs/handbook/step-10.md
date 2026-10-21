# Step 10 – Publish Docker Image & Demo Workflow

This step finalises the public delivery of RevenueLens.

## 1. Image publishing workflow

* **GitHub Actions** (`.github/workflows/publish.yml`) builds the Docker image on every push to `main` and on manual dispatch.
* Image is pushed to **GitHub Container Registry** under `ghcr.io/ajay206/revenuelens`.
* Tags:
  * `latest` – always points to the most recent commit.
  * SHA tag – immutable reference to the exact commit.
* Labels include `org.opencontainers.image.source` pointing to the repo.

> **Manual step** – after the first push, go to **Settings → Packages → revenuelens → Change visibility → Public** so the image can be pulled without authentication.

## 2. Demo compose file

* `docker-compose.demo.yml` bundles a PostgreSQL instance and the app.
* The app uses `scripts/demo-entrypoint.sh` to:
  1. Wait for DB.
  2. Run migrations & seed demo admin.
  3. Load synthetic Nimbus data (`legacy_sim load`).
  4. Choose a fake LLM if no API key is present.
  5. Run the explainer once to generate a story.
  6. Print the URL and demo credentials.
  7. Launch `uvicorn`.

Run it with:

```bash
docker compose -f docker-compose.demo.yml up
```

Stop with `docker compose -f docker-compose.demo.yml down -v`.

## 3. Demo credentials (synthetic)

| Variable | Value |
|----------|-------|
| `ADMIN_EMAIL` | `demo@revenuelens.local` |
| `ADMIN_PASSWORD` | `revenuelens-demo` |
| `COMPANY_ID` | `11111111-2222-3333-4444-555555555555` |
| `COMPANY_NAME` | `Nimbus Telecom (synthetic demo)` |
| `JWT_SECRET` | `demo-only-not-secret` |

All data is synthetic (Nimbus Telecom, ~500 customers, planted leaks). **Never use these credentials in production.**

## 4. CI demo job

The CI workflow (`.github/workflows/ci.yml`) now contains a `demo` job:

* Builds the image locally (`docker build -t revenuelens:ci .`).
* Spins up the demo stack with `docker compose -f docker-compose.demo.yml -p rl-demo up -d`.
* Waits for the health endpoint, performs a smoke test (`scripts/demo-smoke.sh`), and tears everything down.
* On failure it dumps the last 200 lines of container logs for debugging.

## 5. Making the GHCR package public

1. Navigate to **Settings → Packages** in the GitHub repository.
2. Click the `revenuelens` package.
3. Choose **Change visibility** → **Public**.
4. Confirm. This is a one‑time manual action; subsequent pushes will automatically publish new tags.

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| **Port 8000 already in use** | Set a different port with `DEMO_PORT` env var, e.g. `DEMO_PORT=8080 docker compose -f docker-compose.demo.yml up`. |
| **Apple Silicon (M1/M2) build fails** | The `publish.yml` workflow builds for `linux/amd64`. Docker Desktop emulates this automatically, but you can also add `--platform linux/amd64` when building locally. |
| **LLM API keys not recognised** | Ensure the environment variable name matches exactly (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`). If none are set, the fake LLM is used (still functional for the demo). |
| **Health check never passes** | Verify the PostgreSQL container is healthy (`docker compose logs db`). Increase `start_period` in the healthcheck if the DB is slow to start. |

---

That’s it – the Docker image is now public, the demo can be started with a single command, and CI verifies the whole flow automatically. Happy hacking!  
