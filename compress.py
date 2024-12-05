import sys
import os
import shutil
import UnityPy
import logging
import time
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import (
    QFileDialog, QMessageBox, QApplication, QLabel, QLineEdit, QPushButton,
    QGridLayout, QWidget, QTextEdit, QProgressBar, QHBoxLayout, QVBoxLayout,
    QRadioButton, QDialog, QCheckBox
)
from PyQt5.QtGui import QIcon
import qdarkstyle

class SettingsDialog(QDialog):
    def __init__(self, parent=None, compression_method='LZ4', error_logging=True):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.compression_method = compression_method
        self.error_logging = error_logging
        self.init_ui()

    def init_ui(self):
        # Compression Method Selection
        compression_label = QLabel('Compression Method:')
        self.lz4_radio = QRadioButton('LZ4')
        self.uncompressed_radio = QRadioButton('Uncompressed')

        if self.compression_method == 'LZ4':
            self.lz4_radio.setChecked(True)
        else:
            self.uncompressed_radio.setChecked(True)

        compression_layout = QVBoxLayout()
        compression_layout.addWidget(self.lz4_radio)
        compression_layout.addWidget(self.uncompressed_radio)

        # Error Logging Toggle
        self.error_logging_checkbox = QCheckBox('Enable Error Logging')
        self.error_logging_checkbox.setChecked(self.error_logging)

        # OK and Cancel Buttons
        ok_button = QPushButton('OK')
        cancel_button = QPushButton('Cancel')
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(compression_label)
        layout.addLayout(compression_layout)
        layout.addWidget(self.error_logging_checkbox)
        layout.addStretch()
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def get_settings(self):
        if self.lz4_radio.isChecked():
            self.compression_method = 'LZ4'
        else:
            self.compression_method = 'Uncompressed'
        self.error_logging = self.error_logging_checkbox.isChecked()
        return self.compression_method, self.error_logging

class OutputRedirector(QtCore.QObject):
    output_written = QtCore.pyqtSignal(tuple)
    def __init__(self, worker):
        super().__init__()
        self.worker = worker  # Reference to the Worker instance

    def write(self, text):
        if text.strip():  # Avoid empty lines
            # Include the current file being processed in the output
            current_file = self.worker.current_file if hasattr(self.worker, 'current_file') else 'Unknown file'
            # Emit the output along with the current file
            self.output_written.emit((text, current_file))

    def flush(self):
        pass

