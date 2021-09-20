from manager import *
from auth import User, CustomLoginManager
from flask import Flask, render_template, session, request, \
    redirect, url_for, flash, jsonify
from flask_socketio import SocketIO, emit
from functools import wraps
from datetime import timedelta
from time import strptime
from gps import *

# Дата не может быть старше, чем 19.01.2038
if time.time() > mktime(strptime("2038-01-19 00:00:00", "%Y-%m-%d %H:%M:%S")):
    clock_settime(CLOCK_REALTIME, mktime(strptime("1970-01-01 23:59:59", "%Y-%m-%d %H:%M:%S")))


flask_app = Flask(__name__)
secret_key = read_ini_file().get('secretkey', 'default_secret_key!')
flask_app.config.update(SECRET_KEY=secret_key,
                        SESSION_COOKIE_SAMESITE='Lax',
                        SESSION_REFRESH_EACH_REQUEST=True,
                        )
socketio_app = SocketIO(flask_app, async_mode=None, cookie=None, logger=False, engineio_logger=False)
manager = Manager(logger=flask_app.logger, args=sys.argv)
user = User(1, u"name")     # создаем пользователя с дефолтным именем, при подключении клиента именем станет ip
login_manager = CustomLoginManager()
login_manager.init(flask_app)

thread_gps = None
thread_time = None
thread_control = None
# lock = Lock()


def flash_message(msg: str, category=None) -> None:
    """
    Отправляет сообщение в базовый лог, а также выводит на экран

    :param msg: текст сообщения
    :param category: категория сообщения - 'info', 'error'
    :return: None
    """
    manager.logger.error(msg)
    flash(msg, category)


@flask_app.before_request
def make_session_permanent() -> None:
    """
    Обновляет текущую сессию перед загрузкой веб страницы

    :return: None
    """
    session.modified = True
    flask_app.permanent_session_lifetime = timedelta(seconds=60 * int(settings.config['lifetime']))


@login_manager.user_loader
def load_user(user_id) -> type(User):
    """
    Callback функция, возвращает объект класса текущего пользователя в сессии

    :param user_id: id текущего пользователя
    :return: объект класса текущего пользователя
    """
    return User


def authenticated_only(func):
    """
    Декоратор, выполняет проверку авторизации текущего пользователя сессии перед
    выполнением функции

    :param func: декорируемая функция
    :return: результат выполнения функции
    """
    @wraps(func)
    def wrapped(*args, **kwargs):
        if not user.is_authenticated():
            return render_template("login.html", header=settings.header)
        else:
            return func(*args, **kwargs)

    return wrapped


@flask_app.route("/login.html", methods=["GET", "POST"])
def login() -> str:
    """
    Обрабатывает запрос к веб странице авторизации

    :return: функция формирования шаблона веб страницы
    """
    if manager.reset_webserver:
        run_cmd("systemctl restart webserver")
    if request.method == "POST":
        if user.check_password(request.form.get("hash")):
            user.name = request.remote_addr
            if user.login():
                flash_message("Вход в систему.")
                manager.logger.debug("USERNAME: %s", user.name)
                return redirect(request.args.get("next") or url_for("main"))
            else:
                flash_message("Невозможно войти в систему!", 'warning')
        else:
            flash_message(u"Неверный пароль!", 'warning')
    return render_template("login.html", header=settings.header)


@flask_app.route("/logout", methods=["GET", "POST"])
@authenticated_only
def logout():
    """
    Выполняет удаление пользователя из текущей сессии

    :return: функция переадресации на страницу авторизации
    """
    user.logout()
    flash_message("Выход из системы!", 'warning')
    return redirect(url_for("login"))


@flask_app.route("/reauth", methods=["POST"])
def reauth():
    """
    Обрабатывает запрос на авторизацию пользователя

    :return: словарь с результатом проверки на авторизацию
    """
    response = {}
    msg = request.form.get("msg")
    manager.logger.debug(msg)
    manager.logger.error('Смена пароля...')
    if msg == 'not_equal_passwords':
        flash_message(u"Новые пароли не совпадают!", 'warning')
    elif msg == 'null_password':
        flash_message(u"Не введен новый пароль!", 'warning')
    elif msg:
        response['pass_verify'] = user.check_password(request.form["msg"])
        if not response['pass_verify']:
            flash_message(u"Неверный пароль!", 'warning')
        else:
            flash_message(u"Пароль изменен!")
    return jsonify(response)


