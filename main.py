#!/usr/bin/env python3
"""
Default behavior:
  - Performs GET to https://zoo0.pages.dev using User-Agent "Dart/3.8 (dart:io)"
  - Reads response headers and combines: x-request-id + x-payload + authorization + x-data
  - Base64-decodes + XOR-decrypts using key "k6kW8r#Tz3f;" to extract JSON -> baseUrl
  - Calls baseUrl/api/v1/auth/generate?server=1 and routes to appropriate handler

Domain-based routing:
  - If keyUrl contains "nanolinks", uses the nano handler
  - If keyUrl contains "arolinks", uses the aro handler
  - If keyUrl contains "lksfy", uses the lksfy handler

Flags:
  --ssl-bypass    : Disable SSL verification (requests.verify=False). Handy for Termux/testing.
  --debug         : Show debug/background traces.

If you want to target a different URL, set environment variable TARGET_URL (no CLI flags needed).
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import hashlib
import threading
import asyncio
from urllib.parse import urlparse, parse_qs, quote
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
last_link_time = {}

async def start_countdown(update, seconds=120):
    message = await update.message.reply_text("⏳ Please wait 2:00")

    for remaining in range(seconds, -1, -5):
        mins = remaining // 60
        secs = remaining % 60
        await message.edit_text(f"⏳ Please wait {mins:02d}:{secs:02d}")
        await asyncio.sleep(5)

    await message.edit_text("✅ You can now use the key in Sigma!")
try:
    import requests
except Exception:
    print("ERROR: missing dependency 'requests'. Install: pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    from Crypto.Cipher import AES
except Exception:
    print("WARNING: missing dependency 'pycryptodome'. Install: pip install pycryptodome", file=sys.stderr)
    print("         AES decryption for lksfy links will not work", file=sys.stderr)

# Colors (fallback gracefully)
try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
except Exception:
    class _C:
        RESET = ""; RED = ""; GREEN = ""; YELLOW = ""; CYAN = ""; MAGENTA = ""
    Fore = type("F", (), {"RED": _C.RED, "GREEN": _C.GREEN, "YELLOW": _C.YELLOW, "CYAN": _C.CYAN, "MAGENTA": _C.MAGENTA})
    Style = type("S", (), {"BRIGHT": "", "NORMAL": ""})

def err(msg): print(f"{Fore.RED}[ERROR]{Style.NORMAL} {msg}", file=sys.stderr)
def info(msg): print(f"{Fore.CYAN}[INFO]{Style.NORMAL} {msg}")
def ok(msg): print(f"{Fore.GREEN}[OK]{Style.NORMAL} {msg}")
def dbg(msg, on):
    if on:
        print(f"{Fore.MAGENTA}[DEBUG]{Style.NORMAL} {msg}")

def clear_line():
    """Clear the current line in terminal"""
    sys.stdout.write('\r' + ' ' * 80 + '\r')
    sys.stdout.flush()

def show_progress_animation(duration_seconds=180, fetched_key=None):
    """
    Display a SUPER animated progress experience with partial key reveals and ASCII art.
    """
    import random

    spinner_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    bar_length = 40
    start_time = time.time()

    # ASCII Art Collection
    rocket_frames = [
        f"""{Fore.CYAN}
        🚀
       /|\\
      / | \\
     /  |  \\
    /___|___\\
        |
       /|\\
      / | \\
    {Style.NORMAL}""",
        f"""{Fore.YELLOW}
        🚀
       /|\\
      / | \\
     /  |  \\
    /___|___\\
        |
       /|\\
      🔥🔥🔥
    {Style.NORMAL}""",
        f"""{Fore.RED}
        🚀
       /|\\
      / | \\
     /  |  \\
    /___|___\\
        |
      🔥🔥🔥
     🔥🔥🔥🔥🔥
    {Style.NORMAL}"""
    ]

    tom_jerry = [
        f"""{Fore.YELLOW}
    🐱 -----> 🐭
    Tom chasing Jerry...
    {Style.NORMAL}""",
        f"""{Fore.YELLOW}
         🐱 --> 🐭
    Almost got him!
    {Style.NORMAL}""",
        f"""{Fore.YELLOW}
              🐱💨 🐭
    So close!
    {Style.NORMAL}""",
        f"""{Fore.GREEN}
                   🐭 😎
              🐱💫
    Jerry escaped again!
    {Style.NORMAL}"""
    ]

    loading_cat = [
        f"{Fore.YELLOW}(=^･ω･^=) Loading...{Style.NORMAL}",
        f"{Fore.YELLOW}(=^･ｪ･^=) Still loading...{Style.NORMAL}",
        f"{Fore.YELLOW}(=^-ω-^=) Almost there...{Style.NORMAL}",
        f"{Fore.YELLOW}(=^･∀･^=) Yay!{Style.NORMAL}"
    ]

    hacker_art = f"""{Fore.GREEN}
    ╔═══════════════════════════════════════╗
    ║  ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄   ║
    ║  █ ACCESSING SECURE DATABASE...  █   ║
    ║  █ ████████████░░░░░░░░░░░░░░░░  █   ║
    ║  █ DECRYPTING: ██████████░░░░░░  █   ║
    ║  ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀   ║
    ╚═══════════════════════════════════════╝
    {Style.NORMAL}"""

    # BIG BANNER explaining the 3-minute wait
    print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════════════╗
{Fore.CYAN}║{Fore.YELLOW}                                                                  {Fore.CYAN}║
{Fore.CYAN}║{Fore.YELLOW}  ██╗    ██╗ █████╗ ██╗████████╗    ██████╗    ███╗   ███╗██╗███╗   ██╗ {Fore.CYAN}║
{Fore.CYAN}║{Fore.YELLOW}  ██║    ██║██╔══██╗██║╚══██╔══╝    ╚════██╗   ████╗ ████║██║████╗  ██║ {Fore.CYAN}║
{Fore.CYAN}║{Fore.YELLOW}  ██║ █╗ ██║███████║██║   ██║        █████╔╝   ██╔████╔██║██║██╔██╗ ██║ {Fore.CYAN}║
{Fore.CYAN}║{Fore.YELLOW}  ██║███╗██║██╔══██║██║   ██║        ╚═══██╗   ██║╚██╔╝██║██║██║╚██╗██║ {Fore.CYAN}║
{Fore.CYAN}║{Fore.YELLOW}  ╚███╔███╔╝██║  ██║██║   ██║       ██████╔╝   ██║ ╚═╝ ██║██║██║ ╚████║ {Fore.CYAN}║
{Fore.CYAN}║{Fore.YELLOW}   ╚══╝╚══╝ ╚═╝  ╚═╝╚═╝   ╚═╝       ╚═════╝    ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝ {Fore.CYAN}║
{Fore.CYAN}║                                                                  ║
{Fore.CYAN}╠══════════════════════════════════════════════════════════════════╣
{Fore.CYAN}║{Fore.RED}                                                                  {Fore.CYAN}║
{Fore.CYAN}║{Fore.RED}   ⚠️  YOU MUST WAIT 3 MIN BEFORE PASTING KEY IN SIGMA APP!  ⚠️   {Fore.CYAN}║
{Fore.CYAN}║{Fore.RED}                                                                  {Fore.CYAN}║
{Fore.CYAN}║{Fore.GREEN}   🎮 SO TO KEEP YOU ENGAGED, I CREATED THIS COOL ANIMATION! 🎮  {Fore.CYAN}║
{Fore.CYAN}║{Fore.GREEN}                                                                  {Fore.CYAN}║
{Fore.CYAN}║{Fore.MAGENTA}              🚀 SIT BACK, RELAX & ENJOY THE SHOW! 🚀             {Fore.CYAN}║
{Fore.CYAN}║                                                                  ║
{Fore.CYAN}╚══════════════════════════════════════════════════════════════════╝{Style.NORMAL}
""")
    time.sleep(2)

    # Fake hacking steps with timing (in seconds)
    hacking_steps = [
        ("Initializing secure connection", 5),
        ("Connecting to proxy server", 12),
        ("Establishing encrypted tunnel", 20),
        ("Bypassing firewall layer 1/5", 30),
        ("Bypassing firewall layer 2/5", 45),
        ("Bypassing firewall layer 3/5", 60),
        ("Injecting payload packets", 75),
        ("Decrypting authentication tokens", 90),
        ("Bypassing firewall layer 4/5", 105),
        ("Accessing secure database", 120),
        ("Bypassing firewall layer 5/5", 135),
        ("Extracting encrypted key hash", 150),
        ("Cracking encryption layer 1/3", 160),
        ("Cracking encryption layer 2/3", 168),
        ("Cracking encryption layer 3/3", 175),
        ("Finalizing decryption", 178),
    ]

    print(f"\n{Fore.YELLOW}{'═'*70}")
    print(f"{Fore.GREEN}  🔐 SIGMA KEY GENERATOR v4.0 - Ultra Secure Mode")
    print(f"{Fore.YELLOW}{'═'*70}{Style.NORMAL}\n")

    current_step_idx = 0
    last_milestone = 0
    key_length = len(fetched_key) if fetched_key else 12

    try:
        while True:
            elapsed = time.time() - start_time
            if elapsed >= duration_seconds:
                break

            progress = elapsed / duration_seconds
            percentage = min(progress * 100, 100)

            # Check if we need to show a new hacking step
            if current_step_idx < len(hacking_steps):
                step_text, step_time = hacking_steps[current_step_idx]
                if elapsed >= step_time:
                    sys.stdout.write('\r' + ' ' * 80 + '\r')
                    sys.stdout.flush()
                    print(f"  {Fore.GREEN}[✓]{Style.NORMAL} {step_text}...")
                    current_step_idx += 1

            # ============ 25% MILESTONE ============
            if percentage >= 25 and last_milestone < 25:
                last_milestone = 25
                sys.stdout.write('\r' + ' ' * 80 + '\r')
                print(f"\n  {Fore.CYAN}🎉 25% Complete! Keep going...{Style.NORMAL}")

                # Show rocket animation
                for frame in rocket_frames:
                    print(frame)
                    time.sleep(0.5)

                # Reveal first 4 characters of key
                if fetched_key and len(fetched_key) >= 4:
                    partial_key = fetched_key[:4]
                    print(f"\n  {Fore.GREEN}╔════════════════════════════════════════════════╗")
                    print(f"  {Fore.GREEN}║  🔓 GREAT! I found 4 letters from your key!    ║")
                    print(f"  {Fore.GREEN}║                                                ║")
                    print(f"  {Fore.GREEN}║     Your key starts with: {Fore.YELLOW}{partial_key}{Fore.GREEN}...            ║")
                    print(f"  {Fore.GREEN}╚════════════════════════════════════════════════╝{Style.NORMAL}")
                    time.sleep(4)  # Show for 4 seconds
                    print(f"\n  {Fore.MAGENTA}(Key hidden... keep watching!){Style.NORMAL}\n")

            # ============ 50% MILESTONE ============
            if percentage >= 50 and last_milestone < 50:
                last_milestone = 50
                sys.stdout.write('\r' + ' ' * 80 + '\r')
                print(f"\n  {Fore.YELLOW}🔥 50% Halfway there! You're doing great!{Style.NORMAL}")

                # Tom & Jerry animation
                print(f"\n  {Fore.CYAN}--- Entertainment Break! ---{Style.NORMAL}")
                for frame in tom_jerry:
                    print(frame)
                    time.sleep(0.8)

                # Reveal first 8 characters of key
                if fetched_key and len(fetched_key) >= 8:
                    partial_key = fetched_key[:8]
                    print(f"\n  {Fore.GREEN}╔════════════════════════════════════════════════╗")
                    print(f"  {Fore.GREEN}║  🔓 AMAZING! Found 8 letters from your key!    ║")
                    print(f"  {Fore.GREEN}║                                                ║")
                    print(f"  {Fore.GREEN}║     Key so far: {Fore.YELLOW}{partial_key}{Fore.GREEN}...                 ║")
                    print(f"  {Fore.GREEN}╚════════════════════════════════════════════════╝{Style.NORMAL}")
                    time.sleep(4)
                    print(f"\n  {Fore.MAGENTA}(Key hidden... almost there!){Style.NORMAL}\n")

            # ============ 75% MILESTONE ============
            if percentage >= 75 and last_milestone < 75:
                last_milestone = 75
                sys.stdout.write('\r' + ' ' * 80 + '\r')
                print(f"\n  {Fore.GREEN}⚡ 75% Almost done! Final stretch!{Style.NORMAL}")

                # Hacker art
                print(hacker_art)

                # Show cat animation
                for cat in loading_cat:
                    print(f"  {cat}")
                    time.sleep(0.5)

                # Reveal first 10 characters of key
                if fetched_key and len(fetched_key) >= 10:
                    partial_key = fetched_key[:10]
                    print(f"\n  {Fore.GREEN}╔════════════════════════════════════════════════╗")
                    print(f"  {Fore.GREEN}║  🔓 SO CLOSE! Found 10 letters from your key!  ║")
                    print(f"  {Fore.GREEN}║                                                ║")
                    print(f"  {Fore.GREEN}║     Key so far: {Fore.YELLOW}{partial_key}{Fore.GREEN}...               ║")
                    print(f"  {Fore.GREEN}╚════════════════════════════════════════════════╝{Style.NORMAL}")
                    time.sleep(4)
                    print(f"\n  {Fore.MAGENTA}(Key hidden... just a bit more!){Style.NORMAL}\n")

            # Calculate bar
            filled_length = int(bar_length * progress)
            empty_length = bar_length - filled_length
            bar_filled = '█' * filled_length
            bar_empty = '░' * empty_length

            # Spinner
            spinner_idx = int(elapsed * 10) % len(spinner_chars)
            spinner = spinner_chars[spinner_idx]

            # Time
            remaining = duration_seconds - elapsed
            mins_remaining = int(remaining // 60)
            secs_remaining = int(remaining % 60)
            mins_elapsed = int(elapsed // 60)
            secs_elapsed = int(elapsed % 60)

            # Color based on progress
            if percentage < 33:
                bar_color = Fore.RED
            elif percentage < 66:
                bar_color = Fore.YELLOW
            else:
                bar_color = Fore.GREEN

            # Build and show progress bar
            progress_line = (
                f"  {Fore.CYAN}{spinner} {bar_color}[{bar_filled}{bar_empty}]{Style.NORMAL} "
                f"{Fore.YELLOW}{percentage:5.1f}%{Style.NORMAL} "
                f"{Fore.CYAN}⏱️{mins_elapsed:02d}:{secs_elapsed:02d} "
                f"⏳{mins_remaining:02d}:{secs_remaining:02d}{Style.NORMAL}"
            )

            sys.stdout.write(f'\r{progress_line}')
            sys.stdout.flush()

            time.sleep(0.5)

        # ============ 100% COMPLETION ============
        sys.stdout.write('\r' + ' ' * 80 + '\r')
        print(f"\n  {Fore.GREEN}🎊 100% SUCCESS! Key decryption complete!{Style.NORMAL}")

        bar_filled = '█' * bar_length
        print(f"\n  {Fore.GREEN}✓ [{bar_filled}] 100.0% | Complete!{Style.NORMAL}")

        # Final rocket launch celebration
        print(f"""
{Fore.GREEN}
    ╔══════════════════════════════════════════════════╗
    ║                                                  ║
    ║   🎉🎊🎉 CONGRATULATIONS! 🎉🎊🎉                ║
    ║                                                  ║
    ║       YOUR KEY HAS BEEN FULLY DECRYPTED!        ║
    ║                                                  ║
    ║   🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀         ║
    ║                                                  ║
    ╚══════════════════════════════════════════════════╝
{Style.NORMAL}""")

        print(f"\n{Fore.GREEN}{'═'*70}")
        print(f"{Fore.GREEN}  ✅ KEY GENERATION COMPLETE!")
        print(f"{Fore.GREEN}{'═'*70}{Style.NORMAL}\n")

    except KeyboardInterrupt:
        print(f"\n{Fore.RED}Progress interrupted by user.{Style.NORMAL}")
        raise


def reveal_key_dramatically(key):
    """
    Reveal the key character by character with dramatic effect
    """
    import random

    if not key:
        return

    scramble_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*"

    print(f"\n{Fore.CYAN}{'═'*60}")
    print(f"{Fore.YELLOW}  🔓 DECRYPTING YOUR KEY...")
    print(f"{Fore.CYAN}{'═'*60}\n")

    revealed = ['_'] * len(key)

    # Scramble effect before reveal
    print(f"  {Fore.RED}Initializing key decryption sequence...{Style.NORMAL}")
    time.sleep(0.5)

    for i in range(len(key)):
        # Show scrambling effect for this position
        for _ in range(5):  # 5 random chars before revealing
            revealed[i] = random.choice(scramble_chars)
            display_key = ''.join(revealed)
            sys.stdout.write(f"\r  {Fore.YELLOW}🔑 KEY: {Fore.CYAN}{display_key}{Style.NORMAL}  ")
            sys.stdout.flush()
            time.sleep(0.05)

        # Reveal the actual character
        revealed[i] = key[i]
        display_key = ''.join(revealed)
        sys.stdout.write(f"\r  {Fore.YELLOW}🔑 KEY: {Fore.GREEN}{display_key}{Style.NORMAL}  ")
        sys.stdout.flush()
        time.sleep(0.1)

    print()  # New line after reveal

    # Final celebration
    time.sleep(0.3)
    print(f"\n{Fore.GREEN}{'═'*60}")
    print(f"{Fore.GREEN}  🎉 DECRYPTION SUCCESSFUL!")
    print(f"{Fore.GREEN}{'═'*60}")
    print(f"\n  {Fore.YELLOW}╔{'═'*50}╗")
    print(f"  {Fore.YELLOW}║{Fore.GREEN}  🔑 YOUR KEY: {key:^32} {Fore.YELLOW}║")
    print(f"  {Fore.YELLOW}╚{'═'*50}╝\n")

    # Copy hint
    print(f"  {Fore.CYAN}💡 Tip: Copy this key and use it in the Sigma app!{Style.NORMAL}\n")

# default target host
DEFAULT_TARGET = "https://zoo0.pages.dev"
DEFAULT_USER_AGENT = "Dart/3.8 (dart:io)"
KEY = "k6kW8r#Tz3f;"

HEADER_NAMES = ("x-request-id", "x-payload", "authorization", "x-data")
def get_initial_response_headers(target_url, user_agent, verify, debug):
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    dbg(f"GET {target_url} (verify={verify})", debug)
    try:
        resp = session.get(target_url, timeout=25, verify=verify, allow_redirects=True)
        dbg(f"Status {resp.status_code}", debug)
    except Exception as e:
        raise RuntimeError(f"Initial GET failed: {e}")
    return resp.headers, resp

def build_combined(headers, debug):
    parts = []
    missing = []
    for hn in HEADER_NAMES:
        val = None
        # headers is case-insensitive in requests but iterate for safety
        for k, v in headers.items():
            if k.lower() == hn.lower():
                val = v.strip()
                break
        if val is None:
            missing.append(hn)
            parts.append("")  # preserve order
        else:
            dbg(f"Found header {hn} (len={len(val)})", debug)
            parts.append(val)
    combined = "".join(parts)
    dbg(f"Combined length: {len(combined)}", debug)
    return combined, missing

def decode_b64_xor(combined_b64: str, xor_key: bytes, debug: bool=False) -> str:
    if not combined_b64:
        raise ValueError("Combined base64 string empty")
    try:
        raw = base64.b64decode(combined_b64)
    except Exception as e:
        raise ValueError(f"Base64 decode failed: {e}")
    dbg(f"Decoded bytes: {len(raw)}", debug)
    if not xor_key:
        raise ValueError("XOR key empty")
    out = bytearray(len(raw))
    for i, b in enumerate(raw):
        out[i] = b ^ xor_key[i % len(xor_key)]
    # try utf-8
    try:
        text = out.decode("utf-8")
        dbg("Decoded to UTF-8", debug)
        return text
    except UnicodeDecodeError:
        dbg("UTF-8 failed; trying to extract JSON substring", debug)
        txt = out.decode("latin1", errors="ignore")
        start = txt.find("{")
        end = txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            return txt[start:end+1]
        raise ValueError("Decoded bytes not valid UTF-8 and no JSON substring found")

def extract_baseurl(decoded_text: str, debug: bool=False) -> str:
    dbg(f"Decoded preview: {decoded_text[:400]}", debug)
    try:
        obj = json.loads(decoded_text)
    except Exception as e:
        dbg("JSON parse failed; extracting block", debug)
        start = decoded_text.find("{")
        end = decoded_text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"JSON parse failed: {e}")
        obj = json.loads(decoded_text[start:end+1])
    if not isinstance(obj, dict):
        raise ValueError("Decoded JSON not an object")
    for k in ("baseUrl", "baseurl", "base_url"):
        if k in obj:
            return obj[k]
    raise ValueError("'baseUrl' not found in decoded JSON")

def fetch_key_flow(baseurl: str, verify: bool, debug: bool, user_agent: str = None) -> tuple:
    session = requests.Session()
    if user_agent:
        session.headers.update({"User-Agent": user_agent})
    else:
        session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; Python script)"})

    url1 = baseurl.rstrip("/") + "/api/v1/auth/generate?server=1"
    dbg(f"Request1 -> {url1}", debug)
    try:
        r1 = session.get(url1, timeout=30, verify=verify)
        dbg(f"Request1 status: {r1.status_code}", debug)
        r1.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Request 1 failed: {e}")

    try:
        json1 = r1.json()
        dbg(f"JSON1 preview: {json.dumps(json1)[:800]}", debug)
    except Exception as e:
        raise RuntimeError(f"Response1 not JSON: {e}")

    try:
        key_url = json1["data"]["keyUrl"]
       # key_url = "https://lksfy.com/8TRBMLM29A"
    except Exception as e:
        raise RuntimeError(f"keyUrl missing in response1 JSON: {e}")

    info(f"keyUrl: {key_url}")

    # Domain-based routing logic
    # Check for Telegram URL first
    if "t.me" in key_url or "telegram" in key_url.lower():
        info("Detected Telegram URL, using Telegram handler")
        return handle_telegram_url(key_url, session, verify, debug)
    elif "nanolinks" in key_url:
        info("Detected nanolinks domain, using nano handler")
        return handle_nano_links(key_url, session, verify, debug)
    elif "arolinks" in key_url:
        info("Detected arolinks domain, using aro handler")
        return handle_aro_links(key_url, session, verify, debug)
    elif "lksfy" in key_url:
        info("Detected lksfy domain, using lksfy handler")
        return handle_lksfy(key_url, session, verify, debug)
    else:
        # Fallback to nano handler as default
        info("Unknown domain, using nano handler as fallback")
        return handle_nano_links(key_url, session, verify, debug)


