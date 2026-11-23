"""Initialize only Manager-owned writable mounts and verify daemon UID mapping.

Depends on a built backend image and a local Docker daemon. A short-lived isolated
initializer repairs previous container ownership; applications drop all capabilities.
Symlinks are never followed into unrelated data and private files stay owner-only.
"""
import os
from pathlib import Path
import secrets
import tempfile

from manager.configuration import data_root

WRITABLE_DIRECTORIES = ('dossiers', 'runtime', 'ocr-output', 'ocr-models', 'demo-photos', 'private-demo')

INITIALIZE = """
import os, pathlib, stat, sys
uid, gid = map(int, sys.argv[1:3])
for base in pathlib.Path('/managed').iterdir():
    for directory, folders, files in os.walk(base, followlinks=False):
        for path in [pathlib.Path(directory), *(pathlib.Path(directory) / n for n in files)]:
            if path.is_symlink():
                continue
            if not (path.is_dir() or path.is_file()):
                raise RuntimeError('Unsupported special file in persistent storage')
            if path.is_file() and path.stat().st_nlink > 1:
                raise RuntimeError('Managed persistent files must not be hard links')
            if (path.stat().st_uid, path.stat().st_gid) != (uid, gid):
                os.chown(path, uid, gid)
            if base.name == 'private-demo':
                path.chmod(0o700 if path.is_dir() else 0o600)
    base.chmod(0o700)
"""


def prepare_directories(root, config):
    data = data_root(root, config)
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in WRITABLE_DIRECTORIES:
        path = data / name
        if path.is_symlink():
            raise ValueError('Managed persistent directories must not be symlinks: ' + name)
        path.mkdir(exist_ok=True, mode=0o700)


def initialize_storage(root, config, compose, runner, *, rootless):
    data = data_root(root, config)
    image = compose['services']['backend']['image']
    user = '0:0' if rootless else f'{os.getuid()}:{os.getgid()}'
    common = ['docker', 'run', '--rm', '--network', 'none', '--read-only',
              '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL']
    # Verify an empty host-owned mount before changing any existing ownership.
    with tempfile.TemporaryDirectory(prefix='.mapping-', dir=data) as temporary:
        probe = Path(temporary) / 'owner'
        runner.run([*common, '--user', user, '--mount',
                    f'type=bind,source={temporary},target=/probe', '--entrypoint', 'python', image,
                    '-c', "from pathlib import Path; Path('/probe/owner').touch()"], timeout=30, quiet=True)
        if not probe.exists() or probe.stat().st_uid != os.getuid():
            raise ValueError('Docker must use the local Manager owner for persistent bind mounts.')
    mounts = [argument for name in WRITABLE_DIRECTORIES for argument in
              ('--mount', f'type=bind,source={data / name},target=/managed/{name}')]
    runner.run([*common, '--user', '0:0', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER',
                '--cap-add', 'DAC_OVERRIDE', *mounts, '--entrypoint', 'python', image,
                '-c', INITIALIZE, *user.split(':')], timeout=600, quiet=True)
    marker = '.mapping-' + secrets.token_hex(12)
    code = "from pathlib import Path; import sys; [(p / sys.argv[1]).write_text('mapping') for p in Path('/managed').iterdir()]"
    try:
        runner.run([*common, '--user', user, *mounts, '--entrypoint', 'python', image,
                    '-c', code, marker], timeout=30, quiet=True)
        # A remote daemon or another rootless daemon owner cannot share these host mounts.
        for name in WRITABLE_DIRECTORIES:
            probe = data / name / marker
            if not probe.exists() or probe.stat().st_uid != os.getuid():
                raise ValueError('Docker bind-mount mapping does not match the Manager owner: ' + name)
    finally:
        for name in WRITABLE_DIRECTORIES:
            (data / name / marker).unlink(missing_ok=True)
