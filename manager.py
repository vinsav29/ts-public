import logging
from eeprom.eeprom import SystemInfo
import usb as usblib
from calendar import timegm
from time import time, gmtime, localtime, strftime, sleep, mktime, clock_settime, CLOCK_REALTIME
from struct import *
from threading import Thread, Lock, Event
from queue import Queue
from linuxtools import *
import nmea
from utils import validate_ipv4, validate_mac, config_loggers
from copy import deepcopy
from glcd_py.screen import *
import json
from datetime import timedelta
from collections import OrderedDict


class Settings:
    """
    Класс для хранения настроек вебсервера
    """
    time_src = 0
    pps_src = 0
    # watchdog = 3600 * 24 * 30 * 12  # 1 year
    logger = None

    gpsd_data = {}
    eeprom = None
    # pps_sync_src = 0
    # time_sync_src = 0
    main = {
        'sync_src': '1',
        'date': 'n/a',
        'time': 'n/a',
        'timejump': '15',
        'tz': '+3',
        'tz_kv': '+0',
        'tz_rs': '+0',
        'sat_system': 'gnss',
        'ext_sync_src': 'gnss422',
        'reciever': 'irz7',
        'internal': dict(name='ГНСС внутренний',
                         speed='115200',
                         size='8',
                         parity='N',
                         stopbit='1'),
        'gnss422': dict(name='ГНСС RS-422',
                        speed='115200',
                        size='8',
                        parity='N',
                        stopbit='1'),
        'gnss232': dict(name='ГНСС RS-232',
                        speed='115200',
                        size='8',
                        parity='N',
                        stopbit='1'),
    }
    net = {
        'lan1': dict(name='lan1',
                     label='ЛВС 1',
                     ip='192.168.0.101',
                     netmask='255.255.255.0',
                     gateway='192.168.0.1',
                     status='DOWN',
                     mac='00:00:00:00:00:00',
                     listen='1',
                     speed='0'),
        'lan2': dict(name='lan2',
                     label='ЛВС 2',
                     ip='192.168.0.102',
                     netmask='255.255.255.0',
                     gateway='192.168.0.1',
                     status='DOWN',
                     mac='00:00:00:00:00:00',
                     listen='1',
                     speed='0'),
    }
    config = {
        'lifetime': 60,
        'password': '',
        'new_password': '',
        'confirm_password': '',
        'devid': '',
        'devsn': '',
        'devfd': '',
        'mcufw': '',
        'devhv': '',
        'uptime': ['0', '0', '0', '0'],
        'optime': ['0', '0']
    }
    journal = [
        'all',
        'gpsd',
        'ntpd',
    ]
    header = {
        'serial': '',
        'devname': 'Часовая станция',
    }
    mcu = {
        'pps_timeout': 5,
        'connect_timeout': 1800,
        'reset_hold': 1,
        'gps_reset': 0,
        'pps_reset': 0,
        'mcu_reset': 0
    }
    pps_info = {
        'aif_state': 0,
        'aop_state': 0,
        'aop_delta': '',
        'aif_delta': 0,
        'aif_sum': 0,
        'dac': 0
    }
    gps_default = dict(time='-',
                       date='-',
                       latitude='-',
                       longitude='-',
                       speed='-',
                       altitude='-',
                       mode=-1,
                       status=-1,
                       sats_change=True,
                       sat_list=[],
                       sats='-',
                       sats_valid='-',
                       dt=''
                       )

    def __init__(self) -> None:
        """
        Инициализация настроек дефолтными значениями
        """
        self.update(default_settings)

    def read_eeprom(self):
        self.eeprom = SystemInfo(self.logger).eeprom_parsing().copy()

        self.header['serial'] = self.eeprom['CarrierSerialNumber']
        self.config['devid'] = 'БС 683'
        self.config['devsn'] = self.eeprom['CarrierSerialNumber']
        self.config['devfd'] = self.eeprom['CarrierDate']
        self.config['mcufw'] = '1.0'
        self.config['devhv'] = self.eeprom['CarrierVersion']

        self.logger.error(str(self.eeprom))

    def reset_gpsd_data(self):
        self.gpsd_data = self.gps_default.copy()

    def get_config(self) -> dict:
        """
        Заполняет новыми значениями словарь с параметрами для отправки на
        веб страницу conf.html

        :return: словарь с параметрами
        """
        uptimesec = read_uptime('/proc/uptime')  # '32572'
        delta = timedelta(seconds=uptimesec)  # '5 days, 18:34:21' or '12:23:34'
        delta_list = str(delta).split()
        hhmmss_list = delta_list[-1].split(':')  # ['18','34','21']
        days = '0'
        if len(delta_list) == 3:
            days = delta_list[0]
        self.config['uptime'] = list(days) + hhmmss_list  # ['5', '18','34','21'] or ['0', '12','23','34']

        optimesec = read_ini_file().get('optime') or 0
        optimesec = int(optimesec) + uptimesec
        hh = optimesec // 3600  # 452
        mm = (optimesec % 3600) // 60  # 6
        self.config['optime'] = ['%d' % hh, '%02d' % mm]  # ['452', '06']

        return self.config

    def save_to_file(self, func):
        """
        Декоратор, сохраняет текущие значения настроек в файл settings.json,
        после выполнения функции

        :param func: декорируемая функция
        :return: результат выполнения функции
        """

        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            obj = dict(main=deepcopy(settings.main),
                       net=deepcopy(settings.net),
                       config=deepcopy(settings.config),
                       header=deepcopy(settings.header)
                       )
            try:
                with open(linuxtools.SETTINGS_FILE, 'w') as file:
                    json.dump(obj, file)
            except Exception as err:
                self.logger.error('Не удалось сохранить настройки!')
                self.logger.debug(err)

            return result

        return wrapper

    # @save_to_file
    # def get_main(self):
    #     # get timezone from linux
    #     ltime = localtime()
    #     tz = int(strftime("%z", ltime)[:-2])
    #     self.main['tz'] = '%+d' % tz
    #     self.main['date'] = strftime("%Y-%m-%d", ltime)
    #     self.main['time'] = strftime("%T", ltime)
    #     return self.main

    def update(self, obj: dict) -> None:
        """
        Обновить значения в настройках

        :param obj: словарь с новыми значенями
        :return: None
        """
        self.__dict__.update(obj)

    def reset(self) -> bool:
        """
        Выполняет сброс локальных настроек и настроек вебсервера

        :return: true, false
        """
        self.logger.error('Сброс к заводским настройкам...')

        # reset
        obj = dict(main=deepcopy(default_settings['main']),
                   config=deepcopy(default_settings['config']),
                   header=deepcopy(default_settings['header']),
                   )
        settings.__dict__.update(obj)
        self.logger.debug(settings)

        self.logger.error('Перезапуск веб-сервера...')
        if not reset_webserver_config():
            return False

        return True