def handle_telegram_url(key_url, session, verify, debug):
    """
    Handler for Telegram bot URLs
    Extracts key from URLs like: https://t.me/sigma_keygen_bot?start=verify_47671A68130D
    The key is the part after 'verify_' in the start parameter
    """
    info("Using Telegram URL handler...")

    # Parse the URL
    parsed = urlparse(key_url)
    query_params = parse_qs(parsed.query)

    # Get the 'start' parameter
    start_param = query_params.get('start', [None])[0]

    if start_param is None:
        # Try to extract from the path if it's a direct link format
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[0].endswith("bot"):
            start_param = path_parts[-1] if path_parts[-1] != path_parts[0] else None

    dbg(f"Start parameter: {start_param}", debug)

    if start_param is None:
        return None, key_url, RuntimeError("No 'start' parameter found in Telegram URL")

    # Check if the start parameter contains 'verify_'
    if start_param.startswith("verify_"):
        # Extract the key after 'verify_'
        key = start_param[7:]  # Remove 'verify_' prefix (7 characters)
        return key, None, None

    elif start_param == "direct":
        # This means the API wants user to interact with the Telegram bot first
        info("[WARNING] The API returned 'start=direct' which means you need to:")
        info("   1. Open the Telegram bot: https://t.me/sigma_keygen_bot")
        info("   2. Send /start or /getkey command")
        info("   3. Follow the bot instructions to get your key")
        info("   4. The key will be in format: verify_XXXXXXXXXXXX")
        return None, key_url, RuntimeError("Manual Telegram bot interaction required. See instructions above.")

    else:
        # Try to extract key from other formats (e.g., start=XXXXXXXXXXXX)
        # Check if it looks like a hexadecimal key (alphanumeric, typically 12 chars)
        if re.match(r'^[A-Fa-f0-9]{10,14}$', start_param):
            return start_param, None, None
        else:
            return None, key_url, RuntimeError(f"Unknown start parameter format: {start_param}")


