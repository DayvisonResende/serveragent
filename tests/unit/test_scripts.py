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
