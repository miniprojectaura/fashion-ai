# AURA BUILD LOG
Last updated: 2026-07-05, by End-to-End Wiring brick

## Live & Frozen
- Backend: https://aura1-3rk2.onrender.com
- Frozen files/routes:
  - `services/api/api/v1/avatar.py` — POST /analyze, POST /check-quality, GET /measurements, POST /upload
  - `apps/mobile/lib/core/api_client.dart` — analyzeBody(), checkImageQuality(), getMeasurements() signatures
  - `services/api/core/models.py` — BodyProfile schema
  - Auth/JWT flow (all auth routes)
  - Router route names
  - `voice.py` ConverseResponse schema (reply_audio_b64) — FROZEN
  - `voice.py` FinalizeResponse — extended (additive only: tryon_image_b64, tailoring, reasoning)
- Env vars set on Render: GROQ_API_KEY, HUGGINGFACE_API_KEY, DATABASE_URL, SECRET_KEY
- Env vars NOT yet set: SARVAM_API_KEY (TTS falls back to HF MMS without it)

## Bricks shipped
| Brick | Date | What shipped | New frozen items | Open issues |
|---|---|---|---|---|
| Phase 2 (Voice+BodyMesh+TryOn) | earlier | Voice pipeline, body mesh, try-on | auth flow, router | body-mesh confidence was hardcoded |
| Measurement Extraction | 2026-07-04 | Hybrid MediaPipe+VLM measurement pipeline, real confidence scoring, hard-reject <80%, retake UI dialog | avatar.py endpoints, api_client.dart avatar methods, BodyProfile model | Need to verify MediaPipe model download on Render cold start |
| Voice Assistant | 2026-07-05 | Real conversational voice: Groq Whisper ASR → language-mirroring Stylist LLM → Sarvam TTS. Removed mock ASR + silent WAV. Voice-first mobile UI. | groq_asr.py, voice.py ConverseResponse schema (reply_audio_b64) | Deploy pending on Render (Docker rebuild). User must set SARVAM_API_KEY on Render for TTS. |
| Multi-Agent Fashion AI | 2026-07-05 | Replaced finetuning with multi-agent pipeline: (1) body_analyzer.py — deterministic body geometry (WHR, SHR, body type classification, silhouette/neckline recommendations), (2) fashion_rag.py — 200+ embedded fashion principles + JSON knowledge base retrieval, (3) fashion_reasoner.py — chain-of-thought `<think>` reasoning via Groq 70b, (4) tailoring_calc.py — computed cut sizes, ease allowances, yardage, dart placements from real measurements, (5) web_search.py — real product URLs via DuckDuckGo (zero API keys), (6) virtual_tryon.py — HF Spaces compositing + SDXL body-aware fallback. Integrated into stylist.py (3-agent pipeline: body→RAG→reasoner). Enhanced /finalize with tailoring + real search + try-on. Fixed hardcoded clip_score in generate_outfit.py. Rich finalize UI in mobile (tailoring card, product links with url_launcher, expandable AI reasoning). | body_analyzer.py, fashion_rag.py, fashion_reasoner.py interfaces | Render deploy may be slow (~20-30 min). DuckDuckGo search may be rate-limited under heavy use. HF Spaces try-on has cold-start latency (~30-120s). gradio_client + ddgs are new pip dependencies. |
| End-to-End Wiring | 2026-07-05 | 8-fix integration: (1) Outfit image as inline base64 (no cloud storage dep), (2) User front photo stored in BodyProfile & passed to virtual try-on, (3) Chat screen handles outfit_image_b64 primary/URL fallback, (4) Wardrobe screen upgraded with rich outfit cards + tailoring + badges, (5) Avatar stores front photo b64 for try-on reuse, (6) __init__.py for agent/ & retrieval/ Docker imports, (7) Design screen shows finalized designs from wardrobe, (8) Search endpoint wired to DuckDuckGo with legacy fallback. Also: body_analysis scope fix, WardrobeItem model alignment, product screen rewritten for DDG format. | voice.py FinalizeResponse schema (additive: outfit_image_b64), wardrobe.py metadata response | All working locally. Render deploy triggered on push. |

## Process notes (from Step 7 of each brick)
- Phase 2: (pre-existing)
- Measurement Extraction: Direct path. Step 1 trace found the hardcoded confidence issue immediately. Step 2 research confirmed VLMs can't do geometric measurement — chose hybrid approach. No avoidable backtracks.
- Voice Assistant: Direct path. Discovery found 3 landmines (mock ASR, silent TTS, on-device STT bypass). Approach A (Groq+Sarvam) scored highest. One minor bugfix (te-IN normalization case mismatch). Render Docker deploy is slow on free tier (~20-30 min) — still pending at commit time.
- Multi-Agent Fashion AI: Extended discovery traced 10 files to understand what was real vs stub. Key findings: (a) stylist.py used vanilla llama-70b with generic "be an expert" prompt — no actual fashion knowledge, (b) clip_score was hardcoded (0.35+i*0.02) — fabricated metric, (c) product search returned only 3 hardcoded Myntra/AJIO/Amazon URLs. Approach B (multi-agent pipeline with deterministic body math + RAG + CoT) won over single-LLM and tool-calling approaches. One path fix (fashion_rag.py KNOWLEDGE_PATH used wrong parent index). All 3 agent modules verified via local Python tests before integration.
- End-to-End Wiring: Systematic audit of 6-step workflow identified 8 breaks. Fixed: (a) outfit image returned as inline base64 since no cloud storage configured, (b) avatar stores front photo for try-on reuse, (c) wardrobe response now includes metadata_json, (d) body_analysis variable scope bug (NameError if body_profile missing), (e) WardrobeItem model has no created_at — removed references. All 3 rewritten mobile screens (wardrobe, design, products) match AURA dark theme. APK compiles clean (58.6MB).