@flask_app.route('/', methods=['GET', 'POST'])
@flask_app.route('/main.html', methods=['GET', 'POST'])
@authenticated_only
def main() -> str:
    """
    Обрабатывает запрос к веб странице основных настроек

    :return: функция формирования шаблона веб страницы
    """
    if request.method == 'POST':

        action = request.form.get('btn')
        msg = None

        if action == 'set_sync':
            msg = manager.set_sync_source(request.form.get('sync_src'))
        elif action == 'set_ext_sync':
            msg = manager.set_ext_sync_source(request.form.get('ext_sync_src'))
        elif action == 'save_time':
            msg = manager.save_time(request.form.get('date'), request.form.get('time'))
        elif action == 'save_time_settings':
            msg = manager.save_time_settings(request.form.get('timejump'),
                                             request.form.get('tz'),
                                             request.form.get('tz_kv'),
                                             request.form.get('tz_rs'), )
        elif action == 'save_gnss':
            msg = manager.save_gnss(request.form.get('ext_sync_src'),
                                    request.form.get('speed'),
                                    request.form.get('sat_system'),
                                    request.form.get('reciever'))

        if msg:
            flash_message(u"%s" % msg)

    return render_template('main.html',
                           main=manager.get_main(),
                           header=settings.header)


@flask_app.route('/net.html', methods=['GET', 'POST'])
@authenticated_only
def net() -> str:
    """
    Обрабатывает запрос к веб странице сетевых настроек

    :return: функция формирования шаблона веб страницы
    """
    if request.method == 'POST' and request.form.get('btn') == 'save_lan':
        err_msg = manager.change_net_cfg(request.form.get('lan'),
                                         request.form.get('ip'),
                                         request.form.get('netmask'),
                                         request.form.get('gateway'),
                                         request.form.get('listen'),
                                         )
        if err_msg == '':
            msg = "Настройки %s изменены!" % settings.net[request.form.get('lan')]['label']
            flash(u"%s" % msg)
        else:
            msg = err_msg + " Настройки %s не сохранены!" % settings.net[request.form.get('lan')]['label']
            flash_message(u"%s" % msg, 'warning')
    return render_template('net.html',
                           net=manager.get_net_cfg(),
                           header=settings.header)


@flask_app.route('/stat.html', methods=['GET', 'POST'])
@authenticated_only
def stat() -> str:
    """
    Обрабатывает запрос к веб странице данных ГНСС

    :return: функция формирования шаблона веб страницы
    """
    return render_template('stat.html', async_mode=socketio_app.async_mode, header=settings.header)


@flask_app.route('/ntp.html', methods=['GET', 'POST'])
@authenticated_only
def ntp() -> str:
    """
    Обрабатывает запрос к веб странице данных службы времени

    :return: функция формирования шаблона веб страницы
    """
    return render_template('ntp.html', async_mode=socketio_app.async_mode, header=settings.header)


@flask_app.route('/journal.html', methods=['GET', 'POST'])
@authenticated_only
def journal() -> str:
    """
    Обрабатывает запрос к веб странице журнала логов

    :return: функция формирования шаблона веб страницы
    """
    if request.method == 'POST':
        settings.journal = []
        for unit in ('all', 'gpsd', 'ntpd'):
            if request.form.get(unit):
                settings.journal.append(unit)
    log = read_journalctl(since='today', until='now', services=settings.journal)
    return render_template('journal.html',
                           log=str(log),
                           services=settings.journal,
                           header=settings.header)


@flask_app.route('/conf.html', methods=['GET', 'POST'])
@authenticated_only
def conf():
    """
    Обрабатывает запрос к веб странице обслуживания и настроек вебсервера

    :return: функция формирования шаблона веб страницы
    """
    if request.method == 'POST':

        action = request.form.get('btn')
        msg = None

        if action == 'reset':
            if not settings.reset():
                flash_message(u"%s" % "Ошибка, сброс к заводским настройкам не выполнен!", 'warning')
            else:
                flash_message(u"%s" % "Выполнен сброс к заводским настройкам!")
                manager.reset_webserver = True
                return redirect(url_for('logout'))
        elif action == 'rename':
            msg = manager.set_devname(request.form.get('devname'))
        elif action == 'save_config':
            msg = manager.set_lifetime(request.form.get('lifetime'))
            if request.form.get('new_hash'):
                user.change_password(new_password=request.form.get('new_hash'))

        if msg:
            flash_message(u"%s" % msg)
    config = settings.get_config()
    return render_template('conf.html', config=config, header=settings.header)


