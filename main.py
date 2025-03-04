import sys
import numpy as np
import wfdb
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import (
    QMainWindow, QPushButton, QFileDialog, QVBoxLayout, QWidget,
    QLabel, QScrollBar, QHBoxLayout, QMessageBox, QComboBox,
    QSlider, QDialog, QFormLayout, QDialogButtonBox, QInputDialog, QMenu, QLineEdit
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
        layout.addRow("Próbka (indeks):", self.sample_edit)
        self.time_edit = QLineEdit(f"{sample/fs:.3f}")
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
        try:
            new_time = float(self.time_edit.text())
            new_sample = int(new_time * self.fs)
            self.sample_edit.setText(str(new_sample))
        except Exception:
            pass
        super().accept()

class SignalEditDialog(QDialog):
    def __init__(self, sample_idx, fs, current_value, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edycja próbki sygnału")
        self.fs = fs
        layout = QFormLayout(self)
        self.sample_idx_edit = QLineEdit(str(sample_idx))
        layout.addRow("Próbka (indeks):", self.sample_idx_edit)
        self.time_edit = QLineEdit(f"{sample_idx/fs:.3f}")
        layout.addRow("Czas (s):", self.time_edit)
        self.value_edit = QLineEdit(str(current_value))
        layout.addRow("Wartość:", self.value_edit)
        self.btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addRow(self.btn_box)

    def get_data(self):
        return int(self.sample_idx_edit.text()), float(self.value_edit.text())

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
        self.annot_artists = []  # List of tuples (artist, annotation index)
        self.drag_annotation = None
        self.drag_offset = 0
        self.drag_index = None
        self.initUI()

    def initUI(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.canvas = FigureCanvas(plt.Figure(figsize=(10,5)))
        layout.addWidget(self.canvas)
        self.ax1, self.ax2 = self.canvas.figure.subplots(2,1, sharex=True,
                                                         gridspec_kw={'height_ratios':[4, 1]})
        self.ax1.set_xlabel("Czas (s)")
        self.ax2.set_xlabel("Czas (s)")
        self.ax1.grid(True)
        self.ax2.grid(True)
        self.ax2.get_yaxis().set_visible(False)

        self.canvas.mpl_connect('button_press_event', self.on_press)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion)
        self.canvas.mpl_connect('button_release_event', self.on_release)

        file_btn_layout = QHBoxLayout()
        self.btn_load_dat = QPushButton("Wczytaj .dat")
        self.btn_load_dat.clicked.connect(self.load_dat)
        file_btn_layout.addWidget(self.btn_load_dat)
        self.btn_save_dat = QPushButton("Zapisz .dat")
        self.btn_save_dat.clicked.connect(self.save_dat)
        file_btn_layout.addWidget(self.btn_save_dat)
        self.btn_load_atr = QPushButton("Wczytaj .atr/.ii")
        self.btn_load_atr.clicked.connect(self.load_atr)
        file_btn_layout.addWidget(self.btn_load_atr)
        self.btn_save_atr = QPushButton("Zapisz .atr/.ii")
        self.btn_save_atr.clicked.connect(self.save_atr)
        file_btn_layout.addWidget(self.btn_save_atr)
        layout.addLayout(file_btn_layout)

        lead_layout = QHBoxLayout()
        self.label_lead = QLabel("Lead:")
        lead_layout.addWidget(self.label_lead)
        self.combo_leads = QComboBox()
        self.combo_leads.currentIndexChanged.connect(self.update_plot)
        lead_layout.addWidget(self.combo_leads)
        layout.addLayout(lead_layout)

        time_layout = QHBoxLayout()
        self.label_time = QLabel("Czas okna (s):")
        time_layout.addWidget(self.label_time)
        self.slider_time_window = QSlider(QtCore.Qt.Horizontal)
        self.slider_time_window.setRange(1, 30)
        self.slider_time_window.setValue(self.window_size_s)
        self.slider_time_window.valueChanged.connect(self.update_window_size)
        time_layout.addWidget(self.slider_time_window)
        layout.addLayout(time_layout)

        scroll_layout = QHBoxLayout()
        self.label_scroll = QLabel("Przewijanie:")
        scroll_layout.addWidget(self.label_scroll)
        self.scroll_bar = QScrollBar(QtCore.Qt.Horizontal)
        self.scroll_bar.valueChanged.connect(self.scroll_changed)
        scroll_layout.addWidget(self.scroll_bar)
        layout.addLayout(scroll_layout)

    def load_dat(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Wczytaj .dat", "", "Pliki DAT (*.dat)")
        if file_path:
            self.dat_file = file_path[:-4]
            try:
                self.record = wfdb.rdrecord(self.dat_file)
                self.populate_leads()
                self.setup_scroll()
                self.update_plot()
            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))

    def save_dat(self):
        if self.record is None:
            QMessageBox.warning(self, "Błąd", "Brak załadowanego pliku DAT.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Zapisz .dat", "", "Pliki DAT (*.dat)")
        if file_path:
            out_name = file_path.rsplit('.', 1)[0]
            fmt = self.record.fmt if hasattr(self.record, 'fmt') else '16'
            try:
                wfdb.wrrecord(out_name, p_signal=self.record.p_signal, fs=self.record.fs,
                              sig_name=self.record.sig_name, fmt=fmt)
                QMessageBox.information(self, "Sukces", "Plik DAT zapisany.")
            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))

    def load_atr(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Wczytaj .atr/.ii", "", "Pliki ATR (*.atr *.ii)")
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

    def save_atr(self):
        if self.annotations is None:
            QMessageBox.warning(self, "Błąd", "Brak załadowanego pliku ATR.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Zapisz .atr/.ii", "", "Pliki ATR (*.atr *.ii)")
        if file_path:
            out_name = file_path.rsplit('.', 1)[0]
            ext = self.atr_file.split('.')[-1] if self.atr_file else 'atr'
            try:
                wfdb.wrann(out_name, ext, self.annotations.sample, self.annotations.symbol,
                           aux=self.annotations.aux, fs=self.record.fs)
                QMessageBox.information(self, "Sukces", "Plik ATR zapisany.")
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
        if self.record is None:
            return
        total = self.record.p_signal.shape[0]
        max_val = max(0, total - int(self.window_size_s * self.record.fs))
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
        if self.record is None:
            self.canvas.draw()
            return
        fs = self.record.fs
        total = self.record.p_signal.shape[0]
        win_samples = int(self.window_size_s * fs)
        start = self.current_start
        end = min(start + win_samples, total)
        lead = self.combo_leads.currentIndex() if self.combo_leads.currentIndex() >= 0 else 0
        sig = self.record.p_signal[start:end, lead]
        t = np.arange(start, end) / fs
        self.ax1.plot(t, sig, 'b-')
        self.ax1.set_xlabel("Czas (s)")
        self.ax1.grid(True)
        if self.annotations is not None and len(self.annotations.sample):
            ann_mask = (self.annotations.sample >= start) & (self.annotations.sample < end)
            ann_samples = self.annotations.sample[ann_mask]
            ann_times = ann_samples / fs
            ann_syms = np.array(self.annotations.symbol)[ann_mask]
            self.ax1.plot(ann_times, sig[ann_samples - start], 'r^')
            for i, (at, sym) in enumerate(zip(ann_times, ann_syms)):
                art = self.ax2.text(at, 0, sym, ha='center', va='center', fontsize=10, picker=True)
                # Store tuple: (artist, global annotation index)
                global_idx = np.where(self.annotations.sample == ann_samples[i])[0][0]
                self.annot_artists.append((art, global_idx))
        self.ax2.set_xlim(self.ax1.get_xlim())
        self.ax2.set_ylim(-1, 1)
        self.ax2.set_xlabel("Czas (s)")
        self.ax2.get_yaxis().set_visible(False)
        self.canvas.draw()

    def on_press(self, event):
        if event.inaxes == self.ax2 and event.button == 1:
            # Check for double click to open edit dialog
            for artist, idx in self.annot_artists:
                contains, _ = artist.contains(event)
                if contains:
                    if event.dblclick:
                        self.edit_annotation(idx)
                        return
                    else:
                        self.drag_annotation = artist
                        self.drag_index = idx
                        self.drag_offset = event.xdata - artist.get_position()[0]
                        return
        if event.inaxes == self.ax1 and event.button == 3:
            self.show_context_menu(event)

    def on_motion(self, event):
        if self.drag_annotation is not None and event.inaxes == self.ax2:
            new_x = event.xdata - self.drag_offset
            pos = self.drag_annotation.get_position()
            self.drag_annotation.set_position((new_x, pos[1]))
            self.canvas.draw_idle()

    def on_release(self, event):
        if self.drag_annotation is not None and event.inaxes == self.ax2:
            fs = self.record.fs
            new_time = self.drag_annotation.get_position()[0]
            new_sample = int(round(new_time * fs))
            if self.annotations is not None and self.drag_index is not None:
                self.annotations.sample[self.drag_index] = new_sample
            self.drag_annotation = None
            self.drag_index = None
            self.update_plot()

    def show_context_menu(self, event):
        menu = QMenu(self)
        act_edit = menu.addAction("Edytuj próbkę")
        act_add = menu.addAction("Dodaj adnotację")
        action = menu.exec_(self.mapToGlobal(QtCore.QPoint(int(event.guiEvent.x()), int(event.guiEvent.y()))))
        fs = self.record.fs
        sample_idx = int(round(event.xdata * fs))
        lead = self.combo_leads.currentIndex() if self.combo_leads.currentIndex() >= 0 else 0
        if action == act_edit:
            current_value = self.record.p_signal[sample_idx, lead]
            dlg = SignalEditDialog(sample_idx, fs, current_value, self)
            if dlg.exec_() == QDialog.Accepted:
                new_idx, new_val = dlg.get_data()
                if 0 <= new_idx < self.record.p_signal.shape[0]:
                    self.record.p_signal[new_idx, lead] = new_val
                    self.update_plot()
        elif action == act_add:
            sym, ok = QInputDialog.getText(self, "Dodaj adnotację", "Symbol adnotacji:",
                                           text="A")
            if ok and sym:
                # Optionally, allow manual input of sample index via another dialog
                # Here sample is taken from the click location
                if self.annotations is None:
                    self.annotations = wfdb.Annotation(
                        sample=np.array([sample_idx]),
                        symbol=[sym],
                        aux=np.array([sym]),
                        fs=fs
                    )
                else:
                    self.annotations.sample = np.append(self.annotations.sample, sample_idx)
                    self.annotations.symbol = list(self.annotations.symbol) + [sym]
                    if hasattr(self.annotations, 'aux') and self.annotations.aux is not None:
                        self.annotations.aux = np.append(self.annotations.aux, sym)
                    else:
                        self.annotations.aux = np.array([sym]*len(self.annotations.sample))
                self.update_plot()

    def edit_annotation(self, global_idx):
        if self.annotations is None:
            return
        symbol = self.annotations.symbol[global_idx]
        sample_val = self.annotations.sample[global_idx]
        dlg = AnnotationDialog(sample_val, self.record.fs, symbol, global_idx, self)
        if dlg.exec_() == QDialog.Accepted:
            data = dlg.get_data()
            if data["deleted"]:
                self.annotations.sample = np.delete(self.annotations.sample, global_idx)
                self.annotations.symbol.pop(global_idx)
                if hasattr(self.annotations, 'aux') and len(self.annotations.aux) > global_idx:
                    self.annotations.aux = np.delete(self.annotations.aux, global_idx)
            else:
                new_sample = data["sample"]
                self.annotations.sample[global_idx] = new_sample
                self.annotations.symbol[global_idx] = data["symbol"]
                if hasattr(self.annotations, 'aux') and len(self.annotations.aux) > global_idx:
                    self.annotations.aux[global_idx] = data["symbol"]
            self.update_plot()

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    editor = ECGEditor()
    editor.show()
    sys.exit(app.exec_())
