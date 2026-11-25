"""the sandbox container of one contact (SandboxContainer): a long-lived container of SANDBOX_IMAGE with the contact's
files (SandboxVolume) at MOUNT_PATH, where the bash commands of all its conversations run as SANDBOX_USER. made on the
first command, kept running between commands, so what sudo apt-get installs stays while it lives. stopped after
IDLE_MINUTES without a command (SandboxReaper) and started again by the next one. a container of an older image or
another runtime is made again (on its next use and when the hub starts): its files stay, the packages sudo apt installed
(APT_PACKAGES, the image records them) are installed again (_replay). a reset (reset) makes a clean one: the record goes.
the limits: MEMORY_GB, CPUS, PIDS, the capabilities a user with sudo needs for apt (CAPABILITIES, all others dropped), no
docker socket, no host folder, not privileged, its own network. RUNTIME (HUB_SANDBOX_RUNTIME): runsc (gVisor, install.sh
installs it on the host) keeps root inside away from the host's kernel, sudo needs it registered with GVISOR_SUID.
a docker without it runs runc (runtime).
each command runs in its own session (setsid) under timeout, what it left running (a server started with &) is killed
when it ends, so commands of several conversations can run at once"""
import functools
import os
import re
import shlex
import threading
import time
from typing import Dict, Optional, Tuple

from app.utils.sandbox_volume import (SandboxVolume, MOUNT_PATH, SANDBOX_USER, SANDBOX_IMAGE, LABEL, APT_PACKAGES,
                                      docker_client)

from app.common import get_logger
logger = get_logger()

RUNTIME = os.environ.get("HUB_SANDBOX_RUNTIME") or "runsc"
FALLBACK_RUNTIME = "runc"   # docker's own, when RUNTIME is not installed
GVISOR = "runsc"
GVISOR_SUID = "--allow-suid"    # gVisor ignores setuid bits (sudo) without it, install.sh registers runsc with it
IDLE_MINUTES = float(os.environ.get("HUB_SANDBOX_IDLE_MINUTES") or 24 * 60)
MEMORY_GB = 2
CPUS = 2
PIDS = 256
CAPABILITIES = ["CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID", "SETUID", "SETGID", "KILL", "AUDIT_WRITE"]
REAP_SECONDS = 60       # how often the reaper looks for idle containers
STOP_SECONDS = 5        # a stopping container's processes get this long before they are killed
SESSIONS = "/tmp/rueckgrat-sessions"    # a running command's session id, to kill what it leaves (_command)
REPLAY_TIMEOUT = 900    # seconds for installing the recorded packages again (_replay)
PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]+(:[a-z0-9]+)?$")   # a debian package name, with an architecture
RECORD_PACKAGES = "/usr/local/sbin/rueckgrat-packages"  # the image's script that writes APT_PACKAGES
# the files home: git config and pip install --user stay with the files. a fixed git author, git commit refuses without
# one. builds use CPUS jobs: nproc shows the host's cores, not the container's
ENVIRONMENT = {
    "HOME": MOUNT_PATH,
    "PATH": f"{MOUNT_PATH}/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "PIP_NO_CACHE_DIR": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "GIT_AUTHOR_NAME": "Rueckgrat", "GIT_AUTHOR_EMAIL": "sandbox@rueckgrat.local",
    "GIT_COMMITTER_NAME": "Rueckgrat", "GIT_COMMITTER_EMAIL": "sandbox@rueckgrat.local",
    "MAKEFLAGS": f"-j{CPUS}", "CMAKE_BUILD_PARALLEL_LEVEL": str(CPUS),
    "DEBIAN_FRONTEND": "noninteractive",
}

_lock = threading.Lock()
_locks: Dict[str, threading.Lock] = {}  # per container name: one get-or-make at a time
_used: Dict[str, float] = {}            # per container name: monotonic time of its last command's end
_busy: Dict[str, int] = {}              # per container name: its commands running now
_started = time.monotonic()             # a container of the hub before counts as used at its start


