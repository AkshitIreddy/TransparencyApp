# !pip install pywin32 pystray pillow

import json
import tkinter as tk
from tkinter import ttk
import win32gui
from pystray import MenuItem as item
import pystray
from PIL import Image, ImageTk
import threading
import ctypes
from ctypes import wintypes
import win32con
import win32api
from datetime import datetime
import traceback
import os
import shutil
import tempfile
import time

# Constants for taskbar detection
ABM_GETTASKBARPOS = 0x00000005
ABM_GETSTATE = 0x00000004
ABS_AUTOHIDE = 0x0000001
ABE_LEFT = 0
ABE_TOP = 1
ABE_RIGHT = 2
ABE_BOTTOM = 3

# Define APPBARDATA structure for taskbar detection
class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    ]

# Logging system - tracks logged messages to avoid duplicates
_logged_messages = set()
_log_lock = threading.Lock()

def log_message(level, message, exception=None):
    """Log errors and important messages, avoiding duplicates."""
    with _log_lock:
        # Create a signature for the message to detect duplicates
        # For exceptions, use exception type and message
        if exception:
            sig = f"{level}:{type(exception).__name__}:{str(exception)[:100]}"
        else:
            sig = f"{level}:{message[:100]}"
        
        # Only log if we haven't seen this exact message before
        if sig in _logged_messages:
            return
        
        _logged_messages.add(sig)
        
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open("error_log.txt", "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {level}: {message}\n")
                if exception:
                    f.write(f"  Exception: {type(exception).__name__}: {str(exception)}\n")
                    f.write(f"  Traceback:\n")
                    for line in traceback.format_exc().split('\n'):
                        if line.strip():
                            f.write(f"    {line}\n")
                f.write("\n")
        except Exception as e:
            # If we can't write to log file, at least print
            print(f"Failed to write to log: {e}")

def log_error(message, exception=None):
    """Log an error message."""
    log_message("ERROR", message, exception)

def log_warning(message):
    """Log a warning message."""
    log_message("WARNING", message)

def log_info(message):
    """Log an info message."""
    log_message("INFO", message)

def is_file_explorer_window(hwnd):
    """Check if the window represented by hwnd is a File Explorer window."""
    try:
        if not win32gui.IsWindow(hwnd):
            return False
        class_name = win32gui.GetClassName(hwnd)
        return class_name == "CabinetWClass"
    except Exception:
        return False

def cleanup_stale_onefile_temp_dirs(max_age_hours=24):
    """Remove old onefile extraction directories that can accumulate over time."""
    try:
        temp_dir = tempfile.gettempdir()
        now = time.time()
        removed_count = 0
        for entry in os.listdir(temp_dir):
            if not entry.lower().startswith("onefile_"):
                continue
            full_path = os.path.join(temp_dir, entry)
            if not os.path.isdir(full_path):
                continue
            try:
                age_seconds = now - os.path.getmtime(full_path)
                if age_seconds >= max_age_hours * 3600:
                    shutil.rmtree(full_path, ignore_errors=True)
                    removed_count += 1
            except Exception:
                continue
        if removed_count:
            log_info(f"Cleaned up {removed_count} stale onefile temp folders")
    except Exception as e:
        log_warning(f"Failed to clean stale onefile temp folders: {str(e)[:200]}")

def set_transparency_for_file_explorer(hwnd, transparency_level, track_modified=None):
    """Set transparency for the File Explorer window identified by hwnd."""
    if win32gui.IsWindow(hwnd):
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
        ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, transparency_level, win32con.LWA_ALPHA)
        if track_modified is not None:
            track_modified.add(hwnd)

def set_transparency_for_all_file_explorer_windows(transparency_level, track_modified=None):
    """Set transparency for all open File Explorer windows."""
    def enum_file_explorer_windows(hwnd, lParam):
        if is_file_explorer_window(hwnd):
            set_transparency_for_file_explorer(hwnd, transparency_level, track_modified)
        return True

    win32gui.EnumWindows(enum_file_explorer_windows, None)

