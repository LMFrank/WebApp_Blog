#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Override configurations.
自定义的配置文件,用以覆盖一些默认配置,从而避免了对默认配置文件的直接修改,即：
把config_default.py作为开发环境的标准配置，把config_override.py作为生产环境的标准配置，
我们就可以既方便地在本地开发，又可以随时把应用部署到服务器上
"""


configs = {
    'db': {
        'host': '127.0.0.1'  # 本机的ip
    }
}