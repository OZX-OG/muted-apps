from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
import keyboard
import tkinter as tk
import queue
import threading
import ctypes
import time
import os

os.system("")

RED, GREEN, CYAN, DIM, RESET = "\033[91m", "\033[92m", "\033[96m", "\033[90m", "\033[0m"

BG, PANEL, FG, SUBTLE, ACCENT = "#1e1e24", "#2a2a33", "#f0f0f0", "#8a8a99", "#4fc3f7"
MUTED_BG, ON_BG = "#c62828", "#2e7d32"

sessions_map, sessions_name, sessions_pid = {}, {}, {}

PAGE_SIZE = 9
current_page = 0

status = "Ready"
prompting = False
last_snapshot = None
draw_lock = threading.Lock()
gui_mode = False
app_window = None

ui_queue = queue.Queue()

console = ctypes.windll.kernel32.GetConsoleWindow()
can_hide_console = bool(console) and bool(ctypes.windll.user32.IsWindowVisible(console))

def show_console(visible):
    if can_hide_console:
        ctypes.windll.user32.ShowWindow(console, 5 if visible else 0)
        if visible:
            ctypes.windll.user32.SetForegroundWindow(console)

class MutePopup:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)
        self.label = tk.Label(self.root, font=("Segoe UI", 14, "bold"), fg="white", padx=22, pady=12, justify="left")
        self.label.pack()
        self.hide_job = None

    def show(self, text, color, duration=1500):
        self.label.config(text=text, bg=color)
        self.root.configure(bg=color)
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = self.root.winfo_screenwidth() - w - 30
        y = self.root.winfo_screenheight() - h - 80
        self.root.geometry(f"+{x}+{y}")
        self.root.deiconify()
        self.root.lift()
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
        self.hide_job = self.root.after(duration, self.root.withdraw)