class Worker(QtCore.QThread):
    progress = QtCore.pyqtSignal(str)
    progress_bar_update = QtCore.pyqtSignal(int)  # progress percentage
    update_counts = QtCore.pyqtSignal(int, int, int, int, int)  # files_parsed, files_to_parse, files_compressed, files_copied, errors_encountered
    processing_time = QtCore.pyqtSignal(float)

    def __init__(self, input_paths, output_folder, mode, compression_method='LZ4', error_logging=True):
        super().__init__()
        self.input_paths = input_paths  # List of input files or folders
        self.output_folder = output_folder
        self.mode = mode  # 'folder' or 'file'
        self.compression_method = compression_method
        self.error_logging = error_logging
        self.files_to_parse = 0
        self.files_parsed = 0
        self.files_compressed = 0
        self.files_copied = 0
        self.errors_encountered = 0  # Error counter
        self.current_file = ''  # Current file being processed

        # Configure logging to capture UnityPy errors if enabled
        if self.error_logging:
            logging.basicConfig(
                filename='error_log.txt',
                filemode='w',  # Overwrite the log file each time
                level=logging.WARNING,
                format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
            )

    def run(self):
        # Redirect sys.stdout and sys.stderr in this thread
        self.output_redirector = OutputRedirector(self)
        sys.stdout = self.output_redirector
        sys.stderr = self.output_redirector
        self.output_redirector.output_written.connect(self.handle_output)

        self.start_time = time.time()  # Start timing

        # Prepare list of files to process
        file_list = []
        if self.mode == 'folder':
            # Process all files in the folder and subfolders
            for input_folder in self.input_paths:
                for root, dirs, files in os.walk(input_folder):
                    for name in files:
                        input_path = os.path.join(root, name)
                        file_list.append(input_path)
        else:
            # Process selected files
            file_list = self.input_paths

        self.files_to_parse = len(file_list)
        self.update_counts.emit(self.files_parsed, self.files_to_parse, self.files_compressed, self.files_copied, self.errors_encountered)

        # Set compression packer based on selected method
        if self.compression_method == 'LZ4':
            packer = (64, 2)
        else:  # Uncompressed
            packer = (64, 0)

        for input_path in file_list:
            self.current_file = input_path  # Update the current file being processed
            # Determine output path
            if self.mode == 'folder':
                # Preserve directory structure
                rel_path = os.path.relpath(os.path.dirname(input_path), self.input_paths[0])
                output_dir = os.path.join(self.output_folder, rel_path)
                os.makedirs(output_dir, exist_ok=True)
                output_path = os.path.join(output_dir, os.path.basename(input_path))
            else:
                # In file mode, overwrite the original file
                output_path = input_path
            try:
                # Try to load the file as an AssetBundle
                env = UnityPy.load(input_path)
                # Check if env.file has 'save' method
                if hasattr(env.file, 'save'):
                    # Save with selected compression
                    data = env.file.save(packer=packer)
                    with open(output_path, "wb") as f:
                        f.write(data)
                    message = f"Compressed: {input_path}"
                    self.progress.emit(message)
                    self.files_compressed += 1
                else:
                    if self.mode == 'folder':
                        # Not an AssetBundle, copy the file
                        shutil.copy2(input_path, output_path)
                        message = f"Copied: {input_path} -> {output_path} (Not an AssetBundle)"
                        self.progress.emit(message)
                    else:
                        # In file mode, do nothing
                        message = f"Skipped: {input_path} (Not an AssetBundle)"
                        self.progress.emit(message)
                    self.files_copied += 1
            except Exception as e:
                # Log the error and the file path
                if self.error_logging:
                    logging.error(f"Error processing {input_path}: {e}")
                self.errors_encountered += 1  # Increment error counter
                if self.mode == 'folder':
                    # Copy the file instead of compressing
                    shutil.copy2(input_path, output_path)
                    message = f"Copied: {input_path} -> {output_path} (Error occurred during compression)"
                    self.progress.emit(message)
                    self.files_copied += 1
                else:
                    # In file mode, do nothing
                    message = f"Skipped: {input_path} (Error occurred during compression)"
                    self.progress.emit(message)
                # Emit the error to be logged
                self.handle_output((str(e), input_path))
            finally:
                self.files_parsed += 1
                progress_percent = int((self.files_parsed / self.files_to_parse) * 100)
                self.progress_bar_update.emit(progress_percent)
                self.update_counts.emit(
                    self.files_parsed,
                    self.files_to_parse,
                    self.files_compressed,
                    self.files_copied,
                    self.errors_encountered
                )

        # Processing completed
        self.end_time = time.time()
        total_time = self.end_time - self.start_time
        self.processing_time.emit(total_time)

        # Restore sys.stdout and sys.stderr
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

    def handle_output(self, data):
        text, current_file = data
        # Append the output text to the console log
        self.progress.emit(text.strip())
        # If the output is an error, increment the error counter
        if "Error" in text or "error" in text or "Exception" in text:
            self.errors_encountered += 1
            # Log the error to error_log.txt with file path if error logging is enabled
            if self.error_logging:
                with open('error_log.txt', 'a', encoding='utf-8') as f:
                    f.write(f"Error in file: {current_file}\n{text}\n")

