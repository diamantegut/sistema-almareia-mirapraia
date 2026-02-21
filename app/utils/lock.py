
import os
import time
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

@contextmanager
def file_lock(lock_path_base, timeout=10):
    """
    Cross-process file locking to prevent race conditions.
    """
    lock_path = lock_path_base + '.lock'
    start_time = time.time()
    while True:
        try:
            # Exclusive creation
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            break
        except FileExistsError:
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
