# Deliverable 1 — TinyTroupe Persona Simulation (Draft App)

## Objective
Investigate agentic AI with TinyTroupe to simulate persona-based feedback for product features.

## System Requirements
- macOS (Intel or Apple Silicon)
- Python 3.10 (via Miniforge/Conda)
- No API key required when using Offline Mock Mode

## Installation (macOS, Intel example)
```bash
# Install Miniforge (Conda)
curl -L -o Miniforge3.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-x86_64.sh
bash Miniforge3.sh
conda init zsh && exec $SHELL

# Create environment
conda create -n tinytroupe python=3.10 -y
conda activate tinytroupe

# Install packages
pip install git+https://github.com/microsoft/TinyTroupe.git@main
pip install streamlit pyyaml