class SandboxContainer:
    def __init__(self, volume: SandboxVolume):
        self.volume = volume

    @property
    def name(self) -> str:
        return f"rueckgrat-sandbox-contact-{self.volume.contact_id}"

    def _lock(self) -> threading.Lock:
        with _lock:
            return _locks.setdefault(self.name, threading.Lock())

    def run(self, command: str, timeout: int) -> Tuple[int, str, str]:
        """(exit code, stdout, stderr) of command in bash as SANDBOX_USER in MOUNT_PATH, stopped after timeout seconds
        (exit code 124), what it left running killed"""
        with _lock:
            _busy[self.name] = _busy.get(self.name, 0) + 1
        try:
            container = self.get()
            session = f"{SESSIONS}/{threading.get_ident()}-{time.monotonic_ns()}"
            try:
                result = container.exec_run(self._command(command, timeout, session), user=SANDBOX_USER, workdir=MOUNT_PATH,
                                            demux=True)
            finally:
                container.exec_run(["sh", "-c", f'pkill -KILL -s "$(cat {session})" 2>/dev/null; rm -f {session}'], user="root")
            stdout, stderr = result.output or (None, None)
            return result.exit_code, _text(stdout), _text(stderr)
        finally:
            with _lock:
                _busy[self.name] -= 1
                _used[self.name] = time.monotonic()

    @staticmethod
    def _command(command: str, timeout: int, session: str) -> list:
        """command in its own session (setsid: its id goes to the file session) under timeout"""
        inner = f"mkdir -p {SESSIONS} && echo $$ > {session} && exec timeout {int(timeout)} bash -c {shlex.quote(command)}"
        return ["setsid", "--wait", "sh", "-c", inner]

    def get(self):
        """the running container, made (or made again for another image) and started as needed"""
        from docker.errors import NotFound
        with self._lock():
            try:
                container = docker_client().containers.get(self.name)
            except NotFound:
                container = None
            if container is not None and _outdated(container):
                logger.info(f"sandbox of contact {self.volume.contact_id}: new image or runtime, made again")
                container.remove(force=True)
                container = None
            if container is None:
                return self._make()
            if container.status != "running":
                container.start()
            return container

    def _make(self):
        container = docker_client().containers.run(
            SANDBOX_IMAGE, ["sleep", "infinity"], name=self.name, hostname="sandbox", detach=True, init=True,
            user=SANDBOX_USER, environment=dict(ENVIRONMENT), mounts=[self.volume.mount()], runtime=runtime(),
            cap_drop=["ALL"], cap_add=CAPABILITIES, mem_limit=f"{MEMORY_GB}g", nano_cpus=CPUS * 1_000_000_000, pids_limit=PIDS,
            labels={LABEL: "sandbox", "user_id": str(self.volume.user_id), "contact_id": str(self.volume.contact_id)})
        self.volume.own(container)
        logger.info(f"sandbox of contact {self.volume.contact_id} made ({runtime()})")
        self._replay(container)
        return container

    def _replay(self, container) -> None:
        """installs the packages of APT_PACKAGES again in the just made container, one by one when they fail together
        (a package the new image's debian lacks). what fails is logged, the container is used anyway"""
        record = container.exec_run(["cat", f"{MOUNT_PATH}/{APT_PACKAGES}"], user="root")
        packages = [] if record.exit_code else (record.output or b"").decode("utf-8", errors="replace").split()
        valid = [package for package in packages if PACKAGE.match(package)]
        if len(valid) < len(packages):
            logger.warning(f"sandbox of contact {self.volume.contact_id}: invalid package names skipped "
                           f"{sorted(set(packages) - set(valid))}")
        if not valid:
            return
        names = " ".join(valid)
        script = (f"apt-get update -qq && {{ apt-get install -y -qq {names} "
                  f"|| for p in {names}; do apt-get install -y -qq $p; done; }}")
        result = container.exec_run(["timeout", str(REPLAY_TIMEOUT), "sh", "-c", script], user="root", demux=True)
        stderr = _text((result.output or (None, None))[1]).strip()
        if result.exit_code:
            logger.warning(f"sandbox of contact {self.volume.contact_id}: packages {names} not all installed again "
                           f"({result.exit_code}) {stderr[-500:]}")
        else:
            logger.info(f"sandbox of contact {self.volume.contact_id}: packages installed again: {names}")

    def reset(self) -> None:
        """a clean system: the container goes (made again by the next command), and the record of its packages, so
        none come back. the files stay"""
        self.remove()
        if self.volume.exists():
            self.volume.delete(APT_PACKAGES)

    def record(self) -> None:
        """writes APT_PACKAGES from the container's packages again, after the files were replaced (restore) with an
        older record. no container: the record stays"""
        from docker.errors import NotFound
        with self._lock():
            try:
                container = docker_client().containers.get(self.name)
            except NotFound:
                return
            if container.status != "running":
                container.start()
            container.exec_run([RECORD_PACKAGES], user="root")

    def remove(self) -> None:
        """the container (its installs and running processes), the files stay. none is nothing to remove"""
        from docker.errors import NotFound
        with self._lock():
            try:
                docker_client().containers.get(self.name).remove(force=True)
                logger.info(f"sandbox of contact {self.volume.contact_id} removed")
            except NotFound:
                pass

    def stop_processes(self) -> None:
        """kills every process of SANDBOX_USER in a running container, before its files are replaced"""
        from docker.errors import NotFound
        try:
            container = docker_client().containers.get(self.name)
        except NotFound:
            return
        if container.status == "running":
            container.exec_run(["pkill", "-KILL", "-u", str(SANDBOX_USER.split(":")[0])], user="root")


