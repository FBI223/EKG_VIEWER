import sys
import numpy as np
import wfdb
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import (
    QMainWindow, QPushButton, QFileDialog, QVBoxLayout, QWidget,
    QLabel, QScrollBar, QHBoxLayout, QLineEdit, QMessageBox, QComboBox,
    QSlider, QDialog, QFormLayout, QDialogButtonBox
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt

class AnnotationDialog(QDialog):
    def __init__(self, sample, fs, symbol, idx, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edycja adnotacji")
        self.idx = idx
        self.fs = fs
        layout = QFormLayout(self)

        self.sample_edit = QLineEdit(str(sample))
        layout.addRow("Pozycja (próbka):", self.sample_edit)

        time_s = sample / fs
        self.time_edit = QLineEdit(f"{time_s:.3f}")
        layout.addRow("Czas (s):", self.time_edit)

        self.symbol_edit = QLineEdit(symbol)
        layout.addRow("Symbol:", self.symbol_edit)

        self.btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.btn_delete = QPushButton("Usuń")
        self.btn_delete.clicked.connect(self.delete_annotation)
        self.btn_box.addButton(self.btn_delete, QDialogButtonBox.ActionRole)
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addRow(self.btn_box)

        self.deleted = False

    def delete_annotation(self):
        self.deleted = True
        self.accept()

    def get_data(self):
        return {
            "sample": int(self.sample_edit.text()),
            "symbol": self.symbol_edit.text(),
            "deleted": self.deleted
        }

    def accept(self):
        # Jeśli użytkownik zmienił czas (s), przeliczamy na próbki
        try:
            new_time = float(self.time_edit.text())
            new_sample = int(new_time * self.fs)
            self.sample_edit.setText(str(new_sample))
        except:
            pass
        super().accept()


class ECGEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ECG Editor")
        self.record = None
        self.annotations = None
        self.dat_file = ""
        self.atr_file = ""
        self.window_size_s = 5
        self.current_start = 0
        self.annot_artists = []  # Do przechowywania referencji do rysowanych adnotacji
        self.initUI()

    def initUI(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.canvas = FigureCanvas(plt.Figure(figsize=(8,4)))
        layout.addWidget(self.canvas)
        self.ax1, self.ax2 = self.canvas.figure.subplots(2,1,sharex=True,
                                                         gridspec_kw={'height_ratios':[4,1]})
        # Podpinamy obsługę kliknięć w wykres
        self.cid = self.canvas.mpl_connect('button_press_event', self.on_click)

        btn_layout = QHBoxLayout()
        self.btn_load_dat = QPushButton("Wczytaj plik .dat")
        self.btn_load_dat.clicked.connect(self.load_dat)
        btn_layout.addWidget(self.btn_load_dat)
        self.btn_load_atr = QPushButton("Wczytaj plik .atr/.ii")
        self.btn_load_atr.clicked.connect(self.load_atr)
        btn_layout.addWidget(self.btn_load_atr)
        layout.addLayout(btn_layout)

        lead_layout = QHBoxLayout()
        self.label_lead = QLabel("Lead:")
        lead_layout.addWidget(self.label_lead)
        self.combo_leads = QComboBox()
        self.combo_leads.currentIndexChanged.connect(self.update_plot)
        lead_layout.addWidget(self.combo_leads)
        layout.addLayout(lead_layout)

        # Suwak do szerokości okna
        time_layout = QHBoxLayout()
        self.label_time = QLabel("Czas okna (s):")
        time_layout.addWidget(self.label_time)
        self.slider_time_window = QSlider(QtCore.Qt.Horizontal)
        self.slider_time_window.setRange(1, 30)
        self.slider_time_window.setValue(self.window_size_s)
        self.slider_time_window.valueChanged.connect(self.update_window_size)
        time_layout.addWidget(self.slider_time_window)
        layout.addLayout(time_layout)

        # Suwak do przewijania
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
        file_path, _ = QFileDialog.getOpenFileName(self, "Wczytaj plik .dat", "", "Pliki DAT (*.dat)")
        if file_path:
            self.dat_file = file_path[:-4]
            try:
                self.record = wfdb.rdrecord(self.dat_file)
                self.populate_leads()
                self.setup_scroll()
                self.update_plot()
            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))

    def load_atr(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Wczytaj plik .atr/.ii", "", "Pliki ATR (*.atr *.ii)")
        if file_path:
            self.atr_file = file_path
            ext = file_path.split('.')[-1]
            try:
                self.annotations = wfdb.rdann(self.dat_file, ext)
                if not hasattr(self.annotations, 'aux') or self.annotations.aux is None:
                    self.annotations.aux = np.array([''] * len(self.annotations.sample))
                if not hasattr(self.annotations, 'symbol') or self.annotations.symbol is None:
                    self.annotations.symbol = ['?'] * len(self.annotations.sample)
                self.update_plot()
            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))

    def populate_leads(self):
        self.combo_leads.clear()
        if self.record is not None:
            if hasattr(self.record, 'sig_name') and self.record.sig_name:
                for name in self.record.sig_name:
                    self.combo_leads.addItem(name)
            else:
                for i in range(self.record.n_sig):
                    self.combo_leads.addItem(f"Lead {i+1}")

    def setup_scroll(self):
        if self.record is None: return
        total_samples = self.record.p_signal.shape[0]
        max_val = max(0, total_samples - int(self.window_size_s*self.record.fs))
        self.scroll_bar.setRange(0, max_val)

    def scroll_changed(self):
        self.current_start = self.scroll_bar.value()
        self.update_plot()

    def update_window_size(self):
        self.window_size_s = self.slider_time_window.value()
        self.setup_scroll()
        self.update_plot()

    def update_plot(self):
        self.ax1.clear()
        self.ax2.clear()
        self.annot_artists = []
        if self.record is not None:
            fs = self.record.fs
            total_samples = self.record.p_signal.shape[0]
            window_samples = int(self.window_size_s * fs)
            start_idx = self.current_start
            end_idx = min(start_idx + window_samples, total_samples)

            lead_idx = self.combo_leads.currentIndex()
            if lead_idx < 0: lead_idx = 0

            sig = self.record.p_signal[start_idx:end_idx, lead_idx]
            t = np.arange(start_idx, end_idx) / fs
            self.ax1.plot(t, sig, 'b-')
            self.ax1.set_xlabel("Czas (s)")
            self.ax1.grid(True)

            if self.annotations is not None:
                ann_idx = (self.annotations.sample>=start_idx)&(self.annotations.sample<end_idx)
                ann_samples = self.annotations.sample[ann_idx]
                ann_times = ann_samples / fs
                ann_symbols = np.array(self.annotations.symbol)[ann_idx]

                # Górne znaczniki
                self.ax1.plot(ann_times, sig[ann_samples - start_idx], 'r^')
                # Dolne literki
                for i, (at, sym) in enumerate(zip(ann_times, ann_symbols)):
                    art = self.ax2.text(at, 0, sym, ha='center', va='center', fontsize=10,
                                        picker=True)  # picker=True, by kliknąć
                    self.annot_artists.append((art, ann_samples[i]))  # zapamiętujemy (artist, rzeczywista próbka)

            self.ax2.set_xlim(self.ax1.get_xlim())
            self.ax2.set_ylim(-1,1)
            self.ax2.set_xlabel("Czas (s)")
            self.ax2.axis('on')
            self.ax2.get_yaxis().set_visible(False)
            self.ax2.set_yticks([])

        self.canvas.draw()

    def add_annotation(self):
        text = self.annot_input.text().strip()
        if text and self.record is not None:
            pos = self.current_start
            if self.annotations is None:
                self.annotations = wfdb.Annotation(
                    sample=np.array([pos]),
                    symbol=[text],
                    aux=np.array([text]),
                    fs=self.record.fs
                )
            else:
                self.annotations.sample = np.append(self.annotations.sample, pos)
                if not hasattr(self.annotations, 'symbol') or self.annotations.symbol is None:
                    self.annotations.symbol = ['?']*(len(self.annotations.sample)-1)
                self.annotations.symbol.append(text)
                if not hasattr(self.annotations, 'aux') or self.annotations.aux is None:
                    self.annotations.aux = np.array(['']*(len(self.annotations.sample)-1))
                self.annotations.aux = np.append(self.annotations.aux, text)
            self.annot_input.clear()
            self.update_plot()

    def on_click(self, event):
        # Sprawdzamy, czy kliknięto w obszar rysowania adnotacji
        if event.inaxes == self.ax2:
            # Szukamy najbliższego elementu z self.annot_artists
            # Matplotlib automatycznie wykryje obiekt z param picker=True
            for artist, sample_val in self.annot_artists:
                cont, _ = artist.contains(event)
                if cont:
                    self.edit_annotation(sample_val)
                    break

    def edit_annotation(self, sample_val):
        # Szukamy indeksu adnotacji w self.annotations.sample
        idxs = np.where(self.annotations.sample == sample_val)[0]
        if len(idxs) == 0:
            return
        idx = idxs[0]

        symbol = self.annotations.symbol[idx]
        dlg = AnnotationDialog(sample_val, self.record.fs, symbol, idx, self)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            if data["deleted"]:
                # Usuwamy adnotację
                self.annotations.sample = np.delete(self.annotations.sample, idx)
                self.annotations.symbol.pop(idx)
                if len(self.annotations.aux) > idx:
                    self.annotations.aux = np.delete(self.annotations.aux, idx)
            else:
                # Zmieniamy pozycję i symbol
                new_sample = data["sample"]
                self.annotations.sample[idx] = new_sample
                self.annotations.symbol[idx] = data["symbol"]
                if len(self.annotations.aux) > idx:
                    self.annotations.aux[idx] = data["symbol"]
            self.update_plot()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    editor = ECGEditor()
    editor.show()
    sys.exit(app.exec_())
