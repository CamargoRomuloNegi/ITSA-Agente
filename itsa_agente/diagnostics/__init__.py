"""Diagnóstico do gateway: bateria de verificações e relatórios."""

from itsa_agente.diagnostics.modelos import Observacao, Relatorio, Resultado, Status
from itsa_agente.diagnostics.provedores import DiagnosticoProvedor, OpcoesDiagnosticoProvedor
from itsa_agente.diagnostics.relatorio import relatorio_dict, relatorio_json, relatorio_markdown
from itsa_agente.diagnostics.suite import Diagnostico, OpcoesDiagnostico

__all__ = [
    "Diagnostico",
    "DiagnosticoProvedor",
    "Observacao",
    "OpcoesDiagnostico",
    "OpcoesDiagnosticoProvedor",
    "Relatorio",
    "Resultado",
    "Status",
    "relatorio_dict",
    "relatorio_json",
    "relatorio_markdown",
]
