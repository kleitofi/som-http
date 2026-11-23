"""Transmite o som do PC (WASAPI loopback) para navegadores via WebRTC.

Uso:
  python server.py                 abre o painel (janela) no PC
  python server.py --console       roda só no console, sem janela
  python server.py --list          lista as saídas de som
  python server.py --device "Alto" --port 9000

Abra http://IP-DO-PC:8080 no celular e toque em "Ouvir".
"""
import argparse
import asyncio
import fractions
import logging
import socket
import threading
import time
import sys
import uuid
from pathlib import Path

import numpy as np
import pyaudiowpatch as pyaudio
from aiohttp import web
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamTrack
from av import AudioFrame

log = logging.getLogger("som-http")
FROZEN = getattr(sys, "frozen", False)          # rodando como .exe (PyInstaller)
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
HOME = Path(sys.executable).parent if FROZEN else Path(__file__).parent
STATIC = BUNDLE / "static"

FRAME_MS = 20            # duração de cada pacote de áudio
MAX_BUFFER_MS = 60       # acima disso descarta o mais antigo (segura a latência)
SILENCE_GRACE = 1.5      # sem som do PC por 1,5 pacote: manda silêncio


class Broadcaster:
    """Recebe blocos do capturador e distribui para cada ouvinte."""

    def __init__(self):
        self.lock = threading.Lock()
        self.listeners = set()
        self.rate = 48000
        self.channels = 2
        self.paused = False

    def add(self, track):
        with self.lock:
            self.listeners.add(track)

    def remove(self, track):
        with self.lock:
            self.listeners.discard(track)

    def push(self, samples: np.ndarray):
        if self.paused:
            return
        with self.lock:
            for t in self.listeners:
                t.feed(samples)


class LoopbackTrack(MediaStreamTrack):
    """Faixa de áudio de um ouvinte. Entrega quadros em tempo real;
    se não houver som (WASAPI para de enviar no silêncio), manda silêncio."""

    kind = "audio"

    def __init__(self, bc: Broadcaster):
        super().__init__()
        self.bc = bc
        self.channels = bc.channels
        self._set_rate(bc.rate)
        self.buf = np.zeros((0, self.channels), dtype=np.int16)
        self.buf_lock = threading.Lock()
        self.pts = 0
        self.last = None         # quando o último pacote saiu (monotonic)
        bc.add(self)

    def _set_rate(self, rate):
        self.rate = rate
        self.samples_per_frame = rate * FRAME_MS // 1000
        self.max_samples = rate * MAX_BUFFER_MS // 1000

    def feed(self, samples):
        with self.buf_lock:
            self.buf = np.concatenate((self.buf, samples))
            if len(self.buf) > self.max_samples:
                # acumulou (travada momentânea): fica só com 1 pacote, o mais recente
                self.buf = self.buf[-self.samples_per_frame:]

    async def recv(self):
        if self.readyState != "live":
            raise Exception("track ended")

        # A saída capturada mudou de taxa (troca de dispositivo): recomeça.
        if self.bc.rate != self.rate:
            with self.buf_lock:
                self.buf = self.buf[:0]
            self.pts = int(self.pts * self.bc.rate / self.rate)
            self._set_rate(self.bc.rate)

        # O ritmo de envio segue o relógio da placa de som: o pacote sai assim
        # que a captura entrega 20 ms de áudio. Assim o buffer não acumula atraso
        # por diferença entre o relógio da placa e o do Windows.
        n = self.samples_per_frame
        frame_s = n / self.rate
        if self.last is None:
            self.last = time.monotonic() - frame_s
        while True:
            with self.buf_lock:
                if len(self.buf) >= n:
                    chunk = self.buf[:n]
                    self.buf = self.buf[n:]
                    self.last = time.monotonic()
                    break
            now = time.monotonic()
            if now >= self.last + frame_s * SILENCE_GRACE:
                # PC em silêncio (WASAPI para de entregar): completa com zeros
                with self.buf_lock:
                    chunk = self.buf[:n]
                    self.buf = self.buf[n:]
                chunk = np.concatenate((chunk, np.zeros((n - len(chunk), self.channels), np.int16)))
                self.last = self.last + frame_s if now - self.last < 0.2 else now
                break
            await asyncio.sleep(0.003)

        frame = AudioFrame.from_ndarray(chunk.reshape(1, -1), format="s16", layout="stereo")
        frame.sample_rate = self.rate
        frame.pts = self.pts
        frame.time_base = fractions.Fraction(1, self.rate)
        self.pts += n
        return frame

    def stop(self):
        self.bc.remove(self)
        super().stop()


