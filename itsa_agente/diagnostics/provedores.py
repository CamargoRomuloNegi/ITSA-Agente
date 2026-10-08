"""Diagnóstico de provedores externos (NVIDIA, OpenRouter): fatos medidos, não presumidos.

Mesmo espírito da suíte do gateway (:mod:`itsa_agente.diagnostics.suite`): cada verificação é
independente, nada é gravado além de trechos curtos e redigidos, e o resultado é um
:class:`~itsa_agente.diagnostics.modelos.Relatorio` exportável. Foco: o que decide **qual modelo
usar em qual agente** — latência, vazão, streaming incremental, raciocínio, obediência a
instruções e leitura de contexto longo.

======  ==============================================================================
ID      Verificação
======  ==============================================================================
P01     Chave aceita e catálogo de modelos
P02     Chat mínimo: eventos, uso (tokens), motivo de término e latência
P03     Integridade de acentuação (UTF-8)
P04     Instrução de sistema (``role=system``) obedecida
P05     Streaming incremental e vazão de **geração** (tokens/s) com resposta longa
P06     Raciocínio ligado × desligado (opcional)
P07     Chave inválida é rejeitada
P08     Modelo inexistente é rejeitado
P09     Leitura de contexto longo — "agulha no palheiro" (opcional, custa tokens)
======  ==============================================================================
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from itsa_agente import __version__
from itsa_agente.diagnostics.modelos import Observacao, Relatorio, Resultado, Status
from itsa_agente.gateway.errors import GatewayError
from itsa_agente.gateway.models import (
    EventoConcluido,
    EventoDelta,
    EventoErro,
    EventoRaciocinio,
    Mensagem,
    Uso,
)
from itsa_agente.providers.base import OpcoesGeracao, separar
from itsa_agente.providers.openai_compat import ClienteOpenAICompat, RespostaProvedor

log = logging.getLogger("itsa_agente.diagnostico")

_TRECHO = 160
Verificacao = Callable[[], tuple[Status, str, dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class OpcoesDiagnosticoProvedor:
    """Quais verificações executar e com qual modelo (ID **local**, sem prefixo de provedor)."""

    modelo: str | None = None
    incluir_chave_invalida: bool = True
    incluir_raciocinio: bool = True
    incluir_resposta_longa: bool = True
    incluir_contexto_longo: bool = False
    tamanhos_contexto: tuple[int, ...] = (24_000, 96_000)
    prompt_curto: str = "Responda apenas com a palavra OK."


@dataclass(slots=True)
class Coleta:
    """Resultado de uma chamada de chat consumida até o fim, com tempos medidos."""

    texto: str = ""
    raciocinio: str = ""
    deltas: int = 0
    trechos_raciocinio: int = 0
    primeiro_s: float | None = None
    total_s: float = 0.0
    uso: Uso | None = None
    motivo: str | None = None
    concluiu: bool = False
    erro: EventoErro | None = None
    tipos: list[str] = field(default_factory=list)

    @property
    def tokens_por_s(self) -> float | None:
        """Vazão de geração: tokens de saída ÷ tempo entre o 1º trecho e o fim."""
        if not self.uso or self.primeiro_s is None:
            return None
        janela = self.total_s - self.primeiro_s
        if janela <= 0.05 or self.uso.completion_tokens <= 0:
            return None
        return round(self.uso.completion_tokens / janela, 1)


class DiagnosticoProvedor:
    """Executa a bateria contra um provedor externo e produz um :class:`Relatorio`."""

    def __init__(
        self,
        cliente: ClienteOpenAICompat,
        opcoes: OpcoesDiagnosticoProvedor | None = None,
        *,
        ao_concluir: Callable[[Resultado], None] | None = None,
        relogio: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._c = cliente
        self._o = opcoes or OpcoesDiagnosticoProvedor()
        self._ao_concluir = ao_concluir
        self._relogio = relogio
        self._modelo: str | None = self._o.modelo
        self._observacoes: list[Observacao] = []
        self._resultados: list[Resultado] = []

    # =================================================================== execução
    def executar(self) -> Relatorio:
        inicio = self._relogio()
        relatorio = Relatorio(
            versao_app=__version__,
            iniciado_em=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            base_url=self._c.base_url,
            usuario_erp=self._c.id_provedor,
            cpf_cnpj_mascarado="-",
            opcoes=asdict(self._o),
            titulo=f"Relatório de diagnóstico — {self._c.rotulo}",
            rotulo_base="Endpoint",
            identificacao=(
                f"- **Provedor:** {self._c.rotulo} · modelo de teste "
                f"`{self._o.modelo or '(escolhido na verificação P01)'}` "
                "· chave de API mascarada"
            ),
        )
        plano: list[tuple[str, str, Verificacao, bool]] = [
            ("P01", "Chave aceita e catálogo de modelos", self._p01_catalogo, True),
            ("P02", "Chat mínimo: eventos, uso e latência", self._p02_minimo, True),
            ("P03", "Integridade de acentuação (UTF-8)", self._p03_utf8, True),
            ("P04", "Instrução de sistema obedecida", self._p04_system, True),
            (
                "P05",
                "Streaming incremental e vazão de geração",
                self._p05_longa,
                self._o.incluir_resposta_longa,
            ),
            (
                "P06",
                "Raciocínio ligado × desligado",
                self._p06_raciocinio,
                self._o.incluir_raciocinio,
            ),
            (
                "P07",
                "Chave inválida é rejeitada",
                self._p07_chave_invalida,
                self._o.incluir_chave_invalida,
            ),
            ("P08", "Modelo inexistente é rejeitado", self._p08_modelo_inexistente, True),
            (
                "P09",
                "Leitura de contexto longo (agulha no palheiro)",
                self._p09_contexto_longo,
                self._o.incluir_contexto_longo,
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
        if self._modelo:
            relatorio.identificacao = (
                f"- **Provedor:** {self._c.rotulo} · modelo de teste `{self._modelo}` "
                "· chave de API mascarada"
            )
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

    # =================================================================== utilitários
    def _registrar(self, endpoint: str, cenario: str, r: RespostaProvedor) -> None:
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

    def _coletar(
        self,
        mensagens: Sequence[Mensagem],
        opcoes: OpcoesGeracao | None = None,
        *,
        modelo: str | None = None,
    ) -> Coleta:
        """Consome o streaming inteiro medindo 1º trecho, total, raciocínio e uso."""
        alvo = modelo or self._modelo or "indefinido"
        coleta = Coleta()
        partes: list[str] = []
        raciocinio: list[str] = []
        inicio = self._relogio()
        for evento in self._c.transmitir_chat(modelo=alvo, mensagens=mensagens, opcoes=opcoes):
            coleta.tipos.append(evento.tipo)
            agora = self._relogio() - inicio
            if isinstance(evento, EventoDelta):
                if coleta.primeiro_s is None:
                    coleta.primeiro_s = agora
                partes.append(evento.content)
                coleta.deltas += 1
            elif isinstance(evento, EventoRaciocinio):
                raciocinio.append(evento.content)
                coleta.trechos_raciocinio += 1
            elif isinstance(evento, EventoConcluido):
                coleta.concluiu = True
                coleta.uso = evento.usage
                coleta.motivo = evento.motivo
            elif isinstance(evento, EventoErro):
                coleta.erro = evento
        coleta.total_s = self._relogio() - inicio
        coleta.texto = "".join(partes)
        coleta.raciocinio = "".join(raciocinio)
        return coleta

    def _exigir_modelo(self) -> str | None:
        if self._modelo:
            return self._modelo
        try:
            modelos = self._c.listar_modelos()
        except GatewayError:
            return None
        candidatos = [m for m in modelos if m.gratuito] or modelos
        self._modelo = separar(candidatos[0].id)[1] if candidatos else None
        return self._modelo

    @staticmethod
    def _dados_coleta(c: Coleta) -> dict[str, Any]:
        return {
            "sequencia": ", ".join(dict.fromkeys(c.tipos)),
            "trechos_resposta": c.deltas,
            "trechos_raciocinio": c.trechos_raciocinio,
            "primeiro_trecho_s": None if c.primeiro_s is None else round(c.primeiro_s, 2),
            "total_s": round(c.total_s, 2),
            "uso": None if c.uso is None else asdict(c.uso),
            "motivo": c.motivo,
            "tokens_por_s": c.tokens_por_s,
            "amostra": c.texto[:_TRECHO],
        }

    # ================================================================== verificações
    def _p01_catalogo(self) -> tuple[Status, str, dict[str, Any]]:
        self._c.verificar()
        modelos = self._c.listar_modelos(forcar=True)
        dados: dict[str, Any] = {
            "total": len(modelos),
            "gratuitos": sum(1 for m in modelos if m.gratuito),
            "amostra": [m.id for m in modelos[:15]],
        }
        if not modelos:
            return Status.ALERTA, "Chave aceita, mas o catálogo veio vazio.", dados
        escolhido = self._exigir_modelo()
        if (
            self._o.modelo
            and escolhido
            and self._o.modelo not in {separar(m.id)[1] for m in modelos}
        ):
            return (
                Status.INFO,
                f"Chave aceita. O modelo {escolhido!r} não está na lista curta (pode existir "
                "no provedor mesmo assim); os testes de chat dirão.",
                dados,
            )
        return (
            Status.OK,
            f"Chave aceita; {len(modelos)} modelo(s); testando com {escolhido!r}.",
            dados,
        )

    def _p02_minimo(self) -> tuple[Status, str, dict[str, Any]]:
        if not self._exigir_modelo():
            return Status.PULADO, "Sem modelo disponível.", {}
        c = self._coletar([Mensagem.usuario(self._o.prompt_curto)])
        dados = self._dados_coleta(c)
        if c.erro:
            return Status.FALHA, f"O provedor enviou erro: {c.erro.mensagem}", dados
        if not c.concluiu:
            return Status.FALHA, "Fim do streaming sem evento de conclusão.", dados
        if not c.texto.strip():
            return (
                Status.ALERTA,
                "Concluiu sem texto de resposta (modelo pode ter gasto tudo raciocinando).",
                dados,
            )
        avisos = []
        if c.uso is None:
            avisos.append("o provedor não informou o consumo de tokens")
        if c.motivo not in (None, "stop"):
            avisos.append(f"motivo de término {c.motivo!r}")
        detalhe = (
            f"{dados['sequencia']}; 1º trecho em {dados['primeiro_trecho_s']}s, "
            f"total {dados['total_s']}s."
        )
        if avisos:
            return Status.ALERTA, detalhe + " Atenção: " + "; ".join(avisos) + ".", dados
        return Status.OK, detalhe, dados

    def _p03_utf8(self) -> tuple[Status, str, dict[str, Any]]:
        if not self._exigir_modelo():
            return Status.PULADO, "Sem modelo disponível.", {}
        c = self._coletar(
            [Mensagem.usuario("Repita exatamente, sem mais nada: ação, coração, não, é, ü")]
        )
        dados = {"amostra": c.texto[:_TRECHO]}
        if "Ã" in c.texto or "�" in c.texto:
            return Status.FALHA, "Texto com mojibake: a codificação UTF-8 está corrompida.", dados
        if not any(ch in c.texto for ch in "çãõáéíóúâêô"):
            return (
                Status.ALERTA,
                "Sem acentos na resposta (pode ser comportamento do modelo).",
                dados,
            )
        return Status.OK, "Acentuação preservada de ponta a ponta.", dados

    def _p04_system(self) -> tuple[Status, str, dict[str, Any]]:
        if not self._exigir_modelo():
            return Status.PULADO, "Sem modelo disponível.", {}
        c = self._coletar(
            [
                Mensagem.sistema("Responda sempre e somente com a palavra BANANA, nada mais."),
                Mensagem.usuario("Qual é a capital da França?"),
            ]
        )
        dados = {"amostra": c.texto[:_TRECHO]}
        if "BANANA" in c.texto.upper():
            return Status.OK, "role=system aceito e obedecido.", dados
        return (
            Status.ALERTA,
            "A instrução de sistema NÃO foi obedecida (resposta fora do combinado).",
            dados,
        )

    def _p05_longa(self) -> tuple[Status, str, dict[str, Any]]:
        if not self._exigir_modelo():
            return Status.PULADO, "Sem modelo disponível.", {}
        c = self._coletar(
            [
                Mensagem.usuario(
                    "Escreva um texto corrido de cerca de 200 palavras, em português, sobre a "
                    "importância do planejamento tributário para empresas de médio porte."
                )
            ]
        )
        dados = self._dados_coleta(c)
        if c.erro or not c.concluiu:
            return Status.FALHA, "A resposta longa não foi concluída.", dados
        if c.deltas <= 2:
            return (
                Status.ALERTA,
                f"Resposta chegou em {c.deltas} trecho(s): sem streaming incremental "
                "(o usuário esperaria a resposta inteira).",
                dados,
            )
        vazao = f"{c.tokens_por_s} tokens/s" if c.tokens_por_s else "vazão não calculável"
        return (
            Status.OK,
            f"Streaming incremental ({c.deltas} trechos); 1º trecho em "
            f"{dados['primeiro_trecho_s']}s; total {dados['total_s']}s; {vazao}.",
            dados,
        )

    def _p06_raciocinio(self) -> tuple[Status, str, dict[str, Any]]:
        if not self._exigir_modelo():
            return Status.PULADO, "Sem modelo disponível.", {}
        pergunta = [Mensagem.usuario("Quanto é 17 × 23? Mostre o raciocínio e a resposta final.")]
        ligado = self._coletar(pergunta, OpcoesGeracao(raciocinio=True))
        desligado = self._coletar(pergunta, OpcoesGeracao(raciocinio=False))
        dados = {
            "ligado": {
                **self._dados_coleta(ligado),
                "caracteres_raciocinio": len(ligado.raciocinio),
            },
            "desligado": {
                **self._dados_coleta(desligado),
                "caracteres_raciocinio": len(desligado.raciocinio),
            },
        }
        if ligado.erro or desligado.erro:
            return (
                Status.ALERTA,
                "O provedor recusou o parâmetro de raciocínio em uma das chamadas.",
                dados,
            )
        if ligado.raciocinio:
            extra = ""
            if ligado.uso and desligado.uso:
                extra = (
                    f" Tokens de saída: {ligado.uso.completion_tokens} (ligado) × "
                    f"{desligado.uso.completion_tokens} (desligado); tempo total "
                    f"{ligado.total_s:.1f}s × {desligado.total_s:.1f}s."
                )
            return (
                Status.INFO,
                f"Raciocínio recebido à parte ({len(ligado.raciocinio)} caracteres) quando "
                f"ligado.{extra}",
                dados,
            )
        return (
            Status.INFO,
            "Nenhum raciocínio separado foi retornado (o modelo pode não oferecer o recurso, "
            "ou o provedor não o expõe).",
            dados,
        )

    def _p07_chave_invalida(self) -> tuple[Status, str, dict[str, Any]]:
        corpo = self._c.corpo_chat(
            self._modelo or "indefinido", [Mensagem.usuario("OK")], OpcoesGeracao(max_tokens=1)
        )
        corpo["stream"] = False
        r = self._c.sondar(
            "POST", "/chat/completions", json_corpo=corpo, chave="chave-invalida-diagnostico-0000"
        )
        self._registrar("POST /chat/completions", "chave inválida", r)
        dados = {"status_http": r.status, "codigo": r.codigo_erro, "mensagem": r.mensagem_erro}
        if r.erro_rede:
            return Status.FALHA, f"Falha de rede: {r.erro_rede}", dados
        if r.status in (401, 403):
            return Status.OK, f"Chave inválida rejeitada: HTTP {r.status}.", dados
        if r.status == 200:
            return (
                Status.ALERTA,
                "Uma chave inválida foi ACEITA (HTTP 200): o endpoint pode não exigir chave.",
                dados,
            )
        return Status.INFO, f"Chave inválida: HTTP {r.status} (esperado 401/403).", dados

    def _p08_modelo_inexistente(self) -> tuple[Status, str, dict[str, Any]]:
        corpo = self._c.corpo_chat(
            "modelo-inexistente-diagnostico",
            [Mensagem.usuario("OK")],
            OpcoesGeracao(max_tokens=1),
        )
        corpo["stream"] = False
        r = self._c.sondar("POST", "/chat/completions", json_corpo=corpo)
        self._registrar("POST /chat/completions", "modelo inexistente", r)
        dados = {"status_http": r.status, "codigo": r.codigo_erro, "mensagem": r.mensagem_erro}
        if r.erro_rede:
            return Status.FALHA, f"Falha de rede: {r.erro_rede}", dados
        if r.status in (400, 404, 422):
            return Status.OK, f"Modelo inexistente rejeitado: HTTP {r.status}.", dados
        if r.status == 200:
            return Status.ALERTA, "Um modelo inexistente foi ACEITO (HTTP 200).", dados
        return Status.INFO, f"Modelo inexistente: HTTP {r.status} (esperado 400/404).", dados

    def _p09_contexto_longo(self) -> tuple[Status, str, dict[str, Any]]:
        if not self._exigir_modelo():
            return Status.PULADO, "Sem modelo disponível.", {}
        medidas: list[dict[str, Any]] = []
        for tamanho in self._o.tamanhos_contexto:
            codigo = f"AGULHA-{uuid.uuid4().hex[:8].upper()}"
            base = "Registro de teste de contexto. " * (tamanho // 31 + 1)
            posicao = int(tamanho * 0.1)  # perto do início: o caso difícil para janelas curtas
            texto = base[:posicao] + f" O código secreto é {codigo}. " + base[posicao:tamanho]
            c = self._coletar(
                [
                    Mensagem.usuario(
                        f"{texto}\n\nQual é o código secreto mencionado no texto acima? "
                        "Responda apenas com o código."
                    )
                ]
            )
            medidas.append(
                {
                    "caracteres": tamanho,
                    "achou": codigo in c.texto,
                    "tempo_s": round(c.total_s, 2),
                    "prompt_tokens": c.uso.prompt_tokens if c.uso else None,
                    "erro": None if not c.erro else c.erro.mensagem,
                }
            )
            if c.erro:
                break
        dados = {"medidas": medidas}
        perdeu = [m["caracteres"] for m in medidas if not m["achou"]]
        if not perdeu:
            return (
                Status.OK,
                f"Recuperou a informação em todos os tamanhos: {self._o.tamanhos_contexto}.",
                dados,
            )
        return (
            Status.ALERTA,
            f"Não recuperou a informação com {perdeu} caracteres: contexto cortado em silêncio ou "
            "modelo perdeu o trecho.",
            dados,
        )
