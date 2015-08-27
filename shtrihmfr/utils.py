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

from __future__ import unicode_literals
import struct
import sys


__all__ = ('PY2', 'int2', 'int4', 'int5', 'int6', 'int7', 'int8',
    'money2integer', 'integer2money', 'count2integer',
    'get_control_summ','string2bits', 'bits2string',
    'digits2string', 'password_prapare')


PY2 = sys.version_info[0] == 2


class Struct(struct.Struct):
    """ Преобразователь """
    def __init__(self, *args, **kwargs):
        self.length = kwargs.pop('length', None)
        super(Struct, self).__init__(*args, **kwargs)

    def unpack(self, value):
        value = self.pre_value(value)
        return super(Struct, self).unpack(value)[0]

    def pack(self, value):
        value = super(Struct, self).pack(value)
        return self.post_value(value)

    def pre_value(self, value):
        """ Обрезает или добавляет нулевые байты """
        if self.size:
            if self.format in (b'h',b'i',b'I',b'l',b'L',b'q',b'Q'):
                _len = len(value)
                if _len < self.size:
                    value = value.ljust(self.size, chr(0x0))
                elif _len > self.size:
                    value = value[:self.size]
        return value

    def post_value(self, value):
        """ Обрезает или добавляет нулевые байты """
        if self.length:
            if self.format in (b'h',b'i',b'I',b'l',b'L',b'q',b'Q'):
                _len = len(value)
                if _len < self.length:
                    value = value.ljust(self.length, chr(0x0))
                elif _len > self.length:
                    value = value[:self.length]
        return value

# Объекты класса Struct
# Формат short по длинне 2 байта
int2 = Struct(b'h', length=2)
# Формат int по длинне 3 байта
int3 = Struct(b'i', length=3)
# Формат int == long по длинне 4 байта
int4 = Struct(b'i', length=4)
# Формат "long long" для 5-ти байтовых чисел
int5 = Struct(b'q', length=5)
# Формат "long long" для 6-ти байтовых чисел
int6 = Struct(b'q', length=6)
# Формат "long long" для 7-ти байтовых чисел
int7 = Struct(b'q', length=7)
# Формат "long long" для 8-ти байтовых чисел
int8 = Struct(b'q', length=8)


def string2bits(string):
    """ Convert string to bit array """
    result = []
    for char in string:
        bits = bin(ord(char))[2:]
        bits = '00000000'[len(bits):] + bits
        result.extend([int(b) for b in bits])
    return result


def bits2string(bits):
    """ Convert bit array to string """
    chars = []
    for b in range(len(bits) / 8):
        byte = bits[b*8:(b+1)*8]
        chars.append(chr(int(''.join([str(bit) for bit in byte]), 2)))
    return ''.join(chars).encode('utf-8')


def money2integer(money, digits=2):
    """
    Преобразует decimal или float значения в целое число, согласно
    установленной десятичной кратности.

    Например, money2integer(2.3456, digits=3) вернёт  2346
    """
    return int(round(round(float(money), digits) * 10**digits))


def integer2money(integer, digits=2):
    """
    Преобразует целое число в значение float, согласно
    установленной десятичной кратности.

    Например, integer2money(2346, digits=3) вернёт  2.346
    """
    return round(float(integer) / 10**digits, digits)


def count2integer(count, coefficient=1, digits=3):
    """
    Преобразует количество согласно заданного коэффициента
    """
    return money2integer(count, digits=digits) * coefficient


def get_control_summ(string):
    """
    Подсчет CRC
    """
    result = 0
    for s in string:
        result = result ^ ord(s)
    return chr(result)


def digits2string(digits):
    """
    Преобразует список из целых или шестнадцатеричных значений в строку
    """
    return ''.join([ chr(x) for x in digits ]).encode('utf-8')


def password_prapare(password):
    
    if isinstance(password, (list, tuple)):
        try:
            return digits2string(password[:4])
        except:
            msg = 'Тип пароля неидентифицирован'
            if PY2:
                msg = msg.encode('utf-8')
            raise TypeError(msg)

    password = int(password)

    if password > 9999:
        msg = 'Пароль должен быть от 0 до 9999'
        if PY2:
            msg = msg.encode('utf-8')
        raise ValueError(msg)

    return int4.pack(password)





