import sys
import time
import threading
import pyaudio
import numpy as np
import math

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QLabel, QGridLayout, 
                               QLineEdit, QDialog, QDialogButtonBox)
from PySide6.QtCore import Qt, QTimer, QObject, Signal, QThread
from PySide6.QtGui import QDoubleValidator

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

class OhmMeterBackend:
    def __init__(self):
        self.CHUNK = 1024
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 44100
        self.time_div = 1.0
        self.volt_div = 1.0
        self.calibration_factor = 0.1
        self.known_resistor = 1000.0 
        self.generating_signal = False
        self.signal_frequency = 1000
        self.signal_amplitude = 0.9
        self.signal_thread = None
        self.p = pyaudio.PyAudio()
        
        input_device_index = 1
        output_device_index = 3
        
        print(f"Using hardcoded Input Device ID: {input_device_index}")
        print(f"Using hardcoded Output Device ID: {output_device_index}")
        self.stream = self.p.open(format=self.FORMAT, channels=self.CHANNELS, rate=self.RATE, input=True,
                                  input_device_index=input_device_index, frames_per_buffer=self.CHUNK)
        self.output_stream = self.p.open(format=self.FORMAT, channels=self.CHANNELS, rate=self.RATE, output=True,
                                         output_device_index=output_device_index, frames_per_buffer=self.CHUNK)

    def _generate_signal_target(self):
        while self.generating_signal:
            samples = (np.sin(2 * np.pi * np.arange(self.CHUNK) * self.signal_frequency / self.RATE) * 32767 * self.signal_amplitude).astype(np.int16)
            self.output_stream.write(samples.tobytes())
            time.sleep(0.01)

    def start_signal_generation(self):
        if not self.generating_signal:
            self.generating_signal = True
            self.signal_thread = threading.Thread(target=self._generate_signal_target)
            self.signal_thread.daemon = True
            self.signal_thread.start()

    def stop_signal_generation(self):
        self.generating_signal = False
        if self.signal_thread:
            self.signal_thread.join(timeout=0.1)

    def get_latest_data(self):
        data = np.frombuffer(self.stream.read(self.CHUNK, exception_on_overflow=False), dtype=np.int16)
        frequency = self.calculate_frequency(data)
        rms_amplitude = np.sqrt(np.mean(data.astype(np.float32)**2))
        rms_voltage = rms_amplitude / 32767 * self.calibration_factor
        return {"waveform": data, "frequency": frequency, "voltage_rms": rms_voltage}

    def get_stable_rms(self, duration_seconds):
        readings = []
        num_chunks_to_read = int((self.RATE / self.CHUNK) * duration_seconds)
        for _ in range(num_chunks_to_read):
            data = np.frombuffer(self.stream.read(self.CHUNK, exception_on_overflow=False), dtype=np.int16)
            rms_amplitude = np.sqrt(np.mean(data.astype(np.float32)**2))
            rms_voltage = rms_amplitude / 32767 * self.calibration_factor
            readings.append(rms_voltage)
            time.sleep(self.CHUNK / self.RATE)
        return np.mean(readings) if readings else 0
        
    def get_phase_of_signal(self, duration_seconds, freq):
        
        num_samples = int(self.RATE * duration_seconds)
        data = np.array([], dtype=np.int16)
        while len(data) < num_samples:
            chunk_data = np.frombuffer(self.stream.read(self.CHUNK, exception_on_overflow=False), dtype=np.int16)
            data = np.concatenate((data, chunk_data))
        
        data = data[:num_samples]
        data = data.astype(np.float32) / 32767.0
        
        window = np.hanning(len(data))
        windowed_data = data * window
        
        fft_result = np.fft.fft(windowed_data)
        freqs = np.fft.fftfreq(len(fft_result), 1/self.RATE)
        
        idx = np.argmin(np.abs(freqs - freq))
        phase_rad = np.angle(fft_result[idx])
        
        phase_deg = np.degrees(phase_rad) % 360
        if phase_deg > 180:
            phase_deg -= 360
        return phase_deg

    def calculate_frequency(self, data):
        if len(data) == 0: return 0.0
        window = np.hanning(len(data))
        windowed_data = data * window
        fft_result = np.fft.fft(windowed_data)
        freqs = np.fft.fftfreq(len(fft_result), 1 / self.RATE)
        magnitude = np.abs(fft_result)
        peak_index = np.argmax(magnitude[1:len(magnitude) // 2]) + 1
        return abs(freqs[peak_index])

    def close(self):
        self.stop_signal_generation()
        self.stream.stop_stream()
        self.stream.close()
        self.output_stream.stop_stream()
        self.output_stream.close()
        self.p.terminate()

class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, dpi=100):
        self.fig = Figure(figsize=(8, 6), dpi=dpi, facecolor='#1E1E1E')
        self.axes = self.fig.add_subplot(111)
        super(MplCanvas, self).__init__(self.fig)
        self.update_style()

    def update_style(self):
        self.axes.set_facecolor('#1E1E1E')
        self.axes.spines['bottom'].set_color('#00FFFF')
        self.axes.spines['top'].set_color('#1E1E1E')
        self.axes.spines['right'].set_color('#1E1E1E')
        self.axes.spines['left'].set_color('#00FFFF')
        self.axes.tick_params(axis='both', colors='white')
        self.axes.yaxis.label.set_color('white')
        self.axes.xaxis.label.set_color('white')
        self.axes.set_xlabel("Sample Index")
        self.axes.set_ylabel("Amplitude")
        self.axes.grid(True, color='#444', linestyle='--')
        self.fig.tight_layout()
        self.draw()

class PlotWindow(QDialog):
    def __init__(self, backend_ref, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Live Oscilloscope")
        self.backend = backend_ref
        
        self.canvas = MplCanvas(self, dpi=100)
        x_data = np.arange(self.backend.CHUNK)
        y_data = np.zeros(self.backend.CHUNK)
        self.scope_line, = self.canvas.axes.plot(x_data, y_data, lw=1.5, color='#00FFFF')
        
        self.volt_minus_btn = QPushButton("V/Div -")
        self.volt_plus_btn = QPushButton("V/Div +")
        self.volt_label = QLabel(f"{self.backend.volt_div:.2f}x")
        self.calib_input = QLineEdit(f"{self.backend.calibration_factor:.4f}")
        self.calib_input.setValidator(QDoubleValidator(0.0001, 10.0, 4))

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self.volt_minus_btn)
        controls_layout.addWidget(self.volt_label)
        controls_layout.addWidget(self.volt_plus_btn)
        controls_layout.addStretch()
        controls_layout.addWidget(QLabel("Calibration (V):"))
        controls_layout.addWidget(self.calib_input)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.canvas)
        main_layout.addLayout(controls_layout)
        self.setLayout(main_layout)

        self.volt_plus_btn.clicked.connect(lambda: self._adjust_volt_div(0.5))
        self.volt_minus_btn.clicked.connect(lambda: self._adjust_volt_div(2.0))
        self.calib_input.editingFinished.connect(self._update_calibration)
        
        self.setMinimumSize(600, 500)
        self.update_plot_limits()
        self.setStyleSheet("""
            QDialog { background-color: #1E1E1E; }
            QLabel { font-size: 14px; color: #AAA; padding: 5px; }
            QPushButton { background-color: #333; font-size: 14px; font-weight: bold; border: 1px solid #555; padding: 10px; border-radius: 5px; }
            QPushButton:hover { background-color: #444; }
            QLineEdit { border: 1px solid #555; padding: 5px; border-radius: 3px; background-color: #282828; color: white; font-size: 14px; }
        """)

    def _adjust_volt_div(self, factor):
        self.backend.volt_div = max(0.1, self.backend.volt_div * factor)
        self.volt_label.setText(f"{self.backend.volt_div:.2f}x")
        self.update_plot_limits()

    def _update_calibration(self):
        try:
            val = float(self.calib_input.text())
            self.backend.calibration_factor = val
            print(f"Calibration factor updated to: {val}")
        except ValueError:
            self.calib_input.setText(f"{self.backend.calibration_factor:.4f}")

    def update_data(self, waveform_data):
        self.scope_line.set_ydata(waveform_data)
        self.canvas.draw()
    
    def update_plot_limits(self):
        y_lim = 32768 / self.backend.volt_div
        self.canvas.axes.set_ylim([-y_lim, y_lim])
        self.canvas.draw()