def handle_nano_links(key_url, session, verify, debug):
    """
    Handler for nanolinks.in URLs
    Process:
    1. Extract ID from the URL
    2. Make GET request to https://nano.tackledsoul.com/includes/open.php?id={extracted_id} with cookies
    3. Follow redirect to http://sharedisklinks.com/{new_id} and extract new ID
    4. Make request to https://vi-music.app/includes/open.php?id={new_id} with cookies
    5. Follow redirect to https://generateed.pages.dev/?key={key} and extract key
    """
    info("Using nanolinks handler...")

    # Extract ID from the URL
    parsed = urlparse(key_url)
    extracted_id = parsed.path.strip("/").split("/")[-1]
    info(f"Extracted ID from URL: {extracted_id}")

    # First request with extracted ID
    first_url = f"https://nano.tackledsoul.com/includes/open.php?id={extracted_id}"
    cookies = {
        "tp": extracted_id,
        "open": extracted_id
    }

    dbg(f"Nanolinks request 1 -> {first_url}", debug)
    try:
        # Don't follow redirects automatically so we can capture the redirect URL
        r1 = session.get(first_url, cookies=cookies, timeout=30, verify=verify, allow_redirects=False)
        dbg(f"Nanolinks request 1 status: {r1.status_code}", debug)

        if r1.status_code in (301, 302, 303, 307, 308):
            redirect_url = r1.headers.get('Location')
            dbg(f"Redirect URL: {redirect_url}", debug)

            # Extract new ID from redirect URL
            parsed = urlparse(redirect_url)
            new_id = parsed.path.strip("/").split("/")[-1]
            info(f"Extracted new ID: {new_id}")

            # Second request with new ID
            second_url = f"https://vi-music.app/includes/open.php?id={new_id}"
            new_cookies = {
                "tp": new_id,
                "open": new_id
            }

            dbg(f"Nanolinks request 2 -> {second_url}", debug)
            r2 = session.get(second_url, cookies=new_cookies, timeout=30, verify=verify, allow_redirects=False)
            dbg(f"Nanolinks request 2 status: {r2.status_code}", debug)

            if r2.status_code in (301, 302, 303, 307, 308):
                final_redirect = r2.headers.get('Location')
                dbg(f"Final redirect URL: {final_redirect}", debug)

                # Extract key from final redirect URL
                parsed = urlparse(final_redirect)
                key = parse_qs(parsed.query).get("key", [None])[0]

                if key:
                    return key, None, None
                else:
                    return None, key_url, RuntimeError("Could not extract 'key' parameter from final redirect URL")
            else:
                return None, key_url, RuntimeError(f"Second request did not redirect as expected: {r2.status_code}")
        else:
            return None, key_url, RuntimeError(f"First request did not redirect as expected: {r1.status_code}")
    except Exception as e:
        return None, key_url, RuntimeError(f"Nanolinks handler failed: {e}")

