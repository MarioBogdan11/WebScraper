#!/usr/bin/env python3
"""Friendly desktop GUI for batch scraping Individual Web Scrape project pages.

Run with:
    python scraper_gui.py
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from web_scraper import scrape

# Determine base directory for frozen executable vs development
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path.cwd()


URL_RE = re.compile(r"https?://[^\s,]+", re.IGNORECASE)


def safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = (parsed.path or "").strip("/")
    base = path if path else parsed.netloc
    if parsed.query:
        base = f"{base}_{parsed.query}"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if not name:
        name = re.sub(r"[^A-Za-z0-9._-]", "_", parsed.netloc)
    return f"{name}.json"


def extract_urls(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in URL_RE.findall(text):
        url = match.rstrip(")].,;\"'>")
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


@dataclass
class ScrapeResult:
    url: str
    ok: bool
    path: str | None = None
    error: str | None = None
    project_name: str | None = None


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget, **kwargs):
        super().__init__(parent, **kwargs)

        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)

        self.inner.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(self.canvas_window, width=event.width),
        )


class ScraperGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("Individual Web Scraper")
        self.geometry("1180x760")
        self.minsize(1020, 680)

        self.task_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.running = False
        self.queued_urls: list[str] = []

        self.output_dir = tk.StringVar(value=str(BASE_DIR / "output"))
        self.delay_seconds = tk.DoubleVar(value=1.2)
        self.status_text = tk.StringVar(value="Ready to add links.")
        self.progress_text = tk.StringVar(value="0 / 0")

        self._build_style()
        self._build_ui()
        self.after(120, self._drain_queue)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("App.TFrame", background="#f3f5f7")
        style.configure("Hero.TFrame", background="#1f2937")
        style.configure("HeroTitle.TLabel", background="#1f2937", foreground="#ffffff", font=("Segoe UI", 20, "bold"))
        style.configure("HeroBody.TLabel", background="#1f2937", foreground="#d1d5db", font=("Segoe UI", 10))
        style.configure("Section.TLabelframe", background="#f3f5f7", padding=12)
        style.configure("Section.TLabelframe.Label", background="#f3f5f7", foreground="#111827", font=("Segoe UI", 10, "bold"))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))
        style.map("Primary.TButton", foreground=[("active", "#ffffff")], background=[("active", "#2563eb")])
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))
        style.configure("TLabel", background="#f3f5f7", foreground="#111827", font=("Segoe UI", 10))
        style.configure("Hint.TLabel", background="#f3f5f7", foreground="#6b7280", font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#111827", foreground="#ffffff", font=("Segoe UI", 10, "bold"))
        style.configure("TEntry", padding=6)
        style.configure("TSpinbox", padding=6)

    def _build_ui(self) -> None:
        self.configure(bg="#f3f5f7")

        hero = ttk.Frame(self, style="Hero.TFrame", padding=(24, 22))
        hero.pack(fill="x")

        ttk.Label(hero, text="Individual Web Scraper", style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(
            hero,
            text="Paste several project links, queue them, and export clean JSON files with one click.",
            style="HeroBody.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        main = ttk.Frame(self, style="App.TFrame", padding=18)
        main.pack(fill="both", expand=True)

        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(1, weight=1)

        left = ttk.Labelframe(main, text="Add links", style="Section.TLabelframe")
        left.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 10), pady=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        right = ttk.Labelframe(main, text="Queue and output", style="Section.TLabelframe")
        right.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(10, 0), pady=(0, 10))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        input_help = ttk.Label(
            left,
            text="Paste one URL per line, or a whole block of text with multiple links.",
            style="Hint.TLabel",
            wraplength=460,
            justify="left",
        )
        input_help.grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.url_input = tk.Text(
            left,
            height=11,
            wrap="word",
            font=("Segoe UI", 10),
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#d1d5db",
            highlightcolor="#2563eb",
            undo=True,
        )
        self.url_input.grid(row=1, column=0, sticky="nsew")
        self.url_input.insert("1.0", "https://www.archipelag.pl/projekty-domow/moniczka-iii-energo-plus-reco\nhttps://www.archipelag.pl/projekty-domow/daniel-ix-g2")

        left_buttons = ttk.Frame(left)
        left_buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        left_buttons.columnconfigure(0, weight=1)
        left_buttons.columnconfigure(1, weight=1)

        ttk.Button(left_buttons, text="Add to queue", style="Primary.TButton", command=self.add_urls).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(left_buttons, text="Load urls.txt", command=self.load_urls_file).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        queue_help = ttk.Label(right, text="Queued URLs are saved in order. Remove any entry before scraping if needed.", style="Hint.TLabel", wraplength=460, justify="left")
        queue_help.grid(row=0, column=0, sticky="w", pady=(0, 8))

        list_frame = ttk.Frame(right)
        list_frame.grid(row=1, column=0, sticky="ew")
        list_frame.columnconfigure(0, weight=1)
        self.queue_list = tk.Listbox(
            list_frame,
            height=9,
            selectmode=tk.EXTENDED,
            activestyle="none",
            font=("Segoe UI", 10),
            relief="solid",
            borderwidth=1,
            highlightthickness=1,
            highlightbackground="#d1d5db",
            highlightcolor="#2563eb",
        )
        self.queue_list.grid(row=0, column=0, sticky="ew")
        queue_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.queue_list.yview)
        self.queue_list.configure(yscrollcommand=queue_scroll.set)
        queue_scroll.grid(row=0, column=1, sticky="ns")

        queue_buttons = ttk.Frame(right)
        queue_buttons.grid(row=2, column=0, sticky="ew", pady=(10, 10))
        queue_buttons.columnconfigure(0, weight=1)
        queue_buttons.columnconfigure(1, weight=1)
        queue_buttons.columnconfigure(2, weight=1)

        ttk.Button(queue_buttons, text="Remove selected", command=self.remove_selected).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(queue_buttons, text="Clear queue", command=self.clear_queue).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(queue_buttons, text="Open output", command=self.open_output_folder).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        settings = ttk.Frame(right)
        settings.grid(row=3, column=0, sticky="nsew")
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="Output folder").grid(row=0, column=0, sticky="w", pady=(0, 6))
        output_row = ttk.Frame(settings)
        output_row.grid(row=0, column=1, sticky="ew", pady=(0, 6))
        output_row.columnconfigure(0, weight=1)
        ttk.Entry(output_row, textvariable=self.output_dir).grid(row=0, column=0, sticky="ew")
        ttk.Button(output_row, text="Browse", command=self.choose_output_dir).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(settings, text="Delay between requests (seconds)").grid(row=1, column=0, sticky="w", pady=(0, 6))
        ttk.Spinbox(settings, from_=0.0, to=30.0, increment=0.2, textvariable=self.delay_seconds, width=10).grid(row=1, column=1, sticky="w", pady=(0, 6))

        self.start_button = ttk.Button(settings, text="Start scraping", style="Primary.TButton", command=self.start_scraping)
        self.start_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 10))

        ttk.Separator(settings, orient="horizontal").grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 10))

        ttk.Label(settings, text="Progress").grid(row=4, column=0, sticky="w")
        self.progress = ttk.Progressbar(settings, mode="determinate", maximum=100)
        self.progress.grid(row=4, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(settings, textvariable=self.progress_text, style="Hint.TLabel").grid(row=5, column=0, sticky="w", pady=(0, 8))
        ttk.Label(settings, textvariable=self.status_text, style="Status.TLabel", anchor="w").grid(row=6, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        log_frame = ttk.Labelframe(main, text="Activity log", style="Section.TLabelframe")
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log = tk.Text(
            log_frame,
            height=12,
            wrap="word",
            font=("Consolas", 9),
            relief="solid",
            borderwidth=1,
            state="disabled",
            highlightthickness=1,
            highlightbackground="#d1d5db",
            highlightcolor="#2563eb",
        )
        self.log.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        log_scroll.grid(row=0, column=1, sticky="ns")

    def log_message(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def refresh_queue_list(self) -> None:
        self.queue_list.delete(0, tk.END)
        for url in self.queued_urls:
            self.queue_list.insert(tk.END, url)
        self.progress_text.set(f"{len(self.queued_urls)} queued")

    def add_urls(self) -> None:
        text = self.url_input.get("1.0", "end")
        urls = extract_urls(text)
        if not urls:
            messagebox.showinfo("Add URLs", "No valid URLs were found in the text you pasted.")
            return

        added = 0
        existing = set(self.queued_urls)
        for url in urls:
            if url not in existing:
                self.queued_urls.append(url)
                existing.add(url)
                added += 1

        self.refresh_queue_list()
        self.log_message(f"Added {added} URL(s) to the queue.")
        self.status_text.set(f"Queued {len(self.queued_urls)} URL(s).")

    def load_urls_file(self) -> None:
        path = BASE_DIR / "urls.txt"
        if not path.exists():
            messagebox.showwarning("Load URLs", "urls.txt was not found in the application folder.")
            return

        text = path.read_text(encoding="utf-8")
        urls = extract_urls(text)
        if not urls:
            messagebox.showinfo("Load URLs", "urls.txt does not contain any valid links.")
            return

        added = 0
        existing = set(self.queued_urls)
        for url in urls:
            if url not in existing:
                self.queued_urls.append(url)
                existing.add(url)
                added += 1

        self.refresh_queue_list()
        self.log_message(f"Loaded {added} URL(s) from urls.txt.")
        self.status_text.set(f"Queued {len(self.queued_urls)} URL(s).")

    def remove_selected(self) -> None:
        selected = list(self.queue_list.curselection())
        if not selected:
            return
        for index in reversed(selected):
            del self.queued_urls[index]
        self.refresh_queue_list()
        self.log_message("Removed selected URLs from the queue.")

    def clear_queue(self) -> None:
        self.queued_urls.clear()
        self.refresh_queue_list()
        self.log_message("Cleared the queue.")
        self.status_text.set("Queue cleared.")
        self.progress["value"] = 0
        self.progress_text.set("0 / 0")

    def choose_output_dir(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.output_dir.get() or str(Path.cwd()))
        if folder:
            self.output_dir.set(folder)

    def open_output_folder(self) -> None:
        folder = Path(self.output_dir.get()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(folder)
        except AttributeError:
            messagebox.showinfo("Open output", f"Output folder: {folder}")

    def start_scraping(self) -> None:
        if self.running:
            return
        if not self.queued_urls:
            messagebox.showinfo("Start scraping", "Add at least one URL to the queue first.")
            return

        self.running = True
        self.start_button.configure(state="disabled")
        self.progress["value"] = 0
        self.progress["maximum"] = len(self.queued_urls)
        self.progress_text.set(f"0 / {len(self.queued_urls)}")
        self.status_text.set("Scraping started...")
        self.log_message(f"Starting scrape of {len(self.queued_urls)} URL(s).")

        urls = list(self.queued_urls)
        output_dir = Path(self.output_dir.get()).expanduser()
        delay = max(0.0, float(self.delay_seconds.get()))

        self.worker = threading.Thread(target=self._scrape_worker, args=(urls, output_dir, delay), daemon=True)
        self.worker.start()

    def _scrape_worker(self, urls: list[str], output_dir: Path, delay: float) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict] = []

        for index, url in enumerate(urls, start=1):
            self.task_queue.put(("status", f"[{index}/{len(urls)}] Scraping {url}"))
            try:
                data = scrape(url)
                file_name = safe_filename_from_url(url)
                output_path = output_dir / file_name
                output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                results.append({"url": url, "file": str(output_path), "project_name": data.get("project_name")})
                self.task_queue.put(("log", f"Saved {output_path}"))
                self.task_queue.put(("result", ScrapeResult(url=url, ok=True, path=str(output_path), project_name=data.get("project_name"))))
            except Exception as exc:
                self.task_queue.put(("log", f"Error scraping {url}: {exc}"))
                self.task_queue.put(("result", ScrapeResult(url=url, ok=False, error=str(exc))))

            self.task_queue.put(("progress", index, len(urls)))

            if delay and index < len(urls):
                threading.Event().wait(delay)

        combined_path = output_dir / "all_results.json"
        combined_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        self.task_queue.put(("log", f"Wrote combined index to {combined_path}"))
        self.task_queue.put(("done", len(results), len(urls), str(combined_path)))

    def _drain_queue(self) -> None:
        try:
            while True:
                item = self.task_queue.get_nowait()
                kind = item[0]

                if kind == "status":
                    self.status_text.set(item[1])
                elif kind == "log":
                    self.log_message(item[1])
                elif kind == "progress":
                    current, total = item[1], item[2]
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = current
                    self.progress_text.set(f"{current} / {total}")
                elif kind == "done":
                    success_count, total, combined_path = item[1], item[2], item[3]
                    self.running = False
                    self.start_button.configure(state="normal")
                    self.status_text.set(f"Finished. {success_count}/{total} successful.")
                    self.log_message(f"Finished. {success_count}/{total} successful. Combined file: {combined_path}")
                    messagebox.showinfo("Scrape complete", f"Finished {success_count} of {total} URLs.\nCombined index: {combined_path}")
                elif kind == "result":
                    result: ScrapeResult = item[1]
                    if result.ok:
                        self.log_message(f"OK  {result.url}")
                    else:
                        self.log_message(f"FAIL {result.url}: {result.error}")
        except queue.Empty:
            pass

        self.after(120, self._drain_queue)


def main() -> None:
    app = ScraperGUI()
    app.mainloop()


if __name__ == "__main__":
    main()