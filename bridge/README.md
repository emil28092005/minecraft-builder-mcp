# Bridge

Local MCP tools and an in-game ACP client for `minecraft-builder-mcp`.

Requires Node.js 22.22.3+ and the project's running Paper plugin. Installation is reproducible from `package-lock.json`:

```bash
npm ci --ignore-scripts
npm test
```

Direct dependencies are pinned: `codex-acp` 1.11.0, ACP SDK 1.4.0, MCP SDK 1.30.0, Zod 4.6.2, and TypeScript 7.0.2. The transitive Codex version is pinned to 0.153.4. `npm ci` does not select newer versions.

## Running

Secrets come from environment variables, not command-line arguments. The plugin creates separate administrator and agent tokens. Do not commit them. `.env.example` shows the environment configuration; the bridge does not automatically load `.env`.

- `npm run doctor` checks Paper's `/health` when `MCB_TOKEN` is present, creates a separate minimal Codex configuration, and prints JSON containing settings, limitations, and the exact sign-in command.
- `npm run login` explicitly starts device-code sign-in in a separate Codex home; `npm run login -- status` checks that sign-in.
- `npm run mcp` starts MCP over stdio for an external agent. Requires `MCB_AGENT_TOKEN`, `MCB_PLAYER_ID`, and `MCB_PROJECT_ID`.
- `npm run chat` starts `/ai` polling and ACP. Requires `MCB_TOKEN` and `MCB_AGENT_TOKEN`.
- `node dist/rpc.js project_context` makes a direct diagnostic RPC with agent scope.

For this repository's local server, run `python3 scripts/bridge.py doctor`, `python3 scripts/bridge.py login`, `python3 scripts/bridge.py status`, and then `python3 scripts/bridge.py chat` from the repository root. The wrapper shares `.runtime/bridge-state` and reads Paper's private tokens itself. `status` is equivalent to `login status` or `login --status`; these commands only check sign-in and do not start authentication. `doctor`, `login`, and `status` can run before the Paper configuration exists. Do not mix sign-in through this wrapper with a plain `npm run chat` without the matching `MCB_STATE_DIR`: their default state directories differ.

`MCB_BACKEND_URL` defaults to `http://127.0.0.1:8765`. Only loopback HTTP is allowed; a remote server requires a local SSH tunnel. Player/project UUIDs come from trusted configuration or Paper's response, and the server rechecks ownership and scope. The prototype server supports one configured owner.

The game bridge launches the locally installed `codex-acp`, without `npx @latest`. It uses a separate Codex home at `.state/chat/codex-home`; sign-in and settings from the normal `~/.codex` are not copied automatically. Run `npm run login` once from the same working directory and with the same `MCB_STATE_DIR` used for `chat`. The helper uses the pinned Codex CLI with `login --device-auth`; authentication starts only when this command is explicitly invoked. The bridge does not open a browser itself or contact a model during builds or ordinary tests. For API-key authentication, set `MCB_OPENAI_API_KEY` or `MCB_CODEX_API_KEY` and `MCB_ACP_AUTH_METHOD=api-key`; the parent's generic `OPENAI_API_KEY` is not inherited.

Optional settings:

- `MCB_MODEL`: model ID, applied through the advertised ACP model selector. If unset, the adapter chooses.
- `MCB_ACP_COMMAND`: path to an alternative ACP agent. Otherwise, the current Node executable and pinned `codex-acp` are used.
- `MCB_ACP_ARGS`: JSON array of arguments, with no shell interpretation.
- `MCB_STATE_DIR`: state directory, defaulting to `.state/chat` relative to the working directory.
- `MCB_CODEX_HOME`: explicit path to a separate Codex home for sign-in. If a different `config.toml` already exists there, the bridge refuses to start and preserves that file; use a separate empty directory rather than the normal Codex profile.

The child process receives only allowlisted environment variables, separate HOME/XDG/CODEX_HOME directories, and a minimal configuration. Settings request `read-only`, `on-request`, user review, no network inside the command sandbox, and disabled shell, apps, browser, computer use, hooks, plugins, and additional agents. Sources and settings are in `src/security.ts`. Inspection of the pinned CLI confirmed that `shell_tool` and the listed integrations were disabled; that CLI keeps `unified_exec` enabled even when explicitly disabled, which doctor reports.

There is a limitation in `codex-acp` 1.11.0 itself: its `read-only` mode sends a `workspace-write` sandbox with networking disabled for every turn, rather than a literal read-only sandbox. As a result, the individual session directory and temporary paths may remain writable. The code does not claim complete OS isolation and has not yet been verified on a real model turn. Bridge/ACP/MCP processes also remain trusted local programs; Paper permissions are checked separately by the server.

The Bridge denies additional permission requests and reports this in the game. Interactive permission approval through Minecraft is not implemented. It does not advertise ACP file or terminal capabilities. Paper's administrator token is not passed to the child agent; MCP receives a separate restricted agent token. Check configuration with doctor after version changes or when system-wide Codex policies are present. The dynamically supplied Minecraft MCP override does not set `default_tools_approval_mode`: the pinned adapter passes only command/args/env and replaces the corresponding configuration table. MCP permission behavior therefore remains a check for the first real turn after user sign-in; a successful build and initialize do not prove that model-driven building already works.

