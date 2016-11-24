
#include <stdio.h>
#include <sys/socket.h>
#include "main_controller_misc.h"


int build_mainboard_command(char *buf, const char *cmd, size_t cmd_size, uint32_t lineno) {
    if(cmd_size > COMMAND_LENGTH) {
        return -1;
    }

    int size;
    int offset = 0;
    unsigned char c = 0;
    // char byte = cmd[0];

    while(offset < cmd_size) {
        buf[offset] = cmd[offset];
        c ^= cmd[offset];
        ++offset;
    }

    size = offset + snprintf(buf + offset, COMMAND_LENGTH - offset, " N%i", lineno);
    while(offset < size) {
        c ^= buf[offset];
        ++offset;
    }

    offset += snprintf(buf + offset, 256 - offset, "*%i\n", c);

    if(offset == COMMAND_LENGTH) {
        return -1;
    } else {
        return offset;
    }
}


unsigned int handle_ln(const char* buf, unsigned int length, CommandQueue *cmd_sent, CommandQueue *cmd_padding) {
    // buf = "LN {Received line number} {command in queue}"
    char *anchor;
    uint32_t recv_ln, cmd_in_queue;

    recv_ln = strtoul(buf + 3, &anchor, 10);
    cmd_in_queue = strtoul(anchor + 1, NULL, 10);

    while(cmd_sent->length && cmd_sent->begin->lineno <= recv_ln) {
        CommandQueueItem *item = pop_command_queue(cmd_sent);
        append_command_queue_item(cmd_padding, item);
    }

    while(cmd_padding->length > cmd_in_queue) {
        CommandQueueItem *item = pop_command_queue(cmd_padding);
        if(item) {
            free(item);
        }
    }

    return cmd_in_queue + cmd_sent->length;
}


uint32_t handle_ln_mismatch(const char *buf, unsigned int length, int sock_fd, CommandQueue *cmd_sent, CommandQueue *cmd_padding, uint32_t flag) {
    // buf = "ER LINE_MISMATCH {Expected line number} {Received line number}"

    char *anchor;
    uint32_t correct_ln, trigger_ln;

    correct_ln = strtoul(buf + 17, &anchor, 10);
    trigger_ln = strtoul(anchor + 1, NULL, 10);

    while(cmd_sent->length && cmd_sent->begin->lineno < correct_ln) {
        CommandQueueItem *item = pop_command_queue(cmd_sent);
        append_command_queue_item(cmd_padding, item);
    }

    if(correct_ln < trigger_ln) {
        return resend(sock_fd, cmd_sent, flag);
    } else {
        return 0;
    }
}

// __attribute__((optnone))

uint32_t handle_checksum_mismatch(const char *buf, unsigned int length, int sock_fd, CommandQueue *cmd_sent, CommandQueue *cmd_padding, uint32_t flag) {
    // buf = "ER CHECKSUM_MISMATCH {Line number}"
    uint32_t lineno = strtoul(buf + 21, NULL, 10);

    while(cmd_sent->length && cmd_sent->begin->lineno < lineno) {
        CommandQueueItem *item = pop_command_queue(cmd_sent);
        append_command_queue_item(cmd_padding, item);
    }

    return resend(sock_fd, cmd_sent, flag);
}

uint32_t resend(int sock_fd, CommandQueue *cmd_sent, uint32_t flag) {
    if(cmd_sent->length) {
        if(flag > 0) return flag;

        CommandQueueItem *item = cmd_sent->begin;
        while(item) {
            send(sock_fd, item->buffer, item->length, 0);
            item = item->next;
        }
        return cmd_sent->begin->lineno;
    } else {
        return 0;
    }
}
