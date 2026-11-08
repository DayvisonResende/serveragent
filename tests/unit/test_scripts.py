"""Garante que os scripts do Windows tenham a codificação que o PowerShell 5.1 / cmd esperam."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BOM = b"\xef\xbb\xbf"


@pytest.mark.parametrize("script", sorted((ROOT / "scripts").glob("*.ps1")), ids=lambda p: p.name)
def test_powershell_scripts_have_exactly_one_utf8_bom(script):
    data = script.read_bytes()
    assert data.startswith(BOM), "sem BOM o PowerShell 5.1 lê o arquivo como ANSI"
    assert not data[3:].startswith(BOM), "BOM duplicado quebra o bloco param()"
    data[3:].decode("utf-8")


@pytest.mark.parametrize("bat", sorted(ROOT.glob("*.bat")), ids=lambda p: p.name)
def test_batch_files_are_ascii_with_crlf(bat):
    data = bat.read_bytes()
    assert data.isascii()
    assert b"\n" not in data.replace(b"\r\n", b"")


@pytest.mark.parametrize("script", ["install.ps1", "uninstall.ps1"])
def test_clean_stop_failure_cannot_abort_install_scripts(script):
    """No PowerShell 5.1, stderr redirecionado (2>&1) sob ErrorActionPreference=Stop vira
    erro fatal: um agente antigo que não aceita parada limpa abortaria a instalação."""
    text = (ROOT / "scripts" / script).read_bytes()[3:].decode("utf-8")
    stop_lines = [line for line in text.splitlines() if "sentinel stop" in line and not line.lstrip().startswith("#")]
    assert stop_lines, "o script deve tentar a parada limpa"
    assert all("2>&1" not in line for line in stop_lines)
    lines = text.splitlines()
    stop_at = lines.index(stop_lines[0])
    assert any('$ErrorActionPreference = "Continue"' in line for line in lines[max(0, stop_at - 6):stop_at])


def test_investigation_script_is_read_only():
    """O script de investigação não pode alterar o sistema, executar o alvo ou enviar dados."""
    import re

    text = (ROOT / "scripts" / "investigate-process.ps1").read_bytes()[3:].decode("utf-8")
    code = "\n".join(line.split("#")[0] for line in text.splitlines())  # ignora comentários
    forbidden = [
        r"Remove-Item", r"Stop-Process", r"Set-Item", r"New-ItemProperty", r"Remove-ItemProperty",
        r"Rename-Item", r"Move-Item", r"Copy-Item", r"Unregister-", r"Disable-", r"Stop-Service",
        r"Set-Service", r"Set-Mp", r"Remove-Mp", r"Add-Mp", r"Invoke-WebRequest", r"Invoke-RestMethod",
        r"Net\.WebClient", r"\.Save\(", r"Start-ScheduledTask", r"Stop-ScheduledTask", r"Invoke-Expression", r"\biex\b",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, code, re.IGNORECASE), pattern
    # O único programa iniciado é o Bloco de Notas, para exibir o relatório.
    assert re.findall(r"Start-Process\s+(\S+)", code) == ["notepad.exe"]
    # Escritas: somente a pasta de logs e o próprio relatório.
    assert re.findall(r"Add-Content\s+-Path\s+(\$\w+)", code) == ["$Report"]
    assert re.findall(r"New-Item\b.*?-Path\s+(\$\w+)", code) == ["$LogDir"]


def test_code_fingerprint_ignores_line_endings_and_detects_changes(tmp_path):
    from sentinel.agent.fingerprint import fingerprint

    (tmp_path / "sentinel").mkdir()
    (tmp_path / "sentinel" / "a.py").write_bytes(b"x = 1\ny = 2\n")
    (tmp_path / "sentinel" / "__pycache__").mkdir()
    (tmp_path / "sentinel" / "__pycache__" / "a.py").write_bytes(b"lixo")
    code, rows = fingerprint(tmp_path)
    assert [name for name, _ in rows] == ["sentinel/a.py"]  # cache do Python não conta
    (tmp_path / "sentinel" / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")  # cópia que virou CRLF
    assert fingerprint(tmp_path)[0] == code
    (tmp_path / "sentinel" / "a.py").write_bytes(b"x = 1\ny = 3\n")  # conteúdo antigo/diferente
    assert fingerprint(tmp_path)[0] != code
