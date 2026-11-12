"""Agenda (/agenda): compromissos, participantes, o chamado ligado e o aviso do menu.

Cenário (a fixture `cenario`): Ana e Bia (supervisora) no TI, Caio na Infra; a Ana já entrou.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.core.timezone import LOCAL_TZ
from chamados.modules.appointments.models import Appointment
from tests.apoio import registrar
from tests.conftest import entrar, token_csrf

DIA = date(2026, 11, 12)  # uma quinta-feira


def _novo(client: TestClient, **dados: Any) -> Any:
    form = {
        "csrf_token": token_csrf(client),
        "visao": "semana",
        "data": DIA.isoformat(),
        "titulo": "Visita ao cliente",
        "inicio_data": DIA.isoformat(),
        "inicio_hora": "14:00",
        "fim_data": DIA.isoformat(),
        "fim_hora": "15:00",
        **dados,
    }
    return client.post("/agenda/novo", data=form, follow_redirects=False)


def _id(db: Session, titulo: str = "Visita ao cliente") -> str:
    db.expire_all()
    return str(db.scalar(select(Appointment.public_id).where(Appointment.title == titulo)))


def _aviso(client: TestClient) -> int:
    r = client.get("/agenda/aviso")
    assert r.status_code == 200
    achado = re.search(r'data-avisos="(\d+)"', r.text)
    assert achado
    return int(achado.group(1))


def _sair_e_entrar(client: TestClient, email: str) -> None:
    client.cookies.clear()
    entrar(client, email)


def test_sem_login_vai_para_o_login(client: TestClient, db: Session) -> None:
    assert client.get("/agenda", follow_redirects=False).headers["location"] == (
        "/login?volta=%2Fagenda"
    )
    # O aviso não leva ao login: para de perguntar, sem trocar nada.
    r = client.get("/agenda/aviso")
    assert r.status_code == 286
    assert r.headers["HX-Reswap"] == "none"


def test_no_menu_sem_pre_carregamento_e_com_o_aviso(
    client: TestClient, cenario: dict[str, Any]
) -> None:
    html = client.get("/chamados").text
    link = re.search(r'<a href="/agenda"[^>]*>', html)
    assert link
    # Abrir a agenda apaga o aviso: o Chrome não pode pedi-la só porque o mouse passou.
    assert "data-pre-carrega" not in link.group(0)
    assert html.count('id="aviso-agenda"') == 1  # só no menu fixo, não na gaveta


def test_criar_e_ver_no_mes_na_semana_e_no_dia(client: TestClient, cenario: dict[str, Any]) -> None:
    r = _novo(client)
    assert r.status_code == 303
    assert r.headers["location"] == f"/agenda?visao=semana&data={DIA.isoformat()}"

    for visao in ("mes", "semana", "dia"):
        html = client.get(f"/agenda?visao={visao}&data={DIA.isoformat()}").text
        assert "Visita ao cliente" in html, visao
    semana = client.get(f"/agenda?visao=semana&data={DIA.isoformat()}").text
    # Domingo a sábado, e o compromisso na altura das 14h (a grade padrão vai das 7h às 19h).
    assert "08/11 – 14/11/2026" in semana
    assert "14:00 – 15:00" in semana
    assert "top: 58.333%; height: 8.333%; left: 0.000%; width: calc(100.000% - 2px)" in semana
    assert "novembro de 2026" in client.get(f"/agenda?visao=mes&data={DIA.isoformat()}").text


def test_os_que_se_sobrepoem_dividem_a_largura(client: TestClient, cenario: dict[str, Any]) -> None:
    _novo(client, titulo="Primeiro")
    _novo(client, titulo="Segundo", inicio_hora="14:30", fim_hora="15:30")
    _novo(client, titulo="Depois", inicio_hora="16:00", fim_hora="17:00")
    html = client.get(f"/agenda?visao=dia&data={DIA.isoformat()}").text
    assert "left: 0.000%; width: calc(50.000% - 2px)" in html
    assert "left: 50.000%; width: calc(50.000% - 2px)" in html
    assert "left: 0.000%; width: calc(100.000% - 2px)" in html  # o das 16h, sozinho


def test_dia_inteiro_vai_ate_a_meia_noite_do_ultimo_dia(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    r = _novo(client, titulo="Férias", dia_inteiro="1", fim_data="2026-11-13", inicio_hora="")
    assert r.status_code == 303
    db.expire_all()
    a = db.scalar(select(Appointment).where(Appointment.title == "Férias"))
    assert a is not None and a.all_day
    assert a.starts_at == datetime(2026, 11, 12, tzinfo=LOCAL_TZ)
    assert a.ends_at == datetime(2026, 11, 14, tzinfo=LOCAL_TZ)
    # O formulário mostra o último dia, não a meia-noite seguinte.
    html = client.get(f"/agenda?visao=semana&data={DIA.isoformat()}&editar={a.public_id}").text
    assert 'name="fim_data" type="date" value="2026-11-13"' in html


def test_erros_voltam_com_o_que_foi_digitado(client: TestClient, cenario: dict[str, Any]) -> None:
    r = _novo(client, fim_hora="13:00")
    assert r.status_code == 422
    assert "O fim do compromisso precisa ser depois do início." in r.text
    assert 'value="Visita ao cliente"' in r.text  # o painel continua aberto, preenchido
    r = _novo(client, titulo="  ")
    assert r.status_code == 422
    assert "Informe o título do compromisso." in r.text
    r = _novo(client, inicio_hora="")
    assert r.status_code == 422
    assert "Informe uma data e hora válidas." in r.text


def test_participante_ve_mas_so_o_dono_altera(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    assert _novo(client, participantes=[cenario["bia"]]).status_code == 303
    id_ = _id(db)

    _sair_e_entrar(client, "bia@x.com")
    html = client.get(f"/agenda?visao=semana&data={DIA.isoformat()}&editar={id_}").text
    assert "Criado por Ana." in html
    assert '<fieldset class="flex flex-col gap-4" disabled>' in html
    assert 'form="form-compromisso"' not in html  # sem Salvar
    assert f"/agenda/{id_}/remover" not in html
    r = _novo(client)  # a Bia cria o dela normalmente
    assert r.status_code == 303
    form = {
        "csrf_token": token_csrf(client),
        "titulo": "Mudei",
        "inicio_data": DIA.isoformat(),
        "inicio_hora": "14:00",
        "fim_data": DIA.isoformat(),
        "fim_hora": "15:00",
    }
    r = client.post(f"/agenda/{id_}", data=form)
    assert r.status_code == 422
    assert "Só quem criou o compromisso pode alterá-lo." in r.text
    r = client.post(f"/agenda/{id_}/remover", data={"csrf_token": token_csrf(client)})
    assert r.status_code == 200  # volta com o aviso de erro
    assert "Só quem criou o compromisso pode removê-lo." in r.text

    # Quem não participa nem sabe que existe.
    _sair_e_entrar(client, "caio@x.com")
    assert "Visita ao cliente" not in client.get(f"/agenda?visao=semana&data={DIA}").text
    assert client.get(f"/agenda?editar={id_}").status_code == 404


def test_o_dono_altera_tira_participantes_e_remove(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    _novo(client, participantes=[cenario["bia"], cenario["caio"]])
    id_ = _id(db)
    r = client.post(
        f"/agenda/{id_}",
        data={
            "csrf_token": token_csrf(client),
            "titulo": "Visita remarcada",
            "inicio_data": DIA.isoformat(),
            "inicio_hora": "16:00",
            "fim_data": DIA.isoformat(),
            "fim_hora": "17:00",
            "participantes": [cenario["bia"]],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    db.expire_all()
    a = db.scalar(select(Appointment).where(Appointment.public_id == id_))
    assert a is not None and a.title == "Visita remarcada"
    assert sorted(x.user.display_name for x in a.attendees) == ["Ana", "Bia"]

    r = client.post(
        f"/agenda/{id_}/remover", data={"csrf_token": token_csrf(client)}, follow_redirects=False
    )
    assert r.status_code == 303
    db.expire_all()
    assert db.scalar(select(Appointment).where(Appointment.public_id == id_)) is None


def test_participante_invalido(client: TestClient, cenario: dict[str, Any]) -> None:
    r = _novo(client, participantes=["00000000-0000-0000-0000-000000000000"])
    assert r.status_code == 422
    assert "Participante inválido." in r.text


def test_chamado_ligado_passa_pela_visibilidade(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    numero = registrar(client, cenario, title="Impressora do financeiro")["number"]
    # A busca acha pelo número e pelo texto, só os que a pessoa vê.
    assert "Impressora do financeiro" in client.get(f"/agenda/chamados?q={numero}").text
    assert "Impressora do financeiro" in client.get("/agenda/chamados?q=impressora").text

    r = _novo(client, chamado=f"#{numero}", participantes=[cenario["caio"]])
    assert r.status_code == 303
    html = client.get(f"/agenda?visao=semana&data={DIA.isoformat()}").text
    assert f"#{numero} · Impressora do financeiro" in html
    assert f'href="/chamados/{numero}"' in client.get(f"/agenda?editar={_id(db)}").text

    # O Caio (Infra) participa, mas não vê o chamado do TI: só o número.
    _sair_e_entrar(client, "caio@x.com")
    html = client.get(f"/agenda?visao=semana&data={DIA.isoformat()}").text
    assert f"#{numero}" in html
    assert "Impressora do financeiro" not in html
    assert "Impressora do financeiro" not in client.get(f"/agenda/chamados?q={numero}").text
    # E não liga um chamado que não vê.
    r = _novo(client, chamado=str(numero))
    assert r.status_code == 422
    assert "Você não tem acesso a este chamado." in r.text
    r = _novo(client, chamado="999999")
    assert r.status_code == 422
    assert "Chamado não encontrado." in r.text


def test_aviso_15_minutos_antes_e_apaga_ao_abrir_a_agenda(
    client: TestClient, cenario: dict[str, Any], db: Session
) -> None:
    agora = datetime.now(LOCAL_TZ).replace(second=0, microsecond=0)
    daqui = agora + timedelta(minutes=10)
    longe = agora + timedelta(hours=2)

    def novo(titulo: str, inicio: datetime, **extra: Any) -> None:
        fim = inicio + timedelta(minutes=30)
        r = _novo(
            client,
            titulo=titulo,
            inicio_data=inicio.date().isoformat(),
            inicio_hora=inicio.strftime("%H:%M"),
            fim_data=fim.date().isoformat(),
            fim_hora=fim.strftime("%H:%M"),
            **extra,
        )
        assert r.status_code == 303

    novo("Reunião já", daqui, participantes=[cenario["bia"]])
    novo("Reunião depois", longe)
    novo("Dia todo", agora, dia_inteiro="1")  # o dia inteiro não avisa
    assert _aviso(client) == 1

    # Abrir a agenda mostra o que está para começar e apaga o aviso (só de quem abriu).
    html = client.get("/agenda").text
    assert "Começam em breve" in html
    assert "Reunião já" in html.split("Começam em breve")[1].split("</ul>")[0]
    assert _aviso(client) == 0
    assert "Começam em breve" not in client.get("/agenda").text
    # Abrir o painel pelo HTMX não conta como abrir a agenda.
    _sair_e_entrar(client, "bia@x.com")
    assert _aviso(client) == 1
    client.get("/agenda?novo=1", headers={"HX-Request": "true"})
    assert _aviso(client) == 1

    # Mudar o horário acende o aviso de novo para todos.
    _sair_e_entrar(client, "ana@x.com")
    id_ = _id(db, "Reunião já")
    mais_tarde = daqui + timedelta(minutes=2)
    r = client.post(
        f"/agenda/{id_}",
        data={
            "csrf_token": token_csrf(client),
            "titulo": "Reunião já",
            "inicio_data": mais_tarde.date().isoformat(),
            "inicio_hora": mais_tarde.strftime("%H:%M"),
            "fim_data": (mais_tarde + timedelta(minutes=30)).date().isoformat(),
            "fim_hora": (mais_tarde + timedelta(minutes=30)).strftime("%H:%M"),
            "participantes": [cenario["bia"]],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert _aviso(client) == 1
