#!/usr/bin/env python3
"""
FORZEOS Enhanced - Complete GUI Operating System v7.0
A full-featured desktop operating system written in Python with tkinter
Optimized for Android/Pydroid 3 with mobile-friendly interface

Enhanced Features:
- Fixed wallpaper system with proper PIL image handling
- Chess bot with minimax algorithm
- 20+ new applications and tools
- Multi-language support (TR, EN, AR, AZ, RU)
- Theme engine with customizable colors
- Widget system for desktop
- Plugin support
- Session management
- Notification system
- And much more...
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, colorchooser
import os
import sys
import json
import hashlib
import datetime
import threading
import subprocess
import webbrowser
import urllib.request
import socket
import random
import math
import shutil
import sqlite3
import zipfile
import base64
import io
import time
import copy

# Advanced features imports with fallbacks
try:
    import fitz  # PyMuPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    from PIL import Image, ImageTk, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pygame
    PYGAME_AVAILABLE = True
    pygame.mixer.init()
except ImportError:
    PYGAME_AVAILABLE = False

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import qrcode
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Language translations
TRANSLATIONS = {
    'EN': {
        'welcome': 'Welcome to FORZEOS',
        'login': 'Login',
        'username': 'Username',
        'password': 'Password',
        'settings': 'Settings',
        'file_manager': 'File Manager',
        'calculator': 'Calculator',
        'notepad': 'Notepad',
        'terminal': 'Terminal',
        'paint': 'Paint',
        'games': 'Games',
        'tools': 'Tools',
        'logout': 'Logout',
        'shutdown': 'Shutdown',
        'error': 'Error',
        'success': 'Success',
        'cancel': 'Cancel',
        'ok': 'OK',
        'save': 'Save',
        'open': 'Open',
        'new': 'New',
        'delete': 'Delete',
        'copy': 'Copy',
        'paste': 'Paste',
        'cut': 'Cut'
    },
    'TR': {
        'welcome': 'FORZEOS\'a Hoşgeldiniz',
        'login': 'Giriş',
        'username': 'Kullanıcı Adı',
        'password': 'Şifre',
        'settings': 'Ayarlar',
        'file_manager': 'Dosya Yöneticisi',
        'calculator': 'Hesap Makinesi',
        'notepad': 'Not Defteri',
        'terminal': 'Terminal',
        'paint': 'Boyama',
        'games': 'Oyunlar',
        'tools': 'Araçlar',
        'logout': 'Çıkış',
        'shutdown': 'Kapat',
        'error': 'Hata',
        'success': 'Başarılı',
        'cancel': 'İptal',
        'ok': 'Tamam',
        'save': 'Kaydet',
        'open': 'Aç',
        'new': 'Yeni',
        'delete': 'Sil',
        'copy': 'Kopyala',
        'paste': 'Yapıştır',
        'cut': 'Kes'
    },
    'AR': {
        'welcome': 'مرحباً بك في FORZEOS',
        'login': 'تسجيل الدخول',
        'username': 'اسم المستخدم',
        'password': 'كلمة المرور',
        'settings': 'الإعدادات',
        'file_manager': 'مدير الملفات',
        'calculator': 'الآلة الحاسبة',
        'notepad': 'دفتر الملاحظات',
        'terminal': 'الطرفية',
        'paint': 'الرسام',
        'games': 'الألعاب',
        'tools': 'الأدوات',
        'logout': 'تسجيل الخروج',
        'shutdown': 'إغلاق',
        'error': 'خطأ',
        'success': 'نجح',
        'cancel': 'إلغاء',
        'ok': 'موافق',
        'save': 'حفظ',
        'open': 'فتح',
        'new': 'جديد',
        'delete': 'حذف',
        'copy': 'نسخ',
        'paste': 'لصق',
        'cut': 'قص'
    }
}

class NotificationSystem:
    """System notification manager"""
    def __init__(self, parent):
        self.parent = parent
        self.notifications = []
        
    def show_notification(self, title, message, duration=3000, type="info"):
        """Show a notification popup"""
        try:
            notification = tk.Toplevel(self.parent)
            notification.title(title)
            notification.geometry("300x80")
            notification.resizable(False, False)
            
            # Position at top-right
            x = notification.winfo_screenwidth() - 320
            y = 20 + len(self.notifications) * 90
            notification.geometry(f"300x80+{x}+{y}")
            
            # Style based on type
            colors = {
                'info': '#3498DB',
                'success': '#27AE60',
                'warning': '#F39C12',
                'error': '#E74C3C'
            }
            
            bg_color = colors.get(type, '#3498DB')
            notification.configure(bg=bg_color)
            
            # Content
            tk.Label(notification, text=title, bg=bg_color, fg='white',
                    font=('Arial', 12, 'bold')).pack(pady=5)
            tk.Label(notification, text=message, bg=bg_color, fg='white',
                    font=('Arial', 10), wraplength=280).pack()
            
            # Auto-close
            notification.after(duration, notification.destroy)
            self.notifications.append(notification)
            
            # Remove from list when destroyed
            def on_destroy():
                if notification in self.notifications:
                    self.notifications.remove(notification)
            notification.bind('<Destroy>', lambda e: on_destroy())
            
        except Exception as e:
            print(f"Notification error: {e}")

class ChessBot:
    """Minimax algorithm chess bot"""
    def __init__(self, depth=3):
        self.depth = depth
        self.piece_values = {
            'pawn': 1, 'knight': 3, 'bishop': 3,
            'rook': 5, 'queen': 9, 'king': 100
        }
    
    def evaluate_board(self, board):
        """Simple board evaluation"""
        score = 0
        for i in range(8):
            for j in range(8):
                piece = board[i][j]
                if piece:
                    value = self.piece_values.get(piece.lower(), 0)
                    if piece.isupper():  # White pieces
                        score += value
                    else:  # Black pieces
                        score -= value
        return score
    
    def minimax(self, board, depth, maximizing_player, alpha=-float('inf'), beta=float('inf')):
        """Minimax algorithm with alpha-beta pruning"""
        if depth == 0:
            return self.evaluate_board(board)
        
        if maximizing_player:
            max_eval = -float('inf')
            for move in self.get_all_moves(board, True):
                new_board = self.make_move(board, move)
                eval_score = self.minimax(new_board, depth-1, False, alpha, beta)
                max_eval = max(max_eval, eval_score)
                alpha = max(alpha, eval_score)
                if beta <= alpha:
                    break
            return max_eval
        else:
            min_eval = float('inf')
            for move in self.get_all_moves(board, False):
                new_board = self.make_move(board, move)
                eval_score = self.minimax(new_board, depth-1, True, alpha, beta)
                min_eval = min(min_eval, eval_score)
                beta = min(beta, eval_score)
                if beta <= alpha:
                    break
            return min_eval
    
    def get_best_move(self, board, is_white):
        """Get the best move for the current player"""
        best_move = None
        best_value = -float('inf') if is_white else float('inf')
        
        for move in self.get_all_moves(board, is_white):
            new_board = self.make_move(board, move)
            move_value = self.minimax(new_board, self.depth-1, not is_white)
            
            if is_white and move_value > best_value:
                best_value = move_value
                best_move = move
            elif not is_white and move_value < best_value:
                best_value = move_value
                best_move = move
        
        return best_move
    
    def get_all_moves(self, board, is_white):
        """Get all possible moves for the current player"""
        moves = []
        for i in range(8):
            for j in range(8):
                piece = board[i][j]
                if piece and ((is_white and piece.isupper()) or (not is_white and piece.islower())):
                    moves.extend(self.get_piece_moves(board, i, j))
        return moves
    
    def get_piece_moves(self, board, row, col):
        """Get possible moves for a piece at given position"""
        piece = board[row][col].lower()
        moves = []
        
        if piece == 'pawn':
            moves = self.get_pawn_moves(board, row, col)
        elif piece == 'rook':
            moves = self.get_rook_moves(board, row, col)
        elif piece == 'knight':
            moves = self.get_knight_moves(board, row, col)
        elif piece == 'bishop':
            moves = self.get_bishop_moves(board, row, col)
        elif piece == 'queen':
            moves = self.get_queen_moves(board, row, col)
        elif piece == 'king':
            moves = self.get_king_moves(board, row, col)
        
        return moves
    
    def get_pawn_moves(self, board, row, col):
        """Get pawn moves"""
        moves = []
        piece = board[row][col]
        is_white = piece.isupper()
        direction = -1 if is_white else 1
        
        # Forward move
        new_row = row + direction
        if 0 <= new_row < 8 and not board[new_row][col]:
            moves.append((row, col, new_row, col))
            
            # Double move from starting position
            if (is_white and row == 6) or (not is_white and row == 1):
                if not board[new_row + direction][col]:
                    moves.append((row, col, new_row + direction, col))
        
        # Captures
        for dc in [-1, 1]:
            new_col = col + dc
            if 0 <= new_row < 8 and 0 <= new_col < 8:
                target = board[new_row][new_col]
                if target and ((is_white and target.islower()) or (not is_white and target.isupper())):
                    moves.append((row, col, new_row, new_col))
        
        return moves
    
    def get_rook_moves(self, board, row, col):
        """Get rook moves"""
        moves = []
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        
        for dr, dc in directions:
            for i in range(1, 8):
                new_row, new_col = row + dr * i, col + dc * i
                if not (0 <= new_row < 8 and 0 <= new_col < 8):
                    break
                
                target = board[new_row][new_col]
                if not target:
                    moves.append((row, col, new_row, new_col))
                else:
                    if self.is_enemy_piece(board[row][col], target):
                        moves.append((row, col, new_row, new_col))
                    break
        
        return moves
    
    def get_knight_moves(self, board, row, col):
        """Get knight moves"""
        moves = []
        knight_moves = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
        
        for dr, dc in knight_moves:
            new_row, new_col = row + dr, col + dc
            if 0 <= new_row < 8 and 0 <= new_col < 8:
                target = board[new_row][new_col]
                if not target or self.is_enemy_piece(board[row][col], target):
                    moves.append((row, col, new_row, new_col))
        
        return moves
    
    def get_bishop_moves(self, board, row, col):
        """Get bishop moves"""
        moves = []
        directions = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        
        for dr, dc in directions:
            for i in range(1, 8):
                new_row, new_col = row + dr * i, col + dc * i
                if not (0 <= new_row < 8 and 0 <= new_col < 8):
                    break
                
                target = board[new_row][new_col]
                if not target:
                    moves.append((row, col, new_row, new_col))
                else:
                    if self.is_enemy_piece(board[row][col], target):
                        moves.append((row, col, new_row, new_col))
                    break
        
        return moves
    
    def get_queen_moves(self, board, row, col):
        """Get queen moves (combination of rook and bishop)"""
        return self.get_rook_moves(board, row, col) + self.get_bishop_moves(board, row, col)
    
    def get_king_moves(self, board, row, col):
        """Get king moves"""
        moves = []
        directions = [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]
        
        for dr, dc in directions:
            new_row, new_col = row + dr, col + dc
            if 0 <= new_row < 8 and 0 <= new_col < 8:
                target = board[new_row][new_col]
                if not target or self.is_enemy_piece(board[row][col], target):
                    moves.append((row, col, new_row, new_col))
        
        return moves
    
    def is_enemy_piece(self, piece1, piece2):
        """Check if two pieces are enemies"""
        return (piece1.isupper() and piece2.islower()) or (piece1.islower() and piece2.isupper())
    
    def make_move(self, board, move):
        """Make a move on the board (returns new board)"""
        new_board = [row[:] for row in board]
        from_row, from_col, to_row, to_col = move
        new_board[to_row][to_col] = new_board[from_row][from_col]
        new_board[from_row][from_col] = None
        return new_board

class DatabaseManager:
    """SQLite database manager for system data"""
    def __init__(self, db_path="forzeos.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # System logs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user TEXT NOT NULL,
                    action TEXT NOT NULL,
                    details TEXT,
                    app TEXT
                )
            ''')
            
            # Password vault table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS password_vault (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user TEXT NOT NULL,
                    title TEXT NOT NULL,
                    username TEXT,
                    password TEXT NOT NULL,
                    notes TEXT,
                    category TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # Notes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS secure_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            # App store table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS app_store (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    version TEXT,
                    download_url TEXT,
                    icon_url TEXT,
                    category TEXT,
                    rating REAL,
                    downloads INTEGER
                )
            ''')
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Database initialization error: {e}")
    
    def log_action(self, user, action, details="", app="System"):
        """Log system action"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            timestamp = datetime.datetime.now().isoformat()
            cursor.execute('''
                INSERT INTO system_logs (timestamp, user, action, details, app)
                VALUES (?, ?, ?, ?, ?)
            ''', (timestamp, user, action, details, app))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Logging error: {e}")
    
    def get_logs(self, user=None, limit=100):
        """Get system logs"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            if user:
                cursor.execute('''
                    SELECT * FROM system_logs WHERE user = ? 
                    ORDER BY timestamp DESC LIMIT ?
                ''', (user, limit))
            else:
                cursor.execute('''
                    SELECT * FROM system_logs 
                    ORDER BY timestamp DESC LIMIT ?
                ''', (limit,))
            logs = cursor.fetchall()
            conn.close()
            return logs
        except Exception as e:
            print(f"Get logs error: {e}")
            return []

class ForzeOS:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FORZEOS Enhanced - Advanced Desktop OS v7.0")
        
        # Get screen dimensions
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        
        # Detect orientation
        self.is_horizontal = self.screen_width > self.screen_height
        
        # Try fullscreen mode
        try:
            self.root.attributes('-fullscreen', True)
        except:
            self.root.geometry(f"{self.screen_width}x{self.screen_height}")
        
        # System variables
        self.current_user = None
        self.current_language = 'EN'
        self.running_apps = {}
        self.windows = {}
        self.desktop_icons = []
        self.widgets = []
        self.plugins = []
        self.open_sessions = {}
        
        # File paths
        self.config_file = "forzeos_config_v7.json"
        self.file_system_root = "forze_users"
        self.plugins_dir = "forze_plugins"
        self.themes_dir = "forze_themes"
        
        # Initialize systems
        self.notification_system = NotificationSystem(self.root)
        self.db = DatabaseManager()
        self.chess_bot = ChessBot()
        
        # Color schemes and themes
        self.themes = {
            'dark': {
                'bg': '#2C3E50',
                'fg': '#ECF0F1',
                'accent': '#3498DB',
                'success': '#27AE60',
                'warning': '#F39C12',
                'danger': '#E74C3C',
                'dark': '#34495E',
                'light': '#BDC3C7'
            },
            'light': {
                'bg': '#ECF0F1',
                'fg': '#2C3E50',
                'accent': '#3498DB',
                'success': '#27AE60',
                'warning': '#F39C12',
                'danger': '#E74C3C',
                'dark': '#BDC3C7',
                'light': '#FFFFFF'
            },
            'blue': {
                'bg': '#1E3A8A',
                'fg': '#F1F5F9',
                'accent': '#3B82F6',
                'success': '#10B981',
                'warning': '#F59E0B',
                'danger': '#EF4444',
                'dark': '#1E40AF',
                'light': '#DBEAFE'
            }
        }
        
        self.current_theme = 'dark'
        self.colors = self.themes[self.current_theme]
        
        # Initialize system
        self.init_file_system()
        self.load_config()
        
        # Show login first
        self.root.withdraw()
        self.show_login()
        
    def init_file_system(self):
        """Initialize the file system structure"""
        directories = [
            self.file_system_root,
            self.plugins_dir,
            self.themes_dir,
            os.path.join(self.file_system_root, "shared"),
            os.path.join(self.file_system_root, "shared", "documents"),
            os.path.join(self.file_system_root, "shared", "images"),
            os.path.join(self.file_system_root, "shared", "music"),
            os.path.join(self.file_system_root, "shared", "videos"),
            os.path.join(self.file_system_root, "shared", "downloads")
        ]
        
        for directory in directories:
            if not os.path.exists(directory):
                os.makedirs(directory)
        
    def get_text(self, key):
        """Get translated text"""
        return TRANSLATIONS.get(self.current_language, TRANSLATIONS['EN']).get(key, key)
    
    def change_language(self, lang):
        """Change system language"""
        if lang in TRANSLATIONS:
            self.current_language = lang
            self.config['settings']['language'] = lang
            self.save_config()
            self.notification_system.show_notification(
                "Language Changed", 
                f"Language changed to {lang}", 
                type="success"
            )
    
    def change_theme(self, theme_name):
        """Change system theme"""
        if theme_name in self.themes:
            self.current_theme = theme_name
            self.colors = self.themes[theme_name]
            self.config['settings']['theme'] = theme_name
            self.save_config()
            self.update_theme()
            self.notification_system.show_notification(
                "Theme Changed", 
                f"Theme changed to {theme_name}", 
                type="success"
            )
    
    def update_theme(self):
        """Update all UI elements with new theme"""
        try:
            # Update root window
            self.root.configure(bg=self.colors['bg'])
            
            # Update desktop
            if hasattr(self, 'desktop'):
                self.desktop.configure(bg=self.colors['bg'])
            
            # Update taskbar
            if hasattr(self, 'taskbar'):
                self.taskbar.configure(bg=self.colors['dark'])
                self.forze_btn.configure(bg=self.colors['accent'])
                self.system_label.configure(bg=self.colors['dark'], fg=self.colors['fg'])
                self.clock_label.configure(bg=self.colors['dark'], fg=self.colors['fg'])
            
            # Update desktop icons
            for icon in self.desktop_icons:
                icon.configure(bg=self.colors['light'])
                for child in icon.winfo_children():
                    if isinstance(child, tk.Button):
                        child.configure(bg=self.colors['light'])
        except Exception as e:
            print(f"Theme update error: {e}")
    
    def load_config(self):
        """Load system configuration"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            except Exception as e:
                self.config = self.get_default_config()
        else:
            self.config = self.get_default_config()
            self.save_config()
        
        # Apply loaded settings
        self.current_language = self.config.get('settings', {}).get('language', 'EN')
        theme_name = self.config.get('settings', {}).get('theme', 'dark')
        if theme_name in self.themes:
            self.current_theme = theme_name
            self.colors = self.themes[theme_name]
        
    def get_default_config(self):
        """Get default system configuration"""
        return {
            'users': {
                'admin': {
                    'password': hashlib.md5('Forze esp32'.encode()).hexdigest(),
                    'created': datetime.datetime.now().isoformat(),
                    'last_login': None,
                    'settings': {
                        'wallpaper': None,
                        'icon_size': 'medium',
                        'startup_apps': []
                    }
                }
            },
            'settings': {
                'language': 'EN',
                'theme': 'dark',
                'wallpaper_color': '#2C3E50',
                'wallpaper_image': None,
                'taskbar_position': 'bottom',
                'auto_login': False,
                'session_timeout': 0,
                'enable_notifications': True,
                'enable_sounds': True,
                'icon_arrangement': 'auto',
                'widget_enabled': True
            },
            'desktop_layout': {
                'icon_positions': {},
                'widgets': [],
                'icon_size': 'medium'
            },
            'plugins': {
                'enabled': [],
                'available': []
            }
        }
    
    def save_config(self):
        """Save system configuration"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Config save error: {e}")
    
    def save_session(self):
        """Save current session state"""
        try:
            session_data = {
                'user': self.current_user,
                'timestamp': datetime.datetime.now().isoformat(),
                'running_apps': list(self.running_apps.keys()),
                'desktop_state': {
                    'icon_positions': self.config.get('desktop_layout', {}).get('icon_positions', {}),
                    'widgets': []
                }
            }
            
            session_file = f"session_{self.current_user}.json"
            with open(session_file, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2)
                
        except Exception as e:
            print(f"Session save error: {e}")
    
    def restore_session(self):
        """Restore previous session"""
        try:
            session_file = f"session_{self.current_user}.json"
            if os.path.exists(session_file):
                with open(session_file, 'r', encoding='utf-8') as f:
                    session_data = json.load(f)
                
                # Restore running apps
                for app_name in session_data.get('running_apps', []):
                    if hasattr(self, f'open_{app_name.lower().replace(" ", "_")}'):
                        threading.Thread(
                            target=getattr(self, f'open_{app_name.lower().replace(" ", "_")}'),
                            daemon=True
                        ).start()
                
                self.notification_system.show_notification(
                    "Session Restored", 
                    "Previous session has been restored", 
                    type="success"
                )
        except Exception as e:
            print(f"Session restore error: {e}")
    
    def show_login(self):
        """Show enhanced login screen"""
        self.login_window = tk.Toplevel()
        self.login_window.title("FORZEOS Enhanced Login")
        self.login_window.geometry("450x400")
        self.login_window.configure(bg=self.colors['bg'])
        self.login_window.resizable(False, False)
        
        # Center the login window
        x = (self.screen_width - 450) // 2
        y = (self.screen_height - 400) // 2
        self.login_window.geometry(f"450x400+{x}+{y}")
        
        # Main container
        main_frame = tk.Frame(self.login_window, bg=self.colors['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Logo/Title
        title_frame = tk.Frame(main_frame, bg=self.colors['bg'])
        title_frame.pack(pady=20)
        
        tk.Label(title_frame, text="FORZEOS", font=('Arial', 28, 'bold'),
                bg=self.colors['bg'], fg=self.colors['accent']).pack()
        tk.Label(title_frame, text="Enhanced v7.0", font=('Arial', 12),
                bg=self.colors['bg'], fg=self.colors['fg']).pack()
        
        # Login form
        form_frame = tk.Frame(main_frame, bg=self.colors['bg'])
        form_frame.pack(pady=20, fill=tk.X)
        
        # Username
        tk.Label(form_frame, text=self.get_text('username') + ":", 
                bg=self.colors['bg'], fg=self.colors['fg'],
                font=('Arial', 12)).pack(anchor=tk.W, pady=(0, 5))
        self.username_entry = tk.Entry(form_frame, font=('Arial', 14), width=25)
        self.username_entry.pack(fill=tk.X, pady=(0, 15))
        self.username_entry.insert(0, "admin")
        
        # Password
        tk.Label(form_frame, text=self.get_text('password') + ":", 
                bg=self.colors['bg'], fg=self.colors['fg'],
                font=('Arial', 12)).pack(anchor=tk.W, pady=(0, 5))
        self.password_entry = tk.Entry(form_frame, show='*', font=('Arial', 14), width=25)
        self.password_entry.pack(fill=tk.X, pady=(0, 20))
        
        # Buttons
        button_frame = tk.Frame(form_frame, bg=self.colors['bg'])
        button_frame.pack(fill=tk.X)
        
        login_btn = tk.Button(button_frame, text=self.get_text('login'), command=self.login,
                             bg=self.colors['accent'], fg='white', font=('Arial', 14, 'bold'),
                             width=15, height=2, relief=tk.FLAT)
        login_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Language selector
        lang_frame = tk.Frame(main_frame, bg=self.colors['bg'])
        lang_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        
        tk.Label(lang_frame, text="Language:", bg=self.colors['bg'], 
                fg=self.colors['fg'], font=('Arial', 10)).pack(side=tk.LEFT)
        
        self.lang_var = tk.StringVar(value=self.current_language)
        lang_menu = ttk.Combobox(lang_frame, textvariable=self.lang_var, 
                                values=['EN', 'TR', 'AR', 'AZ', 'RU'],
                                state='readonly', width=10)
        lang_menu.pack(side=tk.LEFT, padx=10)
        lang_menu.bind('<<ComboboxSelected>>', 
                      lambda e: self.change_language(self.lang_var.get()))
        
        # Bind Enter key
        self.login_window.bind('<Return>', lambda e: self.login())
        self.password_entry.focus()
        
    def login(self):
        """Handle user login with enhanced features"""
        try:
            username = self.username_entry.get().strip()
            password = self.password_entry.get()
            
            if not username or not password:
                messagebox.showerror(self.get_text('error'), 
                                   "Please enter both username and password")
                return
            
            # Check credentials
            if username in self.config['users']:
                stored_password = self.config['users'][username]['password']
                entered_password = hashlib.md5(password.encode()).hexdigest()
                
                if stored_password == entered_password:
                    self.current_user = username
                    
                    # Update last login
                    self.config['users'][username]['last_login'] = datetime.datetime.now().isoformat()
                    self.save_config()
                    
                    # Log login
                    self.db.log_action(username, "Login", "User logged in successfully")
                    
                    # Close login window
                    self.login_window.destroy()
                    
                    # Create desktop
                    self.create_desktop()
                    self.root.deiconify()
                    
                    # Welcome notification
                    self.notification_system.show_notification(
                        self.get_text('welcome'),
                        f"Welcome back, {username}!",
                        type="success"
                    )
                    
                    # Restore session if available
                    if self.config.get('settings', {}).get('restore_session', True):
                        threading.Thread(target=self.restore_session, daemon=True).start()
                        
                else:
                    messagebox.showerror(self.get_text('error'), "Invalid password")
                    self.db.log_action(username, "Failed Login", "Invalid password attempt")
            else:
                # Create new user
                response = messagebox.askyesno("New User", 
                                            f"User '{username}' not found. Create new user?")
                if response:
                    self.create_new_user(username, password)
                    
        except Exception as e:
            print(f"Login error: {e}")
            messagebox.showerror(self.get_text('error'), "Login failed")
    
    def create_new_user(self, username, password):
        """Create a new user account"""
        try:
            # Create user directory
            user_dir = os.path.join(self.file_system_root, username)
            if not os.path.exists(user_dir):
                os.makedirs(user_dir)
                os.makedirs(os.path.join(user_dir, "documents"))
                os.makedirs(os.path.join(user_dir, "images"))
                os.makedirs(os.path.join(user_dir, "downloads"))
            
            # Add to config
            self.config['users'][username] = {
                'password': hashlib.md5(password.encode()).hexdigest(),
                'created': datetime.datetime.now().isoformat(),
                'last_login': None,
                'settings': {
                    'wallpaper': None,
                    'icon_size': 'medium',
                    'startup_apps': []
                }
            }
            
            self.save_config()
            self.db.log_action(username, "Account Created", "New user account created")
            
            messagebox.showinfo("Success", f"User '{username}' created successfully!")
            
        except Exception as e:
            print(f"User creation error: {e}")
            messagebox.showerror(self.get_text('error'), "Failed to create user")
    
    def create_desktop(self):
        """Create the enhanced desktop environment"""
        # Configure main window
        wallpaper_color = self.config.get('settings', {}).get('wallpaper_color', self.colors['bg'])
        
        # Load wallpaper image if set
        wallpaper_image = self.config.get('settings', {}).get('wallpaper_image')
        if wallpaper_image and os.path.exists(wallpaper_image) and PIL_AVAILABLE:
            try:
                self.load_wallpaper(wallpaper_image)
            except Exception as e:
                print(f"Wallpaper load error: {e}")
                self.root.configure(bg=wallpaper_color)
        else:
            self.root.configure(bg=wallpaper_color)
        
        # Create desktop frame
        self.desktop = tk.Frame(self.root, bg=wallpaper_color)
        self.desktop.pack(fill=tk.BOTH, expand=True)
        
        # Create taskbar
        self.create_enhanced_taskbar()
        
        # Create desktop icons
        self.create_enhanced_desktop_icons()
        
        # Create desktop widgets
        self.create_desktop_widgets()
        
        # Start system monitors
        self.start_system_monitors()
        
        # Bind desktop events
        self.bind_desktop_events()
        
    def load_wallpaper(self, image_path):
        """Load and set wallpaper image with proper error handling"""
        try:
            if not PIL_AVAILABLE:
                raise Exception("PIL not available")
            
            # Open and resize image
            image = Image.open(image_path)
            image = image.resize((self.screen_width, self.screen_height), Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(image)
            
            # Create label with image
            wallpaper_label = tk.Label(self.root, image=photo)
            wallpaper_label.image = photo  # Keep a reference
            wallpaper_label.place(x=0, y=0, relwidth=1, relheight=1)
            
            # Ensure desktop frame is above wallpaper
            self.desktop = tk.Frame(self.root, bg='', highlightthickness=0)
            self.desktop.place(x=0, y=0, relwidth=1, relheight=1)
            
            self.notification_system.show_notification(
                "Wallpaper Set", 
                "Wallpaper loaded successfully", 
                type="success"
            )
            
        except Exception as e:
            print(f"Wallpaper error: {e}")
            fallback_color = self.config.get('settings', {}).get('wallpaper_color', self.colors['bg'])
            self.root.configure(bg=fallback_color)
            self.notification_system.show_notification(
                "Wallpaper Error", 
                f"Failed to load wallpaper: {str(e)}", 
                type="error"
            )
    
    def create_enhanced_taskbar(self):
        """Create enhanced taskbar with more features"""
        self.taskbar = tk.Frame(self.root, bg=self.colors['dark'], height=60)
        self.taskbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.taskbar.pack_propagate(False)
        
        # Left section - Start button and running apps
        left_frame = tk.Frame(self.taskbar, bg=self.colors['dark'])
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=5)
        
        # FORZEOS button (Start menu)
        self.forze_btn = tk.Button(left_frame, text="FORZEOS", 
                                  command=self.show_enhanced_start_menu,
                                  bg=self.colors['accent'], fg='white',
                                  font=('Arial', 12, 'bold'), relief=tk.FLAT,
                                  width=10)
        self.forze_btn.pack(side=tk.LEFT, padx=5, pady=10)
        
        # Running apps area
        self.running_apps_frame = tk.Frame(left_frame, bg=self.colors['dark'])
        self.running_apps_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10)
        
        # Center section - System info
        center_frame = tk.Frame(self.taskbar, bg=self.colors['dark'])
        center_frame.pack(side=tk.LEFT, fill=tk.Y, padx=20)
        
        self.system_label = tk.Label(center_frame, 
                                    text=f"User: {self.current_user} | Lang: {self.current_language}",
                                    bg=self.colors['dark'], fg=self.colors['fg'],
                                    font=('Arial', 10))
        self.system_label.pack(pady=20)
        
        # Right section - System tray and clock
        right_frame = tk.Frame(self.taskbar, bg=self.colors['dark'])
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=5)
        
        # System tray icons
        tray_frame = tk.Frame(right_frame, bg=self.colors['dark'])
        tray_frame.pack(side=tk.RIGHT, padx=10)
        
        # Network status
        self.network_label = tk.Label(tray_frame, text="🌐", bg=self.colors['dark'],
                                     fg=self.colors['success'], font=('Arial', 16))
        self.network_label.pack(side=tk.LEFT, padx=2)
        
        # Notification bell
        notif_btn = tk.Button(tray_frame, text="🔔", bg=self.colors['dark'],
                             fg=self.colors['fg'], font=('Arial', 14),
                             relief=tk.FLAT, command=self.show_notifications)
        notif_btn.pack(side=tk.LEFT, padx=2)
        
        # Clock
        self.clock_label = tk.Label(right_frame, text="", bg=self.colors['dark'],
                                   fg=self.colors['fg'], font=('Arial', 12, 'bold'))
        self.clock_label.pack(side=tk.RIGHT, padx=10, pady=15)
    
    def update_running_apps_display(self):
        """Update running apps display in taskbar"""
        try:
            # Clear existing buttons
            for widget in self.running_apps_frame.winfo_children():
                widget.destroy()
            
            # Add buttons for running apps
            for app_name in self.running_apps:
                if len(app_name) > 10:
                    display_name = app_name[:8] + ".."
                else:
                    display_name = app_name
                    
                app_btn = tk.Button(self.running_apps_frame, text=display_name,
                                   bg=self.colors['light'], fg=self.colors['dark'],
                                   font=('Arial', 9), relief=tk.FLAT,
                                   command=lambda name=app_name: self.focus_app(name))
                app_btn.pack(side=tk.LEFT, padx=2, pady=15)
        except Exception as e:
            print(f"Running apps display error: {e}")
    
    def focus_app(self, app_name):
        """Focus on a running app"""
        if app_name in self.windows:
            try:
                window = self.windows[app_name]
                window.lift()
                window.focus_force()
            except:
                # Window might be destroyed, remove from running apps
                if app_name in self.running_apps:
                    del self.running_apps[app_name]
                if app_name in self.windows:
                    del self.windows[app_name]
                self.update_running_apps_display()
    
    def start_system_monitors(self):
        """Start system monitoring threads"""
        threading.Thread(target=self.update_clock, daemon=True).start()
        threading.Thread(target=self.monitor_network, daemon=True).start()
        threading.Thread(target=self.monitor_system, daemon=True).start()
    
    def update_clock(self):
        """Update the taskbar clock"""
        try:
            while True:
                current_time = datetime.datetime.now().strftime("%H:%M:%S")
                current_date = datetime.datetime.now().strftime("%Y-%m-%d")
                if hasattr(self, 'clock_label'):
                    self.clock_label.config(text=f"{current_date}\n{current_time}")
                time.sleep(1)
        except:
            pass
    
    def monitor_network(self):
        """Monitor network connection"""
        try:
            while True:
                try:
                    # Simple connectivity check
                    socket.create_connection(("8.8.8.8", 53), timeout=3)
                    if hasattr(self, 'network_label'):
                        self.network_label.config(fg=self.colors['success'])
                except:
                    if hasattr(self, 'network_label'):
                        self.network_label.config(fg=self.colors['danger'])
                time.sleep(30)
        except:
            pass
    
    def monitor_system(self):
        """Monitor system resources"""
        try:
            while PSUTIL_AVAILABLE:
                cpu_percent = psutil.cpu_percent(interval=1)
                memory = psutil.virtual_memory()
                
                if hasattr(self, 'system_label'):
                    info_text = f"User: {self.current_user} | CPU: {cpu_percent:.1f}% | RAM: {memory.percent:.1f}%"
                    self.system_label.config(text=info_text)
                time.sleep(5)
        except:
            pass
    
    def bind_desktop_events(self):
        """Bind desktop event handlers"""
        self.desktop.bind("<Button-3>", self.show_desktop_context_menu)  # Right click
        self.root.bind("<Control-Alt-t>", lambda e: self.open_terminal())  # Ctrl+Alt+T
        self.root.bind("<Control-Alt-f>", lambda e: self.open_file_manager())  # Ctrl+Alt+F
        self.root.bind("<Control-Alt-s>", lambda e: self.open_settings())  # Ctrl+Alt+S
    
    def show_desktop_context_menu(self, event):
        """Show desktop right-click context menu"""
        try:
            context_menu = tk.Menu(self.root, tearoff=0)
            context_menu.configure(bg=self.colors['light'], fg=self.colors['dark'])
            
            context_menu.add_command(label="Refresh Desktop", command=self.refresh_desktop)
            context_menu.add_separator()
            context_menu.add_command(label="Change Wallpaper", command=self.change_wallpaper)
            context_menu.add_command(label="Desktop Settings", command=self.open_desktop_settings)
            context_menu.add_separator()
            context_menu.add_command(label="Open Terminal", command=self.open_terminal)
            context_menu.add_command(label="Task Manager", command=self.open_task_manager)
            context_menu.add_separator()
            context_menu.add_command(label="System Info", command=self.show_system_info)
            
            context_menu.post(event.x_root, event.y_root)
        except Exception as e:
            print(f"Context menu error: {e}")
    
    def refresh_desktop(self):
        """Refresh desktop icons and widgets"""
        try:
            # Clear existing icons
            for icon in self.desktop_icons:
                icon.destroy()
            self.desktop_icons.clear()
            
            # Recreate icons
            self.create_enhanced_desktop_icons()
            
            self.notification_system.show_notification(
                "Desktop Refreshed", 
                "Desktop has been refreshed", 
                type="success"
            )
        except Exception as e:
            print(f"Desktop refresh error: {e}")
    
    def change_wallpaper(self):
        """Change desktop wallpaper with enhanced error handling"""
        try:
            if not PIL_AVAILABLE:
                messagebox.showerror("Error", "PIL/Pillow not available for wallpaper support")
                return
            
            file_path = filedialog.askopenfilename(
                title="Select Wallpaper",
                filetypes=[
                    ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif"),
                    ("PNG files", "*.png"),
                    ("JPEG files", "*.jpg *.jpeg"),
                    ("BMP files", "*.bmp"),
                    ("GIF files", "*.gif"),
                    ("All files", "*.*")
                ]
            )
            
            if file_path:
                try:
                    # Test if image can be opened
                    test_image = Image.open(file_path)
                    test_image.close()
                    
                    # Save to config
                    self.config['settings']['wallpaper_image'] = file_path
                    self.save_config()
                    
                    # Apply wallpaper
                    self.load_wallpaper(file_path)
                    
                    # Log action
                    self.db.log_action(self.current_user, "Wallpaper Changed", f"Changed to: {file_path}")
                    
                except Exception as img_error:
                    messagebox.showerror("Error", f"Failed to load image: {str(img_error)}")
                    
        except Exception as e:
            print(f"Wallpaper change error: {e}")
            messagebox.showerror("Error", f"Failed to change wallpaper: {str(e)}")
    
    def create_enhanced_desktop_icons(self):
        """Create enhanced desktop application icons"""
        # All applications including new ones
        apps = [
            # Core Applications
            ("File Manager", self.open_file_manager, "📁"),
            ("Notepad", self.open_notepad, "📝"),
            ("Calculator", self.open_calculator, "🧮"),
            ("Terminal", self.open_terminal, "💻"),
            ("Paint", self.open_paint, "🎨"),
            ("Code Editor", self.open_code_editor, "⚡"),
            
            # Internet & Media
            ("Web Browser", self.open_web_browser, "🌐"),
            ("PDF Reader", self.open_pdf_reader, "📄"),
            ("Gallery", self.open_gallery, "🖼️"),
            ("Music Player", self.open_music_player, "🎵"),
            
            # Security & Tools
            ("Password Manager", self.open_password_manager, "🔐"),
            ("File Encryption", self.open_file_encryption, "🔒"),
            ("Network Scanner", self.open_network_scanner, "📡"),
            
            # New Applications
            ("Icon Manager", self.open_icon_manager, "🎯"),
            ("Connection Monitor", self.open_connection_monitor, "📶"),
            ("Advanced Search", self.open_advanced_search, "🔍"),
            ("QR Tools", self.open_qr_tools, "📱"),
            ("Backup Tool", self.open_backup_tool, "💾"),
            ("Task Manager", self.open_task_manager, "⚙️"),
            ("Weather App", self.open_weather_app, "🌤️"),
            ("Password Vault", self.open_password_vault, "🏦"),
            ("System Logs", self.open_system_logs, "📋"),
            
            # Games
            ("Snake Game", self.open_snake, "🐍"),
            ("Chess", self.open_chess, "♟️"),
            ("Tic-Tac-Toe", self.open_tictactoe, "⭕"),
            ("Flappy Bird", self.open_flappy_bird, "🐦"),
            ("2048", self.open_2048, "🔢"),
            ("Minesweeper", self.open_minesweeper, "💣"),
            ("Sudoku", self.open_sudoku, "🧩"),
            ("Memory Match", self.open_memory_match, "🃏"),
            ("Pong", self.open_pong, "🏓"),
            
            # System
            ("Math Tools", self.open_math_tools, "📊"),
            ("Settings", self.open_settings, "⚙️"),
            ("App Store", self.open_app_store, "🏪")
        ]
        
        # Adaptive grid layout
        if self.is_horizontal:
            cols = 8
            start_x = 30
            start_y = 40
            icon_width = (self.screen_width - 100) // cols
            icon_height = 130
        else:
            cols = 4
            start_x = 20
            start_y = 50
            icon_width = (self.screen_width - 80) // cols
            icon_height = 150
        
        # Create icons
        for i, (name, command, emoji) in enumerate(apps):
            col = i % cols
            row = i // cols
            
            x = start_x + col * icon_width
            y = start_y + row * icon_height
            
            self.create_enhanced_desktop_icon(name, command, emoji, x, y, icon_width - 20, icon_height - 20)
    
    def create_enhanced_desktop_icon(self, name, command, emoji, x, y, width=140, height=100):
        """Create a single enhanced desktop icon"""
        try:
            icon_frame = tk.Frame(self.desktop, bg=self.colors['light'], 
                                 relief=tk.RAISED, bd=2, cursor="hand2")
            icon_frame.place(x=x, y=y, width=width, height=height)
            
            # Bind drag events for repositioning
            icon_frame.bind("<Button-1>", lambda e: self.start_icon_drag(e, icon_frame, name))
            icon_frame.bind("<B1-Motion>", lambda e: self.move_icon(e, icon_frame))
            icon_frame.bind("<ButtonRelease-1>", lambda e: self.end_icon_drag(e, icon_frame, name))
            
            # Emoji/icon
            emoji_label = tk.Label(icon_frame, text=emoji, bg=self.colors['light'],
                                  font=('Arial', 24), fg=self.colors['dark'])
            emoji_label.pack(pady=(10, 5))
            
            # App name
            name_label = tk.Label(icon_frame, text=name, bg=self.colors['light'],
                                 fg=self.colors['dark'], font=('Arial', 9, 'bold'),
                                 wraplength=width-10)
            name_label.pack()
            
            # Bind click events
            for widget in [icon_frame, emoji_label, name_label]:
                widget.bind("<Double-Button-1>", lambda e: command())
                widget.bind("<Button-3>", lambda e: self.show_icon_context_menu(e, name, command))
            
            self.desktop_icons.append(icon_frame)
            
        except Exception as e:
            print(f"Icon creation error: {e}")
    
    def start_icon_drag(self, event, icon_frame, name):
        """Start icon drag operation"""
        self.drag_data = {
            'x': event.x,
            'y': event.y,
            'icon': icon_frame,
            'name': name
        }
    
    def move_icon(self, event, icon_frame):
        """Move icon during drag"""
        if hasattr(self, 'drag_data'):
            x = icon_frame.winfo_x() + event.x - self.drag_data['x']
            y = icon_frame.winfo_y() + event.y - self.drag_data['y']
            icon_frame.place(x=x, y=y)
    
    def end_icon_drag(self, event, icon_frame, name):
        """End icon drag and save position"""
        if hasattr(self, 'drag_data'):
            x = icon_frame.winfo_x()
            y = icon_frame.winfo_y()
            
            # Save position to config
            if 'desktop_layout' not in self.config:
                self.config['desktop_layout'] = {'icon_positions': {}}
            
            self.config['desktop_layout']['icon_positions'][name] = {'x': x, 'y': y}
            self.save_config()
            
            del self.drag_data
    
    def show_icon_context_menu(self, event, name, command):
        """Show context menu for desktop icon"""
        try:
            context_menu = tk.Menu(self.root, tearoff=0)
            context_menu.configure(bg=self.colors['light'], fg=self.colors['dark'])
            
            context_menu.add_command(label=f"Open {name}", command=command)
            context_menu.add_separator()
            context_menu.add_command(label="Change Icon", 
                                   command=lambda: self.change_icon(name))
            context_menu.add_command(label="Create Shortcut", 
                                   command=lambda: self.create_shortcut(name))
            context_menu.add_separator()
            context_menu.add_command(label="Properties", 
                                   command=lambda: self.show_app_properties(name))
            
            context_menu.post(event.x_root, event.y_root)
        except Exception as e:
            print(f"Icon context menu error: {e}")
    
    def create_desktop_widgets(self):
        """Create desktop widgets"""
        if not self.config.get('settings', {}).get('widget_enabled', True):
            return
        
        try:
            # Clock widget
            self.create_clock_widget()
            
            # System monitor widget
            if PSUTIL_AVAILABLE:
                self.create_system_monitor_widget()
            
            # Weather widget (if API available)
            self.create_weather_widget()
            
        except Exception as e:
            print(f"Widget creation error: {e}")
    
    def create_clock_widget(self):
        """Create desktop clock widget"""
        try:
            clock_widget = tk.Frame(self.desktop, bg=self.colors['dark'], 
                                   relief=tk.RAISED, bd=2)
            clock_widget.place(x=self.screen_width-200, y=20, width=180, height=80)
            
            self.widget_clock = tk.Label(clock_widget, text="", 
                                        bg=self.colors['dark'], fg=self.colors['fg'],
                                        font=('Arial', 16, 'bold'))
            self.widget_clock.pack(expand=True)
            
            self.widgets.append(clock_widget)
            
            def update_widget_clock():
                try:
                    current_time = datetime.datetime.now().strftime("%H:%M:%S")
                    current_date = datetime.datetime.now().strftime("%m/%d")
                    self.widget_clock.config(text=f"{current_date}\n{current_time}")
                    self.root.after(1000, update_widget_clock)
                except:
                    pass
            
            update_widget_clock()
        except Exception as e:
            print(f"Clock widget error: {e}")
    
    def create_system_monitor_widget(self):
        """Create system monitor widget"""
        try:
            monitor_widget = tk.Frame(self.desktop, bg=self.colors['dark'],
                                     relief=tk.RAISED, bd=2)
            monitor_widget.place(x=self.screen_width-200, y=120, width=180, height=100)
            
            self.widget_monitor = tk.Label(monitor_widget, text="", 
                                          bg=self.colors['dark'], fg=self.colors['fg'],
                                          font=('Arial', 10))
            self.widget_monitor.pack(expand=True)
            
            self.widgets.append(monitor_widget)
            
            def update_monitor_widget():
                try:
                    if PSUTIL_AVAILABLE:
                        cpu = psutil.cpu_percent(interval=None)
                        memory = psutil.virtual_memory()
                        disk = psutil.disk_usage('/')
                        
                        text = f"CPU: {cpu:.1f}%\nRAM: {memory.percent:.1f}%\nDisk: {disk.percent:.1f}%"
                        self.widget_monitor.config(text=text)
                    
                    self.root.after(5000, update_monitor_widget)
                except:
                    pass
            
            update_monitor_widget()
        except Exception as e:
            print(f"Monitor widget error: {e}")
    
    def create_weather_widget(self):
        """Create weather widget"""
        try:
            weather_widget = tk.Frame(self.desktop, bg=self.colors['dark'],
                                     relief=tk.RAISED, bd=2)
            weather_widget.place(x=self.screen_width-200, y=240, width=180, height=80)
            
            self.widget_weather = tk.Label(weather_widget, text="Weather\nLoading...", 
                                          bg=self.colors['dark'], fg=self.colors['fg'],
                                          font=('Arial', 10))
            self.widget_weather.pack(expand=True)
            
            self.widgets.append(weather_widget)
            
            # Simple weather display (can be enhanced with API)
            def update_weather_widget():
                try:
                    # Simple placeholder - can be enhanced with real API
                    import random
                    temp = random.randint(15, 30)
                    conditions = random.choice(["Sunny", "Cloudy", "Rainy", "Clear"])
                    self.widget_weather.config(text=f"{conditions}\n{temp}°C")
                    self.root.after(300000, update_weather_widget)  # Update every 5 minutes
                except:
                    pass
            
            update_weather_widget()
        except Exception as e:
            print(f"Weather widget error: {e}")
    
    def show_enhanced_start_menu(self):
        """Show enhanced start menu"""
        try:
            if hasattr(self, 'start_menu') and self.start_menu.winfo_exists():
                self.start_menu.destroy()
                return
                
            self.start_menu = tk.Toplevel()
            self.start_menu.title("FORZEOS Start Menu")
            self.start_menu.geometry("400x500")
            self.start_menu.configure(bg=self.colors['bg'])
            self.start_menu.resizable(False, False)
            
            # Position near FORZEOS button
            x = self.forze_btn.winfo_rootx()
            y = self.forze_btn.winfo_rooty() - 510
            self.start_menu.geometry(f"400x500+{x}+{max(0, y)}")
            
            # Create notebook for tabs
            notebook = ttk.Notebook(self.start_menu)
            notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # Applications tab
            apps_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(apps_frame, text="Applications")
            
            # Create scrollable frame for apps
            canvas = tk.Canvas(apps_frame, bg=self.colors['bg'])
            scrollbar = ttk.Scrollbar(apps_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = tk.Frame(canvas, bg=self.colors['bg'])
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            # Application categories
            categories = {
                "System": [
                    ("File Manager", self.open_file_manager),
                    ("Terminal", self.open_terminal),
                    ("Task Manager", self.open_task_manager),
                    ("Settings", self.open_settings)
                ],
                "Productivity": [
                    ("Notepad", self.open_notepad),
                    ("Code Editor", self.open_code_editor),
                    ("Calculator", self.open_calculator),
                    ("PDF Reader", self.open_pdf_reader)
                ],
                "Internet": [
                    ("Web Browser", self.open_web_browser),
                    ("Network Scanner", self.open_network_scanner),
                    ("Connection Monitor", self.open_connection_monitor)
                ],
                "Media": [
                    ("Gallery", self.open_gallery),
                    ("Music Player", self.open_music_player),
                    ("Paint", self.open_paint)
                ],
                "Security": [
                    ("Password Manager", self.open_password_manager),
                    ("Password Vault", self.open_password_vault),
                    ("File Encryption", self.open_file_encryption)
                ],
                "Tools": [
                    ("QR Tools", self.open_qr_tools),
                    ("Backup Tool", self.open_backup_tool),
                    ("Advanced Search", self.open_advanced_search),
                    ("Math Tools", self.open_math_tools)
                ],
                "Games": [
                    ("Snake", self.open_snake),
                    ("Chess", self.open_chess),
                    ("2048", self.open_2048),
                    ("Minesweeper", self.open_minesweeper),
                    ("Sudoku", self.open_sudoku)
                ]
            }
            
            for category, apps in categories.items():
                # Category header
                cat_label = tk.Label(scrollable_frame, text=category, 
                                    bg=self.colors['bg'], fg=self.colors['accent'],
                                    font=('Arial', 12, 'bold'))
                cat_label.pack(anchor=tk.W, padx=10, pady=(10, 5))
                
                # Apps in category
                for app_name, app_command in apps:
                    app_btn = tk.Button(scrollable_frame, text=f"  {app_name}", 
                                       command=lambda cmd=app_command: self.run_from_menu(cmd),
                                       bg=self.colors['light'], fg=self.colors['dark'],
                                       font=('Arial', 10), relief=tk.FLAT,
                                       anchor=tk.W, width=30)
                    app_btn.pack(fill=tk.X, padx=20, pady=1)
            
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            
            # System tab
            system_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(system_frame, text="System")
            
            # System info
            if PSUTIL_AVAILABLE:
                try:
                    cpu_count = psutil.cpu_count()
                    memory = psutil.virtual_memory()
                    disk = psutil.disk_usage('/')
                    
                    system_info = f"""System Information:
