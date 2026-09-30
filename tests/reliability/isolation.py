"""Offline filesystem containment experiments, not host certification.

macOS uses sandbox-exec; Linux uses bubblewrap mount/PID namespaces. The canary
never executes a model, reads credentials, or changes user settings. A passing
result establishes only the stated kernel restrictions. Production host
startup/authentication and retained hook execution require separate evidence.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time


def executable() -> str | None:
    path = Path('/usr/bin/sandbox-exec')
    return str(path) if sys.platform == 'darwin' and path.is_file() else None


def filesystem_profile(fixture: Path, runtime_roots: list[Path],
                       read_files: list[Path] = (),
                       writable_dirs: list[Path] = ()) -> str:
    """Allow fixture writes, exact auth-file reads, runtime reads, and networking.

    No home directory permission is implied by an exact auth-file exception.
    This is an experimental outer boundary; it does not replace host tool policy.
    """
    fixture = fixture.resolve()
    writes = sorted({str(fixture), *(str(p.resolve()) for p in writable_dirs)})
    reads = sorted({*writes, *(str(p.resolve()) for p in runtime_roots)})
    literals = sorted({str(p.resolve()) for p in read_files})
    if any(Path(auth).is_relative_to(Path(writable))
           for auth in literals for writable in writes):
        raise ValueError('Allowed auth file is inside a writable directory')
    if any(Path(auth).is_relative_to(Path(read_root))
           for auth in literals for read_root in reads):
        raise ValueError('Allowed auth file is inside a broad read root')
    return ('(version 1)(deny default)'
            '(allow process-exec process-fork sysctl-read mach-lookup network*)'
            '(allow file-read-metadata)'
            '(allow file-read* (literal "/") (literal "/dev/null")'
            ' (literal "/dev/urandom") ' +
            ' '.join('(subpath ' + json.dumps(p) + ')' for p in reads) + ' ' +
            ' '.join('(literal ' + json.dumps(p) + ')' for p in literals) + ')'
            '(allow file-write* '
            + ' '.join('(subpath ' + json.dumps(p) + ')' for p in writes)
            + ' (literal "/dev/null"))')


def mac_argv(sandbox: str, fixture: Path, runtime_roots: list[Path] = (),
             read_files: list[Path] = (), plugin_roots: list[Path] = (),
             command: list[str] = (), writable_dirs: list[Path] = ()) -> list[str]:
    """Run the host under the same deny-by-default profile as the macOS canary."""
    fixture = Path(fixture)
    if not fixture.is_dir():
        raise FileNotFoundError('Fixture directory does not exist: ' + str(fixture))
    for path in read_files:
        path = Path(path)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError('Allowed read file does not exist: ' + str(path))
        if path.stat().st_nlink != 1:
            raise ValueError('Allowed auth file is hard-linked')
    for path in writable_dirs:
        if not Path(path).is_dir():
            raise FileNotFoundError('Writable host directory does not exist: ' + str(path))
    system_roots = [Path('/System/Library'), Path('/usr/lib'),
                    Path('/Library/Apple/System/Library'),
                    Path('/private/var/db/timezone')]
    profile = filesystem_profile(fixture, [*system_roots, *runtime_roots,
                                           *plugin_roots],
                                 read_files, writable_dirs)
    writable_devices = {path.stat().st_dev for path in
                        [fixture, *(Path(p) for p in writable_dirs)]}
    if any(Path(auth).stat().st_dev in writable_devices for auth in read_files):
        raise ValueError('Allowed auth file requires a separate filesystem')
    return [sandbox, '-p', profile, *command]


_PROGRAM = r'''
import json, pathlib, socket, subprocess, sys
root = pathlib.Path(sys.argv[1])
fixture = root / 'fixture'
checks = {}
checks['fixture_read'] = (fixture / 'input').read_text() == 'allowed'
(fixture / 'output').write_text('written')
checks['fixture_write'] = (fixture / 'output').read_text() == 'written'
checks['auth_exact_read'] = (root / 'auth' / 'auth.json').read_text() == 'synthetic auth'
try:
    (root / 'snapshot').stat()
except PermissionError:
    checks['outside_metadata_visible'] = False
else:
    checks['outside_metadata_visible'] = True
try:
    (root / 'auth' / 'sibling.json').read_text()
except PermissionError:
    checks['auth_sibling_read_denied'] = True
else:
    checks['auth_sibling_read_denied'] = False
try:
    with (root / 'auth' / 'auth.json').open('a'):
        pass
except PermissionError:
    checks['auth_write_denied'] = True
else:
    checks['auth_write_denied'] = False
checks['plugin_read'] = (root / 'plugin' / 'SKILL.md').read_text() == 'synthetic plugin'
for name in ('snapshot', 'evidence', 'global-instructions', 'other-auth', 'fixture/escape'):
    path = root / name
    for mode in ('r', 'w'):
        try:
            with path.open(mode):
                pass
        except PermissionError:
            checks[name + ':' + mode] = True
        else:
            checks[name + ':' + mode] = False
# Network availability is tested locally, without contacting any service.
with socket.socket() as server, socket.socket() as client:
    server.bind(('127.0.0.1', 0)); server.listen(1)
    client.connect(server.getsockname())
    conn, _ = server.accept()
    with conn:
        client.sendall(b'ok')
        checks['loopback_network'] = conn.recv(2) == b'ok'
child = subprocess.run([sys.executable, '-I', '-B', '-c',
    "import pathlib,sys; pathlib.Path(sys.argv[1]).read_text()", str(root / 'snapshot')],
    capture_output=True, text=True)
checks['descendant_read_denied'] = child.returncode != 0 and 'PermissionError' in child.stderr
print(json.dumps(checks, sort_keys=True))
'''


def probe_filesystem_boundary(timeout_seconds: float = 3) -> dict:
    """Retain bounded, secret-free canary evidence; fail closed on any mismatch."""
    sandbox = executable()
    result = {'schema_version': 1, 'mechanism': 'sandbox-exec',
              'filesystem_enforced': False,
              'path_scoped_reads': True, 'inode_alias_isolation': False,
              'auth_path_identity_stable': False,
              'host_certified': False, 'checks': {}, 'error': None,
              'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'host_identity': _host_identity('sandbox-exec', None)}
    if sandbox is None:
        result['error'] = 'macOS /usr/bin/sandbox-exec is unavailable'
        return result
    with tempfile.TemporaryDirectory(prefix='host-isolation-') as temp:
        root = Path(temp).resolve()
        fixture = root / 'fixture'
        fixture.mkdir()
        (fixture / 'input').write_text('allowed')
        for name in ('snapshot', 'evidence', 'global-instructions', 'other-auth'):
            (root / name).write_text('protected')
        (root / 'auth').mkdir()
        (root / 'auth' / 'auth.json').write_text('synthetic auth')
        (root / 'auth' / 'sibling.json').write_text('sibling secret')
        (root / 'plugin').mkdir()
        (root / 'plugin' / 'SKILL.md').write_text('synthetic plugin')
        (fixture / 'escape').symlink_to(root / 'snapshot')
        runtime = [Path(sys.prefix), Path(sys.base_prefix),
                   Path(sys.executable).resolve().parent, Path('/System/Library'),
                   Path('/usr/lib'), Path('/Library/Apple/System/Library'), root / 'plugin']
        profile = filesystem_profile(fixture, runtime, [root / 'auth' / 'auth.json'])
        try:
            process = subprocess.run([sandbox, '-p', profile, sys.executable, '-I', '-B',
                                      '-c', _PROGRAM, str(root)], capture_output=True,
                                     text=True, timeout=timeout_seconds,
                                     env={'PATH': '/usr/bin:/bin'}, cwd=fixture)
            if process.returncode:
                result['error'] = 'Offline sandbox canary failed with exit ' + str(process.returncode)
                return result
            checks = json.loads(process.stdout)
            expected = {'fixture_read', 'fixture_write', 'auth_exact_read',
                        'outside_metadata_visible',
                        'auth_sibling_read_denied',
                        'auth_write_denied', 'plugin_read',
                        'loopback_network', 'descendant_read_denied'} | {
                name + ':' + mode for name in ('snapshot', 'evidence', 'global-instructions',
                                               'other-auth', 'fixture/escape') for mode in ('r', 'w')}
            result['checks'] = checks
            result['filesystem_enforced'] = (isinstance(checks, dict) and set(checks) == expected
                                             and all(value is True for value in checks.values())
                                             and all((root / name).read_text() == 'protected'
                                                     for name in ('snapshot', 'evidence',
                                                                  'global-instructions', 'other-auth'))
                                             and (root / 'auth' / 'auth.json').read_text()
                                             == 'synthetic auth')
            if not result['filesystem_enforced']:
                result['error'] = 'Offline sandbox canary evidence did not match every required control'
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            result['error'] = 'Offline sandbox canary failed: ' + type(exc).__name__
    return result


# --- Linux: bubblewrap mount, PID, IPC and UTS namespaces -------------------

_LINUX_SYSTEM_ROOTS = ('/usr', '/bin', '/sbin', '/lib', '/lib32', '/lib64', '/libx32')
_LINUX_SYSTEM_FILES = (
    ('/run/systemd/resolve/stub-resolv.conf', '/etc/resolv.conf'),
    ('/etc/hosts', '/etc/hosts'),
    ('/etc/nsswitch.conf', '/etc/nsswitch.conf'),
    ('/etc/ssl/certs/ca-certificates.crt', '/etc/ssl/certs/ca-certificates.crt'),
)


def linux_executable() -> str | None:
    # Fixed system path: a PATH lookup could substitute an unconfining binary.
    path = Path('/usr/bin/bwrap')
    return (str(path) if sys.platform.startswith('linux') and path.is_file()
            and os.access(path, os.X_OK) else None)


def linux_argv(bwrap: str, fixture: Path, runtime_roots: list[Path] = (),
               read_files: list[Path] = (), plugin_roots: list[Path] = (),
               command: list[str] = (), writable_dirs: list[Path] = ()) -> list[str]:
    """Build a deny-by-default bubblewrap command.

    Only the listed paths exist inside the namespace. System roots, runtime roots,
    exact auth files and selected plugins are read-only; the fixture is the only
    writable bind, and the synthetic root is remounted read-only afterwards.
    The network namespace is shared, matching the macOS profile. The caller
    passes the complete environment to the process, so secrets never enter argv.
    """
    fixture = Path(fixture).resolve()
    writable = sorted({str(Path(p).resolve()) for p in writable_dirs})
    argv = [bwrap, '--unshare-user', '--unshare-pid', '--unshare-ipc', '--unshare-uts',
            '--unshare-cgroup-try', '--die-with-parent', '--new-session',
            '--proc', '/proc', '--dev', '/dev']
    bound = set()
    for name in _LINUX_SYSTEM_ROOTS:
        path = Path(name)
        if path.is_symlink():
            argv += ['--symlink', os.readlink(path), name]
        elif path.is_dir():
            argv += ['--ro-bind', name, name]
            bound.add(name)
    for source_name, target_name in _LINUX_SYSTEM_FILES:
        source = Path(source_name)
        if source.is_file() and not source.is_symlink():
            target = Path(target_name)
            parents = []
            parent = target.parent
            while parent != parent.parent and str(parent) != '/':
                parents.append(str(parent))
                parent = parent.parent
            for directory in reversed(parents):
                argv += ['--dir', directory]
            argv += ['--ro-bind', source_name, target_name]
    # Real CLIs may create private scratch directories below /tmp (Codex's
    # nested workspace sandbox creates /tmp/.git). Give a host launch an
    # ephemeral tmpfs there before layering the explicitly bound fixture,
    # source, and state paths below it. The standalone canary omits
    # writable_dirs and therefore keeps /tmp read-only for its escape check.
    if writable:
        argv += ['--tmpfs', '/tmp']
    for root in sorted({str(Path(p).resolve()) for p in (*runtime_roots, *plugin_roots)}):
        if not any(root == b or root.startswith(b + '/') for b in bound):
            parents = []
            parent = Path(root).parent
            while parent != parent.parent and str(parent) != '/':
                parents.append(str(parent))
                parent = parent.parent
            for directory in reversed(parents):
                argv += ['--dir', directory]
            argv += ['--ro-bind', root, root]
    # Bind the fixture first. Explicit read files are layered afterwards so a
    # credential mounted below a writable fixture cannot become writable by
    # bind-order accident. Create only the parent directories needed for those
    # exact files; their siblings remain absent from the namespace.
    argv += ['--bind', str(fixture), str(fixture)]
    read_paths = sorted({str(Path(p).resolve()) for p in read_files})
    for path in read_paths:
        source = Path(path)
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError('Allowed read file does not exist: ' + path)
    for directory in writable:
        if not Path(directory).is_dir():
            raise FileNotFoundError('Writable host directory does not exist: ' + directory)
        parents = []
        parent = Path(directory).parent
        while parent != parent.parent and str(parent) != '/':
            parents.append(str(parent))
            parent = parent.parent
        for parent in reversed(parents):
            argv += ['--dir', parent]
        argv += ['--bind', directory, directory]
    for path in read_paths:
        source = Path(path)
        parents = []
        parent = source.parent
        while parent != parent.parent and str(parent) != '/':
            parents.append(str(parent))
            parent = parent.parent
        for directory in reversed(parents):
            argv += ['--dir', directory]
        argv += ['--ro-bind', path, path]
    argv += ['--remount-ro', '/']
    argv += ['--chdir', str(fixture)]
    return argv + ['--', *command]


_LINUX_PROGRAM = r'''
import json, os, pathlib, socket, subprocess, sys
root = pathlib.Path(sys.argv[1]); fixture = root / 'fixture'
nonce, host_pid, host_init = sys.argv[2], int(sys.argv[3]), sys.argv[4]
host_globals = json.loads(sys.argv[5])
checks = {}
def denied(path, mode):
    try:
        with open(path, mode):
            pass
    except OSError:
        return True
    return False
checks['fixture_read'] = (fixture / 'input').read_text() == 'allowed'
(fixture / 'output').write_text('written')
checks['fixture_write'] = (fixture / 'output').read_text() == 'written'
checks['auth_exact_read'] = (root / 'auth' / 'auth.json').read_text() == 'synthetic auth'
checks['auth_sibling_denied'] = denied(root / 'auth' / 'other.json', 'r')
checks['auth_write_denied'] = denied(root / 'auth' / 'auth.json', 'a')
checks['plugin_read'] = (root / 'plugin' / 'SKILL.md').read_text() == 'synthetic plugin'
checks['plugin_write_denied'] = denied(root / 'plugin' / 'SKILL.md', 'a')
checks['unselected_plugin_denied'] = denied(root / 'unselected-plugin' / 'SKILL.md', 'r')
for name in ('snapshot', 'evidence', 'global-instructions', 'other-auth', 'fixture/escape'):
    for mode in ('r', 'w'):
        checks[name + ':' + mode] = denied(root / name, mode)
checks['host_globals_hidden'] = all(not os.path.lexists(p) for p in host_globals)
checks['tmp_write_denied'] = denied('/tmp/agentic-isolation-escape', 'w')
checks['root_write_denied'] = denied('/agentic-isolation-escape', 'w')
checks['host_key_hidden'] = 'AGENTIC_HOST_KEY' not in os.environ
hook = subprocess.run(['/bin/sh', str(root / 'plugin' / 'hooks' / 'session-start.sh'), nonce],
                      capture_output=True, text=True)
checks['selected_hook_executed'] = (hook.returncode == 0 and
    (fixture / 'hook-marker').read_text() == 'hook:' + nonce)
other = subprocess.run(['/bin/sh', str(root / 'unselected-plugin' / 'hooks' / 'session-start.sh'), nonce],
                       capture_output=True, text=True)
checks['unselected_hook_denied'] = other.returncode != 0 and not (fixture / 'unselected-marker').exists()
with socket.socket() as server, socket.socket() as client:
    server.bind(('127.0.0.1', 0)); server.listen(1)
    client.connect(server.getsockname())
    conn, _ = server.accept()
    with conn:
        client.sendall(b'ok')
        checks['loopback_network'] = conn.recv(2) == b'ok'
child = subprocess.run([sys.executable, '-I', '-B', '-c',
    "import pathlib,sys; pathlib.Path(sys.argv[1]).read_text()", str(root / 'snapshot')],
    capture_output=True, text=True)
checks['descendant_read_denied'] = child.returncode != 0 and 'Error' in child.stderr
child = subprocess.run([sys.executable, '-I', '-B', '-c',
    "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('x')", str(root / 'evidence')],
    capture_output=True, text=True)
checks['descendant_write_denied'] = child.returncode != 0 and 'Error' in child.stderr
probe = ("import os,sys\n"
    "pids=[p for p in os.listdir('/proc') if p.isdigit()]\n"
    "try:\n os.kill(int(sys.argv[1]),0); signalled=True\n"
    "except ProcessLookupError:\n signalled=False\n"
    "init=open('/proc/1/comm').read().strip()\n"
    "print(len(pids), signalled, init, os.getuid())")
child = subprocess.run([sys.executable, '-I', '-B', '-c', probe, str(host_pid)],
                       capture_output=True, text=True, start_new_session=True)
count, signalled, init, uid = (child.stdout.split() + ['', '', '', ''])[:4]
checks['descendant_pid_namespace'] = (child.returncode == 0 and count.isdigit()
    and int(count) <= 8 and init != host_init)
checks['descendant_cannot_signal_host'] = child.returncode == 0 and signalled == 'False'
setns = subprocess.run([sys.executable, '-I', '-B', '-c',
    "import os; os.setns(os.open('/proc/1/ns/mnt', os.O_RDONLY), 0); print(open('/etc/hostname').read())"],
    capture_output=True, text=True)
checks['descendant_setns_denied'] = setns.returncode != 0
# This process is itself the sandboxed "host": stdin/argv mirror what
# hosts.run_host launches, and fd 1 is a socketpair end set up by
# probe_linux_boundary the same way run_host sets up a real host's stdout.
# Run the forgery attempts from a GRANDCHILD (spawned by a child, neither of
# which inherits this fd, matching a host that captures tool-command output
# rather than leaking its own trace fd downward) and require every technique
# to fail for the expected reason, not merely with some error: reopening
# /proc/<host>/fd/1 must fail with ENXIO (it names a socket, not a regular file
# or pipe); pidfd_getfd on fd 1 must fail with EPERM (ptrace_scope); and
# PTRACE_ATTACH must fail with EPERM (ptrace_scope, since a descendant is
# attaching to an ancestor). pidfd_open and pidfd_getfd use raw x86_64 syscall
# numbers, so a Python without os.pidfd_open cannot turn a missing API into a
# denial.
own_pid, trace_ino = os.getpid(), -1
try:
    trace_ino = os.fstat(1).st_ino
except OSError:
    pass
forge = (
    "import ctypes, errno, json, os, sys\n"
    "own_pid, trace_ino = int(sys.argv[1]), int(sys.argv[2])\n"
    "checks = {}\n"
    "try:\n"
    "    checks['fd1_is_not_trace_socket'] = os.fstat(1).st_ino != trace_ino\n"
    "except OSError:\n"
    "    checks['fd1_is_not_trace_socket'] = True\n"
    "try:\n"
    "    fd = os.open('/proc/%d/fd/1' % own_pid, os.O_WRONLY)\n"
    "    os.write(fd, b'forged\\n')\n"
    "    os.close(fd)\n"
    "    checks['proc_fd1_reopen_denied'] = False\n"
    "except OSError as exc:\n"
    "    checks['proc_fd1_reopen_denied'] = exc.errno == errno.ENXIO\n"
    "libc = ctypes.CDLL(None, use_errno=True)\n"
    "libc.syscall.restype = ctypes.c_long\n"
    "pfd = libc.syscall(434, own_pid, 0)\n"
    "if pfd < 0:\n"
    "    checks['pidfd_getfd_denied'] = False\n"
    "else:\n"
    "    got = libc.syscall(438, pfd, 1, 0)\n"
    "    checks['pidfd_getfd_denied'] = got < 0 and ctypes.get_errno() == errno.EPERM\n"
    "    if got >= 0:\n"
    "        os.close(got)\n"
    "    os.close(pfd)\n"
    "ctypes.set_errno(0)\n"
    "rc = libc.ptrace(16, own_pid, 0, 0)\n"
    "checks['ptrace_attach_denied'] = rc != 0 and ctypes.get_errno() == errno.EPERM\n"
    "if rc == 0:\n"
    "    libc.ptrace(17, own_pid, 0, 0)\n"
    "print(json.dumps(checks))\n"
)
launcher = (
    "import subprocess, sys\n"
    "r = subprocess.run([sys.executable, '-I', '-B', '-c', sys.argv[1], sys.argv[2], sys.argv[3]],\n"
    "                   capture_output=True, text=True)\n"
    "sys.stdout.write(r.stdout)\n"
    "sys.stderr.write(r.stderr)\n"
    "sys.exit(r.returncode)\n"
)
grandchild = subprocess.run(
    [sys.executable, '-I', '-B', '-c', launcher, forge, str(own_pid), str(trace_ino)],
    capture_output=True, text=True)
try:
    forge_checks = json.loads(grandchild.stdout)
except ValueError:
    forge_checks = {}
checks['descendant_trace_forgery_denied'] = (
    grandchild.returncode == 0 and isinstance(forge_checks, dict)
    and forge_checks.get('fd1_is_not_trace_socket') is True
    and forge_checks.get('proc_fd1_reopen_denied') is True
    and forge_checks.get('pidfd_getfd_denied') is True
    and forge_checks.get('ptrace_attach_denied') is True)
print(json.dumps(checks, sort_keys=True))
'''

LINUX_CHECKS = frozenset({
    'fixture_read', 'fixture_write', 'auth_exact_read', 'auth_sibling_denied',
    'auth_write_denied', 'plugin_read', 'plugin_write_denied', 'unselected_plugin_denied',
    'host_globals_hidden', 'tmp_write_denied', 'root_write_denied', 'host_key_hidden',
    'selected_hook_executed', 'unselected_hook_denied', 'loopback_network',
    'descendant_read_denied', 'descendant_write_denied', 'descendant_pid_namespace',
    'descendant_cannot_signal_host', 'descendant_setns_denied',
    'descendant_trace_forgery_denied',
} | {name + ':' + mode for name in ('snapshot', 'evidence', 'global-instructions',
                                    'other-auth', 'fixture/escape') for mode in ('r', 'w')})

_PROTECTED = ('snapshot', 'evidence', 'global-instructions', 'other-auth')


def host_global_paths(home: Path | None = None) -> list[str]:
    """Existing user-global host inputs the canary must not see (never read)."""
    home = Path(home or Path.home())
    names = ('.claude', '.claude.json', '.codex', '.agents', '.cursor', '.config')
    return sorted(str(home / name) for name in names if os.path.lexists(home / name))


def _bwrap_version(bwrap: str) -> str | None:
    try:
        out = subprocess.run([bwrap, '--version'], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _host_identity(mechanism: str, version: str | None) -> dict:
    uname = os.uname()
    return {'system': uname.sysname, 'release': uname.release, 'machine': uname.machine,
            'node': uname.nodename, 'python': sys.version.split()[0],
            'mechanism': mechanism, 'mechanism_version': version}


def yama_ptrace_scope() -> int | None:
    """Read kernel.yama.ptrace_scope; None means unknown (missing, unreadable,

    or not Linux). Scope 0 permits same-uid PTRACE_ATTACH/pidfd_getfd from any
    process, including a non-ancestor; scope 1-3 restrict attach to a process's
    own descendants, which denies a host's tool-command descendant from
    reaching back up to duplicate or attach to the host's own trace fd.
    """
    if not sys.platform.startswith('linux'):
        return None
    try:
        return int(Path('/proc/sys/kernel/yama/ptrace_scope').read_text().strip())
    except (OSError, ValueError):
        return None


def _run_with_socketpair_stdout(argv: list[str], *, timeout_seconds: float,
                                env: dict, cwd: Path) -> subprocess.CompletedProcess:
    """Capture argv's stdout through an AF_UNIX socketpair, not a pipe.

    Mirrors the production host launcher (`hosts.run_host`) so a canary running
    under this helper is exposed to the same descendant-forgery surface a real
    host is: /proc/<pid>/fd/1 on the launched process resolves to a socket, not
    a reopenable pipe or regular file.
    """
    host_out, child_out = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    chunks: list[bytes] = []
    try:
        process = subprocess.Popen(argv, stdout=child_out, stderr=subprocess.PIPE,
                                   env=env, cwd=cwd)
    finally:
        child_out.close()

    def _drain() -> None:
        try:
            while True:
                chunk = host_out.recv(65536)
                if not chunk:
                    return
                chunks.append(chunk)
        except OSError:
            return

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()
    try:
        _, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise
    finally:
        reader.join(timeout=5)
        host_out.close()
    return subprocess.CompletedProcess(argv, process.returncode,
                                       b''.join(chunks).decode('utf-8', errors='replace'),
                                       stderr.decode('utf-8', errors='replace'))


def probe_linux_boundary(timeout_seconds: float = 10, home: Path | None = None) -> dict:
    """Run the Linux canary under bubblewrap; any mismatch fails closed."""
    bwrap = linux_executable()
    result = {'schema_version': 1, 'mechanism': 'bubblewrap', 'filesystem_enforced': False,
              'host_certified': False, 'checks': {}, 'error': None,
              'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'host_identity': None}
    if bwrap is None:
        result['error'] = 'Linux bubblewrap (/usr/bin/bwrap) is unavailable'
        return result
    result['host_identity'] = _host_identity('bubblewrap', _bwrap_version(bwrap))
    result['yama_ptrace_scope'] = yama_ptrace_scope()
    globals_ = host_global_paths(home)
    result['host_globals_checked'] = len(globals_)
    with tempfile.TemporaryDirectory(prefix='host-isolation-') as temp:
        root = Path(temp).resolve()
        fixture = root / 'fixture'
        fixture.mkdir()
        (fixture / 'input').write_text('allowed')
        for name in _PROTECTED:
            (root / name).write_text('protected')
        (root / 'auth').mkdir()
        (root / 'auth' / 'auth.json').write_text('synthetic auth')
        (root / 'auth' / 'other.json').write_text('protected')
        for plugin, text in (('plugin', 'synthetic plugin'), ('unselected-plugin', 'protected')):
            (root / plugin / 'hooks').mkdir(parents=True)
            (root / plugin / 'SKILL.md').write_text(text)
            marker = 'hook-marker' if plugin == 'plugin' else 'unselected-marker'
            (root / plugin / 'hooks' / 'session-start.sh').write_text(
                'printf "hook:%s" "$1" > ' + json.dumps(str(fixture / marker)) + '\n')
        (fixture / 'escape').symlink_to(root / 'snapshot')
        nonce = secrets.token_hex(8)
        try:
            host_init = Path('/proc/1/comm').read_text().strip()
        except OSError:
            host_init = ''
        runtime = [Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).resolve().parent]
        argv = linux_argv(bwrap, fixture, runtime, [root / 'auth' / 'auth.json'],
                          [root / 'plugin'],
                          [sys.executable, '-I', '-B', '-c', _LINUX_PROGRAM, str(root), nonce,
                           str(os.getpid()), host_init, json.dumps(globals_)])
        try:
            # A socketpair, not subprocess.run's ordinary pipe, so the canary's
            # own descendant-forgery checks exercise the exact channel type
            # `hosts.run_host` uses for a real launch.
            process = _run_with_socketpair_stdout(argv, timeout_seconds=timeout_seconds,
                                                  env={'PATH': '/usr/bin:/bin'}, cwd=fixture)
            if process.returncode:
                detail = process.stderr.strip().splitlines()[-1:] if process.stderr else []
                result['error'] = ('Linux sandbox canary failed with exit ' +
                                   str(process.returncode) +
                                   (': ' + detail[0][:200] if detail else ''))
                return result
            checks = json.loads(process.stdout)
            result['checks'] = checks
            outside = sorted(p.name for p in root.iterdir())
            result['filesystem_enforced'] = (
                isinstance(checks, dict) and set(checks) == LINUX_CHECKS
                and all(value is True for value in checks.values())
                and all((root / name).read_text() == 'protected' for name in _PROTECTED)
                and (root / 'auth' / 'other.json').read_text() == 'protected'
                and outside == sorted(['auth', 'fixture', 'plugin', 'unselected-plugin', *_PROTECTED])
                and (fixture / 'output').read_text() == 'written'
                and (fixture / 'hook-marker').read_text() == 'hook:' + nonce
                and not (fixture / 'unselected-marker').exists())
            if not result['filesystem_enforced']:
                result['error'] = 'Linux sandbox canary evidence did not match every required control'
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            result['error'] = 'Linux sandbox canary failed: ' + type(exc).__name__
    return result


def probe_host_boundary(timeout_seconds: float = 10) -> dict:
    """Select the kernel mechanism for this platform; others stay unavailable."""
    if sys.platform.startswith('linux'):
        return probe_linux_boundary(timeout_seconds=timeout_seconds)
    return probe_filesystem_boundary(timeout_seconds=timeout_seconds)


# --- Receipts bound to repository revision and trial fixture ----------------

def _git(path: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(['git', '-C', str(path), *args], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def repository_revision(repo: Path) -> dict:
    """Committed revision plus a dirty flag; a dirty tree is not that revision."""
    head = _git(repo, 'rev-parse', 'HEAD')
    status = _git(repo, 'status', '--porcelain', '--untracked-files=normal')
    return {'revision': head, 'dirty': status is None or bool(status)}


def fixture_binding(fixture: Path) -> dict:
    """Hash every fixture entry (excluding .git) plus the fixture's Git HEAD."""
    fixture = Path(fixture).resolve()
    digest = hashlib.sha256()
    for path in sorted(fixture.rglob('*')):
        rel = path.relative_to(fixture)
        if rel.parts[0] == '.git':
            continue
        if path.is_symlink():
            digest.update(b'L\0' + str(rel).encode() + b'\0' + os.readlink(path).encode() + b'\0')
        elif path.is_file():
            digest.update(b'F\0' + str(rel).encode() + b'\0' +
                          hashlib.sha256(path.read_bytes()).digest())
        elif path.is_dir():
            digest.update(b'D\0' + str(rel).encode() + b'\0')
    return {'path': str(fixture), 'git_head': _git(fixture, 'rev-parse', 'HEAD')
            if (fixture / '.git').exists() else None, 'tree_sha256': digest.hexdigest()}


