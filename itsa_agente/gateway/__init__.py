"""Cliente da API IAitsaGateway.

Módulos:

- ``errors``  — hierarquia de exceções;
- ``models``  — contratos (DTOs) do swagger, validados com pydantic;
- ``ndjson``  — decodificação do streaming NDJSON em eventos tipados;
- ``auth``    — obtenção e renovação do JWT;
- ``client``  — cliente HTTP de alto nível (modelos, chat, sondagem de diagnóstico).

Os submódulos são importados explicitamente (sem reexportação aqui) para evitar ciclos com
``itsa_agente.config``.
"""