CPU Cores: {cpu_count}
Total RAM: {memory.total // (1024**3)} GB
Available RAM: {memory.available // (1024**3)} GB  
Total Disk: {disk.total // (1024**3)} GB
Free Disk: {disk.free // (1024**3)} GB

User: {self.current_user}
Language: {self.current_language}
Theme: {self.current_theme}
Running Apps: {len(self.running_apps)}"""
                    
                    info_label = tk.Label(system_frame, text=system_info,
                                         bg=self.colors['bg'], fg=self.colors['fg'],
                                         font=('Arial', 10), justify=tk.LEFT)
                    info_label.pack(padx=20, pady=20, anchor=tk.W)
                except:
                    pass
            
            # System actions
            actions_frame = tk.Frame(system_frame, bg=self.colors['bg'])
            actions_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=20)
            
            tk.Button(actions_frame, text="Save Session", 
                     command=self.save_session,
                     bg=self.colors['success'], fg='white',
                     width=15).pack(side=tk.LEFT, padx=5)
            
            tk.Button(actions_frame, text="System Logs", 
                     command=self.open_system_logs,
                     bg=self.colors['warning'], fg='white',
                     width=15).pack(side=tk.LEFT, padx=5)
            
            tk.Button(actions_frame, text="Logout", 
                     command=self.logout,
                     bg=self.colors['danger'], fg='white',
                     width=15).pack(side=tk.LEFT, padx=5)
            
        except Exception as e:
            print(f"Start menu error: {e}")
    
    def run_from_menu(self, command):
        """Run application from start menu"""
        try:
            self.start_menu.destroy()
            command()
        except:
            pass
    
    def show_notifications(self):
        """Show notification center"""
        try:
            notif_window = tk.Toplevel()
            notif_window.title("Notifications")
            notif_window.geometry("350x400")
            notif_window.configure(bg=self.colors['bg'])
            
            # Position near notification icon
            x = self.screen_width - 370
            y = self.screen_height - 470
            notif_window.geometry(f"350x400+{x}+{y}")
            
            # Header
            header = tk.Label(notif_window, text="Notification Center", 
                             font=('Arial', 16, 'bold'),
                             bg=self.colors['accent'], fg='white')
            header.pack(fill=tk.X, pady=(0, 10))
            
            # Recent logs as notifications
            logs_frame = tk.Frame(notif_window, bg=self.colors['bg'])
            logs_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            logs = self.db.get_logs(self.current_user, 10)
            
            if logs:
                for log in logs:
                    timestamp, user, action, details, app = log[1], log[2], log[3], log[4], log[5]
                    time_str = datetime.datetime.fromisoformat(timestamp).strftime("%H:%M")
                    
                    notif_frame = tk.Frame(logs_frame, bg=self.colors['light'], 
                                          relief=tk.RAISED, bd=1)
                    notif_frame.pack(fill=tk.X, pady=2)
                    
                    tk.Label(notif_frame, text=f"{app} - {time_str}",
                            bg=self.colors['light'], fg=self.colors['dark'],
                            font=('Arial', 10, 'bold')).pack(anchor=tk.W, padx=5, pady=2)
                    
                    tk.Label(notif_frame, text=action,
                            bg=self.colors['light'], fg=self.colors['dark'],
                            font=('Arial', 9)).pack(anchor=tk.W, padx=5, pady=(0, 2))
            else:
                tk.Label(logs_frame, text="No recent notifications",
                        bg=self.colors['bg'], fg=self.colors['fg'],
                        font=('Arial', 12)).pack(expand=True)
            
            # Clear notifications button
            tk.Button(notif_window, text="Clear All", 
                     command=lambda: notif_window.destroy(),
                     bg=self.colors['danger'], fg='white').pack(pady=10)
            
        except Exception as e:
            print(f"Notifications error: {e}")
    
    def show_system_info(self):
        """Show detailed system information"""
        try:
            info_window = tk.Toplevel()
            info_window.title("System Information")
            info_window.geometry("500x600")
            info_window.configure(bg=self.colors['bg'])
            
            # Create notebook for different info tabs
            notebook = ttk.Notebook(info_window)
            notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # System tab
            system_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(system_frame, text="System")
            
            system_text = tk.Text(system_frame, bg=self.colors['light'], 
                                 fg=self.colors['dark'], font=('Courier', 10))
            system_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # Gather system info
            info_lines = [
                "FORZEOS Enhanced v7.0 System Information",
                "=" * 50,
                f"Current User: {self.current_user}",
                f"Language: {self.current_language}",
                f"Theme: {self.current_theme}",
                f"Screen Resolution: {self.screen_width}x{self.screen_height}",
                f"Orientation: {'Horizontal' if self.is_horizontal else 'Vertical'}",
                ""
            ]
            
            if PSUTIL_AVAILABLE:
                try:
                    info_lines.extend([
                        "Hardware Information:",
                        "-" * 25,
                        f"CPU Cores: {psutil.cpu_count(logical=False)} physical, {psutil.cpu_count()} logical",
                        f"CPU Usage: {psutil.cpu_percent(interval=1):.1f}%",
                        f"Memory Total: {psutil.virtual_memory().total // (1024**3)} GB",
                        f"Memory Available: {psutil.virtual_memory().available // (1024**3)} GB",
                        f"Memory Usage: {psutil.virtual_memory().percent:.1f}%",
                        f"Disk Total: {psutil.disk_usage('/').total // (1024**3)} GB",
                        f"Disk Free: {psutil.disk_usage('/').free // (1024**3)} GB",
                        f"Disk Usage: {psutil.disk_usage('/').percent:.1f}%",
                        ""
                    ])
                except:
                    pass
            
            info_lines.extend([
                "Available Features:",
                "-" * 20,
                f"PDF Support: {'Yes' if PDF_AVAILABLE else 'No'}",
                f"Image Support: {'Yes' if PIL_AVAILABLE else 'No'}",
                f"Audio Support: {'Yes' if PYGAME_AVAILABLE else 'No'}",
                f"Encryption: {'Yes' if CRYPTO_AVAILABLE else 'No'}",
                f"Plotting: {'Yes' if MATPLOTLIB_AVAILABLE else 'No'}",
                f"QR Codes: {'Yes' if QR_AVAILABLE else 'No'}",
                f"Network Requests: {'Yes' if REQUESTS_AVAILABLE else 'No'}",
                f"System Monitoring: {'Yes' if PSUTIL_AVAILABLE else 'No'}",
                "",
                f"Running Applications: {len(self.running_apps)}",
                f"Desktop Icons: {len(self.desktop_icons)}",
                f"Active Widgets: {len(self.widgets)}",
            ])
            
            system_text.insert(tk.END, "\n".join(info_lines))
            system_text.config(state=tk.DISABLED)
            
            # Process tab (if psutil available)
            if PSUTIL_AVAILABLE:
                process_frame = tk.Frame(notebook, bg=self.colors['bg'])
                notebook.add(process_frame, text="Processes")
                
                process_text = tk.Text(process_frame, bg=self.colors['light'], 
                                      fg=self.colors['dark'], font=('Courier', 9))
                process_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
                
                try:
                    processes = []
                    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                        try:
                            processes.append(proc.info)
                        except:
                            pass
                    
                    # Sort by CPU usage
                    processes.sort(key=lambda x: x['cpu_percent'] or 0, reverse=True)
                    
                    process_lines = [
                        "PID    NAME                 CPU%   MEM%",
                        "-" * 50
                    ]
                    
                    for proc in processes[:20]:  # Top 20 processes
                        pid = proc['pid']
                        name = (proc['name'] or 'Unknown')[:20]
                        cpu = proc['cpu_percent'] or 0
                        mem = proc['memory_percent'] or 0
                        process_lines.append(f"{pid:<6} {name:<20} {cpu:<6.1f} {mem:<6.1f}")
                    
                    process_text.insert(tk.END, "\n".join(process_lines))
                    process_text.config(state=tk.DISABLED)
                except:
                    process_text.insert(tk.END, "Unable to retrieve process information")
                    process_text.config(state=tk.DISABLED)
            
        except Exception as e:
            print(f"System info error: {e}")
    
    def logout(self):
        """Logout current user"""
        try:
            response = messagebox.askyesno("Logout", "Are you sure you want to logout?")
            if response:
                # Save session
                self.save_session()
                
                # Log action
                self.db.log_action(self.current_user, "Logout", "User logged out")
                
                # Close all app windows
                for window in list(self.windows.values()):
                    try:
                        window.destroy()
                    except:
                        pass
                
                # Clear running apps
                self.running_apps.clear()
                self.windows.clear()
                
                # Hide main window
                self.root.withdraw()
                
                # Clear user data
                self.current_user = None
                
                # Show login again
                self.show_login()
                
        except Exception as e:
            print(f"Logout error: {e}")
    
    # =====================================================
    # NEW APPLICATIONS START HERE
    # =====================================================
    
    def open_icon_manager(self):
        """Application Icon Manager - NEW"""
        try:
            if "Icon Manager" in self.running_apps:
                self.windows["Icon Manager"].lift()
                return
            
            window = tk.Toplevel()
            window.title("Application Icon Manager")
            window.geometry("600x500")
            window.configure(bg=self.colors['bg'])
            
            self.running_apps["Icon Manager"] = True
            self.windows["Icon Manager"] = window
            self.update_running_apps_display()
            
            # Header
            header = tk.Label(window, text="🎯 Application Icon Manager", 
                             font=('Arial', 16, 'bold'),
                             bg=self.colors['accent'], fg='white')
            header.pack(fill=tk.X, pady=(0, 10))
            
            # Main content
            main_frame = tk.Frame(window, bg=self.colors['bg'])
            main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
            
            # Instructions
            tk.Label(main_frame, text="Select an application to change its icon:",
                    bg=self.colors['bg'], fg=self.colors['fg'],
                    font=('Arial', 12)).pack(pady=10)
            
            # Application list
            apps_frame = tk.Frame(main_frame, bg=self.colors['light'])
            apps_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            
            # Scrollable list
            canvas = tk.Canvas(apps_frame, bg=self.colors['light'])
            scrollbar = ttk.Scrollbar(apps_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = tk.Frame(canvas, bg=self.colors['light'])
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            # Application icons
            apps = [
                "File Manager", "Notepad", "Calculator", "Terminal", "Paint",
                "Code Editor", "Web Browser", "PDF Reader", "Gallery",
                "Music Player", "Password Manager", "Chess", "Snake Game"
            ]
            
            for app in apps:
                app_frame = tk.Frame(scrollable_frame, bg=self.colors['light'], 
                                    relief=tk.RAISED, bd=1)
                app_frame.pack(fill=tk.X, padx=10, pady=5)
                
                tk.Label(app_frame, text=app, bg=self.colors['light'],
                        fg=self.colors['dark'], font=('Arial', 12)).pack(side=tk.LEFT, padx=10, pady=5)
                
                tk.Button(app_frame, text="Change Icon",
                         command=lambda a=app: self.change_app_icon(a),
                         bg=self.colors['accent'], fg='white').pack(side=tk.RIGHT, padx=10, pady=5)
            
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            
            # Close event
            window.protocol("WM_DELETE_WINDOW", lambda: self.close_app("Icon Manager"))
            
            self.db.log_action(self.current_user, "App Opened", "Icon Manager", "Icon Manager")
            
        except Exception as e:
            print(f"Icon Manager error: {e}")
            messagebox.showerror("Error", f"Failed to open Icon Manager: {str(e)}")
    
    def change_app_icon(self, app_name):
        """Change icon for an application"""
        try:
            file_path = filedialog.askopenfilename(
                title=f"Select icon for {app_name}",
                filetypes=[
                    ("Image files", "*.png *.jpg *.jpeg *.ico *.bmp"),
                    ("All files", "*.*")
                ]
            )
            
            if file_path:
                # Save icon path to config
                if 'app_icons' not in self.config:
                    self.config['app_icons'] = {}
                
                self.config['app_icons'][app_name] = file_path
                self.save_config()
                
                self.notification_system.show_notification(
                    "Icon Changed",
                    f"Icon for {app_name} has been updated",
                    type="success"
                )
                
                self.db.log_action(self.current_user, "Icon Changed", 
                                 f"Changed icon for {app_name}", "Icon Manager")
        except Exception as e:
            print(f"Change icon error: {e}")
    
    def open_connection_monitor(self):
        """Internet Connection Monitor - NEW"""
        try:
            if "Connection Monitor" in self.running_apps:
                self.windows["Connection Monitor"].lift()
                return
            
            window = tk.Toplevel()
            window.title("Internet Connection Monitor")
            window.geometry("700x600")
            window.configure(bg=self.colors['bg'])
            
            self.running_apps["Connection Monitor"] = True
            self.windows["Connection Monitor"] = window
            self.update_running_apps_display()
            
            # Header
            header = tk.Label(window, text="📶 Internet Connection Monitor", 
                             font=('Arial', 16, 'bold'),
                             bg=self.colors['accent'], fg='white')
            header.pack(fill=tk.X, pady=(0, 10))
            
            # Create notebook for different tabs
            notebook = ttk.Notebook(window)
            notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # Status tab
            status_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(status_frame, text="Connection Status")
            
            # Connection status display
            self.connection_status = tk.Text(status_frame, bg=self.colors['light'], 
                                           fg=self.colors['dark'], font=('Courier', 10))
            self.connection_status.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # Speed test tab
            speed_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(speed_frame, text="Speed Test")
            
            tk.Label(speed_frame, text="Connection Speed Test", 
                    bg=self.colors['bg'], fg=self.colors['fg'],
                    font=('Arial', 14, 'bold')).pack(pady=20)
            
            speed_btn = tk.Button(speed_frame, text="Run Speed Test",
                                 command=self.run_speed_test,
                                 bg=self.colors['accent'], fg='white',
                                 font=('Arial', 12), width=20, height=2)
            speed_btn.pack(pady=10)
            
            self.speed_result = tk.Label(speed_frame, text="Click to start speed test",
                                        bg=self.colors['bg'], fg=self.colors['fg'],
                                        font=('Arial', 12))
            self.speed_result.pack(pady=20)
            
            # Port scanner tab
            port_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(port_frame, text="Port Scanner")
            
            tk.Label(port_frame, text="Port Scanner", 
                    bg=self.colors['bg'], fg=self.colors['fg'],
                    font=('Arial', 14, 'bold')).pack(pady=10)
            
            # Target IP input
            ip_frame = tk.Frame(port_frame, bg=self.colors['bg'])
            ip_frame.pack(pady=10)
            
            tk.Label(ip_frame, text="Target IP:", bg=self.colors['bg'], 
                    fg=self.colors['fg']).pack(side=tk.LEFT)
            self.target_ip = tk.Entry(ip_frame, width=20)
            self.target_ip.pack(side=tk.LEFT, padx=10)
            self.target_ip.insert(0, "127.0.0.1")
            
            # Port range input
            port_frame_input = tk.Frame(port_frame, bg=self.colors['bg'])
            port_frame_input.pack(pady=10)
            
            tk.Label(port_frame_input, text="Port Range:", bg=self.colors['bg'], 
                    fg=self.colors['fg']).pack(side=tk.LEFT)
            self.start_port = tk.Entry(port_frame_input, width=10)
            self.start_port.pack(side=tk.LEFT, padx=5)
            self.start_port.insert(0, "1")
            
            tk.Label(port_frame_input, text="to", bg=self.colors['bg'], 
                    fg=self.colors['fg']).pack(side=tk.LEFT)
            self.end_port = tk.Entry(port_frame_input, width=10)
            self.end_port.pack(side=tk.LEFT, padx=5)
            self.end_port.insert(0, "100")
            
            scan_btn = tk.Button(port_frame, text="Scan Ports",
                                command=self.scan_ports,
                                bg=self.colors['warning'], fg='white',
                                font=('Arial', 12))
            scan_btn.pack(pady=10)
            
            self.port_results = tk.Text(port_frame, bg=self.colors['light'], 
                                       fg=self.colors['dark'], font=('Courier', 9),
                                       height=15)
            self.port_results.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # Start monitoring
            self.monitor_connection(window)
            
            # Close event
            window.protocol("WM_DELETE_WINDOW", lambda: self.close_app("Connection Monitor"))
            
            self.db.log_action(self.current_user, "App Opened", "Connection Monitor", "Connection Monitor")
            
        except Exception as e:
            print(f"Connection Monitor error: {e}")
            messagebox.showerror("Error", f"Failed to open Connection Monitor: {str(e)}")
    
    def monitor_connection(self, window):
        """Monitor internet connection status"""
        def update_status():
            try:
                if not window.winfo_exists():
                    return
                
                status_lines = []
                status_lines.append("Connection Status Report")
                status_lines.append("=" * 40)
                status_lines.append(f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                status_lines.append("")
                
                # Test multiple servers
                test_servers = [
                    ("Google DNS", "8.8.8.8", 53),
                    ("Cloudflare DNS", "1.1.1.1", 53),
                    ("OpenDNS", "208.67.222.222", 53)
                ]
                
                for name, ip, port in test_servers:
                    try:
                        start_time = time.time()
                        socket.create_connection((ip, port), timeout=5)
                        ping_time = (time.time() - start_time) * 1000
                        status_lines.append(f"{name}: ✓ Connected ({ping_time:.1f}ms)")
                    except:
                        status_lines.append(f"{name}: ✗ Failed")
                
                status_lines.append("")
                
                # Local network info
                try:
                    hostname = socket.gethostname()
                    local_ip = socket.gethostbyname(hostname)
                    status_lines.append(f"Hostname: {hostname}")
                    status_lines.append(f"Local IP: {local_ip}")
                except:
                    status_lines.append("Local network info unavailable")
                
                # Update display
                self.connection_status.delete(1.0, tk.END)
                self.connection_status.insert(1.0, "\n".join(status_lines))
                
                # Schedule next update
                window.after(5000, update_status)
                
            except Exception as e:
                print(f"Connection monitoring error: {e}")
        
        update_status()
    
    def run_speed_test(self):
        """Run a simple speed test"""
        try:
            self.speed_result.config(text="Running speed test...")
            
            def speed_test():
                try:
                    # Simple download test
                    url = "http://httpbin.org/bytes/1048576"  # 1MB test file
                    start_time = time.time()
                    
                    if REQUESTS_AVAILABLE:
                        response = requests.get(url, timeout=30)
                        if response.status_code == 200:
                            end_time = time.time()
                            duration = end_time - start_time
                            speed_mbps = (1 / duration) * 8  # Convert to Mbps
                            
                            result_text = f"Download Speed: {speed_mbps:.2f} Mbps\nTest Duration: {duration:.2f} seconds"
                        else:
                            result_text = "Speed test failed - Server error"
                    else:
                        # Fallback ping test
                        ping_times = []
                        for _ in range(5):
                            start_time = time.time()
                            try:
                                socket.create_connection(("8.8.8.8", 53), timeout=5)
                                ping_time = (time.time() - start_time) * 1000
                                ping_times.append(ping_time)
                            except:
                                ping_times.append(999)
                        
                        avg_ping = sum(ping_times) / len(ping_times)
                        result_text = f"Average Ping: {avg_ping:.1f} ms\n(Full speed test requires requests module)"
                    
                    self.speed_result.config(text=result_text)
                    
                except Exception as e:
                    self.speed_result.config(text=f"Speed test error: {str(e)}")
            
            # Run in thread to avoid blocking UI
            threading.Thread(target=speed_test, daemon=True).start()
            
        except Exception as e:
            print(f"Speed test error: {e}")
            self.speed_result.config(text=f"Speed test failed: {str(e)}")
    
    def scan_ports(self):
        """Scan ports on target IP"""
        try:
            target = self.target_ip.get()
            start_port = int(self.start_port.get())
            end_port = int(self.end_port.get())
            
            self.port_results.delete(1.0, tk.END)
            self.port_results.insert(tk.END, f"Scanning {target} ports {start_port}-{end_port}...\n")
            self.port_results.insert(tk.END, "=" * 50 + "\n")
            
            def port_scan():
                open_ports = []
                for port in range(start_port, min(end_port + 1, start_port + 100)):  # Limit scan
                    try:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(1)
                        result = sock.connect_ex((target, port))
                        if result == 0:
                            open_ports.append(port)
                            self.port_results.insert(tk.END, f"Port {port}: OPEN\n")
                        sock.close()
                    except:
                        pass
                
                self.port_results.insert(tk.END, f"\nScan complete. Found {len(open_ports)} open ports.\n")
                
                if open_ports:
                    self.port_results.insert(tk.END, f"Open ports: {', '.join(map(str, open_ports))}\n")
            
            # Run in thread
            threading.Thread(target=port_scan, daemon=True).start()
            
        except Exception as e:
            print(f"Port scan error: {e}")
            self.port_results.insert(tk.END, f"Port scan error: {str(e)}\n")
    
    def open_advanced_search(self):
        """Advanced File Search - NEW"""
        try:
            if "Advanced Search" in self.running_apps:
                self.windows["Advanced Search"].lift()
                return
            
            window = tk.Toplevel()
            window.title("Advanced File Search")
            window.geometry("800x600")
            window.configure(bg=self.colors['bg'])
            
            self.running_apps["Advanced Search"] = True
            self.windows["Advanced Search"] = window
            self.update_running_apps_display()
            
            # Header
            header = tk.Label(window, text="🔍 Advanced File Search", 
                             font=('Arial', 16, 'bold'),
                             bg=self.colors['accent'], fg='white')
            header.pack(fill=tk.X, pady=(0, 10))
            
            # Search criteria frame
            criteria_frame = tk.Frame(window, bg=self.colors['bg'])
            criteria_frame.pack(fill=tk.X, padx=20, pady=10)
            
            # Search location
            location_frame = tk.Frame(criteria_frame, bg=self.colors['bg'])
            location_frame.pack(fill=tk.X, pady=5)
            
            tk.Label(location_frame, text="Search Location:", bg=self.colors['bg'], 
                    fg=self.colors['fg'], width=15, anchor='w').pack(side=tk.LEFT)
            self.search_path = tk.Entry(location_frame, width=40)
            self.search_path.pack(side=tk.LEFT, padx=5)
            self.search_path.insert(0, self.file_system_root)
            
            tk.Button(location_frame, text="Browse", 
                     command=self.browse_search_location,
                     bg=self.colors['light']).pack(side=tk.LEFT, padx=5)
            
            # File name pattern
            name_frame = tk.Frame(criteria_frame, bg=self.colors['bg'])
            name_frame.pack(fill=tk.X, pady=5)
            
            tk.Label(name_frame, text="File Name:", bg=self.colors['bg'], 
                    fg=self.colors['fg'], width=15, anchor='w').pack(side=tk.LEFT)
            self.search_name = tk.Entry(name_frame, width=40)
            self.search_name.pack(side=tk.LEFT, padx=5)
            self.search_name.insert(0, "*")
            
            # File type
            type_frame = tk.Frame(criteria_frame, bg=self.colors['bg'])
            type_frame.pack(fill=tk.X, pady=5)
            
            tk.Label(type_frame, text="File Type:", bg=self.colors['bg'], 
                    fg=self.colors['fg'], width=15, anchor='w').pack(side=tk.LEFT)
            self.search_type = ttk.Combobox(type_frame, width=37,
                                           values=["All Files", "Documents (.txt, .doc, .pdf)", 
                                                  "Images (.jpg, .png, .gif)", "Audio (.mp3, .wav)",
                                                  "Video (.mp4, .avi)", "Archives (.zip, .rar)"])
            self.search_type.pack(side=tk.LEFT, padx=5)
            self.search_type.set("All Files")
            
            # File size
            size_frame = tk.Frame(criteria_frame, bg=self.colors['bg'])
            size_frame.pack(fill=tk.X, pady=5)
            
            tk.Label(size_frame, text="File Size:", bg=self.colors['bg'], 
                    fg=self.colors['fg'], width=15, anchor='w').pack(side=tk.LEFT)
            
            self.size_min = tk.Entry(size_frame, width=10)
            self.size_min.pack(side=tk.LEFT, padx=2)
            tk.Label(size_frame, text="KB to", bg=self.colors['bg'], 
                    fg=self.colors['fg']).pack(side=tk.LEFT, padx=2)
            self.size_max = tk.Entry(size_frame, width=10)
            self.size_max.pack(side=tk.LEFT, padx=2)
            tk.Label(size_frame, text="KB", bg=self.colors['bg'], 
                    fg=self.colors['fg']).pack(side=tk.LEFT, padx=2)
            
            # Date range
            date_frame = tk.Frame(criteria_frame, bg=self.colors['bg'])
            date_frame.pack(fill=tk.X, pady=5)
            
            tk.Label(date_frame, text="Modified:", bg=self.colors['bg'], 
                    fg=self.colors['fg'], width=15, anchor='w').pack(side=tk.LEFT)
            
            self.date_option = ttk.Combobox(date_frame, width=20,
                                           values=["Any time", "Today", "This week", 
                                                  "This month", "This year"])
            self.date_option.pack(side=tk.LEFT, padx=5)
            self.date_option.set("Any time")
            
            # Search button
            search_btn = tk.Button(criteria_frame, text="🔍 Search", 
                                  command=self.perform_advanced_search,
                                  bg=self.colors['accent'], fg='white',
                                  font=('Arial', 12, 'bold'), width=20, height=2)
            search_btn.pack(pady=20)
            
            # Results frame
            results_frame = tk.Frame(window, bg=self.colors['bg'])
            results_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
            
            tk.Label(results_frame, text="Search Results:", bg=self.colors['bg'], 
                    fg=self.colors['fg'], font=('Arial', 12, 'bold')).pack(anchor=tk.W)
            
            # Results tree
            columns = ('Name', 'Path', 'Size', 'Modified')
            self.search_results = ttk.Treeview(results_frame, columns=columns, show='headings')
            
            for col in columns:
                self.search_results.heading(col, text=col)
                self.search_results.column(col, width=150)
            
            # Scrollbars for results
            v_scroll = ttk.Scrollbar(results_frame, orient="vertical", command=self.search_results.yview)
            h_scroll = ttk.Scrollbar(results_frame, orient="horizontal", command=self.search_results.xview)
            self.search_results.configure(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
            
            # Pack results
            self.search_results.pack(side="left", fill="both", expand=True)
            v_scroll.pack(side="right", fill="y")
            h_scroll.pack(side="bottom", fill="x")
            
            # Double click to open file
            self.search_results.bind('<Double-1>', self.open_search_result)
            
            # Close event
            window.protocol("WM_DELETE_WINDOW", lambda: self.close_app("Advanced Search"))
            
            self.db.log_action(self.current_user, "App Opened", "Advanced Search", "Advanced Search")
            
        except Exception as e:
            print(f"Advanced Search error: {e}")
            messagebox.showerror("Error", f"Failed to open Advanced Search: {str(e)}")
    
    def browse_search_location(self):
        """Browse for search location"""
        try:
            directory = filedialog.askdirectory(initialdir=self.search_path.get())
            if directory:
                self.search_path.delete(0, tk.END)
                self.search_path.insert(0, directory)
        except Exception as e:
            print(f"Browse location error: {e}")
    
    def perform_advanced_search(self):
        """Perform the advanced file search"""
        try:
            # Clear previous results
            for item in self.search_results.get_children():
                self.search_results.delete(item)
            
            search_path = self.search_path.get()
            name_pattern = self.search_name.get().lower()
            file_type = self.search_type.get()
            
            # Size criteria
            try:
                size_min = int(self.size_min.get()) * 1024 if self.size_min.get() else 0
            except:
                size_min = 0
            
            try:
                size_max = int(self.size_max.get()) * 1024 if self.size_max.get() else float('inf')
            except:
                size_max = float('inf')
            
            # Date criteria
            date_filter = self.date_option.get()
            now = datetime.datetime.now()
            
            if date_filter == "Today":
                min_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif date_filter == "This week":
                days_since_monday = now.weekday()
                min_date = now - datetime.timedelta(days=days_since_monday)
                min_date = min_date.replace(hour=0, minute=0, second=0, microsecond=0)
            elif date_filter == "This month":
                min_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            elif date_filter == "This year":
                min_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                min_date = datetime.datetime.min
            
            # File type extensions
            type_extensions = {
                "Documents (.txt, .doc, .pdf)": ['.txt', '.doc', '.docx', '.pdf', '.rtf'],
                "Images (.jpg, .png, .gif)": ['.jpg', '.jpeg', '.png', '.gif', '.bmp'],
                "Audio (.mp3, .wav)": ['.mp3', '.wav', '.ogg', '.m4a'],
                "Video (.mp4, .avi)": ['.mp4', '.avi', '.mov', '.mkv'],
                "Archives (.zip, .rar)": ['.zip', '.rar', '.7z', '.tar']
            }
            
            allowed_extensions = type_extensions.get(file_type, [])
            
            # Search function
            def search_files():
                results = []
                try:
                    for root, dirs, files in os.walk(search_path):
                        for file in files:
                            try:
                                file_path = os.path.join(root, file)
                                
                                # Name filter
                                if name_pattern != "*" and name_pattern not in file.lower():
                                    continue
                                
                                # Type filter
                                if allowed_extensions:
                                    if not any(file.lower().endswith(ext) for ext in allowed_extensions):
                                        continue
                                
                                # Size filter
                                file_size = os.path.getsize(file_path)
                                if not (size_min <= file_size <= size_max):
                                    continue
                                
                                # Date filter
                                mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
                                if mod_time < min_date:
                                    continue
                                
                                # Add to results
                                size_kb = file_size / 1024
                                mod_str = mod_time.strftime("%Y-%m-%d %H:%M")
                                
                                results.append((file, file_path, f"{size_kb:.1f} KB", mod_str))
                                
                                # Limit results to prevent UI freeze
                                if len(results) >= 1000:
                                    break
                                    
                            except Exception as e:
                                continue
                        
                        if len(results) >= 1000:
                            break
                
                # Update UI in main thread
                def update_results():
                    for result in results:
                        self.search_results.insert('', 'end', values=result)
                    
                    if len(results) >= 1000:
                        messagebox.showwarning("Search Limit", "Search limited to first 1000 results")
                
                self.search_results.after(0, update_results)
            
            # Run search in thread
            threading.Thread(target=search_files, daemon=True).start()
            
            self.db.log_action(self.current_user, "File Search", 
                             f"Searched in {search_path}", "Advanced Search")
            
        except Exception as e:
            print(f"Advanced search error: {e}")
            messagebox.showerror("Error", f"Search failed: {str(e)}")
    
    def open_search_result(self, event):
        """Open selected search result"""
        try:
            selection = self.search_results.selection()
            if selection:
                item = self.search_results.item(selection[0])
                file_path = item['values'][1]
                
                # Open file with system default
                if os.path.exists(file_path):
                    if sys.platform.startswith('darwin'):  # macOS
                        subprocess.call(['open', file_path])
                    elif os.name == 'nt':  # Windows
                        os.startfile(file_path)
                    elif os.name == 'posix':  # Linux
                        subprocess.call(['xdg-open', file_path])
                else:
                    messagebox.showerror("Error", "File not found")
        except Exception as e:
            print(f"Open search result error: {e}")
    
    def open_qr_tools(self):
        """QR Code Generator & Scanner - NEW"""
        try:
            if "QR Tools" in self.running_apps:
                self.windows["QR Tools"].lift()
                return
            
            window = tk.Toplevel()
            window.title("QR Code Tools")
            window.geometry("600x700")
            window.configure(bg=self.colors['bg'])
            
            self.running_apps["QR Tools"] = True
            self.windows["QR Tools"] = window
            self.update_running_apps_display()
            
            # Header
            header = tk.Label(window, text="📱 QR Code Tools", 
                             font=('Arial', 16, 'bold'),
                             bg=self.colors['accent'], fg='white')
            header.pack(fill=tk.X, pady=(0, 10))
            
            # Create notebook for generator and scanner
            notebook = ttk.Notebook(window)
            notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # QR Generator tab
            gen_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(gen_frame, text="Generate QR")
            
            tk.Label(gen_frame, text="QR Code Generator", 
                    bg=self.colors['bg'], fg=self.colors['fg'],
                    font=('Arial', 14, 'bold')).pack(pady=20)
            
            # Text input
            tk.Label(gen_frame, text="Enter text to encode:", 
                    bg=self.colors['bg'], fg=self.colors['fg']).pack(pady=5)
            
            self.qr_text = tk.Text(gen_frame, height=5, width=50, 
                                  bg=self.colors['light'], fg=self.colors['dark'])
            self.qr_text.pack(pady=10)
            
            # Generate button
            gen_btn = tk.Button(gen_frame, text="Generate QR Code",
                               command=self.generate_qr_code,
                               bg=self.colors['accent'], fg='white',
                               font=('Arial', 12), width=20, height=2)
            gen_btn.pack(pady=10)
            
            # QR display area
            self.qr_display_frame = tk.Frame(gen_frame, bg=self.colors['light'], 
                                            width=300, height=300)
            self.qr_display_frame.pack(pady=20)
            self.qr_display_frame.pack_propagate(False)
            
            # Save button
            save_btn = tk.Button(gen_frame, text="Save QR Code",
                                command=self.save_qr_code,
                                bg=self.colors['success'], fg='white',
                                font=('Arial', 12))
            save_btn.pack(pady=10)
            
            # QR Scanner tab
            scan_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(scan_frame, text="Scan QR")
            
            tk.Label(scan_frame, text="QR Code Scanner", 
                    bg=self.colors['bg'], fg=self.colors['fg'],
                    font=('Arial', 14, 'bold')).pack(pady=20)
            
            tk.Label(scan_frame, text="Load QR code image to decode:", 
                    bg=self.colors['bg'], fg=self.colors['fg']).pack(pady=10)
            
            load_btn = tk.Button(scan_frame, text="Load QR Image",
                                command=self.load_qr_image,
                                bg=self.colors['warning'], fg='white',
                                font=('Arial', 12), width=20, height=2)
            load_btn.pack(pady=10)
            
            # Decoded text display
            tk.Label(scan_frame, text="Decoded Text:", 
                    bg=self.colors['bg'], fg=self.colors['fg']).pack(pady=(20, 5))
            
            self.decoded_text = tk.Text(scan_frame, height=10, width=50,
                                       bg=self.colors['light'], fg=self.colors['dark'])
            self.decoded_text.pack(pady=10)
            
            # Store QR image for saving
            self.current_qr_image = None
            
            # Close event
            window.protocol("WM_DELETE_WINDOW", lambda: self.close_app("QR Tools"))
            
            self.db.log_action(self.current_user, "App Opened", "QR Tools", "QR Tools")
            
        except Exception as e:
            print(f"QR Tools error: {e}")
            messagebox.showerror("Error", f"Failed to open QR Tools: {str(e)}")
    
    def generate_qr_code(self):
        """Generate QR code from text"""
        try:
            if not QR_AVAILABLE:
                messagebox.showerror("Error", "QR code library not available")
                return
            
            text = self.qr_text.get(1.0, tk.END).strip()
            if not text:
                messagebox.showerror("Error", "Please enter text to encode")
                return
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(text)
            qr.make(fit=True)
            
            # Create image
            qr_image = qr.make_image(fill_color="black", back_color="white")
            
            # Resize for display
            qr_image = qr_image.resize((280, 280), Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage
            if PIL_AVAILABLE:
                photo = ImageTk.PhotoImage(qr_image)
                
                # Clear previous display
                for widget in self.qr_display_frame.winfo_children():
                    widget.destroy()
                
                # Display QR code
                qr_label = tk.Label(self.qr_display_frame, image=photo)
                qr_label.image = photo  # Keep reference
                qr_label.pack(expand=True)
                
                # Store for saving
                self.current_qr_image = qr_image
                
                self.notification_system.show_notification(
                    "QR Generated", 
                    "QR code generated successfully", 
                    type="success"
                )
            
        except Exception as e:
            print(f"QR generation error: {e}")
            messagebox.showerror("Error", f"Failed to generate QR code: {str(e)}")
    
    def save_qr_code(self):
        """Save generated QR code"""
        try:
            if not self.current_qr_image:
                messagebox.showerror("Error", "No QR code to save")
                return
            
            file_path = filedialog.asksaveasfilename(
                defaultextension=".png",
                filetypes=[("PNG files", "*.png"), ("All files", "*.*")]
            )
            
            if file_path:
                self.current_qr_image.save(file_path)
                self.notification_system.show_notification(
                    "QR Saved", 
                    f"QR code saved to {file_path}", 
                    type="success"
                )
                
        except Exception as e:
            print(f"QR save error: {e}")
            messagebox.showerror("Error", f"Failed to save QR code: {str(e)}")
    
    def load_qr_image(self):
        """Load and decode QR image"""
        try:
            file_path = filedialog.askopenfilename(
                title="Select QR Code Image",
                filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")]
            )
            
            if file_path and PIL_AVAILABLE:
                # For demo purposes, we'll show a simple message
                # Real QR decoding would require additional libraries like pyzbar
                self.decoded_text.delete(1.0, tk.END)
                self.decoded_text.insert(1.0, "QR code decoding requires additional libraries.\n")
                self.decoded_text.insert(tk.END, "This is a placeholder for QR scanning functionality.\n\n")
                self.decoded_text.insert(tk.END, f"Selected file: {file_path}")
                
                self.notification_system.show_notification(
                    "QR Loaded", 
                    "QR image loaded (decoding requires pyzbar library)", 
                    type="warning"
                )
                
        except Exception as e:
            print(f"QR load error: {e}")
            messagebox.showerror("Error", f"Failed to load QR image: {str(e)}")
    
    def open_backup_tool(self):
        """Backup Tool - NEW"""
        try:
            if "Backup Tool" in self.running_apps:
                self.windows["Backup Tool"].lift()
                return
            
            window = tk.Toplevel()
            window.title("Backup Tool")
            window.geometry("700x600")
            window.configure(bg=self.colors['bg'])
            
            self.running_apps["Backup Tool"] = True
            self.windows["Backup Tool"] = window
            self.update_running_apps_display()
            
            # Header
            header = tk.Label(window, text="💾 Backup Tool", 
                             font=('Arial', 16, 'bold'),
                             bg=self.colors['accent'], fg='white')
            header.pack(fill=tk.X, pady=(0, 10))
            
            # Create notebook for backup and restore
            notebook = ttk.Notebook(window)
            notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # Backup tab
            backup_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(backup_frame, text="Create Backup")
            
            tk.Label(backup_frame, text="Create System Backup", 
                    bg=self.colors['bg'], fg=self.colors['fg'],
                    font=('Arial', 14, 'bold')).pack(pady=20)
            
            # Source selection
            source_frame = tk.Frame(backup_frame, bg=self.colors['bg'])
            source_frame.pack(fill=tk.X, pady=10, padx=20)
            
            tk.Label(source_frame, text="Backup Source:", 
                    bg=self.colors['bg'], fg=self.colors['fg']).pack(anchor=tk.W)
            
            self.backup_source = tk.Entry(source_frame, width=50)
            self.backup_source.pack(fill=tk.X, pady=5)
            self.backup_source.insert(0, os.path.join(self.file_system_root, self.current_user))
            
            tk.Button(source_frame, text="Browse", 
                     command=self.browse_backup_source,
                     bg=self.colors['light']).pack(anchor=tk.W, pady=5)
            
            # Destination selection
            dest_frame = tk.Frame(backup_frame, bg=self.colors['bg'])
            dest_frame.pack(fill=tk.X, pady=10, padx=20)
            
            tk.Label(dest_frame, text="Backup Destination:", #!/usr/bin/env python3
"""
FORZEOS Enhanced - Complete GUI Operating System
A full-featured desktop operating system written in Python with tkinter
Optimized for Android/Pydroid 3 with mobile-friendly interface

Enhanced Features:
- Fixed wallpaper system with proper PIL image handling
- Chess bot with minimax algorithm
- New applications: Icon Manager, Network Tools, QR Generator, Backup Tool, etc.
- New games: 2048, Minesweeper, Sudoku, Memory Match, Pong
- System improvements: Session saving, Theme engine, Multi-language support
- Enhanced mobile-friendly interface
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, colorchooser
import os
import sys
import json
import hashlib
import datetime
import threading
import subprocess
import webbrowser
import urllib.request
import socket
import psutil
import random
import math
import shutil
import sqlite3
import zipfile
import io
import base64
import time
import requests
from pathlib import Path

# Advanced features imports
try:
    import fitz  # PyMuPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    from PIL import Image, ImageTk, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pygame
    PYGAME_AVAILABLE = True
    pygame.mixer.init()
except ImportError:
    PYGAME_AVAILABLE = False

try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import qrcode
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False


class ForzeOSEnhanced:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FORZEOS Enhanced - Advanced Desktop OS")
        
        # Get screen dimensions
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        
        # Detect orientation
        self.is_horizontal = self.screen_width > self.screen_height
        
        # Try fullscreen mode
        try:
            self.root.attributes('-fullscreen', True)
        except:
            self.root.geometry(f"{self.screen_width}x{self.screen_height}")
        
        # System variables
        self.current_user = None
        self.running_apps = {}
        self.windows = {}
        self.desktop_icons = []
        self.config_file = "forzeos_config.json"
        self.file_system_root = "forze_users"
        self.session_file = "session.json"
        self.logs_file = "system_logs.db"
        self.current_language = "en"
        self.notifications = []
        self.widgets = []
        self.current_wallpaper = None
        
        # Language translations
        self.translations = {
            "en": {
                "welcome": "Welcome to FORZEOS",
                "login": "Login",
                "username": "Username",
                "password": "Password",
                "settings": "Settings",
                "file_manager": "File Manager",
                "calculator": "Calculator",
                "notepad": "Notepad",
                "terminal": "Terminal",
                "paint": "Paint",
                "games": "Games",
                "tools": "Tools",
                "logout": "Logout",
                "error": "Error",
                "success": "Success",
                "warning": "Warning",
                "info": "Info"
            },
            "tr": {
                "welcome": "FORZEOS'a Hoş Geldiniz",
                "login": "Giriş",
                "username": "Kullanıcı Adı",
                "password": "Şifre",
                "settings": "Ayarlar",
                "file_manager": "Dosya Yöneticisi",
                "calculator": "Hesap Makinesi",
                "notepad": "Not Defteri",
                "terminal": "Terminal",
                "paint": "Boyama",
                "games": "Oyunlar",
                "tools": "Araçlar",
                "logout": "Çıkış",
                "error": "Hata",
                "success": "Başarılı",
                "warning": "Uyarı",
                "info": "Bilgi"
            }
        }
        
        # Color schemes/themes
        self.themes = {
            "dark": {
                'bg': '#2C3E50',
                'fg': '#ECF0F1',
                'accent': '#3498DB',
                'success': '#27AE60',
                'warning': '#F39C12',
                'danger': '#E74C3C',
                'dark': '#34495E',
                'light': '#BDC3C7'
            },
            "light": {
                'bg': '#ECF0F1',
                'fg': '#2C3E50',
                'accent': '#3498DB',
                'success': '#27AE60',
                'warning': '#F39C12',
                'danger': '#E74C3C',
                'dark': '#BDC3C7',
                'light': '#FFFFFF'
            },
            "blue": {
                'bg': '#1E3A8A',
                'fg': '#FFFFFF',
                'accent': '#60A5FA',
                'success': '#10B981',
                'warning': '#F59E0B',
                'danger': '#EF4444',
                'dark': '#1E40AF',
                'light': '#DBEAFE'
            }
        }
        
        self.current_theme = "dark"
        self.colors = self.themes[self.current_theme]
        
        # Initialize system
        self.init_file_system()
        self.init_database()
        self.load_config()
        
        # Show login first
        self.root.withdraw()
        self.show_login()
        
    def init_file_system(self):
        """Initialize the file system structure"""
        directories = [
            self.file_system_root,
            f"{self.file_system_root}/Documents",
            f"{self.file_system_root}/Pictures",
            f"{self.file_system_root}/Music",
            f"{self.file_system_root}/Videos",
            f"{self.file_system_root}/Downloads",
            f"{self.file_system_root}/Desktop",
            "themes",
            "plugins",
            "backups"
        ]
        
        for directory in directories:
            if not os.path.exists(directory):
                os.makedirs(directory)
                
    def init_database(self):
        """Initialize SQLite database for logs and data storage"""
        conn = sqlite3.connect(self.logs_file)
        cursor = conn.cursor()
        
        # System logs table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                user TEXT,
                action TEXT,
                details TEXT
            )
        ''')
        
        # Notes and passwords table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS secure_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT,
                title TEXT,
                content TEXT,
                category TEXT,
                encrypted BOOLEAN,
                created_date TEXT
            )
        ''')
        
        # App icons table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_icons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT,
                icon_path TEXT,
                user TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        
    def log_action(self, action, details=""):
        """Log system actions to database"""
        try:
            conn = sqlite3.connect(self.logs_file)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO system_logs (timestamp, user, action, details)
                VALUES (?, ?, ?, ?)
            ''', (datetime.datetime.now().isoformat(), self.current_user or "system", action, details))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Logging error: {e}")
        
    def load_config(self):
        """Load system configuration"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            except Exception as e:
                self.config = self.get_default_config()
        else:
            self.config = self.get_default_config()
            self.save_config()
            
        # Load theme and language settings
        settings = self.config.get('settings', {})
        self.current_theme = settings.get('theme', 'dark')
        self.current_language = settings.get('language', 'en')
        self.colors = self.themes.get(self.current_theme, self.themes['dark'])
        
    def get_default_config(self):
        """Get default system configuration"""
        return {
            'users': {
                'admin': {
                    'password': hashlib.md5('Forze esp32'.encode()).hexdigest(),
                    'created': datetime.datetime.now().isoformat()
                }
            },
            'settings': {
                'wallpaper_color': '#2C3E50',
                'wallpaper_image': None,
                'taskbar_position': 'bottom',
                'auto_login': False,
                'theme': 'dark',
                'language': 'en',
                'startup_apps': [],
                'show_widgets': True,
                'notification_timeout': 5000
            }
        }
    
    def save_config(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            print(f"Config save error: {e}")
    
    def translate(self, key):
        """Get translated text for current language"""
        return self.translations.get(self.current_language, {}).get(key, key)
    
    def show_notification(self, title, message, type_="info"):
        """Show system notification"""
        try:
            # Create notification window
            notif = tk.Toplevel()
            notif.title(title)
            notif.geometry("300x100")
            notif.configure(bg=self.colors['bg'])
            notif.resizable(False, False)
            
            # Position at top-right
            x = self.screen_width - 320
            y = 50 + len(self.notifications) * 110
            notif.geometry(f"300x100+{x}+{y}")
            
            # Notification content
            color = self.colors.get(type_, self.colors['accent'])
            tk.Label(notif, text=title, font=('Arial', 12, 'bold'),
                    bg=color, fg='white').pack(fill=tk.X)
            tk.Label(notif, text=message, font=('Arial', 10),
                    bg=self.colors['bg'], fg=self.colors['fg'],
                    wraplength=280).pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            
            self.notifications.append(notif)
            
            # Auto-close notification
            timeout = self.config.get('settings', {}).get('notification_timeout', 5000)
            notif.after(timeout, lambda: self.close_notification(notif))
            
        except Exception as e:
            print(f"Notification error: {e}")
    
    def close_notification(self, notif):
        """Close a notification"""
        try:
            if notif in self.notifications:
                self.notifications.remove(notif)
            notif.destroy()
        except:
            pass
    
    def show_login(self):
        """Show login screen"""
        self.login_window = tk.Toplevel()
        self.login_window.title("FORZEOS Enhanced Login")
        self.login_window.geometry("400x350")
        self.login_window.configure(bg=self.colors['bg'])
        self.login_window.resizable(False, False)
        
        # Center the login window
        x = (self.screen_width - 400) // 2
        y = (self.screen_height - 350) // 2
        self.login_window.geometry(f"400x350+{x}+{y}")
        
        # Login form
        tk.Label(self.login_window, text="FORZEOS Enhanced", font=('Arial', 24, 'bold'),
                bg=self.colors['bg'], fg=self.colors['fg']).pack(pady=30)
        
        tk.Label(self.login_window, text=self.translate("username") + ":", 
                bg=self.colors['bg'], fg=self.colors['fg']).pack(pady=5)
        self.username_entry = tk.Entry(self.login_window, font=('Arial', 12))
        self.username_entry.pack(pady=5)
        self.username_entry.insert(0, "admin")
        
        tk.Label(self.login_window, text=self.translate("password") + ":", 
                bg=self.colors['bg'], fg=self.colors['fg']).pack(pady=5)
        self.password_entry = tk.Entry(self.login_window, show='*', font=('Arial', 12))
        self.password_entry.pack(pady=5)
        
        tk.Button(self.login_window, text=self.translate("login"), command=self.login,
                 bg=self.colors['accent'], fg='white', font=('Arial', 12),
                 width=20, height=2).pack(pady=20)
        
        # Language selector
        lang_frame = tk.Frame(self.login_window, bg=self.colors['bg'])
        lang_frame.pack(pady=10)
        
        tk.Label(lang_frame, text="Language:", bg=self.colors['bg'], 
                fg=self.colors['fg']).pack(side=tk.LEFT, padx=5)
        
        self.language_var = tk.StringVar(value=self.current_language)
        lang_combo = ttk.Combobox(lang_frame, textvariable=self.language_var,
                                 values=["en", "tr"], width=10, state="readonly")
        lang_combo.pack(side=tk.LEFT, padx=5)
        lang_combo.bind('<<ComboboxSelected>>', self.change_language)
        
        # Bind Enter key
        self.login_window.bind('<Return>', lambda e: self.login())
        self.password_entry.focus()
        
    def change_language(self, event=None):
        """Change system language"""
        self.current_language = self.language_var.get()
        self.config['settings']['language'] = self.current_language
        self.save_config()
        
        # Update login window labels
        try:
            for widget in self.login_window.winfo_children():
                if isinstance(widget, tk.Label):
                    text = widget.cget('text')
                    if 'Username' in text or 'Kullanıcı' in text:
                        widget.config(text=self.translate("username") + ":")
                    elif 'Password' in text or 'Şifre' in text:
                        widget.config(text=self.translate("password") + ":")
                elif isinstance(widget, tk.Button):
                    if widget.cget('text') in ['Login', 'Giriş']:
                        widget.config(text=self.translate("login"))
        except:
            pass
        
    def login(self):
        """Handle user login"""
        try:
            username = self.username_entry.get()
            password = self.password_entry.get()
            
            if not username or not password:
                messagebox.showerror(self.translate("error"), 
                                   "Please enter both username and password")
                return
            
            # Check credentials
            if username in self.config['users']:
                stored_password = self.config['users'][username]['password']
                entered_password = hashlib.md5(password.encode()).hexdigest()
                
                if stored_password == entered_password:
                    self.current_user = username
                    self.login_window.destroy()
                    self.log_action("user_login", f"User {username} logged in")
                    self.create_desktop()
                    self.root.deiconify()
                    self.show_notification("Welcome", f"{self.translate('welcome')}, {username}!", "success")
                    self.load_session()
                else:
                    messagebox.showerror(self.translate("error"), "Invalid password")
            else:
                messagebox.showerror(self.translate("error"), "User not found")
                
        except Exception as e:
            print(f"Login error: {e}")
            messagebox.showerror(self.translate("error"), "Login failed")
    
    def create_desktop(self):
        """Create the main desktop environment"""
        # Configure main window
        wallpaper_color = self.config.get('settings', {}).get('wallpaper_color', '#2C3E50')
        wallpaper_image = self.config.get('settings', {}).get('wallpaper_image')
        
        # Create desktop frame
        self.desktop = tk.Frame(self.root, bg=wallpaper_color)
        self.desktop.pack(fill=tk.BOTH, expand=True)
        
        # Set wallpaper if available
        if wallpaper_image and os.path.exists(wallpaper_image) and PIL_AVAILABLE:
            self.set_wallpaper(wallpaper_image)
        else:
            self.root.configure(bg=wallpaper_color)
        
        # Create taskbar
        self.create_taskbar()
        
        # Create desktop icons
        self.create_desktop_icons()
        
        # Create widgets if enabled
        if self.config.get('settings', {}).get('show_widgets', True):
            self.create_desktop_widgets()
        
        # Start clock update
        self.update_clock()
        
        # Bind right-click for desktop menu
        self.desktop.bind("<Button-3>", self.show_desktop_menu)
        
    def set_wallpaper(self, image_path):
        """Set desktop wallpaper with proper PIL handling"""
        try:
            if not PIL_AVAILABLE:
                self.show_notification("Error", "PIL not available for wallpaper", "danger")
                return
                
            if not os.path.exists(image_path):
                self.show_notification("Error", "Wallpaper image not found", "danger")
                return
            
            # Load and resize image
            img = Image.open(image_path)
            img = img.resize((self.screen_width, self.screen_height), Image.Resampling.LANCZOS)
            
            # Convert to PhotoImage
            self.current_wallpaper = ImageTk.PhotoImage(img)
            
            # Create canvas for wallpaper
            if hasattr(self, 'wallpaper_canvas'):
                self.wallpaper_canvas.destroy()
                
            self.wallpaper_canvas = tk.Canvas(self.desktop, width=self.screen_width, 
                                            height=self.screen_height, highlightthickness=0)
            self.wallpaper_canvas.place(x=0, y=0)
            self.wallpaper_canvas.create_image(0, 0, anchor="nw", image=self.current_wallpaper)
            
            # Keep canvas in background
            self.wallpaper_canvas.lower()
            
            self.show_notification("Success", "Wallpaper set successfully", "success")
            
        except Exception as e:
            print(f"Wallpaper error: {e}")
            self.show_notification("Error", f"Failed to set wallpaper: {str(e)}", "danger")
    
    def create_taskbar(self):
        """Create enhanced taskbar"""
        self.taskbar = tk.Frame(self.root, bg=self.colors['dark'], height=60)
        self.taskbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.taskbar.pack_propagate(False)
        
        # FORZEOS button (Start menu)
        self.forze_btn = tk.Button(self.taskbar, text="FORZEOS", 
                                  command=self.show_start_menu,
                                  bg=self.colors['accent'], fg='white',
                                  font=('Arial', 12, 'bold'))
        self.forze_btn.pack(side=tk.LEFT, padx=5, pady=5)
        
        # Running apps frame
        self.running_apps_frame = tk.Frame(self.taskbar, bg=self.colors['dark'])
        self.running_apps_frame.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        
        # System info
        self.system_label = tk.Label(self.taskbar, text=f"User: {self.current_user}",
                                    bg=self.colors['dark'], fg=self.colors['fg'],
                                    font=('Arial', 10))
        self.system_label.pack(side=tk.RIGHT, padx=20)
        
        # Clock
        self.clock_label = tk.Label(self.taskbar, text="", bg=self.colors['dark'],
                                   fg=self.colors['fg'], font=('Arial', 12))
        self.clock_label.pack(side=tk.RIGHT, padx=10, pady=5)
    
    def update_clock(self):
        """Update the taskbar clock"""
        try:
            current_time = datetime.datetime.now().strftime("%H:%M:%S")
            current_date = datetime.datetime.now().strftime("%Y-%m-%d")
            self.clock_label.config(text=f"{current_date} {current_time}")
            self.root.after(1000, self.update_clock)
        except:
            pass
    
    def create_desktop_widgets(self):
        """Create desktop widgets"""
        try:
            # Clock widget
            clock_widget = tk.Frame(self.desktop, bg=self.colors['light'], relief=tk.RAISED, bd=2)
            clock_widget.place(x=self.screen_width-200, y=20, width=180, height=80)
            
            self.widget_clock = tk.Label(clock_widget, text="", font=('Arial', 16, 'bold'),
                                        bg=self.colors['light'], fg=self.colors['dark'])
            self.widget_clock.pack(expand=True)
            
            # Weather widget placeholder
            weather_widget = tk.Frame(self.desktop, bg=self.colors['light'], relief=tk.RAISED, bd=2)
            weather_widget.place(x=self.screen_width-200, y=120, width=180, height=100)
            
            tk.Label(weather_widget, text="Weather", font=('Arial', 12, 'bold'),
                    bg=self.colors['light'], fg=self.colors['dark']).pack()
            tk.Label(weather_widget, text="Loading...", font=('Arial', 10),
                    bg=self.colors['light'], fg=self.colors['dark']).pack()
            
            self.widgets.extend([clock_widget, weather_widget])
            self.update_widget_clock()
            
        except Exception as e:
            print(f"Widget creation error: {e}")
    
    def update_widget_clock(self):
        """Update desktop clock widget"""
        try:
            if hasattr(self, 'widget_clock'):
                current_time = datetime.datetime.now().strftime("%H:%M:%S")
                self.widget_clock.config(text=current_time)
                self.root.after(1000, self.update_widget_clock)
        except:
            pass
    
    def create_desktop_icons(self):
        """Create desktop application icons"""
        apps = [
            (self.translate("file_manager"), self.open_file_manager),
            (self.translate("notepad"), self.open_notepad),
            (self.translate("calculator"), self.open_calculator),
            (self.translate("terminal"), self.open_terminal),
            ("Paint", self.open_paint),
            ("Code Editor", self.open_code_editor),
            ("Snake Game", self.open_snake),
            ("Chess", self.open_chess),
            ("Web Browser", self.open_web_browser),
            ("PDF Reader", self.open_pdf_reader),
            ("Gallery", self.open_gallery),
            ("Music Player", self.open_music_player),
            ("Password Manager", self.open_password_manager),
            ("File Encryption", self.open_file_encryption),
            ("Network Scanner", self.open_network_scanner),
            ("Tic-Tac-Toe", self.open_tictactoe),
            ("Flappy Bird", self.open_flappy_bird),
            ("Math Tools", self.open_math_tools),
            # New applications
            ("Icon Manager", self.open_icon_manager),
            ("Network Tools", self.open_network_tools),
            ("QR Generator", self.open_qr_generator),
            ("Backup Tool", self.open_backup_tool),
            ("Task Manager", self.open_task_manager),
            ("Weather", self.open_weather),
            ("Secure Notes", self.open_secure_notes),
            ("System Logs", self.open_system_logs),
            # New games
            ("2048", self.open_2048),
            ("Minesweeper", self.open_minesweeper),
            ("Sudoku", self.open_sudoku),
            ("Memory Match", self.open_memory_match),
            ("Pong", self.open_pong),
            (self.translate("settings"), self.open_settings)
        ]
        
        # Adaptive grid layout
        if self.is_horizontal:
            cols = 10
            start_x = 30
            start_y = 40
            icon_width = (self.screen_width - 100) // cols
            icon_height = 100
        else:
            cols = 5
            start_x = 20
            start_y = 50
            icon_width = (self.screen_width - 80) // cols
            icon_height = 120
        
        # Create icons
        for i, (name, command) in enumerate(apps):
            col = i % cols
            row = i // cols
            
            x = start_x + col * icon_width
            y = start_y + row * icon_height
            
            self.create_desktop_icon(name, command, x, y, icon_width - 10, icon_height - 10)
    
    def create_desktop_icon(self, name, command, x, y, width=90, height=80):
        """Create a single desktop icon with drag support"""
        icon_frame = tk.Frame(self.desktop, bg=self.colors['light'], relief=tk.RAISED, bd=2)
        icon_frame.place(x=x, y=y, width=width, height=height)
        
        icon_btn = tk.Button(icon_frame, text=name, command=command,
                            bg=self.colors['light'], fg='black',
                            font=('Arial', 9, 'bold'), wraplength=width-10,
                            relief=tk.FLAT)
        icon_btn.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)
        
        # Add drag functionality
        icon_btn.bind("<Button-1>", lambda e: self.start_drag(e, icon_frame))
        icon_btn.bind("<B1-Motion>", lambda e: self.drag_icon(e, icon_frame))
        
        self.desktop_icons.append(icon_frame)
    
    def start_drag(self, event, frame):
        """Start dragging an icon"""
        self.drag_data = {"x": event.x, "y": event.y, "frame": frame}
    
    def drag_icon(self, event, frame):
        """Drag an icon to new position"""
        if hasattr(self, 'drag_data'):
            x = frame.winfo_x() - self.drag_data["x"] + event.x
            y = frame.winfo_y() - self.drag_data["y"] + event.y
            
            # Keep icon within desktop bounds
            max_x = self.screen_width - frame.winfo_width()
            max_y = self.screen_height - frame.winfo_height() - 60  # Account for taskbar
            
            x = max(0, min(x, max_x))
            y = max(0, min(y, max_y))
            
            frame.place(x=x, y=y)
    
    def show_desktop_menu(self, event):
        """Show right-click desktop menu"""
        try:
            desktop_menu = tk.Menu(self.root, tearoff=0)
            desktop_menu.add_command(label="Refresh Desktop", command=self.refresh_desktop)
            desktop_menu.add_command(label="Change Wallpaper", command=self.change_wallpaper)
            desktop_menu.add_command(label="Create Folder", command=self.create_folder)
            desktop_menu.add_separator()
            desktop_menu.add_command(label=self.translate("settings"), command=self.open_settings)
            desktop_menu.add_command(label="Task Manager", command=self.open_task_manager)
            desktop_menu.add_separator()
            desktop_menu.add_command(label=self.translate("logout"), command=self.logout)
            
            desktop_menu.post(event.x_root, event.y_root)
        except Exception as e:
            print(f"Desktop menu error: {e}")
    
    def refresh_desktop(self):
        """Refresh desktop"""
        try:
            # Clear existing icons
            for icon in self.desktop_icons:
                icon.destroy()
            self.desktop_icons.clear()
            
            # Recreate icons
            self.create_desktop_icons()
            self.show_notification("Info", "Desktop refreshed", "info")
        except Exception as e:
            print(f"Desktop refresh error: {e}")
    
    def change_wallpaper(self):
        """Change desktop wallpaper with fixed PIL handling"""
        try:
            if not PIL_AVAILABLE:
                messagebox.showerror("Error", "PIL/Pillow is required for wallpaper support")
                return
            
            # File dialog for image selection
            file_path = filedialog.askopenfilename(
                title="Select Wallpaper",
                filetypes=[
                    ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif"),
                    ("PNG files", "*.png"),
                    ("JPEG files", "*.jpg *.jpeg"),
                    ("All files", "*.*")
                ]
            )
            
            if file_path:
                try:
                    # Test if image can be opened
                    test_img = Image.open(file_path)
                    test_img.close()
                    
                    # Set wallpaper
                    self.set_wallpaper(file_path)
                    
                    # Save to config
                    self.config['settings']['wallpaper_image'] = file_path
                    self.save_config()
                    
                    self.log_action("wallpaper_changed", f"Wallpaper set to {file_path}")
                    
                except Exception as img_error:
                    messagebox.showerror("Error", f"Invalid image file: {str(img_error)}")
                    
        except Exception as e:
            print(f"Wallpaper change error: {e}")
            messagebox.showerror("Error", f"Failed to change wallpaper: {str(e)}")
    
    def create_folder(self):
        """Create new folder on desktop"""
        try:
            folder_name = simpledialog.askstring("Create Folder", "Enter folder name:")
            if folder_name:
                folder_path = os.path.join(f"{self.file_system_root}/Desktop", folder_name)
                os.makedirs(folder_path, exist_ok=True)
                self.show_notification("Success", f"Folder '{folder_name}' created", "success")
        except Exception as e:
            print(f"Folder creation error: {e}")
            messagebox.showerror("Error", "Failed to create folder")
    
    def show_start_menu(self):
        """Show enhanced start menu"""
        try:
            if hasattr(self, 'start_menu') and self.start_menu.winfo_exists():
                self.start_menu.destroy()
                return
                
            self.start_menu = tk.Toplevel()
            self.start_menu.title("Start Menu")
            self.start_menu.geometry("350x500")
            self.start_menu.configure(bg=self.colors['bg'])
            self.start_menu.resizable(False, False)
            
            # Position near FORZEOS button
            x = self.forze_btn.winfo_rootx()
            y = self.forze_btn.winfo_rooty() - 520
            self.start_menu.geometry(f"350x500+{x}+{max(0, y)}")
            
            # Menu header
            header = tk.Label(self.start_menu, text="FORZEOS Enhanced", 
                             font=('Arial', 16, 'bold'),
                             bg=self.colors['accent'], fg='white')
            header.pack(fill=tk.X, pady=(0, 10))
            
            # Create notebook for categories
            notebook = ttk.Notebook(self.start_menu)
            notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            
            # Apps tab
            apps_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(apps_frame, text="Apps")
            
            apps_list = [
                ("File Manager", self.open_file_manager),
                ("Notepad", self.open_notepad),
                ("Calculator", self.open_calculator),
                ("Terminal", self.open_terminal),
                ("Web Browser", self.open_web_browser),
                ("Paint", self.open_paint),
                ("Code Editor", self.open_code_editor)
            ]
            
            for name, command in apps_list:
                btn = tk.Button(apps_frame, text=name, command=command,
                               bg=self.colors['light'], fg='black',
                               font=('Arial', 10), width=30, height=1)
                btn.pack(pady=2, padx=10, fill=tk.X)
            
            # Games tab
            games_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(games_frame, text="Games")
            
            games_list = [
                ("Snake", self.open_snake),
                ("Chess", self.open_chess),
                ("Tic-Tac-Toe", self.open_tictactoe),
                ("Flappy Bird", self.open_flappy_bird),
                ("2048", self.open_2048),
                ("Minesweeper", self.open_minesweeper),
                ("Sudoku", self.open_sudoku),
                ("Memory Match", self.open_memory_match),
                ("Pong", self.open_pong)
            ]
            
            for name, command in games_list:
                btn = tk.Button(games_frame, text=name, command=command,
                               bg=self.colors['light'], fg='black',
                               font=('Arial', 10), width=30, height=1)
                btn.pack(pady=2, padx=10, fill=tk.X)
            
            # Tools tab
            tools_frame = tk.Frame(notebook, bg=self.colors['bg'])
            notebook.add(tools_frame, text="Tools")
            
            tools_list = [
                ("Network Tools", self.open_network_tools),
                ("QR Generator", self.open_qr_generator),
                ("Backup Tool", self.open_backup_tool),
                ("Task Manager", self.open_task_manager),
                ("Icon Manager", self.open_icon_manager),
                ("Password Manager", self.open_password_manager),
                ("File Encryption", self.open_file_encryption),
                ("System Logs", self.open_system_logs)
            ]
            
            for name, command in tools_list:
                btn = tk.Button(tools_frame, text=name, command=command,
                               bg=self.colors['light'], fg='black',
                               font=('Arial', 10), width=30, height=1)
                btn.pack(pady=2, padx=10, fill=tk.X)
            
            # System buttons
            system_frame = tk.Frame(self.start_menu, bg=self.colors['bg'])
            system_frame.pack(fill=tk.X, padx=10, pady=5)
            
            tk.Button(system_frame, text=self.translate("settings"), command=self.open_settings,
                     bg=self.colors['warning'], fg='white', font=('Arial', 10, 'bold'),
                     width=15).pack(side=tk.LEFT, padx=5)
            
            tk.Button(system_frame, text=self.translate("logout"), command=self.logout,
                     bg=self.colors['danger'], fg='white', font=('Arial', 10, 'bold'),
                     width=15).pack(side=tk.RIGHT, padx=5)
            
        except Exception as e:
            print(f"Start menu error: {e}")
    
    def save_session(self):
        """Save current session state"""
        try:
            session_data = {
                'user': self.current_user,
                'running_apps': list(self.running_apps.keys()),
                'timestamp': datetime.datetime.now().isoformat()
            }
            
            with open(self.session_file, 'w') as f:
                json.dump(session_data, f, indent=2)
                
        except Exception as e:
            print(f"Session save error: {e}")
    
    def load_session(self):
        """Load and restore previous session"""
        try:
            if os.path.exists(self.session_file):
                with open(self.session_file, 'r') as f:
                    session_data = json.load(f)
                
                if session_data.get('user') == self.current_user:
                    # Auto-start configured apps
                    startup_apps = self.config.get('settings', {}).get('startup_apps', [])
                    for app in startup_apps:
                        if hasattr(self, f'open_{app.lower().replace(" ", "_")}'):
                            threading.Thread(target=getattr(self, f'open_{app.lower().replace(" ", "_")}'), daemon=True).start()
                            
        except Exception as e:
            print(f"Session load error: {e}")
    
    def logout(self):
        """Handle user logout"""
        try:
            self.save_session()
            self.log_action("user_logout", f"User {self.current_user} logged out")
            
            # Close all running apps
            for app_window in list(self.windows.values()):
                try:
                    app_window.destroy()
                except:
                    pass
            
            self.windows.clear()
            self.running_apps.clear()
            self.current_user = None
            
            # Clear notifications
            for notif in self.notifications:
                try:
                    notif.destroy()
                except:
                    pass
            self.notifications.clear()
            
            self.root.withdraw()
            self.show_login()
            
        except Exception as e:
            print(f"Logout error: {e}")
    
    # ==================== APPLICATION IMPLEMENTATIONS ====================
    
    def open_file_manager(self):
        """Enhanced File Manager with improved features"""
        if "File Manager" in self.running_apps:
            self.windows["File Manager"].lift()
            return
            
        window = tk.Toplevel()
        window.title("File Manager")
        window.geometry("800x600")
        window.configure(bg=self.colors['bg'])
        
        self.running_apps["File Manager"] = True
        self.windows["File Manager"] = window
        
        # Current path
        self.current_path = os.path.abspath(self.file_system_root)
        
        # Toolbar
        toolbar = tk.Frame(window, bg=self.colors['dark'])
        toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Button(toolbar, text="Back", command=self.go_back,
                 bg=self.colors['light'], font=('Arial', 10)).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="Home", command=self.go_home,
                 bg=self.colors['light'], font=('Arial', 10)).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="New Folder", command=self.new_folder,
                 bg=self.colors['success'], fg='white', font=('Arial', 10)).pack(side=tk.LEFT, padx=2)
        tk.Button(toolbar, text="Search", command=self.advanced_search,
                 bg=self.colors['accent'], fg='white', font=('Arial', 10)).pack(side=tk.LEFT, padx=2)
        
        # Path bar
        path_frame = tk.Frame(window, bg=self.colors['bg'])
        path_frame.pack(fill=tk.X, padx=5)
        
        tk.Label(path_frame, text="Path:", bg=self.colors['bg'], 
                fg=self.colors['fg']).pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value=self.current_path)
        self.path_entry = tk.Entry(path_frame, textvariable=self.path_var, font=('Arial', 10))
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.path_entry.bind('<Return>', self.navigate_to_path)
        
        # File list with treeview
        list_frame = tk.Frame(window)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Create treeview
        columns = ('Name', 'Size', 'Type', 'Modified')
        self.file_tree = ttk.Treeview(list_frame, columns=columns, show='headings')
        
        # Configure columns
        self.file_tree.heading('Name', text='Name')
        self.file_tree.heading('Size', text='Size')
        self.file_tree.heading('Type', text='Type')
        self.file_tree.heading('Modified', text='Modified')
        
        self.file_tree.column('Name', width=300)
        self.file_tree.column('Size', width=100)
        self.file_tree.column('Type', width=100)
        self.file_tree.column('Modified', width=150)
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.file_tree.xview)
        self.file_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # Pack components
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Bind events
        self.file_tree.bind('<Double-1>', self.open_file_or_folder)
        self.file_tree.bind('<Button-3>', self.show_file_context_menu)
        
        # Status bar
        self.status_bar = tk.Label(window, text="Ready", relief=tk.SUNKEN,
                                  bg=self.colors['light'], fg='black')
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        
        # Load initial directory
        self.refresh_file_list()
        
        # Cleanup on close
        window.protocol("WM_DELETE_WINDOW", lambda: self.close_app("File Manager"))
        
        self.log_action("app_opened", "File Manager opened")
    
    def refresh_file_list(self):
        """Refresh file list in file manager"""
        try:
            # Clear current items
            for item in self.file_tree.get_children():
                self.file_tree.delete(item)
            
            # Add parent directory entry
            if self.current_path != os.path.dirname(self.current_path):
                self.file_tree.insert('', 'end', values=('..', '', 'Directory', ''))
            
            # List directory contents
            try:
                items = os.listdir(self.current_path)
                file_count = 0
                folder_count = 0
                
                for item in sorted(items):
                    item_path = os.path.join(self.current_path, item)
                    
                    if os.path.isdir(item_path):
                        item_type = "Directory"
                        size = ""
                        folder_count += 1
                    else:
                        item_type = "File"
                        try:
                            size = f"{os.path.getsize(item_path)} bytes"
                        except:
                            size = "Unknown"
                        file_count += 1
                    
                    try:
                        modified = datetime.datetime.fromtimestamp(
                            os.path.getmtime(item_path)).strftime("%Y-%m-%d %H:%M")
                    except:
                        modified = "Unknown"
                    
                    self.file_tree.insert('', 'end', values=(item, size, item_type, modified))
                
                # Update status bar
                self.status_bar.config(text=f"{folder_count} folders, {file_count} files")
                
            except PermissionError:
                self.status_bar.config(text="Permission denied")
                messagebox.showerror("Error", "Permission denied to access this directory")
            except Exception as e:
                self.status_bar.config(text=f"Error: {str(e)}")
                
        except Exception as e:
            print(f"File list refresh error: {e}")
    
    def go_back(self):
        """Go to parent directory"""
        parent = os.path.dirname(self.current_path)
        if parent != self.current_path:
            self.current_path = parent
            self.path_var.set(self.current_path)
            self.refresh_file_list()
    
    def go_home(self):
        """Go to home directory"""
        self.current_path = os.path.abspath(self.file_system_root)
        self.path_var.set(self.current_path)
        self.refresh_file_list()
    
    def navigate_to_path(self, event=None):
        """Navigate to entered path"""
        new_path = self.path_var.get()
        if os.path.exists(new_path) and os.path.isdir(new_path):
            self.current_path = os.path.abspath(new_path)
            self.refresh_file_list()
        else:
            messagebox.showerror("Error", "Invalid path")
            self.path_var.set(self.current_path)
    
    def open_file_or_folder(self, event):
        """Open selected file or folder"""
        try:
            selection = self.file_tree.selection()
            if not selection:
                return
            
            item = self.file_tree.item(selection[0])
            name = item['values'][0]
            
            if name == '..':
                self.go_back()
                return
            
            item_path = os.path.join(self.current_path, name)
            
            if os.path.isdir(item_path):
                self.current_path = item_path
                self.path_var.set(self.current_path)
                self.refresh_file_list()
            else:
                # Try to open file with appropriate application
                self.open_file_with_app(item_path)
                
        except Exception as e:
            print(f"File open error: {e}")
    
    def open_file_with_app(self, file_path):
        """Open file with appropriate application"""
        try:
            ext = os.path.splitext(file_path)[1].lower()
            
            if ext in ['.txt', '.py', '.json', '.html', '.css', '.js']:
                self.open_notepad(file_path)
            elif ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                self.open_gallery(file_path)
            elif ext == '.pdf':
                self.open_pdf_reader(file_path)
            elif ext in ['.mp3', '.wav', '.ogg']:
                self.open_music_player(file_path)
            else:
                # Try system default
                try:
                    os.startfile(file_path)  # Windows
                except:
                    try:
                        subprocess.run(['xdg-open', file_path])  # Linux
                    except:
                        messagebox.showinfo("Info", f"Cannot open file: {file_path}")
                        
        except Exception as e:
            print(f"File app open error: {e}")
            messagebox.showerror("Error", f"Failed to open file: {str(e)}")
    
    def new_folder(self):
        """Create new folder"""
        try:
            folder_name = simpledialog.askstring("New Folder", "Enter folder name:")
            if folder_name:
                folder_path = os.path.join(self.current_path, folder_name)
                os.makedirs(folder_path, exist_ok=True)
                self.refresh_file_list()
                self.show_notification("Success", f"Folder '{folder_name}' created", "success")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create folder: {str(e)}")
    
    def advanced_search(self):
        """Open advanced file search dialog"""
        try:
            search_window = tk.Toplevel()
            search_window.title("Advanced File Search")
            search_window.geometry("500x400")
            search_window.configure(bg=self.colors['bg'])
            
            # Search criteria
            criteria_frame = tk.LabelFrame(search_window, text="Search Criteria",
                                         bg=self.colors['bg'], fg=self.colors['fg'])
            criteria_frame.pack(fill=tk.X, padx=10, pady=10)
            
            tk.Label(criteria_frame, text="File name:", bg=self.colors['bg'], 
                    fg=self.colors['fg']).grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
            name_entry = tk.Entry(criteria_frame, width=30)
            name_entry.grid(row=0, column=1, padx=5, pady=5)
            
            tk.Label(criteria_frame, text="File type:", bg=self.colors['bg'], 
                    fg=self.colors['fg']).grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
            type_combo = ttk.Combobox(criteria_frame, values=['All', '.txt', '.py', '.pdf', '.png', '.jpg', '.mp3'],
                                     width=27)
            type_combo.set('All')
            type_combo.grid(row=1, column=1, padx=5, pady=5)
            
            tk.Label(criteria_frame, text="Search in:", bg=self.colors['bg'], 
                    fg=self.colors['fg']).grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
            path_entry = tk.Entry(criteria_frame, width=30)
            path_entry.insert(0, self.current_path)
            path_entry.grid(row=2, column=1, padx=5, pady=5)
            
            # Results
            results_frame = tk.LabelFrame(search_window, text="Search Results",
                                        bg=self.colors['bg'], fg=self.colors['fg'])
            results_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            results_listbox = tk.Listbox(results_frame, bg='white', font=('Arial', 10))
            results_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            
            # Search function
            def perform_search():
                results_listbox.delete(0, tk.END)
                search_name = name_entry.get().lower()
                search_type = type_combo.get()
                search_path = path_entry.get()
                
                if not os.path.exists(search_path):
                    messagebox.showerror("Error", "Invalid search path")
                    return
                
                found_files = []
                try:
                    for root, dirs, files in os.walk(search_path):
                        for file in files:
                            if search_name in file.lower() or not search_name:
                                if search_type == 'All' or file.lower().endswith(search_type.lower()):
                                    found_files.append(os.path.join(root, file))
                    
                    for file_path in found_files[:100]:  # Limit to 100 results
                        results_listbox.insert(tk.END, file_path)
                    
                    if len(found_files) > 100:
                        results_listbox.insert(tk.END, f"... and {len(found_files) - 100} more files")
                    
                    if not found_files:
                        results_listbox.insert(tk.END, "No files found")
                        
                except Exception as e:
                    messagebox.showerror("Error", f"Search failed: {str(e)}")
            
            # Search button
            tk.Button(criteria_frame, text="Search", command=perform_search,
                     bg=self.colors['accent'], fg='white', font=('Arial', 10, 'bold')).grid(row=3, column=1, pady=10)
            
            # Open selected result
            def open_selected():
                selection = results_listbox.curselection()
                if selection:
                    file_path = results_listbox.get(selection[0])
                    if os.path.exists(file_path):
                        self.open_file_with_app(file_path)
            
            results_listbox.bind('<Double-1>', lambda e: open_selected())
            
        except Exception as e:
            print(f"Advanced search error: {e}")
            messagebox.showerror("Error", "Failed to open search dialog")
    
    def show_file_context_menu(self, event):
        """Show context menu for files"""
        try:
            selection = self.file_tree.selection()
            if not selection:
                return
            
            context_menu = tk.Menu(self.root, tearoff=0)
            context_menu.add_command(label="Open", command=lambda: self.open_file_or_folder(None))
            context_menu.add_command(label="Copy", command=self.copy_file)
            context_menu.add_command(label="Cut", command=self.cut_file)
            context_menu.add_command(label="Delete", command=self.delete_file)
            context_menu.add_separator()
            context_menu.add_command(label="Properties", command=self.show_file_properties)
            
            context_menu.post(event.x_root, event.y_root)
        except Exception as e:
            print(f"Context menu error: {e}")
    
    def copy_file(self):
        """Copy selected file"""
        # Implementation for copy functionality
        self.show_notification("Info", "Copy functionality not yet implemented", "info")
    
    def cut_file(self):
        """Cut selected file"""
        # Implementation for cut functionality
        self.show_notification("Info", "Cut functionality not yet implemented", "info")
    
    def delete_file(self):
        """Delete selected file"""
        