"""O fuso da máquina (core/timezone.py): o TZ do ambiente, senão o /etc/localtime, senão UTC."""

from pathlib import Path
from zoneinfo import ZoneInfo

from chamados.core.timezone import machine_timezone


def test_o_tz_do_ambiente_vale_primeiro(tmp_path: Path) -> None:
    assert machine_timezone("America/Manaus", tmp_path / "nada") == ZoneInfo("America/Manaus")
    assert machine_timezone(":Europe/Lisbon", tmp_path / "nada") == ZoneInfo("Europe/Lisbon")


def test_sem_tz_vale_o_fuso_do_sistema(tmp_path: Path) -> None:
    zona = tmp_path / "zoneinfo" / "America" / "Recife"
    zona.parent.mkdir(parents=True)
    zona.touch()
    (tmp_path / "localtime").symlink_to(zona)
    assert machine_timezone(None, tmp_path / "localtime") == ZoneInfo("America/Recife")


def test_sem_nenhum_dos_dois_utc(tmp_path: Path) -> None:
    assert machine_timezone("", tmp_path / "localtime") == ZoneInfo("UTC")
