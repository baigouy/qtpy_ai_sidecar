# Changelog

## 0.1.2 — 2026-11-05

- Bold words in an answer can be clicked: they go into the message box, like the suggested-answer buttons. Links in answers open in the browser instead of blanking the message.
- With an online provider, a second notice line says explicitly that messages, the content the chat reads and images are sent outside the computer to that provider (`Config.remote_notice` lets hosts word it). Never shown for a model on this computer, including a custom server on a loopback address.
- Eight tool searches in a row without a successful application call stop the turn with an explanation of what blocked it, instead of using every remaining step.
- PyFigures adapter: "remove / reset / clear the LUTs" may use NONE (the image file's own LUT) and is steered there instead of ending on a question; the same LUT on several channels of one image (GRAY on all) needs the user's own words ("all channels"); uneven rows (row_counts); every multiple-choice answer also offers to set up the GUI (the panel editor on the right tab, or the right-click menu with the right selection level).

## 0.1.1 — 2026-11-05

- Debug exports include the pictures the chat showed (canvas snapshots, before/after previews) and a screenshot of the window, linked from `conversation.md`; snapshots are kept next to the local log.
- Up to 24 tools are passed to the model directly (was 12); `QTPY_AI_SIDECAR_MAX_DIRECT_TOOLS` changes it.
- litsearch adapter: 22 tools, one per task (reviews, checks, notes, downloads, saved reviews).

## 0.1.0 — 2026-10-23

- Independent QtPy package, standalone launcher and embedding API.
- Managed llama.cpp, explicit CPU-only mode, model/runtime library, verified downloads, portable runtime selection.
- Optional OpenAI, native Claude, OpenRouter and custom API endpoints.
- OS-vault-only credential storage, no plaintext fallback; credential redaction in debugging exports.
- MCP stdio/streamable HTTP, small direct surfaces and paginated discovery for large registries.
- Conversation compression, current-choice buttons, progress/context indicators and debug ZIP export.
- Optional host action adapter and PyFigures prototype integration, without original application source changes.

Initial developer release. See README for validation boundaries and remaining integration work.

- Added PyFigures row-swap guidance/verified completion and validated canvas click context (prototype bridge required).
- litsearch adapter (`adapters/litsearch.py`): live state, read-only classification of its tools, docking in its window; docking shared with PyFigures (`adapters/docking.py`); `Config.from_dict` for hosts that build their configuration in code; the standalone launcher accepts `"type": "litsearch"`.
- Optional embeddings (`embeddings.py`, tools menu > Embeddings…): off by default; the Mistral API with the stored Mistral key, or a local OpenAI-compatible server; `Embedder.model_id` for hosts to record what built their vectors.
- Optional image descriptions for image search (PyFigures): `Embedder.describe()` and `vision_id`, the Embeddings… dialog's Image descriptions field (Mistral: `mistral-small-latest` by default; local: only a named vision model); `search_images` is a read-only PyFigures call.
- litsearch adapter: `manage_watch` (save / run / delete) replaces `save_watch` and `run_watch`; new `export_results`; instructions for date filters, fetching by identifier and checking a summary's claims.
- litsearch adapter: `library` (list / index / remove / download open-access PDFs / open pages) replaces `index_folder`; its "list" action is read-only.
