import sys
import subprocess
from copy import deepcopy
from os import path, remove
from configparser import ConfigParser

WORKING_DIR = path.dirname(path.abspath(__file__))
sys.path.insert(1, "%s/site-packages" % WORKING_DIR)

from werkzeug.datastructures import ImmutableDict

TIME_SRC_NONE = 0
TIME_SRC_INTERNAL = 1
TIME_SRC_GNSS = 2

PPS_SRC_NONE = 0
PPS_SRC_INTERNAL = 1
PPS_SRC_GNSS = 2

GNSS_SRC_NONE = 0
GNSS_SRC_INTERNAL = 1
GNSS_SRC_EXT_RS422 = 2
GNSS_SRC_EXT_RS232 = 3
sync_sources = ['Внутренний', 'ГНСС внутренний', 'ГНСС RS-422', 'ГНСС RS-232']

default_settings_mutable = {
    'time_src': 0,
    'pps_src': 0,
    'watchdog': 3600 * 24 * 30 * 12,  # 1 year,

    'logger': None,
    'gpsd_data': {},
    'eeprom': None,
    'pps_sync_src': 0,
    'time_sync_src': 0,

    'main': {'sync_src': '1',
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
             },
    'net': {'lan1': {'name': 'lan1',
                     'label': 'ЛВС 1',
                     'ip': '192.168.0.101',
                     'netmask': '255.255.255.0',
                     'gateway': '192.168.0.1',
                     'status': 'DOWN',
                     'mac': '00:00:00:00:00:00',
                     'listen': '1',
                     'speed': '0'},
            'lan2': {'name': 'lan2',
                     'label': 'ЛВС 2',
                     'ip': '192.168.0.102',
                     'netmask': '255.255.255.0',
                     'gateway': '192.168.0.1',
                     'status': 'DOWN',
                     'mac': '00:00:00:00:00:00',
                     'listen': '1',
                     'speed': '0'}
            },
    'config': {'lifetime': 60,
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
               },
    'journal': ['all', 'gpsd', 'ntpd'],
    'header': {'serial': '',
               'devname': 'Часовая станция'},
    'gnss_info': {'status': 0,
                  'satcnt': 0,
                  'time': '',
                  'latdeg': 0,
                  'latint': 0,
                  'latfrac': 0,
                  'latns': 0,
                  'londeg': 0,
                  'lonint': 0,
                  'lonfrac': 0,
                  'lonew': 0},
    'pps_info': {'aif_state': 0,
                 'aop_state': 0,
                 'aop_delta': '',
                 'aif_delta': 0,
                 'aif_sum': 0,
                 'dac': 0},
}

default_settings = ImmutableDict(default_settings_mutable)
del default_settings_mutable

timezones = {
    '-12': 'Etc/GMT+12',
    '-11': 'Pacific/Midway',
    '-10': 'Pacific/Honolulu',
    '-9': 'America/Anchorage',
    '-8': 'America/Los_Angeles',
    '-7': 'America/Denver',
    '-6': 'America/Chicago',
    '-5': 'America/Cayman',
    '-4': 'Atlantic/Bermuda',
    '-3': 'America/Argentina/Buenos_Aires',
    '-2': 'Atlantic/South_Georgia',
    '-1': 'Atlantic/Cape_Verde',
    '+0': 'UTC',
    '+1': 'Europe/Rome',
    '+2': 'Europe/Kaliningrad',
    '+3': 'Europe/Moscow',
    '+4': 'Europe/Samara',
    '+5': 'Asia/Yekaterinburg',
    '+6': 'Asia/Omsk',
    '+7': 'Asia/Novosibirsk',
    '+8': 'Asia/Irkutsk',
    '+9': 'Asia/Yakutsk',
    '+10': 'Asia/Vladivostok',
    '+11': 'Asia/Magadan',
    '+12': 'Asia/Kamchatka',
    '+13': 'Pacific/Apia',
    '+14': 'Pacific/Kiritimati',
}