def handle_aro_links(key_url, session, verify, debug):
    """
    Handler for arolinks.com URLs
    """
    info("Using arolinks handler...")

    # Extract the identifier from the URL
    parsed = urlparse(key_url)
    identifier = parsed.path.strip("/").split("/")[-1]
    info(f"Extracted identifier: {identifier}")

    # Make initial request
    dbg(f"Arolinks request 1 -> {key_url}", debug)
    try:
        response = session.get(key_url, timeout=30, verify=verify)
        dbg(f"Arolinks request 1 status: {response.status_code}", debug)

        if response.status_code == 200:
            # Extract the redirect URL from the response
            redirect_url_match = re.search(r'window\.location\.href = "([^"]+)"', response.text)

            if not redirect_url_match:
                # Try to find it in the <a> tag
                redirect_url_match = re.search(r'<a href="([^"]+)"', response.text)

            if redirect_url_match:
                redirect_url = redirect_url_match.group(1)
                dbg(f"Found redirect URL: {redirect_url}", debug)

                # Update headers for the second request
                updated_headers = {
                    "cookie": f"gt_uc_={identifier}",
                    "referer": redirect_url
                }

                # Make the second request
                dbg(f"Arolinks request 2 -> {key_url} with updated headers", debug)
                second_response = session.get(key_url, headers=updated_headers, timeout=30, verify=verify)
                dbg(f"Arolinks request 2 status: {second_response.status_code}", debug)

                if second_response.status_code == 200:
                    # Extract the final URL with the key
                    final_url_match = re.search(r'nofollow noopener noreferrer" href="(https?://[^"]+key=[^"&]+[^"]*)"', second_response.text)
                    final_url_match2 = re.search(r'nofollow noopener noreferrer" href="(https?://[^"]+code=[^"&]+[^"]*)"', second_response.text)

                    if final_url_match:
                        final_url = final_url_match.group(1)
                        dbg(f"Found final URL: {final_url}", debug)
                        key_match = re.search(r'key=([^&"]+)', final_url)
                        if key_match:
                            key = key_match.group(1)
                            return key, None, None
                    elif final_url_match2:
                        final_url = final_url_match2.group(1)
                        code_match = re.search(r'code=([^&"]+)', final_url)
                        if code_match:
                            key = code_match.group(1)
                            return key, None, None

                    return None, key_url, RuntimeError("Final URL with key/code not found in the second response")
                else:
                    return None, key_url, RuntimeError(f"Second request failed with status code: {second_response.status_code}")
            else:
                return None, key_url, RuntimeError("Redirect URL not found in the initial response")
        else:
            return None, key_url, RuntimeError(f"Initial request failed with status code: {response.status_code}")
    except Exception as e:
        return None, key_url, RuntimeError(f"Arolinks handler failed: {e}")


