from __future__ import annotations

import uuid

import pytest

from itsa_agente.conversation import Conversa
from itsa_agente.gateway.client import ClienteGateway
from itsa_agente.gateway.errors import LocalValidationError, StreamError, StreamInterrupted
from tests.gateway_falso import GatewayFalso


def rodar(conversa: Conversa, cliente: ClienteGateway, pergunta: str) -> str:
    return "".join(conversa.perguntar(cliente, modelo="iaitsa-geral", pergunta=pergunta))


class TestConfirmacaoNoHistorico:
    def test_interacao_concluida_entra_no_historico(self, cliente: ClienteGateway) -> None:
        c = Conversa()
        assert rodar(c, cliente, "Responda OK") == "OK"
        assert [(m.role, m.content) for m in c.historico] == [
            ("user", "Responda OK"),
            ("assistant", "OK"),
        ]
        assert c.ultimo_uso is not None
        assert c.ultimo_request_id

    def test_evento_error_descarta_a_interacao(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        gw.modo_stream = "evento_erro"
        c = Conversa()
        with pytest.raises(StreamError):
            rodar(c, cliente, "oi")
        assert c.historico == []

    def test_queda_no_meio_descarta_a_interacao(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        gw.modo_stream = "corte"
        c = Conversa()
        with pytest.raises(StreamInterrupted):
            rodar(c, cliente, "oi")
        assert c.historico == []

    def test_fim_sem_completed_descarta(self, cliente: ClienteGateway, gw: GatewayFalso) -> None:
        gw.modo_stream = "sem_completed"
        c = Conversa()
        with pytest.raises(StreamInterrupted):
            rodar(c, cliente, "oi")
        assert c.historico == []

    def test_cancelamento_pelo_consumidor_descarta(self, cliente: ClienteGateway) -> None:
        c = Conversa()
        gerador = c.perguntar(cliente, modelo="iaitsa-geral", pergunta="oi")
        next(gerador)  # recebeu o 1º trecho...
        gerador.close()  # ...e o usuário cancelou
        assert c.historico == []

    def test_recupera_apos_erro(self, cliente: ClienteGateway, gw: GatewayFalso) -> None:
        c = Conversa()
        gw.modo_stream = "evento_erro"
        with pytest.raises(StreamError):
            rodar(c, cliente, "primeira")
        gw.modo_stream = "normal"
        assert rodar(c, cliente, "segunda") == "OK"
        assert [m.content for m in c.historico if m.role == "user"] == ["segunda"]

    def test_pergunta_vazia_e_rejeitada_sem_rede(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        with pytest.raises(LocalValidationError):
            rodar(Conversa(), cliente, "   ")
        assert gw.chamadas == []


class TestEnvioAoGateway:
    def test_conversation_id_estavel_e_historico_enviado(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        c = Conversa()
        rodar(c, cliente, "primeira")
        rodar(c, cliente, "segunda")
        a, b = gw.corpos_chat
        assert a["conversationId"] == b["conversationId"] == str(c.id)
        assert [m["content"] for m in b["messages"]] == ["primeira", "OK", "segunda"]

    def test_prompt_de_sistema_vai_primeiro(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        c = Conversa(prompt_sistema="Seja breve.")
        rodar(c, cliente, "oi")
        assert gw.corpos_chat[-1]["messages"][0] == {"role": "system", "content": "Seja breve."}
        assert c.historico[0].role == "user"  # o sistema não é duplicado no histórico

    def test_memoria_multi_turno_chega_ao_modelo(self, cliente: ClienteGateway) -> None:
        c = Conversa()
        rodar(c, cliente, "Meu código secreto é ZEBRA-42.")
        assert rodar(c, cliente, "Qual é o meu código secreto?") == "ZEBRA-42"

    def test_reiniciar_gera_nova_conversa(self, cliente: ClienteGateway) -> None:
        c = Conversa()
        rodar(c, cliente, "oi")
        antigo = c.id
        c.reiniciar()
        assert c.id != antigo and c.historico == [] and c.ultimo_uso is None


class TestJanela:
    def _com_historico(self, pares: int, tam: int = 10, **kw: object) -> Conversa:
        c = Conversa(**kw)  # type: ignore[arg-type]
        for i in range(pares):
            c.confirmar(f"p{i:03d}".ljust(tam, "x"), f"r{i:03d}".ljust(tam, "y"))
        return c

    def test_historico_curto_vai_inteiro(self) -> None:
        c = self._com_historico(3)
        j = c.montar_janela("nova")
        assert len(j.mensagens) == 7 and j.descartadas == 0
        assert j.mensagens[-1].role == "user" and j.mensagens[-1].content == "nova"

    def test_limite_de_30_mensagens_sem_sistema(self) -> None:
        j = self._com_historico(40).montar_janela("nova")
        assert len(j.mensagens) <= 30
        assert j.mensagens[-1].role == "user"
        assert j.mensagens[0].role == "user"  # nunca começa por resposta órfã
        assert len(j.mensagens) == 29  # 14 pares + a pergunta atual
        assert j.descartadas == 80 - 28

    def test_limite_com_sistema_reserva_espaco(self) -> None:
        c = self._com_historico(40, prompt_sistema="Regras.")
        j = c.montar_janela("nova")
        assert len(j.mensagens) <= 30
        assert j.mensagens[0].role == "system"
        assert [m.role for m in j.mensagens[1:3]] == ["user", "assistant"]

    def test_mantem_os_pares_mais_recentes(self) -> None:
        c = self._com_historico(40)
        j = c.montar_janela("nova")
        ultimos = [m.content for m in j.mensagens if m.role == "user"][-2]
        assert ultimos.startswith("p039")  # o par mais recente sobrevive

    def test_orcamento_de_caracteres(self) -> None:
        c = self._com_historico(20, tam=100, max_caracteres=1000)
        j = c.montar_janela("pergunta atual")
        assert j.caracteres <= 1000
        assert j.descartadas > 0
        assert j.mensagens[-1].content == "pergunta atual"

    def test_pergunta_gigante_nunca_e_cortada(self) -> None:
        c = self._com_historico(5, max_caracteres=100)
        enorme = "x" * 5000
        j = c.montar_janela(enorme)
        assert [m.content for m in j.mensagens] == [enorme]
        assert j.descartadas == 10

    def test_sistema_enorme_e_preservado(self) -> None:
        c = self._com_historico(5, max_caracteres=200, prompt_sistema="S" * 500)
        j = c.montar_janela("oi")
        assert [m.role for m in j.mensagens] == ["system", "user"]

    @pytest.mark.parametrize(
        "kw", [{"max_mensagens": 0}, {"max_mensagens": 31}, {"max_caracteres": 0}]
    )
    def test_parametros_invalidos(self, kw: dict[str, int]) -> None:
        with pytest.raises(ValueError):
            Conversa(**kw)

    def test_conversa_longa_de_ponta_a_ponta_nunca_viola_o_contrato(
        self, cliente: ClienteGateway, gw: GatewayFalso
    ) -> None:
        c = Conversa(prompt_sistema="Regras.", max_caracteres=300)
        for i in range(40):
            rodar(c, cliente, f"pergunta numero {i}")
        assert len(gw.corpos_chat) == 40  # o gateway falso rejeitaria (400) qualquer violação
        assert all(len(b["messages"]) <= 30 for b in gw.corpos_chat)
        assert {b["conversationId"] for b in gw.corpos_chat} == {str(c.id)}
        assert isinstance(c.id, uuid.UUID)
