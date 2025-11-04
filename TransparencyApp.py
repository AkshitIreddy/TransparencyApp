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
import win32con
import win32api

def is_file_explorer_window(hwnd):
    """Check if the window represented by hwnd is a File Explorer window."""
    class_name = win32gui.GetClassName(hwnd)
    return class_name == "CabinetWClass"

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
        # Check if the window title contains the app name
        window_title = win32gui.GetWindowText(hwnd).lower()
        if app_name_lower in window_title:
            if win32gui.IsWindow(hwnd):
                # Get the current window style
                style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
                # Add the transparency flag to the window style
                win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
                # Set the transparency level
                ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, transparency_level, win32con.LWA_ALPHA)
                if track_modified is not None:
                    track_modified.add(hwnd)
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
        if is_visible_window(hwnd):
            window_title = win32gui.GetWindowText(hwnd)
            if window_title and window_title not in EXCLUDE_TITLES:
                open_windows.append(hwnd)
        return True
    
    win32gui.EnumWindows(enum_windows_proc, None)
    return open_windows

class TransparencyApp:

    def __init__(self, master):
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
        
        # Initialize screen dimming overlay window
        self.dimming_overlay_hwnd = None
        self.dimming_intensity = 128
        self.dimming_enabled = False

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
        while self.running:
            try:
                window_preset_exists = False
                with open("data.json", "r") as f:
                    data = json.load(f)
                    if self.ultra_mode_var.get():
                        focused_hwnd = win32gui.GetForegroundWindow()
                        focused_window = win32gui.GetWindowText(focused_hwnd)
                        for window, value in data["windows"].items():
                            if window.lower() in focused_window.lower() and value != 255:
                                self.apply_ultra_mode(value)
                                window_preset_exists = True
                                continue
                        if not window_preset_exists:
                            self.apply_ultra_mode(180)
                    else:
                        if data:
                            for window, value in data["windows"].items():
                                set_transparency_for_app(window, value, self.modified_windows)
            except:
                continue

            threading.Event().wait(0.1)

    def apply_ultra_mode(self, level):
        open_windows = get_open_windows()
        focused_hwnd = win32gui.GetForegroundWindow()
        
        for hwnd in open_windows:
            if hwnd == focused_hwnd:
                set_transparency(hwnd, level, self.modified_windows)  # Adjust transparency level for focused window
            else:
                set_transparency(hwnd, 0, self.modified_windows)  # Make other windows transparent
        
        self.previous_transparency = {hwnd: win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) for hwnd in open_windows if win32gui.IsWindow(hwnd)}
    
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
        
    def quit_window(self, icon, item):
        self.running = False
        # Restore all window transparency
        self.restore_all_windows_transparency()
        # Clean up dimming overlay
        if self.dimming_overlay_hwnd is not None:
            if win32gui.IsWindow(self.dimming_overlay_hwnd):
                win32gui.DestroyWindow(self.dimming_overlay_hwnd)
        icon.stop()
        self.icon = None  # Reset icon reference
        # Give threads time to exit
        import time
        time.sleep(0.5)
        # Schedule quit on main thread
        self.master.after(0, self.master.quit)
        self.master.after(100, self.master.destroy)
        import os
        self.master.after(200, lambda: os._exit(0))  # Force exit to ensure all threads terminate

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
            with open("data.json", "r") as f:
                data = json.load(f)
                if not data:
                    self.display_empty_message()
                else:
                    self.display_sliders(data)
        except FileNotFoundError:
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
        self.text_entry.delete(0, tk.END)  # Clear the entry box
        
        # Read existing data
        try:
            with open("data.json", "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {"windows": {}}
        
        # Add new text to the dictionary
        data["windows"][new_text] = 255
        
        # Write updated data back to the file
        with open("data.json", "w") as f:
            json.dump(data, f, indent=4)
        
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
            with open("data.json", "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        
        data["windows"][window] = int(value)
        
        with open("data.json", "w") as f:
            json.dump(data, f, indent=4)
    
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
    
    def create_dimming_overlay(self):
        """Create a black overlay window that covers the entire screen.
        This overlay sits on top of all windows but is click-through,
        allowing interaction while providing screen dimming effect."""
        # Get screen dimensions
        screen_width = win32api.GetSystemMetrics(0)
        screen_height = win32api.GetSystemMetrics(1)
        
        # Create a window class
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = lambda hwnd, msg, wParam, lParam: win32gui.DefWindowProc(hwnd, msg, wParam, lParam)
        wc.lpszClassName = "DimmingOverlay"
        wc.hInstance = win32api.GetModuleHandle(None)
        wc.hbrBackground = win32gui.GetStockObject(win32con.BLACK_BRUSH)
        
        try:
            win32gui.RegisterClass(wc)
        except:
            pass  # Class might already be registered
        
        # Create the window with layered, transparent, topmost, and no-activate flags
        # WS_EX_TRANSPARENT makes it click-through
        # WS_EX_TOPMOST keeps it above all windows
        # WS_EX_NOACTIVATE prevents it from stealing focus
        hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_NOACTIVATE,
            "DimmingOverlay",
            "Screen Dimming Overlay",
            win32con.WS_POPUP | win32con.WS_VISIBLE,
            0, 0,
            screen_width, screen_height,
            None, None, None, None
        )
        
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
            0, 0, screen_width, screen_height,
            win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE
        )
        
        return hwnd
    
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
        while self.running:
            try:
                if self.dimming_enabled:
                    if self.dimming_overlay_hwnd is None or not win32gui.IsWindow(self.dimming_overlay_hwnd):
                        self.dimming_overlay_hwnd = self.create_dimming_overlay()
                    else:
                        # Ensure overlay stays visible and positioned correctly
                        screen_width = win32api.GetSystemMetrics(0)
                        screen_height = win32api.GetSystemMetrics(1)
                        win32gui.SetWindowPos(
                            self.dimming_overlay_hwnd,
                            win32con.HWND_TOPMOST,
                            0, 0, screen_width, screen_height,
                            win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE
                        )
                        alpha = self.dimming_intensity
                        ctypes.windll.user32.SetLayeredWindowAttributes(self.dimming_overlay_hwnd, 0, alpha, win32con.LWA_ALPHA)
            except Exception as e:
                pass  # Silently handle errors
            threading.Event().wait(0.5)  # Check every 500ms

def main():
    root = tk.Tk()
    app = TransparencyApp(root)
    try:
        root.mainloop()
    finally:
        # Clean up on exit
        app.running = False
        # Restore all window transparency
        app.restore_all_windows_transparency()
        # Clean up dimming overlay
        if app.dimming_overlay_hwnd is not None:
            if win32gui.IsWindow(app.dimming_overlay_hwnd):
                win32gui.DestroyWindow(app.dimming_overlay_hwnd)
        # Force exit to ensure all threads terminate
        import os
        os._exit(0)

EXCLUDE_TITLES = ["Windows Input Experience", "Settings", "Transparency App", "Screen Dimming Overlay"]  # Modify as needed
     
main()