def describe_agent(ua: str) -> str:
    ua = ua or ""
    for key, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                      ("Windows", "Windows"), ("Macintosh", "Mac"), ("Linux", "Linux")):
        if key in ua:
            return name
    return "Navegador"


def local_ips():
    """IPs da rede local; o da rota principal (o Wi-Fi/cabo de verdade) vem primeiro."""
    primary = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # não envia nada, só escolhe a rota
            primary = s.getsockname()[0]
    except OSError:
        pass
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips = sorted(ip for ip in ips if not ip.startswith("127.") and ip != primary)
    return ([primary] if primary and not primary.startswith("127.") else []) + ips


class Engine:
    """Captura + servidor web. Roda o servidor numa thread própria,
    para poder ser controlado pelo painel (janela) ou pelo console."""

    def __init__(self, port=8080):
        self.port = port
        self.bc = Broadcaster()
        self.pa = pyaudio.PyAudio()
        self.stream = None
        self.device = None
        self.level = 0.0                 # pico recente, 0..1
        self.listeners = {}              # id -> {pc, ip, aparelho, desde, estado}
        self.loop = None
        self.runner = None
        self.on_change = None            # callback quando a lista de ouvintes muda
        self.hostname = socket.gethostname()

    # ---------- captura ----------

    def devices(self):
        default = self.pa.get_default_wasapi_loopback()["name"]
        names = [lb["name"] for lb in self.pa.get_loopback_device_info_generator()]
        return names, default

    def _find(self, name=None):
        if name:
            for lb in self.pa.get_loopback_device_info_generator():
                if name.lower() in lb["name"].lower():
                    return lb
            raise ValueError(f"Saída de som contendo '{name}' não encontrada.")
        return self.pa.get_default_wasapi_loopback()

    def set_device(self, name=None):
        dev = self._find(name)
        self._close_stream()
        rate = int(dev["defaultSampleRate"])
        dev_ch = int(dev["maxInputChannels"])

        def callback(data, frame_count, time_info, status):
            a = np.frombuffer(data, dtype=np.int16).reshape(-1, dev_ch)
            if dev_ch == 1:
                a = np.repeat(a, 2, axis=1)
            elif dev_ch > 2:
                a = a[:, :2]
            if len(a):
                peak = float(np.abs(a).max()) / 32768.0
                self.level = max(peak, self.level)
            self.bc.push(np.ascontiguousarray(a))
            return (None, pyaudio.paContinue)

        self.stream = self.pa.open(
            format=pyaudio.paInt16,
            channels=dev_ch,
            rate=rate,
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=rate * FRAME_MS // 1000,
            stream_callback=callback,
        )
        self.bc.rate = rate
        self.stream.start_stream()
        self.device = dev["name"]
        log.info("Capturando: %s (%d Hz, %d canais)", dev["name"], rate, dev_ch)

    def refresh_devices(self):
        """Relê a lista de saídas (fone ou caixa ligada depois de abrir o programa)."""
        current = self.device
        self._close_stream()
        self.pa.terminate()
        self.pa = pyaudio.PyAudio()
        try:
            self.set_device(current)
        except ValueError:
            self.set_device(None)

    def _close_stream(self):
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except OSError:
                pass
            self.stream = None

    def take_level(self):
        """Lê o pico desde a última leitura (usado pelo medidor)."""
        lv, self.level = self.level, 0.0
        return lv

    @property
    def paused(self):
        return self.bc.paused

    @paused.setter
    def paused(self, v):
        self.bc.paused = bool(v)

    # ---------- servidor ----------

    def start_server(self):
        """Sobe o servidor numa thread. Lança OSError se a porta estiver ocupada."""
        ready = threading.Event()
        err = []

        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self._start_site())
            except Exception as e:      # porta ocupada etc.
                err.append(e)
                ready.set()
                return
            ready.set()
            self.loop.run_forever()

        threading.Thread(target=run, daemon=True, name="servidor").start()
        ready.wait()
        if err:
            raise err[0]

    async def _start_site(self):
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_post("/offer", self._offer)
        app.router.add_get("/status", self._status)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, "0.0.0.0", self.port).start()

    def stop(self):
        if self.loop and self.loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)
            try:
                fut.result(timeout=3)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
        self._close_stream()
        self.pa.terminate()

    async def _shutdown(self):
        await asyncio.gather(*(l["pc"].close() for l in list(self.listeners.values())),
                             return_exceptions=True)
        self.listeners.clear()
        if self.runner:
            await self.runner.cleanup()

    def kick(self, lid):
        """Desconecta um ouvinte (chamado pelo painel)."""
        l = self.listeners.get(lid)
        if l and self.loop:
            asyncio.run_coroutine_threadsafe(l["pc"].close(), self.loop)

    def _changed(self):
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    async def _index(self, request):
        return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    async def _status(self, request):
        return web.json_response({
            "ouvintes": len(self.listeners),
            "pc": self.hostname,
            "dispositivo": self.device,
            "pausado": self.paused,
        })

    async def _offer(self, request):
        params = await request.json()
        # Rede local: sem STUN (evita ~5 s de espera consultando servidor externo)
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        track = LoopbackTrack(self.bc)
        lid = uuid.uuid4().hex[:8]
        self.listeners[lid] = {
            "pc": pc, "ip": request.remote,
            "aparelho": describe_agent(request.headers.get("User-Agent")),
            "desde": time.time(), "estado": "conectando",
        }
        self._changed()

        @pc.on("connectionstatechange")
        async def on_state():
            st = pc.connectionState
            if lid in self.listeners:
                self.listeners[lid]["estado"] = st
            if st in ("failed", "closed", "disconnected"):
                track.stop()
                self.listeners.pop(lid, None)
                await pc.close()
            log.info("%s: %s (ouvintes: %d)", request.remote, st, len(self.listeners))
            self._changed()

        await pc.setRemoteDescription(RTCSessionDescription(sdp=params["sdp"], type=params["type"]))
        pc.addTrack(track)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return web.json_response({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})


