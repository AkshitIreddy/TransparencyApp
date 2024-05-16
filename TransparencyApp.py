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
import win32gui
import win32con

def is_file_explorer_window(hwnd):
    """Check if the window represented by hwnd is a File Explorer window."""
    class_name = win32gui.GetClassName(hwnd)
    return class_name == "CabinetWClass"

def set_transparency_for_file_explorer(hwnd, transparency_level):
    """Set transparency for the File Explorer window identified by hwnd."""
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
    ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, transparency_level, win32con.LWA_ALPHA)

def set_transparency_for_all_file_explorer_windows(transparency_level):
    """Set transparency for all open File Explorer windows."""
    def enum_file_explorer_windows(hwnd, lParam):
        if is_file_explorer_window(hwnd):
            set_transparency_for_file_explorer(hwnd, transparency_level)
        return True

    win32gui.EnumWindows(enum_file_explorer_windows, None)

# Set transparency level (0 to 255, where 0 is completely transparent and 255 is opaque)
# Set transparency for all File Explorer windows
# set_transparency_for_all_file_explorer_windows(200)

def set_transparency_for_app(app_name, transparency_level):
    """Set transparency level for all windows of the specified application."""

    if app_name == "File Explorer":
        set_transparency_for_all_file_explorer_windows(transparency_level)
        return True
    # Convert app name to lowercase for case-insensitive comparison
    app_name_lower = app_name.lower()

    def enum_windows_proc(hwnd, lParam):
        """Callback function for each enumerated window."""
        # Check if the window title contains the app name
        window_title = win32gui.GetWindowText(hwnd).lower()
        if app_name_lower in window_title:
            # Get the current window style
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            # Add the transparency flag to the window style
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
            # Set the transparency level
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, transparency_level, win32con.LWA_ALPHA)
        return True

    # Enumerate all top-level windows
    win32gui.EnumWindows(enum_windows_proc, None)

# Example usage: Set transparency level for all Notepad windows
# set_transparency_for_app("visual studio code", 255)  # Adjust transparency level as needed

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
        self.canvas.pack()

        # Load the background image
        background_image = Image.open("icon.jpg")
        # Resize the background image to fit the window
        background_image = background_image.resize((width, height), Image.Resampling.LANCZOS)
        self.background_photo = ImageTk.PhotoImage(background_image)

        # Place the background image on the canvas
        self.canvas.create_image(0, 0, anchor="nw", image=self.background_photo)

        # Label to display the number of open windows
        self.explain = tk.Label(master, text="Windows List", font=("Arial", 14))
        self.explain_window = self.canvas.create_window(10, 10, anchor="nw", window=self.explain)

        # Dropdown list to display the titles of open windows
        self.window_dropdown = ttk.Combobox(master, state="readonly", font=("Arial", 14))
        self.window_dropdown_window = self.canvas.create_window(10, 50, anchor="nw", window=self.window_dropdown)

        # Text box for user input
        self.text_entry = tk.Entry(master, font=("Arial", 14))
        self.text_entry_window = self.canvas.create_window(10, 90, anchor="nw", window=self.text_entry)
        self.text_entry.bind("<Return>", self.save_to_json)
        
        # Label to display the list of entered texts
        self.list_label = tk.Label(master, text="Windows in List:", font=("Arial", 14))
        self.list_label_window = self.canvas.create_window(10, 130, anchor="nw", window=self.list_label)

        # Frame to contain sliders
        self.slider_frame = tk.Frame(master)
        self.slider_frame_window = self.canvas.create_window(10, 170, anchor="nw", window=self.slider_frame)
        
        # Populate dropdown list with window titles
        self.populate_window_dropdown()
        
        # Load data from JSON file
        self.load_data_from_json()

        # Bind the close event to the window
        master.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)

        # Start the periodic transparency function in a separate thread
        self.running = True
        self.thread = threading.Thread(target=self.transparency_applier_for_all_selected_windows)
        self.thread.start()

        self.update_thread = threading.Thread(target=self.update_window_titles)
        self.update_thread.start()

    def transparency_applier_for_all_selected_windows(self):
        while self.running:
            try:
                with open("data.json", "r") as f:
                    data = json.load(f)
                    if data:
                        for window, value in data["windows"].items():
                            set_transparency_for_app(window, value)
            except:
                continue
            # Sleep for one second 
            threading.Event().wait(1)

    def update_window_titles(self):
        while self.running:
            self.populate_window_dropdown()
            threading.Event().wait(1)  

    def minimize_to_tray(self):
        self.master.withdraw()  # Hide the window
        self.icon = pystray.Icon("TransparencyApp", Image.open("icon.png"), "Transparency App", self.create_menu())
        self.icon.run()
        
    def create_menu(self):
        return (item('Show', self.show_window), item('Quit', self.quit_window))
        
    def show_window(self, icon, item):
        self.master.after(0, self.master.deiconify)
        icon.stop()
        
    def quit_window(self, icon, item):
        self.running = False
        icon.stop()
        self.master.destroy()

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
            
def main():
    root = tk.Tk()
    app = TransparencyApp(root)
    root.mainloop()

main()