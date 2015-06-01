

def add_config_arguments(parser):
    parser.add_argument('--config', dest='configfile', type=str,
                        default='', help='config file')
    parser.add_argument('--debug', dest='debug', action='store_const',
                        const=True, default=False, help='Enable debug')


def apply_config_arguments(options):
    if options.configfile:
        from fluxmonitor.config import load_config
        load_config(options.configfile)


def add_daemon_arguments(proc_name, parser):
    add_config_arguments(parser)

    parser.add_argument('--daemon', dest='daemon', action='store_const',
                        const=True, default=False, help='Run as daemon')
    parser.add_argument('--stop', dest='stop_daemon', action='store_const',
                        const=True, default=False, help='Stop daemon')
    parser.add_argument('--pid', dest='pidfile', type=str,
                        default='%s.pid' % proc_name, help='PID file')
    parser.add_argument('--log', dest='logfile', type=str,
                        default='%s.log' % proc_name, help='Log file')


def apply_daemon_arguments(options):
    apply_config_arguments(options)

    if options.debug:
        from fluxmonitor.config import general_config
        general_config["debug"] = True