class RMSWorker(QObject):
    finished = Signal(float)
    def __init__(self, backend_ref):
        super().__init__()
        self.backend = backend_ref
    def run(self):
        rms_value = self.backend.get_stable_rms(2)
        self.finished.emit(rms_value)

class PhaseWorker(QObject):
    finished = Signal(float)
    def __init__(self, backend_ref):
        super().__init__()
        self.backend = backend_ref
    def run(self):
        phase_value = self.backend.get_phase_of_signal(0.5, self.backend.signal_frequency)
        self.finished.emit(phase_value)

class AutoDetectMethodDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose Auto-Detect Method")
        self.method = None

        layout = QVBoxLayout(self)
        self.label = QLabel("How would you like to detect the component?")
        layout.addWidget(self.label)

        self.button_box = QDialogButtonBox()
        self.freq_button = self.button_box.addButton("Frequency Sweep", QDialogButtonBox.ActionRole)
        self.phase_button = self.button_box.addButton("Phase Shift", QDialogButtonBox.ActionRole)
        layout.addWidget(self.button_box)

        self.freq_button.clicked.connect(self.select_frequency)
        self.phase_button.clicked.connect(self.select_phase)

        self.setStyleSheet("""
            QDialog { background-color: #1E1E1E; }
            QLabel { font-size: 14px; color: #AAA; padding: 15px; }
            QPushButton { background-color: #333; font-size: 14px; font-weight: bold; border: 1px solid #555; padding: 10px; border-radius: 5px; min-width: 120px; }
            QPushButton:hover { background-color: #444; }
        """)

    def select_frequency(self):
        self.method = 'frequency'
        self.accept()

    def select_phase(self):
        self.method = 'phase'
        self.accept()

class LCRMeterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LCR Meter")
        self.setGeometry(100, 100, 600, 620) 
        self.current_mode = 'R'
        
        self.measurement_state = 'IDLE' 
        self.measured_vin_rms = None
        self.measured_vin_phase = None
        self.measured_vin_low = None
        self.measured_vout_low = None
        self.measured_vin_high = None
        self.measured_vout_high = None
        self.f_low = 200   
        self.f_high = 2000 

        try:
            self.backend = OhmMeterBackend()
        except Exception as e:
            error_dialog = QLabel(f"Failed to initialize audio backend:\n{e}\n\nPlease check your audio devices and configuration.")
            error_dialog.setWindowTitle("Initialization Error")
            error_dialog.show()
            sys.exit()

        self.plot_window = None
        self.setup_ui()
        self.apply_stylesheet()
        
        self.info_update_timer = QTimer()
        self.info_update_timer.setInterval(100)
        self.info_update_timer.timeout.connect(self.update_info)
        self.info_update_timer.start()

    def setup_ui(self):
        self.create_widgets()
        self.create_layouts()
        self.connect_signals()
        self.set_measurement_mode('R')

    def create_widgets(self):
        self.measurement_type_label = QLabel("Resistance")
        self.result_label = QLabel("---")
        self.result_label.setObjectName("result_label")
        self.unit_label = QLabel("Ω")
        
        self.info_widgets = {
            'voltage_value_label': QLabel("RMS Voltage:"), 'voltage_value': QLabel("--- V"),
            'freq_value_label': QLabel("Frequency:"), 'freq_value': QLabel("--- Hz")
        }
        self.info_widgets['voltage_value'].setAlignment(Qt.AlignRight)
        self.info_widgets['freq_value'].setAlignment(Qt.AlignRight)

        self.show_plot_button = QPushButton("Show Oscilloscope")
        self.controls = {
            'sig_gen_btn': QPushButton("Signal Gen: OFF"),
            'freq_minus': QPushButton("Freq -"), 'freq_plus': QPushButton("Freq +"),
            'amp_minus': QPushButton("Amp -"), 'amp_plus': QPushButton("Amp +"),
            'freq_label': QLabel(f"{self.backend.signal_frequency} Hz"),
            'amp_label': QLabel(f"{self.backend.signal_amplitude:.1f}"),
            'known_r_input': QLineEdit(f"{self.backend.known_resistor}")
        }
        self.controls['known_r_input'].setValidator(QDoubleValidator(1.0, 1000000.0, 2))
        
        self.known_r_recommendation_label = QLabel()
        self.known_r_recommendation_label.setObjectName("recommendation_label")
        
        self.mode_buttons = {
            'R': QPushButton("Resistance (R)"), 'C': QPushButton("Capacitance (C)"),
            'L': QPushButton("Inductance (L)"), 'AUTO': QPushButton("Auto Detect")
        }
        for key, btn in self.mode_buttons.items(): btn.setObjectName(f"mode_button_{key}")
        
        self.action_button = QPushButton("MEASURE")
        self.action_button.setObjectName("measure_button")
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("status_label")

    def create_layouts(self):
        result_line_layout = QHBoxLayout()
        result_line_layout.addStretch(1)
        result_line_layout.addWidget(self.result_label)
        result_line_layout.addWidget(self.unit_label)
        result_line_layout.addStretch(1)

        display_layout = QVBoxLayout()
        display_layout.addWidget(self.measurement_type_label, 0, Qt.AlignCenter)
        display_layout.addLayout(result_line_layout)
        
        info_layout = QGridLayout()
        info_layout.addWidget(self.info_widgets['voltage_value_label'], 0, 0)
        info_layout.addWidget(self.info_widgets['voltage_value'], 0, 1)
        info_layout.addWidget(self.info_widgets['freq_value_label'], 0, 2)
        info_layout.addWidget(self.info_widgets['freq_value'], 0, 3)

        controls_layout = QGridLayout()
        controls_layout.setSpacing(10)
        controls_layout.addWidget(QLabel("<b>Signal Generator & Settings</b>"), 0, 0, 1, 3)
        controls_layout.addWidget(self.controls['sig_gen_btn'], 1, 0, 1, 3)
        controls_layout.addWidget(self.controls['freq_minus'], 2, 0)
        controls_layout.addWidget(self.controls['freq_label'], 2, 1, Qt.AlignCenter)
        controls_layout.addWidget(self.controls['freq_plus'], 2, 2)
        controls_layout.addWidget(self.controls['amp_minus'], 3, 0)
        controls_layout.addWidget(self.controls['amp_label'], 3, 1, Qt.AlignCenter)
        controls_layout.addWidget(self.controls['amp_plus'], 3, 2)
        controls_layout.addWidget(QLabel("Known R (Ω):"), 4, 0)
        controls_layout.addWidget(self.controls['known_r_input'], 4, 1, 1, 2)
        
        controls_layout.addWidget(self.known_r_recommendation_label, 5, 0, 1, 3, Qt.AlignRight)
        mode_layout = QHBoxLayout()
        for button in self.mode_buttons.values(): mode_layout.addWidget(button)

        main_layout = QVBoxLayout()
        main_layout.addLayout(display_layout)
        main_layout.addLayout(info_layout)
        main_layout.addSpacing(20)
        main_layout.addWidget(self.show_plot_button)
        main_layout.addLayout(controls_layout)
        main_layout.addSpacing(20)
        main_layout.addLayout(mode_layout)
        main_layout.addWidget(self.action_button)
        main_layout.addWidget(self.status_label, 0, Qt.AlignCenter)
        
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

    def connect_signals(self):
        self.show_plot_button.clicked.connect(self.toggle_plot_window)
        self.action_button.clicked.connect(self.on_action_button_clicked)
        for mode, button in self.mode_buttons.items():
            button.clicked.connect(lambda checked=False, m=mode: self.set_measurement_mode(m))
        
        self.controls['sig_gen_btn'].clicked.connect(self.toggle_signal_generator)
        self.controls['freq_plus'].clicked.connect(lambda: self.adjust_sig_gen('freq', 100))
        self.controls['freq_minus'].clicked.connect(lambda: self.adjust_sig_gen('freq', -100))
        self.controls['amp_plus'].clicked.connect(lambda: self.adjust_sig_gen('amp', 0.1))
        self.controls['amp_minus'].clicked.connect(lambda: self.adjust_sig_gen('amp', -0.1))
        self.controls['known_r_input'].editingFinished.connect(self._update_known_resistor)
        
    def _update_known_resistor(self):
        try:
            val = float(self.controls['known_r_input'].text())
            self.backend.known_resistor = val
            print(f"Known resistor updated to: {val} Ω")
        except ValueError:
            self.controls['known_r_input'].setText(f"{self.backend.known_resistor}")

    def update_info(self):
        data = self.backend.get_latest_data()
        self.info_widgets['voltage_value'].setText(f"{data['voltage_rms']:.4f} V")
        self.info_widgets['freq_value'].setText(f"{data['frequency']:.2f} Hz")
        if self.plot_window and self.plot_window.isVisible():
            self.plot_window.update_data(data["waveform"])

    def adjust_sig_gen(self, param, value):
        if param == 'freq': self.backend.signal_frequency = max(20, min(20000, self.backend.signal_frequency + value))
        elif param == 'amp': self.backend.signal_amplitude = max(0.1, min(1.0, self.backend.signal_amplitude + value))
        self.controls['freq_label'].setText(f"{self.backend.signal_frequency} Hz")
        self.controls['amp_label'].setText(f"{self.backend.signal_amplitude:.1f}")

    def toggle_signal_generator(self):
        if self.backend.generating_signal:
            self.backend.stop_signal_generation()
            self.controls['sig_gen_btn'].setText("Signal Gen: OFF")
            self.controls['sig_gen_btn'].setStyleSheet("background-color: #555;")
        else:
            self.backend.start_signal_generation()
            self.controls['sig_gen_btn'].setText("Signal Gen: ON")
            self.controls['sig_gen_btn'].setStyleSheet("background-color: #008888;")

    def toggle_plot_window(self):
        if not self.plot_window or not self.plot_window.isVisible():
            self.plot_window = PlotWindow(self.backend, self)
            self.plot_window.show()
        else:
            self.plot_window.raise_()
            self.plot_window.activateWindow()

    def set_measurement_mode(self, mode):
        self.reset_measurement_state()
        self.current_mode = mode
        mode_map = {
            'R': ("Resistance", "Ω"),
            'C': ("Capacitance", "μF"),
            'L': ("Inductance", "mH"),
            'AUTO': ("Auto Detect", "---"),
        }
        self.measurement_type_label.setText(mode_map[mode][0])
        self.unit_label.setText(mode_map[mode][1])
        self.result_label.setText("---")
        self.status_label.setText("Ready")
        
        if mode == 'R':
            self.known_r_recommendation_label.setText("Recommended: ~1000 Ω")
        elif mode == 'C':
            self.known_r_recommendation_label.setText("Recommended: 100 or 220 Ω for micro orders and larger for smaller orders.")
        elif mode == 'L':
            self.known_r_recommendation_label.setText("Recommended: 10 or 100 Ω for milli orders.")
        else:
            self.known_r_recommendation_label.setText("Choose R_known based on expected component.")

        self.apply_stylesheet()

    def on_action_button_clicked(self):
        if self.measurement_state == 'IDLE':
            if not self.backend.generating_signal:
                self.status_label.setText("Error: Turn on Signal Generator first.")
                return
            self.result_label.setText("---")
            
            if self.current_mode == 'AUTO':
                dialog = AutoDetectMethodDialog(self)
                if dialog.exec():
                    choice = dialog.method
                    if choice == 'frequency':
                        self.backend.signal_frequency = self.f_low
                        self.controls['freq_label'].setText(f"{self.backend.signal_frequency} Hz")
                        self.status_label.setText(f"STEP 1: Connect probes across source (Vin) at {self.f_low}Hz.")
                        self.action_button.setText("Continue")
                        self.measurement_state = 'AUTO_WAITING_FOR_VIN_LOW'
                    elif choice == 'phase':
                        self.status_label.setText("STEP 1: Connect probes across signal source (Vin).")
                        self.action_button.setText("Continue")
                        self.measurement_state = 'WAITING_FOR_VIN_PHASE'
                return 
            
            self.status_label.setText("STEP 1: Connect probes across signal source (Vin).")
            self.action_button.setText("Continue")
            self.measurement_state = 'WAITING_FOR_VIN_RMS'

        elif self.measurement_state == 'AUTO_WAITING_FOR_VIN_LOW':
            self.status_label.setText(f"Measuring Vin at {self.f_low}Hz...")
            self.action_button.setEnabled(False)
            self.start_rms_measurement(self.on_vin_low_measured)
        elif self.measurement_state == 'AUTO_WAITING_FOR_VOUT_LOW':
            self.status_label.setText(f"Measuring Vout at {self.f_low}Hz...")
            self.action_button.setEnabled(False)
            self.start_rms_measurement(self.on_vout_low_measured)
        elif self.measurement_state == 'AUTO_WAITING_FOR_VIN_HIGH':
            self.status_label.setText(f"Measuring Vin at {self.f_high}Hz...")
            self.action_button.setEnabled(False)
            self.start_rms_measurement(self.on_vin_high_measured)
        elif self.measurement_state == 'AUTO_WAITING_FOR_VOUT_HIGH':
            self.status_label.setText(f"Measuring Vout at {self.f_high}Hz...")
            self.action_button.setEnabled(False)
            self.start_rms_measurement(self.on_vout_high_measured)

        elif self.measurement_state == 'WAITING_FOR_VIN_RMS':
            self.status_label.setText("Measuring Vin... (2 seconds)")
            self.action_button.setEnabled(False)
            self.start_rms_measurement(self.on_vin_rms_measured)
        elif self.measurement_state == 'WAITING_FOR_VOUT_RMS':
            self.status_label.setText("Measuring Vout... (2 seconds)")
            self.action_button.setEnabled(False)
            self.start_rms_measurement(self.on_vout_rms_measured)
        elif self.measurement_state == 'WAITING_FOR_VIN_PHASE':
            self.status_label.setText("Measuring Vin Phase...")
            self.action_button.setEnabled(False)
            self.start_phase_measurement(self.on_vin_phase_measured)
        elif self.measurement_state == 'WAITING_FOR_VOUT_PHASE':
            self.status_label.setText("Measuring Vout Phase...")
            self.action_button.setEnabled(False)
            self.start_phase_measurement(self.on_vout_phase_measured)

    def start_rms_measurement(self, slot_to_connect):
        self.thread = QThread()
        self.worker = RMSWorker(self.backend)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(slot_to_connect)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()
        
    def start_phase_measurement(self, slot_to_connect):
        self.thread = QThread()
        self.worker = PhaseWorker(self.backend)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(slot_to_connect)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def on_vin_rms_measured(self, vin_value):
        if vin_value < 0.0001:
            self.status_label.setText(f"Error: Vin is too low ({vin_value:.5f}V). Restarting.")
            self.reset_measurement_state()
            return
        self.measured_vin_rms = vin_value
        
        component_name = {"R": "resistor", "C": "capacitor", "L": "inductor"}.get(self.current_mode, "component")
        self.status_label.setText(f"Vin={vin_value:.4f}V. STEP 2: Connect probes across {component_name} (Vout).")
        
        self.action_button.setEnabled(True)
        self.action_button.setText("Continue")
        self.measurement_state = 'WAITING_FOR_VOUT_RMS'

    def on_vout_rms_measured(self, vout_value):
        vin = self.measured_vin_rms
        if vin is None or vin <= 0:
            self.status_label.setText(f"Error: Vin invalid ({vin}). Restarting.")
            self.reset_measurement_state()
            return
        
        if vin <= vout_value:
            self.status_label.setText(f"Error: Vout>=Vin (Vout={vout_value:.4f}). Restarting.")
            self.result_label.setText("ERR")
        else:
            R_known = self.backend.known_resistor
            f = self.backend.signal_frequency
            
            if self.current_mode == 'R':
                resistance = R_known * vout_value / (vin - vout_value)
                self.result_label.setText(f"{resistance:.2f}")
            elif self.current_mode == 'C':
                try:
                    ratio = vin / vout_value
                    capacitance = (1 / (2 * math.pi * f)) * (1 / math.sqrt(ratio**2 - 1)) / R_known
                    self.result_label.setText(f"{capacitance * 1e6:.4f}") 
                except (ValueError, ZeroDivisionError):
                    self.result_label.setText("ERR")
            elif self.current_mode == 'L':
                try:
                    ratio = vout_value / vin
                    inductance = (R_known / (2 * math.pi * f)) * math.sqrt(ratio**2 / (1 - ratio**2))
                    self.result_label.setText(f"{inductance * 1000:.4f}") 
                except (ValueError, ZeroDivisionError):
                    self.result_label.setText("ERR")

            self.status_label.setText("Measurement Complete!")
        self.reset_measurement_state()

    def on_vin_low_measured(self, vin_value):
        self.measured_vin_low = vin_value
        self.status_label.setText(f"Vin_low={vin_value:.4f}V. STEP 2: Connect probes across component @ {self.f_low}Hz.")
        self.action_button.setEnabled(True)
        self.measurement_state = 'AUTO_WAITING_FOR_VOUT_LOW'

    def on_vout_low_measured(self, vout_value):
        self.measured_vout_low = vout_value
        self.backend.signal_frequency = self.f_high
        self.controls['freq_label'].setText(f"{self.backend.signal_frequency} Hz")
        self.status_label.setText(f"Vout_low={vout_value:.4f}V. STEP 3: Connect probes across source (Vin) @ {self.f_high}Hz.")
        self.action_button.setEnabled(True)
        self.measurement_state = 'AUTO_WAITING_FOR_VIN_HIGH'

    def on_vin_high_measured(self, vin_value):
        self.measured_vin_high = vin_value
        self.status_label.setText(f"Vin_high={vin_value:.4f}V. STEP 4: Connect probes across component @ {self.f_high}Hz.")
        self.action_button.setEnabled(True)
        self.measurement_state = 'AUTO_WAITING_FOR_VOUT_HIGH'

    def on_vout_high_measured(self, vout_value):
        self.measured_vout_high = vout_value
        self.action_button.setEnabled(False)
        self.status_label.setText("Analyzing results...")
        self.analyze_impedance_trend()

    def calculate_impedance_magnitude(self, vin, vout):
        if vin is None or vout is None or vin <= vout:
            return None
        try:
            R_known = self.backend.known_resistor
            ratio_sq = (vin / vout)**2
            impedance = R_known / math.sqrt(ratio_sq - 1)
            return impedance
        except (ValueError, ZeroDivisionError):
            return None
            
    def analyze_impedance_trend(self):
        z_low = self.calculate_impedance_magnitude(self.measured_vin_low, self.measured_vout_low)
        z_high = self.calculate_impedance_magnitude(self.measured_vin_high, self.measured_vout_high)

        if z_low is None or z_high is None or z_low <= 0 or z_high <= 0:
            self.result_label.setText("ERR")
            self.status_label.setText("Measurement error. Check connections.")
            self.reset_measurement_state()
            return
        
        # Check if impedance is very similar, suggesting a resistor
        impedance_ratio = max(z_low, z_high) / min(z_low, z_high)
        component_type = "Unknown"
        if impedance_ratio < 2:
            component_type = "Resistor"
        elif z_high < z_low: # Impedance decreases with frequency
            component_type = "Capacitor"
        else: # Impedance increases with frequency
            component_type = "Inductor"

        self.result_label.setText(component_type)
        self.status_label.setText(f"Detection Complete! |Z|@low={z_low:.1f}Ω, |Z|@high={z_high:.1f}Ω")
        self.backend.signal_frequency = 1000 # Reset frequency
        self.controls['freq_label'].setText(f"{self.backend.signal_frequency} Hz")
        self.reset_measurement_state()

    def on_vin_phase_measured(self, phase_value):
        self.measured_vin_phase = phase_value
        self.status_label.setText(f"Vin Phase={phase_value:.1f}°. STEP 2: Connect probes across component (Vout).")
        self.action_button.setEnabled(True)
        self.action_button.setText("Continue")
        self.measurement_state = 'WAITING_FOR_VOUT_PHASE'
        
    def on_vout_phase_measured(self, vout_phase):
        vin_phase = self.measured_vin_phase
        if vin_phase is None:
             self.status_label.setText(f"Error: Vin phase not measured. Restarting.")
             self.reset_measurement_state()
             return

        phase_diff = vout_phase - vin_phase
        # Normalize to -180 to 180 range
        while phase_diff > 180: phase_diff -= 360
        while phase_diff < -180: phase_diff += 360

        if abs(phase_diff) < 15: # Close to 0 degrees
            component_type = "Resistor"
        elif phase_diff < -15: # Negative phase shift (Vout lags Vin)
            component_type = "Capacitor"
        else: # Positive phase shift (Vout leads Vin)
            component_type = "Inductor"
            
        self.result_label.setText(component_type)
        self.status_label.setText(f"Detection Complete! (Phase Shift: {phase_diff:.1f}°)")
        self.reset_measurement_state()

    def reset_measurement_state(self):
        self.action_button.setEnabled(True)
        self.action_button.setText("MEASURE")
        self.measurement_state = 'IDLE'
        self.measured_vin_rms = None
        self.measured_vin_phase = None
        self.measured_vin_low = None
        self.measured_vout_low = None
        self.measured_vin_high = None
        self.measured_vout_high = None

    def apply_stylesheet(self):
        deep_bluish_green = "#006666"; deep_bluish_green_hover = "#005555"
        cyan = "#00FFFF"; cyan_hover = "#00DDDD"
        active_style = next((f"#{btn.objectName()}{{background-color:{cyan};color:#1E1E1E}} #{btn.objectName()}:hover{{background-color:{cyan_hover}}}"
                                       for mode, btn in self.mode_buttons.items() if mode == self.current_mode), "")
        self.setStyleSheet(f"""
            QWidget {{ background-color: #1E1E1E; color: #FFF; font-family: "Segoe UI", "Arial"; }}
            #result_label {{ font-size: 60px; color: {cyan}; qproperty-alignment: 'AlignCenter'; }}
            #unit_label {{ font-size: 30px; color: {cyan}; padding-top: 20px; }}
            QLabel {{ font-size: 14px; color: #AAA; padding: 5px; }}
            QPushButton {{ background-color: #333; font-size: 14px; font-weight: bold; border: 1px solid #555; padding: 10px; border-radius: 5px; }}
            QPushButton:hover {{ background-color: #444; }}
            QPushButton:disabled {{ background-color: #2a2a2a; color: #555; }}
            QLineEdit {{ border: 1px solid #555; padding: 5px; border-radius: 3px; background-color: #282828; font-size: 14px; }}
            {active_style}
            #measure_button {{ font-size: 20px; background-color: {deep_bluish_green}; }}
            #measure_button:hover {{ background-color: {deep_bluish_green_hover}; }}
            #measure_button:disabled {{ background-color: #555; }}
            #status_label {{ color: #AAA; font-size: 12px; padding: 5px; }}
            #recommendation_label {{ color: #888; font-style: italic; font-size: 11px; }}
        """)

    def closeEvent(self, event):
        self.info_update_timer.stop()
        if self.plot_window:
            self.plot_window.close()
        self.backend.close()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LCRMeterWindow()
    window.show()
    sys.exit(app.exec())