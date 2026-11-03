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
- **Plug icon:** choose sidecar-managed local inference, OpenAI, Claude, OpenRouter, Groq, or a custom compatible API. An LM Studio endpoint belongs in the custom API mode; the sidecar does not control its hardware. **OpenRouter** fills in `openrouter/free`: OpenRouter's free-models router, which sends each request to a free model that can handle it (images and tool calls included; 200k context). A fixed free model also works, such as `nvidia/nemotron-3.5-super-vl:free` (1M-token context, reads images; raise **Context tokens** in the gear dialog to use it). Some free models, such as `thinkingmachines/inkling:free`, are refused to apps not on OpenRouter's approved list; the chat says so. With **Show previews to the model** on Automatic, OpenRouter's model list decides whether a model gets the previews. Free models are limited in requests per minute and per day (each chat message makes one request per tool step); credit on the account raises the daily quota. Free tiers that fit a chat with an application's tools (from the Free-LLM directory, November 2026; free offers change): **IteraCompute** (`qwen/qwen3.8-27b`, 30M tokens a month; slow in our tests, 30–120 s per step, so `openrouter/free` is the recommended free choice) and **NVIDIA NIM** (`nvidia/nemotron-3.5-super-vl-120b-a12b`, reads images). Each fills in its address and a model; **List models…** asks the provider which models your key can use. **Groq** (`qwen/qwen3.8-27b` filled in, 131k context, reads images) needs its paid tier: the free tier allows 7,000 input tokens per minute, less than one message with an application's tools. **Mistral AI API** fills in `mistral-large-4` (Mistral Large 4: 1M-token context, reads images; paid, with your own or your employer's key; `mistral-large-latest` still meant Large 3 in November 2026). The same key also reaches the Z.ai GLM models Mistral serves (`zai-glm-latest`, text only; `zai-glm-5-3-flash` reads images): **List models…** shows the chat models that call tools and marks those that read images. With **Show previews to the model** on Automatic, Mistral's model list decides whether the model gets the previews. Keys are pasted once and kept in the OS vault. A short rate limit (HTTP 429) is waited out and retried up to three times; an account quota (tokens per minute, requests per day) is explained in plain words instead.
- **Model picker** (in the message box, beside the thinking controls): switch between the models of the current connection, e.g. from `mistral-large-4` to `zai-glm-latest` on the same Mistral key. The provider's list is fetched in the background once the key is known, one entry per model (aliases merged); an eye marks the models that read images, a brain those that think before answering, and each entry's tooltip gives its context window. The conversation goes on with the new model. Below the message box, **Context** is the estimated use (characters ÷ 3) of the **Context tokens** setting in the gear dialog, not a figure from the provider; when the provider gives the model's own window (Mistral, OpenRouter) it is shown beside it, with a warning when it is smaller than the setting. A green key means the connection's API key is stored; a red key and "(no API key)" mean it must be added with the plug icon first. Hidden for sidecar-managed local models (chosen in the Model Library).
- **Tools icon:** import an application's MCP JSON configuration. Credential fields must use environment references rather than secret literals.
- **Gear icon:** context and output limits, supported thinking settings, CPU threads, GPU layers and **Force CPU**. Hardware settings apply only to the managed local runtime.
- **Compress:** summarize older dialogue while retaining the latest ten dialogue messages exactly. The complete local log remains. `/compact` works too.
- **Export icon:** save readable Markdown and structured events together as a ZIP.

Enter sends; Shift+Enter inserts a newline. Current numbered/bulleted clarification choices can be clicked into the composer. Status, elapsed time, generation activity and context usage are below the composer. Context estimates are explicitly marked approximate; server-reported usage is shown when available. Loading/compression use an indeterminate progress bar; downloads display byte progress when size is known.

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

`examples/demo.json` connects a small persistent demo document, independent of PyFigures. Run from the repository root, or replace its command/argument paths with absolute paths. A model capable of structured tool calling is required. Small MCP surfaces (at most twelve tools) are passed directly; large surfaces use paginated discovery, keeping all schemas out of the prompt until needed. Existing category-based servers therefore keep their efficient small surface.

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

