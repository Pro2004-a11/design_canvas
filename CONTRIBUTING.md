# Contributing to Design Canvas

Thanks for your interest in improving Design Canvas.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

A working ComfyUI install on port `8188` is required for generation. Set
`COMFYUI_DIR` if it is not auto-detected.

## Guidelines

- **Python:** PEP 8, type hints on function signatures.
- **Scope:** keep the server a thin bridge — GPU work belongs in ComfyUI workflows.
- **Workflows:** new workflow JSONs go in `workflows/`; use the runtime placeholders
  `CANVAS_IMAGE`, `POSITIVE_PROMPT`, `NEGATIVE_PROMPT`, `CHECKPOINT_NAME`.
- **Commits:** small, focused, present-tense subject lines.

## Pull requests

1. Branch from `main`.
2. Describe what changed and why.
3. Confirm the server boots and a generation completes against a local ComfyUI.
