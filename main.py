"""DocuWise — entry point."""
import sys
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow

app = QApplication(sys.argv)
app.setApplicationName("DocuWise")
window = MainWindow()
window.show()
sys.exit(app.exec())