"""Validate read-only network guidance without modifying Linux interfaces or contacting hardware.

Depends on mocked iproute2 and sockets; API health never implies camera availability.
"""
from manager.network_diagnostics import network_readiness


def test_direct_ethernet_without_ipv4_and_wrong_wifi_route_are_explained(monkeypatch):
    monkeypatch.setattr('socket.gethostbyname',lambda host:'192.168.1.3')
    monkeypatch.setattr('manager.network_diagnostics.ip_query',lambda *args:
        [{'dev':'wlan0','gateway':'10.0.0.1'}] if args[0]=='route' else [{'ifname':'enp2s0','addr_info':[]}])
    def disconnected(*args,**kwargs):raise OSError('offline')
    monkeypatch.setattr('socket.create_connection',disconnected)
    result=network_readiness('station')
    assert result['state']=='attention'
    assert 'enp2s0 has no IPv4' in result['message']
    assert 'wlan0' in result['message']
    assert 'will not change host networking' in result['message']


def test_rtsp_response_is_not_camera_readiness(monkeypatch):
    monkeypatch.setattr('socket.gethostbyname',lambda host:'192.168.1.3')
    monkeypatch.setattr('manager.network_diagnostics.ip_query',lambda *args:
        [{'dev':'enp2s0'}] if args[0]=='route' else [{'ifname':'enp2s0','addr_info':[{'family':'inet'}]}])
    class Endpoint:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def settimeout(self,*args):pass
        def sendall(self,*args):pass
        def recv(self,*args):return b'RTSP/1.0 401 Unauthorized'
    monkeypatch.setattr('socket.create_connection',lambda *args,**kwargs:Endpoint())
    result=network_readiness('station')
    assert result['state']=='ready'
    assert 'camera images and credentials are checked separately' in result['message']
