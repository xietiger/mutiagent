#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <dirent.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void trim(char *text) {
    size_t length = strlen(text);
    while (length && (text[length - 1] == '\n' || text[length - 1] == '\r' || text[length - 1] == ' ' || text[length - 1] == '\t')) {
        text[--length] = '\0';
    }
}

static int read_text(const char *path, char *dest, size_t size) {
    FILE *file = fopen(path, "r");
    if (!file || !fgets(dest, (int)size, file)) {
        if (file) fclose(file);
        return -1;
    }
    fclose(file);
    trim(dest);
    return dest[0] ? 0 : -1;
}

static void alert(const char *message) {
    char command[1200];
    snprintf(command, sizeof command,
             "osascript -e 'display dialog \"%s\" buttons {\"好\"} default button 1 with title \"Relay\"' >/dev/null 2>&1",
             message);
    system(command);
}

static int has_marker(const char *project) {
    char marker[PATH_MAX];
    snprintf(marker, sizeof marker, "%s/app/__main__.py", project);
    return access(marker, R_OK) == 0;
}

static int find_site_packages(const char *project, char *dest, size_t size) {
    char lib[PATH_MAX];
    snprintf(lib, sizeof lib, "%s/.venv/lib", project);
    DIR *dir = opendir(lib);
    if (!dir) return -1;
    struct dirent *entry;
    while ((entry = readdir(dir)) != NULL) {
        if (strncmp(entry->d_name, "python", 6) != 0) continue;
        snprintf(dest, size, "%s/%s/site-packages", lib, entry->d_name);
        if (access(dest, R_OK) == 0) {
            closedir(dir);
            return 0;
        }
    }
    closedir(dir);
    return -1;
}

int main(void) {
    char executable[PATH_MAX];
    uint32_t executable_size = sizeof executable;
    if (_NSGetExecutablePath(executable, &executable_size) != 0) return 1;
    char resolved[PATH_MAX];
    if (!realpath(executable, resolved)) return 1;
    char contents_macos[PATH_MAX];
    snprintf(contents_macos, sizeof contents_macos, "%s", resolved);
    char *slash = strrchr(contents_macos, '/');
    if (!slash) return 1;
    *slash = '\0';

    char project[PATH_MAX] = {0};
    char stored_file[PATH_MAX];
    char stored[PATH_MAX];
    snprintf(stored_file, sizeof stored_file, "%s/../Resources/project-root", contents_macos);
    if (read_text(stored_file, stored, sizeof stored) == 0 && has_marker(stored)) {
        snprintf(project, sizeof project, "%s", stored);
    }
    if (!project[0]) {
        char relative[PATH_MAX];
        snprintf(relative, sizeof relative, "%s/../../..", contents_macos);
        if (!realpath(relative, project) || !has_marker(project)) project[0] = '\0';
    }
    if (!project[0]) {
        alert("找不到 Relay 的项目目录。");
        return 1;
    }

    char site_packages[PATH_MAX];
    if (find_site_packages(project, site_packages, sizeof site_packages) != 0) {
        alert("还没有安装运行环境。请先在项目目录创建 .venv 并安装 requirements.txt。");
        return 1;
    }

    char data_dir[PATH_MAX];
    snprintf(data_dir, sizeof data_dir, "%s/data", project);
    mkdir(data_dir, 0755);
    char log_path[PATH_MAX];
    snprintf(log_path, sizeof log_path, "%s/desktop.log", data_dir);
    freopen(log_path, "a", stdout);
    freopen(log_path, "a", stderr);

    char python_path[PATH_MAX * 2];
    snprintf(python_path, sizeof python_path, "%s:%s", project, site_packages);
    setenv("PYTHONPATH", python_path, 1);
    setenv("PYTHONNOUSERSITE", "1", 1);
    if (chdir(project) != 0) return 1;

    char interpreter[PATH_MAX];
    snprintf(interpreter, sizeof interpreter, "%s/.venv/bin/python", project);

    PyConfig config;
    PyStatus status;
    PyConfig_InitPythonConfig(&config);
    config.parse_argv = 0;
    status = PyConfig_SetBytesString(&config, &config.program_name, "Relay");
    if (PyStatus_Exception(status)) goto fail;
    status = PyConfig_SetBytesString(&config, &config.executable, interpreter);
    if (PyStatus_Exception(status)) goto fail;
    status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) goto fail;
    PyConfig_Clear(&config);

    int result = PyRun_SimpleString(
        "import runpy\n"
        "runpy.run_module('app.desktop', run_name='__main__')\n"
    );
    if (result != 0) {
        alert("Relay 没有启动。可以查看项目里的 data/desktop.log。");
        return 1;
    }
    return 0;

fail:
    PyConfig_Clear(&config);
    alert("Relay 没有启动。可以查看项目里的 data/desktop.log。");
    return 1;
}
