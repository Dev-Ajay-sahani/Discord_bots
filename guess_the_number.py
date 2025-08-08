import requests
import time
import os
import random

# --- Config ---
TOKEN = ""  #tokens
CHANNEL_ID = ""
LOW = 250
HIGH = 500
MIN_DELAY = 1.1
MAX_DELAY = 1.2

# --- Setup ---
headers = {
    "Authorization": TOKEN,  # If using a bot token, add "Bot " prefix
    "Content-Type": "application/json"
}

def send_message(channel_id, content):
    url = f"https://discord.com/api/v9/channels/{channel_id}/messages"
    payload = {"content": content}

    while True:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"✅ Sent guess: {content}")
            return True
        elif response.status_code == 429:
            retry_after = response.json().get("retry_after", 1)
            print(f"⏳ Rate limited. Retrying after {retry_after} seconds...")
            time.sleep(retry_after)
        else:
            print(f"❌ Error {response.status_code}: {response.text}")
            return False

def hybrid_loop():
    for num in range(LOW, HIGH + 1):
        # Removed: if str(num)[-1] == "4":
        if send_message(CHANNEL_ID, str(num)):
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

if __name__ == "__main__":
    hybrid_loop()
