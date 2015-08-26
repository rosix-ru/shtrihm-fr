# -*- coding: utf-8 -*-
#
#  Copyright 2013 Grigoriy Kramarenko <root@rosix.ru>
#  
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 3 of the License, or
#  (at your option) any later version.
#  
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#  
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#  
#  

# Пароль админа по умолчанию = 30
DEFAULT_ADMIN_PASSWORD = (0x1e, 0x0, 0x0, 0x0)
# Пароль кассира по умолчанию = 1
DEFAULT_PASSWORD       = (0x1, 0x0, 0x0, 0x0)

# Порт в GNU/Linux по-умолчанию (COM1)
DEFAULT_PORT = '/dev/ttyUSB0'
DEFAULT_BOD  = 4800

# Кодировка текста для устройств
CODE_PAGE = 'cp1251'

# Кол-во попыток и таймаут
MAX_ATTEMPT = 12
MIN_TIMEOUT = 0.05

