import sqlite3
import os
import json
from datetime import datetime

DB_PATH = os.getenv("DATABASE_URL", "zyren_database.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Configuration des serveurs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                log_channel_id INTEGER DEFAULT 0,
                announcement_channel_id INTEGER DEFAULT 0,
                ticket_channel_id INTEGER DEFAULT 0,
                admin_role_id INTEGER DEFAULT 0,
                lia_enabled INTEGER DEFAULT 1,
                social_tiktok TEXT DEFAULT '',
                social_youtube TEXT DEFAULT '',
                social_instagram TEXT DEFAULT '',
                social_discord TEXT DEFAULT '',
                social_website TEXT DEFAULT ''
            )
        ''')

        # Niveaux utilisateurs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_levels (
                guild_id INTEGER,
                user_id INTEGER,
                level INTEGER DEFAULT 0,
                is_premium INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')

        # Commandes verrouillées par serveur
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS locked_commands (
                guild_id INTEGER,
                command_name TEXT,
                unlocked INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, command_name)
            )
        ''')

        # Codes Redeem
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                guild_id INTEGER,
                max_uses INTEGER,
                current_uses INTEGER DEFAULT 0,
                expires_at TEXT,
                unlock_type TEXT, -- 'level', 'command', 'premium'
                unlock_value TEXT, -- niveau (0-3), nom commande, ou '1' pour premium
                is_active INTEGER DEFAULT 1
            )
        ''')

        # Historique d'utilisation Redeem
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS redeem_history (
                code TEXT,
                guild_id INTEGER,
                user_id INTEGER,
                used_at TEXT,
                PRIMARY KEY (code, guild_id, user_id)
            )
        ''')
        
        # Logs des sanctions
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mod_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                moderator_id INTEGER,
                action TEXT,
                reason TEXT,
                timestamp TEXT
            )
        ''')
        conn.commit()

# --- Helpers DB ---

def get_guild_config(guild_id: int):
    with get_connection() as conn:
        res = conn.execute("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)).fetchone()
        if not res:
            conn.execute("INSERT INTO guild_config (guild_id) VALUES (?)", (guild_id,))
            conn.commit()
            res = conn.execute("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)).fetchone()
        return dict(res)

def update_guild_config(guild_id: int, key: str, value):
    with get_connection() as conn:
        conn.execute(f"UPDATE guild_config SET {key} = ? WHERE guild_id = ?", (value, guild_id))
        conn.commit()

def get_user_perm(guild_id: int, user_id: int):
    with get_connection() as conn:
        res = conn.execute("SELECT level, is_premium FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
        if not res:
            return {"level": 0, "is_premium": 0}
        return dict(res)

def set_user_level(guild_id: int, user_id: int, level: int = None, is_premium: int = None):
    curr = get_user_perm(guild_id, user_id)
    new_lvl = level if level is not None else curr["level"]
    new_prem = is_premium if is_premium is not None else curr["is_premium"]
    with get_connection() as conn:
        conn.execute('''
            INSERT INTO user_levels (guild_id, user_id, level, is_premium) 
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET level=?, is_premium=?
        ''', (guild_id, user_id, new_lvl, new_prem, new_lvl, new_prem))
        conn.commit()

def is_cmd_unlocked(guild_id: int, cmd_name: str) -> bool:
    with get_connection() as conn:
        res = conn.execute("SELECT unlocked FROM locked_commands WHERE guild_id = ? AND command_name = ?", (guild_id, cmd_name)).fetchone()
        return bool(res["unlocked"]) if res else False

def set_cmd_unlock(guild_id: int, cmd_name: str, status: bool):
    with get_connection() as conn:
        conn.execute('''
            INSERT INTO locked_commands (guild_id, command_name, unlocked) 
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, command_name) DO UPDATE SET unlocked=?
        ''', (guild_id, cmd_name, int(status), int(status)))
        conn.commit()
