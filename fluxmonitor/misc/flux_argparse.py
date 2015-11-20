

def add_config_arguments(parser):
    parser.add_argument('--config', dest='configfile', type=str,
                        default='', help='config file')
    parser.add_argument('--debug', dest='debug', action='store_const',
                        const=True, default=False, help='Enable debug')


def apply_config_arguments(options):
    from fluxmonitor import config

    if options.configfile:
        config.load_config(options.configfile)

    if options.debug:
        config.general_config["debug"] = True
        config.DEBUG = True


def add_daemon_arguments(proc_name, parser):
    add_config_arguments(parser)

    parser.add_argument('--daemon', dest='daemon', action='store_const',
                        const=True, default=False, help='Run as daemon')
    parser.add_argument('--signal_debug', dest='signal_debug',
                        action='store_const', const=True, default=False,
                        help='Use signal2 for callstack debug')
    parser.add_argument('--stop', dest='stop_daemon', action='store_const',
                        const=True, default=False, help='Stop daemon')
    parser.add_argument('--pid', dest='pidfile', type=str,
                        default='%s.pid' % proc_name, help='PID file')
    parser.add_argument('--log', dest='logfile', type=str, default=None,
                        help='Log file')


def apply_daemon_arguments(options):
    apply_config_arguments(options)

    if options.debug:
        from fluxmonitor.config import general_config
        general_config["debug"] = True