def time_worker() -> None:
    """
    Программный поток, посылает запросы к службе времени, получает данные о
    текущих источниках синхронизации времени, секундной метки, текущей дате и времени,
    выполняет отправку полученных данных на веб страницу

    :return: None
    """
    while True:
        dt = {
            'time': 'Нет данных',
            'date': 'Нет данных',
            'synctime': 'Нет данных',
            'syncpps': 'Нет данных',
            'peers': {}
        }
        # get peers from ntp service
        peers = ntp_peers()
        # print(peers)
        if peers:
            for refid in peers:
                if peers[refid]['status_id'] == '*':

                    peers[refid]['status'] = 'источник времени'
                    dt['synctime'] = peers[refid]['name'].split()[0]

                    if refid == '.GPPS.':
                        if peers['.NMEA.']['status_id'] != 'x':
                            peers['.NMEA.']['status'] = 'источник времени'
                            dt['synctime'] = 'ГНСС'
                        elif peers['.LCL.']['status_id'] != 'x':
                            peers['.LCL.']['status'] = 'источник времени'
                            dt['synctime'] = 'Внутренний'
                        peers['.GPPS.']['status'] = 'источник секундной метки'
                        dt['syncpps'] = 'ГНСС'

                    if refid == '.LPPS.':
                        if peers['.LCL.']['status_id'] != 'x':
                            peers['.LCL.']['status'] = 'источник времени'
                            dt['synctime'] = 'Внутренний'
                        elif peers['.NMEA.']['status_id'] != 'x':
                            peers['.NMEA.']['status'] = 'источник времени'
                            dt['synctime'] = 'ГНСС'
                        peers['.LPPS.']['status'] = 'источник секундной метки'
                        dt['syncpps'] = 'Внутренний'

                elif peers[refid]['status_id'] == 'o':
                    if dt['syncpps'] == 'Нет данных':
                        dt['syncpps'] = peers[refid]['name'].split()[0]

        # save sources of time and pps
        time_src, pps_src = TIME_SRC_NONE, PPS_SRC_NONE
        if dt['synctime'] == 'ГНСС':
            time_src = TIME_SRC_GNSS
        elif dt['synctime'] == 'Внутренний':
            time_src = TIME_SRC_INTERNAL

        if dt['syncpps'] == 'ГНСС':
            pps_src = PPS_SRC_GNSS
        elif dt['syncpps'] == 'Внутренний':
            pps_src = PPS_SRC_INTERNAL

        settings.time_src = time_src
        settings.pps_src = pps_src

        # get local time
        local_struct = localtime()
        date_str = strftime("%d.%m.%Y", local_struct)
        time_str = strftime('%T', local_struct)

        # save data for emitting
        dt['peers'] = peers
        if date_str and time_str:
            dt['date'] = date_str
            dt['time'] = time_str

        # print(date_str, time_str)
        # print(settings.gpsd_data.get('date'), settings.gpsd_data.get('time'))
        # print(dt, '\n')
        socketio_app.emit('datetime_event', dt, namespace='/time')
        socketio_app.sleep(0.25)


@socketio_app.on('connect', namespace='/time')
def time_connect() -> None:
    """
    Callback функция, вызывается при получении запроса от веб страницы и
    запускает программный поток 'time_worker'

    :return: None
    """
    global thread_time
    if thread_time is None:
        thread_time = socketio_app.start_background_task(time_worker)
    emit('my_response', {'data': 'Connected', 'count': 0})


@socketio_app.on('disconnect', namespace='/time')
def time_disconnect() -> None:
    pass


# gps_default = dict(time='-',
#                    date='-',
#                    latitude='-',
#                    longitude='-',
#                    speed='-',
#                    altitude='-',
#                    mode=-1,
#                    status=-1,
#                    sats_change=True,
#                    sat_list=[],
#                    sats='-',
#                    sats_valid='-',
#                    dt=''
#                    )


# def reset_gpsd_data():
#     print('reset_gpsd_data')
#     settings.gpsd_data = settings.gps_default.copy()


def control_worker() -> None:
    saved_value = None
    while True:
        new_value = settings.gpsd_data.get('time')
        if new_value != '-' and new_value == saved_value:
            settings.reset_gpsd_data()
            socketio_app.emit('my_response', settings.gpsd_data, namespace='/gps')
        saved_value = new_value
        sleep(3)


