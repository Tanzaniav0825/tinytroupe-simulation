# app_streamlit.py — Persona Feedback Simulator (Deliverable 1)
# Supports: TinyTroupe 0.5.2  •  Offline Mock Mode (no API calls)  •  Live mode if you add billing later

import os
import re
import time
from datetime import datetime
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import streamlit as st
import yaml

# ---- TinyTroupe imports (compatible with 0.5.2) ----
try:
    from tinytroupe.environment import TinyWorld
    from tinytroupe import config_manager
    from tinytroupe.factory import TinyPersonFactory
    _tt_available = True
except Exception as e:
    TinyWorld = None
    TinyPersonFactory = None
    _tt_available = False
    _import_err = e

APP_TITLE = "Persona-Based Feature Feedback Simulator (TinyTroupe)"
st.set_page_config(page_title=APP_TITLE, layout="wide")

st.title(APP_TITLE)
st.caption("Draft app for Deliverable 1 – Algorithms for Data Science (Agentic AI investigation)")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.header("Environment")
    st.markdown("**API Keys**")
    st.write("Live mode needs OPENAI_API_KEY and billing. Use Mock Mode to avoid API calls.")
    if not _tt_available:
        st.error(f"TinyTroupe import failed: {_import_err}")
    else:
        st.success("TinyTroupe imported successfully.")

    st.divider()
    st.header("Simulation Settings")
    steps = st.slider("Conversation steps (turns)", 1, 8, 2)
    temperature = st.slider("LLM temperature (live mode)", 0.0, 1.5, 0.3, 0.1)
    cache_api = st.checkbox("Cache API calls (live mode, if supported)", value=True)

    # Mock Mode toggle (OFF uses live API; ON runs fully offline)
    mock_mode = st.checkbox("Offline mock mode (no API calls)", value=True)

    # Optional model override for live mode
    model_name = st.text_input("Model override (live mode)", value="gpt-4o-mini",
                               help="Examples: gpt-4o-mini or gpt-3.5-turbo")

    # Gentle pacing UI (mostly relevant in live mode)
    request_delay_ms = st.slider("Delay between personas (ms, live mode)", 0, 5000, 1500, 100)

    st.divider()
    st.header("Export")
    auto_export = st.checkbox("Auto-save results to Markdown", value=True)
    export_dir = st.text_input("Export folder", value="conversations")

# ---------------- Config (applied only if live mode and library honors keys) ----------------
if _tt_available and not mock_mode:
    try:
        config_manager.update("cache_api_calls", cache_api)
        config_manager.update("openai_temperature", temperature)
        try:
            config_manager.update("openai_model", model_name)
        except Exception:
            pass
    except Exception:
        pass

# ---------------- Load personas ----------------
def load_personas(yaml_path: str):
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("personas", [])
    except FileNotFoundError:
        return []

PERSONA_FILE = Path(__file__).with_name("personas.yaml")
personas = load_personas(PERSONA_FILE)

st.subheader("1) Choose Personas")
if personas:
    labels = {p["label"]: p for p in personas}
    selected_labels = st.multiselect(
        "Select one or more personas",
        list(labels.keys()),
        default=[list(labels.keys())[0]],
    )
    selected_personas = [labels[lbl] for lbl in selected_labels]
else:
    st.warning("No personas found. Please add them to personas.yaml.")
    selected_personas = []

# ---------------- Feature inputs ----------------
st.subheader("2) Describe the Feature")
feature_title = st.text_input("Feature title", value="New 'Quick Share' button on iOS detail screen")
feature_desc = st.text_area(
    "Feature description / interaction flow",
    value=(
        "Add a 'Quick Share' button on the product detail page. "
        "The button opens a bottom sheet with 3 recent contacts, AirDrop, and 'Copy Link'. "
        "Long-press reveals 'Share with last contact'. Visible to all beta users; no onboarding."
    ),
    height=140,
)

extra_context = st.text_area(
    "Context (optional): persona tasks or test setup",
    value="Assume one-handed use is common and the user wants to share quickly.",
    height=80,
)

# ---------------- Throttle + Backoff Helpers (used only in live mode) ----------------
_MIN_INTERVAL_S = 15.0      # very conservative to dodge rate limits
_last_call_ts = 0.0
_throttle_lock = Lock()

