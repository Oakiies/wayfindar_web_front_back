"""Server-side helpers: LAN IP discovery, console logging."""
import socket
import time


def get_lan_ip() -> str:
    """Best-effort LAN IP discovery for sharing the URL to mobile devices."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('8.8.8.8', 80))
        ip = probe.getsockname()[0]
        if ip and ip != '127.0.0.1':
            return ip
    except Exception:
        pass
    finally:
        probe.close()
    return '127.0.0.1'


def safe_print(*args, **kwargs) -> None:
    """
    Guarded console logging for long-running worker threads.
    On Windows, writing to a detached/closed console can raise OSError(22).
    """
    try:
        if 'flush' not in kwargs:
            kwargs['flush'] = True
        print(*args, **kwargs)
    except OSError:
        pass


def log_status(stage: str, message: str, session_id=None) -> None:
    ts = time.strftime('%H:%M:%S')
    sid_text = f' [session={session_id}]' if session_id is not None else ''
    safe_print(f"[{ts}] [STATUS] [{stage}] {message}{sid_text}")
