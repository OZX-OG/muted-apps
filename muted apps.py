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

sessions_map, sessions_name, sessions_pid = {}, {}, {}

PAGE_SIZE = 9
current_page = 0

status = "Ready"
prompting = False  
last_snapshot = None 
draw_lock = threading.Lock() 

popup_queue = queue.Queue()

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
        self.root.after(50, self.poll)

    def poll(self):
        try:
            while True:
                msg = popup_queue.get_nowait()
                if msg is None:
                    self.root.destroy()
                    return
                self.show(*msg)
        except queue.Empty:
            pass
        self.root.after(50, self.poll)

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

def show_popup(text, color, duration=1500):
    popup_queue.put((text, color, duration))

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

    print(f"{DIM} F9 Refresh   F8 Reassign   ALT+1-9 Mute/Unmute   ALT+0 Next page   ESC+ALT Exit{RESET}\n")
    print(f" Last action: {status}")

def set_status(msg):
    global status
    status = msg
    redraw()

def list_audio_apps():
    """Rescan audio apps. Apps still running keep their index (including ones moved
    with F8); new apps take the lowest free index; closed apps are dropped."""
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

        # same process still running -> same index
        for idx, (pid, _) in old.items():
            app = next((a for a in found if a[0] == pid), None)
            if app:
                place(idx, app)
        # app was restarted (new process, same name) -> same index
        for idx, (_, name) in old.items():
            if idx not in new_map:
                app = next((a for a in found if a[1] == name), None)
                if app:
                    place(idx, app)
        # brand-new apps -> lowest free index
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

    if new_index in sessions_map:
        sessions_map[old_index], sessions_map[new_index] = sessions_map[new_index], sessions_map[old_index]
        sessions_name[old_index], sessions_name[new_index] = sessions_name[new_index], sessions_name[old_index]
        sessions_pid[old_index], sessions_pid[new_index] = sessions_pid[new_index], sessions_pid[old_index]
        return f"Swapped: [{old_index}] {sessions_name[old_index]} <-> [{new_index}] {sessions_name[new_index]}"
    sessions_map[new_index] = sessions_map.pop(old_index)
    sessions_name[new_index] = sessions_name.pop(old_index)
    sessions_pid[new_index] = sessions_pid.pop(old_index)
    return f"Moved {sessions_name[new_index]} to [{new_index}]"

def toggle_mute(slot):
    app_index = current_page * PAGE_SIZE + slot
    if app_index in sessions_map:
        volume = sessions_map[app_index]
        current_mute = volume.GetMute()
        volume.SetMute(not current_mute, None)
        name = sessions_name[app_index]
        if current_mute:
            show_popup(f"UNMUTED  -  {name}", "#2e7d32")
            set_status(f"Unmuted {name}")
        else:
            show_popup(f"MUTED  -  {name}", "#c62828")
            set_status(f"Muted {name}")
    else:
        show_popup(f"No app on Page {current_page + 1}, ALT+{slot}  (F9 to refresh)", "#555555")
        set_status(f"No app on page {current_page + 1}, ALT+{slot}. Press F9 to refresh.")

def clear_typed_keys():
    time.sleep(0.15)  
    kernel32 = ctypes.windll.kernel32
    kernel32.FlushConsoleInputBuffer(kernel32.GetStdHandle(-10))  

def prompt_reassign():
    global prompting
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
    popup = MutePopup()
    refresh()

    keyboard.add_hotkey("f9", refresh)
    keyboard.add_hotkey("f8", prompt_reassign)
    keyboard.add_hotkey("alt+0", next_page)
    for i in range(1, 10):
        keyboard.add_hotkey(f"alt+{i}", lambda idx=i: toggle_mute(idx))

    keyboard.add_hotkey("esc+alt", lambda: popup_queue.put(None))
    popup.root.after(1000, watch_mutes, popup.root)
    popup.root.mainloop()

if __name__ == "__main__":
    main()
