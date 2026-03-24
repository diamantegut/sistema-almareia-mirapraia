
import os
import time
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

def _process_is_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


@contextmanager
def file_lock(lock_path_base, timeout=20, stale_timeout=600):
    """
    Cross-process file locking to prevent race conditions.
    """
    lock_path = lock_path_base + '.lock'
    start_time = time.time()
    while True:
        try:
            # Exclusive creation
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            payload = f"{os.getpid()}|{int(time.time())}".encode("utf-8")
            os.write(fd, payload)
            os.close(fd)
            break
        except FileExistsError:
            try:
                is_stale = False
                created_at = os.path.getmtime(lock_path)
                if stale_timeout and (time.time() - float(created_at) > float(stale_timeout)):
                    is_stale = True
                else:
                    with open(lock_path, 'r', encoding='utf-8') as lock_file:
                        raw = lock_file.read().strip()
                    lock_pid = int(raw.split('|', 1)[0]) if raw else 0
                    if lock_pid and not _process_is_alive(lock_pid):
                        is_stale = True
                if is_stale:
                    logger.warning(f"Removing stale lock: {lock_path}")
                    os.remove(lock_path)
                    continue
            except Exception:
                pass
            if time.time() - start_time > timeout:
                logger.warning(f"Timeout waiting for lock: {lock_path}")
                raise TimeoutError(f"Could not acquire lock for {lock_path_base}")
            time.sleep(0.1)
        except OSError as e:
            logger.error(f"Error acquiring lock: {e}")
            raise
    
    try:
        yield
    finally:
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except OSError:
            pass
