#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <unistd.h>
#include <msgpack.h>
#include <sys/stat.h>
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
#define BATCH_SIZE 10000  // Process 10k rows at a time
#define PROGRESS_INTERVAL 1000  // Show progress every 1k rows
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

// Function declarations
int process_line(char* line, msgpack_packer* pk);
int process_stop_times(const char* input_file, const char* output_file);
int check_rebuild(const char* executable_path);

// Parse a CSV line into fields
int parse_csv_line(char* line, char** fields, int max_fields) {
    int field = 0;
    char* token = strtok(line, ",");
    while (token && field < max_fields) {
        // Remove quotes if present
        if (token[0] == '"') {
            token++;
            size_t len = strlen(token);
            if (len > 0 && token[len-1] == '"') {
                token[len-1] = '\0';
            }
        }
        fields[field++] = token;
        token = strtok(NULL, ",");
    }
    return field;
}

// Process a single line of the CSV file
int process_line(char* line, msgpack_packer* pk) {
    char* fields[10];  // More than enough for our needs
    int num_fields = parse_csv_line(line, fields, 10);
    
    if (num_fields < 5) {  // We need at least 5 fields
        return 0;
    }
    
    // Pack stop time as a dictionary
    msgpack_pack_map(pk, 5);
    
    // Pack trip_id
    msgpack_pack_str(pk, 7);
    msgpack_pack_str_body(pk, "trip_id", 7);
    msgpack_pack_str(pk, strlen(fields[0]));
    msgpack_pack_str_body(pk, fields[0], strlen(fields[0]));
    
    // Pack stop_id
    msgpack_pack_str(pk, 7);
    msgpack_pack_str_body(pk, "stop_id", 7);
    msgpack_pack_str(pk, strlen(fields[3]));
    msgpack_pack_str_body(pk, fields[3], strlen(fields[3]));
    
    // Pack arrival_time
    msgpack_pack_str(pk, 12);
    msgpack_pack_str_body(pk, "arrival_time", 12);
    msgpack_pack_str(pk, strlen(fields[1]));
    msgpack_pack_str_body(pk, fields[1], strlen(fields[1]));
    
    // Pack departure_time
    msgpack_pack_str(pk, 14);
    msgpack_pack_str_body(pk, "departure_time", 14);
    msgpack_pack_str(pk, strlen(fields[2]));
    msgpack_pack_str_body(pk, fields[2], strlen(fields[2]));
    
    // Pack stop_sequence
    msgpack_pack_str(pk, 13);
    msgpack_pack_str_body(pk, "stop_sequence", 13);
    msgpack_pack_int32(pk, atoi(fields[4]));
    
    return 1;
}

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
        
        // Print progress
#ifdef _WIN32
        // On Windows, we need to print a newline because \r doesn't work well
        printf("Progress: %.1f%% (%ld/%ld) | Speed: %.0f rows/s | Memory: %s | ETA: %s\n",
#else
        // On Unix-like systems, use \r to overwrite the line
        printf("\rProgress: %.1f%% (%ld/%ld) | Speed: %.0f rows/s | Memory: %s | ETA: %s",
#endif
               (float)progress->processed_rows / progress->total_rows * 100,
               progress->processed_rows, progress->total_rows,
               progress->rows_per_second,
               memory_str,
               eta_str);
        
        // Always flush stdout to ensure progress is displayed
        fflush(stdout);
        
        // Update last progress time
        progress->last_progress = now;
    }
}

