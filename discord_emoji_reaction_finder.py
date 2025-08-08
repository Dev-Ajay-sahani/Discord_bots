import requests
import time
import threading
import tkinter as tk
import webbrowser
from tkinter import scrolledtext, messagebox

# --- Global Variables ---
stop_flag = False
scan_thread = None
selected_channels = []



# --- GUI Functions ---
def log(message):
    log_area.insert(tk.END, message + "\n")
    log_area.see(tk.END)

def add_link(text, url):
    log_area.insert(tk.END, text)
    log_area.insert(tk.END, url + "\n", ("link", url))
    log_area.tag_bind("link", "<Button-1>", lambda e: webbrowser.open(url))
    log_area.see(tk.END)

def fetch_messages(channel_id, token, limit=100, before=None):
    headers = {"Authorization": token, "Content-Type": "application/json"}
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit={limit}"
    if before:
        url += f"&before={before}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        return response.json() if response.status_code == 200 else []
    except Exception as e:
        log(f"❌ Error fetching messages from {channel_id}: {e}")
        return []

def fetch_reaction_users(channel_id, message_id, emoji, token):
    headers = {"Authorization": token, "Content-Type": "application/json"}
    emoji_encoded = requests.utils.quote(emoji)
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages/{message_id}/reactions/{emoji_encoded}?limit=100"
    try:
        response = requests.get(url, headers=headers)
        return response.json() if response.status_code == 200 else []
    except Exception as e:
        log(f"❌ Error fetching reaction users: {e}")
        return []

def fetch_text_channels(guild_id, token):
    headers = {"Authorization": token}
    url = f"https://discord.com/api/v9/guilds/{guild_id}/channels"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return [ch for ch in response.json() if ch["type"] == 0]  # type 0 = text channel
        else:
            log(f"❌ Failed to fetch channels: {response.status_code} {response.text}")
            return []
    except Exception as e:
        log(f"❌ Error fetching channels: {e}")
        return []

def scan_channel(channel_id, guild_id, token, target_user_id, target_emoji):
    global stop_flag
    last_message_id = None
    scanned_count = 0

    while not stop_flag:
        messages = fetch_messages(channel_id, token, before=last_message_id)
        if not messages:
            break

        for msg in messages:
            if stop_flag:
                return False
            scanned_count += 1
            last_message_id = msg["id"]
            if "reactions" in msg:
                for reaction in msg["reactions"]:
                    emoji_name = reaction["emoji"]["name"]
                    emoji_id = reaction["emoji"].get("id")
                    if not emoji_id:
                        continue
                    full_emoji = f"{emoji_name}:{emoji_id}"
                    if full_emoji == target_emoji:
                        users = fetch_reaction_users(channel_id, msg["id"], full_emoji, token)
                        for user in users:
                            if user["id"] == target_user_id:
                                message_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{msg['id']}"
                                log(f"✅ User reacted with <:{emoji_name}:{emoji_id}>")
                                add_link("🔗 Message URL: ", message_url)
                                return True
        time.sleep(1)
    log(f"🔍 Scanned {scanned_count} messages in channel {channel_id}. No match.")
    return False

def start_scan():
    global stop_flag, scan_thread
    stop_flag = False

    token = token_entry.get().strip()
    guild_id = guild_entry.get().strip()
    channel_id = channel_entry.get().strip()
    target_user_id = user_entry.get().strip()
    target_emoji = emoji_entry.get().strip()

    if not all([token, guild_id, target_user_id, target_emoji]):
        messagebox.showwarning("Missing Fields", "Please fill in all fields except Channel ID (optional).")
        return

    start_button.config(state="disabled")
    stop_button.config(state="normal")
    log_area.delete('1.0', tk.END)

    def run():
        found = False
        if channel_id:
            found = scan_channel(channel_id, guild_id, token, target_user_id, target_emoji)
        elif selected_channels:
            for ch_id in selected_channels:
                if stop_flag:
                    break
                log(f"📂 Scanning selected channel: {ch_id}")
                if scan_channel(ch_id, guild_id, token, target_user_id, target_emoji):
                    found = True
                    break
        else:
            log("📡 No channel ID or selection, scanning all text channels...")
            channels = fetch_text_channels(guild_id, token)
            for ch in channels:
                if stop_flag:
                    break
                log(f"📂 Scanning channel: {ch['name']} ({ch['id']})")
                if scan_channel(ch['id'], guild_id, token, target_user_id, target_emoji):
                    found = True
                    break

        if not found and not stop_flag:
            log("❌ Reaction not found in any messages.")
        start_button.config(state="normal")
        stop_button.config(state="disabled")

    scan_thread = threading.Thread(target=run, daemon=True)
    scan_thread.start()



