# Changelog

## Unreleased

- PyFigures adapter: "I want to edit / adjust X" with no value given, "let me edit it", "myself", "by hand", "so I can edit it" change nothing: the model is told to open the editor for the user ("i wanna edit smallest ROI inset in b" made a second inset).
- PyFigures adapter: such a request naming its panel ("…in b"), or with one panel selected, or after a turn that named one, opens that panel's editor at once (on the crop / colours / texts tab when named), without the model; with no panel known, the reply asks which, offering to open each panel's editor or to make the change.
- PyFigures adapter: "open the dialog / editor for me" (typos too) opens the panel editor at once; "consistent / the same letters" is checked against the letters (font, size, bold, italic, underline, box; not the automatic colour), and letters still differing are said with the choices to settle it; each panel's insets are passed to the model.

## 0.1.7 — 2026-11-12

- PyFigures adapter: "how many / how much / how big…" asks for a number, not for steps: "how many channels does this image have" was answered with the channel-split guide.

## 0.1.6 — 2026-11-12

- After a turn's edits succeeded, re-reading what each tool already read back is cut short: after two reads in a row the model is told to answer, after four its tools are switched off and it answers from the results (asked to say which part of the request is not done yet, never to call it done). The status line says "Changes applied; checking them (Stop keeps them)" and the Stop tooltip says that the changes already made stay.
- The host-verification recovery note and the stop note are sent as user messages: Mistral refused a conversation ending on a system message after the model's reply (HTTP 400).
- PyFigures adapter:
  - Plain reads (`get_image_property`, `list_luts`, `preview_figure`…) count as reads, not edits.
  - "Colours look unnatural / back to normal / the default colours" may use the image file's own colours (NONE), and the colour question offers them; "restore it as it was" may go back to the LUT the last reply named.
  - Several requests in one sentence each name their panel; "#3" / "number 3" names the panel shown with that number; a journal column must not become a row layout; "publication ready" with no journal or size allows checks only.
  - Short words after "image" or "panel" ("each image bg") are not panel names.
  - `edit_panel_letters` takes bold/italic/underline for some panels; "every rotated panel" is not checked as "every letter".

## 0.1.4 — 2026-11-06

- When the turn is stopped (search loop, repeated refusals) and the model still answers the text-only request with a tool call, it is asked once more for plain text, then given a short fallback reply, instead of ending the turn on an error.

## 0.1.3 — 2026-11-05

- PyFigures adapter: an answer that explains how to do something in the GUI ends with two buttons, **highlight where to click** (outlines every route) and **open it for me** (opens the menus or the panel editor, never does the edit); a list of GUI choices gets **Show me where to click**. Added by the adapter, not left to the model.
- Choice buttons after a list of steps come from the closing question, not from the steps.
- PyFigures adapter: "swap channels 1 and 2" may reuse the colours the channels already show (their LUT, else the file's own colour) without naming them; channels cannot be reordered, so a swap moves the colours.

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
