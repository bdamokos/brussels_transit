#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <msgpack.h>
#include "gtfs_precache_version.h"

#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#define PATH_MAX MAX_PATH
#else
#include <unistd.h>
#include <sys/time.h>
#include <sys/resource.h>
#include <limits.h>
#ifdef __linux__
#include <sys/sysinfo.h>
#endif
#endif

#define MAX_LINE_LENGTH 1024
#define BATCH_SIZE 500
#define DEFAULT_CPU_LIMIT 50  // Default CPU limit in percentage

// Structure to hold a stop time entry
typedef struct {
    char trip_id[64];
    char stop_id[64];
    char arrival_time[16];
    char departure_time[16];
    int stop_sequence;
} StopTime;

// Structure to hold progress statistics
typedef struct {
    long total_rows;
    long processed_rows;
    double start_time;
    double last_progress;
    double rows_per_second;
    long memory_usage;
} Progress;

// Cross-platform function to get current timestamp in seconds
double get_timestamp() {
#ifdef _WIN32
    LARGE_INTEGER frequency;
    LARGE_INTEGER counter;
    QueryPerformanceFrequency(&frequency);
    QueryPerformanceCounter(&counter);
    return (double)counter.QuadPart / frequency.QuadPart;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
#endif
}

// Cross-platform function to get current memory usage in bytes
long get_memory_usage() {
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS pmc;
    if (GetProcessMemoryInfo(GetCurrentProcess(), &pmc, sizeof(pmc))) {
        return pmc.WorkingSetSize;
    }
    return 0;
#else
    struct rusage usage;
    getrusage(RUSAGE_SELF, &usage);
    return usage.ru_maxrss * 1024;  // Convert KB to bytes
#endif
}

// Cross-platform function to sleep for microseconds
void platform_sleep(long microseconds) {
#ifdef _WIN32
    Sleep(microseconds / 1000);  // Windows Sleep takes milliseconds
#else
    struct timespec ts = {
        .tv_sec = microseconds / 1000000,
        .tv_nsec = (microseconds % 1000000) * 1000
    };
    nanosleep(&ts, NULL);
#endif
}

// Cross-platform function to get CPU time
double get_cpu_time() {
#ifdef _WIN32
    FILETIME create_time, exit_time, kernel_time, user_time;
    if (GetProcessTimes(GetCurrentProcess(), &create_time, &exit_time, &kernel_time, &user_time)) {
        ULARGE_INTEGER ui;
        ui.LowPart = user_time.dwLowDateTime;
        ui.HighPart = user_time.dwHighDateTime;
        return (double)ui.QuadPart / 10000000.0;  // Convert to seconds
    }
    return 0;
#else
    struct rusage usage;
    getrusage(RUSAGE_SELF, &usage);
    return usage.ru_utime.tv_sec + usage.ru_utime.tv_usec / 1e6;
#endif
}

// Function to format size in human readable format
void format_size(long bytes, char* buffer) {
    const char* units[] = {"B", "KB", "MB", "GB"};
    int unit = 0;
    double size = bytes;
    while (size >= 1024 && unit < 3) {
        size /= 1024;
        unit++;
    }
    sprintf(buffer, "%.1f %s", size, units[unit]);
}

// Function to format time in human readable format
void format_time(int seconds, char* buffer) {
    int hours = seconds / 3600;
    int minutes = (seconds % 3600) / 60;
    seconds = seconds % 60;
    if (hours > 0) {
        sprintf(buffer, "%dh %dm %ds", hours, minutes, seconds);
    } else if (minutes > 0) {
        sprintf(buffer, "%dm %ds", minutes, seconds);
    } else {
        sprintf(buffer, "%ds", seconds);
    }
}

