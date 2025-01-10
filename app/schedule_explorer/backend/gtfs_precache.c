#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <unistd.h>
#include <msgpack.h>
#include <sys/stat.h>
#include <libgen.h>
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
    char* start = line;
    char* end;
    int in_quotes = 0;
    
    while (*start && field < max_fields) {
        // Skip leading whitespace
        while (*start == ' ' || *start == '\t') start++;
        
        // Handle quoted fields
        if (*start == '"') {
            in_quotes = 1;
            start++;  // Skip opening quote
            end = start;
            
            // Find closing quote
            while (*end) {
                if (*end == '"') {
                    if (*(end + 1) == '"') {  // Double quote inside field
                        end += 2;
                    } else {  // End of quoted field
                        break;
                    }
                } else {
                    end++;
                }
            }
            
            // Store field
            fields[field++] = start;
            
            if (*end == '"') {
                *end = '\0';  // Terminate field at closing quote
                start = end + 1;  // Move past closing quote
            } else {
                start = end;  // No closing quote found
            }
            
            // Skip to next delimiter or end
            while (*start && *start != ',') start++;
            if (*start == ',') start++;
            
        } else {
            // Unquoted field
            fields[field++] = start;
            
            // Find next delimiter or end
            end = start;
            while (*end && *end != ',' && *end != '\n' && *end != '\r') end++;
            
            if (*end) {
                *end = '\0';  // Terminate field
                start = end + 1;  // Move to next field
            } else {
                start = end;  // End of line
            }
        }
    }
    
    return field;
}

