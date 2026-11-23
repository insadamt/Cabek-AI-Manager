"""Report application runtime separately from real hardware readiness.

Depends on native camera/Shelly GET endpoints and host USB discovery. TCP liveness
never claims that physical lighting was verified; no device commands are sent.
"""
import json
from urllib.request import urlopen
from manager.backend import request_native
from manager.compose import selected_serial_device


def hardware_readiness(config):
    from manager.network_diagnostics import network_readiness
    checks = [network_readiness(config.nvr_host)]
    try:
        result = request_native(config, '/api/cameras')
        cameras = result.get('cameras', [])
        online = sum(bool(camera.get('online')) for camera in cameras)
        if result.get('source') != 'tiandy':
            online = 0
        if result.get('source') == 'demo':
            checks.append({'name':'NVR cameras', 'state':'attention', 'message':'Real NVR images are not measured while prepared demo operation is selected. Network and RTSP checks remain independent.'})
        else:
            checks.append({'name': 'NVR cameras', 'state': 'ready' if online == len(cameras) and online else 'disconnected',
                           'message': f'{online} of {len(cameras)} configured cameras delivering images.'})
    except (OSError, ValueError):
        checks.append({'name': 'NVR cameras', 'state': 'disconnected', 'message': 'NVR images are unavailable; verify its network and credentials.'})
    device = selected_serial_device(config)
    checks.append({'name': 'ESP32 lighting', 'state': 'detected' if device else 'disconnected',
                   'message': 'USB device detected. Verify actual output with Cabek lighting controls.' if device else 'Connect the configured ESP32 USB device. The lighting application remains installed.'})
    try:
        result = request_native(config, '/api/settings/internal-lights/status')
        connected = isinstance(result.get('output'), bool)
        checks.append({'name': 'Shelly lighting', 'state': 'ready' if connected else 'attention',
                       'message': 'Shelly status available.' if connected else 'Check the Shelly connection in Cabek lighting settings.'})
    except (OSError, ValueError):
        checks.append({'name': 'Shelly lighting', 'state': 'disconnected', 'message': 'Shelly is unreachable; all applications remain installed.'})
    return checks