class AppWindow:
    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.title("Muted Apps")
        self.win.configure(bg=BG)
        self.win.geometry("560x560")
        self.win.minsize(460, 380)
        self.win.protocol("WM_DELETE_WINDOW", lambda: set_mode(False))
        self.win.withdraw()

        tk.Label(self.win, text="MUTED APPS", font=("Segoe UI", 18, "bold"), bg=BG, fg=ACCENT).pack(pady=(14, 0))
        tk.Label(self.win, text="Created by OG", font=("Segoe UI", 9), bg=BG, fg=SUBTLE).pack()

        body = tk.Frame(self.win, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=10)
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        bar = tk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.list = tk.Frame(self.canvas, bg=BG)
        self.list.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        list_id = self.canvas.create_window((0, 0), window=self.list, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(list_id, width=e.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.win.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-e.delta // 120, "units"))

        move = tk.Frame(self.win, bg=BG)
        move.pack(fill="x", padx=14, pady=(0, 8))
        tk.Label(move, text="Move app #", font=("Segoe UI", 10), bg=BG, fg=FG).pack(side="left")
        self.old_entry = tk.Entry(move, width=5, font=("Segoe UI", 10), bg=PANEL, fg=FG, insertbackground=FG, relief="flat")
        self.old_entry.pack(side="left", padx=4, ipady=3)
        tk.Label(move, text="to #", font=("Segoe UI", 10), bg=BG, fg=FG).pack(side="left")
        self.new_entry = tk.Entry(move, width=5, font=("Segoe UI", 10), bg=PANEL, fg=FG, insertbackground=FG, relief="flat")
        self.new_entry.pack(side="left", padx=4, ipady=3)
        self.button(move, "Apply (F8)", self.apply_move).pack(side="left", padx=6)
        self.old_entry.bind("<Return>", lambda e: self.new_entry.focus_set())
        self.new_entry.bind("<Return>", lambda e: self.apply_move())

        buttons = tk.Frame(self.win, bg=BG)
        buttons.pack(fill="x", padx=14, pady=(0, 6))
        self.button(buttons, "Refresh (F9)", refresh).pack(side="left")
        self.button(buttons, "Next page (ALT+0)", next_page).pack(side="left", padx=6)
        self.button(buttons, "Terminal (F7)", lambda: set_mode(False)).pack(side="right")

        tk.Label(self.win, text="ALT+1-9 Mute/Unmute on the active page   ESC+ALT Exit",
                 font=("Segoe UI", 9), bg=BG, fg=SUBTLE).pack()
        self.status = tk.Label(self.win, font=("Segoe UI", 10), bg=BG, fg=FG, anchor="w")
        self.status.pack(fill="x", padx=14, pady=(4, 12))

    def button(self, parent, text, command, bg=PANEL, width=None):
        return tk.Button(parent, text=text, command=command, bg=bg, fg="white", activebackground=ACCENT,
                         activeforeground="black", relief="flat", font=("Segoe UI", 10, "bold"),
                         padx=10, pady=3, width=width, cursor="hand2")

    def refresh(self):
        with draw_lock:
            rows = [(idx, sessions_name[idx], sessions_map[idx].GetMute()) for idx in sorted(sessions_map)]
            pages = page_count()

        for w in self.list.winfo_children():
            w.destroy()
        if not rows:
            tk.Label(self.list, text="No audio apps found. Play some audio and press F9.",
                     font=("Segoe UI", 10), bg=BG, fg=SUBTLE).pack(pady=20)

        for page in range(pages):
            apps = [r for r in rows if (r[0] - 1) // PAGE_SIZE == page]
            if not apps and page != current_page:
                continue
            active = page == current_page
            head = f"Page {page + 1}/{pages}" + ("   <- active (ALT+1-9)" if active else "")
            tk.Label(self.list, text=head, font=("Segoe UI", 10, "bold"), bg=BG,
                     fg=ACCENT if active else SUBTLE, anchor="w").pack(fill="x", pady=(8, 2))
            for idx, name, muted in apps:
                slot = (idx - 1) % PAGE_SIZE + 1
                row = tk.Frame(self.list, bg=PANEL)
                row.pack(fill="x", pady=2)
                tk.Label(row, text=f"{idx:>3}.", font=("Consolas", 10), bg=PANEL, fg=SUBTLE, width=4).pack(side="left", padx=(6, 0), pady=6)
                tk.Label(row, text=f"ALT+{slot}", font=("Consolas", 10, "bold"), bg=PANEL,
                         fg=FG if active else SUBTLE, width=6).pack(side="left")
                tk.Label(row, text=name, font=("Segoe UI", 10), bg=PANEL, fg=FG, anchor="w").pack(side="left", fill="x", expand=True)
                self.button(row, "MUTED" if muted else "ON", lambda i=idx: toggle_index(i),
                            bg=MUTED_BG if muted else ON_BG, width=7).pack(side="right", padx=6, pady=4)
            if not apps:
                tk.Label(self.list, text="(empty)", font=("Segoe UI", 9), bg=BG, fg=SUBTLE, anchor="w").pack(fill="x", padx=8)

        self.status.config(text=f"Last action: {status}")

    def apply_move(self):
        try:
            msg = reassign_index(int(self.old_entry.get()), int(self.new_entry.get()))
            self.old_entry.delete(0, "end")
            self.new_entry.delete(0, "end")
        except ValueError:
            msg = "Reassign cancelled - please enter valid numbers."
        self.win.focus_set()
        set_status(msg)

    def focus_move(self):
        self.win.lift()
        self.win.focus_force()
        self.old_entry.focus_set()
        self.old_entry.select_range(0, "end")

def show_popup(text, color, duration=1500):
    ui_queue.put(("popup", text, color, duration))

def process_ui_queue(popup):
    try:
        while True:
            msg = ui_queue.get_nowait()
            kind = msg[0]
            if kind == "exit":
                show_console(True)
                popup.root.destroy()
                return
            elif kind == "popup":
                popup.show(*msg[1:])
            elif kind == "gui":
                app_window.refresh()
            elif kind == "toggle_mode":
                set_mode(not gui_mode)
            elif kind == "focus_move":
                app_window.focus_move()
    except queue.Empty:
        pass
    popup.root.after(50, process_ui_queue, popup)

def set_mode(gui):
    global gui_mode
    gui_mode = gui
    if gui:
        os.system("cls")
        print(f"{CYAN} App window is open - press F7 to come back here.{RESET}")
        show_console(False)
        app_window.win.deiconify()
        app_window.win.lift()
        app_window.win.focus_force()
        set_status("Switched to app window")
    else:
        app_window.win.withdraw()
        show_console(True)
        set_status("Switched to terminal")

def page_count():
    if not sessions_map:
        return 1
    return (max(sessions_map) - 1) // PAGE_SIZE + 1

def mute_snapshot():
    try:
        return tuple((idx, sessions_map[idx].GetMute()) for idx in sorted(sessions_map))
    except Exception:
        return None

def watch_mutes(root):
    if not prompting:
        snap = mute_snapshot()
        if snap is not None and snap != last_snapshot:
            redraw()
    root.after(1000, watch_mutes, root)

def redraw():
    global last_snapshot
    if gui_mode:
        last_snapshot = mute_snapshot()
        ui_queue.put(("gui",))
        return
    if prompting:
        return
    with draw_lock:
        last_snapshot = mute_snapshot()
        draw_screen()

def draw_screen():
    os.system("cls")
    print(f"{CYAN}=============== MUTED APPS ==============={RESET}")
    print(f"{DIM}                Created by OG{RESET}\n")

    if not sessions_map:
        print("  No audio apps found. Play some audio and press F9.\n")

    for page in range(page_count()):
        apps = [page * PAGE_SIZE + slot for slot in range(1, PAGE_SIZE + 1)
                if page * PAGE_SIZE + slot in sessions_map]
        if not apps and page != current_page:
            continue
        marker = f"  {CYAN}<- active (ALT+1-9){RESET}" if page == current_page else ""
        print(f" Page {page + 1}/{page_count()}{marker}")
        for idx in apps:
            slot = (idx - 1) % PAGE_SIZE + 1
            state = f"{RED}MUTED{RESET}" if sessions_map[idx].GetMute() else f"{GREEN}ON{RESET}"
            print(f"   {idx:>3}. ALT+{slot}  {sessions_name[idx]:<28} {state}")
        if not apps:
            print(f"   {DIM}(empty){RESET}")
        print()

    print(f"{DIM} F9 Refresh   F8 Reassign   F7 App window   ALT+1-9 Mute/Unmute   ALT+0 Next page   ESC+ALT Exit{RESET}\n")
    print(f" Last action: {status}")

def set_status(msg):
    global status
    status = msg
    redraw()

def list_audio_apps():
    global current_page
    found = []
    for session in AudioUtilities.GetAllSessions():
        if session.Process and session.Process.name():
            volume = session._ctl.QueryInterface(ISimpleAudioVolume)
            found.append((session.Process.pid, session.Process.name(), volume))

    with draw_lock:
        old = {idx: (sessions_pid[idx], sessions_name[idx]) for idx in sessions_map}
        new_map, new_name, new_pid = {}, {}, {}

        def place(idx, app):
            found.remove(app)
            new_pid[idx], new_name[idx], new_map[idx] = app

        for idx, (pid, _) in old.items():
            app = next((a for a in found if a[0] == pid), None)
            if app:
                place(idx, app)
        for idx, (_, name) in old.items():
            if idx not in new_map:
                app = next((a for a in found if a[1] == name), None)
                if app:
                    place(idx, app)
        idx = 1
        for app in list(found):
            while idx in new_map:
                idx += 1
            place(idx, app)

        sessions_map.clear(); sessions_map.update(new_map)
        sessions_name.clear(); sessions_name.update(new_name)
        sessions_pid.clear(); sessions_pid.update(new_pid)
        if current_page >= page_count():
            current_page = 0

def refresh():
    list_audio_apps()
    set_status(f"Refreshed - {len(sessions_map)} app(s) found")

def next_page():
    global current_page
    current_page = (current_page + 1) % page_count()
    start = current_page * PAGE_SIZE
    lines = [f"Page {current_page + 1}/{page_count()}"]
    for slot in range(1, PAGE_SIZE + 1):
        idx = start + slot
        if idx in sessions_map:
            state = "muted" if sessions_map[idx].GetMute() else "on"
            lines.append(f"ALT+{slot}  {sessions_name[idx]}  ({state})")
    if len(lines) == 1:
        lines.append("(no apps on this page)")
    show_popup("\n".join(lines), "#1565c0", duration=3000)
    set_status(f"Switched to page {current_page + 1}")

def reassign_index(old_index, new_index):
    if old_index not in sessions_map:
        return f"No app at index {old_index}. Press F9 to refresh."
    if new_index < 1:
        return "New index must be 1 or higher."

    with draw_lock:
        if new_index in sessions_map:
            sessions_map[old_index], sessions_map[new_index] = sessions_map[new_index], sessions_map[old_index]
            sessions_name[old_index], sessions_name[new_index] = sessions_name[new_index], sessions_name[old_index]
            sessions_pid[old_index], sessions_pid[new_index] = sessions_pid[new_index], sessions_pid[old_index]
            return f"Swapped: [{old_index}] {sessions_name[old_index]} <-> [{new_index}] {sessions_name[new_index]}"
        sessions_map[new_index] = sessions_map.pop(old_index)
        sessions_name[new_index] = sessions_name.pop(old_index)
        sessions_pid[new_index] = sessions_pid.pop(old_index)
        return f"Moved {sessions_name[new_index]} to [{new_index}]"

def toggle_index(app_index):
    volume = sessions_map[app_index]
    current_mute = volume.GetMute()
    volume.SetMute(not current_mute, None)
    name = sessions_name[app_index]
    if current_mute:
        show_popup(f"UNMUTED  -  {name}", ON_BG)
        set_status(f"Unmuted {name}")
    else:
        show_popup(f"MUTED  -  {name}", MUTED_BG)
        set_status(f"Muted {name}")

def toggle_mute(slot):
    app_index = current_page * PAGE_SIZE + slot
    if app_index in sessions_map:
        toggle_index(app_index)
    else:
        show_popup(f"No app on Page {current_page + 1}, ALT+{slot}  (F9 to refresh)", "#555555")
        set_status(f"No app on page {current_page + 1}, ALT+{slot}. Press F9 to refresh.")

def clear_typed_keys():
    time.sleep(0.15)
    kernel32 = ctypes.windll.kernel32
    kernel32.FlushConsoleInputBuffer(kernel32.GetStdHandle(-10))

def prompt_reassign():
    global prompting
    if gui_mode:
        ui_queue.put(("focus_move",))
        return
    redraw()
    prompting = True
    print(f"\n{CYAN} --- Reassign Index ---{RESET}")
    clear_typed_keys()
    try:
        old = int(input("  Enter current index of the app: "))
        new = int(input("  Enter new index to assign it to: "))
        msg = reassign_index(old, new)
    except ValueError:
        msg = "Reassign cancelled - please enter valid numbers."
    prompting = False
    set_status(msg)

def main():
    global app_window
    popup = MutePopup()
    app_window = AppWindow(popup.root)
    refresh()

    keyboard.add_hotkey("f9", refresh)
    keyboard.add_hotkey("f8", prompt_reassign)
    keyboard.add_hotkey("f7", lambda: ui_queue.put(("toggle_mode",)))
    keyboard.add_hotkey("alt+0", next_page)
    for i in range(1, 10):
        keyboard.add_hotkey(f"alt+{i}", lambda idx=i: toggle_mute(idx))

    keyboard.add_hotkey("esc+alt", lambda: ui_queue.put(("exit",)))
    popup.root.after(50, process_ui_queue, popup)
    popup.root.after(1000, watch_mutes, popup.root)
    popup.root.mainloop()

if __name__ == "__main__":
    main()