// Process a single line of the CSV file
int process_line(char* line, msgpack_packer* pk) {
    char* fields[10];  // More than enough for our needs
    int num_fields = parse_csv_line(line, fields, 10);
    
    if (num_fields < 5) {  // We need at least 5 fields
        fprintf(stderr, "Error: Not enough fields in line: %s\n", line);
        fflush(stderr);
        return -1;
    }
    
    // Convert stop_sequence to integer first to validate it
    char* endptr;
    long seq = strtol(fields[4], &endptr, 10);
    if (*endptr != '\0' || seq < 0 || seq > INT_MAX) {
        fprintf(stderr, "Invalid stop_sequence: %s\n", fields[4]);
        fflush(stderr);
        return -1;
    }
    
    // Pack stop time as a dictionary
    if (msgpack_pack_map(pk, 5) != 0) {
        fprintf(stderr, "Error: Could not pack map header\n");
        fflush(stderr);
        return -1;
    }
    
    // Pack trip_id
    if (msgpack_pack_str(pk, 7) != 0 ||
        msgpack_pack_str_body(pk, "trip_id", 7) != 0 ||
        msgpack_pack_str(pk, strlen(fields[0])) != 0 ||
        msgpack_pack_str_body(pk, fields[0], strlen(fields[0])) != 0) {
        fprintf(stderr, "Error: Could not pack trip_id\n");
        fflush(stderr);
        return -1;
    }
    
    // Pack arrival_time
    if (msgpack_pack_str(pk, 12) != 0 ||
        msgpack_pack_str_body(pk, "arrival_time", 12) != 0 ||
        msgpack_pack_str(pk, strlen(fields[1])) != 0 ||
        msgpack_pack_str_body(pk, fields[1], strlen(fields[1])) != 0) {
        fprintf(stderr, "Error: Could not pack arrival_time\n");
        fflush(stderr);
        return -1;
    }
    
    // Pack departure_time
    if (msgpack_pack_str(pk, 14) != 0 ||
        msgpack_pack_str_body(pk, "departure_time", 14) != 0 ||
        msgpack_pack_str(pk, strlen(fields[2])) != 0 ||
        msgpack_pack_str_body(pk, fields[2], strlen(fields[2])) != 0) {
        fprintf(stderr, "Error: Could not pack departure_time\n");
        fflush(stderr);
        return -1;
    }
    
    // Pack stop_id
    if (msgpack_pack_str(pk, 7) != 0 ||
        msgpack_pack_str_body(pk, "stop_id", 7) != 0 ||
        msgpack_pack_str(pk, strlen(fields[3])) != 0 ||
        msgpack_pack_str_body(pk, fields[3], strlen(fields[3])) != 0) {
        fprintf(stderr, "Error: Could not pack stop_id\n");
        fflush(stderr);
        return -1;
    }
    
    // Pack stop_sequence
    if (msgpack_pack_str(pk, 13) != 0 ||
        msgpack_pack_str_body(pk, "stop_sequence", 13) != 0 ||
        msgpack_pack_int32(pk, (int32_t)seq) != 0) {
        fprintf(stderr, "Error: Could not pack stop_sequence\n");
        fflush(stderr);
        return -1;
    }
    
    return 0;
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

// Get the version string from the header file
const char* get_version() {
    static char version[256] = {0};
    if (version[0] != '\0') {
        return version;
    }

    // Get the path to the executable
    char exe_path[PATH_MAX];
    ssize_t len = readlink("/proc/self/exe", exe_path, sizeof(exe_path)-1);
    if (len != -1) {
        exe_path[len] = '\0';
        char* dir = dirname(exe_path);
        char header_path[PATH_MAX];
        snprintf(header_path, sizeof(header_path), "%s/gtfs_precache_version.h", dir);
        
        FILE* fp = fopen(header_path, "r");
        if (fp) {
            char line[256];
            while (fgets(line, sizeof(line), fp)) {
                if (strstr(line, "GTFS_PRECACHE_VERSION_STRING")) {
                    char* start = strchr(line, '"');
                    if (start) {
                        start++;
                        char* end = strchr(start, '"');
                        if (end) {
                            size_t ver_len = end - start;
                            strncpy(version, start, ver_len);
                            version[ver_len] = '\0';
                            fclose(fp);
                            return version;
                        }
                    }
                }
            }
            fclose(fp);
        } else {
            fprintf(stderr, "Warning: Could not open version header file: %s\n", header_path);
        }
    }

    // Fallback version if we can't read the file
    strcpy(version, "1.0.0");
    return version;
}

// Function to check if we need to rebuild
int check_rebuild(const char* executable_path) {
    const char* current_version = get_version();
    if (strcmp(current_version, GTFS_PRECACHE_VERSION_STRING) != 0) {
        printf("Version mismatch: binary=%s, header=%s\n", 
               GTFS_PRECACHE_VERSION_STRING, current_version);
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
    if (!buffer) {
        fprintf(stderr, "Error: Could not create msgpack buffer\n");
        fflush(stderr);
        fclose(fp);
        return 1;
    }
    printf("Created msgpack buffer\n");
    fflush(stdout);

    msgpack_packer* pk = msgpack_packer_new(buffer, msgpack_sbuffer_write);
    if (!pk) {
        fprintf(stderr, "Error: Could not create msgpack packer\n");
        fflush(stderr);
        msgpack_sbuffer_free(buffer);
        fclose(fp);
        return 1;
    }
    printf("Created msgpack packer\n");
    fflush(stdout);

    // Start root map
    if (msgpack_pack_map(pk, 1) != 0) {
        fprintf(stderr, "Error: Could not pack root map\n");
        fflush(stderr);
        goto cleanup;
    }
    printf("Packed root map\n");
    fflush(stdout);

    // Pack "stop_times" key
    if (msgpack_pack_str(pk, 10) != 0 || 
        msgpack_pack_str_body(pk, "stop_times", 10) != 0) {
        fprintf(stderr, "Error: Could not pack stop_times key\n");
        fflush(stderr);
        goto cleanup;
    }
    printf("Packed stop_times key\n");
    fflush(stdout);

    // Start array with known size (total_lines - 1)
    if (msgpack_pack_array(pk, total_lines) != 0) {
        fprintf(stderr, "Error: Could not pack array header\n");
        fflush(stderr);
        goto cleanup;
    }
    printf("Packed array header with size %zu\n", total_lines);
    fflush(stdout);

    size_t processed = 0;
    size_t successful = 0;
    time_t start_time = time(NULL);
    time_t last_progress = start_time;

    // Process each line
    while (fgets(line, sizeof(line), fp)) {
        // Process the line
        if (process_line(line, pk) == 0) {
            successful++;
        }
        processed++;

        // Update progress
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

            printf("Progress: %.1f%% (%zu/%zu) | Success: %zu | Speed: %.0f rows/s | Memory: %.1f MB | ETA: %.0fs | Buffer size: %zu bytes\n",
                   progress, processed, total_lines, successful, speed, memory_mb, eta, buffer->size);
            fflush(stdout);
            last_progress = current_time;
        }
    }

    printf("Processing complete. Final buffer size: %zu bytes\n", buffer->size);
    fflush(stdout);

    // Write to output file
    FILE* out = fopen(output_file, "wb");
    if (!out) {
        fprintf(stderr, "Error: Could not open output file %s\n", output_file);
        fflush(stderr);
        goto cleanup;
    }

    // Write the entire buffer at once
    size_t written = fwrite(buffer->data, 1, buffer->size, out);
    if (written != buffer->size) {
        fprintf(stderr, "Error: Could not write complete buffer. Written %zu of %zu bytes\n", 
                written, buffer->size);
        fflush(stderr);
        fclose(out);
        goto cleanup;
    }

    // Ensure all data is written and close the file
    fflush(out);
    fclose(out);

    // Cleanup msgpack resources
    msgpack_packer_free(pk);
    msgpack_sbuffer_free(buffer);
    fclose(fp);

    printf("Successfully wrote %zu bytes to output file\n", written);
    printf("Processing complete. Processed %zu rows, %zu successful.\n", processed, successful);
    fflush(stdout);
    return 0;

cleanup:
    if (pk) msgpack_packer_free(pk);
    if (buffer) msgpack_sbuffer_free(buffer);
    if (fp) fclose(fp);
    return 1;
}

// Function declarations
int process_line(char* line, msgpack_packer* pk);
int process_stop_times(const char* input_file, const char* output_file);
int check_rebuild(const char* executable_path);

int main(int argc, char* argv[]) {
    // Get version
    const char* version = get_version();
    
    // Check for version flag
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        printf("GTFS Precache Tool v%s\n", version);
        return 0;  // Success exit code for version
    }
    
    // Print version and check arguments
    printf("GTFS Precache Tool v%s\n", version);
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <input_file> <output_file> [cpu_limit]\n", argv[0]);
        return 1;
    }
    
    const char* input_file = argv[1];
    const char* output_file = argv[2];
    int cpu_limit = DEFAULT_CPU_LIMIT;
    
    if (argc > 3) {
        cpu_limit = atoi(argv[3]);
        if (cpu_limit < 1 || cpu_limit > 100) {
            fprintf(stderr, "CPU limit must be between 1 and 100\n");
            return 1;
        }
    }
    
    printf("Processing %s -> %s (CPU limit: %d%%)\n", input_file, output_file, cpu_limit);
    
    return process_stop_times(input_file, output_file);
} 