def decrypt(chipertext: str, alias: str, debug: bool=False) -> str:
    try:
        key_source = "sDye71jNq5" + alias
        iv_source = "7M9u8DG4X" + alias
        key_hash = hashlib.sha256(key_source.encode("utf-8")).hexdigest()
        iv_hash = hashlib.sha256(iv_source.encode("utf-8")).hexdigest()
        key_bytes = key_hash[:32].encode("utf-8")  # 32 bytes -> AES-256
        iv_bytes = iv_hash[:16].encode("utf-8")    # 16 bytes -> IV
        ciphertext = base64.b64decode(base64.b64decode(chipertext)) # Decoding base64 twice
        cipher = AES.new(key_bytes, AES.MODE_CBC, iv=iv_bytes)
        decrypted = cipher.decrypt(ciphertext)
        return decrypted.decode("utf-8")
    except Exception as e:
        dbg(f"Decryption error: {e}", debug)
        return None

def extract_form_data(html_content):
    # Extract _csrfToken
    csrf_token_match = re.search(r'name="_csrfToken"[^>]*value="([^"]+)"', html_content)
    csrf_token = csrf_token_match.group(1) if csrf_token_match else ""

    # Extract ad_form_data
    ad_form_data_match = re.search(r'name="ad_form_data"[^>]*value="([^"]+)"', html_content)
    ad_form_data = ad_form_data_match.group(1) if ad_form_data_match else ""

    # Extract Token fields
    token_fields_match = re.search(r'name="_Token\[fields\]"[^>]*value="([^"]+)"', html_content)
    token_fields = token_fields_match.group(1) if token_fields_match else ""

    # Extract Token unlocked
    token_unlocked_match = re.search(r'name="_Token\[unlocked\]"[^>]*value="([^"]+)"', html_content)
    token_unlocked = token_unlocked_match.group(1) if token_unlocked_match else ""

    # Extract form action
    action_match = re.search(r'action="([^"]+)"', html_content)
    action = action_match.group(1) if action_match else ""

    return {
        "csrf_token": csrf_token,
        "ad_form_data": ad_form_data,
        "token_fields": token_fields,
        "token_unlocked": token_unlocked,
        "action": action
    }

