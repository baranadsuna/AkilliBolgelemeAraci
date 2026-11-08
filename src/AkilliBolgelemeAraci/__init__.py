# -*- coding: utf-8 -*-
def classFactory(iface):
    from .bolgeleme_plugin import AkilliBolgelemePlugin
    return AkilliBolgelemePlugin(iface)