def restart_ntp(func):
    """
    Декоратор, делает перезапуск службы ntp после выполнения функции

    :param func: декорируемая функция, после которой требуется перезапуск
    :return: результат выполнения функции
    """

    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        systemctl('restart', 'ntp')
        return result

    return wrapper


def read_uptime(filepath: str = None) -> int:
    """
    Читает значение uptime из файла 'filepath'

    :param filepath: файл с uptime
    :return: значение uptime
    """
    if not filepath:
        filepath = "%s/uptime" % WORKING_DIR

    uptime = 0
    if path.exists(filepath):
        with open(filepath, 'r') as file:
            timers = file.readline().split()
            try:
                uptime = int(float(timers[0]))
            except Exception as e:
                print(e)
    return uptime


def save_optime() -> None:
    """
    Вычисляет и сохраняет наработку в 'ini' файл

    :return: None
    """
    uptime = read_uptime()
    if not uptime:
        return None

    remove("%s/uptime" % WORKING_DIR)

    old_uptime = read_ini_file()['optime']
    try:
        old_uptime = int(old_uptime)
    except ValueError:
        old_uptime = 0

    write_ini_file({'optime': old_uptime + uptime})


def get_network(device: str):
    """
    Запрашивает у системы параметры сетевого интерфейса

    :param device: имя сетевого интерфейса
    :return: кортеж с настройками сети
    """
    status = run_cmd(command="ip -br a show %s |" % device + "awk '{print $2}'").rstrip('\n')

    if status == 'UP':
        inet4 = run_cmd(command="ip -br a show %s |" % device + "awk '{print $3}'").rstrip('\n')
        gateway_list = run_cmd(
            command="ip route | awk '/%s/'" % device + " | awk '/default via/{print $3}'").splitlines()
        mac = run_cmd(
            command="ip a show %s |" % device + " grep ether | awk '{print $2}'").rstrip('\n')
        speed = run_cmd(command='cat /sys/class/net/%s/speed' % device).rstrip('\n')

    else:
        try:
            with open('/etc/systemd/network/{}.network'.format(device), 'r') as file:
                inet4 = None
                gateway_list = []
                for line in file:
                    if 'Address=' in line:
                        inet4 = line[len('Address='):]
                    if 'Gateway=' in line:
                        gateway_list.append(line[len('Gateway='):])
                mac = '00:00:00:00:00:00'
                speed = '0'
        except FileNotFoundError as e:
            # print('set default: ', default_settings['net'][lan])
            # self.change_net_cfg(lan,
            #                     default_settings['net'][lan]['ip'],
            #                     default_settings['net'][lan]['netmask'],
            #                     default_settings['net'][lan]['gateway'],
            #                     default_settings['net'][lan]['listen']
            #                     )
            # continue
            print(e)
            return None
        except Exception as e:
            print(e)
            return None

    if not inet4 or not gateway_list:
        return None

    ip = inet4.split('/')[0]
    cidr = inet4.split('/')[1]
    netmask = '.'.join(
        [str((0xFFFFFFFF << (32 - int(cidr)) >> i) & 0xFF) for i in [24, 16, 8, 0]])
    gateway = gateway_list[0].rstrip('\n')
    return ip, netmask, gateway, mac, status, speed


def set_timezone(tz: str) -> str:
    """
    Выполняет команду изменения системного часового пояса

    :param tz: часовой пояс в текстовом формате
    :return: результат выполнения
    """
    return run_cmd(command='timedatectl set-timezone "%s"' % timezones[tz])


def reset_webserver_config() -> bool:
    """
    Выполняет возврат к дефолтным настройкам вебсервера

    :return:
    """
    for file in ('%s/settings.json' % WORKING_DIR,
                 '%s/hashsum' % WORKING_DIR):
        if path.exists(file):
            run_cmd('rm %s' % file)
    for lan in ('lan1', 'lan2'):
        add_network(name=default_settings['net'][lan]['name'],
                    ip=default_settings['net'][lan]['ip'],
                    netmask=default_settings['net'][lan]['netmask'],
                    gateway=default_settings['net'][lan]['gateway'],
                    )
        add_listen_ntp(lan=lan,
                       listen=default_settings['net'][lan]['listen'],
                       ip=default_settings['net'][lan]['ip'],
                       sync_src=default_settings['main']['sync_src'],
                       gnss_synced=False
                       )

    run_cmd('bash %s/cfg/services_config.sh' % WORKING_DIR)

    run_cmd('systemctl restart systemd-networkd')
    run_cmd('systemctl restart ntp')
    return True


