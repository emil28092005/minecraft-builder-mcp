# minecraft-builder-mcp

A Minecraft building editor for collaboration between a human and an AI agent.

Working prototype: a Paper plugin, an editing core, an MCP/ACP Bridge, and a Fabric camera mod. Building, conflicts, undo, crash recovery, and `.schem` have been tested against local Paper through HTTP and real MCP stdio. The camera has been tested in Prism with one client: a real 1280×720 PNG was delivered through MCP. Signing in to the separate Codex profile and completing the first model turn through ACP still need verification.

## Features

- Reads bounded regions and builds boxes, lines, cylinders, and repeated elements.
- Saves a plan before applying it in slices with live block checks. Manual changes stop conflicting writes; undo also checks the current world state.
- Keeps an on-disk journal, distinguishes request retries from new operations, and stops ambiguous operations after a crash.
- Saves named parts and their protection, and exports/imports a limited Sponge v2 `.schem` subset through the same planning engine.
- Provides 14 MCP tools and `/ai` game chat through a pinned `codex-acp` adapter.
- Captures real images through a local worker on a spectator client. A single client with the owner temporarily in spectator has also been tested.

The current scope is one owner, one project, and one world, with at most 4096 blocks per plan, loaded chunks only, and a limited vanilla material palette. A complete delta history, automatic merging of manual edits, and the full design document are not implemented yet. [Detailed status and limitations](docs/IMPLEMENTATION.md).

The building palette contains 71 materials. Decorative additions include lanterns, `iron_chain` (the Minecraft 26.2 ID), iron bars, stone brick walls, persistent oak leaves, moss, gray/brown stained glass, glowstone, and gold blocks. Leaves require `persistent=true`; waterlogged states remain unsupported. The strict `.schem` codec currently retains the original 61-material subset.

## Build

Verified environment: Linux x64, Minecraft/Paper 26.2, Java 25, and Node.js 22.22.3+. From the repository root:

```bash
./scripts/build.sh
```

The script downloads pinned JDK 25.0.2 and Maven 3.9.11 into the user cache with hash verification, installs Bridge dependencies from the lockfile, and builds all three components with tests. It does not replace system Java. Python 3, Node.js, and npm must already be installed. [Pinned versions](docs/compatibility.json).

Build outputs:

- `paper-plugin/target/paper-plugin-0.1.0-SNAPSHOT.jar` — server plugin, including the editing core.
- `camera-mod/build/libs/minecraft-builder-camera-0.1.0-SNAPSHOT.jar` — client mod.
- `bridge/dist/` — executable MCP/ACP components.

## Local setup

1. Prepare a separate test Paper server. On first installation, read the [Minecraft EULA](https://www.minecraft.net/eula), then explicitly accept it:

   ```bash
   python3 scripts/dev-server.py --accept-eula --run
   ```

   For subsequent runs, use `python3 scripts/dev-server.py --run`. The server lives in `.runtime/server`, listens on `127.0.0.1:25575`, and keeps Minecraft authentication enabled. The user has accepted the EULA for the server already prepared in this workspace.

2. Connect a Minecraft Java 26.2 client to `127.0.0.1:25575`. In **that server's** console, grant your game account operator access with `op <name>`. In the game, run:

   ```text
   /ai setup
   /ai area here
   ```

   The second command selects an area around the player. Chunks must be loaded, and blocks next to writes must be supported. Set exact bounds with `/ai area minX minY minZ maxX maxY maxZ`.

3. From another terminal at the project root, check the settings and sign in to the separate Codex profile:

   ```bash
   python3 scripts/bridge.py doctor
   python3 scripts/bridge.py login
   python3 scripts/bridge.py login --status
   ```

   The user completes sign-in using a device code. The helper reads local Paper tokens without printing them. It does not copy the normal `~/.codex` profile; project state lives in `.runtime/bridge-state`. The first real turn still needs to confirm authentication and MCP permissions in the pinned adapter.

4. Start chat:

   ```bash
   python3 scripts/bridge.py chat
   ```

   You can now send `/ai Build a small tower next to me`. Set `MCB_MODEL` to choose a model; otherwise the adapter chooses. `/ai status` reports status, and `/ai stop` stops further writes and the agent request. Changes already made require a separate checked undo.

Connect MCP to an external client using `python3 scripts/bridge.py mcp`. Owner scope comes from the Paper configuration. This command is intended for a client that launches MCP over stdio, rather than an interactive terminal.

## Camera

An ordinary player does not need the mod. For the observer, install the pinned Fabric Loader and API versions and add the camera JAR to a separate 26.2 profile. Before launching, pass `MCB_CAMERA_TOKEN` from the plugin's private `camera-token` setting to that process; set `camera-player-uuid` in Paper and restart the server. The observer must connect in spectator mode.

If the builder and observer play simultaneously, they need valid separate game sessions. With one client, set the camera UUID to the owner's UUID and temporarily enable spectator mode. This scenario has been verified in the Prism profile **26.2 MCP Building**; `scripts/camera-wrapper.py` passes the secret to Java without adding it to Prism's logged variables. See the [camera instructions](camera-mod/README.md) for the exact procedure and capture limitations. Once connected, `/ai camera save name` saves the owner's viewpoint. [Local single-client test results](docs/ONE_CLIENT_TEST.md).

## Tests and documentation

```bash
./mvnw test
npm --prefix bridge test
JAVA_HOME="$HOME/.cache/minecraft-builder-mcp/jdk-25.0.2" camera-mod/gradlew --project-dir camera-mod test
```

`python3 scripts/live-server-test.py` starts and stops its own process in `.runtime/server`, checks conflicts and undo, deliberately terminates that process to test recovery, and then exercises MCP and `.schem`. First build the project, run the plugin once, and accept the EULA; any existing server must be stopped. This test targets the prepared test world and changes only bounded test regions. Results are saved in `.runtime/live-server-results.json` and `.runtime/live-mcp-results.log`.

- [Project design and future phases](docs/DESIGN.md).
- [Implementation status and verification](docs/IMPLEMENTATION.md).
- [Gothic hall from a reference: 29,354 blocks in the live world](docs/builds/GOTHIC_HALL.md).
- [Protocol](docs/PROTOCOL.md), [editing core and journal](world-core/README.md).
- [Bridge, sign-in, and ACP limitations](bridge/README.md).

Git is initialized on branch `main`. Generated worlds, secrets, dependencies, and build outputs are excluded by `.gitignore`.
