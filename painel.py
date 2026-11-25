"""Painel local (janela no PC): mostra o endereço/QR code, escolhe a saída
de som, mostra o nível do áudio e os aparelhos conectados."""
import math
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import qrcode

import autostart
from server import BUNDLE, Engine, local_ips

BG = "#eef1f5"
CARD = "#ffffff"
INK = "#111827"
MUTED = "#6b7280"
LINE = "#e5e7eb"
ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
OK = "#16a34a"
WARN = "#d97706"
DANGER = "#dc2626"
FONT = "Segoe UI"


class FlatButton(tk.Label):
    """Botão plano com hover (o tk.Button do Windows não aceita bem cores)."""

    def __init__(self, master, text, command, kind="primary", **kw):
        self.kind = kind
        super().__init__(master, text=text, cursor="hand2", padx=14, pady=7,
                         font=(FONT, 10, "bold"), **kw)
        self.command = command
        self._paint(False)
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))
        self.bind("<Button-1>", lambda e: self.command())

    def set_kind(self, kind):
        self.kind = kind
        self._paint(False)

    def _paint(self, hover):
        if self.kind == "primary":
            self.config(bg=ACCENT_HOVER if hover else ACCENT, fg="white")
        elif self.kind == "warn":
            self.config(bg="#b45309" if hover else WARN, fg="white")
        elif self.kind == "danger":
            self.config(bg="#fee2e2" if hover else "#fef2f2", fg=DANGER)
        else:
            self.config(bg="#e5e7eb" if hover else "#f3f4f6", fg=INK)


def card(master, title):
    outer = tk.Frame(master, bg=LINE)               # borda de 1px
    inner = tk.Frame(outer, bg=CARD, padx=18, pady=14)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    lbl = tk.Label(inner, text=title, bg=CARD, fg=INK, font=(FONT, 11, "bold"), anchor="w")
    lbl.pack(fill="x")
    return outer, inner, lbl


def fmt_dur(sec):
    sec = int(sec)
    if sec < 60:
        return f"{sec} s"
    if sec < 3600:
        return f"{sec // 60} min"
    return f"{sec // 3600} h {sec % 3600 // 60:02d} min"