def handle_lksfy(key_url, session, verify, debug):
    """
    Handler for lksfy.com URLs
    """
    info("Using lksfy handler...")

    # Extract the alias from the URL
    parsed = urlparse(key_url)
    alias = parsed.path.strip("/").split("/")[-1]
    info(f"Extracted alias: {alias}")

    # Make initial request
    dbg(f"Lksfy request 1 -> {key_url}", debug)
    try:
        # First get the redirect
        response = session.get(key_url, headers={"referer": key_url}, timeout=30, verify=verify, allow_redirects=False)
        dbg(f"Lksfy request 1 status: {response.status_code}", debug)

        if response.status_code in (301, 302, 303, 307, 308):
            redirect_url = response.headers.get('Location')
            dbg(f"Redirect URL: {redirect_url}", debug)

            # Now make the second request with referer
            headers = {"referer": redirect_url}
            dbg(f"Lksfy request 2 -> {key_url} with referer", debug)
            second_response = session.get(key_url, headers=headers, timeout=30, verify=verify)
            dbg(f"Lksfy request 2 status: {second_response.status_code}", debug)

            if second_response.status_code == 200:
                # Extract the base64 value from HTML
                base64_match = re.search(r'var base64 = \'([^\']+)\'', second_response.text)
                if base64_match:
                    base64_value = base64_match.group(1)
                    dbg(f"Found base64 value: {base64_value[:20]}...", debug)

                    # Decrypt the base64 value
                    decrypted_html = decrypt(base64_value, alias, debug)
                    if decrypted_html:
                        dbg("Successfully decrypted HTML form data", debug)

                        # Extract form data
                        form_data = extract_form_data(decrypted_html)

                        # Prepare POST request
                        post_url = f"https://lksfy.com{form_data['action']}"

                        post_headers = {
                            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                            "referer": "https://lksfy.com/",
                            "cookie": f"csrfToken={form_data['csrf_token']}",
                            "x-requested-with": "XMLHttpRequest"
                        }

                        # Manually build the POST body with individually URL-encoded values
                        post_body = (
                            f"_method=POST"
                            f"&_csrfToken={quote(form_data['csrf_token'])}"
                            f"&ad_form_data={quote(form_data['ad_form_data'])}"
                            f"&_Token%5Bfields%5D={form_data['token_fields']}"
                            f"&_Token%5Bunlocked%5D={quote(form_data['token_unlocked'])}"
                        )

                        dbg(f"POST body: {post_body[:100]}...", debug)

                        # Wait to prevent rate limiting
                        info("Waiting for 5 seconds to prevent bad request error")
                        time.sleep(5)

                        dbg(f"Lksfy request 3 -> {post_url} (POST)", debug)
                        post_response = session.post(post_url, headers=post_headers, data=post_body, timeout=30, verify=verify)
                        dbg(f"Lksfy request 3 status: {post_response.status_code}", debug)

                        if post_response.status_code == 200:
                            try:
                                json_response = post_response.json()
                                if json_response.get("status") == "success":
                                    encrypted_url = json_response.get("url")
                                    dbg(f"Got encrypted URL: {encrypted_url[:20]}...", debug)

                                    # Decrypt the URL
                                    decrypted_url = decrypt(encrypted_url, alias, debug)
                                    if decrypted_url:
                                        dbg(f"Final URL: {decrypted_url}", debug)

                                        # Extract the key - try multiple formats
                                        key_match = re.search(r'key=([^\&\s]+)', decrypted_url)
                                        if key_match:
                                            key = key_match.group(1).strip()
                                            return key, None, None

                                        # Try verify_ format (Telegram URLs)
                                        verify_match = re.search(r'verify_([A-Fa-f0-9]+)', decrypted_url)
                                        if verify_match:
                                            key = verify_match.group(1).strip()
                                            return key, None, None

                                        # Try start= parameter
                                        start_match = re.search(r'start=verify_([A-Fa-f0-9]+)', decrypted_url)
                                        if start_match:
                                            key = start_match.group(1).strip()
                                            return key, None, None

                                        return None, key_url, RuntimeError(f"Key not found in URL: {decrypted_url}")
                                    else:
                                        return None, key_url, RuntimeError("Failed to decrypt the URL")
                                else:
                                    return None, key_url, RuntimeError(f"Error in response: {json_response.get('message')}")
                            except Exception as e:
                                return None, key_url, RuntimeError(f"Error parsing JSON response: {e}")
                        else:
                            return None, key_url, RuntimeError(f"POST request failed with status code: {post_response.status_code}")
                    else:
                        return None, key_url, RuntimeError("Failed to decrypt the base64 value")
                else:
                    return None, key_url, RuntimeError("Base64 value not found in the HTML")
            else:
                return None, key_url, RuntimeError(f"Second GET request failed with status code: {second_response.status_code}")
        else:
            return None, key_url, RuntimeError(f"First request did not redirect as expected: {response.status_code}")
    except Exception as e:
        return None, key_url, RuntimeError(f"Lksfy handler failed: {e}")


