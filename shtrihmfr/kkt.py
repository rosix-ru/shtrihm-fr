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

import serial
import time
import datetime

from .conf import *  # NOQA
from .protocol import *  # NOQA
from .utils import *  # NOQA

# ASCII

ENQ = chr(0x05)  # Enquire. Прошу подтверждения.
STX = chr(0x02)  # Start of Text, начало текста.
ACK = chr(0x06)  # Acknowledgement. Подтверждаю.
NAK = chr(0x15)  # Negative Acknowledgment, не подтверждаю.


class KktError(Exception):

    def __init__(self, value):
        if isinstance(value, int):
            self.value = value
            self.source, self.message = BUGS[value]
            msg = '%s: %s' % (self.source, self.message)
        else:
            msg = value
        if PY2:
            try:
                msg = msg.encode('utf-8')
            except UnicodeError:
                pass
        super(KktError, self).__init__(msg)


class ConnectionError(KktError):
    pass


class BaseKKT(object):
    """
    Базовый класс включает методы непосредственного общения с
    устройством.

    Общие положения.

    В информационном обмене «Хост – ККТ» хост является главным
    устройством, а ККТ – подчиненным. Поэтому направление
    передачи данных определяется хостом. Физический интерфейс
    «Хост – ККТ» – последовательный интерфейс RS-232С, без линий
    аппаратного квитирования.
    Скорость обмена по интерфейсу RS-232С – 2400, 4800, 9600, 19200,
                                            38400, 57600, 115200.
    При обмене хост и ККТ оперируют сообщениями. Сообщение может
    содержать команду (от хоста) или ответ на команду (от ККТ).
    Формат сообщения:
        Байт 0: признак начала сообщения STX;
        Байт 1: длина сообщения (N) – ДВОИЧНОЕ число.
        В длину сообщения не включаются байты 0, LRC и этот байт;
        Байт 2: код команды или ответа – ДВОИЧНОЕ число;
        Байты 3 – (N + 1): параметры, зависящие от команды
        (могут отсутствовать);
        Байт N + 2 – контрольная сумма сообщения – байт LRC
        – вычисляется поразрядным сложением (XOR) всех байтов
        сообщения (кроме байта 0).

    Сообщение считается принятым, если приняты байт STX
    и байт длины. Сообщение считается принятым корректно, если
    приняты байты сообщения, определенные его байтом длины, и
    байт LRC.
    Каждое принятое сообщение подтверждается передачей
    одного байта (ACK – положительное подтверждение, NAK –
    отрицательное подтверждение).
    Ответ NAK свидетельствует об ошибке интерфейса (данные приняты
    с ошибкой или не распознан STX), но не о неверной команде.
    Отсутствие подтверждения в течение тайм-аута означает, что
    сообщение не принято.
    Если в ответ на сообщение ККТ получен NAK, сообщение не
    повторяется, ККТ ждет уведомления ENQ для повторения ответа.
    После включения питания ККТ ожидает байт запроса – ENQ.
    Ответ от ККТ в виде байта NAK означает, что ККТ находится в
    состоянии ожидания очередной команды;
    ответ ACK означает, что ККТ подготавливает ответное
    сообщение, отсутствии ответа означает отсутствие связи между
    хостом и ККТ.

    По умолчанию устанавливаются следующие параметры порта: 8 бит
    данных, 1 стоп- бит, отсутствует проверка на четность,
    скорость обмена 4800 бод и тайм-аут ожидания каждого байта,
    равный 50 мс. Две последние характеристики обмена могут быть
    изменены командой от хоста. Минимальное время между приемом
    последнего байта сообщения и передачей подтверждения, и между
    приемом ENQ и реакцией на него равно тайм-ауту приема байта.
    Количество повторов при неудачных сеансах связи (нет
    подтверждения после передачи команды, отрицательное
    подтверждение после передачи команды, данные ответа приняты с
    ошибкой или не распознан STX ответа) настраивается при
    реализации программного обеспечения хоста. Коды знаков STX,
    ENQ, ACK и NAK – коды WIN1251.

    """
    error = ''
    port = DEFAULT_PORT
    password = password_prapare(DEFAULT_PASSWORD)
    admin_password = password_prapare(DEFAULT_ADMIN_PASSWORD)
    bod = DEFAULT_BOD
    parity = serial.PARITY_NONE
    stopbits = serial.STOPBITS_ONE
    timeout = 0.7
    writeTimeout = 0.7

    def __init__(self, **kwargs):
        """ Пароли можно передавать в виде набора шестнадцатеричных
            значений, либо в виде обычной ASCII строки. Длина пароля 4
            ASCII символа.
        """
        if 'password' in kwargs:
            self.password = password_prapare(kwargs.pop('password'))
        if 'admin_password' in kwargs:
            self.admin_password = password_prapare(
                kwargs.pop('admin_password')
            )
        for k, v in kwargs.items():
            setattr(self, k, v)

    @property
    def is_connected(self):
        """ Возвращает состояние соединение """
        return bool(self._conn)

    @property
    def conn(self):
        """ Возвращает соединение """
        if hasattr(self, '_conn') and self._conn is not None:
            return self._conn
        self.connect()
        return self._conn

    def connect(self):
        """ Устанавливает соединение """
        try:
            self._conn = serial.Serial(
                self.port, self.bod,
                parity=self.parity,
                stopbits=self.stopbits,
                timeout=self.timeout,
                writeTimeout=self.writeTimeout
            )
        except serial.SerialException:
            raise ConnectionError(
                'Невозможно соединиться с ККМ (порт=%s)' % self.port)
        return self.check_port()

    def disconnect(self):
        """ Закрывает соединение """
        if self.conn:
            self._conn.close()
            self._conn = None
        return True

    def check_port(self):
        """ Проверка на готовность порта """
        if not self.conn.isOpen():
            raise ConnectionError('Последовательный порт закрыт')
        return True

    def check_state(self):
        """ Проверка на ожидание команды """
        self.check_port()
        self._write(ENQ)
        answer = self._read(1)
        if not answer:
            time.sleep(MIN_TIMEOUT)
            answer = self._read(1)
        if answer in (NAK, ACK):
            return answer
        elif not answer:
            raise ConnectionError('Нет связи с устройством')

    def check_STX(self):
        """ Проверка на данные """
        answer = self._read(1)
        # Для гарантированного получения ответа стоит обождать
        # некоторое время, от минимального (0.05 секунд)
        # до 12.8746337890625 секунд по умолчанию для 12 попыток
        n = 0
        timeout = MIN_TIMEOUT
        while not answer and n < MAX_ATTEMPT:
            time.sleep(timeout)
            answer = self._read(1)
            n += 1
            timeout *= 1.5z
        if answer == STX:
            return True
        else:
            raise ConnectionError('Нет связи с устройством')

    def check_NAK(self):
        """ Проверка на ожидание команды """
        answer = self.check_state()
        if answer == NAK:
            return True
        return False

    def check_ACK(self):
        """ Проверка на подготовку ответа """
        answer = self.check_state()
        if answer == ACK:
            return True
        return False

    def _read(self, read=None):
        """ Высокоуровневый метод считывания соединения """
        return self.conn.read(read)

    def _write(self, write):
        """ Высокоуровневый метод записи в соединение """
        return self.conn.write(write)

    def _flush(self):
        """ Высокоуровневый метод слива в ККТ """
        return self.conn.flush()

    def clear(self):
        """ Сбрасывает ответ, если он болтается в ККМ """
        def one_round():
            self._write(ENQ)
            answer = self._read(1)
            if answer == NAK or not answer:
                return True
            time.sleep(MIN_TIMEOUT*10)
            return False

        n = 0
        while n < MAX_ATTEMPT and not one_round():
            n += 1
        if n >= MAX_ATTEMPT:
            return False
        return True

    def read(self, command):
        """ Считывает весь ответ ККМ """
        answer = self.check_state()
        if answer == NAK:
            i = 0
            while i < MAX_ATTEMPT and not self.check_ACK():
                i += 1
            if i >= MAX_ATTEMPT:
                self.disconnect()
                raise ConnectionError('Нет связи с устройством')
        elif not answer:
            self.disconnect()
            raise ConnectionError('Нет связи с устройством')
        j = 0
        while j < MAX_ATTEMPT and not self.check_STX():
            j += 1
        if j >= MAX_ATTEMPT:
            self.disconnect()
            raise ConnectionError('Нет связи с устройством')

        response_length = ord(self._read(1))
        command_length = len(command)
        data_length = response_length - command_length - 1

        command = self._read(command_length)
        error = self._read(1)
        data = self._read(data_length)
        if data_length != len(data):
            self._write(NAK)
            self.disconnect()
            msg = ('Длина ответа (%i) не равна длине полученных данных (%i)' %
                   (data_length, len(data)))
            raise KktError(msg)

        control_read = self._read(1)
        control_summ = get_control_summ(
            chr(response_length) + command + error + data
        )
        if control_read != control_summ:
            self._write(NAK)
            self.disconnect()
            msg = ("Контрольная сумма %i должна быть равна %i " %
                   (ord(control_summ), ord(control_read)))
            raise KktError(msg)
        self._write(ACK)
        self._flush()
        # time.sleep(MIN_TIMEOUT*2)
        return {
            'command': command,
            'error': ord(error),
            'data': data
        }

    def send(self, command, params, quick=False):
        """ Стандартная обработка команды """
        # self.clear()
        if not quick:
            self._flush()
        data = command
        if params is not None:
            data += force_bytes(params)
        # print('kkt.send: %s' % repr(data))
        length = len(data)
        content = chr(length) + data
        control_summ = get_control_summ(content)
        self._write(STX + content + control_summ)
        self._flush()
        return True

    def ask(self, command, params=None, sleep=0, pre_clear=True,
            without_password=False, disconnect=True, quick=False):
        """ Высокоуровневый метод получения ответа. Состоит из
            последовательной цепочки действий.

            Возвращает позиционные параметры: (data, error, command)
        """
        if quick:
            # pre_clear = False
            disconnect = False
            sleep = 0
        if params is None and not without_password:
            params = self.password
        # if pre_clear:
            # self.clear()
        if isinstance(command, int):
            command = chr(command)
        self.send(command, params, quick=quick)
        if sleep:
            time.sleep(sleep)
        a = self.read(command)
        answer, error, command = (a['data'], a['error'], a['command'])
        if disconnect:
            self.disconnect()
        if error:
            raise KktError(error)
        return answer, error, command