class USB:
    """
    Класс управления устройством УПШ
    """

    def __init__(self) -> None:
        """
        Инициализация класса
        """
        self.logger = None
        self.device = None
        self.queue = Queue()
        self.lock = Lock()
        self.event = Event()
        self.handle = None

    def init(self) -> bool:
        """
        Выполняет поиск и конфигурацию устройства УПШ

        :return: false - если устройство не найдено или при ошибке
        конфигурации, true - если устройство готово к работе
        """
        self.device = usblib.core.find(idVendor=0x0483,
                                       idProduct=0x572B,
                                       )
        if not self.device:
            self.logger.error("Устройство USB не обнаружено")
            sleep(5)
            return False
        self.logger.debug(self.device)

        driver_list = []
        try:
            for interface in (0, 1, 2):
                if self.device.is_kernel_driver_active(interface=interface):
                    self.device.detach_kernel_driver(interface=interface)
                    driver_list.append(interface)
                    self.logger.debug("Деактивация USB интерфейса %s", str(interface))
        except usblib.core.USBError as err:
            self.logger.debug("Ошибка деактивации: %s", str(err))

        try:
            self.device.set_configuration()
        except usblib.core.USBError as err:
            self.logger.error("Ошибка конфигурации USB: %s", str(err))
            usblib.util.dispose_resources(self.device)  # release usb device
            sleep(1)
            return False

        try:
            for interface in driver_list:
                self.device.attach_kernel_driver(interface=interface)
                self.logger.debug("Активация USB интерфейса %s", str(interface))
        except usblib.core.USBError as err:
            self.logger.debug("Ошибка конфигурации USB: %s", str(err))

        # self.get_net_cfg()
        # self.queue.put('lan1')  # first ACK unblock logo timeout
        # self.queue.put('lan2')
        # self.queue.put('tz')
        # self.queue.put('sysinfo')
        # self.queue.put('modinfo')
        # self.queue.put('carinfo')
        self.logger.error("Обнаружено устройство USB!")
        return True

    @staticmethod
    def send_gps_mux(func):
        """
        Декоратор, посылает по УПШ команду настройки мультплексора выбора
        источника внешней синхронизации

        :param func: декорируемая функция
        :return: результат выполнения функции
        """

        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            usb.queue.put('gps_mux')
            return result

        return wrapper


