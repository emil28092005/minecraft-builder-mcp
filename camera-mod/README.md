# Minecraft Builder Camera

A client-side Fabric mod for `minecraft-builder-mcp`. It provides real PNG images from Minecraft's framebuffer through an authenticated local HTTP interface. Rendering requires a running client with a working graphics environment. The mod is separate from the server JAR and does not modify blocks.

## Pinned platform

- Minecraft Java Edition **26.2**, Java **25**.
- Fabric Loader **0.19.5**, Fabric API **0.160.0+26.2**.
- Fabric Loom **1.17.20**, Gradle Wrapper **9.5.1** (distribution SHA-256 is verified).
- JUnit **5.12.2** is used only to build and run tests.

Versions were checked against [Fabric Maven](https://maven.fabricmc.net/), [Fabric Meta](https://meta.fabricmc.net/v2/versions/loader/26.2), and the [official 26.2 example](https://github.com/FabricMC/fabric-example-mod/tree/26.2). Since 26.1, Minecraft is unobfuscated; this build needs neither Yarn nor name remapping. [Fabric instructions for 26.2](https://www.fabricmc.net/2026/06/15/262.html).

## Build and installation

```bash
cd camera-mod
JAVA_HOME=/path/to/jdk-25 ./gradlew build
```

Output: `build/libs/minecraft-builder-camera-0.1.0-SNAPSHOT.jar`. Install it and the pinned Fabric API in a separate Minecraft 26.2 profile with Fabric Loader. An ordinary builder's client does not need this mod.

Set the process environment before launching the profile:

```bash
export MCB_CAMERA_TOKEN='<separate secret of at least 32 characters>'
export MCB_CAMERA_PORT=8766
```

Set the same secret in the Paper plugin's camera configuration. Paper accepts 32–512 characters from `A–Z`, `a–z`, `0–9`, `.`, `_`, `~`, and `-`, without spaces or line breaks; the automatically generated value already meets these requirements. All three Paper tokens must differ. Without `MCB_CAMERA_TOKEN`, the HTTP service is disabled. `MCB_CAMERA_PORT` is optional; allowed ports are 1024–65535. The address is always `127.0.0.1`, with no option to bind a public interface.

Launch a separate observer, connect to the intended Paper server, and switch it to spectator using an authorized server mechanism. Configure the observer's UUID in the Paper plugin. A valid separate game session is required if the builder stays on the server simultaneously; the mod does not bypass authentication or account restrictions. Keep client menus closed and do not spectate another entity. A minimized window may stop rendering and cause a timeout.

### One client through Prism

A local test can use one account: the project owner also acts as the camera. This configuration has been tested with a real Prism client and Paper 26.2. Install the mod and dependencies in the selected profile, connect to the server, and register the owner with `/ai setup`. In Paper's private configuration, `camera-player-uuid` must match `owner-uuid`. The owner must be online, have the `minecraftbuilder.use` permission, and be in spectator mode. Configuration changes take effect after restarting the plugin/server.

To keep the secret out of Java arguments and launcher logs, use [scripts/camera-wrapper.py](../scripts/camera-wrapper.py) as the Prism profile's `WrapperCommand`, for example `python3 /path/to/minecraft-builder-mcp/scripts/camera-wrapper.py`. The wrapper reads `camera-token` and `camera-port` from the private `.runtime/server/plugins/MinecraftBuilderMCP/config.yml` and passes them only through the child process environment. Set `MCB_CAMERA_PAPER_CONFIG` to use a different configuration path.

Save a viewpoint inside the project region with `/ai camera save test`. Then run from the repository root:

```bash
python3 scripts/live-camera-test.py --camera-id test --delay 8
```

[scripts/live-camera-test.py](../scripts/live-camera-test.py) checks that the owner and camera UUIDs match, spectator mode is active, and Paper is accessible. After eight seconds it calls the real `camera_capture` through Paper's authenticated HTTP route, waits for the PNG, and saves the original bytes with sanitized metadata in `.runtime/camera-test`. Instead of a saved viewpoint, pass `--pose X Y Z YAW PITCH`, optionally adding `--fov 85` for an overview of a large building (allowed range: 30–110°); `--after-operation-id` links the capture to a completed operation.

Before capture begins, return to Minecraft, close chat and menus, stop moving, and keep the mouse still. Rotation tolerance is only 0.1°, so even slight movement cancels the image. Switching windows may open the pause menu. In this mode, capture temporarily uses your game view; the server teleport changes your position. Your game mode and previous position are not restored automatically. Choose the desired mode and location manually when returning to building.

## Protocol

All requests, including health checks and image retrieval, require `Authorization: Bearer <MCB_CAMERA_TOKEN>`. JSON is not written to the log.

- `GET /health` — cached state from the latest client tick: `status`, `connected`, `spectator`, `busy`, `dimension`, `playerId`, and `updatedAt`. A stale `updatedAt` means the client has stopped updating.
- `POST /v1/capture` — queue one capture. HTTP 202 response: `{"status":"pending","captureId":"<uuid>"}`. A busy camera returns HTTP 409 and `camera_busy`.
- `GET /v1/captures/<uuid>` — retrieve `pending`, `completed`, or `error`. Unknown/expired IDs return HTTP 404. A terminal `error` contains `error` and `message`, without an image.

Example capture body:

```json
{
  "x": 16.5, "y": 90, "z": 16.5,
  "yaw": 45, "pitch": 25,
  "fov": 70, "width": 1280, "height": 720,
  "dimension": "minecraft:overworld",
  "afterOperationId": "operation-id"
}
```

`x/y/z` specify the **observer player's feet position**, as in Paper teleportation. Paper first checks the region and permissions and teleports the configured observer, then calls capture. The mod waits for the requested position and dimension to arrive; it does not send `/tp` or override local position. `dimension` is the client's dimension key, rather than a directory name or Bukkit UUID. Additional `world`/`world_id` fields are accepted for envelope compatibility but are not used to verify the dimension. `dimension` is optional in the low-level interface; the server route should supply it.

Paper's `camera_capture` route forwards the POST request and polls the matching GET when `capture_id` is present. The Bridge determines the external MCP tool names.

A `completed` result contains `imageBase64`, `mimeType: "image/png"`, `captureId`, `capturedAt`, `dimension`, feet position, `eyeY`, actual yaw/pitch, base FOV, source framebuffer and output image dimensions, and readiness metadata.

`width`/`height` specify maximum output dimensions. The capture fits within them while preserving aspect ratio and without upscaling; it does not resize the game window. This avoids distorting geometry. For exactly 1280×720, use a sufficiently large framebuffer with the same aspect ratio. Base FOV is limited to 30–110, width to 320–1920, and height to 180–1080; the source framebuffer is limited to 16 megapixels. Pose values must be finite, with yaw in -360..360 and pitch in -90..90.

## What readiness means

Before capture, the mod checks spectator mode, position agreement (±0.05 blocks), dimension, and use of the observer's own view. It hides the HUD, switches to first-person, and disables view bobbing and movement effects on FOV. It then waits for:

1. Nine client chunks around the observer to remain available for at least 20 consecutive ticks.
2. Three frames with an initialized camera, available chunks, and an empty geometry preparation queue.
3. The pose and window to remain suitable until framebuffer readback.

PNG capture uses `Screenshot.takeScreenshot` after the frame renders, with GPU readback through Blaze3D and no direct OpenGL code. PNG encoding and downscaling run on a separate thread. The HUD, FOV, perspective, view bobbing, and rotation saved when the mod starts handling the capture are restored on the client thread after success or error. Saving starts after the server position arrives; this does not return the player to the position before teleportation. The server remains authoritative over the post-teleport position.

This is a **checked loading heuristic**, not confirmation of a specific server revision. The response always contains `readiness: "local_chunks_and_render_queue_stable"` and `serverRevisionVerified: false`. `afterOperationId` is for correlation; by itself it does not prove the client received every update from that operation. Do not present this result as revision verification. Strict freshness requires an additional server marker and acknowledgment that the corresponding packets were processed. Distant geometry outside the checked chunks and changes after capture remain limitations.

Loading failures, disconnection, world/position changes, open menus, rotation interference, and missing framebuffer data return an error instead of a stale image. A separate thread enforces the 20-second timeout even if rendering hangs. Another capture is allowed after state restoration on the client thread. At most four results are retained for up to two minutes; PNGs are limited to 8 MiB and request bodies to 8192 bytes. Images remain in memory and are not written to the shared screenshots directory.

## Verification and prototype limits

`./gradlew build` compiles the mod against real Minecraft 26.2 dependencies; tests cover HTTP bearer authentication, request-size limits, and parameter validation. These tests do not launch the client or sign in to an account.

A real graphical test ran on September 12, 2026: one Prism client, the project owner in spectator mode, matching owner and camera UUIDs, Paper 26.2, and a completed 575-block tower. Mixin loading, client connection, server teleportation, framebuffer readback, and PNG delivery through Paper HTTP were verified. The image shows the built tower without the HUD.

The first request ended with `view_changed`: actual rotation differed from the requested rotation. A retry after stabilization produced a **1280×720 PNG in 2.052 seconds**, with yaw **140°**, pitch **31°**, after **20 ticks** and **3 frames** of readiness. This is a verified local measurement of one request, not a timing guarantee for other scenes or computers. Verification artifacts: `.runtime/camera-test/20260912T192813Z-2b100930.png` and its JSON metadata; they remain local and are excluded from Git.

The successful image was captured after the building operation completed and includes its `afterOperationId`, but **`serverRevisionVerified` remains `false`**: processing of a specific server revision is not yet acknowledged. Remaining checks include restoration of all view settings, timeout with a minimized window, disconnection during capture, third-party shaders, and a separate camera account. The working graphical cycle is verified for the single-client scenario described above.
