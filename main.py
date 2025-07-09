#!/usr/bin/env python3
from __future__ import annotations
import json, os, sys, threading, subprocess
from pathlib import Path
from queue import Queue, Empty
from typing import Iterable, Sequence
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

def get_allowed_ext() -> set[str]:
    base = {".py", ".java", ".xml", ".css"}
    extra = os.environ.get("CONCAT_EXT_EXTRA", "")
    base |= {x if x.startswith(".") else "." + x for x in (s.strip().lower() for s in extra.split(",") if s.strip())}
    return base

ALLOWED_EXT = get_allowed_ext()
IGNORED_DIRS = {".git", ".idea", ".vscode", "__pycache__", "build", "dist"}
DEFAULT_OUT = "projet.txt"
READ_CHUNK = 1 << 20
MAX_RECENTS = 10
CFG_PATH = Path.home() / ".concat_project.cfg"

CLR_BG = "#0f1b2b"
CLR_BG_ALT = "#142137"
CLR_FG = "#f0f0f0"
CLR_ACCENT = "#347cff"
CLR_DISABLED = "#555555"

def load_cfg() -> dict:
    try:
        return json.loads(CFG_PATH.read_text())
    except Exception:
        return {}

def save_cfg(cfg: dict) -> None:
    try:
        CFG_PATH.write_text(json.dumps(cfg))
    except Exception:
        pass

def discover_sources(root: Path) -> list[Path]:
    return sorted(
        (p for p in root.rglob("*")
         if p.is_file()
         and p.suffix.lower() in ALLOWED_EXT
         and not any(part in IGNORED_DIRS for part in p.relative_to(root).parts)),
        key=lambda p: p.relative_to(root).as_posix().lower()
    )

def read_chunks(path: Path) -> Iterable[str]:
    try:
        with path.open("r", encoding="utf-8") as f:
            while chunk := f.read(READ_CHUNK):
                yield chunk
    except UnicodeDecodeError:
        with path.open("r", encoding="latin-1", errors="replace") as f:
            while chunk := f.read(READ_CHUNK):
                yield chunk

def export_worker(root: Path, files: Sequence[Path], out_: Path, q: Queue) -> None:
    try:
        if not files:
            q.put(("error", "Aucun fichier sélectionné")); return
        total = len(files)
        with out_.open("w", encoding="utf-8") as out:
            for idx, fp in enumerate(files, 1):
                rel = fp.relative_to(root)
                out.write(f"### File: {rel} | {idx}/{total}\n" + "-"*80 + "\n")
                for chunk in read_chunks(fp):
                    out.write(chunk)
                out.write("\n\n")
                q.put(("progress", idx, total))
        q.put(("done_export", total, out_))
    except Exception as exc:
        q.put(("error", str(exc)))

def copy_worker(root: Path, files: Sequence[Path], q: Queue) -> None:
    try:
        if not files:
            q.put(("error", "Aucun fichier sélectionné")); return
        total = len(files); buf: list[str] = []
        for idx, fp in enumerate(files, 1):
            rel = fp.relative_to(root)
            buf.append(f"### File: {rel} | {idx}/{total}\n" + "-"*80 + "\n")
            buf.extend(read_chunks(fp)); buf.append("\n\n")
            q.put(("progress", idx, total))
        q.put(("done_copy", "".join(buf)))
    except Exception as exc:
        q.put(("error", str(exc)))

class ConcatApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_cfg()
        self.recent_dirs: list[str] = self.cfg.get("recent_dirs", [])[:MAX_RECENTS]
        self._apply_theme()

        self.title("Concaténation de sources • Rochias")
        self.geometry(self.cfg.get("win_geom", "960x600"))
        self.minsize(780, 480)

        self.project_dir: Path | None = (Path(self.recent_dirs[0])
                                         if self.recent_dirs and Path(self.recent_dirs[0]).exists() else None)
        self.files_all: list[Path] = []
        self.filter_var = tk.StringVar()
        self.ext_vars = {ext: tk.BooleanVar(value=True) for ext in sorted(ALLOWED_EXT)}
        self.queue: Queue = Queue()
        self.sort_reverse = False; self.sort_col = "name"

        self._build_toolbar()
        self._build_tree()
        self._build_status()

        if self.project_dir:
            self._load_files(scan_progress=False)

        self.after(100, self._process_queue)
        self.bind_all("<Control-o>", lambda e: self.choose_project())
        self.bind_all("<Control-s>", lambda e: self.export_selected())
        self.bind_all("<Control-c>", lambda e: self.copy_selected())
        self.bind_all("<Control-a>", lambda e: self.select_all())
        self.bind_all("<Control-d>", lambda e: self.clear_selection())
        self.bind_all("<F5>", lambda e: self.apply_filter())
        self.bind_all("<Control-f>", lambda e: (self.entry_filter.focus_set(), "break"))
        self.bind_all("<Control-r>", lambda e: self._refresh())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- Thème
    def _apply_theme(self) -> None:
        style = ttk.Style(self)
        base = "clam" if "clam" in style.theme_names() else style.theme_use()
        style.theme_use(base)

        style.configure(".", background=CLR_BG, foreground=CLR_FG, fieldbackground=CLR_BG)
        style.map(".", background=[("disabled", CLR_BG_ALT)], foreground=[("disabled", CLR_DISABLED)])
        style.configure("TEntry", fieldbackground=CLR_BG_ALT, foreground=CLR_FG)
        style.configure("TCheckbutton", background=CLR_BG, foreground=CLR_FG)
        style.configure("TCombobox", fieldbackground=CLR_BG_ALT, background=CLR_BG_ALT, foreground=CLR_FG)
        style.configure("TButton", relief="flat", padding=6)
        style.map("TButton", background=[("active", CLR_ACCENT)], foreground=[("active", "white")])
        style.configure("Treeview", background=CLR_BG, foreground=CLR_FG, fieldbackground=CLR_BG,
                        rowheight=24, borderwidth=0)
        style.map("Treeview", background=[("selected", CLR_ACCENT)], foreground=[("selected", "white")])
        style.configure("Odd.Treeview", background=CLR_BG_ALT)
        style.configure("Even.Treeview", background=CLR_BG)
        style.configure("blue.Horizontal.TProgressbar", troughcolor=CLR_BG_ALT, background=CLR_ACCENT)
        self.configure(background=CLR_BG)

    # ---------- Toolbar
    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=6); bar.pack(fill="x")
        def tip(w: ttk.Widget, t: str): w.bind("<Enter>", lambda _: self.lbl_msg.config(text=t)); w.bind("<Leave>", lambda _: self.lbl_msg.config(text="Prêt"))

        btn_open = ttk.Button(bar, text="📂 Ouvrir…", command=self.choose_project)
        btn_open.pack(side="left"); tip(btn_open, "Choisir un dossier projet")
        self.combo_recent = ttk.Combobox(bar, state="readonly", width=32, values=self.recent_dirs)
        self.combo_recent.pack(side="left", padx=4)
        self.combo_recent.bind("<<ComboboxSelected>>", lambda _: self._open_recent(Path(self.combo_recent.get())))

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=5)

        btn_refresh = ttk.Button(bar, text="🔄 Actualiser", command=self._refresh)
        btn_refresh.pack(side="left"); tip(btn_refresh, "Rafraîchir la liste")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=5)

        ext_frame = ttk.Frame(bar); ext_frame.pack(side="left")
        for ext in sorted(ALLOWED_EXT):
            chk = ttk.Checkbutton(ext_frame, text=ext, variable=self.ext_vars[ext], command=self.apply_filter)
            chk.pack(side="left"); tip(chk, f"Afficher/masquer {ext}")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=5)

        self.entry_filter = ttk.Entry(bar, textvariable=self.filter_var, width=30)
        self.entry_filter.pack(side="left", padx=(0,2))
        btn_filter = ttk.Button(bar, text="Filtrer", command=self.apply_filter)
        btn_filter.pack(side="left")
        btn_clear = ttk.Button(bar, text="✖", width=2, command=lambda: (self.filter_var.set(""), self.apply_filter()))
        btn_clear.pack(side="left", padx=(2,0))

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=5)

        for ext in sorted(ALLOWED_EXT):
            b = ttk.Button(bar, text=f"Tout {ext}", command=lambda e=ext: self._select_by_ext(e))
            b.pack(side="left"); tip(b, f"Sélectionner tous les {ext}")
        b_inv = ttk.Button(bar, text="Invert", command=self._invert_selection)
        b_inv.pack(side="left"); tip(b_inv, "Inverser la sélection")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=5)

        self.btn_copy = ttk.Button(bar, text="📋 Copier", command=self.copy_selected, state="disabled")
        self.btn_export = ttk.Button(bar, text="💾 Exporter", command=self.export_selected, state="disabled")
        self.btn_copy.pack(side="left", padx=(0,3)); self.btn_export.pack(side="left")
        tip(self.btn_copy, "Copier le texte concaténé"); tip(self.btn_export, "Exporter dans un fichier texte")

    # ---------- Treeview
    def _build_tree(self) -> None:
        cols = ("name", "size", "rel")
        frame = ttk.Frame(self); frame.pack(fill="both", expand=True, padx=6, pady=6)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="extended")
        for c,w in zip(cols,(260,80,500)):
            self.tree.column(c, width=self.cfg.get(f"col_{c}", w), anchor="w" if c!="size" else "e")
        for c in cols: self._set_heading(c)
        vs = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=vs.set, xscroll=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); vs.grid(row=0, column=1, sticky="ns"); hs.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._open_external)
        self.tree.bind("<<TreeviewSelect>>", self._update_counter)
        self.tree.bind("<Button-3>", self._popup_menu)

        self.menu = tk.Menu(self, tearoff=False, bg=CLR_BG, fg=CLR_FG, activebackground=CLR_ACCENT)
        self.menu.add_command(label="Ouvrir", command=lambda: self._ctx_action("open"))
        self.menu.add_command(label="Afficher dans l'explorateur", command=lambda: self._ctx_action("reveal"))
        self.menu.add_command(label="Copier chemin", command=lambda: self._ctx_action("copy"))
        self.menu.add_separator()
        self.menu.add_command(label="Basculer sélection", command=lambda: self._ctx_action("toggle"))

    # ---------- Status bar
    def _build_status(self) -> None:
        bar = ttk.Frame(self, padding=3); bar.pack(fill="x", side="bottom")
        self.lbl_count = ttk.Label(bar, text="0 / 0 sélectionné"); self.lbl_count.pack(side="left")
        self.lbl_msg = ttk.Label(bar, text="Prêt"); self.lbl_msg.pack(side="left", padx=10)
        self.progress = ttk.Progressbar(bar, length=200, style="blue.Horizontal.TProgressbar")
        self.progress.pack(side="right")

    # ---------- Files
    def choose_project(self) -> None:
        start = str(self.project_dir) if self.project_dir and self.project_dir.exists() else (self.recent_dirs[0] if self.recent_dirs else str(Path.home()))
        old = os.getcwd()
        try:
            os.chdir(start)
            path = filedialog.askdirectory(parent=self, initialdir=start, title="Choisissez le dossier projet", mustexist=True)
        finally:
            os.chdir(old)
        if path: self._open_recent(Path(path))

    def _open_recent(self, path: Path) -> None:
        if not path.exists(): return
        self.project_dir = path
        if str(path) in self.recent_dirs: self.recent_dirs.remove(str(path))
        self.recent_dirs.insert(0, str(path)); self.recent_dirs = self.recent_dirs[:MAX_RECENTS]
        self.combo_recent["values"] = self.recent_dirs; self.combo_recent.current(0)
        self._load_files()

    def _load_files(self, scan_progress=True) -> None:
        if not self.project_dir: return
        if scan_progress:
            self.progress.start(10); self.lbl_msg.config(text="Scan des fichiers…"); self.update_idletasks()
        self.files_all = discover_sources(self.project_dir)
        if scan_progress: self.progress.stop()
        self.apply_filter()
        self.lbl_msg.config(text=f"{len(self.files_all)} fichier(s) détecté(s).")

    def apply_filter(self) -> None:
        pat = self.filter_var.get().lower()
        exts = {e for e,v in self.ext_vars.items() if v.get()}
        self.tree.delete(*self.tree.get_children())
        for idx, fp in enumerate(self.files_all):
            if fp.suffix.lower() not in exts: continue
            rel = fp.relative_to(self.project_dir)
            if pat and pat not in rel.as_posix().lower(): continue
            tag = ("Even.Treeview" if idx%2 else "Odd.Treeview",)
            self.tree.insert("", "end", iid=str(fp),
                             values=(fp.name, f"{fp.stat().st_size//1024}", rel.as_posix()), tags=tag)
        self._update_counter()

    def _refresh(self) -> None:
        if not self.project_dir: return
        self.progress.start(10); self.lbl_msg.config(text="Actualisation…")
        self.after(100, lambda: (self._load_files(scan_progress=False), self.progress.stop(), self.lbl_msg.config(text="Actualisé")))

    # ---------- Sorting / Selection
    def _set_heading(self, col):
        t = dict(name="Nom", size="Ko", rel="Chemin relatif")[col]
        self.tree.heading(col, text=t, command=lambda c=col: self._sort(c))

    def _sort(self, col):
        items = list(self.tree.get_children(""))
        self.sort_reverse = not self.sort_reverse if self.sort_col==col else False
        self.sort_col = col
        items.sort(key=lambda i: (self.tree.set(i,col).lower() if col!="size" else int(self.tree.set(i,col))), reverse=self.sort_reverse)
        for i in items: self.tree.move(i,"","end")
        for c,txt in dict(name="Nom", size="Ko", rel="Chemin relatif").items():
            self.tree.heading(c, text=txt + (" ▲" if c==col and not self.sort_reverse else " ▼" if c==col else ""))

    def select_all(self): self.tree.selection_set(self.tree.get_children()); self._update_counter()
    def clear_selection(self): self.tree.selection_remove(self.tree.get_children()); self._update_counter()
    def _invert_selection(self): self.tree.selection_set(set(self.tree.get_children()) - set(self.tree.selection())); self._update_counter()
    def _select_by_ext(self, ext): self.tree.selection_set([i for i in self.tree.get_children() if Path(i).suffix.lower()==ext]); self._update_counter()

    def _update_counter(self,*_):
        s = len(self.tree.selection()); t = len(self.tree.get_children())
        self.lbl_count.config(text=f"{s} / {t} sélectionné")
        state = "normal" if s else "disabled"
        self.btn_export.config(state=state); self.btn_copy.config(state=state)

    # ---------- Export / Copy
    def export_selected(self):
        if not self.project_dir: return
        files = [Path(i) for i in self.tree.selection()]
        out = filedialog.asksaveasfilename(parent=self, initialdir=str(self.project_dir), initialfile=DEFAULT_OUT,
                                           defaultextension=".txt", filetypes=[("Fichiers texte","*.txt")])
        if out: self._run_worker(export_worker, (self.project_dir, files, Path(out), self.queue))

    def copy_selected(self):
        if self.project_dir:
            self._run_worker(copy_worker, (self.project_dir, [Path(i) for i in self.tree.selection()], self.queue))

    def _run_worker(self, target, args):
        self.progress["value"] = 0; self.btn_export.config(state="disabled"); self.btn_copy.config(state="disabled")
        self.lbl_msg.config(text="Traitement…"); threading.Thread(target=target, args=args, daemon=True).start()

    # ---------- Queue
    def _process_queue(self):
        try:
            while True:
                k,*d = self.queue.get_nowait()
                if k=="progress":
                    i,t = d; self.progress["value"]=int(i/t*100); self.lbl_msg.config(text=f"Traitement {i}/{t}")
                elif k=="done_export":
                    tot,out_ = d; self.progress["value"]=100
                    self.lbl_msg.config(text="Export terminé."); messagebox.showinfo("Succès", f"{tot} fichiers exportés dans\n{out_}")
                    self._reveal(out_); self._update_counter()
                elif k=="done_copy":
                    content, = d; self.clipboard_clear(); self.clipboard_append(content); self.progress["value"]=100
                    self.lbl_msg.config(text="Copie terminée."); messagebox.showinfo("Succès", "Texte copié dans le presse‑papiers."); self._update_counter()
                elif k=="error":
                    messagebox.showerror("Erreur", d[0]); self.lbl_msg.config(text="Erreur"); self._update_counter()
        except Empty:
            pass
        finally:
            self.after(100, self._process_queue)

    # ---------- Context
    def _popup_menu(self, e):
        row = self.tree.identify_row(e.y)
        if row:
            self.tree.selection_set(row); self.menu.tk_popup(e.x_root, e.y_root)

    def _ctx_action(self, what):
        sel = self.tree.selection()
        if not sel: return
        fp = Path(sel[0])
        if what=="open": self._open_external_fp(fp)
        elif what=="reveal": self._reveal(fp)
        elif what=="copy": self.clipboard_clear(); self.clipboard_append(str(fp)); self.lbl_msg.config(text="Chemin copié")
        elif what=="toggle": self._invert_selection()

    def _open_external(self, e):
        row = self.tree.identify_row(e.y)
        if row: self._open_external_fp(Path(row))

    def _open_external_fp(self, fp: Path):
        try:
            if sys.platform.startswith("win"): os.startfile(str(fp))
            elif sys.platform=="darwin": subprocess.Popen(["open", str(fp)])
            else: subprocess.Popen(["xdg-open", str(fp)])
        except Exception: pass

    def _reveal(self, fp: Path):
        try:
            if sys.platform.startswith("win"): subprocess.Popen(["explorer", "/select,"+str(fp)])
            elif sys.platform=="darwin": subprocess.Popen(["open", "-R", str(fp)])
            else: subprocess.Popen(["xdg-open", str(fp.parent)])
        except Exception: pass

    # ---------- Close
    def _on_close(self):
        self.cfg["win_geom"]=self.geometry(); self.cfg["recent_dirs"]=self.recent_dirs
        for c in ("name","size","rel"): self.cfg[f"col_{c}"]=self.tree.column(c)["width"]
        save_cfg(self.cfg); self.destroy()

if __name__ == "__main__":
    ConcatApp().mainloop()
