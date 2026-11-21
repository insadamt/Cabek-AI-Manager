"""Verify demo fixtures conform to the real backend's side-labelled PNG input contract.

Depends on the standard-library image generator and Pillow in service validation.
"""
import struct
import zlib
from manager.demo import prepare_demo_photos


def test_demo_inputs_have_all_four_sides_and_valid_pixel_rows(tmp_path):
    prepare_demo_photos(tmp_path)
    assert sorted(path.name for path in tmp_path.iterdir()) == ['front_demo.png', 'left_demo.png', 'rear_demo.png', 'right_demo.png']
    for path in tmp_path.iterdir():
        data = path.read_bytes()
        assert data[:8] == b'\x89PNG\r\n\x1a\n'
        width, height = struct.unpack('>II', data[16:24])
        offset = 8
        while offset < len(data):
            size = struct.unpack('>I', data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            payload = data[offset + 8:offset + 8 + size]
            checksum = struct.unpack('>I', data[offset + 8 + size:offset + 12 + size])[0]
            assert zlib.crc32(kind + payload) & 0xFFFFFFFF == checksum
            if kind == b'IDAT':
                assert len(zlib.decompress(payload)) == height * (1 + width * 3)
            offset += size + 12