def stop_scan():
    global stop_flag
    stop_flag = True
    log("🛑 Scanning stopped by user.")
    start_button.config(state="normal")
    stop_button.config(state="disabled")

def open_channel_selector():
    global selected_channels
    token = token_entry.get().strip()
    guild_id = guild_entry.get().strip()
    if not token or not guild_id:
        messagebox.showwarning("Missing Info", "Please enter both Token and Guild ID first.")
        return

    channels = fetch_text_channels(guild_id, token)
    if not channels:
        return

    selector = tk.Toplevel(root)
    selector.title("Select Channels")
    selector.geometry("400x400")
    selected_channels.clear()

    canvas = tk.Canvas(selector)
    scrollbar = tk.Scrollbar(selector, orient="vertical", command=canvas.yview)
    scroll_frame = tk.Frame(canvas)

    scroll_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    check_vars = {}

    for ch in channels:
        var = tk.BooleanVar()
        cb = tk.Checkbutton(scroll_frame, text=f"{ch['name']} ({ch['id']})", variable=var)
        cb.pack(anchor="w", padx=5, pady=2)
        check_vars[ch["id"]] = var

    def on_select():
        selected_channels.clear()
        for ch_id, var in check_vars.items():
            if var.get():
                selected_channels.append(ch_id)
        if selected_channels:
            channel_entry.delete(0, tk.END)
            channel_entry.insert(0, "")  # Clear single ID input
        log(f"✅ {len(selected_channels)} channel(s) selected for scanning.")
        selector.destroy()

    tk.Button(selector, text="Use Selected Channels", command=on_select).pack(pady=10)




# --- GUI Setup ---
root = tk.Tk()
root.title("Discord Reaction Finder")

frame = tk.Frame(root)
frame.pack(padx=10, pady=10)

tk.Label(frame, text="Bot Token:").grid(row=0, column=0, sticky="e")
token_entry = tk.Entry(frame, width=60, show="*")
token_entry.grid(row=0, column=1)

tk.Label(frame, text="Server ID (Guild ID):").grid(row=1, column=0, sticky="e")
guild_entry = tk.Entry(frame, width=60)
guild_entry.grid(row=1, column=1)

tk.Label(frame, text="Channel ID (optional):").grid(row=2, column=0, sticky="e")
channel_entry = tk.Entry(frame, width=40)
channel_entry.grid(row=2, column=1, sticky="w")

channel_button = tk.Button(frame, text="Pick Channel", command=open_channel_selector)
channel_button.grid(row=2, column=1, sticky="e", padx=5)

tk.Label(frame, text="Target User ID:").grid(row=3, column=0, sticky="e")
user_entry = tk.Entry(frame, width=60)
user_entry.grid(row=3, column=1)

tk.Label(frame, text="Target Emoji (name:id):").grid(row=4, column=0, sticky="e")
emoji_entry = tk.Entry(frame, width=60)
emoji_entry.grid(row=4, column=1)

start_button = tk.Button(root, text="Start Scan", command=start_scan)
start_button.pack(pady=5)

stop_button = tk.Button(root, text="Stop Scan", command=stop_scan, state="disabled")
stop_button.pack(pady=5)

log_area = scrolledtext.ScrolledText(root, width=100, height=25, wrap=tk.WORD)
log_area.pack(padx=10, pady=10)
log_area.tag_config("link", foreground="blue", underline=True)

root.mainloop()
