# LCR-Meter
This is a PC-based LCR Meter implemented in Python that utilizes a computer's audio port for signal generation and measurement of resistance, capacitance, and inductance, as well as an auto-detect feature.


## Features

* **Component Measurement**: Measures resistance (R), capacitance (C), and inductance (L) using a voltage divider method.
* **Auto-Detection**: Automatically identifies the component type by analyzing the phase shift between the input and output signals, and a more accurate method, which utilizes frequency sweep, was added as well.
* **Live Oscilloscope**: Includes a built-in oscilloscope using Matplotlib to visualize the real-time waveform of the signal being measured.
* **Adjustable Signal Generator**: Allows for manual control over the output signal's frequency and amplitude via the GUI.

---
## How It Works

The application functions as a basic function generator and oscilloscope. It generates a sine wave through the audio output and measures the resulting voltage at the audio input. All measurements are based on a **voltage divider circuit** composed of a known reference resistor ($R_{known}$) and the unknown component.

The measurement is a guided, two-step process:
1.  **Measure Input Voltage ($V_{in}$)**: The user first connects the probes to the source to establish a reference voltage and phase.
2.  **Measure Output Voltage ($V_{out}$)**: The user then connects the probes across the unknown component to measure the resulting voltage drop and phase shift.

The software calculates the component's value using formulas derived from the voltage divider rule. 

---
## Required Setup

### Software Libraries
The program relies on the following primary Python libraries:
* **PySide6**: For the graphical user interface. 
* **pyaudio**: For interacting with the computer's audio hardware.
* **numpy**: For numerical operations and Fast Fourier Transform (FFT) analysis.
* **matplotlib**: To create and embed the live oscilloscope plot.

### Physical Hardware
To connect components to your computer, you will need:
* A **3.5mm TRRS audio cable**. 
* Either a **TRRS breakout board** for easy connections or a **DIY setup** where the cable is cut and soldered to jumper jacks. A simple search online can guide you on the usage of each part of the wire.
* To protect your audio port and reduce noise, it is highly recommended to use **two large buffer resistors** (e.g., 100kΩ) on the input and output lines. More complicated and effective measures can be taken for this issue, but the simplest is the resistor method.

---
## Measurement Guidelines

For the best performance, the known reference resistor ($R_{known}$) should be chosen to be as close as possible to the expected value of the component being measured.

* **Resistors**: The meter is most accurate for resistances between **300Ω and 28kΩ**. A reference resistor of **1kΩ** is a good choice for this general range. 
* **Capacitors**:
    * For values between **1µF and 220µF**, a reference of **100Ω** is recommended.
    * For smaller values in the **100nF** range, a reference of **1kΩ or 10kΩ** is more suitable.
* **Inductors**: Good results were obtained for **1mH and 10mH** inductors using reference resistors of **10Ω and 100Ω**, respectively.