def set_transparency_for_app(app_name, transparency_level, track_modified=None):
    """Set transparency level for all windows of the specified application."""

    if app_name == "File Explorer":
        set_transparency_for_all_file_explorer_windows(transparency_level, track_modified)
        return True
    # Convert app name to lowercase for case-insensitive comparison
    app_name_lower = app_name.lower()

    def enum_windows_proc(hwnd, lParam):
        """Callback function for each enumerated window."""
        try:
            if not win32gui.IsWindow(hwnd):
                return True
            # Check if the window title contains the app name
            window_title = win32gui.GetWindowText(hwnd).lower()
            if app_name_lower in window_title:
                # Get the current window style
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                # Add the transparency flag to the window style
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
                # Set the transparency level
                ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, transparency_level, win32con.LWA_ALPHA)
                if track_modified is not None:
                    track_modified.add(hwnd)
        except Exception:
            pass
        return True

    # Enumerate all top-level windows
    win32gui.EnumWindows(enum_windows_proc, None)

def is_visible_window(hwnd):
    """Check if the window is visible, not minimized, and not a system-level window."""
    if not win32gui.IsWindowVisible(hwnd):
        return False
    if win32gui.IsIconic(hwnd):
        return False
    if win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) & win32con.WS_EX_TOOLWINDOW:
        return False
    return True

def set_transparency(hwnd, transparency_level, track_modified=None):
    """Set the transparency level for the window identified by hwnd."""
    if win32gui.IsWindow(hwnd):
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
        ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, transparency_level, win32con.LWA_ALPHA)
        if track_modified is not None:
            track_modified.add(hwnd)

def get_open_windows():
    """Get a list of currently open windows with visible titles and not considered system-level."""
    open_windows = []
    
    def enum_windows_proc(hwnd, lParam):
        try:
            if is_visible_window(hwnd):
                window_title = win32gui.GetWindowText(hwnd)
                if window_title and window_title not in EXCLUDE_TITLES:
                    open_windows.append(hwnd)
        except Exception:
            pass
        return True
    
    win32gui.EnumWindows(enum_windows_proc, None)
    return open_windows