## MCP

Tools: `project_context`, `region_inspect`, `build_prepare`, `build_apply`, `operation_status`, `operation_cancel`, `operation_undo_prepare`, `part_get`, `part_define`, `camera_list`, `camera_capture`, `asset_list`, `schematic_export`, `schematic_import_prepare`.

Version 1 recipe:

```json
{
  "version": 1,
  "operations": [
    {"type":"box","min":{"x":0,"y":64,"z":0},"max":{"x":4,"y":70,"z":4},"block":"minecraft:stone_bricks","hollow":true},
    {"type":"line","from":{"x":0,"y":64,"z":0},"to":{"x":8,"y":64,"z":8},"block":"minecraft:stone"},
    {"type":"cylinder","center":{"x":12,"y":64,"z":12},"radius":3,"height":8,"block":"minecraft:stone_bricks","hollow":true},
    {"type":"repeat","count":3,"offset":{"x":6,"y":0,"z":0},"operations":[{"type":"box","min":{"x":0,"y":64,"z":20},"max":{"x":1,"y":67,"z":21},"block":"minecraft:oak_log[axis=y]"}]}
  ]
}
```

An optional `part_id` in `build_prepare` restricts writes to the exact mask of a registered part; extensions use a separate part.

Tools send data to Paper for final validation and computation. The bridge does not store blocks or write to the world. MCP accepts one level of `repeat`; deeply nested repeats, arbitrary code, arches, and general transforms are not advertised yet. Supported block states and limits come from `project_context`.

`build_prepare` returns `plan_id` and `plan_hash`. Pass both to `build_apply` with a stable `idempotency_key`. After a timeout, writing may already have started: check `operation_status` first and reuse the same key. The bridge does not automatically retry writes.

The local `.schem` library supports up to 64 files, Sponge v2, dense regions of at most 4096 blocks, and rotations of 0/90/180/270°. Place files manually in the `schematics` directory inside the Paper plugin's data directory. `asset_list` returns metadata without invented previews; `schematic_export` saves a region and returns its ID; `schematic_import_prepare` creates a normal checked plan that is then applied through `build_apply`. Paths, entities, block entities, and unsupported blocks are rejected. The strict codec currently supports the original 61-material subset; the ten newer decorative materials in the building palette are not yet supported by `.schem`.

`camera_capture` returns `pending` and `captureId`; a request with `capture_id` reads the result. Only `completed` with a real image becomes MCP `ImageContent`. If the camera is absent or the capture is not ready, no image is fabricated. Ordinary text responses are limited to 64 KiB; reading an oversized region fails with a request to reduce its size. HTTP has time, input-size, and streaming response-size limits.

## Conversations and cancellation

One active turn per project, with up to eight queued messages. Different projects can run independently. Sessions and directories are separated by project and player UUID. Replies go only to the initiating player through `chat_reply`; public game chat, model reasoning, tool arguments, and adapter stderr are not broadcast.

Each request includes the player position, viewing direction, and targeted block supplied by the server, when available. Message output is limited to four messages per second per player.

The ACP session ID and latest compact summary are persisted by atomically replacing `session.json` with permissions `0600`. After restarting, the bridge tries `session/load`; if that fails, it starts a new conversation with the summary and explicitly reports the fallback. Replayed history is not shown in chat. An unfinished previous turn is marked separately; operations already started must be checked on Paper. The summary stores the latest request and outcome and does not replace `project_context`.

`/ai stop` must both set the server's write-stop flag and deliver a `type:"cancel"` event to the bridge. ACP cancels generation; blocks already changed remain in the journal. An interrupted agent that does not respond to cancellation within five seconds is terminated. On each launch, the bridge creates a `client_id` and passes it to `chat_poll`. A changed ID lets Paper stop active writes and finish outstanding leased requests while notifying the user; those requests are not replayed automatically. Paper's incoming message queue is currently in memory. After `/ai stop`, the server keeps writing paused until a new owner request or `/ai resume`.

## Verification

`npm test` runs HTTP tests and a real stdio MCP handshake, and uses a separate mock ACP process to test sessions, summaries, history suppression, permission denial, and cancellation. Queue tests verify serialization within a project and independence between projects. The real pinned `codex-acp` also passed a free `initialize`: ACP v1, `loadSession: true`, and authentication methods `api-key` and `chat-gpt` before environment restrictions. A repeat check in a separate home also passed; with `NO_BROWSER=1`, the adapter advertises only `api-key`, while ChatGPT sign-in uses the separate `login` helper. This does not prove ChatGPT authentication, model quality, or Minecraft behavior: those require the complete system running against a real server/client.

The optional `node test/live-paper.mjs` runs only against a separate real test Paper server: it checks a hollow cube, applying again with the same key, `.schem` export, the asset library, undo, import at the same anchor, a second undo back to 27 air blocks, bounds, and a truthful unavailable-camera response. It leaves the exported test asset in the local library. This test changes the world and is not part of ordinary `npm test`.

The original APIs were checked against the [ACP SDK](https://github.com/agentclientprotocol/typescript-sdk), [codex-acp](https://github.com/agentclientprotocol/codex-acp), [MCP SDK](https://github.com/modelcontextprotocol/typescript-sdk), [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference), and [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
