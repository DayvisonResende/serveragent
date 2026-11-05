"""Camada de integração com o sistema operacional (PRD 22.5).

Todo código específico de Windows (ou de POSIX) fica aqui, para que o resto do
Sentinel permaneça portável e testável fora do Windows. O nome ``oslayer``
evita colisão com o módulo ``platform`` da biblioteca padrão.
"""
