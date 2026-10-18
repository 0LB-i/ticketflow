"""Telas do servidor de usuários, grupos e setores atendidos (ADR 0011)."""

import re
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamados.modules.identity.models import User
from chamados.modules.organization.models import Department, Team, TeamMember
from tests.conftest import criar_usuario, entrar, grupo
from tests.test_admin_users import NOVO


def _form(client: TestClient, **dados: Any) -> dict[str, Any]:
    return {"csrf_token": client.cookies["tf_csrf"], **dados}


def _aviso(html: str) -> str:
    achado = re.search(r'data-aviso="\w+".*?<p class="font-semibold">(.*?)</p>', html, re.S)
    return achado.group(1) if achado else ""


def _admin(client: TestClient, db: Session) -> User:
    user = criar_usuario(db, "admin@exemplo.com", "admin", nome="Admin")
    entrar(client, "admin@exemplo.com")
    return user


def test_so_quem_tem_a_permissao(client: TestClient, db: Session) -> None:
    criar_usuario(db, grupos={"TI": "supervisor"})
    entrar(client)
    for url in ("/admin/usuarios", "/admin/grupos", "/admin/setores"):
        assert client.get(url).status_code == 403, url
    # Mesmo enviando direto: a permissão da API fica numa dependência que a tela não usa.
    assert client.post("/admin/usuarios/novo", data=_form(client, **NOVO)).status_code == 403
    assert client.post("/admin/grupos/novo", data=_form(client, name="Novo")).status_code == 403
    assert client.post("/admin/setores/novo", data=_form(client, name="RH")).status_code == 403
    assert db.scalar(select(Team).where(Team.name == "Novo")) is None


# --- usuários --------------------------------------------------------------------------------


def test_lista_e_painel_de_usuarios(client: TestClient, db: Session) -> None:
    _admin(client, db)
    criar_usuario(db, "bia@x.com", nome="Bia Lima", grupos={"TI": "member"})
    r = client.get("/admin/usuarios")
    assert r.status_code == 200
    assert "Bia Lima" in r.text and "TI" in r.text
    assert "data-abre-ao-carregar" not in r.text  # sem ?editar, o painel fica fechado
    assert "Bia Lima" not in client.get("/admin/usuarios?q=admin").text
    assert "Bia Lima" not in client.get("/admin/usuarios?papel=admin").text
    bia = db.scalar(select(User).where(User.email == "bia@x.com"))
    assert bia is not None
    r = client.get(f"/admin/usuarios?editar={bia.public_id}")
    assert "data-abre-ao-carregar" in r.text
    assert 'value="Bia Lima"' in r.text
    assert "Novo usuário" in client.get("/admin/usuarios?novo=1").text


def test_criar_e_editar_usuario(client: TestClient, db: Session) -> None:
    _admin(client, db)
    ti = grupo(db, "TI")
    dados = _form(client, **NOVO, team_ids=[str(ti.public_id)])
    r = client.post("/admin/usuarios/novo", data=dados)
    assert _aviso(r.text) == "Usuário criado"
    bruno = db.scalar(select(User).where(User.email == "bruno@exemplo.com"))
    assert bruno is not None
    assert db.scalar(select(TeamMember).where(TeamMember.user_id == bruno.id)) is not None

    # Repetido: o painel volta aberto, com o erro da API e o que foi digitado.
    r = client.post("/admin/usuarios/novo", data=dados)
    assert r.status_code == 422
    assert "data-abre-ao-carregar" in r.text
    assert 'value="Bruno Lima"' in r.text

    editar = {"full_name": "Bruno Lima", "display_name": "Bruninho", "role": "agent"}
    editar |= {"email": "bruno@exemplo.com", "username": "bruno"}
    r = client.post(f"/admin/usuarios/{bruno.public_id}", data=_form(client, **editar))
    assert _aviso(r.text) == "Alterações salvas"
    db.refresh(bruno)
    assert bruno.display_name == "Bruninho"


def test_link_de_acesso_sem_email_configurado(client: TestClient, db: Session) -> None:
    _admin(client, db)
    bia = criar_usuario(db, "bia@x.com", nome="Bia", senha=None)  # convite pendente
    r = client.post(f"/admin/usuarios/{bia.public_id}/link", data=_form(client))
    assert r.status_code == 200
    assert "Envie este link para Bia" in r.text
    assert re.search(r'id="link-acesso" value="http://teste/convite/[\w-]+"', r.text)


def test_excluir_e_reativar(client: TestClient, db: Session) -> None:
    admin = _admin(client, db)
    bia = criar_usuario(db, "bia@x.com", nome="Bia")
    caio = criar_usuario(db, "caio@x.com", nome="Caio", ativo=False)
    # A própria pessoa não tem o botão de excluir.
    assert "confirmar-exclusao" not in client.get(f"/admin/usuarios?editar={admin.public_id}").text
    r = client.post(f"/admin/usuarios/{bia.public_id}/excluir", data=_form(client))
    assert _aviso(r.text) == "Usuário excluído"
    client.post(f"/admin/usuarios/{caio.public_id}/reativar", data=_form(client))
    db.refresh(caio)
    assert caio.is_active


# --- grupos ----------------------------------------------------------------------------------


