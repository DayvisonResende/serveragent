# sentinel.oslayer

**Objetivo:** concentrar todo código específico de sistema operacional
(PRD 22.5), para que o restante seja portável e testável fora do Windows.

| Arquivo | Responsabilidade |
|---|---|
| `info.py` | Sistema, versão, arquitetura, Python e se o processo é administrador |
| `instance_lock.py` | Trava de instância única (`msvcrt.locking` no Windows, `flock` em POSIX) |
| `signals.py` | Ctrl+C / SIGBREAK no Windows; SIGINT / SIGTERM em POSIX |

- A trava é liberada pelo próprio SO se o processo morrer — não sobra arquivo "preso".
- No Windows o PID gravado no arquivo de trava não é legível por outro processo
  (byte travado); a mensagem de "outra instância" pode sair sem o PID.
- Executar como administrador gera o evento `agent.running_as_admin` (atenção).

**Permissões:** nenhuma; apenas consulta.
**Testes:** `tests/unit/test_oslayer.py` (rodam em Linux; o caminho Windows ainda não foi executado).
**Limitações:** o caminho `win32` precisa ser validado no OptiPlex.
