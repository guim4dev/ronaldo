/* Ronaldo.app's executable: spawns the Python listener as a child so macOS
 * attributes Microphone/Accessibility permissions to "Ronaldo" (this bundle)
 * instead of to the shared python3 interpreter. */
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(void) {
    char *argv[] = {RONALDO_PYTHON, "-m", "ronaldo.listener", NULL};
    if (chdir(RONALDO_ROOT) != 0) { perror("chdir"); return 1; }
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);
    if (posix_spawn(&child, argv[0], NULL, NULL, argv, environ) != 0) { perror("posix_spawn"); return 1; }
    int status;
    while (waitpid(child, &status, 0) < 0) {}
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
