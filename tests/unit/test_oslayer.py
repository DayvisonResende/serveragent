import os

import pytest

from sentinel.core.exceptions import InstanceLockError
from sentinel.oslayer.info import get_platform_info
from sentinel.oslayer.instance_lock import InstanceLock


def test_second_instance_is_refused_until_release(tmp_path):
    path = tmp_path / "sentinel.lock"
    first = InstanceLock(path)
    first.acquire()
    try:
        with pytest.raises(InstanceLockError, match="já está em execução"):
            InstanceLock(path).acquire()
    finally:
        first.release()
    with InstanceLock(path):
        pass
    # Lido após liberar: no Windows o byte travado não é legível nem pelo próprio processo.
    assert path.read_text().strip() == str(os.getpid())


def test_platform_info_is_populated():
    info = get_platform_info()
    assert info.system and info.python_version
    assert info.is_admin in (True, False, None)
    assert set(info.as_dict()) >= {"system", "release", "machine", "is_admin"}
