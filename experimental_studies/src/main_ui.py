import sys
import json
import random
import requests
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QFileDialog, QComboBox, QLineEdit, 
                             QProgressBar, QListWidget, QListWidgetItem, QSplitter, QFrame, 
                             QMessageBox, QStyleFactory)
from PyQt5.QtGui import QPixmap, QImage, QIcon
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QObject

from comfyui_api import ComfyUIClient  # Import the ComfyUI API client


class ImageProcessor(QThread):
    """Thread for processing images asynchronously."""
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(QImage, str)

    def __init__(self, input_image, output_size, task_id):
        super().__init__()
        self.input_image = input_image
        self.output_size = output_size
        self.task_id = task_id
        self.is_cancelled = False

    def run(self):
        try:
            for i in range(101):
                if self.is_cancelled:
                    return
                self.progress.emit(i, self.task_id)
                self.msleep(30)
            processed_image = self.input_image.scaled(self.output_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.finished.emit(processed_image, self.task_id)
        except Exception as e:
            print(f"Error in image processing: {e}")
            self.finished.emit(QImage(), self.task_id)

    def cancel(self):
        self.is_cancelled = True


class QueueManager(QObject):
    """Manages the image processing queue."""
    task_added = pyqtSignal(str, QImage)
    task_removed = pyqtSignal(str)
    task_updated = pyqtSignal(str, int)

    def __init__(self):
        super().__init__()
        self.queue = {}

    def add_task(self, task_id, task):
        """Add a new task to the queue and start processing."""
        self.queue[task_id] = task
        self.task_added.emit(task_id, task['input_image'])
        task['processor'].start()

    def remove_task(self, task_id):
        """Remove a task from the queue (only when cleared by user)."""
        if task_id in self.queue:
            del self.queue[task_id]
            self.task_removed.emit(task_id)

    def update_task_progress(self, task_id, progress):
        """Update the progress of a specific task."""
        if task_id in self.queue:
            self.queue[task_id]['progress'] = progress
            self.task_updated.emit(task_id, progress)

    def get_task(self, task_id):
        """Get a task by its task_id."""
        return self.queue.get(task_id)

    def cancel_task(self, task_id):
        """Cancel a specific task."""
        if task_id in self.queue:
            self.queue[task_id]['processor'].cancel()
            self.task_updated.emit(task_id, 0)


class QueueItemWidget(QWidget):
    """Displays each task with image, progress bar, and cancel/clear button."""
    cancel_task = pyqtSignal(str)
    clear_task = pyqtSignal(str)

    def __init__(self, task_id, image, is_finished=False, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        layout = QHBoxLayout(self)

        self.image_label = QLabel()
        self.image_label.setFixedSize(50, 50)
        self.set_image(image)
        layout.addWidget(self.image_label)

        self.info_label = QLabel(f"Task ID: {task_id} - Process ongoing")
        layout.addWidget(self.info_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # Initially show "Cancel" button, change to "Clear" when finished
        self.action_button = QPushButton("Cancel" if not is_finished else "Clear")
        self.action_button.setFixedSize(60, 24)
        self.action_button.clicked.connect(self.handle_action)
        layout.addWidget(self.action_button)

        layout.setContentsMargins(5, 5, 5, 5)
        self.setLayout(layout)

    def set_image(self, image):
        pixmap = QPixmap.fromImage(image).scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pixmap)

    def update_progress(self, progress):
        """Update the task's progress bar."""
        self.progress_bar.setValue(progress)
        if progress < 100:
            self.info_label.setText(f"Task ID: {self.task_id} - {progress}%")
        else:
            self.info_label.setText(f"Task ID: {self.task_id} - Completed")

    def mark_as_cancelled(self):
        """Mark the task as 'Cancelled' and hide the progress bar."""
        self.info_label.setText(f"Task ID: {self.task_id} - Cancelled")
        self.progress_bar.hide()  # Hide the progress bar for cancelled tasks
        self.action_button.setText("Clear")  # Change the button to "Clear"

    def handle_action(self):
        """Handle the Cancel or Clear action."""
        if self.action_button.text() == "Cancel":
            self.cancel_task.emit(self.task_id)
            self.mark_as_cancelled()  # Hide the progress bar after cancellation
        elif self.action_button.text() == "Clear":
            self.clear_task.emit(self.task_id)

    def mark_as_finished(self):
        """Change the cancel button to clear when the task is finished."""
        self.action_button.setText("Clear")
        self.info_label.setText(f"Task ID: {self.task_id} - Completed")


class MainWindow(QMainWindow):
    """Main application window."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Processor with ComfyUI")
        self.setGeometry(100, 100, 1200, 800)

        # Initialize the application with dark theme
        self.theme = 'dark'
        QApplication.setStyle(QStyleFactory.create('Fusion'))
        self.setStyleSheet(self.load_stylesheet(self.theme))

        self.queue_manager = QueueManager()
        self.queue_manager.task_added.connect(self.add_queue_item)
        self.queue_manager.task_removed.connect(self.remove_queue_item)
        self.queue_manager.task_updated.connect(self.update_queue_item)

        # Initialize ComfyUI Client
        self.comfy_client = ComfyUIClient()
        
        self.setup_ui()

    def load_stylesheet(self, theme):
        """Load dark or light theme stylesheet."""
        if theme == "dark":
            return """
                QWidget {
                    background-color: #2b2b2b;
                    color: white;
                }
                QPushButton {
                    background-color: #5a5a5a;
                    border-radius: 10px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #6d6d6d;
                }
                QLabel {
                    color: white;
                }
                QProgressBar {
                    border: 2px solid grey;
                    border-radius: 5px;
                    text-align: center;
                    background: white;
                }
            """
        elif theme == "light":
            return """
                QWidget {
                    background-color: #f0f0f0;
                    color: black;
                }
                QPushButton {
                    background-color: #ffffff;
                    border-radius: 10px;
                    padding: 5px;
                }
                QPushButton:hover {
                    background-color: #dcdcdc;
                }
                QLabel {
                    color: black;
                }
                QProgressBar {
                    border: 2px solid grey;
                    border-radius: 5px;
                    text-align: center;
                    background: #f0f0f0;
                }
            """

    def toggle_theme(self):
        """Toggle between dark and light themes."""
        if self.theme == 'dark':
            self.theme = 'light'
            self.theme_button.setText('☀️')  # Sun icon for light mode
        else:
            self.theme = 'dark'
            self.theme_button.setText('🌙')  # Moon icon for dark mode
        self.setStyleSheet(self.load_stylesheet(self.theme))

    def setup_ui(self):
        """Set up the user interface."""
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # Right panel for the queue (vertically long)
        self.queue_panel = QWidget()
        queue_layout = QVBoxLayout(self.queue_panel)

        self.queue_list = QListWidget()
        self.queue_list.itemDoubleClicked.connect(self.on_queue_item_double_clicked)
        queue_layout.addWidget(self.queue_list)

        # Control buttons at the bottom of the queue
        queue_control_layout = QHBoxLayout()

        # "Cancel All Tasks" button
        self.cancel_all_button = QPushButton("Cancel All Tasks")
        self.cancel_all_button.setFixedHeight(30)
        self.cancel_all_button.clicked.connect(self.cancel_all_tasks)
        queue_control_layout.addWidget(self.cancel_all_button)

        # "Clear All Queue" button
        self.clear_all_button = QPushButton("Clear All Queue")
        self.clear_all_button.setFixedHeight(30)
        self.clear_all_button.clicked.connect(self.clear_all_queue)
        queue_control_layout.addWidget(self.clear_all_button)

        # Theme toggle button
        self.theme_button = QPushButton('🌙')
        self.theme_button.setFixedSize(30, 30)
        self.theme_button.clicked.connect(self.toggle_theme)
        queue_control_layout.addWidget(self.theme_button)

        queue_layout.addLayout(queue_control_layout)

        # Left panel (Image viewing and processing)
        self.right_panel = QWidget()
        right_layout = QVBoxLayout(self.right_panel)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(400, 400)
        right_layout.addWidget(self.image_label)

        self.main_progress_bar = QProgressBar()
        self.main_progress_bar.setRange(0, 100)
        self.main_progress_bar.hide()
        right_layout.addWidget(self.main_progress_bar)

        # Control panel at the bottom
        control_panel = QFrame()
        control_panel.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        control_panel.setMaximumHeight(50)
        control_layout = QHBoxLayout(control_panel)
        control_layout.setContentsMargins(10, 5, 10, 5)

        self.load_button = QPushButton("Load Image")
        self.load_button.setFixedHeight(30)
        self.load_button.clicked.connect(self.load_image)
        control_layout.addWidget(self.load_button)

        self.size_combo = QComboBox()
        self.size_combo.setFixedHeight(30)
        self.size_combo.addItems(["512x512", "768x768", "Custom"])
        self.size_combo.currentIndexChanged.connect(self.on_size_change)
        control_layout.addWidget(self.size_combo)

        self.custom_size = QLineEdit()
        self.custom_size.setPlaceholderText("Width x Height")
        self.custom_size.setFixedHeight(30)
        self.custom_size.hide()
        control_layout.addWidget(self.custom_size)

        self.process_button = QPushButton("Process Image")
        self.process_button.setFixedHeight(30)
        self.process_button.clicked.connect(self.process_image)
        control_layout.addWidget(self.process_button)

        right_layout.addStretch()
        right_layout.addWidget(control_panel)

        # Add both panels to the main layout
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.right_panel)
        self.splitter.addWidget(self.queue_panel)
        main_layout.addWidget(self.splitter)

        self.input_image = None
        self.current_task_id = None

    def add_queue_item(self, task_id, image):
        """Add a new item to the queue list (at the top)."""
        # Create a new list item
        item = QListWidgetItem()
        
        # Create a new widget for this list item
        item_widget = QueueItemWidget(task_id, image)
        item_widget.cancel_task.connect(self.cancel_task)
        item_widget.clear_task.connect(self.remove_queue_item)
        
        # Set the size hint for the list item based on the widget's size
        item.setSizeHint(item_widget.sizeHint())
        
        # Insert the new list item at the top of the list (index 0)
        self.queue_list.insertItem(0, item)
        
        # Set the newly created widget for the list item at index 0
        self.queue_list.setItemWidget(item, item_widget)

    def remove_queue_item(self, task_id):
        """Remove an item from the queue list."""
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            widget = self.queue_list.itemWidget(item)
            if widget and widget.info_label.text().startswith(f"Task ID: {task_id}"):
                self.queue_list.takeItem(i)
                self.queue_manager.remove_task(task_id)  # Remove from the queue manager when cleared
                break

    def cancel_task(self, task_id):
        """Cancel a task in the queue and hide its progress bar."""
        self.queue_manager.cancel_task(task_id)

        # Find the queue item widget and mark it as cancelled (hide progress bar)
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            widget = self.queue_list.itemWidget(item)
            if widget and widget.task_id == task_id:
                widget.mark_as_cancelled()

                # If the canceled task is the current one in the main window, hide its progress bar
                if task_id == self.current_task_id:
                    self.main_progress_bar.hide()
                break

    def update_queue_item(self, task_id, progress):
        """Update the progress of a queue item."""
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            widget = self.queue_list.itemWidget(item)
            
            # Check if the widget is valid before accessing its properties
            if widget and widget.info_label.text().startswith(f"Task ID: {task_id}"):
                widget.update_progress(progress)
                if progress == 100:
                    widget.mark_as_finished()  # Change the "Cancel" button to "Clear"
                break

    def cancel_all_tasks(self):
        """Cancel all ongoing tasks and mark them as 'Cancelled'. Do nothing for completed tasks."""
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            widget = self.queue_list.itemWidget(item)
            
            # Check if the task is still ongoing (not completed)
            if widget and "Completed" not in widget.info_label.text():
                self.queue_manager.cancel_task(widget.task_id)
                widget.mark_as_cancelled()  # Mark task as cancelled and hide its progress bar

                # Hide the main window progress bar if this is the current task
                if widget.task_id == self.current_task_id:
                    self.main_progress_bar.hide()

    def clear_all_queue(self):
        """Clear the entire queue by removing all tasks."""
        self.queue_list.clear()
        self.queue_manager.queue.clear()

    def load_image(self):
        """Load an image file and display it."""
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Image", "", "Image Files (*.png *.jpg *.bmp)")
        if file_name:
            try:
                self.input_image = QImage(file_name)
                if self.input_image.isNull():
                    raise ValueError("Failed to load image.")
                self.display_image(self.input_image)
            except Exception as e:
                self.show_error_message(f"Error loading image: {e}")

    def display_image(self, image):
        """Display the given image in the image label."""
        pixmap = QPixmap.fromImage(image)
        self.image_label.setPixmap(pixmap.scaled(400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def on_size_change(self, index):
        """Handle changes in the size selection combo box."""
        if self.size_combo.currentText() == "Custom":
            self.custom_size.show()
        else:
            self.custom_size.hide()

    def process_image(self):
        if not self.input_image:
            self.show_error_message("No image loaded.")
            return

        try:
            # Get the upscale size from the combo box or custom size input
            current_text = self.size_combo.currentText()
            if current_text == "Custom":
                # Parse the custom size entered by the user
                try:
                    width, height = map(int, self.custom_size.text().split('x'))
                    upscale_size = (width, height)
                except ValueError:
                    self.show_error_message("Invalid custom size format. Please use 'width x height'.")
                    return
            else:
                # Use the selected predefined size from the combo box
                if 'x' in current_text:
                    width, height = map(int, current_text.split('x'))
                    upscale_size = (width, height)
                else:
                    size = int(current_text)
                    upscale_size = (size, size)

            # Send the image to ComfyUI for processing using the upscale size
            output_image_path = self.comfy_client.process_image(self.input_image, upscale_size)

            # Load the processed image and display it
            output_image = QImage(output_image_path)
            if not output_image.isNull():
                self.display_image(output_image)
            else:
                raise ValueError("Failed to process image via ComfyUI.")

        except Exception as e:
            self.show_error_message(f"Error processing image via ComfyUI: {e}")


    def update_progress(self, value, task_id):
        """Update the progress of a task."""
        self.queue_manager.update_task_progress(task_id, value)
        if task_id == self.current_task_id:
            self.main_progress_bar.setValue(value)

    def display_result(self, image, task_id):
        """Display the result of a completed task."""
        # Do not remove the task from the queue, only update its status
        self.add_finished_queue_item(task_id, image)

    def add_finished_queue_item(self, task_id, image):
        """Mark a task as finished and allow it to be cleared."""
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            widget = self.queue_list.itemWidget(item)
            if widget and widget.info_label.text().startswith(f"Task ID: {task_id}"):
                widget.mark_as_finished()
                break
        self.display_image(image)
        self.main_progress_bar.hide()

    def on_queue_item_double_clicked(self, item):
        """Handle the event when an item in the queue is double-clicked."""
        for i in range(self.queue_list.count()):
            list_item = self.queue_list.item(i)
            widget = self.queue_list.itemWidget(list_item)
            if list_item == item:
                task_id = widget.info_label.text().split()[2]  # Extract Task ID
                task = self.queue_manager.get_task(task_id)
                if task:
                    self.display_image(task['input_image'])  # Load the image in the main window
                    self.main_progress_bar.setValue(task['progress'])  # Set progress
                    self.main_progress_bar.show()
                    self.current_task_id = task_id
                break

    def show_error_message(self, message):
        """Display an error message in a dialog box."""
        error_dialog = QMessageBox(self)
        error_dialog.setWindowTitle("Error")
        error_dialog.setText(message)
        error_dialog.setIcon(QMessageBox.Critical)
        error_dialog.exec_()


def main():
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        print(f"Application error: {e}")


if __name__ == '__main__':
    main()
