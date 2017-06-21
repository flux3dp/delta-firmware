
#include <stdarg.h>
#include "Python.h"

#define RECV_BUFFER_SIZE 512

typedef struct command_queue_item{
    char *buffer;
    size_t length;
    uint32_t lineno;
    struct command_queue_item *next;
} CommandQueueItem;


typedef struct {
    CommandQueueItem *begin;
    CommandQueueItem *end;
    size_t length;
} CommandQueue;


typedef struct {
    char b[RECV_BUFFER_SIZE];
    const char *begin;
    const char *end;
} RecvBuffer;


void init_command_queue(CommandQueue *q);
void append_command_queue(CommandQueue *q, char *buf, size_t length, uint32_t lineno);
void append_command_queue_item(CommandQueue *q, CommandQueueItem *item);
CommandQueueItem* pop_command_queue(CommandQueue *q);
void clear_command_queue(CommandQueue *q);

// Return
//   -2 -> IOError (find error from errno)
//   -1 -> BUFF FULL, buffer reset
//   0 -> No available data
//   1 -> Recv line, string is begin from buf->b until endptr, no more data in buffer
//   2 -> Recv line, string is begin from buf->b until endptr, has data in buffer
int recvline(int sock_fd, RecvBuffer *buf, const char **endptr);

// Return
//   -4 -> Message too short
//   -3 -> Format error
//   -2 -> Sumcheck symbol not found
//   -1 -> Sumcheck failed
//   >0 -> validate message length
int validate_toolhead_message_1(const char *begin, const char *end);


// Return
//   0 -> OK
//   1 -> PyObject not dict
//   2 -> Dict set error
int parse_dict(const char *begin, const char *terminator, PyObject* d);

unsigned int build_toolhead_command(char **buf, const char* fmt, ...);


//
PyObject* create_cmd(int lineno, const char* cmd);
