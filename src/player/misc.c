
#include <sys/socket.h>
#include "misc.h"

void init_command_queue(CommandQueue *q) {
    q->begin = q->end = NULL;
    q->length = 0;
}


void append_command_queue(CommandQueue *q, char *buf, size_t length, uint32_t lineno) {
    CommandQueueItem* item = (CommandQueueItem*)malloc(sizeof(CommandQueueItem));
    item->buffer = buf;
    item->length = length;
    item->lineno = lineno;
    append_command_queue_item(q, item);
}


void append_command_queue_item(CommandQueue *q, CommandQueueItem *item) {
    item->next = NULL;

    if(q->length) {
        q->length++;
        q->end->next = item;
        q->end = item;
    } else {
        q->length = 1;
        q->begin = q->end = item;
    }
}


CommandQueueItem* pop_command_queue(CommandQueue *q) {
    if(q->length > 1) {
        CommandQueueItem* item = q->begin;
        q->begin = item->next;
        --(q->length);
        return item;
    } else if(q->length == 1) {
        CommandQueueItem* item = q->begin;
        q->begin = q->end = NULL;
        q->length = 0;
        return item;
    } else {
        return NULL;
    }
}


void clear_command_queue(CommandQueue *q) {
    while(q->length) {
        CommandQueueItem* item = q->begin;
        q->begin = item->next;

        free(item->buffer);
        free(item);
        q->length--;
    }
    q->begin = q->end = NULL;
}


int recvline(int sock_fd, RecvBuffer *buf, const char **endptr) {
    if(buf->begin != buf->b) {
        strncpy(buf->b, buf->begin, buf->end - buf->begin);
        buf->end = buf->end - (buf->begin - buf->b);
        buf->begin = buf->b;

        for(char *ptr=buf->b;ptr<buf->end;++ptr) {
            if(*ptr == '\n') {
                if((ptr + 1) == buf->end) {
                    buf->end = buf->b;
                    *endptr = ptr;
                    return 1;
                } else {
                    buf->begin = ptr + 1;
                    *endptr = ptr;
                    return 2;
                }
            }
        }
    }

    if(!sock_fd) { return 0; }
    int ret = recv(sock_fd, (void*)buf->end, RECV_BUFFER_SIZE - (unsigned int)(buf->end - buf->b), 0);
    if(ret > 0) {
        const char* new_end = buf->end + ret;
        for(const char* i=buf->end;i<new_end;++i) {
            if(*i == '\n') {
                if((i + 1) == new_end) {
                    buf->end = buf->b;
                    *endptr = i;
                    return 1;
                } else {
                    buf->begin = i + 1;
                    buf->end = new_end;
                    *endptr = i;
                    return 2;
                }
            }
        }
        if(new_end - buf->b == RECV_BUFFER_SIZE) {
            buf->begin = buf->end = buf->b;
            return -1;
        } else {
            buf->end = new_end;
            return 0;
        }
    } else {
        return -2;
    }
}


int validate_toolhead_message_1(const char *begin, const char *end) {
    if(end - begin < 4) { return -4; }
    if(begin[0] != '1' || begin[1] != ' ') { return -3; }

    unsigned char sumcheck = 0 ^ '1' ^ ' ';
    int recv_sumcheck;
    const char *ptr = begin + 2;  // Skip "1 " prefix

    while(ptr < end) {
        if((ptr[0]) == '*') {
            recv_sumcheck = atoi(ptr + 1);
            if(recv_sumcheck == sumcheck) {
                return ptr - begin;
            } else {
                return -1;
            }
        } else {
            sumcheck ^= ptr[0];
            ptr += 1;
        }
    }
    return -2;
}


PyObject* parse_doubles(const char *begin, const char *end) {
    volatile double *numbers = (double*)malloc(sizeof(double) * ((end - begin) / 2) + 1);
    int c = 0;
    char *ptr = (char*)begin;

    while(ptr < end) {
        numbers[c++] = strtod(ptr, &ptr);
        ptr++;
    }

    PyObject *t = PyTuple_New(c);
    for(int i=0;i<c;i++) {
        volatile PyObject* pynum = PyFloat_FromDouble(numbers[i]);
        PyTuple_SetItem(t, i, pynum);
    }
    free(numbers);
    return t;
}