def _text(data: Optional[bytes]) -> str:
    return (data or b"").decode("utf-8", errors="replace")


def _image_id() -> str:
    return docker_client().images.get(SANDBOX_IMAGE).id


@functools.lru_cache(maxsize=1)
def runtime() -> str:
    """RUNTIME when docker has it, else FALLBACK_RUNTIME with a warning, gVisor without GVISOR_SUID with one. asked once"""
    runtimes = docker_client().info().get("Runtimes") or {}
    if RUNTIME in runtimes:
        if RUNTIME == GVISOR and GVISOR_SUID not in (runtimes[RUNTIME] or {}).get("runtimeArgs", []):
            logger.warning(f"the docker runtime {GVISOR} has no {GVISOR_SUID}: sudo fails in the sandboxes. run install.sh "
                           f"or: sudo runsc install -- {GVISOR_SUID} && sudo systemctl reload docker")
        return RUNTIME
    logger.warning(f"the docker runtime {RUNTIME} (HUB_SANDBOX_RUNTIME) is not installed on the host: the sandboxes run "
                   f"with {FALLBACK_RUNTIME}, root in them (sudo) reaches the host's kernel. install gVisor (install.sh) "
                   f"or set HUB_SANDBOX_RUNTIME={FALLBACK_RUNTIME}")
    return FALLBACK_RUNTIME


def _outdated(container, image: Optional[str] = None) -> bool:
    """made of another image than SANDBOX_IMAGE (image, its id) or with another runtime than runtime()"""
    return (container.attrs.get("Image") != (image or _image_id())
            or (container.attrs.get("HostConfig") or {}).get("Runtime") != runtime())


def _containers(**filters) -> list:
    return docker_client().containers.list(all=True, filters={"label": f"{LABEL}=sandbox", **filters})


class SandboxReaper:
    """stops the sandbox containers idle for IDLE_MINUTES (no command), and when it starts removes those of an older
    image or another runtime (made again on their next use). without docker it does nothing"""

    def __init__(self):
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, name="sandbox reaper", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def renew(self) -> None:
        """removes the containers of an older image than SANDBOX_IMAGE or another runtime than runtime()"""
        image = _image_id()
        for container in _containers():
            if _outdated(container, image):
                container.remove(force=True)
                logger.info(f"sandbox {container.name}: older image or other runtime, removed")

    def reap(self) -> None:
        """stops the running containers idle for IDLE_MINUTES"""
        now = time.monotonic()
        for container in _containers(status="running"):
            with _lock:
                idle = not _busy.get(container.name) and now - _used.get(container.name, _started) >= IDLE_MINUTES * 60
            if idle:
                container.stop(timeout=STOP_SECONDS)
                logger.info(f"sandbox {container.name}: idle, stopped")

    def _run(self) -> None:
        try:
            self.renew()
        except Exception as e:
            logger.warning(f"sandboxes not renewed {e!r}")
        while not self._stop.wait(REAP_SECONDS):
            try:
                self.reap()
            except Exception as e:
                logger.debug(f"sandboxes not reaped {e!r}")