def run_cmd(command: str) -> str:
    """
    Выполняет команду в консоли linux

    :param command: текст команды
    :return: результат выполнения
    """
    cmdout = subprocess.Popen(command,
                              shell=True,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, )
    stdout, stderr = cmdout.communicate()
    return stdout.decode('utf-8')


def add_network(name: str,
                ip: str,
                netmask: str,
                gateway: str) -> bool:
    """
    Конфигурирует сетевой интерфейс

    :param name: имя сетевого интерфейса
    :param ip: адрес
    :param netmask: маска сети
    :param gateway: шлюз
    :return: 'true' - конфигурация успешна, 'false' - нет
    """
    try:
        with open('/etc/systemd/network/%s.network' % name, 'w') as file:
            # 255.255.255.0 -> 24
            cidr = str(sum([bin(int(x)).count('1') for x in netmask.split('.')]))

            # '192.168.000.001' -> '192.168.0.1'
            ip = '.'.join([str(int(n)) for n in ip.split('.')])
            gateway = '.'.join([str(int(n)) for n in gateway.split('.')])

            file.write(
                '[Match]\n'
                'Name=%s\n\n' % name +

                '[Network]\n'
                'Address=%s/%s\n' % (ip, cidr) +
                'Gateway=%s\n' % gateway
            )
        return True
    except Exception:
        return False


def add_listen_ntp(lan: str,
                   listen: str,
                   ip: str,
                   sync_src: str,
                   gnss_synced: bool) -> bool:
    """
    Редактирует строки с параметрами 'listen' в конфигурационном файле ntp.conf

    :param lan: имя сетевого интерфейса
    :param listen: 1 - разрешить вещание, 0 - запретить
    :param ip: адрес сетевого интерфейса
    :param sync_src: '0' - внутренний, '1' - внешний источник синхронизации
    :param gnss_synced: True - если была успешная синхронизация со спутником
    :return: true, false
    """
    # print(lan, listen, ip)
    # set listen ip adr
    if not do_with_file(path="/etc/ntp.conf",
                        action='replace',
                        labels=[lan],
                        inserts=[ip],
                        positions=[2]
                        ):
        return False

    if listen == '1':
        if sync_src == '0' or gnss_synced is True:  # разрешить раздачу времени при внутреннем источнике
            action = 'uncomment'  # синхронизации. при внешнем источнике - разрешить,
        else:  # только если была успешная синхронизация со спутником.
            action = 'comment'

    elif listen == '0':
        action = 'comment'
    else:
        return False

    if not do_with_file(path="/etc/ntp.conf",
                        action=action,
                        labels=[lan]
                        ):
        return False

    return True


def stty(device='/dev/ttyS1', speed='115200', size='8', stopbit='1', parity='N') -> str:
    cmd = "stty -F "

    if device in ('/dev/ttyS0', '/dev/ttyS1'):
        cmd += device + ' '
    else:
        return 'Ошибка параметра device'

    if speed in ('9600', '19200', '38400', '57600', '115200'):
        cmd += speed
    else:
        return 'Ошибка параметра speed'

    if int(size) in range(5, 9):
        cmd += ' cs' + size
    else:
        return 'Ошибка параметра size'

    if stopbit == '1':
        cmd += ' -cstopb'
    elif stopbit == '2':
        cmd += ' cstopb'
    else:
        return 'Ошибка параметра stopbit'

    if parity == 'N':
        cmd += ' -parenb'
    elif parity == 'E':
        cmd += ' -parodd'
    elif parity == 'O':
        cmd += ' parodd'
    else:
        return 'Ошибка параметра parity'

    # run_cmd(command='stty -F /dev/ttyS1 115200 cs8 -cstopb -parenb')
    # logging.debug(cmd)
    return run_cmd(command=cmd)


