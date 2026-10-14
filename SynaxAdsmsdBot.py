# ============================================================
# AUTO REQUIREMENT BOOTSTRAP
# This source automatically installs the exact Telegram library
# needed for colored inline keyboard buttons before importing PTB.
# ============================================================
import sys as _sys
import subprocess as _subprocess
import importlib.metadata as _metadata

_REQUIRED_PTB = "22.8"
_REQUIRED_PACKAGING = "24.0"

def _version_at_least(package_name, minimum):
    try:
        from packaging.version import Version as _Version
        return _Version(_metadata.version(package_name)) >= _Version(minimum)
    except Exception:
        return False

def _ensure_requirements():
    packages = []
    try:
        _metadata.version("python-telegram-bot")
    except _metadata.PackageNotFoundError:
        packages.append(f"python-telegram-bot=={_REQUIRED_PTB}")
    else:
        if not _version_at_least("python-telegram-bot", _REQUIRED_PTB):
            packages.append(f"python-telegram-bot=={_REQUIRED_PTB}")

    try:
        _metadata.version("packaging")
    except _metadata.PackageNotFoundError:
        packages.append(f"packaging>={_REQUIRED_PACKAGING}")
    else:
        if not _version_at_least("packaging", _REQUIRED_PACKAGING):
            packages.append(f"packaging>={_REQUIRED_PACKAGING}")

    if packages:
        print("[Requirements] Installing/updating: " + ", ".join(packages))
        _subprocess.check_call([_sys.executable, "-m", "pip", "install", "--upgrade", *packages])
        print("[Requirements] Installation complete.")

_ensure_requirements()

import asyncio
import html
import warnings
warnings.filterwarnings("ignore", message="Using async sessions support is an experimental feature")
import logging
import sqlite3
import json
import os
import time
import random
import pyfiglet
import shutil
import gc
import sys
from termcolor import colored
from colorama import init
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, quote
import io
import base64
import aiohttp
import qrcode
from PIL import Image, ImageDraw, ImageFont
import math

gc.enable()
gc.set_threshold(700, 10, 10)

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    BotCommand, InputMediaPhoto, InputMediaVideo, InputMediaDocument
)
from telegram.constants import ParseMode

# ------------------------------------------------------------------
# Telegram text safety: convert accidental literal "\\n" sequences
# into real line breaks everywhere this source sends/edits text.
# This fixes messages that previously displayed \n\n literally.
# ------------------------------------------------------------------
def _synax_clean_text(value):
    if isinstance(value, str):
        # Handle both literal backslash-n and double-escaped variants.
        value = value.replace("\\\\n", "\n")
        value = value.replace("\\n", "\n")
    return value


# Colored inline keyboard styles require python-telegram-bot 22.7+.
# This source bootstraps PTB 22.8 automatically above.
from telegram import __version__ as PTB_VERSION
from packaging.version import Version
if Version(PTB_VERSION) < Version("22.7"):
    raise RuntimeError(
        f"python-telegram-bot {PTB_VERSION} is still too old after requirement bootstrap. "
        "Please restart the bot once."
    )

# Normalize all outgoing/editable bot text so no UI can display literal \n\n.
from telegram import Bot as _SynaxTelegramBot
_synax_original_send_message = _SynaxTelegramBot.send_message
_synax_original_edit_message_text = _SynaxTelegramBot.edit_message_text

async def _synax_send_message(self, *args, **kwargs):
    if "text" in kwargs:
        kwargs["text"] = _synax_clean_text(kwargs["text"])
    elif len(args) >= 2 and isinstance(args[1], str):
        args = list(args)
        args[1] = _synax_clean_text(args[1])
        args = tuple(args)
    return await _synax_original_send_message(self, *args, **kwargs)

async def _synax_edit_message_text(self, *args, **kwargs):
    if "text" in kwargs:
        kwargs["text"] = _synax_clean_text(kwargs["text"])
    elif len(args) >= 3 and isinstance(args[2], str):
        args = list(args)
        args[2] = _synax_clean_text(args[2])
        args = tuple(args)
    return await _synax_original_edit_message_text(self, *args, **kwargs)

_SynaxTelegramBot.send_message = _synax_send_message
_SynaxTelegramBot.edit_message_text = _synax_edit_message_text
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ContextTypes
)
from telegram.helpers import escape_markdown
from telegram.error import TelegramError, BadRequest

from telethon import TelegramClient, events, functions
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneNumberInvalidError, FloodWaitError, ChatAdminRequiredError,
    UserAlreadyParticipantError, InviteHashExpiredError,
    UserBannedInChannelError, ChannelPrivateError,
    ChatWriteForbiddenError
)
from telethon.tl.functions.messages import ForwardMessagesRequest
from telethon.tl.types import (
    Channel, Chat, User, PeerChannel, PeerChat, PeerUser
)

# Read custom DB and session names from environment variables
DB_NAME = os.environ.get("ADBOT_DB", "adbot.db")
SESSION_NAME = os.environ.get("ADBOT_SESSION", "userbot_session")
SUPPORT_USER_IDS = [8363262755]  # Example support user


CRITICAL_SETTINGS_KEYS = [
    "bot_token", "admin_user_id", "subscription_start", "subscription_duration"
]

# Protect these tables entirely (if any)
CRITICAL_TABLES = []


def show_banner():
    init()
    term_width = shutil.get_terminal_size().columns

    title = pyfiglet.figlet_format("Synax AD BOT", font="slant")
    subtitle = "@SynaxBaby | t.me/SynaxBaby"

    def center_ascii(text):
        return "\n".join(line.center(term_width) for line in text.splitlines())

    def framed_text(text):
        border = "+-" + "-".join(["-"] * len(text)) + "-+"
        content = "| " + " ".join(text) + " |"
        return f"{border}\n{content}\n{border}"

    print(colored(center_ascii(title), "cyan", attrs=["bold"]))
    print(colored(center_ascii(framed_text(subtitle)), "magenta", attrs=["bold"]))

# Database setup
class Database:
    def __init__(self, db_path: str = DB_NAME):
        self.db_path = db_path
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute('PRAGMA journal_mode=WAL')
        conn.commit()
        conn.close()
        self.init_database()
    
    def fetch_one(self, query, params=()):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            result = cursor.fetchone()
            return result
        finally:
            cursor.close()
            conn.close()
    
    def init_database(self):
        """Initialize the database with required tables."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        cursor = conn.cursor()
        
        # Userbot session table (supports multiple userbots per user)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS userbot_session (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                api_id INTEGER,
                api_hash TEXT,
                phone_number TEXT,
                session_string TEXT,
                is_active BOOLEAN DEFAULT 0,
                last_activity TIMESTAMP,
                forward_mode TEXT DEFAULT 'show',
                messages_sent_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, phone_number)
            )
        ''')

        cursor.execute("PRAGMA table_info(userbot_session)")
        columns = [col[1] for col in cursor.fetchall()]
        if "forward_mode" not in columns:
            cursor.execute("ALTER TABLE userbot_session ADD COLUMN forward_mode TEXT DEFAULT 'show'")
        if "user_id" not in columns:
            cursor.execute("ALTER TABLE userbot_session ADD COLUMN user_id INTEGER")
            cursor.execute("UPDATE userbot_session SET user_id = 0 WHERE user_id IS NULL")
        if "messages_sent_count" not in columns:
            cursor.execute("ALTER TABLE userbot_session ADD COLUMN messages_sent_count INTEGER DEFAULT 0")
        if "admin_display_name" not in columns:
            cursor.execute("ALTER TABLE userbot_session ADD COLUMN admin_display_name TEXT")
        if "admin_bio" not in columns:
            cursor.execute("ALTER TABLE userbot_session ADD COLUMN admin_bio TEXT")
        if "connected_at" not in columns:
            cursor.execute("ALTER TABLE userbot_session ADD COLUMN connected_at TIMESTAMP")
        
        # Groups and forums table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                chat_id INTEGER,
                title TEXT,
                username TEXT,
                chat_type TEXT,
                is_selected BOOLEAN DEFAULT 1,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, chat_id)
            )
        ''')
        
        cursor.execute("PRAGMA table_info(groups)")
        groups_columns = [col[1] for col in cursor.fetchall()]
        if "user_id" not in groups_columns:
            cursor.execute("DROP TABLE IF EXISTS groups_backup")
            cursor.execute("ALTER TABLE groups RENAME TO groups_backup")
            cursor.execute('''
                CREATE TABLE groups (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER,
                    title TEXT,
                    username TEXT,
                    chat_type TEXT,
                    is_selected BOOLEAN DEFAULT 1,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, chat_id)
                )
            ''')
        
        # Forwarding messages table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS forwarding_messages (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                message_link TEXT,
                channel_id INTEGER,
                message_id INTEGER,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute("PRAGMA table_info(forwarding_messages)")
        fw_msg_columns = [col[1] for col in cursor.fetchall()]
        if "user_id" not in fw_msg_columns:
            cursor.execute("DROP TABLE IF EXISTS forwarding_messages_backup")
            cursor.execute("ALTER TABLE forwarding_messages RENAME TO forwarding_messages_backup")
            cursor.execute('''
                CREATE TABLE forwarding_messages (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    message_link TEXT,
                    channel_id INTEGER,
                    message_id INTEGER,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

        # Trace log table (for live trace, auto-purged after 1 hour)
        
        # System settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Default Auto Fampay configuration (only fills missing settings; existing admin values are preserved).
        # These defaults mirror the Fampay configuration supplied for the bypass bot.
        default_fampay_settings = {
            "fampay_api_url": "https://api.growfan.in/fampay.php",
            "fampay_api_key": "",
            "fampay_gmail": "gurugamer183@gmail.com",
            "fampay_app_password": "",
            "fampay_upi_id": os.environ.get("FAMPAY_UPI_ID", ""),
            "fampay_upi_name": "CCxBypass_Bot",
            "fampay_enabled": "1",
            "fampay_prices": json.dumps({
                "1_month": 60,
                "3_months": 100,
                "6_months": 600,
                "lifetime": 1000
            })
        }
        for _key, _value in default_fampay_settings.items():
            cursor.execute("SELECT value FROM settings WHERE key = ?", (_key,))
            _row = cursor.fetchone()
            # Fill defaults when the setting is missing OR empty. Existing non-empty admin values are preserved.
            if _row is None:
                cursor.execute(
                    "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                    (_key, _value, datetime.now())
                )
            elif _row[0] is None or str(_row[0]).strip() == "":
                cursor.execute(
                    "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
                    (_value, datetime.now(), _key)
                )

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS afk_replies (
                user_id INTEGER PRIMARY KEY,
                last_replied_at TIMESTAMP
            )
        ''')
        
        # Logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY,
                level TEXT,
                message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Userbot-Message Assignment (assign specific messages to specific userbots)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS userbot_message_assignment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                userbot_id INTEGER NOT NULL,
                forwarding_message_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, userbot_id, forwarding_message_id),
                FOREIGN KEY(userbot_id) REFERENCES userbot_session(id),
                FOREIGN KEY(forwarding_message_id) REFERENCES forwarding_messages(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_joins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                group_link TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute("PRAGMA table_info(pending_joins)")
        pending_joins_columns = [col[1] for col in cursor.fetchall()]
        if "user_id" not in pending_joins_columns:
            cursor.execute("DROP TABLE IF EXISTS pending_joins_backup")
            cursor.execute("ALTER TABLE pending_joins RENAME TO pending_joins_backup")
            cursor.execute('''
                CREATE TABLE pending_joins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    group_link TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

        cursor.execute("DROP TABLE IF EXISTS forward_trace")
        cursor.execute('''
            CREATE TABLE forward_trace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                group_title TEXT,
                group_link TEXT,
                chat_id INTEGER,
                message_id INTEGER,
                forwarded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute("SELECT value FROM settings WHERE key = 'per_message_delay'")
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ('per_message_delay', '5', datetime.now())
            )

            # Forwarded cache to prevent duplication
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS forwarded_cycle_cache (
                chat_id INTEGER,
                message_hash TEXT,
                cycle_id TEXT,
                PRIMARY KEY (chat_id, message_hash, cycle_id)
            )
        ''')

        # State persistence
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS forwarding_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        cursor.execute("SELECT value FROM settings WHERE key = 'group_join_enabled'")
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                ('group_join_enabled', 'on', datetime.now())
            )

        # User-specific logs channels table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_logs_channels (
                user_id INTEGER PRIMARY KEY,
                logs_channel_id INTEGER NOT NULL,
                logs_channel_title TEXT,
                logs_channel_username TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        ''')

        # User-specific settings table (for settings that vary per user)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, key)
            )
        ''')

        # Authorized users table for admin panel
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS authorized_users (
                user_id INTEGER PRIMARY KEY,
                approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                total_minutes_granted INTEGER DEFAULT 0,
                approved_by INTEGER,
                note TEXT,
                message_limit INTEGER DEFAULT NULL,
                userbot_limit INTEGER DEFAULT 1,
                messages_sent_count INTEGER DEFAULT 0
            )
        ''')
        
        # Add new columns to existing table if they don't exist
        cursor.execute("PRAGMA table_info(authorized_users)")
        auth_columns = [col[1] for col in cursor.fetchall()]
        if "message_limit" not in auth_columns:
            cursor.execute("ALTER TABLE authorized_users ADD COLUMN message_limit INTEGER DEFAULT NULL")
        if "userbot_limit" not in auth_columns:
            cursor.execute("ALTER TABLE authorized_users ADD COLUMN userbot_limit INTEGER DEFAULT 1")
        if "messages_sent_count" not in auth_columns:
            cursor.execute("ALTER TABLE authorized_users ADD COLUMN messages_sent_count INTEGER DEFAULT 0")
        
        # Logging bot configuration table - supports multiple destinations per user
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_logging_bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bot_token TEXT NOT NULL,
                destination_type TEXT NOT NULL,
                destination_id INTEGER,
                destination_title TEXT,
                destination_username TEXT,
                is_active BOOLEAN DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, destination_id, bot_token)
            )
        ''')
        
        # Migration: Add id column if it doesn't exist (for old databases)
        cursor.execute("PRAGMA table_info(user_logging_bots)")
        columns = [col[1] for col in cursor.fetchall()]
        if "id" not in columns:
            # Recreate table with new schema
            cursor.execute("DROP TABLE IF EXISTS user_logging_bots_old")
            cursor.execute("ALTER TABLE user_logging_bots RENAME TO user_logging_bots_old")
            cursor.execute('''
                CREATE TABLE user_logging_bots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    bot_token TEXT NOT NULL,
                    destination_type TEXT NOT NULL,
                    destination_id INTEGER,
                    destination_title TEXT,
                    destination_username TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, destination_id, bot_token)
                )
            ''')
            # Migrate data from old table
            try:
                cursor.execute('''
                    INSERT INTO user_logging_bots (user_id, bot_token, destination_type, destination_id, destination_title, destination_username, is_active, added_at, updated_at)
                    SELECT user_id, bot_token, destination_type, destination_id, destination_title, destination_username, is_active, added_at, updated_at
                    FROM user_logging_bots_old
                ''')
                cursor.execute("DROP TABLE user_logging_bots_old")
            except:
                pass
        
        # Broadcast messages table for admin
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                total_users INTEGER DEFAULT 0,
                sent_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                total_groups INTEGER DEFAULT 0,
                sent_groups INTEGER DEFAULT 0,
                failed_groups INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        ''')
        # Migration for older databases
        cursor.execute("PRAGMA table_info(broadcasts)")
        broadcast_columns = [col[1] for col in cursor.fetchall()]
        if "total_groups" not in broadcast_columns:
            cursor.execute("ALTER TABLE broadcasts ADD COLUMN total_groups INTEGER DEFAULT 0")
        if "sent_groups" not in broadcast_columns:
            cursor.execute("ALTER TABLE broadcasts ADD COLUMN sent_groups INTEGER DEFAULT 0")
        if "failed_groups" not in broadcast_columns:
            cursor.execute("ALTER TABLE broadcasts ADD COLUMN failed_groups INTEGER DEFAULT 0")
        
        # Admin settings table for default bio, last name, etc.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Set default admin settings if not exist
        cursor.execute("SELECT value FROM admin_settings WHERE key = 'default_bio'")
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?)",
                ('default_bio', 'Hosted By @SynaxBaby', datetime.now())
            )
        
        cursor.execute("SELECT value FROM admin_settings WHERE key = 'default_lastname'")
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?)",
                ('default_lastname', 'Hosted By @SynaxBaby', datetime.now())
            )
        
        cursor.execute("SELECT value FROM admin_settings WHERE key = 'join_interval'")
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?)",
                ('join_interval', '300', datetime.now())
            )
        for _k, _v in {
            'premium_maintenance': 'off',
            'mandatory_log_bot_token': '',
            'mandatory_log_bot_username': '',
            'mandatory_log_bot_ready': '0',
        }.items():
            if not cursor.execute("SELECT 1 FROM admin_settings WHERE key = ?", (_k,)).fetchone():
                cursor.execute("INSERT INTO admin_settings (key,value,updated_at) VALUES (?,?,?)", (_k,_v,datetime.now()))
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fampay_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                purpose TEXT UNIQUE,
                amount REAL NOT NULL,
                plan_type TEXT NOT NULL,
                plan_duration INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verified_at TIMESTAMP
            )
        ''')
        
        # MIGRATION: Move AFK settings from global settings to per-user settings for admin user
        try:
            admin_id_result = cursor.execute("SELECT value FROM settings WHERE key = 'admin_user_id'").fetchone()
            if admin_id_result:
                admin_id = int(admin_id_result[0])
                # Check if global AFK settings exist
                afk_enabled = cursor.execute("SELECT value FROM settings WHERE key = 'afk_enabled'").fetchone()
                afk_message = cursor.execute("SELECT value FROM settings WHERE key = 'afk_message'").fetchone()
                
                # Migrate to per-user settings if they exist
                if afk_enabled and afk_enabled[0]:
                    cursor.execute(
                        "INSERT OR REPLACE INTO user_settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
                        (admin_id, 'afk_enabled', afk_enabled[0], datetime.now())
                    )
                    print(f"[MIGRATION] Migrated AFK enabled status to user {admin_id}")
                
                if afk_message and afk_message[0]:
                    cursor.execute(
                        "INSERT OR REPLACE INTO user_settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
                        (admin_id, 'afk_message', afk_message[0], datetime.now())
                    )
                    print(f"[MIGRATION] Migrated AFK message to user {admin_id}")
        except Exception as e:
            print(f"[MIGRATION] Error migrating AFK settings: {e}")
        
        conn.commit()
        conn.close()
    
    def execute_query(self, query: str, params: tuple = None) -> List[tuple]:
        """Execute a query and return results (only for SELECT)."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        cursor = conn.cursor()

        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            query_type = query.strip().upper()
            if query_type.startswith("SELECT"):
                results = cursor.fetchall()
            else:
                conn.commit()
                results = []

            return results
        finally:
            cursor.close()
            conn.close()
    
    def get_forwarding_state(self, key: str, default: str = None) -> Optional[str]:
        result = self.execute_query("SELECT value FROM forwarding_state WHERE key = ?", (key,))
        return result[0][0] if result else default

    def set_forwarding_state(self, key: str, value: str):
        self.execute_query(
            "INSERT OR REPLACE INTO forwarding_state (key, value) VALUES (?, ?)",
            (key, value)
        )

    def was_forwarded_this_cycle(self, chat_id: int, message_hash: str, cycle_id: str) -> bool:
        result = self.execute_query(
            "SELECT 1 FROM forwarded_cycle_cache WHERE chat_id = ? AND message_hash = ? AND cycle_id = ?",
            (chat_id, message_hash, cycle_id)
        )
        return bool(result)

    def mark_forwarded_this_cycle(self, chat_id: int, message_hash: str, cycle_id: str):
        self.execute_query(
            "INSERT OR IGNORE INTO forwarded_cycle_cache (chat_id, message_hash, cycle_id) VALUES (?, ?, ?)",
            (chat_id, message_hash, cycle_id)
        )
    
    def get_user_logs_channel(self, user_id: int) -> Optional[Dict]:
        result = self.fetch_one(
            "SELECT logs_channel_id, logs_channel_title, logs_channel_username FROM user_logs_channels WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )
        if result:
            return {
                "channel_id": result[0],
                "channel_title": result[1],
                "channel_username": result[2]
            }
        return None
    
    def set_user_logs_channel(self, user_id: int, channel_id: int, channel_title: str = None, channel_username: str = None):
        self.execute_query(
            "INSERT OR REPLACE INTO user_logs_channels (user_id, logs_channel_id, logs_channel_title, logs_channel_username, is_active) VALUES (?, ?, ?, ?, 1)",
            (user_id, channel_id, channel_title, channel_username)
        )
    
    def remove_user_logs_channel(self, user_id: int):
        self.execute_query(
            "UPDATE user_logs_channels SET is_active = 0 WHERE user_id = ?",
            (user_id,)
        )

    def get_afk_last_reply_time(self, user_id: int) -> Optional[datetime]:
        result = self.fetch_one("SELECT last_replied_at FROM afk_replies WHERE user_id = ?", (user_id,))
        return datetime.fromisoformat(result[0]) if result else None

    def set_afk_last_reply_time(self, user_id: int, reply_time: datetime):
        self.execute_query(
            "INSERT OR REPLACE INTO afk_replies (user_id, last_replied_at) VALUES (?, ?)",
            (user_id, reply_time.isoformat())
        )
    
    def get_setting(self, key: str, default: str = None) -> str:
        """Get a setting value."""
        result = self.execute_query("SELECT value FROM settings WHERE key = ?", (key,))
        return result[0][0] if result else default
    
    def set_setting(self, key: str, value: str):
        """Set a setting value."""
        self.execute_query(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, datetime.now())
        )
    
    def log_event(self, level: str, message: str):
        """Log an event to the database."""
        self.execute_query(
            "INSERT INTO logs (level, message) VALUES (?, ?)",
            (level, message)
        )
    
    def get_selected_groups(self, user_id: int) -> List[Dict]:
        """Get groups selected for forwarding for a specific user."""
        results = self.execute_query(
            "SELECT chat_id, title, username, chat_type FROM groups WHERE user_id = ? AND is_selected = 1",
            (user_id,)
        )
        
        return [
            {
                "chat_id": row[0],
                "title": row[1],
                "username": row[2],
                "type": row[3]
            }
            for row in results
        ]
    
    def get_forwarding_messages(self, user_id: int) -> List[Dict]:
        """Get all active forwarding messages for a specific user."""
        results = self.execute_query(
            "SELECT id, message_link, channel_id, message_id FROM forwarding_messages WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )
        
        return [
            {
                "id": row[0],
                "link": row[1],
                "channel_id": row[2],
                "message_id": row[3]
            }
            for row in results
        ]
    
    def add_forwarding_message(self, user_id: int, message_link: str, channel_id: int, message_id: int) -> Tuple[bool, str]:
        """Add a forwarding message for a specific user with dynamic limit based on admin settings."""
        try:
            user_limit_result = self.execute_query(
                "SELECT message_limit FROM authorized_users WHERE user_id = ?",
                (user_id,)
            )
            
            if user_limit_result and user_limit_result[0][0] is not None:
                max_messages = user_limit_result[0][0]
            else:
                max_messages = 2
            
            existing = self.execute_query(
                "SELECT COUNT(*) FROM forwarding_messages WHERE user_id = ? AND is_active = 1",
                (user_id,)
            )
            
            if existing[0][0] >= max_messages:
                return False, f"❌ Maximum {max_messages} forwarding messages allowed for your account."
            
            self.execute_query(
                "INSERT INTO forwarding_messages (user_id, message_link, channel_id, message_id) VALUES (?, ?, ?, ?)",
                (user_id, message_link, channel_id, message_id)
            )
            return True, "✅ Forwarding message added successfully!"
        
        except Exception as e:
            self.log_event("ERROR", f"Failed to add forwarding message for user {user_id}: {str(e)}")
            return False, f"Error: {str(e)}"
    
    def add_group(self, user_id: int, chat_id: int, title: str, username: str, chat_type: str) -> bool:
        """Add a group for a specific user."""
        try:
            self.execute_query(
                "INSERT OR REPLACE INTO groups (user_id, chat_id, title, username, chat_type, is_selected) VALUES (?, ?, ?, ?, ?, 1)",
                (user_id, chat_id, title, username, chat_type)
            )
            return True
        except Exception as e:
            self.log_event("ERROR", f"Failed to add group for user {user_id}: {str(e)}")
            return False
    
    def get_user_groups_count(self, user_id: int) -> int:
        """Get count of groups for a user."""
        result = self.execute_query(
            "SELECT COUNT(*) FROM groups WHERE user_id = ?",
            (user_id,)
        )
        return result[0][0] if result else 0
    
    def add_forward_trace(self, user_id: int, group_title: str, group_link: str, chat_id: int, message_id: int):
        """Add forward trace log for a user."""
        self.execute_query(
            "INSERT INTO forward_trace (user_id, group_title, group_link, chat_id, message_id, forwarded_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, group_title, group_link, chat_id, message_id, datetime.now(timezone.utc).isoformat())
        )
    
    def get_forwarding_stats(self, user_id: int) -> Dict:
        """Get comprehensive forwarding statistics for analytics."""
        try:
            total_traces = self.fetch_one(
                "SELECT COUNT(*) FROM forward_trace WHERE user_id = ?",
                (user_id,)
            )[0]
            
            today_traces = self.fetch_one(
                "SELECT COUNT(*) FROM forward_trace WHERE user_id = ? AND DATE(forwarded_at) = DATE('now')",
                (user_id,)
            )[0]
            
            week_traces = self.fetch_one(
                "SELECT COUNT(*) FROM forward_trace WHERE user_id = ? AND forwarded_at >= datetime('now', '-7 days')",
                (user_id,)
            )[0]
            
            groups_used = self.fetch_one(
                "SELECT COUNT(DISTINCT group_title) FROM forward_trace WHERE user_id = ?",
                (user_id,)
            )[0]
            
            total_groups = self.fetch_one(
                "SELECT COUNT(*) FROM groups WHERE user_id = ?",
                (user_id,)
            )[0]
            
            selected_groups = self.fetch_one(
                "SELECT COUNT(*) FROM groups WHERE user_id = ? AND is_selected = 1",
                (user_id,)
            )[0]
            
            return {
                "total_forwards": total_traces,
                "forwards_today": today_traces,
                "forwards_week": week_traces,
                "groups_used": groups_used,
                "total_groups": total_groups,
                "selected_groups": selected_groups
            }
        except Exception as e:
            self.log_event("ERROR", f"Failed to get stats: {str(e)}")
            return {}
    
    def get_mandatory_log_bot(self):
        token=self.get_admin_setting('mandatory_log_bot_token','')
        if token and self.get_admin_setting('mandatory_log_bot_ready','0') == '1':
            return {'bot_token':token,'username':self.get_admin_setting('mandatory_log_bot_username','')}
        return None

    def set_mandatory_log_bot(self, token, username):
        self.set_admin_setting('mandatory_log_bot_token',token)
        self.set_admin_setting('mandatory_log_bot_username',username or '')
        self.set_admin_setting('mandatory_log_bot_ready','1')

    def remove_mandatory_log_bot(self):
        self.set_admin_setting('mandatory_log_bot_token','')
        self.set_admin_setting('mandatory_log_bot_username','')
        self.set_admin_setting('mandatory_log_bot_ready','0')

    def get_premium_maintenance(self):
        return self.get_admin_setting('premium_maintenance','off') == 'on'

    def set_premium_maintenance(self, enabled):
        self.set_admin_setting('premium_maintenance','on' if enabled else 'off')

    def get_user_logging_bot(self, user_id: int) -> Optional[Dict]:
        """Get user's logging bot configuration."""
        result = self.fetch_one(
            "SELECT bot_token, destination_type, destination_id, destination_title, destination_username FROM user_logging_bots WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )
        if result:
            return {
                "bot_token": result[0],
                "destination_type": result[1],
                "destination_id": result[2],
                "destination_title": result[3],
                "destination_username": result[4]
            }
        return None
    
    def get_user_logging_destinations(self, user_id: int) -> List[Dict]:
        """Get all logging destinations for user (supports multiple)."""
        results = self.execute_query(
            "SELECT destination_type, destination_id, destination_title, destination_username, bot_token FROM user_logging_bots WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )
        return [
            {
                "destination_type": r[0],
                "destination_id": r[1],
                "destination_title": r[2],
                "destination_username": r[3],
                "bot_token": r[4]
            }
            for r in results
        ]
    
    def set_user_logging_bot(self, user_id: int, bot_token: str, destination_type: str, destination_id: int = None, destination_title: str = None, destination_username: str = None):
        """Add a new logging destination for user (supports multiple destinations)."""
        self.execute_query(
            "INSERT OR IGNORE INTO user_logging_bots (user_id, bot_token, destination_type, destination_id, destination_title, destination_username, is_active, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (user_id, bot_token, destination_type, destination_id, destination_title, destination_username, datetime.now())
        )
    
    def remove_user_logging_bot(self, user_id: int):
        """Remove ALL logging destinations for user."""
        self.execute_query(
            "UPDATE user_logging_bots SET is_active = 0 WHERE user_id = ?",
            (user_id,)
        )
    
    def remove_user_logging_destination(self, user_id: int, destination_id: int):
        """Remove a specific logging destination for user."""
        self.execute_query(
            "UPDATE user_logging_bots SET is_active = 0 WHERE user_id = ? AND destination_id = ?",
            (user_id, destination_id)
        )
    
    def get_admin_setting(self, key: str, default: str = None) -> str:
        """Get an admin setting value."""
        result = self.execute_query("SELECT value FROM admin_settings WHERE key = ?", (key,))
        return result[0][0] if result else default
    
    def set_admin_setting(self, key: str, value: str):
        """Set an admin setting value."""
        self.execute_query(
            "INSERT OR REPLACE INTO admin_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, datetime.now())
        )
    
    def get_user_setting(self, user_id: int, key: str, default: str = None) -> str:
        """Get a user-specific setting value."""
        result = self.execute_query(
            "SELECT value FROM user_settings WHERE user_id = ? AND key = ?",
            (user_id, key)
        )
        return result[0][0] if result else default
    
    def set_user_setting(self, user_id: int, key: str, value: str):
        """Set a user-specific setting value."""
        self.execute_query(
            "INSERT OR REPLACE INTO user_settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, key, value, datetime.now())
        )
    
    def get_user_userbots(self, user_id: int) -> List[Dict]:
        """Get all userbots for a specific user."""
        results = self.execute_query(
            "SELECT id, phone_number, is_active, last_activity, messages_sent_count FROM userbot_session WHERE user_id = ?",
            (user_id,)
        )
        return [
            {
                "id": row[0],
                "phone_number": row[1],
                "is_active": row[2],
                "last_activity": row[3],
                "messages_sent_count": row[4]
            }
            for row in results
        ]
    
    def get_user_userbot_count(self, user_id: int) -> int:
        """Get count of userbots for a user."""
        result = self.execute_query(
            "SELECT COUNT(*) FROM userbot_session WHERE user_id = ?",
            (user_id,)
        )
        return result[0][0] if result else 0
    
    def get_user_limits(self, user_id: int) -> Dict:
        """Get user's limits from authorized_users table."""
        result = self.fetch_one(
            "SELECT userbot_limit, message_limit FROM authorized_users WHERE user_id = ?",
            (user_id,)
        )
        if result:
            return {
                "userbot_limit": result[0] or 1,
                "message_limit": result[1]
            }
        return {"userbot_limit": 1, "message_limit": None}
    
    def update_user_limits(self, user_id: int, userbot_limit: int = None, message_limit: int = None):
        """Update user's limits."""
        if userbot_limit is not None and message_limit is not None:
            self.execute_query(
                "UPDATE authorized_users SET userbot_limit = ?, message_limit = ? WHERE user_id = ?",
                (userbot_limit, message_limit, user_id)
            )
        elif userbot_limit is not None:
            self.execute_query(
                "UPDATE authorized_users SET userbot_limit = ? WHERE user_id = ?",
                (userbot_limit, user_id)
            )
        elif message_limit is not None:
            self.execute_query(
                "UPDATE authorized_users SET message_limit = ? WHERE user_id = ?",
                (message_limit, user_id)
            )
    
    def get_user_timezone(self, user_id: int) -> str:
        """Get user's timezone setting (GMT offset)."""
        return self.get_user_setting(user_id, 'timezone', '+00:00')
    
    def set_user_timezone(self, user_id: int, timezone_str: str):
        """Set user's timezone."""
        self.set_user_setting(user_id, 'timezone', timezone_str)
    
    def get_join_interval(self, user_id: int = None) -> int:
        """Get join interval in seconds. User-specific if user_id provided, else admin default."""
        if user_id:
            user_interval = self.get_user_setting(user_id, 'join_interval')
            if user_interval:
                return int(user_interval)
        return int(self.get_admin_setting('join_interval', '300'))
    
    def set_join_interval(self, interval_seconds: int, user_id: int = None):
        """Set join interval. If user_id provided, sets for that user, else sets admin default."""
        if user_id:
            self.set_user_setting(user_id, 'join_interval', str(interval_seconds))
        else:
            self.set_admin_setting('join_interval', str(interval_seconds))
    
    def save_fampay_payment(self, user_id: int, purpose: str, amount: float, plan_type: str, plan_duration: int) -> bool:
        try:
            self.execute_query(
                "INSERT INTO fampay_payments (user_id, purpose, amount, plan_type, plan_duration, status) VALUES (?, ?, ?, ?, ?, 'pending')",
                (user_id, purpose, amount, plan_type, plan_duration)
            )
            return True
        except Exception as e:
            print(f"[Fampay] Save payment error: {e}")
            return False

    def get_fampay_payment(self, purpose: str) -> Optional[Dict]:
        row = self.fetch_one("SELECT * FROM fampay_payments WHERE purpose = ?", (purpose,))
        if not row:
            return None
        return {
            'id': row[0], 'user_id': row[1], 'purpose': row[2], 'amount': row[3],
            'plan_type': row[4], 'plan_duration': row[5], 'status': row[6],
            'created_at': row[7], 'verified_at': row[8]
        }

    def mark_fampay_verified(self, purpose: str):
        self.execute_query(
            "UPDATE fampay_payments SET status='completed', verified_at=? WHERE purpose=? AND status='pending'",
            (datetime.now().isoformat(), purpose)
        )


class BotBannerGenerator:
    OWNER_NAME = "SynaxBaby"
    OWNER_HANDLE = "@SynaxBaby"
    BOT_NAME = "Synax AD BOT"
    
    def __init__(self):
        self.width = 800
        self.height = 400
        self.bg_color_top = (15, 25, 60)
        self.bg_color_bottom = (5, 15, 45)
        self.header_color = (20, 35, 80)
        self.text_color = (255, 255, 255)
        self.accent_color = (0, 200, 150)
        self.gold_color = (255, 215, 0)
        self._cached_welcome_banner = None
    
    def create_gradient(self, width: int, height: int, color1: tuple, color2: tuple) -> Image.Image:
        img = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(img)
        for y in range(height):
            t = y / max(height - 1, 1)
            r = int(color1[0] + (color2[0] - color1[0]) * t)
            g = int(color1[1] + (color2[1] - color1[1]) * t)
            b = int(color1[2] + (color2[2] - color1[2]) * t)
            draw.line([(0, y), (width, y)], fill=(r, g, b))
        return img

    def draw_rounded_rect(self, draw, coords, radius, fill=None, outline=None, width=1):
        draw.rounded_rectangle(coords, radius=radius, fill=fill, outline=outline, width=width)
    
    def generate_welcome_banner(self) -> bytes:
        if self._cached_welcome_banner:
            return self._cached_welcome_banner
        
        img = self.create_gradient(self.width, self.height, self.bg_color_top, self.bg_color_bottom)
        draw = ImageDraw.Draw(img)
        
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
            font_subtitle = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            font_medium = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            font_title = font_subtitle = font_medium = font_small = ImageFont.load_default()
        
        self.draw_rounded_rect(draw, (20, 15, self.width - 20, 90), 15, fill=self.header_color, outline=self.accent_color, width=2)
        
        title_text = self.BOT_NAME
        bbox = draw.textbbox((0, 0), title_text, font=font_title)
        title_width = bbox[2] - bbox[0]
        draw.text(((self.width - title_width) // 2, 30), title_text, fill=self.gold_color, font=font_title)
        
        subtitle = "Premium Telegram Automation & Advertising"
        bbox = draw.textbbox((0, 0), subtitle, font=font_subtitle)
        subtitle_width = bbox[2] - bbox[0]
        draw.text(((self.width - subtitle_width) // 2, 110), subtitle, fill=self.accent_color, font=font_subtitle)
        
        features = [
            "🚀 Auto-Forward Messages to Multiple Groups",
            "🤖 Userbot Integration with Session Support",
            "👥 Auto-Join Groups via Links",
            "📊 Real-time Analytics & Logging",
            "🇮🇳 Secure UPI Payments via Auto Fampay"
        ]
        
        y_offset = 160
        for feature in features:
            bbox = draw.textbbox((0, 0), feature, font=font_medium)
            feature_width = bbox[2] - bbox[0]
            draw.text(((self.width - feature_width) // 2, y_offset), feature, fill=self.text_color, font=font_medium)
            y_offset += 35
        
        self.draw_rounded_rect(draw, (100, self.height - 70, self.width - 100, self.height - 30), 10, 
                              fill=(0, 80, 60), outline=self.accent_color, width=2)
        
        footer_text = f"Powered by {self.OWNER_HANDLE} | t.me/SynaxBaby"
        bbox = draw.textbbox((0, 0), footer_text, font=font_medium)
        footer_width = bbox[2] - bbox[0]
        draw.text(((self.width - footer_width) // 2, self.height - 60), footer_text, fill=self.gold_color, font=font_medium)
        
        buffer = io.BytesIO()
        img.save(buffer, format='PNG', optimize=True)
        buffer.seek(0)
        result = buffer.getvalue()
        
        self._cached_welcome_banner = result
        
        del img
        del draw
        buffer.close()
        gc.collect()
        
        return result


class ProfessionalBannerGenerator:
    OWNER_HANDLE = "@SynaxBaby"
    _BANNER_B64 = "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AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABCBQjTwAjABxRChSzRBihijjiBTxCThDBhQhTSQizwAggAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABgCwCQDCSyDTjQSQRQyTQxRgiAhTChhRjwCARjQTyiQRAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABRBBTxAgTxwzyCSgChygxRghxxCxygSQwhQQAyAhzABDyhQAAAAAQwgAAQQAAAAAABiwAAAAAAAAAAAAASRTQxxghxzDASRzDxRCQTiBTBxSRSywyzRwxSDziAwwAQggAQQgTARCyjgQggQAgTDwAwAwggAAAAAABRjDRjQzgQSgCRxgjzyDzxxziDwjxQyATSCyzTTThijADQBwSjihDyBwRQjSjCRSDhyjRBTDiwAAAAAAABygzgCDzDyxByDiBBRwTwgDjQTCASijzySjjCyihRiQDxjDhzgwCARxzCTxiARAQDhwgjxRDAAAAAAAAAwRyDSzTgyDizzCRBiSwASjRyDxTyRjiDzARyCjzRzzABCDQAABBCAABBABADADBBABChADiAAAAAAABCijQhTQxCSChQyCyzhBwTDiRTRjAzgRwjgxCyCxxyCAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACxCCRyCizzRDQhSTCAjQzyRhRRzgiRjgjRBwQxjjDzRQgAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABQADRigjTTiBzBQShSTSwwjTAzgijTCARSiAgyQQjhRgiggAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABgiRQyByBRBChTgjQjihSywRwxiyAjyBSAyRDgghxxSCBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABBADyyDzAxQyQDBDTxijRDwDzRjASBxxDzywTyRhQwCiAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABQTjSTxhBhiRRyCgByhRQijBwxQjQSwjxjhwzjSSjBQSgDAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABgywABTjCRzBzQizhSxAzRjCQzDwCBDiSQxBSADjjxBCAwAAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQQASgChiTzwCjSTBwQDygTxAxQByggDDihShygxzyjCgBAAA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"
    _cached_bg_image = None  # cache resets on restart

    def __init__(self):
        self.width = 1200
        self.height = 400
        self.bg_color = (20, 20, 25)
        self.text_color = (255, 255, 255)
        self.accent_color = (200, 200, 200)
        self._cached_bg = None

    def load_background_from_url(self, width: int, height: int) -> Image.Image:
        """Load banner from embedded base64 image (cached after first load)."""
        if ProfessionalBannerGenerator._cached_bg_image is not None:
            return ProfessionalBannerGenerator._cached_bg_image.copy().resize((width, height), Image.Resampling.LANCZOS)
        try:
            img_data = base64.b64decode(self._BANNER_B64)
            img = Image.open(io.BytesIO(img_data)).convert('RGB')
            img = img.resize((width, height), Image.Resampling.LANCZOS)
            ProfessionalBannerGenerator._cached_bg_image = img
            return img.copy()
        except Exception:
            return self.create_dark_textured_background(width, height)

    def create_dark_textured_background(self, width: int, height: int) -> Image.Image:
        img = Image.new('RGB', (width, height))
        pixels = img.load()
        for y in range(height):
            darkness = int(15 * (y / height))
            for x in range(width):
                val = random.randint(15, 30)
                noise = random.randint(-10, 10)
                v = max(0, min(255, val + noise - darkness))
                pixels[x, y] = (v, v, v)
        draw = ImageDraw.Draw(img)
        for _ in range(50):
            x = random.randint(0, width - 1)
            y_pos = random.randint(0, height - 1)
            size = random.randint(1, 4)
            brightness = random.randint(30, 60)
            draw.ellipse([x, y_pos, x+size, y_pos+size], fill=(brightness, brightness, brightness))
        return img
    
    def draw_rocket_icon(self, draw: ImageDraw.Draw, x: int, y: int, size: int = 120):
        scale = size / 120
        cx, cy = x + size // 2, y + size // 2
        
        draw.polygon([
            (cx, cy - 50 * scale),
            (cx - 25 * scale, cy + 20 * scale),
            (cx + 25 * scale, cy + 20 * scale)
        ], outline=self.text_color, width=3)
        
        draw.arc(
            [cx - 25 * scale, cy - 30 * scale, cx + 25 * scale, cy + 30 * scale],
            180, 360, fill=self.text_color, width=3
        )
        
        draw.ellipse(
            [cx - 10 * scale, cy - 15 * scale, cx + 10 * scale, cy + 5 * scale],
            outline=self.text_color, width=2
        )
        
        draw.polygon([
            (cx - 30 * scale, cy + 10 * scale),
            (cx - 40 * scale, cy + 35 * scale),
            (cx - 20 * scale, cy + 20 * scale)
        ], outline=self.text_color, width=2)
        
        draw.polygon([
            (cx + 30 * scale, cy + 10 * scale),
            (cx + 40 * scale, cy + 35 * scale),
            (cx + 20 * scale, cy + 20 * scale)
        ], outline=self.text_color, width=2)
        
        for i in range(3):
            start_x = cx - 15 * scale + i * 10 * scale
            draw.line([
                (start_x, cy + 30 * scale),
                (start_x - 5 * scale, cy + 50 * scale + i * 5 * scale)
            ], fill=self.text_color, width=2)
    
    def draw_star(self, draw: ImageDraw.Draw, x: int, y: int, size: int = 20):
        points = []
        for i in range(4):
            angle = i * 90 - 45
            rad = angle * math.pi / 180
            points.append((x + size * math.cos(rad), y + size * math.sin(rad)))
            angle2 = angle + 45
            rad2 = angle2 * math.pi / 180
            points.append((x + size * 0.4 * math.cos(rad2), y + size * 0.4 * math.sin(rad2)))
        draw.polygon(points, fill=self.text_color)
    
    _banner_cache: dict = {}

    def generate_banner(self, title: str = "", subtitle: str = "", top_text: str = "") -> bytes:
        """Return the embedded banner image as-is (no text overlay)."""
        if "banner" in ProfessionalBannerGenerator._banner_cache:
            return ProfessionalBannerGenerator._banner_cache["banner"]
        img = self.load_background_from_url(self.width, self.height)
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=92, optimize=True)
        buffer.seek(0)
        result = buffer.getvalue()
        ProfessionalBannerGenerator._banner_cache["banner"] = result
        buffer.close()
        gc.collect()
        return result
    
    def generate_service_banner(self, service_name: str = "Synax Ad Bot") -> bytes:
        return self.generate_banner(service_name, "#1 Autobump service", "@SynaxBaby")
    
    def generate_pricing_banner(self, handle: str = "@SynaxBaby") -> bytes:
        return self.generate_banner("Pricing Info", handle, "@SynaxBaby")
    
    def generate_features_banner(self) -> bytes:
        return self.generate_banner("Why Choose Us?", "#1 Autobump service", "@SynaxBaby")
    
    def generate_welcome_banner(self) -> bytes:
        return self.generate_banner("Welcome!", "Premium Telegram Advertising", "@SynaxBaby")
    
    def generate_buy_now_banner(self) -> bytes:
        return self.generate_banner("Buy Now", "Choose Your Plan", "@SynaxBaby")
    
    def generate_crypto_selection_banner(self) -> bytes:
        return self.generate_banner("Select Currency", "Choose Payment Method", "@SynaxBaby")
    
    def generate_network_selection_banner(self, crypto: str = "Crypto") -> bytes:
        return self.generate_banner("Select Network", f"Choose {crypto} Network", "@SynaxBaby")
    
    def generate_faq_banner(self) -> bytes:
        return self.generate_banner("FAQ", "Frequently Asked Questions", "@SynaxBaby")
    
    def generate_vouches_banner(self) -> bytes:
        return self.generate_banner("Testimonials", "What Users Say", "@SynaxBaby")
    
    def generate_subscription_banner(self) -> bytes:
        return self.generate_banner("Subscription", "Your Access Status", "@SynaxBaby")
    
    def generate_userbot_banner(self) -> bytes:
        return self.generate_banner("Userbot", "Manage Your Accounts", "@SynaxBaby")
    
    def generate_groups_banner(self) -> bytes:
        return self.generate_banner("Groups", "Manage Target Groups", "@SynaxBaby")
    
    def generate_settings_banner(self) -> bytes:
        return self.generate_banner("Settings", "Configure Your Bot", "@SynaxBaby")
    
    def generate_admin_banner(self) -> bytes:
        return self.generate_banner("Admin Panel", "System Management", "@SynaxBaby")
    
    def generate_help_banner(self) -> bytes:
        return self.generate_banner("Help Center", "Get Support", "@SynaxBaby")


class LogsChannelManager:
    """Manages logs channel functionality for users"""
    
    def __init__(self, db_instance, bot_application):
        self.db = db_instance
        self.bot_app = bot_application
    
    async def setup_logs_channel(self, user_id: int, channel_input: str) -> Tuple[bool, str]:
        """
        Setup logs channel for a user.
        
        Args:
            user_id: Telegram user ID
            channel_input: Channel username (@channelname) or link (https://t.me/channelname)
        
        Returns:
            Tuple of (success, message)
        """
        try:
            channel_username = channel_input.strip()
            if channel_username.startswith('https://t.me/'):
                channel_username = '@' + channel_username.split('/')[-1]
            elif not channel_username.startswith('@'):
                channel_username = '@' + channel_username
            
            try:
                chat = await self.bot_app.bot.get_chat(channel_username)
                channel_id = chat.id
                channel_title = chat.title
                channel_username_clean = chat.username
            except Exception as e:
                return False, f"❌ Could not find channel. Make sure the username/link is correct.\n\nError: {str(e)}"
            
            try:
                admins = await self.bot_app.bot.get_chat_administrators(channel_id)
                bot_info = await self.bot_app.bot.get_me()
                is_admin = any(admin.user.id == bot_info.id for admin in admins)
                
                if not is_admin:
                    return False, "❌ Bot is not an admin in this channel. Please add the bot as an admin first."
            except Exception as e:
                return False, f"❌ Could not verify admin status.\n\nError: {str(e)}"
            
            self.db.set_user_logs_channel(user_id, channel_id, channel_title, channel_username_clean)
            
            return True, f"✅ Logs channel set successfully!\n\n📢 Channel: {channel_title}\n🔗 @{channel_username_clean}"
        
        except Exception as e:
            self.db.log_event("ERROR", f"Failed to setup logs channel for user {user_id}: {str(e)}")
            return False, f"Error: {str(e)}"
    
    async def send_forward_log(self, user_id: int, group_name: str, message_link: str, group_link: str = None):
        """
        Send a forwarding success log to user's logs channel.
        
        Args:
            user_id: Telegram user ID
            group_name: Name of the group where message was forwarded
            message_link: Link to the forwarded message
            group_link: Optional link to the group
        """
        try:
            logs_channel = self.db.get_user_logs_channel(user_id)
            if not logs_channel or not logs_channel.get('channel_id'):
                return
            
            timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            
            log_text = (
                "✅ *Message Sent Successfully*\n\n"
                f"📨 Message Link: {message_link}\n"
                f"👥 Group Name: {group_name}\n"
                f"📅 Time: {timestamp}"
            )
            
            if group_link and group_link != "N/A":
                log_text += f"\n🔗 Group Link: {group_link}"
            
            await self.bot_app.bot.send_message(
                chat_id=logs_channel['channel_id'],
                text=log_text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
        
        except Exception as e:
            self.db.log_event("ERROR", f"Failed to send log for user {user_id}: {str(e)}")
    
    async def test_logs_channel(self, user_id: int) -> Tuple[bool, str]:
        """Send a test message to user's logs channel."""
        try:
            logs_channel = self.db.get_user_logs_channel(user_id)
            if not logs_channel:
                return False, "❌ No logs channel configured."
            
            test_message = (
                "🧪 *Test Message*\n\n"
                "This is a test message from your Synax AD BOT Bot.\n"
                "If you see this, your logs channel is configured correctly!"
            )
            
            await self.bot_app.bot.send_message(
                chat_id=logs_channel['channel_id'],
                text=test_message,
                parse_mode=ParseMode.MARKDOWN
            )
            
            return True, f"✅ Test message sent to {logs_channel['channel_title']}!"
        
        except Exception as e:
            return False, f"❌ Failed to send test message: {str(e)}"
    
    def get_logs_channel_info(self, user_id: int) -> Optional[str]:
        """Get formatted logs channel info for a user."""
        logs_channel = self.db.get_user_logs_channel(user_id)
        if not logs_channel:
            return None
        
        info = f"📢 *Current Logs Channel:*\n"
        info += f"Title: {logs_channel['channel_title']}\n"
        if logs_channel.get('channel_username'):
            info += f"Username: @{logs_channel['channel_username']}\n"
        info += f"ID: `{logs_channel['channel_id']}`"
        
        return info


class LoggingBotManager:
    """Manages logging bot functionality where users provide their own bot token"""
    
    def __init__(self, db_instance):
        self.db = db_instance
        self.user_bots = {}
        self.pending_log_setups = {}
    
    async def configure_mandatory_log_bot(self, token, admin_id):
        token=(token or '').strip()
        if not token: return False, '❌ Token is empty.'
        try:
            from telegram import Bot
            bot=Bot(token=token)
            me=await bot.get_me()
            username=me.username or str(me.id)
            await bot.send_message(admin_id, '✅ <b>Mandatory Log Bot connected.</b>\n\nAds will stay locked unless this logger is configured. Logs are grouped per cycle to prevent spam.', parse_mode=ParseMode.HTML)
            self.db.set_mandatory_log_bot(token, username)
            self.user_bots[token]=bot
            return True, f'✅ Mandatory Log Bot @{username} is ready.'
        except Exception as e:
            return False, f'❌ Logger setup failed. Start the logger bot with /start first.\n\n{str(e)[:250]}'

    def mandatory_log_bot_ready(self):
        return bool(self.db.get_mandatory_log_bot())

    async def send_compact_cycle_log(self, user_id, total_targets, successful, failed, flood_wait, cycle_no):
        cfg=self.db.get_mandatory_log_bot()
        if not cfg: return
        try:
            token=cfg['bot_token']
            if token not in self.user_bots:
                from telegram import Bot
                self.user_bots[token]=Bot(token=token)
            phone=self.db.fetch_one('SELECT phone_number FROM userbot_session WHERE user_id=? AND is_active=1 LIMIT 1',(user_id,))
            phone=phone[0] if phone and phone[0] else str(user_id)
            status='complete' if failed == 0 else 'incomplete'
            text=(f'📊 <b>Log of:</b> <code>{html.escape(str(phone))}</code>\n'
                  f'<b>Cycle number:</b> {cycle_no}\n'
                  f'<b>Status:</b> <i>{status}</i>\n\n'
                  f'<b>Target groups:</b> {total_targets}\n\n'
                  f'<b>Successful:</b> {successful} ✅\n'
                  f'<b>Failed:</b> {failed} ❌\n'
                  f'<b>Flood wait:</b> {flood_wait} ⏳\n'
                  f'<b>Auto replied:</b> 0 💬\n\n'
                  '🚀 <b>Broadcast cycle completed. Final logs have been updated ♻️</b>')
            admin_id=int(self.db.get_setting('admin_user_id','0'))
            await self.user_bots[token].send_message(admin_id,text,parse_mode=ParseMode.HTML)
        except Exception as e:
            self.db.log_event('ERROR',f'Compact logger failed: {e}')

    async def validate_bot_token(self, bot_token: str, user_id: int) -> Tuple[bool, str, Optional[object]]:
        """
        Validate bot token and check if user has started the bot.
        
        Returns:
            Tuple of (is_valid, message, bot_instance)
        """
        try:
            from telegram import Bot
            test_bot = Bot(token=bot_token)
            
            try:
                bot_info = await test_bot.get_me()
                bot_username = bot_info.username
            except Exception as e:
                return False, f"❌ Invalid bot token. Error: {str(e)}", None
            
            try:
                await test_bot.send_message(
                    chat_id=user_id,
                    text="✅ Bot connected successfully! You can now configure where to receive logs."
                )
                return True, f"✅ Bot @{bot_username} is valid and you have started it!", test_bot
            except Exception as e:
                return False, f"❌ Bot token is valid but you haven't started the bot yet.\n\nPlease start @{bot_username} and try again.", None
                
        except Exception as e:
            return False, f"❌ Error validating bot token: {str(e)}", None
    
    async def setup_destination_with_link(self, user_id: int, bot_token: str, destination_link: str) -> Tuple[bool, str]:
        """
        Enhanced setup for private groups/channels. Accepts link and prompts for chat ID.
        
        Args:
            user_id: Telegram user ID  
            bot_token: User's bot token
            destination_link: Group/channel link (can be private invite link)
        
        Returns:
            Tuple of (success, message)
        """
        self.pending_log_setups[user_id] = {
            'bot_token': bot_token,
            'link': destination_link,
            'step': 'awaiting_chat_id'
        }
        
        return True, (
            "📝 *Link received!*\n\n"
            "Since your bot can't join via private links directly, please provide the **Chat ID** of this group/channel.\n\n"
            "To get the Chat ID:\n"
            "1. Forward any message from that group/channel to @RawDataBot\n"
            "2. Copy the `chat.id` number (e.g., -1001234567890)\n"
            "3. Send it here\n\n"
            "Example: `-1001234567890`"
        )
    
    async def setup_destination_with_chat_id(self, user_id: int, chat_id_str: str) -> Tuple[bool, str]:
        """
        Verify bot admin status using provided chat ID and complete setup.
        
        Args:
            user_id: Telegram user ID
            chat_id_str: Chat ID provided by user
        
        Returns:
            Tuple of (success, message)
        """
        if user_id not in self.pending_log_setups:
            return False, "❌ No pending log bot setup found. Please start from the beginning."
        
        setup_data = self.pending_log_setups[user_id]
        bot_token = setup_data['bot_token']
        
        try:
            chat_id = int(chat_id_str.strip())
        except ValueError:
            return False, "❌ Invalid Chat ID format. Please provide a number (e.g., -1001234567890)"
        
        try:
            from telegram import Bot
            logging_bot = Bot(token=bot_token)
            
            try:
                chat = await logging_bot.get_chat(chat_id)
                dest_id = chat.id
                dest_title = chat.title or chat.first_name or "Unknown"
                dest_username = chat.username
            except Exception as e:
                return False, f"❌ Could not access this chat. Error: {str(e)}\n\nMake sure the bot is added as a member/admin."
            
            try:
                admins = await logging_bot.get_chat_administrators(dest_id)
                bot_info = await logging_bot.get_me()
                is_admin = any(admin.user.id == bot_info.id for admin in admins)
                
                if not is_admin:
                    return False, (
                        f"❌ The bot is not an admin in **{dest_title}**.\n\n"
                        "Please:\n"
                        "1. Add the bot as an admin\n"
                        "2. Give it permission to send messages\n"
                        "3. Try again"
                    )
                
                can_send = any(
                    admin.user.id == bot_info.id and 
                    (admin.can_post_messages if hasattr(admin, 'can_post_messages') else True)
                    for admin in admins
                )
                
                if not can_send:
                    return False, (
                        f"⚠️ Bot is admin in **{dest_title}** but lacks send message permissions.\n\n"
                        "Please grant the bot permission to send messages and try again."
                    )
                    
            except Exception as e:
                return False, f"❌ Could not verify admin status. Error: {str(e)}"
            
            test_message = (
                "✅ *Logs Bot Configured Successfully!*\n\n"
                "📨 Forwarding logs will be sent here.\n\n"
                "Format:\n"
                "• Success: Ad Messages Successfully Sent To [Group] [Link]\n"
                "• Failure: Ad Message was Unable to send on [Group] cuz of [Error]"
            )
            
            try:
                await logging_bot.send_message(
                    chat_id=dest_id,
                    text=test_message,
                    parse_mode=ParseMode.MARKDOWN
                )
                
                self.db.set_user_logging_bot(
                    user_id=user_id,
                    bot_token=bot_token,
                    destination_type='private_group',
                    destination_id=dest_id,
                    destination_title=dest_title,
                    destination_username=dest_username
                )
                
                del self.pending_log_setups[user_id]
                return True, f"✅ Logging bot configured! Logs will be sent to **{dest_title}**."
            except Exception as e:
                return False, f"❌ Failed to send test message: {str(e)}"
            
        except Exception as e:
            return False, f"❌ Error: {str(e)}"
    
    async def setup_destination(self, user_id: int, bot_token: str, destination_type: str, destination_input: str = None) -> Tuple[bool, str]:
        """
        Setup log destination for user's logging bot.
        
        Args:
            user_id: Telegram user ID
            bot_token: User's bot token
            destination_type: 'dm', 'channel', 'group', or 'private'
            destination_input: Channel/group username, link, or chat ID
        
        Returns:
            Tuple of (success, message)
        """
        try:
            from telegram import Bot
            logging_bot = Bot(token=bot_token)
            
            if destination_type == 'dm':
                test_message = (
                    "✅ *Logs Bot Configured Successfully!*\n\n"
                    "📨 You will receive forwarding logs directly in your DM.\n\n"
                    "Format:\n"
                    "• Success: Ad Messages Successfully Sent To [Group] [Link]\n"
                    "• Failure: Ad Message was Unable to send on [Group] cuz of [Error]"
                )
                
                try:
                    await logging_bot.send_message(
                        chat_id=user_id,
                        text=test_message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    self.db.set_user_logging_bot(
                        user_id=user_id,
                        bot_token=bot_token,
                        destination_type='dm',
                        destination_id=user_id
                    )
                    
                    return True, "✅ Logging bot configured! You'll receive logs in your DM."
                except Exception as e:
                    return False, f"❌ Failed to send test message: {str(e)}"
            
            elif destination_type == 'private':
                if not destination_input:
                    return False, "❌ Please provide the private group/channel link."
                return await self.setup_destination_with_link(user_id, bot_token, destination_input)
            
            elif destination_type in ['channel', 'group']:
                if not destination_input:
                    return False, "❌ Please provide channel/group username, link, or chat ID."
                
                dest_input = destination_input.strip()
                
                try:
                    if dest_input.lstrip('-').isdigit():
                        chat_id_to_check = int(dest_input)
                        chat = await logging_bot.get_chat(chat_id_to_check)
                    elif dest_input.startswith('https://t.me/+') or dest_input.startswith('t.me/+') or '+' in dest_input:
                        return await self.setup_destination_with_link(user_id, bot_token, dest_input)
                    elif dest_input.startswith('https://t.me/'):
                        username_part = dest_input.split('/')[-1]
                        if username_part.startswith('+'):
                            return await self.setup_destination_with_link(user_id, bot_token, dest_input)
                        dest_username = '@' + username_part if not username_part.startswith('@') else username_part
                        chat = await logging_bot.get_chat(dest_username)
                    elif dest_input.startswith('@'):
                        chat = await logging_bot.get_chat(dest_input)
                    else:
                        chat = await logging_bot.get_chat('@' + dest_input)
                    
                    dest_id = chat.id
                    dest_title = chat.title or chat.first_name
                    dest_username_clean = chat.username
                except Exception as e:
                    return False, f"❌ Could not find {destination_type}. Make sure the bot has been added as admin and the username/ID is correct. Error: {str(e)}"
                
                try:
                    admins = await logging_bot.get_chat_administrators(dest_id)
                    bot_info = await logging_bot.get_me()
                    is_admin = any(admin.user.id == bot_info.id for admin in admins)
                    
                    if not is_admin:
                        return False, f"❌ Bot is not an admin in this {destination_type}. Please add the bot as an admin first."
                except Exception as e:
                    return False, f"❌ Could not verify admin status. Error: {str(e)}"
                
                test_message = (
                    f"✅ *Logs Bot Configured Successfully!*\n\n"
                    f"📨 Forwarding logs will be sent to this {destination_type}.\n\n"
                    "Format:\n"
                    "• Success: Ad Messages Successfully Sent To [Group] [Link]\n"
                    "• Failure: Ad Message was Unable to send on [Group] cuz of [Error]"
                )
                
                try:
                    await logging_bot.send_message(
                        chat_id=dest_id,
                        text=test_message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    self.db.set_user_logging_bot(
                        user_id=user_id,
                        bot_token=bot_token,
                        destination_type=destination_type,
                        destination_id=dest_id,
                        destination_title=dest_title,
                        destination_username=dest_username_clean
                    )
                    
                    return True, f"✅ Logging bot configured! Logs will be sent to {dest_title}."
                except Exception as e:
                    return False, f"❌ Failed to send test message: {str(e)}"
            
            return False, "❌ Invalid destination type."
            
        except Exception as e:
            return False, f"❌ Error: {str(e)}"
    
    async def send_log(self, user_id: int, success: bool, group_name: str, message_link: str = None, error: str = None):
        """
        Send forwarding log to ALL user's configured logging destinations (Channel, Group, DM, or any combination).
        
        Args:
            user_id: Telegram user ID
            success: Whether forwarding was successful
            group_name: Name of the group
            message_link: Link to the forwarded message (for success)
            error: Error message (for failure)
        """
        try:
            # Suppress logging for "User not found" errors (silent failure - no logs sent)
            if not success and error and "User not found" in str(error):
                return
            
            destinations = self.db.get_user_logging_destinations(user_id)
            if not destinations:
                return
            
            import pytz
            user_tz_str = self.db.get_user_timezone(user_id)
            try:
                if user_tz_str.startswith('+') or user_tz_str.startswith('-'):
                    hours = int(user_tz_str[1:3])
                    minutes = int(user_tz_str[4:6]) if len(user_tz_str) > 4 else 0
                    offset_seconds = (hours * 3600 + minutes * 60)
                    if user_tz_str.startswith('-'):
                        offset_seconds = -offset_seconds
                    user_tz = timezone(timedelta(seconds=offset_seconds))
                else:
                    user_tz = timezone.utc
            except:
                user_tz = timezone.utc
            
            timestamp = datetime.now(user_tz).strftime(f'%Y-%m-%d %H:%M:%S {user_tz_str}')
            
            if success:
                log_text = f"✅ Ad Messages Successfully Sent To {group_name}"
                if message_link:
                    log_text += f" {message_link}"
                log_text += f"\n📅 {timestamp}"
            else:
                error_msg = error or "Unknown error"
                log_text = f"❌ Ad Message was Unable to send on {group_name} cuz of {error_msg}\n📅 {timestamp}"
            
            # Send to ALL destinations in parallel
            async def send_to_destination(dest):
                try:
                    bot_token = dest['bot_token']
                    destination_id = dest['destination_id']
                    dest_type = dest['destination_type']
                    
                    from telegram import Bot
                    if bot_token not in self.user_bots:
                        self.user_bots[bot_token] = Bot(token=bot_token)
                    
                    logging_bot = self.user_bots[bot_token]
                    
                    await logging_bot.send_message(
                        chat_id=destination_id,
                        text=log_text,
                        disable_web_page_preview=True
                    )
                    print(f"[LOG] ✅ Sent to {dest_type}: {destination_id}")
                except Exception as e:
                    print(f"[LOG] ❌ Failed to send to {dest_type}: {str(e)}")
            
            # Send to all destinations in parallel
            await asyncio.gather(*[send_to_destination(dest) for dest in destinations], return_exceptions=True)
            print(f"[LOGGING] ✅ Log sent to {len(destinations)} destination(s) for user {user_id}")
            
        except Exception as e:
            self.db.log_event("ERROR", f"Failed to send logs for user {user_id}: {str(e)}")
    
    async def test_multi_destination_logging(self, user_id: int) -> Tuple[bool, str]:
        """Test function: Add test destinations and verify multi-destination logging works."""
        try:
            print(f"\n[TEST] Starting multi-destination logging test for user {user_id}")
            
            # Step 1: Get user's bot token
            existing_bots = self.db.get_user_logging_destinations(user_id)
            if not existing_bots:
                return False, "❌ No logging bots configured. Add a bot first."
            
            bot_token = existing_bots[0]['bot_token']
            print(f"[TEST] Using bot token from existing destination")
            
            # Step 2: Verify all destinations exist
            destinations = self.db.get_user_logging_destinations(user_id)
            if not destinations:
                return False, "❌ No destinations found"
            
            print(f"[TEST] Found {len(destinations)} configured destination(s):")
            for i, dest in enumerate(destinations, 1):
                print(f"  {i}. {dest['destination_type'].upper()}: {dest.get('destination_title', 'N/A')}")
            
            # Step 3: Send a test log to all destinations
            print(f"[TEST] Sending test log to all {len(destinations)} destination(s)...")
            await self.logging_bot_manager.send_log(
                user_id=user_id,
                success=True,
                group_name="🧪 TEST GROUP",
                message_link="https://t.me/test/999"
            )
            
            print(f"[TEST] ✅ Test log sent successfully to {len(destinations)} destination(s)")
            
            result_msg = (
                f"✅ **Multi-Destination Logging Test PASSED**\n\n"
                f"Destinations tested: {len(destinations)}\n\n"
            )
            for i, dest in enumerate(destinations, 1):
                result_msg += f"{i}. {dest['destination_type'].upper()}: {dest.get('destination_title', 'Unknown')}\n"
            
            result_msg += "\n📨 Check all your destinations - you should have received a test message!"
            return True, result_msg
            
        except Exception as e:
            error_msg = f"❌ Test failed: {str(e)}"
            print(f"[TEST] {error_msg}")
            return False, error_msg


class UserbotManager:
    def __init__(self, database: Database):
        self.db = database
        self.client: Optional[TelegramClient] = None
        self.is_authenticated = False
        self.session_file = os.environ.get("ADBOT_SESSION", "userbot_session")

    
    async def add_userbot(self, api_id: int, api_hash: str, phone_number: str, user_id: int = None) -> Tuple[bool, str, int]:
        """Add a new userbot session. Returns (success, message, row_id)."""
        try:
            # Remove existing session
            await self.remove_userbot()
            
            # Create new client
            self.client = TelegramClient(self.session_file, api_id, api_hash)
            await self.client.connect()
            
            # Send code request
            await self.client.send_code_request(phone_number)
            
            # Store session info - include user_id if provided
            if user_id:
                self.db.execute_query(
                    "INSERT OR REPLACE INTO userbot_session (user_id, api_id, api_hash, phone_number, is_active) VALUES (?, ?, ?, ?, 0)",
                    (user_id, api_id, api_hash, phone_number)
                )
                # Get the row ID that was just inserted
                result = self.db.execute_query(
                    "SELECT id FROM userbot_session WHERE user_id = ? AND phone_number = ?",
                    (user_id, phone_number)
                )
                row_id = result[0][0] if result else None
            else:
                self.db.execute_query(
                    "INSERT OR REPLACE INTO userbot_session (id, api_id, api_hash, phone_number, is_active) VALUES (1, ?, ?, ?, 0)",
                    (api_id, api_hash, phone_number)
                )
                row_id = 1
            
            return True, "Code sent! Please provide the OTP code.", row_id
            
        except Exception as e:
            self.db.log_event("ERROR", f"Failed to add userbot: {str(e)}")
            return False, f"Error: {str(e)}", None
        
    async def restore_session(self):
        """Restore userbot session from database and session file on bot startup."""
        import os
        
        # First try to restore ANY active userbot from database (not just id=1)
        session_data = self.db.execute_query(
            "SELECT api_id, api_hash, phone_number, is_active, id FROM userbot_session WHERE is_active = 1 LIMIT 1"
        )
        
        # If no database record but session file exists, try to load from session file directly
        session_file_exists = os.path.exists(f"{self.session_file}.session")
        
        if not session_data and session_file_exists:
            print("[Userbot] Session file found! Loading from provided session file...")
            try:
                # Use placeholder API credentials - Telethon will use session file credentials
                # These are required to create the client, but won't override session file data
                api_id = 17349  # Placeholder
                api_hash = "344583e45741c457eab40180ab0105b5"  # Placeholder
                
                self.client = TelegramClient(self.session_file, api_id, api_hash)
                await self.client.connect()
                
                if await self.client.is_user_authorized():
                    self.is_authenticated = True
                    print("[Userbot] ✅ Session file loaded and authenticated!")
                    
                    # Get user info and store in database
                    me = await self.client.get_me()
                    # Use admin as user_id if loading from session file
                    self.db.execute_query(
                        "INSERT OR REPLACE INTO userbot_session (user_id, api_id, api_hash, phone_number, is_active, last_activity) VALUES (?, ?, ?, ?, 1, ?)",
                        (1, api_id, api_hash, me.phone or "unknown", datetime.now())
                    )
                    
                    await self.start_monitoring()
                    print(f"[Userbot] Connected as: {me.first_name}")
                else:
                    print("[Userbot] Session file found but not authorized.")
                return
            except Exception as e:
                print(f"[Userbot] Could not load session file: {e}")
                return
        
        # Original logic for database records
        if not session_data:
            return  # No session to restore

        api_id, api_hash, phone_number, is_active, row_id = session_data[0]
        if not is_active:
            return  # Userbot was not logged in previously

        try:
            self.client = TelegramClient(self.session_file, api_id, api_hash)
            await self.client.connect()
            if await self.client.is_user_authorized():
                self.is_authenticated = True
                await self.start_monitoring()
                print("[Userbot] Restored previous session and connected.")
            else:
                print("[Userbot] Session file found but not authorized. Please re-login.")
        except Exception as e:
            err = str(e).lower()
            if "wrong session" in err or "security error" in err or "session" in err:
                print(f"[Userbot] ⚠️ Session corrupted, clearing: {e}")
                self.is_authenticated = False
                self.client = None
                import os, glob
                for f in glob.glob(f"{self.session_file}*"):
                    try: os.remove(f)
                    except: pass
                self.db.execute_query("UPDATE userbot_session SET is_active = 0")
            else:
                print(f"[Userbot] Could not auto-restore userbot: {e}")
    
    async def verify_code(self, phone_number: str, code: str, password: str = None, row_id: int = None) -> Tuple[bool, str]:
        """Verify OTP code and complete authentication."""
        try:
            if not self.client:
                return False, "No active session found."

            try:
                # Step 1: Try signing in with phone and code
                await self.client.sign_in(phone_number, code)
            except SessionPasswordNeededError:
                if not password:
                    return False, "Two-factor authentication required. Please provide your password."
                # Step 2: Sign in using only the password (after code is accepted)
                await self.client.sign_in(password=password)

            # Final check
            if await self.client.is_user_authorized():
                self.is_authenticated = True
                # Use provided row_id, fallback to id=1 for backward compatibility
                where_clause = f"id = {row_id}" if row_id else "id = 1"
                self.db.execute_query(
                    f"UPDATE userbot_session SET is_active = 1, last_activity = ? WHERE {where_clause}",
                    (datetime.now(),)
                )
                
                # Update bio and last name from admin settings
                try:
                    from telethon.tl.functions.account import UpdateProfileRequest
                    default_bio = self.db.get_admin_setting('default_bio', 'Hosted By @SynaxBaby')
                    default_lastname = self.db.get_admin_setting('default_lastname', 'Hosted By @SynaxBaby')
                    
                    await self.client(UpdateProfileRequest(
                        about=default_bio,
                        last_name=default_lastname
                    ))
                    print(f"[Userbot] Bio and last name updated: {default_bio} | {default_lastname}")
                except Exception as e:
                    print(f"[Userbot] Failed to update bio/lastname: {e}")
                
                await self.start_monitoring()
                print("[Userbot] Authenticated and monitoring started!")
                return True, "✅ Userbot authenticated successfully!"
            else:
                return False, "Authentication failed."

        except PhoneCodeInvalidError:
            return False, "Invalid verification code."
        except Exception as e:
            self.db.log_event("ERROR", f"Verification failed: {str(e)}")
            return False, f"Error: {str(e)}"
    
    async def remove_userbot(self) -> bool:
        """Remove the current userbot session."""
        try:
            self.is_authenticated = False
            if self.client:
                try:
                    await self.client.disconnect()
                except:
                    pass
                self.client = None
            
            # Clear sessions from DB
            self.db.execute_query("DELETE FROM userbot_session")
            self.db.execute_query("DELETE FROM groups")
            
            # Remove session files
            import os, glob
            for f in glob.glob(f"{self.session_file}*"):
                try:
                    os.remove(f)
                except:
                    pass
            
            print("[Userbot] ✅ Session removed successfully.")
            return True
            
        except Exception as e:
            self.db.log_event("ERROR", f"Failed to remove userbot: {str(e)}")
            print(f"[Userbot] ❌ Remove failed: {e}")
            return False
    
    async def start_monitoring(self):
        """Start monitoring userbot status, handle AFK auto-reply, and enforce branding protection."""
        if not self.client or not self.is_authenticated:
            return
        
        self.branding_task = asyncio.create_task(self._enforce_branding_protection())

        @self.client.on(events.NewMessage(incoming=True))
        async def handler(event):
            self.db.execute_query(
                "UPDATE userbot_session SET last_activity = ? WHERE id = 1",
                (datetime.now(),)
            )

            if event.is_private and not event.out:
                message_text = event.message.message if event.message else ""
                
                if message_text and message_text.startswith('/'):
                    return
                
                sender = await event.get_sender()
                if sender and getattr(sender, 'bot', False):
                    return
                
                # Get userbot owner from userbot_session table (the user this userbot belongs to)
                userbot_owner_result = self.db.execute_query(
                    "SELECT user_id FROM userbot_session WHERE is_active = 1 LIMIT 1"
                )
                if not userbot_owner_result:
                    return
                
                userbot_owner_id = userbot_owner_result[0][0]
                afk_enabled = self.db.get_user_setting(userbot_owner_id, "afk_enabled", "off")
                afk_message = self.db.get_user_setting(userbot_owner_id, "afk_message", "")
                sender_id = event.sender_id

                if (
                    afk_enabled == "on"
                    and userbot_owner_id
                    and sender_id != userbot_owner_id
                    and afk_message
                ):
                    last_reply_time = self.db.get_afk_last_reply_time(sender_id)
                    now = datetime.now()

                    if not last_reply_time or (now - last_reply_time).total_seconds() >= 7200:
                        await event.reply(afk_message)
                        self.db.set_afk_last_reply_time(sender_id, now)
    
    async def _enforce_branding_protection(self):
        """Monitor and enforce mandatory bio and last name branding with aggressive keep-alive heartbeat."""
        if not self.client or not self.is_authenticated:
            return
        
        while self.is_authenticated:
            try:
                await asyncio.sleep(5)
                
                if not self.client or not self.is_authenticated:
                    break
                
                try:
                    me = await self.client.get_me()
                except (ConnectionError, RuntimeError) as e:
                    print(f"[Userbot] Connection lost, attempting to reconnect: {e}")
                    try:
                        await self.client.connect()
                        print("[Userbot] Successfully reconnected!")
                    except Exception as reconnect_err:
                        self.is_authenticated = False
                        print(f"[Userbot] Failed to reconnect - userbot offline: {reconnect_err}")
                        break
                    continue
                except Exception as e:
                    print(f"[Userbot] Keep-alive error (will retry): {type(e).__name__}")
                    continue
                
                mandatory_lastname = self.db.get_admin_setting('default_lastname', 'Hosted By @SynaxBaby')
                mandatory_bio = self.db.get_admin_setting('default_bio', 'Hosted By @SynaxBaby')
                
                current_lastname = me.last_name or ""
                
                from telethon.tl.functions.users import GetFullUserRequest
                try:
                    full_user = await self.client(GetFullUserRequest(me))
                    current_bio = full_user.full_user.about or ""
                except:
                    current_bio = ""
                
                lastname_needs_fix = not current_lastname.endswith(mandatory_lastname)
                bio_needs_fix = not current_bio.endswith(mandatory_bio)
                
                if lastname_needs_fix or bio_needs_fix:
                    from telethon.tl.functions.account import UpdateProfileRequest
                    
                    new_lastname = current_lastname
                    new_bio = current_bio
                    
                    if lastname_needs_fix:
                        if mandatory_lastname not in current_lastname:
                            new_lastname = f"{current_lastname} {mandatory_lastname}".strip()
                        else:
                            new_lastname = mandatory_lastname
                    
                    if bio_needs_fix:
                        if mandatory_bio not in current_bio:
                            new_bio = f"{current_bio}\n{mandatory_bio}".strip()
                        else:
                            new_bio = mandatory_bio
                    
                    try:
                        await self.client(UpdateProfileRequest(
                            last_name=new_lastname if lastname_needs_fix else None,
                            about=new_bio if bio_needs_fix else None
                        ))
                        
                        owner_id_str = self.db.get_setting("admin_user_id", "")
                        if owner_id_str.isdigit():
                            owner_id = int(owner_id_str)
                            warning_msg = (
                                "⚠️ *Profile Update Notice*\n\n"
                                "Your userbot profile was automatically updated to maintain required branding:\n\n"
                            )
                            if lastname_needs_fix:
                                warning_msg += f"• Last Name: Restored mandatory text\n"
                            if bio_needs_fix:
                                warning_msg += f"• Bio: Restored mandatory text\n"
                            warning_msg += (
                                "\n_Please do not remove the mandatory branding text from your profile. "
                                "You may add your own text, but the required branding must remain visible._"
                            )
                            
                            try:
                                await self.client.send_message(owner_id, warning_msg)
                            except:
                                pass
                        
                        print(f"[Branding Protection] Profile updated - Last Name: {lastname_needs_fix}, Bio: {bio_needs_fix}")
                    except Exception as e:
                        print(f"[Branding Protection] Failed to update profile: {e}")
                        
            except Exception as e:
                print(f"[Branding Protection] Monitoring error: {e}")
                await asyncio.sleep(60)
    

    async def get_status(self) -> Dict:
        """Get current userbot status."""
        if not self.client or not self.is_authenticated:
            return {
                "status": "❌ Disconnected",
                "last_activity": "Never",
                "user_info": "Not authenticated"
            }
        
        try:
            # Get user info
            me = await self.client.get_me()
            
            # Get last activity
            result = self.db.execute_query(
                "SELECT last_activity FROM userbot_session WHERE id = 1"
            )
            last_activity = result[0][0] if result else "Unknown"
            
            return {
                "status": "✅ Connected",
                "last_activity": last_activity,
                "user_info": f"@{me.username}" if me.username else me.first_name
            }
            
        except Exception as e:
            return {
                "status": "❌ Error",
                "last_activity": "Unknown",
                "user_info": f"Error: {str(e)}"
            }
    
    async def fetch_groups(self, user_id: int) -> Dict:
        """Fetch all groups and forums the userbot is member of, and count new vs existing."""
        if not self.client or not self.is_authenticated:
            return {"groups": [], "new": 0, "existing": 0, "total": 0}

        try:
            groups = []
            new_count = 0
            existing_count = 0
            seen_ids = set()

            async for dialog in self.client.iter_dialogs():
                entity = dialog.entity
                title = dialog.title
                username = getattr(entity, "username", None)

                # Determine type
                if isinstance(entity, Chat):
                    chat_type = "basic_group"
                elif isinstance(entity, Channel):
                    if getattr(entity, "broadcast", False):
                        chat_type = "channel"
                    elif getattr(entity, "megagroup", False):
                        chat_type = "forum" if getattr(entity, "forum", False) else "supergroup"
                    else:
                        chat_type = "unknown"
                else:
                    continue  # skip if not group or channel

                chat_id = entity.id
                if chat_id in seen_ids:
                    continue  # avoid duplicates from dialogs pointing to same chat
                seen_ids.add(chat_id)

                chat_info = {
                    "id": chat_id,
                    "title": title,
                    "username": username,
                    "type": chat_type
                }
                groups.append(chat_info)

                # Check if already in database for this user
                existing = self.db.fetch_one("SELECT is_selected FROM groups WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
                if existing:
                    existing_count += 1
                    # Update group info while preserving is_selected status
                    self.db.execute_query(
                        "UPDATE groups SET title = ?, username = ?, chat_type = ? WHERE user_id = ? AND chat_id = ?",
                        (title, username, chat_type, user_id, chat_id)
                    )
                else:
                    new_count += 1
                    # Insert new group with is_selected = 1 (selected by default)
                    self.db.execute_query(
                        "INSERT INTO groups (user_id, chat_id, title, username, chat_type, is_selected) VALUES (?, ?, ?, ?, ?, 1)",
                        (user_id, chat_id, title, username, chat_type)
                    )

            return {
                "groups": groups,
                "new": new_count,
                "existing": existing_count,
                "total": new_count + existing_count
            }

        except Exception as e:
            self.db.log_event("ERROR", f"Failed to fetch groups: {str(e)}")
            return {"groups": [], "new": 0, "existing": 0, "total": 0}
    
    async def join_group(self, group_link: str, user_id: int) -> Tuple[bool, str]:
        """Join a group using invite link or username."""
        if not self.client or not self.is_authenticated:
            return False, "Userbot not authenticated."
        
        try:
            # Parse different link formats
            if group_link.startswith('@'):
                entity = await self.client.get_entity(group_link)
            elif 'joinchat' in group_link:
                # Extract invite hash
                invite_hash = group_link.split('/')[-1]
                entity = await self.client.get_entity(f"https://t.me/joinchat/{invite_hash}")
            elif 't.me/' in group_link:
                # Extract username
                username = group_link.split('/')[-1]
                entity = await self.client.get_entity(f"@{username}")
            else:
                return False, "Invalid group link format."
            
            # Join the group
            await self.client(functions.channels.JoinChannelRequest(entity))
            
            # Add to database for this user
            self.db.execute_query(
                "INSERT OR REPLACE INTO groups (user_id, chat_id, title, username, chat_type, is_selected) VALUES (?, ?, ?, ?, ?, 1)",
                (user_id, entity.id, entity.title, getattr(entity, 'username', None), 'channel' if hasattr(entity, 'broadcast') else 'group')
            )
            
            return True, f"✅ Successfully joined {entity.title}"
            
        except UserAlreadyParticipantError:
            return False, "Already a member of this group."
        except InviteHashExpiredError:
            return False, "Invite link has expired."
        except ChatAdminRequiredError:
            return False, "Admin rights required to join this group."
        except FloodWaitError as e:
            return False, f"Rate limited. Please wait {e.seconds} seconds."
        except Exception as e:
            self.db.log_event("ERROR", f"Failed to join group: {str(e)}")
            return False, f"Error: {str(e)}"

class ForwardingManager:
    def __init__(self, database: Database, userbot_manager: UserbotManager, bot: 'TelegramBot', user_id: int, logging_bot_manager: 'LoggingBotManager' = None):
        self.db = database
        self.userbot = userbot_manager
        self.bot = bot
        self.user_id = user_id
        self.logging_bot_manager = logging_bot_manager
        self.is_running = False
        self.is_paused = False
        self.forwarding_task = None
        self.current_cycle_id = None  # ⏱ Tracked per cycle (from DB)

        self.stats = {
            "total_forwarded": 0,
            "last_forward_time": None,
            "next_forward_time": None,
            "errors": 0
        }

        self.forward_index = 0
        self.forwarded_groups_set = set()

        # 🚀 Load duration settings
        self.hold_duration = int(self.db.get_setting("hold_duration", "15"))
        self.cycle_length = int(self.db.get_setting("cycle_length", "120"))

        # 🔁 Restore forwarding index
        try:
            self.forward_index = int(self.db.get_forwarding_state("forward_index", "0"))
        except Exception:
            self.forward_index = 0

        # 🌗 Restore phase and timestamp
        self.current_phase = self.db.get_forwarding_state("current_phase", "forwarding")
        phase_time_str = self.db.get_forwarding_state("phase_start_time")
        try:
            self.phase_start_time = datetime.fromisoformat(phase_time_str) if phase_time_str else datetime.now()
        except Exception:
            self.phase_start_time = datetime.now()

        # 🌐 Restore last cycle ID (deduplication scope)
        self.current_cycle_id = self.db.get_forwarding_state("current_cycle_id", None)

    def compute_message_hash(self, message) -> str:
        """Compute a hash of the message's content to detect duplicates across channels."""
        base = ""

        if message.message:
            base += message.message

        if message.media:
            media_repr = str(message.media)
            base += media_repr

        return hashlib.sha256(base.encode('utf-8')).hexdigest()

    async def get_group_topic_ids(self, chat_id: int) -> List[Tuple[int, str]]:
        """Get all available open forum topics for a chat with their titles.
        Returns list of (topic_id, title_lower) tuples."""
        try:
            entity = await self.userbot.client.get_entity(chat_id)
            if not (getattr(entity, "megagroup", False) and getattr(entity, "forum", False)):
                self.db.log_event("INFO", f"Chat {chat_id} is not a forum group")
                return []
        except Exception as e:
            self.db.log_event("ERROR", f"Failed to get entity for {chat_id}: {e}")
            return []

        open_topics = []
        
        try:
            result = await self.userbot.client(GetForumTopicsRequest(
                channel=chat_id,
                offset_date=None,
                offset_id=0,
                offset_topic=0,
                limit=100
            ))
            
            self.db.log_event("INFO", f"GetForumTopicsRequest returned {len(result.topics)} topics for {chat_id}")
            
            for topic in result.topics:
                if not isinstance(topic, ForumTopic):
                    continue
                
                topic_id = getattr(topic, "id", None)
                topic_title = getattr(topic, "title", "Unknown")
                is_closed = getattr(topic, "closed", False)
                is_hidden = getattr(topic, "hidden", False)
                
                self.db.log_event("INFO", f"Topic {topic_id} ({topic_title}): closed={is_closed}, hidden={is_hidden}")
                
                if not is_closed and not is_hidden and topic_id:
                    open_topics.append((topic_id, topic_title.lower()))
                    
        except Exception as e:
            self.db.log_event("ERROR", f"GetForumTopicsRequest failed for {chat_id}: {e}")
        
        if not open_topics:
            try:
                self.db.log_event("INFO", f"Trying to get topics from recent messages for {chat_id}")
                messages = await self.userbot.client.get_messages(chat_id, limit=50)
                
                found_topics = set()
                for msg in messages:
                    if hasattr(msg, 'reply_to') and msg.reply_to:
                        if hasattr(msg.reply_to, 'forum_topic') and msg.reply_to.forum_topic:
                            topic_id = getattr(msg.reply_to, 'reply_to_top_id', None)
                            if topic_id and topic_id not in found_topics:
                                found_topics.add(topic_id)
                                open_topics.append((topic_id, "unknown"))
                                self.db.log_event("INFO", f"Found topic {topic_id} from recent messages")
                
            except Exception as e:
                self.db.log_event("ERROR", f"Failed to get topics from messages for {chat_id}: {e}")
        
        if not open_topics:
            self.db.log_event("WARNING", f"No topics found via API, using fallback topic IDs for {chat_id}")
            for test_id in [1, 2]:
                open_topics.append((test_id, "general"))
        
        self.db.log_event("INFO", f"Final result: {len(open_topics)} open topics found for {chat_id}")
        return open_topics


    async def forward_to_forum_group(self, message, chat_id: int, group_title: str, group_link: str) -> bool:
        """Handle forwarding to a forum group with Instagram topic preference"""
        try:
            forward_mode = self.bot.get_forward_mode()

            topics = await self.get_group_topic_ids(chat_id)
            if not topics:
                self.db.log_event("WARNING", f"No valid forum topics found in {group_title}")
                return False

            instagram_topics = [(tid, title) for tid, title in topics if re.search(r'instagram|insta\b', title, re.IGNORECASE)]
            other_topics = [(tid, title) for tid, title in topics if not re.search(r'instagram|insta\b', title, re.IGNORECASE)]
            
            ordered_topics = instagram_topics + other_topics
            
            if instagram_topics:
                self.db.log_event("INFO", f"Found {len(instagram_topics)} Instagram topic(s) in {group_title}, prioritizing")
            
            for topic_tuple in ordered_topics:
                topic_id = topic_tuple[0]
                topic_title = topic_tuple[1]
                
                try:
                    # Check message limit before forwarding
                    can_forward, limit_msg = self.check_and_increment_message_count()
                    if not can_forward:
                        self.db.log_event("WARNING", f"Message limit reached for user {self.user_id}: {limit_msg}")
                        if self.logging_bot_manager:
                            try:
                                await self.logging_bot_manager.send_log(
                                    user_id=self.user_id,
                                    success=False,
                                    group_name=group_title,
                                    error=f"Message limit reached: {limit_msg}"
                                )
                            except:
                                pass
                        return False
                    
                    if forward_mode == "show":
                        await self.userbot.client(ForwardMessagesRequest(
                            from_peer=message.chat_id,
                            id=[message.id],
                            to_peer=chat_id,
                            top_msg_id=int(topic_id)
                        ))
                    else:
                        # Hide mode – native send
                        me = await self.userbot.client.get_me()
                        has_premium = getattr(me, "premium", False)

                        if message.media:
                            file = await message.download_media()
                            await self.userbot.client.send_file(
                                chat_id,
                                file,
                                caption=message.message,
                                formatting_entities=message.entities,
                                reply_to=int(topic_id)
                            )
                        elif message.text:
                            await self.userbot.client.send_message(
                                entity=chat_id,
                                message=message.message,
                                formatting_entities=message.entities,
                                reply_to=int(topic_id)
                            )

                        if not has_premium and message.text and "🪄" in message.text:
                            print("⚠️ Premium emoji may be downgraded (non-premium account)")

                    self.db.execute_query("DELETE FROM forward_trace WHERE forwarded_at < ?", 
                                        (datetime.now() - timedelta(hours=1),))
                    self.db.execute_query(
                        "INSERT INTO forward_trace (user_id, group_title, group_link, chat_id, message_id, forwarded_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (self.user_id, group_title, group_link, chat_id, message.id, datetime.now(timezone.utc).isoformat())
                    )
                    self.stats["total_forwarded"] += 1
                    self.stats["last_forward_time"] = datetime.now()
                    self.forwarded_groups_set.add(chat_id)
                    
                    if self.logging_bot_manager:
                        message_link = f"https://t.me/c/{str(chat_id).replace('-100', '')}/{message.id}/{topic_id}"
                        try:
                            await self.logging_bot_manager.send_log(
                                user_id=self.user_id,
                                success=True,
                                group_name=f"{group_title} (Forum)",
                                message_link=message_link
                            )
                        except Exception as e:
                            print(f"[LOG] Failed to send forum success log: {e}")
                    
                    return True

                except Exception as e:
                    error_msg = str(e)
                    self.db.log_event("ERROR", f"Failed to forward to topic {topic_id} in {group_title}: {e}")
                    continue

            self.db.log_event("WARNING", f"Failed to forward to any topic in forum {group_title}")
            if self.logging_bot_manager:
                try:
                    await self.logging_bot_manager.send_log(
                        user_id=self.user_id,
                        success=False,
                        group_name=group_title,
                        error="User not found"
                    )
                except:
                    pass
            return False

        except Exception as e:
            self.stats["errors"] += 1
            self.db.log_event("ERROR", f"General failure in forum forwarding for {group_title}: {e}")
            return False

    
    async def add_forwarding_message(self, message_link: str, user_id: int) -> Tuple[bool, str]:
        """Add a forwarding message after validating it exists - USER-SCOPED with admin limit."""
        try:
            # Get admin-configured message limit for this user
            user_data = self.db.execute_query(
                "SELECT message_limit FROM authorized_users WHERE user_id = ?",
                (user_id,)
            )
            max_messages = user_data[0][0] if user_data and user_data[0][0] is not None else 2
            
            # Enforce per-user message limit
            existing = self.db.execute_query("SELECT COUNT(*) FROM forwarding_messages WHERE user_id = ? AND is_active = 1", (user_id,))
            if existing[0][0] >= max_messages: 
                return False, f"❌ Maximum {max_messages} forwarding messages allowed for your account."

            # Parse link
            channel_id, message_id = self.parse_message_link(message_link)
            if not channel_id or not message_id:
                return False, "Invalid message link format."

            # Validate via userbot client
            if not self.userbot.client or not self.userbot.is_authenticated:
                return False, "Userbot not connected."

            message = await self.userbot.client.get_messages(channel_id, ids=message_id)
            if not message:
                return False, "❌ Message not found. Check the link or visibility."

            # Insert into DB with correct user_id
            self.db.execute_query(
                "INSERT INTO forwarding_messages (user_id, message_link, channel_id, message_id) VALUES (?, ?, ?, ?)",
                (user_id, message_link, channel_id, message_id)
            )
            return True, "✅ Forwarding message added successfully!"

        except Exception as e:
            self.db.log_event("ERROR", f"Failed to add forwarding message: {str(e)}")
            return False, f"Error: {str(e)}"
    
    def parse_message_link(self, link: str) -> Tuple[Optional[int], Optional[int]]:
        """Parse Telegram message link to extract channel and message ID."""
        try:
            # Pattern: https://t.me/channel_name/message_id
            pattern = r't\.me/([^/]+)/(\d+)'
            match = re.search(pattern, link)
            
            if match:
                channel_name = match.group(1)
                message_id = int(match.group(2))
                return channel_name, message_id
            
            return None, None
            
        except Exception:
            return None, None
    
    def remove_forwarding_message(self, message_id: int, user_id: int) -> bool:
        """Remove a forwarding message - USER-SCOPED."""
        try:
            self.db.execute_query(
                "UPDATE forwarding_messages SET is_active = 0 WHERE id = ? AND user_id = ?",
                (message_id, user_id)
            )
            return True
        except Exception:
            return False
    
    def get_forwarding_messages(self) -> List[Dict]:
        """Get all active forwarding messages for this user."""
        return self.db.get_forwarding_messages(self.user_id)
    
    def get_selected_groups(self) -> List[Dict]:
        """Get groups selected for forwarding for this user."""
        return self.db.get_selected_groups(self.user_id)
    
    def check_and_increment_message_count(self) -> Tuple[bool, str]:
        """Check if user has reached message limit and increment count if allowed. Admin has NO limits."""
        # Admin bypass - no message limits
        if self.user_id == self.bot.ADMIN_USER_ID:
            return True, "OK"
        
        try:
            # Get user's message limit
            user_data = self.db.execute_query(
                "SELECT message_limit, messages_sent_count FROM authorized_users WHERE user_id = ?",
                (self.user_id,)
            )
            
            if not user_data:
                return False, "User not found"
            
            message_limit, messages_sent = user_data[0]
            
            # Check if limit is reached (0 means unlimited)
            if message_limit > 0 and messages_sent >= message_limit:
                return False, f"Message limit reached ({messages_sent}/{message_limit})"
            
            # Increment the counter
            self.db.execute_query(
                "UPDATE authorized_users SET messages_sent_count = messages_sent_count + 1 WHERE user_id = ?",
                (self.user_id,)
            )
            
            return True, "OK"
        except Exception as e:
            self.db.log_event("ERROR", f"Message count check failed: {str(e)}")
            return True, "OK"  # Allow forwarding on error to avoid disruption
    
    async def start_forwarding(self) -> Tuple[bool, str]:
        # Free-dashboard mode: subscription/premium status is not a prerequisite.
        # Check only the operational requirements needed to start forwarding.
        if not self.userbot.is_authenticated:
            return False, "❌ Userbot not authenticated."

        messages = self.get_forwarding_messages()
        if not messages:
            return False, "❌ No forwarding messages configured."

        groups_enabled = self.db.get_user_setting(self.user_id, "ads_groups_enabled", "on") == "on"
        dms_enabled = self.db.get_user_setting(self.user_id, "ads_dms_enabled", "on") == "on"
        groups = self.get_selected_groups() if groups_enabled else []

        dm_targets = []
        if dms_enabled:
            try:
                # Use the actual Telethon dialog entity instead of only the numeric ID.
                # This is important for private chats: Telethon can resolve the correct
                # InputPeerUser from the dialog and forward to it reliably.
                me = await self.userbot.client.get_me()
                my_id = getattr(me, "id", None)
                async for dialog in self.userbot.client.iter_dialogs(ignore_migrated=True):
                    entity = dialog.entity
                    if not isinstance(entity, User):
                        continue
                    if getattr(entity, "bot", False) or getattr(entity, "deleted", False):
                        continue
                    if getattr(entity, "id", None) == my_id:
                        continue
                    try:
                        input_entity = await self.userbot.client.get_input_entity(entity)
                        dm_targets.append({
                            "entity": input_entity,
                            "chat_id": int(entity.id),
                            "title": getattr(entity, "first_name", None) or getattr(entity, "username", None) or str(entity.id),
                            "username": getattr(entity, "username", None),
                        })
                    except Exception as resolve_error:
                        self.db.log_event("ERROR", f"Could not resolve DM target {getattr(entity, 'id', '?')}: {resolve_error}")
            except Exception as e:
                self.db.log_event("ERROR", f"Failed to load DM targets: {e}")

        if not groups and not dm_targets:
            return False, "❌ No ad destinations available. Turn ON Groups/DMs and make sure the account has selected groups or existing Telegram DMs."

        if self.is_running:
            return False, "ℹ️ Forwarding is already running."

        self.is_running = True
        self.is_paused = False

        # Generate new cycle ID so deduplication works correctly
        import uuid
        self.current_cycle_id = str(uuid.uuid4())
        self.db.set_forwarding_state("current_cycle_id", self.current_cycle_id)

        # 🚀 3. Start forwarding loop
        self.forwarding_task = asyncio.create_task(self.forwarding_loop())

        return True, "✅ Forwarding started successfully!"
    
    def stop_forwarding(self) -> Tuple[bool, str]:
        """Stop the forwarding process."""
        if not self.is_running:
            return False, "ℹ️ Forwarding is not running."
        
        self.is_running = False
        self.is_paused = False
        
        if self.forwarding_task:
            self.forwarding_task.cancel()
        
        return True, "⏹️ Forwarding stopped."
    
    def pause_forwarding(self) -> Tuple[bool, str]:
        """Pause the forwarding process."""
        if not self.is_running:
            return False, "ℹ️ Forwarding is not running."
        
        if self.is_paused:
            return False, "ℹ️ Forwarding is already paused."
        
        self.is_paused = True
        return True, "⏸️ Forwarding paused."
    
    def resume_forwarding(self) -> Tuple[bool, str]:
        """Resume the forwarding process."""
        if not self.is_running:
            return False, "ℹ️ Forwarding is not running."
        
        if not self.is_paused:
            return False, "ℹ️ Forwarding is not paused."
        
        self.is_paused = False

        # ✅ Clear next_forward_time since the cycle loop now controls timing
        try:
            self.stats["next_forward_time"] = None
        except Exception as e:
            self.db.log_event("ERROR", f"Failed to reset next_forward_time on resume: {str(e)}")

        return True, "▶️ Forwarding resumed."
    
    async def forwarding_loop(self):
        """Run the ad cycle to selected Groups and/or existing Telegram DMs."""
        try:
            print("[Forwarding] 🚀 DM + Group loop started.")
            while self.is_running:
                if self.is_paused:
                    await asyncio.sleep(2)
                    continue

                groups_enabled = self.db.get_user_setting(self.user_id, "ads_groups_enabled", "on") == "on"
                dms_enabled = self.db.get_user_setting(self.user_id, "ads_dms_enabled", "on") == "on"
                all_groups = self.get_selected_groups() if groups_enabled else []

                dm_targets = []
                if dms_enabled:
                    try:
                        # Refresh the actual private-dialog entities every cycle so newly
                        # available DMs are picked up without restarting the userbot.
                        me = await self.userbot.client.get_me()
                        my_id = getattr(me, "id", None)
                        async for dialog in self.userbot.client.iter_dialogs(ignore_migrated=True):
                            entity = dialog.entity
                            if not isinstance(entity, User):
                                continue
                            if getattr(entity, "bot", False) or getattr(entity, "deleted", False):
                                continue
                            if getattr(entity, "id", None) == my_id:
                                continue
                            try:
                                input_entity = await self.userbot.client.get_input_entity(entity)
                                dm_targets.append({
                                    "entity": input_entity,
                                    "chat_id": int(entity.id),
                                    "title": getattr(entity, "first_name", None) or getattr(entity, "username", None) or str(entity.id),
                                    "username": getattr(entity, "username", None),
                                })
                            except Exception as resolve_error:
                                self.db.log_event("ERROR", f"DM resolve failed for {getattr(entity, 'id', '?')}: {resolve_error}")
                    except Exception as e:
                        self.db.log_event("ERROR", f"DM target scan failed: {e}")

                if not all_groups and not dm_targets:
                    print("[Forwarding] No enabled destinations. Stopping.")
                    self.is_running = False
                    return

                messages = self.get_forwarding_messages()
                if not messages:
                    print("[Forwarding] No messages configured. Stopping.")
                    self.is_running = False
                    return

                delay = max(3, int(self.db.get_setting("per_message_delay", "5")))
                destinations = []
                if groups_enabled:
                    destinations.extend([("group", g) for g in all_groups])
                if dms_enabled:
                    destinations.extend([("dm", d) for d in dm_targets])

                self.cycle_number = getattr(self, 'cycle_number', 0) + 1
                print(f"[Forwarding] Cycle #{self.cycle_number}: {len(all_groups)} groups + {len(dm_targets)} DMs")
                if self.logging_bot_manager and self.logging_bot_manager.mandatory_log_bot_ready():
                    try:
                        self.logging_bot_manager._compact_buffers[self.user_id] = {'ok':0,'fail':0,'flood':0,'group_ok':0,'group_fail':0,'dm_ok':0,'dm_fail':0,'last_error':None}
                        await self.logging_bot_manager.begin_cycle_log(self.user_id, self.cycle_number, len(all_groups), len(dm_targets))
                    except Exception as log_exc:
                        self.db.log_event('ERROR', f'Live cycle logger start failed: {log_exc}')

                for dest_type, destination in destinations:
                    if not self.is_running or self.is_paused:
                        break

                    chat_id = destination["chat_id"]
                    target_entity = destination.get("entity") if dest_type == "dm" else chat_id
                    title = destination.get("title") or destination.get("username") or str(chat_id)
                    username = destination.get("username")
                    display_name = title if dest_type == "group" else f"DM: {title}"
                    link_label = f"@{username}" if username else "DM" if dest_type == "dm" else "N/A"

                    for msg in messages:
                        try:
                            if not self.userbot.client or not self.userbot.is_authenticated:
                                print("[Forwarding] Userbot not connected.")
                                self.is_running = False
                                return

                            tg_msg = await self.userbot.client.get_messages(msg["channel_id"], ids=msg["message_id"])
                            if not tg_msg:
                                continue

                            can_forward, limit_msg = self.check_and_increment_message_count()
                            if not can_forward:
                                print(f"[Forwarding] Limit reached: {limit_msg}")
                                self.is_running = False
                                return

                            forward_mode = self.bot.get_forward_mode()
                            sent_msg = None

                            if forward_mode == "show":
                                # Use the resolved InputPeer for DMs; numeric IDs are used
                                # for groups exactly as before.
                                result = await self.userbot.client.forward_messages(target_entity, tg_msg)
                                sent_msg = result[0] if isinstance(result, list) else result
                            else:
                                if tg_msg.media:
                                    file_path = await tg_msg.download_media()
                                    try:
                                        sent_msg = await self.userbot.client.send_file(
                                            target_entity, file_path,
                                            caption=tg_msg.message,
                                            formatting_entities=tg_msg.entities
                                        )
                                    finally:
                                        if file_path and os.path.exists(file_path):
                                            try:
                                                os.remove(file_path)
                                            except Exception:
                                                pass
                                else:
                                    sent_msg = await self.userbot.client.send_message(
                                        target_entity,
                                        message=tg_msg.message,
                                        formatting_entities=tg_msg.entities
                                    )

                            if sent_msg:
                                self.stats["total_forwarded"] += 1
                                self.stats["last_forward_time"] = datetime.now()
                                if dest_type == "group":
                                    self.forwarded_groups_set.add(chat_id)

                                self.db.execute_query(
                                    "INSERT INTO forward_trace (user_id, group_title, group_link, chat_id, message_id, forwarded_at) VALUES (?, ?, ?, ?, ?, ?)",
                                    (self.user_id, display_name, link_label, chat_id, sent_msg.id, datetime.now(timezone.utc).isoformat())
                                )

                                if self.logging_bot_manager:
                                    try:
                                        if dest_type == "group":
                                            message_link = f"https://t.me/c/{str(chat_id).replace('-100', '')}/{sent_msg.id}"
                                        else:
                                            message_link = "DM delivered"
                                        await self.logging_bot_manager.send_log(
                                            user_id=self.user_id, success=True,
                                            group_name=display_name, message_link=message_link
                                        )
                                    except Exception:
                                        pass

                                print(f"[Forwarding] ✅ Sent to {display_name}")
                                await asyncio.sleep(delay)

                        except FloodWaitError as e:
                            print(f"[Forwarding] FloodWait {e.seconds}s for {display_name}")
                            if self.logging_bot_manager and self.logging_bot_manager.mandatory_log_bot_ready():
                                try:
                                    await self.logging_bot_manager.send_log(
                                        user_id=self.user_id, success=False,
                                        group_name=display_name,
                                        error=f"FloodWait: {e.seconds}s"
                                    )
                                except Exception:
                                    pass
                            await asyncio.sleep(e.seconds)
                        except (ChatWriteForbiddenError, ChatAdminRequiredError, UserBannedInChannelError) as e:
                            print(f"[Forwarding] Skipping {display_name}: {e}")
                            self.db.log_event("ERROR", f"Failed to forward to {display_name}: {e}")
                            if self.logging_bot_manager and self.logging_bot_manager.mandatory_log_bot_ready():
                                try:
                                    await self.logging_bot_manager.send_log(
                                        user_id=self.user_id, success=False,
                                        group_name=display_name, error=str(e)
                                    )
                                except Exception:
                                    pass
                        except Exception as e:
                            print(f"[Forwarding] Error on {display_name}: {e}")
                            self.db.log_event("ERROR", f"Forward failed for {display_name}: {e}")
                            if self.logging_bot_manager and self.logging_bot_manager.mandatory_log_bot_ready():
                                try:
                                    await self.logging_bot_manager.send_log(
                                        user_id=self.user_id, success=False,
                                        group_name=display_name, error=str(e)
                                    )
                                except Exception:
                                    pass

                print(f"[Forwarding] ✅ Cycle done — {len(all_groups)} groups + {len(dm_targets)} DMs. Restarting...")
                if self.logging_bot_manager and self.logging_bot_manager.mandatory_log_bot_ready():
                    try:
                        await self.logging_bot_manager.flush_compact_cycle_log(
                            self.user_id,
                            len(destinations),
                            getattr(self, 'cycle_number', 1),
                            total_groups=len(all_groups),
                            total_dms=len(dm_targets)
                        )
                    except Exception as log_exc:
                        self.db.log_event("ERROR", f"Compact cycle logger failed: {log_exc}")

        except asyncio.CancelledError:
            print("[Forwarding] 🔻 Cancelled.")
        except Exception as e:
            self.db.log_event("ERROR", f"Forwarding loop crashed: {e}")
            print(f"[Forwarding] CRASH: {e}")
        finally:
            self.is_running = False

    async def forward_next_group(self, all_groups: List[Dict]):
        """Forward one message to the next group, checking deduplication scoped to current cycle ID."""
        if not self.userbot.client or not self.userbot.is_authenticated:
            return

        messages = self.get_forwarding_messages()
        if not messages:
            return

        total_groups = len(all_groups)
        attempts = 0
        failed_groups_this_cycle = set()  # Track already-failed groups to avoid duplicate logs

        while attempts < total_groups:
            self.forward_index = self.forward_index % total_groups
            target_group = all_groups[self.forward_index]
            self.forward_index += 1
            attempts += 1

            self.db.set_forwarding_state("forward_index", str(self.forward_index))

            chat_id = target_group["chat_id"]
            group_title = target_group["title"]
            username = target_group.get("username")
            group_link = f"@{username}" if username else "N/A"

            for msg in messages:
                try:
                    tg_msg = await self.userbot.client.get_messages(msg["channel_id"], ids=msg["message_id"])
                    if not tg_msg:
                        continue

                    msg_hash = self.compute_message_hash(tg_msg)

                    # Deduplication for this cycle
                    if self.db.was_forwarded_this_cycle(chat_id, msg_hash, self.current_cycle_id):
                        print(f"[DUPLICATE] Skipping message already sent in current cycle to {chat_id}")
                        continue

                    # Detect if group is a forum
                    try:
                        entity = await self.userbot.client.get_entity(chat_id)
                        is_forum = getattr(entity, "megagroup", False) and getattr(entity, "forum", False)
                    except Exception as e:
                        self.stats["errors"] += 1
                        self.db.log_event("ERROR", f"Forum detection failed for group {chat_id}: {e}")
                        continue

                    if is_forum:
                        success = await self.forward_to_forum_group(tg_msg, chat_id, group_title, group_link)
                        if success:
                            self.db.mark_forwarded_this_cycle(chat_id, msg_hash, self.current_cycle_id)
                            return
                        continue  # Try next group

                    # Non-forum group — apply forward_mode logic
                    # Check message limit before forwarding
                    can_forward, limit_msg = self.check_and_increment_message_count()
                    if not can_forward:
                        self.db.log_event("WARNING", f"Message limit reached for user {self.user_id}: {limit_msg}")
                        if self.logging_bot_manager:
                            try:
                                await self.logging_bot_manager.send_log(
                                    user_id=self.user_id,
                                    success=False,
                                    group_name=group_title,
                                    error=f"Message limit reached: {limit_msg}"
                                )
                            except:
                                pass
                        continue
                    
                    forward_mode = self.bot.get_forward_mode()
                    sent_msg = None

                    if forward_mode == "show":
                        result = await self.userbot.client.forward_messages(chat_id, tg_msg)
                        sent_msg = result[0] if isinstance(result, list) else result
                    else:
                        me = await self.userbot.client.get_me()
                        has_premium = getattr(me, "premium", False)
                        if tg_msg.media:
                            file_path = await tg_msg.download_media()
                            sent_msg = await self.userbot.client.send_file(
                                chat_id,
                                file_path,
                                caption=tg_msg.message,
                                formatting_entities=tg_msg.entities
                            )
                        else:
                            sent_msg = await self.userbot.client.send_message(
                                chat_id,
                                message=tg_msg.message,
                                formatting_entities=tg_msg.entities
                            )
                        if not has_premium and tg_msg.text and "🪄" in tg_msg.text:
                            print("⚠️ Premium emoji may be downgraded (non-premium account)")

                    if sent_msg:
                        self.db.execute_query(
                            "INSERT INTO forward_trace (user_id, group_title, group_link, chat_id, message_id, forwarded_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (self.user_id, group_title, group_link, chat_id, sent_msg.id, datetime.now(timezone.utc).isoformat())
                        )
                        self.db.mark_forwarded_this_cycle(chat_id, msg_hash, self.current_cycle_id)
                        self.stats["total_forwarded"] += 1
                        self.stats["last_forward_time"] = datetime.now()
                        self.forwarded_groups_set.add(chat_id)

                        print(f"[FORWARD] ✅ Sent message {sent_msg.id} to {group_title} ({chat_id})")
                        
                        if self.logging_bot_manager:
                            message_link = f"https://t.me/c/{str(chat_id).replace('-100', '')}/{sent_msg.id}"
                            try:
                                await self.logging_bot_manager.send_log(
                                    user_id=self.user_id,
                                    success=True,
                                    group_name=group_title,
                                    message_link=message_link
                                )
                            except Exception as e:
                                print(f"[LOG] Failed to send success log: {e}")
                        
                        return

                except FloodWaitError as e:
                    print(f"[WAIT] Rate limit: {e.seconds}s wait needed for {group_title}")
                    if self.logging_bot_manager:
                        try:
                            await self.logging_bot_manager.send_log(
                                user_id=self.user_id,
                                success=False,
                                group_name=group_title,
                                error=f"⏱️ Rate limit on this group - wait {e.seconds}s. Buy Premium to remove these limits"
                            )
                        except:
                            pass
                    await asyncio.sleep(e.seconds)
                    return
                except ChatWriteForbiddenError as e:
                    self.stats["errors"] += 1
                    error_msg = "🔇 You're muted from this group - contact group admin to unmute"
                    self.db.log_event("ERROR", f"{error_msg}: {group_title}")
                    if self.logging_bot_manager:
                        try:
                            await self.logging_bot_manager.send_log(
                                user_id=self.user_id,
                                success=False,
                                group_name=group_title,
                                error=error_msg
                            )
                        except:
                            pass
                    break
                except ChatAdminRequiredError as e:
                    self.stats["errors"] += 1
                    error_msg = "👨‍⚖️ Admin rights required - this group needs admin permissions"
                    self.db.log_event("ERROR", f"{error_msg}: {group_title}")
                    if self.logging_bot_manager:
                        try:
                            await self.logging_bot_manager.send_log(
                                user_id=self.user_id,
                                success=False,
                                group_name=group_title,
                                error=error_msg
                            )
                        except:
                            pass
                    break
                except UserBannedInChannelError as e:
                    self.stats["errors"] += 1
                    error_msg = "🚫 You're banned from this group - contact group admin to appeal"
                    self.db.log_event("ERROR", f"{error_msg}: {group_title}")
                    if self.logging_bot_manager:
                        try:
                            await self.logging_bot_manager.send_log(
                                user_id=self.user_id,
                                success=False,
                                group_name=group_title,
                                error=error_msg
                            )
                        except:
                            pass
                    break
                except Exception as e:
                    self.stats["errors"] += 1
                    error_msg = str(e)
                    self.db.log_event("ERROR", f"Failed to forward to {group_title}: {e}")
                    # Only send ONE error log per group, not one per message
                    if chat_id not in failed_groups_this_cycle and self.logging_bot_manager:
                        failed_groups_this_cycle.add(chat_id)
                        try:
                            await self.logging_bot_manager.send_log(
                                user_id=self.user_id,
                                success=False,
                                group_name=group_title,
                                error=f"⚠️ {error_msg}"
                            )
                        except:
                            pass
                    break

        print("[FORWARD] ❌ All groups skipped or duplicates — nothing sent this round.")

    async def forward_messages(self):
        # Check if userbot is authenticated in memory
        if not self.userbot.client or not self.userbot.is_authenticated:
            self.db.log_event("ERROR", "Userbot not authenticated - checking database...")
            # Try to restore from database
            userbot_data = self.db.execute_query("SELECT is_active FROM userbot_session WHERE is_active = 1 LIMIT 1")
            if not userbot_data:
                self.db.log_event("ERROR", "❌ No active userbot found in database. Please add and authenticate a userbot first.")
                return
            else:
                self.db.log_event("WARNING", "Userbot was in database but not in memory - attempting to restore...")
                await self.userbot.restore_session()
                if not self.userbot.is_authenticated:
                    self.db.log_event("ERROR", "❌ Failed to restore userbot session.")
                    return

        messages = self.get_forwarding_messages()
        if not messages:
            self.db.log_event("ERROR", "No active forwarding messages.")
            return

        groups = self.get_selected_groups()
        if not groups:
            self.db.log_event("ERROR", "No selected groups for forwarding.")
            return

        dialogs = await self.userbot.client.get_dialogs()
        groups_to_forward = [g for g in groups if g["chat_id"] not in self.forwarded_groups_set]
        print(f"[Forwarding] Starting cycle with {len(groups_to_forward)} unvisited groups.")

        for message_info in messages:
            try:
                message = await self.userbot.client.get_messages(
                    message_info["channel_id"],
                    ids=message_info["message_id"]
                )
                if not message:
                    self.db.log_event("ERROR", f"Message ID {message_info['message_id']} not found in channel {message_info['channel_id']}")
                    continue

                for group in groups_to_forward:
                    now = datetime.now()
                    elapsed = (now - self.phase_start_time).total_seconds()
                    if self.current_phase == "forwarding" and elapsed >= self.cycle_length * 60:
                        print(f"[Forwarding] ⏳ Time limit of {self.cycle_length} min reached. Exiting early.")
                        return

                    chat_id = group["chat_id"]
                    group_title = group["title"]
                    username = group.get("username")
                    group_link = username if username else None

                    try:
                        # Determine if this is a forum with better error handling
                        is_forum = False
                        try:
                            dialog = next((d for d in dialogs if d.id == chat_id), None)
                            entity = dialog.entity if dialog else await self.userbot.client.get_entity(chat_id)
                            is_forum = getattr(entity, "megagroup", False) and getattr(entity, "forum", False)
                            self.db.log_event("INFO", f"Group {group_title} (ID: {chat_id}) is_forum: {is_forum}")
                        except Exception as e:
                            self.db.log_event("ERROR", f"Failed to determine forum status for {group_title}: {e}")
                            continue

                        # Handle non-forum groups
                        if not is_forum:
                            try:
                                forward_mode = self.bot.get_forward_mode()  # ✅ FIXED SCOPE
                                sent_msg = None
                                
                                if forward_mode == "show":
                                    result = await self.userbot.client.forward_messages(entity=chat_id, messages=message)
                                    sent_msg = result[0] if isinstance(result, list) else result
                                else:
                                    me = await self.userbot.client.get_me()
                                    has_premium = getattr(me, "premium", False)

                                    if message.media:
                                        file = await message.download_media()
                                        sent_msg = await self.userbot.client.send_file(
                                            chat_id,
                                            file,
                                            caption=message.message,
                                            formatting_entities=message.entities
                                        )
                                    elif message.text:
                                        sent_msg = await self.userbot.client.send_message(
                                            entity=chat_id,
                                            message=message.message,
                                            formatting_entities=message.entities
                                        )

                                    if not has_premium and message.text and "🪄" in message.text:
                                        print("⚠️ Premium emoji may be downgraded (non-premium account)")

                                if sent_msg:
                                    print(f"[DEBUG] FORWARD MODE: {forward_mode}")
                                    print(f"[DEBUG] Original Msg ID: {message.id}")
                                    print(f"[DEBUG] Sent Msg Obj: {sent_msg!r}")
                                    print(f"[DEBUG] Sent Msg ID (used in trace): {getattr(sent_msg, 'id', '??')}")
                                    self.stats["total_forwarded"] += 1
                                    self.stats["last_forward_time"] = datetime.now()
                                    self.forwarded_groups_set.add(chat_id)

                                    delay_setting = self.db.get_setting("per_message_delay", "30")
                                    delay_seconds = max(3, int(delay_setting))
                                    await asyncio.sleep(delay_seconds)

                                    print(f"[TRACE] Logging trace: chat_id={chat_id}, msg_id={sent_msg.id}")
                                    self.db.execute_query("DELETE FROM forward_trace WHERE forwarded_at < ?", 
                                                        (datetime.now() - timedelta(hours=1),))
                                    self.db.execute_query(
                                        "INSERT INTO forward_trace (group_title, group_link, chat_id, message_id, forwarded_at) VALUES (?, ?, ?, ?, ?)",
                                        (group_title, group_link, chat_id, sent_msg.id, datetime.now(timezone.utc).isoformat())
                                    )

                            except (ChatAdminRequiredError, UserBannedInChannelError, ChannelPrivateError, ChatWriteForbiddenError) as e:
                                self.stats["errors"] += 1
                                self.db.log_event("ERROR", f"Permission issue forwarding to group {group_title}: {e}")
                                self.db.execute_query("DELETE FROM groups WHERE chat_id = ?", (chat_id,))
                                self.db.log_event("ERROR", f"🚫 Auto-removed bad group {group_title} (ID {chat_id}) from database.")
                                try:
                                    entity = await self.userbot.client.get_entity(chat_id)
                                    await self.userbot.client(functions.channels.LeaveChannelRequest(entity))
                                except Exception as leave_err:
                                    self.db.log_event("ERROR", f"Failed to leave group {group_title} (ID {chat_id}): {leave_err}")
                                continue
                            except Exception as e:
                                self.stats["errors"] += 1
                                if "can't write in this chat" in str(e).lower():
                                    self.db.log_event("ERROR", f"🚫 Write error: removing {group_title} (ID {chat_id})")
                                    self.db.execute_query("DELETE FROM groups WHERE chat_id = ?", (chat_id,))
                                    continue
                                self.db.log_event("ERROR", f"Failed to forward to group {group_title}: {e}")
                                continue

                        # Handle forum groups
                        else:
                            success = await self.forward_to_forum_group(message, chat_id, group_title, group_link)
                            if success:
                                delay_setting = self.db.get_setting("per_message_delay", "30")
                                delay_seconds = max(3, int(delay_setting))
                                await asyncio.sleep(delay_seconds)

                    except Exception as e:
                        self.stats["errors"] += 1
                        self.db.log_event("ERROR", f"General failure forwarding to group {group_title}: {e}")

            except Exception as e:
                self.stats["errors"] += 1
                self.db.log_event("ERROR", f"Message fetch failure (ID {message_info['message_id']}): {e}")

        if len(self.forwarded_groups_set) >= len(groups):
            print("[Forwarding] ✅ All groups covered this round. Resetting set.")
            self.forwarded_groups_set = set()

    def get_status(self) -> Dict:
        """Get current forwarding bot status, including dynamic countdown to next phase event."""
        now = datetime.now()

        # ⏱️ Compute next event time only if bot is running
        if self.is_running:
            if self.current_phase == "forwarding":
                elapsed = (now - self.phase_start_time).total_seconds()
                seconds_left = self.cycle_length * 60 - elapsed
                if seconds_left > 0:
                    mins, secs = divmod(int(seconds_left), 60)
                    next_time_str = f"{mins}m {secs}s until HOLD"
                else:
                    next_time_str = "imminent (switching to HOLD)"
            elif self.current_phase == "holding":
                elapsed = (now - self.phase_start_time).total_seconds()
                seconds_left = self.hold_duration * 60 - elapsed
                if seconds_left > 0:
                    mins, secs = divmod(int(seconds_left), 60)
                    next_time_str = f"{mins}m {secs}s until FORWARDING"
                else:
                    next_time_str = "imminent (switching to FORWARDING)"
            else:
                next_time_str = "N/A"
        else:
            next_time_str = "N/A"

        return {
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "total_forwarded": self.stats["total_forwarded"],
            "last_forward_time": self.stats["last_forward_time"],
            "next_forward_in": next_time_str,
            "errors": self.stats["errors"],
            "selected_groups": len(self.get_selected_groups()),
            "forwarding_messages": len(self.get_forwarding_messages())
        }

class TelegramBot:
    def __init__(self, bot_token: str, admin_id: int):
        self.BOT_TOKEN = bot_token
        self.ADMIN_USER_ID = admin_id

        self.db = Database()
        self.userbot_manager = UserbotManager(self.db)
        self.logging_bot_manager = LoggingBotManager(self.db)
        self.forwarding_manager = ForwardingManager(self.db, self.userbot_manager, self, admin_id, self.logging_bot_manager)
        self.logs_channel_manager = None  # Will be initialized after application is created
        self.application = None
        self.temp_data = {}  # For storing temporary data during flows
        self.progress_containers = {}  # For live group-join progress containers
        self.last_group_join_time = None
        stored = self.db.get_setting("last_group_join_time")
        self.last_group_join_time = float(stored) if stored else None
        
        # Cache to skip redundant database queries (fast in-memory cache)
        self._cache = {}  # {cache_key: (value, timestamp)}
        self._cache_ttl = 300  # Cache validity in seconds (5 minutes for subscription checks)
        
        # Background task tracking
        self.branding_task = None
        self.group_joiner_task = None
        self.user_bots = {}  # Bot instances cache for logging
        
        # Auto Fampay / UPI configuration. Values can be configured from Admin Panel.
        self.fampay_api_url = self.db.get_setting("fampay_api_url", "https://api.growfan.in/fampay.php") or os.environ.get("FAMPAY_API_URL", "https://api.growfan.in/fampay.php")
        self.fampay_api_key = self.db.get_setting("fampay_api_key", "") or os.environ.get("FAMPAY_API_KEY", "")
        self.fampay_gmail = self.db.get_setting("fampay_gmail", "gurugamer183@gmail.com") or os.environ.get("FAMPAY_GMAIL", "gurugamer183@gmail.com")
        self.fampay_app_password = self.db.get_setting("fampay_app_password", "") or os.environ.get("FAMPAY_APP_PASSWORD", "")
        self.fampay_upi_id = self.db.get_setting("fampay_upi_id", "") or os.environ.get("FAMPAY_UPI_ID", "")
        self.fampay_upi_name = self.db.get_setting("fampay_upi_name", "CCxBypass_Bot") or os.environ.get("FAMPAY_UPI_NAME", "CCxBypass_Bot")
        self.fampay_enabled = self.db.get_setting("fampay_enabled", "1") == "1"
        self.fampay_prices = self._load_fampay_prices()
        self.welcome_banner_generator = BotBannerGenerator()
        self.professional_banner_generator = ProfessionalBannerGenerator()
        
        self.SUBSCRIPTION_PLANS = {
            "1_month": {"name": "1 Month", "price": 60, "duration": 43200, "currency": "INR"},
            "3_months": {"name": "3 Months", "price": 100, "duration": 129600, "currency": "INR"},
            "6_months": {"name": "6 Months", "price": 600, "duration": 259200, "currency": "INR"},
            "lifetime": {"name": "Lifetime", "price": 1000, "duration": 5256000, "currency": "INR"},
        }

    def _load_fampay_prices(self) -> dict:
        defaults = {"1_month": 60, "3_months": 100, "6_months": 600, "lifetime": 1000}
        raw = self.db.get_setting("fampay_prices", "")
        if raw:
            try:
                data = json.loads(raw)
                for key in defaults:
                    if key in data:
                        defaults[key] = float(data[key])
            except Exception:
                pass
        return defaults

    def reload_fampay_config(self) -> bool:
        # These are the supplied default Fampay settings. Empty DB values are repaired automatically.
        defaults = {
            "fampay_api_url": "https://api.growfan.in/fampay.php",
            "fampay_gmail": "gurugamer183@gmail.com",
            "fampay_app_password": "",
            "fampay_upi_id": os.environ.get("FAMPAY_UPI_ID", ""),
            "fampay_upi_name": "CCxBypass_Bot",
            "fampay_enabled": "1",
            "fampay_prices": json.dumps({"1_month": 60, "3_months": 100, "6_months": 600, "lifetime": 1000})
        }
        for key, value in defaults.items():
            current = self.db.get_setting(key, None)
            if current is None or str(current).strip() == "":
                self.db.set_setting(key, value)

        self.fampay_api_url = self.db.get_setting("fampay_api_url", defaults["fampay_api_url"])
        self.fampay_api_key = self.db.get_setting("fampay_api_key", "") or os.environ.get("FAMPAY_API_KEY", "")
        self.fampay_gmail = self.db.get_setting("fampay_gmail", defaults["fampay_gmail"])
        self.fampay_app_password = self.db.get_setting("fampay_app_password", defaults["fampay_app_password"])
        self.fampay_upi_id = self.db.get_setting("fampay_upi_id", defaults["fampay_upi_id"])
        self.fampay_upi_name = self.db.get_setting("fampay_upi_name", defaults["fampay_upi_name"])
        self.fampay_enabled = self.db.get_setting("fampay_enabled", "1") == "1"
        self.fampay_prices = self._load_fampay_prices()
        return self.fampay_configured()

    def fampay_configured(self) -> bool:
        return bool(self.fampay_enabled and self.fampay_gmail and self.fampay_app_password and self.fampay_upi_id and self.fampay_api_url)

    async def _activate_fampay_subscription(self, payment: dict) -> tuple:
        user_id = payment['user_id']
        plan_id = payment['plan_type']
        duration = int(payment['plan_duration'])
        current = self.db.fetch_one("SELECT expires_at FROM authorized_users WHERE user_id = ?", (user_id,))
        if current and current[0]:
            try:
                current_expiry = datetime.fromisoformat(current[0])
                new_expiry = (current_expiry if current_expiry > datetime.now() else datetime.now()) + timedelta(minutes=duration)
            except Exception:
                new_expiry = datetime.now() + timedelta(minutes=duration)
        else:
            new_expiry = datetime.now() + timedelta(minutes=duration)
        self.db.mark_fampay_verified(payment['purpose'])
        self.db.execute_query(
            """INSERT OR REPLACE INTO authorized_users
               (user_id, approved_at, expires_at, total_minutes_granted, approved_by, note)
               VALUES (?, ?, ?, COALESCE((SELECT total_minutes_granted FROM authorized_users WHERE user_id = ?), 0) + ?, ?, ?)""",
            (user_id, datetime.now().isoformat(), new_expiry.isoformat(), user_id, duration, self.ADMIN_USER_ID, f"Auto Fampay payment: {payment['purpose']}")
        )
        plan = self.SUBSCRIPTION_PLANS.get(plan_id, {})
        return plan.get('name', plan_id), new_expiry

    async def callback_cancel_fampay(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer("Payment cancelled.")
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(update.effective_user.id, "🔴 <b>Fampay payment cancelled.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="public_back", style="primary")]]), parse_mode=ParseMode.HTML)

    async def show_fampay_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, plan_id: str):
        query = update.callback_query
        user_id = update.effective_user.id
        if plan_id not in self.SUBSCRIPTION_PLANS:
            await query.answer("Invalid plan.", show_alert=True); return
        self.reload_fampay_config()
        if not self.fampay_configured():
            await query.answer("Auto Fampay is not configured by admin.", show_alert=True); return

        plan = self.SUBSCRIPTION_PLANS[plan_id]
        amount = float(self.fampay_prices.get(plan_id, plan['price']))
        purpose = f"adbot_{user_id}_{plan_id}_{int(time.time())}_{random.randint(1000,9999)}"
        if not self.db.save_fampay_payment(user_id, purpose, amount, plan_id, int(plan['duration'])):
            await query.answer("Could not create payment. Try again.", show_alert=True); return

        upi_url = f"upi://pay?pa={quote(self.fampay_upi_id)}&pn={quote(self.fampay_upi_name)}&tn={quote(purpose)}&am={amount:g}&cu=INR"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(upi_url); qr.make(fit=True)
        img = qr.make_image()
        buf = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)

        text = (f"<b>🇮🇳 Auto Fampay Payment</b>\n\n"
                f"<b>Plan:</b> {html.escape(plan['name'])}\n"
                f"<b>Amount:</b> ₹{amount:g}\n"
                f"<b>UPI ID:</b> <code>{html.escape(self.fampay_upi_id)}</code>\n"
                f"<b>Purpose:</b> <code>{purpose}</code>\n\n"
                "Scan the QR or pay using the UPI ID. After payment, tap <b>Check Payment</b>.\n"
                "Payment is automatically verified using the configured Fampay gateway.")
        keyboard = [
            [InlineKeyboardButton("🔄 Check Payment", callback_data=f"check_fampay_{purpose}", style="success")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_fampay", style="danger")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"buy_plan_{plan_id}", style="primary")]
        ]
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_photo(user_id, photo=buf.getvalue(), caption=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    async def _request_fampay_verification(self, purpose: str) -> dict:
        """Call the configured Fampay gateway using the same credentials used by the
        original bypass integration, while tolerating GET/POST and common response shapes."""
        self.reload_fampay_config()
        if not self.fampay_configured():
            return {"ok": False, "error": "Fampay configuration is incomplete."}

        params = {
            "gmail": self.fampay_gmail,
            "app_password": self.fampay_app_password,
            "purpose": purpose,
        }
        # Optional API key support. If an admin has configured one, send it in
        # both common locations without requiring it for the legacy gateway.
        api_key = self.db.get_setting("fampay_api_key", "") or os.environ.get("FAMPAY_API_KEY", "")
        if api_key:
            params["key"] = api_key
            params["api_key"] = api_key

        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        last_error = None
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # 1) Legacy integration: GET with query parameters.
            for method in ("get", "post"):
                try:
                    if method == "get":
                        request = session.get(self.fampay_api_url, params=params)
                    else:
                        request = session.post(self.fampay_api_url, data=params)
                    async with request as response:
                        raw = await response.text()
                        if response.status < 200 or response.status >= 300:
                            last_error = f"HTTP {response.status}: {raw[:300]}"
                            continue
                        try:
                            data = json.loads(raw)
                        except Exception:
                            last_error = f"Invalid JSON response: {raw[:300]}"
                            continue
                        if isinstance(data, list):
                            data = {"data": data}
                        if not isinstance(data, dict):
                            last_error = "Unexpected gateway response format."
                            continue
                        return {"ok": True, "data": data, "raw": raw}
                except Exception as exc:
                    last_error = str(exc)
                    continue

        return {"ok": False, "error": last_error or "Gateway request failed."}

    @staticmethod
    def _extract_fampay_result(data: dict) -> tuple:
        """Return (verified, amount, status) from several common gateway formats."""
        candidates = [data]
        for key in ("data", "result", "payment", "transaction", "response"):
            value = data.get(key)
            if isinstance(value, dict):
                candidates.append(value)

        verified = False
        status = ""
        amount = None
        truthy_statuses = {"verified", "success", "successful", "paid", "completed", "complete", "confirmed", "approved"}
        for item in candidates:
            for key in ("verified", "is_verified", "paid", "is_paid", "success", "completed", "confirmed", "approved"):
                value = item.get(key)
                if isinstance(value, bool) and value:
                    verified = True
                elif isinstance(value, str) and value.lower() in ("true", "1", "yes", "paid", "verified", "success", "completed", "confirmed", "approved"):
                    verified = True
            for key in ("status", "payment_status", "transaction_status", "order_status", "state"):
                value = item.get(key)
                if value is not None:
                    status = str(value).strip().lower()
                    if status in truthy_statuses:
                        verified = True
            if amount is None:
                for key in ("amount", "paid_amount", "received_amount", "credited_amount", "transaction_amount", "amount_paid"):
                    value = item.get(key)
                    if value not in (None, ""):
                        try:
                            amount = float(str(value).replace(",", "").replace("₹", "").strip())
                            break
                        except Exception:
                            pass
        return verified, amount, status

    async def check_fampay_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, purpose: str):
        query = update.callback_query
        user_id = update.effective_user.id
        payment = self.db.get_fampay_payment(purpose)
        if not payment or payment['user_id'] != user_id:
            await query.answer("❌ Payment not found.", show_alert=True); return
        if payment['status'] == 'completed':
            await query.answer("✅ Already verified.", show_alert=True); return

        result = await self._request_fampay_verification(purpose)
        if not result.get("ok"):
            print(f"[Fampay] Verification request failed: {result.get('error')}")
            await query.answer("❌ Fampay gateway error. Check API URL/key configuration and try again.", show_alert=True)
            return

        verified, gateway_amount, gateway_status = self._extract_fampay_result(result["data"])
        expected = float(payment['amount'])

        # Never auto-credit on a generic success response when the gateway does not
        # expose the paid amount. This avoids false-positive premium activation.
        if verified and gateway_amount is None:
            await query.answer("⚠️ Payment is marked paid, but gateway did not return the amount. Contact admin.", show_alert=True)
            print(f"[Fampay] Paid response without amount for {purpose}: {result['data']}")
            return

        if verified and gateway_amount is not None and gateway_amount + 1e-9 >= expected:
            plan_name, expiry = await self._activate_fampay_subscription(payment)
            await query.answer("✅ Payment verified!", show_alert=True)
            await self._safe_edit_text(
                query,
                f"<b>✅ Payment Successful!</b>\n\n<b>Plan:</b> {html.escape(plan_name)}\n<b>Amount:</b> ₹{expected:g}\n<b>Gateway Amount:</b> ₹{gateway_amount:g}\n<b>Expires:</b> {expiry.strftime('%Y-%m-%d %H:%M:%S')}\n\nYour AdBot subscription is active.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Go to Menu", callback_data="public_back", style="success")]]),
                parse_mode=ParseMode.HTML
            )
            try:
                await context.bot.send_message(
                    self.ADMIN_USER_ID,
                    f"<b>💰 Auto Fampay Payment Verified</b>\n\nUser: <code>{user_id}</code>\nPlan: <b>{html.escape(plan_name)}</b>\nAmount: ₹{expected:g}\nGateway Amount: ₹{gateway_amount:g}\nPurpose: <code>{purpose}</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception as exc:
                print(f"[Fampay] Admin notification failed: {exc}")
            return

        if verified and gateway_amount is not None:
            await query.answer(f"⚠️ Payment detected: ₹{gateway_amount:g}. Required: ₹{expected:g}.", show_alert=True)
        else:
            await query.answer(f"⏳ Payment not verified yet. Status: {gateway_status or 'pending'}.", show_alert=True)

    async def _safe_edit_text(self, cbq, text, reply_markup=None, parse_mode=None):
        """Universal safe edit - tries caption first if photo message, else text."""
        msg = cbq.message
        if msg and (msg.photo or msg.document or msg.video or msg.animation):
            try:
                await cbq.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
                return
            except BadRequest as e:
                if "message is not modified" in str(e).lower():
                    return
        try:
            await cbq.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except BadRequest as e:
            error_str = str(e).lower()
            if "message is not modified" in error_str:
                return
            if "there is no text" in error_str:
                try:
                    await cbq.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
                except BadRequest as e2:
                    if "message is not modified" in str(e2).lower():
                        return

    def set_forward_mode(self, mode: str):
        uid = _SYNX_CURRENT_USER.get()
        if uid is None:
            uid = int(self.db.get_setting("admin_user_id", "0") or 0)
        self.db.execute_query(
            "UPDATE userbot_session SET forward_mode = ? WHERE user_id = ? AND is_active = 1",
            (mode, uid)
        )

    def get_forward_mode(self):
        uid = _SYNX_CURRENT_USER.get()
        if uid is None:
            uid = int(self.db.get_setting("admin_user_id", "0") or 0)
        result = self.db.fetch_one(
            "SELECT forward_mode FROM userbot_session WHERE user_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
            (uid,)
        )
        return result[0] if result else "show"

    HELP_PAGES = [
    {
        "title": "🤖 What is AdBot?",
        "content": (
            "*AdBot* is your personal Telegram automation assistant, hosted 24/7 on your VPS.\n\n"
            "Built for creators, marketers, and admins, it uses your actual Telegram account (userbot) to:\n"
            "• Forward messages to unlimited groups & channels\n"
            "• Auto-reply to DMs using smart AFK\n"
            "• Join groups automatically using links\n"
            "• Run in background with full local control\n\n"
            "*Why it's different:*\n"
            "• No third-party servers — hosted on your own VPS\n"
            "• Uses official Telegram API via session login\n"
            "• Hands-free cycles and privacy-first design"
        )
    },
    {
        "title": "🚀 How to Set Up",
        "content": (
            "1. Go to [my.telegram.org](https://my.telegram.org) → API Development\n"
            "2. Get your API ID and API Hash\n"
            "3. In the bot, tap `➕ Add Userbot`\n"
            "4. Enter:\n"
            "   - API ID\n"
            "   - API Hash\n"
            "   - Phone number (linked to your Telegram account)\n"
            "   - OTP code (Telegram login)\n"
            "   - 2FA password (if enabled)\n\n"
            "🎯 AdBot saves a session file and starts running *permanently* from your VPS."
        )
    },
    {
        "title": "👥 Groups & Auto Join",
        "content": (
            "Manage and automate your groups from the `👥 Groups` menu:\n\n"
            "• Add groups via @username, t.me links, or invite URLs\n"
            "• Auto-join queue runs every 5 minutes\n"
            "• Track join status, approval errors, or bans\n"
            "• Toggle groups on/off for forwarding\n"
            "• Remove groups to leave them automatically\n\n"
            "✅ All groups persist between reboots."
        )
    },
    {
        "title": "📤 Forwarding System",
        "content": (
            "From `🔁 Forwarding`, you can:\n"
            "• Add up to 2 messages to forward\n"
            "• Choose destination groups\n"
            "• Set delay via `Alter`\n"
            "• Start/Stop forwarding loop\n\n"
            "💡 Uses Telegram’s `forward_messages` API\n"
            "⏱ Adds random delay between sends\n"
            "🎯 Designed to mimic human behavior and avoid detection"
        )
    },
    {
        "title": "🔄 Forwarding Logic & Cycles",
        "content": (
            "The bot runs on auto cycles:\n\n"
            "• Active phase: 120 mins forwarding\n"
            "• Hold phase: 15+ mins pause (configurable)\n"
            "• Resumes automatically\n\n"
            "⏳ Countdown shown in UI\n"
            "🕹 Modify cycles at runtime\n"
            "🔁 Resets on pause, stop, or restart"
        )
    },
    {
        "title": "💬 AFK Auto-Reply Logic",
        "content": (
            "Smart AFK replies are perfect for passive DM handling:\n\n"
            "• Set message in `⚙️ Settings > 💤 AFK Message`\n"
            "• Turn ON → replies to all new DM users\n"
            "• One reply per user every 2 hours\n"
            "• Admins are excluded from replies\n"
            "• Toggle AFK OFF any time\n\n"
            "💤 Works great while you're away or sleeping"
        )
    },
    {
        "title": "🧠 Live Status & Tracing",
        "content": (
            "Go to `📊 Status` to see:\n\n"
            "• Current session info (userbot active/inactive)\n"
            "• List of selected groups\n"
            "• Next forward countdown\n"
            "• Last message per group (Live Trace)\n"
            "• Pagination & refresh\n\n"
            "🔄 Use `Refresh` to update logs in real-time"
        )
    },
    {
        "title": "⚙️ Settings & Control Panel",
        "content": (
            "Settings include:\n\n"
            "• `Alter`: custom per-message delay (min 30s)\n"
            "• `AFK`: configure & enable/disable reply logic\n"
            "• `Forward Mode`: show/hide sender tag\n"
            "• `Wipe All`: clear all settings & session\n"
            "• `Sync Groups`: reload joined group list\n"
            "• `Support Access`: allow developer debug (optional)\n\n"
            "✅ All changes take effect instantly"
        )
    },
    {
        "title": "🛡️ Emoji & Premium Mode",
        "content": (
            "When hiding sender tags (native send):\n\n"
            "• Premium emojis may break unless you have Telegram Premium\n"
            "• Bot detects this and strips unsupported emojis\n\n"
            "✅ Forward Mode is toggleable:\n"
            "• *Show* → uses official forward method\n"
            "• *Hide* → sends content manually"
        )
    },
    {
        "title": "🔐 Support Access Mode",
        "content": (
            "If you need help, you can enable temporary debug access:\n\n"
            "• Go to `⚙️ Settings > Support Access`\n"
            "• This grants developer limited remote debug rights\n"
            "• You’ll be notified when it’s active\n\n"
            "🔒 You can revoke this any time\n"
            "🛠 Only use if you're actively getting support"
        )
    },
    {
        "title": "📁 Session & Data Info",
        "content": (
            "All your data is stored *locally on the VPS*:\n\n"
            "• Telegram session (userbot)\n"
            "• Group list & join queue\n"
            "• Messages to forward\n"
            "• Logs & live traces\n\n"
            "No external API calls. No cloud sync. 100% local."
        )
    },
    {
        "title": "🚧 Troubleshooting",
        "content": (
            "If forwarding isn't working:\n"
            "• Make sure a message is added\n"
            "• Select at least one group\n"
            "• Ensure forwarding is active (not paused)\n\n"
            "If joining fails:\n"
            "• The group may be private, full, or need approval\n"
            "• Try alternate link (invite vs username)\n\n"
            "If you're banned:\n"
            "• Review delay settings — were they too low?\n"
            "• Contact Telegram support for appeal"
        )
    },
    {
        "title": "📚 Use Cases & Ideas",
        "content": (
            "• Forward CPA/ad posts to 100+ groups\n"
            "• Manage multiple forums passively\n"
            "• Auto-reply to warm leads at night\n"
            "• Promote offers without touching the app\n"
            "• Hands-free DM interaction with rate-limited accounts\n"
            "• Let clients monitor groups with logs"
        )
    },
    {
        "title": "📜 Terms of Service",
        "content": (
            "By using AdBot, you agree:\n\n"
            "• This is a self-hosted tool. You own the risks.\n"
            "• Your Telegram account is under your control\n"
            "• We are NOT responsible for bans, limits, or lockouts\n"
            "• You must follow Telegram’s Terms of Use\n"
            "• Logs are private and stored locally only\n\n"
            "💡 *Always get suggestions before risky changes*\n"
            "Spam at your own risk — automation ≠ abuse."
        )
    },
    {
        "title": "💼 Safety Guidelines",
        "content": (
            "To stay safe:\n\n"
            "• Use delays > 1 mins per forward\n"
            "• Avoid forwarding same post 20+ times quickly\n"
            "• Avoid keywords: ‘free’, ‘earn’, etc.\n"
            "• Prefer native content formats\n"
            "• Don’t mass-forward during Telegram updates\n\n"
            "✅ Best Practice: Ask us before going aggressive"
        )
    },
    {
        "title": "📞 Need Help?",
        "content": (
            "• Telegram support: [@SynaxBaby](https://t.me/SynaxBaby?text=hey%2C%20I%20Want%20Some%20Help%20In%20Your%20Adbot)\n"
            "• Logs, screenshots help us debug fast\n\n"
            "*Thanks for trusting AdBot 🤖*\n"
            "We’re building for creators who want speed, scale, and silence."
        )
    }
]


    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Global error handler for unhandled exceptions."""
        try:
            error_msg = f"Update {update} caused error {context.error}"
            print(f"[ERROR] {error_msg}")
            # Log DB error in background - don't block error handler
            asyncio.create_task(self._log_error_async(error_msg))
        except Exception as e:
            print(f"[ERROR] Error handler failed: {e}")
    
    async def _log_error_async(self, error_msg: str):
        """Log error to database asynchronously in background."""
        try:
            await self._run_db_query(self.db.log_event, "ERROR", error_msg)
        except Exception as e:
            print(f"[ERROR] Failed to log error: {e}")

    async def banner_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Generate and send professional banners."""
        user_id = update.effective_user.id
        
        if user_id != self.ADMIN_USER_ID and not await self.is_user_authorized(user_id, self.ADMIN_USER_ID):
            await update.message.reply_text("You don't have access to this command.")
            return
        
        keyboard = [
            [InlineKeyboardButton("Service Banner", callback_data="gen_banner_service")],
            [InlineKeyboardButton("Pricing Banner", callback_data="gen_banner_pricing")],
            [InlineKeyboardButton("Features Banner", callback_data="gen_banner_features")],
            [InlineKeyboardButton("Custom Banner", callback_data="gen_banner_custom")],
            [InlineKeyboardButton("Cancel", callback_data="back_main")]
        ]
        
        await update.message.reply_text(
            "<b>Professional Banner Generator</b>\n\n"
            "Create stunning promotional banners for your advertising:\n\n"
            "Choose a banner type below:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )
    
    def start_bot(self):
        self.application = Application.builder().token(self.BOT_TOKEN).build()

        # Register handlers
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("banner", self.banner_command))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Add global error handler
        self.application.add_error_handler(self.error_handler)
        
        # Post-init to setup async tasks after app starts
        async def post_init(app):
            """Run after app initialization"""
            try:
                await self.userbot_manager.restore_session()
            except Exception as e:
                print(f"[ERROR] Failed to restore userbot session: {e}")
            
            try:
                await app.bot.set_my_commands([
                    BotCommand("start", "Start the bot"),
                    BotCommand("menu", "Show main menu"),
                    BotCommand("status", "Show system status")
                ])
            except Exception as e:
                print(f"[ERROR] Failed to set bot commands: {e}")
            
            # Start background group joiner task
            self.group_joiner_task = asyncio.create_task(self.background_group_joiner())
            
        
        self.application.post_init = post_init

        print("Bot started successfully!")
        self.application.run_polling()



    
    async def is_admin(self, user_id: int) -> bool:
        """Check if user is admin (async to avoid blocking)."""
        if user_id == self.ADMIN_USER_ID:
            return True
        if user_id in SUPPORT_USER_IDS:
            # Run DB query in executor to avoid blocking
            support_status = await self._run_db_query(self.db.get_setting, "support_access", "off")
            return support_status == "on"
        return False
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Every normal user gets the actual AdBot dashboard.
        # Premium purchasing is intentionally hidden from the user-facing flow;
        # the dashboard remains fully usable on the free tier.
        user_id = update.effective_user.id

        if user_id == self.ADMIN_USER_ID:
            await self.show_main_menu(update, context, send_banner=True)
            return

        if user_id in SUPPORT_USER_IDS:
            support_status = await self._run_db_query(self.db.get_setting, "support_access", "off")
            if support_status == "on":
                await self.show_main_menu(update, context, send_banner=True)
            else:
                await self.show_main_menu(update, context, send_banner=True)
            return

        # Do not send the Premium/Buy Now landing page.
        # Free users can directly access the normal dashboard and its existing tools.
        await self.show_main_menu(update, context, send_banner=True)
    
    async def safe_edit_message(self, query, text: str, keyboard=None, parse_mode=ParseMode.HTML):
        """Safely edit a message, handling both photo captions and text messages."""
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        error_str = ""
        
        try:
            await query.edit_message_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return True
        except BadRequest as e:
            error_str = str(e).lower()
            if "message is not modified" in error_str:
                return True
            if "there is no caption" in error_str or "message can't be edited" in error_str:
                pass
            else:
                raise
        
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            return True
        except BadRequest as e2:
            error_str2 = str(e2).lower()
            if "message is not modified" in error_str2:
                return True
            if "there is no text" in error_str2:
                return True
            raise
    
    async def delete_user_message_and_update(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                              new_text: str, keyboard=None, parse_mode=ParseMode.HTML):
        """Delete user's message and update the main menu message."""
        user_id = update.effective_user.id
        try:
            if update.message:
                await update.message.delete()
        except Exception as e:
            print(f"Could not delete user message: {e}")
        
        main_msg_id = context.user_data.get('main_message_id')
        if main_msg_id:
            try:
                await context.bot.edit_message_caption(
                    chat_id=user_id,
                    message_id=main_msg_id,
                    caption=new_text,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                    parse_mode=parse_mode
                )
                return True
            except BadRequest as e:
                error_str = str(e).lower()
                if "message is not modified" in error_str:
                    return True
                if "there is no caption" in error_str:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=user_id,
                            message_id=main_msg_id,
                            text=new_text,
                            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
                            parse_mode=parse_mode
                        )
                        return True
                    except BadRequest as e2:
                        if "message is not modified" in str(e2).lower():
                            return True
                        if "there is no text" in str(e2).lower():
                            return True
                        print(f"Could not edit main message: {e2}")
                else:
                    print(f"Could not edit main message: {e}")
        
        sent_msg = await context.bot.send_message(
            chat_id=user_id,
            text=new_text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            parse_mode=parse_mode
        )
        context.user_data['main_message_id'] = sent_msg.message_id
        return True

    async def show_support_menu(self, update, context):
        user_id = update.effective_user.id
        keyboard = [
            [InlineKeyboardButton("📄 View Subscription", callback_data="support_subscription")],
            [
                InlineKeyboardButton("➕ Add Minutes", callback_data="support_add_minutes"),
                InlineKeyboardButton("➖ Subtract Minutes", callback_data="support_subtract_minutes")
            ],
            [InlineKeyboardButton("👤 View User ID", callback_data="support_userid")],
            [InlineKeyboardButton("📶 Ping AdBot", callback_data="support_ping")]
        ]
        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = "🛠 *Support Panel*\n\nChoose an action to help the user."

        if update.callback_query:
            await self._safe_edit_text(update.callback_query, 
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        elif update.message:
            await update.message.reply_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )


    def get_subscription_status(self, user_id: int = None) -> Tuple[bool, str]:
        if user_id is None:
            user_id = self.ADMIN_USER_ID
        
        is_admin = (user_id == self.ADMIN_USER_ID)
        
        start_str = self.db.get_setting("subscription_start")
        duration_str = self.db.get_setting("subscription_duration", "0")

        if not start_str:
            now = datetime.now()
            self.db.set_setting("subscription_start", now.isoformat())
            start_str = now.isoformat()
            print("[Subscription] Auto-initialized subscription_start to now")

        if not duration_str or duration_str == "0" or duration_str == "":
            default_duration = "43200"
            self.db.set_setting("subscription_duration", default_duration)
            duration_str = default_duration
            print(f"[Subscription] Auto-set subscription_duration to {default_duration} minutes (30 days)")

        try:
            start_time = datetime.fromisoformat(start_str)
            duration = int(duration_str)
            
            if duration <= 0:
                return True, (
                    f"⏳ *Subscription Status:*\n"
                    f"• Status: `Unlimited (no expiration)`\n"
                    f"• Start: `{start_time.strftime('%Y-%m-%d %H:%M:%S')}`"
                )
            
            end_time = start_time + timedelta(minutes=duration)
            now = datetime.now()

            remaining = end_time - now

            if remaining.total_seconds() <= 0:
                if is_admin:
                    new_start = datetime.now()
                    self.db.set_setting("subscription_start", new_start.isoformat())
                    print(f"[Subscription] Admin auto-renewed subscription_start to {new_start.isoformat()}")
                    start_time = new_start
                    end_time = start_time + timedelta(minutes=duration)
                    remaining = end_time - now
                else:
                    return False, "⛔️ Subscription expired."

            days, rem = divmod(remaining.total_seconds(), 86400)
            hours, rem = divmod(rem, 3600)
            minutes, seconds = divmod(rem, 60)

            return True, (
                f"⏳ *Subscription Status:*\n"
                f"• Start: `{start_time.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                f"• Duration: `{duration}` minutes\n"
                f"• Time left: `{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s`\n"
                f"• Expires at: `{end_time.strftime('%Y-%m-%d %H:%M:%S')}`"
            )
        except Exception as e:
            print(f"[Subscription] Error in get_subscription_status: {e}")
            if is_admin:
                return True, f"⚠️ Subscription check bypassed for admin: {str(e)}"
            return False, f"⚠️ Subscription error: {str(e)}"

    async def show_subscription_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        active, status = self.get_subscription_status()

        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="subscription_refresh")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_back")]
        ]

        if not active:
            keyboard.insert(0, [InlineKeyboardButton("📩 Contact Developer", url="https://t.me/m/6Fr0Uj1EYWFl")])
            await self._safe_edit_text(update.callback_query, 
                text=f"{status}\n\n*Access Denied.* Please contact @SynaxBaby.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await self._safe_edit_text(update.callback_query, 
                text=status,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )


    async def show_public_menu(self, update, context, send_banner: bool = False):
        # Legacy compatibility: the old Premium landing page is no longer shown.
        # All users are routed to the real advertising dashboard.
        await self.show_main_menu(update, context, send_banner=send_banner)

    async def show_subscription_plans(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show subscription plans. Payments are Fampay/UPI only; Fampay/crypto is removed."""
        query = update.callback_query
        self.reload_fampay_config()

        text = (
            "<b>💳 Choose Your Premium Plan</b>\n\n"
            "🇮🇳 <b>Payment Method:</b> UPI Auto Fampay\n\n"
        )
        keyboard = []
        for plan_id, plan in self.SUBSCRIPTION_PLANS.items():
            amount = float(self.fampay_prices.get(plan_id, plan['price']))
            text += f"• <b>{html.escape(plan['name'])}</b> — ₹{amount:g}\n"
            keyboard.append([
                InlineKeyboardButton(
                    f"💎 {plan['name']} - ₹{amount:g}",
                    callback_data=f"buy_plan_{plan_id}",
                    style="primary"
                )
            ])

        text += (
            "\n<b>⚡ Auto verification:</b> After paying, press <b>Check Payment</b>.\n"
            "Your Premium access will be activated automatically after the Fampay gateway confirms the payment."
        )
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="public_back", style="danger")])
        await self._safe_edit_text(
            query, text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML
        )

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, send_banner: bool = False):
        """Show the compact AdBot dashboard, matching the new dashboard-style UI."""
        user_id = update.effective_user.id

        # Dashboard stats
        account_count_row = self.db.fetch_one(
            "SELECT COUNT(*) FROM userbot_session WHERE user_id = ?", (user_id,)
        )
        account_count = account_count_row[0] if account_count_row else 0
        limit_data = self.db.get_user_limits(user_id)
        account_limit = limit_data.get("userbot_limit") or 1

        ad_count_row = self.db.fetch_one(
            "SELECT COUNT(*) FROM forwarding_messages WHERE user_id = ? AND is_active = 1",
            (user_id,)
        )
        ad_count = ad_count_row[0] if ad_count_row else 0
        ad_status = "running 🟢" if self.forwarding_manager.is_running else "stopped 🔴"
        interval_minutes = max(1, int(self.db.get_setting("cycle_length", "5")))
        if user_id == self.ADMIN_USER_ID:
            plan_name = "admin"
        else:
            plan_name = "free"

        # Telegram Bot API button styles:
        # primary = blue, success = green, danger = red.
        # IMPORTANT: do NOT silently fall back to an unstyled button.
        # If style is unsupported, the deployment must upgrade PTB.
        def styled_button(text, callback_data=None, style="primary", url=None):
            kwargs = {}
            if callback_data is not None:
                kwargs["callback_data"] = callback_data
            if url is not None:
                kwargs["url"] = url
            return InlineKeyboardButton(text=text, style=style, **kwargs)

        ads_button = (
            styled_button("Stop Ads ⏹️", callback_data="dashboard_run", style="danger")
            if self.forwarding_manager.is_running
            else styled_button("Run Ads ▶️", callback_data="dashboard_run", style="success")
        )

        keyboard = [
            [styled_button("👤 Manage account", callback_data="dashboard_account", style="primary")],
            [
                styled_button("📢 Set Advertisement", callback_data="dashboard_ad", style="primary"),
                styled_button("⏱ Interval & delay", callback_data="dashboard_interval", style="primary")
            ],
            [ads_button],
            [styled_button("💬 Auto reply", callback_data="dashboard_afk", style="primary"),
             styled_button("👥 Auto join", callback_data="dashboard_join", style="primary")],
            [styled_button("↗️ About bot", callback_data="dashboard_about", style="primary"),
             styled_button("↗️ Powered by", url="https://t.me/SynaxBaby", style="primary")]
        ]
        if user_id == self.ADMIN_USER_ID:
            keyboard.append([styled_button("🔐 Admin Panel", callback_data="admin_panel", style="danger")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        text = (
            "<b>━━━ SYNAX ADS BOT 🚀 ━━━</b>\n\n"
            "<b>━━ Dashboard ━━</b>\n"
            f"• Hosted Accounts: <code>{account_count}/{account_limit}</code>\n"
            f"• Service: <code>{'set' if ad_count else 'not set'}</code>\n"
            f"• Advertisement status: <i>{ad_status}</i>\n"
            f"• Interval: <i>{interval_minutes} minutes</i>\n"
            f"• Current plan: <i>{plan_name}</i>\n\n"
            "<blockquote>Developed and managed by: <b>@SynaxBaby</b></blockquote>"
        )

        if update.callback_query:
            await self._safe_edit_text(
                update.callback_query,
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        elif send_banner or (update.message and update.message.text == "/start"):
            try:
                cached_file_id = self.db.get_setting("banner_file_id", "")
                if cached_file_id:
                    sent_msg = await context.bot.send_photo(
                        chat_id=user_id, photo=cached_file_id,
                        caption=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
                    )
                else:
                    banner_bytes = self.professional_banner_generator.generate_welcome_banner()
                    sent_msg = await context.bot.send_photo(
                        chat_id=user_id, photo=banner_bytes,
                        caption=text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
                    )
                    if sent_msg.photo:
                        self.db.set_setting("banner_file_id", sent_msg.photo[-1].file_id)
                context.user_data['main_message_id'] = sent_msg.message_id
            except Exception as e:
                print(f"[Banner] {e}")
                sent_msg = await update.message.reply_text(
                    text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
                )
                context.user_data['main_message_id'] = sent_msg.message_id
        else:
            sent_msg = await update.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            context.user_data['main_message_id'] = sent_msg.message_id

    async def show_dynamic_delete_menu(self, update, context):
        user_id = update.effective_user.id
        db = self.db

        # Start new session if not already active
        if user_id not in self.temp_data or self.temp_data[user_id].get("flow_type") != "delete_dynamic":
            self.temp_data[user_id] = {
                "flow_type": "delete_dynamic",
                "selected": {}
            }

        selected = self.temp_data[user_id]["selected"]

        # Fetch all table names from SQLite
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        keyboard = []
        for table in tables:
            if table in CRITICAL_TABLES:
                continue

            is_selected = selected.get(table, False)
            status = "🟢" if is_selected else "🔴"
            label = f"{status} {table}"
            keyboard.append([
                InlineKeyboardButton(label, callback_data=f"toggle_delete_{table}")
            ])

        keyboard.append([
            InlineKeyboardButton("✅ Confirm", callback_data="delete_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="delete_cancel")
        ])

        text = (
            "🧹 *Select Tables to Wipe*\n\n"
            "• Tap to toggle\n"
            "• 🟢 = selected for deletion\n"
            "• 🔴 = skipped\n\n"
            "*Some protected settings will never be deleted.*"
        )

        await self._safe_edit_text(update.callback_query, 
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )


    async def show_settings_menu(self, update, context):
        user_id = update.effective_user.id
        """Show settings menu."""

        # ✅ Check subscription status
        if not await self.ensure_subscription_valid(update, context):
            return

        # Check userbot connection status
        userbot_connected = self.userbot_manager.client and self.userbot_manager.is_authenticated
        userbot_status = "✅ Connected" if userbot_connected else "❌ Not Connected"
        
        # Get current forward mode from settings
        forward_mode = self.get_forward_mode()
        mode_label = "Show Sender Info" if forward_mode == "show" else "Hide Sender Info"

        text = (
            "⚙️ *Settings*\n\n"
            f"🤖 *Userbot Status:* _{userbot_status}_\n"
            f"🔁 *Forward Mode:* _{mode_label}_\n"
        )
        
        if userbot_connected and forward_mode == "hide":
            text += "⚠️ _Caution: When hiding forward info, inline buttons will be removed and premium emojis may downgrade (if no premium)._\n\n"
        elif not userbot_connected:
            text += "⚠️ _Connect a userbot to change forward style._\n\n"
        else:
            text += "\n"
            
        text += "Choose a setting to configure:"

        mode_label = "Show" if forward_mode == "show" else "Hide"
        # Run all DB queries in thread pool to avoid blocking
        support_status = await self._run_db_query(self.db.get_setting, "support_access", "off")
        dot = "🟢" if support_status == "on" else "🔴"
        support_label = f"{dot} Support Access"

        logging_config = await self._run_db_query(self.db.get_user_logging_bot, user_id)
        log_bot_label = "📊 Log Bot" if not logging_config else "📊 Log Bot ✅"
        
        current_tz = await self._run_db_query(self.db.get_user_timezone, user_id)
        tz_label = f"🌍 Timezone: {current_tz}"
        
        keyboard = [
            [InlineKeyboardButton(f"🔁 Forward Style: {mode_label}", callback_data="toggle_forward_mode")],
            [InlineKeyboardButton(tz_label, callback_data="set_timezone")],
            [InlineKeyboardButton("💤 AFK Message", callback_data="settings_afk")],
            [InlineKeyboardButton(log_bot_label, callback_data="settings_log_bot")],
            [InlineKeyboardButton("🔄 Sync All Groups", callback_data="confirm_sync_groups")],
            [InlineKeyboardButton("🧹 Custom Wipe (Advanced)", callback_data="show_custom_wipe")],
            [InlineKeyboardButton("🧹 Clear All Data", callback_data="settings_clear_all")],
            [InlineKeyboardButton(support_label, callback_data="toggle_support_access")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ]

        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        if hasattr(update, "callback_query") and update.callback_query:
            try:
                await self._safe_edit_text(update.callback_query, 
                    text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass  # Ignore harmless error
                else:
                    raise
        else:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN
            )
    
    async def show_log_bot_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show logging bot configuration menu with multiple destination support."""
        user_id = update.effective_user.id
        destinations = await self._run_db_query(self.db.get_user_logging_destinations, user_id)
        
        if destinations:
            dest_list = ""
            for i, dest in enumerate(destinations, 1):
                dest_type = dest['destination_type']
                dest_title = dest.get('destination_title', 'N/A')
                dest_username = dest.get('destination_username', '')
                
                if dest_type == 'dm':
                    dest_list += f"{i}. 📨 Direct Message (DM)\n"
                elif dest_type == 'channel':
                    dest_list += f"{i}. 📢 Channel: {dest_title}"
                    if dest_username:
                        dest_list += f" (@{dest_username})"
                    dest_list += "\n"
                elif dest_type == 'group':
                    dest_list += f"{i}. 👥 Group: {dest_title}"
                    if dest_username:
                        dest_list += f" (@{dest_username})"
                    dest_list += "\n"
            
            text = (
                "📊 *Logging Bot Settings*\n\n"
                "✅ Active Logging Destinations:\n"
                f"{dest_list}\n"
                "Your forwarding logs will be sent to ALL selected destinations.\n\n"
                "Format:\n"
                "• Success: ✅ [Group] [Link]\n"
                "• Failure: ❌ [Group] - [Error]"
            )
            
            keyboard = [
                [InlineKeyboardButton("➕ Add Destination", callback_data="logbot_add")],
                [InlineKeyboardButton("🗑️ Remove All", callback_data="logbot_remove")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
            ]
        else:
            text = (
                "📊 *Logging Bot Settings*\n\n"
                "No logging destinations configured.\n\n"
                "Set up logging to send forwarding logs to:\n"
                "• 📨 Direct Message (DM)\n"
                "• 📢 Channel\n"
                "• 👥 Group\n"
                "• Or combine any of the above!\n\n"
                "Get real-time notifications of all your ad campaigns!"
            )
            
            keyboard = [
                [InlineKeyboardButton("➕ Add Logging Destination", callback_data="logbot_add")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
            ]
        
        try:
            await self._safe_edit_text(update.callback_query, 
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass
            else:
                raise

    async def update_group_join_progress(self, user_id):
        from telegram.constants import ParseMode
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        data = self.progress_containers.get(user_id)
        if not data or "progress_msg_id" not in data or "progress_chat_id" not in data:
            print(f"[PROGRESS] No progress container for user {user_id}")
            return

        print(f"[PROGRESS] Updating message for user {user_id}")
        
        # Fetch only pending joins for this specific user - this ensures message updates correctly
        rows = self.db.execute_query(
            "SELECT group_link, status FROM pending_joins WHERE user_id = ? ORDER BY id",
            (user_id,)
        )
        total = len(rows)
        joined = sum(1 for _, s in rows if s == "joined")
        failed = sum(1 for _, s in rows if s == "failed")
        pending = sum(1 for _, s in rows if s == "pending")
        
        print(f"[PROGRESS] Stats - Total: {total}, Joined: {joined}, Failed: {failed}, Pending: {pending}")

        # ✅ If nothing is pending, clear timer and optionally exit early
        if pending == 0:
            self.last_group_join_time = None
            self.db.set_setting("last_group_join_time", "")
            self.progress_containers.pop(user_id, None)

            done_msg = [
                escape_markdown("✅ All groups joined or failed. Nothing pending.", version=2),
                "",
                f"{escape_markdown('Groups queued', version=2)}: {escape_markdown(str(total), version=2)}",
                f"{escape_markdown('Joined', version=2)}: {escape_markdown(str(joined), version=2)} / {escape_markdown(str(total), version=2)}",
                f"{escape_markdown('Failed', version=2)}: {escape_markdown(str(failed), version=2)}",
                f"{escape_markdown('Pending', version=2)}: 0",
                "",
                escape_markdown("Use the button below to go back.", version=2)
            ]

            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu_groups")]
            ])

            try:
                print(f"[PROGRESS] Completion message - editing msg {data['progress_msg_id']}")
                await self.application.bot.edit_message_text(
                    text="\n".join(done_msg),
                    chat_id=data["progress_chat_id"],
                    message_id=data["progress_msg_id"],
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
                print(f"[PROGRESS] ✅ Completion message updated!")
            except BadRequest as e:
                error_str = str(e).lower()
                if "message is not modified" in error_str:
                    print(f"[PROGRESS] Message unchanged - {e}")
                elif "there is no text" in error_str:
                    try:
                        await self.application.bot.edit_message_caption(
                            caption="\n".join(done_msg),
                            chat_id=data["progress_chat_id"],
                            message_id=data["progress_msg_id"],
                            reply_markup=reply_markup,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except BadRequest:
                        pass
                else:
                    print(f"[PROGRESS] ❌ Error: {e}")
                    raise

            return

        # Continue with normal rendering if pending > 0
        page = data.get("progress_page", 0)
        page_size = 10
        total_pages = (total + page_size - 1) // page_size
        start = page * page_size
        end = start + page_size
        page_groups = rows[start:end]

        progress_lines = [
            escape_markdown('🟢 Joining Groups Progress', version=2),
            "",
            f"{escape_markdown('Groups queued', version=2)}: {escape_markdown(str(total), version=2)}",
            f"{escape_markdown('Joined', version=2)}: {escape_markdown(str(joined), version=2)} / {escape_markdown(str(total), version=2)}",
            f"{escape_markdown('Failed', version=2)}: {escape_markdown(str(failed), version=2)}",
            f"{escape_markdown('Pending', version=2)}: {escape_markdown(str(pending), version=2)}",
            ""
        ]

        # ⏳ Join timer or paused
        join_status = self.db.get_setting("group_join_enabled", "on")
        if join_status == "off":
            progress_lines.append(escape_markdown("⏸ Joining is currently paused", version=2))
        elif hasattr(self, "last_group_join_time") and self.last_group_join_time:
            elapsed = time.time() - self.last_group_join_time
            remaining = max(0, 300 - int(elapsed))
            mins = remaining // 60
            secs = remaining % 60
            timer_str = f"{mins}:{secs:02d}"
            progress_lines.append(f"⏳ Next group join in: {escape_markdown(timer_str, version=2)}")
        else:
            progress_lines.append(escape_markdown("⏳ Next group join: pending…", version=2))

        progress_lines.append("")
        for idx, (group, status) in enumerate(page_groups, start=start + 1):
            symbol = {"joined": "✅", "failed": "❌", "pending": "⏳"}.get(status, "❓")
            idx_str = escape_markdown(str(idx), version=2)
            group_str = escape_markdown(group, version=2)
            progress_lines.append(f"{idx_str}\\.{chr(32)}{group_str} {symbol}")
        progress_lines.append("")
        progress_lines.append(escape_markdown("Use the arrows to scroll, or tap Refresh.", version=2))

        # ⏯ Pause/Resume label
        toggle_label = "⏸ Pause Joining" if join_status == "on" else "▶️ Resume Joining"

        # Pagination buttons
        pagination_row = []
        if page > 0:
            pagination_row.append(InlineKeyboardButton("⬅️ Prev", callback_data="progress_prevpage"))
        if page < total_pages - 1:
            pagination_row.append(InlineKeyboardButton("Next ➡️", callback_data="progress_nextpage"))

        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="groups_processes")],
            pagination_row,
            [InlineKeyboardButton(toggle_label, callback_data="toggle_group_join")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_groups")]
        ])

        try:
            print(f"[PROGRESS] Editing progress message {data['progress_msg_id']} - J:{joined} F:{failed} P:{pending}")
            await self.application.bot.edit_message_text(
                text="\n".join(progress_lines),
                chat_id=data["progress_chat_id"],
                message_id=data["progress_msg_id"],
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            print(f"[PROGRESS] ✅ Progress message updated!")
        except BadRequest as e:
            error_str = str(e).lower()
            if "message is not modified" in error_str:
                print(f"[PROGRESS] Message unchanged (expected)")
            elif "there is no text" in error_str:
                try:
                    await self.application.bot.edit_message_caption(
                        caption="\n".join(progress_lines),
                        chat_id=data["progress_chat_id"],
                        message_id=data["progress_msg_id"],
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except BadRequest:
                    pass
            else:
                print(f"[PROGRESS] ❌ Edit failed: {e}")
                raise
        
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries - answer ULTRA FAST, process in background."""
        callback_start = time.time()
        query = update.callback_query
        data = query.data
        
        # Answer callback INSTANTLY - NO TEXT, NO ALERT, NO DELAY
        try:
            await query.answer()  # Instant callback notification
            answer_time = time.time() - callback_start
        except:
            pass
        
        # Delegate processing to a guarded background task.
        # The previous version could fail silently because callback exceptions
        # happened inside an un-awaited task.
        asyncio.create_task(self._safe_process_callback_async(update, context, data))

    async def _safe_process_callback_async(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
        try:
            await self._process_callback_async(update, context, data)
        except Exception as exc:
            logger.exception("Callback failed: %s", exc)
            try:
                await update.callback_query.answer(
                    "❌ Button action failed. Please try again.", show_alert=True
                )
            except Exception:
                pass

    async def _process_callback_async(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
        # Always define this before any authorization/DB branch.
        # The previous source referenced user_id without assigning it, which
        # caused almost every dashboard/admin callback to fail with NameError.
        user_id = update.effective_user.id
        """Process callback asynchronously in background after answering."""
        query = update.callback_query
        
        if data == "public_help" or data.startswith("help_page_"):
            # Figure out which page to show
            if data == "public_help":
                page = 0
            else:
                page = int(data.split("_")[-1])
            await self.show_help_menu(update, context, page=page)
            return

        if data == "public_back":
            await self.show_public_menu(update, context)
            return
        
        if data.startswith("gen_banner_"):
            try:
                banner_type = data.replace("gen_banner_", "")
                user_id = update.effective_user.id
                
                if banner_type == "service":
                    banner_bytes = self.professional_banner_generator.generate_service_banner()
                    caption = "Service Banner - Synax Ad Bot"
                elif banner_type == "pricing":
                    banner_bytes = self.professional_banner_generator.generate_pricing_banner()
                    caption = "Pricing Info Banner"
                elif banner_type == "features":
                    banner_bytes = self.professional_banner_generator.generate_features_banner()
                    caption = "Features Banner - Why Choose Us?"
                elif banner_type == "custom":
                    self.temp_data[user_id] = {"flow_type": "custom_banner"}
                    await query.edit_message_text(
                        "<b>Custom Banner</b>\n\n"
                        "Send the text you want on the banner in this format:\n\n"
                        "<code>Title | Subtitle</code>\n\n"
                        "Example: <code>My Service | Best in class</code>",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Cancel", callback_data="back_main")]
                        ])
                    )
                    return
                else:
                    await query.answer("Unknown banner type", show_alert=True)
                    return
                
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=banner_bytes,
                    caption=f"<b>{caption}</b>\n\nGenerated by Synax Ad Bot",
                    parse_mode=ParseMode.HTML
                )
                await query.answer("Banner generated!", show_alert=False)
            except Exception as e:
                print(f"[ERROR] Banner generation: {e}")
                await query.answer("Failed to generate banner. Please try again.", show_alert=True)
            return
        
        # Public menu feature handlers (for non-authorized users)
        if data == "public_features":
            features_text = (
                "<b>🚀 AutoBuy / AutoPay Bot Features</b>\n\n"
                "<b>Core Capabilities:</b>\n"
                "• <b>Features</b> – Complete list of tools and functions\n"
                "  - Automation, web dashboard, message support\n\n"
                "• <b>FAQ</b> – Common questions and troubleshooting\n"
                "  - How the bot works, pricing, limits\n\n"
                "• <b>Vouches</b> – Real user reviews and proofs\n"
                "  - Build trust and see credibility\n\n"
                "<b>Account & Subscription:</b>\n"
                "• <b>My Plans</b> – Active plans and expiry dates\n"
                "  - Usage details and active services\n\n"
                "• <b>My Referral</b> – Unique referral link and rewards\n"
                "  - Earn rewards for inviting others\n\n"
                "• <b>Buy Now</b> – Instant plan purchases\n"
                "  - Access all available services\n\n"
                "• <b>Deposit Balance</b> – Add funds to wallet\n"
                "  - Multiple payment methods supported\n\n"
                "<b>Customization:</b>\n"
                "• <b>Custom Branding</b> – Fully branded bot version\n"
                "  - Custom logo, name, UI, and panels"
            )
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="public_back")]]
            await self.safe_edit_message(query, features_text, keyboard)
            return
        
        if data == "public_faq":
            faq_text = (
                "<b>❓ Frequently Asked Questions</b>\n\n"
                "<b>How does the bot work?</b>\n"
                "The bot automates Telegram message forwarding and advertising distribution with speed and precision.\n\n"
                "<b>What are the pricing and plans?</b>\n"
                "We offer flexible subscription plans. Visit the Buy Now section to see current pricing.\n\n"
                "<b>Are there usage limits?</b>\n"
                "Different plans have different limits. Check your specific plan for details.\n\n"
                "<b>How do I get referral rewards?</b>\n"
                "Share your unique referral link and earn rewards for each new user.\n\n"
                "<b>What payment methods do you accept?</b>\n"
                "Multiple payment methods are supported. Use Deposit Balance to add funds.\n\n"
                "<b>Can I get a custom branded version?</b>\n"
                "Yes! Our Custom Branding service provides fully branded solutions.\n\n"
                "💡 <i>For more help, contact the developer.</i>"
            )
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="public_back")]]
            await self.safe_edit_message(query, faq_text, keyboard)
            return
        
        if data == "public_vouches":
            vouches_text = (
                "<b>⭐ User Testimonials & Vouches</b>\n\n"
                "Our users trust us for reliable Telegram automation.\n\n"
                "<i>Vouch section coming soon!</i>\n\n"
                "Once you become a subscriber, you can:\n"
                "✓ Share your success stories\n"
                "✓ Build community trust\n"
                "✓ Help others discover the bot\n\n"
                "Subscribe now to join our growing community of satisfied users!"
            )
            keyboard = [
                [InlineKeyboardButton("💳 Subscribe", url="https://t.me/SynaxBaby?text=hey%2C%20I%20Want%20Subcription%20Of%20Your%20Adbot")],
                [InlineKeyboardButton("🔙 Back", callback_data="public_back")]
            ]
            await self.safe_edit_message(query, vouches_text, keyboard)
            return
        
        if data == "buy_now":
            await self.show_subscription_plans(update, context)
            return
        
        if data.startswith("buy_plan_"):
            plan_id = data.replace("buy_plan_", "", 1)
            await self.show_fampay_payment(update, context, plan_id)
            return
        
        if data.startswith("fampay:"):
            plan_id = data.split(":", 1)[1]
            await self.show_fampay_payment(update, context, plan_id)
            return

        if data.startswith("check_fampay_"):
            purpose = data.replace("check_fampay_", "", 1)
            await self.check_fampay_payment(update, context, purpose)
            return

        if data == "cancel_fampay":
            await self.callback_cancel_fampay(update, context)
            return

        # Free-dashboard mode: normal users can access the dashboard and its
        # operational controls. Admin-only actions still perform their own
        # explicit ADMIN_USER_ID checks in their individual handlers.
        is_allowed = True


        
        # Main dashboard shortcuts
        if data == "dashboard_account":
            await self.show_userbot_menu(update, context)
        elif data == "dashboard_ad":
            await self.show_forwarding_messages_menu(update, context)
        elif data == "dashboard_interval":
            await self.show_forwarding_controls_menu(update, context)
        elif data == "dashboard_run":
            if self.forwarding_manager.is_running:
                success, message = self.forwarding_manager.stop_forwarding()
                await update.callback_query.answer(message, show_alert=not success)
                await self.show_main_menu(update, context)
            else:
                success, message = await self.forwarding_manager.start_forwarding()
                if success:
                    await update.callback_query.answer("🔵 Ads started successfully!", show_alert=False)
                    await self.show_main_menu(update, context)
                else:
                    keyboard = [
                        [InlineKeyboardButton("👤 Manage account", callback_data="dashboard_account")],
                        [
                            InlineKeyboardButton("📢 Set Advertisement", callback_data="dashboard_ad"),
                            InlineKeyboardButton("⏱ Interval & delay", callback_data="dashboard_interval")
                        ],
                        [InlineKeyboardButton("👥 Groups / DMs", callback_data="dashboard_interval")],
                        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_main")]
                    ]
                    await self._safe_edit_text(
                        update.callback_query,
                        f"❌ <b>Ads could not be started</b>\n\n{message}\n\nComplete the required setup above, then tap <b>Run Ads</b> again.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.HTML
                    )
        elif data == "dashboard_afk":
            # Reuse the existing AFK/auto-reply settings UI.
            user_id = update.effective_user.id
            afk_enabled = self.db.get_user_setting(user_id, "afk_enabled", "off")
            afk_message = self.db.get_user_setting(user_id, "afk_message", "Not set")
            keyboard = [
                [InlineKeyboardButton("📝 Set Message", callback_data="settings_afk_set")],
                [InlineKeyboardButton("🗑️ Remove Message", callback_data="settings_afk_remove")],
                [InlineKeyboardButton("⏯ Toggle", callback_data="settings_afk_toggle")],
                [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
            ]
            await self._safe_edit_text(
                update.callback_query,
                f"💬 <b>Auto Reply</b>\n\nStatus: <b>{'ON 🟢' if afk_enabled == 'on' else 'OFF 🔴'}</b>\n\nCurrent message:\n<code>{html.escape(str(afk_message))}</code>",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.HTML
            )
        elif data == "dashboard_join":
            await self.show_groups_menu(update, context)
        elif data == "dashboard_premium":
            # Legacy callback compatibility. Premium purchase UI is intentionally disabled.
            await update.callback_query.answer("Premium purchasing is disabled for users.", show_alert=True)
            await self.show_main_menu(update, context)
        elif data == "dashboard_about":
            await self.show_help_menu(update, context, page=0)

        # Main menu handlers
        elif data == "menu_userbot":
            await self.show_userbot_menu(update, context)
        elif data == "menu_groups":
            await self.show_groups_menu(update, context)
        elif data == "menu_forwarding":
            await self.show_forwarding_menu(update, context)
        elif data == "menu_status":
            await self.show_status_menu(update, context)
        elif data == "status_live":
            await self.show_live_status(update, context)
        elif data == "status_analytics":
            await self.show_analytics_dashboard(update, context)
        elif data == "status_logs":
            await self.show_logs(update, context)
        elif data == "status_trace":
            await self.show_live_trace(update, context, page=0)
        elif data.startswith("help_page_"):
            page_num = int(data.split("_")[-1])
            await self.show_help_menu(update, context, page=page_num)

        elif data == "menu_help":
            await self.show_help_menu(update, context, page=0)
        elif data == "menu_settings":
            await self.show_settings_menu(update, context)
        elif data == "back_main":
            await self.show_main_menu(update, context)
        
        elif data == "forwarding_preview":
            await self.show_forwarding_preview(update, context)
        
        elif data == "support_menu":
            await self.show_support_menu(update, context)
        
        elif data == "support_subscription":
            active, status = self.get_subscription_status()
            keyboard = [
                [InlineKeyboardButton("🔙 Back", callback_data="support_menu")]
            ]
            await self._safe_edit_text(update.callback_query, 
                text=status,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == "set_join_interval":
            # Run DB query in thread pool to avoid blocking
            current = int(await self._run_db_query(self.db.get_join_interval, user_id)) // 60
            await self._safe_edit_text(update.callback_query, 
                f"⏱ *Set Join Interval*\n\n"
                f"Current interval: `{current}` minutes\n\n"
                "Please enter a new join interval in minutes (minimum: 5 minutes):",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="groups_processes")]
                ])
            )
            self.temp_data[update.effective_user.id] = {"flow_type": "set_join_interval"}
        
        elif data.startswith("userbot_detail_"):
            # Show userbot details and message assignment
            userbot_id = int(data.split("_")[-1])
            await self.show_userbot_detail(update, context, userbot_id)
        
        elif data.startswith("assign_messages_"):
            # Assign messages to userbot
            userbot_id = int(data.split("_")[-1])
            await self.show_userbot_message_assignment(update, context, userbot_id)
        
        elif data == "set_timezone":
            # Run DB query in thread pool to avoid blocking
            current_tz = await self._run_db_query(self.db.get_user_timezone, user_id)
            await self._safe_edit_text(update.callback_query, 
                f"🌍 *Set Timezone*\n\n"
                f"Current timezone: `{current_tz}`\n\n"
                "Enter your timezone in one of these formats:\n"
                "• GMT offset: `+05:30` or `-08:00`\n"
                "• Country name: `India`, `USA`, `United Kingdom`\n\n"
                "Examples:\n"
                "• For India: `+05:30` or `India`\n"
                "• For New York: `-05:00` or `USA`\n"
                "• For London: `+00:00` or `United Kingdom`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
                ])
            )
            self.temp_data[update.effective_user.id] = {"flow_type": "set_timezone"}
        
        elif data == "set_hold_duration":
            current = self.db.get_setting("hold_duration", "15")
            await self._safe_edit_text(update.callback_query, 
                f"🕒 *Set Hold Duration*\n\n"
                f"Current hold time: `{current}` minutes\n\n"
                "Please enter a new hold duration (minimum: 15 minutes):",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                ])
            )
            self.temp_data[update.effective_user.id] = {"flow_type": "set_hold_duration"}

        elif data == "set_cycle_length":
            current = self.db.get_setting("cycle_length", "120")
            await self._safe_edit_text(update.callback_query, 
                f"♻️ *Set Cycle Length*\n\n"
                f"Current cycle duration: `{current}` minutes\n\n"
                f"Enter a new cycle length (minimum: 10 minutes):",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                ])
            )
            self.temp_data[update.effective_user.id] = {"flow_type": "set_cycle_length"}

        elif data == "support_add_minutes":
            self.temp_data[user_id] = {"flow_type": "support_add"}
            current = self.db.get_setting("subscription_duration", "0")
            await self._safe_edit_text(update.callback_query, 
                f"✏️ *Add Minutes*\n\nCurrent Duration: `{current}` minutes\n\nEnter how many minutes to add:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="support_menu")]])
            )

        elif data == "support_subtract_minutes":
            self.temp_data[update.effective_user.id] = {"flow_type": "support_subtract"}
            await self._safe_edit_text(update.callback_query, 
                "✏️ Enter how many minutes to *subtract* from the subscription:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="support_menu")]
                ])
            )
            
        elif data == "support_userid":
            uid = self.db.get_setting("admin_user_id", "Unknown")
            await self._safe_edit_text(update.callback_query, 
                f"👤 Admin User ID: `{uid}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="support_menu")]])
            )

        elif data == "support_ping":
            userbot_status = await self.userbot_manager.get_status()
            await self._safe_edit_text(update.callback_query, 
                f"📶 *Ping Result:*\n\n"
                f"Status: {userbot_status['status']}\n"
                f"User: {userbot_status['user_info']}\n"
                f"Last Active: {userbot_status['last_activity']}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="support_menu")]])
            )

        elif data == "settings_alter_delay":
            current = self.db.get_setting("per_message_delay", "30")
            await self._safe_edit_text(update.callback_query, 
                f"⏱ *Alter Per-Message Delay*\n\n"
                f"Current delay: `{current}` seconds\n\n"
                "Please enter a new delay (minimum: 30 seconds):",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                ])
            )
            self.temp_data[update.effective_user.id] = {"flow_type": "alter_delay"}
            

        elif data == "confirm_sync_groups":
            text = (
                "⚠️ *Sync All Groups*\n\n"
                "This will scan all groups and channels the userbot is currently joined to, "
                "and update the internal group list. Any missing groups will be added.\n\n"
                "*Are you sure you want to continue?*"
            )
            keyboard = [
                [InlineKeyboardButton("✅ Yes, Sync Now", callback_data="sync_groups_now")],
                [InlineKeyboardButton("❌ Cancel", callback_data="menu_settings")]
            ]
            await self._safe_edit_text(update.callback_query, 
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "sync_groups_now":
            await self._safe_edit_text(update.callback_query, "🔄 Syncing groups... Please wait.")
            try:
                if not self.userbot_manager.client or not self.userbot_manager.is_authenticated:
                    await self._safe_edit_text(update.callback_query,
                        "❌ Userbot not connected. Please connect your userbot first.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]])
                    )
                    return

                result = await self.userbot_manager.fetch_groups(user_id)
                total = result.get("total", 0)
                new_c = result.get("new", 0)
                existing_c = result.get("existing", 0)

                await self._safe_edit_text(update.callback_query,
                    f"✅ Sync done!\n\n"
                    f"📊 Total: {total} groups\n"
                    f"🆕 New: {new_c}\n"
                    f"♻️ Existing: {existing_c}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📋 View Groups", callback_data="groups_view")],
                        [InlineKeyboardButton("🔁 Sync Again", callback_data="sync_groups_now")],
                        [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
                    ])
                )
            except Exception as e:
                print(f"[SYNC ERROR] {e}")
                await self._safe_edit_text(update.callback_query,
                    f"❌ Sync failed: {str(e)}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]])
                )


        elif data == "toggle_support_access":
            current = self.db.get_setting("support_access", "off")
            if current == "on":
                # Confirm turning OFF
                text = (
                    "⚠️ *Disable Support Access*\n\n"
                    "Turning this OFF will revoke panel access from the support team.\n\n"
                    "*Are you sure?*"
                )
                confirm_cb = "confirm_support_off"
            else:
                # Confirm turning ON
                text = (
                    "⚠️ *Enable Support Access*\n\n"
                    "This will grant full control of your panel to our support staff.\n"
                    "They can view your groups, messages, logs, and settings to assist you.\n\n"
                    "*Are you sure you want to continue?*"
                )
                confirm_cb = "confirm_support_on"

            keyboard = [
                [InlineKeyboardButton("✅ Yes, Proceed", callback_data=confirm_cb)],
                [InlineKeyboardButton("❌ Cancel", callback_data="menu_settings")]
            ]

            await self._safe_edit_text(update.callback_query, 
                text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )

        elif data == "confirm_support_on":
            self.db.set_setting("support_access", "on")
            for uid in SUPPORT_USER_IDS:
                try:
                    await self.application.bot.send_message(uid, "✅ Support access has been granted. You can now access the user's panel.")
                except Exception as e:
                    print(f"[Support Access] Notify error: {e}")
            await update.callback_query.answer("✅ Support access enabled.")
            await self.show_settings_menu(update, context)

        elif data == "confirm_support_off":
            self.db.set_setting("support_access", "off")
            for uid in SUPPORT_USER_IDS:
                try:
                    await self.application.bot.send_message(uid, "🚫 Support access has been revoked. You no longer have access.")
                except Exception as e:
                    print(f"[Support Access] Notify error: {e}")
            await update.callback_query.answer("🚫 Support access disabled.")
            await self.show_settings_menu(update, context)

        
        elif data.startswith("logs_page_"):
            page = int(data.split("_")[-1])
            await self.show_logs(update, context, page=page)

        elif data == "groups_processes":
            user_id = update.effective_user.id

            # Load pending joins for this user only
            rows = self.db.execute_query(
                "SELECT group_link, status FROM pending_joins WHERE user_id = ? ORDER BY id",
                (user_id,)
            )
            total = len(rows)
            joined = sum(1 for _, s in rows if s == "joined")
            failed = sum(1 for _, s in rows if s == "failed")
            pending = sum(1 for _, s in rows if s == "pending")

            page = 0
            page_size = 10
            total_pages = (total + page_size - 1) // page_size
            start = page * page_size
            end = start + page_size
            page_groups = rows[start:end]

            progress_lines = [
                escape_markdown("🟢 Joining Groups Progress", version=2),
                "",
                f"{escape_markdown('Groups queued', version=2)}: {escape_markdown(str(total), version=2)}",
                f"{escape_markdown('Joined', version=2)}: {escape_markdown(str(joined), version=2)}",
                f"{escape_markdown('Failed', version=2)}: {escape_markdown(str(failed), version=2)}",
                f"{escape_markdown('Pending', version=2)}: {escape_markdown(str(pending), version=2)}",
                ""
            ]

            # Show timer or pause status
            interval = 300
            join_status = self.db.get_setting("group_join_enabled", "on")
            if join_status == "off":
                progress_lines.append(escape_markdown("⏸ Group joining is currently paused.", version=2))
            elif hasattr(self, "last_group_join_time") and self.last_group_join_time:
                elapsed = time.time() - self.last_group_join_time
                remaining = max(0, interval - int(elapsed))
                mins = remaining // 60
                secs = remaining % 60
                timer_str = f"{mins}:{secs:02d}"
                progress_lines.append(escape_markdown(f"⏳ Next group join in: {timer_str}", version=2))
            else:
                progress_lines.append(escape_markdown("⏳ Next group join: pending…", version=2))

            progress_lines.append("")

            # Add group lines with safe escaping
            for idx, (group, status) in enumerate(page_groups, start=start + 1):
                symbol = {"joined": "✅", "failed": "❌", "pending": "⏳"}.get(status, "❓")
                try:
                    idx_str = escape_markdown(str(idx), version=2)
                    group_str = escape_markdown(group, version=2)
                    progress_lines.append(f"{idx_str}\\.{chr(32)}{group_str} {symbol}")
                except Exception as e:
                    print(f"[MarkdownEscapeError] Failed escaping group {group}: {e}")
                    safe_group = group.replace(".", "\\.").replace("-", "\\-")
                    progress_lines.append(f"{idx}\\.{chr(32)}{safe_group} {symbol}")

            progress_lines.append("")
            progress_lines.append(escape_markdown("Use the arrows to scroll, or tap Refresh.", version=2))

            # UI buttons
            toggle_label = "⏸ Pause Joining" if join_status == "on" else "▶️ Resume Joining"

            pagination_row = []
            if page > 0:
                pagination_row.append(InlineKeyboardButton("⬅️ Prev", callback_data="progress_prevpage"))
            if page < total_pages - 1:
                pagination_row.append(InlineKeyboardButton("Next ➡️", callback_data="progress_nextpage"))

            interval_button = [InlineKeyboardButton("⏱ Join Interval", callback_data="set_join_interval")]
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="groups_processes")],
                pagination_row,
                interval_button,
                [InlineKeyboardButton(toggle_label, callback_data="toggle_group_join")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_groups")]
            ])

            text = "\n".join(progress_lines)
            original_text = update.callback_query.message.text or ""

            try:
                if original_text.startswith("👥 Groups Management") or "Select an option" in original_text:
                    msg = await update.effective_chat.send_message(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode="MarkdownV2"
                    )
                else:
                    msg = await self._safe_edit_text(update.callback_query, 
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode="MarkdownV2"
                    )
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    return  # Silent ignore
                else:
                    raise

            # Save progress pointer
            self.progress_containers[user_id] = {
                "progress_msg_id": msg.message_id,
                "progress_chat_id": msg.chat_id,
                "progress_page": 0
            }

        elif data.startswith("trace_page_"):
            page = int(data.split("_")[-1])
            await self.show_live_trace(update, context, page=page)

        elif data == "trace_clear":
            self.db.execute_query("DELETE FROM forward_trace")
            await update.callback_query.answer("🧹 Cleared all trace logs.")
            await self.show_live_trace(update, context, page=0)

        elif data == "userbot_retry_password":
            user_id = update.effective_user.id
            if user_id in self.temp_data:
                self.temp_data[user_id]["step"] = "password"
                await self._safe_edit_text(update.callback_query, 
                    "🔐 Re-enter your 2FA password:",
                    parse_mode=ParseMode.MARKDOWN
                )

        elif data == "userbot_retry_phone":
            user_id = update.effective_user.id
            if user_id in self.temp_data:
                self.temp_data[user_id]["step"] = "phone"
                await self._safe_edit_text(update.callback_query, 
                    "📱 Re-enter your phone number (with +):\n\nExample: +1234567890",
                    parse_mode=ParseMode.MARKDOWN
                )


        elif data == "show_custom_wipe":
            await self.show_dynamic_delete_menu(update, context)

        elif data.startswith("toggle_delete_"):
            table = data.replace("toggle_delete_", "")
            flow = self.temp_data.get(user_id, {})
            if flow.get("flow_type") == "delete_dynamic":
                selected = flow["selected"]
                selected[table] = not selected.get(table, False)
                await self.show_dynamic_delete_menu(update, context)

        elif data == "delete_confirm":
            flow = self.temp_data.get(user_id, {})
            selected = flow.get("selected", {})
            deleted_tables = []

            for table, should_delete in selected.items():
                if not should_delete:
                    continue

                # Handle settings table specially
                if table == "settings":
                    self.db.execute_query(
                        "DELETE FROM settings WHERE key NOT IN (?, ?, ?, ?)",
                        tuple(CRITICAL_SETTINGS_KEYS)
                    )
                else:
                    self.db.execute_query(f"DELETE FROM {table}")

                deleted_tables.append(table)

            del self.temp_data[user_id]

            await self._safe_edit_text(update.callback_query, 
                "✅ *Deleted tables:*\n" +
                "\n".join([f"• `{t}`" for t in deleted_tables]) +
                "\n\nSubscription/admin settings preserved.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")]
                ])
            )

        elif data == "delete_cancel":
            del self.temp_data[user_id]
            await self._safe_edit_text(update.callback_query, 
                "❌ Cancelled wipe.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
                ])
            )

        elif data == "settings_clear_all":
            keyboard = [
                [InlineKeyboardButton("✅ Yes, clear EVERYTHING", callback_data="settings_clear_all_confirm")],
                [InlineKeyboardButton("❌ Cancel", callback_data="menu_settings")]
            ]
            text = (
                "⚠️ *Are you sure you want to clear ALL bot data?*\n\n"
                "This will delete:\n"
                "• All userbot sessions\n"
                "• All groups\n"
                "• All forwarding messages\n"
                "• All settings\n"
                "• All logs\n"
                "• All pending joins\n\n"
                "*This cannot be undone!*"
            )
            await self._safe_edit_text(update.callback_query, 
                text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
            )

        elif data == "toggle_forward_mode":
            userbot_connected = self.userbot_manager.client and self.userbot_manager.is_authenticated
            
            if not userbot_connected:
                text = (
                    "⚠️ *No Userbot Connected*\n\n"
                    "You need to connect a userbot account first to change forward style.\n\n"
                    "Please add your userbot to enable this feature."
                )
                keyboard = [
                    [InlineKeyboardButton("➕ Add Userbot", callback_data="menu_userbot")],
                    [InlineKeyboardButton("🔙 Back to Settings", callback_data="menu_settings")]
                ]
                try:
                    await self._safe_edit_text(update.callback_query, 
                        text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    await update.callback_query.answer()
                except BadRequest as e:
                    if "Message is not modified" not in str(e):
                        raise
                return

            current_mode = self.get_forward_mode()
            new_mode = "hide" if current_mode == "show" else "show"
            self.set_forward_mode(new_mode)

            has_premium = False
            try:
                me = await self.userbot_manager.client.get_me()
                has_premium = getattr(me, "premium", False)
            except Exception:
                pass

            if new_mode == "show":
                await update.callback_query.answer(
                    "✅ SHOW mode enabled\n\n"
                    "Messages will be forwarded WITH attribution\n"
                    '(Shows "Forwarded from..." header)',
                    show_alert=True
                )
            else:
                if not has_premium:
                    await update.callback_query.answer(
                        "✅ HIDE mode enabled\n\n"
                        "⚠️ CAUTION:\n"
                        "• Premium emojis will appear as regular emojis (no premium)\n"
                        "• Inline buttons will be HIDDEN (converted to text)\n\n"
                        "Messages will be sent as NEW (no forward header)",
                        show_alert=True
                    )
                else:
                    await update.callback_query.answer(
                        "✅ HIDE mode enabled\n\n"
                        "⚠️ CAUTION:\n"
                        "• Premium emojis will work perfectly ✅\n"
                        "• Inline buttons will still be HIDDEN (converted to text)\n\n"
                        "Messages will be sent as NEW (no forward header)",
                        show_alert=True
                    )

            await self.show_settings_menu(update, context)

        elif data == "settings_clear_all_confirm":
            # 1. Delete from all non-critical tables
            tables_to_clear = [
                "userbot_session", "groups", "forwarding_messages",
                "logs", "pending_joins", "forward_trace", "afk_replies"
            ]
            for t in tables_to_clear:
                self.db.execute_query(f"DELETE FROM {t}")

            # 2. Keep subscription + bot token info only
            self.db.execute_query(
                "DELETE FROM settings WHERE key NOT IN (?, ?, ?, ?)",
                ("bot_token", "admin_user_id", "subscription_start", "subscription_duration")
            )

            # 3. Reset forwarding state
            self.forwarding_manager.forwarded_groups_set = set()
            self.forwarding_manager.stats = {
                "total_forwarded": 0,
                "last_forward_time": None,
                "next_forward_time": None,
                "errors": 0
            }

            # 4. Disconnect and remove userbot session
            try:
                if self.userbot_manager.client:
                    await self.userbot_manager.client.disconnect()
                self.userbot_manager.client = None
                self.userbot_manager.is_authenticated = False
            except Exception as e:
                self.db.log_event("ERROR", f"Error disconnecting userbot: {str(e)}")

            # 5. Remove session file(s)
            import os
            session_prefix = self.userbot_manager.session_file  # e.g., "liam_adbot"
            session_files = [f for f in os.listdir('.') if f.startswith(session_prefix)]
            for file in session_files:
                try:
                    os.remove(file)
                except Exception as e:
                    self.db.log_event("ERROR", f"Failed to remove session file {file}: {str(e)}")

            # 6. Notify user
            try:
                await self._safe_edit_text(update.callback_query, 
                    "🧹 *All bot data has been permanently cleared!*\n\n"
                    "✅ Subscription info and bot config have been preserved.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]]),
                    parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise

        
        # Admin Panel Actions
        elif data == "admin_panel":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True)
                return
            text, markup = await self._show_admin_panel(update, context)
            await self._safe_edit_text(update.callback_query, text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        
        elif data == "admin_approve_user":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True)
                return
            self.temp_data[user_id] = {"flow_type": "admin_approve", "step": "user_id"}
            await self._safe_edit_text(update.callback_query, "👤 *Approve User*\n\nSend the User ID:", parse_mode=ParseMode.MARKDOWN)
        
        elif data == "admin_extend_time":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True)
                return
            self.temp_data[user_id] = {"flow_type": "admin_extend", "step": "user_id"}
            await self._safe_edit_text(update.callback_query, "⏰ *Extend Time*\n\nSend the User ID:", parse_mode=ParseMode.MARKDOWN)
        
        elif data == "admin_broadcast":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True)
                return
            self.temp_data[user_id] = {"flow_type": "admin_broadcast", "send_dm": True, "send_group": True, "step": "message"}
            await self._show_broadcast_setup(update, context)
        
        elif data == "broadcast_toggle_dm":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied", show_alert=True); return
            flow=self.temp_data.setdefault(user_id,{"flow_type":"admin_broadcast","send_dm":True,"send_group":True,"step":"message"})
            flow["send_dm"]=not bool(flow.get("send_dm",True))
            await self._show_broadcast_setup(update,context)

        elif data == "broadcast_toggle_group":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied", show_alert=True); return
            flow=self.temp_data.setdefault(user_id,{"flow_type":"admin_broadcast","send_dm":True,"send_group":True,"step":"message"})
            flow["send_group"]=not bool(flow.get("send_group",True))
            await self._show_broadcast_setup(update,context)

        elif data == "broadcast_send":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied", show_alert=True); return
            await self._run_saved_broadcast(update,context)

        elif data == "admin_fampay_config":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True); return
            self.reload_fampay_config()
            masked = (self.fampay_app_password[:2] + "••••••••" + self.fampay_app_password[-2:]) if len(self.fampay_app_password) > 4 else ("Configured" if self.fampay_app_password else "Not set")
            prices = ", ".join(f"{k} ₹{self.fampay_prices.get(k,0):g}" for k in self.SUBSCRIPTION_PLANS)
            text = (f"🇮🇳 <b>Auto Fampay Configuration</b>\n\n"
                    f"Status: <b>{'🟢 ON' if self.fampay_configured() else '🔴 OFF / Incomplete'}</b>\n"
                    f"API: <code>{html.escape(self.fampay_api_url)}</code>\n"
                    f"Gmail: <code>{html.escape(self.fampay_gmail or 'Not set')}</code>\n"
                    f"App Password: <code>{html.escape(masked)}</code>\n"
                    f"UPI ID: <code>{html.escape(self.fampay_upi_id or 'Not set')}</code>\n"
                    f"UPI Name: <code>{html.escape(self.fampay_upi_name)}</code>\n"
                    f"Prices: <code>{html.escape(prices)}</code>\n\n"
                    "Configure the gateway credentials and UPI details below. The bot verifies payments automatically by purpose.")
            masked_key = (self.fampay_api_key[:4] + "••••••••" + self.fampay_api_key[-4:]) if len(self.fampay_api_key) > 8 else ("Configured" if self.fampay_api_key else "Not set")
            text += f"\nAPI Key: <code>{html.escape(masked_key)}</code>"
            keyboard = [
                [InlineKeyboardButton("🔘 Toggle ON/OFF", callback_data="admin_fampay_toggle", style="primary")],
                [InlineKeyboardButton("🌐 Set API URL", callback_data="admin_fampay_api", style="primary"), InlineKeyboardButton("🔑 Set API Key", callback_data="admin_fampay_key", style="primary")],
                [InlineKeyboardButton("📧 Set Gmail", callback_data="admin_fampay_gmail", style="primary")],
                [InlineKeyboardButton("🔐 Set App Password", callback_data="admin_fampay_pass", style="primary"), InlineKeyboardButton("💳 Set UPI ID", callback_data="admin_fampay_upi", style="primary")],
                [InlineKeyboardButton("🏷 Set UPI Name", callback_data="admin_fampay_name", style="primary"), InlineKeyboardButton("💰 Set Prices", callback_data="admin_fampay_prices", style="primary")],
                [InlineKeyboardButton("🔄 Refresh", callback_data="admin_fampay_config", style="primary")],
                [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel", style="danger")]
            ]
            await self._safe_edit_text(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

        elif data == "admin_fampay_toggle":
            if user_id != self.ADMIN_USER_ID: await update.callback_query.answer("❌ Access Denied", show_alert=True); return
            new_state = "0" if self.db.get_setting("fampay_enabled", "0") == "1" else "1"
            self.db.set_setting("fampay_enabled", new_state); self.reload_fampay_config()
            await update.callback_query.answer("Fampay " + ("enabled" if new_state == "1" else "disabled"))
            # Re-render config
            await self._safe_edit_text(update.callback_query, "🇮🇳 <b>Fampay setting updated.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Open Configuration", callback_data="admin_fampay_config", style="primary")],[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel", style="danger")]]), parse_mode=ParseMode.HTML)

        elif data in ("admin_fampay_api", "admin_fampay_key", "admin_fampay_gmail", "admin_fampay_pass", "admin_fampay_upi", "admin_fampay_name", "admin_fampay_prices"):
            if user_id != self.ADMIN_USER_ID: await update.callback_query.answer("❌ Access Denied", show_alert=True); return
            field_map = {
                "admin_fampay_api": ("fampay_api_url", "🌐 Send Fampay API URL"),
                "admin_fampay_key": ("fampay_api_key", "🔑 Send Fampay API Key (optional; leave blank if your gateway uses Gmail/App Password)"),
                "admin_fampay_gmail": ("fampay_gmail", "📧 Send Gmail used by the Fampay gateway"),
                "admin_fampay_pass": ("fampay_app_password", "🔐 Send the Gmail App Password used by the Fampay gateway"),
                "admin_fampay_upi": ("fampay_upi_id", "💳 Send the UPI ID where customers should pay"),
                "admin_fampay_name": ("fampay_upi_name", "🏷 Send the UPI display name"),
                "admin_fampay_prices": ("fampay_prices", "💰 Send prices as: 1_month=20,3_months=50,6_months=90,lifetime=150")
            }
            key, prompt = field_map[data]
            self.temp_data[user_id] = {"flow_type": "admin_fampay_set", "field": key}
            await self._safe_edit_text(update.callback_query, f"<b>{prompt}</b>\n\nSend the value now.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_fampay_config", style="danger")]]), parse_mode=ParseMode.HTML)

        elif data == "admin_remove_user":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True)
                return
            self.temp_data[user_id] = {"flow_type": "admin_remove", "step": "user_id"}
            await self._safe_edit_text(update.callback_query, "❌ *Remove User*\n\nSend the User ID:", parse_mode=ParseMode.MARKDOWN)
        
        elif data == "admin_set_limits":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True)
                return
            self.temp_data[user_id] = {"flow_type": "admin_set_limits", "step": "user_id"}
            await self._safe_edit_text(update.callback_query, "⚙️ *Set User Limits*\n\nSend the User ID:", parse_mode=ParseMode.MARKDOWN)
        
        elif data == "admin_list_users":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True)
                return
            text = self._get_authorized_users_list()
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data="admin_list_users")],
                [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]
            ]
            await self._safe_edit_text(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        
        elif data == "admin_set_bio":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True)
                return
            self.temp_data[user_id] = {"flow_type": "admin_set_bio"}
            current_bio = self.db.get_admin_setting('default_bio', 'Hosted By @SynaxBaby')
            await self._safe_edit_text(update.callback_query, 
                f"📝 *Set Default Bio*\n\nCurrent bio: `{current_bio}`\n\nSend the new default bio text for userbots:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
            )
        
        elif data == "admin_set_lastname":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True)
                return
            self.temp_data[user_id] = {"flow_type": "admin_set_lastname"}
            current_lastname = self.db.get_admin_setting('default_lastname', 'Hosted By @SynaxBaby')
            await self._safe_edit_text(update.callback_query, 
                f"✏️ *Set Default Last Name*\n\nCurrent last name: `{current_lastname}`\n\nSend the new default last name for userbots:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
            )
        
        elif data == "admin_set_interval":
            if user_id != self.ADMIN_USER_ID:
                await update.callback_query.answer("❌ Access Denied: Admin Only", show_alert=True)
                return
            self.temp_data[user_id] = {"flow_type": "admin_set_interval"}
            current_interval = int(self.db.get_admin_setting('join_interval', '300')) // 60
            await self._safe_edit_text(update.callback_query, 
                f"⏱ *Set Join Interval*\n\nCurrent interval: `{current_interval} minutes`\n\nSend the new interval in minutes (e.g., 5, 10, 30):",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")]])
            )

        elif data == "settings_log_bot":
            await self.show_log_bot_menu(update, context)
        
        elif data == "logbot_add":
            await self._safe_edit_text(update.callback_query, 
                "📊 *Setup Logging Bot*\n\n"
                "Please send me your bot token.\n\n"
                "🔹 Get a bot token from @BotFather\n"
                "🔹 Make sure you have started your bot\n\n"
                "Send the token now:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Cancel", callback_data="settings_log_bot")]
                ])
            )
            self.temp_data[update.effective_user.id] = {"flow_type": "logbot_token"}
        
        elif data == "logbot_destination_dm":
            user_id = update.effective_user.id
            if user_id in self.temp_data and "logbot_token" in self.temp_data[user_id]:
                bot_token = self.temp_data[user_id]["logbot_token"]
                success, message = await self.logging_bot_manager.setup_destination(
                    user_id=user_id,
                    bot_token=bot_token,
                    destination_type='dm'
                )
                await update.callback_query.answer(message[:200])
                if user_id in self.temp_data:
                    del self.temp_data[user_id]
                await self.show_log_bot_menu(update, context)
        
        elif data == "logbot_destination_channel":
            await self._safe_edit_text(update.callback_query, 
                "📊 *Setup Channel Destination*\n\n"
                "Please follow these steps:\n\n"
                "1️⃣ Add your logging bot as admin to your channel\n"
                "2️⃣ Send the channel username or link\n\n"
                "Example: @mychannel or https://t.me/mychannel",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Cancel", callback_data="settings_log_bot")]
                ])
            )
            if update.effective_user.id in self.temp_data:
                self.temp_data[update.effective_user.id]["flow_type"] = "logbot_channel"
        
        elif data == "logbot_destination_group":
            await self._safe_edit_text(update.callback_query, 
                "📊 *Setup Group Destination*\n\n"
                "Please follow these steps:\n\n"
                "1️⃣ Add your logging bot as admin to your group\n"
                "2️⃣ Send the group username or link\n\n"
                "Example: @mygroup or https://t.me/mygroup",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Cancel", callback_data="settings_log_bot")]
                ])
            )
            if update.effective_user.id in self.temp_data:
                self.temp_data[update.effective_user.id]["flow_type"] = "logbot_group"
        
        elif data == "logbot_remove":
            user_id = update.effective_user.id
            self.db.remove_user_logging_bot(user_id)
            await update.callback_query.answer("✅ Logging bot removed successfully!")
            await self.show_log_bot_menu(update, context)
        
        elif data == "settings_afk":
            user_id = update.effective_user.id
            afk_enabled = self.db.get_user_setting(user_id, "afk_enabled", "off")
            afk_message = self.db.get_user_setting(user_id, "afk_message", "Hello, this is my adbot account. Please contact me at @username.")
            on_off_button = InlineKeyboardButton(
                "✅ Turn OFF" if afk_enabled == "on" else "✅ Turn ON",
                callback_data="settings_afk_toggle"
            )
            keyboard = [
                [InlineKeyboardButton("📝 Set Message", callback_data="settings_afk_set")],
                [InlineKeyboardButton("🗑️ Remove Message", callback_data="settings_afk_remove")],
                [on_off_button],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
            ]
            text = (
                f"💤 *AFK Message Settings*\n\n"
                f"Status: {'ON' if afk_enabled == 'on' else 'OFF'}\n"
                f"Current message:\n"
                f"_{afk_message}_"
            )
            try:
                await self._safe_edit_text(update.callback_query, 
                    text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    # Ignore harmless error
                    pass
                else:
                    raise

        elif data == "settings_afk_set":
            self.temp_data[update.effective_user.id] = {"flow_type": "afk_set"}
            try:
                await self._safe_edit_text(update.callback_query, 
                    "✏️ *Send the new AFK message now:*",
                    parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    raise

        elif data == "settings_afk_remove":
            user_id = update.effective_user.id
            self.db.set_user_setting(user_id, "afk_message", "")
            try:
                await self._safe_edit_text(update.callback_query, 
                    "🗑️ *AFK message removed!*",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="settings_afk")]]),
                    parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    raise

        elif data == "settings_afk_toggle":
            user_id = update.effective_user.id
            afk_enabled = self.db.get_user_setting(user_id, "afk_enabled", "off")
            new_status = "off" if afk_enabled == "on" else "on"
            self.db.set_user_setting(user_id, "afk_enabled", new_status)
            try:
                await self._safe_edit_text(update.callback_query, 
                    f"{'☑️ AFK is now ON.' if new_status == 'on' else '❌ AFK is now OFF.'}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="settings_afk")]]),
                    parse_mode=ParseMode.MARKDOWN
                )
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    raise


        elif data == "subscription":
            await self.show_subscription_status(update, context)
        elif data == "subscription_refresh":
            await self.show_subscription_status(update, context)
        elif data == "menu_back":
            await self.show_main_menu(update, context)

        # Userbot handlers
        elif data == "userbot_add":
            await self.start_userbot_add_flow(update, context)
        elif data == "userbot_remove" or data.startswith("userbot_remove_") and not data == "userbot_remove_confirm":
            await self.userbot_remove_confirm(update, context)
        elif data == "userbot_remove_confirm":
            await self.userbot_remove_execute(update, context)
        elif data == "userbot_status":
            await self.show_userbot_status(update, context)
        

        elif data == "userbot_retry_code":
            # Let user retry the verification code
            user_id = update.effective_user.id
            if user_id in self.temp_data:
                self.temp_data[user_id]["step"] = "otp"
                await self._safe_edit_text(update.callback_query, 
                    "🔁 Re-enter the OTP code:",
                    parse_mode=ParseMode.MARKDOWN
                )

        elif data == "userbot_resend_code":
            # Re-send the login code
            user_id = update.effective_user.id
            flow_data = self.temp_data.get(user_id)
            if flow_data:
                try:
                    await self.userbot_manager.client.send_code_request(flow_data["phone"])
                    await self._safe_edit_text(update.callback_query, 
                        "📲 New OTP sent!\nEnter the code:",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    self.temp_data[user_id]["step"] = "otp"
                except Exception as e:
                    await self._safe_edit_text(update.callback_query, 
                        f"❌ Failed to resend:\n{str(e)}",
                        parse_mode=ParseMode.MARKDOWN
                    )


        # Groups handlers
        elif data == "groups_add":
            await self.start_groups_add_flow(update, context)
        elif data == "groups_confirm_join":
            await self.process_start_joining(update, context)
        elif data == "start_joining":
            await self.process_start_joining(update, context)
        elif data == "groups_prevpage":
            user_id = update.effective_user.id
            flow_data = self.temp_data.get(user_id)
            if flow_data:
                flow_data["current_page"] = max(0, flow_data["current_page"] - 1)
                await self.send_group_preview(update, context, user_id, edit=True)
        elif data.startswith("groups_page_"):
            page_num = int(data.split("_")[-1])
            await self.show_groups_list(update, context, page=page_num)

        elif data == "groups_nextpage":
            user_id = update.effective_user.id
            flow_data = self.temp_data.get(user_id)
            if flow_data:
                page = flow_data.get("current_page", 0)
                total_pages = (len(flow_data["groups_to_add"]) + 9) // 10
                flow_data["current_page"] = min(total_pages - 1, page + 1)
                await self.send_group_preview(update, context, user_id, edit=True)
        elif data == "groups_view":
            await self.show_groups_list(update, context)

        elif data == "groups_remove":
            await self.show_groups_remove_menu(update, context)

        elif data.startswith("groups_remove_page_"):
            page_num = int(data.split("_")[-1])
            await self.show_groups_remove_menu(update, context, page=page_num)

        elif data.startswith("group_toggle_"):
            await self.toggle_group_selection(update, context, data)
    
        elif data.startswith("group_remove_exec_"):
            chat_id = int(data[len("group_remove_exec_"):])
            # Get group info from DB
            group_info = self.db.execute_query(
                "SELECT title, username, chat_type FROM groups WHERE chat_id = ?", (chat_id,)
            )
            if not group_info:
                await self._safe_edit_text(update.callback_query, "❌ Group not found or already removed.")
                return

            title, username, chat_type = group_info[0]
            # --- Attempt to leave the group using the userbot ---
            try:
                if self.userbot_manager.is_authenticated and self.userbot_manager.client:
                    # Leave group using Telethon
                    try:
                        entity = await self.userbot_manager.client.get_entity(chat_id)
                        await self.userbot_manager.client(functions.channels.LeaveChannelRequest(entity))
                    except Exception as leave_exc:
                        # Log error but proceed with DB cleanup
                        self.db.log_event("ERROR", f"Failed to leave group {title}: {leave_exc}")
                else:
                    # Userbot not connected; just remove from DB
                    pass
            except Exception as e:
                self.db.log_event("ERROR", f"Error in group removal for {title}: {e}")

            # Remove from DB
            self.db.execute_query("DELETE FROM groups WHERE chat_id = ?", (chat_id,))
            # Optionally, remove from forwarding_targets or other tables

            await self._safe_edit_text(update.callback_query, 
                f"✅ <b>Removed group:</b> <code>{title}</code>\n"
                f"Userbot has left the group (if possible).\n",
                parse_mode="HTML"
            )
            # Optionally show updated group list (paginated)
            await self.show_groups_remove_menu(update, context)


        elif data.startswith("group_remove_"):
            chat_id = int(data[len("group_remove_"):])
            print(f"[DEBUG] User selected group_remove_ for chat_id: {chat_id}")
            group_info = self.db.execute_query(
                "SELECT title, username, chat_type FROM groups WHERE chat_id = ?", (chat_id,)
            )
            if not group_info:
                await self._safe_edit_text(update.callback_query, "❌ Group not found.")
                return
            title, username, chat_type = group_info[0]
            text = (
                f"❌ <b>Remove Group</b>\n\n"
                f"<b>Name:</b> {title}\n"
                f"<b>Chat ID:</b> <code>{chat_id}</code>\n"
                f"<b>Username:</b> @{username if username else 'N/A'}\n"
                f"<b>Type:</b> {chat_type}\n\n"
                f"Do you want to remove this group? This will immediately leave and delete the group from your bot."
            )
            keyboard = [
                [InlineKeyboardButton("🚫 Remove Group", callback_data=f"group_remove_exec_{chat_id}")],
                [InlineKeyboardButton("🔙 Back", callback_data="groups_remove_page_0")]
            ]
            await self._safe_edit_text(update.callback_query, 
                text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
            )   

        elif data == "progress_refresh":
            user_id = update.effective_user.id
            await self.update_group_join_progress(user_id)

        elif data == "progress_prevpage":
            user_id = update.effective_user.id
            if user_id in self.progress_containers:
                self.progress_containers[user_id]["progress_page"] = max(
                    0, self.progress_containers[user_id].get("progress_page", 0) - 1
                )
                await self.update_group_join_progress(user_id)

        elif data == "progress_nextpage":
            user_id = update.effective_user.id
            if user_id in self.progress_containers:
                self.progress_containers[user_id]["progress_page"] = (
                    self.progress_containers[user_id].get("progress_page", 0) + 1
                )
                await self.update_group_join_progress(user_id)

        elif data == "toggle_group_join":
            user_id = update.effective_user.id
            current = self.db.get_setting("group_join_enabled", "on")
            new_value = "off" if current == "on" else "on"
            self.db.set_setting("group_join_enabled", new_value)

            await update.callback_query.answer(
                "✅ Group joining has been " + ("paused." if new_value == "off" else "resumed.")
            )

            # Refresh the current group join progress message
            await self.update_group_join_progress(user_id)

        # Forwarding handlers
        elif data == "forwarding_messages":
            await self.show_forwarding_messages_menu(update, context)
        elif data == "forwarding_controls":
            await self.show_forwarding_controls_menu(update, context)
        elif data == "forwarding_destinations":
            await self.show_forwarding_destinations_menu(update, context)
        elif data == "toggle_ads_groups":
            user_id = update.effective_user.id
            current = self.db.get_user_setting(user_id, "ads_groups_enabled", "on") == "on"
            self.db.set_user_setting(user_id, "ads_groups_enabled", "off" if current else "on")
            await update.callback_query.answer("👥 Groups " + ("OFF" if current else "ON"))
            await self.show_forwarding_controls_menu(update, context)
        elif data == "toggle_ads_dms":
            user_id = update.effective_user.id
            current = self.db.get_user_setting(user_id, "ads_dms_enabled", "on") == "on"
            self.db.set_user_setting(user_id, "ads_dms_enabled", "off" if current else "on")
            await update.callback_query.answer("💬 DMs " + ("OFF" if current else "ON"))
            await self.show_forwarding_controls_menu(update, context)
        elif data == "forwarding_start":
            # Validate userbot is active before allowing forwarding
            userbot_data = await self._run_db_query(
                lambda: self.db.execute_query("SELECT is_active FROM userbot_session WHERE is_active = 1 LIMIT 1")
            )
            if not userbot_data:
                await update.callback_query.answer(
                    "❌ No active userbot found. Please add and authenticate a userbot first.",
                    show_alert=True
                )
                return
            await self.start_forwarding(update, context)
        elif data == "forwarding_stop":
            await self.stop_forwarding(update, context)
        elif data == "forwarding_pause":
            await self.pause_forwarding(update, context)
        elif data == "forwarding_resume":
            await self.resume_forwarding(update, context)
        elif data == "message_add":
            await self.start_message_add_flow(update, context)
        elif data.startswith("message_remove_"):
            await self.remove_forwarding_message(update, context, data)
        elif data == "logs_clear":
            self.db.execute_query("DELETE FROM logs")
            await self.show_logs(update, context)
        
    async def process_start_joining(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        flow_data = self.temp_data.get(user_id)
        if not flow_data or "groups_to_add" not in flow_data or not flow_data["groups_to_add"]:
            await self._safe_edit_text(update.callback_query, 
                escape_markdown("❌ No groups to join. Please add at least one group.", version=2),
                parse_mode="MarkdownV2"
            )
            return

        # --- NEW: Get all usernames and @links of already joined groups (USER-SCOPED) ---
        already_joined_groups = set()
        group_rows = self.db.execute_query("SELECT username FROM groups WHERE user_id = ? AND username IS NOT NULL", (user_id,))
        already_joined_groups = set(r[0].lower() for r in group_rows if r[0])

        # Track which links were skipped
        skipped = []
        queued = []

        for group_link in flow_data["groups_to_add"]:
            username = None
            # Extract username from @ or t.me/ link
            if group_link.startswith('@'):
                username = group_link[1:].lower()
            elif 't.me/' in group_link:
                part = group_link.split('t.me/')[-1]
                username = part.split('/')[0].lower() if '/' in part else part.lower()
                # skip joinchat links here, those don't have username
                if username.startswith("joinchat"):
                    username = None

            if username and username in already_joined_groups:
                skipped.append(group_link)
                continue  # skip, already joined

            # Only add to join queue if not skipped
            self.db.execute_query(
                "INSERT INTO pending_joins (user_id, group_link, status) VALUES (?, ?, ?)",
                (user_id, group_link, "pending")
            )
            queued.append(group_link)

        total_groups = len(queued)

        progress_lines = [
            escape_markdown('🟢 Joining Groups Progress', version=2),
            "",
            f"{escape_markdown('Groups queued', version=2)}: {escape_markdown(str(total_groups), version=2)}",
            f"{escape_markdown('Skipped (already joined)', version=2)}: {escape_markdown(str(len(skipped)), version=2)}",
            ""
        ]
        if skipped:
            progress_lines.append(escape_markdown("Already joined:", version=2))
            progress_lines.extend([escape_markdown(g, version=2) for g in skipped])
            progress_lines.append("")

        progress_lines.append(escape_markdown('Next join will happen automatically every 5 minutes.', version=2))
        progress_lines.append(escape_markdown('This message will update as joins complete.', version=2))

        progress_text = "\n".join(progress_lines)

        try:
            msg = await self._safe_edit_text(update.callback_query, 
                progress_text,
                parse_mode="MarkdownV2"
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Silently ignore this expected error
                pass
            else:
                raise

        # Save for later live updating
        self.progress_containers[user_id] = {
            "progress_msg_id": msg.message_id,
            "progress_chat_id": msg.chat_id,
            "progress_page": 0
        }

    def _get_cached_value(self, key: str):
        """Get value from cache if valid."""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return value
            else:
                del self._cache[key]
        return None
    
    def _set_cache(self, key: str, value):
        """Set value in cache."""
        self._cache[key] = (value, time.time())
    
    async def _run_db_query(self, query_func, *args):
        """Run blocking database query in thread pool to avoid blocking event loop."""
        return await asyncio.to_thread(query_func, *args)
    
    async def ensure_subscription_valid(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        # Free-access mode: retain subscription/payment records for admin use,
        # but never block a normal user's dashboard or feature navigation.
        try:
            active, _status_msg = self.get_subscription_status()
            self._set_cache("subscription_active", active)
        except Exception:
            self._set_cache("subscription_active", True)
        return True

    async def show_groups_remove_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
        user_id = update.effective_user.id
        groups = self.db.execute_query(
            "SELECT chat_id, title, username FROM groups WHERE user_id = ? ORDER BY title",
            (user_id,)
        )
        page_size = 10
        total_pages = (len(groups) + page_size - 1) // page_size
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, len(groups))
        page_groups = groups[start_idx:end_idx]

        if not groups:
            text = "❌ **No Groups Found**\n\nNo groups to remove."
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_groups")]]
        else:
            text = f"❌ **Remove from Groups** (Page {page + 1}/{total_pages})\n\nSelect a group to leave:"
            keyboard = []

            for group in page_groups:
                chat_id, title, username = group
                display_name = f"{title} (@{username})" if username else title
                keyboard.append([
                    InlineKeyboardButton(
                        f"❌ {display_name[:40]}...",
                        callback_data=f"group_remove_{chat_id}"
                    )
                ])

            # Pagination row
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"groups_remove_page_{page-1}"))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"groups_remove_page_{page+1}"))
            if nav_buttons:
                keyboard.append(nav_buttons)
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_groups")])

        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        try:
            await self._safe_edit_text(update.callback_query, 
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            print(f"[DEBUG] Exception in show_groups_remove_menu: {e}")

    async def background_group_joiner(self):
        while True:
            # ⏸️ Check if group joining is enabled
            join_enabled = self.db.get_setting("group_join_enabled", "on")
            if join_enabled != "on":
                print("[Joiner] Paused by user. Skipping this cycle.")
                self.last_group_join_time = None  # 🔧 Stop the countdown
                self.db.set_setting("last_group_join_time", "")  # 🔧 Clear saved value
                await asyncio.sleep(60)
                continue

            # 🔐 Check subscription validity (auto-renews if needed)
            active, _ = self.get_subscription_status()
            # Subscription check no longer stops group joiner - get_subscription_status auto-renews

            # 🧭 Get the first pending group for the admin user (status='pending')
            admin_user_id = self.ADMIN_USER_ID
            pending = self.db.execute_query(
                "SELECT id, group_link, user_id FROM pending_joins WHERE user_id = ? AND status = 'pending' ORDER BY id LIMIT 1",
                (admin_user_id,)
            )

            if pending:
                group_id, group_link, owner_user_id = pending[0]
                print(f"[JoinQueue] Attempting to join: {group_link} for user {owner_user_id}")
                success, msg = await self.userbot_manager.join_group(group_link, owner_user_id)
                new_status = "joined" if success else "failed"
                self.db.execute_query(
                    "UPDATE pending_joins SET status = ? WHERE id = ?",
                    (new_status, group_id)
                )
                print(f"[JoinQueue] {group_link} => {msg}")

                # 🕒 Persist join time
                now = time.time()
                self.last_group_join_time = now
                self.db.set_setting("last_group_join_time", str(now))

                # 📡 Update UI for the user who owns this join
                await self.update_group_join_progress(owner_user_id)

                # Use join_interval from admin_settings
                join_interval = int(self.db.get_admin_setting('join_interval', '300'))
                await asyncio.sleep(join_interval)

            else:
                # 🧹 All joins done, clean up UI & timer
                admin_user_id = self.ADMIN_USER_ID
                self.progress_containers.pop(admin_user_id, None)
                self.last_group_join_time = None
                self.db.set_setting("last_group_join_time", "")
                await asyncio.sleep(60)  # Retry in 1 minute

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages."""
        user_id = update.effective_user.id
        support_status = self.db.get_setting("support_access", "off")

        # All users are allowed to use the AdBot dashboard and normal features.
        # Subscription/authorized-user status is NOT required for the free version.
        # Admin-only actions remain protected by their individual admin checks.
        flow_type = self.temp_data.get(user_id, {}).get("flow_type", "")

        user_id = update.effective_user.id
        message_text = update.message.text

        # Handle different flows based on stored state
        if user_id in self.temp_data:
            flow_type = self.temp_data[user_id].get("flow_type")

            if flow_type == "userbot_add":
                await self.handle_userbot_add_flow(update, context, message_text)

            elif flow_type == "groups_add":
                await self.handle_groups_add_flow(update, context, message_text)

            elif flow_type == "message_add":
                await self.handle_message_add_flow(update, context, message_text)

            elif flow_type == "logbot_token":
                bot_token = message_text.strip()
                success, message, bot_instance = await self.logging_bot_manager.validate_bot_token(bot_token, user_id)
                
                if success:
                    self.temp_data[user_id] = {"flow_type": "logbot_destination", "logbot_token": bot_token}
                    keyboard = [
                        [InlineKeyboardButton("📨 DM", callback_data="logbot_destination_dm")],
                        [InlineKeyboardButton("📢 Personal Channel", callback_data="logbot_destination_channel")],
                        [InlineKeyboardButton("👥 Personal Group", callback_data="logbot_destination_group")],
                        [InlineKeyboardButton("🔙 Cancel", callback_data="settings_log_bot")]
                    ]
                    await update.message.reply_text(
                        f"{message}\n\n"
                        "📊 *Choose Log Destination*\n\n"
                        "Where would you like to receive forwarding logs?\n\n"
                        "• *DM* - Direct messages to you\n"
                        "• *Channel* - Your personal channel\n"
                        "• *Group* - Your personal group",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    old_token = self.db.get_user_logging_bot(user_id)
                    if old_token and old_token.get('bot_token') != bot_token:
                        await update.message.reply_text(
                            f"{message}\n\n"
                            "⚠️ *Bot Token Changed*\n\n"
                            "Your previous bot token has been replaced with the new one.",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔁 Try Again", callback_data="logbot_add")],
                                [InlineKeyboardButton("🔙 Back", callback_data="settings_log_bot")]
                            ])
                        )
                    else:
                        await update.message.reply_text(
                            message,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔁 Try Again", callback_data="logbot_add")],
                                [InlineKeyboardButton("🔙 Back", callback_data="settings_log_bot")]
                            ])
                        )
                    if user_id in self.temp_data:
                        del self.temp_data[user_id]
                return
            
            elif flow_type == "logbot_chat_id":
                success, message = await self.logging_bot_manager.setup_destination_with_chat_id(
                    user_id=user_id,
                    chat_id_str=message_text.strip()
                )
                
                # Allow adding more destinations
                if success:
                    keyboard = [
                        [InlineKeyboardButton("➕ Add Another Destination", callback_data="logbot_add")],
                        [InlineKeyboardButton("✅ Done", callback_data="settings_log_bot")]
                    ]
                    result_msg = f"{message}\n\n✅ Destination added successfully!"
                else:
                    keyboard = [[InlineKeyboardButton("🔙 Back to Settings", callback_data="settings_log_bot")]]
                    result_msg = message
                
                await update.message.reply_text(
                    result_msg,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                
                if success and user_id in self.temp_data:
                    del self.temp_data[user_id]
                return
            
            elif flow_type == "logbot_channel" or flow_type == "logbot_group":
                if user_id in self.temp_data and "logbot_token" in self.temp_data[user_id]:
                    bot_token = self.temp_data[user_id]["logbot_token"]
                    dest_type = 'channel' if flow_type == "logbot_channel" else 'group'
                    
                    success, message = await self.logging_bot_manager.setup_destination(
                        user_id=user_id,
                        bot_token=bot_token,
                        destination_type=dest_type,
                        destination_input=message_text.strip()
                    )
                    
                    if "awaiting_chat_id" in message or "Chat ID" in message:
                        self.temp_data[user_id]["flow_type"] = "logbot_chat_id"
                    
                    # Allow adding more destinations
                    if success:
                        keyboard = [
                            [InlineKeyboardButton("➕ Add Another Destination", callback_data="logbot_add")],
                            [InlineKeyboardButton("✅ Done", callback_data="settings_log_bot")]
                        ]
                        result_msg = f"{message}\n\n✅ Destination added successfully!"
                    else:
                        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="settings_log_bot")]]
                        result_msg = message
                    
                    await update.message.reply_text(
                        result_msg,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    
                    if success and user_id in self.temp_data:
                        del self.temp_data[user_id]
                else:
                    await update.message.reply_text(
                        "❌ Session expired. Please start again.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back", callback_data="settings_log_bot")]
                        ])
                    )
                return
            
            elif flow_type == "custom_banner":
                try:
                    parts = message_text.split("|")
                    title = parts[0].strip() if len(parts) > 0 else "Custom Banner"
                    subtitle = parts[1].strip() if len(parts) > 1 else ""
                    
                    banner_bytes = self.professional_banner_generator.generate_banner(title, subtitle)
                    
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=banner_bytes,
                        caption=f"<b>Custom Banner</b>\n\nGenerated by Synax Ad Bot",
                        parse_mode=ParseMode.HTML
                    )
                    del self.temp_data[user_id]
                except Exception as e:
                    print(f"[ERROR] Custom banner generation: {e}")
                    await update.message.reply_text(
                        "Failed to generate banner. Please try again.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Try Again", callback_data="gen_banner_custom")],
                            [InlineKeyboardButton("Back", callback_data="back_main")]
                        ])
                    )
                return
            
            elif flow_type == "afk_set":
                afk_message = message_text.strip()
                self.db.set_user_setting(user_id, "afk_message", afk_message)
                del self.temp_data[user_id]
                await update.message.reply_text(
                    "✅ *AFK message updated!*",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("🔙 Back", callback_data="settings_afk")]]
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            
            elif flow_type == "set_cycle_length":
                try:
                    cycle = int(message_text.strip())
                    if cycle < 10:
                        await update.message.reply_text(
                            "❌ Minimum allowed cycle length is 10 minutes.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔁 Retry", callback_data="set_cycle_length")],
                                [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                            ])
                        )
                    else:
                        self.db.set_setting("cycle_length", str(cycle))
                        await update.message.reply_text(
                            f"✅ Cycle length set to {cycle} minutes.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                            ])
                        )
                        del self.temp_data[user_id]
                except ValueError:
                    await update.message.reply_text(
                        "❌ Invalid input. Please enter a number.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔁 Retry", callback_data="set_cycle_length")],
                            [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                        ])
                    )
                        
            elif flow_type == "support_add":
                try:
                    minutes = int(message_text.strip())
                    current = int(self.db.get_setting("subscription_duration", "0"))
                    new_value = max(0, current + minutes)
                    self.db.set_setting("subscription_duration", str(new_value))
                    self.temp_data.pop(user_id, None)

                    await update.message.reply_text(
                        f"✅ {minutes} minutes added successfully.\n\nNew Duration: `{new_value}` minutes.",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back to Support Panel", callback_data="support_menu")]
                        ])
                    )

                except ValueError:
                    await update.message.reply_text("❌ Invalid input. Please send a number.")

            elif flow_type == "support_subtract":
                try:
                    minutes = int(message_text.strip())
                    current = int(self.db.get_setting("subscription_duration", "0"))
                    new_value = max(0, current - minutes)
                    self.db.set_setting("subscription_duration", str(new_value))
                    self.temp_data.pop(user_id, None)

                    await update.message.reply_text(
                        f"✅ {minutes} minutes subtracted successfully.\n\nNew Duration: `{new_value}` minutes.",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔙 Back to Support Panel", callback_data="support_menu")]
                        ])
                    )

                except ValueError:
                    await update.message.reply_text("❌ Invalid input. Please send a number.")

            elif flow_type == "set_hold_duration":
                try:
                    hold = int(message_text.strip())
                    if hold < 15:
                        await update.message.reply_text(
                            "❌ Minimum hold duration is 15 minutes.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔁 Retry", callback_data="set_hold_duration")],
                                [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                            ])
                        )
                    else:
                        # Save to DB
                        self.db.set_setting("hold_duration", str(hold))

                        # 🆕 If forwarding is running, update its timing immediately
                        if self.forwarding_manager and self.forwarding_manager.is_running:
                            now = datetime.now()
                            self.forwarding_manager.phase_start_time = now

                            if self.forwarding_manager.current_phase == "holding":
                                self.forwarding_manager.stats["next_forward_time"] = now + timedelta(minutes=hold)
                            else:
                                # Forwarding phase continues unchanged
                                pass

                            print("[Forwarding] Hold duration updated live.")

                        # Notify user
                        await update.message.reply_text(
                            f"✅ Hold duration set to {hold} minutes.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔙 Back to Controls", callback_data="forwarding_controls")]
                            ])
                        )
                        del self.temp_data[user_id]

                except ValueError:
                    await update.message.reply_text(
                        "❌ Invalid input. Please enter a number.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔁 Retry", callback_data="set_hold_duration")],
                            [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                        ])
                    )

            elif flow_type == "alter_delay":
                try:
                    delay = int(message_text.strip())
                    if delay < 30:
                        await update.message.reply_text(
                            "❌ Minimum allowed delay is 30 seconds.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔁 Retry", callback_data="settings_alter_delay")],
                                [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                            ])
                        )
                    else:
                        self.db.set_setting("per_message_delay", str(delay))
                        await update.message.reply_text(
                            f"✅ Delay set to {delay} seconds.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                            ])
                        )
                        del self.temp_data[user_id]
                except ValueError:
                    await update.message.reply_text(
                        "❌ Invalid input. Please enter a number.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔁 Retry", callback_data="settings_alter_delay")],
                            [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
                        ])
                    )
            
            elif flow_type == "set_join_interval":
                try:
                    interval_minutes = int(message_text.strip())
                    if interval_minutes < 5:
                        await update.message.reply_text(
                            "❌ Minimum join interval is 5 minutes.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔁 Retry", callback_data="set_join_interval")],
                                [InlineKeyboardButton("🔙 Back", callback_data="groups_processes")]
                            ])
                        )
                    else:
                        self.db.set_join_interval(interval_minutes * 60, user_id)
                        await update.message.reply_text(
                            f"✅ Join interval set to {interval_minutes} minutes.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔙 Back", callback_data="groups_processes")]
                            ])
                        )
                        del self.temp_data[user_id]
                except ValueError:
                    await update.message.reply_text(
                        "❌ Invalid input. Please enter a number.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔁 Retry", callback_data="set_join_interval")],
                            [InlineKeyboardButton("🔙 Back", callback_data="groups_processes")]
                        ])
                    )
            
            elif flow_type == "set_timezone":
                tz_input = message_text.strip()
                import pycountry
                
                if tz_input.startswith('+') or tz_input.startswith('-'):
                    try:
                        parts = tz_input.replace('+', '').replace('-', '').split(':')
                        hours = int(parts[0])
                        minutes = int(parts[1]) if len(parts) > 1 else 0
                        if 0 <= hours <= 14 and 0 <= minutes <= 59:
                            self.db.set_user_timezone(user_id, tz_input)
                            await update.message.reply_text(
                                f"✅ Timezone set to `{tz_input}`",
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
                                ])
                            )
                            del self.temp_data[user_id]
                        else:
                            await update.message.reply_text(
                                "❌ Invalid timezone offset. Please use format like +05:30 or -08:00",
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("🔁 Retry", callback_data="set_timezone")],
                                    [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
                                ])
                            )
                    except (ValueError, IndexError):
                        await update.message.reply_text(
                            "❌ Invalid format. Please use +HH:MM or -HH:MM (e.g., +05:30)",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔁 Retry", callback_data="set_timezone")],
                                [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
                            ])
                        )
                else:
                    try:
                        country = pycountry.countries.search_fuzzy(tz_input)[0]
                        import pytz
                        timezones = pytz.country_timezones.get(country.alpha_2, [])
                        if timezones:
                            main_tz = pytz.timezone(timezones[0])
                            now = datetime.now(main_tz)
                            offset = now.strftime('%z')
                            offset_formatted = f"{offset[:3]}:{offset[3:]}"
                            self.db.set_user_timezone(user_id, offset_formatted)
                            await update.message.reply_text(
                                f"✅ Timezone set to `{offset_formatted}` ({country.name})",
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
                                ])
                            )
                            del self.temp_data[user_id]
                        else:
                            await update.message.reply_text(
                                f"❌ Could not determine timezone for {country.name}. Please use GMT offset format.",
                                reply_markup=InlineKeyboardMarkup([
                                    [InlineKeyboardButton("🔁 Retry", callback_data="set_timezone")],
                                    [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
                                ])
                            )
                    except (LookupError, ModuleNotFoundError, ImportError):
                        await update.message.reply_text(
                            f"❌ Country '{tz_input}' not found. Please use GMT offset format (e.g., +05:30) or a valid country name.",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔁 Retry", callback_data="set_timezone")],
                                [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
                            ])
                        )
            
            elif flow_type == "admin_approve":
                text, markup = await self._handle_admin_approve_flow(update, message_text)
                await update.message.reply_text(text, reply_markup=markup if markup else None, parse_mode=ParseMode.MARKDOWN)
            
            elif flow_type == "admin_extend":
                text, markup = await self._handle_admin_extend_flow(update, message_text)
                await update.message.reply_text(text, reply_markup=markup if markup else None, parse_mode=ParseMode.MARKDOWN)
            
            elif flow_type == "admin_set_limits":
                text, markup = await self._handle_admin_set_limits_flow(update, message_text)
                await update.message.reply_text(text, reply_markup=markup if markup else None, parse_mode=ParseMode.MARKDOWN)
            
            elif flow_type == "admin_fampay_set":
                field = flow.get("field")
                value = (message_text or "").strip()
                if not value:
                    await update.message.reply_text("❌ Value cannot be empty.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_fampay_config", style="danger")]]))
                    return
                if field == "fampay_prices":
                    try:
                        parsed = {}
                        for part in value.split(","):
                            k, v = part.split("=", 1); k=k.strip(); parsed[k]=float(v.strip())
                        for required in self.SUBSCRIPTION_PLANS:
                            if required not in parsed: raise ValueError(f"Missing {required}")
                        self.db.set_setting("fampay_prices", json.dumps(parsed)); self.fampay_prices = self._load_fampay_prices()
                    except Exception as e:
                        await update.message.reply_text(f"❌ Invalid prices. Use 1_month=20,3_months=50,6_months=90,lifetime=150\n\nError: {e}")
                        return
                else:
                    self.db.set_setting(field, value)
                self.reload_fampay_config()
                self.temp_data.pop(user_id, None)
                await update.message.reply_text("✅ <b>Fampay configuration updated.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🇮🇳 Open Fampay Config", callback_data="admin_fampay_config", style="success")],[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_panel", style="danger")]]), parse_mode=ParseMode.HTML)
                return

            elif flow_type == "admin_broadcast":
                flow = self.temp_data.get(user_id, {})
                if flow.get("step") == "message":
                    broadcast_msg = message_text.strip()
                    if not broadcast_msg:
                        await update.message.reply_text("❌ Message cannot be empty.")
                        return
                    flow.update({
                        "broadcast_message": broadcast_msg,
                        "source_chat_id": update.effective_chat.id,
                        "source_message_id": update.message.message_id,
                        "step": "confirm"
                    })
                    self.temp_data[user_id] = flow
                    await self._show_broadcast_setup(update, context)
                    return

                broadcast_msg = flow.get("broadcast_message", message_text.strip())
                source_chat_id = flow.get("source_chat_id", update.effective_chat.id)
                source_message_id = flow.get("source_message_id", update.message.message_id)
                send_dm = bool(flow.get("send_dm", True))
                send_group = bool(flow.get("send_group", True))

                # Authorized users = DM recipients.
                users = self.db.execute_query("SELECT DISTINCT user_id FROM authorized_users")
                dm_ids = {int(row[0]) for row in users if row and row[0]} if send_dm else set()
                dm_ids.discard(user_id)

                group_rows = self.db.execute_query(
                    "SELECT DISTINCT chat_id, title FROM groups "
                    "WHERE user_id = ? AND is_selected = 1 AND chat_type IN ('basic_group', 'supergroup', 'forum')",
                    (user_id,)
                )
                group_targets = ([(int(row[0]), row[1] or str(row[0])) for row in group_rows if row and row[0]]
                                 if send_group else [])

                total_users = len(dm_ids)
                total_groups = len(group_targets)
                sent_count = failed_count = 0
                sent_groups = failed_groups = 0
                total_targets = total_users + total_groups

                progress_msg = await update.message.reply_text(
                    f"📢 <b>Broadcasting</b>\n\n"
                    f"👤 DMs: 0/{total_users}\n"
                    f"👥 Groups: 0/{total_groups}\n"
                    f"📦 Total: 0/{total_targets}",
                    parse_mode=ParseMode.HTML
                )

                processed = 0
                for target_user_id in dm_ids:
                    try:
                        # Copy the admin's message so formatting stays intact and Markdown
                        # characters in user text cannot break the broadcast.
                        await context.bot.copy_message(
                            chat_id=target_user_id,
                            from_chat_id=source_chat_id,
                            message_id=source_message_id
                        )
                        sent_count += 1
                    except Exception as e:
                        failed_count += 1
                        self.db.log_event("ERROR", f"DM broadcast failed for user {target_user_id}: {str(e)}")
                    processed += 1
                    if processed % 5 == 0 or processed == total_targets:
                        try:
                            await progress_msg.edit_text(
                                f"📢 <b>Broadcasting</b>\n\n"
                                f"👤 DMs: {sent_count}/{total_users} (failed {failed_count})\n"
                                f"👥 Groups: {sent_groups}/{total_groups} (failed {failed_groups})\n"
                                f"📦 Total: {processed}/{total_targets}",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass

                for chat_id, group_title in group_targets:
                    try:
                        await context.bot.copy_message(
                            chat_id=chat_id,
                            from_chat_id=source_chat_id,
                            message_id=source_message_id
                        )
                        sent_groups += 1
                    except Exception as e:
                        failed_groups += 1
                        self.db.log_event("ERROR", f"Group broadcast failed for {group_title} ({chat_id}): {str(e)}")
                    processed += 1
                    if processed % 5 == 0 or processed == total_targets:
                        try:
                            await progress_msg.edit_text(
                                f"📢 <b>Broadcasting</b>\n\n"
                                f"👤 DMs: {sent_count}/{total_users} (failed {failed_count})\n"
                                f"👥 Groups: {sent_groups}/{total_groups} (failed {failed_groups})\n"
                                f"📦 Total: {processed}/{total_targets}",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            pass

                # Save broadcast statistics when the table is available.
                try:
                    self.db.execute_query(
                        "INSERT INTO broadcasts (message, total_users, sent_count, failed_count, total_groups, sent_groups, failed_groups, status, completed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?)",
                        (broadcast_msg, total_users, sent_count, failed_count, total_groups, sent_groups, failed_groups, datetime.now())
                    )
                except Exception as e:
                    self.db.log_event("ERROR", f"Failed to save broadcast stats: {e}")

                self.temp_data.pop(user_id, None)
                await progress_msg.edit_text(
                    f"✅ <b>Broadcast Complete</b>\n\n"
                    f"👤 DMs — Sent: <b>{sent_count}</b> | Failed: <b>{failed_count}</b>\n"
                    f"👥 Groups — Sent: <b>{sent_groups}</b> | Failed: <b>{failed_groups}</b>\n\n"
                    f"📦 Total targets: <b>{total_targets}</b>",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]]),
                    parse_mode=ParseMode.HTML
                )
                return
            
            elif flow_type == "admin_set_bio":
                new_bio = message_text.strip()
                if not new_bio:
                    await update.message.reply_text("❌ Bio cannot be empty.")
                    return
                
                self.db.set_admin_setting('default_bio', new_bio)
                del self.temp_data[user_id]
                
                await update.message.reply_text(
                    f"✅ *Default Bio Updated*\n\nNew bio: `{new_bio}`\n\nThis will be applied to all new userbots.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]])
                )
                return
            
            elif flow_type == "admin_set_lastname":
                new_lastname = message_text.strip()
                if not new_lastname:
                    await update.message.reply_text("❌ Last name cannot be empty.")
                    return
                
                self.db.set_admin_setting('default_lastname', new_lastname)
                del self.temp_data[user_id]
                
                await update.message.reply_text(
                    f"✅ *Default Last Name Updated*\n\nNew last name: `{new_lastname}`\n\nThis will be applied to all new userbots.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]])
                )
                return
            
            elif flow_type == "admin_set_interval":
                try:
                    interval_minutes = int(message_text.strip())
                    if interval_minutes < 1:
                        await update.message.reply_text("❌ Interval must be at least 1 minute.")
                        return
                    
                    interval_seconds = interval_minutes * 60
                    self.db.set_admin_setting('join_interval', str(interval_seconds))
                    del self.temp_data[user_id]
                    
                    await update.message.reply_text(
                        f"✅ *Join Interval Updated*\n\nNew interval: `{interval_minutes} minutes`\n\nThe auto-join system will now use this interval.",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]])
                    )
                except ValueError:
                    await update.message.reply_text("❌ Invalid number. Please send a valid number of minutes.")
                return
            
            elif flow_type == "admin_remove":
                try:
                    target_user_id = int(message_text.strip())
                    self.db.execute_query("DELETE FROM authorized_users WHERE user_id = ?", (target_user_id,))
                    del self.temp_data[user_id]
                    await update.message.reply_text(
                        f"✅ User `{target_user_id}` removed.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    await update.message.reply_text("❌ Invalid User ID.")
                return

        # --- AFK auto-reply for private DMs ---
        message_text = update.message.text if update.message and update.message.text else ""
        
        if message_text and message_text.startswith('/'):
            return
        
        afk_enabled = self.db.get_user_setting(user_id, "afk_enabled", "off")
        afk_message = self.db.get_user_setting(user_id, "afk_message", "")
        OWNER_ID = 7538794191   # <-- your Telegram user ID

        if (
            afk_enabled == "on"
            and update.effective_chat.type == "private"
            and update.effective_user.id != OWNER_ID
        ):
            if afk_message:
                await update.message.reply_text(afk_message)
    
    # Userbot Menu Methods
    async def show_userbot_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show userbot management menu with list of all userbots."""
        import datetime
        ts_start = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # Subscription already checked in callback handler - no redundant check needed
        user_id = update.effective_user.id
        
        # Get user's userbots (run in thread pool to avoid blocking)
        userbots = await self._run_db_query(
            lambda uid: self.db.execute_query(
                "SELECT id, phone_number, is_active FROM userbot_session WHERE user_id = ? ORDER BY id",
                (uid,)
            ),
            user_id
        )
        
        # Get userbot limit for this user (run in thread pool)
        limits = await self._run_db_query(self.db.get_user_limits, user_id)
        
        userbot_limit = limits.get("userbot_limit", 1)
        current_count = len(userbots)
        
        keyboard = []
        
        # Show list of userbots
        if userbots:
            text = f"🛠 *Userbot Management* ({current_count}/{userbot_limit})\n\n"
            for bot in userbots:
                bot_id, phone, is_active = bot
                status = "✅ Active" if is_active else "❌ Inactive"
                text += f"{status} • {phone}\n"
            text += "\nSelect an option:"
            
            # Add buttons for each userbot
            for bot in userbots:
                bot_id, phone, is_active = bot
                keyboard.append([InlineKeyboardButton(f"📋 {phone}", callback_data=f"userbot_detail_{bot_id}")])
        else:
            text = "🛠 *Userbot Management*\n\nNo userbots added yet."
        
        # Add "Add More" button if limit not reached
        if current_count < userbot_limit:
            keyboard.append([InlineKeyboardButton("➕ Add Userbot", callback_data="userbot_add")])
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_main")])
        try:
            await self._safe_edit_text(update.callback_query, 
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            ts_edit_done = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[USER_TIMING] {ts_edit_done} ✅ MESSAGE VISIBLE TO USER (userbot_menu)")
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore the harmless error
                pass
            else:
                raise
    
    async def show_userbot_detail(self, update: Update, context: ContextTypes.DEFAULT_TYPE, userbot_id: int):
        """Show userbot details menu with admin-configured name and bio."""
        user_id = update.effective_user.id
        userbot = await self._run_db_query(
            lambda: self.db.execute_query(
                "SELECT phone_number, is_active, admin_display_name, admin_bio, connected_at FROM userbot_session WHERE id = ? AND user_id = ?",
                (userbot_id, user_id)
            )
        )
        
        if not userbot:
            await update.callback_query.answer("Userbot not found")
            return
        
        phone, is_active, display_name, bio, connected_at = userbot[0]
        status = "✅ Active" if is_active else "❌ Inactive"
        
        # Build details text
        text = f"📋 *Userbot Details*\n\n"
        text += f"*Phone:* {phone}\n"
        text += f"*Status:* {status}\n"
        
        if display_name:
            text += f"*Name:* {display_name}\n"
        if bio:
            text += f"*Bio:* {bio}\n"
        if connected_at:
            text += f"*Connected:* {connected_at}\n"
        
        text += "\nSelect an action:"
        
        keyboard = [
            [InlineKeyboardButton("❌ Remove", callback_data=f"userbot_remove_{userbot_id}")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_userbot")]
        ]
        
        try:
            await self._safe_edit_text(update.callback_query, 
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
    
    async def start_userbot_add_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start userbot addition flow - SIMPLIFIED: Just ask for phone number."""
        self.temp_data[update.effective_user.id] = {
            "flow_type": "userbot_add",
            "step": "phone",
            "api_id": 23701497,  # Hardcoded Telegram API credentials
            "api_hash": "6065ed9b8a9399e2a5d331ea1a657e66"
        }
        print(f"[USERBOT] 📱 Starting add userbot flow for user {update.effective_user.id}")
        
        text = "📱 **Add Userbot**\n\nSend your phone number (with country code):\n\nExample: +1234567890"
        try:
            await self._safe_edit_text(update.callback_query, text, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise

    async def handle_userbot_add_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
        """Handle userbot addition flow - SIMPLIFIED: Phone + OTP only."""
        user_id = update.effective_user.id
        flow_data = self.temp_data[user_id]
        step = flow_data["step"]
        print(f"[USERBOT] Processing step: {step}")

        if step == "phone":
            phone_number = message_text.strip()
            
            # Validate phone format
            if not phone_number.startswith('+'):
                await update.message.reply_text(
                    "❌ Phone number must start with +\n\nExample: +1234567890",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Retry", callback_data="userbot_add")]])
                )
                return
            
            flow_data["phone"] = phone_number
            flow_data["step"] = "otp"
            
            # Send OTP via Telegram
            try:
                print(f"[USERBOT] 📲 Sending OTP to {phone_number}...")
                success, message, row_id = await self.userbot_manager.add_userbot(
                    api_id=flow_data["api_id"],
                    api_hash=flow_data["api_hash"],
                    phone_number=phone_number,
                    user_id=user_id
                )
                
                print(f"[USERBOT] OTP sent: {success}, row_id: {row_id}")
                
                if success:
                    flow_data["row_id"] = row_id  # Store row_id for later use in verify_code
                    await update.message.reply_text(
                        f"✅ {message}\n\n🔐 **Enter the OTP code you received:**",
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await update.message.reply_text(
                        f"❌ {message}",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔁 Try Again", callback_data="userbot_add")]])
                    )
                    if user_id in self.temp_data:
                        del self.temp_data[user_id]
            except Exception as e:
                print(f"[USERBOT] ❌ Error: {str(e)}")
                await update.message.reply_text(f"❌ Error: {str(e)}")
                if user_id in self.temp_data:
                    del self.temp_data[user_id]
                return

        elif step == "otp":
            otp_code = message_text.strip()
            flow_data["code"] = otp_code  # Store code for 2FA password step
            print(f"[USERBOT] 🔐 Verifying OTP code...")
            
            try:
                success, message = await self.userbot_manager.verify_code(
                    flow_data["phone"],
                    otp_code,
                    row_id=flow_data.get("row_id")
                )
                
                if success:
                    print(f"[USERBOT] ✅ OTP verified successfully!")
                    await update.message.reply_text(
                        f"✅ {message}\n\n🎉 Userbot activated!",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="back_main")]]),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    await self.userbot_manager.fetch_groups(user_id)
                    if user_id in self.temp_data:
                        del self.temp_data[user_id]
                elif "Two-factor" in message:
                    print(f"[USERBOT] 🔐 2FA required")
                    flow_data["step"] = "password"
                    await update.message.reply_text("🔐 Two-factor authentication required.\n\nEnter your password:")
                else:
                    print(f"[USERBOT] ❌ OTP invalid: {message}")
                    await update.message.reply_text(
                        f"❌ {message}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔁 Retry OTP", callback_data="userbot_retry_code")],
                            [InlineKeyboardButton("📲 Resend Code", callback_data="userbot_resend_code")],
                            [InlineKeyboardButton("❌ Cancel", callback_data="back_main")]
                        ])
                    )
            except Exception as e:
                print(f"[USERBOT] ❌ Error during OTP verification: {str(e)}")
                await update.message.reply_text(f"❌ Error: {str(e)}")

        elif step == "password":
            print(f"[USERBOT] 🔐 Verifying 2FA password...")
            try:
                success, message = await self.userbot_manager.verify_code(
                    flow_data["phone"],
                    flow_data.get("code"),
                    message_text,
                    row_id=flow_data.get("row_id")
                )
                
                if success:
                    print(f"[USERBOT] ✅ 2FA verified!")
                    await update.message.reply_text(
                        f"✅ {message}\n\n🎉 Userbot activated!",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="back_main")]]),
                        parse_mode=ParseMode.MARKDOWN
                    )
                    await self.userbot_manager.fetch_groups(user_id)
                    if user_id in self.temp_data:
                        del self.temp_data[user_id]
                else:
                    print(f"[USERBOT] ❌ 2FA failed: {message}")
                    await update.message.reply_text(f"❌ {message}\n\nRetry:")
            except Exception as e:
                print(f"[USERBOT] ❌ 2FA error: {str(e)}")
                await update.message.reply_text(f"❌ Error: {str(e)}")
    
    async def userbot_remove_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show userbot removal confirmation."""
        user_id = update.effective_user.id
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Remove", callback_data="userbot_remove_confirm")],
            [InlineKeyboardButton("❌ Cancel", callback_data="menu_userbot")]
        ]
        
        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = "⚠️ **Confirm Userbot Removal**\n\nThis will remove the userbot session and all associated data. Are you sure?"
        
        try:
            await self._safe_edit_text(update.callback_query, 
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this harmless error
                pass
            else:
                raise
    
    async def userbot_remove_execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute userbot removal."""
        user_id = update.effective_user.id
        # Stop forwarding first if running
        if hasattr(self, 'forwarding_manager') and self.forwarding_manager.is_running:
            self.forwarding_manager.stop_forwarding()
        success = await self.userbot_manager.remove_userbot()
        
        if success:
            text = "✅ **Userbot Removed**\n\nUserbot session has been successfully removed."
        else:
            text = "❌ **Error**\n\nFailed to remove userbot session."
        
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_userbot")]]
        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await self._safe_edit_text(update.callback_query, 
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore this harmless error
                pass
            else:
                raise
    
    async def show_userbot_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        caller_user_id = update.effective_user.id
        status = await self.userbot_manager.get_status()

        if not self.userbot_manager.is_authenticated:
            status_text = escape_markdown("❌ Disconnected", version=2)
            user_info = escape_markdown("Not authenticated", version=2)
            last_activity = escape_markdown("Never", version=2)

            text = f"""📊 *Userbot Status*

    *Status:* {status_text}
    *User:* {user_info}
    *Last Activity:* {last_activity}
    """
        else:
            me = await self.userbot_manager.client.get_me()
            user_info = f"@{me.username}" if me.username else f"{me.first_name} {me.last_name or ''}".strip()
            user_info = escape_markdown(user_info, version=2)
            status_text = escape_markdown("✅ Connected", version=2)
            premium = "✅ Yes" if getattr(me, "premium", False) else "❌ No"
            premium = escape_markdown(premium, version=2)
            user_id = escape_markdown(str(me.id), version=2)
            phone = escape_markdown(getattr(me, "phone", "Unknown"), version=2)
            last_activity = escape_markdown(str(status.get("last_activity", "Unknown")), version=2)

            text = f"""📊 *Userbot Status*

    *Status:* {status_text}
    *User:* `{user_info}`
    *Premium:* {premium}
    *User ID:* `{user_id}`
    *Phone:* `{phone}`
    *Last Activity:* `{last_activity}`
    """

        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="userbot_status")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_userbot")]
        ]
        if caller_user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await self._safe_edit_text(update.callback_query, 
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise


    
    # Groups Menu Methods
    async def show_groups_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show groups management menu - OPTIMIZED (no DB queries)."""
        user_id = update.effective_user.id
        
        keyboard = [
            [InlineKeyboardButton("➕ Add to Groups", callback_data="groups_add")],
            [InlineKeyboardButton("📋 View Groups", callback_data="groups_view")],
            [InlineKeyboardButton("❌ Remove from Group", callback_data="groups_remove")],
            [InlineKeyboardButton("⏱ Join Interval", callback_data="set_join_interval")],
            [InlineKeyboardButton("🔄 Processes", callback_data="groups_processes")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ]
        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(5, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        
        text = "👥 **Groups Management**\n\nSelect an option:"
        try:
            await self._safe_edit_text(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
    
    async def start_groups_add_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start groups addition flow."""
        self.temp_data[update.effective_user.id] = {
            "flow_type": "groups_add",
            "groups_to_add": [],
            "current_index": 0
        }
        
        text = """➕ **Add to Groups**

You can add multiple groups/channels. Supported formats:
• `@username`
• `https://t.me/username`
• `https://t.me/joinchat/invite_hash`

Please send the first group link or username:"""
        
        await self._safe_edit_text(update.callback_query, 
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu_groups")]
            ])
        )
    
    async def handle_groups_add_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
        """Handle groups addition flow, now supports multi-line input and pagination preview, with validation and user feedback."""
        from telegram.helpers import escape_markdown

        user_id = update.effective_user.id
        flow_data = self.temp_data[user_id]

        # Split lines, trim, filter non-empty
        new_links = [line.strip() for line in message_text.strip().splitlines() if line.strip()]
        existing = set(flow_data.get("groups_to_add", []))
        invalid = []
        added = []

        for link in new_links:
            # Basic Telegram link validation
            if link in existing or not (link.startswith('@') or 't.me/' in link):
                invalid.append(link)
                continue
            flow_data.setdefault("groups_to_add", []).append(link)
            existing.add(link)
            added.append(link)

        # Build feedback message
        msg_lines = []
        if added:
            msg_lines.append("✅ *Added:* " + ", ".join([escape_markdown(l, version=2) for l in added]))
        if invalid:
            msg_lines.append("❌ *Invalid or duplicate:* " + ", ".join([escape_markdown(l, version=2) for l in invalid]))

        # Always show back/cancel button!
        await update.message.reply_text(
            "\n".join(msg_lines) if msg_lines else "Nothing new added.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_groups")]]),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True
        )

        # Save current page (if not already set)
        flow_data.setdefault("current_page", 0)

        # Show the group preview with all entered so far
        await self.send_group_preview(update, context, user_id)


    async def send_group_preview(self, update, context, user_id, edit=False):
        flow_data = self.temp_data[user_id]
        groups = flow_data["groups_to_add"]
        page = flow_data.get("current_page", 0)
        page_size = 10
        total_pages = (len(groups) + page_size - 1) // page_size
        start = page * page_size
        end = start + page_size
        page_groups = groups[start:end]

        # Escape the list number, the dot, and the group
        preview = "\n".join([
            f"{escape_markdown(str(start + idx + 1), version=2)}\\."
            f" {escape_markdown(g, version=2)}"
            for idx, g in enumerate(page_groups)
        ]) or escape_markdown("_No groups entered yet._", version=2)

        # ESCAPE ALL STATIC TEXT and any punctuation!
        title = escape_markdown("📝 Confirm Groups to Join", version=2)
        page_str = escape_markdown(f"(Page {page+1}/{total_pages or 1})", version=2)
        instructions = escape_markdown(
            "Paste all group links/usernames above, review, then press ✅ to confirm or add more.",
            version=2
        )

        text = f"{title} {page_str}\n\n{preview}\n\n{instructions}"

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Prev", callback_data="groups_prevpage"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("Next ➡️", callback_data="groups_nextpage"))

        keyboard = []
        if nav:
            keyboard.append(nav)
        keyboard.append([
            InlineKeyboardButton("✅ Confirm Join", callback_data="groups_confirm_join"),
            InlineKeyboardButton("❌ Cancel", callback_data="menu_groups"),
        ])
        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        if edit and update.callback_query:
            try:
                await self._safe_edit_text(update.callback_query, 
                    text, reply_markup=reply_markup, parse_mode="MarkdownV2"
                )
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    # Ignore harmless error
                    pass
                else:
                    raise
        else:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode="MarkdownV2"
            )

    
    async def start_group_joining_process(self, update: Update, context: ContextTypes.DEFAULT_TYPE, groups_list: List[str]):
        """Start the group joining process with progress updates."""
        successful_joins = 0
        total_groups = len(groups_list)

        # Create progress message
        progress_text = (
            f"🔄 **Joining Groups Progress**\n\n"
            f"**Total Groups:** {total_groups}\n"
            f"**Current:** Starting...\n"
            f"**Status:** Initializing"
        )

        if update.message:
            message = await update.message.reply_text(progress_text, parse_mode=ParseMode.MARKDOWN)
        else:
            # For CallbackQuery context
            message = await update.callback_query.message.reply_text(progress_text, parse_mode=ParseMode.MARKDOWN)

        for i, group_link in enumerate(groups_list, 1):
            # Update progress
            progress_text = (
                f"🔄 **Joining Groups Progress**\n\n"
                f"**Total Groups:** {total_groups}\n"
                f"**Current:** {i}/{total_groups}\n"
                f"**Joining:** {group_link}\n"
                f"**Status:** Attempting to join..."
            )

            await message.edit_text(progress_text, parse_mode=ParseMode.MARKDOWN)

            # Attempt to join
            success, result_message = await self.userbot_manager.join_group(group_link)
            if success:
                successful_joins += 1

            # Print to your console for debug
            print(f"[Join Debug] {group_link} — {success} — {result_message}")

            # Update with result
            status_emoji = "✅" if success else "❌"
            progress_text = (
                f"🔄 **Joining Groups Progress**\n\n"
                f"**Total Groups:** {total_groups}\n"
                f"**Current:** {i}/{total_groups}\n"
                f"**Last Group:** {group_link}\n"
                f"**Result:** {status_emoji} {result_message}\n\n"
                f"{'⏳ Waiting 5 minutes before next join...' if i < total_groups else '🎉 Process completed!'}"
            )

            await message.edit_text(progress_text, parse_mode=ParseMode.MARKDOWN)

            # Wait 10 minutes between joins (except for the last one)
            if i < total_groups:
                await asyncio.sleep(600)  # 10 minutes

        # Final message
        await message.edit_text(
            f"🎉 **Group Joining Completed!**\n\n"
            f"Tried to join {total_groups} groups.\n"
            f"✅ Successfully joined {successful_joins} group(s).\n"
            f"❌ Failed to join {total_groups - successful_joins} group(s).\n"
            "Check the groups list to see results.",
            parse_mode=ParseMode.MARKDOWN
        )

        # Refresh groups list
        await self.userbot_manager.fetch_groups()

    
    async def show_groups_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
        """Show groups list with pagination and chat type labeling - USER-SCOPED."""
        user_id = update.effective_user.id
        groups = self.db.execute_query(
            "SELECT chat_id, title, username, chat_type, is_selected FROM groups WHERE user_id = ? ORDER BY title",
            (user_id,)
        )
        
        if not groups:
            text = "📋 **Groups List**\n\nNo groups found. Add some groups first!"
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_groups")]]
        else:
            page_size = 10
            total_pages = (len(groups) + page_size - 1) // page_size
            start_idx = page * page_size
            end_idx = min(start_idx + page_size, len(groups))
            page_groups = groups[start_idx:end_idx]

            type_map = {
                "channel": "📢 Channel",
                "basic_group": "👥 Group",
                "supergroup": "👥 Supergroup",
                "forum": "🧵 Forum",
                "unknown": "❓ Unknown"
            }

            groups_text = ""
            keyboard = []

            for group in page_groups:
                chat_id, title, username, chat_type, is_selected = group
                status_emoji = "✅" if is_selected else "❌"
                safe_title = escape_markdown(str(title), version=2)
                safe_username = escape_markdown(str(username), version=2) if username else "Private"
                safe_chat_type = escape_markdown(type_map.get(chat_type, "❓"), version=2)

                groups_text += f"{status_emoji} *{safe_title}*\n   {safe_username} • {safe_chat_type}\n\n"

                # Toggle button
                button_label = f"{status_emoji} {title[:30]}..."
                keyboard.append([
                    InlineKeyboardButton(button_label, callback_data=f"group_toggle_{chat_id}")
                ])

            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"groups_page_{page-1}"))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"groups_page_{page+1}"))
            if nav_buttons:
                keyboard.append(nav_buttons)

            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_groups")])

            text = f"""👥 **MANAGE DESTINATION GROUPS** (Page {page + 1}/{total_pages})

{groups_text}

**✅** = Will receive your messages
**❌** = Will NOT receive your messages

_Tap any group to toggle ON/OFF:_"""

        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await self._safe_edit_text(update.callback_query, 
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass  # harmless
            else:
                raise
    
    async def toggle_group_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str):
        """Toggle group selection for forwarding."""
        chat_id = int(callback_data.split("_")[-1])
        
        # Toggle selection
        current_selection = self.db.execute_query(
            "SELECT is_selected FROM groups WHERE chat_id = ?", (chat_id,)
        )
        
        if current_selection:
            new_selection = 1 - current_selection[0][0]
            self.db.execute_query(
                "UPDATE groups SET is_selected = ? WHERE chat_id = ?",
                (new_selection, chat_id)
            )
        
        # Refresh the groups list
        await self.show_groups_list(update, context)
    
    

    async def safe_edit_message_text(self, cbq, *args, **kwargs):
        """Safely edit message text, falling back to caption for media messages."""
        try:
            await cbq.edit_message_text(*args, **kwargs)
        except BadRequest as e:
            error_str = str(e).lower()
            if "message is not modified" in error_str:
                return
            if "there is no text" in error_str:
                try:
                    text = kwargs.get('text', args[0] if args else '')
                    reply_markup = kwargs.get('reply_markup')
                    parse_mode = kwargs.get('parse_mode')
                    await cbq.edit_message_caption(
                        caption=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode
                    )
                except BadRequest as e2:
                    if "message is not modified" in str(e2).lower():
                        return
                    raise
                return
            raise
    
    # Forwarding Menu Methods
    async def show_forwarding_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show forwarding management menu - OPTIMIZED (no DB queries)."""
        user_id = update.effective_user.id
        
        # Build keyboard without any DB overhead
        keyboard = [
            [InlineKeyboardButton("✏️ Manage Messages", callback_data="forwarding_messages")],
            [InlineKeyboardButton("⚙️ Forwarding Controls", callback_data="forwarding_controls")],
            [InlineKeyboardButton("📑 Manage Destinations", callback_data="forwarding_destinations")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ]
        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        
        text = "📤 **Forwarding Management**\n\nSelect an option:"
        
        try:
            await self._safe_edit_text(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
    
    async def show_forwarding_messages_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show forwarding messages management menu - USER-SCOPED with dynamic limits."""
        user_id = update.effective_user.id
        messages = self.db.get_forwarding_messages(user_id)
        
        # Get user's message limit
        user_data = self.db.execute_query("SELECT message_limit FROM authorized_users WHERE user_id = ?", (user_id,))
        max_messages = user_data[0][0] if user_data and user_data[0][0] is not None else 2
        
        keyboard = []
        messages_text = ""
        
        if messages:
            messages_text = "📨 **ACTIVE MESSAGES TO FORWARD:**\n\n"
            for i, msg in enumerate(messages, 1):
                messages_text += f"Message #{i}:\n`{msg['link']}`\n\n"
                keyboard.append([
                    InlineKeyboardButton(
                        f"🗑️ Delete Message #{i}",
                        callback_data=f"message_remove_{msg['id']}"
                    )
                ])
        else:
            messages_text = "❌ No messages configured for forwarding yet."
        
        if len(messages) < max_messages:
            keyboard.append([InlineKeyboardButton("➕ Add New Message", callback_data="message_add")])
        
        keyboard.append([InlineKeyboardButton("🔙 Back to Forwarding", callback_data="menu_forwarding")])
        
        text = f"""📤 **MANAGE FORWARDING MESSAGES** ({len(messages)}/{max_messages})

{messages_text}

_What are these?_ These are the SOURCE messages you want to automatically forward to your selected groups."""

        
        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await self._safe_edit_text(update.callback_query, 
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                # Ignore harmless error
                pass
            else:
                raise
    
    async def start_message_add_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start message addition flow."""
        self.temp_data[update.effective_user.id] = {
            "flow_type": "message_add"
        }
        
        text = """➕ **Add Forwarding Message**

Please send the message link in this format:
`https://t.me/channel_name/message_id`

Example: `https://t.me/mychannel/123`"""
        
        try:
            await self._safe_edit_text(update.callback_query, text, parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass  # Ignore harmless error
            else:
                raise
    
    async def handle_message_add_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str):
        """Handle message addition flow."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        user_id = update.effective_user.id

        success, message = await self.forwarding_manager.add_forwarding_message(message_text, user_id)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Forwarding", callback_data="menu_forwarding")]
        ])

        if success:
            await update.message.reply_text(f"✅ {message}", reply_markup=keyboard)
        else:
            await update.message.reply_text(f"❌ {message}", reply_markup=keyboard)

        if user_id in self.temp_data:
            del self.temp_data[user_id]
    
    async def remove_forwarding_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE, callback_data: str):
        """Remove a forwarding message - USER-SCOPED."""
        user_id = update.effective_user.id
        message_id = int(callback_data.split("_")[-1])
        
        success = self.forwarding_manager.remove_forwarding_message(message_id, user_id)
        
        if success:
            await update.callback_query.answer("✅ Message removed successfully!")
        else:
            await update.callback_query.answer("❌ Failed to remove message.")
        
        # Refresh the messages menu
        await self.show_forwarding_messages_menu(update, context)
    
    async def show_forwarding_controls_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show forwarding controls, including Group/DM destination toggles."""
        user_id = update.effective_user.id
        status = self.forwarding_manager.get_status()

        groups_on = self.db.get_user_setting(user_id, "ads_groups_enabled", "on") == "on"
        dms_on = self.db.get_user_setting(user_id, "ads_dms_enabled", "on") == "on"

        current_phase = getattr(self.forwarding_manager, "current_phase", "N/A").capitalize()
        next_event = status["next_forward_in"] or "N/A"
        hold_duration = self.db.get_setting("hold_duration", "15")
        per_msg_delay = self.db.get_setting("per_message_delay", "30")
        cycle_length = self.db.get_setting("cycle_length", "120")

        if status["is_running"]:
            if status["is_paused"]:
                status_text = "⏸️ **Paused**"
                control_buttons = [
                    InlineKeyboardButton("▶️ Resume", callback_data="forwarding_resume", style="success"),
                    InlineKeyboardButton("⏹️ Stop", callback_data="forwarding_stop", style="danger")
                ]
            else:
                status_text = "▶️ **Running**"
                control_buttons = [
                    InlineKeyboardButton("⏸️ Pause", callback_data="forwarding_pause", style="primary"),
                    InlineKeyboardButton("⏹️ Stop", callback_data="forwarding_stop", style="danger")
                ]
        else:
            status_text = "⏹️ **Stopped**"
            control_buttons = [InlineKeyboardButton("Run Ads ▶️", callback_data="forwarding_start", style="success")]

        if status["is_running"]:
            control_row = control_buttons
        else:
            control_row = control_buttons
        keyboard = [
            [
                InlineKeyboardButton(f"{'🟢' if groups_on else '🔴'} Groups: {'ON' if groups_on else 'OFF'}", callback_data="toggle_ads_groups", style="primary"),
                InlineKeyboardButton(f"{'🟢' if dms_on else '🔴'} DMs: {'ON' if dms_on else 'OFF'}", callback_data="toggle_ads_dms", style="primary")
            ],
            control_row,
            [InlineKeyboardButton("⏱ Per-Message Delay", callback_data="settings_alter_delay", style="primary"),
             InlineKeyboardButton("🕒 Hold Duration", callback_data="set_hold_duration", style="primary")],
            [InlineKeyboardButton("♻️ Cycle Length", callback_data="set_cycle_length", style="primary"),
             InlineKeyboardButton("👁 Preview Plan", callback_data="forwarding_preview", style="primary")],
            [InlineKeyboardButton(
                f"🏷️ Forward Tag: {'ON 🟢' if self.get_forward_mode() == 'show' else 'OFF 🔴'}",
                callback_data="toggle_forward_mode", style="primary"
            )],
            [InlineKeyboardButton("🔄 Refresh", callback_data="forwarding_controls", style="primary"),
             InlineKeyboardButton("🔙 Back", callback_data="back_main", style="primary")]
        ]

        text = f"""⚙️ **Forwarding Controls**

**Status:** {status_text}
**Destinations:** {'Groups ' + ('ON' if groups_on else 'OFF')} • {'DMs ' + ('ON' if dms_on else 'OFF')}

_💡 DMs use existing private chats of the connected userbot account._
**Total Forwarded:** {status['total_forwarded']}
**Errors / Info:** {status['errors']}
**Selected Groups:** {status['selected_groups']}
**Forwarding Messages:** {status['forwarding_messages']}
**Cycle Phase:** {current_phase}
**Next Event:** {next_event}
**Cycle Length:** {cycle_length} minutes
**Hold Duration:** {hold_duration} minutes
**Per-Message Delay:** {per_msg_delay} seconds
**Last Forward:** {status['last_forward_time'] or 'Never'}

Select an action:"""

        if user_id == self.ADMIN_USER_ID:
            keyboard.append([InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel", style="danger")])
        await self._safe_edit_text(
            update.callback_query, text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

    async def start_forwarding(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start forwarding process."""
        success, message = await self.forwarding_manager.start_forwarding()
        
        await update.callback_query.answer(message)
        await self.show_forwarding_controls_menu(update, context)
    
    async def stop_forwarding(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stop forwarding process."""
        success, message = self.forwarding_manager.stop_forwarding()
        
        await update.callback_query.answer(message)
        await self.show_forwarding_controls_menu(update, context)
    
    async def pause_forwarding(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pause forwarding process."""
        success, message = self.forwarding_manager.pause_forwarding()
        
        await update.callback_query.answer(message)
        await self.show_forwarding_controls_menu(update, context)
    
    async def resume_forwarding(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resume forwarding process."""
        success, message = self.forwarding_manager.resume_forwarding()
        
        await update.callback_query.answer(message)
        await self.show_forwarding_controls_menu(update, context)
    
    
    async def show_forwarding_destinations_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show forwarding destinations (same as groups list)."""
        await self.show_groups_list(update, context)
    
    # Status Menu Methods
    async def show_status_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show system status menu."""
        import datetime
        ts_start = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # Subscription already checked in callback handler - no redundant check needed
        user_id = update.effective_user.id
        keyboard = [
            [InlineKeyboardButton("📈 Live Status", callback_data="status_live")],
            [InlineKeyboardButton("📊 Analytics", callback_data="status_analytics")],
            [InlineKeyboardButton("📡 Live Trace", callback_data="status_trace")],
            [InlineKeyboardButton("📄 Logs", callback_data="status_logs")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_main")]
        ]
        
        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = "📊 **System Status**\n\nSelect an option:"
        
        try:
            await self._safe_edit_text(update.callback_query, 
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            ts_after_edit = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[USER_TIMING] {ts_after_edit} ✅ MESSAGE VISIBLE TO USER (status_menu)")
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass
            else:
                print(f"[ERROR] show_status_menu error: {e}")
        except Exception as e:
            print(f"[ERROR] show_status_menu unexpected error: {e}")
    
    async def show_analytics_dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show advanced analytics and statistics dashboard."""
        user_id = update.effective_user.id
        # Get stats without blocking - use thread pool
        stats = await self._run_db_query(self.db.get_forwarding_stats, user_id) if hasattr(self, '_run_db_query') else self.db.get_forwarding_stats(user_id)
        
        success_rate = "N/A"
        if stats.get("total_forwards", 0) > 0:
            success_pct = int((stats["total_forwards"] / max(stats["total_forwards"], 1)) * 100)
            success_rate = f"{success_pct}% ✅"
        
        text = (
            "📊 *Advanced Analytics Dashboard*\n\n"
            "*📈 Forwarding Performance:*\n"
            f"├ Success Rate: {success_rate}\n"
            f"├ Total Forwards: {stats.get('total_forwards', 0)}\n"
            f"├ Today: {stats.get('forwards_today', 0)}\n"
            f"└ This Week: {stats.get('forwards_week', 0)}\n\n"
            "*👥 Group Statistics:*\n"
            f"├ Groups Used: {stats.get('groups_used', 0)}\n"
            f"├ Selected for Forwarding: {stats.get('selected_groups', 0)}\n"
            f"└ Total Groups: {stats.get('total_groups', 0)}\n\n"
            "*⚡ Performance Metrics:*\n"
            f"├ Avg Per Day: {stats.get('forwards_week', 0) // 7 if stats.get('forwards_week', 0) > 0 else 0}\n"
            f"├ Active Groups: {stats.get('selected_groups', 0)} / {stats.get('total_groups', 0)}\n"
            f"└ Coverage: {int((stats.get('groups_used', 0) / max(stats.get('total_groups', 1), 1)) * 100)}%"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="status_analytics")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await self._safe_edit_text(update.callback_query, 
                text, 
                reply_markup=reply_markup, 
                parse_mode=ParseMode.MARKDOWN
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
    
    async def show_live_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        """Show live system status - USER-SCOPED."""
        # Get userbot status
        userbot_status = await self.userbot_manager.get_status()
        forwarding_status = self.forwarding_manager.get_status()
        groups_count = self.db.execute_query("SELECT COUNT(*) FROM groups WHERE user_id = ?", (user_id,))[0][0]
        selected_groups = self.db.execute_query("SELECT COUNT(*) FROM groups WHERE user_id = ? AND is_selected = 1", (user_id,))[0][0]
        messages_count = self.db.execute_query("SELECT COUNT(*) FROM forwarding_messages WHERE user_id = ? AND is_active = 1", (user_id,))[0][0]

        # Escape all dynamic/user content!
        userbot_status_text = escape_markdown(
            "✅ Connected" if userbot_status["status"] == "✅ Connected" else "❌ Disconnected", version=2)
        user_info = escape_markdown(str(userbot_status.get("user_info", "")), version=2)
        last_activity = escape_markdown(str(userbot_status.get("last_activity", "")), version=2)

        if forwarding_status["is_running"]:
            forwarding_status_text = escape_markdown(
                "⏸️ Paused" if forwarding_status["is_paused"] else "▶️ Running", version=2)
        else:
            forwarding_status_text = escape_markdown("⏹️ Stopped", version=2)

        total_forwarded = escape_markdown(str(forwarding_status["total_forwarded"]), version=2)
        errors = escape_markdown(str(forwarding_status["errors"]), version=2)
        last_forward_time = escape_markdown(
            str(forwarding_status["last_forward_time"] or "Never"), version=2)

        groups_count_str = escape_markdown(str(groups_count), version=2)
        selected_groups_str = escape_markdown(str(selected_groups), version=2)
        messages_count_str = escape_markdown(str(messages_count), version=2)

        last_update = escape_markdown(datetime.now().strftime('%Y-%m-%d %H:%M:%S'), version=2)

        text = (
            f"{escape_markdown('📈 Live System Status', version=2)}\n\n"
            f"{escape_markdown('🛠 Userbot:', version=2)}\n"
            f"Status: {userbot_status_text}\n"
            f"User: {user_info}\n"
            f"Last Activity: {last_activity}\n\n"
            f"{escape_markdown('📤 Forwarding:', version=2)}\n"
            f"Status: {forwarding_status_text}\n"
            f"Total Forwarded: {total_forwarded}\n"
            f"Errors: {errors}\n"
            f"Last Forward: {last_forward_time}\n\n"
            f"{escape_markdown('👥 Groups:', version=2)}\n"
            f"Total Groups: {groups_count_str}\n"
            f"Selected for Forwarding: {selected_groups_str}\n\n"
            f"{escape_markdown('📝 Messages:', version=2)}\n"
            f"Forwarding Messages: {messages_count_str}/2\n\n"
            f"{escape_markdown('⏰ Last Update:', version=2)} {last_update}"
        )

        MAX_LEN = 3900
        if len(text) > MAX_LEN:
            text = text[:MAX_LEN] + escape_markdown("\n...truncated...", version=2)

        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="status_live")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_status")]
        ]
        if user_id == self.ADMIN_USER_ID:
            keyboard.insert(4, [InlineKeyboardButton("🔐 Admin Panel", callback_data="admin_panel")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await self._safe_edit_text(update.callback_query, 
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                pass
            else:
                raise
    
    async def show_forwarding_preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show live preview of forwarding plan."""
        messages = self.forwarding_manager.get_forwarding_messages()
        groups = self.forwarding_manager.get_selected_groups()
        status = self.forwarding_manager.get_status()

        lines = [escape_markdown("📤 Forwarding Preview", version=2), ""]

        if not messages:
            lines.append(escape_markdown("No messages added.", version=2))
        else:
            for i, m in enumerate(messages, start=1):
                link = escape_markdown(m.get("link", "N/A"), version=2)
                lines.append(f"{i}\\: {link}")

        lines.append("")
        if not groups:
            lines.append(escape_markdown("No destination groups selected.", version=2))
        else:
            lines.append(escape_markdown(f"{len(groups)} groups selected:", version=2))
            for g in groups[:5]:
                title = escape_markdown(g.get("title", "Unnamed"), version=2)
                lines.append(f"• {title}")
            if len(groups) > 5:
                lines.append(escape_markdown(f"...and {len(groups)-5} more", version=2))

        lines.append("")
        status_text = escape_markdown("▶️ Running" if status.get("is_running") else "⏹️ Stopped", version=2)
        lines.append(f"Status: {status_text}")
        lines.append(f"Total Forwarded: {escape_markdown(str(status.get('total_forwarded', 0)), version=2)}")
        lines.append(f"Errors: {escape_markdown(str(status.get('errors', 0)), version=2)}")

        last_time = status.get("last_forward_time")
        last_time_str = escape_markdown(str(last_time), version=2) if last_time else "Never"
        lines.append(f"Last Forward: {last_time_str}")

        text = "\n".join(lines).strip()

        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data="forwarding_preview")],
            [InlineKeyboardButton("🔙 Back", callback_data="forwarding_controls")]
        ]
        new_markup = InlineKeyboardMarkup(keyboard)
        new_markup_json = json.dumps(new_markup.to_dict(), sort_keys=True)

        current_text = update.callback_query.message.text.strip()
        current_markup = update.callback_query.message.reply_markup
        current_markup_json = json.dumps(current_markup.to_dict(), sort_keys=True) if current_markup else ""

        # Safe comparison
        text_changed = text != current_text
        markup_changed = new_markup_json != current_markup_json

        try:
            if text_changed:
                await self._safe_edit_text(update.callback_query, 
                    text=text,
                    reply_markup=new_markup,
                    parse_mode="MarkdownV2"
                )
            elif markup_changed:
                await update.callback_query.edit_message_reply_markup(
                    reply_markup=new_markup
                )
        except Exception as e:
            # Log silently if the error is 'Message is not modified'
            if "Message is not modified" not in str(e):
                raise e

    async def show_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
        """Show system logs with pagination."""
        PAGE_SIZE = 20
        offset = page * PAGE_SIZE

        logs = self.db.execute_query(
            "SELECT level, message, timestamp FROM logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (PAGE_SIZE, offset)
        )

        total_logs = self.db.fetch_one("SELECT COUNT(*) FROM logs")[0]
        total_pages = (total_logs + PAGE_SIZE - 1) // PAGE_SIZE

        if not logs:
            logs_text = escape_markdown("No logs found.", version=2)
        else:
            logs_text = ""
            for level, message, timestamp in logs:
                emoji = "❌" if level == "ERROR" else "ℹ️"
                logs_text += (
                    f"{emoji} "
                    f"`{escape_markdown(str(timestamp), version=2)}`"
                    f" \\- "
                    f"{escape_markdown(str(message), version=2)}\n"
                )

        text = (
            f"{escape_markdown(f'📄 System Logs (Page {page + 1} of {total_pages})', version=2)}\n\n"
            f"{logs_text}\n"
            f"{escape_markdown('Legend:', version=2)}\n"
            f"{escape_markdown('❌ = Error', version=2)}\n"
            f"{escape_markdown('ℹ️ = Info', version=2)}"
        )

        MAX_LEN = 3900
        if len(text) > MAX_LEN:
            text = text[:MAX_LEN] + escape_markdown("\n...truncated...", version=2)

        # Pagination buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"logs_page_{page - 1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"logs_page_{page + 1}"))

        keyboard = [
            nav_buttons if nav_buttons else [],
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"logs_page_{page}")],
            [InlineKeyboardButton("🗑️ Clear Logs", callback_data="logs_clear")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_status")]
        ]
        reply_markup = InlineKeyboardMarkup([row for row in keyboard if row])  # Remove empty rows

        if hasattr(update, "callback_query") and update.callback_query:
            try:
                await self._safe_edit_text(update.callback_query, 
                    text, reply_markup=reply_markup, parse_mode="Markdown"
                )
            except BadRequest as e:
                if "Message is not modified" in str(e):
                    pass
                else:
                    raise
        else:
            await update.message.reply_text(
                text, reply_markup=reply_markup, parse_mode="Markdown"
            )
    async def show_live_trace(self, update, context, page=0):
        """Show recent forwarded traces (only from last 1 hour)."""
        self.db.execute_query(
            "DELETE FROM forward_trace WHERE forwarded_at < datetime('now', '-1 hour')"
        )

        all_traces = self.db.execute_query(
            "SELECT group_title, chat_id, message_id, forwarded_at FROM forward_trace ORDER BY forwarded_at DESC"
        )

        per_page = 10
        total_pages = (len(all_traces) + per_page - 1) // per_page
        traces_page = all_traces[page * per_page : (page + 1) * per_page]

        if not traces_page:
            text = "⚠️ *No trace records found in the last 1 hour.*"
            parse_mode = ParseMode.MARKDOWN
        else:
            text = escape_markdown("📡 Live Trace Logs (past 1 hour)", version=2) + "\n\n"
            for title, chat_id, msg_id, ts in traces_page:
                try:
                    clean_chat_id = str(chat_id).replace("-100", "")
                    raw_link = f"https://t.me/c/{clean_chat_id}/{msg_id}"
                    link = quote(raw_link, safe=':/')

                    time_obj = datetime.fromisoformat(ts)
                    if time_obj.tzinfo is None:
                        time_obj = time_obj.replace(tzinfo=timezone.utc).astimezone()
                    else:
                        time_obj = time_obj.astimezone()

                    ago_delta = datetime.now().astimezone() - time_obj
                    if ago_delta < timedelta(minutes=1):
                        ago = "Just now"
                    elif ago_delta < timedelta(hours=1):
                        ago = f"{int(ago_delta.total_seconds() // 60)} min ago"
                    elif ago_delta < timedelta(days=1):
                        ago = f"{int(ago_delta.total_seconds() // 3600)} hour ago"
                    else:
                        ago = f"{ago_delta.days} day ago"

                    title_md = escape_markdown(title or "Unknown", version=2)
                    ago_md = escape_markdown(ago, version=2)

                    text += f"• [{title_md}]({link})\n  Time: {ago_md}\n\n"

                except Exception:
                    fallback = escape_markdown(title or "Unknown", version=2)
                    text += f"• *{fallback}* \\(error parsing time or link\\)\n\n"

            parse_mode = ParseMode.MARKDOWN_V2

        # Navigation buttons
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"trace_page_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"trace_page_{page+1}"))

        keyboard = [
            nav_buttons if nav_buttons else [],
            [InlineKeyboardButton("🔄 Refresh", callback_data="status_trace")],
            [InlineKeyboardButton("🗑️ Clear Traces", callback_data="trace_clear")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_status")]
        ]
        reply_markup = InlineKeyboardMarkup([row for row in keyboard if row])

        try:
            if hasattr(update, "callback_query") and update.callback_query:
                await self._safe_edit_text(update.callback_query, 
                    text=text, reply_markup=reply_markup, parse_mode=parse_mode
                )
            else:
                await update.message.reply_text(
                    text=text, reply_markup=reply_markup, parse_mode=parse_mode
                )
        except BadRequest as e:
            if "Message is not modified" in str(e):
                await update.callback_query.answer("✅ Already up to date.", show_alert=False)
            elif "Can't parse entities" in str(e):
                await update.callback_query.answer("⚠️ Formatting issue. Please check log entries.", show_alert=True)
            else:
                raise

    async def show_help_menu(self, update, context, page=0):
        total_pages = len(self.HELP_PAGES)
        page = max(0, min(page, total_pages - 1))
        data = self.HELP_PAGES[page]
        text = f"{data['title']}\n\n{data['content']}\n\n_Page {page + 1} of {total_pages}_"

        user_id = update.effective_user.id
        is_admin = await self.is_admin(user_id)

        buttons = []
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"help_page_{page - 1}"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"help_page_{page + 1}"))
        if nav:
            buttons.append(nav)
        # Show "Back" only for public (non-admin) users
        if not is_admin:
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="public_back")])
        else:
            buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back_main")])

        # Use callback or normal message
        if hasattr(update, "callback_query") and update.callback_query:
            try:
                await self._safe_edit_text(update.callback_query, 
                    text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            await update.message.reply_text(
                text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown"
            )

    async def is_user_authorized(self, user_id: int, admin_id: int) -> bool:
        """Free-access mode: every Telegram user may use normal bot features.

        This method is kept for compatibility with the existing codebase and
        payment/subscription records. It no longer blocks normal dashboard
        callbacks when a user has no subscription or an expired subscription.
        Admin-only panels still use explicit ADMIN_USER_ID checks.
        """
        return True
    
    def get_user_time_remaining(self, user_id: int) -> Optional[int]:
        """Get remaining minutes for a user."""
        result = self.db.fetch_one(
            "SELECT expires_at FROM authorized_users WHERE user_id = ?",
            (user_id,)
        )
        if not result or not result[0]:
            return None
        
        expires_at = datetime.fromisoformat(result[0])
        remaining = (expires_at - datetime.now()).total_seconds() / 60
        return max(0, int(remaining))

    async def _show_broadcast_setup(self, update, context):
        user_id = update.effective_user.id
        flow = self.temp_data.get(user_id, {})
        send_dm = bool(flow.get("send_dm", True))
        send_group = bool(flow.get("send_group", True))
        has_message = bool(flow.get("broadcast_message"))
        dm_label = "🟢 DMs: ON" if send_dm else "🔴 DMs: OFF"
        group_label = "🟢 Groups: ON" if send_group else "🔴 Groups: OFF"
        keyboard = [
            [InlineKeyboardButton(dm_label, callback_data="broadcast_toggle_dm")],
            [InlineKeyboardButton(group_label, callback_data="broadcast_toggle_group")],
        ]
        if has_message:
            keyboard.append([InlineKeyboardButton("🚀 Start Broadcast", callback_data="broadcast_send")])
            text=("📢 <b>Broadcast Settings</b>\n\n"
                  "Choose destinations for this message.\n\n"
                  f"👤 DMs: <b>{'ON' if send_dm else 'OFF'}</b>\n"
                  f"👥 Groups: <b>{'ON' if send_group else 'OFF'}</b>\n\n"
                  "Tap <b>Start Broadcast</b> when ready.")
        else:
            text=("📢 <b>Broadcast Message</b>\n\n"
                  "Send the message/media you want to broadcast first.\n\n"
                  "After that you can turn <b>DMs</b> and <b>Groups</b> ON/OFF.")
        keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data="admin_panel")])
        if update.callback_query:
            await self._safe_edit_text(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)

    async def _run_saved_broadcast(self, update, context):
        user_id=update.effective_user.id
        flow=self.temp_data.get(user_id,{})
        if not flow.get("broadcast_message"):
            await update.callback_query.answer("❌ Send a message first.", show_alert=True)
            return
        if not flow.get("send_dm",True) and not flow.get("send_group",True):
            await update.callback_query.answer("❌ Turn on DMs or Groups first.", show_alert=True)
            return
        source_chat_id=flow["source_chat_id"]; source_message_id=flow["source_message_id"]
        send_dm=bool(flow.get("send_dm",True)); send_group=bool(flow.get("send_group",True))
        users=self.db.execute_query("SELECT DISTINCT user_id FROM authorized_users")
        dm_ids={int(r[0]) for r in users if r and r[0]} if send_dm else set(); dm_ids.discard(user_id)
        rows=self.db.execute_query("SELECT DISTINCT chat_id,title FROM groups WHERE user_id=? AND is_selected=1 AND chat_type IN ('basic_group','supergroup','forum')",(user_id,))
        groups=[(int(r[0]),r[1] or str(r[0])) for r in rows if r and r[0]] if send_group else []
        total=len(dm_ids)+len(groups)
        if total==0:
            await update.callback_query.answer("❌ No targets found.",show_alert=True); return
        await update.callback_query.answer("📢 Broadcast started!")
        progress=await context.bot.send_message(user_id,f"📢 <b>Broadcasting</b>\n\n👤 DMs: 0/{len(dm_ids)}\n👥 Groups: 0/{len(groups)}\n📦 Total: 0/{total}",parse_mode=ParseMode.HTML)
        ds=fs=gs=gf=done=0
        for target in dm_ids:
            try: await context.bot.copy_message(target,source_chat_id,source_message_id); ds+=1
            except Exception as e: fs+=1; self.db.log_event("ERROR",f"DM broadcast failed for {target}: {e}")
            done+=1
        for chat_id,title in groups:
            try: await context.bot.copy_message(chat_id,source_chat_id,source_message_id); gs+=1
            except Exception as e: gf+=1; self.db.log_event("ERROR",f"Group broadcast failed for {title} ({chat_id}): {e}")
            done+=1
        self.temp_data.pop(user_id,None)
        await progress.edit_text(f"✅ <b>Broadcast Complete</b>\n\n👤 DMs — Sent: <b>{ds}</b> | Failed: <b>{fs}</b>\n👥 Groups — Sent: <b>{gs}</b> | Failed: <b>{gf}</b>\n\n📦 Total targets: <b>{total}</b>",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin Panel",callback_data="admin_panel")]]),parse_mode=ParseMode.HTML)

    async def _show_admin_panel(self, update, context):
        """Show admin panel menu"""
        current_bio = self.db.get_admin_setting('default_bio', 'Hosted By @SynaxBaby')
        current_lastname = self.db.get_admin_setting('default_lastname', 'Hosted By @SynaxBaby')
        
        keyboard = [
            [InlineKeyboardButton("✅ Approve User", callback_data="admin_approve_user")],
            [InlineKeyboardButton("⏰ Extend User Time", callback_data="admin_extend_time")],
            [InlineKeyboardButton("⚙️ Set User Limits", callback_data="admin_set_limits")],
            [InlineKeyboardButton("📋 View Authorized Users", callback_data="admin_list_users")],
            [InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast")],
            [InlineKeyboardButton("🇮🇳 Auto Fampay Configuration", callback_data="admin_fampay_config")],
            [InlineKeyboardButton("❌ Remove User", callback_data="admin_remove_user")],
            [InlineKeyboardButton("📊 Mandatory Log Bot", callback_data="admin_log_bot")],
            [InlineKeyboardButton("💎 Premium Maintenance", callback_data="admin_premium_maintenance")],
            [InlineKeyboardButton(f"📝 Set Default Bio", callback_data="admin_set_bio")],
            [InlineKeyboardButton(f"✏️ Set Default Last Name", callback_data="admin_set_lastname")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="back_main")]
        ]
        
        panel_text = (
            "🔐 *Admin Panel*\n\n"
            "Manage user access and permissions:\n\n"
            f"_Current Bio:_ `{current_bio}`\n"
            f"_Current Last Name:_ `{current_lastname}`"
        )
        
        return (panel_text, InlineKeyboardMarkup(keyboard))

    async def _handle_admin_approve_flow(self, update, message_text):
        """Handle admin approve user flow"""
        user_id = update.effective_user.id
        flow_data = self.temp_data[user_id]
        step = flow_data["step"]
        
        if step == "user_id":
            try:
                target_user_id = int(message_text.strip())
                flow_data["target_user_id"] = target_user_id
                flow_data["step"] = "duration"
                return (f"✅ User ID: `{target_user_id}`\n\nNow specify access duration:\n• `60` = 60 minutes\n• `2h` = 2 hours\n• `7d` = 7 days", None)
            except:
                return ("❌ Invalid User ID. Please send a valid number.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
        
        elif step == "duration":
            try:
                duration_text = message_text.strip().lower()
                
                if duration_text.endswith('d'):
                    minutes = int(duration_text[:-1]) * 24 * 60
                    display = f"{int(duration_text[:-1])} day(s)"
                elif duration_text.endswith('h'):
                    minutes = int(duration_text[:-1]) * 60
                    display = f"{int(duration_text[:-1])} hour(s)"
                else:
                    minutes = int(duration_text.replace('m', ''))
                    display = f"{minutes} minute(s)"
                
                flow_data["minutes"] = minutes
                flow_data["display"] = display
                flow_data["step"] = "userbot_limit"
                return (f"✅ Duration: {display}\n\nNow specify userbot limit (how many userbots can this user add):\nExample: `1`, `3`, `5`", None)
            except:
                return ("❌ Invalid duration format. Use: `60`, `2h`, or `7d`", None)
        
        elif step == "userbot_limit":
            try:
                userbot_limit = int(message_text.strip())
                if userbot_limit < 1:
                    return ("❌ Userbot limit must be at least 1.", None)
                
                flow_data["userbot_limit"] = userbot_limit
                flow_data["step"] = "message_limit"
                return (f"✅ Userbot Limit: {userbot_limit}\n\nNow specify message limit per userbot (or type 'unlimited'):\nExample: `100`, `1000`, `unlimited`", None)
            except:
                return ("❌ Invalid userbot limit. Please send a valid number.", None)
        
        elif step == "message_limit":
            try:
                if message_text.strip().lower() == "unlimited":
                    message_limit = None
                    message_limit_display = "Unlimited"
                else:
                    message_limit = int(message_text.strip())
                    message_limit_display = str(message_limit)
                
                target_user_id = flow_data["target_user_id"]
                minutes = flow_data["minutes"]
                display = flow_data["display"]
                userbot_limit = flow_data["userbot_limit"]
                
                approved_at = datetime.now()
                expires_at = approved_at + timedelta(minutes=minutes)
                
                self.db.execute_query(
                    "INSERT OR REPLACE INTO authorized_users (user_id, approved_at, expires_at, total_minutes_granted, approved_by, userbot_limit, message_limit) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (target_user_id, approved_at, expires_at, minutes, user_id, userbot_limit, message_limit)
                )
                
                del self.temp_data[user_id]
                return (
                    f"✅ *User Approved*\n\nUser ID: `{target_user_id}`\nDuration: {display}\nExpires: `{expires_at.strftime('%Y-%m-%d %H:%M:%S')}`\nUserbot Limit: {userbot_limit}\nMessage Limit: {message_limit_display}",
                    InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_panel")]])
                )
            except:
                return ("❌ Invalid message limit. Use a number or 'unlimited'.", None)
        
        return ("❌ Error", None)

    async def _handle_admin_extend_flow(self, update, message_text):
        """Handle extend user time flow"""
        user_id = update.effective_user.id
        flow_data = self.temp_data[user_id]
        step = flow_data["step"]
        
        if step == "user_id":
            try:
                target_user_id = int(message_text.strip())
                result = self.db.fetch_one("SELECT expires_at, total_minutes_granted FROM authorized_users WHERE user_id = ?", (target_user_id,))
                
                if not result:
                    del self.temp_data[user_id]
                    return (f"❌ User ID `{target_user_id}` is not in the authorized list.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                
                flow_data["target_user_id"] = target_user_id
                flow_data["step"] = "duration"
                
                remaining = self.get_user_time_remaining(target_user_id)
                remaining_str = f"{remaining} minutes" if remaining else "No expiration"
                
                return (f"✅ User ID: `{target_user_id}`\nCurrent Remaining: {remaining_str}\n\nHow much time to add? (e.g., `60`, `2h`, `7d`):", None)
            except:
                return ("❌ Invalid User ID.", None)
        
        elif step == "duration":
            try:
                duration_text = message_text.strip().lower()
                
                if duration_text.endswith('d'):
                    additional_minutes = int(duration_text[:-1]) * 24 * 60
                    display = f"{int(duration_text[:-1])} day(s)"
                elif duration_text.endswith('h'):
                    additional_minutes = int(duration_text[:-1]) * 60
                    display = f"{int(duration_text[:-1])} hour(s)"
                else:
                    additional_minutes = int(duration_text.replace('m', ''))
                    display = f"{additional_minutes} minute(s)"
                
                target_user_id = flow_data["target_user_id"]
                result = self.db.fetch_one("SELECT expires_at, total_minutes_granted FROM authorized_users WHERE user_id = ?", (target_user_id,))
                current_expires, current_total = result
                
                current_expires_dt = datetime.fromisoformat(current_expires) if current_expires else datetime.now()
                new_expires = max(current_expires_dt, datetime.now()) + timedelta(minutes=additional_minutes)
                new_total = current_total + additional_minutes
                
                self.db.execute_query("UPDATE authorized_users SET expires_at = ?, total_minutes_granted = ? WHERE user_id = ?", (new_expires, new_total, target_user_id))
                
                del self.temp_data[user_id]
                return (
                    f"✅ *Time Extended*\n\nUser ID: `{target_user_id}`\nAdded: {display}\nNew Expiration: `{new_expires.strftime('%Y-%m-%d %H:%M:%S')}`\nTotal Granted: {new_total} minutes",
                    InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
                )
            except:
                return ("❌ Invalid duration format.", None)
        
        return ("❌ Error", None)

    async def _handle_admin_set_limits_flow(self, update, message_text):
        """Handle admin set limits flow"""
        user_id = update.effective_user.id
        flow_data = self.temp_data[user_id]
        step = flow_data["step"]
        
        if step == "user_id":
            try:
                target_user_id = int(message_text.strip())
                result = self.db.fetch_one("SELECT message_limit, userbot_limit FROM authorized_users WHERE user_id = ?", (target_user_id,))
                
                if not result:
                    del self.temp_data[user_id]
                    return (f"❌ User ID `{target_user_id}` is not in the authorized list.", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                
                flow_data["target_user_id"] = target_user_id
                flow_data["step"] = "message_limit"
                
                current_msg_limit = result[0] if result[0] else "Unlimited"
                return (f"✅ User ID: `{target_user_id}`\nCurrent Message Limit: {current_msg_limit}\n\nEnter new message limit (number or 'unlimited'):", None)
            except:
                return ("❌ Invalid User ID.", None)
        
        elif step == "message_limit":
            try:
                if message_text.strip().lower() == "unlimited":
                    message_limit = None
                else:
                    message_limit = int(message_text.strip())
                
                flow_data["message_limit"] = message_limit
                flow_data["step"] = "userbot_limit"
                
                limit_str = "Unlimited" if message_limit is None else str(message_limit)
                return (f"✅ Message Limit: {limit_str}\n\nNow enter userbot limit (number):", None)
            except:
                return ("❌ Invalid input. Use a number or 'unlimited'.", None)
        
        elif step == "userbot_limit":
            try:
                userbot_limit = int(message_text.strip())
                if userbot_limit < 1:
                    return ("❌ Userbot limit must be at least 1.", None)
                
                target_user_id = flow_data["target_user_id"]
                message_limit = flow_data["message_limit"]
                
                self.db.execute_query(
                    "UPDATE authorized_users SET message_limit = ?, userbot_limit = ? WHERE user_id = ?",
                    (message_limit, userbot_limit, target_user_id)
                )
                
                del self.temp_data[user_id]
                msg_limit_str = "Unlimited" if message_limit is None else str(message_limit)
                return (
                    f"✅ *Limits Updated*\n\nUser ID: `{target_user_id}`\nMessage Limit: {msg_limit_str}\nUserbot Limit: {userbot_limit}",
                    InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]])
                )
            except:
                return ("❌ Invalid userbot limit. Use a number.", None)
        
        return ("❌ Error", None)

    def _get_authorized_users_list(self):
        """Get formatted list of authorized users"""
        users = self.db.execute_query("SELECT user_id, approved_at, expires_at, total_minutes_granted, message_limit, userbot_limit, messages_sent_count FROM authorized_users ORDER BY approved_at DESC")
        
        if not users:
            return "📋 *Authorized Users*\n\nNo users found."
        
        text = f"📋 *Authorized Users* ({len(users)} total)\n\n"
        
        for user_id, approved_at, expires_at, total_granted, msg_limit, bot_limit, msg_sent in users:
            approved_dt = datetime.fromisoformat(approved_at)
            
            if expires_at:
                remaining = self.get_user_time_remaining(user_id)
                if remaining and remaining > 0:
                    if remaining >= 1440:
                        remaining_str = f"{remaining // 1440}d {(remaining % 1440) // 60}h"
                    elif remaining >= 60:
                        remaining_str = f"{remaining // 60}h {remaining % 60}m"
                    else:
                        remaining_str = f"{remaining}m"
                    status = f"⏰ {remaining_str} left"
                else:
                    status = "❌ Expired"
            else:
                status = "✅ No expiration"
            
            msg_limit_str = str(msg_limit) if msg_limit else "Unlimited"
            bot_limit_str = str(bot_limit) if bot_limit else "1"
            msg_sent_str = str(msg_sent) if msg_sent else "0"
            
            text += f"• User: `{user_id}`\n  Status: {status}\n  Total: {total_granted}m\n  Approved: {approved_dt.strftime('%Y-%m-%d %H:%M')}\n  Msg Limit: {msg_limit_str} (Sent: {msg_sent_str})\n  Bot Limit: {bot_limit_str}\n\n"
        
        return text

# Free-dashboard mode: user-facing Premium/Buy Now entry points stay hidden.
# Admin-side premium configuration remains available for compatibility.

# ============================================================
# ADVANCED PATCHES — additive only, existing features retained
# ============================================================

# Mandatory logger gate: Ads cannot start until admin configured the logger bot.
_original_start_forwarding = ForwardingManager.start_forwarding
async def _patched_start_forwarding(self):
    if not self.bot.logging_bot_manager.mandatory_log_bot_ready():
        return False, ("❌ <b>Mandatory Log Bot Required</b>\n\n"
                       "Admin must configure the Log Bot from Admin Panel and start it with /start first.\n"
                       "Ads are locked until the logger is online.")
    return await _original_start_forwarding(self)
ForwardingManager.start_forwarding = _patched_start_forwarding

# Premium maintenance gate: no plan prices/buttons are exposed while maintenance is ON.
_original_show_plans = TelegramBot.show_subscription_plans
async def _patched_show_plans(self, update, context):
    if self.db.get_premium_maintenance():
        q=update.callback_query
        await q.answer('💎 Premium is temporarily under maintenance 🛠️', show_alert=True)
        await self._safe_edit_text(q,
            '💎 <b>Premium is temporarily under maintenance</b> 🛠️\n\n'
            'Our premium system is being updated right now.\n'
            'Please try again later. Your existing access remains safe. ❤️',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Back',callback_data='back_main',style='primary')]]),
            parse_mode=ParseMode.HTML)
        return
    return await _original_show_plans(self, update, context)
TelegramBot.show_subscription_plans = _patched_show_plans

# New admin callbacks are handled here, then every old callback continues normally.
_original_callback = TelegramBot._process_callback_async
async def _patched_callback(self, update, context, data):
    uid=update.effective_user.id
    q=update.callback_query
    if data == 'admin_log_bot':
        if uid != self.ADMIN_USER_ID:
            await q.answer('❌ Admin only',show_alert=True); return
        cfg=self.db.get_mandatory_log_bot()
        status=(f"🟢 @{cfg['username']}" if cfg else '🔴 Not configured')
        await self._safe_edit_text(q,
            f'📊 <b>MANDATORY LOG BOT</b>\n\n<b>Status:</b> {status}\n\n'
            'This logger is required before Ads can run.\n'
            'The admin must open the logger bot and send /start.\n'
            'Logs are grouped into one compact summary per cycle to avoid spam.',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('🔑 Set / Replace Token',callback_data='admin_log_bot_set',style='primary')],
                [InlineKeyboardButton('🗑️ Remove Logger',callback_data='admin_log_bot_remove',style='danger')],
                [InlineKeyboardButton('🔙 Admin Panel',callback_data='admin_panel',style='danger')]]),
            parse_mode=ParseMode.HTML); return
    if data == 'admin_log_bot_set':
        if uid != self.ADMIN_USER_ID: await q.answer('❌ Admin only',show_alert=True); return
        self.temp_data[uid]={'flow_type':'admin_log_bot_token'}
        await self._safe_edit_text(q,
            '🔑 <b>Set Mandatory Log Bot</b>\n\nSend the BotFather token.\n\n'
            '⚠️ Start that logger bot first with <code>/start</code>.',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Cancel',callback_data='admin_log_bot',style='danger')]]),
            parse_mode=ParseMode.HTML); return
    if data == 'admin_log_bot_remove':
        if uid != self.ADMIN_USER_ID: await q.answer('❌ Admin only',show_alert=True); return
        self.db.remove_mandatory_log_bot(); await q.answer('✅ Logger removed.',show_alert=True)
        await self._safe_edit_text(q,'🗑️ <b>Mandatory Log Bot removed.</b>\n\nAds are locked until a logger is configured.',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🔙 Admin Panel',callback_data='admin_panel',style='danger')]]),parse_mode=ParseMode.HTML); return
    if data == 'admin_premium_maintenance':
        if uid != self.ADMIN_USER_ID: await q.answer('❌ Admin only',show_alert=True); return
        enabled=not self.db.get_premium_maintenance(); self.db.set_premium_maintenance(enabled)
        await q.answer('Premium Maintenance '+('ON 🟢' if enabled else 'OFF 🔴'),show_alert=True)
        text,markup=await self._show_admin_panel(update,context)
        await self._safe_edit_text(q,text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN); return
    return await _original_callback(self, update, context, data)
TelegramBot._process_callback_async = _patched_callback

# Admin text flow for the mandatory logger token.
_original_handle_message = TelegramBot.handle_message
async def _patched_handle_message(self, update, context):
    uid=update.effective_user.id
    flow=self.temp_data.get(uid,{})
    if flow.get('flow_type') == 'admin_log_bot_token' and uid == self.ADMIN_USER_ID:
        ok,msg=await self.logging_bot_manager.configure_mandatory_log_bot(update.message.text.strip(), self.ADMIN_USER_ID)
        self.temp_data.pop(uid,None)
        await update.message.reply_text(msg,parse_mode=ParseMode.HTML,reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('📊 Log Bot Settings',callback_data='admin_log_bot')],
            [InlineKeyboardButton('🔐 Admin Panel',callback_data='admin_panel')]]))
        return
    return await _original_handle_message(self, update, context)
TelegramBot.handle_message = _patched_handle_message

# ------------------------------------------------------------------
# ADVANCED REAL-TIME CYCLE LOGGER
# One logger message is created at cycle start. Every DM/group result
# edits that SAME message, so the logger bot receives a live dashboard
# instead of one message per target.
# ------------------------------------------------------------------
async def _live_logger_send_log(self, user_id, success, group_name, message_link=None, error=None):
    """Admin-only individual delivery logger.

    Every delivery result is written as a separate message to the mandatory
    logger bot's configured admin chat. User accounts never receive these
    logger messages. The existing cycle counters/live logger remain intact.
    """
    try:
        cfg = self.db.get_mandatory_log_bot()
        if not cfg:
            return

        admin_id = int(self.db.get_setting("admin_user_id", "0") or 0)
        if not admin_id:
            admin_id = int(os.environ.get("ADMIN_USER_ID", "0") or 0)
        if not admin_id:
            return

        token = cfg.get("bot_token")
        if not token:
            return

        from telegram import Bot
        if token not in self.user_bots:
            self.user_bots[token] = Bot(token=token)
        logger_bot = self.user_bots[token]

        # Keep counters used by the existing realtime cycle dashboard.
        buffers = getattr(self, "_compact_buffers", None)
        if buffers is None:
            buffers = {}
            self._compact_buffers = buffers
        buf = buffers.setdefault(user_id, {
            "ok": 0, "fail": 0, "flood": 0,
            "group_ok": 0, "group_fail": 0,
            "dm_ok": 0, "dm_fail": 0,
            "last_error": None, "last_target": None,
        })

        name = str(group_name or "Unknown target")
        link = str(message_link or "")
        err = str(error or "Unknown error")
        is_dm = name.startswith("DM:") or "DM delivered" in link

        if success:
            buf["ok"] += 1
            buf["dm_ok" if is_dm else "group_ok"] += 1
            buf["last_target"] = name
            text = (
                "✅ <b>Ad Message Sent</b>\n\n"
                f"🎯 <b>Target:</b> {html.escape(name)}\n"
                f"{'💬 <b>Type:</b> DM' if is_dm else '👥 <b>Type:</b> Group'}\n"
            )
            if link:
                text += f"🔗 <b>Message:</b> {html.escape(link)}\n"
            text += f"📅 <b>Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        else:
            buf["fail"] += 1
            buf["dm_fail" if is_dm else "group_fail"] += 1
            buf["last_error"] = err[:220]
            buf["last_target"] = name
            if "flood" in err.lower() or "rate limit" in err.lower():
                buf["flood"] += 1
            text = (
                "❌ <b>Ad Message Failed</b>\n\n"
                f"🎯 <b>Target:</b> {html.escape(name)}\n"
                f"{'💬 <b>Type:</b> DM' if is_dm else '👥 <b>Type:</b> Group'}\n"
                f"⚠️ <b>Reason:</b> <code>{html.escape(err[:700])}</code>\n"
                f"📅 <b>Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )

        # Individual messages are deliberately sent ONLY to the admin logger.
        # No per-delivery log is sent to the advertising user.
        await logger_bot.send_message(
            chat_id=admin_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

        # Also keep the existing realtime single-message dashboard updated.
        try:
            await self.update_live_cycle_log(user_id)
        except Exception as exc:
            self.db.log_event("ERROR", f"Live logger dashboard update failed: {exc}")

    except Exception as exc:
        self.db.log_event("ERROR", f"Admin individual logger failed: {exc}")

LoggingBotManager.send_log = _live_logger_send_log

async def _begin_cycle_log(self, user_id, cycle_no, total_groups, total_dms):
    cfg = self.db.get_mandatory_log_bot()
    if not cfg:
        return
    try:
        from telegram import Bot
        token = cfg["bot_token"]
        if token not in self.user_bots:
            self.user_bots[token] = Bot(token=token)

        phone_row = self.db.fetch_one(
            "SELECT phone_number FROM userbot_session WHERE user_id=? AND is_active=1 LIMIT 1",
            (user_id,)
        )
        phone = phone_row[0] if phone_row and phone_row[0] else str(user_id)
        admin_id = int(self.db.get_setting("admin_user_id", "0") or 0)
        if not admin_id:
            admin_id = int(os.environ.get("ADMIN_USER_ID", "0") or 0)
        if not admin_id:
            raise RuntimeError("ADMIN_USER_ID is not configured")

        self._compact_buffers[user_id] = {
            "ok": 0, "fail": 0, "flood": 0,
            "group_ok": 0, "group_fail": 0,
            "dm_ok": 0, "dm_fail": 0,
            "last_error": None, "last_target": None,
        }

        text = (
            f"📊 <b>LIVE BROADCAST LOGGER</b> 🚀\n\n"
            f"📱 <b>Account:</b> <code>{html.escape(str(phone))}</code>\n"
            f"🔢 <b>Cycle:</b> #{cycle_no}\n"
            f"🟢 <b>Status:</b> <i>RUNNING</i>\n\n"
            f"👥 <b>Groups:</b> 0/{total_groups}\n"
            f"💬 <b>DMs:</b> 0/{total_dms}\n"
            f"🎯 <b>Total:</b> 0/{total_groups + total_dms}\n\n"
            f"✅ <b>Successful:</b> 0\n"
            f"❌ <b>Failed:</b> 0\n"
            f"⏳ <b>Flood Waits:</b> 0\n"
            f"💬 <b>Auto Replied:</b> 0\n\n"
            f"📡 <b>Last target:</b> <i>Waiting...</i>"
        )
        msg = await self.user_bots[token].send_message(
            chat_id=admin_id, text=text, parse_mode=ParseMode.HTML
        )
        if not hasattr(self, "_cycle_log_messages"):
            self._cycle_log_messages = {}
        self._cycle_log_messages[user_id] = {
            "message_id": msg.message_id, "cycle_no": cycle_no,
            "groups": total_groups, "dms": total_dms,
            "token": token, "admin_id": admin_id,
        }
    except Exception as e:
        self.db.log_event("ERROR", f"Live cycle logger start failed: {e}")

LoggingBotManager.begin_cycle_log = _begin_cycle_log

async def _update_live_cycle_log(self, user_id, force=False, status="running"):
    state = getattr(self, "_cycle_log_messages", {}).get(user_id)
    if not state:
        return
    buf = getattr(self, "_compact_buffers", {}).get(user_id, {})
    try:
        from telegram import Bot
        token = state["token"]
        if token not in self.user_bots:
            self.user_bots[token] = Bot(token=token)

        group_done = buf.get("group_ok", 0) + buf.get("group_fail", 0)
        dm_done = buf.get("dm_ok", 0) + buf.get("dm_fail", 0)
        done = buf.get("ok", 0) + buf.get("fail", 0)
        total = state["groups"] + state["dms"]
        last_target = html.escape(str(buf.get("last_target") or "Waiting..."))
        last_error = buf.get("last_error")
        error_line = (
            f"\n⚠️ <b>Last error:</b> <code>{html.escape(str(last_error))}</code>"
            if last_error else ""
        )
        text = (
            f"📊 <b>LIVE BROADCAST LOGGER</b> 🚀\n\n"
            f"🔢 <b>Cycle:</b> #{state['cycle_no']}\n"
            f"{'🟢' if status == 'running' else '🏁'} <b>Status:</b> <i>{html.escape(status.upper())}</i>\n\n"
            f"👥 <b>Groups:</b> {group_done}/{state['groups']}\n"
            f"💬 <b>DMs:</b> {dm_done}/{state['dms']}\n"
            f"🎯 <b>Total:</b> {done}/{total}\n\n"
            f"✅ <b>Successful:</b> {buf.get('ok', 0)}\n"
            f"❌ <b>Failed:</b> {buf.get('fail', 0)}\n"
            f"⏳ <b>Flood Waits:</b> {buf.get('flood', 0)}\n"
            f"💬 <b>Auto Replied:</b> 0\n\n"
            f"📡 <b>Last target:</b> <code>{last_target}</code>"
            f"{error_line}"
        )
        await self.user_bots[token].edit_message_text(
            chat_id=state["admin_id"], message_id=state["message_id"],
            text=text, parse_mode=ParseMode.HTML
        )
    except Exception as e:
        self.db.log_event("ERROR", f"Live cycle logger update failed: {e}")

LoggingBotManager.update_live_cycle_log = _update_live_cycle_log

async def _flush_compact_cycle_log(self, user_id, total_targets, cycle_no, total_groups=None, total_dms=None):
    buffers = getattr(self, "_compact_buffers", {})
    buf = buffers.get(user_id, {
        "ok": 0, "fail": 0, "flood": 0,
        "group_ok": 0, "group_fail": 0, "dm_ok": 0, "dm_fail": 0,
        "last_error": None, "last_target": None,
    })
    cfg = self.db.get_mandatory_log_bot()
    if not cfg:
        return
    try:
        tg = total_groups if total_groups is not None else buf.get("group_ok", 0) + buf.get("group_fail", 0)
        td = total_dms if total_dms is not None else buf.get("dm_ok", 0) + buf.get("dm_fail", 0)
        total = total_targets if total_targets is not None else tg + td
        status = "complete" if buf.get("fail", 0) == 0 else "incomplete"
        await self.update_live_cycle_log(user_id, force=True, status=status)

        # Keep the same message as the final cycle log.
        state = getattr(self, "_cycle_log_messages", {}).pop(user_id, None)
        if state:
            from telegram import Bot
            token = state["token"]
            if token not in self.user_bots:
                self.user_bots[token] = Bot(token=token)
            phone_row = self.db.fetch_one(
                "SELECT phone_number FROM userbot_session WHERE user_id=? AND is_active=1 LIMIT 1",
                (user_id,)
            )
            phone = phone_row[0] if phone_row and phone_row[0] else str(user_id)
            final_text = (
                f"📊 <b>BROADCAST CYCLE #{cycle_no} — FINAL LOG</b> ♻️\n\n"
                f"📱 <b>Account:</b> <code>{html.escape(str(phone))}</code>\n"
                f"{'✅' if status == 'complete' else '⚠️'} <b>Status:</b> <i>{status.upper()}</i>\n\n"
                f"👥 <b>Groups:</b> {tg}  |  ✅ {buf.get('group_ok',0)}  |  ❌ {buf.get('group_fail',0)}\n"
                f"💬 <b>DMs:</b> {td}  |  ✅ {buf.get('dm_ok',0)}  |  ❌ {buf.get('dm_fail',0)}\n"
                f"🎯 <b>Total Targets:</b> {total}\n\n"
                f"✅ <b>Successful:</b> {buf.get('ok',0)}\n"
                f"❌ <b>Failed:</b> {buf.get('fail',0)}\n"
                f"⏳ <b>Flood Waits:</b> {buf.get('flood',0)}\n"
                f"💬 <b>Auto Replied:</b> 0\n"
            )
            if buf.get("last_error"):
                final_text += f"\n⚠️ <b>Last error:</b> <code>{html.escape(str(buf['last_error']))}</code>\n"
            final_text += "\n🏁 <b>Broadcast cycle completed. Final logs updated ♻️</b>"
            await self.user_bots[token].edit_message_text(
                chat_id=state["admin_id"], message_id=state["message_id"],
                text=final_text, parse_mode=ParseMode.HTML
            )
        buffers.pop(user_id, None)
    except Exception as e:
        self.db.log_event("ERROR", f"Compact logger failed: {e}")

LoggingBotManager.flush_compact_cycle_log = _flush_compact_cycle_log


# ============================================================
# FINAL STABLE MULTI-USER RUN-ADS PATCH
# Applied BEFORE main() so the fixes are actually active at startup.
# ============================================================
from contextvars import ContextVar

_SYNX_CURRENT_USER = ContextVar("synax_current_user", default=None)

# ---------- Per-user UserbotManager ----------
_ORIGINAL_USERBOT_INIT = UserbotManager.__init__

def _userbot_init(self, database: Database):
    _ORIGINAL_USERBOT_INIT(self, database)
    uid = _SYNX_CURRENT_USER.get()
    self.owner_user_id = uid
    base_session = os.environ.get("ADBOT_SESSION", "userbot_session")
    # Keep the legacy/default session for the admin; every other account gets
    # its own Telethon session file so one user's login cannot replace another's.
    if uid is not None:
        try:
            admin_id = int(database.get_setting("admin_user_id", "0") or 0)
        except Exception:
            admin_id = 0
        if uid != admin_id:
            self.session_file = f"{base_session}_{uid}"

UserbotManager.__init__ = _userbot_init


def _ub_owner(self):
    return getattr(self, "owner_user_id", None) or _SYNX_CURRENT_USER.get()

async def _userbot_remove_scoped(self) -> bool:
    uid = _ub_owner(self)
    try:
        self.is_authenticated = False
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
        if uid is None:
            self.db.execute_query("DELETE FROM userbot_session")
            self.db.execute_query("DELETE FROM groups")
        else:
            self.db.execute_query("DELETE FROM userbot_session WHERE user_id = ?", (uid,))
            self.db.execute_query("DELETE FROM groups WHERE user_id = ?", (uid,))
        import glob
        for f in glob.glob(f"{self.session_file}*"):
            try:
                os.remove(f)
            except Exception:
                pass
        return True
    except Exception as e:
        self.db.log_event("ERROR", f"Scoped userbot removal failed for {uid}: {e}")
        return False

UserbotManager.remove_userbot = _userbot_remove_scoped

async def _userbot_restore_scoped(self):
    uid = _ub_owner(self)
    if uid is None:
        return await _ORIGINAL_USERBOT_RESTORE(self)
    row = self.db.fetch_one(
        "SELECT api_id, api_hash, phone_number, is_active, id FROM userbot_session "
        "WHERE user_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1", (uid,)
    )
    if not row:
        return
    api_id, api_hash, phone, active, row_id = row
    try:
        self.client = TelegramClient(self.session_file, api_id, api_hash)
        await self.client.connect()
        if await self.client.is_user_authorized():
            self.is_authenticated = True
            self.db.execute_query(
                "UPDATE userbot_session SET last_activity = ? WHERE id = ? AND user_id = ?",
                (datetime.now(), row_id, uid)
            )
            await self.start_monitoring()
        else:
            self.is_authenticated = False
    except Exception as e:
        self.is_authenticated = False
        self.client = None
        self.db.log_event("ERROR", f"Userbot restore failed for {uid}: {e}")

_ORIGINAL_USERBOT_RESTORE = UserbotManager.restore_session
UserbotManager.restore_session = _userbot_restore_scoped

async def _userbot_status_scoped(self) -> Dict:
    uid = _ub_owner(self)
    if not self.client or not self.is_authenticated:
        return {"status": "❌ Disconnected", "last_activity": "Never", "user_info": "Not authenticated"}
    try:
        me = await self.client.get_me()
        if uid is not None:
            row = self.db.fetch_one(
                "SELECT last_activity FROM userbot_session WHERE user_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
                (uid,)
            )
        else:
            row = self.db.fetch_one("SELECT last_activity FROM userbot_session WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
        return {
            "status": "✅ Connected",
            "last_activity": row[0] if row and row[0] else "Unknown",
            "user_info": f"@{me.username}" if getattr(me, "username", None) else (getattr(me, "first_name", "Unknown") or "Unknown")
        }
    except Exception as e:
        return {"status": "❌ Disconnected", "last_activity": "Unknown", "user_info": f"Error: {e}"}

UserbotManager.get_status = _userbot_status_scoped

# Fix the monitoring callback's legacy id=1/first-active assumptions.
_ORIGINAL_START_MONITORING = UserbotManager.start_monitoring
async def _userbot_monitoring_scoped(self):
    uid = _ub_owner(self)
    if uid is None:
        return await _ORIGINAL_START_MONITORING(self)
    if not self.client or not self.is_authenticated:
        return
    self.branding_task = asyncio.create_task(self._enforce_branding_protection())
    @self.client.on(events.NewMessage(incoming=True))
    async def handler(event):
        try:
            row = self.db.fetch_one(
                "SELECT id FROM userbot_session WHERE user_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
                (uid,)
            )
            if row:
                self.db.execute_query("UPDATE userbot_session SET last_activity = ? WHERE id = ?", (datetime.now(), row[0]))
        except Exception:
            pass
        if event.is_private and not event.out:
            message_text = event.message.message if event.message else ""
            if message_text and message_text.startswith('/'):
                return
            sender = await event.get_sender()
            if sender and getattr(sender, 'bot', False):
                return
            afk_enabled = self.db.get_user_setting(uid, "afk_enabled", "off")
            afk_message = self.db.get_user_setting(uid, "afk_message", "")
            sender_id = event.sender_id
            if afk_enabled == "on" and sender_id != uid and afk_message:
                last_reply_time = self.db.get_afk_last_reply_time(sender_id)
                now = datetime.now()
                if not last_reply_time or (now - last_reply_time).total_seconds() >= 7200:
                    await event.reply(afk_message)
                    self.db.set_afk_last_reply_time(sender_id, now)
UserbotManager.start_monitoring = _userbot_monitoring_scoped

# ---------- Per-user TelegramBot manager routing ----------
_ORIGINAL_TGB_INIT = TelegramBot.__init__

def _tgb_init(self, bot_token: str, admin_id: int):
    _ORIGINAL_TGB_INIT(self, bot_token, admin_id)
    self._admin_userbot_manager = self.userbot_manager
    self._admin_forwarding_manager = self.forwarding_manager
    self._userbot_managers = {admin_id: self._admin_userbot_manager}
    self._forwarding_managers = {admin_id: self._admin_forwarding_manager}
    # Remove shared mutable manager attributes. Properties below select the
    # manager from the current update context, making concurrent users safe.
    del self.userbot_manager
    del self.forwarding_manager


def _current_uid(self):
    return _SYNX_CURRENT_USER.get() or self.ADMIN_USER_ID

@property
def _dynamic_userbot_manager(self):
    uid = _current_uid(self)
    mgr = self._userbot_managers.get(uid)
    if mgr is None:
        token = _SYNX_CURRENT_USER.set(uid)
        try:
            mgr = UserbotManager(self.db)
        finally:
            _SYNX_CURRENT_USER.reset(token)
        mgr.owner_user_id = uid
        base_session = os.environ.get("ADBOT_SESSION", "userbot_session")
        if uid != self.ADMIN_USER_ID:
            mgr.session_file = f"{base_session}_{uid}"
        self._userbot_managers[uid] = mgr
    return mgr

@property
def _dynamic_forwarding_manager(self):
    uid = _current_uid(self)
    mgr = self._forwarding_managers.get(uid)
    if mgr is None:
        mgr = ForwardingManager(self.db, self.userbot_manager, self, uid, self.logging_bot_manager)
        self._forwarding_managers[uid] = mgr
    return mgr

TelegramBot.__init__ = _tgb_init
TelegramBot.userbot_manager = _dynamic_userbot_manager
TelegramBot.forwarding_manager = _dynamic_forwarding_manager

# ---------- Context is set before ANY user update is processed ----------
_ORIGINAL_SAFE_CALLBACK = TelegramBot._safe_process_callback_async
async def _safe_callback_with_user(self, update, context, data):
    token = _SYNX_CURRENT_USER.set(update.effective_user.id)
    try:
        return await _ORIGINAL_SAFE_CALLBACK(self, update, context, data)
    finally:
        _SYNX_CURRENT_USER.reset(token)
TelegramBot._safe_process_callback_async = _safe_callback_with_user

_ORIGINAL_HANDLE_MESSAGE = TelegramBot.handle_message
async def _handle_message_with_user(self, update, context):
    token = _SYNX_CURRENT_USER.set(update.effective_user.id)
    try:
        return await _ORIGINAL_HANDLE_MESSAGE(self, update, context)
    finally:
        _SYNX_CURRENT_USER.reset(token)
TelegramBot.handle_message = _handle_message_with_user

# ---------- Mandatory logger: start first, then ads ----------
async def _mandatory_logger_preflight(self, user_id):
    cfg = self.db.get_mandatory_log_bot()
    if not cfg or not cfg.get("bot_token"):
        return False, "📊 <b>Mandatory Log Bot is not configured.</b>\n\nAdmin must configure it first.", None
    token = cfg["bot_token"]
    username = (cfg.get("username") or "").lstrip("@")
    try:
        from telegram import Bot
        bot = self.logging_bot_manager.user_bots.get(token)
        if bot is None:
            bot = Bot(token=token)
            self.logging_bot_manager.user_bots[token] = bot
        await bot.get_chat(user_id)
        return True, "OK", None
    except Exception:
        link = f"https://t.me/{username}" if username else None
        msg = (
            "📊 <b>Start the Mandatory Log Bot first</b>\n\n"
            f"Open <b>@{html.escape(username or 'LogBot')}</b> and press <b>/start</b>.\n\n"
            "After that, tap <b>🔄 Check & Run Ads</b>."
        )
        return False, msg, link

async def _run_setup_screen(self, update, message, logger_link=None):
    buttons = []
    lower = message.lower()
    if "log bot" in lower or "logger" in lower:
        if logger_link:
            buttons.append([InlineKeyboardButton("📊 Start Log Bot ▶️", url=logger_link, style="primary")])
        buttons.append([InlineKeyboardButton("🔄 Check & Run Ads", callback_data="dashboard_run", style="success")])
    if "userbot" in lower or "account" in lower:
        buttons.append([InlineKeyboardButton("👤 Add / Manage Userbot", callback_data="dashboard_account", style="primary")])
    if not buttons:
        buttons.append([InlineKeyboardButton("👤 Add / Manage Userbot", callback_data="dashboard_account", style="primary")])
    buttons += [
        [InlineKeyboardButton("📢 Set Advertisement", callback_data="dashboard_ad", style="primary")],
        [InlineKeyboardButton("👥 Groups / DMs", callback_data="dashboard_interval", style="primary")],
        [InlineKeyboardButton("🔙 Back to Dashboard", callback_data="back_main", style="primary")]
    ]
    await self._safe_edit_text(update.callback_query, message, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.HTML)

async def _start_ads_fast(self, update, context):
    uid = update.effective_user.id
    mgr = self.forwarding_manager
    # 1) Userbot must exist for THIS user.
    row = self.db.fetch_one(
        "SELECT id, phone_number, is_active FROM userbot_session WHERE user_id = ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
        (uid,)
    )
    if not row:
        await _run_setup_screen(self, update, "👤 <b>Userbot account required</b>\n\nAdd and authenticate your Telegram account first. Ads cannot run without a userbot.")
        return
    if not self.userbot_manager.client or not self.userbot_manager.is_authenticated:
        try:
            await self.userbot_manager.restore_session()
        except Exception as e:
            self.db.log_event("ERROR", f"Userbot restore failed for {uid}: {e}")
    if not self.userbot_manager.client or not self.userbot_manager.is_authenticated:
        await _run_setup_screen(self, update, "❌ <b>Userbot is not connected.</b>\n\nOpen <b>Manage account</b> and reconnect it, then run Ads again.")
        return
    # 2) The admin-configured log bot must have been started by THIS user.
    ok, msg, link = await _mandatory_logger_preflight(self, uid)
    if not ok:
        await _run_setup_screen(self, update, msg, link)
        return
    # 3) Start immediately. No subscription/premium gate for free dashboard.
    success, message = await mgr.start_forwarding()
    if success:
        await update.callback_query.answer("🚀 Ads started", show_alert=False)
        await self.show_main_menu(update, context)
    else:
        await _run_setup_screen(self, update, f"❌ <b>Ads could not be started</b>\n\n{html.escape(str(message))}")

# One final callback router. It runs BEFORE the old subscription branch.
_PREVIOUS_PROCESS_CALLBACK = TelegramBot._process_callback_async
async def _process_callback_stable(self, update, context, data):
    uid = update.effective_user.id
    if data == "dashboard_run":
        if self.forwarding_manager.is_running:
            self.forwarding_manager.stop_forwarding()
            await update.callback_query.answer("⏹️ Ads stopped", show_alert=False)
            await self.show_main_menu(update, context)
        else:
            await _start_ads_fast(self, update, context)
        return
    if data == "dashboard_account":
        await self.show_userbot_menu(update, context)
        return
    if data in {"forwarding_start", "forwarding_stop", "forwarding_pause", "forwarding_resume"}:
        if data == "forwarding_start":
            await _start_ads_fast(self, update, context)
        elif data == "forwarding_stop":
            await self.stop_forwarding(update, context)
        elif data == "forwarding_pause":
            await self.pause_forwarding(update, context)
        else:
            await self.resume_forwarding(update, context)
        return
    return await _PREVIOUS_PROCESS_CALLBACK(self, update, context, data)
TelegramBot._process_callback_async = _process_callback_stable

# ---------- Free dashboard: never block normal users on subscription ----------
# The legacy callback authorization block is bypassed by routing normal dashboard
# callbacks above. Keep payment/admin functionality intact.

# ---------- Mandatory logger fallback: logs go to the user who ran the ad ----------
_ORIGINAL_SEND_LOG = LoggingBotManager.send_log
async def _send_log_user_only(self, user_id: int, success: bool, group_name: str, message_link: str = None, error: str = None):
    destinations = self.db.get_user_logging_destinations(user_id)
    if destinations:
        return await _ORIGINAL_SEND_LOG(self, user_id, success, group_name, message_link, error)
    cfg = self.db.get_mandatory_log_bot()
    if not cfg or not cfg.get("bot_token"):
        return await _ORIGINAL_SEND_LOG(self, user_id, success, group_name, message_link, error)
    try:
        from telegram import Bot
        token = cfg["bot_token"]
        bot = self.user_bots.get(token)
        if bot is None:
            bot = Bot(token=token)
            self.user_bots[token] = bot
        if success:
            text = f"✅ <b>Ad delivered</b>\n\n🎯 <b>Target:</b> {html.escape(str(group_name))}"
            if message_link:
                text += f"\n🔗 {html.escape(str(message_link))}"
        else:
            text = f"❌ <b>Ad failed</b>\n\n🎯 <b>Target:</b> {html.escape(str(group_name))}\n⚠️ <b>Error:</b> {html.escape(str(error or 'Unknown error'))}"
        text += f"\n🕒 <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        await bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return True
    except Exception as e:
        self.db.log_event("ERROR", f"User-only mandatory logger failed for {user_id}: {e}")
        return False
LoggingBotManager.send_log = _send_log_user_only

# The existing main() is intentionally kept below this patch so every fix is
# installed before TelegramBot is instantiated.

if __name__ == "__main__":
    show_banner()

    # 1. Create database connection
    db = Database()
    old_token = db.get_setting("bot_token", "BOT_TOKEN_HERE")
    old_admin = db.get_setting("admin_user_id", "8363262755")
    old_duration = db.get_setting("subscription_duration", "")

    # Get configuration from environment variables or database
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "8974937786:AAG3ryVN-VD1338K2LgC7wUW3unKBCHiAhc").strip() or old_token
    admin_id = os.environ.get("ADMIN_USER_ID", "7100478654").strip() or old_admin
    sub_minutes = os.environ.get("SUBSCRIPTION_MINUTES", "").strip() or old_duration

    # Validate required settings
    import sys
    if not bot_token:
        print("ERROR: BOT_TOKEN is required. Set it as a secret in Replit or environment variable.")
        sys.exit(1)
    if not admin_id:
        print("ERROR: ADMIN_USER_ID is required. Set it as a secret in Replit or environment variable.")
        sys.exit(1)
    if not sub_minutes:
        print("[INFO] SUBSCRIPTION_MINUTES not set. Using default of 43200 minutes (30 days).")
        sub_minutes = "43200"

    # 3. Save everything in the database
    db.set_setting("bot_token", bot_token)
    db.set_setting("admin_user_id", admin_id)
    db.set_setting("subscription_duration", sub_minutes)
    db.set_setting("subscription_start", datetime.now().isoformat())

    print(f"[Config] Bot Token: {bot_token[:10]}... (hidden)")
    print(f"[Config] Admin User ID: {admin_id}")
    print(f"[Config] Subscription Duration: {sub_minutes} minutes")

    # 4. Start bot with retry logic for stability
    max_retries = 10
    retry_delay = 30
    
    for attempt in range(max_retries):
        bot = TelegramBot(bot_token=bot_token, admin_id=int(admin_id))
        try:
            print(f"[Startup] Attempt {attempt + 1}/{max_retries}")
            bot.start_bot()
            break
        except KeyboardInterrupt:
            print("Bot stopped by user.")
            break
        except Exception as e:
            print(f"[Error] Bot crashed: {e}")
            if attempt < max_retries - 1:
                print(f"[Retry] Restarting in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 300)
            else:
                print("[Error] Max retries reached. Bot stopped.")
