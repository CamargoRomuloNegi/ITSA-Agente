"""Suíte de diagnóstico contra o gateway **real**.

Objetivo: transformar as lacunas da documentação (catálogo de ``error.code``, formato do evento
``error``, limites de tamanho, aceitação de ``role=system``, parâmetros extras, desvio de relógio
etc.) em **fatos medidos**, registrados em relatório. O relatório alimenta o ``docs/sdd/03``.

Princípios:

- cada verificação é independente e nunca derruba as demais;
- cenários *negativos* usam credencial válida e payloads inválidos — nunca tentam adivinhar
  credenciais. A única exceção é ``D18`` (credencial inválida), **desligada por padrão**, pois pode
  acionar bloqueio/limite de taxa no licenciamento;
- cenários de *carga* (``D19``) são opcionais porque custam tempo de inferência;
- nenhum conteúdo de resposta do modelo, token ou segredo é gravado no relatório além de trechos
  curtos e mascarados.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from itsa_agente import __version__
from itsa_agente.diagnostics.modelos import Observacao, Relatorio, Resultado, Status
from itsa_agente.gateway.client import ClienteGateway, RespostaSondagem
from itsa_agente.gateway.errors import GatewayError
from itsa_agente.gateway.models import (
    EventoConcluido,
    EventoDelta,
    EventoErro,
    EventoIniciado,
    EventoStream,
    Mensagem,
)

log = logging.getLogger("itsa_agente.diagnostico")

_TRECHO = 160


@dataclass(frozen=True, slots=True)
class OpcoesDiagnostico:
    """Quais verificações executar."""

    modelo: str | None = None
    incluir_credencial_invalida: bool = False
    incluir_carga: bool = False
    tamanhos_carga: tuple[int, ...] = (2_000, 8_000, 32_000, 96_000, 192_000)
    prompt_curto: str = "Responda apenas com a palavra OK."


Verificacao = Callable[[], tuple[Status, str, dict[str, Any]]]


class Diagnostico:
    """Executa a bateria e produz um :class:`Relatorio`."""

    def __init__(
        self,
        cliente: ClienteGateway,
        opcoes: OpcoesDiagnostico | None = None,
        *,
        ao_concluir: Callable[[Resultado], None] | None = None,
        relogio: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._c = cliente
        self._o = opcoes or OpcoesDiagnostico()
        self._ao_concluir = ao_concluir
        self._relogio = relogio
        self._observacoes: list[Observacao] = []
        self._modelo: str | None = self._o.modelo
        self._resultados: list[Resultado] = []

    # =================================================================== execução
    def executar(self) -> Relatorio:
        cred = self._c.credenciais
        inicio = self._relogio()
        relatorio = Relatorio(
            versao_app=__version__,
            iniciado_em=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            base_url=self._c.configuracao.base_url,
            usuario_erp=cred.usuario_erp,
            cpf_cnpj_mascarado=cred.cpf_cnpj_mascarado,
            opcoes=asdict(self._o),
        )

        plano: list[tuple[str, str, Verificacao, bool]] = [
            ("D01", "Alcance do gateway e formato de erro (sem token)", self._d01_alcance, True),
            ("D02", "Emissão do token (JWT) e validade", self._d02_token, True),
            ("D03", "Listagem de modelos", self._d03_modelos, True),
            ("D04", "Token adulterado é rejeitado", self._d04_token_adulterado, True),
            ("D05", "Chat sem token é rejeitado", self._d05_chat_sem_token, True),
            ("D06", "Cabeçalhos de telemetria (X-*)", self._d06_cabecalhos, True),
            (
                "D07",
                "Chat mínimo: sequência de eventos, uso e latência",
                self._d07_chat_minimo,
                True,
            ),
            ("D08", "Integridade de acentuação (UTF-8)", self._d08_utf8, True),
            ("D09", "Memória multi-turno (histórico respeitado)", self._d09_memoria, True),
            ("D10", "Papel 'system' aceito e obedecido", self._d10_system, True),
            ("D11", "Modelo inexistente", self._d11_modelo_inexistente, True),
            ("D12", "stream=false é rejeitado", self._d12_stream_false, True),
            ("D13", "31 mensagens são rejeitadas", self._d13_trinta_e_uma, True),
            ("D14", "Última mensagem 'assistant' é rejeitada", self._d14_ultima_assistant, True),
            ("D15", "Conteúdo vazio é rejeitado", self._d15_conteudo_vazio, True),
            ("D16", "Corpo malformado e conversationId inválido", self._d16_corpo_invalido, True),
            ("D17", "Parâmetros extras (ex.: temperature) são aceitos?", self._d17_extras, True),
            (
                "D18",
                "Credencial inválida (opcional: pode acionar bloqueio)",
                self._d18_credencial_invalida,
                self._o.incluir_credencial_invalida,
            ),
            (
                "D19",
                "Tamanho máximo de contexto (opcional: carga)",
                self._d19_carga,
                self._o.incluir_carga,
            ),
        ]

        for id_, titulo, funcao, ativo in plano:
            if not ativo:
                resultado = Resultado(id_, titulo, Status.PULADO, "Desativado nas opções.")
            else:
                resultado = self._rodar(id_, titulo, funcao)
            self._resultados.append(resultado)
            if self._ao_concluir:
                self._ao_concluir(resultado)

        relatorio.resultados = self._resultados
        relatorio.observacoes = self._observacoes
        relatorio.duracao_total_s = round(self._relogio() - inicio, 2)
        return relatorio

    def _rodar(self, id_: str, titulo: str, funcao: Verificacao) -> Resultado:
        t0 = self._relogio()
        try:
            status, detalhe, dados = funcao()
        except GatewayError as exc:
            status, detalhe, dados = Status.FALHA, f"{type(exc).__name__}: {exc}", {}
        except Exception as exc:
            log.exception("Erro inesperado na verificação %s", id_)
            status, detalhe, dados = Status.FALHA, f"Erro inesperado ({type(exc).__name__}).", {}
        return Resultado(id_, titulo, status, detalhe, (self._relogio() - t0) * 1000, dados)

    # ================================================================== utilitários
    def _registrar(self, endpoint: str, cenario: str, r: RespostaSondagem) -> None:
        self._observacoes.append(
            Observacao(
                endpoint=endpoint,
                cenario=cenario,
                status_http=r.status,
                codigo=r.codigo_erro,
                mensagem=r.mensagem_erro,
                tempo_ms=round(r.tempo_ms, 1),
                erro_rede=r.erro_rede,
                corpo=r.corpo_resumo,
            )
        )

    def _corpo_chat(self, **alteracoes: Any) -> dict[str, Any]:
        corpo: dict[str, Any] = {
            "conversationId": str(uuid.uuid4()),
            "model": self._modelo or "indefinido",
            "stream": True,
            "messages": [{"role": "user", "content": self._o.prompt_curto}],
        }
        corpo.update(alteracoes)
        return corpo

    def _chat(self, cenario: str, **alteracoes: Any) -> RespostaSondagem:
        r = self._c.sondar("POST", "/api/chat", json_corpo=self._corpo_chat(**alteracoes))
        self._registrar("POST /api/chat", cenario, r)
        return r

    def _exigir_modelo(self) -> str | None:
        if self._modelo:
            return self._modelo
        try:
            modelos = self._c.listar_modelos()
        except GatewayError:
            return None
        self._modelo = modelos[0].id if modelos else None
        return self._modelo

    @staticmethod
    def _formato_erro_ok(r: RespostaSondagem) -> bool:
        dados = r.json()
        return (
            isinstance(dados, dict)
            and isinstance(dados.get("error"), dict)
            and bool(dados["error"].get("code"))
        )

    def _esperar_rejeicao(
        self,
        r: RespostaSondagem,
        esperados: set[int],
        rotulo: str,
        *,
        formato_opcional: bool = False,
    ) -> tuple[Status, str, dict[str, Any]]:
        """Avalia uma rejeição esperada.

        ``formato_opcional``: rejeições feitas pelo *framework* antes da aplicação (JWT ausente,
        JSON malformado) costumam não seguir ``{error:{code,message}}``. Medido no gateway real:
        é o caso. Aqui isso é INFO (o cliente usa mensagens padrão), não ALERTA.
        """
        dados = {
            "status_http": r.status,
            "codigo": r.codigo_erro,
            "mensagem": r.mensagem_erro,
            "tempo_ms": round(r.tempo_ms, 1),
        }
        if r.erro_rede:
            return Status.FALHA, f"Falha de rede: {r.erro_rede}", dados
        if r.status in esperados:
            extra = (
                ""
                if self._formato_erro_ok(r)
                else " (corpo de erro fora do formato {error:{code,message}})"
            )
            if extra and formato_opcional:
                st = Status.INFO
            else:
                st = Status.OK if not extra else Status.ALERTA
            return st, f"{rotulo}: HTTP {r.status}, código={r.codigo_erro!r}{extra}.", dados
        if r.status is not None and r.status >= 500:
            return Status.FALHA, f"{rotulo}: erro de servidor HTTP {r.status}.", dados
        if r.status == 200:
            return (
                Status.ALERTA,
                f"{rotulo}: foi ACEITO (HTTP 200); esperado {sorted(esperados)}.",
                dados,
            )
        return Status.ALERTA, f"{rotulo}: HTTP {r.status}; esperado {sorted(esperados)}.", dados

    # ================================================================== verificações
    def _d01_alcance(self) -> tuple[Status, str, dict[str, Any]]:
        r = self._c.sondar("GET", "/api/models", token=None)
        self._registrar("GET /api/models", "sem token", r)
        return self._esperar_rejeicao(r, {401}, "GET /api/models sem token", formato_opcional=True)

    def _d02_token(self) -> tuple[Status, str, dict[str, Any]]:
        info = self._c.autenticar()
        dados: dict[str, Any] = {
            "validade_total_s": info.validade_total_s,
            "expira_em_s": round(info.expira_em_s, 1),
            "expira_em_utc": info.expira_em_utc.isoformat() if info.expira_em_utc else None,
        }
        status, avisos = Status.OK, []
        if info.validade_total_s > 900:
            status = Status.ALERTA
            avisos.append(f"validade {info.validade_total_s}s excede os 15 min documentados")
        if info.expira_em_utc is not None:
            exp = info.expira_em_utc
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            desvio = (exp - datetime.now(timezone.utc)).total_seconds() - info.validade_total_s
            dados["desvio_relogio_s"] = round(desvio, 1)
            if abs(desvio) > 120:
                status = Status.ALERTA
                avisos.append(
                    f"relógio local difere do servidor em ~{desvio:.0f}s (o cliente usa expiresIn, "
                    "portanto não é afetado)"
                )
        detalhe = f"JWT emitido; validade {info.validade_total_s}s."
        if avisos:
            detalhe += " Atenção: " + "; ".join(avisos) + "."
        return status, detalhe, dados

    def _d03_modelos(self) -> tuple[Status, str, dict[str, Any]]:
        modelos = self._c.listar_modelos(forcar=True)
        dados = {"modelos": [{"id": m.id, "nome": m.display_name} for m in modelos]}
        if not modelos:
            return (
                Status.ALERTA,
                "Lista vazia (válida pelo contrato), mas sem modelo para testar.",
                dados,
            )
        if self._modelo is None:
            self._modelo = modelos[0].id
        elif self._modelo not in {m.id for m in modelos}:
            return Status.FALHA, f"O modelo escolhido {self._modelo!r} não está na lista.", dados
        return (
            Status.OK,
            f"{len(modelos)} modelo(s); usando {self._modelo!r} nos testes de chat.",
            dados,
        )

    def _d04_token_adulterado(self) -> tuple[Status, str, dict[str, Any]]:
        r = self._c.sondar(
            "GET",
            "/api/models",
            token="eyJhbGciOiJIUzI1NiJ9.e30.assinatura-invalida",  # noqa: S106 - JWT falso de teste
        )
        self._registrar("GET /api/models", "token adulterado", r)
        return self._esperar_rejeicao(r, {401}, "Token adulterado", formato_opcional=True)

    def _d05_chat_sem_token(self) -> tuple[Status, str, dict[str, Any]]:
        if not self._exigir_modelo():
            return Status.PULADO, "Sem modelo disponível.", {}
        r = self._c.sondar("POST", "/api/chat", json_corpo=self._corpo_chat(), token=None)
        self._registrar("POST /api/chat", "sem token", r)
        return self._esperar_rejeicao(r, {401}, "Chat sem token", formato_opcional=True)

    def _d06_cabecalhos(self) -> tuple[Status, str, dict[str, Any]]:
        ok = self._c.sondar(
            "GET",
            "/api/models",
            cabecalhos={
                "X-Erp-Version": "diag-1.0",
                "X-Chat-Module-Version": "diag-1.0",
                "X-Installation-Id": str(uuid.uuid4()),
            },
        )
        self._registrar("GET /api/models", "cabeçalhos X-* válidos", ok)
        longo = self._c.sondar("GET", "/api/models", cabecalhos={"X-Erp-Version": "x" * 51})
        self._registrar("GET /api/models", "X-Erp-Version com 51 caracteres", longo)
        guid_ruim = self._c.sondar(
            "GET", "/api/models", cabecalhos={"X-Installation-Id": "nao-e-guid"}
        )
        self._registrar("GET /api/models", "X-Installation-Id inválido", guid_ruim)
        dados = {
            "validos": ok.status,
            "versao_51_chars": longo.status,
            "installation_id_invalido": guid_ruim.status,
        }
        if ok.status != 200:
            return Status.FALHA, f"Cabeçalhos válidos foram recusados (HTTP {ok.status}).", dados
        return (
            Status.INFO,
            f"Válidos: 200. 51 caracteres: HTTP {longo.status}. "
            f"GUID inválido: HTTP {guid_ruim.status}.",
            dados,
        )

    # ---- chat ------------------------------------------------------------------
    def _coletar(self, r: RespostaSondagem) -> tuple[list[EventoStream], str]:
        eventos = r.eventos()
        texto = "".join(e.content for e in eventos if isinstance(e, EventoDelta))
        return eventos, texto

    def _d07_chat_minimo(self) -> tuple[Status, str, dict[str, Any]]:
        modelo = self._exigir_modelo()
        if not modelo:
            return Status.PULADO, "Sem modelo disponível.", {}
        eventos: list[EventoStream] = []
        t0 = self._relogio()
        primeiro: float | None = None
        for ev in self._c.transmitir_chat(
            modelo=modelo, mensagens=[Mensagem.usuario(self._o.prompt_curto)]
        ):
            if primeiro is None and isinstance(ev, EventoDelta):
                primeiro = self._relogio() - t0
            eventos.append(ev)
        total = self._relogio() - t0

        tipos = [e.tipo for e in eventos]
        deltas = [e for e in eventos if isinstance(e, EventoDelta)]
        concl = next((e for e in eventos if isinstance(e, EventoConcluido)), None)
        ids = {getattr(e, "request_id", None) for e in eventos} - {None}
        texto = "".join(d.content for d in deltas)
        dados: dict[str, Any] = {
            "sequencia": _comprimir(tipos),
            "trechos": len(deltas),
            "request_ids_distintos": len(ids),
            "primeiro_trecho_s": None if primeiro is None else round(primeiro, 2),
            "total_s": round(total, 2),
            "uso": None if not concl or not concl.usage else asdict(concl.usage),
            "amostra": texto[:_TRECHO],
        }
        if concl and concl.usage and concl.usage.completion_tokens and total > 0:
            dados["tokens_por_s"] = round(concl.usage.completion_tokens / total, 1)

        problemas = []
        if not eventos or not isinstance(eventos[0], EventoIniciado):
            problemas.append("o primeiro evento não é 'started'")
        if concl is None:
            problemas.append("sem 'completed'")
        if not texto.strip():
            problemas.append("resposta vazia")
        if len(ids) > 1:
            problemas.append("requestId varia entre eventos")
        if concl and not concl.usage:
            problemas.append("'completed' sem usage")
        if concl and concl.model and concl.model != modelo:
            problemas.append(f"modelo no 'completed' ({concl.model!r}) difere do solicitado")
        if problemas:
            falha = concl is None or not texto.strip()
            return (Status.FALHA if falha else Status.ALERTA), "; ".join(problemas) + ".", dados
        return (
            Status.OK,
            (
                f"started→{len(deltas)} delta→completed; "
                f"1º trecho em {dados['primeiro_trecho_s']}s, "
                f"total {dados['total_s']}s."
            ),
            dados,
        )

    def _d08_utf8(self) -> tuple[Status, str, dict[str, Any]]:
        modelo = self._exigir_modelo()
        if not modelo:
            return Status.PULADO, "Sem modelo disponível.", {}
        r = self._c.conversar(
            modelo=modelo,
            mensagens=[
                Mensagem.usuario("Repita exatamente, sem mais nada: ação, coração, não, é, ü")
            ],
        )
        dados = {"amostra": r.texto[:_TRECHO]}
        if "Ã" in r.texto or "�" in r.texto:
            return Status.FALHA, "Texto com mojibake: a codificação UTF-8 está corrompida.", dados
        acentuado = any(c in r.texto for c in "çãõáéíóúâêô")
        if not acentuado:
            return (
                Status.ALERTA,
                "Sem acentos na resposta (pode ser comportamento do modelo).",
                dados,
            )
        return Status.OK, "Acentuação preservada de ponta a ponta.", dados

    def _d09_memoria(self) -> tuple[Status, str, dict[str, Any]]:
        modelo = self._exigir_modelo()
        if not modelo:
            return Status.PULADO, "Sem modelo disponível.", {}
        r = self._c.conversar(
            modelo=modelo,
            mensagens=[
                Mensagem.usuario("Meu código secreto é ZEBRA-42. Apenas confirme com 'Entendido'."),
                Mensagem.assistente("Entendido."),
                Mensagem.usuario("Qual é o meu código secreto? Responda somente com o código."),
            ],
        )
        dados = {"amostra": r.texto[:_TRECHO]}
        if "ZEBRA-42" in r.texto.upper():
            return Status.OK, "O modelo usou o histórico enviado.", dados
        return (
            Status.ALERTA,
            "O modelo não recuperou o dado do histórico (qualidade do modelo).",
            dados,
        )

    def _d10_system(self) -> tuple[Status, str, dict[str, Any]]:
        modelo = self._exigir_modelo()
        if not modelo:
            return Status.PULADO, "Sem modelo disponível.", {}
        r = self._chat(
            "role=system no início",
            messages=[
                {
                    "role": "system",
                    "content": "Você responde SEMPRE e SOMENTE com a palavra BANANA.",
                },
                {"role": "user", "content": "Qual é a capital da França?"},
            ],
        )
        if r.status != 200:
            return (
                Status.ALERTA,
                f"O gateway recusou role=system (HTTP {r.status}, código={r.codigo_erro!r}). "
                "A engenharia de prompt dos agentes terá de usar a mensagem de usuário.",
                {"status_http": r.status, "codigo": r.codigo_erro},
            )
        _, texto = self._coletar(r)
        dados = {"amostra": texto[:_TRECHO]}
        if "BANANA" in texto.upper():
            return Status.OK, "role=system aceito e obedecido.", dados
        return (
            Status.ALERTA,
            "role=system aceito, mas NÃO obedecido pelo modelo (ver ADR-0003).",
            dados,
        )

    def _d11_modelo_inexistente(self) -> tuple[Status, str, dict[str, Any]]:
        r = self._chat("modelo inexistente", model="modelo-que-nao-existe-xyz")
        return self._esperar_rejeicao(r, {400, 403, 404}, "Modelo inexistente")

    def _d12_stream_false(self) -> tuple[Status, str, dict[str, Any]]:
        r = self._chat("stream=false", stream=False)
        return self._esperar_rejeicao(r, {400}, "stream=false")

    def _d13_trinta_e_uma(self) -> tuple[Status, str, dict[str, Any]]:
        msgs = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"mensagem {i}"}
            for i in range(31)
        ]
        r = self._chat("31 mensagens", messages=msgs)
        return self._esperar_rejeicao(r, {400}, "31 mensagens")

    def _d14_ultima_assistant(self) -> tuple[Status, str, dict[str, Any]]:
        r = self._chat(
            "última mensagem assistant",
            messages=[
                {"role": "user", "content": "Olá"},
                {"role": "assistant", "content": "Oi!"},
            ],
        )
        return self._esperar_rejeicao(r, {400}, "Última mensagem assistant")

    def _d15_conteudo_vazio(self) -> tuple[Status, str, dict[str, Any]]:
        r = self._chat("content vazio", messages=[{"role": "user", "content": "   "}])
        return self._esperar_rejeicao(r, {400}, "Conteúdo vazio")

    def _d16_corpo_invalido(self) -> tuple[Status, str, dict[str, Any]]:
        bruto = self._c.sondar(
            "POST",
            "/api/chat",
            conteudo_bruto=b"{nao-e-json",
            cabecalhos={"Content-Type": "application/json"},
        )
        self._registrar("POST /api/chat", "JSON malformado", bruto)
        guid = self._chat("conversationId inválido", conversationId="nao-e-guid")
        s1, d1, _ = self._esperar_rejeicao(bruto, {400}, "JSON malformado", formato_opcional=True)
        s2, d2, _ = self._esperar_rejeicao(
            guid, {400}, "conversationId inválido", formato_opcional=True
        )
        status = _pior(s1, s2)
        return status, f"{d1} {d2}", {"json_malformado": bruto.status, "guid_invalido": guid.status}

    def _d17_extras(self) -> tuple[Status, str, dict[str, Any]]:
        r = self._chat("campo extra 'temperature'", temperature=0.2)
        dados = {"status_http": r.status, "codigo": r.codigo_erro}
        if r.status == 200:
            return (
                Status.INFO,
                "O gateway ACEITOU 'temperature' (pode estar sendo ignorado). "
                "Verificar se tem efeito.",
                dados,
            )
        return (
            Status.INFO,
            f"O gateway rejeita campos extras (HTTP {r.status}, código={r.codigo_erro!r}): "
            "não há como ajustar temperatura/limites pelo cliente.",
            dados,
        )

    def _d18_credencial_invalida(self) -> tuple[Status, str, dict[str, Any]]:
        cred = self._c.credenciais
        corpo = {**cred.payload(), "tokenId": "TOKEN-INVALIDO-DIAGNOSTICO"}
        r = self._c.sondar("POST", "/api/auth/token", json_corpo=corpo, token=None)
        self._registrar("POST /api/auth/token", "tokenId inválido", r)
        # Medido: um Token ID de formato inválido recebe 400 INVALID_REQUEST (validação de entrada),
        # enquanto um Token ID bem formado porém errado recebe 401. Os três são rejeições corretas.
        return self._esperar_rejeicao(r, {400, 401, 403}, "Token ID inválido")

    def _d19_carga(self) -> tuple[Status, str, dict[str, Any]]:
        modelo = self._exigir_modelo()
        if not modelo:
            return Status.PULADO, "Sem modelo disponível.", {}
        medidas: list[dict[str, Any]] = []
        maior_ok = 0
        for tamanho in self._o.tamanhos_carga:
            enchimento = ("Registro de teste de contexto. " * (tamanho // 31 + 1))[:tamanho]
            conteudo = f"{enchimento}\n\nIgnore o texto acima e responda apenas: OK"
            r = self._chat(
                f"conteúdo de {tamanho} caracteres",
                messages=[{"role": "user", "content": conteudo}],
            )
            item: dict[str, Any] = {
                "caracteres": tamanho,
                "status_http": r.status,
                "codigo": r.codigo_erro,
                "tempo_s": round(r.tempo_ms / 1000, 2),
            }
            if r.status == 200:
                concl = next((e for e in r.eventos() if isinstance(e, EventoConcluido)), None)
                erro = next((e for e in r.eventos() if isinstance(e, EventoErro)), None)
                if erro:
                    item["evento_erro"] = {"codigo": erro.codigo, "mensagem": erro.mensagem}
                elif concl and concl.usage:
                    item["prompt_tokens"] = concl.usage.prompt_tokens
                    item["caracteres_por_token"] = round(
                        len(conteudo) / max(concl.usage.prompt_tokens, 1), 2
                    )
                    maior_ok = tamanho
            medidas.append(item)
            if r.status != 200 or "evento_erro" in item:
                break
        dados = {"medidas": medidas, "maior_tamanho_ok": maior_ok}
        if maior_ok == 0:
            return Status.ALERTA, "Nem o menor tamanho de teste foi aceito.", dados
        ultimo = medidas[-1]
        if ultimo["status_http"] == 200 and "evento_erro" not in ultimo:
            return Status.OK, f"Aceitou até {maior_ok} caracteres (maior tamanho testado).", dados
        return (
            Status.INFO,
            f"Aceitou até {maior_ok} caracteres; falhou em {ultimo['caracteres']} "
            f"(HTTP {ultimo['status_http']}, código={ultimo.get('codigo')!r}). "
            "Use isto para calibrar ITSA_MAX_HISTORY_CHARS.",
            dados,
        )


_GRAVIDADE = {Status.OK: 0, Status.INFO: 0, Status.PULADO: 0, Status.ALERTA: 1, Status.FALHA: 2}


def _pior(*status: Status) -> Status:
    return max(status, key=lambda s: _GRAVIDADE[s])


def _comprimir(tipos: list[str]) -> str:
    """['started','delta','delta','completed'] -> 'started, delta×2, completed'."""
    if not tipos:
        return ""
    saida: list[str] = []
    atual, n = tipos[0], 1
    for t in tipos[1:]:
        if t == atual:
            n += 1
            continue
        saida.append(atual if n == 1 else f"{atual}×{n}")
        atual, n = t, 1
    saida.append(atual if n == 1 else f"{atual}×{n}")
    return ", ".join(saida)