def host_key(environ: dict | None = None) -> bytes:
    value = (os.environ if environ is None else environ).get('AGENTIC_HOST_KEY', '')
    if not value:
        raise RuntimeError('AGENTIC_HOST_KEY is required to sign isolation receipts')
    return value.encode('utf-8')


def _canonical(record: dict) -> bytes:
    body = {k: v for k, v in record.items() if k != 'signature'}
    return json.dumps(body, sort_keys=True, separators=(',', ':')).encode('utf-8')


def sign_command_receipt(*, key: bytes, host: str, model: str, argv: list[str],
                         exit_status: int, repository: dict, fixture: dict,
                         isolation: dict, issued_at: float | None = None) -> dict:
    """Sign what the adapter itself observed; never fields reported by a model."""
    if not key:
        raise ValueError('host signing key is required')
    if not host or not model or not isinstance(exit_status, int):
        raise ValueError('host, model and integer exit status are required')
    if not repository.get('revision') or not fixture.get('tree_sha256'):
        raise ValueError('repository revision and fixture digest are required')
    record = {
        'purpose': 'isolation.command', 'schema_version': 1,
        'host': host, 'model': model, 'host_identity': isolation.get('host_identity'),
        'argv_sha256': hashlib.sha256(json.dumps(argv).encode()).hexdigest(),
        'exit_status': exit_status,
        'repository_revision': repository['revision'], 'repository_dirty': repository['dirty'],
        'fixture_path': fixture['path'], 'fixture_git_head': fixture.get('git_head'),
        'fixture_sha256': fixture['tree_sha256'],
        'isolation_mechanism': isolation.get('mechanism'),
        'isolation_probe_sha256': isolation.get('probe_sha256'),
        'filesystem_enforced': isolation.get('filesystem_enforced') is True,
        'trace_channel': (isolation.get('trace_channel') or {}).get('channel'),
        'trace_channel_protected': (isolation.get('trace_channel') or {}).get(
            'trace_channel_protected') is True,
        'host_certified': False,
        'issued_at': time.time() if issued_at is None else issued_at,
    }
    record['signature'] = base64.urlsafe_b64encode(
        hmac.new(key, _canonical(record), hashlib.sha256).digest()).decode('ascii')
    return record


def verify_command_receipt(record: dict, key: bytes, *, repository_revision: str,
                           fixture_sha256: str, host: str, model: str) -> dict:
    """Reject forged, re-bound or dirty-tree receipts."""
    if not isinstance(record, dict) or record.get('purpose') != 'isolation.command':
        raise ValueError('isolation receipt purpose mismatch')
    try:
        supplied = base64.urlsafe_b64decode(str(record.get('signature', '')).encode('ascii'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('isolation receipt signature is malformed') from exc
    expected = hmac.new(key, _canonical(record), hashlib.sha256).digest()
    if not key or not hmac.compare_digest(supplied, expected):
        raise ValueError('isolation receipt signature is invalid')
    if record.get('repository_revision') != repository_revision or record.get('repository_dirty'):
        raise ValueError('isolation receipt is not bound to the clean repository revision')
    if record.get('fixture_sha256') != fixture_sha256:
        raise ValueError('isolation receipt is not bound to this trial fixture')
    if record.get('host') != host or record.get('model') != model:
        raise ValueError('isolation receipt host or model identity mismatch')
    return dict(record)