def _throttled_call(fn):
    """Ensure ≥ _MIN_INTERVAL_S between API calls (live mode)."""
    global _last_call_ts
    with _throttle_lock:
        now = time.time()
        wait = _MIN_INTERVAL_S - (now - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        result = fn()
        _last_call_ts = time.time()
        return result

def run_with_retry(fn, retries=8, base_sleep=5.0):
    """Retry on 429 with exponential backoff (live mode only)."""
    last_err = None
    for i in range(retries):
        try:
            return _throttled_call(fn)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "Too Many Requests" in msg or "rate limit" in msg.lower():
                sleep_s = base_sleep * (2 ** i)
                st.warning(f"Rate-limited (429). Backing off {sleep_s:.1f}s (attempt {i+1}/{retries})…")
                time.sleep(sleep_s)
                last_err = e
                continue
            else:
                raise
    if last_err:
        raise last_err

# ---------------- Mock helpers (used when mock_mode=True) ----------------
def make_mock_agent(persona_label: str):
    """Create a lightweight local persona object (no API)."""
    return SimpleNamespace(name=persona_label)

def mock_run_export(persona_label: str, feature_title: str):
    """Simulate persona feedback without API calls; produces a TinyTroupe-like export."""
    content = (
        f"[MOCK] Persona {persona_label} feedback on {feature_title}:\n"
        f"- Reaction: Convenient for frequent sharers; minimal taps is good.\n"
        f"- Usability: Ensure 44x44pt targets, clear label, and undo after share.\n"
        f"- Accessibility: VoiceOver should announce 'Quick Share button'; respect Dynamic Type; high contrast.\n"
        f"- Privacy: No background uploads; clarify data use; allow opt-out in Settings.\n"
        f"- Adoption: 78/100 if non-intrusive and fast; improve with tooltip on first launch, then stay quiet.\n"
        f"- Follow-ups: 1) Does it respect system text size? 2) Can users disable or reorder share options?\n"
    )
    transcript = [{"from": persona_label, "action": "TALK", "content": content}]
    return {"transcript": transcript}

# ---------------- Live helpers (only called when mock_mode=False) ----------------
def make_agents(factory: TinyPersonFactory, selected):
    agents = []
    for p in selected:
        try:
            # Factory may call the model; throttle + retry
            person = run_with_retry(lambda: factory.generate_person(p["factory_prompt"]))
            agents.append(person)
        except Exception as e:
            st.error(f"Failed to generate agent for persona '{p['label']}': {e}")
    return agents

def run_world_with_prompt(person, steps, user_instruction):
    world = TinyWorld("Feedback Session", [person])
    world.make_everyone_accessible()
    person.listen(user_instruction)
    world.run(steps)
    return world.export_machine_readable()

# ---------------- Run simulation ----------------
run_clicked = st.button("Run Simulation", type="primary",
                        disabled=not selected_personas or not feature_desc)
results = []

if run_clicked:
    if not _tt_available and not mock_mode:
        st.error("TinyTroupe not available and Mock Mode is OFF. Enable Mock Mode or fix TinyTroupe install.")
        st.stop()

    with st.spinner("Generating agents and running conversations…"):
        # Build the instruction (works for both modes; shorter prompt = fewer tokens in live mode)
        user_instruction = (
            f"Feature: {feature_title}\n"
            f"{feature_desc}\n"
            f"Context: {extra_context}\n\n"
            f"Give:\n"
            f"- Initial reaction\n"
            f"- Usability issues (discoverability, load, targets, contrast, screen reader)\n"
            f"- Privacy/Security if any\n"
            f"- Adoption & how to increase\n"
            f"- Acceptance 0-100 + 1-sentence why\n"
            f"- Up to 2 follow-up questions\n"
        )

        # Create agents (mock vs live)
        if mock_mode:
            agents = [make_mock_agent(p["label"]) for p in selected_personas]
        else:
            factory = TinyPersonFactory(context="Mobile app beta test for a new iOS feature.")
            agents = make_agents(factory, selected_personas)

        # Run each agent (mock vs live)
        for i, a in enumerate(agents):
            if i > 0 and request_delay_ms > 0:
                time.sleep(request_delay_ms / 1000.0)

            if mock_mode:
                export = mock_run_export(a.name, feature_title)
            else:
                export = run_with_retry(
                    lambda: run_world_with_prompt(a, steps, user_instruction),
                    retries=8,
                    base_sleep=5.0
                )

            results.append({"persona_name": a.name, "export": export})

# ---------------- Results ----------------
if results:
    st.subheader("3) Results")
    for r in results:
        st.markdown(f"### Persona: **{r['persona_name']}**")
        transcript = r["export"].get("transcript", [])
        if transcript:
            with st.expander("Show raw transcript"):
                st.json(transcript)
        msgs = [m for m in transcript if m.get("action") in ("TALK", "CONVERSATION")]
        if msgs:
            st.markdown("**Simulated Feedback (final message)**")
            st.write(msgs[-1].get("content", ""))

    st.divider()
    st.markdown("### Aggregated Metrics (heuristic)")
    scores = []
    for r in results:
        text = " ".join([m.get("content", "") for m in r["export"].get("transcript", [])
                         if m.get("action") in ("TALK", "CONVERSATION")])
        m = re.search(r"(?i)(?:acceptance|score|rating)[^0-9]{0,10}(\d{1,3})", text)
        if m:
            scores.append((r["persona_name"], min(100, int(m.group(1)))))
    if scores:
        st.write({n: s for n, s in scores})
        st.write(f"Average (n={len(scores)}): {sum(s for _, s in scores)/len(scores):.1f}")
    else:
        st.info("No numeric acceptance scores found (mock output includes one example).")

    # Export to markdown
    if auto_export:
        Path(export_dir).mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r'[^a-z0-9]+', '-', feature_title.lower()).strip('-')[:60]
        out_path = Path(export_dir) / f"{ts}__{slug}.md"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# Conversation Log – {feature_title}\n\n")
            for r in results:
                f.write(f"## Persona: {r['persona_name']}\n\n")
                for m in r["export"].get("transcript", []):
                    who = m.get("from", "Agent")
                    act = m.get("action", "")
                    content = m.get("content", "")
                    f.write(f"**{who}** [{act}]:\n\n{content}\n\n---\n\n")
        st.success(f"Saved: {out_path}")
        st.download_button("Download conversation log (.md)",
                           data=open(out_path, "rb").read(),
                           file_name=out_path.name,
                           mime="text/markdown")

st.divider()
st.subheader("Notes")
st.markdown("""
- Mock Mode is ON by default to avoid API usage; turn it OFF only if you have billing enabled.
- Use 1 persona and 1–2 steps for quick tests.
- Live mode includes conservative throttling + exponential backoff to reduce 429 errors.
""")