async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_message = update.message.text.strip()

    now = time.time()

    if user_id in last_link_time:
        if now - last_link_time[user_id] < 120:
            wait = int(120 - (now - last_link_time[user_id]))
            await update.message.reply_text(f"⏳ Wait {wait} seconds before sending another link.")
            return

    last_link_time[user_id] = now

    if not user_message.startswith("http"):
        await update.message.reply_text("❌ Please send a valid link.")
        return

    await update.message.reply_text("🔄 Processing your link...")

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    try:
        if "lksfy" in user_message:
            key, _, error = handle_lksfy(user_message, session, True, False)
        elif "nanolinks" in user_message:
            key, _, error = handle_nano_links(user_message, session, True, False)
        elif "arolinks" in user_message:
            key, _, error = handle_aro_links(user_message, session, True, False)
        elif "t.me" in user_message:
            key, _, error = handle_telegram_url(user_message, session, True, False)
        else:
            await update.message.reply_text("❌ Unsupported link.")
            return
        if key:
            await update.message.reply_text(f"{key}")
            asyncio.create_task(start_countdown(update, 120))
        else:
            await update.message.reply_text(f"❌ Failed:\n{error}")

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error:\n{str(e)}")


def start_telegram_bot():
    import os

    BOT_TOKEN = os.getenv("BOT_TOKEN")  # use Railway variable

    app = ApplicationBuilder() \
        .token(BOT_TOKEN) \
        .job_queue(None) \
        .build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot started successfully...")
    app.run_polling()

if __name__ == "__main__":
    start_telegram_bot()















