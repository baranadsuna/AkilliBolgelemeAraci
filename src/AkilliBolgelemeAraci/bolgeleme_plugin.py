# -*- coding: utf-8 -*-
import os
import stat
import shutil
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon
from .bolgeleme_dialog import BolgelemeDialog


def _clear_readonly_and_subdirs(plugin_dir):
    """Windows / OneDrive kaynaklı Salt-Okunur (Read-Only) dizin bayraklarını ve alt önbellek klasörlerini temizler."""
    if not plugin_dir or not os.path.exists(plugin_dir):
        return
    for root, dirs, files in os.walk(plugin_dir, topdown=False):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                os.chmod(fpath, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
        for dname in dirs:
            dpath = os.path.join(root, dname)
            try:
                os.chmod(dpath, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
            if dname in ("__pycache__", "katex", "tests"):
                shutil.rmtree(dpath, ignore_errors=True)
    try:
        os.chmod(plugin_dir, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


class AkilliBolgelemePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None
        _clear_readonly_and_subdirs(self.plugin_dir)

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, 'icon.svg')
        self.action = QAction(
            QIcon(icon_path),
            "Urban Zoning and Vulnerability Analysis Tool",
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToVectorMenu("&Urban Zoning and Vulnerability Analysis", self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginVectorMenu("&Urban Zoning and Vulnerability Analysis", self.action)
            self.iface.removeToolBarIcon(self.action)
        if self.dialog:
            self.dialog.close()
            self.dialog = None
        _clear_readonly_and_subdirs(self.plugin_dir)

    def run(self):
        if self.dialog is None:
            self.dialog = BolgelemeDialog(self.iface, self.iface.mainWindow())
        self.dialog.auto_populate_all_layers()
        self.dialog.fit_to_screen()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