def test_grupo_e_membros(client: TestClient, db: Session) -> None:
    _admin(client, db)
    bia = criar_usuario(db, "bia@x.com", nome="Bia")
    r = client.post(
        "/admin/grupos/novo", data=_form(client, name="Suporte"), follow_redirects=False
    )
    team = db.scalar(select(Team).where(Team.name == "Suporte"))
    assert team is not None
    # Criado, o painel continua aberto para incluir os membros.
    assert r.headers["location"] == f"/admin/grupos?editar={team.public_id}"
    r = client.get(r.headers["location"])
    assert f'<option value="{bia.public_id}">Bia (bia@x.com)</option>' in r.text

    base = f"/admin/grupos/{team.public_id}"
    client.post(f"{base}/membros", data=_form(client, user_id=str(bia.public_id), role="member"))
    client.post(
        f"{base}/membros", data=_form(client, user_id=str(bia.public_id), role="supervisor")
    )
    membro = db.scalar(select(TeamMember).where(TeamMember.team_id == team.id))
    assert membro is not None and membro.role == "supervisor"
    assert "Bia" in client.get("/admin/grupos").text  # coluna de supervisores
    client.post(f"{base}/membros/{bia.public_id}/remover", data=_form(client))
    assert db.scalar(select(TeamMember).where(TeamMember.team_id == team.id)) is None

    r = client.post(base, data=_form(client, name="Suporte N1", notify_on_new="queue_only"))
    assert _aviso(r.text) == "Alterações salvas"
    db.refresh(team)
    assert team.name == "Suporte N1"
    assert not team.is_active  # caixa "Ativo" desmarcada
    assert "Suporte N1" not in client.get("/admin/grupos").text
    assert "Suporte N1" in client.get("/admin/grupos?inativos=true").text


# --- setores ---------------------------------------------------------------------------------


def test_setores_em_arvore(client: TestClient, db: Session) -> None:
    _admin(client, db)
    client.post("/admin/setores/novo", data=_form(client, name="Financeiro", code="FIN"))
    fin = db.scalar(select(Department).where(Department.name == "Financeiro"))
    assert fin is not None
    r = client.post(
        "/admin/setores/novo",
        data=_form(client, name="Contas a pagar", parent_id=str(fin.public_id)),
    )
    assert _aviso(r.text) == "Setor criado"
    assert 'aria-level="2"' in r.text
    contas = db.scalar(select(Department).where(Department.name == "Contas a pagar"))
    assert contas is not None

    # O setor acima nunca é o próprio setor nem um subsetor dele.
    r = client.get(f"/admin/setores?editar={fin.public_id}")
    opcoes = r.text.split('id="campo-parent_id"')[1].split("</select>")[0]
    assert "Contas a pagar" not in opcoes and ">Financeiro<" not in opcoes

    dados = {"name": "Financeiro", "code": "FIN", "parent_id": "", "is_active": ""}
    client.post(f"/admin/setores/{fin.public_id}", data=_form(client, **dados))
    db.refresh(fin)
    assert not fin.is_active


def test_setor_acima_inativo_continua_nas_opcoes(client: TestClient, db: Session) -> None:
    _admin(client, db)
    client.post("/admin/setores/novo", data=_form(client, name="Financeiro"))
    fin = db.scalar(select(Department).where(Department.name == "Financeiro"))
    assert fin is not None
    client.post(
        "/admin/setores/novo", data=_form(client, name="Contas", parent_id=str(fin.public_id))
    )
    contas = db.scalar(select(Department).where(Department.name == "Contas"))
    assert contas is not None
    client.post(f"/admin/setores/{fin.public_id}", data=_form(client, name="Financeiro"))  # inativa
    r = client.get(f"/admin/setores?editar={contas.public_id}")
    # Sem a opção, o navegador escolheria "Nenhum" e salvar apagaria o vínculo.
    assert f'<option value="{fin.public_id}" selected>Financeiro (Inativo)</option>' in r.text


def test_filtros_da_lista_continuam(client: TestClient, db: Session) -> None:
    _admin(client, db)
    bia = criar_usuario(db, "bia@x.com", nome="Bia")
    r = client.get(f"/admin/usuarios?situacao=ativo&editar={bia.public_id}")
    assert 'data-volta="/admin/usuarios?situacao=ativo"' in r.text
    assert 'name="volta" value="/admin/usuarios?situacao=ativo"' in r.text
    assert f'href="/admin/usuarios?situacao=ativo&amp;editar={bia.public_id}"' in r.text
    dados = {"full_name": "Bia", "display_name": "Bia", "role": "agent"}
    r = client.post(
        f"/admin/usuarios/{bia.public_id}",
        data=_form(client, **dados, volta="/admin/usuarios?situacao=ativo"),
        follow_redirects=False,
    )
    assert r.headers["location"] == "/admin/usuarios?situacao=ativo"
    # Só volta para a mesma tela.
    r = client.post(
        f"/admin/usuarios/{bia.public_id}",
        data=_form(client, **dados, volta="/chamados"),
        follow_redirects=False,
    )
    assert r.headers["location"] == "/admin/usuarios"


def test_pagina_do_link_troca_o_endereco(client: TestClient, db: Session) -> None:
    """A resposta do POST vira o endereço da tela: um F5 não gera outro link (que invalidaria o
    já enviado)."""
    _admin(client, db)
    bia = criar_usuario(db, "bia@x.com", nome="Bia", senha=None)
    r = client.post(f"/admin/usuarios/{bia.public_id}/link", data=_form(client))
    assert f'data-endereco="/admin/usuarios?editar={bia.public_id}"' in r.text