def gnss_config(source: str,
                speed: str,
                size: str,
                stopbit: str,
                parity: str) -> str:
    if source == 'internal':
        pass
    elif source == 'gnss422':
        return stty(device='/dev/ttyS1',
                    speed=speed,
                    size=size,
                    stopbit=stopbit,
                    parity=parity
                    )
    elif source == 'gnss232':
        return stty(device='/dev/ttyS1',
                    speed=speed,
                    size=size,
                    stopbit=stopbit,
                    parity=parity
                    )


def read_journalctl(output='short', since='yesterday', until='now', services: list = None) -> str:
    """
    Получает логи системного журнала для указанных служб

    :param output: формат логов
    :param since: дата начала логов
    :param until: дата конца логов
    :param services: имена служб
    :return: текст логов
    """
    if not services:
        return ''
    cmd = 'journalctl --no-pager'
    units = []
    for srv in services:
        if srv == 'all':
            units.append('webserver')
            units.append('time-station')
            units.append('systemd-networkd')
        if srv == 'gpsd':
            units.append('gpsd.service')
            units.append('gpsd.socket')
        if srv == 'ntpd':
            units.append('ntp')
    for unit in units:
        cmd += ' -u ' + unit
    cmd = ' '.join([cmd, '-o', output, '--since', since, '--until', until])
    return run_cmd(command=cmd)


def systemctl(action: str, service: str):
    """
    Выполняет действие с системной службой

    :param action: действие
    :param service: имя службы
    :return: результат выполнения команды при запросе статуса службы,
    None - в остальных случаях
    """
    if service == 'gpsd':
        if action == 'start':
            run_cmd(command='systemctl start gpsd.socket')
        elif action == 'stop':
            run_cmd(command='systemctl stop gpsd.socket')
            run_cmd(command='systemctl stop gpsd')
        elif action == 'restart':
            run_cmd(command='systemctl stop gpsd.socket')
            run_cmd(command='systemctl stop gpsd')
            run_cmd(command='systemctl start gpsd.socket')
            run_cmd(command='systemctl start gpsd')
    elif action == 'status':
        return run_cmd(command='systemctl status {s}'.format(s=service))
    else:
        run_cmd(command='systemctl {} {}'.format(action, service))
    return None


# TODO: service status checking
def is_service_active(*services) -> bool:
    """
    Проверяет работают ли системные службы

    :param services: имена системных служб
    :return: 'True', 'False'
    """
    for service in services:
        status = run_cmd(command="systemctl list-units --state active | egrep '%s'" % service)
        if status == '':
            return False
    return True


peer_fields = dict(name='',
                   status_id='',
                   status='не используется',
                   stratum='',
                   offset='',
                   jitter='')
peers_default = {
    '.LCL.': peer_fields.copy(),
    '.NMEA.': peer_fields.copy(),
    '.GPPS.': peer_fields.copy(),
    '.LPPS.': peer_fields.copy(),
}
peers_default['.LCL.']['name'] = 'Внутренний (время)'
peers_default['.NMEA.']['name'] = 'ГНСС (время)'
peers_default['.GPPS.']['name'] = 'ГНСС (секундная метка)'
peers_default['.LPPS.']['name'] = 'Внутренний (секундная метка)'

selection_fields = {
    '': '',
    'x': 'отклонен',
    '.': 'отклонен',
    '-': 'отклонен',
    '+': 'достоверный',
    '#': 'достоверный',
    '*': 'источник времени',
    'o': 'источник секундной метки'
}