class Painel:
    def __init__(self, root: tk.Tk, engine: Engine):
        self.root = root
        self.e = engine
        self.ips = local_ips() or ["127.0.0.1"]
        self.ip = tk.StringVar(value=self.ips[0])
        self.dev = tk.StringVar(value=engine.device or "")
        self.shown_level = 0.0
        self.auto = tk.BooleanVar(value=autostart.is_enabled())

        root.title("Som do PC")
        root.configure(bg=BG)
        root.minsize(820, 560)
        self._style()
        self._build()
        self._load_devices()
        self._draw_qr()
        self._sync_autostart()
        self._tick_level()
        self._tick_listeners()

    # ---------- montagem ----------

    def _style(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")
        st.configure("TCombobox", padding=6, fieldbackground="white", background="white",
                     bordercolor=LINE, lightcolor=LINE, darkcolor=LINE, arrowcolor=MUTED)
        st.map("TCombobox", fieldbackground=[("readonly", "white")],
               selectbackground=[("readonly", "white")], selectforeground=[("readonly", INK)])
        st.configure("Treeview", rowheight=30, font=(FONT, 10), background="white",
                     fieldbackground="white", bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        st.configure("Treeview.Heading", font=(FONT, 9, "bold"), background="#f9fafb",
                     foreground=MUTED, relief="flat", bordercolor=LINE)
        st.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", INK)])

    def _build(self):
        # Cabeçalho
        head = tk.Frame(self.root, bg=INK, padx=24, pady=16)
        head.pack(fill="x")
        left = tk.Frame(head, bg=INK)
        left.pack(side="left")
        tk.Label(left, text="🎧  Som do PC", bg=INK, fg="white",
                 font=(FONT, 16, "bold")).pack(anchor="w")
        tk.Label(left, text="Ouça o som deste computador no celular, pela rede local",
                 bg=INK, fg="#9ca3af", font=(FONT, 10)).pack(anchor="w")
        self.pill = tk.Label(head, text="", font=(FONT, 10, "bold"), padx=12, pady=5)
        self.pill.pack(side="right")

        body = tk.Frame(self.root, bg=BG, padx=20, pady=18)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        # Cartão: conectar o celular
        c, inner, _ = card(body, "1. Conecte o celular")
        c.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 16))
        tk.Label(inner, text="Aponte a câmera do celular para o código\nou digite o endereço no navegador.",
                 bg=CARD, fg=MUTED, font=(FONT, 9), justify="left").pack(anchor="w", pady=(2, 10))
        self.qr = tk.Canvas(inner, width=232, height=232, bg="white", highlightthickness=0)
        self.qr.pack(pady=(0, 10))
        self.url_lbl = tk.Label(inner, text="", bg=CARD, fg=ACCENT, cursor="hand2",
                                font=(FONT, 13, "bold"))
        self.url_lbl.pack()
        self.url_lbl.bind("<Button-1>", lambda e: self._copy())
        if len(self.ips) > 1:
            row = tk.Frame(inner, bg=CARD)
            row.pack(pady=(8, 0))
            tk.Label(row, text="Não conectou? Tente:", bg=CARD, fg=MUTED,
                     font=(FONT, 9)).pack(side="left", padx=(0, 6))
            cb = ttk.Combobox(row, textvariable=self.ip, values=self.ips, state="readonly", width=15)
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>", lambda e: self._draw_qr())
        btns = tk.Frame(inner, bg=CARD)
        btns.pack(pady=(12, 4))
        self.copy_btn = FlatButton(btns, "Copiar endereço", self._copy, bg=CARD)
        self.copy_btn.pack(side="left", padx=4)
        FlatButton(btns, "Abrir neste PC", self._open, kind="ghost").pack(side="left", padx=4)
        tk.Label(inner, text="📶  O celular precisa estar no mesmo Wi-Fi.",
                 bg=CARD, fg=MUTED, font=(FONT, 9)).pack(pady=(10, 0))

        # Cartão: som capturado
        c, inner, _ = card(body, "2. Som que vai para o celular")
        c.grid(row=0, column=1, sticky="ew")
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(8, 10))
        self.dev_cb = ttk.Combobox(row, textvariable=self.dev, state="readonly")
        self.dev_cb.pack(side="left", fill="x", expand=True)
        self.dev_cb.bind("<<ComboboxSelected>>", lambda e: self._change_device())
        FlatButton(row, "↻", self._refresh_devices, kind="ghost").pack(side="left", padx=(8, 0))
        self.meter = tk.Canvas(inner, height=16, bg=CARD, highlightthickness=0)
        self.meter.pack(fill="x")
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(10, 0))
        self.level_lbl = tk.Label(row, text="", bg=CARD, fg=MUTED, font=(FONT, 9))
        self.level_lbl.pack(side="left")
        self.pause_btn = FlatButton(row, "", self._toggle_pause, bg=CARD)
        self.pause_btn.pack(side="right")
        self._paint_pause()

        # Cartão: aparelhos
        c, inner, self.list_title = card(body, "Aparelhos ouvindo")
        c.grid(row=1, column=1, sticky="nsew", pady=(16, 0))
        wrap = tk.Frame(inner, bg=CARD)
        wrap.pack(fill="both", expand=True, pady=(8, 8))
        self.tree = ttk.Treeview(wrap, columns=("aparelho", "ip", "tempo"), show="headings",
                                 selectmode="browse", height=4)
        for col, txt, w in (("aparelho", "Aparelho", 140), ("ip", "Endereço", 140), ("tempo", "Ouvindo há", 100)):
            self.tree.heading(col, text=txt, anchor="w")
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.empty = tk.Label(wrap, text="Nenhum aparelho conectado.\nAbra o endereço no celular e toque em Ouvir.",
                              bg="white", fg=MUTED, font=(FONT, 9), justify="center")
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x")
        self.kick_btn = FlatButton(row, "Desconectar selecionado", self._kick, kind="danger")
        self.kick_btn.pack(side="right")

        foot = tk.Frame(self.root, bg=BG, padx=20)
        foot.pack(fill="x", pady=(0, 10))
        if autostart.available():
            tk.Checkbutton(foot, text="Iniciar com o Windows", variable=self.auto,
                           command=self._toggle_autostart, bg=BG, fg=INK, activebackground=BG,
                           font=(FONT, 9), cursor="hand2").pack(side="left")
        tk.Label(foot, text=f"Porta {self.e.port}  ·  {self.e.hostname}  ·  não exponha esta porta na internet",
                 bg=BG, fg=MUTED, font=(FONT, 8)).pack(side="right")

    # ---------- endereço / QR ----------

    @property
    def url(self):
        return f"http://{self.ip.get()}:{self.e.port}"

    def _draw_qr(self):
        self.url_lbl.config(text=self.url.replace("http://", ""))
        qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(self.url)
        qr.make(fit=True)
        m = qr.get_matrix()
        size = 232
        cell = size / len(m)
        self.qr.delete("all")
        for y, row in enumerate(m):
            for x, on in enumerate(row):
                if on:
                    self.qr.create_rectangle(x * cell, y * cell, (x + 1) * cell, (y + 1) * cell,
                                             fill=INK, outline=INK)

    def _copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.url)
        self.copy_btn.config(text="✓ Copiado")
        self.root.after(1500, lambda: self.copy_btn.config(text="Copiar endereço"))

    def _open(self):
        webbrowser.open(f"http://127.0.0.1:{self.e.port}")

    # ---------- dispositivo ----------

    def _load_devices(self):
        names, default = self.e.devices()
        self.dev_names = names
        self.default_dev = default
        self.dev_cb["values"] = [n + ("  (padrão)" if n == default else "") for n in names]
        cur = self.e.device
        if cur in names:
            self.dev_cb.current(names.index(cur))

    def _change_device(self):
        name = self.dev_names[self.dev_cb.current()]
        try:
            self.e.set_device(name)
        except Exception as ex:
            messagebox.showerror("Som do PC", f"Não foi possível capturar esta saída:\n{ex}")
        self._load_devices()
        self._sync_autostart()

    def _refresh_devices(self):
        try:
            self.e.refresh_devices()
        except Exception as ex:
            messagebox.showerror("Som do PC", f"Erro ao atualizar a lista:\n{ex}")
        self._load_devices()

    # ---------- iniciar com o Windows ----------

    def _autostart_args(self):
        # Grava a saída de som só se não for a padrão (a padrão pode mudar).
        dev = self.e.device if self.e.device != self.default_dev else None
        return self.e.port, dev

    def _toggle_autostart(self):
        try:
            if self.auto.get():
                autostart.enable(*self._autostart_args())
            else:
                autostart.disable()
        except OSError as ex:
            messagebox.showerror("Som do PC", f"Não foi possível alterar a inicialização:\n{ex}")
        self.auto.set(autostart.is_enabled())

    def _sync_autostart(self):
        try:
            autostart.sync(*self._autostart_args())
        except OSError:
            pass

    # ---------- pausa ----------

    def _toggle_pause(self):
        self.e.paused = not self.e.paused
        self._paint_pause()

    def _paint_pause(self):
        if self.e.paused:
            self.pause_btn.config(text="▶  Retomar transmissão")
            self.pause_btn.set_kind("primary")
            self.pill.config(text="⏸  Pausado", bg="#fef3c7", fg="#92400e")
        else:
            self.pause_btn.config(text="⏸  Pausar transmissão")
            self.pause_btn.set_kind("ghost")
            self.pill.config(text="●  No ar", bg="#dcfce7", fg="#166534")

    # ---------- atualizações periódicas ----------

    def _tick_level(self):
        lv = self.e.take_level()
        self.shown_level = max(lv, self.shown_level * 0.85)
        db = 20 * math.log10(self.shown_level) if self.shown_level > 1e-5 else -100
        frac = max(0.0, min(1.0, (db + 60) / 60))

        c = self.meter
        w = max(c.winfo_width(), 100)
        c.delete("all")
        segs = 32
        gap = 3
        sw = (w - gap * (segs - 1)) / segs
        lit = round(frac * segs)
        for i in range(segs):
            x = i * (sw + gap)
            if i < lit:
                color = OK if i < segs * 0.7 else (WARN if i < segs * 0.9 else DANGER)
            else:
                color = "#f3f4f6"
            c.create_rectangle(x, 0, x + sw, 16, fill=color, outline="")

        if self.e.paused:
            txt = "Pausado: os celulares recebem silêncio"
        elif db < -55:
            txt = "Sem som no momento. Toque algo no PC."
        else:
            txt = "Recebendo som do PC"
        self.level_lbl.config(text=txt)
        self.root.after(60, self._tick_level)

    def _tick_listeners(self):
        items = list(self.e.listeners.items())
        self.list_title.config(text=f"Aparelhos ouvindo ({len(items)})")
        seen = set()
        now = time.time()
        for lid, l in items:
            seen.add(lid)
            estado = "" if l["estado"] == "connected" else f"  ({l['estado']})"
            vals = (l["aparelho"] + estado, l["ip"], fmt_dur(now - l["desde"]))
            if self.tree.exists(lid):
                self.tree.item(lid, values=vals)
            else:
                self.tree.insert("", "end", iid=lid, values=vals)
        for iid in self.tree.get_children():
            if iid not in seen:
                self.tree.delete(iid)
        if items:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.6, anchor="center")
        self.root.after(1000, self._tick_listeners)

    def _kick(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Som do PC", "Selecione um aparelho na lista.")
            return
        self.e.kick(sel[0])


def run_gui(engine: Engine, device=None, minimized=False):
    try:  # textos nítidos em telas com escala (125%, 150%...)
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = tk.Tk()
    root.withdraw()
    try:
        root.iconbitmap(default=str(BUNDLE / "icone.ico"))
    except tk.TclError:
        pass
    try:
        engine.set_device(device)
    except ValueError as ex:
        messagebox.showwarning("Som do PC", f"{ex}\nUsando a saída de som padrão.")
        engine.set_device(None)
    try:
        engine.start_server()
    except OSError:
        messagebox.showerror("Som do PC", f"A porta {engine.port} já está em uso.\n\n"
                             "O Som do PC já deve estar aberto em outra janela.\n"
                             "Feche-a ou use outra porta: iniciar.bat --port 9000")
        engine.stop()
        root.destroy()
        return

    Painel(root, engine)
    if minimized:      # aberto pela inicialização do Windows: fica na barra de tarefas
        root.iconify()
    else:
        root.deiconify()

    def on_close():
        if engine.listeners and not messagebox.askyesno(
                "Som do PC", f"{len(engine.listeners)} aparelho(s) ouvindo.\nEncerrar a transmissão?"):
            return
        root.destroy()
        engine.stop()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