def gps_worker() -> None:
    """
    Программный поток, посылает запросы к службе gpsd, получает данные
    ГНСС приемника, а также информацию об используемых спутниках,
    выполняет отправку полученных данных на веб страницу

    :return: None
    """
    connection = None
    # gps_dict = settings.gpsd_data = {}

    # gps_default = dict(time='-',
    #                    date='-',
    #                    latitude='-',
    #                    longitude='-',
    #                    speed='-',
    #                    altitude='-',
    #                    mode=-1,
    #                    status=-1,
    #                    sats_change=True,
    #                    sat_list=[],
    #                    sats='-',
    #                    sats_valid='-',
    #                    dt=''
    #                    )

    manager.logger.error('Подключение к службе GPSD...')

    while True:
        try:
            if connection is None:
                try:
                    connection = gps(mode=WATCH_ENABLE)
                except ConnectionRefusedError:
                    manager.logger.error('Ожидание сообщений от службы GPSD...')
                    settings.reset_gpsd_data()
                    socketio_app.emit('my_response', settings.gpsd_data, namespace='/gps')
                    systemctl(action='restart', service='gpsd.socket')
                    socketio_app.sleep(5)
                    continue

            for dataset in connection:
                gps_fix = vars(connection.fix).copy()
                # print(gps_fix)
                # gps_dict = gps_default.copy()

                # gps data
                mode = gps_fix['mode']
                if str(mode) == 'nan':
                    mode = -1
                settings.gpsd_data['mode'] = mode

                status = gps_fix['status']
                if str(status) == 'nan':
                    status = 0
                if mode < 3:
                    status = 0

                settings.gpsd_data['status'] = status
                # print(status, mode)

                # при первой успешной синхронизации со спутником - разрешить
                # раздачу времени по сети
                if manager.gnss_synced is False and status > 0:
                    manager.gnss_synced = True
                    for lan in ('lan1', 'lan2'):
                        add_listen_ntp(lan,
                                       listen=settings.net[lan]['listen'],
                                       ip=settings.net[lan]['ip'],
                                       sync_src=settings.main['sync_src'],
                                       gnss_synced=True)

                if not status:
                    for idx in ('date', 'time', 'latitude', 'longitude', 'speed', 'altitude'):
                        settings.gpsd_data[idx] = '-'
                else:
                    # date and time
                    t = gps_fix['time']
                    if isinstance(t, str):
                        utc_struct = strptime(t, '%Y-%m-%dT%X.%fZ')
                        local_struct = localtime(timegm(utc_struct))
                        settings.gpsd_data['dt'] = local_struct
                        settings.gpsd_data['time'] = strftime('%T', local_struct)
                        settings.gpsd_data['date'] = strftime('%d.%m.%y', local_struct)
                    else:
                        settings.gpsd_data['date'] = '-'
                        settings.gpsd_data['time'] = '-'

                    for idx in ['latitude', 'longitude', 'speed', 'altitude']:
                        value = gps_fix[idx]
                        if settings.gpsd_data['mode'] == 3 and str(value) != 'nan':

                            if idx in ('latitude', 'longitude'):
                                minute = value % 1 * 60
                                sec = minute % 1 * 60
                                deg = "%d° %d' %d\"" % (int(value), int(minute), int(sec))
                                if idx == 'latitude':
                                    settings.gpsd_data[idx] = deg + ' N'
                                else:
                                    settings.gpsd_data[idx] = deg + ' E'
                            else:
                                settings.gpsd_data[idx] = int(value)

                        else:
                            settings.gpsd_data[idx] = '-'

                # satellites data
                sat_list = []
                settings.gpsd_data['sat_list'] = []
                settings.gpsd_data['sats_change'] = False
                if "satellites" in connection.data:
                    for sat in connection.data['satellites']:
                        sat_list.append(dict(sat))
                    settings.gpsd_data['sat_list'] = sat_list
                    settings.gpsd_data['sats'] = len(sat_list)
                    settings.gpsd_data['sats_valid'] = connection.satellites_used
                    settings.gpsd_data['sats_change'] = True

                # manager.logger.error(settings.gpsd_data)
                socketio_app.emit('my_response', settings.gpsd_data, namespace='/gps')

            dataset = connection.next()
            if dataset['class'] == 'DEVICE':
                connection.close()
                connection = None

        except StopIteration:
            manager.logger.error('Выполняется подключение к службе GPSD..')
            connection = None
            # TODO: when gpsd is off - show time&date on stat.html
            settings.reset_gpsd_data()
            socketio_app.emit('my_response', settings.gpsd_data, namespace='/gps')
            socketio_app.sleep(5)


@socketio_app.on('connect', namespace='/gps')
def gps_connect() -> None:
    """
    Callback функция, вызывается при получении запроса от веб страницы и
    запускает программный поток 'gps_worker'

    :return: None

    """
    # TODO: verify thread joining (no new thread with old thread alive)
    global thread_gps
    if thread_gps is None:
        thread_gps = socketio_app.start_background_task(gps_worker)
    emit('my_response', {'data': 'Connected', 'count': 0})


@socketio_app.on('disconnect', namespace='/gps')
def gps_disconnect() -> None:
    pass


if __name__ == '__main__':
    thread_time = socketio_app.start_background_task(time_worker)
    thread_gps = socketio_app.start_background_task(gps_worker)
    thread_control = socketio_app.start_background_task(control_worker)
    socketio_app.run(flask_app, debug=False, host='0.0.0.0', port='5001')
