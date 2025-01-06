#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <msgpack.h>

#define MAX_LINE_LENGTH 1024
#define BATCH_SIZE 500

// Structure to hold a stop time entry
typedef struct {
    char trip_id[64];
    char stop_id[64];
    char arrival_time[16];
    char departure_time[16];
    int stop_sequence;
} StopTime;

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

int main(int argc, char* argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Usage: %s <input_file> <output_file>\n", argv[0]);
        return 1;
    }
    
    char* input_file = argv[1];
    char* output_file = argv[2];
    
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
    long total_rows = 0;
    while (fgets(line, sizeof(line), fp)) {
        total_rows++;
    }
    printf("Total rows to process: %ld\n", total_rows);
    rewind(fp);
    fgets(line, sizeof(line), fp);  // Skip header again
    
    // Start packing data
    msgpack_pack_map(pk, 1);  // Root map with 1 key
    msgpack_pack_str(pk, 11);  // Key length
    msgpack_pack_str_body(pk, "stop_times", 11);
    msgpack_pack_array(pk, total_rows);  // Array of stop times
    
    // Process rows
    long processed_rows = 0;
    StopTime stop_time;
    time_t last_progress = time(NULL);
    
    while (fgets(line, sizeof(line), fp)) {
        // Parse line
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
        
        processed_rows++;
        
        // Show progress every second
        time_t now = time(NULL);
        if (now > last_progress) {
            printf("Progress: %.1f%% (%ld/%ld)\n", 
                   (float)processed_rows / total_rows * 100,
                   processed_rows, total_rows);
            last_progress = now;
            
            // Sleep briefly to prevent overload
            usleep(10000);  // 10ms
        }
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
    
    printf("Successfully processed %ld rows\n", processed_rows);
    return 0;
} 