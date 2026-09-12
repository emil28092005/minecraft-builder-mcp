#!/usr/bin/env python3
"""Capture a real PNG through Paper and the Fabric worker using one online owner/spectator.

Does not start Minecraft/Paper, change configuration, or fabricate/alter images. By default,
uses the pose saved in game with /ai camera save test. Run with --delay 8 and return to the
Minecraft window, close menus, and keep the player still until the capture completes.
"""
import argparse
import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
MAX_RESPONSE = 12 * 1024 * 1024
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
SAFE_METADATA = {
    'status', 'captureId', 'capturedAt', 'dimension', 'x', 'y', 'z', 'eyeY', 'yaw', 'pitch',
    'fov', 'readiness', 'serverRevisionVerified', 'loadedChunkRadius', 'stabilizationTicks',
    'stabilizationFrames', 'afterOperationId', 'width', 'height', 'sourceWidth', 'sourceHeight',
    'mimeType',
}


class TestFailure(Exception):
    """Messages are selected locally and never contain raw HTTP bodies or header values."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise TestFailure('Refusing an HTTP redirect from the local camera/Paper endpoint.')


def scalar(text, key):
    matches = re.findall(r'^' + re.escape(key) + r':[ \t]*(.*?)[ \t]*$', text, re.M)
    if len(matches) != 1:
        raise TestFailure('Missing or duplicate top-level configuration field: ' + key)
    raw = matches[0].strip()
    if raw.startswith("'"):
        match = re.fullmatch(r"'((?:[^']|'')*)'[ \t]*(?:#.*)?", raw)
        if match:
            return match.group(1).replace("''", "'")
    elif raw.startswith('"'):
        match = re.fullmatch(r'("(?:[^"\\]|\\.)*")[ \t]*(?:#.*)?', raw)
        if match:
            try:
                value = json.loads(match.group(1))
                if isinstance(value, str):
                    return value
            except (ValueError, TypeError):
                pass
    else:
        return re.split(r'[ \t]+#', raw, maxsplit=1)[0].strip()
    raise TestFailure('Use a single Paper-generated scalar for configuration field: ' + key)


def identifier(value, label):
    try:
        parsed = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise TestFailure(label + ' must be configured as a UUID.') from None
    return parsed


def port(value, label):
    if not value.isdigit() or not 1 <= int(value) <= 65535:
        raise TestFailure(label + ' must be a port in 1..65535.')
    return int(value)


def instant(value, label):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.timestamp()
    except (ValueError, TypeError, AttributeError):
        raise TestFailure(label + ' is missing or invalid.') from None


def request_json(opener, url, token, body=None, timeout=10):
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, headers=headers,
        data=None if body is None else json.dumps(body, allow_nan=False).encode('utf-8'),
        method='GET' if body is None else 'POST')
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise TestFailure('Backend response exceeds the 12 MiB limit.')
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise TestFailure('Backend returned an invalid JSON object.')
            return value
    except urllib.error.HTTPError as error:
        # Do not relay the body, reason, request object, headers, or arbitrary exception text.
        raise TestFailure('Local endpoint rejected the request (HTTP ' + str(error.code) + ').') from None
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        raise TestFailure('Local endpoint is unavailable or timed out; check the running Paper/Fabric services.') from None
    except (json.JSONDecodeError, UnicodeError):
        raise TestFailure('Local endpoint returned invalid JSON.') from None


def rpc(opener, endpoint, token, scope, method, params=None, timeout=10):
    reply = request_json(opener, endpoint + '/v1/rpc', token,
        {'method': method, 'params': {**(params or {}), **scope}}, timeout=timeout)
    if reply.get('ok') is not True or not isinstance(reply.get('result'), dict):
        code = reply.get('error', {}).get('code', '') if isinstance(reply.get('error'), dict) else ''
        safe_code = code if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,64}', code) else 'request_failed'
        raise TestFailure('Paper rejected the scoped request: ' + safe_code)
    return reply['result']


def check_health(health, owner):
    if health.get('status') != 'ok' or health.get('connected') is not True:
        raise TestFailure('The Fabric camera is not connected to a world.')
    if health.get('spectator') is not True:
        raise TestFailure('The owner must already be in spectator mode; this script does not change game modes.')
    if identifier(health.get('playerId'), 'Worker player ID') != owner:
        raise TestFailure('The worker is using a different account from the configured owner.')
    age = time.time() - instant(health.get('updatedAt'), 'Worker heartbeat')
    if age < -5 or age > 5:
        raise TestFailure('The worker heartbeat is stale; ensure Minecraft is ticking and the clocks agree.')
    if health.get('busy') is True:
        raise TestFailure('The camera is already busy; finish its current capture before running the test.')


def validate_pose(values):
    x, y, z, yaw, pitch = values
    if not all(math.isfinite(value) for value in values):
        raise TestFailure('Pose values must all be finite numbers.')
    if abs(x) > 29_999_984 or abs(z) > 29_999_984 or not -2048 <= y <= 2048:
        raise TestFailure('Pose is outside the camera coordinate limits.')
    if not -360 <= yaw <= 360 or not -90 <= pitch <= 90:
        raise TestFailure('Yaw must be -360..360 and pitch -90..90.')
    return dict(zip(('x', 'y', 'z', 'yaw', 'pitch'), values))


def inspect_png(raw):
    """Verify bytes received from the worker, without re-encoding or generating an image."""
    if not raw.startswith(PNG_SIGNATURE) or len(raw) > 8 * 1024 * 1024:
        raise TestFailure('Worker did not return a bounded PNG image.')
    offset, dimensions, saw_pixels = 8, None, False
    while offset + 12 <= len(raw):
        length = struct.unpack_from('>I', raw, offset)[0]
        kind = raw[offset + 4:offset + 8]
        if length > len(raw) - offset - 12:
            raise TestFailure('PNG chunk is truncated.')
        data = raw[offset + 8:offset + 8 + length]
        expected = struct.unpack_from('>I', raw, offset + 8 + length)[0]
        if zlib.crc32(kind + data) & 0xffffffff != expected:
            raise TestFailure('PNG checksum does not match the received data.')
        if offset == 8:
            if kind != b'IHDR' or length != 13:
                raise TestFailure('PNG has no valid IHDR header.')
            dimensions = struct.unpack_from('>II', data)
            if not 1 <= dimensions[0] <= 1920 or not 1 <= dimensions[1] <= 1080:
                raise TestFailure('PNG dimensions exceed the output limits.')
        if kind == b'IDAT':
            saw_pixels = True
        offset += length + 12
        if kind == b'IEND':
            if length != 0 or offset != len(raw) or not saw_pixels:
                raise TestFailure('PNG is incomplete or contains trailing data.')
            return dimensions
    raise TestFailure('PNG does not contain a complete image.')


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def run(args):
    try:
        text = args.config.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        raise TestFailure('Cannot read the private Paper config; start/configure the plugin first.') from None
    owner = identifier(scalar(text, 'owner-uuid'), 'Owner UUID')
    camera_player = identifier(scalar(text, 'camera-player-uuid'), 'Camera player UUID')
    if owner != camera_player:
        raise TestFailure('This single-client test requires camera-player-uuid to equal owner-uuid.')
    agent_token, camera_token = scalar(text, 'agent-token'), scalar(text, 'camera-token')
    if any(not re.fullmatch(r'[A-Za-z0-9._~-]{32,512}', value) for value in (agent_token, camera_token)) or agent_token == camera_token:
        raise TestFailure('Agent and camera tokens must be distinct safe values; contents are not displayed.')
    project = scalar(text, 'project-id')
    if not project or len(project) > 256:
        raise TestFailure('A valid project-id is required.')
    endpoint = 'http://127.0.0.1:' + str(port(scalar(text, 'http-port'), 'http-port'))
    worker = 'http://127.0.0.1:' + str(port(scalar(text, 'camera-port'), 'camera-port'))
    scope = {'project_id': project, 'player_id': owner}
    # Never let HTTP_PROXY/HTTPS_PROXY forward private capability headers away from loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    health = request_json(opener, worker + '/health', camera_token)
    check_health(health, owner)
    # This authenticates the real in-game owner and confirms the configured Paper server is reachable.
    context = rpc(opener, endpoint, agent_token, scope, 'project_context')
    if context.get('project_id') != project:
        raise TestFailure('Paper returned a different project scope.')
    if args.pose:
        params = {'pose': validate_pose(args.pose)}
        if args.fov is not None:
            params['pose']['fov'] = args.fov
        pose_label = 'explicit pose'
    else:
        cameras = rpc(opener, endpoint, agent_token, scope, 'camera_list')
        if not any(isinstance(camera, dict) and camera.get('camera_id') == args.camera_id for camera in cameras.get('cameras', [])):
            raise TestFailure('Saved camera was not found. In Minecraft run /ai camera save test, or pass --pose X Y Z YAW PITCH.')
        params = {'camera_id': args.camera_id}
        pose_label = 'saved camera'
    if args.after_operation_id:
        params['after_operation_id'] = identifier(args.after_operation_id, 'Operation ID')
    print('Ready: online owner/spectator and scoped Paper route verified; using ' + pose_label + '.', flush=True)
    print('Return to Minecraft, close chat/menus, keep the window rendering, and do not move the mouse or player. Capture starts in '
          + str(args.delay) + ' seconds.', flush=True)
    time.sleep(args.delay)
    check_health(request_json(opener, worker + '/health', camera_token), owner)
    started = time.time()
    deadline = time.monotonic() + args.timeout
    result = rpc(opener, endpoint, agent_token, scope, 'camera_capture', params, timeout=min(35, args.timeout))
    capture_id = identifier(result.get('captureId'), 'Capture ID')
    print('Paper accepted the capture; waiting for the real rendered frame.', flush=True)
    while result.get('status') == 'pending':
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TestFailure('Capture did not complete within the test deadline; no image was saved.')
        time.sleep(min(0.5, remaining))
        result = rpc(opener, endpoint, agent_token, scope, 'camera_capture', {'capture_id': capture_id}, timeout=min(10, max(0.5, remaining)))
    if result.get('status') != 'completed':
        code = result.get('error', '')
        safe_code = code if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,64}', code) else 'capture_failed'
        raise TestFailure('The camera returned ' + safe_code + '; no image was saved.')
    if result.get('captureId') != capture_id or result.get('mimeType') != 'image/png':
        raise TestFailure('Completed capture identity or MIME type did not match.')
    captured_at = instant(result.get('capturedAt'), 'Capture timestamp')
    if captured_at < started - 1 or captured_at > time.time() + 5:
        raise TestFailure('The frame timestamp does not correspond to this capture request.')
    encoded = result.get('imageBase64')
    if not isinstance(encoded, str) or len(encoded) > 12_000_000:
        raise TestFailure('Completed capture did not include a bounded image payload.')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise TestFailure('Completed capture contained invalid image encoding.') from None
    width, height = inspect_png(raw)
    if result.get('width') != width or result.get('height') != height:
        raise TestFailure('PNG dimensions disagree with the capture metadata.')
    metadata = {key: value for key, value in result.items() if key in SAFE_METADATA}
    # Include only known primitive fields; a backend must not smuggle an arbitrary nested payload here.
    if any(not isinstance(value, (str, int, float, bool, type(None))) for value in metadata.values()):
        raise TestFailure('Capture metadata contains unexpected structured values.')
    metadata.update(imageSha256=hashlib.sha256(raw).hexdigest(), imageBytes=len(raw), elapsedSeconds=round(time.time() - started, 3),
                    transport='authenticated Paper HTTP camera_capture', testMode='one owner/spectator client')
    safe_json = json.dumps(metadata, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8') + b'\n'
    if agent_token.encode() in safe_json or camera_token.encode() in safe_json:
        raise TestFailure('Refusing to save metadata containing a component secret.')
    directory = ROOT / '.runtime/camera-test'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    prefix = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + capture_id[:8]
    image_path, metadata_path = directory / (prefix + '.png'), directory / (prefix + '.json')
    write_private(image_path, raw)
    write_private(metadata_path, safe_json)
    print('Saved real PNG: ' + str(image_path), flush=True)
    print('Saved sanitized metadata: ' + str(metadata_path), flush=True)
    print('Frame size: ' + str(width) + 'x' + str(height) + '. Server revision verified: '
          + str(result.get('serverRevisionVerified') is True).lower() + '.', flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', type=Path, default=ROOT / '.runtime/server/plugins/MinecraftBuilderMCP/config.yml')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--camera-id', default='test', help='Saved in-game camera name; default: test')
    source.add_argument('--pose', type=float, nargs=5, metavar=('X', 'Y', 'Z', 'YAW', 'PITCH'), help='Explicit feet position and viewing angles')
    parser.add_argument('--fov', type=int, help='Field of view for an explicit --pose (30..110 degrees)')
    parser.add_argument('--after-operation-id', help='Optional completed operation UUID for Paper validation and correlation')
    parser.add_argument('--delay', type=int, default=8, help='Seconds to return to the Minecraft window before capture (0..60)')
    parser.add_argument('--timeout', type=int, default=45, help='Total capture/poll budget in seconds (20..120)')
    args = parser.parse_args()
    if args.fov is not None and (not args.pose or not 30 <= args.fov <= 110):
        parser.error('--fov requires --pose and must be 30..110')
    if not 0 <= args.delay <= 60 or not 20 <= args.timeout <= 120:
        parser.error('--delay must be 0..60 and --timeout must be 20..120')
    if args.camera_id and (not args.camera_id.strip() or len(args.camera_id) > 64):
        parser.error('--camera-id must contain 1..64 characters')
    try:
        return run(args)
    except TestFailure as error:
        print('Camera test failed: ' + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Camera test interrupted; the worker will expire its current request.', file=sys.stderr)
        return 130
    except Exception:
        # Unexpected errors can include HTTP header details; never print a traceback with private state.
        print('Camera test failed unexpectedly; no private configuration or raw exception is printed.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
