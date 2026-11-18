# QtPy AI Sidecar

An independent, local-first assistant panel for desktop applications with MCP servers. Run it as a separate companion window or embed it in a QtPy application. This is the initial 0.1 developer version, extracted conceptually from the PyFigures experiment without importing or changing PyFigures source.

## Install and start

Requires Python 3.10+ and a supported Qt binding. The simplest installation selects PyQt6:

```sh
python -m pip install -e ".[qt]"
python -m qtpy_ai_sidecar
```

If your host already uses PySide6/PyQt, install without the `qt` extra and use its binding. Do not mix Qt bindings in one process. Installing Python dependencies may require network access; no model/runtime is downloaded merely by importing or launching the package.

In the standalone window:

- **Download icon:** search Hugging Face, list GGUF sizes, download a chosen single-file quantization, choose existing files, check official llama.cpp builds and optionally install one.
- **Plug icon:** choose sidecar-managed local inference, OpenAI, Claude, OpenRouter, Groq, or a custom compatible API. An LM Studio endpoint belongs in the custom API mode; the sidecar does not control its hardware. **OpenRouter** fills in `openrouter/free`: OpenRouter's free-models router, which sends each request to a free model that can handle it (images and tool calls included; 200k context). A fixed free model also works, such as `nvidia/nemotron-3.5-super-vl:free` (1M-token context, reads images; raise **Context tokens** in the gear dialog to use it). Some free models, such as `thinkingmachines/inkling:free`, are refused to apps not on OpenRouter's approved list; the chat says so. With **Model vision** on Automatic, OpenRouter's model list decides whether a model gets the previews. Free models are limited in requests per minute and per day (each chat message makes one request per tool step); credit on the account raises the daily quota. Free tiers that fit a chat with an application's tools (from the Free-LLM directory, November 2026; free offers change): **IteraCompute** (`qwen/qwen3.8-27b`, 30M tokens a month; slow in our tests, 30–120 s per step, so `openrouter/free` is the recommended free choice) and **NVIDIA NIM** (`nvidia/nemotron-3.5-super-vl-120b-a12b`, reads images). Each fills in its address and a model; **List models…** asks the provider which models your key can use. **Groq** (`qwen/qwen3.8-27b` filled in, 131k context, reads images) needs its paid tier: the free tier allows 7,000 input tokens per minute, less than one message with an application's tools. **Mistral AI API** fills in `mistral-large-4` (Mistral Large 4: 1M-token context, reads images; paid, with your own or your employer's key; `mistral-large-latest` still meant Large 3 in November 2026). The same key also reaches the Z.ai GLM models Mistral serves (`zai-glm-latest`, text only; `zai-glm-5-3-flash` reads images): **List models…** shows the chat models that call tools and marks those that read images. With **Model vision** on Automatic, Mistral's model list decides whether the model gets the previews. **Model vision** (eye button in the message box, or the gear dialog) has four choices: *Automatic* (real images for a model that reads them, else text), *Real images* (preview pixels go to the model, and to its provider when online), *Text descriptions only* (no image is ever sent; the tools' measured descriptions still are) and *Off* (previews are shown to the human only; their descriptions are withheld too, and the application's MCP server is told through `QTPY_AI_SIDECAR_VISION=none`). A saved `"vision": "off"` from earlier versions reads as *Text descriptions only*, which is what it did. Keys are pasted once and kept in the OS vault. With every provider, Claude included, a connection that cannot be opened and a brief server outage (HTTP 500, 502, 503, 504, Claude's 529 "overloaded") are retried after 2, 4, 8, 16 and 30 s. A short rate limit (HTTP 429) is waited out and retried up to three times; an account quota (tokens per minute, requests per day) is explained in plain words instead.
- **Your own providers:** in the plug dialog, **Add provider…** adds any other OpenAI-compatible API (a name, its address, the model to fill in, its thinking capability and, optionally, how its keys begin, so a key pasted under the wrong provider is refused). It is offered next time in every application using the sidecar (`providers.json` in the sidecar's user data folder); **Edit…** and **Remove** change it. Its key goes in the OS vault like the others. The dialog also remembers the last model used with each provider.
- **Model picker** (in the message box, beside the eye and brain buttons): switch between the models of the current connection, e.g. from `mistral-large-4` to `zai-glm-latest` on the same Mistral key. The provider's list is fetched in the background once the key is known, one entry per model (aliases merged); in the open list an eye marks the models that read images, a brain those that think before answering, and each entry's tooltip gives its context window. The closed picker shows the name only: the **eye button** beside it shows what the current model gets (an eye: real images; a page: text descriptions; a crossed eye: nothing visual) and its menu holds the four **Model vision** choices; the **brain button** is purple when the model thinks (grey when it does not, or thinking is off) and its menu holds **Thinking** (Default, On, Off) and **Strength** (Default, Low, Medium, High). Their tooltips say what the model does and what is chosen. The conversation goes on with the new model. Below the message box, **Context** is the estimated use (characters ÷ 3) of the **Context tokens** setting in the gear dialog, not a figure from the provider; when the provider gives the model's own window (Mistral, OpenRouter) it is shown beside it, with a warning when it is smaller than the setting. A green key means the connection's API key is stored; a red key and "(no API key)" mean it must be added first. Clicking the key changes it (**Change API key…**, or **Add API key…**; the key goes to the OS vault, and a key that plainly belongs to another provider is refused) or deletes the stored one, without opening the plug dialog. A key read from an environment variable (`api_key_env`) is changed there instead. Hidden for sidecar-managed local models (chosen in the Model Library).
- **Provider line** (under the title): the provider and model in use, e.g. "Provider: Mistral AI API · mistral-large-4 — change…"; click it to open the same dialog as the plug icon.
- **Tools icon:** import an application's MCP JSON configuration, or export the one in use as a standard `{"mcpServers": …}` file for another MCP client or computer. Credential fields must use environment references rather than secret literals, so an exported file holds no secret.
- **Gear icon:** context and output limits, supported thinking settings, CPU threads, GPU layers and **Force CPU**. Hardware settings apply only to the managed local runtime. **Maximum time for a closing answer** (60 s by default): when a turn stalls, the model is asked for a short text answer saying what was done; reasoning models need 30–60 s for it. A turn that keeps looking (previews, reads) without changing anything is told after 4 looks to act on its best estimate or ask one question, and after 8 it answers with what it found and that question; a stopped turn's message says why it stopped (no answer in time, an empty answer…).
- **Compress:** summarize older dialogue while retaining the latest ten dialogue messages exactly. The complete local log remains. `/compact` works too.
- **Your responsibility (asked once):** before the first message the user accepts that they are responsible for what they ask and for everything the chat does and sends on their behalf, even without typing it themselves (tool results, descriptions and previews), that models make mistakes and results must be checked, and that the software comes "as is", its authors accepting no liability. The first message to an online provider asks again, saying what leaves the computer and that sharing it must be allowed by the provider's terms and the user's institution. Declined, nothing is sent and the text stays in the box. The acceptance is kept per application in `accepted_terms.json` (local, online).
- **Export icon:** save readable Markdown and structured events together as a ZIP, with the pictures the chat showed (canvas snapshots, before/after previews) in `images/` and a screenshot of the window in `screenshots/`, linked from the Markdown. Attach it to bug reports.

Enter sends; Shift+Enter inserts a newline. Current numbered/bulleted clarification choices can be clicked into the composer. A host whose answers are lists of findings rather than options turns that off with `list_choices: false` (litsearch does); the user can change it in the gear dialog (**Turn listed options into follow-up buttons**), and options written inside the question itself (`**this** or **that**?`) stay clickable either way. **Bold** words in an answer can be clicked too: they go into the composer, ready to send or edit. Under the composer, a notice reminds that models make mistakes (hosts word it with `notice`); with an online provider a second line says explicitly that the messages, the content the chat reads and any images are sent outside this computer, to that provider (hosts word it with `remote_notice`, `{provider}` and `{host}` filled in). It is never shown for a model on this computer. Status, elapsed time, generation activity and context usage are below the composer. Context estimates are explicitly marked approximate; server-reported usage is shown when available. Loading/compression use an indeterminate progress bar; downloads display byte progress when size is known.

## Connect an application's MCP server

Supply a JSON configuration with `--config path/to/application.json`. Both stdio and streamable HTTP are supported; configured stdio commands are launched as child processes. Configure only servers you trust.

```json
{
  "application": "My application",
  "context_tokens": 16384,
  "output_tokens": 4096,
  "mcpServers": {
    "application": {
      "command": "python",
      "args": ["/absolute/path/to/application_mcp.py"]
    }
  }
}
```

An HTTP server uses `{"url":"http://127.0.0.1:8765/mcp"}` instead. MCP header/env values can reference environment variables (`${NAME}`; Windows also accepts `%NAME%`). Do not put secret literals in an application config. The model API key is handled separately by the vault UI.

`examples/demo.json` connects a small persistent demo document, independent of PyFigures. Run from the repository root, or replace its command/argument paths with absolute paths. A model capable of structured tool calling is required. Small MCP surfaces (at most 24 tools; `QTPY_AI_SIDECAR_MAX_DIRECT_TOOLS` changes the limit) are passed directly; large surfaces use paginated discovery, keeping all schemas out of the prompt until needed. Existing category-based servers therefore keep their efficient small surface.

## Embed in a Qt host

```python
from qtpy.QtCore import Qt
from qtpy_ai_sidecar import create_dock
from qtpy_ai_sidecar.config import Config

dock = create_dock(main_window, Config.load("application.json"))
main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
app.aboutToQuit.connect(dock.shutdown)
```

The host owns QApplication. Call `shutdown()` during application shutdown. Host-adapter methods run in the worker and must marshal native GUI work to the application's Qt thread. MCP normally performs that dispatch on the application side.

## Host features and PyFigures

The generic core does not pretend that arbitrary applications support transactions. An optional `HostAdapter` supplies fresh selection/state, per-message checkpoints, preview isolation and action controls. Only controls actually returned by the adapter are shown. The included `PyFiguresAdapter` connects to the existing prototype's authenticated loopback bridge without importing PyFigures. It supplies guarded message Undo/Redo, draft Apply/Discard, and a before/after slider where the host provides images.

For PyFigures, run the existing prototype GUI and connect this config (fill paths for your computer):

```json
{
  "application": "PyFigures",
  "adapter": {"type":"pyfigures", "descriptor":"/path/to/chatGPT_validation/live_mcp_gui/runtime/connection.json"},
  "mcpServers": {"pyfigures": {
    "command":"python",
    "args":["-B", "/path/to/chatGPT_validation/live_mcp_gui/live_mcp.py"],
    "env":{"PYFIGURES_MCP_SURFACE":"categories"}
  }}
}
```

The PyFigures prototype must be restarted to pick up its recent redo fixes. Use only one assistant to edit that document at a time. Original application source is unaffected. The adapter relies on the prototype bridge API; it is not yet an integration with a released PyFigures API.

Readability checks and PyFigures-specific editing policies remain in the original prototype/server for now; they are not universal features silently imposed on other applications. Interrupted tool transport marks the outcome uncertain and blocks subsequent requests until the human inspects and acknowledges. The core does not automatically replay work or promise arbitrary selective undo. Tool-step and output limits stop further submission and report completed edits may remain.

## Procedures: a chat's edits, saved and run again

The **Procedures** button of the chat panel (list icon) works for any connected application:

- **Replay a chat (turn by turn)…** plays a chat log or debug zip back in the chat panel: *Next turn* shows the request, runs the edits the model made then (*Apply the edits*; reads, failed calls and undone replies are not run), lists every call with what it gave then and now, and shows the model's answer then. *Play all* plays the rest. The model is not called. With **Ask the model again (live)** each recorded request is instead sent to the model in use (API calls; start from the same document): after each reply the edits it made are compared with the recorded ones (*same edits*, *same operations, other arguments*, *different edits*, *no edit now*), with the calls, the time and the answer then; a Markdown + JSON report lands in `chats/replays/`. Run it after changing an application's MCP tools or documentation, or with another model, to see whether the answers improve and stay consistent. A **setup turn** (a `user` event with `"setup": true`, shown with ⚙) puts the document in a known state: its recorded calls always run, in the live mode too, and the model is not asked. A chat assembled from many chats uses one before each of them, to rebuild the document that chat started from.
- **Save this chat as a procedure…** keeps the MCP calls that changed the application, in order, as a JSON file (next to the document when the application's state names one). Left out: reads and searches, failed calls, a reply undone with its Undo button, an edit the chat undid itself (a redo puts it back).
- **Run a procedure…** runs every step on the application as it is now, through its MCP servers, without the model; it stops at the first failed step.
- **Make a demo video from a chat…** (when the application can film a chat: its adapter's `make_demo_video(dock, chat)`, PyFigures does) makes an MP4 / GIF of part of a past chat without calling the model: choose the first and last request, the pacing and the format; the application films its window off-screen with the requests typed in the chat panel, the recorded edits run again one by one and the recorded answers shown as they appeared. In PyFigures: `python -m pyfigures.assistant.chat_video`.
- **Step through a chat or procedure…** lists the calls of a chat log, a debug-export zip or a procedure, with what each gave in the chat (*Then*) and now (*Now*); edit a call's arguments before running it, run up to a step, or save the steps as a procedure. A tool for debugging an application's MCP tools.

An application adapter may implement `procedure_role(name, arguments)` (edit, read, undo, redo or skip) and `describe_call(name, arguments)`; without them, names starting with get_/list_/inspect_/find_… read. Paths under the document's folder become `{folder}` / `{name}`, filled with the document a procedure runs on. Module: `qtpy_ai_sidecar.procedures` (no Qt). The file format:

```json
{"procedure": 1, "application": "PyFigures",
 "steps": [{"request": "rotate all by 25", "call": "use_pyfigures_tool", "arguments": {}}]}
```

## litsearch

[litsearch](https://github.com/baigouy/litsearch) (literature search over a local PDF index, PubMed, bioRxiv and arXiv) docks this panel in its own window: install both packages in one environment (`pip install -e path/to/qtpy_ai_sidecar -e "path/to/litsearch[gui,sidecar]"`), run `python -m litsearch.gui` and choose **View > Chat assistant** (Ctrl+Shift+A, or the button beside the tabs). The entry is absent when this package is not installed.

It follows the PyFigures pattern: the GUI serves an authenticated loopback bridge (a fresh token in a descriptor file readable by the user only, removed on exit), litsearch's MCP server (`python -m litsearch.sidecar.mcp_server`) forwards each tool call to it, and `LitsearchAdapter` (`adapters/litsearch.py`) reads the window's current state before every message, so "what did I find?" is answered without a tool step. `adapters/docking.py` docks the panel as for PyFigures. The tools act on the live window, whose labels they share: L1, L2… for local hits, P1, P2… for external articles.

| Tool | Changes |
|---|---|
| `inspect_litsearch`, `read_paper`, `show_figure`, `get_evidence`, `list_watches` | nothing (read-only) |
| `search_local`, `search_external`, `show_paper`, `set_summary` | what the window shows (results, selection, summary) |
| `manage_watch` (save / run / delete), `export_results`, `library` (list / index / remove / download / open) | files: a watch's settings, its state and report; an HTML report or BibTeX/RIS bibliography; the PDF index and downloaded PDFs (`library` with `action="list"` is read-only) |

Twenty-two tools, one per task, passed to the model directly (up to 24 are; more go behind a search step). litsearch has no undo, so no Undo/Redo controls are shown; `manage_watch` runs and `library` indexing start background jobs that the state reports when they finish. The provider and model are this panel's own connection settings for "litsearch" (first-run preset: Mistral AI API, `mistral-large-4`); keys stay in the OS vault, and litsearch's NCBI key stays in litsearch's own settings, never in the chat. The standalone window can also connect to a running litsearch with `{"adapter": {"type": "litsearch", "descriptor": "~/.litsearch/sidecar/connection.json"}}` and the same MCP server in its config.

## Optional embeddings

**Tools icon > Embeddings (optional)…** chooses a text-embeddings source for the applications that need one (litsearch indexes and searches PDFs with it; PyFigures searches folders of images with it). Off by default; the chat never uses it, and it adds no dependency (`embeddings.py`, `embeddings_dialog.py`, loaded only when used). The choice is shared by every application using the sidecar (`embeddings.json` beside `providers.json`):

- **Mistral AI API** (`mistral-embed`): uses the key already stored for the Mistral chat provider, nothing more to set up. It sends the texts to Mistral (for litsearch, the full text of the PDFs you index); check that your agreement covers unpublished material. With this source, litsearch's automatic OCR also reads scanned pages with Mistral OCR (same key).
- **Local server**: any OpenAI-compatible `/v1/embeddings` server on this computer, e.g. `llama-server -m nomic-embed-text-v1.5.Q8_0.gguf --embedding --port 8081`, Ollama or LM Studio. Nothing leaves the computer.

**Image descriptions** (the dialog's last field) is the vision model that describes pictures in words for image search, since the embedding models read text only: `mistral-small-latest` by default with the Mistral source (`pixtral-large-latest` describes better and costs more), none with a local server unless you name a vision model it serves. It is used only when a host indexes images (PyFigures' `index_image_folder`), and then sends a small thumbnail of each image to that model.

**Test** embeds one sentence with the settings shown. An index built with one model can only be searched with that model, so a host should record `Embedder.model_id` beside its vectors (litsearch does, and refuses a mismatch with a clear message). For a host: `from qtpy_ai_sidecar import embeddings; e = embeddings.configured()` gives `None` when off, else `e.embed(texts)` (synchronous, batched, retried on HTTP 429/5xx); `e.describe(jpeg_bytes, prompt)` returns the vision model's text, `e.vision_id` names that model (`''` when there is none).

## Local runtime and modest hardware

The sidecar owns only the llama-server process it starts. It never stops other servers or changes system GPU drivers. Downloads and updates are explicit. The managed installer selects compatible official Windows ZIPs or macOS/Linux tarballs for x64/ARM64. macOS uses Metal or CPU; Windows/Linux offer Vulkan or CPU. Official Linux binaries require compatible Ubuntu/glibc libraries; users of other distributions can choose a locally built executable.

**Force CPU** sets `-ngl 0`, `--device none`, `--no-op-offload` and `--no-kv-offload`. Changing runtime settings stops the owned model; the next request reloads it. Use a CPU build for environments where loading accelerator libraries is undesirable. No hardware controls are offered for API connections, including separately managed local servers.

Smaller context limits reduce KV-cache memory; smaller quantizations/models reduce weight memory. Output limit and context size are separate. Thinking can be default/enabled/disabled, with low/medium/high effort where supported. Effort is model/template dependent, not a universal guarantee. A thinking token budget is available for compatible managed llama.cpp builds and Claude's legacy manual-thinking mode. Newer Claude models require the adaptive capability instead; choose the capability appropriate to the model. Unsupported backends keep thinking overrides disabled. Older llama.cpp builds may reject newer reasoning/CPU flags; use the update manager or a compatible build.

## API credentials and privacy

The default is local; there is no automatic fallback to a paid provider. API mode is an explicit connection selection. It sends conversation and MCP tool results to the chosen endpoint and may incur charges. ChatGPT/Claude subscriptions and API billing are separate.

Saved API keys use native OS vaults via `keyring`: Windows Credential Manager, macOS Keychain, or supported Linux Secret Service/libsecret/KWallet backends. Plaintext, null and third-party file backends are rejected. If no secure vault is available, saving fails clearly; there is no plaintext fallback. Native secure backends inside a keyring chain can be selected. Keys can be removed in the connection dialog. Advanced deployments can supply `api_key_env`; the application never persists that environment value.

Keys exist briefly in process memory and HTTP headers while used. Known keys and common credential fields are redacted from event logs. Exported logs still contain user conversation/document content, file paths, the pictures shown in the chat and a screenshot of the window; review them before sharing. Configs, raw credentials, model files and figure files are not bundled into debug exports. Remote credentialed requests require HTTPS; HTTP is allowed only for local loopback endpoints. TLS verification remains enabled.

Settings/logs/downloads live in per-user platform data folders, grouped by application name. `state_dir` can override that for a fully self-contained deployment or isolated tests. No personal paths, models or credentials belong in Git.

## Validation and current status

Run `python -m pytest` with the test extra installed. On headless systems set `QT_QPA_PLATFORM=offscreen`; if the environment has unrelated pytest plugins use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. CI exercises Windows/macOS/Linux with PyQt6. Windows has been tested locally; other OS execution awaits CI/native machines. Runtime asset mappings and Unix archive extraction are covered by portable unit tests.

Tests use actual local MCP subprocesses and controlled streaming HTTP servers. Paid providers are tested for request/stream/tool formats without spending credits. No real cloud credential or large model download is required. This first package is a reusable foundation, not a claim that all prototype integrations or every provider/model combination have production validation. Packaging into native installers and publishing to PyPI/GitHub are outside this initial local commit.

Implementation references: [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server), [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Claude streaming](https://platform.claude.com/docs/en/build-with-claude/streaming), [OpenRouter](https://openrouter.ai/docs/quickstart).


### Follow-up editing safeguards
Tool IDs are stable across reconnects. Completed tool calls/results and discovered schemas remain in working context until explicit compression or the context budget is reached; a new message no longer discards them.
For simple PyFigures letter-color edits, the host can finish immediately from exact verified target/color readback, without another model generation. Compound requests remain with the model.
Model responses have an adjustable time cap (120 seconds by default, under Performance settings). This is separate from context and output-token limits; no context reduction is implied. An incomplete response is never executed as a tool call. A text-only recovery, when needed, has no tools and does not replay edits.

## Licence

BSD 2-Clause (see [LICENSE](LICENSE)). Copyright (c) 2026, Benoit Aigouy.