class KKT(BaseKKT):
    """ Класс с командами, исполняемыми согласно протокола """

    def x01(self, code):
        """ Запрос дампа
            Команда: 01H. Длина сообщения: 6 байт.
                Пароль ЦТО или пароль системного администратора, если
                    пароль ЦТО не был установлен (4 байта)
                Код устройства (1 байт)
                    00h – стационарная проверка ФП
                    01h – накопитель ФП 1 / оперативная память ФП
                    02h – накопитель ФП 2
                    03h – часы
                    04h – энергонезависимая память
                    05h – процессор / память программ ФП
                    06h – память программ ККТ
                    07h – оперативная память ККТ
                    08h – образ файловой системы
                    09h – образ uLinux
                    0Ah – исполняемый файл ПО
                    86h – память программ ККТ
            Ответ: 01H. Длина сообщения: 4 байта.
                Код ошибки (1 байт)
                Количество блоков данных (2 байта)
        """
        command = 0x01
        params = self.admin_password + chr(code)
        data, error, command = self.ask(command, params)
        return data

    def x02(self, code):
        """ Запрос данных
            Команда: 02H. Длина сообщения: 5 байт.
                Пароль ЦТО или пароль системного администратора, если
                    пароль ЦТО не был установлен (4 байта)
            Ответ: 02H. Длина сообщения: 37 байт.
                Код ошибки (1 байт)
                Код устройства в команде запроса дампа (1 байт):
                    01 – накопитель ФП1
                    02 – накопитель ФП2
                    03 – часы
                    04 – энергонезависимая память
                    05 – процессор ФП
                    06 – память программ ККТ
                    07 – оперативная память ККТ
                Номер блока данных (2 байта)
                Блок данных (32 байта)
        """
        command = 0x02
        params = self.admin_password + chr(code)
        data, error, command = self.ask(command, params)
        return data

    def x03(self):
        """ Прерывание выдачи данных
            Команда: 03H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: 03H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0x03
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    # Not implemented
    def x0D(self, old_password, new_password, rnm, inn):
        """ Фискализация (перерегистрация) с длинным РНМ
            Команда: 0DH. Длина сообщения: 22 байта.
                Пароль старый (4 байта)
                Пароль новый (4 байта)
                РНМ (7 байт) 00000000000000...99999999999999
                ИНН (6 байт) 000000000000...999999999999
            Ответ: 0DH. Длина сообщения: 9 байт.
                Код ошибки (1 байт)
                Номер фискализации (перерегистрации) (1 байт) 1...16
                Количество оставшихся перерегистраций (1 байт) 0...15
                Номер последней закрытой смены (2 байта) 0000...2100
                Дата фискализации (перерегистрации) (3 байта) ДД-ММ-ГГ
        """
        raise NotImplementedError()

    # Not implemented
    def x0E(self):
        """ Ввод длинного заводского номера
            Команда: 0EH. Длина сообщения: 12 байт.
                Пароль (4 байта) (пароль «0»)
                Заводской номер (7 байт) 00000000000000...99999999999999
            Ответ: 0EH. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def x0F(self):
        """ Запрос длинного заводского номера и длинного РНМ
            Команда: 0FH. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 0FH. Длина сообщения: 16 байт.
                Код ошибки (1 байт)
                Заводской номер (7 байт) 00000000000000...99999999999999
                РНМ (7 байт) 00000000000000...99999999999999
        """
        raise NotImplementedError()

    def x10(self):
        """ Короткий запрос состояния ФР
            Команда: 10H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 10H. Длина сообщения: 16 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Флаги ККТ (2 байта)
                Режим ККТ (1 байт)
                Подрежим ККТ (1 байт)
                Количество операций в чеке (1 байт) младший байт
                    двухбайтного числа (см. документацию)
                Напряжение резервной батареи (1 байт)
                Напряжение источника питания (1 байт)
                Код ошибки ФП (1 байт)
                Код ошибки ЭКЛЗ (1 байт)
                Количество операций в чеке (1 байт) старший байт
                    двухбайтного числа (см. документацию)
                Зарезервировано (3 байта)
        """
        command = 0x10
        data, error, command = self.ask(command)

        # Флаги ККТ
        # старший байт и младший байт
        kkt_flags = string2bits(data[2] + data[1])
        kkt_flags = [KKT_FLAGS[i] for i, x in enumerate(kkt_flags) if x]
        # Количество операций
        # старший байт и младший байт
        operations = int2.unpack(data[10]+data[5])

        result = {
            'error': error,
            'operator': ord(data[0]),
            'kkt_flags': kkt_flags,
            'kkt_mode': ord(data[3]),
            'kkt_submode': ord(data[4]),
            'voltage_battery': ord(data[6]),
            'voltage_power': ord(data[7]),
            'fp_error': ord(data[8]),
            'eklz_error': ord(data[9]),
            'operations': operations,
            'reserve': data[11:],
        }
        return result

    def x11(self):
        """ Запрос состояния ФР
            Команда: 11H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 11H. Длина сообщения: 48 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Версия ПО ККТ (2 байта)
                Сборка ПО ККТ (2 байта)
                Дата ПО ККТ (3 байта) ДД-ММ-ГГ
                Номер в зале (1 байт)
                Сквозной номер текущего документа (2 байта)
                Флаги ККТ (2 байта)
                Режим ККТ (1 байт)
                Подрежим ККТ (1 байт)
                Порт ККТ (1 байт)
                Версия ПО ФП (2 байта)
                Сборка ПО ФП (2 байта)
                Дата ПО ФП (3 байта) ДД-ММ-ГГ
                Дата (3 байта) ДД-ММ-ГГ
                Время (3 байта) ЧЧ-ММ-СС
                Флаги ФП (1 байт)
                Заводской номер (4 байта)
                Номер последней закрытой смены (2 байта)
                Количество свободных записей в ФП (2 байта)
                Количество перерегистраций (фискализаций) (1 байт)
                Количество оставшихся перерегистраций (фискализаций)
                    (1 байт)
                ИНН (6 байт)
        """

        command = 0x11
        data, error, command = self.ask(command)

        # Дата ПО ККТ
        day = ord(data[5])
        month = ord(data[6])
        year = ord(data[7])
        if year > 90:
            kkt_date = datetime.date(1900+year, month, day)
        else:
            kkt_date = datetime.date(2000+year, month, day)

        # Флаги ККТ
        # старший байт и младший байт
        kkt_flags = string2bits(data[12] + data[11])
        kkt_flags = [KKT_FLAGS[i] for i, x in enumerate(kkt_flags) if x]

        # Дата ПО ФП
        day = ord(data[20])
        month = ord(data[21])
        year = ord(data[22])
        if year > 90:
            fp_date = datetime.date(1900+year, month, day)
        else:
            fp_date = datetime.date(2000+year, month, day)

        # Дата и время текущие
        date = datetime.date(2000+ord(data[25]), ord(data[24]), ord(data[23]))
        time = datetime.time(ord(data[26]), ord(data[27]), ord(data[28]))

        # Флаги ФП
        fp_flags = string2bits(data[29])
        fp_flags = [FP_FLAGS[i][x] for i, x in enumerate(fp_flags)]

        result = {
            'error': error,
            'operator': ord(data[0]),
            'kkt_version': '%s.%s' % (data[1], data[2]),
            'kkt_build': int2.unpack(data[3] + data[4]),
            'kkt_date': kkt_date,
            'hall': ord(data[8]),
            'document': int2.unpack(data[9] + data[10]),
            'kkt_flags': kkt_flags,
            'kkt_mode': ord(data[13]),
            'kkt_submode': ord(data[14]),
            'kkt_port': ord(data[15]),
            'fp_version': '%s.%s' % (data[16], data[17]),
            'fp_build': int2.unpack(data[18] + data[19]),
            'fp_date': fp_date,
            'date': date,
            'time': time,
            'fp_flags': fp_flags,
            'serial_number': int4.unpack(data[30] + data[31] +
                                         data[32] + data[33]),
            'last_closed_session': int2.unpack(data[34] + data[35]),
            'fp_free_records': int2.unpack(data[36] + data[37]),
            'registration_count': ord(data[38]),
            'registration_left': ord(data[39]),
            'inn': int6.unpack(
                data[40] + data[41] + data[42] +
                data[43] + data[44] + data[45])
        }
        return result

    def x12_loop(self, text='', control_tape=False):
        """ Печать жирной строки без ограничения на 20 символов """
        last_result = None
        while len(text) > 0:
            last_result = self.x12(text=text[:20], control_tape=control_tape)
            text = text[20:]
        return last_result

    def x12(self, text='', control_tape=False):
        """ Печать жирной строки
            Команда: 12H. Длина сообщения: 26 байт.
                Пароль оператора (4 байта)
                Флаги (1 байт)
                    Бит 0 – контрольная лента,
                    Бит 1 – чековая лента.
                Печатаемые символы (20 байт)
            Ответ: 12H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x12

        flags = 2  # по умолчанию bin(2) == '0b00000010'
        if control_tape:
            flags = 1  # bin(1) == '0b00000001'

        if len(text) > 20:
            raise KktError(
                'Длина строки должна быть меньше или равна 20 символов')
        text = text.encode(CODE_PAGE).ljust(20, chr(0x0))

        params = self.password + chr(flags) + text

        data, error, command = self.ask(command, params, quick=True)
        operator = ord(data[0])
        return operator

    def x13(self):
        """ Гудок
            Команда: 13H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 13H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        params = self.password
        data, error, command = self.ask(0x13, params)
        return error

    def x14(self, port=0, speed=1, timeout=100):
        """ Установка параметров обмена
            Команда: 14H. Длина сообщения: 8 байт.
                Пароль системного администратора (4 байта)
                Номер порта (1 байт) 0...255
                Код скорости обмена (1 байт) 0...6
                Тайм аут приема байта (1 байт) 0...255
            Ответ: 14H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание:
                ККТ поддерживает обмен со скоростями 2400, 4800, 9600,
                19200, 38400, 57600, 115200 для порта 0, чему
                соответствуют коды от 0 до 6. Для остальных портов
                диапазон скоростей может быть сужен, и в этом случае,
                если порт не поддерживает выбранную скорость, будет
                выдано сообщение об ошибке. Тайм-аут приема байта
                нелинейный. Диапазон допустимых значений [0...255]
                распадается на три диапазона:
                    1. В диапазоне [0...150] каждая единица
                    соответствует 1 мс, т.е. данным диапазоном
                    задаются значения тайм-аута от 0 до 150 мс;
                    2. В диапазоне [151...249] каждая единица
                    соответствует 150 мс, т.е. данным диапазоном
                    задаются значения тайм-аута от 300 мс до 15 сек;
                    3. В диапазоне [250...255] каждая единица
                    соответствует 15 сек, т.е. данным диапазоном
                    задаются значения тайм-аута от 30 сек до 105 сек.

                По умолчанию все порты настроены на параметры:
                скорость 4800 бод с тайм-аутом 100 мс. Если
                устанавливается порт, по которому ведется обмен, то
                подтверждение на прием команды и ответное сообщение
                выдаются ККТ со старой скоростью обмена.
        """
        command = 0x14
        new_bod = [2400, 4800, 9600, 19200, 38400, 57600, 115200][speed]
        params = self.admin_password + chr(port) + chr(speed) + chr(timeout)
        data, error, command = self.ask(command, params)
        self.bod = new_bod
        return error

    def x15(self, port=0):
        """ Чтение параметров обмена
            Команда: 15H. Длина сообщения: 6 байт.
                Пароль системного администратора (4 байта)
                Номер порта (1 байт) 0...255
            Ответ: 15H. Длина сообщения: 4 байта.
                Код ошибки (1 байт)
                Код скорости обмена (1 байт) 0...6
                Тайм аут приема байта (1 байт) 0...255
        """
        command = 0x15
        params = self.admin_password + chr(port)
        data, error, command = self.ask(command, params)
        speed = ord(data[0])
        timeout = ord(data[1])
        return port, speed, timeout

    def x16(self):
        """ Технологическое обнуление
            Команда: 16H. Длина сообщения: 1 байт.
            Ответ: 16H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание:
                Технологическое обнуление доступно только после
                вскрытия пломбы на кожухе ККТ и выполнения
                последовательности действий, описанных в ремонтной
                документации на ККТ.
        """
        command = 0x16
        data, error, command = self.ask(command)
        return error

    def x17_loop(self, text='', control_tape=False):
        """ Печать строки без ограничения на 36 символов
            В документации указано 40, но 4 символа выходят за область
            печати на ФРК.
        """
        last_result = None
        while len(text) > 0:
            last_result = self.x17(text=text[:36], control_tape=control_tape)
            text = text[36:]
        return last_result

    def x17(self, text='', control_tape=False):
        """ Печать строки
            Команда: 17H. Длина сообщения: 46 байт.
                Пароль оператора (4 байта)
                Флаги (1 байт)
                    Бит 0 – контрольная лента,
                    Бит 1 – чековая лента.
                Печатаемые символы (40 байт)
            Ответ: 17H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30

            Примечание:
                Печатаемые символы – символы в кодовой странице
                WIN1251. Символы с кодами 0..31 не отображаются.
        """
        command = 0x17

        flags = 2  # по умолчанию bin(2) == '0b00000010'
        if control_tape:
            flags = 1  # bin(1) == '0b00000001'

        if len(text) > 40:
            raise KktError(
                'Длина строки должна быть меньше или равна 40 символов')
        text = text.encode(CODE_PAGE).ljust(40, chr(0x0))

        params = self.password + chr(flags) + text

        data, error, command = self.ask(command, params, quick=True)
        operator = ord(data[0])
        return operator

    def x18(self, text, number=1):
        """ Печать заголовка документа
            Команда: 18H. Длина сообщения: 37 байт.
                Пароль оператора (4 байта)
                Наименование документа (30 байт)
                Номер документа (2 байта)
            Ответ: 18H. Длина сообщения: 5 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Сквозной номер документа (2 байта)

            Примечание:
                Печатаемые символы – символы в кодовой странице
                WIN1251. Символы с кодами 0..31 не отображаются.
        """
        command = 0x18

        if len(text) > 30:
            raise KktError(
                'Длина строки должна быть меньше или равна 30 символов')
        text = text.encode(CODE_PAGE).ljust(30, chr(0x0))

        params = self.password + text + chr(flags)

        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x19(self, period=1):
        """ Тестовый прогон
            Команда: 19H. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Период вывода в минутах (1 байт) 1...99
            Ответ: 19H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x19
        params = self.password + chr(period)
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x1A(self):
        """ Запрос денежного регистра
            Команда: 1AH. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Номер регистра (1 байт) 0... 255
            Ответ: 1AH. Длина сообщения: 9 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Содержимое регистра (6 байт)

        Пример запроса:
            integer2money(
                int6.unpack(
                    kkt.ask(0x1A, kkt.password + chr(121))[0][1:]
                )
            )
        """

        command = 0x1A

        params = self.password + chr(number)

        data, error, command = self.ask(command, params)

        return integer2money(int6.unpack(data[1:]))

    def x1B(self):
        """ Запрос операционного регистра
            Команда: 1BH. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Номер регистра (1 байт) 0... 255
            Ответ: 1BH. Длина сообщения: 5 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Содержимое регистра (2 байта)
        """
        command = 0x1B

        params = self.password + chr(number)

        data, error, command = self.ask(command, params)

        return int2.unpack(data[1:])

    # Not implemented
    def x1C(self):
        """ Запись лицензии
            Команда: 1CH. Длина сообщения: 10 байт.
                Пароль системного администратора (4 байта)
                Лицензия (5 байт) 0000000000...9999999999
            Ответ: 1CH. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        raise NotImplementedError()

    def x1D(self):
        """ Чтение лицензии
            Команда: 1DH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: 1DH. Длина сообщения: 7 байт.
                Код ошибки (1 байт)
                Лицензия (5 байт) 0000000000...9999999999
        """
        command = 0x1D
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return data

    def x1E(self, table, row, field, value):
        """ Запись таблицы
            Команда: 1EH. Длина сообщения: (9+X) байт.
                Пароль системного администратора (4 байта)
                Таблица (1 байт)
                Ряд (2 байта)
                Поле (1 байт)
                Значение (X байт) до 40 байт
            Ответ: 1EH. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание: поля бывают бинарные и строковые, поэтому value
            делаем в исходном виде.
        """
        command = 0x1E

        table = chr(table)
        row = int2.pack(row)
        field = chr(field)

        params = self.admin_password + table + row + field + value

        data, error, command = self.ask(command, params)
        return error

    def x1F(self, table=1, row=1, col=1):
        """ Чтение таблицы
            Команда: 1FH. Длина сообщения: 9 байт.
                Пароль системного администратора (4 байта)
                Таблица (1 байт)
                Ряд (2 байта)
                Поле (1 байт)
            Ответ: 1FH. Длина сообщения: (2+X) байт.
                Код ошибки (1 байт)
                Значение (X байт) до 40 байт
        """
        command = 0x1F
        params = self.admin_password + chr(table) + int2.pack(row) + chr(col)
        data, error, command = self.ask(command, params)
        return data

    def x20(self, pos=0):
        """ Запись положения десятичной точки
            Команда: 20H. Длина сообщения: 6 байт.
                Пароль системного администратора (4 байта)
                Положение десятичной точки (1 байт) «0» – 0 разряд,
                                                    «1» – 2 разряд
            Ответ: 20H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

        """
        command = 0x20
        params = self.admin_password + chr(pos)
        data, error, command = self.ask(command, params)
        return error

    def x21(self, hour, minute, second):
        """ Программирование времени
            Команда: 21H. Длина сообщения: 8 байт.
                Пароль системного администратора (4 байта)
                Время (3 байта) ЧЧ-ММ-СС
            Ответ: 21H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0x21
        hour = chr(hour)
        minute = chr(minute)
        second = chr(second)
        params = self.admin_password + hour + minute + second
        data, error, command = self.ask(command, params)
        return error

    def x22(self, year, month, day):
        """ Программирование даты
            Команда: 22H. Длина сообщения: 8 байт.
                Пароль системного администратора (4 байта)
                Дата (3 байта) ДД-ММ-ГГ
            Ответ: 22H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0x22

        if year >= 2000:
            year = year - 2000

        year = chr(year)
        month = chr(month)
        day = chr(day)
        params = self.admin_password + day + month + year
        data, error, command = self.ask(command, params)
        return error

    def x23(self, year, month, day):
        """ Подтверждение программирования даты
            Команда: 23H. Длина сообщения: 8 байт.
                Пароль системного администратора (4 байта)
                Дата (3 байта) ДД-ММ-ГГ
            Ответ: 23H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0x23
        if year >= 2000:
            year = year - 2000
        year = chr(year)
        month = chr(month)
        day = chr(day)
        params = self.admin_password + day + month + year
        data, error, command = self.ask(command, params)
        return error

    def x24(self):
        """ Инициализация таблиц начальными значениями
            Команда: 24H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: 24H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0x24
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def x25(self, fullcut=True):
        """ Отрезка чека
            Команда: 25H. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Тип отрезки (1 байт) «0» – полная, «1» – неполная
            Ответ: 25H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x25

        cut = int(not bool(fullcut))  # 0 по умолчанию

        params = self.password + chr(cut)
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x26(self, font_number=0):
        """ Прочитать параметры шрифта
            Команда: 26H. Длина сообщения: 6 байт.
                Пароль системного администратора (4 байта)
                Номер шрифта (1 байт)
            Ответ: 26H. Длина сообщения: 7 байт.
                Код ошибки (1 байт)
                Ширина области печати в точках (2 байта)
                Ширина символа с учетом межсимвольного интервала в точках
                    (1 байт)
                Высота символа с учетом межстрочного интервала в точках
                    (1 байт)
                Количество шрифтов в ККТ (1 байт)
        """
        command = 0x26
        params = self.admin_password + chr(font_number)
        data, error, command = self.ask(command, params)
        return {
            'width_area': int2.unpack(data[0:2]),
            'width_char': ord(data[2]),
            'height_char': ord(data[3]),
            'fonts': ord(data[4]),
        }

    def x27(self):
        """ Общее гашение
            Команда: 27H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: 27H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0x27
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def x28(self, box=0):
        """ Открыть денежный ящик
            Команда: 28H. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Номер денежного ящика (1 байт) 0, 1
            Ответ: 28H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x28
        params = self.admin_password + chr(box)
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x29(self, receipt_tape=False, control_tape=False, row_count=1):
        """ Протяжка
            Команда: 29H. Длина сообщения: 7 байт.
                Пароль оператора (4 байта)
                Флаги (1 байт)
                    Бит 0 – контрольная лента,
                    Бит 1 – чековая лента,
                    Бит 2 – подкладной документ.
                Количество строк (1 байт) 1...255 – максимальное
                    количество строк ограничивается размером буфера
                    печати, но не превышает 255
            Ответ: 29H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x29

        flags = 4  # по умолчанию подкладной документ bin(4) == '0b00000100'
        if receipt_tape:
            flags = 2  # bin(2) == '0b00000010'
        if control_tape:
            flags = 1  # bin(1) == '0b00000001'

        if row_count < 1 or row_count > 255:
            raise KktError(
                "Количество строк должно быть в диапазоне между 1 и 255")

        params = self.password + chr(flags) + chr(row_count)
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x2A(self, top=False):
        """ Выброс подкладного документа
            Команда: 2AH. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Направление выброса подкладного документа (1 байт) «0» – вниз,
                                                                   «1» – вверх
            Ответ: 2AH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x2A
        params = self.admin_password + chr(1 if top else 0)
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x2B(self):
        """ Прерывание тестового прогона
            Команда: 2BH. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 2BH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x2B
        params = self.password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x2C(self):
        """ Снятие показаний операционных регистров
            Команда: 2СH. Длина сообщения: 5 байт.
                Пароль администратора или системного администратора (4 байта)
            Ответ: 2СH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 29, 30
        """
        command = 0x2C
        params = self.admin_password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x2D(self, table=1):
        """ Запрос структуры таблицы
            Команда: 2DH. Длина сообщения: 6 байт.
                Пароль системного администратора (4 байта)
                Номер таблицы (1 байт)
            Ответ: 2DH. Длина сообщения: 45 байт.
                Код ошибки (1 байт)
                Название таблицы (40 байт)
                Количество рядов (2 байта)
                Количество полей (1 байт)
        """
        command = 0x2D
        params = self.admin_password + chr(table)
        data, error, command = self.ask(command, params)
        result = {
            'name': data[:40],
            'rows': int2.unpack(data[40:42]),
            'cols': ord(data[42]),
        }
        raise result

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def x2E(self):
        """ Запрос структуры поля
            Команда: 2EH. Длина сообщения: 7 байт.
                Пароль системного администратора (4 байта)
                Номер таблицы (1 байт)
                Номер поля (1 байт)
            Ответ: 2EH. Длина сообщения: (44+X+X) байт.
                Код ошибки (1 байт)
                Название поля (40 байт)
                Тип поля (1 байт) «0» – BIN, «1» – CHAR
                Количество байт – X (1 байт)
                Минимальное значение поля – для полей типа BIN (X байт)
                Максимальное значение поля – для полей типа BIN (X байт)
        """
        raise NotImplementedError()

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def x2F(self):
        """ Печать строки данным шрифтом
            Команда: 2FH. Длина сообщения: 47 байт.
                Пароль оператора (4 байта)
                Флаги (1 байт)
                    Бит 0 – контрольная лента,
                    Бит 1 – чековая лента.
                Номер шрифта (1 байт) 0...255
                Печатаемые символы (40 байт)
            Ответ: 2FH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30

            Примечание:
                Печатаемые символы – символы в кодовой странице
                WIN1251. Символы с кодами 0...31 не отображаются.
        """
        raise NotImplementedError()

    def x40(self):
        """ Суточный отчет без гашения
            Команда: 40H. Длина сообщения: 5 байт.
                Пароль администратора или системного администратора (4 байта)
            Ответ: 40H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 29, 30
        """
        command = 0x40

        params = self.admin_password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x41(self):
        """ Суточный отчет с гашением
            Команда: 41H. Длина сообщения: 5 байт.
                Пароль администратора или системного администратора (4 байта)
            Ответ: 41H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 29, 30
        """
        command = 0x41

        params = self.admin_password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x42(self):
        """ Отчѐт по секциям
            Команда: 42H. Длина сообщения: 5 байт.
                Пароль администратора или системного администратора (4 байта)
            Ответ: 42H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 29, 30
        """
        command = 0x42
        params = self.admin_password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x43(self):
        """ Отчѐт по налогам
            Команда: 43H. Длина сообщения: 5 байт.
                Пароль администратора или системного администратора (4 байта)
            Ответ: 43H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 29, 30
        """
        command = 0x43
        params = self.admin_password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x44(self):
        """ Отчёт по кассирам
            Команда: 44H. Длина сообщения: 5 байт.
                Пароль администратора или системного администратора
                или "СТАРШИЙ КАССИР" 1 (4 байта)
            Ответ: 44H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 28, 29, 30
        """
        command = 0x44
        params = self.admin_password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x45(self):
        """ Отчёт почасовой
            Команда: 45H. Длина сообщения: 5 байт.
                Пароль администратора или системного администратора
                или "СТАРШИЙ КАССИР" 1 (4 байта)
            Ответ: 45H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 28, 29, 30
        """
        command = 0x45
        params = self.admin_password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x46(self):
        """ Отчёт по товарам
            Команда: 46H. Длина сообщения: 5 байт.
                Пароль администратора или системного администратора
                или "СТАРШИЙ КАССИР" 1 (4 байта)
            Ответ: 46H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 28, 29, 30
        """
        command = 0x46
        params = self.admin_password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    # Not implemented
    def x4A(self):
        """ Добавить или обновить товар в базе товаров
            Команда: 4AH. Длина сообщения: от 17 до 71 байт..
                Пароль администратора или системного администратора
                или "СТАРШИЙ КАССИР" 1 (4 байта)
                Код товара (2 байта) 1...9999
                Цена (5 байт) 0000000000...9999999999
                Номер отдела (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (от 0 до 54 байт) строка – название товара
            Ответ: 4AH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 28, 29, 30
        """
        raise NotImplementedError()

    # Not implemented
    def x4B(self):
        """ Считать товар из базы товаров
            Команда: 4BH. Длина сообщения: 7 байт.
                Пароль администратора или системного администратора
                или "СТАРШИЙ КАССИР" 1 (4 байта)
                Код товара (2 байта) 1...9999
            Ответ: 4BH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 28, 29, 30
                Цена (5 байт) 0000000000...9999999999
                Номер отдела (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (54 байт) строка – название товара
        """
        raise NotImplementedError()

    # Not implemented
    def x4C(self):
        """ Удалить товар в базе товаров
            Команда: 4CH. Длина сообщения: 7 байт.
                Пароль администратора или системного администратора
                или "СТАРШИЙ КАССИР" 1 (4 байта)
                Код товара (2 байта) 1...9999
            Ответ: 4CH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 28, 29, 30
        """
        raise NotImplementedError()

    # Not implemented
    def x4D(self):
        """ Печать графики-512 с масштабированием
            Команда: 4DH. Длина сообщения: 12 байт.
                Пароль оператора (4 байта)
                Начальная линия (2 байта) 1...600
                Конечная линия (2 байта) 1...600
                Коэффициент масштабирования точки по вертикали (1 байт) 1...255
                Коэффициент масштабирования точки по горизонтали (1 байт) 1...6
                Флаги (1 байт)
                    Бит 0 – контрольная лента 2 ,
                    Бит 1 – чековая лента,
                    Бит 2 – подкладной документ,
                    Бит 3 – слип чек;
                    Бит 7 – отложенная печать графики
            Ответ: 4DH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x4E(self):
        """ Загрузка графики-512
            Команда: 4EH. Длина сообщения: 11+X байт.
                Пароль оператора (4 байта)
                Длина линии L (1 байт) 1...40 для T = 0; 1...64 для T = 1
                Номер начальной линии (2 байта)
                    1...1200 для T = 0;
                    1...600 для T = 1
                Количество последующих линий N (2 байта)
                    1...1200 для T = 0;
                    1...600 для T = 1
                Тип графического буфера T (1 байт)
                    0 – для команд [расширенной] графики;
                    1 – для команд графики-512
                Графическая информация (X = N * L байт)
            Ответ: 4EH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x4F(self):
        """ Печать графики с масштабированием
            Команда: 4FH. Длина сообщения: 9 байт.
                Пароль оператора (4 байта)
                Начальная линия (1 байт) 1...200
                Конечная линия (1 байт) 1...200
                Масштабирование точки по вертикали (1 байт) «0» – нет
                Масштабирование точки по горизонтали (1 байт) «0» – нет
            Ответ: 4EH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    def x50(self, summa):
        """ Внесение
            Команда: 50H. Длина сообщения: 10 байт.
                Пароль оператора (4 байта)
                Сумма (5 байт)
            Ответ: 50H. Длина сообщения: 5 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Сквозной номер документа (2 байта)
        """
        command = 0x50
        summa = money2integer(summa)
        summa = int5.pack(summa)
        params = self.password + summa

        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        document = int4.unpack(data[1:3])
        result = {
            'operator': operator,
            'document': document,
        }
        return result

    def x51(self, summa):
        """ Выплата
            Команда: 51H. Длина сообщения: 10 байт.
                Пароль оператора (4 байта)
                Сумма (5 байт)
            Ответ: 51H. Длина сообщения: 5 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Сквозной номер документа (2 байта)

        """
        command = 0x51
        summa = money2integer(summa)
        summa = int5.pack(summa)
        params = self.password + summa

        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        document = int4.unpack(data[1:3])
        result = {
            'operator': operator,
            'document': document,
        }
        return result

    def x52(self):
        """ Печать клише
            Команда: 52H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 52H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x52

        params = self.password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x53(self, ads=False):
        """ Конец Документа
            Команда: 53H. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Параметр (1 байт)
                    0 - без рекламного текста
                    1 - с рекламным тестом
            Ответ: 53H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x53
        params = self.password + chr(1 if ads else 0)
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x54(self):
        """ Печать рекламного текста
            Команда: 54H. Длина сообщения:5 байт.
                Пароль оператора (4 байта)
            Ответ: 54H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x54
        params = self.password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x60(self, password, number):
        """ Ввод заводского номера
            Команда: 60H. Длина сообщения: 9 байт.
                Пароль (4 байта) (пароль «0»)
                Заводской номер (4 байта) 00000000...99999999
            Ответ: 60H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0x60
        params = int4.pack(password) + int4.pack(number)
        data, error, command = self.ask(command, params)
        return error

    def x61(self):
        """ Инициализация ФП
            Команда: 61H. Длина сообщения: 1 байт.
            Ответ: 61H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание:
                Команда доступна только в случае установки в ФП
                процессора с программным обеспечением для
                инициализации и используется в технологических целях
                при производстве ККМ на заводе-изготовителе.
        """
        command = 0x61
        data, error, command = self.ask(command)
        return error

    def x62(self, after=False):
        """ Запрос суммы записей в ФП
            Команда: 62H. Длина сообщения: 6 байт.
                Пароль администратора или системного администратора
                    (4 байта)
                Тип запроса (1 байт) «0» – сумма всех записей, «1» –
                    сумма записей после последней перерегистрации
            Ответ: 62H. Длина сообщения: 29 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 29, 30
                Сумма всех сменных итогов продаж (8 байт)
                Сумма всех сменных итогов покупок (6 байт)
                    При отсутствии ФП 2:
                        FFh FFh FFh FFh FFh FFh
                Сумма всех сменных возвратов продаж (6 байт)
                    При отсутствии ФП 2:
                        FFh FFh FFh FFh FFh FFh
                Сумма всех сменных возвратов покупок (6 байт)
                    При отсутствии ФП 2:
                        FFh FFh FFh FFh FFh FFh
        """
        command = 0x62
        params = self.admin_password + chr(1 if after else 0)
        data, error, command = self.ask(command, params)

        result = {
            'operator': ord(data[0]),
            'sale': integer2money(int8.unpack(data[1:9])),
            'purchase': integer2money(int6.unpack(data[9:15])),
            'refuse_sale': integer2money(int6.unpack(data[15:21])),
            'refuse_purchase': integer2money(int6.unpack(data[21:])),
        }

        # Если ФП 2 установлена, то почему-то вовращает предельное число.
        # Поэтому мы его сбрасываем.
        for key in ('purchase', 'refuse_sale', 'refuse_purchase'):
            if result[key] == 2814749767106.55:
                result[key] = 0

        return result

    def x63(self):
        """ Запрос даты последней записи в ФП
            Команда: 63H. Длина сообщения: 5 байт.
                Пароль администратора или системного администратора
                    (4 байта)
            Ответ: 63H. Длина сообщения: 7 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 29, 30
                Тип последней записи (1 байт)
                    «0» – фискализация (перерегистрация),
                    «1» – сменный итог
                Дата (3 байта) ДД-ММ-ГГ
        """
        command = 0x63
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return {
            'operator': ord(data[0]),
            'type': ord(data[1]),
            'date': {
                'day': ord(data[2]),
                'month': ord(data[3]),
                'year': ord(data[4]),
            },
        }

    # Not implemented
    def x64(self):
        """ Запрос диапазона дат и смен
            Команда: 64H. Длина сообщения: 5 байт.
                Пароль налогового инспектора (4 байта)
            Ответ: 64H. Длина сообщения: 12 байт.
                Код ошибки (1 байт)
                Дата первой смены (3 байта) ДД-ММ-ГГ
                Дата последней смены (3 байта) ДД-ММ-ГГ
                Номер первой смены (2 байта) 0000...2100
                Номер последней смены (2 байта) 0000...2100
        """
        raise NotImplementedError()

    # Not implemented
    def x65(self):
        """ Фискализация (перерегистрация)
            Команда: 65H. Длина сообщения: 20 байт.
                Пароль старый (4 байта)
                Пароль новый (4 байта)
                РНМ (5 байт) 0000000000...9999999999
                ИНН (6 байт) 000000000000...999999999999
            Ответ: 65H. Длина сообщения: 9 байт.
                Код ошибки (1 байт)
                Номер фискализации (перерегистрации) (1 байт) 1...16
                Количество оставшихся перерегистраций (1 байт) 0...15
                Номер последней закрытой смены (2 байта) 0000...2100
                Дата фискализации (перерегистрации) (3 байта) ДД-ММ-ГГ
        """
        raise NotImplementedError()

    # Not implemented
    def x66(self):
        """ Фискальный отчет по диапазону дат
            Команда: 66H. Длина сообщения: 12 байт.
                Пароль налогового инспектора (4 байта)
                Тип отчета (1 байт) «0» – короткий, «1» – полный
                Дата первой смены (3 байта) ДД-ММ-ГГ
                Дата последней смены (3 байта) ДД-ММ-ГГ
            Ответ: 66H. Длина сообщения: 12 байт.
                Код ошибки (1 байт)
                Дата первой смены (3 байта) ДД-ММ-ГГ
                Дата последней смены (3 байта) ДД-ММ-ГГ
                Номер первой смены (2 байта) 0000...2100
                Номер последней смены (2 байта) 0000...2100
        """
        raise NotImplementedError()

    # Not implemented
    def x67(self):
        """ Фискальный отчет по диапазону смен
            Команда: 67H. Длина сообщения: 10 байт.
                Пароль налогового инспектора (4 байта)
                Тип отчета (1 байт) «0» – короткий, «1» – полный
                Номер первой смены (2 байта) 0000...2100
                Номер последней смены (2 байта) 0000...2100
            Ответ: 67H. Длина сообщения: 12 байт.
                Код ошибки (1 байт)
                Дата первой смены (3 байта) ДД-ММ-ГГ
                Дата последней смены (3 байта) ДД-ММ-ГГ
                Номер первой смены (2 байта) 0000...2100
                Номер последней смены (2 байта) 0000...2100
        """
        raise NotImplementedError()

    def x68(self, password):
        """ Прерывание полного отчета
            Команда: 68H. Длина сообщения: 5 байт.
                Пароль налогового инспектора (4 байта)
            Ответ: 68H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0x68
        params = int4.pack(password)
        data, error, command = self.ask(command, params)
        return error

    # Not implemented
    def x69(self):
        """ Чтение параметров фискализации (перерегистрации)
            Команда: 69H. Длина сообщения: 6 байт.
                Пароль налогового инспектора, при котором была проведена
                    данная фискализация (4 байта)
                Номер фискализации (перерегистрации) (1 байт) 1...16
            Ответ: 69H. Длина сообщения: 22 байта.
                Код ошибки (1 байт)
                Пароль (4 байта)
                РНМ (5 байт) 0000000000...9999999999
                ИНН (6 байт) 000000000000...999999999999
                Номер смены перед фискализацией (перерегистрацией)
                    (2 байта) 0000...2100
                Дата фискализации (перерегистрации) (3 байта) ДД-ММ-ГГ
        """
        raise NotImplementedError()

    # Not implemented
    def x6A(self):
        """ Проверка накопителя ФП на сбойные записи
            Команда: 6AH. Длина сообщения: 6 байт.
                Пароль системного администратора (4 байта)
                Тип проверяемой записи (1 байт):
                    «0» – проверка всех записей;
                    «1» – проверка записи серийного номера;
                    «2» – проверка записей фискализаций (перерегистраций);
                    «3» – проверка записей активизаций ЭКЛЗ;
                    «4» – проверка записей сменных итогов;
            Ответ: 6AH. Длина сообщения: 5 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 30
                Количество сбойных записей (2 байта)
        """
        raise NotImplementedError()

    def x6B(self, code):
        """ Возврат названия ошибки
            Команда: 6BH. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
            Ответ: 6BH. Длина сообщения: (2+X байт).
                Код ошибки (1 байт)
                Название ошибки 1 (X байт)
        """
        command = 0x6B
        params = chr(code)
        data, error, command = self.ask(command, params)
        return data

    # Not implemented
    def x70(self):
        """ Открыть фискальный подкладной документ
            Команда: 70H. Длина сообщения: 26 байт.
                Пароль оператора (4 байта)
                Тип документа (1 байт) «0» – продажа, «1» – покупка,
                    «2» – возврат продажи, «3» – возврат покупки
                Дублирование печати (извещение, квитанция) (1 байт) «0»
                    – колонки, «1» – блоки строк
                Количество дублей (1 байт) 0...5
                Смещение между оригиналом и 1-ым дублем печати (1 байт) *
                Смещение между 1-ым и 2-ым дублями печати (1 байт) *
                Смещение между 2-ым и 3-им дублями печати (1 байт) *
                Смещение между 3-им и 4-ым дублями печати (1 байт) *
                Смещение между 4-ым и 5-ым дублями печати (1 байт) *
                Номер шрифта клише (1 байт)
                Номер шрифта заголовка документа (1 байт)
                Номер шрифта номера ЭКЛЗ (1 байт)
                Номер шрифта значения КПК и номера КПК (1 байт)
                Номер строки клише (1 байт)
                Номер строки заголовка документа (1 байт)
                Номер строки номера ЭКЛЗ (1 байт)
                Номер строки признака повтора документа (1 байт)
                Смещение клише в строке (1 байт)
                Смещение заголовка документа в строке (1 байт)
                Смещение номера ЭКЛЗ в строке (1 байт)
                Смещение КПК и номера КПК в строке (1 байт)
                Смещение признака повтора документа в строке (1 байт)
            Ответ: 70H. Длина сообщения: 5 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Сквозной номер документа (2 байта)

            *– Для колонок величина смещения задаѐтся в символах, для
            блоков строк – в строках.
        """
        raise NotImplementedError()

    # Not implemented
    def x71(self):
        """ Открыть стандартный фискальный подкладной документ
            Команда: 71H. Длина сообщения: 13 байт.
                Пароль оператора (4 байта)
                Тип документа (1 байт)
                    «0» – продажа,
                    «1» – покупка,
                    «2» – возврат продажи,
                    «3» – возврат покупки
                Дублирование печати (извещение, квитанция) (1 байт)
                    «0» – колонки,
                    «1» – блоки строк
                Количество дублей (1 байт) 0...5
                Смещение между оригиналом и 1-ым дублем печати (1 байт) *
                Смещение между 1-ым и 2-ым дублями печати (1 байт) *
                Смещение между 2-ым и 3-им дублями печати (1 байт) *
                Смещение между 3-им и 4-ым дублями печати (1 байт) *
                Смещение между 4-ым и 5-ым дублями печати (1 байт) *
            Ответ: 71H. Длина сообщения: 5 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Сквозной номер документа (2 байта)
        """
        raise NotImplementedError()

    # Not implemented
    def x72(self):
        """ Формирование операции на подкладном документе
            Команда: 72H. Длина сообщения: 82 байта.
                Пароль оператора (4 байта)
                Формат целого количества (1 байт)
                    «0» – без цифр после запятой,
                    «1» – с цифрами
                после запятой
                Количество строк в операции (1 байт) 1...3
                Номер текстовой строки в операции (1 байт) 0...3,
                    «0» – не печатать
                Номер строки произведения количества на цену в операции
                (1 байт) 0...3,
                    «0» – не печатать
                Номер строки суммы в операции (1 байт) 1...3
                Номер строки отдела в операции (1 байт) 1...3
                Номер шрифта текстовой строки (1 байт)
                Номер шрифта количества (1 байт)
                Номер шрифта знака умножения количества на цену (1 байт)
                Номер шрифта цены (1 байт)
                Номер шрифта суммы (1 байт)
                Номер шрифта отдела (1 байт)
                Количество символов поля текстовой строки (1 байт)
                Количество символов поля количества (1 байт)
                Количество символов поля цены (1 байт)
                Количество символов поля суммы (1 байт)
                Количество символов поля отдела (1 байт)
                Смещение поля текстовой строки в строке (1 байт)
                Смещение поля произведения количества на цену в строке (1 байт)
                Смещение поля суммы в строке (1 байт)
                Смещение поля отдела в строке (1 байт)
                Номер строки ПД с первой строкой блока операции (1 байт)
                Количество (5 байт)
                Цена (5 байт)
                Отдел (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 72H. Длина сообщения: 3 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x73(self):
        """ Формирование стандартной операции на подкладном
                документе
            Команда: 73H. Длина сообщения: 61 байт.
                Пароль оператора (4 байта)
                Номер строки ПД с первой строкой блока операции (1 байт)
                Количество (5 байт)
                Цена (5 байт)
                Отдел (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 73H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x74(self):
        """ Формирование скидки/надбавки на подкладном документе
            Команда: 74H. Длина сообщения: 68 байт.
                Пароль оператора (4 байта)
                Количество строк в операции (1 байт) 1...2
                Номер текстовой строки в операции (1 байт) 0...2,
                    «0» – не печатать
                Номер строки названия операции в операции (1 байт) 1...2
                Номер строки суммы в операции (1 байт) 1...2
                Номер шрифта текстовой строки (1 байт)
                Номер шрифта названия операции (1 байт)
                Номер шрифта суммы (1 байт)
                Количество символов поля текстовой строки (1 байт)
                Количество символов поля суммы (1 байт)
                Смещение поля текстовой строки в строке (1 байт)
                Смещение поля названия операции в строке (1 байт)
                Смещение поля суммы в строке (1 байт)
                Тип операции (1 байт) «0» – скидка, «1» – надбавка
                Номер строки ПД с первой строкой блока скидки/надбавки (1 байт)
                Сумма (5 байт)
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 74H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x75(self):
        """ Формирование стандартной скидки/надбавки на
                подкладном документе
            Команда: 75H. Длина сообщения: 56 байт.
                Пароль оператора (4 байта)
                Тип операции (1 байт) «0» – скидка, «1» – надбавка
                Номер строки ПД с первой строкой блока скидки/надбавки
                    (1 байт)
                Сумма (5 байт)
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 75H. Длина сообщения: 3 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x76(self):
        """ Формирование закрытия чека на подкладном документе
            Команда: 76H. Длина сообщения: 182 байта.
                Пароль оператора (4 байта)
                Количество строк в операции (1 байт) 1...17
                Номер строки итога в операции (1 байт) 1...17
                Номер текстовой строки в операции (1 байт) 0...17,
                    «0» – не печатать
                Номер строки наличных в операции (1 байт) 0...17,
                    «0» – не печатать
                Номер строки типа оплаты 2 в операции (1 байт) 0...17,
                    «0» – не печатать
                Номер строки типа оплаты 3 в операции (1 байт) 0...17,
                    «0» – не печатать
                Номер строки типа оплаты 4 в операции (1 байт) 0...17,
                    «0» – не печатать
                Номер строки сдачи в операции (1 байт) 0...17, «0» – не
                    печатать
                Номер строки оборота по налогу А в операции (1 байт)
                    0...17, «0» – не печатать
                Номер строки оборота по налогу Б в операции (1 байт)
                    0...17, «0» – не печатать
                Номер строки оборота по налогу В в операции (1 байт)
                    0...17, «0» – не печатать
                Номер строки оборота по налогу Г в операции (1 байт)
                    0...17, «0» – не печатать
                Номер строки суммы по налогу А в операции (1 байт)
                    0...17, «0» – не печатать
                Номер строки суммы по налогу Б в операции (1 байт)
                    0...17, «0» – не печатать
                Номер строки суммы по налогу В в операции (1 байт)
                    0...17, «0» – не печатать
                Номер строки суммы по налогу Г в операции (1 байт)
                    0...17, «0» – не печатать
                Номер строки суммы до начисления скидки в операции
                    (1 байт) 0...17, «0» – не
                печатать
                Номер строки суммы скидки в операции (1 байт) 0...17,
                    «0» – не печатать
                Номер шрифта текстовой строки (1 байт)
                Номер шрифта «ИТОГ» (1 байт)
                Номер шрифта суммы итога (1 байт)
                Номер шрифта «НАЛИЧНЫМИ» (1 байт)
                Номер шрифта суммы наличных (1 байт)
                Номер шрифта названия типа оплаты 2 (1 байт)
                Номер шрифта суммы типа оплаты 2 (1 байт)
                Номер шрифта названия типа оплаты 3 (1 байт)
                Номер шрифта суммы типа оплаты 3 (1 байт)
                Номер шрифта названия типа оплаты 4 (1 байт)
                Номер шрифта суммы типа оплаты 4 (1 байт)
                Номер шрифта «СДАЧА» (1 байт)
                Номер шрифта суммы сдачи (1 байт)
                Номер шрифта названия налога А (1 байт)
                Номер шрифта оборота налога А (1 байт)
                Номер шрифта ставки налога А (1 байт)
                Номер шрифта суммы налога А (1 байт)
                Номер шрифта названия налога Б (1 байт)
                Номер шрифта оборота налога Б (1 байт)
                Номер шрифта ставки налога Б (1 байт)
                Номер шрифта суммы налога Б (1 байт)
                Номер шрифта названия налога В (1 байт)
                Номер шрифта оборота налога В (1 байт)
                Номер шрифта ставки налога В (1 байт)
                Номер шрифта суммы налога В (1 байт)
                Номер шрифта названия налога Г (1 байт)
                Номер шрифта оборота налога Г (1 байт)
                Номер шрифта ставки налога Г (1 байт)
                Номер шрифта суммы налога Г (1 байт)
                Номер шрифта «ВСЕГО» (1 байт)
                Номер шрифта суммы до начисления скидки (1 байт)
                Номер шрифта «СКИДКА ХХ.ХХ %» (1 байт)
                Номер шрифта суммы скидки на чек (1 байт)
                Количество символов поля текстовой строки (1 байт)
                Количество символов поля суммы итога (1 байт)
                Количество символов поля суммы наличных (1 байт)
                Количество символов поля суммы типа оплаты 2 (1 байт)
                Количество символов поля суммы типа оплаты 3 (1 байт)
                Количество символов поля суммы типа оплаты 4 (1 байт)
                Количество символов поля суммы сдачи (1 байт)
                Количество символов поля названия налога А (1 байт)
                Количество символов поля оборота налога А (1 байт)
                Количество символов поля ставки налога А (1 байт)
                Количество символов поля суммы налога А (1 байт)
                Количество символов поля названия налога Б (1 байт)
                Количество символов поля оборота налога Б (1 байт)
                Количество символов поля ставки налога Б (1 байт)
                Количество символов поля суммы налога Б (1 байт)
                Количество символов поля названия налога В (1 байт)
                Количество символов поля оборота налога В (1 байт)
                Количество символов поля ставки налога В (1 байт)
                Количество символов поля суммы налога В (1 байт)
                Количество символов поля названия налога Г (1 байт)
                Количество символов поля оборота налога Г (1 байт)
                Количество символов поля ставки налога Г (1 байт)
                Количество символов поля суммы налога Г (1 байт)
                Количество символов поля суммы до начисления скидки
                    (1 байт)
                Количество символов поля процентной скидки на чек
                    (1 байт)
                Количество символов поля суммы скидки на чек (1 байт)
                Смещение поля текстовой строки в строке (1 байт)
                Смещение поля «ИТОГ» в строке (1 байт)
                Смещение поля суммы итога в строке (1 байт)
                Смещение поля «НАЛИЧНЫМИ» в строке (1 байт)
                Смещение поля суммы наличных в строке (1 байт)
                Смещение поля названия типа оплаты 2 в строке (1 байт)
                Смещение поля суммы типа оплаты 2 в строке (1 байт)
                Смещение поля названия типа оплаты 3 в строке (1 байт)
                Смещение поля суммы типа оплаты 3 в строке (1 байт)
                Смещение поля названия типа оплаты 4 в строке (1 байт)
                Смещение поля суммы типа оплаты 4 в строке (1 байт)
                Смещение поля «СДАЧА» в строке (1 байт)
                Смещение поля суммы сдачи в строке (1 байт)
                Смещение поля названия налога А в строке (1 байт)
                Смещение поля оборота налога А в строке (1 байт)
                Смещение поля ставки налога А в строке (1 байт)
                Смещение поля суммы налога А в строке (1 байт)
                Смещение поля названия налога Б в строке (1 байт)
                Смещение поля оборота налога Б в строке (1 байт)
                Смещение поля ставки налога Б в строке (1 байт)
                Смещение поля суммы налога Б в строке (1 байт)
                Смещение поля названия налога В в строке (1 байт)
                Смещение поля оборота налога В в строке (1 байт)
                Смещение поля ставки налога В в строке (1 байт)
                Смещение поля суммы налога В в строке (1 байт)
                Смещение поля названия налога Г в строке (1 байт)
                Смещение поля оборота налога Г в строке (1 байт)
                Смещение поля ставки налога Г в строке (1 байт)
                Смещение поля суммы налога Г в строке (1 байт)
                Смещение поля «ВСЕГО» в строке (1 байт)
                Смещение поля суммы до начисления скидки в строке
                    (1 байт)
                Смещение поля «СКИДКА ХХ.ХХ %» в строке (1 байт)
                Смещение поля суммы скидки в строке (1 байт)
                Номер строки ПД с первой строкой блока операции (1 байт)
                Сумма наличных (5 байт)
                Сумма типа оплаты 2 (5 байт)
                Сумма типа оплаты 3 (5 байт)
                Сумма типа оплаты 4 (5 байт)
                Скидка в % на чек от 0 до 99,99 % (2 байта) 0000...9999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 76H. Длина сообщения: 8 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Сдача (5 байт) 0000000000...9999999999
        """
        raise NotImplementedError()

    def x77(self, cash=0, payment2=0, payment3=0, payment4=0, discount=0,
            text='', taxes=[0, 0, 0, 0]):
        """ Формирование стандартного закрытия чека на подкладном
                документе
            Команда: 77H. Длина сообщения: 72 байта.
                Пароль оператора (4 байта)
                Номер строки ПД с первой строкой блока операции (1 байт)
                Сумма наличных (5 байт)
                Сумма типа оплаты 2 (5 байт)
                Сумма типа оплаты 3 (5 байт)
                Сумма типа оплаты 4 (5 байт)
                Скидка в % на чек от 0 до 99,99 % (2 байта) 0000...9999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 77H. Длина сообщения: 8 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Сдача (5 байт) 0000000000...9999999999
        """
        command = 0x77

        cash = money2integer(cash)
        payment2 = money2integer(payment2)
        payment3 = money2integer(payment3)
        payment4 = money2integer(payment4)
        discount = money2integer(discount)

        if cash < 0 or cash > 9999999999:
            raise KktError(
                "Наличные должны быть в диапазоне между 0 и 9999999999")
        if payment2 < 0 or payment2 > 9999999999:
            raise KktError(
                "Оплата 2 должна быть в диапазоне между 0 и 9999999999")
        if payment3 < 0 or payment3 > 9999999999:
            raise KktError(
                "Оплата 3 должна быть в диапазоне между 0 и 0..9999999999")
        if payment4 < 0 or payment4 > 9999999999:
            raise KktError(
                "Оплата 4 должна быть в диапазоне между 0 и 9999999999")
        if discount < -9999 or discount > 9999:
            raise KktError(
                "Скидка должна быть в диапазоне между -9999 и 9999")
        if len(text) > 40:
            raise KktError(
                "Текст должнен быть менее или равен 40 символам")
        if len(taxes) != 4:
            raise KktError(
                "Количество налогов должно равняться 4")
        if not isinstance(taxes, (list, tuple)):
            raise KktError(
                "Перечень налогов должен быть типом list или tuple")
        for t in taxes:
            if t not in range(0, 5):
                raise KktError(
                    "Налоги должны быть равны 0,1,2,3 или 4")

        cash = int5.pack(cash)
        payment2 = int5.pack(payment2)
        payment3 = int5.pack(payment3)
        payment4 = int5.pack(payment4)
        discount = int2.pack(discount)
        taxes = digits2string(taxes)
        text = text.encode(CODE_PAGE).ljust(40, chr(0x0))

        params = (self.password + cash + payment2 + payment3 + payment4 +
                  discount + taxes + text)
        data, error, command = self.ask(command, params, quick=True)
        operator = ord(data[0])
        odd = int5.unpack(data[1:6])
        result = {
            'operator': operator,
            'odd': integer2money(odd),
        }
        return result

    # Not implemented
    def x78(self):
        """ Конфигурация подкладного документа
            Команда: 78H. Длина сообщения: 209 байт.
                Пароль оператора (4 байта)
                Ширина подкладного документа в шагах (2 байта)*
                Длина подкладного документа в шагах (2 байта)*
                Ориентация печати – поворот в градусах по часовой
                    стрелке (1 байт) «0» – 0o, «1» – 90o, «2» – 180o,
                    «3» – 270o
                Межстрочный интервал между 1-ой и 2-ой строками в шагах
                    (1 байт)*
                Межстрочный интервал между 2-ой и 3-ей строками в шагах
                    (1 байт)*
                Аналогично для строк 3...199 в шагах (1 байт)*
                Межстрочный интервал между 199-ой и 200-ой строками в
                    шагах (1 байт)*
            Ответ: 78H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30

            * - размер шага зависит от печатающего механизма
            конкретного фискального регистратора. Шаг по горизонтали
            не равен шагу по вертикали: эти параметры печатающего
            механизма указываются в инструкции по эксплуатации на ККТ.
        """
        raise NotImplementedError()

    # Not implemented
    def x79(self):
        """ Установка стандартной конфигурации подкладного
                документа
            Команда: 79H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 79H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x7A(self):
        """ Заполнение буфера подкладного документа нефискальной
                информацией
            Команда: 7AH. Длина сообщения: (6 + X) байт.
                Пароль оператора (4 байта)
                Номер строки (1 байт) 1...200
                Печатаемая информация (X байт) символ с кодом 27 и
                    следующий за ним символ не помещаются в буфер
                    подкладного документа, а задают тип шрифта
                    следующих символов; не более 250 байт
            Ответ: 7AH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x7B(self):
        """ Очистка строки буфера подкладного документа от
                нефискальной информации
            Команда: 7BH. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Номер строки (1 байт) 1...200
            Ответ: 7BH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x7C(self):
        """ Очистка всего буфера подк ладного документа от
                нефискальной информации
            Команда: 7CH. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 7CH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x7D(self):
        """ Печать подкладного документа
            Команда: 7DH. Длина сообщения: 7 байт.
                Пароль оператора (4 байта)
                Очистка нефискальной информации (1 байт) «0» – есть,
                    «1» – нет
                Тип печатаемой информации (1 байт) «0» – только
                    нефискальная информация, «1» – только фискальная
                    информация, «2» – вся информация
            Ответ: 7DH. Длина сообщения: 3 байта.
            Код ошибки (1 байт)
            Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x7E(self):
        """ Общая конфигурация подкладного документа
            Команда: 7EH. Длина сообщения: 11 байт.
                Пароль оператора (4 байта)
                Ширина подкладного документа в шагах (2 байта)*
                Длина подкладного документа в шагах (2 байта)*
                Ориентация печати (1 байт) «0» – 0o; «1» – 90o; «2» –
                    180o; «3» – 270o
                Межстрочный интервал между строками в шагах (1 байт)*
            Ответ: 7EH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30

            * - размер шага зависит от печатающего механизма
            конкретного фискального регистратора. Шаг по горизонтали
            не равен шагу по вертикали: эти параметры печатающего
            механизма указываются в инструкции по эксплуатации на ККТ.
        """
        raise NotImplementedError()

    def _x8count(self, command, count, price, text='', department=0,
                 taxes=[0, 0, 0, 0]):
        """ Общий метод для продаж, покупок, возвратов и сторно
            Команда: 80H. Длина сообщения: 60 байт.
                Пароль оператора (4 байта)
                Количество (5 байт) 0000000000...9999999999
                Цена (5 байт) 0000000000...9999999999
                Номер отдела (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 80H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = command

        count = count2integer(count)
        price = money2integer(price)

        if count < 0 or count > 9999999999:
            raise KktError(
                "Количество должно быть в диапазоне между 0 и 9999999999")
        if price < 0 or price > 9999999999:
            raise KktError(
                "Цена должна быть в диапазоне между 0 и 9999999999")
        if department not in range(17):
            raise KktError(
                "Номер отдела должен быть в диапазоне между 0 и 16")

        if len(text) > 40:
            raise KktError("Текст должнен быть менее или равен 40 символам")
        if len(taxes) != 4:
            raise KktError("Количество налогов должно равняться 4")
        if not isinstance(taxes, (list, tuple)):
            raise KktError("Перечень налогов должен быть типом list или tuple")
        for t in taxes:
            if t not in range(0, 5):
                raise KktError("Налоги должны быть равны 0, 1, 2, 3 или 4")

        count = int5.pack(count)
        price = int5.pack(price)
        department = chr(department)
        taxes = digits2string(taxes)
        text = text.encode(CODE_PAGE).ljust(40, chr(0x0))

        params = self.password + count + price + department + taxes + text
        data, error, command = self.ask(command, params, quick=True)
        operator = ord(data[0])
        return operator

    def x80(self, count, price, text='', department=0, taxes=[0, 0, 0, 0]):
        """ Продажа
            Команда: 80H. Длина сообщения: 60 байт.
                Пароль оператора (4 байта)
                Количество (5 байт) 0000000000...9999999999
                Цена (5 байт) 0000000000...9999999999
                Номер отдела (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 80H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x80
        return self._x8count(
            command=command, count=count, price=price, text=text,
            department=department, taxes=taxes)

    def x81(self, count, price, text='', department=0, taxes=[0, 0, 0, 0]):
        """ Покупка
            Команда: 81H. Длина сообщения: 60 байт.
                Пароль оператора (4 байта)
                Количество (5 байт) 0000000000...9999999999
                Цена (5 байт) 0000000000...9999999999
                Номер отдела (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 81H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x81
        return self._x8count(
            command=command, count=count, price=price, text=text,
            department=department, taxes=taxes)

    def x82(self, count, price, text='', department=0, taxes=[0, 0, 0, 0]):
        """ Возврат продажи
            Команда: 82H. Длина сообщения: 60 байт.
                Пароль оператора (4 байта)
                Количество (5 байт) 0000000000...9999999999
                Цена (5 байт) 0000000000...9999999999
                Номер отдела (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 82H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x82
        return self._x8count(
            command=command, count=count, price=price, text=text,
            department=department, taxes=taxes)

    def x83(self, count, price, text='', department=0, taxes=[0, 0, 0, 0]):
        """ Возврат покупки
            Команда: 83H. Длина сообщения: 60 байт.
                Пароль оператора (4 байта)
                Количество (5 байт) 0000000000...9999999999
                Цена (5 байт) 0000000000...9999999999
                Номер отдела (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 83H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x83
        return self._x8count(
            command=command, count=count, price=price, text=text,
            department=department, taxes=taxes)

    def x84(self, count, price, text='', department=0, taxes=[0, 0, 0, 0]):
        """ Сторно
            Команда: 84H. Длина сообщения: 60 байт.
                Пароль оператора (4 байта)
                Количество (5 байт) 0000000000...9999999999
                Цена (5 байт) 0000000000...9999999999
                Номер отдела (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 84H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x84
        return self._x8count(
            command=command, count=count, price=price, text=text,
            department=department, taxes=taxes)

    def x85(self, cash=0, summs=[0, 0, 0, 0], discount=0, taxes=[0, 0, 0, 0],
            text=''):
        """ Закрытие чека
            Команда: 85H. Длина сообщения: 71 байт.
                Пароль оператора (4 байта)
                Сумма наличных      (5 байт) 0000000000...9999999999
                Сумма типа оплаты 2 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 3 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 4 (5 байт) 0000000000...9999999999
                Скидка/Надбавка(в случае отрицательного значения) в % на
                    чек от 0 до 99,99 % (2 байта со знаком) -9999...9999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 85H. Длина сообщения: 8 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Сдача (5 байт) 0000000000...9999999999
        """
        command = 0x85

        summa1 = money2integer(summs[0] or cash)
        summa2 = money2integer(summs[1])
        summa3 = money2integer(summs[2])
        summa4 = money2integer(summs[3])
        discount = money2integer(discount)

        for i, s in enumerate([summa1, summa2, summa3, summa4]):
            if s < 0 or s > 9999999999:
                raise KktError(
                    "Переменная `summa%d` должна быть в диапазоне между "
                    "0 и 9999999999" % i + 1)
        if discount < -9999 or discount > 9999:
            raise KktError("Скидка должна быть в диапазоне между -9999 и 9999")

        if len(text) > 40:
            raise KktError("Текст должнен быть менее или равен 40 символам")
        if len(taxes) != 4:
            raise KktError("Количество налогов должно равняться 4")
        if not isinstance(taxes, (list, tuple)):
            raise KktError("Перечень налогов должен быть типом list или tuple")
        for t in taxes:
            if t not in range(0, 5):
                raise KktError("Налоги должны быть равны 0, 1, 2, 3 или 4")

        summa1 = int5.pack(summa1)
        summa2 = int5.pack(summa2)
        summa3 = int5.pack(summa3)
        summa4 = int5.pack(summa4)
        discount = int2.pack(discount)
        taxes = digits2string(taxes)
        text = text.encode(CODE_PAGE).ljust(40, chr(0x0))

        params = (self.password + summa1 + summa2 + summa3 + summa4 +
                  discount + taxes + text)
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        odd = int5.unpack(data[1:6])
        result = {
            'operator': operator,
            'odd': integer2money(odd),
        }
        return result

    def _x8summa(self, command, summa, text='', taxes=[0, 0, 0, 0]):
        """ Общий метод для скидок,
            Команда: 86H. Длина сообщения: 54 байт.
                Пароль оператора (4 байта)
                Сумма (5 байт) 0000000000...9999999999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 86H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = command

        summa = money2integer(summa)

        if summa < 0 or summa > 9999999999:
            raise KktError(
                "Сумма должна быть в диапазоне между 0 и 9999999999")
        if len(text) > 40:
            raise KktError("Текст должнен быть менее или равен 40 символам")
        if len(taxes) != 4:
            raise KktError("Количество налогов должно равняться 4")
        if not isinstance(taxes, (list, tuple)):
            raise KktError("Перечень налогов должен быть типом list или tuple")
        for t in taxes:
            if t not in range(0, 5):
                raise KktError("Налоги должны быть равны 0, 1, 2, 3 или 4")

        summa = int5.pack(summa)
        taxes = digits2string(taxes)
        text = text.encode(CODE_PAGE).ljust(40, chr(0x0))

        params = self.password + summa + taxes + text
        data, error, command = self.ask(command, params, quick=True)
        operator = ord(data[0])
        return operator

    def x86(self, summa, text='', taxes=[0, 0, 0, 0]):
        """ Скидка
            Команда: 86H. Длина сообщения: 54 байт.
                Пароль оператора (4 байта)
                Сумма (5 байт) 0000000000...9999999999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 86H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x86
        return self._x8summa(command=command, summa=summa, text=text,
                             taxes=taxes)

    def x87(self, summa, text='', taxes=[0, 0, 0, 0]):
        """ Надбавка
            Команда: 87H. Длина сообщения: 54 байт.
                Пароль оператора (4 байта)
                Сумма (5 байт) 0000000000...9999999999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 87H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x87
        return self._x8summa(command=command, summa=summa, text=text,
                             taxes=taxes)

    def x88(self):
        """ Аннулирование чека
            Команда: 88H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 88H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30

        """
        command = 0x88
        data, error, command = self.ask(command)
        operator = ord(data[0])
        return operator

    def x89(self):
        """ Подытог чека
            Команда: 89H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 89H. Длина сообщения: 8 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Подытог чека (5 байт) 0000000000...9999999999
        """
        command = 0x89
        data, error, command = self.ask(command)
        operator = ord(data[0])
        return operator

    def x8A(self, summa, text='', taxes=[0, 0, 0, 0]):
        """ Сторно скидки
            Команда: 8AH. Длина сообщения: 54 байта.
                Пароль оператора (4 байта)
                Сумма (5 байт) 0000000000...9999999999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 8AH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x8A
        return self._x8summa(command=command, summa=summa, text=text,
                             taxes=taxes)

    def x8B(self, summa, text='', taxes=[0, 0, 0, 0]):
        """ Сторно надбавки
            Команда: 8BH. Длина сообщения: 54 байта.
                Пароль оператора (4 байта)
                Сумма (5 байт) 0000000000...9999999999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 8BH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x8B
        return self._x8summa(command=command, summa=summa,
                             text=text, taxes=taxes)

    def x8C(self):
        """ Повтор документа
            Команда: 8CH. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 8CH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30

            Примечание:
                Команда выводит на печать копию последнего закрытого
                документа продажи, покупки, возврата продажи и
                возврата покупки.
        """
        command = 0x8C
        data, error, command = self.ask(command)
        operator = ord(data[0])
        return operator

    def x8D(self, document_type):
        """ Открыть чек
            Команда: 8DH. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Тип документа (1 байт):
                    0 – продажа;
                    1 – покупка;
                    2 – возврат продажи;
                    3 – возврат покупки
            Ответ: 8DH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0x8D

        if document_type not in range(4):
            raise KktError("Тип документа должен быть значением 0, 1, 2 или 3")

        params = self.password + chr(document_type)
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def x8E(self, payments, taxes, text='', discount_percent=0):
        """ Закрытие чека расширенное
            Команда: 8EH. Длина сообщения: 71+12*5=131 байт.
                Пароль оператора (4 байта)
                Сумма наличных (5 байт) 0000000000...9999999999
                Сумма типа оплаты 2 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 3 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 4 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 5 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 6 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 7 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 8 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 9 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 10 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 11 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 12 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 13 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 14 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 15 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 16 (5 байт) 0000000000...9999999999
                Скидка/Надбавка(в случае отрицательного значения) в % на чек
                    от 0 до 99,99 % (2 байта со знаком) -9999...9999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 8EH. Длина сообщения: 8 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Сдача (5 байт) 0000000000...9999999999
        """
        command = 0x8E
        params = self.password
        assert len(payments) == 16, \
            'Количество типов оплат должно быть равно 16.'
        for val in payments:
            params += int5.pack(money2integer(val))
        params += int2.pack(discount_percent)
        assert len(taxes) == 4, 'Количество налогов должно быть равно 4.'
        for val in taxes:
            params += chr(val)
        params += text.encode(CODE_PAGE).ljust(40, chr(0x0))
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return integer2money(int5.unpack(data[1:]))

    # Not implemented
    def x90(self):
        """ Формирование чека отпуска нефтепродуктов в режиме
            предоплаты заданной дозы
            Команда: 90H. Длина сообщения: 61 байт.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
                Доза в миллилитрах (4 байта)
                Номер отдела (1 байт) 0...16
                Сумма наличных (5 байт) 0000000000...9999999999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 90H. Длина сообщения: 12 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Доза в миллилитрах (4 байта) 00000000...99999999
                Доза в денежных единицах (5 байт) 0000000000...9999999999
        """
        raise NotImplementedError()

    # Not implemented
    def x91(self):
        """ Формирование чека отпуска нефтепродуктов в режиме
                предоплаты на заданную сумму
            Команда: 91H. Длина сообщения: 57 байт.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
                Номер отдела (1 байт) 0...16
                Сумма наличных (5 байт) 0000000000...9999999999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 91H. Длина сообщения: 12 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Доза в миллилитрах (4 байта) 00000000...99999999
                Доза в денежных единицах (5 байт) 0000000000...9999999999
        """
        raise NotImplementedError()

    # Not implemented
    def x92(self):
        """ Формирование чека коррекции при неполном отпуске
                нефтепродуктов
            Команда: 92H. Длина сообщения: 52 байта.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
                Номер отдела (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 92H. Длина сообщения: 12 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Недолитая доза в миллилитрах (4 байта) 00000000...99999999
                Возвращаемая сумма (5 байт) 0000000000...9999999999
        """
        raise NotImplementedError()

    # Not implemented
    def x93(self):
        """ Задание дозы РК в миллилитрах
            Команда: 93H. Длина сообщения: 11 байт.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
                Доза в миллилитрах (4 байта), если доза FFh FFh FFh FFh,
                то производится заправка до полного бака:
                    00000000...99999999
            Ответ: 93H. Длина сообщения: 12 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Доза в миллилитрах (4 байта) 00000000...99999999
                Доза в денежных единицах (5 байт) 0000000000...9999999999
        """
        raise NotImplementedError()

    # Not implemented
    def x94(self):
        """ Задание дозы РК в денежных единицах
            Команда: 94H. Длина сообщения: 12 байт.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
                Сумма наличных (5 байт) 0000000000...9999999999
            Ответ: 94H. Длина сообщения: 12 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Доза в миллилитрах (4 байта) 00000000...99999999
                Доза в денежных единицах (5 байт) 0000000000...9999999999
        """
        raise NotImplementedError()

    # Not implemented
    def x95(self):
        """ Продажа нефтепродуктов
            Команда: 95H. Длина сообщения: 52 байта.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
                Номер отдела (1 байт) 0...16
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Текст (40 байт)
            Ответ: 95H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x96(self):
        """ Останов РК
            Команда: 96H. Длина сообщения: 7 байт.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
            Ответ: 96H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x97(self):
        """ Пуск РК
            Команда: 97H. Длина сообщения: 7 байт.
                Пароль оператора (4 байта)
                Номер ТРК 1...31 (1 байт)
                Номер РК в ТРК 1...8 (1 байт)
            Ответ: 97H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x98(self):
        """ Сброс РК
            Команда: 98H. Длина сообщения: 7 байт.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
            Ответ: 98H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x99(self):
        """ Сброс всех ТРК
            Команда: 99H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: 99H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x9A(self):
        """ Задание параметров РК
            Команда: 9AH. Длина сообщения: 13 байт.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
                Замедление в миллилитрах (3 байта) 000000...999999
                Цена (3 байта) 000000...999999
            Ответ: 9AH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def x9B(self):
        """ Считать литровый суммарный счетчик
            Команда: 9BH. Длина сообщения: 7 байт.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
            Ответ: 9BH. Длина сообщения: 7 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Суммарный счетчик в миллилитрах (4 байта) 00000000...99999999
        """
        raise NotImplementedError()

    # Not implemented
    def x9E(self):
        """ Запрос текущей дозы РК
            Команда: 9EH. Длина сообщения: 7 байт.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
            Ответ: 9EH. Длина сообщения: 7 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Текущая доза в миллилитрах (4 байта) 00000000...99999999
        """
        raise NotImplementedError()

    # Not implemented
    def x9F(self):
        """ Запрос состояния РК
            Команда: 9FH. Длина сообщения: 7 байт.
                Пароль оператора (4 байта)
                Номер ТРК (1 байт) 1...31
                Номер РК в ТРК (1 байт) 1...8
            Ответ: 9FH. Длина сообщения: 30 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Текущая доза в миллилитрах (4 байта) 00000000...99999999
                Заданная доза в миллилитрах (4 байта) 00000000...99999999
                Текущая доза в денежных единицах (5 байт)
                    0000000000...9999999999
                Заданная доза в денежных единицах (5 байт)
                    0000000000...9999999999
                Замедление в миллилитрах (3 байта) 000000...999999
                Цена (3 байта) 000000...999999
                Статус РК (1 байт):
                    00 ТРК в сервисном режиме
                    01 готовность, доза не задана
                    02 готовность, доза задана
                    03 пуск, ожидание снятия пистолета
                    04 пуск, ожидание возврата пистолета
                    05 пуск, ожидание снятия пистолета,
                       после возврата пистолета
                    06 пуск, тест индикатора
                    07 заправка на полной производительности
                    08 заправка с замедлением
                    09 остановка по исчерпанию дозы
                    0A остановка при отсутствии импульсов с датчика
                       (по тайм-ауту)
                    0B остановка по команде оператора
                    0С остановка по возврату пистолета
                    0D остановка по ошибке
                Флаги РК (1 байт)
                    0 бит – «0» – мотор выключен, «1» – включен
                    1 бит – «0» – грубый клапан выключен, «1» - включен
                    2 бит – «0» – замедляющий клапан выключен, «1» - включен
                    3 бит – «0» – пистолет повешен, «1» – пистолет снят
                    4 бит – «0» – чек оформлен, «1» – чек не оформлен
                    5 бит – «0» – чек закрыт, «1» – чек не закрыт
                Код ошибки при аварийной остановке (1 байт)
                    00 – аварийной остановки нет
                    01 – внутренняя ошибка контроллера
                    02 – обратное вращение датчика
                    03 – обрыв фаз датчика объема SIN
                    04 – обрыв цепи управления пускателя
                    05 – обрыв цепи управления основным клапаном
                    06 – обрыв цепи управления клапаном снижения
                    07 – переполнение
                    08 – перелив
                    09 – обрыв фаз датчика объѐма COS
                    FF – неисправность оборудования
        """
        raise NotImplementedError()

    # Not implemented
    def xA0(self):
        """ Отчет ЭКЛЗ по отделам в заданном диапазоне дат
            Команда: A0H. Длина сообщения: 13 байт.
                Пароль системного администратора (4 байта)
                Тип отчета (1 байт) «0» – короткий, «1» – полный
                Номер отдела (1 байт) 1...16
                Дата первой смены (3 байта) ДД-ММ-ГГ
                Дата последней смены (3 байта) ДД-ММ-ГГ
            Ответ: A0H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание: Время выполнения команды – до 150 секунд.
        """
        raise NotImplementedError()

    # Not implemented
    def xA1(self):
        """ Отчет ЭКЛЗ по отделам в заданном диапазоне номеров
                смен
            Команда: A1H. Длина сообщения: 11 байт.
                Пароль системного администратора (4 байта)
                Тип отчета (1 байт) «0» – короткий, «1» – полный
                Номер отдела (1 байт) 1...16
                Номер первой смены (2 байта) 0000...2100
                Номер последней смены (2 байта) 0000...2100
            Ответ: A1H. Длина сообщения: 2 байта.
            Код ошибки (1 байт)

            Примечание: Время выполнения команды – до 150 секунд.
        """
        raise NotImplementedError()

    # Not implemented
    def xA2(self):
        """ Отчет ЭКЛЗ по закрытиям смен в заданном диапазоне дат
            Команда: A2H. Длина сообщения: 12 байт.
                Пароль системного администратора (4 байта)
                Тип отчета (1 байт) «0» – короткий, «1» – полный
                Дата первой смены (3 байта) ДД-ММ-ГГ
                Дата последней смены (3 байта) ДД-ММ-ГГ
            Ответ: A2H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание: Время выполнения команды – до 100 секунд.
        """
        raise NotImplementedError()

    # Not implemented
    def xA3(self):
        """ Отчет ЭКЛЗ по закрытиям смен в заданном диапазоне
                номеров смен
            Команда: A3H. Длина сообщения: 10 байт.
                Пароль системного администратора (4 байта)
                Тип отчета (1 байт) «0» – короткий, «1» – полный
                Номер первой смены (2 байта) 0000...2100
                Номер последней смены (2 байта) 0000...2100
            Ответ: A3H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание: Время выполнения команды – до 100 секунд.
        """
        raise NotImplementedError()

    def xA4(self, number):
        """ Итоги смены по номеру смены ЭКЛЗ
            Команда: A4H. Длина сообщения: 7 байт.
                Пароль системного администратора (4 байта)
                Номер смены (2 байта) 0000...2100
            Ответ: A4H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание: Время выполнения команды – до 40 секунд.
        """
        command = 0xBA
        params = self.admin_password + int2.pack(int(number))
        data, error, command = self.ask(command, params)
        return True

    # Not implemented
    def xA5(self):
        """ Платежный документ из ЭКЛЗ по номеру КПК
            Команда: A5H. Длина сообщения: 9 байт.
                Пароль системного администратора (4 байта)
                Номер КПК (4 байта) 00000000...99999999
            Ответ: A5H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание: Время выполнения команды – до 40 секунд.
        """
        raise NotImplementedError()

    # Not implemented
    def xA6(self):
        """ Контрольная лента из ЭКЛЗ по номеру смены
            Команда: A6H. Длина сообщения: 7 байт.
                Пароль системного администратора (4 байта)
                Номер смены (2 байта) 0000...2100
            Ответ: A6H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание: Время выполнения команды – до 40 секунд.
        """
        raise NotImplementedError()

    def xA7(self):
        """ Прерывание полного отчета ЭКЛЗ или контрольной ленты
                ЭКЛЗ или печати платежного документа ЭКЛЗ
            Команда: A7H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: A7H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0xA7
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xA8(self):
        """ Итог активизации ЭКЛЗ
            Команда: A8H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: A8H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0xA8
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xA9(self):
        """ Активизация ЭКЛЗ
            Команда: A9H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: A9H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0xA9
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xAA(self):
        """ Закрытие архива ЭКЛЗ
            Команда: AAH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: AAH. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0xAA
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xAB(self):
        """ Запрос регистрационного номера ЭКЛЗ
            Команда: ABH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: ABH. Длина сообщения: 7 байт.
                Код ошибки (1 байт)
                Номер ЭКЛЗ (5 байт) 0000000000...9999999999
        """
        command = 0xAB
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return int5.unpack(data[:5])

    def xAC(self):
        """ Прекращение ЭКЛЗ
            Команда: ACH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: ACH. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0xAC
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    # Not implemented
    def xAD(self):
        """ Запрос состояния по коду 1 ЭКЛЗ
            Команда: ADH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: ADH. Длина сообщения: 22 байта.
                Код ошибки (1 байт)
                Итог документа последнего КПК (5 байт) 0000000000...9999999999
                Дата последнего КПК (3 байта) ДД-ММ-ГГ
                Время последнего КПК (2 байта) ЧЧ-ММ
                Номер последнего КПК (4 байта) 00000000...99999999
                Номер ЭКЛЗ (5 байт) 0000000000...9999999999
                Флаги ЭКЛЗ (см. описание ЭКЛЗ) (1 байт)

            Примечание:
                Флаги, используемые ЭКЛЗ, описаны в документе
                «Драйвер ККТ: руководство программиста» версии А4.3 и
                выше.
        """
        # command = 0xAD
        # params = self.admin_password
        # data, error, command = self.ask(command, params)
        raise NotImplementedError()

    # Not implemented
    def xAE(self):
        """ Запрос состояния по коду 2 ЭКЛЗ
            Команда: AEH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: AEH. Длина сообщения: 28 байт.
                Код ошибки (1 байт)
                Номер смены (2 байта) 0000...2100
                Итог продаж (6 байт) 000000000000...999999999999
                Итог покупок (6 байт) 000000000000...999999999999
                Итог возвратов продаж (6 байт) 000000000000...999999999999
                Итог возвратов покупок (6 байт) 000000000000...999999999999
        """
        # command = 0xAE
        # params = self.admin_password
        # data, error, command = self.ask(command, params)
        raise NotImplementedError()

    def xAF(self):
        """ Тест целостности архива ЭКЛЗ
            Команда: AFH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: AFH. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        command = 0xAF
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xB0(self, admin_password=None):
        """ Продолжение печати
            Команда: B0H. Длина сообщения: 5 байт.
                Пароль оператора, администратора или системного
                    администратора (4 байта)
            Ответ: B0H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0xB0
        params = admin_password or self.admin_password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def xB1(self):
        """ Запрос версии ЭКЛЗ
            Команда: B1H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: B1H. Длина сообщения: 20 байт.
                Код ошибки (1 байт)
                Строка символов в кодировке WIN1251 (18 байт)
        """
        command = 0xB1
        params = self.admin_password
        data, error, command = self.ask(command, params)
        version = data[:18].decode(CODE_PAGE)
        return version

    def xB2(self):
        """ Инициализация архива ЭКЛЗ
            Команда: B2H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: B2H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание:
                Команда работает только с отладочным комплектом ЭКЛЗ.
                Время выполнения команды – до 20 секунд.
        """
        command = 0xB2
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xB3(self):
        """ Запрос данных отчѐта ЭКЛЗ
            Команда: B3H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: B3H. Длина сообщения: (2+Х) байт.
                Код ошибки (1 байт)
                Строка или фрагмент отчета (см. спецификацию ЭКЛЗ) (X байт)
        """
        command = 0xE1
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return data.decode(CODE_PAGE)

    # Not implemented
    def xB4(self):
        """ Запрос контрольной ленты ЭКЛЗ
            Команда: B4H. Длина сообщения: 7 байт.
                Пароль системного администратора (4 байта)
                Номер смены (2 байта) 0000...2100
            Ответ: B4H. Длина сообщения: 18 байт.
                Код ошибки (1 байт)
                Тип ККМ – строка символов в кодировке WIN1251 (16 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xB5(self):
        """ Запрос документа ЭКЛЗ
            Команда: B5H. Длина сообщения: 9 байт.
                Пароль системного администратора (4 байта)
                Номер КПК (4 байта) 00000000...99999999
            Ответ: B5H. Длина сообщения: 18 байт.
                Код ошибки (1 байт)
                Тип ККМ – строка символов в кодировке WIN1251 (16 байт)

            Примечание: Время выполнения команды – до 40 секунд.
        """
        raise NotImplementedError()

    # Not implemented
    def xB6(self):
        """ Запрос отчѐта ЭКЛЗ по отделам в заданном диапазоне дат
            Команда: B6H. Длина сообщения: 13 байт.
                Пароль системного администратора (4 байта)
                Тип отчета (1 байт) «0» – короткий, «1» – полный
                Номер отдела (1 байт) 1...16
                Дата первой смены (3 байта) ДД-ММ-ГГ
                Дата последней смены (3 байта) ДД-ММ-ГГ
            Ответ: B6H. Длина сообщения: 18 байт.
                Код ошибки (1 байт)
                Тип ККМ – строка символов в кодировке WIN1251 (16 байт)

            Примечание: Время выполнения команды – до 150 секунд.

        """
        raise NotImplementedError()

    # Not implemented
    def xB7(self):
        """ Запрос отчѐта ЭКЛЗ по отделам в заданном диапазоне
                номеров смен
            Команда: B7H. Длина сообщения: 11 байт.
                Пароль системного администратора (4 байта)
                Тип отчета (1 байт) «0» – короткий, «1» – полный
                Номер отдела (1 байт) 1...16
                Номер первой смены (2 байта) 0000...2100
                Номер последней смены (2 байта) 0000...2100
            Ответ: B7H. Длина сообщения: 18 байт.
                Код ошибки (1 байт)
                Тип ККМ – строка символов в кодировке WIN1251 (16 байт)

            Примечание: Время выполнения команды – до 150 секунд.

        """
        raise NotImplementedError()

    # Not implemented
    def xB8(self):
        """ Запрос отчѐта ЭКЛЗ по закрытиям смен в заданном
                диапазоне дат
            Команда: B8H. Длина сообщения: 12 байт.
                Пароль системного администратора (4 байта)
                Тип отчета (1 байт) «0» – короткий, «1» – полный
                Дата первой смены (3 байта) ДД-ММ-ГГ
                Дата последней смены (3 байта) ДД-ММ-ГГ
            Ответ: B8H. Длина сообщения: 18 байт.
                Код ошибки (1 байт)
                Тип ККМ – строка символов в кодировке WIN1251 (16 байт)

            Примечание: Время выполнения команды – до 100 секунд.

        """
        raise NotImplementedError()

    # Not implemented
    def xB9(self):
        """ Запрос отчѐта ЭКЛЗ по закрытиям смен в заданном диапазоне
                номеров смен.
            Команда: B9H. Длина сообщения: 10 байт.
                Пароль системного администратора (4 байта)
                Тип отчета (1 байт) «0» – короткий, «1» – полный
                Номер первой смены (2 байта) 0000...2100
                Номер последней смены (2 байта) 0000...2100
            Ответ: B9H. Длина сообщения: 18 байт.
                Код ошибки (1 байт)
                Тип ККМ – строка символов в кодировке WIN1251 (16 байт)

            Примечание: Время выполнения команды – до 100 секунд.
        """
        raise NotImplementedError()

    def xBA(self, number):
        """ Запрос в ЭКЛЗ итогов смены по номеру смены
            Команда: BAH. Длина сообщения: 7 байт.
                Пароль системного администратора (4 байта)
                Номер смены (2 байта) 0000...2100
            Ответ: BAH. Длина сообщения: 18 байт.
                Код ошибки (1 байт)
                Тип ККМ – строка символов в кодировке WIN1251 (16 байт)

            Примечание: Время выполнения команды – до 40 секунд.
        """
        command = 0xBA
        params = self.admin_password + int2.pack(int(number))
        data, error, command = self.ask(command, params)
        kkm = data.decode(CODE_PAGE)
        return kkm

    # Not implemented
    def xBB(self):
        """ Запрос итога активизации ЭКЛЗ
            Команда: BBH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: BBH. Длина сообщения: 18 байт.
                Код ошибки (1 байт)
                Тип ККМ – строка символов в кодировке WIN1251 (16 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xBC(self):
        """ Вернуть ошибку ЭКЛЗ
            Команда: BCH. Длина сообщения: 6 байт.
                Пароль системного администратора (4 байта)
                Код ошибки (1 байт)
            Ответ: BCH. Длина сообщения: 2 байта.
                Код ошибки (1 байт)

            Примечание:
                Команда работает только с отладочным комплектом ЭКЛЗ.
        """
        raise NotImplementedError()

    # Not implemented
    def xBD(self):
        """ Запрос состояния по коду 3 ЭКЛЗ
            Команда: BDH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: BDH. Длина сообщения: 4 байта.
                Код ошибки (1 байт)
                Байт состояния МФП (1 байт)
                Расширенной состояние активации act_status (1 байт)
        """
        raise NotImplementedError()

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def xC0(self):
        """ Загрузка графики
            Команда: C0H. Длина сообщения: 46 байт.
                Пароль оператора (4 байта)
                Номер линии (1 байт) 0...199
                Графическая информация (40 байт)
            Ответ: C0H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def xC1(self):
        """ Печать графики
            Команда: C1H. Длина сообщения: 7 байт.
                Пароль оператора (4 байта)
                Начальная линия (1 байт) 1...200
                Конечная линия (1 байт) 1...200
            Ответ: С1H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    def xC2(self, barcode):
        """ Печать штрих-кода
            Команда: C2H. Длина сообщения: 10 байт.
                Пароль оператора (4 байта)
                Штрих-код (5 байт) 000000000000...999999999999
            Ответ: С2H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        command = 0xC2
        barcode = int5.pack(barcode)

        params = self.password + barcode
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def xC3(self):
        """ Печать расширенной графики
            Команда: C3H. Длина сообщения: 9 байт.
                Пароль оператора (4 байта)
                Начальная линия (2 байта) 1...1200
                Конечная линия (2 байта) 1...1200
            Ответ: C3H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def xC4(self):
        """ Загрузка расширенной графики
            Команда: C4H. Длина сообщения: 47 байт.
                Пароль оператора (4 байта)
                Номер линии (2 байта) 0...1199
                Графическая информация (40 байт)
            Ответ: С4H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def xC5(self):
        """ Печать графической линии (одномерный штрихкод)
            Команда: C5H. Длина сообщения: 7+Y или 7+1+Y байт.
                Пароль оператора (4 байта)
                Количество повторов линии (2 байта) 1...1200
                Флаги 1 (1 байт)
                    Бит 0 – контрольная лента,
                    Бит 1 – чековая лента,
                    Бит 2 – подкладной документ,
                    Бит 3 – слип чек;
                    Бит 7 – отложенная печать графики
                Графическая информация (Y байт)
            Ответ: C5H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def xC6(self):
        """ Суточный отчет с гашением в буфер
            Команда: C6H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: C6H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def xC7(self):
        """ Распечатать отчет из буфера
            Команда: C7H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: C7H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def xC8(self):
        """ Запрос количества строк в буфере печати
            Команда: C8H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: C8H. Длина сообщения: 6 байт.
                Код ошибки (1 байт)
                Количество строк в буфере печати(2 байта)
                Количество напечатанных строк (2 байта)
        """
        raise NotImplementedError()

    # Not implemented
    def xC9(self):
        """ Получить строку буфера печати
            Команда: C9H. Длина сообщения: 7 байт.
                Пароль оператора (4 байта)
                Номер строки (2 байта)
            Ответ: C9H. Длина сообщения: 2 + n байт
                Код ошибки (1 байт)
                Данные строки (n байт)
        """
        raise NotImplementedError()

    def xCA(self):
        """ Очистить буфер печати
            Команда: CAH. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: CAH. Длина сообщения: 2 байта
                Код ошибки (1 байт)
        """
        command = 0xCA
        data, error, command = self.ask(command)
        return error

    # Not implemented
    def xCB(self):
        """ Печать штрих-кода средствами принтера
            Команда: CBH. Длина сообщения: 57 байт или менее.
                Пароль оператора (4 байта)
                Высота штрих-кода (1 байт) 1...255
                Ширина штриха (1 байт)
                Позиция HRI (1 байт):
                    «0» – Not printed;
                    «1» – Above the bar code;
                    «2» – Below the bar code;
                    «3» – Both above and below the bar code;
                Шрифт HRI (1 байт):
                    «0» – Standard Pitch at 15.2 CPI on receipt;
                    «1» – Compressed Pitch at 19 CPI on receipt;
                Тип штрих-кода (1 байт):
                    «0» – UPC-A;
                    «1» – UPC-E;
                    «2» – EAN13 (JAN-13);
                    «3» – EAN8 (JAN-8);
                    «4» – CODE39;
                    «5» – ITF;
                    «6» – CODABAR (NW-7);
                    «7» – CODE93;
                    «8» – CODE128;
                    «10» – PDF417;
                    «11» – GS1 DataBar Omnidirectional;
                    «12» – GS1 DataBar Truncated;
                    «13» – GS1 DataBar Limited;
                    «14» – GS1 DataBar Expanded;
                    «15» – GS1 DataBar Stacked;
                    «16» – GS1 DataBar Stacked Omnidirectional;
                    «17» – GS1 DataBar Expanded Stacked;
                Данные штрих-кода (1...48 байт)
            Ответ: CBH. Длина сообщения: 3 байта
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def xCC(self):
        """ Закрытие чека с возвратом КПК
            Команда: ССH. Длина сообщения: 71 или 40+Y байт.
                • Пароль оператора (4 байта)
                • Сумма наличных (5 байт) 0000000000...9999999999
                • Сумма типа оплаты 2 (5 байт) 0000000000...9999999999
                • Сумма типа оплаты 3 (5 байт) 0000000000...9999999999
                • Сумма типа оплаты 4 (5 байт) 0000000000...9999999999
                • Скидка/Надбавка(в случае отрицательного значения) в % на чек
                  от 0 до 99,99 % (2 байта со знаком) -9999...9999
                • Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                • Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                • Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                • Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                • Текст (40 или до Y байт)
            Ответ: ССH. Длина сообщения: 24 или до 255 байт.
                • Код ошибки (1 байт)
                • Порядковый номер оператора (1 байт) 1...30
                • Сдача (5 байт) 0000000000...9999999999
                • КПК и номер КПК (16 байт) текстовый формат
                  типа "12345678 #123456"
                • Веб-ссылка (до 231 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xCD(self):
        """ Чтение параметров активизации ЭКЛЗ
            Команда: СDH. Длина сообщения: 6 байт.
                Пароль НИ (4 байта)
                Номер активизации 1...255 (1 байт)
            Ответ:CDH. Длина сообщения: 12 байт.
                Код ошибки (1 байт)
                Дата активизации ДД-ММ-ГГ (3 байта)
                Регистрационный номер ЭКЛЗ (5 байт)
                Номер смены перед активизацией 0000...9999 (2 байта)
        """
        raise NotImplementedError()

    # Not implemented
    def xCE(self):
        """ Получить случайную последовательность
            Команда: СEH. Длина сообщения: 5 байт.
                • Пароль оператора (4 байта)
            Ответ: СEH. Длина сообщения: 19 байта.
                • Код ошибки (1 байт)
                • Порядковый номер оператора (1 байт) 1...30
                • Случайная последовательность (16 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xCF(self):
        """ Аутентификация
            Команда: СFH. Длина сообщения: 21 байт.
                • Пароль оператора (4 байта)
                • Код аутентификации (16 байт)
            Ответ: CFH. Длина сообщения: 3 байт.
                • Код ошибки (1 байт)
                • Порядковый номер оператора (1 байт) 1...30

            В коротком запросе состояния последний байт (зерезервированный):
            Бит 0: 1 – лоченая версия,
                   0 – нелоченая.
            Бит 1: 1 – аутентификация проведена,
                   0 – аутентификация не проведена.
            Бит 2: 1 – защита сработала,
                   0 – защита еще не сработала.
        """
        raise NotImplementedError()

    # Not implemented
    def xD0(self):
        """ Запрос состояния ФР IBM длинный
            Команда: D0H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: D0H. Длина сообщения: 44 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Текущая дата (3 байта) ДД-ММ-ГГ
                Текущее время (3 байта) ЧЧ-ММ-СС
                Номер последней закрытой смены (2 байта)
                Сквозной номер последнего закрытого документа (4 байта)
                Количество чеков продаж в текущей смене (2 байта)
                Количество чеков покупок текущей смене (2 байта)
                Количество чеков возврата продаж в текущей смене
                    (2 байта)
                Количество чеков чека возврата покупок продаж в текущей
                    смене (2 байта)
                Дата начала открытой смены (3 байта) ДД-ММ-ГГ
                Время начала открытой смены (3 байта) ЧЧ-ММ-СС
                Наличные в кассе (6 байт)
                Состояние принтера (8 байт)
                Флаги (1 байт)
                    Битовое поле (назначение бит):
                        0 – Сериализована (0 –нет, 1 – есть)
                        1 – Фискализирована (0 –нет, 1 – есть)
                        2 – Активизирована ЭКЛЗ (0 – нет, 1 – да)
                        3 – Смена открыта (0 – нет, 1 – есть)
                        4 – Смена открыта 24 часа закончились (0 – нет,
                            1 – есть)
        """
        raise NotImplementedError()

    # Not implemented
    def xD1(self):
        """ Запрос состояния ФР IBM короткий
            Команда: D1H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: D1H. Длина сообщения: 12 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Состояние принтера (8 байт)
                Флаги (1 байт)
                    Битовое поле (назначение бит):
                        0 – Буфер печати ККТ пуст (0 –нет, 1 – есть)
        """
        raise NotImplementedError()

    # Not implemented
    def xD2(self):
        """ Запрос короткого отчета по диапазону смен
            Команда: D2H. Длина сообщения: 9 байт.
                • Пароль НИ (4 байта)
                • Номер первой смены 0000...9999 (2 байта)
                • Номер последней смены 0000...9999 (2 байта)
            Ответ: D2H. Длина сообщения:38 байта.
                • Код ошибки (1 байт)
                • Номер первой смены 0000...9999 (2 байта)
                • Номер последней смены 0000...9999 (2 байта)
                • Дата первой смены ДД-ММ-ГГ (3 байта)
                • Дата последней смены ДД-ММ-ГГ (3 байта)
                • Сумма сменных итогов продаж (8 байт)
                • Сумма сменных итог покупок (6 байт)
                  При отсутствии данных в ФП FFh FFh FFh FFh FFh FFh
                • Сумма сменных возвратов продаж (6 байт)
                  При отсутствии данных в ФП FFh FFh FFh FFh FFh FFh
                • Сумма сменных возвратов покупок (6 байт)
                  При отсутствии данных в ФП FFh FFh FFh FFh FFh FFh
        """
        raise NotImplementedError()

    # Not implemented
    def xD3(self):
        """ Запрос короткого отчета по диапазону дат
            Команда: D3H. Длина сообщения:11 байт.
                • Пароль НИ (4 байта)
                • Дата первой смены ДД-ММ-ГГ (3 байта)
                • Дата последней смены ДД-ММ-ГГ (3 байта)
            Ответ: D3H. Длина сообщения: 38 байта.
                • Код ошибки (1 байт)
                • Номер первой смены 0000...9999 (2 байта)
                • Номер последней смены 0000...9999 (2 байта)
                • Дата первой смены ДД-ММ-ГГ (3 байта)
                • Дата последней смены ДД-ММ-ГГ (3 байта)
                • Сумма сменных итогов продаж (8 байт)
                • Сумма сменных итог покупок (6 байт)
                  При отсутствии данных в ФП FFh FFh FFh FFh FFh FFh
                • Сумма сменных возвратов продаж (6 байт)
                  При отсутствии данных в ФП FFh FFh FFh FFh FFh FFh
                • Сумма сменных возвратов покупок (6 байт)
                  При отсутствии данных в ФП FFh FFh FFh FFh FFh FFh
        """
        raise NotImplementedError()

    # Not implemented
    def xD4(self):
        """ Запрос состояния по коду 3 ЭКЛЗ
            Команда: D4H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: D4H. Длина сообщения: 4 байта.
                Код ошибки (1 байт)
                Байт состояния МФП (1 байт)
                Расширенной состояние активации act_status (1 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xD5(self):
        """ Запрос состояния по коду 4 ЭКЛЗ
            Команда: D5H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: D5H. Длина сообщения: 15 байт.
                Код ошибки (1 байт)
                Состояние связи с ОФД (1 байт) 0x00 – есть; 0xFF – нет
                Номер пакета в текущий сессии (1 байт) если связь есть
                Идентификатор текущей сессии (11 байт) если связь есть
        """
        raise NotImplementedError()

    # Not implemented
    def xDB(self):
        """ Запрос строки буфера отчета
            Команда: DBH. Длина сообщения: 7 байт.
                • Пароль системного администратора (4 байта)
                • Порядковый номер отчета в буфере (1 байт)
                • Порядковый номер строки отчета (1 байт)
            Ответ: DBH. Длина сообщения: 3-131 байта.
                • Код ошибки (1 байт)
                • Порядковый номер оператора (1 байт) 1...30
                • Бинарная строчка (0-128 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xDC(self):
        """ Очистка буфера отчетов
            Команда: DCH. Длина сообщения: 5 байт.
                • Пароль системного администратора (4 байта)
            Ответ: DCH. Длина сообщения: 3 байт.
                • Код ошибки (1 байт)
                • Порядковый номер оператора (1 байт) 1...30

            Строки передаются в таком виде как их надо передавать в принтер
            VKP80 (для Ярус-01) или PPU700 (для Ярус-02). Нумерация строк и
            отчетов начинается с 0. Следует подряд запрашивать все строки всех
            отчетов до получения ошибки 0xD1 – нет данных в буфере.
        """
        raise NotImplementedError()

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def xDD(self):
        """ Загрузка данных
            Команда: DDH. Длина сообщения: 71 байт.
                Пароль (4 байта)
                Тип данных (1 байт) 0 – данные для двумерного штрих-кода
                Порядковый номер блока данных (1 байт)
                Данные (64 байта)
            Ответ: DDH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def xDE(self):
        """ Печать многомерного штрих -кода
            Команда: DEH. Длина сообщения: 15 байт.
                Пароль (4 байта)
                Тип штрих-кода (1 байт)
                Длина данных штрих-кода (2 байта)
                Номер начального блока данных (1байт)
                Параметр 1 (1 байт)
                Параметр 2 (1 байт)
                Параметр 3 (1 байт)
                Параметр 4 (1 байт)
                Параметр 5 (1 байт)
                Выравнивание (1 байт)
            Ответ: DEH. Длина сообщения: 3 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30

            Примечание: тип штрих-кода смотрите в документации
        """
        raise NotImplementedError()

    # Not implemented
    def xDF(self):
        """ Операции с контрольной лентой
            Команда: DFH. Длина сообщения: 6 байт.
                • Пароль системного администратора (4 байта)
                • Тип операции (1 байт)
            Ответ: 0xDF. Длина сообщения: 3 байта.
                • Код ошибки (1 байт)
                • Порядковый номер оператора (1 байт) 1...30

            Типы операций:
                0x00 Печать контрольной ленты
                0x01 Очистка контрольной ленты
        """
        raise NotImplementedError()

    def xE0(self):
        """ Открыть смену
            Команда: E0H. Длина сообщения: 5байт.
                Пароль оператора (4 байта)
            Ответ: E0H. Длина сообщения: 2 байта.
                Порядковый номер оператора (1 байт) 1...30

            Примечание:
                Команда открывает смену в ФП и переводит ККТ в режим
                «Открытой смены».
        """
        command = 0xE0
        data, error, command = self.ask(command)
        operator = ord(data[0])
        return operator

    def xE1(self):
        """ Допечатать ПД
            Команда: E1H. Длина сообщения: 5байт.
                Пароль оператора (4 байта)
            Ответ: E1H. Длина сообщения: 2 байта.
                Порядковый номер оператора (1 байт) 1...30

            Примечание:
                Команда допечатывает ПД после нештатных ситуаций
                (обрыв бумаги, отключение питания и т.д.). Печать
                возобновляется с той же строки, на которой произошел
                останов печати в случае отключения питания или обрыва
                бумаги.

        """
        command = 0xE1
        data, error, command = self.ask(command)
        operator = ord(data[0])
        return operator

    def xE2(self):
        """ Открыть нефискальный документ
            Команда: E2H. Длина сообщения: 5байт.
                Пароль оператора (4 байта)
            Ответ: E2H. Длина сообщения: 3 байта.
                Код ошибки(1 байт)
                Порядковый номер оператора (1 байт) 1...30

            Примечание:
                Команда переводит ККТ в режим, позволяющий печатать
                произвольные текстовые строки.
        """
        command = 0xE2
        data, error, command = self.ask(command)
        operator = ord(data[0])
        return operator

    def xE3(self):
        """ Закрыть нефискальный документ
            Команда: E3H. Длина сообщения: 5байт.
                Пароль оператора (4 байта)
            Ответ: E3H. Длина сообщения: 3 байта.
                Код ошибки(1 байт)
                Порядковый номер оператора (1 байт) 1...30

            Примечание:
                Команда выводит ККТ в режим, позволяющий печатать
                произвольные текстовые строки.
        """
        command = 0xE3
        data, error, command = self.ask(command)
        operator = ord(data[0])
        return operator

    # Not implemented
    def xE4(self):
        """ Печать Реквизита
            Команда: E4H. Длина сообщения: 7-206 байт.
                Пароль оператора (4 байта)
                Номер реквизита (1 байт)
                Значение реквизита (1-200 байт)
            Ответ: E4H. Длина сообщения: 3 байта.
                Код ошибки(1 байт)
                Порядковый номер оператора (1 байт) 1...30

            Примечание:
                Команда печатает реквизит в открытом фискальном
                документе. Поле «значение реквизита» содержит
                текстовую информацию в кодировке win1251 с
                разделителем строк 0х0А. Может быть напечатано не
                более 4-х строк.
        """
        raise NotImplementedError()

    # Not implemented
    def xE5(self):
        """ Запрос состояния купюроприемника
            Команда: E5H. Длина сообщения: 5 байт.
                Пароль оператора (4 байта)
            Ответ: E5H. Длина сообщения: 6 байт.
                Код ошибки(1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Режим опроса купюроприемника (1 байт) 0 – не ведется,
                    1 – ведется
                Poll 1 (1 байт)
                Poll 2 (1 байт) – Байты, которые вернул купюроприемник
                    на последнюю команду
                Poll (подробности в описании протокола CCNet)
        """
        raise NotImplementedError()

    # Not implemented
    def xE6(self):
        """ Запрос регистров купюроприемника
            Команда: E6H. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Номер набора регистров (1 байт) 0 – количество купюр в
                    текущем чеке, 1 – количество купюр в текущей
                    смене, 2 – Общее количество принятых купюр.
            Ответ: E6H. Длина сообщения: 100 байт.
                Код ошибки(1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Номер набора регистров (1 байт)
                Количество купюр типа 0.23(4*24=96 байт) 24 4-х байтный
                    целых числа.
        """
        raise NotImplementedError()

    def xE7(self):
        """ Отчет по купюроприемнику
            Команда: E7H. Длина сообщения: 5 байт.
                Пароль администратора или системного администратора (4 байта)
            Ответ: E7H. Длина сообщения: 3 байта.
                Код ошибки(1 байт)
                Порядковый номер оператора (1 байт) 29, 30
        """
        command = 0xE7
        params = self.admin_password
        data, error, command = self.ask(command, params)
        operator = ord(data[0])
        return operator

    def xE8(self, tax_password):
        """ Оперативный отчет НИ
            Команда: E8H. Длина сообщения: 5 байт.
                Пароль НИ (4 байта)
            Ответ: E8H. Длина сообщения: 2 байта.
                Код ошибки(1 байт)
        """
        command = 0xE8
        params = tax_password
        data, error, command = self.ask(command, params)
        return error

    # Not implemented
    def xE9(self):
        """ Установка кода заказчика МФП (команда фазы производства)
            Команда: E9H. Длина сообщения: 6 байт.
                Пароль системного администратора (4 байта)
                Код заказчика МФП (1 байт)
            Ответ: E9H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xEA(self):
        """ Запрос кода разрешения активизации (команда отладочного комплекта)
            Команда: EAH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: EAH. Длина сообщения: 5 байт.
                Код ошибки (1 байт)
                Код разрешения активизации ( 3 байта) 000000 – 999999 BCD
        """
        raise NotImplementedError()

    # Not implemented
    def xEB(self):
        """ Подготовка активизации МФП
            Команда: EBH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: EBH. Длина сообщения: 48 байта.
                Код ошибки (1 байт)
                Дата (3 байт) ДД-ММ-ГГ
                Время (3 байта) ЧЧ-ММ-СС
                Заводской номер ККМ ( 12 байт, ASCII)
                ИНН ( 6 байт) 000000000000...999999999999
                РЕЗЕРВНОЕ ПОЛЕ ( 6 байт) BCD
                Номер последней закрытой смены в ККМ (2 байта ) 0000-9999
                Номер МФП (5 байт) 0000000000...9999999999
                Номер КПК (4 байта) 00000000...99999999
                Значение КПК (3 байта) 000000...999999
                Контрольный байт данных активизации ( 1 байт)
                Оставшееся количество попыток подготовки активизации ( 1 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xEC(self):
        """ Ввод кода разрешения активизации
            Команда: ECH. Длина сообщения: 8 байт.
                Пароль системного администратора (4 байта)
                Код разрешениея активизации ( 3 байта) BCD
            Ответ: ECH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Код ответа (1 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xED(self):
        """ Активизация МФП
            Команда: EDH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: EDH. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xEE(self):
        """ Запрос результатов команды подготовки активизации
            Команда: EEH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: EEH. Длина сообщения: 48 байта.
                Код ошибки (1 байт)
                Дата (3 байт) ДД-ММ-ГГ
                Время (3 байта) ЧЧ-ММ-СС
                Заводской номер ККМ ( 12 байт, ASCII)
                ИНН ( 6 байт) 000000000000...999999999999
                РЕЗЕРВНОЕ ПОЛЕ ( 6 байт) BCD
                Номер последней закрытой смены в ККМ (2 байта ) 0000-9999
                Номер МФП (5 байт) 0000000000...9999999999
                Номер КПК (4 байта) 00000000...99999999
                Значение КПК (3 байта) 000000...999999
                Контрольный байт данных активизации ( 1 байт)
                Оставшееся количество попыток подготовки активизации ( 1 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xEF(self):
        """ Запрос кода заказчика МФП
            Команда: EFH. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: EFH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Код заказчика МФП(1 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xF0(self):
        """ Управление заслонкой
            Команда: F0H. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Положение (1 байт) «1» – открыта; «0» – закрыта
            Ответ: F0H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def xF1(self):
        """ Выдать чек
            Команда: F1H. Длина сообщения: 6 байт.
                Пароль оператора (4 байта)
                Тип выдачи (1 байт)
                    1 - до срабатывания датчика на выходе из презентера
                        (захватить чек)
                    0 - не учитывать датчик (выброс чека)
            Ответ: F1H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
        """
        raise NotImplementedError()

    # Not implemented
    def xF2(self):
        """ Команда закрытия архива МФП
            Команда: F2H. Длина сообщения: 5 байт.
                Пароль системного администратора (4 байта)
            Ответ: F2H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xF3(self):
        """ Установить пароль ЦТО
            Команда: F3H. Длина сообщения: 9 байт.
                Пароль ЦТО (4 байта)
                Новый пароль ЦТО (4 байта)
            Ответ: F3H. Длина сообщения: 2 байта.
                Код ошибки (1 байт)
        """
        raise NotImplementedError()

    # Not implemented
    def xF7(self):
        """ Расширенный запрос
            Команда: F7H. Длина сообщения: 2+X байта.
                Тип запроса (1 байт) 0...255
                Данные (X 1 байт)
            Ответ: F7H. Длина сообщения: 2+Y 1 байт.
                Код ошибки (1 байт)
                Данные (Y 1 байт)

            Типы запросов см. в официальной документации.
        """
        raise NotImplementedError()

    def xFC(self):
        """ Получить тип устройства
            Команда: FCH. Длина сообщения: 1 байт.
            Ответ: FCH. Длина сообщения: (8+X) байт.
                Код ошибки (1 байт)
                Тип устройства (1 байт) 0...255
                Подтип устройства (1 байт) 0...255
                Версия протокола для данного устройства (1 байт) 0...255
                Подверсия протокола для данного устройства (1 байт) 0...255
                Модель устройства (1 байт) 0...255
                Язык устройства (1 байт):
                    «0» – русский;
                    «1» – английский;
                    «2» – эстонский;
                    «3» – казахский;
                    «4» – белорусский;
                    «5» – армянский;
                    «6» – грузинский;
                    «7» – украинский;
                    «8» – киргизский;
                    «9» – туркменский;
                    «10» – молдавский;
                Название устройства – строка символов в кодировке WIN1251.
                Количество байт, отводимое под название устройства,
                определяется в каждом конкретном случае
                самостоятельно разработчиками устройства (X байт)

            Примечание:
                Команда предназначена для идентификации устройств.
        """
        command = 0xFC

        data, error, command = self.ask(command, without_password=True)
        result = {
            'device_type': ord(data[0]),
            'device_subtype': ord(data[1]),
            'protocol_version': ord(data[2]),
            'protocol_subversion': ord(data[3]),
            'device_model': ord(data[4]),
            'device_language': sord(data[5]),
            'device_name': data[6:].decode(CODE_PAGE),
        }
        return result

    # Not implemented
    def xFD(self):
        """ Управление портом дополнительного внешнего устройства
            Команда: FDH. Длина сообщения: (6+X) байт.
                Пароль оператора (4 байта)
                Номер порта (1 байт) 0...255
                Строка команд, которые будут посланы в порт
                    дополнительного внешнего устройства (X байт).
            Ответ: FDH. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30

            Примечание:
                Дополнительное внешнее устройство – устройство, для
                функционирования которого не требуется формирования
                ответного сообщения.
        """
        # Наверное устарело
        raise NotImplementedError()

    def xFF01(self):
        """ Запрос статуса ФН
            Код команды FF01h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF01h Длина сообщения: 31 байт.
                Код ошибки: 1 байт
                Состояние фазы жизни: 1 байт
                    Бит 0 – проведена настройка ФН
                    Бит 1 – открыт фискальный режим
                    Бит 2 – закрыт фискальный режим
                    Бит 3 – закончена передача фискальных данных в ОФД
                Текущий документ: 1 байт
                    00h – нет открытого документа
                    01h – отчет о фискализации
                    02h – отчет об открытии смены
                    04h – кассовый чек
                    08h – отчет о закрытии смены
                    10h – отчет о закрытии фискального режима
                    11h – Бланк строкой отчетности
                    12h - Отчет об изменении параметров регистрации ККТ в
                          связи с заменой ФН
                    13h – Отчет об изменении параметров регистрации ККТ
                    14h – Кассовый чек коррекции
                    15h – БСО коррекции
                    17h – Отчет о текущем состоянии расчетов
                Данные документа: 1 байт
                    00 – нет данных документа
                    01 – получены данные документа
                Состояние смены: 1 байт
                    00 – смена закрыта
                    01 – смена открыта
                Флаги предупреждения: 1 байт
                Дата и время: 5 байт (документа или ФН?)
                Номер ФН: 16 байт ASCII
                Номер последнего ФД: 4 байта
        """
        command = chr(0xFF) + chr(0x01)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        doc_dict = {
            0x00: 'нет открытого документа',
            0x01: 'отчет о фискализации',
            0x02: 'отчет об открытии смены',
            0x04: 'кассовый чек',
            0x08: 'отчет о закрытии смены',
            0x10: 'отчет о закрытии фискального режима',
            0x11: 'Бланк строкой отчетности',
            0x12: ('Отчет об изменении параметров регистрации ККТ в '
                   'связи с заменой ФН'),
            0x13: 'Отчет об изменении параметров регистрации ККТ',
            0x14: 'Кассовый чек коррекции',
            0x15: 'БСО коррекции',
            0x17: 'Отчет о текущем состоянии расчетов',
        }
        return {
            'life_state': string2bits(data[0]),
            'current_doc': doc_dict.get(ord(data[1]), None),
            'doc_data': ord(data[2]),
            'workshift_is_open': bool(ord(data[3])),
            'warning_flags': string2bits(data[4]),
            'datetime': {
                'year': 2000 + ord(data[5]),
                'month': ord(data[6]),
                'day': ord(data[7]),
                'hour': ord(data[8]),
                'minute': ord(data[9]),
            },
            'fn_number': data[10:26],
            'last_doc': int4.unpack(data[26:30]),
        }

    def xFF02(self):
        """ Запрос номера ФН
            Код команды FF02h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF02 Длина сообщения: 17 байт.
                Код ошибки: 1 байт
                Номер ФН: 16 байт ASCII
        """
        command = chr(0xFF) + chr(0x02)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return data

    def xFF03(self):
        """ Запрос срока действия ФН
            Код команды FF03h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF03h Длина сообщения: 4 байт.
                Код ошибки: 1 байт
                Срок действия: 3 байта ГГ,ММ,ДД
        """
        command = chr(0xFF) + chr(0x03)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return {
            'year': 2000 + ord(data[0]),
            'month': ord(data[1]),
            'day': ord(data[2]),
        }

    def xFF04(self):
        """ Запрос версии ФН
            Код команды FF04h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF04h Длина сообщения: 18 байт.
                Код ошибки: 1 байт
                Строка версии программного обеспечения ФН: 16 байт ASCII
                Тип программного обеспечения ФН: 1 байт
                    0 – отладочная версия
                    1 – серийная версия
        """
        command = chr(0xFF) + chr(0x04)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return {
            'version': data[0:16],
            'is_serial': bool(ord(data[16])),
        }

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def xFF05(self):
        """ Начать отчет о регистрации ККТ
            Код команды FF05h. Длина сообщения: 7 байт.
                Пароль системного администратора: 4 байта
                Тип отчета: 1 байт
                    00 – Отчет о регистрации КТТ
                    01 – Отчет об изменении параметров регистрации ККТ, в
                         связи с заменой ФН
                    02 – Отчет об изменении параметров регистрации ККТ без
                         замены ФН
            Ответ: FF05h Длина сообщения: 1 байт.
                Код ошибки: 1 байт
        """
        raise NotImplementedError()

    # TODO: Реализовать в первую очередь для ШТРИХ-ФР-01Ф.
    def xFF06(self):
        """ Сформировать отчёт о регистрации ККТ
            Код команды FF06h. Длина сообщения: 40 байт.
                Пароль системного администратора: 4 байта
                ИНН : 12 байт ASCII
                Регистрационный номер ККТ: 20 байт ASCII
                Код налогообложения: 1 байт
                Режим работы: 1 байт
            Ответ: FF06h Длина сообщения: 9 байт.
                Код ошибки: 1 байт
                Номер ФД: 4 байта
                Фискальный признак: 4 байта
        """
        raise NotImplementedError()

    def xFF07(self, code):
        """ Сброс состояния ФН
            Код команды FF07h. Длина сообщения: 7 байт.
                Пароль системного администратора: 4 байта
                Код запроса: 1 байт
            Ответ: FF07h Длина сообщения: 1 байт.
                Код ошибки: 1 байт
        """
        command = chr(0xFF) + chr(0x07)
        params = self.admin_password + chr(code)
        data, error, command = self.ask(command, params)
        return error

    def xFF08(self):
        """ Отменить документ в ФН
            Код команды FF08h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF08h Длина сообщения: 1 байт.
                Код ошибки: 1 байт
        """
        command = chr(0xFF) + chr(0x08)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xFF09(self):
        """ Запрос итогов фискализации
            Код команды FF09h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF09h Длина сообщения: 48 байт.
                Код ошибки : 1 байт
                Дата и время: 5 байт DATE_TIME
                ИНН: 12 байт ASCII
                Регистрационный номер ККT: 20 байт ASCII
                Код налогообложения: 1 байт
                Режим работы: 1 байт
                Номер ФД: 4 байта
                Фискальный признак: 4 байта
        """
        command = chr(0xFF) + chr(0x09)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return {
            'datetime': {
                'year': 2000 + ord(data[0]),
                'month': ord(data[1]),
                'day': ord(data[2]),
                'hour': ord(data[3]),
                'minute': ord(data[4]),
            },
            'inn': data[5:17].replace(' ', ''),
            'reg_number': data[17:37].replace(' ', ''),
            'tax_code': ord(data[37]),
            'work_mode': ord(data[38]),
            'fd_number': int4.unpack(data[39:43]),
            'fiscal': int4.unpack(data[43:47]),
        }

    def xFF0A(self, number):
        """ Найти фискальный документ по номеру
            Код команды FF0Ah. Длина сообщения: 10 байт.
                Пароль системного администратора: 4 байта
                Номер фискального документа: 4 байта
            Ответ: FF0Аh Длина сообщения 3+N байт.
                Код ошибки: 1 байт
                Тип фискального документа: 1 байт
                Получена ли квитанция из ОФД: 1 байт
                    1- да
                    0 -нет
                Данные фискального документа в зависимости от типа
                документ: N байт
        """
        command = chr(0xFF) + chr(0x09)
        params = self.admin_password + int4.pack(number)
        data, error, command = self.ask(command, params)
        return {
            'doc_type': data[0],
            'ofd_check': bool(ord(data[1])),
            'data': data[2:],
        }

    # Not implemented
    def xFF0B(self):
        """ Открыть смену в ФН
            Код команды FF0Bh. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байт
            Ответ: FF0Bh Длина сообщения: 11 байт.
                Код ошибки: 1 байт
                Номер новой открытой смены: 2 байта
                Номер ФД :4 байта
                Фискальный признак: 4 байта
        """
        raise NotImplementedError()

    def xFF0C(self, tlv_dict):
        """ Передать произвольную TLV структуру
            Код команды FF0Ch. Длина сообщения: 6+N байт.
                Пароль системного администратора: 4 байта
                TLV Структура: N байт (мах 250 байт)
            Ответ: FF0Сh Длина сообщения: 1 байт.
                Код ошибки: 1 байт
        """
        command = chr(0xFF) + chr(0x0C)
        tlv = b''
        for key, value in tlv_dict.items():
            if isinstance(key, int):
                key = int2.pack(key)
            assert len(key) == 2, 'Key for TLV must be 2 chars.'
            value = force_bytes(value.encode(CODE_PAGE))
            vlength = int2.pack(len(value))
            tlv += key + vlength + value
        assert len(tlv) <= 250, 'Length TLV struct longer then 250 chars.'
        params = self.admin_password + tlv
        data, error, command = self.ask(command, params)
        return error

    # TODO: Тщательно протестировать и, возможно, улучшить.
    def xFF0D(self, operation, count, price, discount, increment,
              department, tax, barcode, text):
        """ Операция со скидками и надбавками
            Код команды FF0Dh. Длина сообщения: 254 байт.
                Пароль системного администратора: 4 байта ??? Оператора!!!
                Тип операции: 1 байт
                    1 – Приход,
                    2 – Возврат прихода,
                    3 – Расход,
                    4 – Возврат расхода
                Количество: 5 байт 0000000000...9999999999
                Цена: 5 байт 0000000000...9999999999
                Скидка: 5 байт 0000000000...9999999999
                Надбавка: 5 байт 0000000000...9999999999
                Номер отдела: 1 байт
                    0...16 – режим свободной продажи,
                    255 – режим продажи по коду товара
                Налог: 1 байт
                    Бит 1 «0» – нет, «1» – 1 налоговая группа
                    Бит 2 «0» – нет, «1» – 2 налоговая группа
                    Бит 3 «0» – нет, «1» – 3 налоговая группа
                    Бит 4 «0» – нет, «1» – 4 налоговая группа
                Штрих-код: 5 байт 000000000000...999999999999
                Текст: Текст: 220 байта строка - название товара и скидки
                    Примечание: если строка начинается символами \\ то она
                    передаётся на сервер ОФД но не печатается на кассе.
                    Названия товара и скидки должны заканчиваться
                    нулём (Нуль терминированные строки).
            Ответ: FF0Dh Длина сообщения: 1 байт.
            Код ошибки: 1 байт
        """
        count = count2integer(count)
        price = money2integer(price)
        discount = money2integer(discount)
        text = text.encode(CODE_PAGE)[:219]
        if text[-1] != chr(0x0):
            text += chr(0x0)

        command = chr(0xFF) + chr(0x0D)
        params = self.password + chr(operation)
        params += int5.pack(count)
        params += int5.pack(price)
        params += int5.pack(discount)
        params += int5.pack(increment)
        params += chr(department)
        params += chr(tax)
        params += int5.pack(barcode)
        params += text
        data, error, command = self.ask(command, params)
        return error

    def xFF16(self):
        """ Инициализация EEPROM
            Команда: FF16H. Длина сообщения: 2 байта.
            Ответ: FF16H. Длина сообщения: 3 байта.
                Код ошибки (1 байт)
            Примечание: для Белоруссии.
        """
        command = chr(0xFF) + chr(0x16)
        data, error, command = self.ask(command)
        return error

    # Not implemented
    def xFF1A(self):
        """ Запрос денежных регистров базы товаров
            Команда: FF1AH. Длина сообщения: 8 байт.
                Пароль оператора (4 байта)
                Код товара (2 байта) 1...9999
            Ответ: FF1AH. Длина сообщения: 52 байт.
                Код ошибки (1 байт)
                Порядковый номер оператора (1 байт) 1...30
                Содержимое регистра продаж по данному товару
                в чеке (6 байт)
                Содержимое регистра покупок по данному товару
                в чеке (6 байт)
                Содержимое регистра возврата продаж по данному товару
                в чеке (6 байт)
                Содержимое регистра возврата покупок по данному товару
                в чеке (6 байт)
                Содержимое регистра продаж по данному товару
                за смену (6 байт)
                Содержимое регистра покупок по данному товару
                за смену (6 байт)
                Содержимое регистра возврата продаж по данному товару
                за смену (6 байт)
                Содержимое регистра возврата покупок по данному товару
                за смену (6 байт)

            Примечание: в зависимости от модели ККТ (для параметра модели
            Бит 23, см. команду F7H); команда функционирует только если в
            таблице 1 установлено значение 1 в поле "ПЕЧАТЬ ОТЧЕТА ПО ТОВАРАМ".
        """
        raise NotImplementedError()

    def xFF34(self, code):
        """ Сформировать отчёт о перерегистрации ККТ
            Код команды FF34h. Длина сообщения: 7 байт.
                Пароль системного администратора: 4 байта
                Код причины перерегистрации: 1 байт
            Ответ: FF34h Длина сообщения: 9 байт.
                Код ошибки: 1 байт
                Номер ФД: 4 байта
                Фискальный признак: 4 байта
        """
        command = chr(0xFF) + chr(0x34)
        params = self.admin_password + chr(code)
        data, error, command = self.ask(command, params)
        return {
            'doc_number': int4.unpack(data[0:4]),
            'fiscal': int4.unpack(data[4:8]),
        }

    def xFF35(self):
        """ Начать формирование чека коррекции
            Код команды FF35h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF35h Длина сообщения: 1 байт.
                Код ошибки: 1 байт
        """
        command = chr(0xFF) + chr(0x35)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xFF36(self, total, typeop):
        """ Сформировать чек коррекции FF36H
            Код команды FF36h. Длина сообщения: 12 байт.
                Пароль системного администратора: 4 байта
                Итог чека: 5 байт 0000000000...9999999999
                Тип операции 1 байт
            Ответ: FF36h Длина сообщения: 11 байт.
                Код ошибки: 1 байт
                Номер чека: 2 байта
                Номер ФД: 4 байта
                Фискальный признак: 4 байт
        """
        command = chr(0xFF) + chr(0x36)
        params = self.admin_password + int5.pack(total) + chr(typeop)
        data, error, command = self.ask(command, params)
        return {
            'check_number': int2.unpack(data[0:2]),
            'doc_number': int4.unpack(data[2:6]),
            'fiscal': int4.unpack(data[6:10]),
        }

    def xFF37(self):
        """ Начать формирование отчёта о состоянии расчётов
            Код команды FF37h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF37h Длина сообщения: 1 байт.
                Код ошибки: 1 байт
        """
        command = chr(0xFF) + chr(0x37)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xFF38(self):
        """ Сформировать отчёт о состоянии расчётов
            Код команды FF38h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF38h Длина сообщения: 16 байт.
                Код ошибки: 1 байт
                Номер ФД: 4 байта
                Фискальный признак: 4 байта
                Количество неподтверждённых документов: 4 байта
                Дата первого неподтверждённого документа: 3 байта ГГ,ММ,ДД
        """
        command = chr(0xFF) + chr(0x38)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return {
            'number': int4.unpack(data[0:4]),
            'fiscal': int4.unpack(data[4:8]),
            'count': int4.unpack(data[8:12]),
            'first': {
                'year': ord(data[12]),
                'month': ord(data[13]),
                'day': ord(data[14]),
            },
        }

    def xFF39(self):
        """ Получить статус информационного обмена
            Код команды FF39h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF39h Длина сообщения: 14 байт.
                Код ошибки: 1 байт
                Статус информационного обмена: 1 байт
                    (0 – нет, 1 – да)
                    Бит 0 – транспортное соединение установлено
                    Бит 1 – есть сообщение для передачи в ОФД
                    Бит 2 – ожидание ответного сообщения (квитанции) от ОФД
                    Бит 3 – есть команда от ОФД
                    Бит 4 – изменились настройки соединения с ОФД
                    Бит 5 – ожидание ответа на команду от ОФД
                Состояние чтения сообщения: 1 байт
                    1 – да,
                    0 - нет
                Количество сообщений для ОФД: 2 байта
                Номер документа для ОФД первого в очереди: 4 байта
                Дата и время документа для ОФД первого в очереди: 5 байт
        """
        command = chr(0xFF) + chr(0x39)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        status = string2bits(data[0])
        status.reverse()
        status_dict = {
            'connection': bool(status[0]),
            'message': bool(status[1]),
            'wait_message': bool(status[2]),
            'command': bool(status[3]),
            'changed': bool(status[4]),
            'wait_command': bool(status[5]),
        }
        return {
            'status': status_dict,
            'is_read': bool(ord(data[1])),
            'messages': int2.unpack(data[2:4]),
            'first': {
                'number': int4.unpack(data[4:8]),
                'date': '20%(year)02d-%(month)02d-%(day)02d %(hour)02d:%(minute)02d' % {
                    'year': ord(data[8]),
                    'month': ord(data[9]),
                    'day': ord(data[10]),
                    'hour': ord(data[11]),
                    'minute': ord(data[12]),
                },
            },
        }

    def xFF3A(self, number):
        """ Запросить фискальный документ в TLV формате
            Код команды FF3Аh. Длина сообщения: 10 байт.
                Пароль системного администратора: 4 байта
                Номер фискального документа: 4 байта
            Ответ: FF3Аh Длина сообщения: 5 байт.
                Код ошибки: 1 байт
                Тип фискального документа: 2 байта STLV
                Длина фискального документа: 2 байта
        """
        command = chr(0xFF) + chr(0x3A)
        params = self.admin_password + int4.pack(number)
        data, error, command = self.ask(command, params)
        return {
            'type': int2.unpack(data[0:2]),
            'length': int2.unpack(data[2:4]),
        }

    def xFF3B(self):
        """ Чтение TLV фискального документа
            Код команды FF3Bh. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF3Bh Длина сообщения: 1+N байт.
                Код ошибки:1 байт
                TLV структура: N байт
        """
        command = chr(0xFF) + chr(0x3B)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return data

    def xFF3C(self, number):
        """ Запрос квитанции о получении данных в ОФД по номеру документа
            Код команды FF3Сh. Длина сообщения: 11 байт.
                Пароль системного администратора: 4 байта
                Номер фискального документа: 4 байта
            Ответ: FF3Сh Длина сообщения: 1+N байт.
                Код ошибки: 1 байт
                Квитанция: N байт
        """
        command = chr(0xFF) + chr(0x3C)
        params = self.admin_password + int4.pack(number)
        data, error, command = self.ask(command, params)
        return data

    def xFF3D(self):
        """ Начать закрытие фискального режима
            Код команды FF3Dh. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF3Dh Длина сообщения: 1 байт.
                Код ошибки: 1 байт
        """
        command = chr(0xFF) + chr(0x3D)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xFF3E(self):
        """ Закрыть фискальный режим
            Код команды FF3Eh. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF3Eh Длина сообщения: 9 байт.
                Код ошибки: 1 байт
                Номер ФД : 4 байта
                Фискальный признак: 4 байта
        """
        command = chr(0xFF) + chr(0x3E)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return {
            'number': int4.unpack(data[0:4]),
            'sign': int4.unpack(data[4:8]),
        }

    def xFF3F(self):
        """ Запрос количества ФД на которые нет квитанции
            Код команды FF3Fh. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF3Fh Длина сообщения: 3 байт.
                Код ошибки: 1 байт
                Количество неподтверждённых ФД: 2 байта
        """
        command = chr(0xFF) + chr(0x3F)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return int2.unpack(data[0:2])

    def xFF40(self):
        """ Запрос параметров текущей смены
            Код команды FF40h . Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF40h Длина сообщения: 6 байт.
                Код ошибки: 1 байт
                Состояние смены: 1 байт
                Номер смены : 2 байта
                Номер чека: 2 байта
        """
        command = chr(0xFF) + chr(0x41)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return {
            'status': ord(data[0]),
            'shift': int2.unpack(data[1:3]),
            'check': int2.unpack(data[3:5]),
        }

    def xFF41(self):
        """ Начать открытие смены
            Код команды FF41h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF41h Длина сообщения: 1 байт.
                Код ошибки: 1 байт
        """
        command = chr(0xFF) + chr(0x41)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    def xFF42(self):
        """ Начать закрытие смены
            Код команды FF42h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байта
            Ответ: FF42h Длина сообщения: 1 байт.
                Код ошибки: 1 байт
        """
        command = chr(0xFF) + chr(0x42)
        params = self.admin_password
        data, error, command = self.ask(command, params)
        return error

    # Not implemented
    def xFF43(self):
        """ Закрыть смену в ФН
            Код команды FF43h. Длина сообщения: 6 байт.
                Пароль системного администратора: 4 байт
            Ответ: FF43h Длина сообщения: 11 байт.
                Код ошибки: 1 байт
                Номер только что закрытой смены: 2 байта
                Номер ФД :4 байта
                Фискальный признак: 4 байта
        """
        raise NotImplementedError()

    # Not implemented
    def xFF44(self):
        """ Операция со скидками, надбавками и налогом
            Код команды FF44h. Длина сообщения: 254 байт.
                Пароль системного администратора: 4 байта
                Тип операции: 1 байт
                    1 – Приход,
                    2 – Возврат прихода,
                    3 – Расход,
                    4 – Возврат расхода
                Количество: 5 байт 0000000000...9999999999
                Цена: 5 байт 0000000000...9999999999
                Скидка: 5 байт 0000000000...9999999999
                Надбавка: 5 байт 0000000000...9999999999
                Налог: 5 байт 0000000000...9999999999
                Номер отдела: 1 байт
                    0...16 – режим свободной продажи,
                    255 – режим продажи по коду товара
                Налог: 1 байт
                    Бит 1 «0» – нет, «1» – 1 налоговая группа
                    Бит 2 «0» – нет, «1» – 2 налоговая группа
                    Бит 3 «0» – нет, «1» – 3 налоговая группа
                    Бит 4 «0» – нет, «1» – 4 налоговая группа
                Штрих-код: 5 байт 000000000000...999999999999
                Текст: 215 байта строка - название товара и скидки
                    Примечание: если строка начинается символами \\ то она
                    передаётся на сервер ОФД но не печатается на кассе.
                    Названия товара и скидки должны заканчиваться
                    нулём (Нуль терминированные строки).
                    Примечание: налог является справочной информацией и
                    передаётся извне в случае,
                    когда касса не может его рассчитать сама.
            Ответ: FF43h Длина сообщения: 1 байт.
                Код ошибки: 1 байт
        """
        raise NotImplementedError()

    # Not implemented
    def xFF45(self):
        """ Закрытие чека расширенное вариант No2
            Код команды FF45h. Длина сообщения: 131 байт.
                Пароль системного администратора: 4 байта
                Сумма наличных (5 байт) 0000000000...9999999999
                Сумма типа оплаты 2 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 3 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 4 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 5 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 6 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 7 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 8 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 9 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 10 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 11 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 12 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 13 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 14 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 15 (5 байт) 0000000000...9999999999
                Сумма типа оплаты 16 (5 байт) 0000000000...9999999999
                Скидка/Надбавка(в случае отрицательного значения) в %
                на чек от 0 до 99,99 % (2 байта со знаком) -9999...9999
                Налог 1 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 2 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 3 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Налог 4 (1 байт) «0» – нет, «1»...«4» – налоговая группа
                Система налогообложения (1 байт)
                Текст (40 байт)
            Ответ: FF45h Длина сообщения: 6 байт.
                Код ошибки: 1 байт
                Сдача ( 5 байт) 0000000000...9999999999
        """
        raise NotImplementedError()
