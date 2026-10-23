"""O fuso horário da máquina, usado nas telas, nos relatórios e nas rotinas.

Vale o `TZ` do ambiente; sem ele, o do sistema (`/etc/localtime`, que o `timedatectl
set-timezone` aponta). Sem nenhum dos dois, UTC, como o próprio sistema faria. É lido uma vez,
ao subir: trocar o fuso da máquina pede reiniciar o serviço e o worker.
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo


def machine_timezone(tz: str | None = None, localtime: Path = Path("/etc/localtime")) -> ZoneInfo:
    name = (tz or "").removeprefix(":")
    if not name:
        # /etc/localtime -> /usr/share/zoneinfo/America/Sao_Paulo
        name = str(localtime.resolve()).partition("zoneinfo/")[2] or "UTC"
    return ZoneInfo(name)


LOCAL_TZ = machine_timezone(os.environ.get("TZ"))
