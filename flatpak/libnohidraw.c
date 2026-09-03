/* Block access to /dev/hidraw* so WebKitGTK's libmanette can't grab the
 * Steam Deck's built-in controller (disabling its firmware lizard-mode
 * keyboard/mouse emulation and fighting Steam Input). LD_PRELOADed only
 * for a Steam-shortcut Deck session by playdate-wrapper.sh. */
#define _GNU_SOURCE
#include <stdarg.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <dlfcn.h>

static int is_hidraw(const char *p) {
    return p && strncmp(p, "/dev/hidraw", 11) == 0;
}

static int (*real_open)(const char *, int, ...);
static int (*real_open64)(const char *, int, ...);
static int (*real_openat)(int, const char *, int, ...);
static int (*real_openat64)(int, const char *, int, ...);

__attribute__((constructor)) static void init(void) {
    real_open     = dlsym(RTLD_NEXT, "open");
    real_open64   = dlsym(RTLD_NEXT, "open64");
    real_openat   = dlsym(RTLD_NEXT, "openat");
    real_openat64 = dlsym(RTLD_NEXT, "openat64");
}

int open(const char *path, int flags, ...) {
    if (is_hidraw(path)) { errno = EACCES; return -1; }
    mode_t m = 0; va_list ap; va_start(ap, flags);
    if (flags & O_CREAT) m = va_arg(ap, int);
    va_end(ap);
    return real_open(path, flags, m);
}
int open64(const char *path, int flags, ...) {
    if (is_hidraw(path)) { errno = EACCES; return -1; }
    mode_t m = 0; va_list ap; va_start(ap, flags);
    if (flags & O_CREAT) m = va_arg(ap, int);
    va_end(ap);
    return real_open64(path, flags, m);
}
int openat(int fd, const char *path, int flags, ...) {
    if (is_hidraw(path)) { errno = EACCES; return -1; }
    mode_t m = 0; va_list ap; va_start(ap, flags);
    if (flags & O_CREAT) m = va_arg(ap, int);
    va_end(ap);
    return real_openat(fd, path, flags, m);
}
int openat64(int fd, const char *path, int flags, ...) {
    if (is_hidraw(path)) { errno = EACCES; return -1; }
    mode_t m = 0; va_list ap; va_start(ap, flags);
    if (flags & O_CREAT) m = va_arg(ap, int);
    va_end(ap);
    return real_openat64(fd, path, flags, m);
}