class CompressorApp(QWidget):
    def __init__(self):
        super().__init__()
        self.compression_method = 'LZ4'
        self.error_logging = True
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("UnityPy AssetBundle Compressor")

        # Set window icon
        icon_path = self.resource_path('icon.ico')
        self.setWindowIcon(QIcon(icon_path))

        # Mode selection
        mode_label = QLabel('Mode:')
        self.folder_mode_radio = QRadioButton('Folder Mode')
        self.file_mode_radio = QRadioButton('File Mode')
        self.folder_mode_radio.setChecked(True)

        # Connect mode change
        self.folder_mode_radio.toggled.connect(self.update_mode)

        # Mode layout
        mode_layout = QVBoxLayout()
        mode_layout.addWidget(self.folder_mode_radio)
        mode_layout.addWidget(self.file_mode_radio)
        mode_widget = QWidget()
        mode_widget.setLayout(mode_layout)

        # Labels
        self.input_label = QLabel('Input Folder:')
        self.output_folder_label = QLabel('Output Folder:')
        self.output_folder_label.setVisible(True)

        # Line edits
        self.input_entry = QLineEdit()
        self.output_folder_entry = QLineEdit()
        self.output_folder_entry.setVisible(True)

        # Buttons
        self.input_button = QPushButton('Browse')
        self.output_folder_button = QPushButton('Browse')
        self.output_folder_button.setVisible(True)
        start_button = QPushButton('Start Processing')
        settings_button = QPushButton('Settings')

        # Connect buttons to functions
        self.input_button.clicked.connect(self.select_input)
        self.output_folder_button.clicked.connect(self.select_output_folder)
        start_button.clicked.connect(self.start_processing)
        settings_button.clicked.connect(self.open_settings)

        # Console log
        self.console_log = QTextEdit()
        self.console_log.setReadOnly(True)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        # File counts labels
        self.status_label = QLabel('Status:')
        self.files_parsed_label = QLabel('Files Parsed: 0')
        self.files_to_parse_label = QLabel('Files to Parse: 0')
        self.files_compressed_label = QLabel('Files Compressed: 0')
        self.files_copied_label = QLabel('Files Copied: 0')
        self.errors_label = QLabel('Errors: 0')

        # Layout
        grid = QGridLayout()
        grid.setSpacing(10)

        grid.addWidget(mode_label, 0, 0)
        grid.addWidget(mode_widget, 0, 1, 1, 2)

        grid.addWidget(self.input_label, 1, 0)
        grid.addWidget(self.input_entry, 1, 1)
        grid.addWidget(self.input_button, 1, 2)

        grid.addWidget(self.output_folder_label, 2, 0)
        grid.addWidget(self.output_folder_entry, 2, 1)
        grid.addWidget(self.output_folder_button, 2, 2)

        grid.addWidget(start_button, 3, 1)
        grid.addWidget(settings_button, 3, 2)

        grid.addWidget(self.progress_bar, 4, 0, 1, 3)

        # Status layout
        status_layout = QHBoxLayout()
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.files_parsed_label)
        status_layout.addWidget(self.files_to_parse_label)
        status_layout.addWidget(self.files_compressed_label)
        status_layout.addWidget(self.files_copied_label)
        status_layout.addWidget(self.errors_label)

        grid.addLayout(status_layout, 5, 0, 1, 3)

        grid.addWidget(self.console_log, 6, 0, 1, 3)

        self.setLayout(grid)

        # Worker thread placeholder
        self.worker_thread = None

    def resource_path(self, relative_path):
        """ Get absolute path to resource, works for development and for PyInstaller """
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, relative_path)

    def update_mode(self):
        if self.folder_mode_radio.isChecked():
            self.input_label.setText('Input Folder:')
            self.output_folder_label.setVisible(True)
            self.output_folder_entry.setVisible(True)
            self.output_folder_button.setVisible(True)
        else:
            self.input_label.setText('Input Files:')
            self.output_folder_label.setVisible(False)
            self.output_folder_entry.setVisible(False)
            self.output_folder_button.setVisible(False)

    def select_input(self):
        if self.folder_mode_radio.isChecked():
            folder_selected = QFileDialog.getExistingDirectory(self, "Select Input Folder")
            if folder_selected:
                self.input_entry.setText(folder_selected)
        else:
            files_selected, _ = QFileDialog.getOpenFileNames(self, "Select Input Files")
            if files_selected:
                self.input_entry.setText(';'.join(files_selected))

    def select_output_folder(self):
        folder_selected = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder_selected:
            self.output_folder_entry.setText(folder_selected)

    def open_settings(self):
        settings_dialog = SettingsDialog(self, self.compression_method, self.error_logging)
        if settings_dialog.exec_():
            self.compression_method, self.error_logging = settings_dialog.get_settings()

    def start_processing(self):
        input_text = self.input_entry.text()
        mode = 'folder' if self.folder_mode_radio.isChecked() else 'file'

        if not input_text:
            QMessageBox.critical(self, "Error", "Please select input.")
            return

        if mode == 'folder':
            output_folder = self.output_folder_entry.text()
            if not output_folder:
                QMessageBox.critical(self, "Error", "Please select an output folder.")
                return
            input_paths = [input_text]
        else:
            output_folder = ''  # Not used in file mode
            input_paths = input_text.split(';')

        self.console_log.clear()
        self.progress_bar.setValue(0)

        # Disable UI elements during processing
        self.input_entry.setEnabled(False)
        self.output_folder_entry.setEnabled(False)
        self.input_button.setEnabled(False)
        self.output_folder_button.setEnabled(False)

        # Start the worker thread
        self.worker_thread = Worker(input_paths, output_folder, mode, self.compression_method, self.error_logging)
        self.worker_thread.progress.connect(self.update_console_log)
        self.worker_thread.progress_bar_update.connect(self.update_progress_bar)
        self.worker_thread.update_counts.connect(self.update_counts)
        self.worker_thread.processing_time.connect(self.display_processing_time)
        self.worker_thread.start()

    def update_console_log(self, message):
        self.console_log.append(message)

    def update_progress_bar(self, value):
        self.progress_bar.setValue(value)

    def update_counts(self, files_parsed, files_to_parse, files_compressed, files_copied, errors_encountered):
        self.files_parsed_label.setText(f'Files Parsed: {files_parsed}')
        self.files_to_parse_label.setText(f'Files to Parse: {files_to_parse}')
        self.files_compressed_label.setText(f'Files Compressed: {files_compressed}')
        self.files_copied_label.setText(f'Files Copied: {files_copied}')
        self.errors_label.setText(f'Errors: {errors_encountered}')

    def display_processing_time(self, total_time):
        # Re-enable UI elements
        self.input_entry.setEnabled(True)
        self.output_folder_entry.setEnabled(True)
        self.input_button.setEnabled(True)
        self.output_folder_button.setEnabled(True)
        minutes, seconds = divmod(int(total_time), 60)
        message = f"Processing completed successfully in {minutes} minutes and {seconds} seconds."
        QMessageBox.information(self, "Completed", message)

    def closeEvent(self, event):
        # Ensure the worker thread is properly terminated
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.terminate()
            self.worker_thread.wait()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    ex = CompressorApp()
    ex.show()
    sys.exit(app.exec_())
