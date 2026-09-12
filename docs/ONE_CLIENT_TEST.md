# Single-client Prism test

The test used the existing **26.2 MCP Building** profile: Minecraft 26.2, Fabric Loader 0.19.5, Fabric API 0.160.0+26.2, and Java 25.0.1 supplied by Prism. The built `minecraft-builder-camera-0.1.0-SNAPSHOT.jar` was installed.

The user selected an offline profile for this local test. In this working installation, `.runtime/server/server.properties` contains `online-mode=false`, `server-ip=127.0.0.1`, and `server-port=25575`; the listening address was not broadened. This is a test configuration change; the normal initial setup through `dev-server.py` still enables account authentication.

In the plugin's private configuration, `owner-uuid` and `camera-player-uuid` match. The player was granted operator permissions on this test server; `allow-local-automation` remains disabled, and all calls used owner scope. The game mode was temporarily changed to spectator for photographs. After the test, the player was returned to creative on the platform in front of the tower; the plugin does not yet switch modes automatically.

## What was verified

1. Prism loaded the Fabric mod and connected one player to Paper. The HTTP worker reported a connection and the correct UUID.
2. A 575-block structure was prepared and applied through Paper's agent route in a previously empty area. A named part, `One-client camera test tower`, was created with the exact write mask.
3. The first capture stopped with `view_changed`, without returning a stale frame. On retry, the stationary client produced a real 1280×720 PNG. Metadata confirms the requested yaw/pitch, 20 stable ticks, and three frames; the request took 2.052 seconds after the operator delay.
4. A second viewpoint and a daylight version of the first were captured successfully.
5. A separate MCP stdio client requested a new capture and received one `ImageContent` containing a PNG. The text block contained only metadata, without base64. The capture ID, timestamp, PNG signature, and dimensions were checked. The image was viewed: it shows the test tower without the HUD.

All images are original Minecraft framebuffer data. They were neither AI-generated nor retouched. `serverRevisionVerified: false` remains an explicit limitation: client readiness is still heuristic. This test did not verify the first model turn through `codex-acp`.

Local results:

- `.runtime/camera-test/build.json` — plan/operation ID, block count, part, and region.
- `.runtime/camera-test/20260912T192813Z-2b100930.png` and the adjacent JSON — first successful viewpoint.
- `.runtime/camera-test/20260912T192831Z-776d8f9e.png` — second viewpoint.
- `.runtime/camera-test/20260912T192909Z-76b04afd.png` — daylight image.
- `.runtime/camera-test/mcp-975cd742-d23f-4b8d-bcc8-dc6e151a8f5c.png` and the adjacent JSON — image received through MCP.

The tower was left for inspection near `12, 95, 12`, on a platform at `x/z=4..20`, `y=94`. It overlaps the automated server tests' region. Before rerunning those tests, use a separate clean test world or a checked undo of this operation; the tests do not clear an occupied region themselves.

## Repeating a capture

The Prism profile uses the wrapper `python3 /path/to/minecraft-builder-mcp/scripts/camera-wrapper.py`. It reads the private camera token from Paper's configuration and passes it only to the Java process through its environment. The secret is not placed in `instance.cfg` or the command line. The original `instance.cfg` and `options.txt` are backed up in `.runtime/prism-one-client-backup`.

After connecting, run in the game:

```text
/gamemode spectator
/ai camera save test
```

Save the viewpoint inside the selected region. From the project root:

```bash
python3 scripts/live-camera-test.py --delay 8
```

Return to Minecraft, close menus/chat, and remain still until completion. The script saves a new PNG and sanitized metadata. You can then run `/gamemode creative` manually.

`bridge/test/live-camera.mjs` separately verifies MCP ImageContent. It requires the trusted variables `MCB_AGENT_TOKEN`, `MCB_PLAYER_ID`, `MCB_PROJECT_ID`, a JSON pose in `MCB_CAPTURE_POSE`, and optionally `MCB_AFTER_OPERATION_ID`. Capture moves the configured observer; this is an explicit integration test and is not included in ordinary `npm test`.