int parse_dict(const char *begin, const char *terminator, PyObject* d) {
    if(!PyDict_Check(d)) {
        return 1;
    }

    PyObject *key = NULL,
             *value = NULL;

    const char *ptr = begin;
    int find_quote = 0, found_val = 0, parse_numbers;
    char* buf = (char *)malloc(terminator - begin);
    char* bufptr;

    while(ptr < terminator) {
        // Ignore white space
        while(ptr < terminator && ptr[0] == ' ') { ptr++; }

        // Find key
        found_val = 0;
        bufptr = buf;
        while(ptr < terminator && !found_val) {
            switch(ptr[0]) {
                case '"':
                    find_quote = !find_quote;
                    break;
                case '\\':
                    if(ptr + 1 < terminator) {
                        bufptr[0] = ptr[1];
                        bufptr++;
                        ptr++;
                    } else {
                        key = PyString_FromStringAndSize(buf, bufptr - buf);
                        found_val = 1;
                    }
                    break;
                case ':':
                    if(!find_quote) {
                        parse_numbers = ((bufptr - buf) == 2) && (buf[1] == 'T') && ((buf[0] == 'T') || (buf[0] == 'R'));
                        if(parse_numbers) {
                            buf[1] = 't';
                            buf[0] = buf[0] == 'R' ? 'r' : 't';
                        }
                        key = PyString_FromStringAndSize(buf, bufptr - buf);
                        found_val = 1;
                        break;
                    }
                case ' ':
                    if(!find_quote) {
                        key = PyString_FromStringAndSize(buf, bufptr - buf);
                        found_val = 1;
                        ptr--;
                        break;
                    }
                default:
                    bufptr[0] = ptr[0];
                    bufptr++;
            }
            ptr++;
        }
        if(!found_val) {
            key = PyString_FromStringAndSize(buf, bufptr - buf);
        }

        // Find Value
        found_val = 0;
        bufptr = buf;
        while(ptr < terminator && !found_val) {
            switch(ptr[0]) {
                case '"':
                    find_quote = !find_quote;
                    break;
                case '\\':
                    if(ptr + 1 < terminator) {
                        bufptr[0] = ptr[1];
                        bufptr++;
                        ptr++;
                    } else {
                        value = PyString_FromStringAndSize(buf, bufptr - buf);
                        found_val = 1;
                    }
                    break;
                case ' ':
                    if(!find_quote) {
                        if(parse_numbers) {
                            parse_numbers = 0;
                            bufptr[0] = 0;
                            value = parse_doubles(buf, bufptr);
                        } else {
                            value = PyString_FromStringAndSize(buf, bufptr - buf);
                        }
                        found_val = 1;
                        break;
                    }
                default:
                    bufptr[0] = ptr[0];
                    bufptr++;
            }
            ptr++;
        }
        if(!found_val) {
            if(parse_numbers) {
                parse_numbers = 0;
                bufptr[0] = 0;
                value = parse_doubles(buf, bufptr);
            } else {
                value = PyString_FromStringAndSize(buf, bufptr - buf);
            }
        }
        if(key != NULL) {
            if(PyDict_SetItem(d, key, value ? value : Py_None) == -1) {
                return 2;
            }
        }
        key = NULL;
        value = NULL;
    }
    free(buf);
    return 0;
}


unsigned int build_toolhead_command(char **buf, const char* fmt, ...) {
    char *swap;
    va_list argptr;
    va_start(argptr, fmt);
    size_t l = vasprintf(&swap, fmt, argptr);
    unsigned char c = 0 ^ '1' ^ ' ';
    // "1 ...... *xxx\n"
    //  ^^      ^^^^^^
    (*buf) = (char*)(malloc(sizeof(char) * (l + 8)));
    (*buf)[0] = '1';
    (*buf)[1] = ' ';

    for(int i=0;i<l; i++) {
        c ^= swap[i];
        (*buf)[i + 2] = swap[i];
    }
    c ^= 32;
    return l + sprintf((*buf) + l + 2, " *%i\n", (int)c) + 2;
}


// PyObject* create_cmd(int lineno, const char* cmd) {
//     int i, size;
//     int offset = 0;
//     int sumcheck = 0;
//     char buf[256];
//     char byte = cmd[0];

//     while(offset < 256 && byte != 0) {
//         buf[offset] = byte;
//         sumcheck ^= byte;
//         offset += 1;
//         byte = cmd[offset];
//     }

//     size = snprintf((char *)buf + offset, 256 - offset, " N%i", lineno);
//     size = offset + size;

//     for(i=offset;i<size;i++) {
//         sumcheck ^= buf[i];
//         offset += 1;
//     }

//     size = snprintf((char *)buf + offset, 256 - offset, "*%i\n", sumcheck);
//     return PyString_FromStringAndSize(buf, offset + size);
// }
