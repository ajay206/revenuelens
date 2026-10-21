**DRAFT – for Ajay to review and publish himself (not posted)**

🚀 Introducing **RevenueLens** – an open‑source AI‑powered revenue‑assurance platform for telecom billing.

Billing systems are notoriously complex and hidden leaks cost operators millions every year. RevenueLens scans your billing database, surfaces the leaks, explains *why* they happen, and even drafts fixes – all in a read‑only UI that never moves data off‑site.

💡 **One‑command demo**  
```bash
curl -O https://raw.githubusercontent.com/ajay206/revenuelens/main/docker-compose.demo.yml
docker compose -f docker-compose.demo.yml up
```  
Open http://localhost:8000, log in with the demo credentials (see README), and explore the leak list, stories, fixes, reports and on‑demand docs.

The demo runs entirely on synthetic data (Nimbus Telecom, ~500 customers, 64 planted leaks). No real customer data is used. If you provide a free LLM key (GROQ, OpenRouter or Gemini) you get real‑time AI‑generated leak stories; otherwise a built‑in fake model demonstrates the full flow.

🔗 https://github.com/ajay206/revenuelens

#AI #OpenSource #Telecom #RevenueAssurance #Python #FastAPI
