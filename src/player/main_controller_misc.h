
#include "misc.h"
#define COMMAND_LENGTH 256

// return buf length
int build_mainboard_command(char *buf, const char *cmd, size_t cmd_size, uint32_t lineno);

// return command quenty in mainboard
unsigned int handle_ln(const char *buf, unsigned int length, CommandQueue *cmd_sent, CommandQueue *cmd_padding);

uint32_t handle_ln_mismatch(const char *buf, unsigned int length, int sock_fd, CommandQueue *cmd_sent, CommandQueue *cmd_padding, uint32_t flag);
uint32_t handle_checksum_mismatch(const char *buf, unsigned int length, int sock_fd, CommandQueue *cmd_sent, CommandQueue *cmd_padding, uint32_t flag);

// return new flag
uint32_t resend(int sock_fd, CommandQueue *cmd_sent, uint32_t flag);