def run_console(engine: Engine):
    engine.start_server()
    print("\nAbra no celular (mesma rede Wi-Fi):")
    for ip in local_ips():
        print(f"   http://{ip}:{engine.port}")
    print("\nCtrl+C para sair.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()


def main():
    ap = argparse.ArgumentParser(description="Transmite o som do PC para celulares via WebRTC")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--device", help="parte do nome da saída de som a capturar")
    ap.add_argument("--list", action="store_true", help="lista as saídas de som")
    ap.add_argument("--console", action="store_true", help="roda sem a janela do painel")
    args = ap.parse_args()

    if (args.console or args.list) and sys.stdout is None:
        # .exe sem console: usa o console de onde foi chamado (ou abre um novo)
        import ctypes
        k = ctypes.windll.kernel32
        if not k.AttachConsole(-1):
            k.AllocConsole()
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout

    handlers = [logging.FileHandler(HOME / "som-http.log", encoding="utf-8")]
    if args.console or args.list:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S", handlers=handlers)
    logging.getLogger("aioice").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    if args.list:
        p = pyaudio.PyAudio()
        default = p.get_default_wasapi_loopback()["name"]
        for lb in p.get_loopback_device_info_generator():
            mark = " (padrão)" if lb["name"] == default else ""
            print(f"- {lb['name']}{mark}")
        p.terminate()
        return

    engine = Engine(args.port)

    if args.console:
        try:
            engine.set_device(args.device)
        except ValueError as e:
            raise SystemExit(f"{e} Use --list.")
        run_console(engine)
    else:
        from painel import run_gui
        run_gui(engine, args.device)


if __name__ == "__main__":
    main()
