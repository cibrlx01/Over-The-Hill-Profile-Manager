"""Over the Hill profile manager — local desktop interface."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import subprocess
import queue
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

from profile_core import Manager

BG = '#f5f7f4'
PANEL = '#ffffff'
FG = '#263328'
MUTED = '#687369'
ACCENT = '#496b43'
APP_DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'OverTheHillProfileManager'
DESCRIPTIONS = {}


def normalize_root(path):
    path = Path(path).expanduser()
    return path.parent if path.name.casefold() == 'saves' else path


def detect_root():
    candidates = []
    if os.name == 'nt':
        try:
            import ctypes
            buffer = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:
                candidates.append(Path(buffer.value))
        except (OSError, AttributeError):
            pass
    candidates.extend([Path(os.environ.get('OneDrive', str(Path.home() / 'OneDrive'))) / 'Documents', Path.home() / 'Documents'])
    for documents in candidates:
        root = documents / 'My games/over the hill'
        if (root / 'Saves/Player1.json').is_file():
            return root
    return candidates[0] / 'My games/over the hill' if candidates else Path.home() / 'Documents/My games/over the hill'


def saved_root():
    try:
        value = json.loads((APP_DATA / 'settings.json').read_text(encoding='utf-8'))['root']
        return normalize_root(value)
    except (OSError, ValueError, KeyError, TypeError):
        return detect_root()


def remember_root(root):
    APP_DATA.mkdir(parents=True, exist_ok=True)
    temporary = APP_DATA / 'settings.json.tmp'
    temporary.write_text(json.dumps({'root': str(root)}, indent=2), encoding='utf-8')
    os.replace(temporary, APP_DATA / 'settings.json')



def format_last_played(value):
    if not value:
        return '-'
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).strftime('%Y-%m-%d - %H:%M')
    except (ValueError, TypeError):
        return '-'


class SwitchPreviewDialog:
    """Read-only review; the caller commits only after an explicit confirmation."""
    def __init__(self, app, preview):
        self.app = app
        self.preview = preview
        self.result = False
        self.closed = False
        self.after_id = None
        self.window = tk.Toplevel(app.window)
        self.window.title('Review profile switch')
        self.window.configure(bg=BG)
        self.window.transient(app.window)
        width = min(1080, app.window.winfo_screenwidth() - 80)
        height = min(760, app.window.winfo_screenheight() - 100)
        self.window.geometry(f'{width}x{height}')
        self.window.minsize(min(850, width), min(550, height))
        self.window.protocol('WM_DELETE_WINDOW', self.cancel)
        self.window.bind('<Escape>', lambda _event: self.cancel())
        self.window.bind('<Destroy>', self.destroyed, add='+')
        shell = ttk.Frame(self.window, padding=20)
        shell.pack(fill='both', expand=True)
        ttk.Label(shell, text='Review your switch', style='Title.TLabel').pack(anchor='w')
        ttk.Label(shell, text=f'{preview["active"]}  ->  {preview["target"]}', style='Current.TLabel').pack(anchor='w', pady=(10, 12))
        if preview['allow_empty']:
            ttk.Label(shell, text='FRESH START: after backing up your outgoing journey, the two live save files will be removed. The game will create a new save for this empty profile.', wraplength=width - 60, font=('Segoe UI', 11, 'bold'), foreground='#8b4c23').pack(anchor='w', pady=(0, 10))
        self.initial = not preview.get('initialized', False)
        explanation = 'Initial combine: distances from separate journeys will be added. Copied profiles may contain overlapping driving; review before continuing.' if self.initial else 'Only new driving since the previous sync is added. All distances below are kilometers.'
        ttk.Label(shell, text=explanation, style='Muted.TLabel', wraplength=width - 60).pack(anchor='w', pady=(0, 10))
        ttk.Label(shell, text='Vehicles absent from the destination stay locked. Their accumulated distance is retained; this does not unlock them.', style='Muted.TLabel', wraplength=width - 60).pack(anchor='w', pady=(0, 10))
        bottom = ttk.Frame(shell)
        bottom.pack(side='bottom', fill='x', pady=(14, 0))
        self.confirm_button = ttk.Button(bottom, text='Sync & Switch', command=self.confirm)
        self.confirm_button.pack(side='right')
        ttk.Button(bottom, text='Cancel', command=self.cancel).pack(side='right', padx=10)
        self.game_label = ttk.Label(bottom, text='', style='Muted.TLabel', wraplength=520)
        self.game_label.pack(side='left', fill='x', expand=True)
        total = sum(float(row.get('combined_meters', 0) if self.initial else row.get('new_meters', 0)) for row in preview.get('rows', [])) / 1000
        ttk.Label(shell, text=f'{"Initial combined distance" if self.initial else "Total new driving"}: {total:,.2f} km', style='Active.TLabel').pack(side='bottom', anchor='w', pady=(12, 0))
        self.show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(shell, text='Show all vehicles (including unchanged)', variable=self.show_all, command=self.render).pack(anchor='w', pady=(0, 10))
        container = ttk.Frame(shell)
        container.pack(fill='both', expand=True)
        columns = ('vehicle', 'current', 'new', 'updated', 'destination')
        self.tree = ttk.Treeview(container, columns=columns, show='headings', selectmode='browse')
        headings = ('Vehicle', 'Current combined km', 'Initial combine km' if self.initial else 'New driving +km', 'Updated km', 'Destination status')
        for column, title, size in zip(columns, headings, (240, 155, 155, 140, 260)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=size, minwidth=100, stretch=False, anchor='w' if column in ('vehicle', 'destination') else 'e')
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(container, orient='vertical', command=self.tree.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(container, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self.render()
        self.check_game()

    def render(self):
        self.tree.delete(*self.tree.get_children())
        rows = sorted(self.preview.get('rows', []), key=lambda row: (-float(row.get('combined_meters', 0) if self.initial else row.get('new_meters', 0)), str(row['vehicle_id'])))
        for row in rows:
            new = float(row.get('combined_meters', 0) if self.initial else row.get('new_meters', 0))
            if not self.show_all.get() and new <= 0:
                continue
            updated = float(row.get('combined_meters', 0))
            current = float(row.get('current_meters', 0 if self.initial else max(0, updated - new)))
            vid = str(row['vehicle_id'])
            name = self.app.names.get(vid, 'Unknown vehicle')
            locked = row.get('profiles', {}).get(self.preview['target']) is None
            status = 'Locked / absent — distance retained' if locked else 'Owned — mileage updated'
            self.tree.insert('', 'end', iid=vid, values=(name, f'{current / 1000:,.2f}', f'{new / 1000:,.2f}', f'{updated / 1000:,.2f}', status))

    def check_game(self):
        if self.closed:
            return
        safe = self.app.game_state is False and self.app.backup_ready and not self.app.state.get('recovery_required')
        self.confirm_button.configure(state='normal' if safe else 'disabled')
        self.game_label.configure(text='Close the game before confirming.' if self.app.game_state else 'Game status unavailable; switching paused.' if self.app.game_state is None else 'Ready. Mileage sync, backup, and switching are saved together.')
        self.after_id = self.window.after(200, self.check_game)

    def confirm(self):
        if self.app.game_state is not False or not self.app.backup_ready or self.app.state.get('recovery_required'):
            return
        self.result = True
        self.window.destroy()

    def cancel(self):
        self.result = False
        self.window.destroy()

    def destroyed(self, event):
        if event.widget is not self.window:
            return
        self.closed = True
        if self.after_id is not None:
            try:
                self.window.after_cancel(self.after_id)
            except tk.TclError:
                pass

    def show(self):
        self.window.wait_visibility()
        self.window.grab_set()
        self.window.wait_window()
        return self.result


class ProfileApp:
    def __init__(self, window, root, startup_backup=True, poll_game=True, quiet=False):
        self.window = window
        self.quiet = quiet
        self.root = normalize_root(root)
        self.manager = Manager(self.root)
        self.startup_backup_enabled = startup_backup
        self.backup_ready = not startup_backup
        self.game_state = None
        self.game_results = queue.Queue()
        self.game_worker_busy = False
        self.game_next_poll = 0
        self.game_after = None
        self.closed = False
        self.selected = tk.StringVar(value='')
        self.units = tk.StringVar(value='km')
        self.status_text = tk.StringVar()
        self.active_text = tk.StringVar()
        self.game_text = tk.StringVar(value='Game - Checking…')
        self.profile_detail = tk.StringVar()
        self.mileage_note = tk.StringVar()
        self.total_distance_text = tk.StringVar(value='Total Distance KM: —')
        self.combined_card_text = tk.StringVar(value='— km')
        self.new_card_text = tk.StringVar(value='— km')
        self.new_card_title = tk.StringVar(value='NEW DRIVING SINCE SYNC')
        self.preview = None
        self.names = {}
        for name_path in (Path(__file__).parent / 'vehicle_names.json', APP_DATA / 'vehicle_names.json'):
            try:
                labels = json.loads(name_path.read_text(encoding='utf-8'))
                if isinstance(labels, dict):
                    self.names.update({key: value for key, value in labels.items() if isinstance(key, str) and isinstance(value, str) and value.strip()})
            except (OSError, ValueError):
                pass
        self.setup_style()
        window.title('Over the Hill · Profile Manager')
        screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
        initial_w, initial_h = min(1320, screen_w - 60), min(900, screen_h - 90)
        window.geometry(f'{initial_w}x{initial_h}')
        window.minsize(min(880, initial_w), min(820, initial_h))
        window.configure(bg=BG)
        shell = ttk.Frame(window, padding=16)
        shell.pack(fill='both', expand=True)
        ttk.Label(shell, text='OVER THE HILL', style='Eyebrow.TLabel').pack(anchor='w')
        ttk.Label(shell, text='Your profiles', style='Title.TLabel').pack(anchor='w', pady=(5, 8))
        banner = ttk.Frame(shell, style='Banner.TFrame', padding=(20, 14))
        banner.pack(fill='x', pady=(12, 16))
        self.game_badge = ttk.Label(banner, textvariable=self.game_text, style='UnknownBadge.TLabel', padding=(16, 10))
        self.game_badge.pack(side='right', padx=(20, 0))
        ttk.Label(banner, text='CURRENT JOURNEY', style='BannerEyebrow.TLabel').pack(anchor='w')
        ttk.Label(banner, textvariable=self.active_text, style='BannerTitle.TLabel').pack(anchor='w', pady=(4, 0))
        self.bind_panel = ttk.Frame(shell, style='Card.TFrame', padding=14)
        self.root_text = tk.StringVar(value=str(self.root))
        ttk.Label(self.bind_panel, text='First setup · choose your game save folder', style='CardTitle.TLabel').grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(self.bind_panel, textvariable=self.root_text, style='CardMuted.TLabel', wraplength=700).grid(row=1, column=0, columnspan=2, sticky='w', pady=5)
        ttk.Button(self.bind_panel, text='Browse…', command=self.browse_root).grid(row=1, column=2, padx=8)
        ttk.Label(self.bind_panel, text='Select the game folder or its Saves folder. Profiles are stored in the sibling BackupSaves folder.', style='CardMuted.TLabel', wraplength=720).grid(row=2, column=0, columnspan=3, sticky='w')
        self.setup_name = tk.StringVar(value='Main Profile')
        self.setup_description = tk.StringVar()
        ttk.Label(self.bind_panel, text='Profile name', style='Card.TLabel').grid(row=3, column=0, sticky='w', pady=(10, 2))
        ttk.Entry(self.bind_panel, textvariable=self.setup_name, width=26).grid(row=4, column=0, sticky='ew', padx=(0, 12))
        ttk.Label(self.bind_panel, text='Description (optional)', style='Card.TLabel').grid(row=3, column=1, sticky='w', pady=(10, 2))
        ttk.Entry(self.bind_panel, textvariable=self.setup_description, width=36).grid(row=4, column=1, sticky='ew')
        self.bind_button = ttk.Button(self.bind_panel, text='Create profile from current save', style='Primary.TButton', command=self.bind_current)
        self.bind_button.grid(row=4, column=2, padx=(12, 0))
        self.bind_panel.columnconfigure(1, weight=1)
        self.tabs = ttk.Notebook(shell)
        self.build_profiles()
        self.build_mileage()
        footer = ttk.Frame(shell)
        footer.pack(side='bottom', fill='x')
        self.play_button = ttk.Button(footer, text='Play Game', style='Primary.TButton', command=self.play_game)
        self.play_button.pack(side='right')
        ttk.Button(footer, text='Refresh', command=self.refresh).pack(side='right', padx=8)
        self.recover_button = ttk.Button(footer, text='Recover interrupted change', command=self.recover)
        ttk.Label(footer, textvariable=self.status_text, style='Muted.TLabel', wraplength=580).pack(side='left', fill='x', expand=True)
        self.tabs.pack(fill='both', expand=True, pady=(8, 14))
        self.refresh()
        window.bind('<Destroy>', self.on_destroy, add='+')
        if poll_game:
            self.poll_game()
        else:
            self.game_text.set('Game - Checking')

    def on_destroy(self, event):
        if event.widget is not self.window:
            return
        self.closed = True
        if self.game_after is not None:
            try:
                self.window.after_cancel(self.game_after)
            except tk.TclError:
                pass

    def update_controls(self):
        state = getattr(self, 'state', {})
        safe = self.backup_ready and not state.get('recovery_required') and self.game_state is False
        for button in (self.switch_button, self.capture_button, self.sync_button):
            button.configure(state='normal' if safe and bool(getattr(self, 'active', None)) else 'disabled')
        for button in (self.add_button, self.rename_button, self.description_button):
            button.configure(state='normal' if safe and bool(getattr(self, 'active', None)) else 'disabled')
        self.bind_button.configure(state='normal' if self.game_state is False and not state.get('recovery_required') else 'disabled')
        self.recover_button.configure(state='normal' if self.game_state is False else 'disabled')
        self.play_button.configure(state='normal' if safe else 'disabled')

    def poll_game(self):
        if self.closed:
            return
        try:
            while True:
                running, error = self.game_results.get_nowait()
                self.game_worker_busy = False
                self.game_state = running
                self.game_text.set('Game - Unavailable' if error else 'Game - Running' if running else 'Game - Closed')
                self.game_badge.configure(style='UnknownBadge.TLabel' if error else 'RunningBadge.TLabel' if running else 'ClosedBadge.TLabel')
                self.update_controls()
        except queue.Empty:
            pass
        if not self.game_worker_busy and time.monotonic() >= self.game_next_poll:
            self.game_worker_busy = True
            self.game_next_poll = time.monotonic() + 3
            def worker():
                try:
                    self.game_results.put((self.manager.game_running(), None))
                except Exception as exc:
                    self.game_results.put((None, str(exc)))
            threading.Thread(target=worker, daemon=True, name='game-status').start()
        self.game_after = self.window.after(150, self.poll_game)

    def setup_style(self):
        s = ttk.Style(self.window)
        s.theme_use('clam')
        s.configure('.', background=BG, foreground=FG, font=('Segoe UI', 10))
        s.configure('TFrame', background=BG)
        s.configure('TLabel', background=BG, foreground=FG)
        s.configure('Muted.TLabel', foreground=MUTED)
        s.configure('Eyebrow.TLabel', foreground=ACCENT, font=('Segoe UI', 10, 'bold'))
        s.configure('Title.TLabel', font=('Segoe UI', 20, 'bold'))
        s.configure('Active.TLabel', foreground=ACCENT, font=('Segoe UI Semibold', 12))
        s.configure('Current.TLabel', foreground=ACCENT, font=('Segoe UI', 16, 'bold'))
        s.configure('GameStatus.TLabel', foreground=FG, font=('Segoe UI', 12, 'bold'))
        s.configure('Card.TFrame', background=PANEL)
        s.configure('Card.TLabel', background=PANEL)
        s.configure('CardTitle.TLabel', background=PANEL, font=('Segoe UI Semibold', 15))
        s.configure('CardMuted.TLabel', background=PANEL, foreground=MUTED)
        s.configure('Metric.TLabel', background=PANEL, foreground='#304b36', font=('Segoe UI', 22, 'bold'))
        s.configure('MetricEyebrow.TLabel', background=PANEL, foreground=MUTED, font=('Segoe UI', 9, 'bold'))
        s.configure('Banner.TFrame', background='#e0e9dc')
        s.configure('BannerEyebrow.TLabel', background='#e0e9dc', foreground='#61735e', font=('Segoe UI', 9, 'bold'))
        s.configure('BannerTitle.TLabel', background='#e0e9dc', foreground='#2e4732', font=('Segoe UI', 25, 'bold'))
        s.configure('UnknownBadge.TLabel', background='#eadfbe', foreground='#745a26', font=('Segoe UI', 10, 'bold'))
        s.configure('RunningBadge.TLabel', background='#f1ddb6', foreground='#75511c', font=('Segoe UI', 10, 'bold'))
        s.configure('ClosedBadge.TLabel', background='#cbdcbe', foreground='#2e4d2c', font=('Segoe UI', 10, 'bold'))
        s.configure('TButton', background='#e8ede5', foreground=FG, padding=(12, 6), borderwidth=1)
        s.map('TButton', background=[('active', '#dce6d6'), ('disabled', '#eeeeec')], foreground=[('disabled', '#90958e')])
        s.configure('Primary.TButton', background='#385540', foreground='#ffffff', font=('Segoe UI', 10, 'bold'), padding=(18, 9))
        s.map('Primary.TButton', background=[('active', '#486b4f'), ('disabled', '#dce2d9')], foreground=[('disabled', '#889184')])
        s.configure('TRadiobutton', background=PANEL, padding=8)
        s.map('TRadiobutton', background=[('active', PANEL)])
        s.configure('TNotebook', background=BG, borderwidth=0)
        s.configure('TNotebook.Tab', background=PANEL, foreground=FG, padding=(20, 12))
        s.map('TNotebook.Tab', background=[('selected', '#dce6d6')])
        s.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=32, borderwidth=0)
        s.configure('Treeview.Heading', background='#e8ede5', foreground=FG, padding=8)
        s.map('Treeview', background=[('selected', '#6b8266')], foreground=[('selected', '#ffffff')])

    def build_profiles(self):
        page = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(page, text='Profiles')
        header = ttk.Frame(page, style='Card.TFrame', padding=(16, 12))
        header.pack(fill='x', pady=(0, 1))
        self.add_button = ttk.Button(header, text='+  Add Profile', command=self.add_profile)
        self.add_button.pack(side='right')
        self.rename_button = ttk.Button(header, text='Rename', command=self.rename_profile)
        self.rename_button.pack(side='right', padx=8)
        self.description_button = ttk.Button(header, text='Edit description', command=self.edit_description)
        self.description_button.pack(side='right')
        ttk.Label(header, text='Your journeys', style='CardTitle.TLabel').pack(anchor='w')
        ttk.Label(header, text='Choose a profile to continue your journey.', style='CardMuted.TLabel').pack(anchor='w', pady=(4, 0))
        summaries = ttk.Frame(page)
        summaries.pack(side='bottom', fill='x', pady=(14, 0))
        summaries.columnconfigure(0, weight=1)
        summaries.columnconfigure(1, weight=1)
        for column, title, value in [(0, 'COMBINED DISTANCE', self.combined_card_text), (1, self.new_card_title, self.new_card_text)]:
            card = ttk.Frame(summaries, style='Card.TFrame', padding=(18, 14))
            card.grid(row=0, column=column, sticky='nsew', padx=(0, 7) if column == 0 else (7, 0))
            kwargs = {'textvariable': title} if isinstance(title, tk.Variable) else {'text': title}
            ttk.Label(card, style='MetricEyebrow.TLabel', **kwargs).pack(anchor='w')
            ttk.Label(card, textvariable=value, style='Metric.TLabel').pack(anchor='w', pady=(5, 0))
        row = ttk.Frame(page, style='Card.TFrame', padding=(14, 10))
        row.pack(side='bottom', fill='x')
        self.switch_button = ttk.Button(row, text='Switch Profile', style='Primary.TButton', command=self.switch)
        self.switch_button.pack(side='left')
        self.capture_button = ttk.Button(row, text='Back Up Profile', command=self.capture)
        self.capture_button.pack(side='left', padx=8)
        ttk.Button(row, text='Open Saves', command=lambda: self.open_folder(self.root / 'Saves')).pack(side='right')
        ttk.Button(row, text='Open Backups', command=lambda: self.open_folder(self.root / 'BackupSaves')).pack(side='right', padx=8)
        ttk.Label(page, textvariable=self.profile_detail, style='Muted.TLabel', wraplength=800).pack(side='bottom', anchor='w', pady=8)
        container = ttk.Frame(page)
        container.pack(fill='both', expand=True)
        self.profile_tree = ttk.Treeview(container, columns=('name','state','vehicles','last_played','total_distance','description'), show='headings', selectmode='browse', height=5)
        for col, title, width in [('name','Profile',160),('state','Save status',190),('vehicles','Vehicles',95),('last_played','Last played',210),('total_distance','Total Distance KM',175),('description','Description',260)]:
            self.profile_tree.heading(col,text=title)
            self.profile_tree.column(col,width=width,minwidth=80,stretch=False)
        self.profile_tree.grid(row=0,column=0,sticky='nsew')
        scroll = ttk.Scrollbar(container,orient='vertical',command=self.profile_tree.yview)
        scroll.grid(row=0,column=1,sticky='ns')
        self.profile_tree.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(container,orient='horizontal',command=self.profile_tree.xview)
        horizontal.grid(row=1,column=0,sticky='ew')
        self.profile_tree.configure(xscrollcommand=horizontal.set)
        container.columnconfigure(0,weight=1)
        container.rowconfigure(0,weight=1)
        self.profile_tree.bind('<<TreeviewSelect>>', self.select_profile)
        self.profile_tree.tag_configure('even', background='#ffffff')
        self.profile_tree.tag_configure('odd', background='#f6f8f3')
        self.profile_tree.tag_configure('current', background='#deead7', foreground='#34513a', font=('Segoe UI', 10, 'bold'))

    def build_mileage(self):
        page = ttk.Frame(self.tabs, padding=18)
        self.tabs.add(page, text='Vehicle mileage')
        heading = ttk.Frame(page)
        heading.pack(fill='x')
        ttk.Label(heading, text='One odometer, every journey', font=('Segoe UI Semibold', 17)).pack(side='left')
        unit_picker = ttk.Combobox(heading, textvariable=self.units, values=('km', 'mi'), state='readonly', width=5)
        unit_picker.pack(side='right')
        unit_picker.bind('<<ComboboxSelected>>', lambda _: self.render_mileage())
        ttk.Label(page, textvariable=self.mileage_note, style='Muted.TLabel', wraplength=920).pack(anchor='w', pady=(8, 14))
        totals = ttk.Frame(page, style='Card.TFrame', padding=(16, 10))
        totals.pack(fill='x', pady=(0, 12))
        ttk.Label(totals, textvariable=self.total_distance_text, style='CardTitle.TLabel').pack(anchor='w')
        actions = ttk.Frame(page)
        actions.pack(side='bottom', fill='x', pady=(16, 0))
        ttk.Button(actions, text='Preview mileage', command=self.load_mileage).pack(side='left')
        ttk.Button(actions, text='Name selected vehicle', command=self.name_vehicle).pack(side='left', padx=8)
        self.sync_button = ttk.Button(actions, text='Sync mileage across profiles', style='Primary.TButton', command=self.sync)
        self.sync_button.pack(side='right')
        container = ttk.Frame(page)
        container.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(container, columns=('vehicle','combined'), show='headings', selectmode='browse',height=6)
        self.tree.grid(row=0,column=0,sticky='nsew')
        vertical = ttk.Scrollbar(container, orient='vertical', command=self.tree.yview)
        vertical.grid(row=0,column=1,sticky='ns')
        horizontal = ttk.Scrollbar(container, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        container.columnconfigure(0,weight=1)
        container.rowconfigure(0,weight=1)

    def run_action(self, function, success):
        try:
            function()
            self.refresh()
            self.status_text.set(success)
        except Exception as exc:
            messagebox.showerror('Profile Manager', str(exc), parent=self.window)
            self.status_text.set('Action stopped. ' + str(exc))

    def refresh(self):
        try:
            backup_error = None
            if self.startup_backup_enabled and not self.backup_ready and self.manager.status().get('active'):
                try:
                    self.manager.snapshot_all('opened')
                    self.backup_ready = True
                except Exception as exc:
                    backup_error = str(exc)
            state = self.manager.status()
            self.state = state
            self.active = state.get('active')
            recovery = state.get('recovery_required', False)
            if recovery:
                self.recover_button.pack(side='right', padx=8)
            else:
                self.recover_button.pack_forget()
            self.active_text.set(str(self.active) if self.active else 'Setup needed')
            if not self.active:
                self.bind_panel.pack(fill='x', before=self.tabs, pady=(0, 8))
            else:
                self.bind_panel.pack_forget()
            self.update_controls()
            profiles = state.get('profiles', {})
            if isinstance(profiles, list):
                profiles = {item['name']: item for item in profiles}
            self.profiles = profiles
            if not self.selected.get() or self.selected.get() not in profiles:
                self.selected.set(self.active or next(iter(profiles), ''))
            self.profile_tree.delete(*self.profile_tree.get_children())
            self.profile_row_names = {}
            for index, (name, item) in enumerate(profiles.items()):
                iid = f'profile_{index}'
                self.profile_row_names[iid] = name
                label = 'Current live journey' if name == self.active else 'Save available' if item.get('exists') else 'Fresh start (empty)'
                if item.get('error'):
                    label = 'Save needs review'
                total_distance = f'{float(item.get("total_meters", 0)) / 1000:,.2f}' if item.get('exists') or name == self.active else '—'
                self.profile_tree.insert('', 'end', iid=iid, values=(name, label, item.get('vehicles', 0), format_last_played(item.get('last_played')), total_distance, ' '.join(item.get('description', '').split())[:180]), tags=('current' if name == self.active else 'even' if index % 2 == 0 else 'odd',))
                if name == self.selected.get():
                    self.profile_tree.selection_set(iid)
            self.profile_detail.set('Select a journey above. Empty profiles start fresh when selected.')
            self.status_text.set('Recovery required: ' + str(recovery) if recovery else 'Backups ready. Select a profile to continue.' if self.backup_ready and self.startup_backup_enabled else 'Preview mode. Startup backups were not created.')
            self.load_mileage(quiet=True)
            if backup_error:
                self.status_text.set('Opening backup failed; changes disabled. Click Refresh to retry. ' + backup_error)
        except Exception as exc:
            self.status_text.set(str(exc))
            if not self.quiet:
                messagebox.showerror('Cannot read profiles', str(exc), parent=self.window)

    def select_profile(self, _event=None):
        selection = self.profile_tree.selection()
        if selection:
            self.selected.set(self.profile_row_names[selection[0]])

    def add_profile(self):
        name = simpledialog.askstring('Add Profile', 'Name for a new empty journey:', parent=self.window)
        if name is None:
            return
        name = name.strip()
        if not name:
            return
        self.selected.set(name)
        self.run_action(lambda: self.manager.add_profile(name), f'{name} was added as an empty profile. Switch to it to start a fresh journey.')

    def play_game(self):
        try:
            if self.game_state is not False:
                raise RuntimeError('The game is already running or its status is unavailable.')
            if self.state.get('recovery_required') or not self.backup_ready:
                raise RuntimeError('Resolve the backup or recovery warning before starting the game.')
            steam = Path(os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')) / 'Steam' / 'steam.exe'
            if steam.is_file():
                subprocess.Popen([str(steam), '-applaunch', '2929250'], cwd=str(steam.parent))
            else:
                os.startfile('steam://rungameid/2929250')
            self.status_text.set('Starting Over the Hill through Steam. Refresh after closing the game.')
        except Exception as exc:
            messagebox.showerror('Play Game', str(exc), parent=self.window)

    def browse_root(self):
        chosen = filedialog.askdirectory(title='Select game folder or Saves folder', initialdir=str(self.root if self.root.exists() else Path.home()), parent=self.window)
        if not chosen:
            return
        self.root = normalize_root(chosen)
        self.manager = Manager(self.root)
        self.game_state = None
        self.game_text.set('Game - Checking')
        self.game_next_poll = 0
        self.root_text.set(str(self.root))
        self.backup_ready = False
        self.refresh()
        if getattr(self, 'active', None):
            try:
                remember_root(self.root)
            except OSError as exc:
                self.status_text.set('Folder opened, but its setting could not be saved: ' + str(exc))

    def bind_current(self):
        name = self.setup_name.get().strip()
        if not name:
            messagebox.showerror('Profile name required', 'Enter a name for your current journey.', parent=self.window)
            return
        def initialize():
            self.manager.initialize_profile(name)
            if self.setup_description.get().strip():
                self.manager.set_description(name, self.setup_description.get().strip())
            self.backup_ready = True
            self.selected.set(name)
        self.run_action(initialize, f'{name} is ready. Your current save has been preserved.')
        if getattr(self, 'active', None) == name:
            try:
                remember_root(self.root)
            except OSError as exc:
                self.status_text.set('Profile created, but folder preference could not be saved: ' + str(exc))

    def rename_profile(self):
        old = self.selected.get()
        name = simpledialog.askstring('Rename profile', 'New profile name:', initialvalue=old, parent=self.window)
        if name is None or not name.strip():
            return
        def rename():
            self.manager.rename_profile(old, name.strip())
            self.selected.set(name.strip())
        self.run_action(rename, 'Profile renamed.')

    def edit_description(self):
        name = self.selected.get()
        description = simpledialog.askstring('Profile description', f'Description for {name}:', initialvalue=self.profiles.get(name, {}).get('description', ''), parent=self.window)
        if description is not None:
            self.run_action(lambda: self.manager.set_description(name, description), 'Description updated.')

    def switch(self):
        target = self.selected.get()
        if target == self.active:
            messagebox.showinfo('Already active', target + ' is already the current profile.', parent=self.window)
            return
        try:
            preview = self.manager.switch_preview(target)
        except Exception as exc:
            messagebox.showerror('Cannot preview switch', str(exc), parent=self.window)
            self.status_text.set('Switch stopped: ' + str(exc))
            return
        dialog = SwitchPreviewDialog(self, preview)
        if dialog.show():
            self.run_action(lambda: self.manager.switch(target, allow_empty=preview['allow_empty'], sync_mileage=True, expected_preview=preview['token']), f'{target} is ready. You can start the game.')

    def capture(self):
        if messagebox.askyesno('Back up current profile', f'Copy the live save into {self.active}? Close the game first.', parent=self.window):
            self.run_action(lambda: self.manager.capture(self.active), f'{self.active} has been backed up.')

    def recover(self):
        if messagebox.askyesno('Recover interrupted change', 'Restore all files to their state before the interrupted operation? Close the game first.', parent=self.window):
            self.run_action(self.manager.recover, 'The interrupted change was rolled back. Refresh and review your profiles.')

    def load_mileage(self, quiet=False):
        try:
            self.preview = self.manager.mileage_preview()
            self.render_mileage()
        except Exception as exc:
            self.preview = None
            self.render_mileage()
            self.status_text.set('Mileage preview: ' + str(exc))
            if not quiet:
                messagebox.showerror('Mileage preview', str(exc), parent=self.window)

    def render_mileage(self):
        self.tree.delete(*self.tree.get_children())
        profile_names = list(getattr(self, 'profiles', DESCRIPTIONS))
        if self.preview:
            profile_names.extend(name for name in self.preview.get('profiles', []) if name not in profile_names)
        columns = ['vehicle'] + [f'p_{index}' for index in range(len(profile_names))] + ['new_distance', 'combined']
        self.tree.configure(columns=columns)
        distance_title = 'New since sync' if self.preview and self.preview.get('initialized') else 'Initial combined distance'
        for column, title in zip(columns, ['Vehicle'] + profile_names + [distance_title, 'Combined']):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=255 if column == 'vehicle' else 145, minwidth=100, stretch=False, anchor='w' if column == 'vehicle' else 'e')
        if self.preview is None:
            self.total_distance_text.set('Total Distance KM: —')
            self.mileage_note.set('Preview each vehicle’s odometer before syncing. Distances are displayed in your selected unit.')
            return
        initialized = self.preview.get('initialized', False)
        total_meters = sum(float(row.get('combined_meters', 0)) for row in self.preview.get('rows', []))
        self.total_distance_text.set(f'Total Distance KM: {total_meters / 1000:,.2f}')
        self.combined_card_text.set(f'{total_meters / 1000:,.2f} km')
        added = sum(float(row.get('new_meters', 0)) for row in self.preview.get('rows', [])) if initialized else total_meters
        self.new_card_text.set(f'{added / 1000:,.2f} km')
        self.new_card_title.set('NEW DRIVING SINCE SYNC' if initialized else 'INITIAL COMBINED DISTANCE')
        self.mileage_note.set('Only mileage added since the last sync is combined. Syncing again without driving adds nothing.' if initialized else 'First sync adds mileage from each distinct profile. Review the totals: overlapping or copied journeys may contain the same distance. Future syncs add only new distance.')
        factor = 1000 if self.units.get() == 'km' else 1609.344
        for row in self.preview.get('rows', []):
            vid = str(row['vehicle_id'])
            values = row.get('profiles', {})
            distance = lambda value: '—' if value is None else f'{float(value) / factor:,.2f}'
            label = self.names.get(vid, 'Unknown vehicle')
            new_meters = row.get('new_meters', 0) if initialized else row.get('combined_meters', 0)
            self.tree.insert('', 'end', iid=vid, values=(label, *(distance(values.get(name)) for name in profile_names), distance(new_meters), distance(row.get('combined_meters', 0))))

    def name_vehicle(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo('Name a vehicle', 'Preview mileage, then select a vehicle row.', parent=self.window)
            return
        vid = selection[0]
        label = simpledialog.askstring('Vehicle name', 'Friendly vehicle name:', initialvalue=self.names.get(vid, ''), parent=self.window)
        if label is None:
            return
        try:
            updated = dict(self.names)
            if label.strip():
                updated[vid] = label.strip()
            else:
                updated.pop(vid, None)
            APP_DATA.mkdir(parents=True, exist_ok=True)
            destination = APP_DATA / 'vehicle_names.json'
            temporary = destination.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temporary, destination)
            self.names = updated
            self.render_mileage()
        except Exception as exc:
            messagebox.showerror('Cannot save vehicle name', str(exc), parent=self.window)

    def sync(self):
        self.load_mileage()
        if self.preview is None:
            return
        preview_token = self.preview['token']
        if messagebox.askyesno('Sync vehicle mileage?', 'Write the previewed combined odometers to the live save and every existing profile?\n\nOnly vehicle mileage is changed. Empty profiles stay empty. Safety copies are kept. Close the game first.\n\nOn the first sync, confirm the profile distances represent separate driving.', parent=self.window):
            self.run_action(lambda: self.manager.sync_mileage(expected_preview=preview_token), 'Vehicle mileage has been synced across existing profiles.')
            self.load_mileage()

    def open_folder(self, path):
        try:
            if not path.is_dir():
                raise FileNotFoundError(f'Folder does not exist: {path}')
            os.startfile(path)
        except Exception as exc:
            messagebox.showerror('Open folder', str(exc), parent=self.window)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=None, help='Game folder containing Saves and BackupSaves')
    parser.add_argument('--smoke-test', action='store_true', help='Build widgets and exit; does not modify saves')
    args = parser.parse_args()
    window = tk.Tk()
    if args.smoke_test:
        window.withdraw()
    root = normalize_root(args.root) if args.root else saved_root()
    ProfileApp(window, root, startup_backup=not args.smoke_test, poll_game=not args.smoke_test, quiet=args.smoke_test)
    if args.smoke_test:
        window.update_idletasks()
        window.destroy()
    else:
        window.mainloop()


if __name__ == '__main__':
    main()