class TransparencyApp:

    def __init__(self, master):
        # Flag to track if we should quit
        self.should_quit = False
        self.master = master
        master.title("Transparency App")
        
        # Set window attributes for translucency
        master.attributes("-alpha", 0.9)

        width = 800
        height = 800        
        # Set window size and position
        master.geometry(f"{width}x{height}+100+100")

        # Create a canvas
        self.canvas = tk.Canvas(master, width=width, height=height)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Load the original background image
        self.original_background_image = Image.open("icon.jpg")
        
        # Store initial dimensions
        self.window_width = width
        self.window_height = height
        
        # Resize the background image to fit the window
        background_image = self.original_background_image.resize((width, height), Image.Resampling.LANCZOS)
        self.background_photo = ImageTk.PhotoImage(background_image)

        # Place the background image on the canvas
        self.background_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.background_photo)
        
        # Bind resize event to update background image
        master.bind('<Configure>', self.on_window_resize)

        # Screen Dimming Controls at the top
        self.screen_dimming_var = tk.BooleanVar()
        self.screen_dimming_checkbox = tk.Checkbutton(master, text="Screen Dimming", variable=self.screen_dimming_var, command=self.update_screen_dimming)
        self.screen_dimming_checkbox_window = self.canvas.create_window(10, 10, anchor="nw", window=self.screen_dimming_checkbox)
        
        # Dimming intensity slider
        self.dimming_label = tk.Label(master, text="Dimming Intensity:", font=("Arial", 12))
        self.dimming_label_window = self.canvas.create_window(10, 40, anchor="nw", window=self.dimming_label)
        
        self.dimming_slider = tk.Scale(master, from_=0, to=200, orient='horizontal', length=200, command=self.update_dimming_intensity)
        self.dimming_slider.set(128)  # Default to moderate dimming (max is 200 to prevent full blackout)
        self.dimming_slider_window = self.canvas.create_window(10, 65, anchor="nw", window=self.dimming_slider)
        
        # Initialize screen dimming overlay window with defaults
        # Screen dimming settings are NOT loaded from JSON - always start with defaults
        self.dimming_overlay_hwnd = None
        self.dimming_intensity = 128  # Default intensity
        self.dimming_enabled = False  # Default disabled
        self.overlay_geometry = None  # Will store (x, y, width, height)
        self.taskbar_auto_hide = False
        self.taskbar_edge = ABE_BOTTOM
        
        # Set the slider to match defaults
        self.dimming_slider.set(128)
        self.screen_dimming_var.set(False)

        # Checkbox for Ultra Mode
        self.ultra_mode_var = tk.BooleanVar()
        self.ultra_mode_checkbox = tk.Checkbutton(master, text="Ultra Mode", variable=self.ultra_mode_var, command=self.update_ultra_mode)
        self.ultra_mode_checkbox_window = self.canvas.create_window(10, 100, anchor="nw", window=self.ultra_mode_checkbox)

        # Label to display the number of open windows
        self.explain = tk.Label(master, text="Windows List", font=("Arial", 14))
        self.explain_window = self.canvas.create_window(10, 140, anchor="nw", window=self.explain)

        # Dropdown list to display the titles of open windows
        self.window_dropdown = ttk.Combobox(master, state="readonly", font=("Arial", 14))
        self.window_dropdown_window = self.canvas.create_window(10, 180, anchor="nw", window=self.window_dropdown)

        # Text box for user input
        self.text_entry = tk.Entry(master, font=("Arial", 14))
        self.text_entry_window = self.canvas.create_window(10, 220, anchor="nw", window=self.text_entry)
        self.text_entry.bind("<Return>", self.save_to_json)
        
        # Label to display the list of entered texts
        self.list_label = tk.Label(master, text="Windows in List:", font=("Arial", 14))
        self.list_label_window = self.canvas.create_window(10, 260, anchor="nw", window=self.list_label)

        # Frame to contain sliders
        self.slider_frame = tk.Frame(master)
        self.slider_frame_window = self.canvas.create_window(10, 300, anchor="nw", window=self.slider_frame)
        
        # Populate dropdown list with window titles
        self.populate_window_dropdown()
        
        # Load data from JSON file
        self.load_data_from_json()

        # Bind the close event to the window
        master.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        
        # Schedule periodic check for quit flag (for tray menu quit)
        self.check_quit_flag()

        # Initialize previous transparency settings
        self.previous_transparency = {}
        
        # Track all windows that have been modified for transparency restoration on exit
        self.modified_windows = set()

        # Start the periodic transparency function in a separate thread
        self.running = True
        self.thread = threading.Thread(target=self.transparency_applier_for_all_selected_windows)
        self.thread.start()

        self.update_thread = threading.Thread(target=self.update_window_titles)
        self.update_thread.start()
        
        # Start thread to maintain dimming overlay
        self.dimming_thread = threading.Thread(target=self.maintain_dimming_overlay)
        self.dimming_thread.daemon = True
        self.dimming_thread.start()
    
    def on_window_resize(self, event):
        """Handle window resize event to update background image."""
        # Only handle if it's the main window being resized (not child widgets)
        if event.widget == self.master:
            new_width = event.width
            new_height = event.height
            
            # Only update if size actually changed
            if new_width != self.window_width or new_height != self.window_height:
                self.window_width = new_width
                self.window_height = new_height
                
                # Update canvas size
                self.canvas.config(width=new_width, height=new_height)
                
                # Resize and update background image
                resized_image = self.original_background_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
                self.background_photo = ImageTk.PhotoImage(resized_image)
                
                # Update the canvas image
                self.canvas.itemconfig(self.background_image_id, image=self.background_photo)
                
                # Move image to top-left corner
                self.canvas.coords(self.background_image_id, 0, 0)

    def transparency_applier_for_all_selected_windows(self):
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        while self.running:
            try:
                window_preset_exists = False
                
                # Try to read data.json with timeout protection
                try:
                    with open("data.json", "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    # Ensure data has the expected structure
                    if "windows" not in data:
                        if consecutive_errors == 0:
                            log_warning("data.json missing 'windows' key, creating default structure")
                        data = {"windows": {}}
                    elif not isinstance(data["windows"], dict):
                        if consecutive_errors == 0:
                            log_warning("data.json 'windows' is not a dict, resetting to empty dict")
                        data["windows"] = {}
                    
                    # Remove screen_dimmer if it exists (we don't use it)
                    if "screen_dimmer" in data:
                        del data["screen_dimmer"]
                        # Save cleaned version back
                        try:
                            with open("data.json", "w", encoding="utf-8") as f:
                                json.dump(data, f, indent=4)
                            log_info("Removed screen_dimmer section from data.json")
                        except:
                            pass
                    
                    consecutive_errors = 0  # Reset on success
                    
                    if self.ultra_mode_var.get():
                        focused_hwnd = win32gui.GetForegroundWindow()
                        if focused_hwnd:
                            focused_window = win32gui.GetWindowText(focused_hwnd)
                            for window, value in data["windows"].items():
                                if window.lower() in focused_window.lower() and value != 255:
                                    self.apply_ultra_mode(value)
                                    window_preset_exists = True
                                    continue
                            if not window_preset_exists:
                                self.apply_ultra_mode(180)
                    else:
                        if data and data.get("windows"):
                            for window, value in data["windows"].items():
                                set_transparency_for_app(window, value, self.modified_windows)
                            
                except json.JSONDecodeError as e:
                    consecutive_errors += 1
                    if consecutive_errors == 1:
                        log_error(f"data.json is corrupted (JSON decode error): {str(e)[:200]}", e)
                        # Create a backup and reset data.json
                        try:
                            if os.path.exists("data.json"):
                                import shutil
                                shutil.copy("data.json", "data.json.backup")
                            with open("data.json", "w", encoding="utf-8") as f:
                                json.dump({"windows": {}}, f, indent=4)
                            log_info("Created backup and reset corrupted data.json")
                        except Exception as backup_error:
                            log_error("Failed to backup/reset corrupted data.json", backup_error)
                    
                except FileNotFoundError:
                    consecutive_errors += 1
                    if consecutive_errors == 1:
                        log_info("data.json not found, creating default")
                        try:
                            with open("data.json", "w", encoding="utf-8") as f:
                                json.dump({"windows": {}}, f, indent=4)
                        except Exception as create_error:
                            log_error("Failed to create default data.json", create_error)
                    
                except PermissionError as e:
                    consecutive_errors += 1
                    if consecutive_errors == 1:
                        log_error("Permission denied accessing data.json", e)
                    
                except Exception as e:
                    consecutive_errors += 1
                    if consecutive_errors <= 3:  # Log first 3 unknown errors
                        log_error(f"Unexpected error reading data.json: {str(e)[:200]}", e)
                    
                # If we have too many consecutive errors, slow down to prevent tight loop
                if consecutive_errors > max_consecutive_errors:
                    threading.Event().wait(1.0)  # Wait longer on repeated errors
                    consecutive_errors = 0  # Reset counter after wait
                
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors <= 3:
                    log_error(f"Critical error in transparency_applier thread: {str(e)[:200]}", e)

            threading.Event().wait(0.1)

    def apply_ultra_mode(self, level):
        try:
            open_windows = get_open_windows()
            focused_hwnd = win32gui.GetForegroundWindow()
            
            for hwnd in open_windows:
                try:
                    if hwnd == focused_hwnd:
                        set_transparency(hwnd, level, self.modified_windows)  # Adjust transparency level for focused window
                    else:
                        set_transparency(hwnd, 0, self.modified_windows)  # Make other windows transparent
                except Exception as e:
                    # Individual window errors shouldn't stop the process
                    if not hasattr(self, '_ultra_mode_window_error_logged'):
                        log_error(f"Error applying transparency to window in ultra mode: {str(e)[:200]}", e)
                        self._ultra_mode_window_error_logged = True
            
            try:
                self.previous_transparency = {hwnd: win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) for hwnd in open_windows if win32gui.IsWindow(hwnd)}
            except Exception as e:
                log_error(f"Error saving previous transparency state: {str(e)[:200]}", e)
        except Exception as e:
            log_error(f"Critical error in apply_ultra_mode: {str(e)[:200]}", e)
    
    def update_window_titles(self):
        while self.running:
            self.populate_window_dropdown()
            threading.Event().wait(1)  

    def minimize_to_tray(self):
        self.master.withdraw()  # Hide the window
        # Create and run tray icon in a separate thread to avoid blocking main loop
        # The transparency threads will continue running in the background
        if not hasattr(self, 'icon') or self.icon is None:
            self.icon = pystray.Icon("TransparencyApp", Image.open("icon.png"), "Transparency App", self.create_menu())
            # Run icon in a separate thread (non-daemon so it stays alive)
            icon_thread = threading.Thread(target=self.icon.run, daemon=False)
            icon_thread.start()
        
    def create_menu(self):
        return (item('Show', self.show_window), item('Quit', self.quit_window))
        
    def show_window(self, icon, item):
        icon.stop()  # Stop the tray icon first
        self.icon = None  # Reset icon reference
        # Use after_idle to ensure it runs in the main thread
        self.master.after_idle(self.master.deiconify)  # Show the window
        
    def check_quit_flag(self):
        """Periodically check if quit was requested from tray menu."""
        if self.should_quit:
            self.cleanup_and_exit()
        else:
            # Check again in 100ms
            self.master.after(100, self.check_quit_flag)
    
    def cleanup_and_exit(self):
        """Perform cleanup and exit the application."""
        log_info("Cleaning up and exiting application")
        self.running = False
        
        # Restore all window transparency
        try:
            self.restore_all_windows_transparency()
        except Exception as e:
            log_error("Error restoring window transparency during quit", e)
        
        # Clean up dimming overlay
        try:
            if self.dimming_overlay_hwnd is not None:
                if win32gui.IsWindow(self.dimming_overlay_hwnd):
                    win32gui.DestroyWindow(self.dimming_overlay_hwnd)
        except Exception as e:
            log_error("Error destroying dimming overlay during quit", e)
        
        # Stop the tray icon if it exists
        try:
            if hasattr(self, 'icon') and self.icon is not None:
                self.icon.stop()
                self.icon = None
        except Exception as e:
            log_error("Error stopping tray icon", e)
        
        # Give threads time to exit
        import time
        time.sleep(0.3)
        
        # Destroy window and exit
        try:
            self.master.quit()
            self.master.destroy()
        except:
            pass
        
        import os
        time.sleep(0.1)
        os._exit(0)
    
    def quit_window(self, icon, item):
        """Called when Quit is selected from tray menu."""
        log_info("Quit requested from tray menu")
        # Set flag that will be picked up by check_quit_flag
        self.should_quit = True
        # Also stop the icon to close the menu
        try:
            icon.stop()
        except:
            pass

    def populate_window_dropdown(self):
        window_titles = []
        def get_window_titles(hwnd, lParam):
            window_title = win32gui.GetWindowText(hwnd)
            if window_title:
                window_titles.append(window_title)
            return True
        win32gui.EnumWindows(get_window_titles, None)

        current_values = self.window_dropdown['values']
        if current_values != tuple(window_titles):
            self.window_dropdown['values'] = window_titles

    def load_data_from_json(self):
        try:
            with open("data.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Remove screen_dimmer if present (we don't use it)
            if "screen_dimmer" in data:
                del data["screen_dimmer"]
                # Save cleaned version
                try:
                    with open("data.json", "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4)
                    log_info("Removed screen_dimmer section from data.json")
                except Exception as e:
                    log_error("Failed to save cleaned data.json", e)
            
            # Ensure windows key exists
            if "windows" not in data:
                data["windows"] = {}
            elif not isinstance(data.get("windows"), dict):
                log_warning("data.json 'windows' is not a dict, resetting")
                data["windows"] = {}
            
            if not data.get("windows"):
                self.display_empty_message()
            else:
                self.display_sliders(data)
                
        except json.JSONDecodeError as e:
            log_error("data.json is corrupted (JSON decode error) in load_data_from_json", e)
            # Create backup and reset
            try:
                if os.path.exists("data.json"):
                    import shutil
                    shutil.copy("data.json", "data.json.backup")
                with open("data.json", "w", encoding="utf-8") as f:
                    json.dump({"windows": {}}, f, indent=4)
                log_info("Created backup and reset corrupted data.json")
            except Exception as backup_error:
                log_error("Failed to backup/reset corrupted data.json", backup_error)
            self.display_empty_message()
            
        except FileNotFoundError:
            log_info("data.json not found on startup, will be created on first save")
            self.display_empty_message()
            
        except Exception as e:
            log_error(f"Error loading data.json: {str(e)[:200]}", e)
            self.display_empty_message()
        
    def display_empty_message(self):
        # Display message indicating that data.json is empty
        empty_label = tk.Label(self.slider_frame, text="data.json is empty", font=("Arial", 12))
        empty_label.pack(pady=10, anchor='w')
        
    def display_sliders(self, data):
        # Display sliders for each item in the dictionary
        for window, value in data["windows"].items():
            slider_label = tk.Label(self.slider_frame, text=window, font=("Arial", 12))
            slider_label.pack(pady=5, anchor='w')
            slider = tk.Scale(self.slider_frame, from_=0, to=255, orient='horizontal', length=200, command=lambda v, w=window: self.update_json_value(w, v))
            slider.set(value)
            slider.pack(pady=5, anchor='w')
        
    def save_to_json(self, event):
        new_text = self.text_entry.get()
        if not new_text.strip():
            return
        
        self.text_entry.delete(0, tk.END)  # Clear the entry box
        
        # Read existing data
        try:
            with open("data.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Ensure structure is correct
            if "windows" not in data:
                data["windows"] = {}
            elif not isinstance(data.get("windows"), dict):
                data["windows"] = {}
            
            # Remove screen_dimmer if present (we don't save it)
            if "screen_dimmer" in data:
                del data["screen_dimmer"]
        except FileNotFoundError:
            data = {"windows": {}}
        except json.JSONDecodeError as e:
            log_error("data.json corrupted when saving new window", e)
            # Try to recover by creating new structure
            data = {"windows": {}}
        except Exception as e:
            log_error(f"Error reading data.json before save: {str(e)[:200]}", e)
            data = {"windows": {}}
        
        # Add new text to the dictionary
        data["windows"][new_text] = 255
        
        # Write updated data back to the file (ensure screen_dimmer is not included)
        try:
            with open("data.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            log_error(f"Failed to save data.json: {str(e)[:200]}", e)
            return
        
        # Update the list display
        self.update_list_display(data["windows"])
        
    def update_list_display(self, window_dict):
        # Clear the slider frame
        for widget in self.slider_frame.winfo_children():
            widget.destroy()
        
        # Display the sliders
        if not window_dict:
            self.display_empty_message()
        else:
            self.display_sliders({"windows": window_dict})
    
    def update_json_value(self, window, value):
        # Update the JSON value corresponding to the slider
        try:
            with open("data.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Ensure structure is correct
            if "windows" not in data:
                data["windows"] = {}
            elif not isinstance(data.get("windows"), dict):
                data["windows"] = {}
            
            # Remove screen_dimmer if present (we don't save it)
            if "screen_dimmer" in data:
                del data["screen_dimmer"]
                
        except FileNotFoundError:
            data = {"windows": {}}
        except json.JSONDecodeError as e:
            log_error("data.json corrupted when updating slider value", e)
            return
        except Exception as e:
            log_error(f"Error reading data.json for slider update: {str(e)[:200]}", e)
            return
        
        data["windows"][window] = int(value)
        
        try:
            with open("data.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            log_error(f"Failed to save data.json after slider update: {str(e)[:200]}", e)
    
    def restore_all_windows_transparency(self):
        """Restore all modified windows to full opacity."""
        # Restore all tracked windows
        for hwnd in list(self.modified_windows):
            if win32gui.IsWindow(hwnd):
                try:
                    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
                    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, win32con.LWA_ALPHA)
                except:
                    pass
        
        # Also restore windows from previous_transparency
        for hwnd in list(self.previous_transparency.keys()):
            if win32gui.IsWindow(hwnd):
                try:
                    style = self.previous_transparency[hwnd]
                    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
                    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, win32con.LWA_ALPHA)
                except:
                    pass
        
        self.modified_windows.clear()
        self.previous_transparency.clear()
    
    def update_ultra_mode(self):
        if not self.ultra_mode_var.get():
            # Restore previous transparency settings
            open_windows = get_open_windows()
            for hwnd in open_windows:
                if hwnd in self.previous_transparency:
                    if win32gui.IsWindow(hwnd):
                        style = self.previous_transparency[hwnd]
                        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
                        ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, win32con.LWA_ALPHA)
            self.previous_transparency.clear()
    
    def get_taskbar_info(self):
        """Get taskbar position, auto-hide state, and dimensions.
        Returns: (edge, is_auto_hide, rect) where edge is ABE_LEFT/TOP/RIGHT/BOTTOM
        and rect is (left, top, right, bottom)"""
        try:
            # Initialize APPBARDATA structure
            abd = APPBARDATA()
            abd.cbSize = ctypes.sizeof(APPBARDATA)
            
            # Get taskbar state (auto-hide, always-on-top)
            state = ctypes.windll.shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd))
            is_auto_hide = bool(state & ABS_AUTOHIDE)
            
            # Get taskbar position
            abd2 = APPBARDATA()
            abd2.cbSize = ctypes.sizeof(APPBARDATA)
            ctypes.windll.shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(abd2))
            
            edge = abd2.uEdge
            rect = (abd2.rc.left, abd2.rc.top, abd2.rc.right, abd2.rc.bottom)
            
            return edge, is_auto_hide, rect
        except Exception as e:
            log_error(f"Error getting taskbar info: {str(e)[:200]}", e)
            # Default to bottom edge, no auto-hide
            return ABE_BOTTOM, False, (0, 0, 0, 0)
    
    def create_dimming_overlay(self):
        """Create a black overlay window that covers the screen.
        This overlay sits on top of all windows but is click-through,
        allowing interaction while providing screen dimming effect.
        Leaves a gap at the taskbar edge if auto-hide is enabled."""
        try:
            # Get screen dimensions
            screen_width = win32api.GetSystemMetrics(0)
            screen_height = win32api.GetSystemMetrics(1)
            
            # Get taskbar info
            taskbar_edge, is_auto_hide, taskbar_rect = self.get_taskbar_info()
            
            # Calculate overlay dimensions, leaving gap for auto-hide taskbar
            overlay_x = 0
            overlay_y = 0
            overlay_width = screen_width
            overlay_height = screen_height
            
            # Gap size in pixels - enough for Windows to detect cursor at edge
            GAP_SIZE = 2
            
            if is_auto_hide:
                if taskbar_edge == ABE_BOTTOM:
                    overlay_height = screen_height - GAP_SIZE
                elif taskbar_edge == ABE_TOP:
                    overlay_y = GAP_SIZE
                    overlay_height = screen_height - GAP_SIZE
                elif taskbar_edge == ABE_LEFT:
                    overlay_x = GAP_SIZE
                    overlay_width = screen_width - GAP_SIZE
                elif taskbar_edge == ABE_RIGHT:
                    overlay_width = screen_width - GAP_SIZE
                
                log_info(f"Taskbar auto-hide detected at edge {taskbar_edge}. Leaving {GAP_SIZE}px gap.")
            
            # Create a window class
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = lambda hwnd, msg, wParam, lParam: win32gui.DefWindowProc(hwnd, msg, wParam, lParam)
            wc.lpszClassName = "DimmingOverlay"
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.hbrBackground = win32gui.GetStockObject(win32con.BLACK_BRUSH)
            
            try:
                win32gui.RegisterClass(wc)
            except Exception as e:
                # Class might already be registered, that's okay
                pass
            
            # Create the window with layered, transparent, topmost, and no-activate flags
            # WS_EX_TRANSPARENT makes it click-through
            # WS_EX_TOPMOST keeps it above all windows
            # WS_EX_NOACTIVATE prevents it from stealing focus
            hwnd = win32gui.CreateWindowEx(
                win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_NOACTIVATE,
                "DimmingOverlay",
                "Screen Dimming Overlay",
                win32con.WS_POPUP | win32con.WS_VISIBLE,
                overlay_x, overlay_y,
                overlay_width, overlay_height,
                None, None, None, None
            )
            
            if not hwnd:
                log_error("Failed to create dimming overlay window")
                return None
            
            # Ensure window properties are set correctly
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_NOACTIVATE)
            
            # Set transparency (0 = fully transparent, 255 = fully opaque black)
            # Higher slider value = more dimming = higher alpha on black overlay
            alpha = self.dimming_intensity
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, alpha, win32con.LWA_ALPHA)
            
            # Keep window on top
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOPMOST,
                overlay_x, overlay_y, overlay_width, overlay_height,
                win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE
            )
            
            # Store overlay geometry for maintain function
            self.overlay_geometry = (overlay_x, overlay_y, overlay_width, overlay_height)
            self.taskbar_auto_hide = is_auto_hide
            self.taskbar_edge = taskbar_edge
            
            return hwnd
        except Exception as e:
            log_error(f"Error creating dimming overlay: {str(e)[:200]}", e)
            return None
    
    def update_screen_dimming(self):
        """Enable or disable screen dimming."""
        self.dimming_enabled = self.screen_dimming_var.get()
        if self.dimming_enabled:
            if self.dimming_overlay_hwnd is None:
                self.dimming_overlay_hwnd = self.create_dimming_overlay()
            else:
                # Update existing overlay
                if win32gui.IsWindow(self.dimming_overlay_hwnd):
                    alpha = self.dimming_intensity
                    ctypes.windll.user32.SetLayeredWindowAttributes(self.dimming_overlay_hwnd, 0, alpha, win32con.LWA_ALPHA)
                    win32gui.ShowWindow(self.dimming_overlay_hwnd, win32con.SW_SHOW)
        else:
            if self.dimming_overlay_hwnd is not None:
                if win32gui.IsWindow(self.dimming_overlay_hwnd):
                    win32gui.ShowWindow(self.dimming_overlay_hwnd, win32con.SW_HIDE)
    
    def update_dimming_intensity(self, value):
        """Update the dimming intensity when slider changes."""
        self.dimming_intensity = int(float(value))
        if self.dimming_enabled and self.dimming_overlay_hwnd is not None:
            if win32gui.IsWindow(self.dimming_overlay_hwnd):
                alpha = self.dimming_intensity
                ctypes.windll.user32.SetLayeredWindowAttributes(self.dimming_overlay_hwnd, 0, alpha, win32con.LWA_ALPHA)
    
    def maintain_dimming_overlay(self):
        """Maintain the dimming overlay window, recreating if needed."""
        error_count = 0
        while self.running:
            try:
                if self.dimming_enabled:
                    if self.dimming_overlay_hwnd is None or not win32gui.IsWindow(self.dimming_overlay_hwnd):
                        self.dimming_overlay_hwnd = self.create_dimming_overlay()
                        if self.dimming_overlay_hwnd is None and error_count < 3:
                            error_count += 1
                            log_warning(f"Failed to create dimming overlay (attempt {error_count})")
                    else:
                        # Use stored geometry if available, otherwise recalculate
                        if hasattr(self, 'overlay_geometry') and self.overlay_geometry:
                            overlay_x, overlay_y, overlay_width, overlay_height = self.overlay_geometry
                        else:
                            # Fallback: get current screen size and taskbar info
                            screen_width = win32api.GetSystemMetrics(0)
                            screen_height = win32api.GetSystemMetrics(1)
                            taskbar_edge, is_auto_hide, _ = self.get_taskbar_info()
                            
                            overlay_x = 0
                            overlay_y = 0
                            overlay_width = screen_width
                            overlay_height = screen_height
                            GAP_SIZE = 2
                            
                            if is_auto_hide:
                                if taskbar_edge == ABE_BOTTOM:
                                    overlay_height = screen_height - GAP_SIZE
                                elif taskbar_edge == ABE_TOP:
                                    overlay_y = GAP_SIZE
                                    overlay_height = screen_height - GAP_SIZE
                                elif taskbar_edge == ABE_LEFT:
                                    overlay_x = GAP_SIZE
                                    overlay_width = screen_width - GAP_SIZE
                                elif taskbar_edge == ABE_RIGHT:
                                    overlay_width = screen_width - GAP_SIZE
                            
                            self.overlay_geometry = (overlay_x, overlay_y, overlay_width, overlay_height)
                        
                        # Ensure overlay stays visible and positioned correctly
                        win32gui.SetWindowPos(
                            self.dimming_overlay_hwnd,
                            win32con.HWND_TOPMOST,
                            overlay_x, overlay_y, overlay_width, overlay_height,
                            win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE
                        )
                        alpha = self.dimming_intensity
                        ctypes.windll.user32.SetLayeredWindowAttributes(self.dimming_overlay_hwnd, 0, alpha, win32con.LWA_ALPHA)
                        error_count = 0  # Reset on success
            except Exception as e:
                error_count += 1
                if error_count <= 3:
                    log_error(f"Error maintaining dimming overlay: {str(e)[:200]}", e)
            threading.Event().wait(0.5)  # Check every 500ms

def main():
    log_info("TransparencyApp starting")
    cleanup_stale_onefile_temp_dirs(max_age_hours=24)
    
    try:
        root = tk.Tk()
        app = TransparencyApp(root)
        log_info("TransparencyApp initialized successfully")
        
        try:
            root.mainloop()
        except KeyboardInterrupt:
            log_info("Application interrupted by user")
        except Exception as e:
            log_error("Critical error in main loop", e)
    except Exception as e:
        log_error("Critical error during application startup", e)
    finally:
        log_info("TransparencyApp shutting down")
        try:
            # Clean up on exit
            app.running = False
            # Restore all window transparency
            app.restore_all_windows_transparency()
            # Clean up dimming overlay
            if app.dimming_overlay_hwnd is not None:
                if win32gui.IsWindow(app.dimming_overlay_hwnd):
                    win32gui.DestroyWindow(app.dimming_overlay_hwnd)
        except Exception as e:
            log_error("Error during cleanup", e)
        
        log_info("TransparencyApp shutdown complete")
        # Force exit to ensure all threads terminate
        import os
        os._exit(0)

EXCLUDE_TITLES = ["Windows Input Experience", "Settings", "Transparency App", "Screen Dimming Overlay"]  # Modify as needed
     
main()