def ntp_peers():
    """
    Выполняет команду "ntpq -p" для запроса пиров службы ntp

    :return: словарь с пирами и их параметрами или None в случае ошибки
    """
    cmdout = run_cmd(command="ntpq -p")
    peers = deepcopy(peers_default)

    if 'remote' not in cmdout:
        return peers

    for line in cmdout.splitlines()[2:]:
        labels = line.split()
        if len(labels) < 10:
            continue
        refid = labels[1]
        if refid in peers:
            peers[refid]['stratum'] = labels[2]
            peers[refid]['offset'] = labels[8]
            peers[refid]['jitter'] = labels[9]
            status_id = labels[0][0]
            if status_id in selection_fields:
                peers[refid]['status_id'] = status_id
                peers[refid]['status'] = selection_fields[status_id]
    #         print(peers[refid])
    # print('\n')
    return peers


def ntp_config(sync: int):
    """
    Изменение конфиг. файла службы ntp, в зависимости от выбранного источника синхр.

    :param sync: источник синхронизации
    :return: наименование выбранного источника синхр. или None в случае ошибки
    """
    if sync == 0:
        action = 'comment'
    else:
        action = 'uncomment'

    if do_with_file(path="/etc/ntp.conf",
                    action=action,
                    labels=['GPS_server', 'GPS_fudge', 'PPS_server', 'PPS_fudge'],
                    ):
        # run_cmd('systemctl restart ntp')
        return ['Внутренний', 'Внешний (ГНСС)'][sync]
    return None


def replace_in_line(line: str, string: str, position: int) -> str:
    """
    Замена текста в строке

    :param line: строка
    :param string: текст для замены
    :param position: позиция замены
    :return: новая строка
    """
    # remove line if string is None
    if not string:
        return ''

    lst = line.split()
    lst.pop(position)
    lst.insert(position, string)
    return ' '.join(lst) + '\n'


# TODO: rename to file_operation
def do_with_file(path: str,
                 action: str,
                 labels: list,
                 inserts: list = None,
                 positions: list = None) -> bool:
    """
    Выполняет различные операции над текстовым файлом

    :param path: путь к файлу
    :param action: действие (comment, uncomment, remove, replace)
    :param labels: лист с метками для поиска в файле
    :param inserts: лист значений для вставки в файл
    :param positions: лист позиций для вставки значений
    :return: 'True' - если действие успешно, 'False' - если нет
    """
    try:
        with open(path, mode='r+') as file:
            newtext = []
            for line in file.readlines():
                for label in labels:
                    if label in line:
                        idx = labels.index(label)

                        if action == 'comment':
                            if not line.startswith('#'):
                                line = '#' + line
                        elif action == 'uncomment':
                            line = line.strip('# ')
                        elif action == 'remove':
                            line = ''
                        elif action == 'replace':
                            line = replace_in_line(line, inserts.pop(idx), positions.pop(idx))

                        labels.pop(idx)
                        break
                newtext.append(line)

            # write new text to file
            file.truncate(0)
            file.seek(0)
            file.writelines(newtext)
            return True
    except Exception as e:
        # logging.getLogger('app').debug(e)
        return False


def read_ini_file() -> dict:
    """
    Читает 'ini' файл

    :return: словарь с настройками конфигурации
    """
    if not path.exists('%s/AfterInstallConfig.ini' % WORKING_DIR):
        return dict()
    config = ConfigParser()
    config.read('%s/AfterInstallConfig.ini' % WORKING_DIR)
    # dictionary = {}
    # for field in fields:
    #     dictionary[field] = config['DEFAULT'].get(field)
    # return dictionary
    return config['DEFAULT']


def write_ini_file(dictionary: dict) -> bool:
    """
    Записывает изменения конфигурации в ini файл

    :param dictionary: словарь с параметрами
    :return: 'True' - если запись успешна, 'False' - если нет
    """
    if not path.exists('./AfterInstallConfig.ini'):
        return False
    config = ConfigParser()
    config.read('./AfterInstallConfig.ini')

    for key, value in dictionary.items():
        dictionary[key] = str(value)

    config['DEFAULT'].update(dictionary)
    with open('./AfterInstallConfig.ini', 'w') as configfile:
        config.write(configfile)
    return True


if __name__ == "__main__":
    print(get_network('lan2'))
    # d = dict(Uptime=1)
    # write_ini_file(d)
    # WORKING_DIR = read_ini_file('Uptime')
    # print(WORKING_DIR)