// Function to update and display progress
void update_progress(Progress* progress) {
    double now = get_timestamp();
    if (now - progress->last_progress >= 1.0) {  // Update every second
        // Calculate statistics
        double elapsed = now - progress->start_time;
        progress->rows_per_second = progress->processed_rows / elapsed;
        int eta = (progress->total_rows - progress->processed_rows) / progress->rows_per_second;
        progress->memory_usage = get_memory_usage();
        
        // Format memory usage
        char memory_str[32];
        format_size(progress->memory_usage, memory_str);
        
        // Format ETA
        char eta_str[32];
        format_time(eta, eta_str);
        
        // Print progress (use \r only on Unix-like systems)
#ifdef _WIN32
        printf("Progress: %.1f%% (%ld/%ld) | Speed: %.0f rows/s | Memory: %s | ETA: %s\n",
#else
        printf("\rProgress: %.1f%% (%ld/%ld) | Speed: %.0f rows/s | Memory: %s | ETA: %s",
#endif
               (float)progress->processed_rows / progress->total_rows * 100,
               progress->processed_rows, progress->total_rows,
               progress->rows_per_second,
               memory_str,
               eta_str);
        fflush(stdout);
        
        progress->last_progress = now;
    }
}

// Function to limit CPU usage
void limit_cpu(int cpu_limit) {
    static double last_check = 0;
    static double last_cpu_time = 0;
    
    double now = get_timestamp();
    if (now - last_check < 0.1) return;  // Check every 100ms
    
    double cpu_time = get_cpu_time();
    
    if (last_cpu_time > 0) {
        // Calculate CPU usage percentage
        double time_diff = cpu_time - last_cpu_time;
        double real_diff = now - last_check;
        double cpu_usage = (time_diff / real_diff) * 100;
        
        // If CPU usage is too high, sleep
        if (cpu_usage > cpu_limit) {
            long sleep_time = (long)((time_diff * 100 / cpu_limit - real_diff) * 1000000);  // microseconds
            if (sleep_time > 0) {
                platform_sleep(sleep_time);
            }
        }
    }
    
    last_check = now;
    last_cpu_time = cpu_time;
}

// Function to parse a CSV line into a StopTime struct
int parse_line(char* line, StopTime* stop_time, int* column_indices) {
    char* token;
    char* rest = line;
    int column = 0;
    
    while ((token = strtok_r(rest, ",", &rest))) {
        if (column == column_indices[0]) {  // trip_id
            strncpy(stop_time->trip_id, token, sizeof(stop_time->trip_id) - 1);
            stop_time->trip_id[sizeof(stop_time->trip_id) - 1] = '\0';
        } else if (column == column_indices[1]) {  // stop_id
            strncpy(stop_time->stop_id, token, sizeof(stop_time->stop_id) - 1);
            stop_time->stop_id[sizeof(stop_time->stop_id) - 1] = '\0';
        } else if (column == column_indices[2]) {  // arrival_time
            strncpy(stop_time->arrival_time, token, sizeof(stop_time->arrival_time) - 1);
            stop_time->arrival_time[sizeof(stop_time->arrival_time) - 1] = '\0';
        } else if (column == column_indices[3]) {  // departure_time
            strncpy(stop_time->departure_time, token, sizeof(stop_time->departure_time) - 1);
            stop_time->departure_time[sizeof(stop_time->departure_time) - 1] = '\0';
        } else if (column == column_indices[4]) {  // stop_sequence
            stop_time->stop_sequence = atoi(token);
        }
        column++;
    }
    
    return 0;
}

// Function to get column indices from header
int get_column_indices(char* header, int* indices) {
    char* token;
    char* rest = header;
    int column = 0;
    
    // Initialize indices to -1
    for (int i = 0; i < 5; i++) {
        indices[i] = -1;
    }
    
    while ((token = strtok_r(rest, ",", &rest))) {
        // Remove quotes and whitespace
        while (*token == ' ' || *token == '"') token++;
        char* end = token + strlen(token) - 1;
        while (end > token && (*end == ' ' || *end == '"' || *end == '\n' || *end == '\r')) end--;
        *(end + 1) = '\0';
        
        if (strcmp(token, "trip_id") == 0) indices[0] = column;
        else if (strcmp(token, "stop_id") == 0) indices[1] = column;
        else if (strcmp(token, "arrival_time") == 0) indices[2] = column;
        else if (strcmp(token, "departure_time") == 0) indices[3] = column;
        else if (strcmp(token, "stop_sequence") == 0) indices[4] = column;
        
        column++;
    }
    
    // Verify all required columns were found
    for (int i = 0; i < 5; i++) {
        if (indices[i] == -1) {
            fprintf(stderr, "Missing required column %d\n", i);
            return -1;
        }
    }
    
    return 0;
}

// Function to get the current executable path
int get_executable_path(char* path, size_t size) {
#ifdef _WIN32
    return GetModuleFileName(NULL, path, size) != 0 ? 0 : -1;
#else
    ssize_t len = readlink("/proc/self/exe", path, size - 1);
    if (len != -1) {
        path[len] = '\0';
        return 0;
    }
    return -1;
#endif
}

// Function to read version from header file
int read_header_version(char* version, size_t size) {
    FILE* fp = fopen("gtfs_precache_version.h", "r");
    if (!fp) return -1;

    char line[256];
    while (fgets(line, sizeof(line), fp)) {
        if (strstr(line, "GTFS_PRECACHE_VERSION_STRING")) {
            char* start = strchr(line, '"');
            if (start) {
                start++;
                char* end = strchr(start, '"');
                if (end) {
                    size_t len = end - start;
                    if (len < size) {
                        strncpy(version, start, len);
                        version[len] = '\0';
                        fclose(fp);
                        return 0;
                    }
                }
            }
        }
    }
    fclose(fp);
    return -1;
}

// Function to check if we need to rebuild
int check_rebuild() {
    char header_version[32] = {0};
    if (read_header_version(header_version, sizeof(header_version)) != 0) {
        fprintf(stderr, "Warning: Could not read version from header\n");
        return 0;  // Continue without rebuild if we can't read the header
    }

    // Compare versions
    if (strcmp(header_version, GTFS_PRECACHE_VERSION_STRING) != 0) {
        printf("Version mismatch: binary=%s, header=%s\n", 
               GTFS_PRECACHE_VERSION_STRING, header_version);
        printf("Rebuilding...\n");

        // Get our own path
        char exe_path[PATH_MAX];
        if (get_executable_path(exe_path, sizeof(exe_path)) != 0) {
            fprintf(stderr, "Error: Could not get executable path\n");
            return -1;
        }

        // Build command
#ifdef _WIN32
        char cmd[512];
        snprintf(cmd, sizeof(cmd), "cmake --build . && copy /Y gtfs_precache.exe \"%s\"", exe_path);
#else
        char cmd[512];
        snprintf(cmd, sizeof(cmd), "make && cp -f gtfs_precache \"%s\"", exe_path);
#endif

        // Execute build command
        int result = system(cmd);
        if (result != 0) {
            fprintf(stderr, "Error: Rebuild failed\n");
            return -1;
        }

        printf("Rebuild successful, restarting...\n\n");

        // Re-execute ourselves
        execv(exe_path, __argv);
        
        // If we get here, execv failed
        fprintf(stderr, "Error: Failed to restart after rebuild\n");
        return -1;
    }

    return 0;  // No rebuild needed
}

int main(int argc, char* argv[]) {
    // Check for rebuild first
    if (check_rebuild() != 0) {
        return 1;
    }

    int cpu_limit = DEFAULT_CPU_LIMIT;
    char* input_file = NULL;
    char* output_file = NULL;
    
    // Parse command line arguments
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--cpu-limit") == 0 && i + 1 < argc) {
            cpu_limit = atoi(argv[i + 1]);
            i++;
        } else if (strcmp(argv[i], "--version") == 0) {
            printf("GTFS Precache Tool v%s\n", GTFS_PRECACHE_VERSION_STRING);
            return 0;
        } else if (!input_file) {
            input_file = argv[i];
        } else if (!output_file) {
            output_file = argv[i];
        }
    }
    
    if (!input_file || !output_file) {
        fprintf(stderr, "GTFS Precache Tool v%s\n", GTFS_PRECACHE_VERSION_STRING);
        fprintf(stderr, "Usage: %s [--cpu-limit PERCENT] [--version] <input_file> <output_file>\n", argv[0]);
        return 1;
    }
    
    printf("GTFS Precache Tool v%s\n", GTFS_PRECACHE_VERSION_STRING);
    printf("Starting with CPU limit: %d%%\n", cpu_limit);
    
    // Initialize progress tracking
    Progress progress = {0};
    progress.start_time = get_timestamp();
    progress.last_progress = progress.start_time;
    
    // Open input file
    FILE* fp = fopen(input_file, "r");
    if (!fp) {
        fprintf(stderr, "Could not open input file: %s\n", input_file);
        return 1;
    }
    
    // Initialize msgpack buffer
    msgpack_sbuffer* buffer = msgpack_sbuffer_new();
    msgpack_packer* pk = msgpack_packer_new(buffer, msgpack_sbuffer_write);
    
    // Read header and get column indices
    char line[MAX_LINE_LENGTH];
    int column_indices[5];
    if (!fgets(line, sizeof(line), fp)) {
        fprintf(stderr, "Could not read header\n");
        return 1;
    }
    if (get_column_indices(line, column_indices) != 0) {
        fprintf(stderr, "Invalid header format\n");
        return 1;
    }
    
    // Count total rows
    progress.total_rows = 0;
    while (fgets(line, sizeof(line), fp)) {
        progress.total_rows++;
    }
    printf("Total rows to process: %ld\n", progress.total_rows);
    rewind(fp);
    fgets(line, sizeof(line), fp);  // Skip header again
    
    // Start packing data
    msgpack_pack_map(pk, 1);  // Root map with 1 key
    msgpack_pack_str(pk, 11);  // Key length
    msgpack_pack_str_body(pk, "stop_times", 11);
    msgpack_pack_array(pk, progress.total_rows);  // Array of stop times
    
    // Process rows
    while (fgets(line, sizeof(line), fp)) {
        // Limit CPU usage
        limit_cpu(cpu_limit);
        
        // Parse line
        StopTime stop_time;
        if (parse_line(line, &stop_time, column_indices) != 0) {
            fprintf(stderr, "Error parsing line: %s\n", line);
            continue;
        }
        
        // Pack stop time as a map
        msgpack_pack_map(pk, 5);
        
        // Pack trip_id
        msgpack_pack_str(pk, 7);
        msgpack_pack_str_body(pk, "trip_id", 7);
        msgpack_pack_str(pk, strlen(stop_time.trip_id));
        msgpack_pack_str_body(pk, stop_time.trip_id, strlen(stop_time.trip_id));
        
        // Pack stop_id
        msgpack_pack_str(pk, 7);
        msgpack_pack_str_body(pk, "stop_id", 7);
        msgpack_pack_str(pk, strlen(stop_time.stop_id));
        msgpack_pack_str_body(pk, stop_time.stop_id, strlen(stop_time.stop_id));
        
        // Pack arrival_time
        msgpack_pack_str(pk, 12);
        msgpack_pack_str_body(pk, "arrival_time", 12);
        msgpack_pack_str(pk, strlen(stop_time.arrival_time));
        msgpack_pack_str_body(pk, stop_time.arrival_time, strlen(stop_time.arrival_time));
        
        // Pack departure_time
        msgpack_pack_str(pk, 14);
        msgpack_pack_str_body(pk, "departure_time", 14);
        msgpack_pack_str(pk, strlen(stop_time.departure_time));
        msgpack_pack_str_body(pk, stop_time.departure_time, strlen(stop_time.departure_time));
        
        // Pack stop_sequence
        msgpack_pack_str(pk, 13);
        msgpack_pack_str_body(pk, "stop_sequence", 13);
        msgpack_pack_int(pk, stop_time.stop_sequence);
        
        progress.processed_rows++;
        update_progress(&progress);
    }
    
    // Write buffer to output file
    FILE* out_fp = fopen(output_file, "wb");
    if (!out_fp) {
        fprintf(stderr, "Could not open output file: %s\n", output_file);
        return 1;
    }
    fwrite(buffer->data, buffer->size, 1, out_fp);
    fclose(out_fp);
    
    // Clean up
    msgpack_sbuffer_free(buffer);
    msgpack_packer_free(pk);
    fclose(fp);
    
    printf("\nCompleted processing %ld rows\n", progress.processed_rows);
    return 0;
} 