settings = Settings()
lcd = LCD(settings=settings)
usb = USB()


class Manager(object):
    """
    Класс для управления вебсервером
    """
    global settings
    global lcd
    global usb
    logger = None
    reset_webserver = False
    gnss_synced = False
    status = {
        'n/a': 0,
        'ok': 1,
        'err': 2,
        'ip': 3
    }

    def __init__(self, logger: logging.Logger, args: list) -> None:
        """
        Инициализация параметров класса, загрузка настроек, запуск программных потоков

        :param logger: ссылка на базовый логгер
        :param args: лист с аргументами командной строки (при запуске из командной строки)
        """
        for obj in (self, settings, usb, lcd):
            obj.logger = logger

        self.config_logger(args)

        usb.init()

        try:
            with open(SETTINGS_FILE, 'r') as file:
                saved_settings = json.load(file, object_hook=dict)
                settings.update(saved_settings)
                self.logger.error('Загружены сохраненные настройки')
        except Exception as e:
            self.logger.error('Не удалось загрузить сохраненные настройки!')
            self.logger.debug(e)

        set_timezone(settings.main['tz'])

        # LAN init
        self.get_net_cfg()
        # get eeprom data, optime, uptime
        settings.read_eeprom()
        settings.get_config()

        # USB threads
        thread_rd = Thread(name="Thread USB read",
                           target=self.usb_reader,
                           daemon=True,
                           )
        thread_wr = Thread(name="Thread USB write",
                           target=self.usb_writer,
                           daemon=True,
                           )
        thread_rd.start()
        thread_wr.start()

        thread_uptime = Thread(name="Thread uptime",
                               target=self.uptime_worker,
                               daemon=True,
                               )
        thread_uptime.start()

        thread_tz = Thread(name="Thread send TZ",
                           target=self.tz_worker,
                           daemon=True,
                           )
        thread_tz.start()

        # gnss config
        source = settings.main['ext_sync_src']
        self.set_ext_sync_source(source)      # вызывается в save_gnss()
        # self.set_sat_system(device='/dev/ttyS1',
        #                     speed=settings.main[source]['speed'],
        #                     system=settings.main['sat_system'],
        #                     reciever=settings.main['reciever'])
        self.save_gnss(source=source,
                       new_speed=settings.main[source]['speed'],
                       sat_system=settings.main['sat_system'],
                       reciever=settings.main['reciever'])

        # get version struct from MK
        self.get_n_struct = 4
        usb.queue.put('get')

    @staticmethod
    def uptime_worker() -> None:
        """
        Поток, каждые timeout секунд копирует в рабочую директорию файл /proc/uptime

        :return: None
        """
        event = Event()
        while True:
            event.wait(timeout=3600)
            run_cmd("cp /proc/uptime %s/uptime" % WORKING_DIR)
            settings.get_config()   # read and save uptime, optime to settings.config

    def config_logger(self, argv: list) -> None:
        """
        Вызывает функцию конфигурации логгирования

        :param argv: лист с аргументами командной строки (при запуске из командной строки)
        :return: None
        """
        log_level = read_ini_file()['logginglevel']
        if not log_level:
            log_level = 'info'

        try:
            log_level = argv[1]
        except IndexError:
            pass

        config_loggers(self.logger, log_level)

    @settings.save_to_file
    def change_net_cfg(self,
                       lan: str,
                       ip: str,
                       netmask: str,
                       gateway: str,
                       listen: str) -> str:
        """
        Изменяет настройки сетевого интерфейса, перезапускает сетевые службы

        :param lan: имя сетевого интерфейса
        :param ip: адрес
        :param netmask: маска сети
        :param gateway: шлюз
        :param listen: 1 - разрешить вещание по ntp, 0 - запретить
        :return: сообщение об успешности изменения
        """
        if not validate_ipv4(ip, netmask, gateway):
            msg = 'Ошибка ввода адреса!'
            self.logger.error(msg)
            return msg

        dev_id = settings.net[lan]['name']

        if not add_network(dev_id, ip, netmask, gateway):
            return 'Ошибка создания сетевого интерфейса!'

        self.logger.debug('Изменен файл %s.network' % dev_id)
        settings.net[lan]['ip'] = ip
        settings.net[lan]['netmask'] = netmask
        settings.net[lan]['gateway'] = gateway
        run_cmd('systemctl restart systemd-networkd')
        # TODO: add checking systemd-networkd status
        sleep(0.3)

        # TODO: add option: don't change listen ntp
        if listen is None:
            listen = settings.net[lan]['listen']

        if add_listen_ntp(lan=lan,
                          listen=listen,
                          ip=ip,
                          sync_src=settings.main['sync_src'],
                          gnss_synced=self.gnss_synced):
            settings.net[lan]['listen'] = listen
            self.logger.debug(systemctl('restart', 'ntp'))
            if listen == '1':
                self.logger.error(
                    'Разрешена работа службы времени на сетевом интерфейсе %s' % settings.net[lan]['label'])
            else:
                self.logger.error(
                    'Запрещена работа службы времени на сетевом интерфейсе %s' % settings.net[lan]['label'])
        else:
            return "Ошибка настройки разрешений службы времени на сетевом интерфейсе %s!" % settings.net[lan]['label']

        self.logger.error("Настройки %s изменены!" % settings.net[lan]['label'])
        return ''

    @settings.save_to_file
    def get_net_cfg(self, lans: tuple = ('lan1', 'lan2')) -> dict:
        """
        Вызывает функцию чтения параметров сети, в случае ошибки - выставляет
        дефолтные настройки

        :param lans: кортеж с именами сетевых интерфейсов
        :return: словарь с настройками сети для всех интерфейсов
        """
        for lan in lans:
            try:
                ip, netmask, gateway, mac, status, speed = get_network(device=settings.net[lan]['name'])
                add_listen_ntp(lan=lan,
                               listen=settings.net[lan]['listen'],
                               ip=ip,
                               sync_src=settings.main['sync_src'],
                               gnss_synced=self.gnss_synced)
            except TypeError:
                self.logger.error('Ошибка: устройство %s не обнаружено' % settings.net[lan]['label'])
                self.logger.error('Загружена дефолтная конфигурация %s' % settings.net[lan]['label'])
                self.logger.debug('Загружены дефолтные настройки: ', default_settings['net'][lan])
                self.change_net_cfg(lan,
                                    default_settings['net'][lan]['ip'],
                                    default_settings['net'][lan]['netmask'],
                                    default_settings['net'][lan]['gateway'],
                                    default_settings['net'][lan]['listen']
                                    )
                continue

            settings.net[lan]['ip'] = ip
            settings.net[lan]['netmask'] = netmask
            settings.net[lan]['gateway'] = gateway
            settings.net[lan]['mac'] = mac
            settings.net[lan]['status'] = status
            settings.net[lan]['speed'] = speed

        self.logger.debug(settings.net)
        return settings.net

    @settings.save_to_file
    def get_main(self):
        """
        Заполняет новыми значениями словарь с параметрами для отправки на
        веб страницу main.html

        :return: словарь с параметрами
        """
        ltime = localtime()
        tz = int(strftime("%z", ltime)[:-2])
        settings.main['tz'] = '%+d' % tz
        settings.main['date'] = strftime("%Y-%m-%d", ltime)
        settings.main['time'] = strftime("%T", ltime)
        return settings.main

    def save_time(self, date: str, time: str):
        """
        Изменяет системную дату и время при синхронизации от внутреннего источника

        :param date: дата
        :param time: время
        :return: сообщение об успешности изменения
        """
        if settings.main['sync_src'] == str(GNSS_SRC_NONE) and date and time:
            cmdout = run_cmd(command='timedatectl set-time "%s %s"' % (date, time))
            if cmdout == '':
                msg = "Установлены дата и время: %s %s" % (date, time)
            else:
                self.logger.debug(cmdout)
                msg = "Ошибка установки даты и времени!"
            return msg
        elif settings.main['sync_src'] in map(str, (GNSS_SRC_INTERNAL, GNSS_SRC_EXT_RS422, GNSS_SRC_EXT_RS232)):
            return 'Установка возможна только при синхронизации от внутреннего источника'
        return None

    @settings.save_to_file
    def save_time_settings(self,
                           timejump: str,
                           tz: str,
                           tz_kv: str,
                           tz_rs: str) -> str:
        """
        Сохраняет настройки параметров времени

        :param timejump: максимальная перестройка времени
        :param tz: часовой пояс системы
        :param tz_kv: часовой пояс выносного индикатора КВ
        :param tz_rs: часовой пояс выносного индикатора RS-485
        :return: сообщение об успешности изменения
        """
        if timejump:
            seconds = str(int(timejump) * 60)
            if do_with_file(path='/etc/ntp.conf',
                            action='replace',
                            labels=['tinker panic'],
                            inserts=[seconds],
                            positions=[2]):
                settings.main['timejump'] = timejump
                self.logger.error("Установлена макс. перестройка времени %s мин." % timejump)
            else:
                self.logger.error("Ошибка: макс. перестройка времени не установлена!")

        if tz is None or tz_kv is None or tz_rs is None:
            return "Ошибка настройки часовых поясов!"

        settings.main['tz_kv'] = tz_kv
        settings.main['tz_rs'] = tz_rs

        result = set_timezone(tz)
        if result == '':
            self.logger.error("Настройки часовых поясов изменены:\n"
                              "Часовая станция %s\n"
                              "Индикатор КВ %s\n"
                              "Индикатор выносной RS-485 %s",
                              tz, settings.main['tz_kv'], settings.main['tz_rs'])
            msg = 'Параметры времени изменены!'
        else:
            self.logger.debug(result)
            msg = "Ошибка настройки часовых поясов!"

        return msg

    @settings.save_to_file
    @nmea.gpsd_stop_start
    def save_gnss(self,
                  source: str,
                  new_speed: str,
                  sat_system: str,
                  reciever: str) -> str:
        """
        Сохраняет настройки параметров ГНСС
        :param source: источник внешней синхронизации 'internal', 'rs422', 'rs232'
        :param new_speed: скорость uart
        :param sat_system: система ГНСС
        :param reciever: модель приемника ГНСС. 'irz7' - ИРЗ МНП-7.

        :return: сообщение об успешности изменения
        """
        if source in ('internal', 'gnss232', 'gnss422'):
            self.set_ext_sync_source(source)
        else:
            return 'Ошибка выбора источника внешней синхронизации!'

        if new_speed != settings.main[source]['speed']:
            new_speed = nmea.set_speed(device='/dev/ttyS1',
                                       speed=settings.main[source]['speed'],
                                       new_speed=new_speed)
            if new_speed:
                settings.main[source]['speed'] = new_speed

        sat_sys_changed = self.set_sat_system(device='/dev/ttyS1',
                                              speed=settings.main[source]['speed'],
                                              system=sat_system,
                                              reciever=reciever)

        if sat_sys_changed:
            return 'Настройки ГНСС изменены!'
        else:
            return 'Ошибка настройки ГНСС!'

    @restart_ntp
    def set_sync_source(self, sync_src: str):
        """
        Изменяет источник синхронизации в настройках, вызывает функцию конфигурации службы ntp

        :param: sync_src: '0' - внутренний, '1' - внешний источник синхронизации
        :return: сообщение об успешности изменения
        """
        if sync_src in ('0', '1'):
            source = ntp_config(sync=int(sync_src))
            if source is None:
                msg = "Ошибка! Источник синхронизации не изменен"
            else:
                msg = "Выбран источник синхронизации: %s" % source
                settings.main['sync_src'] = sync_src

                # если синхронизации со спутником еще не было, то при переключении
                # источника синхронизации на внешний - отключаем раздачу времени
                if not self.gnss_synced:
                    for lan in ('lan1', 'lan2'):
                        add_listen_ntp(lan,
                                       listen=settings.net[lan]['listen'],
                                       ip=settings.net[lan]['ip'],
                                       sync_src=settings.main['sync_src'],
                                       gnss_synced=self.gnss_synced)

                # TODO: при переключении на внешний источник установить время спутника
                if sync_src == '1' and settings.gpsd_data.get('dt') and settings.gpsd_data.get('dt') != '-':
                    clock_settime(CLOCK_REALTIME, mktime(settings.gpsd_data['dt']))
            return msg
        return None

    @restart_ntp
    @usb.send_gps_mux
    @nmea.gpsd_stop_start
    def set_ext_sync_source(self, source: str):
        """
        Изменяет тип источника внешней синхронизации

        :param source: 'internal', 'rs422', 'rs232'
        :return: сообщение об успешности изменения
        """
        if source:
            msg = "Выбран источник внешней синхронизации: %s" % settings.main[source]['name']
            settings.main['ext_sync_src'] = source
            # TODO: init sat
        else:
            msg = "Ошибка! Источник внешней синхронизации не изменен"
        return msg

    def set_sat_system(self, device: str,
                       system: str,
                       speed: str,
                       reciever: str) -> bool:
        """
        Изменяет тип используемой системы ГНСС

        :param device: путь к устройству связи с приемником - 'dev/ttyS1'
        :param system: тип системы - 'all', 'gnss', 'gps'
        :param speed: '1200', '2400', '4800', '9600', '19200', '38400', '57600', '115200'
        :param reciever: модель приемника - 'irz7'
        :return: true, false
        """
        if reciever == 'irz7':
            sat_system, selected_speed = nmea.set_satellites(device=device,
                                                             speed=speed,
                                                             system=system)
            # TODO: add reciever types
        else:
            sat_system, selected_speed = None, None

        if selected_speed:
            source = settings.main['ext_sync_src']
            if selected_speed != settings.main[source]['speed']:
                settings.main[source]['speed'] = selected_speed

        if sat_system:
            settings.main['sat_system'] = sat_system

            self.logger.error("Выбор навигационной системы: %s" % nmea.mode[sat_system])
            return True
        else:
            self.logger.error("Ошибка изменения навигационной системы!")
            return False

    @settings.save_to_file
    def set_lifetime(self, lifetime: str) -> str:
        """
        Устанавливает таймаут бездействия вебсервера

        :param lifetime: значение таймаута в минутах
        :return: сообщение об успешности изменения
        """
        try:
            int(lifetime)
        except ValueError:
            return "Ошибка ввода таймаута бездействия: %s" % lifetime
        else:
            settings.config['lifetime'] = lifetime
            return "Таймаут бездействия равен %s мин." % lifetime

    @settings.save_to_file
    def set_devname(self, devname: str):
        """
        Изменяет название устройства

        :param devname: новое название
        :return: сообщение об успешности изменения
        """
        if devname:
            settings.header['devname'] = devname
            return "Название изменено на: %s" % devname
        return None

    def usb_reader(self) -> None:
        """
        Поток, принимает пакеты УПШ, вызывает функцию распаковки пакета,
        помещает id ответа в очередь УПШ

        :return: None
        """
        while True:
            if not usb.device:
                usb.init()
                continue
            try:
                # print('READ: ', perf_counter())
                packet = usb.device.read(endpoint=0x81,
                                         size_or_buffer=64,
                                         timeout=100)
                # print('STOP: ', perf_counter(), '\n')
                self.logger.debug("READ: %s", str(packet))
                responses = self.unpacking(packet)
                if responses:
                    for response in responses:
                        usb.queue.put(response)
            except usblib.core.USBTimeoutError as err:
                # data not found
                self.logger.debug("RD timeout")
            except usblib.core.USBError as err:
                self.logger.error("Ошибка чтения USB: %s", str(err))

                if '[Errno 19] No such device' in str(err):
                    usb.device = None
                else:
                    try:
                        status = usblib.control.get_status(usb.device, usb.device[0][0, 0][0])
                        if status:
                            usblib.control.clear_feature(usb.device, 0, recipient=0x81)
                        else:
                            usb.device = None
                    except Exception as err:
                        self.logger.error("Ошибка clear_feature USB: %s", str(err))

                sleep(5)
            except Exception as err:
                self.logger.debug('USB reader error: %s', str(err))

    def usb_writer(self) -> None:
        """
        Поток, получает из очереди УПШ id ответной структуры и вызывает функцию
        формирования пакета, результат передается в УПШ

        :return: None
        """
        while True:
            if not usb.device:
                usb.init()
                continue

            response = usb.queue.get()
            if not response:
                continue

            name = response
            if name not in self.pack_fmt:
                usb.queue.task_done()
                continue

            self.logger.debug("SEND: %s", response)
            packet = self.packing(name=response)
            if packet is not None:
                try:
                    usb.device.write(1, packet)
                    # if response == 'get':
                    #     print('send: ', packet)
                except usblib.core.USBTimeoutError as err:
                    self.logger.debug('SEND timeout')
                except usblib.core.USBError as err:
                    self.logger.error("Ошибка записи USB: %s", str(err))

                    if '[Errno 19] No such device' in str(err):
                        usb.device = None
                    else:
                        try:
                            status = usblib.control.get_status(usb.device, usb.device[0][0, 0][1])
                            if status:
                                usblib.control.clear_feature(usb.device, 0, recipient=0x1)
                            else:
                                usb.device = None
                        except Exception as err:
                            self.logger.error("Ошибка clear_feature USB: %s", str(err))

                    sleep(5)
                except Exception as err:
                    self.logger.debug('USB writer error: %s', str(err))
            usb.queue.task_done()  # queue feature to finish .get()

    # output data struct
    pack_fmt = OrderedDict()
    pack_fmt['void'] = ('<H', 0)
    pack_fmt['get'] = ('<HH', 1)
    pack_fmt['time'] = ('<HQQQQ', 2)
    pack_fmt['status'] = ('<HBB', 3)
    pack_fmt['gps_mux'] = ('<HB', 4)
    pack_fmt['gps_wdog'] = ('<HLLL', 5)
    pack_fmt['reset'] = ('<HBBB', 6)
    pack_fmt['lcd'] = ("<H488s", 7)

    get_n_struct = 0

    def packing(self, name: str = 'void') -> bytes:
        """
        Формирует пакет для передачи по УПШ

        :param name: лист с id передаваемой структуры
        :return: пакет в формате bytes
        """
        if name == 'void':
            return pack(self.pack_fmt[name][0], self.pack_fmt[name][1])

        elif name == 'get':
            return pack(self.pack_fmt[name][0], self.pack_fmt[name][1],
                        self.get_n_struct)

        elif name == 'time':
            tz = int(settings.main['tz'])
            tz_kv = int(settings.main['tz_kv'])
            tz_rs = int(settings.main['tz_rs'])
            # utc = timegm(gmtime())
            utc = round(time.time())
            # print(strftime("%T", localtime()))
            # self.logger.debug("PACKING time: %d %d %d %d",
            #                   utc, utc + tz * 3600, utc + tz_kv * 3600, utc + tz_rs * 3600)
            return pack(self.pack_fmt[name][0], self.pack_fmt[name][1],
                        utc,
                        utc + tz * 3600,
                        utc + tz_kv * 3600,
                        utc + tz_rs * 3600)

        elif name == 'status':
            gnss_status = settings.gpsd_data.get('status')  # NMEA: 'V' = 0, 'A' = 1, 'D' = 2
            if gnss_status not in (-1, 0, 1, 2):
                gnss_status = -1
            gnss_status += 1                        # USB : NONE = 0 'V' = 1, 'A' = 2
            if gnss_status > 2:
                gnss_status = 2

            # print(gnss_status)
            ntp_mode = int(settings.main['sync_src'])   # PC:           LOCAL = 0, GNSS = 1
            ntp_mode += 1                               # USB: NONE = 0, LOCAL = 1, GNSS = 2
            self.logger.debug("PACKING status: %d", gnss_status)
            return pack(self.pack_fmt[name][0], self.pack_fmt[name][1],
                        gnss_status, ntp_mode)

        elif name == 'gps_mux':
            source = GNSS_SRC_NONE
            if settings.main['sync_src'] != GNSS_SRC_NONE:
                if settings.main['ext_sync_src'] == 'internal':
                    source = GNSS_SRC_INTERNAL
                elif settings.main['ext_sync_src'] == 'gnss232':
                    source = GNSS_SRC_EXT_RS232
                elif settings.main['ext_sync_src'] == 'gnss422':
                    source = GNSS_SRC_EXT_RS422
            self.logger.debug("PACKING gps_mux: %d", source)
            return pack(self.pack_fmt[name][0], self.pack_fmt[name][1],
                        source)

        elif name == 'gps_wdog':
            return pack(self.pack_fmt[name][0], self.pack_fmt[name][1],
                        settings.mcu['pps_timeout'],
                        settings.mcu['connect_timeout'],
                        settings.mcu['reset_hold'])

        elif name == 'reset':
            return pack(self.pack_fmt[name][0], self.pack_fmt[name][1],
                        settings.mcu['gps_reset'],
                        settings.mcu['pps_reset'],
                        settings.mcu['mcu_reset'])

        elif name == 'lcd':
            return pack(self.pack_fmt[name][0], self.pack_fmt[name][1],
                        lcd.show_screen())

    def unpacking(self, packet):
        """
        Выполняет распаковку пакета, принятого по УПШ

        :param packet: пакет в формате bytes
        :return: лист с id ответной структуры
        """
        try:
            idx = list(packet)[0]
        except Exception as err:
            return ['']

        response = []
        if idx == 0:
            return ['void']
        elif idx == 1:
            command, n_struct = list(unpack("<HH", packet))
            self.logger.debug("UNPACKING get: %s", list(self.pack_fmt)[n_struct])
            return [list(self.pack_fmt)[n_struct]]

        elif idx == 2:
            command, aif_state, aop_state, aop_delta, aif_delta, aif_sum, dac = list(unpack("<HiiiiQH", packet))
            self.logger.error("UNPACKING pps_info: %d %d %d %d %d %d",
                              aif_state, aop_state, aop_delta, aif_delta, aif_sum, dac)
            settings.pps_info['aif_state'] = aif_state
            settings.pps_info['aop_state'] = aop_state
            settings.pps_info['aop_delta'] = aop_delta
            settings.pps_info['aif_delta'] = aif_delta
            settings.pps_info['aif_sum'] = aif_sum
            settings.pps_info['dac'] = dac
            return ['']

        elif idx == 3:
            command, rising, falling, pressed, clamping, timers = list(unpack("<HHHHHH", packet))
            self.logger.debug("UNPACKING buttons_info: %d %d %d %d %d\n",
                              rising, falling, pressed, clamping, timers)
            changes = lcd.change_screen(rising, falling, clamping, timers)

            params = lcd.get_unsaved_params()
            if params:
                print('GET UNSAVED PARAMS')
                label = lcd.get_screen_label()

                if label == 'Дата и время':
                    dt = datetime.strptime('-'.join(params[0] + params[1]), '%H-%M-%S-%d-%m-%y')
                    msg = self.save_time(date=dt.strftime("%Y-%m-%d"), time=dt.strftime("%T"))
                    print(msg)

                elif label == 'Часовые пояса':
                    # tz = '%+d' % int(params[0][0])
                    # tz_kv = '%+d' % int(params[1][0])
                    # tz_rs = '%+d' % int(params[2][0])
                    tz, tz_kv, tz_rs = ['%+d' % int(p[0]) for p in params]
                    msg = self.save_time_settings(None, tz, tz_kv, tz_rs)
                    print(msg)

                elif label == settings.net['lan1']['label'] or label == settings.net['lan2']['label']:
                    lan = 'lan1' if label == settings.net['lan1']['label'] else 'lan2'
                    print(params)
                    ip, sn, gw, _, (ntp,) = params
                    listen = '1' if ntp == CP_YES else '0'
                    err_msg = self.change_net_cfg(lan=lan,
                                                  ip='.'.join(ip),
                                                  netmask='.'.join(sn),
                                                  gateway='.'.join(gw),
                                                  listen=listen,
                                                  )
                    if err_msg:
                        self.logger.error(err_msg)

                elif label == 'Синхронизация':
                    sync_src, ext_sync_src, sat_system = [p[0] for p in params]
                    # sync_src = params[0][0]
                    if sync_src != settings.main['sync_src']:
                        msg = self.set_sync_source(sync_src)
                        if msg:
                            self.logger.error(msg)

                    # ext_sync_src = params[1][0]
                    if ext_sync_src != settings.main['ext_sync_src']:
                        msg = self.set_ext_sync_source(ext_sync_src)
                        self.logger.error(msg)

                    # sat_system = params[2][0]
                    if sat_system != settings.main['sat_system']:
                        source = settings.main['ext_sync_src']
                        self.set_sat_system(device='/dev/ttyS1',
                                            system=sat_system,
                                            speed=settings.main[source]['speed'],
                                            reciever=settings.main['reciever'])

                elif label == 'Обслуживание':
                    reset, reboot, poweroff = [p[0] for p in params]
                    # TODO: включить сброс, перезагрузку и выключение
                    if reset:
                        self.logger.error('Перезапуск веб-сервера...')
                        print('РАСКОММЕНТИРОВАТЬ СБРОС!')
                        # reset_webserver_config()

                    if reboot:
                        print('РАСКОММЕНТИРОВАТЬ РЕБУТ!')
                        self.logger.error('Перезагрузка...')
                        # run_cmd('reboot')

                    if poweroff:
                        print('РАСКОММЕНТИРОВАТЬ ВЫКЛ!')
                        self.logger.error('Выключение...')
                        # run_cmd('poweroff')

            if not changes:
                return None
            else:
                return ['lcd']

        elif idx == 4:
            command, model, _range, date, mods = list(unpack("<H16s16s16s2s", packet))
            self.logger.error("UNPACKING version: %s %s %s %s",
                              model.decode().rstrip('\x00'),
                              _range.decode().rstrip('\x00'),
                              date.decode().rstrip('\x00'),
                              mods.decode().rstrip('\x00'))
            return ['']

        else:
            return ['err']

    def tz_worker(self):
        while True:
            if not usb.device:
                sleep(0.25)
                # usb.event.wait(timeout=0.25)
                continue
            # print(strftime("%T", localtime()), run_cmd('timedatectl'))
            # usb.queue.put('time')
            # lcd.change_screen(rising=0, falling=0, clamping=0, timers=0x8)
            # usb.queue.put('lcd')
            # sleep(1)

            diff = time.time() % 1
            if diff < 0.1:
                usb.queue.put('time')
                # lcd.change_screen(rising=0, falling=0, clamping=0, timers=0x8)
                # usb.queue.put('lcd')
                self.get_n_struct = 4
                usb.queue.put('get')
            sleep(1 - diff)
            # usb.event.wait(timeout=1 - diff)
            # else:
            #     # print(diff)
            #     sleep(1 - diff)

            # lcd.change_screen(rising=0, falling=0, clamping=0, timers=0x8)
            # usb.queue.put('lcd')
            # self.get_n_struct = 2
            # usb.queue.put('get')
            # usb.event.wait(timeout=0.25)