// Function to limit CPU usage
void limit_cpu(int cpu_limit) {
    static double last_check = 0;
    static double last_cpu_time = 0;
    static int debug_counter = 0;
    
    double now = get_timestamp();
    if (now - last_check < 0.1) return;  // Check every 100ms
    
    double cpu_time = get_cpu_time();
    
    if (last_cpu_time > 0) {
        // Calculate CPU usage percentage
        double time_diff = cpu_time - last_cpu_time;
        double real_diff = now - last_check;
        double cpu_usage = (time_diff / real_diff) * 100;
        
        // Print debug info every 10 seconds
        debug_counter++;
        if (debug_counter >= 100) {  // 100 * 100ms = 10s
            printf("\nCPU usage: %.1f%% (limit: %d%%)\n", cpu_usage, cpu_limit);
            fflush(stdout);
            debug_counter = 0;
        }
        
        // If CPU usage is too high, sleep
        if (cpu_usage > cpu_limit) {
            // Calculate sleep time in microseconds
            // Use a more aggressive sleep time when CPU usage is much higher than the limit
            double overage_factor = cpu_usage / cpu_limit;
            long sleep_time = (long)((time_diff * 100 / cpu_limit - real_diff) * 1000000 * overage_factor);
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
    int found_columns = 0;
    static int debug_counter = 0;
    
    // Initialize stop_time with empty strings
    stop_time->trip_id[0] = '\0';
    stop_time->stop_id[0] = '\0';
    stop_time->arrival_time[0] = '\0';
    stop_time->departure_time[0] = '\0';
    stop_time->stop_sequence = -1;
    
    while ((token = strtok_r(rest, ",", &rest))) {
        // Remove quotes and whitespace
        while (*token == ' ' || *token == '"') token++;
        char* end = token + strlen(token) - 1;
        while (end > token && (*end == ' ' || *end == '"' || *end == '\n' || *end == '\r')) end--;
        *(end + 1) = '\0';
        
        if (column == column_indices[0]) {  // trip_id
            if (strlen(token) >= sizeof(stop_time->trip_id)) {
                fprintf(stderr, "trip_id too long: %s\n", token);
                fflush(stderr);
                return -1;
            }
            strncpy(stop_time->trip_id, token, sizeof(stop_time->trip_id) - 1);
            stop_time->trip_id[sizeof(stop_time->trip_id) - 1] = '\0';
            found_columns++;
        } else if (column == column_indices[1]) {  // stop_id
            if (strlen(token) >= sizeof(stop_time->stop_id)) {
                fprintf(stderr, "stop_id too long: %s\n", token);
                fflush(stderr);
                return -1;
            }
            strncpy(stop_time->stop_id, token, sizeof(stop_time->stop_id) - 1);
            stop_time->stop_id[sizeof(stop_time->stop_id) - 1] = '\0';
            found_columns++;
        } else if (column == column_indices[2]) {  // arrival_time
            if (strlen(token) >= sizeof(stop_time->arrival_time)) {
                fprintf(stderr, "arrival_time too long: %s\n", token);
                fflush(stderr);
                return -1;
            }
            strncpy(stop_time->arrival_time, token, sizeof(stop_time->arrival_time) - 1);
            stop_time->arrival_time[sizeof(stop_time->arrival_time) - 1] = '\0';
            found_columns++;
        } else if (column == column_indices[3]) {  // departure_time
            if (strlen(token) >= sizeof(stop_time->departure_time)) {
                fprintf(stderr, "departure_time too long: %s\n", token);
                fflush(stderr);
                return -1;
            }
            strncpy(stop_time->departure_time, token, sizeof(stop_time->departure_time) - 1);
            stop_time->departure_time[sizeof(stop_time->departure_time) - 1] = '\0';
            found_columns++;
        } else if (column == column_indices[4]) {  // stop_sequence
            char* endptr;
            long seq = strtol(token, &endptr, 10);
            if (*endptr != '\0' || seq < 0 || seq > INT_MAX) {
                fprintf(stderr, "Invalid stop_sequence: %s\n", token);
                fflush(stderr);
                return -1;
            }
            stop_time->stop_sequence = (int)seq;
            found_columns++;
        }
        column++;
    }
    
    // Print debug info every 10000 rows
    debug_counter++;
    if (debug_counter >= 10000) {
        printf("\nParsed row: trip_id=%s, stop_id=%s, arrival=%s, departure=%s, seq=%d\n",
               stop_time->trip_id, stop_time->stop_id,
               stop_time->arrival_time, stop_time->departure_time,
               stop_time->stop_sequence);
        fflush(stdout);
        debug_counter = 0;
    }
    
    // Verify all required columns were found
    if (found_columns != 5) {
        fprintf(stderr, "Missing columns in line: found %d/5\n", found_columns);
        fflush(stderr);
        return -1;
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
    const char* column_names[] = {"trip_id", "stop_id", "arrival_time", "departure_time", "stop_sequence"};
    for (int i = 0; i < 5; i++) {
        if (indices[i] == -1) {
            fprintf(stderr, "Missing required column: %s\n", column_names[i]);
            fflush(stderr);
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
    if (!fp) {
        fprintf(stderr, "Could not open version header file\n");
        fflush(stderr);
        return -1;
    }

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
    fprintf(stderr, "Could not find version string in header file\n");
    fflush(stderr);
    return -1;
}

// Function to check if we need to rebuild
int check_rebuild(const char* executable_path) {
    char header_version[32] = {0};
    if (read_header_version(header_version, sizeof(header_version)) != 0) {
        fprintf(stderr, "Warning: Could not read version from header\n");
        fflush(stderr);
        return 0;  // Continue without rebuild if we can't read the header
    }

    // Compare versions
    if (strcmp(header_version, GTFS_PRECACHE_VERSION_STRING) != 0) {
        printf("Version mismatch: binary=%s, header=%s\n", 
               GTFS_PRECACHE_VERSION_STRING, header_version);
        printf("Rebuilding...\n");
        fflush(stdout);

        // Build command
#ifdef _WIN32
        char cmd[512];
        snprintf(cmd, sizeof(cmd), "cmake --build . && copy /Y gtfs_precache.exe \"%s\"", executable_path);
#else
        char cmd[512];
        snprintf(cmd, sizeof(cmd), "make && cp -f gtfs_precache \"%s\"", executable_path);
#endif

        // Execute build command
        int result = system(cmd);
        if (result != 0) {
            fprintf(stderr, "Error: Rebuild failed\n");
            fflush(stderr);
            return -1;
        }

        printf("Rebuild successful, restarting...\n\n");
        fflush(stdout);

        // Re-execute ourselves
        char* argv[] = {(char*)executable_path, NULL};
        execv(executable_path, argv);
        
        // If we get here, execv failed
        fprintf(stderr, "Error: Failed to restart after rebuild\n");
        fflush(stderr);
        return -1;
    }

    return 0;  // No rebuild needed
}

int process_stop_times(const char* input_file, const char* output_file) {
    FILE* fp = fopen(input_file, "r");
    if (!fp) {
        fprintf(stderr, "Error: Could not open input file %s\n", input_file);
        fflush(stderr);
        return 1;
    }

    // First count total lines
    printf("Counting total lines...\n");
    fflush(stdout);
    size_t total_lines = 0;
    char line[1024];
    while (fgets(line, sizeof(line), fp)) {
        total_lines++;
    }
    total_lines--; // Subtract header line
    printf("Total lines to process: %zu\n", total_lines);
    fflush(stdout);

    // Reset file pointer
    rewind(fp);

    // Skip header line
    if (!fgets(line, sizeof(line), fp)) {
        fprintf(stderr, "Error: Could not read header line\n");
        fflush(stderr);
        fclose(fp);
        return 1;
    }

    // Initialize msgpack buffer
    msgpack_sbuffer* buffer = msgpack_sbuffer_new();
    msgpack_packer* pk = msgpack_packer_new(buffer, msgpack_sbuffer_write);

    // Start root map
    msgpack_pack_map(pk, 1);
    msgpack_pack_str(pk, 10);
    msgpack_pack_str_body(pk, "stop_times", 10);

    // Start array with known size (total_lines - 1)
    msgpack_pack_array(pk, total_lines - 1);

    size_t processed = 0;
    time_t start_time = time(NULL);
    time_t last_progress = start_time;

    // Process in batches
    char** batch = malloc(BATCH_SIZE * sizeof(char*));
    size_t batch_size = 0;

    while (fgets(line, sizeof(line), fp)) {
        // Add line to current batch
        batch[batch_size] = strdup(line);
        batch_size++;

        // Process batch if it's full or if we're at the end
        if (batch_size == BATCH_SIZE || feof(fp)) {
            // Process each line in the batch
            for (size_t i = 0; i < batch_size; i++) {
                char* line = batch[i];
                // Process the line
                process_line(line, pk);
                free(line);  // Free the line after processing
            }

            // Reset batch
            batch_size = 0;

            // Update progress
            processed += batch_size;
            time_t current_time = time(NULL);
            if (current_time - last_progress >= 1) {
                double progress = (double)processed / total_lines * 100.0;
                double elapsed = difftime(current_time, start_time);
                double speed = processed / (elapsed > 0 ? elapsed : 1);
                double eta = (total_lines - processed) / (speed > 0 ? speed : 1);
                
                // Get current memory usage
                struct rusage r_usage;
                getrusage(RUSAGE_SELF, &r_usage);
                double memory_mb = r_usage.ru_maxrss / 1024.0;

                printf("Progress: %.1f%% (%zu/%zu) | Speed: %.0f rows/s | Memory: %.1f MB | ETA: %.0fs\n",
                       progress, processed, total_lines, speed, memory_mb, eta);
                fflush(stdout);
                last_progress = current_time;
            }
        }
    }

    // Free batch array
    free(batch);

    // Write to output file
    FILE* out = fopen(output_file, "wb");
    if (!out) {
        fprintf(stderr, "Error: Could not open output file %s\n", output_file);
        fflush(stderr);
        return 1;
    }

    fwrite(buffer->data, buffer->size, 1, out);
    fclose(out);

    // Cleanup
    msgpack_sbuffer_free(buffer);
    msgpack_packer_free(pk);
    fclose(fp);

    printf("Processing complete. Processed %zu rows.\n", processed);
    fflush(stdout);
    return 0;
}

// Function declarations
int process_line(char* line, msgpack_packer* pk);
int process_stop_times(const char* input_file, const char* output_file);
int check_rebuild(const char* executable_path);

int main(int argc, char* argv[]) {
    // Print version if requested
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        printf("GTFS Precache Tool v%s\n", GTFS_PRECACHE_VERSION_STRING);
        fflush(stdout);
        return 0;
    }

    // Check for self-update
    if (check_rebuild(argv[0]) != 0) {
        fprintf(stderr, "Failed to check for updates\n");
        fflush(stderr);
        return 1;
    }

    // Check arguments
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <input_file> <output_file>\n", argv[0]);
        fflush(stderr);
        return 1;
    }

    printf("GTFS Precache Tool v%s starting...\n", GTFS_PRECACHE_VERSION_STRING);
    fflush(stdout);

    return process_stop_times(argv[1], argv[2]);
} 