"""Iniciar com o Windows: grava/remove o programa em
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run (só para o usuário atual,
não precisa de administrador)."""
import subprocess
import sys
from pathlib import Path

try:
    import winreg
except ImportError:          # fora do Windows: a opção fica indisponível
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "SomDoPC"
FROZEN = getattr(sys, "frozen", False)


def available():
    return winreg is not None


def command(port=8080, device=None):
    """Linha de comando usada na inicialização do Windows (abre minimizado)."""
    if FROZEN:
        args = [sys.executable]
    else:
        exe = Path(sys.executable)
        pythonw = exe.with_name("pythonw.exe")      # sem janela de console
        args = [str(pythonw if pythonw.exists() else exe),
                str(Path(__file__).with_name("server.py").resolve())]
    args.append("--minimized")
    if port != 8080:
        args += ["--port", str(port)]
    if device:
        args += ["--device", device]
    return subprocess.list2cmdline(args)


def current():
    """Comando gravado hoje, ou None se não está configurado."""
    if not available():
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, NAME)[0]
    except OSError:
        return None


def is_enabled():
    return current() is not None


def enable(port=8080, device=None):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, command(port, device))


def disable():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, NAME)
    except FileNotFoundError:
        pass


def sync(port=8080, device=None):
    """Se já está ligado, atualiza o comando (ex.: o .exe mudou de pasta,
    trocou a saída de som). Não liga nada sozinho."""
    if is_enabled() and current() != command(port, device):
        enable(port, device)
