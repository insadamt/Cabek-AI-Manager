"""Explain station network failures using bounded read-only host probes.

Depends on Linux iproute2 and socket connectivity. No host addresses, routes or
interfaces are changed; RTSP connectivity is distinct from camera image readiness.
"""
import ipaddress
import json
import socket
import subprocess


def ip_query(*arguments):
    try:
        result = subprocess.run(['ip','-j',*arguments],capture_output=True,text=True,timeout=3)
        return json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def network_readiness(host):
    if not host:
        return {'name':'NVR network / RTSP','state':'attention','message':'Configure the NVR address before testing Ethernet and RTSP.'}
    try:
        address = socket.gethostbyname(host)
    except OSError:
        return {'name':'NVR network / RTSP','state':'disconnected','message':'The NVR hostname cannot be resolved.'}
    routes = ip_query('route','get',address)
    interfaces = ip_query('address','show')
    route = routes[0] if routes else {}
    selected = route.get('dev')
    guidance = []
    for interface in interfaces:
        name = interface.get('ifname','')
        if name.startswith(('en','eth')) and not any(item.get('family')=='inet' for item in interface.get('addr_info',[])):
            guidance.append(f'Ethernet {name} has no IPv4 address.')
    if not selected:
        guidance.append('No route to the NVR was found.')
    elif selected.startswith(('wl','tun','wg')) or route.get('gateway'):
        guidance.append(f'Traffic to the NVR uses {selected}' + (' through a gateway.' if route.get('gateway') else '.') + ' For a direct cable, verify the Ethernet route and subnet.')
    connected = False
    try:
        with socket.create_connection((address,554),timeout=1.5) as stream:
            stream.settimeout(1.5)
            stream.sendall(b'OPTIONS rtsp://'+address.encode()+b'/ RTSP/1.0\r\nCSeq: 1\r\n\r\n')
            connected = stream.recv(128).startswith(b'RTSP/')
    except OSError:
        pass
    if not connected:
        guidance.append('RTSP port 554 is unreachable or did not respond. Check the cable, NVR power and RTSP settings.')
    if guidance:
        guidance.append('For direct PC-to-NVR Ethernet, assign a compatible IPv4 subnet manually and verify the route. Manager will not change host networking.')
    return {'name':'NVR network / RTSP','state':'ready' if connected and not guidance else 'attention',
            'message':('RTSP endpoint responds; camera images and credentials are checked separately. ' if connected else '')+' '.join(guidance)}
