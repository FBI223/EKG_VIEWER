import sys
import numpy as np
import wfdb
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import (
    QMainWindow, QPushButton, QFileDialog, QVBoxLayout, QWidget,
    QLabel, QScrollBar, QHBoxLayout, QLineEdit, QMessageBox, QComboBox,
    QSlider
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt

class ECGEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Editor")
        self.record = None
        self.annotations = None
        self.dat_file = ""
        self.atr_file = ""

        # Domyślna szerokość okna w sekundach (zoom czasowy)
        self.window_size_s = 5
        # Indeks próbki od której wyświetlamy wykres
        self.current_start = 0

        self.initUI()

    def initUI(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Główne pole wykresu
        self.canvas = FigureCanvas(plt.Figure(figsize=(8,4)))
        layout.addWidget(self.canvas)
        # Dwa pod-wykresy: górny sygnał ECG i dolny pasek adnotacji
        self.ax1, self.ax2 = self.canvas.figure.subplots(
            2, 1, sharex=True, gridspec_kw={'height_ratios': [4, 1]}
        )

        # Przyciski do wczytywania plików
        btn_layout = QHBoxLayout()
        self.btn_load_dat = QPushButton("Wczytaj plik .dat")
        self.btn_load_dat.clicked.connect(self.load_dat)
        btn_layout.addWidget(self.btn_load_dat)

        self.btn_load_atr = QPushButton("Wczytaj plik .atr/.ii")
        self.btn_load_atr.clicked.connect(self.load_atr)
        btn_layout.addWidget(self.btn_load_atr)
        layout.addLayout(btn_layout)

        # Wybór konkretnego odprowadzenia (kanału)
        lead_layout = QHBoxLayout()
        self.label_lead = QLabel("Lead:")
        lead_layout.addWidget(self.label_lead)
        self.combo_leads = QComboBox()
        self.combo_leads.currentIndexChanged.connect(self.update_plot)
        lead_layout.addWidget(self.combo_leads)
        layout.addLayout(lead_layout)

        # Suwak do zmiany szerokości okna (zoom czasowy)
        time_layout = QHBoxLayout()
        self.label_time = QLabel("Czas okna (s):")
        time_layout.addWidget(self.label_time)
        self.slider_time_window = QSlider(QtCore.Qt.Horizontal)
        self.slider_time_window.setRange(1, 30)
        self.slider_time_window.setValue(self.window_size_s)
        self.slider_time_window.valueChanged.connect(self.update_window_size)
        time_layout.addWidget(self.slider_time_window)
        layout.addLayout(time_layout)

        # Suwak do przewijania w czasie
        scroll_layout = QHBoxLayout()
        self.label_scroll = QLabel("Przewijanie:")
        scroll_layout.addWidget(self.label_scroll)
        self.scroll_bar = QScrollBar(QtCore.Qt.Horizontal)
        self.scroll_bar.valueChanged.connect(self.scroll_changed)
        scroll_layout.addWidget(self.scroll_bar)
        layout.addLayout(scroll_layout)

        # Dodawanie adnotacji
        annot_layout = QHBoxLayout()
        self.annot_input = QLineEdit()
        self.annot_input.setPlaceholderText("Wpisz adnotację")
        annot_layout.addWidget(self.annot_input)
        self.btn_add_annot = QPushButton("Dodaj adnotację")
        self.btn_add_annot.clicked.connect(self.add_annotation)
        annot_layout.addWidget(self.btn_add_annot)
        layout.addLayout(annot_layout)

    def load_dat(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Wczytaj plik .dat", "", "Pliki DAT (*.dat)"
        )
        if file_path:
            self.dat_file = file_path[:-4]  # ścieżka bez rozszerzenia .dat
            try:
                self.record = wfdb.rdrecord(self.dat_file)
                self.populate_leads()
                self.setup_scroll()
                self.update_plot()
            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))

    def load_atr(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Wczytaj plik .atr/.ii", "", "Pliki ATR (*.atr *.ii)"
        )
        if file_path:
            self.atr_file = file_path
            ext = file_path.split('.')[-1]
            try:
                self.annotations = wfdb.rdann(self.dat_file, ext)
                # Upewniamy się, że jeśli aux nie istnieje lub jest None, tworzymy pustą tablicę
                if not hasattr(self.annotations, 'aux') or self.annotations.aux is None:
                    self.annotations.aux = np.array([''] * len(self.annotations.sample))
                # Jeśli symbol nie istnieje, tworzymy pustą
                if not hasattr(self.annotations, 'symbol') or self.annotations.symbol is None:
                    self.annotations.symbol = ['?'] * len(self.annotations.sample)
                self.update_plot()
            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))

    def populate_leads(self):
        self.combo_leads.clear()
        if self.record is not None:
            # Dodajemy nazwy kanałów (jeśli są w pliku)
            if hasattr(self.record, 'sig_name') and self.record.sig_name:
                for name in self.record.sig_name:
                    self.combo_leads.addItem(name)
            else:
                for i in range(self.record.n_sig):
                    self.combo_leads.addItem(f"Lead {i+1}")

    def setup_scroll(self):
        """Ustawia zakres suwaka przewijania w zależności od długości sygnału."""
        if self.record is None:
            return
        total_samples = self.record.p_signal.shape[0]
        max_val = max(0, total_samples - int(self.window_size_s * self.record.fs))
        self.scroll_bar.setRange(0, max_val)

    def scroll_changed(self):
        """Reakcja na zmianę położenia suwaka przewijania."""
        self.current_start = self.scroll_bar.value()
        self.update_plot()

    def update_window_size(self):
        """Zmiana szerokości okna czasowego (zoom) na podstawie suwaka."""
        self.window_size_s = self.slider_time_window.value()
        self.setup_scroll()
        self.update_plot()

    def update_plot(self):
        """Odświeżenie wykresu w zależności od wybranego kanału, zakresu i adnotacji."""
        self.ax1.clear()
        self.ax2.clear()
        if self.record is not None:
            fs = self.record.fs
            total_samples = self.record.p_signal.shape[0]
            window_samples = int(self.window_size_s * fs)
            start_idx = self.current_start
            end_idx = min(start_idx + window_samples, total_samples)

            lead_idx = self.combo_leads.currentIndex()
            if lead_idx < 0:
                lead_idx = 0

            # Pobieramy fragment sygnału
            sig = self.record.p_signal[start_idx:end_idx, lead_idx]
            t = np.arange(start_idx, end_idx) / fs

            # Rysujemy sygnał w górnym panelu
            self.ax1.plot(t, sig, 'b-')

            # Rysujemy adnotacje w dolnym panelu
            if self.annotations is not None:
                ann_idx = (self.annotations.sample >= start_idx) & (self.annotations.sample < end_idx)
                ann_times = self.annotations.sample[ann_idx] / fs

                # W zależności od potrzeb, można wyświetlać 'symbol' albo 'aux'
                ann_symbols = np.array(self.annotations.symbol)[ann_idx]

                # Rysujemy trójkąty na górnym wykresie w miejscu adnotacji
                self.ax1.plot(
                    ann_times,
                    sig[self.annotations.sample[ann_idx] - start_idx],
                    'r^'
                )

                # Rysujemy symbole (literki) na dolnym pasku
                for at, sym in zip(ann_times, ann_symbols):
                    self.ax2.text(
                        at, 0, sym,
                        ha='center', va='center', fontsize=10
                    )

            # Dopasowanie osi
            if len(t) > 1:
                self.ax1.set_xlim(t[0], t[-1])
                self.ax2.set_xlim(t[0], t[-1])

            # Dolny panel (adnotacje) bez osi
            self.ax2.set_ylim(-1, 1)
            self.ax2.axis('off')

        self.canvas.draw()

    def add_annotation(self):
        """Dodawanie nowej adnotacji w miejscu aktualnego startu okna."""
        text = self.annot_input.text().strip()
        if text and self.record is not None:
            pos = self.current_start  # pozycja (w próbkach) = początek okna
            # Tworzymy nowy obiekt adnotacji jeśli nie istnieje
            if self.annotations is None:
                # Domyślnie symbol i aux mogą być tym samym, można to rozdzielić wg potrzeb
                self.annotations = wfdb.Annotation(
                    sample=np.array([pos]),
                    symbol=[text],
                    aux=np.array([text]),
                    fs=self.record.fs
                )
            else:
                self.annotations.sample = np.append(self.annotations.sample, pos)

                # Uzupełniamy symbol
                if not hasattr(self.annotations, 'symbol') or self.annotations.symbol is None:
                    self.annotations.symbol = ['?'] * (len(self.annotations.sample) - 1)
                self.annotations.symbol.append(text)

                # Uzupełniamy aux
                if not hasattr(self.annotations, 'aux') or self.annotations.aux is None:
                    self.annotations.aux = np.array([''] * (len(self.annotations.sample) - 1))
                self.annotations.aux = np.append(self.annotations.aux, text)

            self.annot_input.clear()
            self.update_plot()

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    editor = ECGEditor()
    editor.show()
    sys.exit(app.exec_())