## Local runtime and modest hardware

The sidecar owns only the llama-server process it starts. It never stops other servers or changes system GPU drivers. Downloads and updates are explicit. The managed installer selects compatible official Windows ZIPs or macOS/Linux tarballs for x64/ARM64. macOS uses Metal or CPU; Windows/Linux offer Vulkan or CPU. Official Linux binaries require compatible Ubuntu/glibc libraries; users of other distributions can choose a locally built executable.

**Force CPU** sets `-ngl 0`, `--device none`, `--no-op-offload` and `--no-kv-offload`. Changing runtime settings stops the owned model; the next request reloads it. Use a CPU build for environments where loading accelerator libraries is undesirable. No hardware controls are offered for API connections, including separately managed local servers.

Smaller context limits reduce KV-cache memory; smaller quantizations/models reduce weight memory. Output limit and context size are separate. Thinking can be default/enabled/disabled, with low/medium/high effort where supported. Effort is model/template dependent, not a universal guarantee. A thinking token budget is available for compatible managed llama.cpp builds and Claude's legacy manual-thinking mode. Newer Claude models require the adaptive capability instead; choose the capability appropriate to the model. Unsupported backends keep thinking overrides disabled. Older llama.cpp builds may reject newer reasoning/CPU flags; use the update manager or a compatible build.

## API credentials and privacy

The default is local; there is no automatic fallback to a paid provider. API mode is an explicit connection selection. It sends conversation and MCP tool results to the chosen endpoint and may incur charges. ChatGPT/Claude subscriptions and API billing are separate.

Saved API keys use native OS vaults via `keyring`: Windows Credential Manager, macOS Keychain, or supported Linux Secret Service/libsecret/KWallet backends. Plaintext, null and third-party file backends are rejected. If no secure vault is available, saving fails clearly; there is no plaintext fallback. Native secure backends inside a keyring chain can be selected. Keys can be removed in the connection dialog. Advanced deployments can supply `api_key_env`; the application never persists that environment value.

Keys exist briefly in process memory and HTTP headers while used. Known keys and common credential fields are redacted from event logs. Exported logs still contain user conversation/document content and file paths; review them before sharing. Configs, raw credentials, model files and figure files are not bundled into debug exports. Remote credentialed requests require HTTPS; HTTP is allowed only for local loopback endpoints. TLS verification remains enabled.

Settings/logs/downloads live in per-user platform data folders, grouped by application name. `state_dir` can override that for a fully self-contained deployment or isolated tests. No personal paths, models or credentials belong in Git.

## Validation and current status

Run `python -m pytest` with the test extra installed. On headless systems set `QT_QPA_PLATFORM=offscreen`; if the environment has unrelated pytest plugins use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`. CI exercises Windows/macOS/Linux with PyQt6. Windows has been tested locally; other OS execution awaits CI/native machines. Runtime asset mappings and Unix archive extraction are covered by portable unit tests.

Tests use actual local MCP subprocesses and controlled streaming HTTP servers. Paid providers are tested for request/stream/tool formats without spending credits. No real cloud credential or large model download is required. This first package is a reusable foundation, not a claim that all prototype integrations or every provider/model combination have production validation. Packaging into native installers and publishing to PyPI/GitHub are outside this initial local commit.

Implementation references: [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server), [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Claude streaming](https://platform.claude.com/docs/en/build-with-claude/streaming), [OpenRouter](https://openrouter.ai/docs/quickstart).


### Follow-up editing safeguards
Tool IDs are stable across reconnects. Completed tool calls/results and discovered schemas remain in working context until explicit compression or the context budget is reached; a new message no longer discards them.
For simple PyFigures letter-color edits, the host can finish immediately from exact verified target/color readback, without another model generation. Compound requests remain with the model.
Model responses have an adjustable time cap (120 seconds by default, under Performance settings). This is separate from context and output-token limits; no context reduction is implied. An incomplete response is never executed as a tool call. A text-only recovery, when needed, has no tools and does not replay edits.
