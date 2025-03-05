import sys
import copy
import os
import re
import numpy as np
import wfdb
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtWidgets import (
    QMainWindow, QPushButton, QFileDialog, QVBoxLayout, QWidget,
    QLabel, QScrollBar, QHBoxLayout, QMessageBox, QComboBox,
    QSlider, QDialog, QFormLayout, QDialogButtonBox, QInputDialog, QLineEdit
)
from PyQt6.QtCore import pyqtSlot
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseEvent
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView



class DataInfoDialog(QDialog):
    def __init__(self, parent, data, title, headers):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)

        self.table = QTableWidget()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(len(data))

        for row_idx, row_data in enumerate(data):
            for col_idx, value in enumerate(row_data):
                self.table.setItem(row_idx, col_idx, QTableWidgetItem(str(value)))

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)


def sanitize_record_name(name: str) -> str:
    return re.sub(r'\W+', '_', name)

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
        self.btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.btn_delete = QPushButton("Usuń")
        self.btn_delete.clicked.connect(self.delete_annotation)
        self.btn_box.addButton(self.btn_delete, QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addRow(self.btn_box)
        self.deleted = False

    @pyqtSlot()
    def delete_annotation(self) -> None:
        self.deleted = True
        self.accept()

    def get_data(self):
        return {
            "sample": int(self.sample_edit.text()),
            "symbol": self.symbol_edit.text(),
            "deleted": self.deleted
        }

    @pyqtSlot()
    def accept(self) -> None:
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
        self.btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
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
        self.annotations = None  # Kopia pliku ATR – tu będą zmiany
        self.atr_original_path = ""  # Ścieżka oryginalnego pliku ATR
        self.dat_file = ""
        self.atr_file = ""  # Ścieżka, na której pracujemy
        self.window_size_s = 5
        self.current_start = 0
        self.annot_artists = []
        self.drag_annotation = None
        self.drag_offset = 0
        self.drag_index = None
        self.initUI()



    def initUI(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.canvas = FigureCanvas(plt.Figure(figsize=(20, 10)))
        layout.addWidget(self.canvas)
        self.ax1, self.ax2 = self.canvas.figure.subplots(
            2, 1, sharex=True, gridspec_kw={'height_ratios': [4, 1]}
        )
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

        self.btn_load_atr = QPushButton("Wczytaj .atr/.ii")
        self.btn_load_atr.clicked.connect(self.load_atr)
        self.btn_load_atr.setEnabled(False)  # Plik ATR można wczytać dopiero po pliku DAT
        file_btn_layout.addWidget(self.btn_load_atr)

        self.btn_save_atr = QPushButton("Zapisz .atr/.ii")
        self.btn_save_atr.clicked.connect(self.save_atr)
        self.btn_save_atr.setEnabled(False)  # Zablokowane na starcie
        file_btn_layout.addWidget(self.btn_save_atr)

        layout.addLayout(file_btn_layout)

        lead_layout = QHBoxLayout()
        self.label_lead = QLabel("Lead:")
        lead_layout.addWidget(self.label_lead)

        self.combo_leads = QComboBox()
        self.combo_leads.currentIndexChanged.connect(self.update_plot)
        self.combo_leads.setEnabled(False)  # Zablokowane na starcie
        lead_layout.addWidget(self.combo_leads)

        layout.addLayout(lead_layout)

        time_layout = QHBoxLayout()
        self.label_time = QLabel("Czas okna (s):")
        time_layout.addWidget(self.label_time)

        self.slider_time_window = QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_time_window.setRange(1, 30)
        self.slider_time_window.setValue(self.window_size_s)
        self.slider_time_window.valueChanged.connect(self.update_window_size)
        self.slider_time_window.setEnabled(False)  # Zablokowane na starcie
        time_layout.addWidget(self.slider_time_window)

        layout.addLayout(time_layout)

        scroll_layout = QHBoxLayout()
        self.label_scroll = QLabel("Przewijanie:")
        scroll_layout.addWidget(self.label_scroll)

        self.scroll_bar = QScrollBar(QtCore.Qt.Orientation.Horizontal)
        self.scroll_bar.valueChanged.connect(self.scroll_changed)
        self.scroll_bar.setEnabled(False)  # Zablokowane na starcie
        scroll_layout.addWidget(self.scroll_bar)

        layout.addLayout(scroll_layout)


        self.btn_show_info = QPushButton("Show Signal Info")
        self.btn_show_info.clicked.connect(self.show_signal_info)
        self.btn_show_info.setEnabled(False)  # Domyślnie zablokowane
        layout.addWidget(self.btn_show_info)


    def show_signal_info(self):
        """ Wyświetla tabelę z danymi sygnału oraz adnotacjami z możliwością wyszukiwania próbki """
        if self.record is None or self.annotations is None:
            QMessageBox.warning(self, "Błąd", "Najpierw wczytaj pliki .dat i .atr!")
            return

        fs = self.record.fs  # Częstotliwość próbkowania
        total_samples = len(self.record.p_signal)  # Liczba próbek

        # Pobranie adnotacji (jeśli brak, zostaną puste wartości)
        annotation_dict = {int(s): sym for s, sym in zip(self.annotations.sample, self.annotations.symbol)}

        # 🔹 **Lista próbek: co 100 + wszystkie z adnotacjami**
        sample_indices = sorted(set(range(0, total_samples, 100)) | set(annotation_dict.keys()))

        # Przygotowanie danych do tabeli (próbka, czas, wartość, adnotacja)
        self.signal_data = [
            (sample, (sample / fs) * 1000, self.record.p_signal[sample, 0], annotation_dict.get(sample, ""))
            for sample in sample_indices
        ]

        # Tworzenie okna tabeli
        self.dialog = QDialog(self)
        self.dialog.setWindowTitle("Informacje o sygnale")
        self.dialog.resize(1000, 700)  # **Większe okno**
        layout = QVBoxLayout(self.dialog)

        # Tworzenie tabeli
        self.table = QtWidgets.QTableWidget(len(self.signal_data), 4)
        self.table.setHorizontalHeaderLabels(["Próbka", "Czas (ms)", "Wartość", "Adnotacja"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)  # **Wyłączenie sortowania przy wypełnianiu**

        # Wypełnianie tabeli
        for row_idx, (sample_id, time_ms, value, annotation) in enumerate(self.signal_data):
            item_sample = QtWidgets.QTableWidgetItem(str(sample_id))
            item_sample.setData(QtCore.Qt.ItemDataRole.UserRole, sample_id)  # **Dane liczbowe do sortowania**
            self.table.setItem(row_idx, 0, item_sample)

            self.table.setItem(row_idx, 1, QtWidgets.QTableWidgetItem(f"{time_ms:.2f}"))
            self.table.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(f"{value:.3f}"))
            self.table.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(annotation))

        self.table.setSortingEnabled(True)
        self.table.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)  # **Sortowanie rosnące od razu**

        layout.addWidget(self.table)

        # Przycisk zamknięcia
        btn_close = QPushButton("Zamknij")
        btn_close.clicked.connect(self.dialog.accept)
        layout.addWidget(btn_close)

        self.dialog.setLayout(layout)
        self.dialog.exec()





    def keyPressEvent(self, event):
        """ Obsługa klawiszy A/D i strzałek ← → do przesuwania sygnału """
        if self.record is None:
            return  # Nie rób nic, jeśli nie ma załadowanego sygnału

        step = int(self.record.fs * 0.5)  # Przesunięcie o 0.5 sekundy

        if event.key() == QtCore.Qt.Key.Key_A or event.key() == QtCore.Qt.Key.Key_Left:
            self.scroll_bar.setValue(self.scroll_bar.value() - step)  # Przesuwaj w lewo
        elif event.key() == QtCore.Qt.Key.Key_D or event.key() == QtCore.Qt.Key.Key_Right:
            self.scroll_bar.setValue(self.scroll_bar.value() + step)  # Przesuwaj w prawo

    @pyqtSlot()
    def load_dat(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Wczytaj .dat", "", "Pliki DAT (*.dat)")
        if file_path:
            self.dat_file = file_path[:-4]
            try:
                self.record = wfdb.rdrecord(self.dat_file)
                self.populate_leads()
                self.setup_scroll()
                self.update_plot()


                self.combo_leads.setEnabled(True)
                self.slider_time_window.setEnabled(True)
                self.scroll_bar.setEnabled(True)
                self.btn_load_atr.setEnabled(True)

            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))


    @pyqtSlot()
    def load_atr(self) -> None:

        if not self.record:
            QMessageBox.warning(self, "Błąd", "Najpierw wczytaj plik .dat!")
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Wczytaj .atr/.ii", "", "Pliki ATR (*.atr *.ii)")
        if file_path:
            self.atr_original_path = file_path  # Zapamiętujemy oryginalną ścieżkę
            self.atr_file = file_path  # Pracujemy na tym pliku (w kopii)
            ext = file_path.split('.')[-1]
            try:
                # Tworzymy głęboką kopię adnotacji z oryginalnego pliku
                original_ann = wfdb.rdann(self.dat_file, ext)
                self.annotations = copy.deepcopy(original_ann)
                if not hasattr(self.annotations, 'aux') or self.annotations.aux is None:
                    self.annotations.aux = np.array([''] * len(self.annotations.sample))
                if not hasattr(self.annotations, 'symbol') or self.annotations.symbol is None:
                    self.annotations.symbol = ['?'] * len(self.annotations.sample)
                self.update_plot()

                self.btn_save_atr.setEnabled(True)
                self.btn_show_info.setEnabled(True)

            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))

    def auto_save_atr(self) -> None:
        if self.atr_file and self.annotations is not None and self.record is not None:
            out_dir = os.path.dirname(self.atr_file)
            base = os.path.basename(self.atr_file)
            base = os.path.splitext(base)[0]
            sanitized_base = sanitize_record_name(base)
            ext = os.path.splitext(self.atr_file)[1].lstrip('.') or 'atr'
            current_dir = os.getcwd()
            # Sortowanie adnotacji – uporządkuj próbki oraz odpowiadające im symbole
            sort_idx = np.argsort(self.annotations.sample)
            sorted_samples = self.annotations.sample[sort_idx]
            sorted_symbols = np.array(self.annotations.symbol)[sort_idx]
            try:
                os.chdir(out_dir)
                wfdb.wrann(sanitized_base, ext, sorted_samples, sorted_symbols, fs=self.record.fs)
            except Exception as e:
                print("Auto-save ATR error:", e)
            finally:
                os.chdir(current_dir)

    @pyqtSlot()
    def save_atr(self) -> None:
        if self.annotations is None:
            QMessageBox.warning(self, "Błąd", "Brak załadowanego pliku ATR.")
            return
        default_dir = os.path.dirname(self.atr_original_path) if self.atr_original_path else ""
        file_path, _ = QFileDialog.getSaveFileName(self, "Zapisz .atr/.ii", default_dir, "Pliki ATR (*.atr *.ii)")
        if file_path:
            out_dir = os.path.dirname(file_path)
            base = os.path.basename(file_path)
            base = os.path.splitext(base)[0]
            sanitized_base = sanitize_record_name(base)
            ext = os.path.splitext(file_path)[1].lstrip('.') or 'atr'
            current_dir = os.getcwd()
            sort_idx = np.argsort(self.annotations.sample)
            sorted_samples = self.annotations.sample[sort_idx]
            sorted_symbols = np.array(self.annotations.symbol)[sort_idx]
            try:
                os.chdir(out_dir)
                wfdb.wrann(sanitized_base, ext, sorted_samples, sorted_symbols, fs=self.record.fs)
                QMessageBox.information(self, "Sukces", "Plik ATR zapisany.")
            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))
            finally:
                os.chdir(current_dir)


    def populate_leads(self) -> None:
        self.combo_leads.clear()
        if self.record is not None:
            if hasattr(self.record, 'sig_name') and self.record.sig_name:
                for name in self.record.sig_name:
                    self.combo_leads.addItem(name)
            else:
                for i in range(self.record.n_sig):
                    self.combo_leads.addItem(f"Lead {i+1}")

    def setup_scroll(self) -> None:
        if self.record is None:
            return
        total = self.record.p_signal.shape[0]
        max_val = max(0, total - int(self.window_size_s * self.record.fs))
        self.scroll_bar.setRange(0, max_val)

    @pyqtSlot()
    def scroll_changed(self) -> None:
        self.current_start = self.scroll_bar.value()
        self.update_plot()

    @pyqtSlot()
    def update_window_size(self) -> None:
        self.window_size_s = self.slider_time_window.value()
        self.setup_scroll()
        self.update_plot()

    @pyqtSlot()
    def update_plot(self) -> None:
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
                global_idx = np.where(self.annotations.sample == ann_samples[i])[0][0]
                self.annot_artists.append((art, global_idx))
        self.ax2.set_xlim(self.ax1.get_xlim())
        self.ax2.set_ylim(-1, 1)
        self.ax2.set_xlabel("Czas (s)")
        self.ax2.get_yaxis().set_visible(False)
        self.canvas.draw()



    @pyqtSlot(object)
    def on_press(self, event: MouseEvent) -> None:
        if not self.record or not self.annotations:
            QMessageBox.warning(self, "Błąd", "Najpierw wczytaj plik .dat i .atr!")
            return

        # 🔹 Lewy przycisk myszy - przesuwanie adnotacji na dolnym wykresie
        if event.inaxes == self.ax2 and event.button == 1:
            for artist, idx in self.annot_artists:
                contains, _ = artist.contains(event)
                if contains:
                    print(f"[DEBUG] Przesuwanie adnotacji: idx={idx}, symbol={self.annotations.symbol[idx]}")
                    self.drag_annotation = artist
                    self.drag_index = idx
                    self.drag_offset = event.xdata - artist.get_position()[0]
                    return

        # 🔹 Prawy przycisk myszy - USUWANIE adnotacji na dolnym wykresie
        if event.inaxes == self.ax2 and event.button == 3:
            for artist, idx in self.annot_artists:
                contains, _ = artist.contains(event)
                if contains:
                    confirm = QMessageBox.question(
                        self, "Usuń adnotację",
                        f"Czy na pewno chcesz usunąć adnotację '{self.annotations.symbol[idx]}'?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                    )

                    if confirm == QMessageBox.StandardButton.Yes:
                        print(f"[DEBUG] Usuwanie adnotacji: idx={idx}, symbol={self.annotations.symbol[idx]}")
                        self.annotations.sample = np.delete(self.annotations.sample, idx)
                        del self.annotations.symbol[idx]

                        if hasattr(self.annotations, 'aux') and self.annotations.aux is not None:
                            self.annotations.aux = np.delete(self.annotations.aux, idx)

                        self.update_plot()
                        self.auto_save_atr()
                    return

        # 🔹 Jeśli kliknięto PPM na głównym wykresie, dodajemy adnotację
        if event.inaxes == self.ax1 and event.button == 3:
            fs = self.record.fs
            sample_idx = int(round(event.xdata * fs))  # Przeliczenie współrzędnych na próbki

            sym, ok = QInputDialog.getText(self, "Dodaj adnotację", "Symbol adnotacji:", text="A")
            if ok:
                sym = sym.strip()

                # 🔹 WALIDACJA: Dopuszczone znaki (litery, cyfry, matematyczne, znaki specjalne)
                allowed_pattern = re.compile(r"^[a-zA-Z0-9()\[\]{}+\-*/=!@%^&|~]$")

                if not allowed_pattern.match(sym):
                    QMessageBox.warning(self, "Błąd", "Niepoprawny symbol! Dopuszczalne są tylko litery, cyfry, znaki matematyczne i specjalne.")
                    return

                print(f"[DEBUG] Dodawanie adnotacji: sample={sample_idx}, symbol={sym}")

                if self.annotations is None:
                    self.annotations = wfdb.Annotation(
                        record_name=self.dat_file,
                        extension='atr',
                        sample=np.array([sample_idx]),
                        symbol=[sym],
                        aux_note=np.array([sym]),
                        fs=fs
                    )
                else:
                    self.annotations.sample = np.append(self.annotations.sample, sample_idx)
                    self.annotations.symbol = list(self.annotations.symbol) + [sym]

                    if hasattr(self.annotations, 'aux') and self.annotations.aux is not None:
                        self.annotations.aux = np.append(self.annotations.aux, sym)
                    else:
                        self.annotations.aux = np.array([sym] * len(self.annotations.sample))

                self.update_plot()
                self.auto_save_atr()  # Zapisanie zmiany od razu



    @pyqtSlot(object)
    def on_motion(self, event: MouseEvent) -> None:
        if self.drag_annotation is not None and event.inaxes == self.ax2:
            new_x = event.xdata - self.drag_offset
            pos = self.drag_annotation.get_position()
            self.drag_annotation.set_position((new_x, pos[1]))
            self.canvas.draw_idle()

    @pyqtSlot(object)
    def on_release(self, event: MouseEvent) -> None:
        if self.drag_annotation is not None and event.inaxes == self.ax2:
            fs = self.record.fs
            new_time = self.drag_annotation.get_position()[0]
            new_sample = int(round(new_time * fs))
            if self.annotations is not None and self.drag_index is not None:
                self.annotations.sample[self.drag_index] = new_sample
            self.drag_annotation = None
            self.drag_index = None
            self.update_plot()
            self.auto_save_atr()  # Aktualizuj stan pliku ATR na dysku po zmianie



    @pyqtSlot(int)
    def edit_annotation(self, global_idx: int) -> None:
        if self.annotations is None:
            return
        symbol = self.annotations.symbol[global_idx]
        sample_val = self.annotations.sample[global_idx]
        dlg = AnnotationDialog(sample_val, self.record.fs, symbol, global_idx, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
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
            self.auto_save_atr()  # Zapisz zmiany

if __name__ == '__main__':

    import PyQt6.QtCore
    print(PyQt6.QtCore.PYQT_VERSION_STR)


    app = QtWidgets.QApplication(sys.argv)
    editor = ECGEditor()
    editor.show()
    sys.exit(app.exec())
