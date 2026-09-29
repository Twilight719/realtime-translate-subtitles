import sys
from PyQt5.QtCore import QLibraryInfo, QCoreApplication

app = QCoreApplication(sys.argv)
print(QLibraryInfo.location(QLibraryInfo.PluginsPath))
