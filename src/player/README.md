
MainboardController:
    def __init__(self, int sock_fd, unsigned int bufsize,
                 msg_empty_callback=None, msg_sendable_callback=None)

    (property) ready: Ready for operation
    def bootstrap(self, callback=None)



ToolheadController:
    def __init__(self, int sock_fd, required_module=None)

    (property) ready: Ready for operation
    def bootstrap(self, callback=None)
    def handle_recv(self)
    def patrol(self)
    def sendable(self)

    def set_allset_callback(self, callback=None)
    def recover(self, callback=None)
    def standby(self, callback=None)
    def shutdown(self, callback=None)

    (property) ext: look Extentions
    (property) error_code: toolhead error_code (uint32_t)
    (property) module_info: Module profile (dict)
    (property) module_status: Module status (dict)


Extentions:
    # ToolheadControler invoke this method when completing handshake
    def on_hello(self, info)

    # ToolheadController invoke this method when toolhead response PONG
    def on_update(self, status)

    # Generate commands to set toolhead to current status
    def do_recover(self, source)

    # Generate commands to set toolhead to standby status but keep its current
    # status in Extentions. When on_recover invoked, toolhead will back to its
    # origin status
    def do_standby(self, source)

    # Generate commands to set toolhead to standby status. All settings in
    # Extentions will be removed.
    def do_shutdown(self, source)

    # Return true if toolhead status is exactly as it was set.
    # For example it will return False when heater is set to 210 degress but
    # real temperature is 80 degree.
    def allset(self)


ExtruderExtention:
    def __init__(self, num_of_extruder=1, max_temperature=235.0)
    def set_heater(self, index, temperature, complete_callback=None)
    def set_fan_speed(self, index, strength, complete_callback=None)

